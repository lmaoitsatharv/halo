"""The Immersive room's menu: one key with three lines at the top left, and a dark dropdown with flyouts."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QSettings, Qt, QPoint
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QPushButton

from halo import theme
from halo.app import Controller, MainWindow
from halo.gallery import HandsetButton, mix, song_light
from halo.glass import GlassPanel


class RoomMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-room-menu-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        settings.setValue("floating", False)
        settings.setValue("appearance", "light")
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.c.set_demo(True)
        self.c.tick()
        theme.apply(False)
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
        self.window.resize(1280, 800)
        self.window.fullscreen()
        QTest.qWait(60)
        self.room = self.window.immersive

    def tearDown(self):
        if self.room.menu_open():
            self.room.menu.close()
        self.window.exiting = True
        self.window.hide()
        self.window.tray.hide()
        self.room.media_background.close()
        self.c.close()
        self.c.audio.thread.join(1)
        for widget in (self.window.overlay, *self.window.edges, self.window):
            widget.hide()
            widget.deleteLater()
        QApplication.processEvents()
        # Let the closed popups hand activation back before the next test's windows appear.
        QTest.qWait(120)
        self.temp.cleanup()

    def open(self):
        QTest.mouseClick(self.room.menu_button, Qt.MouseButton.LeftButton)
        QTest.qWait(30)
        self.assertTrue(self.room.menu_open())
        return self.room.menu

    def row(self, menu, text):
        return [entry.text for entry in menu.entries].index(text)

    def test_the_header_holds_only_the_menu_key_and_the_name(self):
        header = self.room.header
        self.assertEqual([widget for widget in header.findChildren(QPushButton) if widget.isVisible()], [])
        self.assertEqual([widget for widget in header.findChildren(QComboBox) if widget.isVisible()], [])
        self.assertFalse(self.room.scene_select.isVisible())
        self.assertFalse(self.room.style_select.isVisible())
        key = self.room.menu_button
        self.assertTrue(key.isVisible())
        self.assertLess(key.mapTo(self.room, QPoint(0, 0)).x(), 80)
        self.assertEqual(key.accessibleName(), "Room menu")

    def test_the_menu_drops_down_under_the_key_with_every_room_control(self):
        menu = self.open()
        self.assertEqual([entry.text for entry in menu.entries if entry.kind != "separator"],
                         ["Room", "Lyric style", "Lighting", "Background", "Background settings…", "Browse modes",
                          "Return to Halo"])
        key_bottom = self.room.menu_button.mapToGlobal(QPoint(0, self.room.menu_button.height())).y()
        panel_top = menu.mapToGlobal(menu.panel().topLeft().toPoint()).y()
        self.assertGreater(panel_top, key_bottom)
        self.assertLess(abs(menu.mapToGlobal(menu.panel().topLeft().toPoint()).x()
                            - self.room.menu_button.mapToGlobal(QPoint(0, 0)).x()), 4)
        # The room's controls stay on screen while the menu is open.
        self.room.IDLE_INTERVAL = 80
        self.room._wake_chrome()
        QTest.qWait(200)
        self.assertTrue(self.room.chrome_visible)
        QTest.keyClick(menu, Qt.Key.Key_Escape)
        self.assertFalse(self.room.menu_open())
        self.assertFalse(self.room.menu_button.open)

    def test_the_room_flyout_marks_the_current_room_and_picks_another(self):
        menu = self.open()
        index = self.row(menu, "Room")
        menu._hover_at(dict(menu.rows())[index].center().toPoint())
        flyout = menu.child
        self.assertIsNotNone(flyout)
        self.assertTrue(flyout.isVisible())
        self.assertGreater(flyout.x(), menu.x())
        current = [entry.text for entry in flyout.entries if entry.is_on()]
        self.assertEqual(current, [self.room.scene_select.currentText()])
        flyout.activate(self.row(flyout, "Cinema"))
        self.assertEqual(self.c.immersive_mode, "cinema")
        self.assertFalse(self.room.menu_open())

    def test_the_lighting_flyout_switches_the_light_and_picks_a_mode(self):
        self.c.set("glow", True)
        self.c.set("halo_mode", "orbit")
        menu = self.open()
        index = self.row(menu, "Lighting")
        self.assertEqual(menu.entries[index].detail(), "Orbit")
        # It sits right under Lyric style, with the room's other choices.
        self.assertEqual(index, self.row(menu, "Lyric style") + 1)
        menu._hover_at(dict(menu.rows())[index].center().toPoint())
        flyout = menu.child
        self.assertIsNotNone(flyout)
        texts = [entry.text for entry in flyout.entries if entry.kind != "separator"]
        self.assertEqual(texts[0], "Screen-edge light")
        self.assertEqual(texts[1:], [spec[1] for spec in self.c.mode_specs("halo_mode")])
        self.assertEqual([entry.text for entry in flyout.entries if entry.kind == "radio" and entry.is_on()], ["Orbit"])
        # The switch stays open and turns the light off and on.
        switch = self.row(flyout, "Screen-edge light")
        flyout.activate(switch)
        self.assertFalse(self.c.glow)
        self.assertTrue(self.room.menu_open())
        self.assertEqual(menu.entries[index].detail(), "Off")
        flyout.activate(switch)
        self.assertTrue(self.c.glow)
        flyout.activate(self.row(flyout, "Aura"))
        self.assertEqual(self.c.halo_mode, "aura")
        self.assertFalse(self.room.menu_open())

    def test_the_keyboard_reaches_every_row_and_flyout(self):
        menu = self.open()
        QTest.keyClick(menu, Qt.Key.Key_Down)
        self.assertEqual(menu.entries[menu.hover].text, "Room")
        QTest.keyClick(menu, Qt.Key.Key_Down)
        self.assertEqual(menu.entries[menu.hover].text, "Lyric style")
        QTest.keyClick(menu, Qt.Key.Key_Right)
        flyout = menu.child
        self.assertEqual(flyout.hover, 0)
        QTest.keyClick(flyout, Qt.Key.Key_Left)
        self.assertIsNone(menu.child)
        QTest.keyClick(menu, Qt.Key.Key_Up)
        QTest.keyClick(menu, Qt.Key.Key_Right)
        flyout = menu.child
        target = flyout.entries[1].text
        QTest.keyClick(flyout, Qt.Key.Key_Down)
        QTest.keyClick(flyout, Qt.Key.Key_Return)
        self.assertEqual(self.room.scene_select.currentText(), target)
        self.assertFalse(self.room.menu_open())

    def test_the_background_switch_stays_open_and_remembers_your_background(self):
        self.c.set("background_source", "artwork")
        menu = self.open()
        index = self.row(menu, "Background")
        self.assertTrue(menu.entries[index].is_on())
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=dict(menu.rows())[index].center().toPoint())
        self.assertTrue(self.room.menu_open())
        self.assertEqual(self.c.background_source, "ambient")
        self.assertEqual(self.c.settings.value("background_last_source"), "artwork")
        self.assertFalse(menu.entries[index].is_on())
        menu.activate(index)
        self.assertEqual(self.c.background_source, "artwork")
        # An image with no file chosen falls back to the album artwork rather than an empty room.
        self.c.settings.setValue("background_last_source", "image")
        self.c.set("background_source", "ambient")
        menu.activate(index)
        self.assertEqual(self.c.background_source, "artwork")

    def keys(self):
        return sorted((widget for widget in self.room.player.findChildren(QAbstractButton) if widget.isVisible()),
                      key=lambda widget: widget.x())

    def test_the_room_player_is_the_main_windows_handset(self):
        main, room = self.window, self.room
        self.assertIsInstance(room.player, GlassPanel)
        self.assertEqual(room.player.variant, "player")
        self.assertEqual(room.player.height(), main.player.height())
        for name in ("previous", "play", "next"):
            key = getattr(room, name)
            self.assertIsInstance(key, HandsetButton)
            self.assertEqual(key.kind, getattr(main, name).kind)
            self.assertEqual(key.size(), getattr(main, name).size())
        self.assertIsInstance(room.progress, type(main.progress))
        # Its keys, left to right: the transport, then the mini player and the way out. No share key.
        self.assertEqual([key.kind for key in self.keys()], ["previous", "play", "next", "mini", "exit-fullscreen"])
        self.assertLess(room.total.x(), room.mini_button.x())
        # The timeline is lit in the song's light, like the main one.
        room.tick()
        self.assertEqual(room.progress.fill_colour, mix(song_light(self.c), QColor("#ffffff"), .22))

    def test_the_player_bar_ends_with_a_key_back_out_of_the_room(self):
        key = self.room.leave_button
        self.assertTrue(key.isVisible())
        self.assertIs(key.parentWidget(), self.room.player)
        self.assertEqual(key.accessibleName(), "Return to Halo")
        self.assertIn("Esc", key.toolTip())
        self.assertIs(self.keys()[-1], key)
        self.assertGreater(key.x(), self.room.total.x())
        self.assertLessEqual(key.geometry().right(), self.room.player.width())
        self.assertGreaterEqual(key.width(), 42)
        left = []
        self.room.exited.connect(lambda: left.append(True))
        QTest.mouseClick(key, Qt.MouseButton.LeftButton)
        self.assertEqual(left, [True])
        QTest.qWait(30)
        self.assertFalse(self.window.isFullScreen())

    def test_the_mini_player_key_leaves_the_room_for_the_mini_player(self):
        key = self.room.mini_button
        self.assertEqual(key.accessibleName(), "Mini player")
        self.assertIn("Ctrl+Shift+M", key.toolTip())
        QTest.mouseClick(key, Qt.MouseButton.LeftButton)
        QTest.qWait(30)
        try:
            self.assertIsNotNone(self.window.mini_player)
            self.assertTrue(self.window.mini_player.isVisible())
            self.assertFalse(self.window.isVisible())
            self.assertIs(self.window.app_stack.currentWidget(), self.window.shell)
        finally:
            if self.window.mini_player is not None:
                self.window.mini_player.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
                self.window.close_mini_player()
                self.window.mini_player.close()

    def test_f11_goes_in_and_back_out(self):
        self.assertTrue(self.window.isFullScreen())
        self.window.toggle_immersive()
        QTest.qWait(30)
        self.assertFalse(self.window.isFullScreen())
        self.assertIs(self.window.app_stack.currentWidget(), self.window.shell)
        self.window.toggle_immersive()
        QTest.qWait(30)
        self.assertTrue(self.window.isFullScreen())
        self.assertIs(self.window.app_stack.currentWidget(), self.room)

    def test_return_leaves_the_room(self):
        left = []
        self.room.exited.connect(lambda: left.append(True))
        menu = self.open()
        menu.activate(self.row(menu, "Return to Halo"))
        self.assertEqual(left, [True])
        self.assertFalse(self.room.menu_open())

    def test_a_click_outside_closes_the_menu_and_does_not_reopen_it(self):
        menu = self.open()
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(menu.width() + 40, menu.height() + 40))
        self.assertFalse(self.room.menu_open())
        self.room.open_menu()
        self.assertFalse(self.room.menu_open())
        QTest.qWait(300)
        self.room.open_menu()
        self.assertTrue(self.room.menu_open())


if __name__ == "__main__":
    unittest.main()
