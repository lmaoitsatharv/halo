"""The window name lives under the halo wordmark, and Modes can leave out what is already yours."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget

from halo import titlebar
from halo.app import Controller, MainWindow
from halo.mode_catalog import all_modes
from halo.mode_library import ModeLibrary, _font

from tests.test_mode_library_ui import LibraryController


class EmptyTitleBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-header-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        settings.setValue("appearance", "light")
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()

    def tearDown(self):
        self.c.close()
        self.c.audio.thread.join(1)
        self.temp.cleanup()

    def make_window(self):
        window = MainWindow(self.c)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.draw_timer.stop()
        return window

    def close_window(self, window):
        window.exiting = True
        window.hide()
        window.tray.hide()
        window.immersive.media_background.close()
        for widget in (window.overlay, *window.edges, window):
            widget.hide()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    @unittest.skipUnless(titlebar.TITLE_STRIP, "Windows title strip only")
    def test_the_wall_runs_up_under_the_window_keys_with_no_title_drawn(self):
        window = self.make_window()
        window.show()
        window.resize(1280, 800)
        QTest.qWait(20)
        try:
            self.assertEqual(window.windowTitle(), "Halo")
            for flags in (window.windowFlags(), window.windowHandle().flags()):
                self.assertTrue(flags & titlebar.EXPANDED)
                self.assertTrue(flags & Qt.WindowType.NoTitleBarBackgroundHint)
                # Without the title hint Qt draws only minimise, maximise and close: no icon, no text.
                self.assertFalse(flags & Qt.WindowType.WindowTitleHint)
                self.assertFalse(flags & Qt.WindowType.FramelessWindowHint)
                for key in (Qt.WindowType.WindowMinimizeButtonHint, Qt.WindowType.WindowMaximizeButtonHint,
                            Qt.WindowType.WindowCloseButtonHint, Qt.WindowType.WindowSystemMenuHint):
                    self.assertTrue(flags & key, key)
            strip = window.title_strip_height()
            self.assertGreaterEqual(strip, 24)
            self.assertLessEqual(strip, 48)
            # The wall itself starts at the top edge of the window.
            self.assertEqual(window.shell.mapTo(window, QPoint(0, 0)).y(), 0)
            # Every header control sits below the strip, so none hides under the keys.
            for widget in (window.mark, window.tagline, window.place_nav, window.settings_button):
                self.assertGreaterEqual(widget.mapTo(window, QPoint(0, 0)).y(), strip, widget)
        finally:
            self.close_window(window)

    @unittest.skipUnless(titlebar.TITLE_STRIP, "Windows title strip only")
    def test_nothing_in_the_strip_takes_a_press_so_it_drags_the_window(self):
        window = self.make_window()
        window.show()
        window.resize(1280, 800)
        QTest.qWait(20)
        try:
            strip = window.title_strip_height()
            for x in range(10, window.width() - 160, 60):
                for y in (2, strip // 2, strip - 2):
                    point = QPoint(x, y)
                    target = window.childAt(point) or window
                    local = target.mapFrom(window, point)
                    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(local), QPointF(window.mapToGlobal(point)),
                                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                        Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(target, press)
                    self.assertFalse(press.isAccepted(), (x, y, target))
        finally:
            self.close_window(window)

    @unittest.skipUnless(titlebar.TITLE_STRIP, "Windows title strip only")
    def test_the_fullscreen_room_has_no_strip_and_returning_brings_it_back(self):
        window = self.make_window()
        window.show()
        window.resize(1280, 800)
        QTest.qWait(20)
        try:
            window.fullscreen()
            QTest.qWait(40)
            for flags in (window.windowFlags(), window.windowHandle().flags()):
                self.assertFalse(flags & titlebar.EXPANDED)
            self.assertEqual(window.title_strip_height(), 0)
            window.immersive.leave()
            QTest.qWait(40)
            self.assertFalse(window.isFullScreen())
            for flags in (window.windowFlags(), window.windowHandle().flags()):
                self.assertTrue(flags & titlebar.EXPANDED)
                self.assertFalse(flags & Qt.WindowType.WindowTitleHint)
            self.assertGreaterEqual(window.settings_button.mapTo(window, QPoint(0, 0)).y(), window.title_strip_height())
        finally:
            self.close_window(window)

    def test_the_listening_wall_has_no_lyric_style_picker(self):
        window = self.make_window()
        window.show()
        window.resize(1280, 800)
        QTest.qWait(20)
        try:
            page = window.listening_page
            self.assertEqual([combo for combo in page.findChildren(QComboBox) if combo.isVisible()], [])
            self.assertFalse(hasattr(window, "style_select"))
            # The lyric tools keep their two keys, aligned with the frame's foot.
            self.assertTrue(window.retry_button.isVisible())
        finally:
            self.close_window(window)

    def test_your_listening_space_sits_under_the_halo_wordmark(self):
        window = self.make_window()
        window.show()
        window.resize(1280, 800)
        QTest.qWait(20)
        try:
            tagline = window.tagline
            self.assertEqual(tagline.text(), "Your listening space")
            self.assertTrue(tagline.isVisible())
            wordmark = next(label for label in window.shell.findChildren(QLabel) if label.text() == "halo")
            word_at = wordmark.mapTo(window, QPoint(0, 0))
            line_at = tagline.mapTo(window, QPoint(0, 0))
            self.assertGreaterEqual(line_at.y(), word_at.y() + wordmark.height() - 4)
            self.assertLessEqual(abs(line_at.x() - word_at.x()), 2)
            # It belongs to the header, beside the mark, not to any page.
            self.assertLess(line_at.y() + tagline.height(), window.page_stack.mapTo(window, QPoint(0, 0)).y() + 4)
            self.assertGreater(line_at.x(), window.mark.mapTo(window, QPoint(0, 0)).x() + window.mark.width())
        finally:
            self.close_window(window)


def _message(hwnd, message, wparam=0, lparam=0):
    msg = wintypes.MSG()
    msg.hWnd, msg.message, msg.wParam, msg.lParam = hwnd, message, wparam, lparam
    return msg


class _FakeUser32:
    """Records what the caption guard asks Windows to do, for the visible-window path."""
    def __init__(self, style):
        self.style, self.calls = style, []

    def GetWindowLongPtrW(self, hwnd, index):
        return self.style

    def SetWindowLongPtrW(self, hwnd, index, value):
        self.calls.append(("style", value))
        self.style = value
        return 0

    def DefWindowProcW(self, hwnd, message, wparam, lparam):
        self.calls.append(("default", message, self.style))
        return 1


@unittest.skipUnless(titlebar.TITLE_STRIP, "Windows title strip only")
class OldCaptionGuardTests(unittest.TestCase):
    """Windows' fallback caption (the old light title bar) must never be painted over the wall."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = QWidget()
        self.widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.hwnd = int(self.widget.winId())

    def tearDown(self):
        self.widget.deleteLater()
        titlebar._api.clear()

    def handle(self, *args):
        msg = _message(self.hwnd, *args)
        return titlebar.handle_message(ctypes.addressof(msg))

    def test_windows_own_key_tracking_never_starts(self):
        for hit in (titlebar.HTMINBUTTON, titlebar.HTMAXBUTTON, titlebar.HTCLOSE, titlebar.HTSIZE):
            for message in (titlebar.WM_NCLBUTTONDOWN, titlebar.WM_NCLBUTTONUP, titlebar.WM_NCLBUTTONDBLCLK):
                self.assertEqual(self.handle(message, hit), (True, 0), (message, hit))
        # Dragging and double-clicking the strip itself stay Windows' own.
        HTCAPTION = 2
        self.assertEqual(self.handle(titlebar.WM_NCLBUTTONDOWN, HTCAPTION), (False, 0))
        self.assertEqual(self.handle(titlebar.WM_NCLBUTTONDBLCLK, HTCAPTION), (False, 0))

    def test_focus_changes_ask_windows_not_to_repaint_its_caption(self):
        fake = _FakeUser32(0)
        titlebar._api["user32"] = fake
        handled, result = self.handle(titlebar.WM_NCACTIVATE, 1, 0)
        self.assertTrue(handled)
        self.assertEqual(result, 1)
        self.assertEqual(fake.calls, [("default", titlebar.WM_NCACTIVATE, 0)])
        # The real call works on a real window too.
        titlebar._api.clear()
        self.assertTrue(self.handle(titlebar.WM_NCACTIVATE, 0, 0)[0])

    def test_a_new_title_or_icon_is_taken_without_drawing_a_caption(self):
        visible = titlebar.WS_VISIBLE | 0x00C00000
        for message in (titlebar.WM_SETTEXT, titlebar.WM_SETICON):
            fake = _FakeUser32(visible)
            titlebar._api["user32"] = fake
            self.assertEqual(self.handle(message), (True, 1))
            self.assertEqual(fake.calls, [("style", visible & ~titlebar.WS_VISIBLE),
                                          ("default", message, visible & ~titlebar.WS_VISIBLE),
                                          ("style", visible)])
        # Before the window is shown there is nothing to protect.
        titlebar._api["user32"] = _FakeUser32(0x00C00000)
        self.assertEqual(self.handle(titlebar.WM_SETTEXT), (False, 0))

    def test_other_messages_pass_through(self):
        WM_MOUSEMOVE, WM_PAINT, WM_NCHITTEST = 0x0200, 0x000F, 0x0084
        for message in (WM_MOUSEMOVE, WM_PAINT, WM_NCHITTEST):
            self.assertEqual(self.handle(message), (False, 0))

    def test_the_main_window_routes_its_messages_through_the_guard(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="halo-guard-", dir=scratch) as folder:
            settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("glow", False)
            c = Controller(settings, offline=True)
            c.timer.stop()
            window = MainWindow(c)
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            window.draw_timer.stop()
            window.show()
            QTest.qWait(20)
            try:
                msg = _message(int(window.winId()), titlebar.WM_NCLBUTTONDOWN, titlebar.HTMINBUTTON)
                handled, result = window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
                self.assertTrue(handled)
                self.assertFalse(window.isMinimized())
                msg = _message(int(window.winId()), 0x0200)
                self.assertFalse(window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))[0])
                # Fullscreen has Windows' ordinary frame back, so the guard stands aside.
                window.fullscreen()
                QTest.qWait(20)
                msg = _message(int(window.winId()), titlebar.WM_NCLBUTTONDOWN, titlebar.HTMINBUTTON)
                self.assertFalse(window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))[0])
            finally:
                window.exiting = True
                window.hide()
                window.tray.hide()
                window.immersive.media_background.close()
                c.close()
                c.audio.thread.join(1)
                for widget in (window.overlay, *window.edges, window):
                    widget.hide()
                    widget.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()


class HideIncludedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.owner.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.controller = LibraryController()
        self.libraries = []

    def tearDown(self):
        for library in self.libraries:
            library.hide()
            library.deleteLater()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()

    def library(self):
        library = ModeLibrary(self.owner, self.controller)
        library.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.libraries.append(library)
        library.open_page("all")
        self.app.processEvents()
        return library

    def optional(self):
        return [spec for spec in all_modes() if not spec.included]

    def test_the_switch_sits_in_the_toolbar_beside_search_and_starts_off(self):
        library = self.library()
        switch = library.hide_owned
        self.assertTrue(switch.isVisible())
        self.assertFalse(switch.isChecked())
        self.assertEqual(switch.text(), "Hide included")
        self.assertIs(switch.parentWidget(), library.search.parentWidget())
        self.assertLess(switch.mapTo(library, QPoint(0, 0)).x(), library.search.mapTo(library, QPoint(0, 0)).x())
        self.assertGreaterEqual(switch.height(), 32)
        self.assertEqual(len(library.filtered_specs), len(all_modes()))
        # The label is never cut short, even in the bold it takes when the switch is on.
        switch.setChecked(True)
        bold = QFontMetrics(_font(12, QFont.Weight.DemiBold)).horizontalAdvance(switch.text())
        self.assertLessEqual(bold, switch.width() - 14 - 50)

    def test_hiding_leaves_out_included_and_added_modes(self):
        added = self.optional()[0]
        self.controller.add_mode(added.kind, added.key)
        library = self.library()
        QTest.mouseClick(library.hide_owned, Qt.MouseButton.LeftButton)
        self.assertTrue(library.hide_owned.isChecked())
        shown = library.filtered_specs
        self.assertTrue(shown)
        self.assertFalse(any(self.controller.has_mode(spec.kind, spec.key) for spec in shown))
        self.assertNotIn(added, shown)
        owned = sum(self.controller.has_mode(spec.kind, spec.key) for spec in all_modes())
        self.assertEqual(len(shown), len(all_modes()) - owned)
        self.assertIn(f"{owned} already yours, hidden", library.count_label.text())
        self.assertNotIn(library.selected, [spec for spec in all_modes() if spec not in shown])
        # Off again brings every mode back.
        QTest.keyClick(library.hide_owned, Qt.Key.Key_Space)
        self.assertFalse(library.hide_owned.isChecked())
        self.assertEqual(len(library.filtered_specs), len(all_modes()))

    def test_my_modes_ignores_the_switch(self):
        library = self.library()
        library.hide_owned.setChecked(True)
        library.set_category("mine")
        self.assertFalse(library.hide_owned.isEnabled())
        self.assertTrue(library.filtered_specs)
        self.assertTrue(all(self.controller.has_mode(spec.kind, spec.key) for spec in library.filtered_specs))
        library.set_category("all")
        self.assertTrue(library.hide_owned.isEnabled())

    def test_adding_a_mode_keeps_it_in_the_detail_panel_while_its_card_leaves(self):
        library = self.library()
        library.hide_owned.setChecked(True)
        spec = library.filtered_specs[1]
        library.select_mode(spec)
        QTest.mouseClick(library.add_button, Qt.MouseButton.LeftButton)
        self.assertTrue(self.controller.has_mode(spec.kind, spec.key))
        self.assertNotIn(spec, library.filtered_specs)
        self.assertIs(library.selected, spec)
        self.assertEqual(library.detail_title.text(), spec.title)
        self.assertEqual(library.add_button.text(), "Added ✓")
        self.assertTrue(library.remove_button.isVisible())

    def test_a_category_that_is_all_yours_says_so(self):
        for spec in self.optional():
            if spec.kind == "halo":
                self.controller.add_mode(spec.kind, spec.key)
        library = self.library()
        library.hide_owned.setChecked(True)
        library.set_category("halo")
        self.assertEqual(library.filtered_specs, [])
        self.assertFalse(library.empty_label.isHidden())
        self.assertIn("already yours", library.empty_label.text())

    def test_the_choice_is_remembered(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="halo-modes-filter-", dir=scratch) as folder:
            self.controller.settings = QSettings(str(Path(folder) / "settings.ini"), QSettings.Format.IniFormat)
            first = self.library()
            first.hide_owned.setChecked(True)
            self.assertTrue(self.controller.settings.value("modes_hide_owned", False, type=bool))
            second = self.library()
            self.assertTrue(second.hide_owned.isChecked())
            self.assertEqual(second.hide_owned.knob, 1.)
            self.assertFalse(any(self.controller.has_mode(spec.kind, spec.key) for spec in second.filtered_specs))
            self.controller.settings.sync()
            del self.controller.settings


if __name__ == "__main__":
    unittest.main()
