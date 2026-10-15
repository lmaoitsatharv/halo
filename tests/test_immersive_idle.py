"""Idle chrome behavior with actual Qt timers/events and original demo lyrics."""
import unittest
import warnings

from PySide6.QtCore import QObject, Signal, Qt, QEvent, QPointF
from PySide6.QtGui import QColor, QFocusEvent, QMouseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtTest import QTest

from halo.immersive import Immersive, IMMERSIVE_SCENES
from halo.models import Track, Lyrics, parse_lrc, DEMO_LRC


class DemoController(QObject):
    trackChanged = Signal()
    lyricsChanged = Signal()
    settingChanged = Signal()

    def __init__(self):
        super().__init__()
        self.track = Track("In the light we made", "Halo Studio · visual demo", "Sound in colour", 60, 8, True, True)
        self.lyrics = Lyrics(parse_lrc(DEMO_LRC), "Original demo text · line-synced")
        self.position, self.offset, self.generation = 18.5, 0, 1
        self.demo = True
        self.primary, self.secondary = QColor("#d4b5ff"), QColor("#7576eb")
        self.immersive_mode, self.lyric_style, self.halo_mode = "studio", "ship", "aura"
        self.motion_time, self.motion_speed, self.reduced_motion = 12., 45, True
        self.glow, self.intensity, self.glow_width, self.pulse = False, 24, 24, .5
        self.calls = []

    def set(self, name, value):
        setattr(self, name, value)
        self.settingChanged.emit()

    def transport(self, action):
        self.calls.append(action)

    def seek(self, seconds):
        self.calls.append(("seek", seconds))


class ImmersiveIdleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = DemoController()
        self.window = Immersive(self.controller)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        for combo in (self.window.scene_select, self.window.style_select):
            combo.view().window().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.resize(960, 640)
        self.window.show()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(self.window)
        self.app.processEvents()

    def tearDown(self):
        self.window.scene_select.hidePopup()
        self.window.style_select.hidePopup()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def fast_idle(self):
        self.window.IDLE_INTERVAL = 120
        self.window._wake_chrome()

    def move(self, widget, x=8, y=8):
        local = QPointF(x, y)
        global_point = QPointF(widget.mapToGlobal(local.toPoint()))
        event = QMouseEvent(QEvent.Type.MouseMove, local, global_point,
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(widget, event)

    def assert_chrome(self, visible):
        self.assertEqual(self.window.chrome_visible, visible)
        self.assertEqual(self.window._cursor_hidden, not visible)
        self.assertEqual(self.window.canvas.cursor().shape(), Qt.CursorShape.PointingHandCursor if visible else Qt.CursorShape.BlankCursor)
        self.assertEqual(len(self.window.chrome_effects), 2)
        for effect in self.window.chrome_effects:
            self.assertEqual(effect.opacity(), 1.0 if visible else 0.0)

    def test_every_scene_hides_after_1500ms_over_stationary_header_and_movement_wakes(self):
        self.assertEqual(self.window.IDLE_INTERVAL, 1500)
        for scene, _, _ in IMMERSIVE_SCENES:
            with self.subTest(scene=scene):
                self.controller.set("immersive_mode", scene)
                self.move(self.window.header, 9, 9)
                self.assert_chrome(True)
                QTest.qWait(1580)
                self.assert_chrome(False)
                self.move(self.window.header, 10, 9)
                self.assert_chrome(True)

    def test_identical_move_events_and_unrelated_focus_events_do_not_rearm(self):
        self.fast_idle()
        self.move(self.window.player, 12, 12)
        for _ in range(4):
            QTest.qWait(40)
            self.move(self.window.player, 12, 12)
            self.app.sendEvent(self.window.play, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.OtherFocusReason))
        self.assert_chrome(False)
        self.move(self.window.player, 13, 12)
        self.assert_chrome(True)

    def test_open_dropdown_defers_hide_and_closing_rearms_full_interval(self):
        self.fast_idle()
        self.window.style_select.showPopup()
        QTest.qWait(260)
        self.assertTrue(self.window.style_select.view().isVisible())
        self.assert_chrome(True)
        self.window.style_select.hidePopup()
        QTest.qWait(70)
        self.assert_chrome(True)
        QTest.qWait(120)
        self.assert_chrome(False)

    def test_slider_drag_defers_hide_and_release_rearms_without_blink(self):
        self.fast_idle()
        self.window.progress.setSliderDown(True)
        QTest.qWait(260)
        self.assert_chrome(True)
        self.window.progress.setValue(500)
        self.window.progress.setSliderDown(False)
        self.assertEqual(self.controller.calls[-1], ("seek", 30.0))
        QTest.qWait(70)
        self.assert_chrome(True)
        QTest.qWait(120)
        self.assert_chrome(False)

    def test_keyboard_focus_is_protected_until_focus_leaves_chrome(self):
        self.fast_idle()
        self.window.play.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.qWait(260)
        self.assert_chrome(True)
        self.window.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.window.canvas.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.qWait(70)
        self.assert_chrome(True)
        QTest.qWait(120)
        self.assert_chrome(False)

    def test_held_keyboard_input_protects_then_release_resumes_idle(self):
        self.fast_idle()
        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.window.progress, press)
        QTest.qWait(260)
        self.assert_chrome(True)
        release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.window.progress, release)
        QTest.qWait(70)
        self.assert_chrome(True)
        QTest.qWait(120)
        self.assert_chrome(False)

    def test_scene_switch_rearms_and_shortcuts_survive_removed_hint(self):
        self.fast_idle()
        QTest.qWait(160)
        self.assert_chrome(False)
        self.controller.set("immersive_mode", "orbit")
        self.assert_chrome(True)
        QTest.qWait(70)
        self.assert_chrome(True)
        QTest.qWait(120)
        self.assert_chrome(False)
        self.assertFalse(hasattr(self.window, "hint"))
        self.assertFalse(any("Space to pause" in label.text() for label in self.window.findChildren(QLabel)))
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertEqual(self.controller.calls[-1], "toggle")
        exits = []
        self.window.exited.connect(lambda: exits.append(True))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.assertEqual(exits, [True])
        self.assertFalse(self.window.isVisible())

    def test_reduced_motion_transitions_are_immediate(self):
        self.window._hide_chrome()
        self.assert_chrome(False)
        self.window._wake_chrome()
        self.assert_chrome(True)
        self.controller.reduced_motion = False
        self.window._hide_chrome()
        self.assertFalse(self.window.chrome_visible)
        self.assertGreater(self.window.chrome_effects[0].opacity(), 0.0)
        QTest.qWait(380)
        self.assertEqual(self.window.chrome_effects[0].opacity(), 0.0)
        self.window._wake_chrome()
        QTest.qWait(30)
        self.assertLess(self.window.chrome_effects[0].opacity(), 1.0)
        self.controller.set("reduced_motion", True)
        self.assert_chrome(True)

    def test_cursor_hides_over_children_and_restores_without_affecting_other_windows(self):
        other = QWidget()
        other.setCursor(Qt.CursorShape.CrossCursor)
        self.addCleanup(other.close)
        cursors = {widget: (widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor), widget.cursor().shape())
                   for widget in (self.window, self.window.canvas, self.window.play, self.window.exit)}
        self.fast_idle()
        self.move(self.window.canvas, 15, 15)
        QTest.qWait(160)
        self.assert_chrome(False)
        for widget in (self.window, self.window.canvas, self.window.play, self.window.exit):
            self.assertEqual(widget.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.assertIsNone(self.app.overrideCursor())
        self.assertEqual(other.cursor().shape(), Qt.CursorShape.CrossCursor)
        self.move(self.window.canvas, 16, 15)
        self.assert_chrome(True)
        for widget, (explicit, shape) in cursors.items():
            # Qt's top-level unsetCursor installs a native arrow explicitly;
            # child widgets must retain their explicit/inherited distinction.
            if not widget.isWindow():
                self.assertEqual(widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor), explicit)
            self.assertEqual(widget.cursor().shape(), shape)

    def test_deactivation_and_leaving_restore_cursor_and_reentry_restarts_idle(self):
        self.fast_idle()
        QTest.qWait(160)
        self.assert_chrome(False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(None)
        self.app.processEvents()
        self.assertFalse(self.window._cursor_hidden)
        QTest.qWait(160)
        self.assertFalse(self.window._cursor_hidden)
        self.assertEqual(self.window.canvas.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(self.window)
        self.app.processEvents()
        self.assert_chrome(True)
        QTest.qWait(160)
        self.assert_chrome(False)
        self.window.leave()
        self.assertFalse(self.window._cursor_hidden)
        self.assertEqual(self.window.canvas.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        self.window.show()
        self.assert_chrome(True)


if __name__ == "__main__":
    unittest.main()
