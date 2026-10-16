"""A native settings studio with real, isolated rendering previews."""
import math
import time
from dataclasses import replace
from PySide6.QtCore import (Qt, QRectF, QPointF, QPoint, QSize, Property, QTimer,
                            QPropertyAnimation, QEasingCurve, QSignalBlocker)
from PySide6.QtGui import (QColor, QPainter, QPen, QPainterPath, QPixmap, QIcon,
                          QLinearGradient, QRadialGradient, QFont, QFontMetrics)
from PySide6.QtWidgets import (QDialog, QWidget, QFrame, QLabel,
    QPushButton, QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QScrollArea)
from .models import Lyrics, parse_lrc, DEMO_LRC, floating_geometry
from .widgets import LyricCanvas, tint
from .glow import HALO_MODES, paint_edge_glow
from .lyric_rendering import LYRIC_STYLES
from .immersive import IMMERSIVE_SCENES
from .color_controls import LightControls
from .frontend import ModeTile, action, text_label, selector


STUDIO_STYLE = """
QDialog#settingsStudio { background: #141416; }
QWidget#studioSidebar { background: #19191c; border: 1px solid #303034; border-radius: 16px; }
QFrame#studioPreview { background: #101013; border: 1px solid #303035; border-radius: 18px; }
QFrame#studioGroup { background: #202023; border: 1px solid #333337; border-radius: 14px; }
QLabel#studioTitle { color: #f7f6f8; font-size: 25px; font-weight: 600; }
QLabel#studioSectionTitle { color: #ecebee; font-size: 15px; font-weight: 600; }
QLabel#studioRowTitle { color: #eeedf1; font-size: 12px; font-weight: 600; }
QLabel#studioHint { color: #94939e; font-size: 11px; }
QLabel#studioValue { color: #d0c9df; font-size: 11px; }
QLabel#studioEyebrow { color: #777581; font-size: 9px; letter-spacing: 1.5px; font-weight: 600; }
QPushButton#studioNav { background: transparent; border: 0; border-radius: 9px; text-align: left;
                       padding: 11px 12px; color: #a3a1ad; font-size: 12px; }
QPushButton#studioNav:checked { color: #faf7ff; font-weight: 600; }
QPushButton#studioNav:hover { color: #ffffff; background: rgba(255, 255, 255, 5); }
QPushButton#studioNav:focus { border: 1px solid #b7a7d3; padding: 10px 11px; }
QFrame#studioNavSelection { background: #323036; border: 1px solid #403a49; border-radius: 9px; }
QPushButton#studioClose { background: #242427; border: 1px solid #39393e; padding: 0;
                        border-radius: 10px; font-size: 19px; color: #b7b3bf; }
QPushButton#studioClose:hover { color: #ffffff; background: #39333f; }
QPushButton { background: #2b2930; border-color: #45404d; }
QPushButton:hover { background: #3b3544; border-color: #796a8d; }
QPushButton#primary { background: #ded2fa; color: #20192d; }
QComboBox { background: #29272e; border-color: #46404f; }
QComboBox QAbstractItemView { background: #242128; selection-background-color: #51425f; }
QSlider::groove:horizontal { background: #39343e; height: 4px; }
QSlider::sub-page:horizontal { background: #bba7dc; }
QSlider::handle:horizontal { background: #efe6ff; width: 11px; margin: -5px 0; border-radius: 5px; }
QScrollArea, QWidget#studioPage, QWidget#studioViewport { background: transparent; border: 0; }
QScrollBar::handle:vertical { background: #45404b; }
"""


def studio_icon(kind="general"):
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2.)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#d5cedf"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "general":
        path = QPainterPath()
        for i in range(64):
            angle = 2 * math.pi * i / 64
            radius = 9.2 if i % 8 in (2, 3, 4, 5) else 7.3
            point = QPointF(12 + math.cos(angle) * radius, 12 + math.sin(angle) * radius)
            path.moveTo(point) if i == 0 else path.lineTo(point)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QPointF(12, 12), 3., 3.)
    elif kind == "halo":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.setPen(QPen(QColor("#a696c3"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(7, 7, 10, 10), 20 * 16, 245 * 16)
    elif kind == "lyrics":
        for y, length in ((6, 13), (12, 17), (18, 10)):
            p.drawLine(QPointF(4, y), QPointF(4 + length, y))
    else:
        p.drawRoundedRect(QRectF(3, 4, 18, 14), 3, 3)
        p.drawLine(QPointF(8, 21), QPointF(16, 21))
        p.drawLine(QPointF(12, 18), QPointF(12, 21))
    p.end()
    return QIcon(pixmap)


class StudioSwitch(QCheckBox):
    """Keyboard-accessible native checkbox, with a gently travelling thumb."""
    def __init__(self, controller, title):
        super().__init__()
        self.c = controller
        self._knob = 0.
        self.setFixedSize(42, 25)
        self.setAccessibleName(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.animation = QPropertyAnimation(self, b"knob", self)
        self.animation.setDuration(190)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self.animate)

    def get_knob(self):
        return self._knob

    def set_knob(self, value):
        self._knob = float(value)
        self.update()

    knob = Property(float, get_knob, set_knob)

    def animate(self, checked):
        self.animation.stop()
        if self.c.reduced_motion or not self.isVisible():
            self.set_knob(float(checked))
        else:
            self.animation.setStartValue(self._knob)
            self.animation.setEndValue(float(checked))
            self.animation.start()

    def sync(self, checked):
        changed = self.isChecked() != bool(checked)
        with QSignalBlocker(self):
            self.setChecked(checked)
        if changed:
            self.animate(checked)
        elif self.c.reduced_motion or not self.isVisible():
            self.animation.stop()
            self.set_knob(float(checked))

    def hitButton(self, point):
        return self.rect().contains(point)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a, b = QColor("#434048"), QColor("#cdb8ee")
        t = self._knob
        colour = QColor.fromRgbF(*(x + (y - x) * t for x, y in zip(a.getRgbF(), b.getRgbF())))
        p.setPen(QPen(QColor("#eadfff") if self.hasFocus() else colour.lighter(115), 1))
        p.setBrush(colour)
        p.drawRoundedRect(QRectF(1, 2, 40, 21), 10.5, 10.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#fffaff"))
        p.drawEllipse(QPointF(12 + 18 * t, 12.5), 7.4, 7.4)


class PageCurtain(QWidget):
    """Animate a captured page, keeping the live controls responsive below it."""
    def __init__(self, stack, background="#141416", radius=0):
        super().__init__(stack)
        self.background, self.radius = QColor(background), radius
        self._progress = 1.
        self.before = self.after = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.animation = QPropertyAnimation(self, b"progress", self)
        self.animation.setDuration(240)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.finish)
        self.hide()

    def get_progress(self):
        return self._progress

    def set_progress(self, value):
        self._progress = float(value)
        self.update()

    progress = Property(float, get_progress, set_progress)

    def finish(self):
        self.hide()
        self.before = self.after = QPixmap()

    def start(self, before, after):
        self.animation.stop()
        self.before, self.after = before, after
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.animation.setStartValue(0.)
        self.animation.setEndValue(1.)
        self.animation.start()

    def paintEvent(self, event):
        p = QPainter(self)
        if self.radius:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
            p.setClipPath(path)
        p.fillRect(self.rect(), self.background)
        t = self._progress
        p.setOpacity(1 - t)
        p.drawPixmap(QPointF(-10 * t, 0), self.before)
        p.setOpacity(t)
        p.drawPixmap(QPointF(16 * (1 - t), 0), self.after)


class PreviewController:
    """Render sample words when needed without changing playback or preferences."""
    def __init__(self, controller):
        self.c = controller
        self.sample = Lyrics(parse_lrc(DEMO_LRC))
        self.motion_time = 0.
        self.motion_phase = 0.
        self.position = 8.
        self.last = time.monotonic()

    def __getattr__(self, name):
        return getattr(self.c, name)

    @property
    def uses_sample(self):
        return not self.c.lyrics.lines

    @property
    def lyrics(self):
        return self.sample if self.uses_sample else self.c.lyrics

    @property
    def track(self):
        return replace(self.c.track, duration=60., playing=not self.c.reduced_motion) if self.uses_sample else self.c.track

    @property
    def generation(self):
        return -1 if self.uses_sample else self.c.generation

    @property
    def pulse(self):
        if self.c.track.connected and self.c.track.playing:
            return self.c.pulse
        return .22 + .55 * max(0., math.sin(self.motion_time * 2.4)) ** 4

    def advance(self):
        now = time.monotonic()
        elapsed = min(.08, max(0., now - self.last))
        self.last = now
        moving = self.uses_sample or not self.c.track.connected or self.c.track.playing
        if not self.c.reduced_motion and moving:
            self.motion_time += elapsed
            if self.c.halo_animation != "still":
                rate = self.c.motion_speed / 45 / 26.28
                if self.c.halo_animation == "idle":
                    rate *= .18
                elif self.c.halo_animation == "music":
                    rate *= .4 + 1.4 * self.pulse
                self.motion_phase = (self.motion_phase + elapsed * rate) % 1.
            if self.uses_sample:
                self.position = (self.position + elapsed) % 60
        if not self.uses_sample:
            self.position = self.c.position


class PreviewScreen(QWidget):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.c = controller
        self.proxy = PreviewController(controller)
        self.section = "general"
        self.words = LyricCanvas(self.proxy, mode="immersive")
        self.words.setParent(self)
        self.words.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.words.hide()
        self.floating_words = LyricCanvas(self.proxy, mode="floating")
        self.floating_words.setParent(self)
        self.floating_words.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.floating_words.hide()
        self.art = QPixmap()
        self.setAccessibleName("Live preview of Halo on your desktop")
        controller.trackChanged.connect(self.refresh_art)
        self.refresh_art()

    def refresh_art(self):
        self.art = QPixmap()
        if self.c.track.artwork:
            self.art.loadFromData(self.c.track.artwork)
        self.update()

    @staticmethod
    def text(p, rect, text, size, colour, weight=QFont.Weight.Normal, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter):
        face = QFont("Segoe UI")
        face.setPixelSize(size)
        face.setWeight(weight)
        p.setFont(face)
        p.setPen(colour)
        text = QFontMetrics(face).elidedText(text, Qt.TextElideMode.ElideRight, max(1, int(rect.width())))
        p.drawText(rect, align, text)

    def cover(self, p, rect, circle=False):
        p.save()
        path = QPainterPath()
        path.addEllipse(rect) if circle else path.addRoundedRect(rect, 18, 18)
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if self.art.isNull():
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, self.c.primary)
            gradient.setColorAt(1, self.c.secondary.darker(260))
            p.fillRect(rect, gradient)
            p.setPen(QPen(tint(QColor("#ffffff"), 36), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(8):
                r = rect.width() * (.12 + i * .06)
                p.drawEllipse(rect.center(), r, r)
        else:
            pixmap = self.art.scaled(round(rect.width()), round(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(rect.topLeft(), pixmap, QRectF((pixmap.width() - rect.width()) / 2,
                         (pixmap.height() - rect.height()) / 2, rect.width(), rect.height()))
        p.restore()

    def lyrics(self, p, rect, scene="lyrics", floating=False):
        canvas = self.floating_words if floating else self.words
        canvas.scene_mode = scene
        canvas.resize(round(rect.width()), round(rect.height()))
        canvas.set_alignment("center")
        p.save()
        p.translate(rect.topLeft())
        canvas.render(p, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, -1, -1), 12, 12)
        p.setClipPath(path)
        p.scale(self.width() / 1000., self.height() / 625.)
        p.fillRect(QRectF(0, 0, 1000, 625), QColor("#0b0c11"))
        for x, y, colour in ((220, 430, self.c.secondary), (860, 110, self.c.primary)):
            gradient = QRadialGradient(x, y, 680)
            gradient.setColorAt(0, tint(colour, 19))
            gradient.setColorAt(1, tint(colour, 0))
            p.fillRect(QRectF(0, 0, 1000, 625), gradient)
        scene = self.c.immersive_mode if self.section == "scenes" else "lyrics"
        if self.section in {"general", "halo"}:
            p.setPen(QPen(QColor(255, 255, 255, 10), 1))
            for y in range(420, 650, 40):
                p.drawLine(QPointF(0, y), QPointF(1000, y))
            self.text(p, QRectF(70, 54, 550, 30), "H A L O   /   YOUR DESKTOP", 17, QColor("#777984"))
            card = QRectF(160, 204, 680, 170)
            p.setPen(QPen(QColor("#38333f"), 1))
            p.setBrush(QColor(25, 25, 32, 225))
            p.drawRoundedRect(card, 24, 24)
            self.cover(p, QRectF(186, 230, 118, 118))
            title = self.c.track.title if self.c.track.connected else "Your music, in colour."
            artist = self.c.track.artist if self.c.track.connected else "A little atmosphere. All around you."
            self.text(p, QRectF(332, 235, 464, 25), "NOW PLAYING" if self.c.track.connected else "HALO STUDIO", 15, QColor("#9690a8"))
            self.text(p, QRectF(332, 274, 464, 36), title, 25, QColor("#f5f0fc"), QFont.Weight.DemiBold)
            self.text(p, QRectF(332, 318, 464, 26), artist, 18, QColor("#a6a0b2"))
            if self.c.floating:
                self.lyrics(p, QRectF(*floating_geometry((0, 0, 1000, 625), self.c.floating_x, self.c.floating_y)), floating=True)
        elif self.section == "lyrics":
            if self.c.floating:
                self.text(p, QRectF(70, 50, 800, 30), "YOUR DESKTOP", 17, QColor("#777984"))
                self.lyrics(p, QRectF(*floating_geometry((0, 0, 1000, 625), self.c.floating_x, self.c.floating_y)), floating=True)
            else:
                self.lyrics(p, QRectF(40, 40, 920, 545))
        elif scene == "studio":
            self.cover(p, QRectF(80, 148, 270, 270))
            self.text(p, QRectF(80, 442, 280, 36), self.c.track.title if self.c.track.connected else "Your favourite record", 25, QColor("#f7f1ff"), QFont.Weight.DemiBold)
            self.lyrics(p, QRectF(392, 78, 560, 470), "studio")
        elif scene == "orbit":
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(7):
                p.setPen(QPen(tint(self.c.primary, 60 - 7 * i), 1.5))
                p.drawEllipse(QPointF(278, 290), 152 + i * 16, 152 + i * 10)
            self.cover(p, QRectF(160, 172, 236, 236), circle=True)
            self.lyrics(p, QRectF(490, 72, 460, 480), "orbit")
        else:
            self.lyrics(p, QRectF(40, 32, 920, 500), scene)
            if scene == "cinema":
                self.cover(p, QRectF(48, 542, 46, 46))
                self.text(p, QRectF(110, 542, 550, 26), self.c.track.title if self.c.track.connected else "Your favourite record", 17, QColor("#e8e1ef"))
        if self.c.glow:
            paint_edge_glow(p, 1000, 625, self.proxy)


class StudioPreview(QFrame):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.setObjectName("studioPreview")
        self.setMinimumWidth(310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 23, 22, 22)
        header = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: #b5d5bc; font-size: 10px;")
        header.addWidget(dot)
        header.addWidget(text_label("LIVE PREVIEW", "studioEyebrow"))
        header.addStretch()
        layout.addLayout(header)
        self.scene = PreviewScreen(controller, self)
        self.transition = PageCurtain(self.scene, "#0b0c11", 12)
        self.scene.hide()
        layout.addStretch(1)
        self.caption = text_label("Your desktop, in colour", "studioSectionTitle")
        layout.addWidget(self.caption)
        self.note = text_label("", "studioHint")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.swatches = text_label("", "studioHint")
        layout.addWidget(self.swatches)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        controller.settingChanged.connect(self.sync)
        controller.trackChanged.connect(self.sync)
        controller.lyricsChanged.connect(self.sync)
        self.sync()

    def set_section(self, section):
        changed = self.scene.section != section
        self.transition.animation.stop()
        self.transition.finish()
        before = self.scene.grab() if changed and self.isVisible() and not self.c.reduced_motion else None
        self.scene.section = section
        self.sync()
        if before is not None:
            self.transition.start(before, self.scene.grab())

    def sync(self):
        if self.c.reduced_motion:
            self.transition.animation.stop()
            self.transition.finish()
        section = self.scene.section
        specs = HALO_MODES if section == "halo" else LYRIC_STYLES if section == "lyrics" else IMMERSIVE_SCENES
        key = self.c.halo_mode if section == "halo" else self.c.lyric_style if section == "lyrics" else self.c.immersive_mode
        name = next((spec[1] for spec in specs if spec[0] == key), "Halo")
        self.caption.setText("Your desktop, in colour" if section == "general" else name)
        if section in {"lyrics", "scenes"}:
            self.note.setText("Sample words · your chosen style" if self.scene.proxy.uses_sample else "Live lyrics · follows your playback")
        else:
            self.note.setText("Live audio response" if self.c.track.connected and self.c.track.playing and self.c.reactive else "Sample motion · your saved settings")
        self.swatches.setText(f"{self.c.halo_primary.name().upper()}    /    {self.c.halo_secondary.name().upper()}")
        self.scene.update()

    def tick(self):
        self.scene.proxy.advance()
        self.swatches.setText(f"{self.c.halo_primary.name().upper()}    /    {self.c.halo_secondary.name().upper()}")
        self.scene.update()
        self.update()

    def resizeEvent(self, event):
        self.transition.animation.stop()
        self.transition.finish()
        super().resizeEvent(event)
        width = self.width() - 40
        height = min(round(width * .625), max(110, self.height() - 235))
        width = round(height * 1.6)
        self.scene.setGeometry((self.width() - width) // 2, max(82, (self.height() - height - 95) // 2), width, height)
        self.scene.show()

    def showEvent(self, event):
        super().showEvent(event)
        self.scene.proxy.last = time.monotonic()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.transition.animation.stop()
        self.transition.finish()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        screen = QRectF(self.scene.geometry())
        if screen.isEmpty():
            return
        p.save()
        p.translate(screen.center().x(), screen.bottom() + 45)
        p.scale(screen.width() * .65, 65)
        pool = QRadialGradient(0, 0, 1)
        pool.setColorAt(0, tint(self.c.secondary, 23))
        pool.setColorAt(1, tint(self.c.secondary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pool)
        p.drawEllipse(QPointF(0, 0), 1, 1)
        p.restore()
        for i in range(10, 0, -1):
            p.setPen(QPen(QColor(0, 0, 0, 7), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(screen.adjusted(-i, -i + 5, i, i + 5), 16 + i, 16 + i)
        p.setPen(QPen(QColor("#4c4655"), 1.2))
        p.setBrush(QColor("#1c1a22"))
        p.drawRoundedRect(screen.adjusted(-5, -5, 5, 5), 16, 16)
        stand = QLinearGradient(screen.center().x() - 20, 0, screen.center().x() + 20, 0)
        stand.setColorAt(0, QColor("#24222a"))
        stand.setColorAt(.5, QColor("#55505d"))
        stand.setColorAt(1, QColor("#292630"))
        p.setBrush(stand)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(screen.center().x() - 16, screen.bottom() + 5, 32, 33), 2, 2)
        p.setBrush(QColor("#34303c"))
        p.drawRoundedRect(QRectF(screen.center().x() - 65, screen.bottom() + 34, 130, 6), 3, 3)


class SettingsStudio(QDialog):
    SECTIONS = (("general", "General", "A few essentials for your desktop."),
                ("halo", "Halo", "Shape the light around your music."),
                ("lyrics", "Lyrics", "Find the way you like to see every word."),
                ("scenes", "Immersive", "Set the stage for a closer listen."))

    def __init__(self, owner, controller):
        super().__init__(owner)
        self.owner, self.c = owner, controller
        self.setObjectName("settingsStudio")
        self.setWindowTitle("Halo · Settings")
        self.setWindowIcon(owner.windowIcon())
        self.setMinimumSize(960, 600)
        self.setStyleSheet(STUDIO_STYLE)
        self.section = "general"
        self.switches = {}
        self.nav_buttons = []
        self.mode_tiles = []
        owner.mode_tiles = self.mode_tiles
        owner.setting_controls = {}
        owner.setting_sliders = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 19, 24, 18)
        root.setSpacing(19)
        heading = QHBoxLayout()
        heading.addWidget(text_label("Settings", "studioSectionTitle"))
        heading.addStretch()
        heading.addWidget(text_label("MAKE HALO YOURS", "studioEyebrow"))
        heading.addSpacing(18)
        close = action("×", self.close, "studioClose")
        close.setFixedSize(32, 32)
        close.setAccessibleName("Close settings")
        close.setToolTip("Close settings · Esc")
        heading.addWidget(close)
        root.addLayout(heading)
        columns = QHBoxLayout()
        columns.setSpacing(22)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("studioSidebar")
        self.sidebar.setFixedWidth(172)
        navigation = QVBoxLayout(self.sidebar)
        navigation.setContentsMargins(10, 18, 10, 15)
        navigation.setSpacing(5)
        navigation.addWidget(text_label("YOUR SPACE", "studioEyebrow"))
        navigation.addSpacing(12)
        self.selection = QFrame(self.sidebar)
        self.selection.setObjectName("studioNavSelection")
        self.selection.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.nav_animation = QPropertyAnimation(self.selection, b"geometry", self)
        self.nav_animation.setDuration(240)
        self.nav_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        for index, (key, title, description) in enumerate(self.SECTIONS):
            button = QPushButton(title)
            button.setObjectName("studioNav")
            button.setIcon(studio_icon(key))
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedHeight(43)
            button.setAccessibleName(f"{title} settings")
            button.clicked.connect(lambda checked=False, i=index: self.select(i))
            navigation.addWidget(button)
            self.nav_buttons.append(button)
        navigation.addStretch()
        navigation.addWidget(text_label("H A L O  /  01", "studioEyebrow"))
        columns.addWidget(self.sidebar)
        center = QVBoxLayout()
        center.setSpacing(10)
        self.page_title = text_label("General", "studioTitle")
        center.addWidget(self.page_title)
        self.page_hint = text_label(self.SECTIONS[0][2], "studioHint")
        self.page_hint.setWordWrap(True)
        center.addWidget(self.page_hint)
        center.addSpacing(10)
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(330)
        self.curtain = PageCurtain(self.pages)
        center.addWidget(self.pages, 1)
        columns.addLayout(center, 5)
        self.preview = StudioPreview(controller)
        columns.addWidget(self.preview, 6)
        root.addLayout(columns, 1)
        footer = QHBoxLayout()
        self.saved = text_label("✓   Changes save automatically", "studioHint")
        footer.addWidget(self.saved)
        footer.addStretch()
        footer.addWidget(text_label("Esc to close   ·   Ctrl+, to open", "studioEyebrow"))
        root.addLayout(footer)
        self.build_pages()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.pages.currentChanged.connect(self.sync_nav)
        controller.settingChanged.connect(self.sync)
        self.select(0, animate=False)
        self.sync()

    def page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setObjectName("studioViewport")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("studioPage")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 9, 8)
        layout.setSpacing(16)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def group(self, layout, title):
        layout.addWidget(text_label(title, "studioSectionTitle"))
        frame = QFrame()
        frame.setObjectName("studioGroup")
        content = QVBoxLayout(frame)
        content.setContentsMargins(15, 6, 15, 6)
        content.setSpacing(0)
        layout.addWidget(frame)
        return content

    def row(self, layout, title, hint="", control=None):
        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 12)
        row.setSpacing(15)
        words = QVBoxLayout()
        words.setSpacing(5)
        words.addWidget(text_label(title, "studioRowTitle"))
        if hint:
            description = text_label(hint, "studioHint")
            description.setWordWrap(True)
            words.addWidget(description)
        row.addLayout(words, 1)
        if control is not None:
            row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)

    def switch(self, layout, field, title, hint):
        switch = StudioSwitch(self.c, title)
        switch.setToolTip(hint)
        switch.sync(getattr(self.c, field))
        switch.toggled.connect(lambda checked: self.c.set(field, checked))
        self.row(layout, title, hint, switch)
        self.switches[field] = switch
        self.owner.setting_controls[field] = switch
        return switch

    def modes(self, layout, field, specs):
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, spec in enumerate(specs):
            tile = ModeTile(self.c, field, spec)
            self.mode_tiles.append(tile)
            grid.addWidget(tile, index // 2, index % 2)
        layout.addLayout(grid)

    def build_pages(self):
        general = self.page()
        essential = self.group(general, "Desktop experience")
        self.owner.reduced_motion = self.switch(essential, "reduced_motion", "Reduce motion", "Keep the light and words calm. Transitions settle instantly.")
        self.row(essential, "When you close Halo", "Keep your music, glow and floating lyrics in the system tray.", text_label("Keep running", "studioValue"))
        library = self.group(general, "Artwork & connection")
        self.switch(library, "artwork_online", "Find missing covers online", "Use MusicBrainz and Cover Art Archive when Spotify omits a cover. Song details are shared for matching.")
        self.row(library, "Music source", "Halo connects through Windows media controls.", text_label("Spotify desktop", "studioValue"))
        general.addStretch()

        halo = self.page()
        light = self.group(halo, "Lighting")
        self.owner.glow = self.switch(light, "glow", "Screen-edge halo", "Soft, click-through light around every monitor.")
        self.owner.reactive = self.switch(light, "reactive", "React to audio", "Let bass and accents bloom into light. Audio stays on this PC.")
        style = QHBoxLayout()
        style.addWidget(text_label("Halo style", "studioSectionTitle"))
        style.addStretch()
        self.halo_style = selector(self.c, "halo_mode", HALO_MODES, "Halo style")
        self.halo_style.setMinimumWidth(146)
        style.addWidget(self.halo_style)
        halo.addLayout(style)
        self.light_controls = LightControls(self.c)
        self.light_controls.artwork_online.hide()
        self.owner.light_controls = self.light_controls
        self.owner.palette_select = self.light_controls.palette_select
        for name, slider in self.light_controls.sliders.items():
            self.owner.setting_sliders[name] = (slider, self.light_controls.value_labels[name], self.light_controls.suffixes[name])
        halo.addWidget(self.light_controls)
        halo.addWidget(text_label("Explore looks", "studioSectionTitle"))
        self.modes(halo, "halo_mode", HALO_MODES)
        halo.addStretch()

        lyrics = self.page()
        lyrics.addWidget(text_label("Lyric style", "studioSectionTitle"))
        self.modes(lyrics, "lyric_style", LYRIC_STYLES)
        desktop = self.group(lyrics, "On your desktop")
        self.owner.floating = self.switch(desktop, "floating", "Floating lyrics", "Keep words above your desktop while Halo is minimized.")
        self.row(desktop, "Position", "Choose a monitor and place your words.", action("Adjust…", self.owner.open_position_settings, "ghost"))
        timing = self.group(lyrics, "Timing & lyrics")
        self.owner.slider(timing, "Lyrics timing", "offset", -3000, 3000, " ms")
        slider = timing.itemAt(timing.count() - 1).widget()
        value = timing.itemAt(timing.count() - 2).layout().itemAt(2).widget()
        self.owner.setting_sliders["offset"] = (slider, value, " ms")
        hint = text_label("Positive brings lyrics earlier; negative delays them. Word timing is estimated between synced lines.", "studioHint")
        hint.setWordWrap(True)
        timing.addWidget(hint)
        timing.addSpacing(12)
        timing.addWidget(action("Import timed lyrics (.lrc)", self.owner.import_lrc, "ghost"))
        timing.addSpacing(10)
        lyrics.addStretch()

        scenes = self.page()
        scenes.addWidget(text_label("Choose your room", "studioSectionTitle"))
        self.modes(scenes, "immersive_mode", IMMERSIVE_SCENES)
        scenes.addWidget(action("Enter immersive view   ↗", self.enter_immersive, "primary"))
        hint = text_label("Space to play or pause. Esc to return. Your window size is kept when you come back.", "studioHint")
        hint.setWordWrap(True)
        scenes.addWidget(hint)
        scenes.addStretch()

    def enter_immersive(self):
        self.close()
        self.owner.fullscreen()

    def select(self, index, animate=True):
        changed = self.pages.currentIndex() != index
        self.curtain.animation.stop()
        self.curtain.finish()
        before = self.pages.currentWidget().grab() if changed and animate and self.isVisible() and not self.c.reduced_motion else None
        self.pages.setCurrentIndex(index)
        self.section, title, description = self.SECTIONS[index]
        self.page_title.setText(title)
        self.page_hint.setText(description)
        self.preview.set_section(self.section)
        self.sync_nav()
        if self.isVisible():
            self.nav_buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
        if before is not None:
            self.curtain.start(before, self.pages.currentWidget().grab())

    def sync_nav(self):
        index = self.pages.currentIndex()
        self.nav_buttons[index].setChecked(True)
        target = self.nav_buttons[index].geometry()
        self.nav_animation.stop()
        if self.c.reduced_motion or not self.isVisible():
            self.selection.setGeometry(target)
        else:
            self.nav_animation.setStartValue(self.selection.geometry())
            self.nav_animation.setEndValue(target)
            self.nav_animation.start()
        self.selection.lower()

    def sync(self):
        for name, switch in self.switches.items():
            switch.sync(getattr(self.c, name))
        for name, (slider, value, suffix) in self.owner.setting_sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(getattr(self.c, name))
            value.setText(str(getattr(self.c, name)) + suffix)
        if self.c.reduced_motion:
            self.nav_animation.stop()
            self.selection.setGeometry(self.nav_buttons[self.pages.currentIndex()].geometry())
            self.curtain.animation.stop()
            self.curtain.finish()

    def open_studio(self):
        area = self.owner.screen().availableGeometry()
        self.resize(min(1260, area.width() - 48), min(790, area.height() - 70))
        self.select(0, animate=False)
        self.show()
        bounds = self.frameGeometry()
        bounds.moveCenter(area.center())
        self.move(bounds.topLeft())
        self.raise_()
        self.activateWindow()
        self.nav_buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)
        self.sync_nav()

    def resizeEvent(self, event):
        self.curtain.animation.stop()
        self.curtain.finish()
        super().resizeEvent(event)
        QTimer.singleShot(0, self.sync_nav)

    def hideEvent(self, event):
        self.nav_animation.stop()
        self.curtain.animation.stop()
        self.curtain.finish()
        super().hideEvent(event)
