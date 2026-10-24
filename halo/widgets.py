import colorsys
from collections import OrderedDict
import math
import time
from PySide6.QtCore import Qt, QEvent, QRectF, QRect, QPointF
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QLinearGradient,
                          QRadialGradient, QPainterPath, QPixmap)
from PySide6.QtWidgets import QWidget
from .models import floating_geometry
from .glow import paint_edge_glow
from .palette import artwork_colours
from .taskbar import allow_taskbar_reveal
from .extra_lyrics import LINE_BASED_STYLES, paint_lyric_mode
from .lyric_rendering import (LYRIC_STYLES, WordTimeline, TypeCache, clamp, smooth,
                              spring, alpha, SYMBOLS, symbol_kind, line_symbol_kind, canonical_lyric_style)

WHITE = QColor("#f1f5ef")


def font(size, weight=QFont.Weight.Normal):
    result = QFont("Segoe UI", size)
    result.setWeight(weight)
    return result


def tint(color, alpha):
    result = QColor(color)
    result.setAlpha(max(0, min(255, round(alpha))))
    return result


def artwork_palette(data):
    return artwork_colours(data)


class Artwork(QWidget):
    def __init__(self, controller, size=132):
        super().__init__()
        self.controller = controller
        self.setFixedSize(size, size)
        self.pixmap = QPixmap()
        controller.trackChanged.connect(self.track_changed)

    def track_changed(self):
        self.pixmap = QPixmap()
        if self.controller.track.artwork:
            self.pixmap.loadFromData(self.controller.track.artwork)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(box, 14, 14)
        p.setClipPath(path)
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        else:
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#c8d7b1"))
            gradient.setColorAt(.5, QColor("#6c9d8d"))
            gradient.setColorAt(1, QColor("#233e3e"))
            p.fillRect(box, gradient)
            for i in range(8):
                p.setPen(QPen(QColor(225, 241, 209, 35), 1))
                r = self.width() * (.16 + i * .055)
                p.drawEllipse(QRectF(self.width() * .62 - r, self.height() * .6 - r, r * 2, r * 2))
            p.setPen(QColor("#eaf3d8"))
            p.setFont(font(10, QFont.Weight.DemiBold))
            p.drawText(box.adjusted(13, 10, -10, -12), Qt.AlignmentFlag.AlignTop, "H / 01")
            if self.width() >= 112:
                p.setFont(font(8))
                p.drawText(box.adjusted(13, 10, -10, -12), Qt.AlignmentFlag.AlignBottom, "SOUND IN COLOUR")


class LyricCanvas(QWidget):
    """Native lyric choreographies sharing one playback-aware animation clock."""
    def __init__(self, controller, mode="preview"):
        super().__init__()
        self.controller = controller
        self.mode = mode
        self.scene_mode = "studio"
        self.alignment = "left" if mode == "immersive" else "center"
        self.visual_index = -1.0
        self.last_generation = -1
        self.fitted_sizes = {}  # Retained for callers of earlier Halo versions.
        self.type_cache = TypeCache()
        self.timeline = None
        self._timeline_key = None
        self._last_motion = None
        self._last_position = None
        self._word_visual = -1.0
        self._word_velocity = self._line_velocity = 0.0
        self._active_word = -1
        self._previous_word = -1
        self._transition_at = 0.0
        self._line_art_clock = None
        self._line_art_motion = 0.0
        self._line_art_key = None
        self._line_text_rasters = OrderedDict()
        self._line_text_pixels = 0
        self._hit_rows = []
        self.setMinimumHeight(110)
        self.setAccessibleName("Animated lyrics")
        self.setToolTip("")
        if mode != "floating":
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_alignment(self, alignment):
        self.alignment = "left" if alignment == "left" else "center"
        self.update()

    def _clock(self):
        c = self.controller
        if hasattr(c, "motion_time"):
            return float(c.motion_time)
        # Backward-compatible standalone canvases still freeze when paused.
        if c.track.playing:
            return time.monotonic()
        return self._last_motion or 0.0

    def _advance(self, index, word_index, position, motion):
        c = self.controller
        elapsed = max(0.0, motion - self._last_motion) if self._last_motion is not None else 0.0
        jumped = (self._last_position is not None and
                  (position < self._last_position - .15 or
                   position - self._last_position > max(.85, elapsed * 2 + .35)))
        # Word-heavy cues must not snap Ship's whole-line scroll into place.
        whole_line = canonical_lyric_style(getattr(c, "lyric_style", "fisheye_visual")) in ({"ship_visual"} | LINE_BASED_STYLES)
        word_jump = (not whole_line
                     and abs(word_index - self._word_visual) > 8)
        reset = (self.last_generation != c.generation or jumped or self._last_motion is None
                 or abs(index - self.visual_index) > 3 or word_jump)
        reduced = bool(getattr(c, "reduced_motion", False))
        if reset or reduced:
            self.visual_index = float(index)
            self._word_visual = float(word_index)
            self._word_velocity = self._line_velocity = 0.0
        elif c.track.playing:
            self.visual_index, self._line_velocity = spring(self.visual_index, self._line_velocity, index, elapsed, 10)
            frequency = 15
            if not whole_line:
                span = self._timed_word_span(index, word_index)
                if span is not None and span < .26:
                    frequency = min(240, 6 / max(.001, span))
            self._word_visual, self._word_velocity = spring(self._word_visual, self._word_velocity, word_index, elapsed, frequency)
        if word_index != self._active_word:
            self._previous_word = self._active_word if not reset else -1
            self._active_word = word_index
            self._transition_at = motion - .26 if reset or reduced or not c.track.playing else motion
        self.last_generation = c.generation
        self._last_motion = motion
        self._last_position = position
        span = self._timed_word_span(index, word_index)
        if not (reduced or reset) and span is not None:
            word = self.timeline.display_words[word_index]
            # A fixed 260 ms crossfade can hide every word in a fast phrase.
            # Source-timed words settle by the interval's midpoint, and use
            # playback position so a late repaint catches up immediately.
            if span <= 0 or not c.track.playing:
                return 1.0
            return smooth((position - word.begin) / min(.26, span / 2))
        return 1.0 if reduced or reset else smooth((motion - self._transition_at) / .26)

    def _timed_word_span(self, index, word_index):
        if self.timeline is None or index not in self.timeline.timed_lines or word_index < 0:
            return None
        word = self.timeline.display_words[word_index]
        finish = word.finish
        if word_index + 1 < len(self.timeline.display_words):
            next_word = self.timeline.display_words[word_index + 1]
            if next_word.line == word.line:
                finish = min(finish, next_word.begin)
        return finish - word.begin

    def _shape(self, text, width, height, pixels, alignment=None):
        return self.type_cache.get(text, width, height, pixels, alignment=alignment or self.alignment)

    def _word_shape(self, text, width, height, pixels):
        return self.type_cache.get(text, width, height, pixels, alignment="center", expressive=True)

    def _cutout(self, p, x, y, width, height, opacity, motion):
        """A skewed colour strip, reminiscent of the supplied kinetic-type demo."""
        p.save()
        p.translate(x, y)
        p.rotate(-2 if getattr(self.controller, "reduced_motion", False) else -2 + math.sin(motion * .8) * 1.8)
        path = QPainterPath()
        path.moveTo(-width / 2 - 7, -height / 2)
        path.lineTo(width / 2 + 9, -height / 2 - 3)
        path.lineTo(width / 2 + 4, height / 2)
        path.lineTo(-width / 2 - 2, height / 2 + 2)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(self.controller.secondary, opacity * .25))
        p.drawPath(path)
        p.restore()

    def _text(self, p, shape, x, y, color, opacity=1, scale=1, angle=0):
        if (self.mode == "floating" and canonical_lyric_style(getattr(self.controller, "lyric_style", "")) == "ship_visual"
                and self._line_text(p, shape, x, y, color, opacity, scale)):
            return
        p.save()
        p.translate(x, y)
        p.rotate(angle)
        p.scale(scale, scale)
        p.translate(-shape.bounds.center().x(), -shape.bounds.center().y())
        path = shape.path
        if self.mode == "floating":
            p.setPen(QPen(alpha(QColor("#000000"), opacity * .8), 3.8 / scale,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(alpha(QColor("#000000"), opacity * .5))
            p.translate(0, 1.5 / scale)
            p.drawPath(path)
            p.translate(0, -1.5 / scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(color, opacity))
        p.drawPath(path)
        p.restore()

    def _line_text(self, p, shape, x, y, color, opacity, scale):
        """Rasterize floating outlines once, then move the whole cue cheaply.

        Retain the shape with its raster, so recycled object IDs cannot collide.
        Twelve entries and two million physical pixels bound memory at 8 MiB.
        """
        dpr = self.devicePixelRatioF()
        key = (id(shape), color.rgba(), dpr)
        cached = self._line_text_rasters.get(key)
        if cached is None:
            padding = 7
            width = max(1, math.ceil((shape.bounds.width() + padding * 2) * dpr))
            height = max(1, math.ceil((shape.bounds.height() + padding * 2) * dpr))
            pixels = width * height
            if pixels > 2_000_000:
                return False
            raster = QPixmap(width, height)
            raster.setDevicePixelRatio(dpr)
            raster.fill(Qt.GlobalColor.transparent)
            ink = QPainter(raster)
            ink.setRenderHint(QPainter.RenderHint.Antialiasing)
            ink.translate(padding - shape.bounds.left(), padding - shape.bounds.top())
            ink.setPen(QPen(alpha(QColor("#000000"), .8), 3.8,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            ink.setBrush(alpha(QColor("#000000"), .5))
            ink.translate(0, 1.5)
            ink.drawPath(shape.path)
            ink.translate(0, -1.5)
            ink.setPen(Qt.PenStyle.NoPen)
            ink.setBrush(color)
            ink.drawPath(shape.path)
            ink.end()
            cached = (shape, raster, pixels, padding)
            self._line_text_rasters[key] = cached
            self._line_text_pixels += pixels
            while len(self._line_text_rasters) > 12 or self._line_text_pixels > 2_000_000:
                _, removed = self._line_text_rasters.popitem(last=False)
                self._line_text_pixels -= removed[2]
        else:
            self._line_text_rasters.move_to_end(key)
        _, raster, _, padding = cached
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(opacity)
        p.translate(x, y)
        p.scale(scale, scale)
        p.drawPixmap(QPointF(-shape.bounds.width() / 2 - padding,
                            -shape.bounds.height() / 2 - padding), raster)
        p.restore()
        return True

    def _symbol(self, p, word, x, y, radius, opacity, motion, subdued=False):
        c = self.controller
        reduced = bool(getattr(c, "reduced_motion", False))
        p.save()
        p.translate(x, y)
        if not reduced:
            p.rotate(math.sin(motion * .62) * 7)
        p.scale(radius, radius)
        if self.mode == "floating":
            p.setPen(QPen(alpha(QColor("#000000"), opacity * .85), 4 / radius))
            p.drawPath(SYMBOLS[symbol_kind(word)])
        p.setPen(QPen(alpha(c.primary, opacity), 1.7 / radius,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(alpha(c.primary, opacity * (.055 if subdued else .11)))
        p.drawPath(SYMBOLS[symbol_kind(word)])
        p.restore()

    def _edge_opacity(self, y, height, scale=1):
        half = height * scale / 2
        available = min(y - half, self.height() - y - half)
        return smooth(available / max(12, self.height() * .13))

    def _empty(self, p):
        w, h = self.width(), self.height()
        shape = self._shape("Your music. A little more alive.", max(1, w - 44), h * .4,
                            min(30, w * .055), "center")
        self._text(p, shape, w / 2, h * .43, WHITE)

    def paintEvent(self, event):
        c = self.controller
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hit_rows = []
        if not c.lyrics.lines:
            self._empty(p)
            p.end()
            return
        position = c.position + c.offset / 1000
        lines = c.lyrics.lines
        key = (id(lines), c.generation, c.track.duration)
        if key != self._timeline_key:
            self.timeline = WordTimeline(lines, c.track.duration)
            self._timeline_key = key
            self.type_cache.clear()
            self._line_text_rasters.clear()
            self._line_text_pixels = 0
            self._last_motion = None
        style = canonical_lyric_style(getattr(c, "lyric_style", "fisheye_visual"))
        index, word_index, fraction = self.timeline.display_at(
            c.lyrics.index_at(position), position)
        motion = self._clock()
        transition = self._advance(index, word_index, position, motion)
        if paint_lyric_mode(self, p, style, index, word_index, fraction, motion, transition):
            pass
        elif style == "ship_visual":
            self._ship_visual(p, index, motion)
        elif style == "visual":
            if word_index >= 0 and self.timeline.display_words[word_index].text != "♪":
                self._visual(p, index, word_index, fraction, motion, transition)
        else:
            # Empty cues occupy a real scroll position; only their ink is
            # omitted, so context stays above/below an empty centre.
            self._fisheye(p, index, word_index, fraction, motion, True)
        p.end()

    def _instrumental(self, p, motion):
        w, h = self.width(), self.height()
        c = self.controller
        radius = min(5, max(2, w / 120))
        for i in range(3):
            breath = .55 if getattr(c, "reduced_motion", False) else .48 + .25 * math.sin(motion * 2 - i * .65)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(c.primary, breath))
            p.drawEllipse(QRectF(w / 2 + (i - 1) * radius * 4 - radius, h / 2 - radius, radius * 2, radius * 2))

    def _base_size(self):
        w, h = self.width(), self.height()
        if self.mode == "preview":
            return min(44, max(20, w / 11))
        if self.mode == "floating":
            return min(48, max(20, w / 15))
        giant = self.scene_mode in {"lyrics", "cinema", "orbit", "scene_runway"}
        return min(110 if giant else 76, max(25, min(w / (9 if giant else 11), h / 7)))

    def _ship(self, p, index):
        # Compatibility for older callers; the plain renderer is retired.
        self._ship_visual(p, index, self._clock())

    def _line_emblem(self, p, kind, x, y, radius, focus, opacity, phase):
        """An airy line illustration, never a backdrop behind the lyric text."""
        c = self.controller
        reduced = bool(getattr(c, "reduced_motion", False))
        breathe = 0.0 if reduced else math.sin(phase * .65) * .035
        p.save()
        p.translate(x, y)
        p.scale(1 + breathe * focus, 1 + breathe * focus)
        p.save()
        p.scale(radius, radius)
        if self.mode != "floating":
            # Light follows the glyph itself, with no enclosing rings or pins.
            p.setPen(QPen(alpha(c.primary, opacity * focus * .09), 5.5 / radius,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(SYMBOLS[kind])
        if self.mode == "floating":
            p.setPen(QPen(alpha(QColor("#000000"), opacity * .8), 3.4 / radius,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(SYMBOLS[kind])
        p.setPen(QPen(alpha(c.primary, opacity), max(1.15, radius * .06) / radius,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(alpha(c.primary, opacity * .035))
        p.drawPath(SYMBOLS[kind])
        p.restore()
        p.restore()

    def _ship_visual(self, p, index, motion):
        """Whole lines move as one; illustrations follow cues, never word ticks."""
        c = self.controller
        w, h = self.width(), self.height()
        # This local clock also freezes standalone canvases with external clocks.
        # A hidden window resuming cannot accumulate a large decorative jump.
        art_key = (id(c.lyrics.lines), c.generation)
        if art_key != self._line_art_key or self._line_art_clock is None:
            self._line_art_motion = 0.0
            self._line_art_key = art_key
        elif c.track.playing and not getattr(c, "reduced_motion", False):
            self._line_art_motion += clamp(motion - self._line_art_clock, 0, .1)
        self._line_art_clock = motion
        phase = self._line_art_motion
        margin = max(16, min(54, w * .055))
        size = self._base_size() * .88
        radius = min(25, max(6, size * .29))
        gutter = radius * 4.5
        width = max(1, w - margin * 2 - gutter)
        spacing = max(42, min(h * .30, size * 2.75))
        alignment = "center" if self.scene_mode in {"lyrics", "cinema", "orbit"} else self.alignment
        for i in range(max(0, index - 3), min(len(c.lyrics.lines), index + 4)):
            text = c.lyrics.lines[i].text
            if not text.strip():
                continue
            delta = i - self.visual_index
            distance = abs(delta)
            focus = math.exp(-distance * distance * 1.65)
            scale = .62 + focus * .38
            shape = self._shape(text, width * .96, spacing * .76, size, alignment)
            y = h * .5 + delta * spacing
            opacity = (max(0, 1 - distance * .39) * (.54 + .46 * focus)
                       * self._edge_opacity(y, shape.bounds.height(), scale))
            if opacity < .012:
                continue
            # Centre the composition, including its emblem, as a single object.
            emblem_radius = radius * (.58 + focus * .42)
            row_gutter = emblem_radius * 4.5
            x = ((w + row_gutter) / 2 if alignment == "center"
                 else margin + row_gutter + shape.bounds.width() * scale / 2)
            left = x - shape.bounds.width() * scale / 2
            emblem_x = left - emblem_radius * 2.6
            emblem_y = y + (shape.first_line_center - shape.bounds.center().y()) * scale
            self._line_emblem(p, line_symbol_kind(text), emblem_x, emblem_y, emblem_radius,
                              focus, opacity * (.48 + focus * .42), phase)
            # Fine, short ink flourishes sit outside the text's reading area.
            ink_focus = smooth((focus - .4) / .6)
            if ink_focus > .01 and shape.bounds.width() > size * 2.4:
                ink = QPainterPath()
                ink_y = y + shape.bounds.height() * scale / 2 + max(8, size * .19)
                length = min(size * 1.6, shape.bounds.width() * scale * .17)
                ink_x = x - length / 2
                ink.moveTo(ink_x, ink_y)
                ink.cubicTo(ink_x + length * .32, ink_y - size * .045,
                            ink_x + length * .67, ink_y - size * .045, ink_x + length, ink_y)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(alpha(c.primary, opacity * ink_focus * .23), max(.8, size * .025),
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawPath(ink)
            self._text(p, shape, x, y, c.primary, opacity, scale)
            hit_top = min(y - shape.bounds.height() * scale / 2, emblem_y - emblem_radius * 1.5)
            hit_bottom = max(y + shape.bounds.height() * scale / 2, emblem_y + emblem_radius * 1.5)
            hit = QRectF(emblem_x - emblem_radius * 1.5, hit_top,
                         x + shape.bounds.width() * scale / 2 - emblem_x + emblem_radius * 1.5,
                         hit_bottom - hit_top).adjusted(-8, -7, 8, 7)
            self._hit_rows.append((QRectF(hit.toAlignedRect()), i))

    def _fisheye(self, p, index, word_index, fraction, motion, illustrated):
        c = self.controller
        w, h = self.width(), self.height()
        size = self._base_size()
        spacing = max(27, min(h * .235, size * 1.30))
        center = h * .5
        word_width = max(1, w * (.63 if illustrated else .86))
        for i in range(max(0, word_index - 4), min(len(self.timeline.display_words), word_index + 5)):
            word = self.timeline.display_words[i]
            if word.text == "♪":
                continue
            delta = i - self._word_visual
            distance = abs(delta)
            # Lens projection: large in the centre, compressed gently toward its rim.
            scale = .30 + .70 * math.exp(-distance * distance * .9)
            y = center + spacing * delta * (1 - min(.27, distance * .055))
            shape = self._word_shape(word.text, word_width, spacing * 1.16, size * 1.30)
            opacity = max(0, 1 - distance * .34) * self._edge_opacity(y, shape.bounds.height(), scale)
            if opacity < .015:
                continue
            x = w / 2
            if illustrated:
                if i == word_index:
                    self._cutout(p, x - shape.bounds.width() * scale * .08, y + shape.bounds.height() * .04,
                                 shape.bounds.width() * scale * .92, shape.bounds.height() * scale * .9,
                                 opacity, motion)
                if symbol_kind(word.text) != "star" or i == word_index:
                    self._symbol(p, word.text, x - shape.bounds.width() * scale / 2 - size * .58,
                                 y, size * .22 * scale, opacity * (.9 if i == word_index else .45), motion, True)
            color = WHITE if i == word_index and illustrated else c.primary
            self._text(p, shape, x, y, color, opacity, scale,
                       0 if getattr(c, "reduced_motion", False) else clamp(delta * -.7, -2, 2))
            self._hit_rows.append((QRectF(x - shape.bounds.width() * scale / 2 - 12, y - spacing * .35,
                                         shape.bounds.width() * scale + 24, spacing * .7), word.line))

    def _visual(self, p, index, word_index, fraction, motion, transition):
        c = self.controller
        w, h = self.width(), self.height()
        word = self.timeline.display_words[word_index]
        size = self._base_size() * 1.35
        symbol_radius = min(h * .13, size * .58)
        lift = 0 if getattr(c, "reduced_motion", False) else math.sin(motion * 1.1) * min(4, h * .012)
        self._symbol(p, word.text, w / 2, h * .24 + lift, symbol_radius, .83, motion)
        shape = self._word_shape(word.text, max(1, w - 56), h * .27, size)
        if (0 <= self._previous_word < len(self.timeline.display_words) and transition < 1
                and self.timeline.display_words[self._previous_word].text != "♪"):
            previous = self.timeline.display_words[self._previous_word]
            old = self._word_shape(previous.text, max(1, w - 56), h * .27, size)
            self._text(p, old, w / 2, h * .5 - transition * 15, WHITE, (1 - transition) * .55, 1 - transition * .07)
        self._text(p, shape, w / 2, h * .5 + (1 - transition) * 13, c.primary, transition, .90 + transition * .10)
        # Follow the supplied word duration, or the line-based estimate.
        length = min(w * .15, 64)
        p.setPen(QPen(alpha(c.primary, .28), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(w / 2 - length / 2, h * .69), QPointF(w / 2 + length / 2, h * .69))
        p.setPen(QPen(alpha(c.primary, .8), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(w / 2 - length / 2, h * .69), QPointF(w / 2 - length / 2 + length * fraction, h * .69))

    def mousePressEvent(self, event):
        if self.mode != "floating" and event.button() == Qt.MouseButton.LeftButton:
            for rect, index in reversed(self._hit_rows):
                if rect.contains(event.position()):
                    cue = self.controller.lyrics.lines[index]
                    self.controller.seek(max(0, cue.time - self.controller.offset / 1000))
                    self.update()
                    event.accept()
                    return
        super().mousePressEvent(event)


class EdgeOverlay(QWidget):
    def __init__(self, controller, screen):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.controller = controller
        self.target_screen = screen
        self.setWindowTitle("Halo ambient edge")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(screen.geometry())
        screen.geometryChanged.connect(self.setGeometry)

    def event(self, event):
        if event.type() == QEvent.Type.WinIdChange:
            allow_taskbar_reveal(self.effectiveWinId())
        return super().event(event)

    def paintEvent(self, event):
        p = QPainter(self)
        paint_edge_glow(p, self.width(), self.height(), self.controller)


class FloatingLyrics(LyricCanvas):
    def __init__(self, controller):
        super().__init__(controller, "floating")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Halo floating lyrics")
        self.target_screen = None
        self.previewing = False

    def event(self, event):
        if event.type() == QEvent.Type.WinIdChange:
            allow_taskbar_reveal(self.effectiveWinId())
        return super().event(event)

    def place(self, screen):
        if screen is not self.target_screen:
            if self.target_screen:
                try:
                    self.target_screen.availableGeometryChanged.disconnect(self.reposition)
                except (RuntimeError, TypeError):
                    pass
            self.target_screen = screen
            screen.availableGeometryChanged.connect(self.reposition)
        self.reposition()

    def reposition(self, *_):
        if self.target_screen:
            geometry = self.target_screen.availableGeometry()
            self.setGeometry(*floating_geometry((geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                                                self.controller.floating_x, self.controller.floating_y))

    def paintEvent(self, event):
        if self.previewing and not (self.controller.lyrics.lines and self.controller.track.playing):
            p = QPainter(self)
            p.setFont(font(26, QFont.Weight.DemiBold))
            p.setPen(QColor("#000000"))
            p.drawText(self.rect().translated(1, 2), Qt.AlignmentFlag.AlignCenter, "Floating lyrics preview")
            p.setPen(self.controller.primary)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Floating lyrics preview")
        else:
            super().paintEvent(event)


class AmbientBackdrop(QWidget):
    def __init__(self, controller, parent=None, edge_glow=False):
        super().__init__(parent)
        self.controller = controller
        self.edge_glow = edge_glow
        self.background = QPixmap()
        self.background_key = None

    def paintEvent(self, event):
        c = self.controller
        key = (self.width(), self.height(), c.primary.rgba(), c.secondary.rgba())
        if key != self.background_key:
            self.background_key = key
            self.background = QPixmap(self.size())
            self.background.fill(QColor("#0c1110"))
            cached = QPainter(self.background)
            radius = max(self.width(), self.height()) * .7
            for x, y, color in [(self.width() * .17, self.height() * .9, c.secondary),
                                (self.width() * .93, self.height() * .1, c.primary)]:
                g = QRadialGradient(x, y, radius)
                g.setColorAt(0, tint(color, 30))
                g.setColorAt(1, tint(color, 0))
                cached.fillRect(self.rect(), g)
            cached.end()
        p = QPainter(self)
        p.drawPixmap(0, 0, self.background)
        if self.edge_glow and c.glow and c.track.connected and c.track.playing and c.intensity > 0:
            paint_edge_glow(p, self.width(), self.height(), c)


class ListeningBackdrop(AmbientBackdrop):
    """Cached atmosphere plus gentle motion; album art stays clear and unchanged."""
    def __init__(self, controller):
        super().__init__(controller, edge_glow=True)
        self.scene = QPixmap()
        self.scene_key = None

    def paintEvent(self, event):
        c = self.controller
        w, h = self.width(), self.height()
        key = (w, h, c.primary.rgba(), c.secondary.rgba())
        if key != self.scene_key:
            self.scene_key = key
            self.scene = QPixmap(w, h)
            self.scene.fill(QColor("#080e10"))
            paint = QPainter(self.scene)
            paint.setRenderHint(QPainter.RenderHint.Antialiasing)
            for x, y, radius, color, strength in [
                (w * .16, h * .56, w * .53, c.primary, 58),
                (w * .88, h * .15, w * .65, c.secondary, 48),
                (w * .73, h * 1.16, w * .61, c.primary, 30),
            ]:
                gradient = QRadialGradient(x, y, radius)
                gradient.setColorAt(0, tint(color, strength))
                gradient.setColorAt(.45, tint(color, strength * .38))
                gradient.setColorAt(1, tint(color, 0))
                paint.fillRect(self.scene.rect(), gradient)
            # Fine concentric grooves frame the artwork like a listening room.
            center_x, center_y = w * .23, h * .43
            for i in range(16):
                radius = w * (.16 + i * .016)
                paint.setPen(QPen(QColor(211, 230, 220, max(2, 9 - i // 2)), 1))
                paint.drawEllipse(QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2))
            # Sparse, deterministic grain avoids a flat digital gradient.
            paint.setPen(QColor(232, 244, 237, 6))
            for y in range(0, h, 6):
                for x in range((y * 13) % 7, w, 7):
                    if (x * 17 + y * 11) % 5 == 0:
                        paint.drawPoint(x, y)
            paint.end()
        p = QPainter(self)
        p.drawPixmap(0, 0, self.scene)
        breathe = .5 + .5 * math.sin(time.monotonic() * .32)
        haze = QRadialGradient(w * .34, h * .71, min(w, h) * .48)
        haze.setColorAt(0, tint(c.secondary, 6 + breathe * 10))
        haze.setColorAt(1, tint(c.secondary, 0))
        p.fillRect(QRectF(w * .02, h * .22, w * .62, h * .78), haze)
        if c.glow and c.track.connected and c.track.playing and c.intensity > 0:
            paint_edge_glow(p, w, h, c)
