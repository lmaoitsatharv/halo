"""The mini player: a small dark case for the song, always on top, while Halo's window rests.

At rest it holds only what the song needs: the framed print under the song's light, the title and
artist, the line being sung with its word in that light, a fine progress line and the play key.
Hovering, or tabbing in, brings up previous and next beside play, the times, and two small keys on
the case's top edge: back to Halo, and close to the tray. The case is dark in both lights, so it
sits well on any desktop.
"""
import math
import time

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, Signal
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont, QFontMetricsF, QKeySequence, QShortcut,
                           QGuiApplication, QLinearGradient, QPixmap)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .gallery import (HANDSET_INK, HANDSET_MUTED, HANDSET_RAISED, FRAME, MAT, WHITE, HandsetButton, _Hover, face,
                      tint, mix, paint_shadow, paint_spotlight, song_light, contrast)
from .wall import wall_lines, line_words, sung_word

CASE_TOP = QColor("#1a2420")
CASE_LOW = QColor("#0f1513")
CASE_EDGE = QColor("#060a09")


def _ease(t):
    t = max(0., min(1., t))
    return 1 - (1 - t) ** 3


def _smooth(t):
    t = max(0., min(1., t))
    return t * t * (3 - 2 * t)


def readable_light(light, ground=CASE_TOP, target=4.5):
    """The song's light, lifted toward white only as far as it needs to read as small lettering on the case."""
    colour = QColor(light)
    amount = 0.
    while contrast(colour, ground) < target and amount < 1.:
        amount += .08
        colour = mix(light, WHITE, amount)
    return colour


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


class MiniKey(HandsetButton):
    """A round key on the case: play, or the smaller previous and next beside it."""
    NAMES = dict(HandsetButton.NAMES, restore="Back to Halo", close="Close to the tray")

    def __init__(self, kind, callback, controller, hint=""):
        super().__init__(kind, callback, controller, hint)
        if kind == "play":
            self.setFixedSize(40, 44)
        else:
            self.setFixedSize(30, 34)


MiniButton = MiniKey


class CaseChip(_Hover):
    """A small round key sitting on the case's top edge, for leaving the mini player."""
    NAMES = {"restore": "Back to Halo", "close": "Close to the tray"}

    def __init__(self, kind, callback, controller, hint=""):
        super().__init__(controller)
        self.kind = kind
        self.setFixedSize(24, 26)
        self.clicked.connect(callback)
        name = self.NAMES[kind]
        self.setAccessibleName(name)
        self.setToolTip(f"{name}  ·  {hint}" if hint else name)

    def paintEvent(self, event):
        from .glass import draw_icon
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        down = self.isDown()
        body = QRectF(1, 1, 22, 22).translated(0, 1.5 if down else 0)
        p.setPen(Qt.PenStyle.NoPen)
        if not down:
            p.setBrush(QColor("#070c0a"))
            p.drawEllipse(body.translated(0, 1.5))
        p.setBrush(QColor("#15201d") if down else mix(HANDSET_RAISED, QColor("#3a4c46"), self._hover))
        p.drawEllipse(body)
        p.setPen(QPen(tint(WHITE, 26 + 22 * self._hover), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(body.adjusted(1, 1, -1, -1), 30 * 16, 120 * 16)
        centre = body.center()
        draw_icon(p, self.kind, QRectF(centre.x() - 6.5, centre.y() - 6.5, 13, 13), HANDSET_INK)
        if self.show_focus():
            p.setPen(QPen(HANDSET_INK, 1.6))
            p.drawEllipse(body.adjusted(-1.5, -1.5, 1.5, 1.5))


class MiniPlayer(QWidget):
    """A small always-on-top case: the print, the song, the line being sung, and playback."""
    restoreRequested = Signal()
    closeRequested = Signal()
    SIZE = (384, 136)
    REHANG = .6
    RISE = .32
    REVEAL = .16  # seconds for the hidden keys to come up or go

    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.c = controller
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Halo · Mini player")
        self.setAccessibleName("Halo mini player")
        self.setFixedSize(*self.SIZE)
        self.setMouseTracking(True)
        self._drag = None
        self._pressed_at = None
        self.pixmap = QPixmap()
        self.track_key = None
        self.print_cache = QPixmap()
        self.print_key = None
        self.previous_print = QPixmap()
        self.hung_at = 0.
        self.shown_index = None
        self.changed_at = 0.
        self.scroll = 0.
        self.lyric_room = 0.
        self.hovered = False
        self.revealed = 0.
        self._last_tick = None
        self.previous = MiniKey("previous", lambda: controller.transport("previous"), controller, "Ctrl+Left")
        self.play = MiniKey("play", lambda: controller.transport("toggle"), controller, "Space")
        self.next = MiniKey("next", lambda: controller.transport("next"), controller, "Ctrl+Right")
        self.restore_button = CaseChip("restore", self.restoreRequested.emit, controller, "Esc")
        self.close_button = CaseChip("close", self.closeRequested.emit, controller)
        self.hidden_keys = (self.previous, self.next, self.restore_button, self.close_button)
        self.fades = {}
        for key in (self.play, *self.hidden_keys):
            key.setParent(self)
        for key in self.hidden_keys:
            effect = QGraphicsOpacityEffect(key)
            effect.setOpacity(0.)
            key.setGraphicsEffect(effect)
            self.fades[key] = effect
            key.hide()
        QShortcut(QKeySequence("Space"), self, activated=lambda: controller.transport("toggle") if controller.track.connected else None)
        QShortcut(QKeySequence("Esc"), self, activated=self.restoreRequested.emit)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=lambda: controller.transport("previous") if controller.track.connected else None)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=lambda: controller.transport("next") if controller.track.connected else None)
        controller.trackChanged.connect(self.refresh)
        self.arrange()
        self.refresh()

    # --- geometry ---------------------------------------------------------------------

    def card(self):
        """The case. Room above it for the keys on its top edge, and below it for its shadow."""
        return QRectF(12, 16, self.width() - 24, self.height() - 34)

    def frame_rect(self):
        card = self.card()
        side = card.height() - 24
        return QRectF(card.left() + 12, card.top() + 12, side, side)

    def play_rest(self):
        """Where play sits at rest; it steps left to make room for next while the keys are up."""
        card = self.card()
        return QPointF(card.right() - 16 - self.play.width(), card.center().y() - 1 - self.play.height() / 2)

    def text_rect(self):
        """The lettering's column, which gives way on the right while the keys are up."""
        card, frame = self.card(), self.frame_rect()
        left = frame.right() + 14
        right = self.play.x() - 12 if self.revealed < .01 else min(self.play.x() - 12, self.previous.x() - 10)
        return QRectF(left, card.top() + 4, max(20., right - left), card.height() - 18)

    def strip_centre(self):
        return self.card().bottom() - 11

    def arrange(self):
        """Place the keys for the current reveal: play slides left, and its neighbours come up beside it."""
        shown = _smooth(self.revealed)
        rest = self.play_rest()
        step = self.next.width() + 6
        play = QPointF(rest.x() - step * shown, rest.y())
        self.play.move(round(play.x()), round(play.y()))
        middle = play.y() + self.play.height() / 2
        self.previous.move(round(play.x() - 6 - self.previous.width()), round(middle - self.previous.height() / 2 + 1))
        self.next.move(round(play.x() + self.play.width() + 6), round(middle - self.next.height() / 2 + 1))
        card = self.card()
        chip_y = round(card.top() - 12 + 4 * (1 - shown))
        self.close_button.move(round(card.right() - 16 - self.close_button.width()), chip_y)
        self.restore_button.move(round(self.close_button.x() - 6 - self.restore_button.width()), chip_y)
        for key, effect in self.fades.items():
            effect.setOpacity(shown)
            key.setVisible(self.revealed > .02)

    def wants_keys(self):
        return self.hovered or any(getattr(key, "keyboard_focus", False) for key in (self.play, *self.hidden_keys))

    # --- state ------------------------------------------------------------------------

    def refresh(self):
        c = self.c
        playing = c.track.playing
        self.play.setText("Ⅱ" if playing else "▶")
        for button in (self.previous, self.play, self.next):
            button.setEnabled(c.track.connected)
        key = (c.track.key, len(c.track.artwork))
        if key != self.track_key:
            new_song = self.track_key is not None and self.track_key[0] != c.track.key
            if (new_song and not self.print_cache.isNull() and self.isVisible()
                    and not getattr(c, "reduced_motion", False)):
                self.previous_print = QPixmap(self.print_cache)
                self.hung_at = time.monotonic()
            else:
                self.previous_print = QPixmap()
            self.track_key = key
            self.pixmap = QPixmap()
            if c.track.artwork:
                self.pixmap.loadFromData(c.track.artwork)
            self.print_key = None
        if not self.isVisible():
            # Opening on a song with words starts with its line in place, not sliding in.
            self.lyric_room = 1. if self.has_lyrics() else 0.
        self.update()

    def has_lyrics(self):
        return bool(getattr(self.c.lyrics, "lines", None)) and (self.c.track.connected or getattr(self.c, "demo", False))

    def rehanging(self):
        return not self.previous_print.isNull() and time.monotonic() - self.hung_at < self.REHANG

    def place(self):
        """Back where it was left, or the lower right of the screen; always fully on a screen."""
        settings = self.c.settings
        saved = settings.value("mini_position", None)
        screen = QGuiApplication.primaryScreen()
        target = None
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                target = QPoint(int(saved[0]), int(saved[1]))
            except (TypeError, ValueError):
                target = None
        elif isinstance(saved, str) and "," in saved:
            try:
                x, y = saved.split(",", 1)
                target = QPoint(int(x), int(y))
            except ValueError:
                target = None
        if target is not None:
            screen = QGuiApplication.screenAt(target + QPoint(self.width() // 2, self.height() // 2)) or None
            if screen is None:
                target = None
                screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if target is None:
            target = QPoint(area.right() - self.width() - 12, area.bottom() - self.height() - 12)
        target.setX(max(area.left(), min(target.x(), area.right() - self.width())))
        target.setY(max(area.top(), min(target.y(), area.bottom() - self.height())))
        self.move(target)

    def remember(self):
        self.c.settings.setValue("mini_position", f"{self.x()},{self.y()}")

    def line(self):
        """(text, words, index of the word being sung, line index) for the lyric at this moment."""
        lyrics = self.c.lyrics
        if not getattr(lyrics, "lines", None):
            return "", [], -1, -1
        position = self.c.position + getattr(self.c, "offset", 0) / 1000
        _, line, index, waiting = wall_lines(lyrics, position)
        if line is None or not line.text.strip():
            return "", [], -1, index
        words = line_words(line)
        later = [item.time for item in lyrics.lines[index + 1:] if item.time > line.time]
        current = -1 if waiting else sung_word(line, words, position, later[0] if later else None)
        return line.text.strip(), words, current, index

    # --- painting -----------------------------------------------------------------------

    def _print(self, frame):
        """The cover as a small print: a dark frame, a thin mat, the art, and a soft shadow on the case."""
        dpr = self.devicePixelRatioF()
        key = (round(frame.width()), dpr, self.track_key, self.c.halo_primary.rgba() if self.pixmap.isNull() else 0)
        if key == self.print_key and not self.print_cache.isNull():
            return self.print_cache
        pad = 20
        image = QPixmap(round((frame.width() + pad * 2) * dpr), round((frame.height() + pad * 2) * dpr))
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(pad, pad, frame.width(), frame.height())
        # Shadows here fall on the dark case, so they are drawn in black whatever the wall's light.
        paint_shadow(p, rect, 3, 8, .55, 4, QColor("#000000"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FRAME)
        p.drawRoundedRect(rect, 3, 3)
        mat = rect.adjusted(2.5, 2.5, -2.5, -2.5)
        p.setBrush(MAT)
        p.drawRect(mat)
        art = mat.adjusted(4, 4, -4, -4)
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(round(art.width() * dpr), round(art.height() * dpr),
                                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            p.save()
            p.setClipRect(art)
            p.drawPixmap(QPointF(art.center().x() - scaled.width() / dpr / 2,
                                 art.center().y() - scaled.height() / dpr / 2), scaled)
            p.restore()
        else:
            from .wall import paint_placeholder
            paint_placeholder(p, art, self.c.halo_primary)
        p.setPen(QPen(tint(QColor("#1c2a26"), 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(art.adjusted(-.5, -.5, .5, .5))
        p.end()
        self.print_cache, self.print_key = image, key
        return image

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = self.card()
        frame = self.frame_rect()
        light = song_light(c)
        moving = c.track.playing and not getattr(c, "reduced_motion", False)
        motion = getattr(c, "motion_time", 0.)

        # The case: a dark, slightly lit box with a soft shadow on the desktop.
        paint_shadow(p, card, 20, 12, .45, 5, QColor("#000000"))
        case = QPainterPath()
        case.addRoundedRect(card, 20, 20)
        fill = QLinearGradient(card.topLeft(), card.bottomLeft())
        fill.setColorAt(0, CASE_TOP)
        fill.setColorAt(1, CASE_LOW)
        p.setPen(QPen(CASE_EDGE, 1))
        p.setBrush(fill)
        p.drawPath(case)

        # The song's light pools behind the print and spills a little across the case, breathing while it plays.
        breath = .5 + .5 * math.sin(motion * math.tau / 7) if moving else .5
        p.save()
        p.setClipPath(case)
        p.setOpacity(.5 + .16 * breath)
        paint_spotlight(p, frame.center() + QPointF(4, 6), card.height() * 1.25,
                        getattr(c, "halo_primary", c.primary), getattr(c, "halo_secondary", c.secondary), 1., motion)
        p.restore()
        p.setPen(QPen(tint(WHITE, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(1, 1, -1, -1), 19, 19)

        # The print, re-hung with a small drop when the song changes.
        image = self._print(frame)
        pad = 20
        t = min(1., (time.monotonic() - self.hung_at) / self.REHANG) if not self.previous_print.isNull() else 1.
        if t < 1.:
            p.setOpacity(max(0., 1 - t * 2.2))
            p.drawPixmap(QPointF(frame.x() - pad, frame.y() - pad - 6 * _ease(t)), self.previous_print)
            settle = _ease(max(0., (t - .25) / .75))
            p.setOpacity(settle)
            p.drawPixmap(QPointF(frame.x() - pad, frame.y() - pad + 8 * (1 - settle)), image)
            p.setOpacity(1.)
        else:
            self.previous_print = QPixmap()
            p.drawPixmap(QPointF(frame.x() - pad, frame.y() - pad), image)

        self._paint_words(p, readable_light(light))
        self._paint_timeline(p, light)

    def _paint_words(self, p, light):
        """Title, artist and the sung line, lettered into a layer that fades out where the keys come up."""
        c = self.c
        area = self.text_rect()
        dpr = self.devicePixelRatioF()
        connected = c.track.connected or getattr(c, "demo", False)
        text, words, current, index = self.line()
        now = time.monotonic()
        if index != self.shown_index:
            if self.shown_index is not None and not getattr(c, "reduced_motion", False):
                self.changed_at = now
            self.shown_index = index
            self.scroll = 0.
            self.setAccessibleDescription(text)
        if getattr(c, "reduced_motion", False):
            self.lyric_room = 1. if self.has_lyrics() else 0.
        room = _smooth(self.lyric_room)

        layer = QPixmap(round((area.width() + 2) * dpr), round(area.height() * dpr))
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        q = QPainter(layer)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        title = c.track.title if connected else "Halo"
        artist = c.track.artist if connected else "Play something in Spotify, a browser or any player."
        # Two rows sit centred on the print; a third, for the sung line, opens beneath when the song has words.
        title_y = 30 + 10 * (1 - room)
        q.setFont(face(15, QFont.Weight.DemiBold, display=True))
        q.setPen(HANDSET_INK)
        q.drawText(QPointF(0, title_y), title)
        q.setFont(face(11.5, QFont.Weight.Medium))
        q.setPen(HANDSET_MUTED)
        q.drawText(QPointF(0, title_y + 19), artist)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if room > .01 and text:
            baseline = title_y + 44
            self._paint_line(q, words, current, light, area.width(), baseline, now, room)
            if self.scroll > .5:
                # A line that has glided along fades in from the left rather than starting mid-letter.
                q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                lead = QLinearGradient(QPointF(0, 0), QPointF(20, 0))
                lead.setColorAt(0, QColor(0, 0, 0, round(255 * max(0., 1 - self.scroll / 12))))
                lead.setColorAt(1, QColor(0, 0, 0, 255))
                q.fillRect(QRectF(0, baseline - 20, 20, 28), lead)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QLinearGradient(QPointF(area.width() - 22, 0), QPointF(area.width(), 0))
        fade.setColorAt(0, QColor(0, 0, 0, 255))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        q.fillRect(QRectF(0, 0, area.width() + 2, area.height()), fade)
        q.end()
        p.drawPixmap(area.topLeft(), layer)

    def _paint_line(self, q, words, current, light, width, baseline, now, room):
        """The sung line on one row, gliding along so the word being sung stays in view."""
        c = self.c
        font = face(13, QFont.Weight.DemiBold, display=True)
        metrics = QFontMetricsF(font)
        space = metrics.horizontalAdvance(" ")
        lettering = [word for word, _ in words]
        lit = current if c.track.playing else -1
        lefts, x = [], 0.
        for word in lettering:
            lefts.append(x)
            x += metrics.horizontalAdvance(word) + space
        total = max(0., x - space)
        target = 0.
        if total > width - 20 and 0 <= current < len(lettering):
            end = lefts[current] + metrics.horizontalAdvance(lettering[current])
            target = max(0., min(total - width + 24, end - width * .62))
        if getattr(c, "reduced_motion", False) or self.scroll == 0. and target == 0.:
            self.scroll = target
        else:
            self.scroll += (target - self.scroll) * .14
        progress = _ease((now - self.changed_at) / self.RISE) if self.changed_at else 1.
        q.save()
        q.setFont(font)
        q.setOpacity(room * (.3 + .7 * progress))
        y = baseline + (1 - progress) * 6
        for i, word in enumerate(lettering):
            if lit == i:
                colour = light
            elif i < lit:
                colour = QColor(HANDSET_INK)
            else:
                colour = tint(HANDSET_INK, 130)
            q.setPen(colour)
            q.drawText(QPointF(lefts[i] - self.scroll, y), word)
        q.restore()

    def _paint_timeline(self, p, light):
        """A fine line along the foot of the case; the times come up at its ends with the keys."""
        c = self.c
        y = self.strip_centre()
        card = self.card()
        duration = max(0., float(c.track.duration or 0))
        fraction = max(0., min(1., c.position / duration)) if duration > 0 else 0.
        shown = _smooth(self.revealed)
        left, right = self.frame_rect().right() + 14, card.right() - 18
        if shown > .01:
            p.setFont(face(10.5, QFont.Weight.Medium))
            p.setOpacity(shown)
            p.setPen(HANDSET_MUTED)
            p.drawText(QRectF(left, y - 8, 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clock(c.position))
            p.drawText(QRectF(right - 40, y - 8, 40, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       clock(duration))
            p.setOpacity(1.)
        start, finish = left + 36 * shown, right - 36 * shown
        if finish <= start:
            return
        p.setPen(QPen(tint(HANDSET_INK, 34), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(start, y), QPointF(finish, y))
        if fraction > 0:
            x = start + (finish - start) * fraction
            p.setPen(QPen(light, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(start, y), QPointF(x, y))
            glow = QColor(light)
            glow.setAlpha(round(40 + 50 * shown))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(x, y), 3.5 + 1.5 * shown, 3.5 + 1.5 * shown)
            p.setBrush(mix(light, WHITE, .35))
            p.drawEllipse(QPointF(x, y), 1.6 + .6 * shown, 1.6 + .6 * shown)

    # --- moving it ----------------------------------------------------------------------

    def tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        elapsed = 0. if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        reduced = getattr(self.c, "reduced_motion", False)
        # At least one step a tick, so the keys still come up when frames are slow or come in a burst.
        step = 1. if reduced else max(.1, elapsed / self.REVEAL)
        target = 1. if self.wants_keys() else 0.
        if self.revealed != target:
            self.revealed = min(target, self.revealed + step) if target > self.revealed else max(target, self.revealed - step)
            self.arrange()
        room = 1. if self.has_lyrics() else 0.
        if self.lyric_room != room:
            self.lyric_room = room if reduced else (min(room, self.lyric_room + step * .5) if room > self.lyric_room
                                                    else max(room, self.lyric_room - step * .5))
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.hovered = False
        self.revealed = 0.
        self._last_tick = None
        self.arrange()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._pressed_at = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            moved = self._pressed_at is not None and (event.globalPosition().toPoint() - self._pressed_at).manhattanLength() > 3
            self._drag = None
            self._pressed_at = None
            if moved:
                self.remember()
            elif self.frame_rect().contains(event.position()):
                # A click on the print brings Halo back, like the case's back-to-Halo key.
                self.restoreRequested.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.restoreRequested.emit()
