"""Leaving Immersive puts the window back where it was, not lifted by the old title bar's height."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QRect, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow


class ImmersiveExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-exit-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.c.set_demo(True)
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
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
        QTest.qWait(30)
        self.app.processEvents()

    def leave_and_record(self, maximized):
        window = self.window
        window.fullscreen()
        self.settle()
        self.assertTrue(window.isFullScreen())
        # How the window was before the room (fullscreen() reads it from the window, so set it after).
        window._return_maximized = maximized
        window._workspace_geometry = QRect(200, 150, 1000, 680)
        calls = []
        strip, place, maximize = window._title_strip, window.setGeometry, window.showMaximized
        with patch.object(window, "_title_strip", side_effect=lambda on: (calls.append(("strip", on)), strip(on))), \
             patch.object(window, "setGeometry", side_effect=lambda *a: (calls.append(("place",)), place(*a))), \
             patch.object(window, "showMaximized", side_effect=lambda: (calls.append(("maximize",)), maximize())):
            window._show_workspace()
        return calls

    def test_the_strip_returns_before_a_normal_window_is_placed(self):
        calls = self.leave_and_record(maximized=False)
        self.assertIn(("strip", True), calls)
        self.assertIn(("place",), calls)
        self.assertLess(calls.index(("strip", True)), calls.index(("place",)))

    def test_the_strip_returns_before_the_window_is_maximised(self):
        calls = self.leave_and_record(maximized=True)
        self.assertIn(("maximize",), calls)
        self.assertLess(calls.index(("strip", True)), calls.index(("maximize",)))

    def test_a_normal_window_is_placed_again_once_its_new_frame_is_known(self):
        window = self.window
        window.showNormal()
        self.settle()
        target = QRect(220, 160, 1000, 680)
        window.setGeometry(QRect(218, 158, 1004, 680))  # a few pixels off, as Windows leaves it
        window._settle_workspace_geometry(target)
        self.assertEqual(window.geometry(), target)
        # A maximised or exiting window is left alone.
        with patch.object(window, "setGeometry") as place:
            window.exiting = True
            window._settle_workspace_geometry(QRect(0, 0, 900, 600))
            place.assert_not_called()


if __name__ == "__main__":
    unittest.main()
