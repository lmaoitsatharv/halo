"""Recording isolation, durable choices and non-destructive correction errors."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, QEvent, Qt
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow
from halo.lyric_store import LyricStore, MAX_RECORD_BYTES, recording_key
from halo.models import Track, Lyrics, LyricLine, LyricWord


def recording(**changes):
    return replace(Track("Song", "Artist", "Album", 200., connected=True), **changes)


def timed():
    return Lyrics([LyricLine(1., "One two", (LyricWord("One ", 1., 1.4), LyricWord("two", 1.5, 2.))),
                   LyricLine(3., "Three")], "Chosen timed lyrics", source_id="123", selected_record={"id": "123", "album": "Album"})


class LyricStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.store = LyricStore(Path(self.temp.name) / "lyrics")

    def test_round_trip_retains_word_boundaries_source_and_offset(self):
        self.store.save(recording(), 700, timed(), "imported")
        result = LyricStore(self.store.directory).load(recording())
        self.assertEqual(result["offset"], 700)
        self.assertEqual(result["kind"], "imported")
        self.assertEqual(result["lyrics"], timed())

    def test_round_trip_preserves_source_intervals_without_parent_containment(self):
        lyrics = Lyrics([LyricLine(2., "One two", (LyricWord("One ", 1., 2.5),
                                                  LyricWord("two", 2., 4.)), 3.)])
        self.store.save(recording(), 0, lyrics)
        self.assertEqual(self.store.load(recording())["lyrics"], lyrics)

    def test_song_artist_album_and_duration_each_isolate_recordings(self):
        self.store.save(recording(), 600, timed())
        for change in ({"title": "Song Live"}, {"artist": "Other"}, {"album": "Live"}, {"duration": 220.}):
            self.assertEqual(self.store.load(recording(**change)), {})
        self.assertEqual(self.store.load(recording(title=" SONG ", artist="artist"))["offset"], 600)
        self.assertIsNone(recording_key(recording(duration=0)))
        self.assertEqual(self.store.load(recording(duration=0)), {})

    def test_invalid_new_content_never_overwrites_previous_record(self):
        self.store.save(recording(), 300, timed())
        bad = Lyrics([LyricLine(float("nan"), "Bad")])
        with self.assertRaises(ValueError):
            self.store.save(recording(), 400, bad)
        self.assertEqual(self.store.load(recording())["lyrics"], timed())
        self.assertEqual(self.store.load(recording())["offset"], 300)

    def test_atomic_replace_failure_preserves_previous_and_cleans_temporary(self):
        self.store.save(recording(), 300)
        with patch("halo.lyric_store.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.store.save(recording(), 500)
        self.assertEqual(self.store.load(recording())["offset"], 300)
        self.assertEqual(len(list(self.store.directory.iterdir())), 1)

    def test_corrupt_oversized_and_nonfinite_files_are_ignored(self):
        self.store.save(recording(), 300, timed())
        path = self.store._path(recording_key(recording()))
        original = path.read_text(encoding="utf-8")
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.store.load(recording()), {})
        path.write_bytes(b" " * (MAX_RECORD_BYTES + 1))
        self.assertEqual(self.store.load(recording()), {})
        data = json.loads(original)
        data["lyrics"]["lines"][0]["words"][0]["start"] = float("inf")
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.store.load(recording()), {})

    def test_reset_preserves_saved_source_but_empty_corrections_leave_no_file(self):
        self.store.save(recording(), 300, timed())
        self.store.save(recording(), 0, timed())
        self.assertEqual(self.store.load(recording())["lyrics"], timed())
        self.store.clear_lyrics(recording())
        self.assertEqual(self.store.load(recording()), {})
        self.assertEqual(list(self.store.directory.iterdir()), [])


class CorrectionControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for controller in self.controllers:
            controller.close()
            controller.audio.thread.join(1)

    def controller(self, baseline=None):
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        if baseline is not None:
            settings.setValue("offset", baseline)
        c = Controller(settings, offline=True)
        c.timer.stop()
        c.requestLyrics.disconnect(c.lyrics_worker.fetch)
        c.requestChoices.disconnect(c.lyrics_worker.list_choices)
        c.requestLyricSelection.disconnect(c.lyrics_worker.select_candidate)
        self.controllers.append(c)
        return c

    def test_per_song_correction_survives_restart_and_never_leaks_to_other_song(self):
        c = self.controller(250)
        c.accept_track(recording())
        c.adjust_lyrics(700)
        self.assertEqual(c.offset, 950)
        c.accept_track(recording(title="Other"))
        self.assertEqual((c.song_offset, c.offset), (0, 250))
        c.accept_track(recording())
        self.assertEqual((c.song_offset, c.offset), (700, 950))
        new = self.controller()
        new.accept_track(recording())
        self.assertEqual((new.song_offset, new.offset), (700, 950))
        new.set_song_offset(0)
        self.assertEqual(new.offset, 250)
        self.assertEqual(new.settings.value("offset", type=int), 250)

    def test_earlier_later_and_bounds_have_correct_direction(self):
        c = self.controller()
        c.accept_track(recording())
        c.adjust_lyrics(100)
        self.assertEqual(c.offset, 100)
        c.adjust_lyrics(-200)
        self.assertEqual(c.offset, -100)
        c.set_song_offset(999999)
        self.assertEqual(c.song_offset, 10000)
        c.set_song_offset(-999999)
        self.assertEqual(c.song_offset, -10000)

    def test_saved_import_restores_across_tracks_restart_and_retry(self):
        c = self.controller()
        c.accept_track(recording())
        path = Path(self.temp.name) / "example.lrc"
        path.write_text("[00:01]One two\n[00:03]Three", encoding="utf-8")
        c.import_lyrics(path)
        imported = c.lyrics
        c.retry_lyrics()
        self.assertIs(c.lyrics, imported)
        c.accept_track(recording(title="Other"))
        c.accept_track(recording())
        self.assertEqual(c.lyrics, imported)
        restarted = self.controller()
        requests = []
        restarted.requestLyrics.connect(lambda *args: requests.append(args))
        restarted.accept_track(recording())
        self.assertEqual(restarted.lyrics, imported)
        self.assertEqual(restarted.saved_lyric_kind, "imported")
        self.assertEqual(requests, [])

    def test_invalid_import_keeps_lyrics_generation_and_saved_choice(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyric_store.save(c.track, 0, timed(), "selected")
        c.lyrics = timed()
        c.saved_lyric_kind = "selected"
        previous, generation = c.lyrics, c.generation
        path = Path(self.temp.name) / "bad.lrc"
        path.write_text("no timestamps", encoding="utf-8")
        with self.assertRaises(ValueError):
            c.import_lyrics(path)
        self.assertIs(c.lyrics, previous)
        self.assertEqual(c.generation, generation)
        self.assertEqual(c.lyric_store.load(c.track)["lyrics"], previous)

    def test_late_network_result_cannot_replace_import_or_next_song(self):
        c = self.controller()
        c.accept_track(recording())
        old_generation = c.generation
        path = Path(self.temp.name) / "new.lrc"
        path.write_text("[00:01]Imported\n[00:03]More", encoding="utf-8")
        c.import_lyrics(path)
        imported = c.lyrics
        c.accept_lyrics(old_generation, timed())
        self.assertIs(c.lyrics, imported)
        c.accept_track(recording(title="Other"))
        current = c.lyrics
        c.accept_lyric_choices(old_generation, [{"id": "old"}])
        c.accept_lyrics(old_generation, timed())
        self.assertIs(c.lyrics, current)
        self.assertEqual(c.lyric_choices, [])

    def test_explicit_source_selection_is_saved_and_automatic_reset_keeps_offset(self):
        c = self.controller()
        c.accept_track(recording())
        c.adjust_lyrics(400)
        c.find_lyric_choices()
        c.accept_lyric_choices(c.generation, [{"id": "123", "preview": "One two"}])
        c.select_lyric_source("123")
        c.accept_lyrics(c.generation, timed())
        self.assertEqual(c.saved_lyric_kind, "selected")
        restarted = self.controller()
        restarted.accept_track(recording())
        self.assertEqual(restarted.lyrics, timed())
        requests = []
        restarted.requestLyrics.connect(lambda *args: requests.append(args))
        restarted.use_automatic_lyrics()
        self.assertEqual(restarted.saved_lyric_kind, "")
        self.assertEqual(restarted.song_offset, 400)
        self.assertEqual(len(requests), 1)
        self.assertNotIn("lyrics", restarted.lyric_store.load(restarted.track))

    def test_failed_source_selection_and_failed_storage_preserve_current_lyrics(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyrics = timed()
        original = c.lyrics
        c.lyric_choices = [{"id": "123"}]
        c.select_lyric_source("123")
        c.accept_lyrics(c.generation, Lyrics(message="Lookup failed"))
        self.assertIs(c.lyrics, original)
        self.assertEqual(c.lyric_choices_status, "Lookup failed")
        with patch.object(c.lyric_store, "save", side_effect=OSError("disk full")):
            c.adjust_lyrics(100)
        self.assertEqual(c.song_offset, 0)
        self.assertIn("disk full", c.error)

    def test_retry_cancels_pending_selection_and_rejects_its_late_result(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyric_choices = [{"id": "123"}]
        c.select_lyric_source("123")
        selected_generation = c.generation
        c.retry_lyrics()
        self.assertIsNone(c.selection_generation)
        current = c.lyrics
        c.accept_lyrics(selected_generation, timed())
        self.assertIs(c.lyrics, current)

    def test_failed_automatic_reset_is_visible_and_preserves_the_saved_source(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyrics = timed()
        c.saved_lyric_kind = "selected"
        c.lyric_store.save(c.track, 400, c.lyrics)
        notifications = []
        c.settingChanged.connect(lambda: notifications.append(True))
        with patch.object(c.lyric_store, "clear_lyrics", side_effect=OSError("disk read-only")):
            c.use_automatic_lyrics()
        self.assertEqual(c.saved_lyric_kind, "selected")
        self.assertEqual(c.lyrics, timed())
        self.assertIn("read-only", c.lyric_save_error)
        self.assertTrue(notifications)
        self.assertEqual(c.lyric_store.load(c.track)["lyrics"], timed())
        c.use_automatic_lyrics()
        self.assertEqual(c.lyric_save_error, "")
        self.assertEqual(c.saved_lyric_kind, "")

    def test_failed_import_save_keeps_current_source_and_pending_generation(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyric_store.save(c.track, 400, timed(), "selected")
        c.lyrics, c.saved_lyric_kind = timed(), "selected"
        previous, generation = c.lyrics, c.generation
        path = Path(self.temp.name) / "example.elrc"
        path.write_text("[00:01]<00:01>New <00:02>words\n[00:03]More", encoding="utf-8")
        with patch.object(c.lyric_store, "save", side_effect=OSError("read-only")):
            with self.assertRaises(OSError):
                c.import_lyrics(path)
        self.assertIs(c.lyrics, previous)
        self.assertEqual(c.generation, generation)
        self.assertEqual(c.saved_lyric_kind, "selected")
        self.assertEqual(c.lyric_store.load(c.track)["lyrics"], previous)

    def test_failed_source_save_keeps_the_previous_saved_choice(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyrics, c.saved_lyric_kind = timed(), "selected"
        c.lyric_store.save(c.track, 0, c.lyrics)
        previous = c.lyrics
        c.lyric_choices = [{"id": "456"}]
        c.select_lyric_source("456")
        replacement = Lyrics([LyricLine(1., "New"), LyricLine(3., "Words")], source_id="456")
        with patch.object(c.lyric_store, "save", side_effect=OSError("read-only")):
            c.accept_lyrics(c.generation, replacement)
        self.assertIs(c.lyrics, previous)
        self.assertEqual(c.saved_lyric_kind, "selected")
        self.assertIsNone(c.selection_generation)
        self.assertIn("read-only", c.lyric_choices_status)
        self.assertEqual(c.lyric_store.load(c.track)["lyrics"], previous)

    def test_current_recording_duration_updates_restore_the_corresponding_correction(self):
        c = self.controller()
        c.accept_track(recording())
        c.adjust_lyrics(700)
        c.accept_track(recording(duration=0))
        self.assertEqual(c.song_offset, 0)
        c.accept_track(recording(duration=201))
        self.assertEqual(c.song_offset, 0)
        c.adjust_lyrics(-300)
        c.accept_track(recording())
        self.assertEqual(c.song_offset, 700)
        c.accept_track(recording(duration=201))
        self.assertEqual(c.song_offset, -300)

    def test_opening_picker_during_initial_lookup_does_not_abandon_automatic_lyrics(self):
        c = self.controller()
        requests = []
        c.requestLyrics.connect(lambda *args: requests.append(args))
        c.accept_track(recording())
        original_generation = c.generation
        c.find_lyric_choices()
        choice_generation = c.generation
        c.accept_lyrics(original_generation, timed())
        self.assertFalse(c.lyrics.lines)
        c.accept_lyric_choices(choice_generation, [{"id": "123", "timed": True}])
        self.assertEqual([request[1] for request in requests], [original_generation, choice_generation])
        c.accept_lyrics(choice_generation, timed())
        self.assertEqual(c.lyrics, timed())
        self.assertEqual(c.saved_lyric_kind, "")

    def test_opening_picker_preserves_an_existing_automatic_or_saved_result(self):
        c = self.controller()
        c.accept_track(recording())
        c.lyrics = timed()
        requests = []
        c.requestLyrics.connect(lambda *args: requests.append(args))
        c.find_lyric_choices()
        c.accept_lyric_choices(c.generation, [])
        self.assertEqual(c.lyrics, timed())
        self.assertEqual(requests, [])

    def test_demo_and_unknown_duration_cannot_save_corrections(self):
        c = self.controller()
        c.accept_track(recording(duration=0))
        c.adjust_lyrics(100)
        self.assertEqual(c.song_offset, 0)
        c.accept_track(recording())
        c.adjust_lyrics(700)
        c.set_demo(True)
        c.adjust_lyrics(100)
        self.assertEqual(c.song_offset, 0)
        c.set_demo(False)
        self.assertEqual(c.song_offset, 700)

    def test_settings_controls_and_source_picker_follow_the_current_recording(self):
        c = self.controller()
        window = MainWindow(c)
        def clean_window():
            window.settings_dialog.hide()
            window.draw_timer.stop()
            window.tray.hide()
            for widget in [window.immersive, window.overlay, *window.edges]:
                widget.hide()
                widget.deleteLater()
            window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        self.addCleanup(clean_window)
        studio = window.settings_dialog
        self.assertFalse(studio.song_timing_slider.isEnabled())
        c.accept_track(recording())
        self.assertTrue(studio.song_timing_slider.isEnabled())
        studio.song_timing_buttons[0].click()
        self.assertEqual(c.song_offset, 100)
        studio.song_timing_buttons[1].click()
        self.assertEqual(c.song_offset, 0)
        c.lyrics = timed()
        c.lyricsChanged.emit()
        self.assertIn("Some lines have word timestamps", studio.lyric_timing_status.text())
        studio.choose_lyrics_button.click()
        c.accept_lyric_choices(c.generation, [{"id": "123", "title": "Song", "artist": "Artist", "album": "Album", "duration": 200., "timed": True, "preview": "One two\nThree"}])
        dialog = window.lyric_choice_dialog
        self.assertIn("Album · 3:20", dialog.choices.item(0).text())
        self.assertEqual(dialog.preview.toPlainText(), "One two\nThree")
        dialog.choose.click()
        c.accept_lyrics(c.generation, timed())
        self.assertTrue(studio.automatic_lyrics_button.isEnabled())
        c.accept_track(recording(title="Other"))
        self.assertFalse(dialog.choose.isEnabled())
        self.assertEqual(dialog.choices.count(), 0)
        self.assertFalse(studio.automatic_lyrics_button.isEnabled())

    def test_compact_settings_scroll_reaches_every_new_control_and_reports_save_failure(self):
        c = self.controller()
        window = MainWindow(c)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        studio = window.settings_dialog
        studio.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        try:
            c.accept_track(recording())
            c.lyrics = timed()
            c.saved_lyric_kind = "selected"
            c.lyricsChanged.emit()
            c.set("reduced_motion", True)
            window.resize(960, 640)
            window.show()
            window.open_settings_section("lyrics")
            self.app.processEvents()
            scroll = studio.pages.currentWidget()
            controls = [studio.song_timing_slider, *studio.song_timing_buttons,
                        studio.import_lyrics_button, studio.choose_lyrics_button, studio.automatic_lyrics_button]
            for control in controls:
                with self.subTest(control=control.accessibleName() or control.text()):
                    scroll.ensureWidgetVisible(control)
                    self.app.processEvents()
                    origin = control.mapTo(scroll.viewport(), control.rect().topLeft())
                    self.assertTrue(scroll.viewport().rect().contains(control.rect().translated(origin)))
                    self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
                    self.assertTrue(control.isEnabled())
                    self.assertNotEqual(control.focusPolicy(), Qt.FocusPolicy.NoFocus)
            with patch.object(c.lyric_store, "clear_lyrics", side_effect=OSError("read-only")):
                studio.automatic_lyrics_button.click()
            self.assertIn("read-only", studio.lyric_timing_status.text())
        finally:
            studio.hide()
            window.draw_timer.stop()
            window.tray.hide()
            for widget in [window.immersive, window.overlay, *window.edges]:
                widget.hide()
                widget.deleteLater()
            window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
