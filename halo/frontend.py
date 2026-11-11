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
from .gallery import (INK, INK_SOFT, CARD, FOCUS, HandsetButton, ink_accent, paint_shadow, paint_focus,
                      face)


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
        accent = ink_accent(getattr(self.c, "halo_primary", self.c.primary), target=3.2)
        p.setPen(QPen(tint(INK, 30), 5))
        p.drawEllipse(QRectF(6, 6, 33, 33))
        p.setPen(QPen(accent, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(6, 6, 33, 33), int(phase * 16), 245 * 16)
        p.setPen(QPen(INK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(13, 13, 19, 19), int((-phase + 130) * 16), 220 * 16)


class TransportButton(HandsetButton):
    """Previous, play and next on the audio-guide handset."""
    def __init__(self, kind, callback, controller=None):
        super().__init__(kind, callback, controller, hint={"previous": "Ctrl+Left", "next": "Ctrl+Right", "play": "Space"}[kind])


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
        box = QRectF(self.rect()).adjusted(2, 2, -2, -4)
        selected = self.isChecked()
        hovered = self.underMouse() and self.isEnabled()
        if self.isDown():
            box.translate(0, 1)
        elif selected:
            box.translate(0, -1)
            paint_shadow(p, box, 12, 9, .24, 3)
        else:
            paint_shadow(p, box, 12, 6 if hovered else 4, .2 if hovered else .14, 2)
        p.setPen(QPen(INK, 2) if selected else Qt.PenStyle.NoPen)
        p.setBrush(CARD)
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
        # Every preview is a small dark screen hung inside the white card.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#11171a"))
        p.drawRoundedRect(preview, 8, 8)
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
        p.setPen(QColor(INK if selected else INK_SOFT))
        title_width = max(20, self.width() - (31 if selected else 20))
        title_face = font(9, QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        if QFontMetrics(title_face).horizontalAdvance(self.title) > title_width:
            title_face = font(8, QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        p.setFont(title_face)
        fitted_title = QFontMetrics(title_face).elidedText(self.title, Qt.TextElideMode.ElideRight, title_width)
        p.drawText(QRectF(10, preview.bottom() + 3, title_width, 21), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fitted_title)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(INK)
            p.drawEllipse(QPointF(self.width() - 13, preview.bottom() + 13), 3.5, 3.5)
        if self.hasFocus():
            paint_focus(p, box, 12)


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
