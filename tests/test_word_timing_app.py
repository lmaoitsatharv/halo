"""Learned word timing inside the app: off changes nothing, and on stays out of the listener's way."""
import gc
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from qt_support import ensure_system_fonts
from halo.app import Controller, MainWindow
from halo.models import LyricLine, LyricWord, Lyrics, Track
from halo.settings_ui import LEARN_FIRST_LISTEN_NOTICE, LEARN_WORD_TIMING_HINT, show_learn_notice
from halo.widgets import LyricCanvas

LINES = [LyricLine(1, "go now then"), LyricLine(5, "we run home"), LyricLine(9, "they sing loud")]


class FakeTimer:
    def __init__(self):
        self.songs, self.fed, self.finished, self.closed, self.word = [], [], 0, False, None
        self.abandoned, self.failed = 0, False

    def start_song(self, key, lines, on_done):
        self.songs.append((key, list(lines), on_done))

    def finish_song(self):
        self.finished += 1

    def abandon_song(self):
        self.abandoned += 1

    def feed(self, samples, rate, position, playing):
        self.fed.append((position, playing))

    def live_word(self, line):
        return self.word

    def close(self):
        self.closed = True


def playing(title="Song", position=5.):
    return Track(title, "Band", "Album", 200, position, True, True, observed_at=time.monotonic())


class AppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="halo-word-timing-")
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "settings.ini")
        self.timer = FakeTimer()
        factory = patch("halo.app.WordTimer", lambda: self.timer)
        factory.start()
        self.addCleanup(factory.stop)

    def controller(self, learn=False):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        settings.setValue("learn_word_timing", learn)
        c = Controller(settings, offline=True)
        c.requestLyrics.disconnect()
        c.timer.stop()
        self.addCleanup(c.close)
        return c

    def with_song(self, c, track=None, source="42"):
        c.accept_track(track or playing())
        c.accept_lyrics(c.generation, Lyrics(list(LINES), "Line-synced lyrics", source_id=source))
        return c

    def tick(self, c):
        c.tick()
        return c.audio.enabled


class WordTimingAppTests(AppCase):
    def test_off_is_the_default_and_never_starts_anything(self):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        c = Controller(settings, offline=True)
        c.requestLyrics.disconnect()
        c.timer.stop()
        self.addCleanup(c.close)
        self.assertFalse(c.learn_word_timing)
        self.with_song(c)
        self.assertFalse(self.tick(c))
        self.assertIsNone(c.word_timer)
        self.assertEqual(self.timer.songs, [])

    def test_react_to_audio_is_unchanged(self):
        c = self.with_song(self.controller())
        c.set("halo_animation", "music")
        self.assertTrue(self.tick(c))
        self.assertIsNone(c.word_timer)

    def test_learning_does_not_turn_on_the_music_light(self):
        c = self.with_song(self.controller(True))
        c.audio.level = 1.
        c.tick()
        self.assertTrue(c.audio.enabled)
        c.set("halo_animation", "flow")
        c.pulse = 0.
        c.tick()
        self.assertEqual(c.pulse, 0.)

    def test_on_captures_without_react_to_audio(self):
        c = self.with_song(self.controller(True))
        self.assertTrue(self.tick(c))
        self.assertEqual(len(self.timer.songs), 1)
        self.assertEqual(self.timer.songs[-1][0], (c.track, c.learned_source(c.lyrics)))

    def test_capture_stops_when_paused(self):
        c = self.with_song(self.controller(True))
        c.accept_track(Track("Song", "Band", "Album", 200, 5, False, True))
        self.assertFalse(self.tick(c))

    def test_audio_reaches_the_timer_on_the_lyric_clock(self):
        c = self.with_song(self.controller(True))
        c.position, c.offset = 10., 500
        c.audio.listener(np.zeros((960, 2), np.float32), 48000)
        self.assertAlmostEqual(self.timer.fed[-1][0], 10.48)
        self.assertTrue(self.timer.fed[-1][1])

    def test_demo_never_captures(self):
        c = self.controller(True)
        c.set_demo(True)
        self.assertFalse(self.tick(c))
        self.assertEqual(self.timer.songs, [])

    def test_saved_timing_loads_with_lyrics(self):
        c = self.controller(True)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), "Line-synced lyrics", source_id="42"))
        self.assertEqual([word.start for word in c.lyrics.lines[0].words], [1., 1.4, 1.8])
        self.assertEqual(c.lyrics.timing_source, "learned")
        self.assertEqual(c.lyrics.lines[1].words, ())

    def test_saved_timing_is_ignored_while_off(self):
        c = self.controller(False)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="42"))
        self.assertEqual(c.lyrics.lines[0].words, ())

    def test_finished_songs_are_saved_for_their_own_track(self):
        c = self.with_song(self.controller(True))
        key, _, on_done = self.timer.songs[-1]
        c.accept_track(playing("Other song"))
        on_done(key, {0: [1., 1.4, 1.8]})
        self.assertEqual(c.learned_store.load(key[0], key[1]), {0: [1., 1.4, 1.8]})
        self.assertEqual(c.learned_store.load(c.track, key[1]), {})

    def test_a_track_change_finishes_the_old_song_first(self):
        c = self.with_song(self.controller(True))
        finished = self.timer.finished
        c.accept_track(playing("Other song"))
        self.assertEqual(self.timer.finished, finished + 1)

    def test_imported_lyrics_are_not_learned_over(self):
        c = self.with_song(self.controller(True))
        c.saved_lyric_kind = "imported"
        c.learned_store.save(c.track, "import", {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="import"))
        self.assertEqual(c.lyrics.lines[0].words, ())
        self.assertIsNone(c.timing_session)
        self.assertFalse(self.tick(c))

    def test_fully_word_timed_lyrics_need_no_listening(self):
        c = self.controller(True)
        c.accept_track(playing())
        timed = [LyricLine(1, "go", (LyricWord("go", 1.),))]
        c.accept_lyrics(c.generation, Lyrics(timed, source_id="42"))
        self.assertIsNone(c.timing_session)
        self.assertFalse(self.tick(c))

    def test_turning_off_mid_song_stops_capture_and_restores_the_lyrics(self):
        c = self.controller(True)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="42"))
        c.set("learn_word_timing", False)
        self.assertFalse(self.tick(c))
        self.assertEqual(c.lyrics.lines[0].words, ())
        self.assertEqual(c.lyrics.timing_source, "")

    def test_turning_on_mid_song_applies_saved_timing_and_listens(self):
        c = self.with_song(self.controller(False))
        c.learned_store.save(c.track, c.learned_source(c.lyrics), {0: [1., 1.4, 1.8]})
        c.set("learn_word_timing", True)
        self.assertTrue(c.lyrics.lines[0].words)
        self.assertTrue(self.tick(c))

    def test_forget_clears_timing_and_restores_the_lyrics(self):
        c = self.controller(True)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="42"))
        c.forget_learned_timing()
        self.assertEqual(c.learned_store.load(c.track, source), {})
        self.assertEqual(c.lyrics.lines[0].words, ())

    def test_forget_during_a_listen_is_not_undone(self):
        c = self.with_song(self.controller(True))
        finished = self.timer.finished
        c.forget_learned_timing()
        self.assertEqual(self.timer.abandoned, 1)
        self.assertEqual(self.timer.finished, finished)

    def test_changed_lyrics_under_the_same_source_discard_learned_timing(self):
        c = self.controller(True)
        c.accept_track(playing())
        c.learned_store.save(c.track, c.learned_source(Lyrics(list(LINES), source_id="42")), {0: [1., 1.4, 1.8]})
        shifted = [LyricLine(0, "new first line"), *LINES]
        c.accept_lyrics(c.generation, Lyrics(shifted, source_id="42"))
        self.assertEqual(c.lyrics.lines[0].words, ())
        self.assertEqual(c.lyrics.lines[1].words, ())

    def test_toggling_after_an_import_keeps_the_import(self):
        c = self.with_song(self.controller(True))
        imported = Path(self.path).with_name("song.lrc")
        imported.write_text("[00:01.00]imported words here\n[00:05.00]more of them\n", encoding="utf-8")
        c.import_lyrics(str(imported))
        c.set("learn_word_timing", False)
        self.assertEqual(c.lyrics.lines[0].text, "imported words here")
        c.forget_learned_timing()
        self.assertEqual(c.lyrics.lines[0].text, "imported words here")

    def test_toggling_in_demo_keeps_the_demo(self):
        c = self.with_song(self.controller(True))
        c.set_demo(True)
        text = c.lyrics.lines[0].text
        c.set("learn_word_timing", False)
        self.assertEqual(c.lyrics.lines[0].text, text)

    def test_a_song_it_cannot_spell_is_not_followed(self):
        c = self.controller(True)
        c.accept_track(playing())
        c.accept_lyrics(c.generation, Lyrics([LyricLine(1, "तुम ही हो")], source_id="42"))
        self.assertIsNone(c.timing_session)
        self.assertEqual(c.timing_label(), "")
        self.assertFalse(self.tick(c))

    def test_a_failed_timer_stops_the_session_and_the_badge(self):
        c = self.with_song(self.controller(True))
        self.timer.failed = True
        self.assertFalse(self.tick(c))
        self.assertIsNone(c.timing_session)
        self.assertEqual(c.timing_label(), "")

    def test_a_capture_error_drops_the_following_badge(self):
        c = self.with_song(self.controller(True))
        c.audio.error = "Audio output unavailable"
        self.assertEqual(c.timing_label(), "")

    def test_switching_off_closes_the_timer(self):
        c = self.with_song(self.controller(True))
        c.set("learn_word_timing", False)
        self.assertTrue(self.timer.closed)
        self.assertIsNone(c.word_timer)

    def test_close_finishes_the_song_and_stops_the_timer(self):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        settings.setValue("learn_word_timing", True)
        c = Controller(settings, offline=True)
        c.requestLyrics.disconnect()
        self.with_song(c)
        finished = self.timer.finished
        c.close()
        self.assertEqual(self.timer.finished, finished + 1)
        self.assertTrue(self.timer.closed)


class WordTimingSurfaceTests(AppCase):
    def window(self, c):
        window = MainWindow(c)
        window.draw_timer.stop()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.addCleanup(window.deleteLater)
        return window

    def test_switch_is_off_and_explains_itself(self):
        window = self.window(self.controller())
        self.assertFalse(window.setting_controls["learn_word_timing"].isChecked())
        for words in ("all sound", "small model", "this PC", "only word times", "never saves or sends audio", "Spotify's rules"):
            self.assertIn(words, LEARN_WORD_TIMING_HINT)
        self.assertNotIn("verified sync", LEARN_WORD_TIMING_HINT.lower())
        self.assertIn("which songs", LEARN_WORD_TIMING_HINT)

    def switch(self, window):
        return window.setting_controls["learn_word_timing"]

    def test_turning_it_on_shows_the_first_listen_notice(self):
        c = self.controller()
        window = self.window(c)
        with patch("halo.settings_ui.show_learn_notice", return_value=False) as notice:
            self.switch(window).click()
        notice.assert_called_once()
        self.assertTrue(c.learn_word_timing)

    def test_the_notice_says_replays_are_smoother(self):
        for words in ("first listen", "abrupt", "next word", "Replays", "saved timing"):
            self.assertIn(words, LEARN_FIRST_LISTEN_NOTICE)

    def test_dont_show_again_is_remembered_across_restarts(self):
        c = self.controller()
        window = self.window(c)
        with patch("halo.settings_ui.show_learn_notice", return_value=True):
            self.switch(window).click()
        self.switch(window).click()
        with patch("halo.settings_ui.show_learn_notice") as notice:
            self.switch(window).click()
        notice.assert_not_called()
        reloaded = QSettings(self.path, QSettings.Format.IniFormat)
        self.assertEqual(reloaded.value("hide_learn_word_timing_notice", False, type=bool), True)

    def test_the_notice_returns_unless_dont_show_again_was_ticked(self):
        c = self.controller()
        window = self.window(c)
        with patch("halo.settings_ui.show_learn_notice", return_value=False) as notice:
            self.switch(window).click()
            self.switch(window).click()
            self.switch(window).click()
        self.assertEqual(notice.call_count, 2)

    def answer_real_notice(self, tick):
        """Paint the real dialog, then answer it the way a person would."""
        def answer():
            box = QApplication.activeModalWidget()
            gc.collect()
            box.grab()
            box.checkBox().setChecked(tick)
            box.accept()
        QTimer.singleShot(0, answer)

    def test_the_real_notice_reports_the_tick(self):
        self.answer_real_notice(True)
        self.assertTrue(show_learn_notice(None))

    def test_the_real_notice_reports_no_tick(self):
        self.answer_real_notice(False)
        self.assertFalse(show_learn_notice(None))

    def test_the_real_notice_opens_from_the_real_switch(self):
        c = self.controller()
        window = self.window(c)
        self.answer_real_notice(True)
        self.switch(window).click()
        self.assertTrue(c.hide_learn_word_timing_notice)

    def test_turning_it_off_shows_nothing(self):
        c = self.controller(True)
        window = self.window(c)
        with patch("halo.settings_ui.show_learn_notice") as notice:
            self.switch(window).click()
        notice.assert_not_called()
        self.assertFalse(c.learn_word_timing)

    def test_restoring_the_saved_setting_shows_nothing(self):
        with patch("halo.settings_ui.show_learn_notice") as notice:
            window = self.window(self.controller(True))
            self.assertTrue(self.switch(window).isChecked())
        notice.assert_not_called()

    def test_learned_status_text(self):
        c = self.controller(True)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="42"))
        self.assertEqual(c.timing_label(), "Word timing learned on this PC")

    def test_live_status_text(self):
        c = self.with_song(self.controller(True))
        self.assertEqual(c.timing_label(), "Line synced · words following playback")

    def test_no_label_while_off(self):
        self.assertEqual(self.with_song(self.controller(False)).timing_label(), "")

    def test_paused_song_still_counts_as_following(self):
        c = self.with_song(self.controller(True))
        c.accept_track(Track("Song", "Band", "Album", 200, 5, False, True))
        self.assertEqual(c.timing_label(), "Line synced · words following playback")

    def test_forget_buttons_clear_timing(self):
        c = self.controller(True)
        window = self.window(c)
        c.accept_track(playing())
        source = c.learned_source(Lyrics(list(LINES), source_id="42"))
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        c.accept_lyrics(c.generation, Lyrics(list(LINES), source_id="42"))
        window.settings_dialog.forget_timing_button.click()
        self.assertEqual(c.learned_store.load(c.track, source), {})
        c.learned_store.save(c.track, source, {0: [1., 1.4, 1.8]})
        window.settings_dialog.forget_all_timing_button.click()
        self.assertEqual(c.learned_store.load(c.track, source), {})

    def test_readme_no_longer_says_halo_does_not_listen(self):
        readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("does not listen to the singing", readme)
        self.assertNotIn("no audio alignment", readme)
        self.assertIn("listening history", readme)
        self.assertIn("Learn word timing from playback", readme)
        self.assertIn("Spotify", readme)


class CanvasController:
    """The small surface a canvas reads, plus a settable live word."""
    def __init__(self):
        self.lyrics = Lyrics(list(LINES))
        self.track = Track(duration=18, playing=True)
        self.position, self.offset, self.generation, self.motion_time = 5.1, 0, 1, 10.
        self.lyric_style, self.reduced_motion = "visual", True
        self.primary, self.secondary = QColor("#e0d4f0"), QColor("#9b88cf")
        self.word = None

    def live_word(self, line):
        return self.word

    def seek(self, value):
        pass


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def canvas(self, style="visual"):
        c = CanvasController()
        c.lyric_style = style
        canvas = LyricCanvas(c, "immersive")
        canvas.resize(600, 300)
        self.addCleanup(canvas.close)
        return c, canvas

    def shown(self, canvas, method="_visual"):
        seen = []
        real = getattr(canvas, method)

        def spy(p, index, word_index, *rest):
            seen.append(word_index)
            return real(p, index, word_index, *rest)
        with patch.object(canvas, method, side_effect=spy):
            canvas.grab()
        return seen[-1]

    def test_live_word_drives_the_canvas(self):
        c, canvas = self.canvas()
        canvas.grab()
        c.word = 2
        self.assertEqual(self.shown(canvas), canvas.timeline.display_word(1, 2))

    def test_no_live_word_keeps_the_estimate(self):
        c, canvas = self.canvas()
        canvas.grab()
        self.assertEqual(self.shown(canvas), canvas.timeline.display_at(1, c.position)[1])

    def test_seek_back_moves_the_live_word_back(self):
        c, canvas = self.canvas()
        c.word = 2
        canvas.grab()
        c.word = None
        c.position = 5.01
        self.assertEqual(self.shown(canvas), canvas.timeline.display_at(1, 5.01)[1])

    def test_a_line_with_real_word_timing_ignores_live_words(self):
        c, canvas = self.canvas()
        words = (LyricWord("we ", 5.), LyricWord("run ", 5.05), LyricWord("home", 7.))
        c.lyrics = Lyrics([LINES[0], LyricLine(5, "we run home", words), LINES[2]])
        c.generation += 1
        canvas.grab()
        c.word = 2
        self.assertEqual(self.shown(canvas), canvas.timeline.display_at(1, c.position)[1])

    def test_ship_ignores_live_words(self):
        c, canvas = self.canvas("ship_visual")
        image = canvas.grab().toImage()
        c.word = 2
        self.assertEqual(image, canvas.grab().toImage())

    def test_glow_entrance_counts_from_the_live_word(self):
        c, canvas = self.canvas("lyric_impact")
        canvas.grab()
        c.word = 2
        canvas.grab()
        shown = canvas.timeline.display_word(1, 2)
        c.position += .05
        self.assertAlmostEqual(canvas.word_elapsed(shown, c.position), .05)

    def peak_speed(self, learned):
        """Peak words per second of the on-screen position through a burst of quick and slow words."""
        c, canvas = self.canvas("fisheye_visual")
        c.reduced_motion = False
        starts = [1., 1.1, 1.2, 1.7, 1.82, 2.5, 2.6, 2.72]
        text = "one two six ten red big old sun"
        pieces = text.split()
        words = tuple(LyricWord(piece + (" " if k + 1 < len(pieces) else ""), starts[k]) for k, piece in enumerate(pieces))
        c.lyrics = Lyrics([LyricLine(1, text, words), LyricLine(5, "then we go")],
                          timing_source="learned" if learned else "")
        c.position, c.motion_time = .95, 10.
        c.generation += 1
        canvas.grab()
        peak = 0.
        for frame in range(150):
            c.position += 1 / 60
            c.motion_time += 1 / 60
            canvas.grab()
            peak = max(peak, abs(canvas._word_velocity))
        return peak

    def test_learned_words_glide_instead_of_snapping(self):
        self.assertLess(self.peak_speed(True), 10.)
        self.assertGreater(self.peak_speed(False), 12.)

    def test_a_glide_reaches_the_word_about_when_it_is_sung(self):
        c, canvas = self.canvas()
        c.lyrics = Lyrics([LyricLine(1, "go now", (LyricWord("go ", 1.), LyricWord("now", 3.)))], timing_source="learned")
        c.generation += 1
        canvas.grab()
        timeline = canvas.timeline
        self.assertEqual(timeline.flowing(0, 1.5), 0.)
        self.assertGreater(timeline.flowing(0, 2.9), .5)
        self.assertLessEqual(timeline.flowing(0, 3.), 1.)
        self.assertEqual(timeline.flowing(1, 4.), 1.)

    def test_elapsed_uses_the_timeline_without_a_live_word(self):
        c, canvas = self.canvas()
        canvas.grab()
        word = canvas.timeline.display_at(1, c.position)[1]
        begin = canvas.timeline.display_words[word].begin
        self.assertAlmostEqual(canvas.word_elapsed(word, c.position), c.position - begin)


if __name__ == "__main__":
    unittest.main()
