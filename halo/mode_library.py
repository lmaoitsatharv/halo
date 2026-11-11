"""A live mode catalogue following the current song, with sample fallback."""
from dataclasses import replace
import math
import time
from types import SimpleNamespace

from PySide6.QtCore import (Qt, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Property,
                            QPropertyAnimation, QEasingCurve, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                          QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget)

from .glow import paint_halo_preview
from .lyric_rendering import canonical_lyric_style
from .mode_catalog import all_modes, find_mode, MODE_TITLES
from .models import Lyrics, LyricLine, Track
from .scene_extras import extra_scene_layout, paint_extra_scene, _artwork_image
from .widgets import LyricCanvas


from .gallery import paint_shadow, paint_focus, tint, INK, INK_SOFT, SHADOW
from .theme import hexc, pick, style
from .glass import icon as line_icon

LIBRARY_STYLE = """
QDialog#modeLibrary { background: #e7ece6; color: #1c2a26; }
QDialog#embeddedModes { background: transparent; color: #1c2a26; }
QWidget { font-family: 'Segoe UI'; color: #1c2a26; }
QLabel { background: transparent; }
QLabel#libraryEyebrow { color: #55625e; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#libraryTitle { color: #1c2a26; font-size: 30px; font-weight: 600; letter-spacing: -1px; }
QLabel#librarySubtitle { color: #55625e; font-size: 13px; }
QLabel#libraryCount { color: #55625e; font-size: 12px; }
QLabel#libraryDetailTitle { color: #1c2a26; font-size: 25px; font-weight: 600; letter-spacing: -0.5px; }
QLabel#libraryDescription { color: #3e4c47; font-size: 13px; }
QLabel#libraryState { color: #24685b; font-size: 12px; font-weight: 600; }
QLabel#libraryFooter { color: #55625e; font-size: 11px; }
QFrame#libraryDetail { background: #ffffff; border: 1px solid rgba(28, 42, 38, 30); border-radius: 20px; }
QFrame#libraryToolbar { background: rgba(28, 42, 38, 12); border: 1px solid rgba(28, 42, 38, 18);
    border-radius: 14px; }
QPushButton#libraryTab { border: 1px solid transparent; border-radius: 10px;
    background: transparent; color: #3e4c47; padding: 9px 13px; font-size: 12px; }
QPushButton#libraryTab:hover { background: rgba(255, 255, 255, 150); color: #1c2a26; }
QPushButton#libraryTab:checked { border-color: rgba(28, 42, 38, 36); background: #ffffff; color: #1c2a26; font-weight: 600; }
QPushButton#libraryTab:focus { border: 2px solid #2f7d6d; }
QPushButton#libraryClose { background: #ffffff; color: #1c2a26;
    border: 1px solid rgba(28, 42, 38, 46); border-radius: 11px; padding: 7px 12px; font-size: 12px; }
QPushButton#libraryClose:hover { border-color: rgba(28, 42, 38, 110); }
QPushButton#libraryPause { background: #ffffff; color: #1c2a26;
    border: 1px solid rgba(28, 42, 38, 46); border-radius: 12px; padding: 9px 12px; font-size: 12px; }
QPushButton#libraryPause:hover { border-color: rgba(28, 42, 38, 110); }
QPushButton#libraryPause:checked { background: #1c2a26; color: #f2f4ef; border-color: #1c2a26; }
QPushButton#libraryAdd { background: #1c2a26; color: #f2f4ef; border: 1px solid #0f1715;
    border-radius: 12px; padding: 10px 12px; font-size: 12px; font-weight: 600; }
QPushButton#libraryAdd:hover { background: #2b3b36; }
QPushButton#libraryAdd:disabled { background: #dcebe3; color: #24685b; border-color: rgba(36, 104, 91, 60); }
QPushButton#libraryUse { background: #ffffff; color: #1c2a26; border: 1px solid rgba(28, 42, 38, 60);
    border-radius: 12px; padding: 10px 12px; font-size: 12px; }
QPushButton#libraryUse:hover { border-color: rgba(28, 42, 38, 130); background: #f9fbf8; }
QPushButton#libraryUse:disabled { color: #6f7b77; border-color: rgba(28, 42, 38, 22); background: rgba(28, 42, 38, 8); }
QPushButton#libraryRemove { background: transparent; color: #8a3b2f; border: 0;
    font-size: 12px; padding: 6px 2px; text-align: left; }
QPushButton#libraryRemove:hover { color: #6d2a20; text-decoration: underline; }
QLineEdit#librarySearch { background: #ffffff; border: 1px solid rgba(28, 42, 38, 50);
    border-radius: 10px; padding: 8px 12px; color: #1c2a26; font-size: 12px; selection-background-color: #bfe0d2; }
QLineEdit#librarySearch:focus { border: 2px solid #2f7d6d; }
QScrollArea#libraryScroll, QScrollArea#libraryDetailScroll, QWidget#libraryDetailBody,
QWidget#libraryGrid, QWidget#libraryViewport, QWidget#libraryDetailViewport { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QScrollBar::handle:vertical { background: rgba(28, 42, 38, 70); border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: rgba(28, 42, 38, 120); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 18px; }
QPushButton:focus { border: 2px solid #2f7d6d; }
"""

_SAMPLE = Lyrics([
    LyricLine(0, "Let the evening in"), LyricLine(5, "The room turns to gold"),
    LyricLine(10, "Stay a little longer"), LyricLine(15, "Light finds every corner"),
    LyricLine(20, ""), LyricLine(24, "Hold the quiet close"),
    LyricLine(29, "Leave the day behind"), LyricLine(34, "We find our way back home"),
    LyricLine(40, ""),
], "Original Halo visual preview")
CARD_LOOP = 20.  # The sample's first verse, which ends where its first pause begins.
CARD_SCALE = 2


def _alpha(value, amount):
    colour = QColor(value)
    colour.setAlphaF(max(0., min(1., amount)))
    return colour


def _font(pixels, weight=QFont.Weight.Normal):
    result = QFont("Segoe UI")
    result.setPixelSize(max(1, int(pixels)))
    result.setWeight(weight)
    return result


def _label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _text(p, rect, text, pixels, colour, weight=QFont.Weight.Normal, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
    face = _font(pixels, weight)
    p.setFont(face)
    p.setPen(colour)
    shown = QFontMetrics(face).elidedText(text, Qt.TextElideMode.ElideRight, max(1, round(rect.width())))
    p.drawText(rect, align, shown)


class _PreviewClock:
    def __init__(self):
        self.elapsed = 5.8
        self.running = True
        self.last = None

    def tick(self, advance=True):
        now = time.monotonic()
        if self.last is not None and self.running and advance:
            self.elapsed += max(0., min(.12, now - self.last))
        self.last = now


class _PreviewProxy:
    """Read the current playback without exposing mutable live objects."""
    def __init__(self, source, clock, spec):
        self.source, self.clock, self.spec = source, clock, spec
        self._generation = 1
        self._track = Track("Afterglow", "Halo original visual demo", "A study in colour", 44, 0, True, True)
        self._lyrics_key = None
        self._lyrics = None
        self._held_position = None
        self._held_key = None
        self.intensity, self.glow_width, self.rim_width = 78, 50, 2
        self.glow_opacity = 78
        self.primary_brightness = self.secondary_brightness = 100
        self.color_mix, self.motion_speed = 60, 45
        self.halo_animation = "flow"
        self.demo = True
        self.audio = SimpleNamespace(error="")

    @property
    def uses_live(self):
        return bool(self.source.track.connected and self.source.lyrics.lines)

    @property
    def lyrics(self):
        if not self.uses_live:
            return _SAMPLE
        live = self.source.lyrics
        key = (id(live), id(live.lines), self.source.generation)
        if key != self._lyrics_key:
            self._lyrics = replace(live, lines=list(live.lines))
            self._lyrics_key = key
        return self._lyrics

    @property
    def offset(self):
        return self.source.offset if self.uses_live else 0

    @property
    def track(self):
        if self.source.track.connected:
            return replace(self.source.track, position=self.position,
                           playing=self.clock.running and (self.source.track.playing if self.uses_live else True))
        self._track.artwork = getattr(self.source.track, "artwork", b"")
        self._track.position = self.position
        self._track.playing = self.clock.running
        return self._track

    @property
    def position(self):
        if self.uses_live:
            key = (self.source.track.key, self.source.generation)
            if self.clock.running or self._held_position is None or key != self._held_key:
                self._held_position = self.source.position
                self._held_key = key
            return self._held_position
        return self.clock.elapsed % 44

    @property
    def motion_time(self):
        return self.clock.elapsed

    @property
    def motion_phase(self):
        return self.clock.elapsed / 26.28

    @property
    def generation(self):
        return (self._generation, self.uses_live, self.source.generation if self.uses_live else 0,
                id(self.source.lyrics.lines) if self.uses_live else 0)

    @property
    def reduced_motion(self):
        return bool(getattr(self.source, "reduced_motion", False))

    @property
    def primary(self):
        return QColor(getattr(self.source, "primary", QColor("#d7c5fb")))

    @property
    def secondary(self):
        return QColor(getattr(self.source, "secondary", QColor("#8ca9d9")))

    halo_primary = primary
    halo_secondary = secondary

    @property
    def pulse(self):
        return .30 + .22 * (.5 + .5 * math.sin(self.clock.elapsed * 1.35))

    @property
    def lyric_style(self):
        return self.spec.key if self.spec.kind == "lyrics" else canonical_lyric_style(getattr(self.source, "lyric_style", "ship_visual"))

    @property
    def immersive_mode(self):
        return self.spec.key if self.spec.kind == "scenes" else "lyrics"

    @property
    def halo_mode(self):
        return self.spec.key if self.spec.kind == "halo" else getattr(self.source, "halo_mode", "orbit")

    def seek(self, _seconds):
        pass


class _CardProxy(_PreviewProxy):
    """A style card always plays the sample verse, whatever the listener has on."""
    uses_live = False

    @property
    def position(self):
        return self.clock.elapsed % CARD_LOOP

    @property
    def track(self):
        self._track.position, self._track.playing = self.position, self.clock.running
        return self._track


CARD_CLOCK = _PreviewClock()


class StyleCard:
    """One lyric style's real renderer at card size, drawn large and scaled down so small type stays clean."""
    def __init__(self, controller, style, parent):
        self.proxy = _CardProxy(controller, CARD_CLOCK, SimpleNamespace(kind="lyrics", key=style))
        self.words = LyricCanvas(self.proxy, "immersive")
        self.words.setParent(parent)
        self.words.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.words.hide()
        self.words.setMinimumHeight(0)
        self.words.scene_mode = "lyrics"
        self.words.set_alignment("center")

    def paint(self, p, rect):
        CARD_CLOCK.tick(advance=not self.proxy.reduced_motion)
        self.words.resize(round(rect.width() * CARD_SCALE), round(rect.height() * CARD_SCALE))
        p.save()
        p.translate(rect.topLeft())
        p.scale(1 / CARD_SCALE, 1 / CARD_SCALE)
        self.words.render(p, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        p.restore()


class ModePreview(QWidget):
    """The real native mode renderer on a lightweight original demo stage."""
    def __init__(self, controller, clock, spec, parent=None, proxy=None):
        super().__init__(parent)
        self.c, self.clock, self.spec = controller, clock, spec
        self.proxy = proxy or _PreviewProxy(controller, clock, spec)
        self.words = LyricCanvas(self.proxy, "immersive")
        self.words.setParent(self)
        self.words.hide()
        self.words.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumHeight(100)
        self.badge = ""
        self.badge_tone = "normal"
        self._reveal = 1.
        self.reveal_animation = QPropertyAnimation(self, b"reveal", self)
        self.reveal_animation.setDuration(240)
        self.reveal_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_reveal(self):
        return self._reveal

    def set_reveal(self, value):
        self._reveal = value
        self.update()

    reveal = Property(float, get_reveal, set_reveal)

    def set_spec(self, spec, animate=False):
        changed = self.spec.identity != spec.identity
        self.spec = self.proxy.spec = spec
        if changed:
            self.proxy._generation += 1
            self.reveal_animation.stop()
            if animate and not self.proxy.reduced_motion:
                self.reveal_animation.setStartValue(.15)
                self.reveal_animation.setEndValue(1.)
                self.reveal_animation.start()
            else:
                self._reveal = 1.
        self.update()

    def _cover(self, p, rect, circle=False):
        image = _artwork_image(self.proxy.track.artwork)
        p.save()
        path = QPainterPath()
        path.addEllipse(rect) if circle else path.addRoundedRect(rect, 12, 12)
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if not image.isNull():
            ratio = max(rect.width() / image.width(), rect.height() / image.height())
            sw, sh = rect.width() / ratio, rect.height() / ratio
            p.drawImage(rect, image, QRectF((image.width() - sw) / 2, (image.height() - sh) / 2, sw, sh))
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, self.proxy.primary.darker(130))
            gradient.setColorAt(1, self.proxy.secondary.darker(230))
            p.fillRect(rect, gradient)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(245, 236, 255, 45), 1.5))
            for i in range(7):
                radius = rect.width() * (.11 + i * .055)
                p.drawEllipse(rect.center(), radius, radius)
            _text(p, rect.adjusted(15, 12, -10, -12), "HALO / ORIGINAL", max(8, rect.width() * .034),
                  _alpha(self.proxy.primary, .9), QFont.Weight.DemiBold, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        p.restore()

    def _lyrics(self, p, rect, scene="lyrics", alignment="center"):
        self.words.scene_mode = scene
        self.words.set_alignment(alignment)
        self.words.resize(max(1, round(rect.width())), max(1, round(rect.height())))
        p.save()
        p.translate(rect.topLeft())
        self.words.render(p, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        p.restore()

    def _scene(self, p):
        scene = self.spec.key
        c = self.proxy
        phase = 0 if c.reduced_motion else c.motion_time
        layout = extra_scene_layout(scene, 1000, 625)
        if layout:
            paint_extra_scene(p, 1000, 625, c, scene, phase)
            self._cover(p, QRectF(layout["cover"]))
            self._lyrics(p, QRectF(layout["canvas"]), scene, layout.get("alignment", "left"))
            for key, text, size in (("song", c.track.title, 14 if scene == "scene_runway" else 22),
                                     ("artist", c.track.artist, 11 if scene == "scene_runway" else 13),
                                     ("album", c.track.album, 10)):
                _text(p, QRectF(layout[key]), text, size, QColor("#c2becf"))
        elif scene == "studio":
            self._cover(p, QRectF(72, 150, 255, 255))
            _text(p, QRectF(72, 425, 290, 38), c.track.title, 27, QColor("#eee8fa"), QFont.Weight.DemiBold)
            _text(p, QRectF(72, 468, 290, 26), c.track.artist, 16, QColor("#9e9ab0"))
            self._lyrics(p, QRectF(382, 96, 566, 428), "studio", "left")
        elif scene == "orbit":
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(7):
                radius = 150 + i * 15
                p.setPen(QPen(_alpha(c.primary, .17 - i * .018), 1.2))
                p.drawEllipse(QPointF(260, 280), radius, radius)
            for i in range(3):
                radius = 165 + i * 15
                angle = phase * (.08 + i * .025) + i * 2.1
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(_alpha(c.primary, .65 - i * .12))
                p.drawEllipse(QPointF(260 + math.cos(angle) * radius, 280 + math.sin(angle) * radius), 2.8, 2.8)
            self._cover(p, QRectF(145, 165, 230, 230))
            _text(p, QRectF(125, 440, 280, 36), c.track.title, 23, QColor("#eae4f5"), align=Qt.AlignmentFlag.AlignCenter)
            self._lyrics(p, QRectF(472, 86, 478, 440), "orbit", "left")
        elif scene == "cinema":
            beam = QLinearGradient(0, 0, 0, 550)
            beam.setColorAt(0, _alpha(c.primary, .12))
            beam.setColorAt(1, _alpha(c.primary, 0))
            shape = QPainterPath()
            shape.moveTo(390, 0)
            shape.lineTo(610, 0)
            shape.lineTo(910, 510)
            shape.lineTo(90, 510)
            shape.closeSubpath()
            p.fillPath(shape, beam)
            self._lyrics(p, QRectF(40, 68, 920, 410), "cinema")
            self._cover(p, QRectF(45, 520, 45, 45))
            _text(p, QRectF(104, 522, 350, 26), c.track.title, 16, QColor("#d8d1e7"))
        else:
            self._lyrics(p, QRectF(35, 62, 930, 475), "lyrics")
        # A quiet native transport silhouette gives each room its real scale.
        p.setPen(QPen(QColor(228, 219, 247, 35), 1))
        p.setBrush(QColor(8, 12, 19, 190))
        p.drawRoundedRect(QRectF(190, 550, 620, 48), 20, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(c.primary, .85))
        p.drawEllipse(QRectF(225, 563, 22, 22))
        p.setPen(QPen(_alpha(c.primary, .36), 2))
        p.drawLine(QPointF(278, 574), QPointF(775, 574))

    def _halo(self, p):
        c = self.proxy
        p.setPen(QPen(QColor(233, 226, 255, 15), 1))
        p.setBrush(QColor(16, 21, 32, 225))
        p.drawRoundedRect(QRectF(194, 205, 612, 198), 24, 24)
        self._cover(p, QRectF(220, 231, 144, 144))
        _text(p, QRectF(394, 234, 380, 24), "NOW PLAYING", 12, QColor("#9b94b3"), QFont.Weight.DemiBold)
        _text(p, QRectF(394, 275, 380, 44), c.track.title, 31, QColor("#f2eefa"), QFont.Weight.DemiBold)
        _text(p, QRectF(394, 328, 380, 30), c.track.artist, 15, QColor("#a5a0b8"))
        paint_halo_preview(p, QRectF(0, 0, 1000, 625), c, self.spec.key,
                           motion_time=c.motion_time, motion_phase=0 if c.reduced_motion else c.motion_phase)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 15, 15)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor("#0c0e17"))
        p.save()
        scale = min(self.width() / 1000., self.height() / 625.)
        p.translate((self.width() - 1000 * scale) / 2, (self.height() - 625 * scale) / 2)
        p.scale(scale, scale)
        for x, y, colour in ((130, 540, self.proxy.secondary), (820, 75, self.proxy.primary)):
            wash = QLinearGradient(x, y, 1000 - x, 625 - y)
            wash.setColorAt(0, _alpha(colour, .06))
            wash.setColorAt(1, _alpha(colour, 0))
            p.fillRect(QRectF(0, 0, 1000, 625), wash)
        p.setOpacity(.30 + self._reveal * .70)
        p.translate(0, (1 - self._reveal) * 12)
        if self.spec.kind == "lyrics":
            self._lyrics(p, QRectF(30, 35, 940, 555))
        elif self.spec.kind == "scenes":
            self._scene(p)
        else:
            self._halo(p)
        p.restore()
        if self.badge:
            face = _font(8, QFont.Weight.DemiBold)
            p.setFont(face)
            width = QFontMetrics(face).horizontalAdvance(self.badge) + 14
            badge = QRectF(self.width() - width - 9, 9, width, 20)
            tone = QColor("#c0e5d5") if self.badge_tone == "added" else QColor("#d8c5f5")
            p.setPen(QPen(_alpha(tone, .23), 1))
            p.setBrush(QColor(20, 22, 31, 215))
            p.drawRoundedRect(badge, 7, 7)
            p.setPen(tone)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.badge)
        p.end()


class SceneCard:
    """One room's real renderer at card size, with the listener's lyric style inside it."""
    def __init__(self, controller, scene, parent):
        spec = find_mode("scenes", scene)
        self.preview = ModePreview(controller, CARD_CLOCK, spec, parent, _CardProxy(controller, CARD_CLOCK, spec))
        self.preview.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.preview.hide()
        self.preview.setMinimumHeight(0)

    def paint(self, p, rect):
        CARD_CLOCK.tick(advance=not self.preview.proxy.reduced_motion)
        self.preview.resize(round(rect.width()), round(rect.height()))
        p.save()
        p.translate(rect.topLeft())
        self.preview.render(p, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        p.restore()


class ModeCard(QAbstractButton):
    def __init__(self, controller, clock, spec, parent=None):
        super().__init__(parent)
        self.c, self.spec = controller, spec
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Preview " + spec.title + " · " + MODE_TITLES[spec.kind])
        self.setToolTip(spec.description)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview = ModePreview(controller, clock, spec, self)
        self._hover = 0.
        self.hover_animation = QPropertyAnimation(self, b"hover", self)
        self.hover_animation.setDuration(160)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = value
        if hasattr(self, "preview"):
            self.preview.move(10, round(10 - 2 * self._hover))
        self.update()

    hover = Property(float, get_hover, set_hover)

    def _animate_hover(self, value):
        self.hover_animation.stop()
        if getattr(self.c, "reduced_motion", False):
            self.set_hover(value)
        else:
            self.hover_animation.setStartValue(self._hover)
            self.hover_animation.setEndValue(value)
            self.hover_animation.start()

    def enterEvent(self, event):
        self._animate_hover(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        width = max(1, self.width() - 20)
        preview_height = round(width * .625)
        self.preview.setGeometry(10, round(10 - 2 * self._hover), width, preview_height)
        desired = preview_height + 101
        if self.height() != desired:
            self.setFixedHeight(desired)
        super().resizeEvent(event)

    def sync(self):
        owned = self.c.has_mode(self.spec.kind, self.spec.key)
        current = getattr(self.c, self.spec.field, None) == self.spec.key
        self.preview.badge = "IN USE" if current else "INCLUDED" if self.spec.included else "ADDED" if owned else "DISCOVER"
        self.preview.badge_tone = "added" if current or owned and not self.spec.included else "normal"
        self.preview.update()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A white label card on the wall; the live preview inside it stays dark, like a screen.
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -5)
        if self.isChecked():
            paint_shadow(p, rect, 16, 10, .24, 4)
            p.setPen(QPen(hexc("#1c2a26"), 2))
        else:
            paint_shadow(p, rect, 16, 6 + 4 * self._hover, .14 + .08 * self._hover, 2 + self._hover)
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hexc("#ffffff"))
        p.drawRoundedRect(rect, 16, 16)
        if self.hasFocus():
            paint_focus(p, rect, 16)
        y = 10 + self.preview.height() + 8
        _text(p, QRectF(14, y, self.width() - 28, 24), self.spec.title, 15,
              hexc("#1c2a26"), QFont.Weight.DemiBold)
        _text(p, QRectF(14, y + 24, self.width() - 28, 17), MODE_TITLES[self.spec.kind].upper(),
              8, hexc("#24685b"), QFont.Weight.DemiBold)
        p.save()
        desc = QRectF(14, y + 45, self.width() - 28, 29)
        p.setClipRect(desc)
        p.setFont(_font(10))
        p.setPen(hexc("#55625e"))
        p.drawText(desc, Qt.TextFlag.TextWordWrap, self.spec.description)
        p.restore()
        p.end()


class FilterSwitch(QAbstractButton):
    """A labelled on/off switch for the toolbar; the words and the switch are one target."""
    def __init__(self, text, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self._knob = 0.
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.animation = QPropertyAnimation(self, b"knob", self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def get_knob(self):
        return self._knob

    def set_knob(self, value):
        self._knob = float(value)
        self.update()

    knob = Property(float, get_knob, set_knob)

    def _animate(self, checked):
        self.animation.stop()
        if getattr(self.c, "reduced_motion", False) or not self.isVisible():
            self.set_knob(float(checked))
            return
        self.animation.setStartValue(self._knob)
        self.animation.setEndValue(float(checked))
        self.animation.start()

    def sizeHint(self):
        # Measured in the bold the label takes when the switch is on, so it never shortens.
        words = QFontMetrics(_font(12, QFont.Weight.DemiBold)).horizontalAdvance(self.text())
        return QSize(14 + words + 4 + 12 + 30 + 12, 36)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(.45)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.underMouse() and self.isEnabled():
            # The same hover as the category tabs beside it.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, pick(150, 18)))
            p.drawRoundedRect(rect, 10, 10)
        if self.hasFocus():
            paint_focus(p, rect, 10)
        on = self.isChecked()
        _text(p, QRectF(14, 0, self.width() - 14 - 50, self.height()), self.text(), 12,
              INK if on else INK_SOFT, QFont.Weight.DemiBold if on else QFont.Weight.Normal)
        # A recessed track with a small raised key, like the switches in Settings.
        a, b = hexc("#c3ccc6"), hexc("#2f7d6d")
        t = self._knob
        fill = QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(a.getRgbF(), b.getRgbF())))
        track = QRectF(self.width() - 12 - 30, (self.height() - 18) / 2, 30, 18)
        p.setPen(QPen(fill.darker(118), 1))
        p.setBrush(fill)
        p.drawRoundedRect(track, 9, 9)
        centre = QPointF(track.left() + 9 + 12 * t, track.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint(SHADOW, pick(60, 140)))
        p.drawEllipse(centre + QPointF(0, 1), 6.4, 6.4)
        p.setBrush(QColor(pick("#ffffff", "#e6ece6")))
        p.drawEllipse(centre, 6.4, 6.4)
        p.end()


class ModeLibrary(QDialog):
    CATEGORIES = (("all", "All modes"), ("lyrics", "Lyrics"), ("scenes", "Immersive"),
                  ("halo", "Halo light"), ("mine", "My modes"))

    def __init__(self, owner, controller, embedded=False):
        super().__init__(owner)
        self.owner, self.c = owner, controller
        self.embedded = bool(embedded)
        if self.embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("embeddedModes" if self.embedded else "modeLibrary")
        self.setWindowTitle("Halo · Modes")
        self.setWindowIcon(owner.windowIcon())
        style(self, LIBRARY_STYLE)
        if not self.embedded:
            self.setMinimumSize(900, 600)
            self.resize(1320, 840)
        self.clock = _PreviewClock()
        self.category = "all"
        priority = {"lyrics": 0, "scenes": 1, "halo": 2}
        self.specs = tuple(sorted(all_modes(), key=lambda spec: (spec.included, priority[spec.kind])))
        self.selected = self.specs[0]
        self.filtered_specs = []
        self.cards = {}
        self._columns = 0
        self._tick_number = 0
        self._visible_card_updates = 0
        self._positioned = False

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 16)
        root.setSpacing(16 if not self.embedded else 12)
        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(3)
        title_group.addWidget(_label("Find your atmosphere.", "libraryTitle"))
        subtitle = _label("A different way to feel your music. Make it yours.", "librarySubtitle")
        subtitle.setWordWrap(True)
        title_group.addWidget(subtitle)
        heading.addLayout(title_group, 1)
        self.pause_button = QPushButton("Pause previews")
        self.pause_button.setIcon(line_icon("pause", "#1c2a26", 14))
        self.pause_button.setObjectName("libraryPause")
        self.pause_button.setCheckable(True)
        self.pause_button.setAccessibleName("Pause live mode previews")
        self.pause_button.toggled.connect(self._pause_changed)
        heading.addWidget(self.pause_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = QPushButton("Back to listening" if self.embedded else "×")
        self.close_button.setObjectName("libraryClose")
        if self.embedded:
            self.close_button.setIcon(line_icon("back", "#1c2a26", 16))
            self.close_button.setMinimumHeight(38)
        else:
            self.close_button.setFixedSize(34, 34)
        self.close_button.setAccessibleName("Back to listening" if self.embedded else "Close Modes")
        self.close_button.setToolTip("Back to listening · Esc" if self.embedded else "Close Modes · Esc")
        self.close_button.clicked.connect(self.reject)
        heading.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(heading)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("libraryToolbar")
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(5, 5, 5, 5)
        toolbar.setSpacing(3)
        self.category_buttons = {}
        for key, title in self.CATEGORIES:
            button = QPushButton(title)
            button.setObjectName("libraryTab")
            button.setCheckable(True)
            button.setAccessibleName("Browse " + title)
            button.clicked.connect(lambda checked=False, kind=key: self.set_category(kind))
            self.category_buttons[key] = button
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        # Leave out what is already yours, so the list shows only what's new.
        self.hide_owned = FilterSwitch("Hide included", controller)
        self.hide_owned.setObjectName("libraryHideOwned")
        self.hide_owned.setAccessibleName("Hide modes already in your collection")
        self.hide_owned.setToolTip("Hide modes that are already yours: included with Halo or added by you")
        settings = getattr(controller, "settings", None)
        if settings is not None and settings.value("modes_hide_owned", False, type=bool):
            self.hide_owned.setChecked(True)
            self.hide_owned.set_knob(1.)
        self.hide_owned.toggled.connect(self._hide_owned_changed)
        toolbar.addWidget(self.hide_owned)
        toolbar.addSpacing(4)
        self.search = QLineEdit()
        self.search.setObjectName("librarySearch")
        self.search.setPlaceholderText("Search modes…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search modes")
        self.search.setMinimumWidth(130)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh_filter)
        toolbar.addWidget(self.search, 1)
        root.addWidget(toolbar_frame)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        self.count_label = _label("", "libraryCount")
        left_layout.addWidget(self.count_label)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("libraryScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("libraryViewport")
        self.scroll.viewport().installEventFilter(self)
        self.grid_widget = QWidget()
        self.grid_widget.setObjectName("libraryGrid")
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 10, 12)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.grid_widget)
        self.empty_label = _label("No modes found. Try another word or category.", "librarySubtitle")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        left_layout.addWidget(self.scroll, 1)
        left_layout.addWidget(self.empty_label)
        left.setMinimumWidth(280 if self.embedded else 310)
        self.splitter.addWidget(left)

        self.detail = QFrame()
        self.detail.setObjectName("libraryDetail")
        self.detail.setMinimumWidth(290 if self.embedded else 330)
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(18, 18, 18, 16)
        detail.setSpacing(10)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("libraryDetailScroll")
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.detail_scroll.viewport().setObjectName("libraryDetailViewport")
        self.detail_body = QWidget()
        self.detail_body.setObjectName("libraryDetailBody")
        self.body_layout = QVBoxLayout(self.detail_body)
        self.body_layout.setContentsMargins(0, 0, 2, 0)
        self.body_layout.setSpacing(10)
        # The category reads beside the title below the preview, never as an eyebrow above it.
        self.detail_category = _label("", "libraryState")
        self.detail_category.hide()
        self.selected_preview = ModePreview(controller, self.clock, self.selected, self.detail)
        self.selected_preview.setMinimumHeight(120)
        self.selected_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.body_layout.addWidget(self.selected_preview)
        self.detail_title = _label("", "libraryDetailTitle")
        self.body_layout.addWidget(self.detail_title)
        self.description = _label("", "libraryDescription")
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(28)
        self.body_layout.addWidget(self.description)
        self.state_label = _label("", "libraryState")
        self.state_label.setWordWrap(True)
        self.body_layout.addWidget(self.state_label)
        self.body_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_body)
        detail.addWidget(self.detail_scroll, 1)
        self.add_button = QPushButton("Add to my modes")
        self.add_button.setObjectName("libraryAdd")
        self.add_button.clicked.connect(self.add_selected)
        self.use_button = QPushButton("Use mode")
        self.use_button.setObjectName("libraryUse")
        self.use_button.clicked.connect(self.use_selected)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.add_button, 1)
        buttons.addWidget(self.use_button, 1)
        detail.addLayout(buttons)
        self.remove_button = QPushButton("Remove from my modes")
        self.remove_button.setObjectName("libraryRemove")
        self.remove_button.clicked.connect(self.remove_selected)
        detail.addWidget(self.remove_button)
        self.preview_note = _label("Original demo words · your colours and artwork\nVisual preview only; your music keeps playing.", "libraryFooter")
        self.preview_note.setWordWrap(True)
        detail.addWidget(self.preview_note)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([520, 340] if self.embedded else [720, 460])
        self.splitter.splitterMoved.connect(self._fit_detail)
        root.addWidget(self.splitter, 1)
        self.status_label = _label("Added modes appear automatically in their mode selectors.", "libraryFooter")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        for spec in self.specs:
            card = ModeCard(controller, self.clock, spec, self.grid_widget)
            card.clicked.connect(lambda checked=False, value=spec: self.select_mode(value))
            self.cards[spec.identity] = card
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        if self.embedded:
            owner.installEventFilter(self)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        controller.modeLibraryChanged.connect(self.refresh_collection)
        controller.settingChanged.connect(self.sync_state)
        if hasattr(controller, "paletteChanged"):
            controller.paletteChanged.connect(self.repaint_previews)
        if hasattr(controller, "trackChanged"):
            controller.trackChanged.connect(self.repaint_previews)
        if hasattr(controller, "lyricsChanged"):
            controller.lyricsChanged.connect(self.repaint_previews)
        self.set_category("all")

    def set_category(self, category):
        self.category = category if category in self.category_buttons else "all"
        for key, button in self.category_buttons.items():
            button.setChecked(key == self.category)
        self.refresh_filter()

    def hiding_owned(self):
        """True when modes already in the collection are left out of this list."""
        return self.hide_owned.isChecked() and self.category != "mine"

    def _hide_owned_changed(self, checked):
        settings = getattr(self.c, "settings", None)
        if settings is not None:
            settings.setValue("modes_hide_owned", bool(checked))
        self.refresh_filter()

    def refresh_filter(self, *_, keep_selected=False):
        query = self.search.text().strip().casefold()
        matches = [spec for spec in self.specs
                   if (self.category == "all" or self.category == spec.kind
                       or self.category == "mine" and self.c.has_mode(spec.kind, spec.key))
                   and (not query or query in (spec.title + " " + spec.description + " " + MODE_TITLES[spec.kind]).casefold())]
        hide = self.hiding_owned()
        self.filtered_specs = [spec for spec in matches if not (hide and self.c.has_mode(spec.kind, spec.key))]
        hidden = len(matches) - len(self.filtered_specs)
        # "My modes" is the collection itself, so there is nothing to hide there.
        self.hide_owned.setEnabled(self.category != "mine")
        self._columns = 0
        self.reflow()
        self.empty_label.setText("Every mode here is already yours. Turn off Hide included to see them."
                                 if hidden and not self.filtered_specs
                                 else "No modes found. Try another word or category.")
        self.empty_label.setVisible(not self.filtered_specs)
        self.scroll.setVisible(bool(self.filtered_specs))
        count = len(self.filtered_specs)
        detail = ("Your collection" if self.category == "mine"
                  else f"{hidden} already yours, hidden" if hidden
                  else "Curated for a different kind of listening")
        self.count_label.setText(f"{count} mode{'s' if count != 1 else ''}  ·  {detail}")
        if self.filtered_specs and self.selected not in self.filtered_specs and not keep_selected:
            self.select_mode(self.filtered_specs[0], animate=False)
        else:
            # A mode you just added stays in the detail panel, even when its card leaves the list.
            self.sync_state()
        if not keep_selected:
            self.scroll.verticalScrollBar().setValue(0)

    def reflow(self):
        width = max(1, self.scroll.viewport().width())
        columns = 2 if width >= 420 else 1
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
        for column in range(3):
            self.grid.setColumnStretch(column, 0)
        for i, spec in enumerate(self.filtered_specs):
            card = self.cards[spec.identity]
            self.grid.addWidget(card, i // columns, i % columns)
            card.show()
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self._columns = columns
        self.grid.invalidate()
        self.grid.activate()

    def select_mode(self, spec, animate=True):
        self.selected = spec
        for identity, card in self.cards.items():
            card.setChecked(identity == spec.identity)
        self.selected_preview.set_spec(spec, animate and self.isVisible())
        self.detail_category.setText(MODE_TITLES[spec.kind].upper())
        self.detail_title.setText(spec.title)
        self.description.setText(spec.description)
        self.description.setToolTip(spec.description)
        self.sync_state()

    def sync_state(self, *_):
        for card in self.cards.values():
            card.setChecked(card.spec.identity == self.selected.identity)
            card.sync()
        spec = self.selected
        owned = self.c.has_mode(spec.kind, spec.key)
        current = getattr(self.c, spec.field, None) == spec.key
        self.detail_category.setText(MODE_TITLES[spec.kind].upper())
        self.detail_title.setText(spec.title)
        self.description.setText(spec.description)
        self.add_button.setText("Included" if spec.included else "Added ✓" if owned else "Add to my modes")
        self.add_button.setEnabled(not owned)
        self.use_button.setText("Currently in use" if current else "Use mode")
        self.use_button.setEnabled(not current)
        self.remove_button.setVisible(owned and not spec.included)
        state = "Currently in use" if current else "Included with Halo" if spec.included else "In your modes" if owned else "Ready to add to your collection"
        self.state_label.setText(state)
        self.selected_preview.badge = "IN USE" if current else "INCLUDED" if spec.included else "ADDED" if owned else "DISCOVER"
        self.selected_preview.badge_tone = "added" if owned and not spec.included or current else "normal"
        self.selected_preview.update()
        if getattr(self.c, "reduced_motion", False):
            self.selected_preview.reveal_animation.stop()
            self.selected_preview._reveal = 1.
            for card in self.cards.values():
                card.hover_animation.stop()
                card.set_hover(0.)
        self._sync_timer()
        self.sync_preview_note()

    def refresh_collection(self):
        self.refresh_filter(keep_selected=True)

    def repaint_previews(self, *_):
        self.sync_preview_note()
        self._sync_timer()
        self.selected_preview.update()
        for card in self.visible_cards():
            card.preview.update()

    def sync_preview_note(self):
        proxy = self.selected_preview.proxy
        if proxy.uses_live:
            note = "Current song lyrics · follows playback\nPause previews freezes this page only."
        elif self.c.track.connected:
            note = "Sample lyrics · waiting for this song's lyrics\nYour song and artwork stay live."
        else:
            note = "Original demo words · your colours and artwork\nPlay a song to preview its lyrics here."
        self.preview_note.setText(note)

    def add_selected(self):
        spec = self.selected
        if self.c.add_mode(spec.kind, spec.key):
            self.status_label.setText(f"{spec.title} added. Find it in your {MODE_TITLES[spec.kind].lower()} modes.")
        self.sync_state()

    def use_selected(self):
        spec = self.selected
        if self.c.add_mode(spec.kind, spec.key):
            self.c.set(spec.field, spec.key)
            self.status_label.setText(f"{spec.title} is selected. Your music and lyric timing are unchanged.")
        self.sync_state()

    def remove_selected(self):
        spec = self.selected
        if self.c.remove_mode(spec.kind, spec.key):
            self.status_label.setText(f"{spec.title} removed from your collection. You can add it again anytime.")
        self.sync_state()

    def _pause_changed(self, paused):
        self.clock.running = not paused
        self.clock.last = None
        self.pause_button.setText("Resume previews" if paused else "Pause previews")
        self.pause_button.setIcon(line_icon("play" if paused else "pause", "#f2f4ef" if paused else "#1c2a26", 14))
        self._sync_timer()
        self.repaint_previews()

    def _sync_timer(self):
        run = (self.isVisible() and not self.window().isMinimized() and self.clock.running
               and (self.selected_preview.proxy.uses_live or not getattr(self.c, "reduced_motion", False)))
        if run and not self.timer.isActive():
            self.clock.last = None
            self.timer.start()
        elif not run:
            self.clock.last = None
            self.timer.stop()

    def visible_cards(self):
        viewport = self.scroll.viewport()
        bounds = viewport.rect()
        return [card for spec in self.filtered_specs
                for card in (self.cards[spec.identity],)
                if card.isVisible() and QRect(card.mapTo(viewport, QPoint()), card.size()).intersects(bounds)]

    def tick(self):
        live = self.selected_preview.proxy.uses_live
        if (not self.isVisible() or self.window().isMinimized() or not self.clock.running
                or (getattr(self.c, "reduced_motion", False) and not live)):
            self._sync_timer()
            return
        self.clock.tick(advance=not getattr(self.c, "reduced_motion", False)
                        and (not live or self.c.track.playing))
        self.selected_preview.update()
        self._tick_number += 1
        if self._tick_number % 2 == 0:
            visible = self.visible_cards()
            self._visible_card_updates += len(visible)
            for card in visible:
                card.preview.update()

    def eventFilter(self, obj, event):
        if self.embedded and obj is self.owner and event.type() in (
                QEvent.Type.WindowStateChange, QEvent.Type.Show, QEvent.Type.Hide):
            QTimer.singleShot(0, self, self._sync_timer)
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            columns = 2 if self.scroll.viewport().width() >= 420 else 1
            if columns != self._columns:
                QTimer.singleShot(0, self, self.reflow)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "selected_preview"):
            self._fit_detail()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "timer"):
            self._sync_timer()

    def _fit_detail(self, *_):
        compact = self.height() < 740
        layout = self.detail.layout()
        layout.setContentsMargins(14 if compact else 18, 12 if compact else 18,
                                  14 if compact else 18, 12 if compact else 16)
        layout.setSpacing(7 if compact else 10)
        self.body_layout.setSpacing(7 if compact else 10)
        self.preview_note.setVisible(not compact)
        self.description.setMaximumHeight(38 if compact else 80)
        width = max(1, self.detail.width() - (28 if compact else 36))
        height = (max(120, min(150, round((self.height() - 210) * .31))) if compact
                  else max(180, min(290, round(width * .625), round(self.height() * .33))))
        self.selected_preview.setFixedHeight(height)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned and not self.embedded:
            self._positioned = True
            available = (self.owner.screen() or self.screen()).availableGeometry()
            self.resize(min(self.width(), available.width() - 36), min(self.height(), available.height() - 52))
            rect = self.frameGeometry()
            rect.moveCenter(available.center())
            self.move(rect.topLeft())
        self._sync_timer()
        QTimer.singleShot(0, self, self.reflow)
        QTimer.singleShot(0, self, self._fit_detail)

    def hideEvent(self, event):
        self.timer.stop()
        self.clock.last = None
        self.selected_preview.reveal_animation.stop()
        self.selected_preview._reveal = 1.
        for card in self.cards.values():
            card.hover_animation.stop()
            card.set_hover(0.)
        super().hideEvent(event)

    def open_page(self, kind="all"):
        self.search.clear()
        self.set_category(kind)
        self.show()
        if not self.embedded:
            self.raise_()
            self.activateWindow()
