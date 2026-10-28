"""Optional mode selection persists and updates every native selector."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow
from halo.mode_catalog import BASE_MODE_KEYS, MODE_FIELDS, all_modes, read_collection
from halo.scene_extras import EXTRA_SCENES, extra_scene_layout


class ModeCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-mode-collection-", dir=scratch)
        self.path = str(Path(self.temp.name) / "settings.ini")
        self.controllers = []
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.draw_timer.stop()
            window.settings_dialog.hide()
            window.tray.hide()
            if window.mode_library is not None:
                window.mode_library.hide()
            window.immersive.media_background.close()
            for widget in (window.immersive, window.overlay, *window.edges, window):
                widget.hide()
                widget.deleteLater()
        for c in self.controllers:
            c.close()
            c.audio.thread.join(1)
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def controller(self):
        c = Controller(QSettings(self.path, QSettings.Format.IniFormat), offline=True)
        c.timer.stop()
        self.controllers.append(c)
        return c

    def window(self, c):
        window = MainWindow(c)
        window.draw_timer.stop()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.windows.append(window)
        return window

    def test_catalogue_contains_nine_optional_modes_across_three_categories(self):
        modes = all_modes()
        self.assertEqual(len({spec.identity for spec in modes}), len(modes))
        self.assertEqual(len([spec for spec in modes if not spec.included]), 9)
        for kind in MODE_FIELDS:
            self.assertEqual(len([spec for spec in modes if spec.kind == kind and not spec.included]), 3)

    def test_default_selectors_keep_the_familiar_included_modes(self):
        c = self.controller()
        for kind, field in MODE_FIELDS.items():
            self.assertEqual(tuple(spec[0] for spec in c.mode_specs(field)), BASE_MODE_KEYS[kind])

    def test_adding_a_mode_does_not_change_playback_lyrics_or_active_choices(self):
        c = self.controller()
        before = (c.track, c.lyrics, c.position, c.generation, c.lyric_style, c.immersive_mode, c.halo_mode)
        self.assertTrue(c.add_mode("lyrics", "lyric_marquee"))
        self.assertTrue(c.add_mode("lyrics", "lyric_marquee"))
        self.assertEqual(c.added_modes["lyrics"], ["lyric_marquee"])
        self.assertEqual(before, (c.track, c.lyrics, c.position, c.generation, c.lyric_style, c.immersive_mode, c.halo_mode))

    def test_add_and_remove_refresh_main_immersive_and_settings_without_restart(self):
        c = self.controller()
        window = self.window(c)
        c.add_mode("lyrics", "lyric_marquee")
        for selector in (window.style_select, window.immersive.style_select):
            self.assertGreaterEqual(selector.findData("lyric_marquee"), 0)
        self.assertIn("lyric_marquee", {tile.mode_id for tile in window.mode_tiles})
        c.set("lyric_style", "lyric_marquee")
        self.assertEqual(window.style_select.currentData(), "lyric_marquee")
        self.assertTrue(c.remove_mode("lyrics", "lyric_marquee"))
        self.assertEqual(c.lyric_style, "ship_visual")
        for selector in (window.style_select, window.immersive.style_select):
            self.assertEqual(selector.findData("lyric_marquee"), -1)
        self.assertNotIn("lyric_marquee", {tile.mode_id for tile in window.mode_tiles})

    def test_chosen_collection_and_active_extras_survive_reload(self):
        c = self.controller()
        choices = {"lyric_style": "lyric_afterimage", "immersive_mode": "scene_refraction", "halo_mode": "meteor"}
        for field, key in choices.items():
            c.set(field, key)
        c.settings.sync()
        restored = self.controller()
        for kind, field in MODE_FIELDS.items():
            self.assertEqual(getattr(restored, field), choices[field])
            self.assertTrue(restored.has_mode(kind, choices[field]))

    def test_background_dropdowns_remain_intact_when_optional_modes_are_added(self):
        c = self.controller()
        window = self.window(c)
        studio = window.settings_dialog
        fields = ("background_art_source", "background_fit", "background_motion", "background_playback")
        before = {field: [(studio.background_controls[field].itemData(i), studio.background_controls[field].itemText(i))
                          for i in range(studio.background_controls[field].count())] for field in fields}
        self.assertTrue(all(before.values()))
        c.add_mode("halo", "aurora")
        c.add_mode("lyrics", "lyric_monument")
        for field in fields:
            selector = studio.background_controls[field]
            self.assertEqual([(selector.itemData(i), selector.itemText(i)) for i in range(selector.count())], before[field])

    def test_malformed_and_unknown_collection_entries_are_ignored(self):
        for raw in ("{", "[]", "x" * 65537, None, {"lyrics": ["unknown", 1, "ship_visual"], "halo": {"meteor": True}}):
            self.assertEqual(read_collection(raw), {kind: [] for kind in MODE_FIELDS})
        self.assertEqual(read_collection({"halo": ["meteor", "meteor", "foreign"]})["halo"], ["meteor"])
        c = self.controller()
        self.assertFalse(c.add_mode("lyrics", "scene_gallery"))
        self.assertFalse(c.remove_mode("lyrics", "ship_visual"))

    def test_selected_extra_is_recovered_if_collection_record_is_missing(self):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        settings.setValue("lyric_style", "lyric_monument")
        settings.sync()
        c = self.controller()
        self.assertTrue(c.has_mode("lyrics", "lyric_monument"))
        self.assertEqual(c.lyric_style, "lyric_monument")

    def test_each_added_scene_uses_its_real_layout_and_fits_compact_and_large_views(self):
        c = self.controller()
        window = self.window(c)
        c.set_demo(True)
        for scene, _, _ in EXTRA_SCENES:
            c.set("immersive_mode", scene)
            for width, height in ((960, 640), (1920, 1080)):
                with self.subTest(scene=scene, size=(width, height)):
                    room = window.immersive
                    room.resize(width, height)
                    room._arrange()
                    layout = extra_scene_layout(scene, width, height)
                    self.assertEqual(room.canvas.geometry(), layout["canvas"])
                    self.assertEqual(room.cover.geometry(), layout["cover"])
                    self.assertFalse(room.cover.geometry().intersects(room.canvas.geometry()))
                    self.assertFalse(room.now_label.isVisible())
                    self.assertFalse(room.words_label.isVisible())
                    self.assertFalse(room.grab().isNull())

    def test_modes_page_restores_the_settings_section_it_was_opened_from(self):
        c = self.controller()
        window = self.window(c)
        window.settings_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.settings_dialog.open_studio("lyrics")
        window.open_modes("lyrics")
        self.assertFalse(window.settings_dialog.isVisible())
        self.assertTrue(window.mode_library.isVisible())
        window.mode_library.reject()
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertEqual(window.settings_dialog.section, "lyrics")

    def test_nested_immersive_settings_and_modes_return_to_the_maximized_app(self):
        c = self.controller()
        window = self.window(c)
        window.immersive.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.settings_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.showMaximized()
        self.app.processEvents()
        window.fullscreen()
        window.open_background_settings()
        self.assertFalse(window.immersive.isVisible())
        self.assertFalse(window.isFullScreen())
        self.assertTrue(window.settings_dialog.isVisible())
        window.open_modes("scenes")
        self.assertFalse(window.immersive.isVisible())
        window.mode_library.reject()
        self.assertFalse(window.immersive.isVisible())
        self.assertFalse(window.isFullScreen())
        self.assertTrue(window.settings_dialog.isVisible())
        self.assertEqual(window.settings_dialog.section, "scenes")
        window.settings_dialog.reject()
        self.assertTrue(window.immersive.isVisible())
        self.assertTrue(window.isFullScreen())
        self.assertFalse(window.settings_dialog.isVisible())
        window.immersive.leave()
        self.assertTrue(window.isMaximized())


if __name__ == "__main__":
    unittest.main()
