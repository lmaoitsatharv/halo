"""Small native glass surfaces and controls for Halo's desktop shell."""
import math

from PySide6.QtCore import (Qt, QRectF, QPointF, QSize, Property,
                            QPropertyAnimation, QEasingCurve)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QLinearGradient,
                           QRadialGradient, QPixmap, QIcon, QFont)
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QSizePolicy, QSlider


APP_STYLE = """
QWidget { color: #f5f3fa; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; border: none; }
QLabel#eyebrow { color: #858595; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#muted { color: #999aaa; font-size: 12px; }
QLabel#title { color: #f5f3fa; font-size: 25px; font-weight: 600; }
QLabel#pageTitle { color: #f5f3fa; font-size: 30px; font-weight: 600; letter-spacing: -1px; }
QLabel#panelTitle { color: #f5f3fa; font-size: 17px; font-weight: 600; }
QLabel#badge { color: #b9d7c4; background: rgba(151, 200, 172, 13); border: 1px solid rgba(183, 220, 196, 30); border-radius: 13px; padding: 6px 11px; font-size: 10px; }
QPushButton { color: #dbd9e5; background: rgba(255,255,255,9); border: 1px solid rgba(255,255,255,22); border-radius: 10px; padding: 8px 12px; }
QPushButton:hover { background: rgba(255,255,255,18); border-color: rgba(220,209,255,70); }
QPushButton:pressed { background: rgba(255,255,255,28); }
QPushButton:disabled { color: #60606f; border-color: rgba(255,255,255,10); }
QPushButton#primary { background: #c4b4f8; color: #1b152d; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #d7caff; }
QPushButton#ghost { background: transparent; font-size: 11px; }
QPushButton:focus { border-color: #c4b4f8; }
QCheckBox { spacing: 10px; color: #d9d7e4; }
QCheckBox::indicator { width: 30px; height: 17px; border-radius: 8px; background: #3a3945; border: 1px solid #4a4859; }
QCheckBox::indicator:checked { background: #c4b4f8; border-color: #d9ceff; }
QSlider { background: transparent; border: none; }
QSlider::groove:horizontal { border: 0px solid transparent; height: 3px; background: rgba(223,217,241,28); border-radius: 1px; }
QSlider::sub-page:horizontal { border: 0px solid transparent; height: 3px; background: #c4b4f8; border-radius: 1px; }
QSlider::handle:horizontal { width: 9px; margin: -4px 0; border-radius: 4px; background: #f1eaff; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider:disabled::sub-page:horizontal { background: #55515f; }
QComboBox { color: #d9d6e8; background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,22); border-radius: 10px; padding: 7px 12px; font-size: 11px; }
QComboBox:hover { border-color: rgba(211,192,255,85); background: rgba(255,255,255,13); }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox QAbstractItemView { background: #202029; color: #eeeaf7; border: 1px solid #45414f; selection-background-color: #423952; padding: 5px; outline: none; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: #46434f; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLineEdit, QPlainTextEdit, QListWidget { color: #e6e1ef; background: #19191f; border: 1px solid #3a3644; border-radius: 10px; padding: 9px; selection-background-color: #514164; }
QListWidget::item { padding: 10px; border-radius: 7px; }
QListWidget::item:selected { background: #3b304e; }
QMenu { background: #1c1b24; color: #e7e1ef; border: 1px solid #423b4e; padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 5px; }
QMenu::item:selected { background: #3b304e; }
QToolTip { color: #eee9f8; background: #292530; border: 1px solid #50455e; padding: 6px; }
QSizeGrip { width: 12px; height: 12px; background: transparent; }
"""


def colour(value, opacity):
    result = QColor(value)
    result.setAlpha(max(0, min(255, int(opacity))))
    return result


def draw_icon(p, kind, rect, ink):
    """Draw a consistent family of original, resolution-independent line icons."""
    p.save()
    p.translate(rect.center())
    scale = min(rect.width(), rect.height()) / 24
    p.scale(scale, scale)
    p.setPen(QPen(ink, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "listening":
        for x, y in ((-8, -8), (2, -8), (-8, 2), (2, 2)):
            p.drawRoundedRect(QRectF(x, y, 6, 6), 1.6, 1.6)
    elif kind == "modes":
        p.save()
        p.rotate(-9)
        p.drawRoundedRect(QRectF(-7, -7, 12, 15), 2, 2)
        p.restore()
        p.drawRoundedRect(QRectF(-3, -9, 12, 15), 2, 2)
        p.drawLine(QPointF(1, -4), QPointF(5, -4))
    elif kind == "lyrics":
        for y, w in ((-6, 15), (0, 11), (6, 14)):
            p.drawLine(QPointF(-7, y), QPointF(-7 + w, y))
    elif kind == "halo":
        p.drawEllipse(QRectF(-6, -6, 12, 12))
        for i in range(8):
            angle = i * math.pi / 4
            p.drawLine(QPointF(math.cos(angle) * 9, math.sin(angle) * 9),
                       QPointF(math.cos(angle) * 10.5, math.sin(angle) * 10.5))
    elif kind == "settings":
        path = QPainterPath()
        for i in range(48):
            a = i * math.pi / 24
            r = 9 if i % 6 in (1, 2, 3, 4) else 7.2
            point = QPointF(math.cos(a) * r, math.sin(a) * r)
            path.moveTo(point) if i == 0 else path.lineTo(point)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QRectF(-3, -3, 6, 6))
    elif kind in ("fullscreen", "scenes"):
        for x, y in ((-8, -7), (8, -7), (-8, 7), (8, 7)):
            p.drawLine(QPointF(x, y), QPointF(x + (5 if x < 0 else -5), y))
            p.drawLine(QPointF(x, y), QPointF(x, y + (4 if y < 0 else -4)))
    elif kind == "arrow":
        p.drawLine(QPointF(-5, 5), QPointF(6, -6))
        p.drawLine(QPointF(-2, -6), QPointF(6, -6))
        p.drawLine(QPointF(6, -6), QPointF(6, 2))
    elif kind == "back":
        p.drawLine(QPointF(5, -6), QPointF(-2, 0))
        p.drawLine(QPointF(-2, 0), QPointF(5, 6))
    elif kind == "import":
        p.drawLine(QPointF(0, -8), QPointF(0, 3))
        p.drawLine(QPointF(-4, -1), QPointF(0, 3))
        p.drawLine(QPointF(4, -1), QPointF(0, 3))
        path = QPainterPath(QPointF(-8, 3))
        path.lineTo(-8, 8)
        path.lineTo(8, 8)
        path.lineTo(8, 3)
        p.drawPath(path)
    elif kind == "wave":
        for x, h in ((-8, 4), (-4, 10), (0, 16), (4, 8), (8, 4)):
            p.drawLine(QPointF(x, -h / 2), QPointF(x, h / 2))
    elif kind == "refresh":
        p.drawArc(QRectF(-7, -7, 14, 14), 40 * 16, 290 * 16)
        p.drawLine(QPointF(7, -7), QPointF(7, -1))
        p.drawLine(QPointF(7, -1), QPointF(1, -1))
    elif kind == "close":
        p.drawLine(QPointF(-5, -5), QPointF(5, 5))
        p.drawLine(QPointF(5, -5), QPointF(-5, 5))
    elif kind == "play":
        path = QPainterPath(QPointF(-3, -6))
        path.lineTo(6, 0)
        path.lineTo(-3, 6)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawPath(path)
    p.restore()


def icon(kind, ink="#aaa4bb", size=22):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, kind, QRectF(0, 0, size, size), QColor(ink))
    p.end()
    return QIcon(pixmap)


class GlassPanel(QFrame):
    """Layered translucent material; light comes from the app's backdrop."""
    def __init__(self, parent=None, radius=22, variant="normal"):
        super().__init__(parent)
        self.radius, self.variant = radius, variant
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.radius, self.radius)
        p.setClipPath(path)
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        opacity = {"player": (238, 245), "sheet": (252, 255)}.get(self.variant, (205, 210))
        base.setColorAt(0, QColor(32, 32, 42, opacity[0]))
        base.setColorAt(1, QColor(17, 18, 25, opacity[1]))
        p.fillPath(path, base)
        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0, QColor(238, 228, 255, 7))
        sheen.setColorAt(.45, QColor(238, 228, 255, 1))
        sheen.setColorAt(1, QColor(255, 255, 255, 3))
        p.fillPath(path, sheen)
        p.setClipping(False)
        border = QLinearGradient(rect.topLeft(), rect.bottomRight())
        border.setColorAt(0, QColor(235, 224, 255, 42))
        border.setColorAt(.5, QColor(235, 224, 255, 13))
        border.setColorAt(1, QColor(235, 224, 255, 25))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(border, 1))
        p.drawPath(path)


class GlassButton(QPushButton):
    """One animated hover value, no perpetual animation or layout movement."""
    def __init__(self, text="", parent=None, controller=None, variant=None):
        super().__init__(text, parent)
        self.c, self.variant = controller, variant
        self._hover = 0.
        self.animation = QPropertyAnimation(self, b"hover", self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if controller is not None and hasattr(controller, "settingChanged"):
            controller.settingChanged.connect(self._settle_motion)

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = float(value)
        self.update()

    hover = Property(float, get_hover, set_hover)

    def _animate(self, value):
        self.animation.stop()
        if self.c is not None and self.c.reduced_motion:
            self.set_hover(value)
        else:
            self.animation.setStartValue(self._hover)
            self.animation.setEndValue(value)
            self.animation.start()

    def _settle_motion(self):
        if self.c is not None and self.c.reduced_motion:
            self.animation.stop()
            self.set_hover(1. if self.underMouse() else 0.)

    def enterEvent(self, event):
        self._animate(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(0.)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.animation.stop()
        self._hover = 0.
        super().hideEvent(event)

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self.text()) + 28
        if not self.icon().isNull():
            width += self.iconSize().width() + (8 if self.text() else -4)
        return QSize(max(34, width), 36 if self.variant != "nav" else 44)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        variant = self.variant or self.objectName()
        h = self._hover if self.isEnabled() else 0.
        selected = self.isCheckable() and self.isChecked()
        radius = 11 if variant != "nav" else 12
        if variant == "primary":
            fill = QColor.fromRgbF(.77 + h * .07, .71 + h * .07, .97)
            ink = QColor("#20182f")
            border = QColor(255, 255, 255, 90)
        elif variant == "nav":
            fill = QColor(196, 180, 248, (25 if selected else 0) + round(h * 14))
            ink = QColor("#ede7ff" if selected else "#a09aaa")
            border = QColor(213, 199, 255, 42 if selected else 0)
        else:
            fill = QColor(255, 255, 255, (4 if variant == "ghost" else 9) + round(h * 13))
            ink = QColor("#e1dcea")
            border = QColor(223, 211, 255, 20 + round(h * 40))
        if self.isDown():
            fill = fill.darker(125)
        if not self.isEnabled():
            ink = QColor("#65616f")
            fill.setAlpha(4)
            border.setAlpha(12)
        p.setPen(QPen(border, 1))
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#c4b4f8"), 1.2))
            p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
        font = self.font()
        font.setPixelSize(12 if variant != "primary" else 12)
        font.setWeight(QFont.Weight.Medium if selected or variant == "primary" else QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(ink)
        icon_width = self.iconSize().width() if not self.icon().isNull() else 0
        text_width = p.fontMetrics().horizontalAdvance(self.text())
        total = text_width + (icon_width + 9 if icon_width and self.text() else icon_width)
        x = 14 if variant == "nav" else (self.width() - total) / 2
        if icon_width:
            self.icon().paint(p, int(x), int((self.height() - icon_width) / 2), icon_width, icon_width,
                              Qt.AlignmentFlag.AlignCenter,
                              QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled)
            x += icon_width + 9
        p.drawText(QRectF(x, 0, max(1, self.width() - x - 8), self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())


class DesktopBackdrop(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.background = QPixmap()
        self.background_key = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        c = self.controller
        key = (self.width(), self.height(), c.primary.rgba(), c.secondary.rgba(), self.isMaximized(), self.isFullScreen())
        if key != self.background_key:
            self.background_key = key
            self.background = QPixmap(self.size())
            self.background.fill(QColor("#0e0f15"))
            p = QPainter(self.background)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
            path = QPainterPath()
            path.addRect(rect)
            p.setClipPath(path)
            p.fillRect(rect, QColor("#0e0f15"))
            for x, y, color, opacity, radius in ((.64, -.15, QColor("#8470bf"), 32, .75),
                                                (1., .8, c.secondary, 20, .62),
                                                (.3, 1., c.primary, 13, .6)):
                gradient = QRadialGradient(self.width() * x, self.height() * y, self.width() * radius)
                gradient.setColorAt(0, colour(color, opacity))
                gradient.setColorAt(1, colour(color, 0))
                p.fillRect(rect, gradient)
            p.setClipping(False)
            p.setPen(QPen(QColor(233, 225, 255, 38), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.end()
        p = QPainter(self)
        p.drawPixmap(0, 0, self.background)

class GlassSlider(QSlider):
    """A fine native timeline, with direct dragging and keyboard seeking."""
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(65)
        self.setFixedHeight(24)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, y = 6., self.width() - 6., self.height() / 2
        progress = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        x = left + (right - left) * progress
        p.setPen(QPen(QColor(221, 209, 245, 32), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(left, y), QPointF(right, y))
        p.setPen(QPen(QColor("#b9a8e7" if self.isEnabled() else "#55505f"), 3,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(left, y), QPointF(x, y))
        if self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f0e7ff"))
            r = 4.5 if self.underMouse() or self.isSliderDown() or self.hasFocus() else 3.2
            p.drawEllipse(QPointF(x, y), r, r)
        if self.hasFocus():
            p.setPen(QPen(QColor(196, 180, 248, 100), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 6, 6)

    def _point_value(self, point):
        position = min(1., max(0., (point.x() - 6) / max(1, self.width() - 12)))
        self.setValue(round(self.minimum() + position * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            self._point_value(event.position())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self._point_value(event.position())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown() and event.button() == Qt.MouseButton.LeftButton:
            self._point_value(event.position())
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                           Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self.sliderReleased.emit()

    def wheelEvent(self, event):
        super().wheelEvent(event)
        self.sliderReleased.emit()


class SeekSlider(GlassSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)

