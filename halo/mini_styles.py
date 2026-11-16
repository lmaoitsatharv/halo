"""The mini player's other styles. The shared window (drag, keys, menu, placement) is MiniBase in mini_player.py.

Notch    a tall dark card: a tab with Halo's mark, a bright tab with the clock, a raised panel with the
         cover and three lines of lyrics, then the title, a seek bar and big keys.
Capsule  a slim pill: a round cover ringed by progress, the line being sung, a small live meter, play.
Disc     the cover as a record that turns while the song plays, ringed by its progress, with the line
         being sung on a caption beneath.
Poster   the cover edge to edge, with the line being sung lettered over it.
"""
import math
import re
import time

from PySide6.QtCore import Qt, QRectF, QPointF, QLocale, QTime
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont, QFontMetricsF, QLinearGradient, QPixmap,
                           QConicalGradient, QRadialGradient)

from .gallery import _Hover, face, tint, mix, paint_shadow, song_light, contrast, WHITE
from .mini_player import (MiniBase, MiniPlayer, MINI_STYLE_KEYS, _smooth, _ease, readable_light, word_lefts, glide,
                          paint_dark_placeholder)

BLACK = QColor("#000000")
ON_ACCENT = QColor("#0b0d0c")

# The Notch's own greys and its default bright green.
NEON = QColor("#1ed760")
NOTCH_TOP = QColor("#1a1a1a")
NOTCH_LOW = QColor("#101010")
NOTCH_PANEL = QColor("#222222")
NOTCH_PANEL_LOW = QColor("#1a1a1a")
NOTCH_MUTED = QColor("#a7a7a7")
NOTCH_TRACK = QColor("#4a4a4a")

# The glass the Capsule and the Disc's caption are made of.
GLASS_TOP = QColor("#181d1b")
GLASS_LOW = QColor("#0e1110")
MUTED = QColor("#a9b3ae")


def vivid(colour):
    """A song colour made bright enough to stand as an accent: a tab, a key, lit lettering."""
    hue, saturation, _, _ = QColor(colour).getHslF()
    if hue < 0 or saturation < .06:
        return QColor(NEON)
    saturation, lightness = max(.62, min(.9, saturation)), .6
    candidate = QColor.fromHslF(hue, saturation, lightness)
    # Dark lettering sits on it (the clock, the play glyph), so deep blues and violets are lifted until it reads.
    while contrast(candidate, ON_ACCENT) < 5. and lightness < .9:
        lightness += .02
        candidate = QColor.fromHslF(hue, saturation, lightness)
    return candidate


def time_of_day():
    """The time in the person's own Windows format, written tight like a watch face: 6:46PM, or 18:46."""
    text = QLocale.system().toString(QTime.currentTime(), QLocale.FormatType.ShortFormat)
    return re.sub(r"[\s  ]+(?=[^\d\s])", "", text)


def paint_glyph(p, kind, text, centre, size, ink):
    """Play, pause, previous and next as filled shapes; the window keys as Halo's line icons."""
    x, y = centre.x(), centre.y()
    p.save()
    if kind in ("restore", "close"):
        from .glass import draw_icon
        draw_icon(p, kind, QRectF(x - size / 2, y - size / 2, size, size), ink)
        p.restore()
        return
    p.setPen(QPen(ink, max(1., size * .07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(ink)
    s = size
    if kind == "play":
        if text == "Ⅱ":
            width, height = s * .2, s * .64
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x - s * .27, y - height / 2, width, height), width * .3, width * .3)
            p.drawRoundedRect(QRectF(x + s * .07, y - height / 2, width, height), width * .3, width * .3)
        else:
            height = s * .62
            path = QPainterPath(QPointF(x - s * .2, y - height / 2))
            path.lineTo(x + s * .34, y)
            path.lineTo(x - s * .2, y + height / 2)
            path.closeSubpath()
            p.drawPath(path)
    elif kind in ("previous", "next"):
        d = 1 if kind == "next" else -1
        height = s * .62
        path = QPainterPath(QPointF(x - d * s * .34, y - height / 2))
        path.lineTo(x + d * s * .18, y)
        path.lineTo(x - d * s * .34, y + height / 2)
        path.closeSubpath()
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        bar = s * .13
        left = x + s * .24 if d > 0 else x - s * .24 - bar
        p.drawRoundedRect(QRectF(left, y - height / 2 - s * .02, bar, height + s * .04), bar * .4, bar * .4)
    p.restore()


class FaceKey(_Hover):
    """A round key for the newer styles.

    look is "accent" (a bright disc with a dark glyph: play), "flat" (a glyph that brightens and
    gains a soft disc under the pointer), "glass" (a dark see-through disc over artwork), or
    "tab" (a dark glyph on the Notch's bright clock tab).
    """
    NAMES = {"previous": "Previous track", "play": "Play", "next": "Next track",
             "restore": "Back to Halo", "close": "Close to the tray"}

    def __init__(self, kind, callback, controller, hint="", size=32, glyph=None, look="flat", accent=None, ink=None):
        super().__init__(controller)
        self.kind = kind
        self.hint = hint
        self.look = look
        self.glyph = glyph or size * .42
        self.accent = accent or (lambda: song_light(controller))
        self.ink = ink
        self.setFixedSize(size, size)
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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        down = self.isDown()
        enabled = self.isEnabled()
        h = self._hover if enabled else 0.
        body = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if down:
            body = body.adjusted(1, 1, -1, -1)
        accent = QColor(self.accent())
        p.setPen(Qt.PenStyle.NoPen)
        if self.look == "accent":
            fill = accent.darker(112) if down else mix(accent, WHITE, .14 * h)
            if not enabled:
                fill = QColor("#4a504d")
            p.setBrush(fill)
            p.drawEllipse(body)
            if enabled and not down:
                p.setPen(QPen(tint(WHITE, 70 + 40 * h), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(body.adjusted(1.5, 1.5, -1.5, -1.5), 40 * 16, 100 * 16)
            ink = QColor(ON_ACCENT) if enabled else QColor("#7b8480")
        elif self.look == "glass":
            p.setBrush(tint(BLACK, 120 + 50 * h + (40 if down else 0)))
            p.setPen(QPen(tint(WHITE, 46 + 50 * h), 1))
            p.drawEllipse(body)
            ink = QColor(WHITE) if enabled else tint(WHITE, 90)
        elif self.look == "tab":
            if h > 0 or down:
                p.setBrush(tint(BLACK, 34 * h + (40 if down else 0)))
                p.drawEllipse(body)
            ink = QColor(ON_ACCENT)
        else:
            if h > 0 or down:
                p.setBrush(tint(WHITE, 18 * h + (16 if down else 0)))
                p.drawEllipse(body)
            base = QColor(self.ink()) if self.ink else QColor("#b3b3b3")
            ink = mix(base, WHITE, h) if enabled else tint(base, 80)
        paint_glyph(p, self.kind, self.text(), body.center(), self.glyph, ink)
        if self.show_focus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ON_ACCENT if self.look == "tab" else WHITE, 1.6))
            p.drawEllipse(QRectF(self.rect()).adjusted(.8, .8, -.8, -.8))


def faded(width, height, dpr):
    """A clear layer to letter into before fading its edges."""
    layer = QPixmap(round(width * dpr), round(height * dpr))
    layer.setDevicePixelRatio(dpr)
    layer.fill(Qt.GlobalColor.transparent)
    return layer


def fade_edges(q, width, height, left=0., right=0., top=0., bottom=0.):
    """Fade a layer to nothing over the given distance at each edge (DestinationIn)."""
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    for start, end, size in ((QPointF(0, 0), QPointF(left, 0), left), (QPointF(width, 0), QPointF(width - right, 0), right),
                             (QPointF(0, 0), QPointF(0, top), top), (QPointF(0, height), QPointF(0, height - bottom), bottom)):
        if size <= 0:
            continue
        ramp = QLinearGradient(start, end)
        ramp.setColorAt(0, QColor(0, 0, 0, 0))
        ramp.setColorAt(1, QColor(0, 0, 0, 255))
        q.fillRect(QRectF(0, 0, width, height), ramp)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


def sung_colours(lit, count, playing, now, sung, ahead):
    """The colour of each word on a sung line: words sung so far, the word now, and those still to come."""
    colours = []
    for i in range(count):
        if not playing or lit < 0:
            colours.append(sung if lit >= 0 and i <= lit else ahead)
        elif i == lit:
            colours.append(now)
        elif i < lit:
            colours.append(sung)
        else:
            colours.append(ahead)
    return colours


def wrap_words(lettering, metrics, width):
    """Lay words into rows no wider than width: [(row, left)] per word, and how many rows."""
    space = metrics.horizontalAdvance(" ")
    placed, row, x = [], 0, 0.
    for word in lettering:
        advance = metrics.horizontalAdvance(word)
        if x > 0 and x + advance > width:
            row, x = row + 1, 0.
        placed.append((row, x))
        x += advance + space
    return placed, (row + 1 if lettering else 0)


# --- Notch -------------------------------------------------------------------------------------

class NotchPlayer(MiniBase):
    """A tall dark card: Halo's mark on a tab, the clock on a bright tab, a raised lyric panel, and big keys."""
    STYLE = "notch"
    SIZE = (400, 336)
    LEFT, TOP, RIGHT, BOTTOM = 16., 14., 352., 316.
    STEP = 40.      # where the card's top steps down to the right of Halo's tab
    RADIUS = 24.
    FILLET = 12.
    LINE = 21.      # the lyric stack's line spacing
    CENTRE = 198.   # the lower half's centre line: between the card and the panel that juts past it

    def prepare(self):
        self.scroll = 0.
        self.mark_turn = 0.
        wordmark = QFontMetricsF(face(27, QFont.Weight.Bold, display=True)).horizontalAdvance("halo")
        self.tab_right = max(150., self.LEFT + 62 + wordmark + 22)
        self._path = None

    def accent(self):
        if getattr(self.c, "mini_song_accent", False):
            return vivid(getattr(self.c, "halo_primary", self.c.primary))
        return QColor(NEON)

    def make_key(self, kind, callback, hint):
        if kind == "play":
            return FaceKey(kind, callback, self.c, hint, size=44, glyph=17, look="accent", accent=self.accent)
        if kind in ("previous", "next"):
            return FaceKey(kind, callback, self.c, hint, size=40, glyph=17, look="flat", ink=lambda: NOTCH_MUTED)
        return FaceKey(kind, callback, self.c, hint, size=28, glyph=14, look="tab", accent=self.accent)

    def keys_hidden_at_rest(self):
        return (self.restore_button, self.close_button)

    # --- geometry ---------------------------------------------------------------------

    def card_path(self):
        """Halo's tab rises on the left; to its right the top steps down, joined by a soft S."""
        if self._path is not None:
            return self._path
        L, T, R, B, S, rad, r, tab = self.LEFT, self.TOP, self.RIGHT, self.BOTTOM, self.STEP, self.RADIUS, self.FILLET, self.tab_right
        path = QPainterPath(QPointF(L, T + rad))
        path.arcTo(QRectF(L, T, rad * 2, rad * 2), 180, -90)
        path.lineTo(tab - r, T)
        path.arcTo(QRectF(tab - r * 2, T, r * 2, r * 2), 90, -90)
        path.lineTo(tab, S - r)
        path.arcTo(QRectF(tab, S - r * 2, r * 2, r * 2), 180, 90)
        path.lineTo(R - rad, S)
        path.arcTo(QRectF(R - rad * 2, S, rad * 2, rad * 2), 90, -90)
        path.lineTo(R, B - rad)
        path.arcTo(QRectF(R - rad * 2, B - rad * 2, rad * 2, rad * 2), 0, -90)
        path.lineTo(L + rad, B)
        path.arcTo(QRectF(L, B - rad * 2, rad * 2, rad * 2), 270, -90)
        path.closeSubpath()
        self._path = path
        return path

    def tab_rect(self):
        """The bright tab's visible part, between the step and the lyric panel."""
        left = self.tab_right + self.FILLET
        return QRectF(left, self.STEP, self.RIGHT - left, self.panel().top() - self.STEP)

    def panel(self):
        return QRectF(34, 82, 350, 110)

    def art_rect(self):
        panel = self.panel()
        return QRectF(panel.left() + 14, panel.top() + 14, 82, 82)

    def stack_rect(self):
        panel, art = self.panel(), self.art_rect()
        left = art.right() + 16
        return QRectF(left, panel.top() + 36, panel.right() - 16 - left, panel.height() - 44)

    def bar(self):
        return QRectF(self.CENTRE - 142, 249, 284, 4)

    def seek_rect(self):
        return self.bar().adjusted(-6, -10, 6, 10)

    def controls_y(self):
        return 287.

    def arrange(self):
        y = self.controls_y()
        for key, x in ((self.previous, self.CENTRE - 76), (self.play, self.CENTRE), (self.next, self.CENTRE + 76)):
            key.move(round(x - key.width() / 2), round(y - key.height() / 2))
        tab = self.tab_rect()
        shown = _smooth(self.revealed)
        middle = tab.center().y() + 3 * (1 - shown)
        self.restore_button.move(round(tab.center().x() - 2 - self.restore_button.width()),
                                 round(middle - self.restore_button.height() / 2))
        self.close_button.move(round(tab.center().x() + 2), round(middle - self.close_button.height() / 2))
        self.show_revealed()

    def advance_time(self, elapsed, reduced):
        if self.c.track.playing and not reduced:
            self.mark_turn = (self.mark_turn + elapsed * 40) % 360

    def menu_extras(self):
        from .room_menu import MenuEntry
        return [MenuEntry("toggle", "Song colour accent", "halo", checked=lambda: getattr(self.c, "mini_song_accent", False),
                          run=lambda: self.c.set("mini_song_accent", not getattr(self.c, "mini_song_accent", False)))]

    # --- painting ---------------------------------------------------------------------

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        accent = self.accent()
        path = self.card_path()
        tab = self.tab_rect()
        panel = self.panel()

        # The card, its shadow on the desktop, and the bright tab's faint glow.
        body = QRectF(self.LEFT, self.STEP, self.RIGHT - self.LEFT, self.BOTTOM - self.STEP)
        paint_shadow(p, body, self.RADIUS, 14, .5, 6, BLACK)
        paint_shadow(p, QRectF(self.LEFT, self.TOP, self.tab_right - self.LEFT, 60), self.RADIUS, 12, .3, 4, BLACK)
        paint_shadow(p, tab.adjusted(4, 0, -4, 10), 18, 14, .32, -2, accent)
        fill = QLinearGradient(QPointF(0, self.TOP), QPointF(0, self.BOTTOM))
        fill.setColorAt(0, NOTCH_TOP)
        fill.setColorAt(1, NOTCH_LOW)
        p.setPen(QPen(QColor("#050505"), 1))
        p.setBrush(fill)
        p.drawPath(path)

        # The bright tab holds the clock; under the pointer the clock gives way to the window keys.
        p.save()
        p.setClipPath(path)
        pill = QPainterPath()
        pill.addRoundedRect(QRectF(tab.left(), tab.top(), tab.width() + 40, tab.height() + 40), 20, 20)
        shade = QLinearGradient(tab.topLeft(), tab.bottomLeft())
        shade.setColorAt(0, mix(accent, WHITE, .1))
        shade.setColorAt(1, accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        p.drawPath(pill)
        p.restore()
        shown = _smooth(self.revealed)
        if shown < .99:
            p.setOpacity(1 - shown)
            p.setFont(face(17, QFont.Weight.Bold, display=True))
            p.setPen(ON_ACCENT)
            p.drawText(tab.adjusted(0, -2 * shown, 0, 0), Qt.AlignmentFlag.AlignCenter, time_of_day())
            p.setOpacity(1.)
        p.setPen(QPen(tint(WHITE, 14), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        self._paint_brand(p, accent)

        # The raised panel: the cover, what is playing, and three lines of lyrics. It juts past the card.
        paint_shadow(p, panel, 16, 14, .62, 7, BLACK)
        raised = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        raised.setColorAt(0, NOTCH_PANEL)
        raised.setColorAt(1, NOTCH_PANEL_LOW)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(raised)
        p.drawRoundedRect(panel, 16, 16)
        p.setPen(QPen(tint(WHITE, 14), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(panel.adjusted(.5, .5, -.5, -.5), 15.5, 15.5)
        art = self.art_rect()
        p.drawPixmap(art.topLeft(), self.art(art.width(), 5))
        p.setPen(QPen(tint(WHITE, 18), 1))
        p.drawRoundedRect(art.adjusted(.5, .5, -.5, -.5), 4.5, 4.5)
        self._paint_tag(p, accent)
        self._paint_stack(p, readable_light(accent, NOTCH_PANEL, 4.5))

        # What is playing, the seek bar, and (as widgets) the keys.
        connected = self.connected()
        title = c.track.title if connected else "Halo"
        artist = c.track.artist if connected else "Play something in Spotify, a browser or any player."
        p.setPen(WHITE)
        font = face(16.5, QFont.Weight.Bold, display=True)
        p.setFont(font)
        width = 300
        text = QFontMetricsF(font).elidedText(title, Qt.TextElideMode.ElideRight, width)
        p.drawText(QRectF(self.CENTRE - width / 2, 200, width, 24), Qt.AlignmentFlag.AlignCenter, text)
        font = face(12.5, QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(NOTCH_MUTED)
        text = QFontMetricsF(font).elidedText(artist, Qt.TextElideMode.ElideRight, width)
        p.drawText(QRectF(self.CENTRE - width / 2, 223, width, 18), Qt.AlignmentFlag.AlignCenter, text)
        self._paint_bar(p, accent)

    def _paint_brand(self, p, accent):
        """Halo's mark, a bright disc holding the two halo rings, and the wordmark."""
        centre = QPointF(self.LEFT + 22 + 17, 47.)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawEllipse(centre, 17, 17)
        turn = self.mark_turn
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ON_ACCENT, 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(centre.x() - 10.5, centre.y() - 10.5, 21, 21), round((40 + turn) * 16), 250 * 16)
        p.setPen(QPen(ON_ACCENT, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(centre.x() - 5, centre.y() - 5, 10, 10), round((200 - turn * 1.6) * 16), 210 * 16)
        p.setFont(face(27, QFont.Weight.Bold, display=True))
        p.setPen(WHITE)
        p.drawText(QPointF(self.LEFT + 62, centre.y() + 9.5), "halo")

    def _paint_tag(self, p, accent):
        """• NOW PLAYING, and a bright tick when the song has synced lyrics."""
        c = self.c
        art = self.art_rect()
        panel = self.panel()
        if not self.connected():
            tag = "WAITING FOR MUSIC"
        else:
            tag = "NOW PLAYING" if c.track.playing else "PAUSED"
        font = face(12, QFont.Weight.Bold, display=True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, .4)
        p.setFont(font)
        p.setPen(WHITE)
        x = art.right() + 16
        p.setBrush(WHITE)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x + 2.5, panel.top() + 21.5), 2.4, 2.4)
        p.setPen(WHITE)
        p.drawText(QPointF(x + 10, panel.top() + 26), tag)
        if self.has_lyrics():
            badge = QPointF(panel.right() - 24, panel.top() + 21)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawEllipse(badge, 9, 9)
            p.setPen(QPen(ON_ACCENT, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            tick = QPainterPath(QPointF(badge.x() - 4, badge.y() + .2))
            tick.lineTo(badge.x() - 1.2, badge.y() + 3)
            tick.lineTo(badge.x() + 4.2, badge.y() - 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(tick)

    def _paint_stack(self, p, light):
        """The line before, the line being sung (lit), and the line after, rising as the song moves on."""
        c = self.c
        area = self.stack_rect()
        dpr = self.devicePixelRatioF()
        layer = faded(area.width() + 2, area.height(), dpr)
        q = QPainter(layer)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        width, middle = area.width(), area.height() / 2 + 5
        text, words, current, index = self.line()
        if self.note_line(index, text):
            self.scroll = 0.
        if self.has_lyrics() and (text or index >= 0):
            before, after = self.neighbours(index) if index >= 0 else ("", "")
            rise = (1 - self.settle()) * self.LINE
            side = face(13.5, QFont.Weight.Bold, display=True)
            q.setFont(side)
            q.setPen(tint(light, 104))
            if before:
                q.drawText(QPointF(0, middle - self.LINE + rise), before)
            q.setPen(tint(light, 112))
            if after:
                q.drawText(QPointF(0, middle + self.LINE + rise), after)
            if text:
                font = face(14.5, QFont.Weight.Bold, display=True)
                metrics = QFontMetricsF(font)
                lettering = [word for word, _ in words]
                lefts, total = word_lefts(lettering, metrics)
                self.scroll = glide(self.scroll, lefts, lettering, metrics, current, total, width, self.reduced())
                colours = sung_colours(current, len(lettering), c.track.playing, light, light, tint(light, 150))
                q.setFont(font)
                for i, word in enumerate(lettering):
                    q.setPen(colours[i])
                    q.drawText(QPointF(lefts[i] - self.scroll, middle + rise), word)
        else:
            status = self.lyric_status() or "Play a song in any player"
            q.setFont(face(13.5, QFont.Weight.DemiBold, display=True))
            q.setPen(NOTCH_MUTED)
            q.drawText(QPointF(0, middle), status)
        fade_edges(q, width + 2, area.height(), right=22, top=16, bottom=14)
        q.end()
        p.drawPixmap(area.topLeft(), layer)

    def _paint_bar(self, p, accent):
        bar = self.bar()
        y = bar.center().y()
        fraction = self.fraction()
        p.setPen(QPen(NOTCH_TRACK, bar.height(), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(bar.left(), y), QPointF(bar.right(), y))
        x = bar.left() + bar.width() * fraction
        if fraction > 0:
            p.setPen(QPen(accent, bar.height(), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(bar.left(), y), QPointF(x, y))
        if self.connected():
            radius = 6.5 if self.hovered else 5.5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tint(accent, 60))
            p.drawEllipse(QPointF(x, y), radius + 3, radius + 3)
            p.setBrush(accent)
            p.drawEllipse(QPointF(x, y), radius, radius)


# --- Capsule -----------------------------------------------------------------------------------

class CapsulePlayer(MiniBase):
    """A slim dark pill: a round cover ringed by progress, the line being sung, a small live meter and play."""
    STYLE = "capsule"
    SIZE = (352, 88)

    def prepare(self):
        self.scroll = 0.
        self.meter_time = 0.

    def make_key(self, kind, callback, hint):
        if kind == "play":
            return FaceKey(kind, callback, self.c, hint, size=36, glyph=14, look="accent", accent=self.light)
        if kind in ("previous", "next"):
            return FaceKey(kind, callback, self.c, hint, size=30, glyph=12, look="flat", ink=lambda: MUTED)
        return FaceKey(kind, callback, self.c, hint, size=24, glyph=12, look="glass")

    def light(self):
        return readable_light(song_light(self.c), GLASS_TOP, 4.5)

    def pill(self):
        return QRectF(12, 20, self.width() - 24, 56)

    def art_rect(self):
        pill = self.pill()
        return QRectF(pill.left() + 6, pill.center().y() - 22, 44, 44)

    def play_rest(self):
        pill = self.pill()
        return QPointF(pill.right() - 10 - self.play.width(), pill.center().y() - self.play.height() / 2)

    def meter_rect(self):
        rest = self.play_rest()
        return QRectF(rest.x() - 12 - 22, self.pill().center().y() - 9, 22, 18)

    def text_rect(self):
        pill, art = self.pill(), self.art_rect()
        left = art.right() + 12
        shown = _smooth(self.revealed)
        right = self.meter_rect().left() - 10 if shown < .5 else self.previous.x() - 8
        return QRectF(left, pill.top(), max(20., right - left), pill.height())

    def arrange(self):
        shown = _smooth(self.revealed)
        rest = self.play_rest()
        step = self.next.width() + 2
        x = rest.x() - step * shown
        self.play.move(round(x), round(rest.y()))
        middle = rest.y() + self.play.height() / 2
        self.previous.move(round(x - 2 - self.previous.width()), round(middle - self.previous.height() / 2))
        self.next.move(round(x + self.play.width() + 2), round(middle - self.next.height() / 2))
        pill = self.pill()
        chip_y = round(pill.top() - 15 + 3 * (1 - shown))
        self.close_button.move(round(pill.right() - 22 - self.close_button.width()), chip_y)
        self.restore_button.move(round(self.close_button.x() - 5 - self.restore_button.width()), chip_y)
        self.show_revealed()

    def advance_time(self, elapsed, reduced):
        if self.c.track.playing and not reduced:
            self.meter_time += elapsed * (1. + 1.6 * min(1., getattr(self.c, "pulse", 0.)))

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pill = self.pill()
        radius = pill.height() / 2
        light = song_light(c)
        paint_shadow(p, pill, radius, 12, .5, 5, BLACK)
        shape = QPainterPath()
        shape.addRoundedRect(pill, radius, radius)
        fill = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        fill.setColorAt(0, GLASS_TOP)
        fill.setColorAt(1, GLASS_LOW)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(shape)
        # The song's light glows out from behind the cover and fades along the pill, breathing with the beat.
        art = self.art_rect()
        breath = min(1., getattr(c, "pulse", 0.)) if c.track.playing and not self.reduced() else 0.
        wash = QRadialGradient(art.center(), pill.width() * .62)
        wash.setColorAt(0, tint(light, 92 + 40 * breath))
        wash.setColorAt(.45, tint(light, 26 + 12 * breath))
        wash.setColorAt(1, tint(light, 0))
        p.save()
        p.setClipPath(shape)
        p.fillRect(pill, wash)
        p.restore()
        p.setPen(QPen(tint(WHITE, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pill.adjusted(.5, .5, -.5, -.5), radius - .5, radius - .5)

        # The round cover, ringed by how far the song has gone.
        p.drawPixmap(art.topLeft(), self.art(art.width(), round_=True))
        ring = art.adjusted(-3.5, -3.5, 3.5, 3.5)
        p.setPen(QPen(tint(WHITE, 30), 2.2))
        p.drawEllipse(ring)
        fraction = self.fraction()
        if fraction > 0:
            p.setPen(QPen(self.light(), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, -round(fraction * 360 * 16))

        self._paint_words(p)
        self._paint_meter(p)

    def _paint_words(self, p):
        c = self.c
        area = self.text_rect()
        dpr = self.devicePixelRatioF()
        layer = faded(area.width() + 2, area.height(), dpr)
        q = QPainter(layer)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        connected = self.connected()
        text, words, current, index = self.line()
        if self.note_line(index, text):
            self.scroll = 0.
        title = c.track.title if connected else "Halo"
        artist = c.track.artist if connected else "Play something in any player"
        middle = area.height() / 2
        if text and self.has_lyrics():
            font = face(14, QFont.Weight.DemiBold, display=True)
            metrics = QFontMetricsF(font)
            lettering = [word for word, _ in words]
            lefts, total = word_lefts(lettering, metrics)
            self.scroll = glide(self.scroll, lefts, lettering, metrics, current, total, area.width(), self.reduced())
            settle = self.settle()
            colours = sung_colours(current, len(lettering), c.track.playing, self.light(), WHITE, tint(WHITE, 130))
            q.setFont(font)
            q.setOpacity(.3 + .7 * settle)
            for i, word in enumerate(lettering):
                q.setPen(colours[i])
                q.drawText(QPointF(lefts[i] - self.scroll, middle - 1 + (1 - settle) * 6), word)
            q.setOpacity(1.)
            q.setFont(face(11, QFont.Weight.Medium))
            q.setPen(MUTED)
            q.drawText(QPointF(0, middle + 16), f"{title} · {artist}" if artist else title)
        else:
            q.setFont(face(14, QFont.Weight.DemiBold, display=True))
            q.setPen(WHITE)
            q.drawText(QPointF(0, middle - 1), title)
            q.setFont(face(11, QFont.Weight.Medium))
            q.setPen(MUTED)
            q.drawText(QPointF(0, middle + 16), artist)
        if self.scroll > .5 and text and self.has_lyrics():
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            lead = QLinearGradient(QPointF(0, 0), QPointF(18, 0))
            lead.setColorAt(0, QColor(0, 0, 0, round(255 * max(0., 1 - self.scroll / 12))))
            lead.setColorAt(1, QColor(0, 0, 0, 255))
            q.fillRect(QRectF(0, middle - 18, 18, 23), lead)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        fade_edges(q, area.width() + 2, area.height(), right=20)
        q.end()
        p.drawPixmap(area.topLeft(), layer)

    def _paint_meter(self, p):
        """Four small bars in the song's light, moving with the music; they give way to the keys."""
        shown = _smooth(self.revealed)
        if shown > .98:
            return
        rect = self.meter_rect()
        playing = self.c.track.playing
        pulse = min(1., getattr(self.c, "pulse", 0.))
        p.setOpacity(1 - shown)
        p.setPen(QPen(self.light(), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i, (speed, phase, rest) in enumerate(((3.1, 0., .45), (4.3, 1.7, .8), (2.6, 3.1, .6), (3.7, 4.4, .35))):
            if playing and not self.reduced():
                level = .3 + .7 * abs(math.sin(self.meter_time * speed + phase)) * (.6 + .4 * pulse)
            elif playing:
                level = rest
            else:
                level = .08
            x = rect.left() + 1.5 + i * 6.3
            height = max(1., (rect.height() - 3) * level)
            p.drawLine(QPointF(x, rect.bottom() - 1.5), QPointF(x, rect.bottom() - 1.5 - height))
        p.setOpacity(1.)


# --- Disc --------------------------------------------------------------------------------------

class DiscPlayer(MiniBase):
    """The cover as a record that turns while the song plays, ringed by its progress, with a caption beneath."""
    STYLE = "disc"
    SIZE = (248, 308)
    TURN = 14.  # seconds for one turn of the record
    ROW = 19.   # the caption's line spacing

    def prepare(self):
        self.angle = 0.
        self.scroll = 0.

    def make_key(self, kind, callback, hint):
        if kind == "play":
            return FaceKey(kind, callback, self.c, hint, size=50, glyph=18, look="accent", accent=self.light)
        if kind in ("previous", "next"):
            return FaceKey(kind, callback, self.c, hint, size=38, glyph=14, look="glass")
        return FaceKey(kind, callback, self.c, hint, size=26, glyph=13, look="glass")

    def keys_hidden_at_rest(self):
        return (self.previous, self.play, self.next, self.restore_button, self.close_button)

    def light(self):
        return readable_light(song_light(self.c), GLASS_TOP, 4.5)

    def disc(self):
        return QRectF(24, 18, 200, 200)

    art_rect = disc

    def caption_rect(self):
        return QRectF(10, 236, self.width() - 20, 34 + self.ROW)

    def arrange(self):
        disc = self.disc()
        centre = disc.center()
        shown = _smooth(self.revealed)
        drop = 4 * (1 - shown)
        for key, dx in ((self.previous, -60), (self.play, 0), (self.next, 60)):
            key.move(round(centre.x() + dx - key.width() / 2), round(centre.y() + 6 + drop - key.height() / 2))
        self.close_button.move(round(disc.right() - 6 - self.close_button.width() / 2), round(disc.top() - 8 + drop))
        self.restore_button.move(round(self.close_button.x() - 30), round(disc.top() - 8 + drop))
        self.show_revealed()

    def advance_time(self, elapsed, reduced):
        if self.c.track.playing and not reduced:
            self.angle = (self.angle + elapsed * 360 / self.TURN) % 360

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        disc = self.disc()
        centre = disc.center()
        radius = disc.width() / 2
        light = self.light()

        paint_shadow(p, disc, radius, 16, .55, 8, BLACK)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b0c0c"))
        p.drawEllipse(disc)
        # The cover as a picture disc, turning while the song plays.
        side = disc.width() - 16
        p.save()
        p.translate(centre)
        p.rotate(self.angle)
        p.drawPixmap(QPointF(-side / 2, -side / 2), self.art(side, round_=True))
        p.restore()
        # Grooves, and a still sheen of light across them.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, r in enumerate(range(16, round(radius) - 1, 5)):
            p.setPen(QPen(tint(BLACK if i % 2 else WHITE, 14 if r < side / 2 else 22), 1))
            p.drawEllipse(centre, r, r)
        sheen = QConicalGradient(centre, 35)
        for at, alpha in ((0, 0), (.06, 46), (.14, 0), (.5, 0), (.56, 34), (.64, 0), (1, 0)):
            sheen.setColorAt(at, tint(WHITE, alpha))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sheen)
        p.drawEllipse(disc)
        p.setPen(QPen(tint(WHITE, 26), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(disc.adjusted(.5, .5, -.5, -.5))
        # The spindle.
        p.setPen(QPen(tint(WHITE, 60), 1))
        p.setBrush(QColor("#0b0c0c"))
        p.drawEllipse(centre, 9, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3a3f3d"))
        p.drawEllipse(centre, 3, 3)

        # Progress runs round the record.
        ring = disc.adjusted(-6, -6, 6, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(tint(WHITE, 34), 3))
        p.drawEllipse(ring)
        fraction = self.fraction()
        if fraction > 0:
            p.setPen(QPen(light, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, -round(fraction * 360 * 16))
            angle = math.radians(90 - fraction * 360)
            dot = QPointF(centre.x() + math.cos(angle) * ring.width() / 2, centre.y() - math.sin(angle) * ring.height() / 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(light, WHITE, .35))
            p.drawEllipse(dot, 4, 4)

        # Under the pointer, the record dims and names the song around its keys.
        shown = _smooth(self.revealed)
        if shown > .01:
            p.setOpacity(shown)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tint(BLACK, 150))
            p.drawEllipse(disc)
            connected = self.connected()
            title = c.track.title if connected else "Halo"
            artist = c.track.artist if connected else "Play something"
            font = face(13.5, QFont.Weight.Bold, display=True)
            p.setFont(font)
            p.setPen(WHITE)
            p.drawText(QRectF(centre.x() - 75, centre.y() - 58, 150, 20), Qt.AlignmentFlag.AlignCenter,
                       QFontMetricsF(font).elidedText(title, Qt.TextElideMode.ElideRight, 150))
            font = face(11.5, QFont.Weight.Medium)
            p.setFont(font)
            p.setPen(MUTED)
            p.drawText(QRectF(centre.x() - 70, centre.y() + 38, 140, 18), Qt.AlignmentFlag.AlignCenter,
                       QFontMetricsF(font).elidedText(artist, Qt.TextElideMode.ElideRight, 140))
            p.setOpacity(1.)

        self._paint_caption(p, light)

    def _paint_caption(self, p, light):
        """The line being sung on a small dark caption under the record, centred on up to two rows.

        With no words to show, the caption names the song instead.
        """
        c = self.c
        text, words, current, index = self.line()
        self.note_line(index, text)
        lyric = bool(text) and self.has_lyrics()
        if lyric:
            lettering = [word for word, _ in words]
        else:
            connected = self.connected()
            name = f"{c.track.title} — {c.track.artist}" if connected and c.track.artist else (c.track.title if connected else "Halo")
            lettering = name.split()
            current = -1
        if not lettering:
            return
        font = face(13.5, QFont.Weight.DemiBold, display=True)
        metrics = QFontMetricsF(font)
        room = self.caption_rect()
        placed, rows = wrap_words(lettering, metrics, room.width() - 30)
        first = 0
        if rows > 2:
            # Keep the word being sung in view: the row it is on and the one before.
            row_now = placed[current][0] if 0 <= current < len(placed) else 0
            first = max(0, min(rows - 2, row_now - 1))
        shown_rows = min(2, rows)
        widths = {}
        for (row, left), word in zip(placed, lettering):
            widths[row] = left + metrics.horizontalAdvance(word)
        widest = max(widths.get(row, 0.) for row in range(first, first + shown_rows))
        width = min(room.width(), widest + 30)
        height = 34 + self.ROW * (shown_rows - 1)
        pill = QRectF(room.center().x() - width / 2, room.top(), width, height)
        paint_shadow(p, pill, 17, 10, .45, 4, BLACK)
        fill = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        fill.setColorAt(0, GLASS_TOP)
        fill.setColorAt(1, GLASS_LOW)
        p.setPen(QPen(tint(WHITE, 24), 1))
        p.setBrush(fill)
        p.drawRoundedRect(pill.adjusted(.5, .5, -.5, -.5), 16.5, 16.5)
        if lyric:
            colours = sung_colours(current, len(lettering), c.track.playing, light, WHITE, tint(WHITE, 130))
        else:
            colours = [MUTED] * len(lettering)
        settle = self.settle() if lyric else 1.
        p.save()
        p.setFont(font)
        p.setOpacity(.3 + .7 * settle)
        for i, word in enumerate(lettering):
            row, left = placed[i]
            if not first <= row < first + shown_rows:
                continue
            x = pill.center().x() - widths[row] / 2 + left
            y = pill.top() + 22 + (row - first) * self.ROW + (1 - settle) * 5
            p.setPen(colours[i])
            p.drawText(QPointF(x, y), word)
        p.restore()


# --- Poster ------------------------------------------------------------------------------------

class PosterPlayer(MiniBase):
    """The cover edge to edge, the line being sung lettered over its foot, and a bright play key."""
    STYLE = "poster"
    SIZE = (264, 300)

    def prepare(self):
        self.rows_shown = 0.

    def make_key(self, kind, callback, hint):
        if kind == "play":
            return FaceKey(kind, callback, self.c, hint, size=38, glyph=15, look="accent", accent=self.light)
        if kind in ("previous", "next"):
            return FaceKey(kind, callback, self.c, hint, size=32, glyph=13, look="flat", ink=lambda: WHITE)
        return FaceKey(kind, callback, self.c, hint, size=26, glyph=13, look="glass")

    def light(self):
        return readable_light(song_light(self.c), QColor("#141414"), 4.5)

    def card(self):
        return QRectF(14, 12, 236, 268)

    art_rect = card

    def play_rest(self):
        card = self.card()
        return QPointF(card.right() - 12 - self.play.width(), card.bottom() - 14 - self.play.height())

    def arrange(self):
        shown = _smooth(self.revealed)
        rest = self.play_rest()
        x = rest.x() - (self.next.width() + 2) * shown
        self.play.move(round(x), round(rest.y()))
        middle = rest.y() + self.play.height() / 2
        self.previous.move(round(x - 2 - self.previous.width()), round(middle - self.previous.height() / 2))
        self.next.move(round(x + self.play.width() + 2), round(middle - self.next.height() / 2))
        card = self.card()
        top = round(card.top() + 10 - 3 * (1 - shown))
        self.close_button.move(round(card.right() - 10 - self.close_button.width()), top)
        self.restore_button.move(round(self.close_button.x() - 6 - self.restore_button.width()), top)
        self.show_revealed()

    def paintEvent(self, event):
        c = self.c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = self.card()
        light = self.light()
        paint_shadow(p, card, 18, 16, .55, 7, BLACK)
        shape = QPainterPath()
        shape.addRoundedRect(card, 18, 18)
        p.save()
        p.setClipPath(shape)
        side = card.height()
        p.drawPixmap(QPointF(card.center().x() - side / 2, card.top()), self.art(side))
        # A dark fall at the foot for the lettering, faintly in the song's colour.
        ground = mix(BLACK, getattr(c, "halo_primary", c.primary), .12)
        foot = QLinearGradient(QPointF(0, card.top() + card.height() * .34), QPointF(0, card.bottom()))
        foot.setColorAt(0, tint(ground, 0))
        foot.setColorAt(.45, tint(ground, 150))
        foot.setColorAt(1, tint(ground, 238))
        p.fillRect(card, foot)
        shown = _smooth(self.revealed)
        if shown > .01:
            head = QLinearGradient(QPointF(0, card.top()), QPointF(0, card.top() + 64))
            head.setColorAt(0, tint(BLACK, 130 * shown))
            head.setColorAt(1, tint(BLACK, 0))
            p.fillRect(card, head)
        # Progress along the very foot of the poster.
        fraction = self.fraction()
        y = card.bottom() - 1.5
        p.setPen(QPen(tint(WHITE, 40), 3))
        p.drawLine(QPointF(card.left(), y), QPointF(card.right(), y))
        if fraction > 0:
            p.setPen(QPen(light, 3))
            p.drawLine(QPointF(card.left(), y), QPointF(card.left() + card.width() * fraction, y))
        p.restore()
        p.setPen(QPen(tint(WHITE, 26), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(.5, .5, -.5, -.5), 17.5, 17.5)

        self._paint_names(p)
        self._paint_lyric(p, light)

    def _paint_names(self, p):
        c = self.c
        card = self.card()
        connected = self.connected()
        title = c.track.title if connected else "Halo"
        artist = c.track.artist if connected else "Play something in any player"
        left = card.left() + 16
        right = (self.previous.x() if self.revealed > .02 else self.play.x()) - 10
        width = max(20., right - left)
        font = face(14.5, QFont.Weight.Bold, display=True)
        p.setFont(font)
        p.setPen(WHITE)
        p.drawText(QPointF(left, card.bottom() - 34), QFontMetricsF(font).elidedText(title, Qt.TextElideMode.ElideRight, width))
        font = face(11.5, QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(tint(WHITE, 190))
        p.drawText(QPointF(left, card.bottom() - 17), QFontMetricsF(font).elidedText(artist, Qt.TextElideMode.ElideRight, width))

    def _paint_lyric(self, p, light):
        """The line being sung in poster lettering, up to two rows, rising into place when it changes."""
        c = self.c
        text, words, current, index = self.line()
        self.note_line(index, text)
        if not text or not self.has_lyrics():
            return
        card = self.card()
        font = face(18, QFont.Weight.Bold, display=True)
        metrics = QFontMetricsF(font)
        lettering = [word for word, _ in words]
        width = card.width() - 32
        placed, rows = wrap_words(lettering, metrics, width)
        line_height = 23.
        first = 0
        if rows > 2:
            # Keep the word being sung in view: show the row it is on and the one before.
            row_now = placed[current][0] if 0 <= current < len(placed) else 0
            first = max(0, min(rows - 2, row_now - 1))
        shown_rows = min(2, rows)
        settle = self.settle()
        bottom = card.bottom() - 58
        colours = sung_colours(current, len(lettering), c.track.playing, light, WHITE, tint(WHITE, 150))
        p.save()
        p.setFont(font)
        p.setOpacity(.25 + .75 * settle)
        for i, word in enumerate(lettering):
            row, left = placed[i]
            if not first <= row < first + shown_rows:
                continue
            y = bottom - (shown_rows - 1 - (row - first)) * line_height + (1 - settle) * 8
            p.setPen(colours[i])
            p.drawText(QPointF(card.left() + 16 + left, y), word)
        p.restore()


MINI_CLASSES = {
    "case": MiniPlayer,
    "notch": NotchPlayer,
    "capsule": CapsulePlayer,
    "disc": DiscPlayer,
    "poster": PosterPlayer,
}
assert tuple(MINI_CLASSES) == MINI_STYLE_KEYS


def create_mini(controller, style=None):
    """A mini player in the chosen style (the controller's, unless one is named)."""
    key = style or getattr(controller, "mini_style", MINI_STYLE_KEYS[0])
    return MINI_CLASSES.get(key, MiniPlayer)(controller)
