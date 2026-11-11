"""The pieces hung on the gallery wall: the framed print, its museum label, and the wall lettering."""
import math
import time

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QLinearGradient, QPixmap, QFont, QFontMetricsF
from PySide6.QtWidgets import QWidget, QFrame, QSizePolicy, QGraphicsOpacityEffect

from .gallery import (INK, INK_SOFT, INK_MUTED, CARD, MAT, FRAME, WALL, WHITE, FOCUS, ACCENT_INK, face, tint, mix,
                      paint_shadow, spotlight_colour, ink_accent)


def _ease(t):
    t = max(0., min(1., t))
    return 1 - (1 - t) ** 3


# --- which words are on the wall ---------------------------------------------

def wall_lines(lyrics, position):
    """(previous text, current line or None, index, waiting) for the lyric at this position.

    Before the first line, the first line waits on the wall in quiet ink.
    """
    lines = getattr(lyrics, "lines", None) or []
    if not lines:
        return "", None, -1, False
    index = lyrics.index_at(position)
    if index < 0:
        return "", lines[0], 0, True
    previous = ""
    for back in range(index - 1, -1, -1):
        if lines[back].text.strip():
            previous = lines[back].text.strip()
            break
    return previous, lines[index], index, False


def line_words(line):
    """Words shown for a line, with the start time each one is sung (None when estimated)."""
    if line is None:
        return []
    timed = [(word.text.strip(), word.start) for word in getattr(line, "words", ()) if word.text.strip()]
    if timed:
        return timed
    return [(word, None) for word in line.text.split()]


def sung_word(line, words, position, next_time=None):
    """Index of the word being sung now; estimated evenly across the line when it has no word timing."""
    if not words:
        return -1
    if position < line.time:
        return -1
    if words[0][1] is not None:
        index = -1
        for i, (_, start) in enumerate(words):
            if start is not None and start <= position:
                index = i
        return index
    finish = line.end if getattr(line, "end", None) else next_time
    if finish is None or finish <= line.time:
        finish = line.time + max(2.5, .42 * len(words))
    # Most singers finish a line before the next one starts; lead the estimate slightly.
    fraction = (position - line.time) / max(.3, (finish - line.time) * .86)
    return max(0, min(len(words) - 1, math.floor(fraction * len(words))))


# --- the framed print -------------------------------------------------------------

def paint_placeholder(p, art, light_source):
    """No cover yet: an original quiet print of the halo ring, in the song's light."""
    light = spotlight_colour(light_source)
    wash = QLinearGradient(art.topLeft(), art.bottomRight())
    wash.setColorAt(0, mix(WALL, light, .35))
    wash.setColorAt(1, mix(WALL, light, .12))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(wash)
    p.drawRect(art)
    centre, radius = art.center(), art.width() * .24
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(tint(INK, 40), max(3., radius * .12)))
    p.drawEllipse(centre, radius, radius)
    p.setPen(QPen(ink_accent(light_source, WALL, 3.2), max(2., radius * .07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2), 40 * 16, 245 * 16)
    inner = radius * .58
    p.setPen(QPen(tint(INK, 120), max(1.5, radius * .05), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(centre.x() - inner, centre.y() - inner, inner * 2, inner * 2), 170 * 16, 220 * 16)


def paint_framed_print(p, frame, pixmap, light_source, dpr=1.):
    """A cover hung as a print: long soft shadow, dark frame, off-white mat, then the art."""
    frame = QRectF(frame)
    side = frame.width()
    paint_shadow(p, frame, 2, max(8, side * .05), .42, side * .045)
    paint_shadow(p, frame, 2, 3, .28, 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(FRAME)
    p.drawRect(frame)
    rim = max(5., side * .018)
    mat = frame.adjusted(rim, rim, -rim, -rim)
    p.setBrush(MAT)
    p.drawRect(mat)
    border = max(14., side * .085)
    art = mat.adjusted(border, border, -border, -border)
    # The mat's bevelled cut reads as a fine shadowed line around the art (the mat is light in both lights).
    p.setPen(QPen(tint(QColor("#1c2a26"), 34), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(art.adjusted(-1.5, -1.5, 1.5, 1.5))
    if pixmap is not None and not pixmap.isNull():
        scaled = pixmap.scaled(round(art.width() * dpr), round(art.height() * dpr),
                               Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        p.save()
        p.setClipRect(art)
        p.drawPixmap(QPointF(art.center().x() - scaled.width() / dpr / 2,
                             art.center().y() - scaled.height() / dpr / 2), scaled)
        p.restore()
    else:
        paint_placeholder(p, art, light_source)
    glare = QLinearGradient(frame.topLeft(), frame.bottomRight())
    glare.setColorAt(0, tint(WHITE, 34))
    glare.setColorAt(.35, tint(WHITE, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glare)
    p.drawRect(mat)
    return art


class FramedPrint(QWidget):
    """The cover in a mat and a dark frame, re-hung when the song changes."""
    clicked = Signal()

    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.pixmap = QPixmap()
        self.track_key = None
        self.cache = QPixmap()
        self.cache_key = None
        self.previous = QPixmap()
        self.hung_at = 0.
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Album artwork. Open immersive view")
        self.setToolTip("Open immersive view  ·  F11")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.keyboard_focus = False
        controller.trackChanged.connect(self.track_changed)
        self.track_changed(animate=False)

    def focusInEvent(self, event):
        from .gallery import keyboard_reason
        self.keyboard_focus = keyboard_reason(event.reason())
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.keyboard_focus = False
        super().focusOutEvent(event)

    def print_rect(self):
        """The frame's outer edge inside the widget; the rest is room for its shadow."""
        side = min(self.width() / 1.16, self.height() / 1.22)
        return QRectF((self.width() - side) / 2, (self.height() - side) * .38, side, side)

    def track_changed(self, animate=True):
        track = self.c.track
        key = (track.key, len(track.artwork))
        if key == self.track_key:
            return
        new_song = self.track_key is None or self.track_key[0] != track.key
        if animate and new_song and not self.cache.isNull() and not getattr(self.c, "reduced_motion", False) and self.isVisible():
            self.previous = QPixmap(self.cache)
            self.hung_at = time.monotonic()
        else:
            self.previous = QPixmap()
        self.track_key = key
        self.pixmap = QPixmap()
        if track.artwork:
            self.pixmap.loadFromData(track.artwork)
        self.cache_key = None
        self.update()

    def theme_changed(self):
        self.cache_key = None

    def rehanging(self):
        return not self.previous.isNull() and time.monotonic() - self.hung_at < .7

    def _render(self, rect):
        dpr = self.devicePixelRatioF()
        key = (round(rect.width()), round(rect.height()), dpr, self.track_key, self.c.halo_primary.rgba() if self.pixmap.isNull() else 0)
        if key == self.cache_key and not self.cache.isNull():
            return self.cache
        pad = 64
        image = QPixmap(round((rect.width() + pad * 2) * dpr), round((rect.height() + pad * 2) * dpr))
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        paint_framed_print(p, QRectF(pad, pad, rect.width(), rect.height()), self.pixmap, self.c.halo_primary, dpr)
        p.end()
        self.cache, self.cache_key = image, key
        return image

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.print_rect()
        image = self._render(rect)
        pad = 64
        t = min(1., (time.monotonic() - self.hung_at) / .7) if not self.previous.isNull() else 1.
        if t < 1.:
            p.setOpacity(max(0., 1 - t * 2.2))
            p.drawPixmap(QPointF(rect.x() - pad, rect.y() - pad - 16 * _ease(t)), self.previous)
            settle = _ease(max(0., (t - .25) / .75))
            p.setOpacity(settle)
            p.drawPixmap(QPointF(rect.x() - pad, rect.y() - pad + 20 * (1 - settle)), image)
            p.setOpacity(1.)
        else:
            self.previous = QPixmap()
            p.drawPixmap(QPointF(rect.x() - pad, rect.y() - pad), image)
        if self.hasFocus() and self.keyboard_focus:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(FOCUS, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(-5, -5, 5, 5))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.print_rect().contains(event.position()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PrintThumb(QWidget):
    """A tiny matted print for the handset and the mini player."""
    def __init__(self, controller, size=40, dark=True):
        super().__init__()
        self.c = controller
        self.dark = dark
        self.pixmap = QPixmap()
        self.setFixedSize(size, size)
        controller.trackChanged.connect(self.track_changed)
        self.track_changed()

    def track_changed(self):
        self.pixmap = QPixmap()
        if self.c.track.artwork:
            self.pixmap.loadFromData(self.c.track.artwork)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        box = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(MAT)
        p.drawRoundedRect(box, 3, 3)
        art = box.adjusted(3, 3, -3, -3)
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(round(art.width() * self.devicePixelRatioF()), round(art.height() * self.devicePixelRatioF()),
                                        Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            p.save()
            p.setClipRect(art)
            p.drawPixmap(QPointF(art.center().x() - scaled.width() / scaled.devicePixelRatio() / 2,
                                 art.center().y() - scaled.height() / scaled.devicePixelRatio() / 2), scaled)
            p.restore()
        else:
            p.setBrush(mix(WALL, spotlight_colour(self.c.halo_primary), .4))
            p.drawRect(art)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(tint(INK, 120), 1.4))
            radius = art.width() * .26
            p.drawEllipse(art.center(), radius, radius)


# --- the museum label ---------------------------------------------------------------

class StatusDot(QWidget):
    """Where the music comes from: a filled dot when connected, a ring while waiting."""
    def __init__(self):
        super().__init__()
        self.state = "waiting"
        self.setFixedSize(12, 12)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        if self.state == "waiting":
            p.setPen(QPen(INK_MUTED, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centre, 4, 4)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ACCENT_INK if self.state == "connected" else INK_SOFT)
            p.drawEllipse(centre, 4.5, 4.5)


class MuseumLabel(QFrame):
    """A white card on the wall: title, artist, album, and where the music comes from.

    When the song changes, the card's words turn over: they settle in from just below.
    """
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.c = controller
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.content = QWidget(self)
        self.effect = QGraphicsOpacityEffect(self.content)
        self.effect.setOpacity(1.)
        self.effect.setEnabled(False)
        self.content.setGraphicsEffect(self.effect)
        self.turn_animation = QVariantAnimation(self)
        self.turn_animation.setDuration(460)
        self.turn_animation.setStartValue(0.)
        self.turn_animation.setEndValue(1.)
        self.turn_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.turn_animation.valueChanged.connect(self._turning)
        self.turn_animation.finished.connect(self._turned)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.turn_animation.state() != QVariantAnimation.State.Running:
            self.content.setGeometry(self.rect())

    def turn(self):
        """Turn the card over to the new song, unless motion is reduced or nobody can see it."""
        if (self.c is not None and getattr(self.c, "reduced_motion", False)) or not self.isVisible():
            return
        self.effect.setEnabled(True)
        self.turn_animation.stop()
        self.turn_animation.start()

    def turning(self):
        return self.turn_animation.state() == QVariantAnimation.State.Running

    def _turning(self, value):
        self.effect.setOpacity(value)
        self.content.setGeometry(self.rect().translated(0, round(10 * (1 - value))))

    def _turned(self):
        self.effect.setOpacity(1.)
        self.effect.setEnabled(False)
        self.content.setGeometry(self.rect())

    def card_rect(self):
        return QRectF(self.rect()).adjusted(8, 4, -8, -12)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.card_rect()
        paint_shadow(p, card, 3, 10, .16, 4)
        paint_shadow(p, card, 3, 2, .12, 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(CARD)
        p.drawRoundedRect(card, 3, 3)


# --- the wall lettering ---------------------------------------------------------------

class WallLyrics(QWidget):
    """The lyric as lettering on the wall: the line before, small; the line now, large.

    Only the word being sung takes the song's colour.
    """
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.shown_index = None
        self.changed_at = 0.
        self.outgoing = None
        self._layout_key = None
        self._layout = None
        self.setAccessibleName("Lyrics")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(120)

    def position(self):
        return self.c.position + getattr(self.c, "offset", 0) / 1000

    def _fit(self, words, width, height):
        """Wrap words into at most three rows at the largest size that fits."""
        key = (tuple(word for word, _ in words), round(width), round(height))
        if key == self._layout_key:
            return self._layout
        top = max(26, min(58, height * .34))
        size = top
        while True:
            font = face(size, QFont.Weight.DemiBold, display=True)
            metrics = QFontMetricsF(font)
            space = metrics.horizontalAdvance(" ")
            rows, row, row_width = [], [], 0.
            for i, (word, _) in enumerate(words):
                advance = metrics.horizontalAdvance(word)
                needed = advance if not row else row_width + space + advance
                if row and needed > width:
                    rows.append(row)
                    row, row_width = [], 0.
                    needed = advance
                row.append((i, word, advance))
                row_width = needed
            if row:
                rows.append(row)
            line_height = metrics.height() * 1.04
            if (len(rows) <= 3 and len(rows) * line_height <= height) or size <= 20:
                break
            size -= 2
        self._layout_key = key
        self._layout = (font, rows, line_height, space, metrics.ascent())
        return self._layout

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        width, height = self.width(), self.height()
        lines = getattr(c.lyrics, "lines", None) or []
        if not lines:
            message = c.lyrics.message if c.track.connected or c.demo else "Play a song anywhere, and its words will be lettered here."
            p.setFont(face(19, QFont.Weight.Normal, display=True))
            p.setPen(INK_MUTED)
            p.drawText(QRectF(0, 0, width, height * .7), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                       message or "No timed lyrics for this song.")
            return
        position = self.position()
        previous, line, index, waiting = wall_lines(c.lyrics, position)
        now = time.monotonic()
        if index != self.shown_index:
            if self.shown_index is not None and not getattr(c, "reduced_motion", False):
                self.changed_at = now
            self.shown_index = index
            self.setAccessibleDescription(line.text.strip() if line is not None else "")
        progress = _ease((now - self.changed_at) / .42) if self.changed_at else 1.
        top_band = min(78., height * .3)
        p.setFont(face(17, QFont.Weight.Medium))
        p.setPen(tint(INK_MUTED, 255 * (.4 + .6 * progress)))
        if previous and not waiting:
            p.drawText(QRectF(0, top_band - 34 - (1 - progress) * 10, width, 30),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetricsF(face(17)).elidedText(previous, Qt.TextElideMode.ElideRight, width))
        text = line.text.strip() if line is not None else ""
        if not text:
            p.setFont(face(30, QFont.Weight.Normal, display=True))
            p.setPen(tint(INK_MUTED, 200))
            p.drawText(QRectF(0, top_band, width, 60), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "·   ·   ·")
            return
        words = line_words(line)
        next_time = next((later.time for later in lines[index + 1:] if later.time > line.time), None)
        current = -1 if waiting else sung_word(line, words, position, next_time)
        font, rows, line_height, space, ascent = self._fit(words, width, height - top_band - 8)
        accent = ink_accent(c.halo_primary)
        p.setFont(font)
        rise = (1 - progress) * 18
        p.setOpacity(.35 + .65 * progress)
        y = top_band + rise
        for row in rows:
            x = 0.
            for i, word, advance in row:
                if waiting:
                    colour = tint(INK, 120)
                elif i == current and c.track.playing:
                    colour = accent
                elif i <= current:
                    colour = QColor(INK)
                else:
                    colour = tint(INK, 132)
                p.setPen(colour)
                p.drawText(QPointF(x, y + ascent), word)
                x += advance + space
            y += line_height
        p.setOpacity(1.)
