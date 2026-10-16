"""Native shell-policy checks without changing the user's taskbar preferences."""
import ctypes
from ctypes import wintypes
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from halo.taskbar import allow_taskbar_reveal
from halo.widgets import EdgeOverlay, FloatingLyrics


class TaskbarPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_handle_and_other_platforms_are_safe(self):
        self.assertFalse(allow_taskbar_reveal(0))
        with patch("halo.taskbar.sys", SimpleNamespace(platform="linux")):
            self.assertFalse(allow_taskbar_reveal(123))

    @unittest.skipUnless(sys.platform == "win32", "Requires native Windows handles")
    def test_desktop_overlays_opt_out_before_show_and_after_handle_recreation(self):
        if self.app.platformName() != "windows":
            self.skipTest("Requires Qt's native Windows platform")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_property = user32.GetPropW
        get_property.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
        get_property.restype = wintypes.HANDLE
        controller = SimpleNamespace()
        screen = self.app.primaryScreen()
        edge = EdgeOverlay(controller, screen)
        floating = FloatingLyrics(controller)
        regular = QWidget()
        widgets = (edge, floating, regular)
        try:
            self.assertFalse(get_property(int(regular.winId()), "NonRudeHWND"))
            for overlay in (edge, floating):
                with self.subTest(overlay=type(overlay).__name__):
                    self.assertFalse(overlay.isVisible())
                    self.assertEqual(get_property(int(overlay.winId()), "NonRudeHWND"), 1)
                    self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput)
                    self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
                    overlay.destroy()
                    self.assertEqual(get_property(int(overlay.winId()), "NonRudeHWND"), 1)
                    self.assertFalse(overlay.isVisible())
            # Keep the full-monitor rendering extent, including scaled and
            # offset displays. No strip is removed from the visible halo.
            self.assertEqual(edge.geometry(), screen.geometry())
        finally:
            for widget in widgets:
                widget.close()
                widget.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
