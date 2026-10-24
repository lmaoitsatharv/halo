"""A live mode catalogue following the current song, with sample fallback."""
from dataclasses import replace
import math
import time
from types import SimpleNamespace

from PySide6.QtCore import (Qt, QEvent, QPoint, QPointF, QRect, QRectF, Property,
                            QPropertyAnimation, QEasingCurve, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                          QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget)

from .glow import paint_halo_preview
from .lyric_rendering import canonical_lyric_style
from .mode_catalog import all_modes, MODE_TITLES
from .models import Lyrics, LyricLine, Track
from .scene_extras import extra_scene_layout, paint_extra_scene, _artwork_image
from .widgets import LyricCanvas


LIBRARY_STYLE = """
QDialog#modeLibrary { background: #111217; color: #ecebf3; }
QWidget { font-family: 'Segoe UI'; }
QLabel { background: transparent; }
QLabel#libraryEyebrow { color: #9693ac; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#libraryTitle { color: #f2effa; font-size: 29px; font-weight: 600; }
QLabel#librarySubtitle { color: #9997a9; font-size: 12px; }
QLabel#libraryCount { color: #b2afc1; font-size: 11px; }
QLabel#libraryDetailTitle { color: #f5f0fe; font-size: 25px; font-weight: 600; }
QLabel#libraryDescription { color: #b7b2c6; font-size: 12px; }
QLabel#libraryState { color: #b4d8ca; font-size: 11px; }
QLabel#libraryFooter { color: #838197; font-size: 10px; }
QFrame#libraryDetail { background: #191a22; border: 1px solid #353442; border-radius: 18px; }
QPushButton#libraryTab { border: 1px solid transparent; border-radius: 10px;
    background: transparent; color: #9a97ad; padding: 9px 12px; font-size: 11px; }
QPushButton#libraryTab:hover { background: #252532; color: #f3eafa; }
QPushButton#libraryTab:checked { border-color: #65577d; background: #373044; color: #f5efff; }
QPushButton#libraryTab:focus { border-color: #c0a8ec; }
QPushButton#libraryClose { background: #24252e; color: #c1bbd3; border: 1px solid #3d3b4b;
    border-radius: 11px; padding: 0; font-size: 22px; }
QPushButton#libraryClose:hover { background: #383241; }
QPushButton#libraryPause { background: #20222b; color: #beb9d0; border: 1px solid #3a3949;
    border-radius: 10px; padding: 8px 12px; font-size: 11px; }
QPushButton#libraryPause:checked { background: #393044; border-color: #88739f; }
QPushButton#libraryAdd { background: #d7c5fb; color: #21182e; border: 1px solid #d7c5fb;
    border-radius: 11px; padding: 11px 16px; font-weight: 600; }
QPushButton#libraryAdd:hover { background: #e9ddff; }
QPushButton#libraryAdd:disabled { background: #292d31; color: #a3b8ac; border-color: #424b47; }
QPushButton#libraryUse { background: #2c2a38; color: #e6ddf6; border: 1px solid #51465f;
    border-radius: 11px; padding: 10px 16px; }
QPushButton#libraryUse:hover { background: #44364f; }
QPushButton#libraryUse:disabled { color: #a4a0b0; border-color: #393641; background: #25242b; }
QPushButton#libraryRemove { background: transparent; color: #b2a4bb; border: 0;
    font-size: 10px; padding: 6px 2px; text-align: left; }
QPushButton#libraryRemove:hover { color: #ebadbd; }
QLineEdit#librarySearch { background: #1d1f29; border: 1px solid #38394a;
    border-radius: 11px; padding: 9px 13px; color: #e1dbea; font-size: 11px; }
QLineEdit#librarySearch:focus { border-color: #a690ca; }
QScrollArea#libraryScroll, QWidget#libraryGrid, QWidget#libraryViewport { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 4px 0; }
QScrollBar::handle:vertical { background: #4a455d; border-radius: 3px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 16px; }
QPushButton:focus { border-color: #cdb3f2; }
"""

_SAMPLE = Lyrics([
    LyricLine(0, "Let the evening in"), LyricLine(5, "The room turns to gold"),
    LyricLine(10, "Stay a little longer"), LyricLine(15, "Light finds every corner"),
    LyricLine(20, ""), LyricLine(24, "Hold the quiet close"),
    LyricLine(29, "Leave the day behind"), LyricLine(34, "We find our way back home"),
    LyricLine(40, ""),
], "Original Halo visual preview")


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


class ModePreview(QWidget):
    """The real native mode renderer on a lightweight original demo stage."""
    def __init__(self, controller, clock, spec, parent=None):
        super().__init__(parent)
        self.c, self.clock, self.spec = controller, clock, spec
        self.proxy = _PreviewProxy(controller, clock, spec)
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
        clip.addRoundedRect(QRectF(self.rect()), 11, 11)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor("#0a101a"))
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
            p.setBrush(QColor(19, 24, 33, 220))
            p.drawRoundedRect(badge, 7, 7)
            p.setPen(tone)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.badge)
        p.end()


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
        width = max(1, self.width() - 18)
        preview_height = round(width * .625)
        self.preview.setGeometry(9, 9, width, preview_height)
        desired = preview_height + 99
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
        rect = QRectF(self.rect()).adjusted(.7, .7, -.7, -.7)
        base = QColor("#282333") if self.isChecked() else QColor("#1b1d27")
        border = QColor("#ad8dd5") if self.isChecked() else _alpha(QColor("#aa98c5"), .22 + self._hover * .28)
        if self.hasFocus():
            border = QColor("#ddc5ff")
        p.setPen(QPen(border, 1.25 if self.isChecked() or self.hasFocus() else 1))
        p.setBrush(base)
        p.drawRoundedRect(rect, 15, 15)
        y = self.preview.geometry().bottom() + 9
        _text(p, QRectF(14, y, self.width() - 28, 24), self.spec.title, 15,
              QColor("#efebf8"), QFont.Weight.DemiBold)
        _text(p, QRectF(14, y + 24, self.width() - 28, 17), MODE_TITLES[self.spec.kind].upper(),
              8, QColor("#9f90b9"), QFont.Weight.DemiBold)
        p.save()
        desc = QRectF(14, y + 45, self.width() - 28, 29)
        p.setClipRect(desc)
        p.setFont(_font(10))
        p.setPen(QColor("#9d99ae"))
        p.drawText(desc, Qt.TextFlag.TextWordWrap, self.spec.description)
        p.restore()
        p.end()


class ModeLibrary(QDialog):
    CATEGORIES = (("all", "All modes"), ("lyrics", "Lyrics"), ("scenes", "Immersive"),
                  ("halo", "Halo light"), ("mine", "My modes"))

    def __init__(self, owner, controller):
        super().__init__(owner)
        self.owner, self.c = owner, controller
        self.setObjectName("modeLibrary")
        self.setWindowTitle("Halo · Modes")
        self.setWindowIcon(owner.windowIcon())
        self.setStyleSheet(LIBRARY_STYLE)
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
        root.setContentsMargins(26, 20, 26, 16)
        root.setSpacing(16)
        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(3)
        title_group.addWidget(_label("MAKE ROOM FOR SOMETHING DIFFERENT", "libraryEyebrow"))
        title_group.addWidget(_label("Find your next atmosphere.", "libraryTitle"))
        title_group.addWidget(_label("Places, words and light. Preview a mode, then make it yours.", "librarySubtitle"))
        heading.addLayout(title_group, 1)
        self.pause_button = QPushButton("Ⅱ  Pause previews")
        self.pause_button.setObjectName("libraryPause")
        self.pause_button.setCheckable(True)
        self.pause_button.setAccessibleName("Pause live mode previews")
        self.pause_button.toggled.connect(self._pause_changed)
        heading.addWidget(self.pause_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("libraryClose")
        self.close_button.setFixedSize(34, 34)
        self.close_button.setAccessibleName("Close Modes")
        self.close_button.clicked.connect(self.reject)
        heading.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(heading)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(5)
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
        self.search = QLineEdit()
        self.search.setObjectName("librarySearch")
        self.search.setPlaceholderText("Search modes…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search modes")
        self.search.setMinimumWidth(150)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh_filter)
        toolbar.addWidget(self.search, 1)
        root.addLayout(toolbar)

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
        left.setMinimumWidth(310)
        self.splitter.addWidget(left)

        self.detail = QFrame()
        self.detail.setObjectName("libraryDetail")
        self.detail.setMinimumWidth(330)
        detail = QVBoxLayout(self.detail)
        detail.setContentsMargins(18, 18, 18, 16)
        detail.setSpacing(10)
        stage_heading = QHBoxLayout()
        self.detail_category = _label("", "libraryEyebrow")
        stage_heading.addWidget(self.detail_category)
        stage_heading.addStretch()
        stage_heading.addWidget(_label("LIVE PREVIEW", "libraryEyebrow"))
        detail.addLayout(stage_heading)
        self.selected_preview = ModePreview(controller, self.clock, self.selected, self.detail)
        self.selected_preview.setMinimumHeight(120)
        self.selected_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        detail.addWidget(self.selected_preview)
        self.detail_title = _label("", "libraryDetailTitle")
        detail.addWidget(self.detail_title)
        self.description = _label("", "libraryDescription")
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(28)
        detail.addWidget(self.description)
        self.state_label = _label("", "libraryState")
        self.state_label.setWordWrap(True)
        detail.addWidget(self.state_label)
        detail.addStretch(1)
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
        self.splitter.setSizes([720, 460])
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

    def refresh_filter(self, *_):
        query = self.search.text().strip().casefold()
        self.filtered_specs = [spec for spec in self.specs
                               if (self.category == "all" or self.category == spec.kind
                                   or self.category == "mine" and self.c.has_mode(spec.kind, spec.key))
                               and (not query or query in (spec.title + " " + spec.description + " " + MODE_TITLES[spec.kind]).casefold())]
        self._columns = 0
        self.reflow()
        self.empty_label.setVisible(not self.filtered_specs)
        self.scroll.setVisible(bool(self.filtered_specs))
        count = len(self.filtered_specs)
        self.count_label.setText(f"{count} mode{'s' if count != 1 else ''}  ·  " + ("Your collection" if self.category == "mine" else "Curated for a different kind of listening"))
        if self.filtered_specs and self.selected not in self.filtered_specs:
            self.select_mode(self.filtered_specs[0], animate=False)
        else:
            self.sync_state()
        self.scroll.verticalScrollBar().setValue(0)

    def reflow(self):
        width = max(1, self.scroll.viewport().width())
        columns = 2 if width >= 540 else 1
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
                card._hover = 0.
        self._sync_timer()
        self.sync_preview_note()

    def refresh_collection(self):
        self.refresh_filter()

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
        self.pause_button.setText("▶  Resume previews" if paused else "Ⅱ  Pause previews")
        self._sync_timer()
        self.repaint_previews()

    def _sync_timer(self):
        run = (self.isVisible() and not self.isMinimized() and self.clock.running
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
        if (not self.isVisible() or self.isMinimized() or not self.clock.running
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
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            columns = 2 if self.scroll.viewport().width() >= 540 else 1
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
        self.preview_note.setVisible(not compact)
        self.description.setMaximumHeight(38 if compact else 80)
        width = max(1, self.detail.width() - (28 if compact else 36))
        height = (max(120, min(150, round((self.height() - 210) * .31))) if compact
                  else max(180, min(290, round(width * .625), round(self.height() * .33))))
        self.selected_preview.setFixedHeight(height)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned:
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
            card._hover = 0.
        super().hideEvent(event)

    def open_page(self, kind="all"):
        self.search.clear()
        self.set_category(kind)
        self.show()
        self.raise_()
        self.activateWindow()
