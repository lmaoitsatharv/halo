"""The mini player: a small always-on-top window for the song, while Halo's window rests.

It comes in several styles (MINI_STYLES). They share one window, MiniBase: it stays on top, drags
from anywhere, remembers where it was left, answers the same keys (Space, Ctrl+Left, Ctrl+Right,
Esc), and opens a Windows 11 style menu on right-click for switching styles. Each style decides
only how the song looks and where its keys sit.

The Case style lives here: a small dark case holding the framed print under the song's light, the
title and artist, the line being sung with its word in that light, a fine progress line and the
play key. Hovering, or tabbing in, brings up previous and next beside play, the times, and two
small keys on the case's top edge: back to Halo, and close to the tray. The case is dark in both
lights, so it sits well on any desktop.

The other styles are in mini_styles.py.
"""
import math
import time

from PySide6.QtCore import Qt, QRectF, QPointF, QPoint, QTimer, Signal
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont, QFontMetricsF, QKeySequence, QShortcut,
                           QGuiApplication, QLinearGradient, QPixmap)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .gallery import (HANDSET_INK, HANDSET_MUTED, HANDSET_RAISED, FRAME, MAT, WHITE, HandsetButton, _Hover, face,
                      tint, mix, paint_shadow, paint_spotlight, song_light, contrast)
from .wall import wall_lines, line_words, sung_word
from .models import TAGLINE, finding_lyrics

CASE_TOP = QColor("#1a2420")
CASE_LOW = QColor("#0f1513")
CASE_EDGE = QColor("#060a09")

# Every look the mini player can take: (key, name, what it is). The first is the default.
MINI_STYLES = (
    ("case", "Case", "The cover as a small print in a lit case, with the line being sung."),
    ("notch", "Notch", "A tall card: the cover, three lines of lyrics, the clock on a bright tab, and big keys."),
    ("capsule", "Capsule", "A slim pill: a round cover ringed by progress, the line being sung, and play."),
    ("disc", "Disc", "The cover as a record that turns while the song plays, ringed by its progress."),
    ("poster", "Poster", "The cover, edge to edge, with the line being sung lettered over it."),
)
MINI_STYLE_KEYS = tuple(spec[0] for spec in MINI_STYLES)


def mini_style_name(key):
    return next((name for style, name, _ in MINI_STYLES if style == key), MINI_STYLES[0][1])


def next_mini_style(key):
    keys = MINI_STYLE_KEYS
    return keys[(keys.index(key) + 1) % len(keys)] if key in keys else keys[0]


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


class MiniBase(QWidget):
    """The window every mini player style shares: on top, draggable, remembered, with the same keys and menu.

    A style sets STYLE and SIZE, makes its keys in make_key(), places them in arrange(), and paints
    in paintEvent(). Keys listed in hidden_keys come up while the pointer is over the window or the
    keyboard is in it.
    """
    restoreRequested = Signal()
    closeRequested = Signal()
    STYLE = ""
    SIZE = (320, 120)
    REVEAL = .16  # seconds for the hidden keys to come up or go
    RISE = .32    # seconds for a new lyric line to settle

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
        self._seeking = False
        self.pixmap = QPixmap()
        self.track_key = None
        self.art_cache = {}
        self.hovered = False
        self.revealed = 0.
        self._last_tick = None
        self.shown_index = None
        self.changed_at = 0.
        self.menu = None
        self.prepare()
        self.previous = self.make_key("previous", lambda: controller.transport("previous"), "Ctrl+Left")
        self.play = self.make_key("play", lambda: controller.transport("toggle"), "Space")
        self.next = self.make_key("next", lambda: controller.transport("next"), "Ctrl+Right")
        self.restore_button = self.make_key("restore", self.restoreRequested.emit, "Esc")
        self.close_button = self.make_key("close", self.closeRequested.emit, "")
        self.hidden_keys = self.keys_hidden_at_rest()
        self.fades = {}
        for key in (self.previous, self.play, self.next, self.restore_button, self.close_button):
            key.setParent(self)
        for key in self.hidden_keys:
            effect = QGraphicsOpacityEffect(key)
            effect.setOpacity(0.)
            key.setGraphicsEffect(effect)
            self.fades[key] = effect
            key.hide()
        connected = lambda action: (lambda: controller.transport(action) if controller.track.connected else None)
        QShortcut(QKeySequence("Space"), self, activated=connected("toggle"))
        QShortcut(QKeySequence("Esc"), self, activated=self.restoreRequested.emit)
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=connected("previous"))
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=connected("next"))
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, activated=self.next_style)
        controller.trackChanged.connect(self.refresh)
        self.arrange()
        self.refresh()

    # --- what each style supplies ---------------------------------------------------------

    def prepare(self):
        """Set up the style's own state, before its keys are made."""

    def make_key(self, kind, callback, hint):
        raise NotImplementedError

    def keys_hidden_at_rest(self):
        return (self.previous, self.next, self.restore_button, self.close_button)

    def arrange(self):
        """Place the keys for the current reveal. Styles move their keys, then call show_revealed()."""
        self.show_revealed()

    def art_rect(self):
        """Where the cover sits; a click there brings Halo back."""
        return QRectF()

    def seek_rect(self):
        """A progress bar that can be clicked to move through the song, or an empty rect for none."""
        return QRectF()

    def song_changed(self, first):
        """A new song (or new artwork) arrived. first is True when it is the window's first song."""

    def advance(self, step, reduced):
        """Move this style's own animations along, once a tick while visible."""

    def menu_extras(self):
        """Extra rows for the right-click menu, under the Style flyout."""
        return []

    # --- shared state ----------------------------------------------------------------------

    def show_revealed(self):
        shown = _smooth(self.revealed)
        for key, effect in self.fades.items():
            effect.setOpacity(shown)
            key.setVisible(self.revealed > .02)

    def wants_keys(self):
        keys = (self.previous, self.play, self.next, self.restore_button, self.close_button)
        return self.hovered or any(getattr(key, "keyboard_focus", False) for key in keys)

    def refresh(self):
        c = self.c
        self.play.setText("Ⅱ" if c.track.playing else "▶")
        for button in (self.previous, self.play, self.next):
            button.setEnabled(c.track.connected)
        key = (c.track.key, len(c.track.artwork))
        if key != self.track_key:
            first = self.track_key is None
            self.song_changed(first)
            self.track_key = key
            self.pixmap = QPixmap()
            if c.track.artwork:
                self.pixmap.loadFromData(c.track.artwork)
            self.art_cache.clear()
        self.update()

    def connected(self):
        return self.c.track.connected or getattr(self.c, "demo", False)

    def has_lyrics(self):
        return bool(getattr(self.c.lyrics, "lines", None)) and self.connected()

    def reduced(self):
        return getattr(self.c, "reduced_motion", False)

    def position(self):
        return self.c.position + getattr(self.c, "offset", 0) / 1000

    def fraction(self):
        duration = max(0., float(self.c.track.duration or 0))
        return max(0., min(1., self.c.position / duration)) if duration > 0 else 0.

    def line(self):
        """(text, words, index of the word being sung, line index) for the lyric at this moment."""
        lyrics = self.c.lyrics
        if not getattr(lyrics, "lines", None):
            return "", [], -1, -1
        position = self.position()
        _, line, index, waiting = wall_lines(lyrics, position)
        if line is None or not line.text.strip():
            return "", [], -1, index
        words = line_words(line)
        later = [item.time for item in lyrics.lines[index + 1:] if item.time > line.time]
        current = -1 if waiting else sung_word(line, words, position, later[0] if later else None)
        return line.text.strip(), words, current, index

    def neighbours(self, index):
        """The nearest lines with words before and after a line index."""
        lines = getattr(self.c.lyrics, "lines", None) or []
        before = next((lines[i].text.strip() for i in range(index - 1, -1, -1) if lines[i].text.strip()), "")
        after = next((lines[i].text.strip() for i in range(index + 1, len(lines)) if lines[i].text.strip()), "")
        return before, after

    def note_line(self, index, text):
        """Start the settle animation when the line being sung changes."""
        if index != self.shown_index:
            if self.shown_index is not None and not self.reduced():
                self.changed_at = time.monotonic()
            self.shown_index = index
            self.setAccessibleDescription(text)
            return True
        return False

    def settle(self):
        """0 just after the line changed, 1 once it has settled."""
        return _ease((time.monotonic() - self.changed_at) / self.RISE) if self.changed_at else 1.

    def lyric_status(self):
        """What to say with no line to show: the search while it runs, otherwise Halo's tagline."""
        if not self.connected():
            return ""
        return "Finding lyrics…" if finding_lyrics(self.c.lyrics) else TAGLINE

    def art(self, side, radius=0., round_=False):
        """The cover cropped to a square of this side (rounded, or a circle), cached for the song."""
        dpr = self.devicePixelRatioF()
        key = (round(side), round(radius, 1), round_, dpr, self.c.halo_primary.rgba() if self.pixmap.isNull() else 0)
        cached = self.art_cache.get(key)
        if cached is not None:
            return cached
        image = QPixmap(round(side * dpr), round(side * dpr))
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, side, side)
        clip = QPainterPath()
        if round_:
            clip.addEllipse(rect)
        else:
            clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip)
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(round(side * dpr), round(side * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            p.drawPixmap(QPointF(side / 2 - scaled.width() / dpr / 2, side / 2 - scaled.height() / dpr / 2), scaled)
        else:
            paint_dark_placeholder(p, rect, song_light(self.c))
        p.end()
        if len(self.art_cache) > 8:
            self.art_cache.clear()
        self.art_cache[key] = image
        return image

    # --- placing ---------------------------------------------------------------------------

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
        self.move(self._inside(target, area))

    def place_like(self, previous):
        """Take the place of another mini player, holding to whichever screen edges it was nearer."""
        screen = QGuiApplication.screenAt(previous.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = previous.right() + 1 - self.width() if previous.center().x() > area.center().x() else previous.left()
        y = previous.bottom() + 1 - self.height() if previous.center().y() > area.center().y() else previous.top()
        self.move(self._inside(QPoint(x, y), area))

    def _inside(self, target, area):
        return QPoint(max(area.left(), min(target.x(), area.right() + 1 - self.width())),
                      max(area.top(), min(target.y(), area.bottom() + 1 - self.height())))

    def remember(self):
        self.c.settings.setValue("mini_position", f"{self.x()},{self.y()}")

    # --- the menu --------------------------------------------------------------------------

    def choose_style(self, key):
        """Ask for another style. The main window swaps the mini player once the setting changes."""
        if key in MINI_STYLE_KEYS and key != getattr(self.c, "mini_style", ""):
            self.c.set("mini_style", key)

    def next_style(self):
        self.choose_style(next_mini_style(getattr(self.c, "mini_style", self.STYLE)))

    def menu_entries(self):
        from .room_menu import MenuEntry, separator
        styles = lambda: [MenuEntry("radio", name, run=lambda key=key: self.choose_style(key), tip=description,
                                    checked=lambda key=key: self.STYLE == key)
                          for key, name, description in MINI_STYLES]
        entries = [MenuEntry("submenu", "Style", "mini", submenu=styles, detail=lambda: mini_style_name(self.STYLE)),
                   MenuEntry("action", "Next style", "forward", run=self.next_style, shortcut="Ctrl+Shift+M")]
        entries += self.menu_extras()
        entries += [separator(),
                    MenuEntry("action", "Back to Halo", "restore", run=self.restoreRequested.emit, shortcut="Esc"),
                    MenuEntry("action", "Close to the tray", "close", run=self.closeRequested.emit)]
        return entries

    def open_menu(self, global_point):
        from .room_menu import RoomMenu
        if self.menu is not None:
            self.menu.close()
            self.menu.deleteLater()
        self.menu = RoomMenu(self.menu_entries, self, title="Mini player menu")
        self.menu.open_at(global_point)
        return self.menu

    def contextMenuEvent(self, event):
        self.open_menu(event.globalPos())
        event.accept()

    # --- moving it -------------------------------------------------------------------------

    def tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        elapsed = 0. if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        reduced = self.reduced()
        # At least one step a tick, so the keys still come up when frames are slow or come in a burst.
        step = 1. if reduced else max(.1, elapsed / self.REVEAL)
        target = 1. if self.wants_keys() else 0.
        if self.revealed != target:
            self.revealed = min(target, self.revealed + step) if target > self.revealed else max(target, self.revealed - step)
            self.arrange()
        self.advance(step, reduced)
        self.advance_time(elapsed, reduced)
        self.update()

    def advance_time(self, elapsed, reduced):
        """Animations measured in seconds rather than reveal steps (a turning record, a moving meter)."""

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
        if self.menu is not None:
            self.menu.close()
        super().hideEvent(event)

    def _seek_to(self, x):
        bar = self.seek_rect()
        duration = float(self.c.track.duration or 0)
        if bar.isEmpty() or duration <= 0 or not self.c.track.connected:
            return
        fraction = max(0., min(1., (x - bar.left()) / max(1., bar.width())))
        self.c.seek(fraction * duration)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.seek_rect().contains(event.position()) and self.c.track.connected and self.c.track.duration:
                self._seeking = True
                self._seek_to(event.position().x())
                event.accept()
                return
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._pressed_at = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._seeking and event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_to(event.position().x())
            event.accept()
        elif self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._seeking:
            self._seeking = False
            event.accept()
            return
        if self._drag is not None:
            moved = self._pressed_at is not None and (event.globalPosition().toPoint() - self._pressed_at).manhattanLength() > 3
            self._drag = None
            self._pressed_at = None
            if moved:
                self.remember()
            elif self.art_rect().contains(event.position()):
                # A click on the cover brings Halo back, like the back-to-Halo key.
                self.restoreRequested.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.seek_rect().contains(event.position()):
            self.restoreRequested.emit()


def paint_dark_placeholder(p, rect, light):
    """No cover yet: the halo ring in the song's light on a dark square, for the dark styles."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    wash = QLinearGradient(rect.topLeft(), rect.bottomRight())
    wash.setColorAt(0, mix(QColor("#202422"), light, .22))
    wash.setColorAt(1, QColor("#121514"))
    p.setBrush(wash)
    p.drawRect(rect)
    centre, radius = rect.center(), rect.width() * .24
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(tint(WHITE, 26), max(2.5, radius * .12)))
    p.drawEllipse(centre, radius, radius)
    p.setPen(QPen(light, max(2., radius * .08), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2), 40 * 16, 245 * 16)
    inner = radius * .58
    p.setPen(QPen(tint(WHITE, 150), max(1.5, radius * .06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(centre.x() - inner, centre.y() - inner, inner * 2, inner * 2), 170 * 16, 220 * 16)
    p.restore()


class MiniPlayer(MiniBase):
    """The Case: a small always-on-top case with the print, the song, the line being sung, and playback."""
    STYLE = "case"
    SIZE = (384, 136)
    REHANG = .6

    def prepare(self):
        self.print_cache = QPixmap()
        self.print_key = None
        self.previous_print = QPixmap()
        self.hung_at = 0.
        self.scroll = 0.
        self.lyric_room = 0.

    def make_key(self, kind, callback, hint):
        if kind in ("restore", "close"):
            return CaseChip(kind, callback, self.c, hint)
        return MiniKey(kind, callback, self.c, hint)

    # --- geometry ---------------------------------------------------------------------

    def card(self):
        """The case. Room above it for the keys on its top edge, and below it for its shadow."""
        return QRectF(12, 16, self.width() - 24, self.height() - 34)

    def frame_rect(self):
        card = self.card()
        side = card.height() - 24
        return QRectF(card.left() + 12, card.top() + 12, side, side)

    art_rect = frame_rect

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
        self.show_revealed()

    # --- state ------------------------------------------------------------------------

    def song_changed(self, first):
        c = self.c
        if (not first and self.track_key[0] != c.track.key and not self.print_cache.isNull() and self.isVisible()
                and not self.reduced()):
            self.previous_print = QPixmap(self.print_cache)
            self.hung_at = time.monotonic()
        else:
            self.previous_print = QPixmap()
        self.print_key = None

    def refresh(self):
        super().refresh()
        if not self.isVisible():
            # Opening on a song with words starts with its line in place, not sliding in.
            self.lyric_room = 1. if self.has_lyrics() else 0.

    def rehanging(self):
        return not self.previous_print.isNull() and time.monotonic() - self.hung_at < self.REHANG

    def advance(self, step, reduced):
        room = 1. if self.has_lyrics() else 0.
        if self.lyric_room != room:
            self.lyric_room = room if reduced else (min(room, self.lyric_room + step * .5) if room > self.lyric_room
                                                    else max(room, self.lyric_room - step * .5))

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
        moving = c.track.playing and not self.reduced()
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
        connected = self.connected()
        text, words, current, index = self.line()
        now = time.monotonic()
        if self.note_line(index, text):
            self.scroll = 0.
        if self.reduced():
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
        lettering = [word for word, _ in words]
        lit = current if c.track.playing else -1
        lefts, total = word_lefts(lettering, metrics)
        self.scroll = glide(self.scroll, lefts, lettering, metrics, current, total, width, self.reduced())
        progress = self.settle()
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
        fraction = self.fraction()
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


def word_lefts(lettering, metrics):
    """Where each word starts on one row, and the row's whole width."""
    space = metrics.horizontalAdvance(" ")
    lefts, x = [], 0.
    for word in lettering:
        lefts.append(x)
        x += metrics.horizontalAdvance(word) + space
    return lefts, max(0., x - space)


def glide(scroll, lefts, lettering, metrics, current, total, width, reduced):
    """How far a too-long row has slid along so the word being sung stays in view."""
    target = 0.
    if total > width - 20 and 0 <= current < len(lettering):
        end = lefts[current] + metrics.horizontalAdvance(lettering[current])
        target = max(0., min(total - width + 24, end - width * .62))
    if reduced or scroll == 0. and target == 0.:
        return target
    return scroll + (target - scroll) * .14
