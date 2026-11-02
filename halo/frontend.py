"""Halo's native control room: live previews and a focused listening surface."""
import time
from PySide6.QtCore import Qt, QRectF, QPointF, QSignalBlocker, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QAbstractButton,
    QVBoxLayout, QHBoxLayout, QComboBox, QSlider, QSizePolicy, QStackedWidget,
    QScrollArea, QSizeGrip, QApplication)
from .widgets import Artwork, LyricCanvas, font, tint
from .glow import paint_halo_preview
from .lyric_rendering import LYRIC_STYLES
from .mode_library import SceneCard, StyleCard
from .mode_catalog import available_specs
from .glass import APP_STYLE, GlassPanel, GlassButton, icon, draw_icon, colour


STYLE = APP_STYLE


def text_label(text, name="muted"):
    result = QLabel(text)
    result.setObjectName(name)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


def action(text, callback, name=None):
    result = GlassButton(text)
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
        p.scale(self.width() / 45., self.height() / 45.)
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


class TransportButton(GlassButton):
    """Crisp vector transport icons rather than platform-dependent glyphs."""
    def __init__(self, kind, callback, controller=None):
        super().__init__("▶" if kind == "play" else kind, controller=controller)
        self.kind = kind
        self.setFixedSize(42 if kind == "play" else 32, 42 if kind == "play" else 32)
        self.clicked.connect(callback)
        self.setAccessibleName({"play": "Play or pause", "previous": "Previous track", "next": "Next track"}[kind])
        self.setToolTip(self.accessibleName())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        primary = self.kind == "play"
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor.fromRgbF(.83 + self._hover * .07, .79 + self._hover * .08, .97)
                   if primary else QColor(223, 211, 255, round(self._hover * 20)))
        if self.isDown():
            p.setBrush(QColor("#b3a0df") if primary else QColor(223, 211, 255, 30))
        p.drawEllipse(box)
        ink = QColor("#221c30" if primary else "#b9b1c9")
        if not self.isEnabled():
            ink.setAlpha(70)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#c4b4f8"), 1))
            p.drawEllipse(box.adjusted(2, 2, -2, -2))
        p.setPen(Qt.PenStyle.NoPen)
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


LYRIC_CARD_PREVIEW, ROOM_CARD_PREVIEW = 45, 140


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
        self.live_card = None
        self.preview_height = ROOM_CARD_PREVIEW if setting == "immersive_mode" else LYRIC_CARD_PREVIEW
        self.setFixedHeight(self.preview_height + 37)
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
        preview = QRectF(9, 7, self.width() - 18, self.preview_height)
        if self.setting == "immersive_mode":
            preview.setWidth(min(preview.width(), self.preview_height * 1.6))
            preview.moveLeft((self.width() - preview.width()) / 2)
        now = time.monotonic()
        elapsed = max(0, min(.08, now - self.last_phase_tick))
        self.last_phase_tick = now
        if self.underMouse() and not self.c.reduced_motion:
            self.hover_phase += elapsed
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
        else:
            dpr = self.devicePixelRatioF()
            cache_key = (preview.width(), preview.height(), dpr, self.c.primary.rgba(), self.c.secondary.rgba(),
                         self.c.lyric_style, self.c.reduced_motion)
            # All of a page's cards share 30 Hz, and reduced motion redraws only when the look changes.
            if cache_key != self.preview_cache_key or (not self.c.reduced_motion and now - self.preview_cache_at >= 1 / 30):
                self.preview_cache_key, self.preview_cache_at = cache_key, now
                self.preview_cache = QPixmap(max(1, round(preview.width() * dpr)), max(1, round(preview.height() * dpr)))
                self.preview_cache.setDevicePixelRatio(dpr)
                self.preview_cache.fill(Qt.GlobalColor.transparent)
                cached = QPainter(self.preview_cache)
                cached.setRenderHint(QPainter.RenderHint.Antialiasing)
                cached.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                if self.live_card is None:
                    card = SceneCard if self.setting == "immersive_mode" else StyleCard
                    self.live_card = card(self.c, self.mode_id, self)
                self.live_card.paint(cached, QRectF(0, 0, preview.width(), preview.height()))
                cached.end()
            p.drawPixmap(preview.topLeft(), self.preview_cache)
        p.setPen(QColor("#f0eef6" if selected else "#bec3d3"))
        title_width = max(20, self.width() - (31 if selected else 20))
        face = font(9)
        if QFontMetrics(face).horizontalAdvance(self.title) > title_width:
            face = font(8)
        p.setFont(face)
        fitted_title = QFontMetrics(face).elidedText(self.title, Qt.TextElideMode.ElideRight, title_width)
        p.drawText(QRectF(10, preview.bottom() + 3, title_width, 21), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fitted_title)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.c.primary)
            p.drawEllipse(QPointF(self.width() - 12, preview.bottom() + 13), 2.5, 2.5)
        if self.hasFocus():
            p.setPen(QPen(QColor("#e3dafa"), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(3, 3, -3, -3), 9, 9)


def selector(controller, field, specs, accessible):
    combo = QComboBox()
    combo.setAccessibleName(accessible)
    def populate():
        with QSignalBlocker(combo):
            combo.clear()
            for key, title, description in available_specs(controller, field, specs):
                combo.addItem(title, key)
                combo.setItemData(combo.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
            combo.setCurrentIndex(max(0, combo.findData(getattr(controller, field))))
    populate()
    combo.currentIndexChanged.connect(lambda index: controller.set(field, combo.itemData(index)) if index >= 0 else None)
    def sync():
        with QSignalBlocker(combo):
            combo.setCurrentIndex(max(0, combo.findData(getattr(controller, field))))
    controller.settingChanged.connect(sync)
    if hasattr(controller, "modeLibraryChanged"):
        controller.modeLibraryChanged.connect(populate)
    return combo


def build_main(window, c):
    from .shell import build_shell
    build_shell(window, c)
