"""A native settings studio with real, isolated rendering previews."""
import math
import time
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import (Qt, QRectF, QPointF, QPoint, QSize, Property, QTimer,
                            QPropertyAnimation, QEasingCurve, QSignalBlocker)
from PySide6.QtGui import (QColor, QPainter, QPen, QPainterPath, QPixmap, QIcon,
                          QLinearGradient, QRadialGradient, QFont, QFontMetrics)
from PySide6.QtWidgets import (QDialog, QWidget, QFrame, QLabel,
    QPushButton, QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QScrollArea, QFileDialog, QSlider, QSizePolicy, QMessageBox)
from .models import Lyrics, parse_lrc, DEMO_LRC, floating_geometry
from .widgets import LyricCanvas, tint
from .lens import lens_status_text
from .glow import HALO_MODES, paint_edge_glow
from .lyric_rendering import LYRIC_STYLES
from .immersive import IMMERSIVE_SCENES
from .color_controls import LightControls
from .frontend import ModeTile, ElidedLabel, action, text_label, selector
from .backgrounds import BackgroundRenderer, BACKGROUND_PRESETS
from .mode_catalog import available_specs
from .glass import GlassSlider
from .scene_extras import extra_scene_layout, paint_extra_scene


STUDIO_STYLE = """
QDialog#settingsStudio { background: #0e1016; }
QDialog#embeddedSettings { background: transparent; }
QWidget#studioSidebar { background: rgba(255, 255, 255, 5); border: 1px solid rgba(255, 255, 255, 15); border-radius: 18px; }
QFrame#studioPreview { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(255,255,255,10),stop:1 rgba(255,255,255,3)); border: 1px solid rgba(255, 255, 255, 22); border-radius: 24px; }
QFrame#studioGroup { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,10),stop:1 rgba(255,255,255,5)); border: 1px solid rgba(255, 255, 255, 20); border-radius: 18px; }
QLabel { background: transparent; }
QLabel#studioTitle { color: #f5f3fa; font-size: 28px; font-weight: 600; }
QLabel#studioSectionTitle { color: #e9e6f1; font-size: 13px; font-weight: 600; }
QLabel#studioRowTitle { color: #edeaf4; font-size: 12px; font-weight: 500; }
QLabel#studioHint { color: #999aaa; font-size: 11px; }
QLabel#studioValue { color: #c4b4f8; font-size: 11px; }
QLabel#studioEyebrow { color: #78798c; font-size: 9px; letter-spacing: 1.6px; font-weight: 600; }
QPushButton#studioNav { background: transparent; border: 0; border-radius: 9px; text-align: left;
                       padding: 11px 10px; color: #999aaa; font-size: 12px; }
QPushButton#studioNav:checked { color: #faf7ff; font-weight: 600; }
QPushButton#studioNav:hover { color: #ffffff; }
QPushButton#studioNav:focus { border: 1px solid rgba(196,180,248,155); padding: 10px 9px; }
QFrame#studioNavSelection { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(196,180,248,31),stop:1 rgba(160,174,240,13)); border: 1px solid rgba(196,180,248,52); border-radius: 11px; }
QPushButton#studioClose { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,22); padding: 0;
                        border-radius: 11px; font-size: 19px; color: #b5b2c4; }
QPushButton#studioClose:hover { color: #ffffff; background: rgba(196,180,248,23); }
QPushButton#studioBack { background: rgba(255,255,255,5); border: 1px solid rgba(255,255,255,18); padding: 7px 12px;
                       border-radius: 12px; font-size: 11px; color: #aaa7bc; }
QPushButton#studioBack:hover { color: #f5f3fa; background: rgba(196,180,248,18); border-color: rgba(196,180,248,66); }
QPushButton#backgroundChoice { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,20);
                               border-radius: 11px; padding: 9px 5px; font-size: 11px; }
QPushButton#backgroundChoice:checked { background: rgba(196,180,248,30); border-color: rgba(196,180,248,135);
                                      color: #ece5ff; }
QPushButton#backgroundPreset { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,19);
                               border-radius: 10px; padding: 8px 4px; font-size: 11px; }
QPushButton#backgroundPreset:hover { background: rgba(196,180,248,25); border-color: rgba(196,180,248,100); }
QPushButton#backgroundDisclosure { text-align: left; background: transparent;
                                   border: 0; padding: 10px 0; color: #c4b4f8; font-size: 11px; }
QPushButton { background: rgba(255,255,255,7); border: 1px solid rgba(255,255,255,23); border-radius: 11px; padding: 8px 11px; color: #d7d4e2; }
QPushButton:hover { background: rgba(196,180,248,20); border-color: rgba(196,180,248,76); }
QPushButton:disabled { color: #626272; border-color: rgba(255,255,255,10); }
QPushButton#primary { background: #c4b4f8; color: #211b35; border: 0; font-weight: 600; }
QPushButton#primary:hover { background: #d8cbff; }
QComboBox { background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,24); border-radius: 10px; padding: 8px 10px; color: #e0dce9; }
QComboBox:hover { border-color: rgba(196,180,248,90); }
QComboBox QAbstractItemView { background: #20212b; selection-background-color: #40394f; }
QSlider::groove:horizontal { background: rgba(255,255,255,23); border: 0px solid transparent; height: 3px; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #bcaef0; border: 0px solid transparent; height: 3px; border-radius: 1px; }
QSlider::handle:horizontal { background: #eee8ff; width: 11px; margin: -5px 0; border-radius: 5px; }
QScrollArea, QWidget#studioPage, QWidget#studioViewport { background: transparent; border: 0; }
QScrollBar::handle:vertical { background: rgba(196,180,248,55); }
"""


LEARN_FIRST_LISTEN_NOTICE = ("On a first listen, words can move abruptly, because Halo can't see the next word coming. "
                             "Replays use saved timing, so words glide smoothly once a song has played through.")
LEARN_WORD_TIMING_HINT = ("Halo analyses all sound on this PC's output with a small model that runs here, to place each lyric word. "
                          "It keeps only word times, which do show which songs you played, and never saves or sends audio. "
                          "Timing is estimated, and can be wrong. "
                          "Spotify's rules restrict this kind of processing, so turn this on only if you accept that.")


class StudioNavButton(QPushButton):
    """A restrained glass highlight that eases in with the pointer."""
    def __init__(self, controller, title):
        super().__init__(title)
        self.c = controller
        self._hover = 0.
        self.hover_animation = QPropertyAnimation(self, b"hover", self)
        self.hover_animation.setDuration(170)
        self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        controller.settingChanged.connect(self._settle_motion)

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = float(value)
        self.update()

    hover = Property(float, get_hover, set_hover)

    def _animate_hover(self, target):
        self.hover_animation.stop()
        if self.c.reduced_motion or not self.isVisible():
            self.set_hover(target)
        else:
            self.hover_animation.setStartValue(self._hover)
            self.hover_animation.setEndValue(target)
            self.hover_animation.start()

    def _settle_motion(self):
        if self.c.reduced_motion:
            self.hover_animation.stop()
            self.set_hover(float(self.underMouse()))

    def enterEvent(self, event):
        self._animate_hover(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.)
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._hover > .001:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            sheen = QLinearGradient(0, 0, self.width(), self.height())
            sheen.setColorAt(0, QColor(220, 211, 255, round(14 * self._hover)))
            sheen.setColorAt(1, QColor(220, 211, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sheen)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)


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


def show_learn_notice(parent):
    """Explain the first listen. Returns True if the listener asked not to see this again."""
    box = QMessageBox(parent)
    box.setWindowTitle("Learn word timing")
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(LEARN_FIRST_LISTEN_NOTICE)
    # The dialog does not take ownership, so an inline checkbox is freed while it is still on screen.
    remember = QCheckBox("Don't show this again")
    box.setCheckBox(remember)
    box.exec()
    return remember.isChecked()


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
        self.background = BackgroundRenderer(self)
        self.background.changed.connect(self.update)
        self.setAccessibleName("Live preview of Halo on your desktop")
        controller.trackChanged.connect(self.refresh_art)
        if hasattr(controller, "backgroundChanged"):
            controller.backgroundChanged.connect(self.refresh_background)
        self.refresh_art()

    def refresh_art(self):
        self.art = QPixmap()
        if self.c.track.artwork:
            self.art.loadFromData(self.c.track.artwork)
        self.refresh_background()
        self.update()

    def refresh_background(self):
        active = (self.section == "scenes" and self.isVisible()
                  and self.window().isVisible() and not self.window().isMinimized())
        if active:
            self.background.sync(self.c, active=True, preview=True)
        else:
            self.background.close()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_background()

    def hideEvent(self, event):
        self.background.close()
        super().hideEvent(event)

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

    def lyrics(self, p, rect, scene="lyrics", floating=False, alignment="center"):
        canvas = self.floating_words if floating else self.words
        canvas.scene_mode = scene
        canvas.resize(round(rect.width()), round(rect.height()))
        canvas.set_alignment(alignment)
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
        painted = self.section == "scenes" and self.background.paint(p, QRectF(0, 0, 1000, 625), self.proxy.motion_time)
        if not painted:
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
        elif extra_scene_layout(scene, 1000, 625) is not None:
            layout = extra_scene_layout(scene, 1000, 625)
            paint_extra_scene(p, 1000, 625, self.proxy, scene, self.proxy.motion_time)
            self.cover(p, QRectF(layout["cover"]))
            self.lyrics(p, QRectF(layout["canvas"]), scene, alignment=layout["alignment"])
            credits = (("song", self.c.track.title if self.c.track.connected else "Your favourite record", 14 if scene == "scene_runway" else 22),
                       ("artist", self.c.track.artist if self.c.track.connected else "In your own atmosphere", 11 if scene == "scene_runway" else 16),
                       ("album", self.c.track.album or "Sound in colour", 10 if scene == "scene_runway" else 12))
            for key, value, pixels in credits:
                self.text(p, QRectF(layout[key]), value, pixels, QColor("#d9dee5"))
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
        self.setMinimumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 22)
        header = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: #a6d7bd; font-size: 8px;")
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
        self.scene.refresh_background()
        self.scene.update()

    def tick(self):
        if not self.isVisible() or not self.window().isVisible() or self.window().isMinimized():
            self.timer.stop()
            self.scene.background.close()
            return
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
        if self.window().isVisible() and not self.window().isMinimized():
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.scene.background.close()
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
                ("halo", "Lighting", "Shape the light around your music."),
                ("lyrics", "Lyrics", "Find the way you like to see every word."),
                ("scenes", "Immersive", "Set the stage for a closer listen."))

    def __init__(self, owner, controller, embedded=False):
        super().__init__(owner)
        self.owner, self.c = owner, controller
        self.embedded = bool(embedded)
        if self.embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("embeddedSettings" if self.embedded else "settingsStudio")
        self.setWindowTitle("Halo · Settings")
        self.setWindowIcon(owner.windowIcon())
        self.setMinimumSize(0, 0) if self.embedded else self.setMinimumSize(960, 600)
        self.setStyleSheet(STUDIO_STYLE)
        self.section = "general"
        self.switches = {}
        self.background_controls = {}
        self.background_sliders = {}
        self.background_sources = {}
        self.nav_buttons = []
        self.mode_tiles = []
        self.mode_grids = {}
        owner.mode_tiles = self.mode_tiles
        owner.setting_controls = {}
        owner.setting_sliders = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 8, 4, 4) if self.embedded else root.setContentsMargins(24, 21, 24, 18)
        root.setSpacing(18)
        heading = QHBoxLayout()
        heading.addWidget(text_label("PREFERENCES" if self.embedded else "Settings", "studioEyebrow" if self.embedded else "studioSectionTitle"))
        heading.addStretch()
        if not self.embedded:
            heading.addWidget(text_label("MAKE HALO YOURS", "studioEyebrow"))
            heading.addSpacing(18)
        close = action("‹  Back to listening" if self.embedded else "×", self.close, "studioBack" if self.embedded else "studioClose")
        if not self.embedded:
            close.setFixedSize(32, 32)
        close.setAccessibleName("Back to listening" if self.embedded else "Close settings")
        close.setToolTip("Return to listening · Esc" if self.embedded else "Close settings · Esc")
        heading.addWidget(close)
        root.addLayout(heading)
        columns = QHBoxLayout()
        columns.setSpacing(20)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("studioSidebar")
        self.sidebar.setFixedWidth(132 if self.embedded else 156)
        navigation = QVBoxLayout(self.sidebar)
        navigation.setContentsMargins(8, 18, 8, 15)
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
            button = StudioNavButton(self.c, title)
            button.setObjectName("studioNav")
            button.setIcon(studio_icon(key))
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedHeight(42)
            button.setAccessibleName(f"{title} settings")
            button.clicked.connect(lambda checked=False, i=index: self.select(i))
            navigation.addWidget(button)
            self.nav_buttons.append(button)
        navigation.addStretch()
        navigation.addWidget(text_label("YOUR HALO", "studioEyebrow"))
        columns.addWidget(self.sidebar)
        if self.embedded:
            self.sidebar.hide()
            self.selection.hide()
        center = QVBoxLayout()
        center.setSpacing(8)
        self.page_title = text_label("General", "studioTitle")
        self.page_title.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self.embedded else Qt.FocusPolicy.NoFocus)
        center.addWidget(self.page_title)
        self.page_hint = text_label(self.SECTIONS[0][2], "studioHint")
        self.page_hint.setWordWrap(True)
        center.addWidget(self.page_hint)
        center.addSpacing(12)
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(270 if self.embedded else 330)
        self.curtain = PageCurtain(self.pages, "#14151d")
        center.addWidget(self.pages, 1)
        columns.addLayout(center, 6)
        self.preview = StudioPreview(controller)
        columns.addWidget(self.preview, 5)
        root.addLayout(columns, 1)
        footer = QHBoxLayout()
        self.saved = text_label("✓   Changes save automatically", "studioHint")
        footer.addWidget(self.saved)
        footer.addStretch()
        footer.addWidget(text_label("Esc to return" if self.embedded else "Esc to close   ·   Ctrl+, to open", "studioEyebrow"))
        root.addLayout(footer)
        self.build_pages()
        self.preview.scene.background.changed.connect(self.sync_background)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pages.currentChanged.connect(self.sync_nav)
        controller.settingChanged.connect(self.sync)
        if hasattr(controller, "modeLibraryChanged"):
            controller.modeLibraryChanged.connect(self.refresh_modes)
        controller.trackChanged.connect(self.sync_lyrics)
        controller.lyricsChanged.connect(self.sync_lyrics)
        if hasattr(controller, "backgroundChanged"):
            controller.backgroundChanged.connect(self.sync_background)
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
        content.setContentsMargins(16, 6, 16, 6)
        content.setSpacing(0)
        layout.addWidget(frame)
        return content

    def row(self, layout, title, hint="", control=None):
        row = QHBoxLayout()
        row.setContentsMargins(0, 14, 0, 14)
        row.setSpacing(14)
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
        self.mode_grids[field] = (grid, specs)
        for index, spec in enumerate(available_specs(self.c, field, specs)):
            tile = ModeTile(self.c, field, spec)
            self.mode_tiles.append(tile)
            grid.addWidget(tile, index // 2, index % 2)
        layout.addLayout(grid)

    def refresh_modes(self):
        for field, (grid, specs) in self.mode_grids.items():
            self.mode_tiles[:] = [tile for tile in self.mode_tiles if tile.setting != field]
            while grid.count():
                item = grid.takeAt(0)
                if item.widget() is not None:
                    item.widget().hide()
                    item.widget().deleteLater()
            for index, spec in enumerate(available_specs(self.c, field, specs)):
                tile = ModeTile(self.c, field, spec)
                self.mode_tiles.append(tile)
                grid.addWidget(tile, index // 2, index % 2)
        self.preview.sync()

    def background_selector(self, layout, field, title, specs, hint=""):
        control = selector(self.c, field, specs, title)
        control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        control.setMinimumWidth(0)
        self.row(layout, title, hint)
        layout.addWidget(control)
        self.background_controls[field] = control
        return control

    def background_slider(self, layout, field, title, low, high, suffix="%"):
        line = QHBoxLayout()
        title_label = text_label(title, "studioHint")
        line.addWidget(title_label)
        line.addStretch()
        value = text_label(f"{getattr(self.c, field)}{suffix}", "studioValue")
        line.addWidget(value)
        layout.addSpacing(13)
        layout.addLayout(line)
        slider = GlassSlider(Qt.Orientation.Horizontal)
        slider.setAccessibleName(title)
        slider.setRange(low, high)
        slider.setValue(getattr(self.c, field))
        slider.setMinimumHeight(27)
        slider.valueChanged.connect(lambda amount: self.c.set(field, amount))
        layout.addWidget(slider)
        self.background_sliders[field] = slider
        self.background_controls[field] = slider
        self.owner.setting_sliders[field] = (slider, value, suffix)
        return slider

    def build_background_controls(self, scenes):
        source = self.group(scenes, "Background")
        self.background_anchor = source.parentWidget()
        source.addSpacing(10)
        hint = text_label("Give your listening room its own atmosphere.", "studioHint")
        hint.setWordWrap(True)
        source.addWidget(hint)
        source.addSpacing(12)
        choices = QGridLayout()
        choices.setSpacing(7)
        for index, (key, label) in enumerate((("ambient", "Ambient light"), ("artwork", "Album artwork"),
                                             ("image", "Your image"), ("video", "Your video"))):
            button = action(label, lambda checked=False, selected=key: self.c.set("background_source", selected), "backgroundChoice")
            button.setCheckable(True)
            button.setAccessibleName(f"Use {label.lower()} background")
            choices.addWidget(button, index // 2, index % 2)
            self.background_sources[key] = button
        source.addLayout(choices)
        source.addSpacing(9)
        self.background_file = action("Choose image…", self.choose_background_file, "ghost")
        self.background_file.setAccessibleName("Choose a background image or video")
        source.addWidget(self.background_file)
        self.background_file_label = ElidedLabel("", "studioHint")
        self.background_file_label.setAccessibleName("Selected background file")
        source.addWidget(self.background_file_label)
        self.background_art_group = QWidget()
        art_controls = QVBoxLayout(self.background_art_group)
        art_controls.setContentsMargins(0, 0, 0, 0)
        art_controls.setSpacing(0)
        self.background_art_source = self.background_selector(art_controls, "background_art_source", "Artwork source", (
            ("spotify", "Spotify cover", "Use the artwork supplied by Spotify."),
            ("online", "Find a cover online", "Match song details with MusicBrainz and Cover Art Archive.")))
        source.addWidget(self.background_art_group)
        self.background_privacy = text_label("Online matching sends song, artist and album details to MusicBrainz and Cover Art Archive. Spotify artwork is used when a match is unavailable.", "studioHint")
        self.background_privacy.setWordWrap(True)
        source.addSpacing(8)
        source.addWidget(self.background_privacy)
        self.background_status = text_label("", "studioHint")
        self.background_status.setWordWrap(True)
        self.background_status.setAccessibleName("Background status")
        source.addSpacing(10)
        source.addWidget(self.background_status)
        reset = action("Reset background", self.c.reset_background, "ghost")
        reset.setAccessibleName("Reset background to ambient light")
        source.addSpacing(10)
        source.addWidget(reset)
        source.addSpacing(7)

        look = self.group(scenes, "Look")
        look.addSpacing(8)
        self.background_look_hint = text_label("Choose artwork, an image or a video to explore these looks.", "studioHint")
        self.background_look_hint.setWordWrap(True)
        look.addWidget(self.background_look_hint)
        look.addSpacing(7)
        presets = QGridLayout()
        presets.setSpacing(7)
        self.background_presets = {}
        for index, (key, title, _) in enumerate(BACKGROUND_PRESETS):
            button = action(title, lambda checked=False, chosen=key: self.c.apply_background_preset(chosen), "backgroundPreset")
            button.setAccessibleName(f"Apply {title.lower()} background look")
            presets.addWidget(button, index // 2, index % 2, 1, 2 if index == 4 else 1)
            self.background_presets[key] = button
        look.addLayout(presets)
        self.background_slider(look, "background_dim", "Darken", 0, 90)
        self.background_slider(look, "background_blur", "Soft focus", 0, 60, " px")
        self.background_slider(look, "background_saturation", "Colour richness", 0, 160)
        self.background_disclosure = action("Composition & finishing   +", self.toggle_background_composition, "backgroundDisclosure")
        self.background_disclosure.setCheckable(True)
        self.background_disclosure.setAccessibleName("Show composition and finishing controls")
        look.addWidget(self.background_disclosure)
        self.background_composition = QWidget()
        composition = QVBoxLayout(self.background_composition)
        composition.setContentsMargins(0, 0, 0, 6)
        composition.setSpacing(0)
        self.background_selector(composition, "background_fit", "Framing", (
            ("cover", "Fill the screen", "Crop the image to fill your listening room."),
            ("contain", "Show the full image", "Keep all of your image visible.")))
        self.background_slider(composition, "background_zoom", "Zoom", 100, 150)
        self.background_slider(composition, "background_focus_x", "Horizontal focus", 0, 100)
        self.background_slider(composition, "background_focus_y", "Vertical focus", 0, 100)
        self.background_slider(composition, "background_vignette", "Edge shading", 0, 100)
        self.background_slider(composition, "background_tint", "Album colour wash", 0, 60)
        look.addWidget(self.background_composition)
        self.background_composition.hide()

        motion = self.group(scenes, "Motion")
        self.background_selector(motion, "background_motion", "Movement", (
            ("still", "Still", "Keep the composition settled."),
            ("drift", "Slow drift", "A gentle, floating camera movement."),
            ("breathe", "Breathe", "A soft, gradual expansion and release.")))
        self.background_slider(motion, "background_speed", "Movement speed", 0, 100)
        self.background_video_group = QWidget()
        video_controls = QVBoxLayout(self.background_video_group)
        video_controls.setContentsMargins(0, 0, 0, 0)
        video_controls.setSpacing(0)
        self.background_playback = self.background_selector(video_controls, "background_playback", "Video playback", (
            ("music", "Follow music playback", "Pause the video when your music pauses."),
            ("always", "Loop while immersive is open", "Keep the video moving while the room is visible.")))
        motion.addWidget(self.background_video_group)
        self.background_motion_note = text_label("", "studioHint")
        self.background_motion_note.setWordWrap(True)
        motion.addSpacing(10)
        motion.addWidget(self.background_motion_note)
        motion.addSpacing(7)

    def toggle_background_composition(self, checked):
        self.background_composition.setVisible(checked)
        self.background_disclosure.setText("Composition & finishing   −" if checked else "Composition & finishing   +")
        self.background_disclosure.setAccessibleName("Hide composition and finishing controls" if checked else "Show composition and finishing controls")

    def choose_background_file(self):
        source = self.c.background_source
        video = source == "video"
        title = "Choose your background video" if video else "Choose your background image"
        filters = ("Videos (*.mp4 *.m4v *.mov *.webm *.mkv *.avi);;All files (*)" if video else
                   "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif);;All files (*)")
        path, _ = QFileDialog.getOpenFileName(self, title, "", filters)
        if path:
            try:
                self.c.set_background_file(path, "video" if video else "image")
            except (OSError, ValueError):
                self.sync_background()

    def sync_background(self):
        if not hasattr(self, "background_status"):
            return
        c = self.c
        source = c.background_source
        media = source in {"artwork", "image", "video"}
        camera = media and c.background_fit == "cover"
        local = source in {"image", "video"}
        for key, button in self.background_sources.items():
            with QSignalBlocker(button):
                button.setChecked(key == source)
        self.background_file.setVisible(local)
        self.background_file.setText("Choose video…" if source == "video" else "Choose image…")
        self.background_file_label.setVisible(local and bool(c.background_path))
        filename = Path(c.background_path).name if c.background_path else ""
        self.background_file_label.setText(filename)
        self.background_file_label.setToolTip(filename)
        self.background_art_source.setEnabled(source == "artwork")
        self.background_art_group.setVisible(source == "artwork")
        self.background_privacy.setVisible(source == "artwork")
        self.background_playback.setEnabled(source == "video" and not c.reduced_motion)
        self.background_video_group.setVisible(source == "video")
        self.background_look_hint.setVisible(not media)
        for field in ("background_dim", "background_blur", "background_saturation", "background_fit", "background_zoom", "background_focus_x", "background_focus_y", "background_vignette", "background_tint"):
            self.background_controls[field].setEnabled(media)
        for field in ("background_zoom", "background_focus_x", "background_focus_y"):
            self.background_controls[field].setEnabled(camera)
        for button in self.background_presets.values():
            button.setEnabled(media)
        self.background_controls["background_motion"].setEnabled(camera and not c.reduced_motion)
        self.background_controls["background_speed"].setEnabled(camera and not c.reduced_motion and c.background_motion != "still")
        status = getattr(c, "background_error", "")
        if not status:
            if source == "ambient":
                status = "Soft album-colour light. No background file needed."
            elif source == "artwork":
                status = ("Online cover matching · Spotify artwork is the fallback." if c.background_art_source == "online" else
                          "Changes with the cover supplied by Spotify.")
                renderer = self.preview.scene.background
                if not renderer.has_media and renderer.status not in {"", "Halo ambience"}:
                    status = renderer.status
            elif not filename:
                status = "Choose a video to set the scene." if source == "video" else "Choose an image to set the scene."
            else:
                status = self.preview.scene.background.status or "Your background is saved."
                if status == filename:
                    status = "Video background · saved automatically." if source == "video" else "Image background · saved automatically."
        self.background_status.setText(status)
        self.background_motion_note.setText("Ambient light follows your Halo settings. Choose an image, video or artwork to shape a background." if not media else
                                           "Reduce motion is on. Camera movement is still and video holds a quiet frame." if c.reduced_motion else
                                           "Full-image framing keeps the camera still and the whole image visible. Videos can still loop silently." if not camera else
                                           "Videos loop silently. Playback stops when you leave the room or close the preview." if source == "video" else
                                           "Subtle camera movement keeps the room alive without distracting from the words.")

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
        halo.addWidget(action("Explore light modes   →", lambda: self.owner.open_modes("halo"), "ghost"))
        halo.addStretch()

        lyrics = self.page()
        lyrics.addWidget(text_label("Lyric style", "studioSectionTitle"))
        self.modes(lyrics, "lyric_style", LYRIC_STYLES)
        lyrics.addWidget(action("Explore lyric styles   →", lambda: self.owner.open_modes("lyrics"), "ghost"))
        self.lens_status = text_label("", "studioHint")
        self.lens_status.setWordWrap(True)
        lyrics.addWidget(self.lens_status)
        desktop = self.group(lyrics, "On your desktop")
        self.owner.floating = self.switch(desktop, "floating", "Floating lyrics", "Keep words above your desktop while Halo is minimized.")
        self.row(desktop, "Position", "Choose a monitor and place your words.", action("Adjust…", self.owner.open_position_settings, "ghost"))
        timing = self.group(lyrics, "Timing & lyrics")
        self.lyric_song_label = text_label("", "studioRowTitle")
        self.lyric_song_label.setTextFormat(Qt.TextFormat.PlainText)
        self.lyric_song_label.setWordWrap(True)
        timing.addWidget(self.lyric_song_label)
        self.owner.slider(timing, "This song's correction", "song_offset", -10000, 10000, " ms")
        slider = timing.itemAt(timing.count() - 1).widget()
        value = timing.itemAt(timing.count() - 2).layout().itemAt(2).widget()
        self.owner.setting_sliders["song_offset"] = (slider, value, " ms")
        self.song_timing_slider = slider
        self.song_timing_buttons = []
        adjustments = QHBoxLayout()
        for title, delta in (("Earlier · 0.1s", 100), ("Later · 0.1s", -100), ("Reset", 0)):
            button = action(title, lambda checked=False, amount=delta: self.c.adjust_lyrics(amount) if amount else self.c.set_song_offset(0), "ghost")
            button.setAccessibleName(f"{title} for this song")
            adjustments.addWidget(button)
            self.song_timing_buttons.append(button)
        timing.addLayout(adjustments)
        hint = text_label("Earlier advances the words; Later delays them. Saved for this recording, including after restarting Halo. A fixed correction cannot repair uneven timestamps.", "studioHint")
        hint.setWordWrap(True)
        timing.addWidget(hint)
        timing.addSpacing(12)
        self.lyric_timing_status = text_label("", "studioHint")
        self.lyric_timing_status.setWordWrap(True)
        timing.addWidget(self.lyric_timing_status)
        self.import_lyrics_button = action("Import timed lyrics…", self.owner.import_lrc, "ghost")
        timing.addWidget(self.import_lyrics_button)
        self.choose_lyrics_button = action("Wrong lyrics? Choose a match…", self.owner.choose_lyrics, "ghost")
        timing.addWidget(self.choose_lyrics_button)
        self.automatic_lyrics_button = action("Use automatic lyrics again", self.c.use_automatic_lyrics, "ghost")
        timing.addWidget(self.automatic_lyrics_button)
        timing.addSpacing(12)
        self.switch(timing, "learn_word_timing", "Learn word timing from playback", "Follow each word by listening to this PC's sound.")
        self.switches["learn_word_timing"].clicked.connect(self.learn_timing_clicked)
        hint = text_label(LEARN_WORD_TIMING_HINT, "studioHint")
        hint.setWordWrap(True)
        timing.addWidget(hint)
        self.forget_timing_button = action("Forget learned timing", lambda checked=False: self.c.forget_learned_timing(), "ghost")
        timing.addWidget(self.forget_timing_button)
        self.forget_all_timing_button = action("Forget all", lambda checked=False: self.c.forget_learned_timing(True), "ghost")
        timing.addWidget(self.forget_all_timing_button)
        timing.addSpacing(10)
        lyrics.addStretch()

        scenes = self.page()
        scenes.addWidget(text_label("Choose your room", "studioSectionTitle"))
        self.modes(scenes, "immersive_mode", IMMERSIVE_SCENES)
        scenes.addWidget(action("Explore immersive rooms   →", lambda: self.owner.open_modes("scenes"), "ghost"))
        scenes.addWidget(action("Enter immersive view   →", self.enter_immersive, "primary"))
        hint = text_label("Space to play or pause. Esc to return. Your window size is kept when you come back.", "studioHint")
        hint.setWordWrap(True)
        scenes.addWidget(hint)
        self.build_background_controls(scenes)
        scenes.addStretch()
        self.sync_lyrics()

    def learn_timing_clicked(self, checked):
        if checked and not self.c.hide_learn_word_timing_notice and show_learn_notice(self):
            self.c.set("hide_learn_word_timing_notice", True)

    def sync_lyrics(self):
        if not hasattr(self, "lyric_song_label"):
            return
        c = self.c
        enabled = c.can_correct_lyrics()
        self.lyric_song_label.setText(c.track.title if enabled else "Play a Spotify song to save corrections")
        self.song_timing_slider.setEnabled(enabled)
        for button in [*self.song_timing_buttons, self.import_lyrics_button, self.choose_lyrics_button]:
            button.setEnabled(enabled)
        self.automatic_lyrics_button.setEnabled(enabled and bool(c.saved_lyric_kind))
        populated = [line for line in c.lyrics.lines if line.text.strip()]
        true_words = sum(bool(getattr(line, "words", ())) for line in populated)
        timing = ("Word timing learned on this PC; other words follow playback or are estimated." if c.lyrics.timing_source == "learned"
                  else "Word timestamps supplied by the lyric source." if true_words and true_words == len(populated)
                  else "Some lines have word timestamps; other words are estimated." if true_words
                  else "Line timestamps only; word animation is estimated." if populated
                  else "No timed lyrics loaded.")
        source = "Saved import. " if c.saved_lyric_kind == "imported" else "Your saved lyric choice. " if c.saved_lyric_kind else ""
        calibration = f" All-song calibration: {c.global_offset:+d} ms." if c.global_offset else ""
        self.lyric_timing_status.setText(c.lyric_save_error or source + timing + calibration)
        self.sync_lens_status()

    def sync_lens_status(self):
        lens_text = lens_status_text()
        self.lens_status.setText(lens_text)
        self.lens_status.setVisible(bool(lens_text))

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
        self.page_title.setAccessibleName(f"{title} settings")
        self.page_hint.setText(description)
        if (self.embedded and getattr(self.owner, "settings_dialog", None) is self
                and hasattr(self.owner, "sync_navigation")):
            self.owner.sync_navigation()
        self.preview.set_section(self.section)
        self.sync_nav()
        if self.isVisible():
            target = self.page_title if self.embedded else self.nav_buttons[index]
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        if before is not None:
            self.curtain.start(before, self.pages.currentWidget().grab())

    def sync_nav(self):
        index = self.pages.currentIndex()
        self.nav_buttons[index].setChecked(True)
        self.nav_animation.stop()
        if self.embedded:
            self.selection.hide()
            for button in self.nav_buttons:
                button.hover_animation.stop()
                button.set_hover(0.)
            return
        target = self.nav_buttons[index].geometry()
        if self.c.reduced_motion or not self.isVisible():
            self.selection.setGeometry(target)
        else:
            self.nav_animation.setStartValue(self.selection.geometry())
            self.nav_animation.setEndValue(target)
            self.nav_animation.start()
        self.selection.lower()

    def sync(self):
        self.sync_lyrics()
        self.sync_background()
        for name, switch in self.switches.items():
            switch.sync(getattr(self.c, name))
        for name, (slider, value, suffix) in self.owner.setting_sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(getattr(self.c, name))
            value.setText(str(getattr(self.c, name)) + suffix)
        if self.c.reduced_motion:
            self.nav_animation.stop()
            if not self.embedded:
                self.selection.setGeometry(self.nav_buttons[self.pages.currentIndex()].geometry())
            self.curtain.animation.stop()
            self.curtain.finish()

    def open_studio(self, section="general"):
        if self.embedded:
            if hasattr(self.owner, "navigate"):
                self.owner.navigate("settings")
        else:
            area = self.owner.screen().availableGeometry()
            self.resize(min(1260, area.width() - 48), min(790, area.height() - 70))
        index = next((index for index, item in enumerate(self.SECTIONS) if item[0] == section), 0)
        self.select(index, animate=False)
        self.show()
        if not self.embedded:
            bounds = self.frameGeometry()
            bounds.moveCenter(area.center())
            self.move(bounds.topLeft())
            self.raise_()
            self.activateWindow()
        if self.embedded:
            self.page_title.setFocus(Qt.FocusReason.OtherFocusReason)
            self.sync_nav()
        else:
            self.nav_buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
            self.sidebar.layout().activate()
            self.nav_animation.stop()
            self.nav_buttons[index].setChecked(True)
            self.selection.setGeometry(self.nav_buttons[index].geometry())
            self.selection.lower()
        self.sync_visibility()

    def sync_visibility(self):
        """Suspend preview work while the shell is hidden or minimized."""
        active = (self.isVisible() and self.preview.isVisible()
                  and self.window().isVisible() and not self.window().isMinimized())
        if active:
            if not self.preview.timer.isActive():
                self.preview.scene.proxy.last = time.monotonic()
                self.preview.timer.start()
            self.preview.scene.refresh_background()
        else:
            self.preview.timer.stop()
            self.preview.scene.background.close()
            self.preview.transition.animation.stop()
            self.preview.transition.finish()
            self.nav_animation.stop()
            self.curtain.animation.stop()
            self.curtain.finish()

    def open_backgrounds(self):
        self.open_studio("scenes")
        def reveal():
            if self.isVisible() and self.section == "scenes":
                page = self.pages.currentWidget()
                page.verticalScrollBar().setValue(max(0, self.background_anchor.y() - 38))
                self.background_sources[self.c.background_source].setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, self, reveal)

    def resizeEvent(self, event):
        self.curtain.animation.stop()
        self.curtain.finish()
        super().resizeEvent(event)
        if self.embedded:
            self.preview.setVisible(self.width() >= 730)
        QTimer.singleShot(0, self, self.sync_nav)
        QTimer.singleShot(0, self, self.sync_visibility)

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_lens_status()
        QTimer.singleShot(0, self, self.sync_visibility)

    def hideEvent(self, event):
        self.nav_animation.stop()
        self.curtain.animation.stop()
        self.curtain.finish()
        self.preview.timer.stop()
        self.preview.scene.background.close()
        for button in self.nav_buttons:
            button.hover_animation.stop()
        super().hideEvent(event)
