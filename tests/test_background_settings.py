"""Native immersive background controls and isolated, bounded previews."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QSettings, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from halo.app import Controller, MainWindow
from halo.backgrounds import BackgroundRenderer, BACKGROUND_PRESETS


class BackgroundSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-background-studio-", dir=Path(__file__).resolve().parents[1] / ".cache")
        self.ini = str(Path(self.temp.name) / "settings.ini")
        settings = QSettings(self.ini, QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.studio = self.window.settings_dialog
        self.studio.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.show()
        # The responsive live preview needs the default workspace size,
        # whatever the host screen's size is.
        self.window.resize(1280, 800)
        self.app.processEvents()
        self.image = Path(self.temp.name) / "Quiet evening.png"
        image = QImage(500, 340, QImage.Format.Format_RGB32)
        image.fill(QColor("#ea725c"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 250, 170, QColor("#1533c9"))
        painter.fillRect(250, 170, 250, 170, QColor("#f9d66b"))
        painter.end()
        self.assertTrue(image.save(str(self.image)))

    def tearDown(self):
        self.studio.hide()
        self.studio.preview.scene.background.close()
        self.window.hide()
        self.window.draw_timer.stop()
        self.window.tray.hide()
        for widget in [self.window.immersive, self.window.overlay, *self.window.edges]:
            widget.hide()
            widget.deleteLater()
        self.c.close()
        self.c.audio.thread.join(1)
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def open_backgrounds(self):
        self.studio.open_studio("scenes")
        self.app.processEvents()
        self.assertTrue(self.studio.preview.isVisible())
        self.studio.preview.transition.finish()

    def test_background_entry_opens_immersive_and_default_entry_remains_general(self):
        self.open_backgrounds()
        self.assertEqual(self.studio.section, "scenes")
        self.assertEqual(self.studio.preview.scene.section, "scenes")
        self.assertTrue(self.studio.background_sources["ambient"].isChecked())
        self.assertFalse(self.studio.background_sliders["background_blur"].isEnabled())
        self.assertFalse(self.studio.background_file.isVisible())
        self.studio.close()
        self.studio.open_studio()
        self.assertEqual(self.studio.section, "general")

    def test_source_choices_enable_relevant_controls_and_readable_status(self):
        self.open_backgrounds()
        QTest.mouseClick(self.studio.background_sources["image"], Qt.MouseButton.LeftButton)
        self.assertEqual(self.c.background_source, "image")
        self.assertTrue(self.studio.background_file.isVisible())
        self.assertTrue(self.studio.background_sliders["background_blur"].isEnabled())
        self.assertFalse(self.studio.background_art_source.isEnabled())
        self.assertFalse(self.studio.background_playback.isEnabled())
        self.assertIn("Choose an image", self.studio.background_status.text())
        QTest.mouseClick(self.studio.background_sources["artwork"], Qt.MouseButton.LeftButton)
        self.assertTrue(self.studio.background_art_source.isEnabled())
        self.assertTrue(self.studio.background_privacy.isVisible())
        self.assertFalse(self.studio.background_file.isVisible())
        self.assertIn("MusicBrainz", self.studio.background_privacy.text())

    def test_direct_background_entry_reveals_source_controls_at_compact_size(self):
        self.studio.open_backgrounds()
        self.studio.resize(960, 600)
        self.app.processEvents()
        page = self.studio.pages.currentWidget()
        button = self.studio.background_sources["ambient"]
        self.assertEqual(self.studio.section, "scenes")
        self.assertGreater(page.verticalScrollBar().value(), 0)
        self.assertTrue(page.viewport().rect().contains(button.mapTo(page.viewport(), button.rect().center())))

    def test_online_background_choice_is_separate_from_missing_cover_preference(self):
        self.c.set("artwork_online", False)
        self.open_backgrounds()
        self.c.set("background_source", "artwork")
        choice = self.studio.background_art_source
        choice.setCurrentIndex(choice.findData("online"))
        self.assertEqual(self.c.background_art_source, "online")
        self.assertFalse(self.c.artwork_online)
        self.assertFalse(self.studio.switches["artwork_online"].isChecked())

    def test_file_picker_preserves_on_cancel_and_applies_filename_without_path(self):
        self.open_backgrounds()
        self.c.set("background_source", "image")
        with patch("halo.settings_ui.QFileDialog.getOpenFileName", return_value=("", "")):
            self.studio.choose_background_file()
        self.assertEqual(self.c.background_path, "")
        with patch("halo.settings_ui.QFileDialog.getOpenFileName", return_value=(str(self.image), "")):
            self.studio.choose_background_file()
        self.assertEqual(self.c.background_path, str(self.image))
        self.assertEqual(self.studio.background_file_label.full_text, self.image.name)
        self.assertEqual(self.studio.background_file_label.toolTip(), self.image.name)
        self.assertNotIn(str(self.image.parent), self.studio.background_status.text())

    def test_background_values_and_presets_are_saved_for_reopening(self):
        self.open_backgrounds()
        self.c.set_background_file(str(self.image), "image")
        self.studio.background_sliders["background_blur"].setValue(35)
        self.studio.background_sliders["background_dim"].setValue(67)
        self.studio.background_sliders["background_focus_x"].setValue(24)
        control = self.studio.background_controls["background_fit"]
        control.setCurrentIndex(control.findData("contain"))
        self.c.settings.sync()
        saved = QSettings(self.ini, QSettings.Format.IniFormat)
        for field, expected in (("background_blur", 35), ("background_dim", 67), ("background_focus_x", 24)):
            self.assertEqual(saved.value(field, type=int), expected)
        self.assertEqual(saved.value("background_source"), "image")
        self.assertEqual(saved.value("background_fit"), "contain")
        self.studio.close()
        self.open_backgrounds()
        self.assertEqual(self.studio.background_sliders["background_blur"].value(), 35)
        self.assertEqual(control.currentData(), "contain")
        for key, _, values in BACKGROUND_PRESETS:
            self.studio.background_presets[key].click()
            for field, expected in values.items():
                self.assertEqual(getattr(self.c, field), expected)
            self.assertEqual(self.c.background_path, str(self.image))
            self.assertEqual(self.c.background_source, "image")

    def test_invalid_file_is_reported_inline_and_preserves_previous_background(self):
        self.open_backgrounds()
        self.c.set_background_file(str(self.image), "image")
        with patch("halo.settings_ui.QFileDialog.getOpenFileName", return_value=(str(self.image.parent / "missing.png"), "")):
            self.studio.choose_background_file()
        self.assertEqual(self.c.background_path, str(self.image))
        self.assertEqual(self.studio.background_status.text(), self.c.background_error)
        self.assertTrue(self.c.background_error)

    def test_live_preview_uses_real_renderer_without_changing_other_sections(self):
        self.c.set("reduced_motion", True)
        self.studio.open_studio()
        self.app.processEvents()
        screen = self.studio.preview.scene
        self.assertIsInstance(screen.background, BackgroundRenderer)
        before = screen.grab().toImage()
        self.c.set_background_file(str(self.image), "image")
        self.assertEqual(before, screen.grab().toImage())
        self.open_backgrounds()
        image_preview = screen.grab().toImage()
        self.assertTrue(screen.background.has_media)
        self.c.set("background_dim", 85)
        self.assertNotEqual(image_preview, screen.grab().toImage())
        self.studio.select(0, animate=False)
        self.assertEqual(before, screen.grab().toImage())

    def test_preview_releases_renderer_when_hidden_or_leaving_immersive_settings(self):
        self.open_backgrounds()
        self.c.set_background_file(str(self.image), "image")
        renderer = self.studio.preview.scene.background
        with patch.object(renderer, "close", wraps=renderer.close) as close:
            self.studio.select(2, animate=False)
            self.assertTrue(close.called)
        self.studio.select(3, animate=False)
        self.assertTrue(renderer.has_media)
        with patch.object(renderer, "close", wraps=renderer.close) as close:
            self.studio.close()
            self.app.processEvents()
            self.assertTrue(close.called)
        self.assertFalse(self.studio.preview.timer.isActive())

    def test_reduced_motion_disables_camera_and_video_playback_controls(self):
        self.open_backgrounds()
        self.c.set("background_source", "video")
        self.assertTrue(self.studio.background_playback.isEnabled())
        self.c.set("reduced_motion", True)
        for field in ("background_motion", "background_speed", "background_playback"):
            self.assertFalse(self.studio.background_controls[field].isEnabled())
        self.assertIn("Reduce motion is on", self.studio.background_motion_note.text())
        self.c.set("reduced_motion", False)
        self.assertTrue(self.studio.background_playback.isEnabled())

    def test_full_image_framing_disables_camera_controls_but_keeps_treatment(self):
        self.open_backgrounds()
        self.c.set_background_file(str(self.image), "image")
        self.c.set("background_fit", "contain")
        for field in ("background_zoom", "background_focus_x", "background_focus_y", "background_motion", "background_speed"):
            self.assertFalse(self.studio.background_controls[field].isEnabled())
        for field in ("background_blur", "background_dim", "background_saturation"):
            self.assertTrue(self.studio.background_controls[field].isEnabled())
        self.assertIn("Full-image framing", self.studio.background_motion_note.text())
        self.c.set("background_fit", "cover")
        self.assertTrue(self.studio.background_controls["background_zoom"].isEnabled())
        self.assertTrue(self.studio.background_controls["background_motion"].isEnabled())

    def test_compact_layout_scrolls_and_five_lyric_modes_remain_accessible(self):
        self.open_backgrounds()
        self.studio.resize(960, 600)
        self.app.processEvents()
        page = self.studio.pages.currentWidget()
        self.assertIsInstance(page, QScrollArea)
        self.assertGreater(page.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(page.widget().width(), page.viewport().width())
        self.studio.background_disclosure.click()
        self.app.processEvents()
        self.assertTrue(self.studio.background_composition.isVisible())
        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
        self.assertTrue(page.viewport().rect().contains(self.studio.background_motion_note.mapTo(page.viewport(), self.studio.background_motion_note.rect().center())))
        self.studio.select(2, animate=False)
        styles = [tile for tile in self.studio.mode_tiles if tile.setting == "lyric_style"]
        self.assertEqual(len(styles), 3)
        self.assertIn("ship_visual", {tile.mode_id for tile in styles})
        for tile in styles:
            self.assertGreaterEqual(tile.width(), 130)
            self.assertFalse(tile.grab().isNull())


if __name__ == "__main__":
    unittest.main()
