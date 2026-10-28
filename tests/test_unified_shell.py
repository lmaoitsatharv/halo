"""Single-window navigation preserves music, previews and desktop behavior."""
from pathlib import Path
import tempfile
import unittest
import warnings

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow


class UnifiedShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-unified-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.c.set_demo(True)
        self.c.tick()
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
        # The responsive settings preview needs the default workspace size,
        # whatever the host screen's size is.
        self.window.resize(1280, 800)
        self.settle()

    def tearDown(self):
        self.window.exiting = True
        self.window.hide()
        self.window.draw_timer.stop()
        self.window.tray.hide()
        self.window.immersive.media_background.close()
        self.c.close()
        self.c.audio.thread.join(1)
        for widget in (self.window.overlay, *self.window.edges, self.window):
            widget.hide()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def settle(self):
        self.app.processEvents()
        QTest.qWait(20)
        self.app.processEvents()

    def test_settings_modes_and_immersive_share_one_native_window(self):
        self.assertEqual(self.window.windowTitle(), "Halo · Your listening space")
        flags = self.window.windowFlags()
        self.assertFalse(flags & Qt.WindowType.FramelessWindowHint)
        for flag in (Qt.WindowType.WindowTitleHint, Qt.WindowType.WindowSystemMenuHint,
                     Qt.WindowType.WindowMinimizeButtonHint,
                     Qt.WindowType.WindowMaximizeButtonHint,
                     Qt.WindowType.WindowCloseButtonHint):
            self.assertTrue(flags & flag, flag)
        self.window.open_settings()
        self.settle()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.settings_dialog)
        self.window.open_modes()
        self.settle()
        self.assertIs(self.window.page_stack.currentWidget(), self.window.mode_library)
        for page in (self.window.settings_dialog, self.window.mode_library, self.window.immersive):
            self.assertFalse(page.isWindow())
            self.assertIs(page.window(), self.window)
        self.window.fullscreen()
        self.settle()
        self.assertIs(self.window.app_stack.currentWidget(), self.window.immersive)
        self.assertTrue(self.window.isFullScreen())
        self.assertFalse(self.window.settings_dialog.isVisible())
        self.assertFalse(self.window.mode_library.isVisible())

    def test_persistent_player_controls_the_same_song_on_every_workspace_page(self):
        lyrics, generation = self.c.lyrics, self.c.generation
        for page in ("settings", "modes", "listening"):
            if page == "settings":
                self.window.open_settings()
            elif page == "modes":
                self.window.open_modes()
            else:
                self.window.navigate(page)
            self.settle()
            self.assertTrue(self.window.player.isVisible())
            before = self.c.track.playing
            QTest.mouseClick(self.window.play, Qt.MouseButton.LeftButton)
            self.assertEqual(self.c.track.playing, not before)
            self.window.progress.setSliderDown(True)
            self.window.progress.setValue(500)
            self.window.progress.setSliderDown(False)
            self.c.tick()
            self.assertAlmostEqual(self.c.position, 30., delta=.1)
            self.assertEqual(self.c.track.title, "In the light we made")
            self.assertIs(self.c.lyrics, lyrics)
            self.assertEqual(self.c.generation, generation)

    def test_hidden_and_minimized_pages_suspend_their_live_previews(self):
        self.window.open_settings()
        self.settle()
        self.assertTrue(self.window.settings_dialog.preview.isVisible())
        settings_timer = self.window.settings_dialog.preview.timer
        self.assertTrue(settings_timer.isActive())

        self.window.open_modes()
        self.settle()
        self.assertFalse(settings_timer.isActive())
        modes_timer = self.window.mode_library.timer
        self.assertTrue(modes_timer.isActive())
        self.window.showMinimized()
        self.settle()
        self.assertFalse(modes_timer.isActive())
        self.window.reopen()
        self.settle()
        self.assertTrue(modes_timer.isActive())
        self.window.navigate("listening")
        self.settle()
        self.assertFalse(modes_timer.isActive())
        self.window.open_settings()
        self.settle()
        self.window.showMinimized()
        self.settle()
        self.assertFalse(settings_timer.isActive())
        self.window.reopen()
        self.settle()
        self.assertTrue(settings_timer.isActive())

    def test_timeline_mouse_drag_and_keyboard_seek_the_playback_backend(self):
        self.c.transport("toggle")
        self.window.open_modes()
        self.settle()
        slider = self.window.progress

        def point(fraction):
            return QPoint(round(6 + (slider.width() - 12) * fraction), slider.height() // 2)

        QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=point(.75))
        self.c.tick()
        self.assertAlmostEqual(self.c.position, 45., delta=.25)
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=point(.2))
        QTest.mouseMove(slider, point(.4))
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=point(.4))
        self.c.tick()
        self.assertFalse(slider.isSliderDown())
        self.assertAlmostEqual(self.c.position, 24., delta=.25)
        QTest.keyClick(slider, Qt.Key.Key_Home)
        self.c.tick()
        self.assertEqual(self.c.position, 0.)
        QTest.keyClick(slider, Qt.Key.Key_PageUp)
        self.c.tick()
        self.assertGreater(self.c.position, 0.)
        self.assertAlmostEqual(self.c.position, slider.value() / 1000 * self.c.track.duration)

    def test_nested_browsing_restores_settings_then_the_original_fullscreen_room(self):
        self.window.resize(1100, 720)
        self.settle()
        original_geometry = self.window.geometry()
        original_scene = self.c.immersive_mode
        self.window.fullscreen()
        self.settle()
        self.window.open_background_settings()
        self.settle()
        self.assertFalse(self.window.isFullScreen())
        self.assertFalse(self.window.immersive.isVisible())
        self.assertEqual(self.window.settings_dialog.section, "scenes")
        self.window.open_modes("scenes")
        self.settle()
        self.window.mode_library.reject()
        self.settle()
        self.assertEqual(self.window.current_page, "settings")
        self.assertEqual(self.window.settings_dialog.section, "scenes")
        self.assertFalse(self.window.immersive.isVisible())
        self.window.settings_dialog.reject()
        self.settle()
        self.assertTrue(self.window.isFullScreen())
        self.assertTrue(self.window.immersive.isVisible())
        self.assertEqual(self.c.immersive_mode, original_scene)
        self.window.immersive.leave()
        self.settle()
        self.assertFalse(self.window.isFullScreen())
        self.assertEqual(self.window.geometry(), original_geometry)
        self.assertEqual(self.window.current_page, "listening")

    def test_minimizing_modes_keeps_floating_lyrics_available_and_restoring_hides_them(self):
        self.c.set("floating", True)
        self.window.open_modes()
        self.settle()
        self.window.showMinimized()
        self.settle()
        self.window.draw()
        self.assertTrue(self.window.overlay.isVisible())
        self.window.reopen()
        self.settle()
        self.window.draw()
        self.assertFalse(self.window.overlay.isVisible())

    def test_position_controls_are_an_in_app_sheet_and_dismiss_desktop_preview(self):
        self.window.open_position_settings()
        self.settle()
        dialog = self.window.position_dialog
        self.assertTrue(self.window.sheet.isVisible())
        self.assertFalse(dialog.isWindow())
        self.assertIs(dialog.window(), self.window)
        dialog.set_position(50, 50)
        dialog.desktop_preview.setChecked(True)
        self.window.draw()
        self.assertTrue(self.window.overlay.isVisible())
        self.window.sheet.dismiss()
        self.settle()
        self.window.draw()
        self.assertFalse(dialog.desktop_preview.isChecked())
        self.assertFalse(self.window.sheet.isVisible())
        self.assertFalse(self.window.overlay.isVisible())
        self.assertEqual((self.c.floating_x, self.c.floating_y), (50, 50))

    def test_embedded_room_restores_its_cursor_when_the_app_minimizes(self):
        self.window.fullscreen()
        self.settle()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(self.window)
        self.window.immersive._set_cursor_hidden(True)
        self.assertTrue(self.window.immersive._cursor_hidden)
        self.window.showMinimized()
        self.settle()
        self.assertFalse(self.window.immersive._cursor_hidden)
        self.assertFalse(self.window.immersive.idle.isActive())
        self.window.reopen()
        self.settle()
        self.assertTrue(self.window.isFullScreen())
        self.assertTrue(self.window.immersive.idle.isActive())

    def test_immersive_space_and_escape_shortcuts_control_music_and_restore_navigation(self):
        self.window.fullscreen()
        self.settle()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(self.window)
        self.window.immersive.setFocus(Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        self.assertTrue(self.c.track.playing)
        QTest.keyClick(self.window.immersive, Qt.Key.Key_Space)
        self.assertFalse(self.c.track.playing)
        QTest.keyClick(self.window.immersive, Qt.Key.Key_Space)
        self.assertTrue(self.c.track.playing)
        QTest.keyClick(self.window.immersive, Qt.Key.Key_Escape)
        self.settle()
        self.assertFalse(self.window.isFullScreen())
        self.assertFalse(self.window.immersive.isVisible())
        self.assertEqual(self.window.current_page, "listening")
        self.window.open_modes()
        self.settle()
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.settle()
        self.assertEqual(self.window.current_page, "listening")
        self.assertFalse(self.window.mode_library.isVisible())


if __name__ == "__main__":
    unittest.main()
