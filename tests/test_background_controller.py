"""Background preferences and online artwork stay independent of Spotify playback."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QIODevice, QSettings, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow
from halo.backgrounds import BACKGROUND_DEFAULTS, BACKGROUND_PRESETS
from halo.models import Track


def picture(colour):
    image = QImage(80, 60, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class BackgroundControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".cache")
        self.addCleanup(self.temp.cleanup)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for c in self.controllers:
            c.close()
            c.audio.thread.join(1)

    def controller(self, values=None):
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        for name, value in (values or {}).items():
            settings.setValue(name, value)
        c = Controller(settings, offline=True)
        c.timer.stop()
        c.requestLyrics.disconnect(c.lyrics_worker.fetch)
        c.requestArtwork.disconnect(c.artwork_worker.fetch)
        self.controllers.append(c)
        return c

    def test_preferences_reload_and_invalid_values_fall_back_without_changing_other_controls(self):
        c = self.controller({"background_source": "removed", "background_dim": "invalid", "background_zoom": 9999})
        self.assertEqual(c.background_source, "ambient")
        self.assertEqual(c.background_dim, BACKGROUND_DEFAULTS["background_dim"])
        self.assertEqual(c.background_zoom, 150)
        for key, value in (("background_source", "artwork"), ("background_blur", 37),
                           ("background_focus_x", 23), ("background_fit", "contain")):
            c.set(key, value)
        c.settings.sync()
        new = self.controller()
        self.assertEqual((new.background_source, new.background_blur, new.background_focus_x, new.background_fit),
                         ("artwork", 37, 23, "contain"))
        self.assertEqual((new.lyric_style, new.immersive_mode, new.glow),
                         (c.lyric_style, c.immersive_mode, c.glow))

    def test_presets_keep_source_and_file_while_reset_restores_ambient(self):
        c = self.controller()
        path = Path(self.temp.name) / "wallpaper.png"
        path.write_bytes(picture("#194d88"))
        c.set_background_file(str(path), "image")
        c.apply_background_preset(BACKGROUND_PRESETS[-1][0])
        self.assertEqual(c.background_source, "image")
        self.assertEqual(Path(c.background_path), path)
        c.reset_background()
        self.assertEqual(c.background_source, "ambient")
        self.assertEqual(c.background_path, "")
        self.assertTrue(path.exists())

    def test_rejected_import_keeps_previous_wallpaper_and_reports_error(self):
        c = self.controller()
        path = Path(self.temp.name) / "wallpaper.png"
        path.write_bytes(picture("#8e4058"))
        c.set_background_file(str(path), "image")
        for bad in (Path(self.temp.name) / "missing.png", "https://example.com/image.png"):
            with self.assertRaises(ValueError):
                c.set_background_file(str(bad), "image")
            self.assertEqual((c.background_source, Path(c.background_path)), ("image", path))
            self.assertTrue(c.background_error)

    def test_online_background_uses_separate_artwork_and_rejects_late_previous_track(self):
        c = self.controller()
        requests = []
        c.requestArtwork.connect(lambda track: requests.append(track.key))
        native, online = picture("#37b38e"), picture("#8f58b8")
        first = Track("First", "Artist", "Album", 200, connected=True, artwork=native)
        c.accept_track(first)
        c.set("background_art_source", "online")
        self.assertEqual(requests, [])
        c.set("background_source", "artwork")
        self.assertEqual(requests, [first.key])
        c.accept_artwork(first.key, online)
        self.assertEqual(c.background_artwork, online)
        self.assertEqual(c.track.artwork, native)
        self.assertFalse(c.artwork_online)
        second = replace(first, title="Second")
        c.accept_track(second)
        self.assertEqual(c.background_artwork, b"")
        c.accept_artwork(first.key, online)
        self.assertEqual(c.background_artwork, b"")
        c.set("background_source", "ambient")
        c.accept_artwork(second.key, online)
        self.assertEqual(c.background_artwork, b"")
        self.assertEqual(c.track.artwork, native)

    def test_background_entry_opens_immersive_settings_without_changing_scene_or_maximized_preference(self):
        c = self.controller()
        window = MainWindow(c)
        window.draw_timer.stop()
        try:
            saved = c.immersive_mode
            window.immersive.background_button.click()
            self.app.processEvents()
            self.assertEqual(window.settings_dialog.section, "scenes")
            self.assertEqual(c.immersive_mode, saved)
            self.assertEqual(window.immersive.style_select.findData("ship_visual") >= 0, True)
            for selector in (window.style_select, window.immersive.style_select):
                self.assertEqual([selector.itemText(i) for i in range(selector.count())],
                                 ["Ship", "Fisheye", "Visual"])
                self.assertEqual(selector.findData("ship"), -1)
                self.assertEqual(selector.findData("fisheye"), -1)
        finally:
            window.settings_dialog.hide()
            window.tray.hide()
            window.immersive.media_background.close()
            for widget in (window.immersive, window.overlay, *window.edges, window):
                widget.hide()
                widget.deleteLater()
            self.app.processEvents()

    def test_closing_background_settings_returns_to_immersive_in_the_same_app_window(self):
        c = self.controller()
        window = MainWindow(c)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.draw_timer.stop()
        try:
            window.show()
            window.fullscreen()
            self.app.processEvents()
            window.open_background_settings()
            self.app.processEvents()
            self.assertTrue(window.settings_dialog.isVisible())
            self.assertFalse(window.immersive.isVisible())
            self.assertFalse(window.isFullScreen())
            with patch.object(window, "activateWindow") as activated:
                window.settings_dialog.close()
                activated.assert_called_once()
            self.assertTrue(window.isFullScreen())
            self.assertTrue(window.immersive.isVisible())
            self.assertFalse(window.settings_dialog.isVisible())
            self.assertIs(window.immersive.window(), window)
            self.assertFalse(window._return_to_immersive_settings)
        finally:
            window.settings_dialog.hide()
            window.tray.hide()
            window.immersive.media_background.close()
            for widget in (window.immersive, window.overlay, *window.edges, window):
                widget.hide()
                widget.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
