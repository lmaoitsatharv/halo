"""Real offline Controller checks for settings, playback motion and native overlays."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.app import Controller
from halo.frontend import ModeTile
from halo.glow import HALO_MODES, paint_edge_glow
from halo.immersive import Immersive
from halo.models import Track
from halo.widgets import EdgeOverlay, FloatingLyrics


class MotionSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-motion-settings-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "settings.ini")
        self.now = 1000.
        # Replace only app.py's clock reference; audio/worker clocks stay real.
        clock = SimpleNamespace(monotonic=lambda: self.now)
        self.clock_patch = patch("halo.app.time", clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for controller in reversed(self.controllers):
            controller.close()
            controller.audio.thread.join(timeout=1.)
            self.assertFalse(controller.lyrics_thread.isRunning())
            self.assertFalse(controller.audio.thread.is_alive())
        self.controllers.clear()

    def controller(self, values=None):
        settings = QSettings(self.path, QSettings.Format.IniFormat)
        for key, value in (values or {}).items():
            settings.setValue(key, value)
        settings.sync()
        controller = Controller(settings, offline=True)
        controller.timer.stop()
        self.controllers.append(controller)
        return controller

    def advance(self, controller, seconds):
        self.now += seconds
        controller.tick()

    def test_fresh_and_invalid_saved_modes_initialise_a_renderable_controller(self):
        controller = self.controller({"halo_mode": "old-mode", "lyric_style": "removed-style",
                                      "immersive_mode": "missing-scene"})
        self.assertEqual(controller.halo_mode, "orbit")
        self.assertEqual(controller.lyric_style, "fisheye_visual")
        self.assertEqual(controller.immersive_mode, "studio")
        self.assertEqual(controller.motion_speed, 45)
        self.assertFalse(controller.reduced_motion)
        self.assertEqual(controller.motion_time, 0.)
        image = QImage(640, 420, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            paint_edge_glow(painter, 640, 420, controller)
        finally:
            painter.end()
        self.assertGreater(image.pixelColor(320, 8).alpha(), 0)
        self.assertEqual(image.pixelColor(320, 210).alpha(), 0)

    def test_selected_modes_and_motion_preferences_survive_settings_reload(self):
        controller = self.controller()
        for key, value in (("halo_mode", "prism"), ("lyric_style", "ship"),
                           ("immersive_mode", "cinema"), ("motion_speed", 73),
                           ("reduced_motion", True)):
            controller.set(key, value)
        controller.settings.sync()
        # A new actual Controller reads persisted values, rather than copying
        # the old object's fields or assuming the writer's setting format.
        restored = self.controller()
        self.assertEqual(restored.halo_mode, "prism")
        self.assertEqual(restored.lyric_style, "ship")
        self.assertEqual(restored.immersive_mode, "cinema")
        self.assertEqual(restored.motion_speed, 73)
        self.assertTrue(restored.reduced_motion)
        self.assertEqual(restored.motion_time, 0.)

    def test_out_of_range_saved_speed_is_clamped(self):
        self.assertEqual(self.controller({"motion_speed": -20}).motion_speed, 0)
        self.assertEqual(self.controller({"motion_speed": 120}).motion_speed, 100)

    def test_play_pause_resume_freezes_motion_without_accumulating_paused_time(self):
        controller = self.controller()
        controller.set_demo(True)
        self.advance(controller, .016)
        initial = controller.motion_time
        self.assertGreater(initial, 0.)
        controller.transport("toggle")
        for elapsed in (.016, 10., 60.):
            self.advance(controller, elapsed)
            self.assertEqual(controller.motion_time, initial)
        controller.transport("toggle")
        self.advance(controller, .016)
        self.assertAlmostEqual(controller.motion_time - initial, .016)

    def test_reduced_motion_freezes_and_resumes_without_a_time_jump(self):
        controller = self.controller()
        controller.set_demo(True)
        self.advance(controller, .016)
        initial = controller.motion_time
        controller.set("reduced_motion", True)
        self.advance(controller, 40.)
        self.assertEqual(controller.motion_time, initial)
        controller.set("reduced_motion", False)
        self.advance(controller, .016)
        self.assertAlmostEqual(controller.motion_time - initial, .016)

    def test_disconnected_playback_does_not_animate_or_catch_up_on_reconnection(self):
        controller = self.controller()
        controller.track = Track(playing=True, connected=False, observed_at=self.now)
        self.advance(controller, 30.)
        self.assertEqual(controller.motion_time, 0.)
        controller.track.connected = True
        self.advance(controller, .016)
        self.assertAlmostEqual(controller.motion_time, .016)

    def test_delayed_tick_cannot_fast_forward_the_visual_animation(self):
        controller = self.controller()
        controller.set_demo(True)
        self.advance(controller, .016)
        before = controller.motion_time
        self.advance(controller, 600.)
        self.assertGreater(controller.motion_time, before)
        self.assertLessEqual(controller.motion_time - before, .11)
        before = controller.motion_time
        self.advance(controller, .016)
        self.assertAlmostEqual(controller.motion_time - before, .016)

    def test_native_surfaces_share_the_controller_and_keep_click_through_flags(self):
        controller = self.controller()
        screen = self.app.primaryScreen()
        edge = EdgeOverlay(controller, screen)
        floating = FloatingLyrics(controller)
        immersive = Immersive(controller)
        preview = ModeTile(controller, "halo_mode", HALO_MODES[1])
        widgets = (edge, floating, immersive, preview)
        try:
            for widget in widgets:
                self.assertFalse(widget.isVisible())
            self.assertIs(edge.controller, controller)
            self.assertIs(floating.controller, controller)
            self.assertIs(immersive.controller, controller)
            self.assertIs(immersive.canvas.controller, controller)
            self.assertIs(preview.c, controller)
            for widget in (edge, floating):
                self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowTransparentForInput)
                self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
                self.assertTrue(widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        finally:
            for widget in widgets:
                widget.close()
                widget.deleteLater()
            self.app.processEvents()

    @unittest.skipUnless(sys.platform == "win32", "Requires native Windows handles")
    def test_immersive_allows_taskbar_reveal_while_retaining_fullscreen_and_shortcuts(self):
        if self.app.platformName() != "windows":
            self.skipTest("Requires Qt's native Windows platform")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_property = user32.GetPropW
        get_property.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
        get_property.restype = wintypes.HANDLE
        controller = self.controller()
        controller.set_demo(True)
        immersive = Immersive(controller)
        immersive.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        exited = []
        immersive.exited.connect(lambda: exited.append(True))
        try:
            self.assertEqual(get_property(int(immersive.winId()), "NonRudeHWND"), 1)
            immersive.showFullScreen()
            self.app.setActiveWindow(immersive)
            self.app.processEvents()
            self.assertTrue(immersive.isFullScreen())
            self.assertEqual(get_property(int(immersive.winId()), "NonRudeHWND"), 1)
            playing = controller.track.playing
            QTest.keyClick(immersive, Qt.Key.Key_Space)
            self.assertEqual(controller.track.playing, not playing)
            QTest.keyClick(immersive, Qt.Key.Key_Escape)
            self.assertFalse(immersive.isVisible())
            self.assertEqual(exited, [True])
            immersive.destroy()
            self.assertEqual(get_property(int(immersive.winId()), "NonRudeHWND"), 1)
        finally:
            immersive.hide()
            immersive.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
