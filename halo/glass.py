"""Native gallery-wall surfaces and controls for Halo's desktop shell.

The module keeps its historical name; the material is now a painted wall with
white cards and physical buttons rather than dark glass.
"""
import math

from PySide6.QtCore import (Qt, QRectF, QPointF, QSize, Property,
                            QPropertyAnimation, QEasingCurve)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QLinearGradient,
                           QPixmap, QIcon, QFont, QImage)
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QSizePolicy, QSlider

from .gallery import (INK, INK_SOFT, INK_MUTED, CARD, FOCUS, HANDSET_INK, MINT, ON_INK, WHITE,
                      tint, mix, paint_shadow, paint_focus, paint_wall, paint_spotlight, keyboard_reason)
from .theme import hexc, pick, line_icon


APP_STYLE = """
QWidget { color: #1c2a26; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; border: none; }
QLabel#eyebrow { color: #55625e; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#muted { color: #55625e; font-size: 12px; }
QLabel#title { color: #1c2a26; font-size: 25px; font-weight: 600; }
QLabel#pageTitle { color: #1c2a26; font-size: 30px; font-weight: 600; letter-spacing: -1px; }
QLabel#panelTitle { color: #1c2a26; font-size: 17px; font-weight: 600; }
QLabel#badge { color: #2f5a4f; font-size: 11px; }
QPushButton { color: #1c2a26; background: #ffffff; border: 1px solid rgba(28,42,38,46); border-radius: 10px; padding: 8px 12px; }
QPushButton:hover { background: #fbfcfa; border-color: rgba(28,42,38,90); }
QPushButton:pressed { background: #eaefe9; }
QPushButton:disabled { color: #8d9894; border-color: rgba(28,42,38,22); }
QPushButton#primary { background: #1c2a26; color: #f2f4ef; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #2b3b36; }
QPushButton#ghost { background: transparent; border-color: transparent; font-size: 12px; }
QPushButton:focus { border: 2px solid #2f7d6d; }
QCheckBox { spacing: 10px; color: #1c2a26; }
QCheckBox::indicator { width: 30px; height: 17px; border-radius: 8px; background: #c9d2cc; border: 1px solid #b3bdb7; }
QCheckBox::indicator:checked { background: #2f7d6d; border-color: #2f7d6d; }
QSlider { background: transparent; border: none; }
QSlider::groove:horizontal { border: 0px solid transparent; height: 4px; background: rgba(28,42,38,40); border-radius: 2px; }
QSlider::sub-page:horizontal { border: 0px solid transparent; height: 4px; background: #2f7d6d; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -6px 0; border-radius: 7px; background: #ffffff; border: 1px solid rgba(28,42,38,80); }
QSlider::handle:horizontal:hover { border-color: #1c2a26; }
QSlider:disabled::sub-page:horizontal { background: #a7b1ac; }
QComboBox { color: #1c2a26; background: #ffffff; border: 1px solid rgba(28,42,38,50); border-radius: 10px; padding: 7px 12px; font-size: 12px; }
QComboBox:hover { border-color: rgba(28,42,38,100); }
QComboBox:focus { border: 2px solid #2f7d6d; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #ffffff; color: #1c2a26; border: 1px solid rgba(28,42,38,60); selection-background-color: #dcebe3; selection-color: #1c2a26; padding: 5px; outline: none; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(28,42,38,70); border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(28,42,38,120); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLineEdit, QPlainTextEdit, QListWidget { color: #1c2a26; background: #ffffff; border: 1px solid rgba(28,42,38,50); border-radius: 10px; padding: 9px; selection-background-color: #bfe0d2; selection-color: #1c2a26; }
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus { border: 2px solid #2f7d6d; }
QListWidget::item { padding: 10px; border-radius: 7px; }
QListWidget::item:selected { background: #dcebe3; color: #1c2a26; }
QMenu { background: #ffffff; color: #1c2a26; border: 1px solid rgba(28,42,38,60); padding: 6px; }
QMenu::item { padding: 8px 20px; border-radius: 5px; }
QMenu::item:selected { background: #dcebe3; }
QMenu::separator { height: 1px; background: rgba(28,42,38,30); margin: 5px 8px; }
QToolTip { color: #f2f4ef; background: #1c2a26; border: 0; padding: 6px 8px; }
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
    p.setPen(QPen(ink, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "listening":
        # A framed picture: the room where the song hangs.
        p.drawRect(QRectF(-8, -8, 16, 16))
        p.drawRect(QRectF(-4.5, -4.5, 9, 9))
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
    elif kind == "exit-fullscreen":
        # The Immersive key turned inside out: four corners folding in towards the middle.
        for sx in (-1, 1):
            for sy in (-1, 1):
                corner = QPointF(sx * 3, sy * 3)
                p.drawLine(corner, QPointF(sx * 3, sy * 8))
                p.drawLine(corner, QPointF(sx * 8, sy * 3))
    elif kind == "arrow":
        p.drawLine(QPointF(-5, 5), QPointF(6, -6))
        p.drawLine(QPointF(-2, -6), QPointF(6, -6))
        p.drawLine(QPointF(6, -6), QPointF(6, 2))
    elif kind == "back":
        p.drawLine(QPointF(5, -6), QPointF(-2, 0))
        p.drawLine(QPointF(-2, 0), QPointF(5, 6))
    elif kind == "forward":
        p.drawLine(QPointF(-3, -6), QPointF(4, 0))
        p.drawLine(QPointF(4, 0), QPointF(-3, 6))
    elif kind == "import":
        p.drawLine(QPointF(0, -8), QPointF(0, 3))
        p.drawLine(QPointF(-4, -1), QPointF(0, 3))
        p.drawLine(QPointF(4, -1), QPointF(0, 3))
        path = QPainterPath(QPointF(-8, 3))
        path.lineTo(-8, 8)
        path.lineTo(8, 8)
        path.lineTo(8, 3)
        p.drawPath(path)
    elif kind == "save":
        p.drawLine(QPointF(0, -8), QPointF(0, 3))
        p.drawLine(QPointF(-4, -1), QPointF(0, 3))
        p.drawLine(QPointF(4, -1), QPointF(0, 3))
        p.drawLine(QPointF(-8, 8), QPointF(8, 8))
    elif kind == "share":
        # A card leaving the frame.
        path = QPainterPath(QPointF(-3, -4))
        path.lineTo(-8, -4)
        path.lineTo(-8, 8)
        path.lineTo(4, 8)
        path.lineTo(4, 3)
        p.drawPath(path)
        p.drawLine(QPointF(-2, 2), QPointF(8, -8))
        p.drawLine(QPointF(2, -8), QPointF(8, -8))
        p.drawLine(QPointF(8, -8), QPointF(8, -2))
    elif kind == "mini":
        p.drawRoundedRect(QRectF(-9, -7, 18, 14), 2, 2)
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(0, 0, 6, 4), 1, 1)
    elif kind == "copy":
        p.drawRoundedRect(QRectF(-4, -8, 12, 13), 2, 2)
        path = QPainterPath(QPointF(-4, -3))
        path.lineTo(-8, -3)
        path.lineTo(-8, 8)
        path.lineTo(3, 8)
        path.lineTo(3, 5)
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
    elif kind == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawRoundedRect(QRectF(-6, -7, 4, 14), 1, 1)
        p.drawRoundedRect(QRectF(2, -7, 4, 14), 1, 1)
    elif kind.startswith("toward-"):
        # A direction for lyric placement: "toward-<degrees>", 0 pointing up, clockwise.
        p.rotate(float(kind.split("-", 1)[1]))
        p.drawLine(QPointF(0, 7), QPointF(0, -7))
        p.drawLine(QPointF(-5, -2), QPointF(0, -7))
        p.drawLine(QPointF(5, -2), QPointF(0, -7))
    elif kind == "centre":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QPointF(0, 0), 3.5, 3.5)
    elif kind == "image":
        # A picture: a frame, a hill and a sun.
        p.drawRoundedRect(QRectF(-9, -7, 18, 14), 2, 2)
        path = QPainterPath(QPointF(-8, 6))
        path.lineTo(-2, 0)
        path.lineTo(2, 4)
        path.lineTo(5, 1)
        path.lineTo(8.5, 5)
        p.drawPath(path)
        p.drawEllipse(QPointF(3.5, -3), 1.6, 1.6)
    elif kind == "restore":
        # Back to the full window: an arrow out of a small frame.
        p.drawRoundedRect(QRectF(-9, -2, 11, 10), 1.5, 1.5)
        p.drawLine(QPointF(-1, 0), QPointF(8, -9))
        p.drawLine(QPointF(2, -9), QPointF(8, -9))
        p.drawLine(QPointF(8, -9), QPointF(8, -3))
    p.restore()


def icon(kind, ink="#1c2a26", size=22):
    """A drawn line icon; its ink follows the light (dark ink on the light wall, light ink after hours)."""
    return line_icon(kind, ink)


class GlassPanel(QFrame):
    """A white card hung on the wall; the "player" variant is the dark audio-guide handset."""
    def __init__(self, parent=None, radius=22, variant="normal"):
        super().__init__(parent)
        self.radius, self.variant = radius, variant
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def body_rect(self):
        if self.variant == "player":
            return QRectF(self.rect()).adjusted(4, 2, -4, -8)
        return QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.body_rect()
        if self.variant == "player":
            paint_shadow(p, rect, self.radius, 12, .34, 5)
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0, hexc("#24342f"))
            fill.setColorAt(1, hexc("#1a2723"))
            p.setPen(QPen(QColor(pick("#0f1715", "#070b0a")), 1))
            p.setBrush(fill)
            p.drawRoundedRect(rect, self.radius, self.radius)
            p.setPen(QPen(tint(WHITE, pick(26, 30)), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self.radius - 1, self.radius - 1)
            return
        if self.variant == "sheet":
            paint_shadow(p, rect, self.radius, 18, .3, 8)
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setPen(QPen(tint(INK, 22), 1))
        p.setBrush(CARD)
        p.drawRoundedRect(rect, self.radius, self.radius)


class GlassButton(QPushButton):
    """A physical button: it sits raised on the wall and sinks when pressed."""
    def __init__(self, text="", parent=None, controller=None, variant=None):
        super().__init__(text, parent)
        self.c, self.variant = controller, variant
        self._hover = 0.
        self.animation = QPropertyAnimation(self, b"hover", self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.keyboard_focus = False
        if controller is not None and hasattr(controller, "settingChanged"):
            controller.settingChanged.connect(self._settle_motion)

    def focusInEvent(self, event):
        self.keyboard_focus = keyboard_reason(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus = False
        super().focusOutEvent(event)

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
        width = self.fontMetrics().horizontalAdvance(self.text()) + 30
        if not self.icon().isNull():
            width += self.iconSize().width() + (8 if self.text() else -4)
        return QSize(max(38, width), 40 if self.variant != "nav" else 46)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        variant = self.variant or self.objectName()
        h = self._hover if self.isEnabled() else 0.
        down = self.isDown()
        selected = self.isCheckable() and self.isChecked()
        # Disclosures open and close; only choices among options take the chosen outline.
        chosen = selected and self.objectName() != "backgroundDisclosure"
        radius = 11
        body = QRectF(self.rect()).adjusted(2, 2, -2, -4)
        if variant == "ghost" or variant == "nav" and not selected:
            if down:
                body.translate(0, 1)
                fill, border = tint(INK, 22), Qt.PenStyle.NoPen
            elif h > .01:
                fill, border = tint(INK, 12 * h), Qt.PenStyle.NoPen
            else:
                fill, border = QColor(0, 0, 0, 0), Qt.PenStyle.NoPen
            ink = QColor(INK if h > .5 or selected else INK_SOFT)
            p.setPen(border)
            p.setBrush(fill)
            p.drawRoundedRect(body, radius, radius)
        else:
            primary = variant == "primary"
            if not self.isEnabled():
                fill, ink, edge = tint(INK, 10), tint(INK_MUTED, 150), tint(INK, 18)
            else:
                if down:
                    body.translate(0, 1)
                elif selected:
                    body.translate(0, -1)
                    paint_shadow(p, body, radius, 9, .24, 3)
                else:
                    paint_shadow(p, body, radius, 5 + 3 * h, .15 + .07 * h, 2 + h)
                if primary:
                    fill = hexc("#15201d") if down else mix(INK, hexc("#2f403a"), h)
                    ink, edge = QColor(ON_INK), hexc("#0f1715")
                else:
                    fill = hexc("#eaefe9") if down else mix(CARD, hexc("#f9fbf8"), h)
                    ink, edge = QColor(INK), tint(INK, pick(34, 26) + 30 * h)
                    if chosen:
                        # A chosen option is outlined in ink, like a chosen mode card.
                        edge = QColor(INK)
            p.setPen(QPen(edge, 2 if chosen and self.isEnabled() and not primary else 1))
            p.setBrush(fill)
            p.drawRoundedRect(body, radius, radius)
            if self.isEnabled() and not down and not primary:
                p.setPen(QPen(tint(WHITE, pick(255, 22)), 1))
                p.drawLine(QPointF(body.left() + radius, body.top() + 1), QPointF(body.right() - radius, body.top() + 1))
        if self.hasFocus() and self.keyboard_focus:
            paint_focus(p, body, radius)
        font = self.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold if selected or variant == "primary" else QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(ink)
        icon_width = self.iconSize().width() if not self.icon().isNull() else 0
        text_width = p.fontMetrics().horizontalAdvance(self.text())
        total = text_width + (icon_width + 8 if icon_width and self.text() else icon_width)
        x = body.left() + 14 if variant == "nav" else body.center().x() - total / 2
        if icon_width:
            self.icon().paint(p, int(x), int(body.center().y() - icon_width / 2), icon_width, icon_width,
                              Qt.AlignmentFlag.AlignCenter,
                              QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled)
            x += icon_width + 8
        if self.text():
            p.drawText(QRectF(x, body.top(), max(1, body.right() - x), body.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())


class DesktopBackdrop(QWidget):
    """The painted wall behind every page; a subclass may hang a spotlight on it."""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.background = QPixmap()
        self.background_key = None
        self.light_image = QImage()
        self.light_key = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def spotlight(self):
        """(centre, radius, strength, drift) in this widget's coordinates, or None."""
        return None

    def theme_changed(self):
        self.background_key = None
        self.light_key = None

    @staticmethod
    def spotlight_bounds(centre, radius):
        return QRectF(centre.x() - radius * 1.35, centre.y() - radius * 1.35, radius * 2.7, radius * 2.7)

    def _light(self, radius, strength, drift):
        """The spotlight at quarter resolution: soft gradients scale up without visible loss."""
        c = self.controller
        primary = getattr(c, "halo_primary", c.primary)
        secondary = getattr(c, "halo_secondary", c.secondary)
        size = max(8, round(radius * 2.7 / 4))
        key = (size, round(strength * 96), round(drift * 20), primary.rgba(), secondary.rgba())
        if key != self.light_key:
            image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            p = QPainter(image)
            paint_spotlight(p, QPointF(size / 2, size / 2), size / 2.7, primary, secondary, strength, drift)
            p.end()
            self.light_image, self.light_key = image, key
        return self.light_image

    def paintEvent(self, event):
        key = (self.width(), self.height())
        if key != self.background_key:
            self.background_key = key
            self.background = QPixmap(self.size())
            p = QPainter(self.background)
            paint_wall(p, QRectF(self.rect()))
            p.end()
        p = QPainter(self)
        p.setClipRect(event.rect())
        p.drawPixmap(0, 0, self.background)
        light = self.spotlight()
        if light is not None:
            centre, radius, strength, drift = light
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(self.spotlight_bounds(centre, radius), self._light(radius, strength, drift))


class GlassSlider(QSlider):
    """A clear timeline on the wall, with direct dragging and keyboard seeking."""
    track_colour = None
    fill_colour = FOCUS
    thumb_colour = None
    dark = False

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(65)
        self.setFixedHeight(26)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right, y = 8., self.width() - 8., self.height() / 2
        progress = (self.value() - self.minimum()) / max(1, self.maximum() - self.minimum())
        x = left + (right - left) * progress
        track = self.track_colour if self.track_colour is not None else tint(INK, pick(40, 46))
        p.setPen(QPen(track, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(left, y), QPointF(right, y))
        fill = self.fill_colour if self.isEnabled() else tint(INK_MUTED, 110)
        p.setPen(QPen(fill, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(left, y), QPointF(x, y))
        if self.isEnabled():
            r = 7.5 if self.underMouse() or self.isSliderDown() or self.hasFocus() else 6.
            paint_shadow(p, QRectF(x - r, y - r, r * 2, r * 2), r, 3, .4 if self.dark else .25, 1)
            p.setPen(QPen(tint(INK, 70) if not self.dark else Qt.PenStyle.NoPen, 1) if not self.dark else Qt.PenStyle.NoPen)
            p.setBrush(self.thumb_colour if self.thumb_colour is not None else QColor(pick("#ffffff", "#e6ece6")))
            p.drawEllipse(QPointF(x, y), r, r)
        if self.hasFocus():
            p.setPen(QPen(MINT if self.dark else FOCUS, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)

    def _point_value(self, point):
        position = min(1., max(0., (point.x() - 8) / max(1, self.width() - 16)))
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
    """The handset's timeline: light on dark, mint for what has played."""
    track_colour = tint(HANDSET_INK, 46)
    fill_colour = MINT
    thumb_colour = HANDSET_INK
    dark = True

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
