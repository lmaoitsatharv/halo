"""Halo's native control room: live previews and a focused listening surface."""
import math
import time
from PySide6.QtCore import Qt, QRectF, QPointF, QSignalBlocker, QRect, QSize, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QLinearGradient, QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QAbstractButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QButtonGroup, QStackedWidget, QScrollArea,
    QCheckBox, QComboBox, QSlider, QSizePolicy)
from .widgets import Artwork, LyricCanvas, font, tint
from .glow import HALO_MODES, paint_halo_preview
from .lyric_rendering import LYRIC_STYLES
from .immersive import IMMERSIVE_SCENES
from .color_controls import LightControls


STYLE = """
QWidget { color: #f0f0f4; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; }
QFrame#card { background: rgba(20, 23, 31, 235); border: 1px solid #30333e; border-radius: 20px; }
QFrame#settingsCard { background: rgba(18, 21, 28, 240); border: 1px solid #30333e; border-radius: 20px; }
QLabel#eyebrow { color: #9093a5; font-size: 10px; font-weight: 600; letter-spacing: 2px; }
QLabel#muted { color: #9398ac; font-size: 12px; }
QLabel#title { font-size: 27px; font-weight: 600; color: #f2f1f6; }
QLabel#brand { font-size: 29px; font-weight: 600; letter-spacing: 4px; }
QLabel#badge { background: #1d2927; border: 1px solid #334c42; border-radius: 12px;
              color: #b5ddc6; padding: 6px 12px; font-size: 11px; }
QLabel#panelTitle { color: #eeeef5; font-size: 18px; font-weight: 600; }
QPushButton { border: 1px solid #393d4c; border-radius: 11px; padding: 9px 14px;
              background: #222632; color: #e3e5ed; }
QPushButton:hover { background: #313646; border-color: #646780; }
QPushButton:pressed { background: #3d4257; }
QPushButton:disabled { color: #64697b; border-color: #2c303d; }
QPushButton#primary { color: #181925; background: #dad1fa; border: 0; font-weight: 600; }
QPushButton#primary:hover { background: #ece5ff; }
QPushButton#ghost { background: transparent; border-color: #333747; font-size: 11px; padding: 6px 10px; }
QPushButton#sectionTab { background: transparent; border: 0; border-radius: 10px; padding: 8px 12px; color: #969bb1; }
QPushButton#sectionTab:checked { background: #343447; color: #f4f0ff; }
QPushButton#sectionTab:hover { background: #292c3b; color: #f4f0ff; }
QPushButton:focus { border-color: #cbb9f3; }
QPushButton#sectionTab:focus { border: 1px solid #b6a5d7; padding: 7px 11px; }
QCheckBox { spacing: 10px; color: #d9dce8; }
QCheckBox::indicator { width: 30px; height: 17px; border-radius: 8px; background: #3b4051; border: 1px solid #454b5f; }
QCheckBox::indicator:checked { background: #c9baf3; border-color: #ddd0ff; }
QCheckBox::indicator:hover { border-color: #a18cbf; }
QSlider::groove:horizontal { height: 4px; background: #35394a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #bba8e7; border-radius: 2px; }
QSlider::handle:horizontal { width: 10px; margin: -4px 0; border-radius: 5px; background: #e1d6fa; }
QComboBox { color: #d8dbe9; background: #232734; border: 1px solid #3a4050; border-radius: 9px; padding: 8px 10px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #222735; color: #eef0f5; border: 1px solid #464c62; selection-background-color: #44405e; }
QScrollArea#settingsScroll, QWidget#settingsPage, QWidget#settingsViewport { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
QScrollBar::handle:vertical { background: #464b5c; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QMenu { background: #202432; color: #e5e7ef; border: 1px solid #434a5d; padding: 6px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: #41425c; }
QToolTip { color: #edf0f7; background: #2b3040; border: 1px solid #626984; padding: 5px; }
"""


def text_label(text, name="muted"):
    result = QLabel(text)
    result.setObjectName(name)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


def action(text, callback, name=None):
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.clicked.connect(callback)
    return result


class FittedTitle(QLabel):
    """Keep long song names inside the now-playing card at compact sizes."""
    def __init__(self, text):
        super().__init__(text)
        self.full_text = text
        self.setObjectName("title")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setMaximumHeight(70)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        width, height = max(40, self.width()), max(30, self.height())
        value = self.full_text
        preferred = QFont("Segoe UI")
        preferred.setPixelSize(27)
        preferred.setWeight(QFont.Weight.DemiBold)
        minimum = 60 if QFontMetrics(preferred).horizontalAdvance(value) > width else 0
        if self.minimumHeight() != minimum:
            self.setMinimumHeight(minimum)
        for size in range(27, 15, -1):
            face = QFont("Segoe UI")
            face.setPixelSize(size)
            face.setWeight(QFont.Weight.DemiBold)
            metrics = QFontMetrics(face)
            bounds = metrics.boundingRect(QRect(0, 0, width, 1000), int(Qt.TextFlag.TextWordWrap), value)
            if bounds.height() <= height:
                break
        if bounds.height() > height:
            low, high = 0, len(value)
            while low < high:
                middle = (low + high + 1) // 2
                bounds = metrics.boundingRect(QRect(0, 0, width, 1000), int(Qt.TextFlag.TextWordWrap), value[:middle].rstrip() + "…")
                if bounds.height() <= height:
                    low = middle
                else:
                    high = middle - 1
            value = value[:low].rstrip() + "…"
        self.setStyleSheet(f"font-size: {size}px; font-weight: 600;")
        super().setText(value)


class ElidedLabel(QLabel):
    def __init__(self, text, name="muted"):
        super().__init__(text)
        self.full_text = text
        self.setObjectName(name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        super().setText(QFontMetrics(self.font()).elidedText(text, Qt.TextElideMode.ElideRight, max(20, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.full_text)


class HaloMark(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.hover_phase = 0.0
        self.last_phase_tick = time.monotonic()
        self.setFixedSize(45, 45)
        self.setToolTip("Your music, in motion")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = time.monotonic()
        elapsed = max(0, min(.08, now - self.last_phase_tick))
        self.last_phase_tick = now
        if self.underMouse() and not self.c.reduced_motion:
            self.hover_phase += elapsed * 40
        phase = getattr(self.c, "motion_time", 0) * 20 + (self.hover_phase if not self.c.reduced_motion else 0)
        p.setPen(QPen(tint(self.c.primary, 48), 5))
        p.drawEllipse(QRectF(6, 6, 33, 33))
        p.setPen(QPen(self.c.primary, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(6, 6, 33, 33), int(phase * 16), 245 * 16)
        p.setPen(QPen(self.c.secondary, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(13, 13, 19, 19), int((-phase + 130) * 16), 220 * 16)


class TransportButton(QPushButton):
    """Crisp vector transport icons rather than platform-dependent glyphs."""
    def __init__(self, kind, callback):
        super().__init__("▶" if kind == "play" else kind)
        self.kind = kind
        self.setFixedSize(48 if kind == "play" else 36, 48 if kind == "play" else 36)
        self.clicked.connect(callback)
        self.setAccessibleName({"play": "Play or pause", "previous": "Previous track", "next": "Next track"}[kind])
        self.setToolTip(self.accessibleName())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        primary = self.kind == "play"
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e4dafa") if primary else QColor("#34394a" if self.underMouse() else "#222734"))
        if primary and self.underMouse():
            p.setBrush(QColor("#f0eaff"))
        p.drawEllipse(box)
        ink = QColor("#222334" if primary else "#d5dae6")
        if not self.isEnabled():
            ink.setAlpha(70)
        p.setBrush(ink)
        x, y = self.width() / 2, self.height() / 2
        if primary and self.text() == "Ⅱ":
            p.drawRoundedRect(QRectF(x - 6, y - 7, 4, 14), 1, 1)
            p.drawRoundedRect(QRectF(x + 2, y - 7, 4, 14), 1, 1)
        else:
            direction = -1 if self.kind == "previous" else 1
            size = 8 if primary else 5
            path = QPainterPath(QPointF(x - direction * size * .65, y - size))
            path.lineTo(x + direction * size, y)
            path.lineTo(x - direction * size * .65, y + size)
            path.closeSubpath()
            p.drawPath(path)
            if not primary:
                p.drawRoundedRect(QRectF(x + direction * 6 - 1, y - 5, 2, 10), .7, .7)


class ModeTile(QAbstractButton):
    def __init__(self, controller, setting, spec):
        super().__init__()
        self.c, self.setting = controller, setting
        self.mode_id, self.title, self.description = spec
        self.hover_phase = 0.0
        self.last_phase_tick = time.monotonic()
        self.preview_cache = QPixmap()
        self.preview_cache_key = None
        self.preview_cache_at = 0.
        self.setFixedHeight(82)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCheckable(True)
        self.setToolTip(self.description)
        self.setAccessibleName(f"{self.title}: {self.description}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: controller.set(setting, self.mode_id))
        controller.settingChanged.connect(self.sync)
        self.sync()

    def sync(self):
        self.setChecked(getattr(self.c, self.setting) == self.mode_id)
        self.update()

    def keyPressEvent(self, event):
        direction = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -2, Qt.Key.Key_Down: 2}.get(event.key())
        if direction is not None:
            siblings = [tile for tile in self.parentWidget().findChildren(ModeTile) if tile.setting == self.setting]
            index = siblings.index(self)
            siblings[(index + direction) % len(siblings)].setFocus(Qt.FocusReason.TabFocusReason)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        selected = self.isChecked()
        p.setPen(QPen(tint(self.c.primary, 150) if selected else QColor("#464b60" if self.underMouse() else "#323745"), 1.2))
        p.setBrush(QColor("#2a2b3e" if selected else "#1e2330" if self.underMouse() else "#1a1e28"))
        p.drawRoundedRect(box, 12, 12)
        preview = QRectF(9, 7, self.width() - 18, 45)
        now = time.monotonic()
        elapsed = max(0, min(.08, now - self.last_phase_tick))
        self.last_phase_tick = now
        if self.underMouse() and not self.c.reduced_motion:
            self.hover_phase += elapsed
        phase = self.c.motion_time + (self.hover_phase if not self.c.reduced_motion else 0)
        if self.setting == "halo_mode":
            dpr = self.devicePixelRatioF()
            a, b = getattr(self.c, "halo_primary", self.c.primary), getattr(self.c, "halo_secondary", self.c.secondary)
            cache_key = (preview.width(), preview.height(), dpr, a.rgba(), b.rgba(), self.mode_id,
                         self.c.intensity, getattr(self.c, "rim_width", 3), getattr(self.c, "glow_width", 40),
                         getattr(self.c, "glow_opacity", 65), getattr(self.c, "primary_brightness", 100),
                         getattr(self.c, "secondary_brightness", 100), getattr(self.c, "color_mix", 60),
                         self.c.motion_speed, self.c.reduced_motion, getattr(self.c, "halo_animation", "flow"))
            # Small previews run at 30 Hz so the full desktop light gets the frame budget.
            if cache_key != self.preview_cache_key or now - self.preview_cache_at >= 1 / 30:
                self.preview_cache_key, self.preview_cache_at = cache_key, now
                self.preview_cache = QPixmap(max(1, round(preview.width() * dpr)), max(1, round(preview.height() * dpr)))
                self.preview_cache.setDevicePixelRatio(dpr)
                self.preview_cache.fill(Qt.GlobalColor.transparent)
                cached = QPainter(self.preview_cache)
                current_phase = getattr(self.c, "motion_phase", self.c.motion_time * self.c.motion_speed / 45 / 26.28)
                if not self.c.reduced_motion:
                    current_phase += self.hover_phase * self.c.motion_speed / 45 / 26.28
                paint_halo_preview(cached, QRectF(0, 0, preview.width(), preview.height()), self.c,
                                   self.mode_id, motion_phase=current_phase)
                cached.end()
            p.drawPixmap(preview.topLeft(), self.preview_cache)
        elif self.setting == "lyric_style":
            p.save()
            p.setClipRect(preview)
            center = preview.center()
            p.setPen(tint(self.c.secondary, 120))
            p.setFont(font(6))
            if self.mode_id == "ship":
                p.drawText(QRectF(preview.x(), preview.top(), preview.width(), 13), Qt.AlignmentFlag.AlignCenter, "Let the room fall quiet")
                p.setFont(font(9))
                p.setPen(self.c.primary)
                p.drawText(QRectF(preview.x(), center.y() - 10, preview.width(), 20), Qt.AlignmentFlag.AlignCenter, "Feel every word")
                p.setFont(font(6))
                p.setPen(tint(self.c.secondary, 120))
                p.drawText(QRectF(preview.x(), preview.bottom() - 13, preview.width(), 13), Qt.AlignmentFlag.AlignCenter, "Let the colours find their way")
            else:
                wobble = 1.5 * math.sin(phase * 1.6) if not self.c.reduced_motion else 0
                if self.mode_id == "fisheye_visual":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(tint(self.c.secondary, 65))
                    p.drawRoundedRect(QRectF(center.x() - 33, center.y() - 10, 66, 22), 1, 1)
                p.setPen(self.c.primary)
                f = font(17 if self.mode_id == "visual" else 14)
                f.setItalic(True)
                f.setBold(True)
                p.setFont(f)
                p.drawText(QRectF(preview.x(), center.y() - 15 + wobble, preview.width(), 32), Qt.AlignmentFlag.AlignCenter,
                           "alive" if self.mode_id == "visual" else "every")
                if self.mode_id != "visual":
                    p.setFont(font(7))
                    p.setPen(tint(self.c.secondary, 160))
                    p.drawText(QRectF(preview.x(), preview.top(), preview.width(), 12), Qt.AlignmentFlag.AlignCenter, "feel")
                    p.drawText(QRectF(preview.x(), preview.bottom() - 12, preview.width(), 12), Qt.AlignmentFlag.AlignCenter, "word")
            p.restore()
        else:
            p.setPen(Qt.PenStyle.NoPen)
            g = QLinearGradient(preview.topLeft(), preview.bottomRight())
            g.setColorAt(0, tint(self.c.primary, 32))
            g.setColorAt(1, tint(self.c.secondary, 4))
            p.setBrush(g)
            p.drawRoundedRect(preview, 6, 6)
            if self.mode_id in ("studio", "orbit"):
                cover = QRectF(preview.left() + 10, preview.top() + 11, 32, 32)
                p.setBrush(tint(self.c.primary, 110))
                if self.mode_id == "orbit":
                    cover.moveCenter(preview.center())
                    p.drawEllipse(cover)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(tint(self.c.secondary, 100), 1))
                    p.drawEllipse(cover.adjusted(-7, -7, 7, 7))
                    p.drawEllipse(cover.adjusted(-11, -4, 11, 4))
                else:
                    p.drawRoundedRect(cover, 5, 5)
            if self.mode_id != "orbit":
                start = preview.left() + (55 if self.mode_id == "studio" else 24)
                end = preview.right() - 17
                p.setPen(QPen(tint(self.c.primary, 180), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(start, preview.center().y()), QPointF(end, preview.center().y()))
                p.setPen(QPen(tint(self.c.secondary, 65), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(start + 5, preview.center().y() - 12), QPointF(end - 8, preview.center().y() - 12))
                p.drawLine(QPointF(start + 5, preview.center().y() + 12), QPointF(end - 8, preview.center().y() + 12))
        p.setPen(QColor("#f0eef6" if selected else "#bec3d3"))
        title_width = max(20, self.width() - (31 if selected else 20))
        face = font(9)
        if QFontMetrics(face).horizontalAdvance(self.title) > title_width:
            face = font(8)
        p.setFont(face)
        fitted_title = QFontMetrics(face).elidedText(self.title, Qt.TextElideMode.ElideRight, title_width)
        p.drawText(QRectF(10, 55, title_width, 21), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fitted_title)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.c.primary)
            p.drawEllipse(QPointF(self.width() - 12, 65), 2.5, 2.5)
        if self.hasFocus():
            p.setPen(QPen(QColor("#e3dafa"), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(3, 3, -3, -3), 9, 9)


def selector(controller, field, specs, accessible):
    combo = QComboBox()
    combo.setAccessibleName(accessible)
    for key, title, description in specs:
        combo.addItem(title, key)
        combo.setItemData(combo.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
    combo.setCurrentIndex(max(0, combo.findData(getattr(controller, field))))
    combo.currentIndexChanged.connect(lambda index: controller.set(field, combo.itemData(index)) if index >= 0 else None)
    def sync():
        with QSignalBlocker(combo):
            combo.setCurrentIndex(max(0, combo.findData(getattr(controller, field))))
    controller.settingChanged.connect(sync)
    return combo


def build_main(window, c):
    window.resize(1140, 835)
    window.setMinimumSize(960, 660)
    root = QVBoxLayout(window)
    root.setContentsMargins(28, 20, 28, 18)
    root.setSpacing(18)
    header = QHBoxLayout()
    window.mark = HaloMark(c)
    header.addWidget(window.mark)
    header.addSpacing(8)
    header.addWidget(text_label("halo", "brand"))
    header.addSpacing(18)
    header.addWidget(text_label("MAKE YOUR MUSIC MOVE", "eyebrow"))
    header.addStretch()
    window.badge = text_label("○  Waiting for Spotify", "badge")
    header.addWidget(window.badge)
    root.addLayout(header)

    hero = QFrame()
    hero.setObjectName("card")
    hero.setMinimumHeight(151)
    hero.setMaximumHeight(177)
    row = QHBoxLayout(hero)
    row.setContentsMargins(20, 18, 24, 18)
    row.setSpacing(20)
    window.main_art = Artwork(c, 100)
    row.addWidget(window.main_art)
    info = QVBoxLayout()
    info.setSpacing(5)
    info.addWidget(text_label("NOW PLAYING", "eyebrow"))
    window.title = FittedTitle("Waiting for Spotify")
    info.addWidget(window.title)
    window.artist = ElidedLabel("Open Spotify and play something you love.")
    window.artist.setMaximumHeight(36)
    info.addWidget(window.artist)
    info.addStretch()
    row.addLayout(info, 1)
    player = QVBoxLayout()
    transport = QHBoxLayout()
    transport.setSpacing(10)
    window.previous = TransportButton("previous", lambda: c.transport("previous"))
    window.play = TransportButton("play", lambda: c.transport("toggle"))
    window.next = TransportButton("next", lambda: c.transport("next"))
    for item in (window.previous, window.play, window.next):
        transport.addWidget(item)
    player.addLayout(transport)
    window.time_label = text_label("0:00 / 0:00")
    window.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    player.addWidget(window.time_label)
    row.addLayout(player)
    root.addWidget(hero)

    columns = QHBoxLayout()
    columns.setSpacing(18)
    left = QVBoxLayout()
    left.setSpacing(14)
    lyric_panel = QFrame()
    lyric_panel.setObjectName("card")
    lyric = QVBoxLayout(lyric_panel)
    lyric.setContentsMargins(23, 19, 23, 19)
    heading = QHBoxLayout()
    heading.addWidget(text_label("THE WORDS", "eyebrow"))
    heading.addStretch()
    window.lyrics_badge = text_label("Waiting for a song")
    heading.addWidget(window.lyrics_badge)
    window.retry_button = action("Retry", c.retry_lyrics, "ghost")
    window.retry_button.setAccessibleName("Retry lyrics")
    heading.addWidget(window.retry_button)
    lyric.addLayout(heading)
    window.canvas = LyricCanvas(c)
    lyric.addWidget(window.canvas, 1)
    window.progress = QSlider(Qt.Orientation.Horizontal)
    window.progress.setRange(0, 1000)
    window.progress.setAccessibleName("Track position")
    window.progress.sliderReleased.connect(lambda: c.seek(window.progress.value() / 1000 * c.track.duration))
    lyric.addWidget(window.progress)
    bottom = QHBoxLayout()
    bottom.addStretch()
    window.style_select = selector(c, "lyric_style", LYRIC_STYLES, "Lyric animation style")
    window.style_select.setFixedWidth(152)
    bottom.addWidget(window.style_select)
    lyric.addLayout(bottom)
    left.addWidget(lyric_panel, 1)
    actions = QHBoxLayout()
    actions.addWidget(action("Enter immersive view   ↗", window.fullscreen, "primary"), 1)
    actions.addWidget(action("Lyrics only", lambda: (c.set("immersive_mode", "lyrics"), window.fullscreen())))
    actions.addWidget(action("Import .lrc", window.import_lrc))
    left.addLayout(actions)
    columns.addLayout(left, 1)

    controls = QFrame()
    controls.setObjectName("settingsCard")
    controls.setFixedWidth(333)
    settings = QVBoxLayout(controls)
    settings.setContentsMargins(17, 18, 17, 13)
    settings.setSpacing(13)
    settings.addWidget(text_label("Make it yours", "panelTitle"))
    tabrow = QHBoxLayout()
    tabrow.setSpacing(3)
    window.settings_pages = QStackedWidget()
    tabs = QButtonGroup(controls)
    window.settings_tabs = tabs
    for index, title in enumerate(("Light", "Lyrics", "Scenes")):
        tab = QPushButton(title)
        tab.setObjectName("sectionTab")
        tab.setCheckable(True)
        tab.setChecked(index == 0)
        tabs.addButton(tab, index)
        tabrow.addWidget(tab, 1)
    tabs.idClicked.connect(window.settings_pages.setCurrentIndex)
    window.settings_pages.currentChanged.connect(lambda index: tabs.button(index).setChecked(True) if tabs.button(index) else None)
    settings.addLayout(tabrow)
    window.mode_tiles = []
    window.setting_controls = {}
    window.setting_sliders = {}

    def page():
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.viewport().setObjectName("settingsViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("settingsPage")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(1, 2, 8, 8)
        layout.setSpacing(12)
        scroll.setWidget(content)
        window.settings_pages.addWidget(scroll)
        return layout

    def modes(layout, field, specs):
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, spec in enumerate(specs):
            tile = ModeTile(c, field, spec)
            window.mode_tiles.append(tile)
            grid.addWidget(tile, index // 2, index % 2)
        layout.addLayout(grid)
        description = text_label("")
        description.setWordWrap(True)
        description.setMinimumHeight(29)
        def describe():
            description.setText(next((item[2] for item in specs if item[0] == getattr(c, field)), ""))
        c.settingChanged.connect(describe)
        describe()
        layout.addWidget(description)

    def add_slider(layout, title, name, low, high, suffix):
        window.slider(layout, title, name, low, high, suffix)
        slider = layout.itemAt(layout.count() - 1).widget()
        value_label = layout.itemAt(layout.count() - 2).layout().itemAt(2).widget()
        window.setting_sliders[name] = (slider, value_label, suffix)

    light = page()
    window.glow = window.checkbox("Screen-edge glow", "glow", light, "Luminous, click-through lighting on every monitor.")
    window.reactive = window.checkbox("React to audio", "reactive", light, "Responds to the sound playing through your speakers. Audio stays on this PC.")
    light.addWidget(text_label("HALO MOTION", "eyebrow"))
    modes(light, "halo_mode", HALO_MODES)
    window.fine_tune_toggle = QPushButton("Fine tune   +")
    window.fine_tune_toggle.setObjectName("ghost")
    window.fine_tune_toggle.setCheckable(True)
    window.fine_tune_toggle.setAccessibleName("Expand light fine tuning")
    light.addWidget(window.fine_tune_toggle)
    window.light_controls = LightControls(c)
    window.fine_tune_panel = window.light_controls
    window.palette_select = window.light_controls.palette_select
    for name, slider in window.light_controls.sliders.items():
        window.setting_sliders[name] = (slider, window.light_controls.value_labels[name], window.light_controls.suffixes[name])
    light.addWidget(window.fine_tune_panel)
    window.fine_tune_panel.hide()
    def show_fine_tune_start():
        # Keep the fine-tuning tabs at the top on compact windows. Asking Qt
        # to fit the whole panel would centre it and scroll its tabs away.
        scroll = window.settings_pages.widget(0)
        scroll.verticalScrollBar().setValue(window.fine_tune_toggle.y())
    def expand_fine_tune(expanded):
        window.fine_tune_panel.setVisible(expanded)
        window.fine_tune_toggle.setText("Fine tune   −" if expanded else "Fine tune   +")
        window.fine_tune_toggle.setAccessibleName("Collapse light fine tuning" if expanded else "Expand light fine tuning")
        if expanded:
            QTimer.singleShot(0, show_fine_tune_start)
    window.fine_tune_toggle.toggled.connect(expand_fine_tune)
    light.addStretch()

    lyrics = page()
    lyrics.addWidget(text_label("LYRIC CHOREOGRAPHY", "eyebrow"))
    modes(lyrics, "lyric_style", LYRIC_STYLES)
    floating = QHBoxLayout()
    window.floating = window.checkbox("Floating lyrics", "floating", floating, "Animated lyrics above your desktop when Halo is minimized.")
    floating.addStretch()
    floating.addWidget(action("Position…", window.open_position_settings, "ghost"))
    lyrics.addLayout(floating)
    add_slider(lyrics, "Lyrics timing", "offset", -3000, 3000, " ms")
    motion = window.checkbox("Reduce motion", "reduced_motion", lyrics, "Keep clear, steady lyrics and a calm halo without motion effects.")
    window.reduced_motion = motion
    timing_hint = text_label("Word animation follows estimated timing between synced lyric lines.\n\nPositive timing brings lyrics earlier; negative timing delays them.")
    timing_hint.setWordWrap(True)
    lyrics.addWidget(timing_hint)
    lyrics.addStretch()

    scenes = page()
    scenes.addWidget(text_label("IMMERSIVE SCENES", "eyebrow"))
    modes(scenes, "immersive_mode", IMMERSIVE_SCENES)
    scenes.addWidget(action("Open selected scene   ↗", window.fullscreen, "primary"))
    hint = text_label("Switch scenes and lyric styles inside immersive view.")
    hint.setWordWrap(True)
    scenes.addWidget(hint)
    scenes.addStretch()
    settings.addWidget(window.settings_pages, 1)
    columns.addWidget(controls)
    root.addLayout(columns, 1)
    footer = QHBoxLayout()
    window.demo_button = action("Try the visual demo", lambda: c.set_demo(not c.demo), "ghost")
    footer.addWidget(window.demo_button)
    footer.addStretch()
    window.footer = ElidedLabel("Spotify desktop · close to keep Halo in the tray")
    window.footer.setStyleSheet("font-size: 10px; color: #777f96;")
    footer.addWidget(window.footer)
    root.addLayout(footer)

    def sync_controls():
        for field, control in window.setting_controls.items():
            with QSignalBlocker(control):
                control.setChecked(getattr(c, field))
        with QSignalBlocker(window.palette_select):
            window.palette_select.setCurrentText(c.palette)
        for field, (slider, value_label, suffix) in window.setting_sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(getattr(c, field))
            value_label.setText(str(getattr(c, field)) + suffix)
    c.settingChanged.connect(sync_controls)
