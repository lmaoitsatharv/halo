"""Gallery wall: Halo's light listening room.

The wall stays quiet; the only saturated colour is the spotlight, taken from
the song. Controls are physical: a selected control lifts, a pressed one sinks.
"""
import math
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QLinearGradient, QRadialGradient,
                           QImage, QFont, QFontMetricsF)
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QSizePolicy

from .theme import hexc, is_dark


WALL = QColor("#e7ece6")
WALL_TOP = QColor("#eef2ed")
WALL_LOW = QColor("#dce3dc")
INK = QColor("#1c2a26")
INK_SOFT = QColor("#3e4c47")
INK_MUTED = QColor("#55625e")
CARD = QColor("#ffffff")
MAT = QColor("#f8f7f2")
FRAME = QColor("#1c2a26")
HANDSET = QColor("#1c2a26")
HANDSET_RAISED = QColor("#2b3b36")
HANDSET_INK = QColor("#f2f4ef")
HANDSET_MUTED = QColor("#aab7b1")
MINT = QColor("#b7e4ad")
MINT_TOP = QColor("#d3f1cb")
FOCUS = QColor("#2f7d6d")
# The house green, dark enough for text on the wall and on cards.
ACCENT_INK = QColor("#24685b")
# What casts shadows and recesses: green-black on the light wall, black after hours.
SHADOW = QColor("#1c2a26")
# Lettering on ink-filled controls.
ON_INK = QColor("#f2f4ef")
# Plain white light: glare, highlights and keys. It never changes with the wall.
WHITE = QColor("#ffffff")

DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI"]
TEXT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI"]


def face(pixels, weight=QFont.Weight.Normal, display=False):
    result = QFont()
    result.setFamilies(DISPLAY_FAMILIES if display else TEXT_FAMILIES)
    result.setPixelSize(max(1, round(pixels)))
    result.setWeight(weight)
    return result


def tint(colour, opacity):
    result = QColor(colour)
    result.setAlpha(max(0, min(255, round(opacity))))
    return result


def mix(a, b, amount):
    amount = max(0., min(1., amount))
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(*(x + (y - x) * amount for x, y in zip(a.getRgbF(), b.getRgbF())))


def luminance(colour):
    def channel(value):
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    colour = QColor(colour)
    return .2126 * channel(colour.redF()) + .7152 * channel(colour.greenF()) + .0722 * channel(colour.blueF())


def contrast(a, b):
    first, second = sorted((luminance(a), luminance(b)), reverse=True)
    return (first + .05) / (second + .05)


def spotlight_colour(colour):
    """A song colour lifted into light: never muddy, never neon, always readable as light on the wall."""
    hue, saturation, lightness, _ = QColor(colour).getHslF()
    if hue < 0 or saturation < .06:
        hue, saturation = .36, .32
    saturation = min(.9, max(.52, saturation))
    lightness = min(.7, max(.56, lightness))
    return QColor.fromHslF(hue, saturation, lightness)


def song_light(controller):
    """The current song's light, or the house mint before any song has coloured the room."""
    source = getattr(controller, "halo_primary", None) if controller is not None else None
    return spotlight_colour(source) if source is not None else QColor(MINT)


def ink_accent(colour, ground=WALL, target=4.6):
    """The song's hue, dark enough to read on a light wall, or light enough on a dark one."""
    hue, saturation, _, _ = QColor(colour).getHslF()
    if hue < 0 or saturation < .06:
        return QColor(ACCENT_INK)
    saturation = min(.8, max(.48, saturation))
    if luminance(ground) < .18:
        lightness, step, limit = .6, .02, .94
    else:
        lightness, step, limit = .46, -.02, .08
    candidate = QColor.fromHslF(hue, saturation, lightness)
    while contrast(candidate, ground) < target and (lightness < limit if step > 0 else lightness > limit):
        lightness += step
        candidate = QColor.fromHslF(hue, saturation, lightness)
    return candidate


# --- soft shadows -----------------------------------------------------------

_SHADOWS = OrderedDict()


def _box(values, radius, axis):
    if radius < 1:
        return values
    pads = [(0, 0), (0, 0)]
    pads[axis] = (radius + 1, radius)
    padded = np.pad(values, pads)
    total = np.cumsum(padded, axis=axis, dtype=np.float32)
    width = 2 * radius + 1
    if axis == 0:
        return (total[width:, :] - total[:-width, :]) / width
    return (total[:, width:] - total[:, :-width]) / width


def shadow_image(width, height, radius, blur, opacity, colour=SHADOW):
    """A blurred rounded-rect shadow, cached by size; drawn offset beneath a raised surface."""
    width, height = max(1, round(width)), max(1, round(height))
    blur = max(1, round(blur))
    key = (width, height, round(radius), blur, round(opacity * 255), QColor(colour).rgba())
    cached = _SHADOWS.get(key)
    if cached is not None:
        _SHADOWS.move_to_end(key)
        return cached
    pad = blur * 2 + 2
    w, h = width + pad * 2, height + pad * 2
    mask = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(0)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0))
    painter.drawRoundedRect(QRectF(pad, pad, width, height), radius, radius)
    painter.end()
    stride = mask.bytesPerLine() // 4
    alpha = np.frombuffer(mask.constBits(), np.uint8).reshape(h, stride, 4)[:, :w, 3].astype(np.float32)
    step = max(1, blur // 2)
    for _ in range(3):
        alpha = _box(_box(alpha, step, 0), step, 1)
    alpha = np.clip(alpha * opacity, 0, 255).astype(np.uint8)
    tone = QColor(colour)
    pixels = np.zeros((h, w, 4), np.uint8)
    # Premultiplied BGRA, the byte order Qt uses for ARGB32 on little-endian Windows.
    pixels[..., 0] = (alpha.astype(np.uint16) * tone.blue() // 255).astype(np.uint8)
    pixels[..., 1] = (alpha.astype(np.uint16) * tone.green() // 255).astype(np.uint8)
    pixels[..., 2] = (alpha.astype(np.uint16) * tone.red() // 255).astype(np.uint8)
    pixels[..., 3] = alpha
    image = QImage(pixels.tobytes(), w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
    _SHADOWS[key] = (image, pad)
    while len(_SHADOWS) > 160:
        _SHADOWS.popitem(last=False)
    return image, pad


def paint_shadow(p, rect, radius=12, blur=10, opacity=.22, dy=4, colour=SHADOW):
    rect = QRectF(rect)
    if luminance(WALL) < .18:
        # Shadows on a dark wall need more weight to read at all.
        opacity = min(.92, opacity * 1.6)
    image, pad = shadow_image(rect.width(), rect.height(), radius, blur, opacity, colour)
    p.drawImage(QPointF(rect.x() - pad, rect.y() - pad + dy), image)


# --- the wall ---------------------------------------------------------------

_GRAIN = None


def reset_wall():
    """Forget the cached grain, so the next wall is painted in the current light."""
    global _GRAIN
    _GRAIN = None


def grain_tile():
    """A fine, deterministic plaster grain so the wall never reads as a flat fill."""
    global _GRAIN
    if _GRAIN is None:
        size = 192
        rng = np.random.default_rng(7)
        alpha = (rng.random((size, size)) ** 6 * 15).astype(np.uint8)
        pixels = np.zeros((size, size, 4), np.uint8)
        pixels[..., 0] = (alpha.astype(np.uint16) * INK.blue() // 255).astype(np.uint8)
        pixels[..., 1] = (alpha.astype(np.uint16) * INK.green() // 255).astype(np.uint8)
        pixels[..., 2] = (alpha.astype(np.uint16) * INK.red() // 255).astype(np.uint8)
        pixels[..., 3] = alpha
        _GRAIN = QImage(pixels.tobytes(), size, size, size * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
    return _GRAIN


def paint_wall(p, rect):
    rect = QRectF(rect)
    wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    wash.setColorAt(0, WALL_TOP)
    wash.setColorAt(.62, WALL)
    wash.setColorAt(1, WALL_LOW)
    p.fillRect(rect, wash)
    # A faint falloff toward the corners, so the spotlight reads as light rather than paint.
    falloff = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * .72)
    dark = luminance(WALL) < .18
    falloff.setColorAt(.55, tint(SHADOW, 0))
    falloff.setColorAt(1, tint(SHADOW, 90 if dark else 20))
    p.fillRect(rect, falloff)
    tile = grain_tile()
    p.save()
    p.setClipRect(rect)
    y = rect.top()
    while y < rect.bottom():
        x = rect.left()
        while x < rect.right():
            p.drawImage(QPointF(x, y), tile)
            x += tile.width()
        y += tile.height()
    p.restore()


def paint_spotlight(p, centre, radius, primary, secondary, strength=1., drift=0.):
    """The song's light on the wall: one pool, plus two fainter layers drifting at different speeds."""
    if radius <= 1 or strength <= 0:
        return
    spot = spotlight_colour(primary)
    second = spotlight_colour(secondary)
    centre = QPointF(centre)
    bounds = QRectF(centre.x() - radius * 1.35, centre.y() - radius * 1.35, radius * 2.7, radius * 2.7)
    pool = QRadialGradient(centre, radius)
    pool.setColorAt(0, tint(spot, 215 * strength))
    pool.setColorAt(.34, tint(spot, 168 * strength))
    pool.setColorAt(.68, tint(spot, 62 * strength))
    pool.setColorAt(1, tint(spot, 0))
    p.fillRect(bounds, pool)
    for speed, scale, share, phase, colour in ((.021, .62, .34, 0., second), (.037, .46, .26, 2.1, spot)):
        angle = drift * speed * math.tau + phase
        moved = centre + QPointF(math.cos(angle) * radius * .26, math.sin(angle * 1.3) * radius * .15)
        layer = QRadialGradient(moved, radius * scale)
        layer.setColorAt(0, tint(colour, 150 * share * strength))
        layer.setColorAt(1, tint(colour, 0))
        p.fillRect(bounds, layer)


# --- physical controls --------------------------------------------------------

class _Hover(QAbstractButton):
    """One eased hover value; reduced motion settles it instantly."""
    def __init__(self, controller=None, parent=None):
        super().__init__(parent)
        self.c = controller
        self._hover = 0.
        self.hover_animation = QPropertyAnimation(self, b"hover", self)
        self.hover_animation.setDuration(150)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.keyboard_focus = False

    def focusInEvent(self, event):
        self.keyboard_focus = keyboard_reason(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus = False
        super().focusOutEvent(event)

    def show_focus(self):
        return self.hasFocus() and self.keyboard_focus

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = float(value)
        self.update()

    hover = Property(float, get_hover, set_hover)

    def _ease(self, target):
        self.hover_animation.stop()
        if (self.c is not None and getattr(self.c, "reduced_motion", False)) or not self.isVisible():
            self.set_hover(target)
        else:
            self.hover_animation.setStartValue(self._hover)
            self.hover_animation.setEndValue(target)
            self.hover_animation.start()

    def enterEvent(self, event):
        self._ease(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._ease(0.)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.hover_animation.stop()
        self._hover = 0.
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.isEnabled():
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


def keyboard_reason(reason):
    """Focus rings are for people moving by keyboard; a click should not leave a ring behind."""
    return reason in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)


def paint_focus(p, rect, radius, colour=FOCUS):
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour, 2))
    p.drawRoundedRect(QRectF(rect).adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
    p.restore()


class NavTile(_Hover):
    """A place in the window: an icon and a word, a lifted tile when you are there."""
    def __init__(self, text, glyph, hint="", controller=None, standalone=False):
        super().__init__(controller)
        self.setText(text)
        self.glyph = glyph
        self.standalone = standalone
        self.setCheckable(True)
        self.setAccessibleName(text)
        self.setToolTip(f"{text}  ·  {hint}" if hint else text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        metrics = QFontMetricsF(face(13, QFont.Weight.DemiBold))
        return QSize(round(metrics.horizontalAdvance(self.text()) + 18 + 8 + 36), 46)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        from .glass import draw_icon
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isChecked()
        down = self.isDown()
        h = self._hover if self.isEnabled() else 0.
        body = QRectF(self.rect()).adjusted(3, 4, -3, -5)
        radius = 12
        ink = QColor(INK if selected or h > .5 else INK_SOFT)
        if self.standalone and not selected:
            if not down:
                paint_shadow(p, body, radius, 6 + 3 * h, .16 + .06 * h, 2 + h)
            else:
                body.translate(0, 1)
            p.setPen(QPen(tint(INK, 26), 1))
            p.setBrush(hexc("#f3f6f2") if down else mix(CARD, hexc("#fbfcfa"), h))
            p.drawRoundedRect(body, radius, radius)
        elif selected:
            if down:
                body.translate(0, 1)
            else:
                body.translate(0, -1)
                paint_shadow(p, body, radius, 9, .24, 3)
            p.setPen(Qt.PenStyle.NoPen)
            # After hours the lifted tile is lit a little brighter than the cards, so it reads as raised.
            p.setBrush(INK if self.standalone else (QColor("#2e3a35") if is_dark() else CARD))
            if self.standalone:
                ink = QColor(ON_INK)
            p.drawRoundedRect(body, radius, radius)
            if is_dark() and not self.standalone:
                p.setPen(QPen(tint(WHITE, 26), 1))
                p.drawLine(QPointF(body.left() + radius, body.top() + .5), QPointF(body.right() - radius, body.top() + .5))
        else:
            if down:
                body.translate(0, 1)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(tint(INK, 20))
                p.drawRoundedRect(body, radius, radius)
            elif h > .01:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(tint(WHITE, (18 if is_dark() else 150) * h))
                p.drawRoundedRect(body, radius, radius)
        if not self.isEnabled():
            ink.setAlpha(110)
        metrics = QFontMetricsF(face(13, QFont.Weight.DemiBold if selected else QFont.Weight.Medium))
        text_width = metrics.horizontalAdvance(self.text())
        total = 18 + 8 + text_width
        x = body.center().x() - total / 2
        draw_icon(p, self.glyph, QRectF(x, body.center().y() - 9, 18, 18), ink)
        p.setFont(face(13, QFont.Weight.DemiBold if selected else QFont.Weight.Medium))
        p.setPen(ink)
        p.drawText(QRectF(x + 26, body.top(), text_width + 4, body.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        if self.show_focus():
            paint_focus(p, body, radius)


class PlaceNav(QFrame):
    """A recessed track holding the places; arrow keys move between them."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 3, 5, 4)
        layout.setSpacing(2)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def add(self, tile):
        self.tiles.append(tile)
        self.layout().addWidget(tile)
        tile.installEventFilter(self)
        return tile

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress and watched in self.tiles:
            step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(event.key())
            if step is not None:
                index = (self.tiles.index(watched) + step) % len(self.tiles)
                self.tiles[index].setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        dark = is_dark()
        p.setPen(QPen(tint(INK, 14) if dark else tint(INK, 16), 1))
        p.setBrush(tint(SHADOW, 80 if dark else 13))
        p.drawRoundedRect(track, 16, 16)
        # A faint inner top edge makes the track read as recessed into the wall.
        inner = QLinearGradient(track.topLeft(), track.topLeft() + QPointF(0, 8))
        inner.setColorAt(0, tint(SHADOW, 110 if dark else 16))
        inner.setColorAt(1, tint(SHADOW, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(inner)
        p.drawRoundedRect(track, 16, 16)


class HandsetButton(_Hover):
    """A round control on the dark audio-guide handset. Play is the raised mint key."""
    NAMES = {"previous": "Previous track", "play": "Play", "next": "Next track",
             "share": "Share a lyric card", "mini": "Mini player", "fullscreen": "Immersive view",
             "exit-fullscreen": "Return to Halo"}

    def __init__(self, kind, callback=None, controller=None, hint=""):
        super().__init__(controller)
        self.kind = kind
        self.hint = hint
        size = 54 if kind == "play" else 42
        self.setFixedSize(size, size + 4)
        if callback is not None:
            self.clicked.connect(callback)
        name = self.NAMES.get(kind, kind.title())
        self.setAccessibleName(name)
        self.setToolTip(f"{name}  ·  {hint}" if hint else name)
        if kind == "play":
            self.setText("▶")

    def setText(self, text):
        super().setText(text)
        if self.kind == "play":
            name = "Pause" if text == "Ⅱ" else "Play"
            self.setAccessibleName(name)
            self.setToolTip(f"{name}  ·  Space")

    def paintEvent(self, event):
        from .glass import draw_icon
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        down = self.isDown()
        h = self._hover if self.isEnabled() else 0.
        size = self.width()
        body = QRectF(1, 1, size - 2, size - 2)
        if down:
            body.translate(0, 2)
        primary = self.kind == "play"
        if primary:
            if not down and self.isEnabled():
                paint_shadow(p, body, size / 2, 7, .55, 3, QColor("#060b09"))
            # The play key carries the song's light, so the handset belongs to this song too.
            light = song_light(self.c)
            top = mix(mix(light, WHITE, .5), WHITE, h * .25)
            bottom = mix(mix(light, WHITE, .14), WHITE, h * .2)
            if down:
                top, bottom = mix(light, WHITE, .22), light.darker(108)
            if not self.isEnabled():
                top, bottom = QColor("#46564f"), QColor("#3c4b45")
            fill = QLinearGradient(body.topLeft(), body.bottomLeft())
            fill.setColorAt(0, top)
            fill.setColorAt(1, bottom)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawEllipse(body)
            if not down and self.isEnabled():
                p.setPen(QPen(tint(WHITE, 170), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(body.adjusted(2, 2, -2, -2), 35 * 16, 110 * 16)
            ink = QColor(HANDSET) if self.isEnabled() else QColor("#7d8a85")
        else:
            fill = mix(HANDSET_RAISED, QColor("#3a4c46"), h)
            if down:
                fill = QColor("#15201d")
            p.setPen(Qt.PenStyle.NoPen)
            if not down:
                p.setBrush(QColor("#111a17"))
                p.drawEllipse(body.translated(0, 2))
            p.setBrush(fill)
            p.drawEllipse(body)
            if not down:
                p.setPen(QPen(tint(WHITE, 22 + 18 * h), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(body.adjusted(1, 1, -1, -1), 30 * 16, 120 * 16)
            ink = QColor(HANDSET_INK) if self.isEnabled() else tint(HANDSET_INK, 80)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        x, y = body.center().x(), body.center().y()
        if primary:
            if self.text() == "Ⅱ":
                p.drawRoundedRect(QRectF(x - 7, y - 8, 5, 16), 1.4, 1.4)
                p.drawRoundedRect(QRectF(x + 2, y - 8, 5, 16), 1.4, 1.4)
            else:
                path = QPainterPath(QPointF(x - 5, y - 9))
                path.lineTo(x + 9, y)
                path.lineTo(x - 5, y + 9)
                path.closeSubpath()
                p.drawPath(path)
        elif self.kind in ("previous", "next"):
            direction = -1 if self.kind == "previous" else 1
            path = QPainterPath(QPointF(x - direction * 5, y - 6.5))
            path.lineTo(x + direction * 4.5, y)
            path.lineTo(x - direction * 5, y + 6.5)
            path.closeSubpath()
            p.drawPath(path)
            p.drawRoundedRect(QRectF(x + direction * 5.5 - 1.2, y - 6.5, 2.4, 13), 1, 1)
        else:
            draw_icon(p, self.kind, QRectF(x - 10, y - 10, 20, 20), ink)
        if self.show_focus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(MINT if not primary else HANDSET_INK, 2))
            p.drawEllipse(body.adjusted(-2.5, -2.5, 2.5, 2.5))
