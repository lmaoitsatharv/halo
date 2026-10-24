"""Native Modes browsing, explicit collection actions and preview isolation."""
from contextlib import ExitStack
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal, Qt, QEvent
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from halo.mode_catalog import all_modes, find_mode
from halo.mode_library import ModeLibrary
from halo.models import Lyrics, LyricLine, Track


class LibraryController(QObject):
    modeLibraryChanged = Signal()
    settingChanged = Signal()
    paletteChanged = Signal()
    trackChanged = Signal()
    lyricsChanged = Signal()

    def __init__(self):
        super().__init__()
        self.track = Track("A listener's actual song", "A listener's actual artist", "Real album", 200, 52, True, True)
        self.lyrics = Lyrics([LyricLine(0, "The listener's real lyrics")])
        self.primary, self.secondary = QColor("#d4bce8"), QColor("#7aa7cb")
        self.lyric_style, self.immersive_mode, self.halo_mode = "ship_visual", "studio", "orbit"
        self.added_modes = {"lyrics": [], "scenes": [], "halo": []}
        self.position, self.offset, self.generation = 52., 350, 9
        self.reduced_motion = False
        self.calls = []

    def has_mode(self, kind, key):
        spec = find_mode(kind, key)
        return bool(spec and (spec.included or key in self.added_modes[kind]))

    def add_mode(self, kind, key):
        spec = find_mode(kind, key)
        if spec is None:
            return False
        if not self.has_mode(kind, key):
            self.calls.append(("add", kind, key))
            self.added_modes[kind].append(key)
            self.modeLibraryChanged.emit()
        return True

    def remove_mode(self, kind, key):
        spec = find_mode(kind, key)
        if spec is None or spec.included or key not in self.added_modes[kind]:
            return False
        self.calls.append(("remove", kind, key))
        self.added_modes[kind].remove(key)
        if getattr(self, spec.field) == key:
            self.set(spec.field, {"lyrics": "ship_visual", "scenes": "studio", "halo": "orbit"}[kind])
        self.modeLibraryChanged.emit()
        return True

    def set(self, name, value):
        self.calls.append(("set", name, value))
        setattr(self, name, value)
        self.settingChanged.emit()


class ModeLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.owner.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.controller = LibraryController()
        self.library = ModeLibrary(self.owner, self.controller)
        self.library.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)

    def tearDown(self):
        self.library.hide()
        self.library.deleteLater()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def open(self, kind="all"):
        self.library.open_page(kind)
        self.app.processEvents()

    def optional(self):
        return next(spec for spec in all_modes() if not spec.included)

    def test_browsing_search_and_live_previews_never_mutate_the_real_song(self):
        c = self.controller
        track, lyrics = c.track, c.lyrics
        original = (c.position, c.offset, c.generation, c.lyric_style, c.immersive_mode, c.halo_mode)
        self.open()
        self.library.search.setText("Runway")
        self.app.processEvents()
        self.assertEqual([spec.title for spec in self.library.filtered_specs], ["Runway"])
        self.assertEqual(self.library.selected.title, "Runway")
        self.assertIsNot(self.library.selected_preview.proxy.track, track)
        self.assertIsNot(self.library.selected_preview.proxy.lyrics, lyrics)
        self.library.selected_preview.grab()
        QTest.qWait(90)
        self.library.search.clear()
        self.library.set_category("halo")
        self.library.selected_preview.grab()
        self.assertIs(c.track, track)
        self.assertIs(c.lyrics, lyrics)
        self.assertEqual(original, (c.position, c.offset, c.generation, c.lyric_style, c.immersive_mode, c.halo_mode))
        self.assertEqual(c.calls, [])

    def test_add_use_and_remove_are_explicit_and_update_collection_states(self):
        self.open()
        spec = self.optional()
        self.library.select_mode(spec)
        before = getattr(self.controller, spec.field)
        self.assertTrue(self.library.add_button.isEnabled())
        QTest.mouseClick(self.library.add_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self.controller.has_mode(spec.kind, spec.key))
        self.assertEqual(getattr(self.controller, spec.field), before)
        self.assertFalse(self.library.add_button.isEnabled())
        self.assertTrue(self.library.remove_button.isVisible())
        QTest.mouseClick(self.library.use_button, Qt.MouseButton.LeftButton)
        self.assertEqual(getattr(self.controller, spec.field), spec.key)
        self.assertEqual(self.library.use_button.text(), "Currently in use")
        QTest.mouseClick(self.library.remove_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.controller.has_mode(spec.kind, spec.key))
        self.assertNotEqual(getattr(self.controller, spec.field), spec.key)
        self.assertTrue(self.library.add_button.isEnabled())

    def test_use_can_add_a_mode_in_one_deliberate_action(self):
        self.open()
        spec = self.optional()
        self.library.select_mode(spec)
        QTest.mouseClick(self.library.use_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self.controller.has_mode(spec.kind, spec.key))
        self.assertEqual(getattr(self.controller, spec.field), spec.key)
        self.assertEqual(self.controller.calls[:2], [("add", spec.kind, spec.key), ("set", spec.field, spec.key)])

    def test_included_modes_cannot_be_removed_and_my_modes_filters_optional_additions(self):
        self.open("mine")
        self.assertTrue(all(spec.included for spec in self.library.filtered_specs))
        included = next(spec for spec in self.library.filtered_specs if spec.kind == "lyrics")
        self.library.select_mode(included)
        self.assertFalse(self.library.add_button.isEnabled())
        self.assertFalse(self.library.remove_button.isVisible())
        spec = self.optional()
        self.controller.add_mode(spec.kind, spec.key)
        self.assertIn(spec, self.library.filtered_specs)
        self.controller.remove_mode(spec.kind, spec.key)
        self.assertNotIn(spec, self.library.filtered_specs)

    def test_timers_stop_hidden_paused_and_reduced_motion(self):
        self.open()
        self.assertTrue(self.library.timer.isActive())
        QTest.qWait(100)
        before = self.library.clock.elapsed
        self.assertGreater(before, 5.8)
        self.library.pause_button.click()
        self.assertFalse(self.library.timer.isActive())
        QTest.qWait(80)
        self.assertEqual(before, self.library.clock.elapsed)
        self.library.pause_button.click()
        self.assertTrue(self.library.timer.isActive())
        self.controller.reduced_motion = True
        self.controller.settingChanged.emit()
        self.assertTrue(self.library.timer.isActive(), "Live words still update without decorative motion")
        before = self.library.clock.elapsed
        QTest.qWait(80)
        self.assertEqual(before, self.library.clock.elapsed)
        self.controller.track.connected = False
        self.controller.trackChanged.emit()
        self.assertFalse(self.library.timer.isActive(), "Reduced-motion sample previews can sleep")
        self.controller.reduced_motion = False
        self.controller.settingChanged.emit()
        self.assertTrue(self.library.timer.isActive())
        self.library.hide()
        self.assertFalse(self.library.timer.isActive())
        before = self.library.clock.elapsed
        QTest.qWait(80)
        self.assertEqual(before, self.library.clock.elapsed)

    def test_only_viewport_visible_cards_get_animation_updates(self):
        self.open()
        self.library.timer.stop()
        visible = self.library.visible_cards()
        self.assertTrue(visible)
        self.assertLess(len(visible), len(self.library.cards))
        with ExitStack() as stack:
            updates = {card: stack.enter_context(patch.object(card.preview, "update")) for card in self.library.cards.values()}
            self.library._tick_number = 1
            self.library.tick()
            for card, update in updates.items():
                self.assertEqual(update.called, card in visible)

    def test_compact_and_large_layout_keep_actions_reachable_and_grid_inside_viewport(self):
        self.open()
        for width, height in ((960, 640), (1280, 840)):
            with self.subTest(size=(width, height)):
                self.library.resize(width, height)
                self.app.processEvents()
                self.library.reflow()
                self.app.processEvents()
                self.assertEqual((self.library.width(), self.library.height()), (width, height))
                for widget in (self.library.close_button, self.library.add_button, self.library.use_button, self.library.search):
                    point = widget.mapTo(self.library, widget.rect().center())
                    self.assertTrue(self.library.rect().contains(point), widget.objectName())
                self.assertLessEqual(self.library.grid_widget.width(), self.library.scroll.viewport().width())
                self.assertFalse(self.library.scroll.horizontalScrollBar().isVisible())

    def test_empty_search_and_escape_work_without_changes(self):
        self.open()
        self.library.search.setText("no_such_original_mode_123")
        self.app.processEvents()
        self.assertTrue(self.library.empty_label.isVisible())
        self.assertEqual(self.library.filtered_specs, [])
        QTest.keyClick(self.library, Qt.Key.Key_Escape)
        self.assertFalse(self.library.isVisible())
        self.assertFalse(self.library.timer.isActive())
        self.assertEqual(self.controller.calls, [])

    def test_all_catalogue_modes_render_distinctly_without_touching_live_state(self):
        self.open()
        self.controller.reduced_motion = True
        self.controller.settingChanged.emit()
        hashes = set()
        for spec in self.library.specs:
            with self.subTest(mode=spec.identity):
                self.library.select_mode(spec, animate=False)
                image = self.library.selected_preview.grab().toImage()
                hashes.add(hashlib.sha256(image.constBits()).hexdigest())
                self.assertTrue(self.library.cards[spec.identity].isChecked())
        self.assertEqual(len(hashes), len(self.library.specs))
        self.assertEqual(self.controller.calls, [])

    def test_closing_mid_transition_reopens_with_an_undimmed_preview(self):
        self.open()
        self.library.select_mode(self.library.specs[1], animate=True)
        QTest.qWait(25)
        self.library.hide()
        self.open()
        self.assertEqual(self.library.selected_preview._reveal, 1.)

    def test_compact_selected_preview_keeps_the_real_scene_aspect_ratio(self):
        self.open()
        preview = self.library.selected_preview
        preview.set_spec(find_mode("scenes", "orbit"), animate=False)
        preview.setFixedSize(400, 120)
        transforms = []
        with patch.object(preview, "_scene", side_effect=lambda painter: transforms.append(painter.transform())):
            preview.grab()
        self.assertTrue(transforms)
        self.assertAlmostEqual(transforms[-1].m11(), transforms[-1].m22())
        self.assertAlmostEqual(transforms[-1].m11(), 120 / 625)

    def test_minimizing_suspends_preview_work_and_restoring_resumes(self):
        self.open()
        self.assertTrue(self.library.timer.isActive())
        self.library.showMinimized()
        self.app.processEvents()
        self.assertFalse(self.library.timer.isActive())
        position = self.library.clock.elapsed
        QTest.qWait(90)
        self.assertEqual(self.library.clock.elapsed, position)
        self.library.showNormal()
        self.app.processEvents()
        self.assertTrue(self.library.timer.isActive())

    def test_destroying_a_page_cancels_its_queued_layout_work(self):
        page = ModeLibrary(self.owner, self.controller)
        page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        errors = []
        with patch("sys.excepthook", side_effect=lambda *args: errors.append(args)):
            page.open_page("scenes")
            page.hide()
            page.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        self.assertEqual(errors, [])

    def test_all_previews_follow_current_lyrics_position_and_correction(self):
        self.open()
        for preview in (self.library.selected_preview, *(card.preview for card in self.library.cards.values())):
            proxy = preview.proxy
            self.assertTrue(proxy.uses_live)
            self.assertIsNot(proxy.lyrics, self.controller.lyrics)
            self.assertIsNot(proxy.lyrics.lines, self.controller.lyrics.lines)
            self.assertEqual(proxy.lyrics.lines, self.controller.lyrics.lines)
            self.assertEqual(proxy.position, 52.)
            self.assertEqual(proxy.offset, 350)
            self.assertEqual((proxy.track.title, proxy.track.artist, proxy.track.duration),
                             (self.controller.track.title, self.controller.track.artist, 200))
        self.assertIn("Current song lyrics", self.library.preview_note.text())
        self.controller.position = 95.25
        self.assertEqual(self.library.selected_preview.proxy.position, 95.25)

    def test_preview_pause_freezes_only_the_preview_then_catches_up(self):
        self.open()
        proxy = self.library.selected_preview.proxy
        self.assertEqual(proxy.position, 52.)
        self.library.pause_button.click()
        self.controller.position = 60.
        self.assertEqual(proxy.position, 52.)
        self.assertTrue(self.controller.track.playing)
        self.library.pause_button.click()
        self.assertEqual(proxy.position, 60.)

    def test_song_change_and_lyrics_arrival_replace_the_preview_without_stale_text(self):
        self.open()
        proxy = self.library.selected_preview.proxy
        old_generation = proxy.generation
        self.controller.track = Track("A new original song", "Halo tests", duration=90, playing=True, connected=True)
        self.controller.lyrics = Lyrics()
        self.controller.generation += 1
        self.controller.position = 3.
        self.controller.trackChanged.emit()
        self.controller.lyricsChanged.emit()
        self.assertFalse(proxy.uses_live)
        self.assertIn("Sample lyrics", self.library.preview_note.text())
        self.controller.lyrics = Lyrics([LyricLine(0, "Entirely new original words")])
        self.controller.lyricsChanged.emit()
        self.assertTrue(proxy.uses_live)
        self.assertEqual(proxy.lyrics.lines[0].text, "Entirely new original words")
        self.assertEqual(proxy.position, 3.)
        self.assertNotEqual(proxy.generation, old_generation)
        self.assertEqual(proxy.track.title, "A new original song")

    def test_paused_song_keeps_lyrics_and_freezes_decorative_motion(self):
        self.open()
        self.controller.track.playing = False
        before = self.library.clock.elapsed
        QTest.qWait(100)
        self.assertEqual(self.library.clock.elapsed, before)
        self.assertTrue(self.library.selected_preview.proxy.uses_live)
        self.assertFalse(self.library.selected_preview.proxy.track.playing)
        self.controller.position = 12.
        self.assertEqual(self.library.selected_preview.proxy.position, 12.)

    def test_no_song_uses_clearly_labelled_sample_words(self):
        self.controller.track.connected = False
        self.open()
        proxy = self.library.selected_preview.proxy
        self.assertFalse(proxy.uses_live)
        self.assertEqual(proxy.track.title, "Afterglow")
        self.assertIn("Original demo words", self.library.preview_note.text())

    def test_immersive_and_light_preview_metadata_uses_the_current_song(self):
        self.open()
        from halo import mode_library
        for identity in (("scenes", "studio"), ("scenes", "scene_refraction"), ("halo", "aurora")):
            self.library.select_mode(find_mode(*identity), animate=False)
            with patch.object(mode_library, "_text", wraps=mode_library._text) as text:
                self.library.selected_preview.grab()
                rendered = [call.args[2] for call in text.call_args_list]
                self.assertIn(self.controller.track.title, rendered)
                self.assertNotIn("Afterglow", rendered)


if __name__ == "__main__":
    unittest.main()
