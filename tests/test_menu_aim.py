"""The room menu's safety triangle: a diagonal move toward an open flyout keeps it open."""
import unittest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from halo.room_menu import AIM_PATIENCE_MS, MenuEntry, RoomMenu, separator


class MenuAimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QWidget()
        self.host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.host.resize(200, 200)
        self.host.show()
        styles = lambda: [MenuEntry("radio", name) for name in
                          ("Ship", "Fisheye", "Visual", "Monument", "Marquee", "Afterimage", "Strata", "Cascade",
                           "Starline", "Neon", "Impact")]
        rooms = lambda: [MenuEntry("radio", name) for name in ("Studio", "Lyrics only", "Cinema")]
        lights = lambda: [MenuEntry("radio", name) for name in ("Orbit", "Aurora", "Neon", "Liquid")]
        self.entries = lambda: [MenuEntry("submenu", "Room", submenu=rooms),
                                MenuEntry("submenu", "Lyric style", submenu=styles),
                                MenuEntry("submenu", "Lighting", submenu=lights),
                                separator(),
                                MenuEntry("action", "Browse modes")]

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()

    def open(self, at=QPoint(120, 120)):
        menu = RoomMenu(self.entries, self.host, title="Room menu")
        menu.open_at(at)
        self.addCleanup(menu.close)
        return menu

    def row(self, menu, index):
        return dict(menu.rows())[index]

    def open_lyric_style(self, menu, x_share=.85):
        row = self.row(menu, 1)
        start = QPointF(row.left() + row.width() * x_share, row.center().y())
        menu._hover_at(start.toPoint())
        self.assertEqual(menu.child.owner_index, 1)
        return start

    def test_a_diagonal_move_across_lighting_keeps_the_lyric_style_flyout(self):
        menu = self.open()
        start = self.open_lyric_style(menu)
        child = menu.child
        lighting = self.row(menu, 2)
        # Head for the flyout's middle: the way crosses the Lighting row inside the menu.
        target = QPointF(menu.panel().right() + 4, lighting.bottom() + 30)
        crossed = False
        for step in range(1, 13):
            t = step / 12
            point = start + (target - start) * t
            if not menu.panel().contains(point):
                break
            crossed = crossed or menu.row_at(point.toPoint()) == 2
            menu._hover_at(point.toPoint())
            self.assertIs(menu.child, child, f"step {step}")
            self.assertEqual(menu.hover, 1, f"step {step}")
        self.assertTrue(crossed, "the path should cross Lighting")
        self.assertTrue(menu._aim_timer.isActive())
        self.assertEqual(menu._aim_timer.interval(), AIM_PATIENCE_MS)

    def test_moving_straight_down_the_list_switches_at_once(self):
        menu = self.open()
        row = self.row(menu, 1)
        menu._hover_at(QPointF(row.left() + 40, row.center().y()).toPoint())
        self.assertEqual(menu.child.owner_index, 1)
        lighting = self.row(menu, 2)
        menu._hover_at(QPointF(lighting.left() + 40, lighting.center().y()).toPoint())
        self.assertEqual(menu.child.owner_index, 2)
        self.assertEqual(menu.hover, 2)

    def test_heading_back_away_from_the_flyout_switches_at_once(self):
        menu = self.open()
        start = self.open_lyric_style(menu)
        lighting = self.row(menu, 2)
        inside = QPointF(start.x() + 6, lighting.top() + 4)
        menu._hover_at(inside.toPoint())
        self.assertEqual(menu.child.owner_index, 1)
        menu._hover_at(QPointF(inside.x() - 20, lighting.center().y()).toPoint())
        self.assertEqual(menu.child.owner_index, 2)

    def test_resting_on_another_row_lets_it_take_over(self):
        menu = self.open()
        start = self.open_lyric_style(menu)
        lighting = self.row(menu, 2)
        menu._hover_at(QPointF(start.x() + 6, lighting.top() + 4).toPoint())
        self.assertEqual(menu.child.owner_index, 1)
        menu._aim_expired()  # the pointer rested there for AIM_PATIENCE_MS
        self.assertEqual(menu.child.owner_index, 2)
        self.assertEqual(menu.hover, 2)
        # From there, moving on works as usual, and the old triangle is gone.
        self.assertIsNone(menu._aim)

    def test_crossing_an_action_row_keeps_the_flyout_and_clicking_still_works(self):
        menu = self.open()
        self.open_lyric_style(menu)
        browse = self.row(menu, 4)
        menu._hover_at(QPointF(browse.left() + 30, browse.center().y()).toPoint())
        # Far from the triangle: Browse takes over and the flyout closes.
        self.assertEqual(menu.hover, 4)
        self.assertIsNone(menu.child)

    def test_a_flyout_opened_on_the_left_aims_left(self):
        area = QGuiApplication.primaryScreen().availableGeometry()
        menu = self.open(QPoint(area.right() - 260, area.top() + 120))
        start = self.open_lyric_style(menu, x_share=.15)
        child = menu.child
        self.assertLess(child.mapToGlobal(child.panel().center()).x(), menu.mapToGlobal(menu.panel().center()).x())
        lighting = self.row(menu, 2)
        menu._hover_at(QPointF(start.x() - 6, lighting.top() + 4).toPoint())
        self.assertIs(menu.child, child)
        self.assertEqual(menu.hover, 1)
        menu._hover_at(QPointF(start.x() + 30, lighting.center().y()).toPoint())
        self.assertEqual(menu.child.owner_index, 2)


    def brush_past_and_enter(self, menu, owner, brushed):
        """Leave the owner row diagonally, clip the next row's right end, then land inside the flyout."""
        row = self.row(menu, owner)
        start = QPointF(row.right() - 24, row.center().y())
        menu._hover_at(start.toPoint())
        child = menu.child
        self.assertEqual(child.owner_index, owner)
        edge = self.row(menu, brushed)
        menu._hover_at(QPointF(row.right() - 10, edge.top() + 3).toPoint())
        self.assertIs(menu.child, child, "brushing the next row keeps the flyout")
        self.assertTrue(menu._aim_timer.isActive())
        # Into the flyout, onto its second option.
        option = dict(child.rows())[1]
        child._hover_at(QPointF(option.left() + 30, option.center().y()).toPoint())
        return child

    def test_resting_on_a_room_option_never_opens_lyric_style(self):
        menu = self.open()
        child = self.brush_past_and_enter(menu, 0, 1)
        self.assertFalse(menu._aim_timer.isActive())
        menu._aim_expired()  # even if a stale timer fired, nothing switches
        self.assertIs(menu.child, child)
        self.assertEqual(menu.child.owner_index, 0)
        self.assertEqual(menu.hover, 0)
        self.assertEqual(child.hover, 1)

    def test_resting_on_a_lyric_style_option_never_opens_lighting(self):
        menu = self.open()
        child = self.brush_past_and_enter(menu, 1, 2)
        menu._aim_expired()
        self.assertIs(menu.child, child)
        self.assertEqual(menu.child.owner_index, 1)

    def test_coming_back_out_of_the_flyout_switches_at_once(self):
        menu = self.open()
        self.brush_past_and_enter(menu, 1, 2)
        lighting = self.row(menu, 2)
        menu._hover_at(QPointF(lighting.right() - 20, lighting.center().y()).toPoint())
        self.assertEqual(menu.child.owner_index, 2)


if __name__ == "__main__":
    unittest.main()
