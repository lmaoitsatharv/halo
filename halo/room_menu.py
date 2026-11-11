"""The Immersive room's menu: one button with three lines at the top left, and a dark dropdown.

The dropdown reads like a Windows 11 menu: an icon and a word per row, a dot beside the
current choice, flyouts for longer lists, a switch for things that are simply on or off,
and the key that does the same thing on the right.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QFontMetricsF, QGuiApplication
from PySide6.QtWidgets import QWidget, QAbstractButton

from .gallery import face, tint, paint_shadow, keyboard_reason

PANEL = QColor(30, 37, 35, 250)
EDGE = QColor(255, 255, 255, 30)
HOVER = QColor(255, 255, 255, 20)
TEXT = QColor("#eef1ec")
MUTED = QColor("#9eaaa4")
DISABLED = QColor("#6f7a75")
MINT = QColor("#b7e4ad")
ON_MINT = QColor("#1c2a26")


@dataclass
class MenuEntry:
    """One row. kind is "action", "radio", "check", "toggle", "submenu" or "separator"."""
    kind: str
    text: str = ""
    icon: Optional[str] = None
    run: Optional[Callable[[], None]] = None
    checked: Optional[Callable[[], bool]] = None
    submenu: Optional[Callable[[], list]] = None
    detail: Optional[Callable[[], str]] = None
    shortcut: str = ""
    tip: str = ""
    enabled: Callable[[], bool] = field(default=lambda: True)

    def is_on(self):
        return bool(self.checked()) if self.checked is not None else False

    def selectable(self):
        return self.kind != "separator" and self.enabled()


def separator():
    return MenuEntry("separator")


class RoomMenu(QWidget):
    """A dark dropdown with flyouts. Built fresh from its entries each time it opens."""
    closed = Signal()
    ROW = 36
    SEPARATOR = 9
    PAD = 5
    MARGIN = 16
    RADIUS = 10

    def __init__(self, entries, parent=None, parent_menu=None, title="Menu"):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if parent is not None and parent.window().testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
            # A window drawn off screen (tests, snapshots) keeps its menus off screen too.
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.entries_source = entries
        self.entries = []
        self.parent_menu = parent_menu
        self.child = None
        self.hover = -1
        self._pressed_inside = False
        self._has_icons = False
        self._right = 0.

    # --- building ----------------------------------------------------------------------

    def panel(self):
        return QRectF(self.rect()).adjusted(self.MARGIN, self.MARGIN - 6, -self.MARGIN, -self.MARGIN - 4)

    def _measure(self):
        text_font, side_font = face(13), face(12)
        text_metrics, side_metrics = QFontMetricsF(text_font), QFontMetricsF(side_font)
        self._has_icons = any(entry.icon for entry in self.entries)
        widest, right = 120., 0.
        for entry in self.entries:
            if entry.kind == "separator":
                continue
            widest = max(widest, text_metrics.horizontalAdvance(entry.text))
            extra = 0.
            if entry.kind == "toggle":
                extra = 40
            elif entry.kind == "submenu":
                detail = entry.detail() if entry.detail else ""
                extra = 18 + (side_metrics.horizontalAdvance(detail) + 14 if detail else 0)
            elif entry.shortcut:
                extra = side_metrics.horizontalAdvance(entry.shortcut) + 8
            right = max(right, extra)
        self._right = right
        width = self.text_left() + widest + 28 + right + 12
        height = self.PAD * 2 + sum(self.SEPARATOR if entry.kind == "separator" else self.ROW for entry in self.entries)
        return round(max(232., width)), round(height)

    def text_left(self):
        return 58. if self._has_icons else 34.

    def rows(self):
        """(index, rect) for every row, in this widget's coordinates."""
        panel = self.panel()
        y = panel.top() + self.PAD
        result = []
        for index, entry in enumerate(self.entries):
            height = self.SEPARATOR if entry.kind == "separator" else self.ROW
            result.append((index, QRectF(panel.left() + 4, y, panel.width() - 8, height)))
            y += height
        return result

    def row_at(self, point):
        for index, rect in self.rows():
            if rect.contains(QPointF(point)) and self.entries[index].kind != "separator":
                return index
        return -1

    def open_at(self, anchor, below=True):
        """Open with the panel's top-left at a global point (or flipped to stay on screen)."""
        self.entries = list(self.entries_source())
        width, height = self._measure()
        self.resize(width + self.MARGIN * 2, height + self.MARGIN * 2 - 2)
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = anchor.x() - self.MARGIN
        y = anchor.y() - (self.MARGIN - 6)
        if x + self.width() > area.right() and self.parent_menu is not None:
            x = self.parent_menu.mapToGlobal(self.parent_menu.panel().topLeft().toPoint()).x() - self.width() + self.MARGIN + 4
        x = max(area.left() - self.MARGIN, min(x, area.right() - self.width() + self.MARGIN))
        y = max(area.top() - self.MARGIN, min(y, area.bottom() - self.height() + self.MARGIN))
        self.move(x, y)
        self.hover = -1
        self._pressed_inside = False
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    # --- painting ----------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        panel = self.panel()
        paint_shadow(p, panel, self.RADIUS, 12, .5, 6, QColor("#000000"))
        p.setPen(QPen(EDGE, 1))
        p.setBrush(PANEL)
        p.drawRoundedRect(panel.adjusted(.5, .5, -.5, -.5), self.RADIUS, self.RADIUS)
        text_font, side_font = face(13), face(12)
        for index, rect in self.rows():
            entry = self.entries[index]
            if entry.kind == "separator":
                p.setPen(QPen(tint(QColor("#ffffff"), 24), 1))
                y = rect.center().y()
                p.drawLine(QPointF(rect.left() + 6, y), QPointF(rect.right() - 6, y))
                continue
            enabled = entry.enabled()
            if (index == self.hover or (self.child is not None and self.child.isVisible() and self.child.owner_index == index)) and enabled:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(HOVER)
                p.drawRoundedRect(rect, 6, 6)
            ink = TEXT if enabled else DISABLED
            cy = rect.center().y()
            if entry.kind == "radio" and entry.is_on():
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ink)
                p.drawEllipse(QPointF(rect.left() + 13, cy), 3, 3)
            elif entry.kind == "check" and entry.is_on():
                p.setPen(QPen(ink, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                path = QPainterPath(QPointF(rect.left() + 8, cy))
                path.lineTo(rect.left() + 11.5, cy + 3.5)
                path.lineTo(rect.left() + 18, cy - 4)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            if entry.icon:
                from .glass import draw_icon
                draw_icon(p, entry.icon, QRectF(rect.left() + 24, cy - 9, 18, 18), ink)
            left = rect.left() + self.text_left() - 4
            p.setFont(text_font)
            p.setPen(ink)
            p.drawText(QRectF(left, rect.top(), rect.width(), rect.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, entry.text)
            right = rect.right() - 10
            if entry.kind == "toggle":
                self._paint_switch(p, QRectF(right - 34, cy - 9, 34, 18), entry.is_on(), enabled)
            elif entry.kind == "submenu":
                from .glass import draw_icon
                draw_icon(p, "forward", QRectF(right - 12, cy - 6, 12, 12), MUTED if enabled else DISABLED)
                detail = entry.detail() if entry.detail else ""
                if detail:
                    p.setFont(side_font)
                    p.setPen(MUTED if enabled else DISABLED)
                    p.drawText(QRectF(left, rect.top(), right - 20 - left, rect.height()),
                               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, detail)
            elif entry.shortcut:
                p.setFont(side_font)
                p.setPen(MUTED if enabled else DISABLED)
                p.drawText(QRectF(left, rect.top(), right - left, rect.height()),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, entry.shortcut)

    @staticmethod
    def _paint_switch(p, track, on, enabled):
        p.setPen(Qt.PenStyle.NoPen if on else QPen(QColor(255, 255, 255, 90), 1))
        p.setBrush(MINT if on else QColor(255, 255, 255, 16))
        if not enabled:
            p.setOpacity(.45)
        p.drawRoundedRect(track.adjusted(.5, .5, -.5, -.5), 9, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ON_MINT if on else QColor("#cfd6d2"))
        knob = QPointF(track.right() - 9 if on else track.left() + 9, track.center().y())
        p.drawEllipse(knob, 5.5 if on else 4.5, 5.5 if on else 4.5)
        p.setOpacity(1.)

    # --- acting ------------------------------------------------------------------------

    def activate(self, index):
        if not (0 <= index < len(self.entries)):
            return
        entry = self.entries[index]
        if not entry.selectable():
            return
        if entry.kind == "submenu":
            self.open_child(index, focus=True)
            return
        if entry.kind == "toggle":
            if entry.run:
                entry.run()
            self.update()
            return
        root = self.root()
        root.close()
        if entry.run:
            entry.run()

    def open_child(self, index, focus=False):
        entry = self.entries[index]
        if entry.kind != "submenu" or not entry.enabled():
            return
        if self.child is not None and self.child.isVisible() and self.child.owner_index == index:
            if focus:
                self.child.setFocus(Qt.FocusReason.PopupFocusReason)
                self.child.hover = self.child._first_from(0, 1)
                self.child.update()
            return
        self.close_child()
        rect = dict(self.rows())[index]
        self.child = RoomMenu(entry.submenu, self.parentWidget(), parent_menu=self, title=entry.text)
        self.child.owner_index = index
        self.child.closed.connect(self.update)
        anchor = self.mapToGlobal(QPointF(self.panel().right() - 2, rect.top() - self.PAD).toPoint())
        self.child.open_at(anchor)
        if focus:
            self.child.hover = self.child._first_from(0, 1)
            self.child.update()
        else:
            # Hovering into a flyout should not take the keyboard away from this menu.
            self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    def close_child(self):
        if self.child is not None:
            child, self.child = self.child, None
            child.close()
            child.deleteLater()
            self.update()

    def root(self):
        menu = self
        while menu.parent_menu is not None:
            menu = menu.parent_menu
        return menu

    def chain(self):
        menus, menu = [], self.root()
        while menu is not None and menu.isVisible():
            menus.append(menu)
            menu = menu.child
        return menus

    def _first_from(self, start, step):
        count = len(self.entries)
        for offset in range(count):
            index = (start + offset * step) % count
            if self.entries[index].selectable():
                return index
        return -1

    def _menu_at(self, global_point):
        for menu in reversed(self.chain()):
            if menu.panel().contains(QPointF(menu.mapFromGlobal(global_point))):
                return menu
        return None

    # --- events ------------------------------------------------------------------------

    def mouseMoveEvent(self, event):
        global_point = event.globalPosition().toPoint()
        menu = self._menu_at(global_point)
        if menu is not None and menu is not self:
            menu._hover_at(menu.mapFromGlobal(global_point))
            return
        if menu is self:
            self._hover_at(event.position().toPoint())

    def _hover_at(self, point):
        index = self.row_at(point)
        if index != self.hover:
            self.hover = index
            if index >= 0 and self.entries[index].kind == "submenu":
                self.open_child(index)
            elif index >= 0 and self.child is not None:
                self.close_child()
            self.update()

    def mousePressEvent(self, event):
        global_point = event.globalPosition().toPoint()
        menu = self._menu_at(global_point)
        if menu is None:
            # A click outside every open menu closes them all, like any Windows menu.
            self.root().close()
            return
        menu._pressed_inside = True
        event.accept()

    def mouseReleaseEvent(self, event):
        global_point = event.globalPosition().toPoint()
        menu = self._menu_at(global_point)
        if menu is None or not menu._pressed_inside:
            return
        menu._pressed_inside = False
        menu.activate(menu.row_at(menu.mapFromGlobal(global_point)))

    def leaveEvent(self, event):
        if self.child is None or not self.child.isVisible():
            self.hover = -1
            self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if key == Qt.Key.Key_Down else -1
            start = (self.hover + step) if self.hover >= 0 else (0 if step > 0 else len(self.entries) - 1)
            self.hover = self._first_from(start % max(1, len(self.entries)), step)
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate(self.hover)
        elif key == Qt.Key.Key_Right:
            if 0 <= self.hover < len(self.entries) and self.entries[self.hover].kind == "submenu":
                self.open_child(self.hover, focus=True)
        elif key == Qt.Key.Key_Left and self.parent_menu is not None:
            parent = self.parent_menu
            parent.close_child()
            parent.setFocus(Qt.FocusReason.PopupFocusReason)
        elif key == Qt.Key.Key_Escape:
            if self.parent_menu is not None:
                parent = self.parent_menu
                parent.close_child()
                parent.setFocus(Qt.FocusReason.PopupFocusReason)
            else:
                self.close()
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.hover = self._first_from(0, 1) if key == Qt.Key.Key_Home else self._first_from(len(self.entries) - 1, -1)
            self.update()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def closeEvent(self, event):
        self.close_child()
        super().closeEvent(event)
        self.closed.emit()


class MenuButton(QAbstractButton):
    """The room's menu key: three lines on a dark, softly lit square."""
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.c = controller
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Room menu")
        self.setToolTip("Menu  ·  rooms, lyric style, background, modes")
        self.keyboard_focus = False
        self.open = False

    def focusInEvent(self, event):
        self.keyboard_focus = keyboard_reason(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus = False
        super().focusOutEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        lit = self.open or self.isDown()
        hovered = self.underMouse()
        p.setPen(QPen(QColor(240, 232, 255, 90 if hovered or lit else 38), 1))
        p.setBrush(QColor(43, 59, 54, 230) if lit else QColor(20, 30, 27, 200 if hovered else 175))
        p.drawRoundedRect(body, 12, 12)
        p.setPen(QPen(QColor("#eef1ec"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        cx, cy = body.center().x(), body.center().y()
        for dy in (-6, 0, 6):
            p.drawLine(QPointF(cx - 8, cy + dy), QPointF(cx + 8, cy + dy))
        if self.hasFocus() and self.keyboard_focus:
            p.setPen(QPen(MINT, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(body.adjusted(-2, -2, 2, 2), 14, 14)
