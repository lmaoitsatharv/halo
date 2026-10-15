"""Contrast-preserving light along a continuous rounded-screen perimeter."""
from functools import lru_cache
import math
from types import SimpleNamespace

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QConicalGradient,
                          QPainter)


HALO_MODES = (
    ("aura", "Aura", "A calm, continuous wash of your album colours."),
    ("orbit", "Orbit", "A luminous comet flows around a two-colour rim."),
    ("wave", "Wave", "Silky ribbons of colour travel around the screen."),
    ("pulse", "Pulse", "A slow breathing bloom responds to the music."),
    ("prism", "Prism", "A flowing spectrum inspired by your album palette."),
)


def balanced_glow_colour(colour):
    """Compatibility helper: preserve the requested colour, including black.

    Brightness belongs to the light's opacity, not a forced white admixture.
    The former equal-luminance conversion erased deliberate palette contrast.
    """
    return QColor(colour)


def _unit(value):
    return max(0., min(1., float(value)))


def _phase(c):
    animation = getattr(c, "halo_animation", "flow")
    if animation == "still":
        return 0.
    if hasattr(c, "motion_phase"):
        # The controller integrates rate changes and freezes this on pause.
        result = float(c.motion_phase)
    elif getattr(c, "reduced_motion", False):
        result = 0.
    else:
        speed = _unit(getattr(c, "motion_speed", 45) / 100) / .45
        result = float(getattr(c, "motion_time", 0.)) * (13.7 / 360) * speed
        if animation == "idle":
            result *= .18
    return result % 1. if math.isfinite(result) else 0.


def _mix(a, b, amount):
    return tuple(x + (y - x) * amount for x, y in zip(a, b))


def _colour_function(c, mode, phase):
    """Sample a cyclic palette at a distance around the rim, in full cycles.

    RGB energy becomes premultiplied light: black is transparent, grey is
    neutral light, and saturated blue stays saturated blue. It never creates
    an opaque dark overlay or invents a hue for achromatic palettes.
    """
    a = QColor(getattr(c, "halo_primary", c.primary)).getRgbF()
    b = QColor(getattr(c, "halo_secondary", c.secondary)).getRgbF()
    ba = _unit(getattr(c, "primary_brightness", 100) / 100)
    bb = _unit(getattr(c, "secondary_brightness", 100) / 100)
    a = tuple(channel * ba * a[3] for channel in a[:3])
    b = tuple(channel * bb * b[3] for channel in b[:3])
    proportion = _unit(getattr(c, "color_mix", 60) / 100)
    transition = min(.12, proportion, 1 - proportion)
    primary = QColor(getattr(c, "halo_primary", c.primary))
    secondary = QColor(getattr(c, "halo_secondary", c.secondary))
    saturation = max(primary.hsvSaturationF(), secondary.hsvSaturationF())
    hue = primary.hsvHueF() if primary.hsvHueF() >= 0 else secondary.hsvHueF()
    hue = max(0., hue)

    def sample(distance):
        u = distance % 1.
        if mode != "aura":
            u = (u - phase * (.15 if mode == "pulse" else 1.)) % 1.
        if mode == "wave":
            u = (u * 3) % 1.
        if proportion <= 0:
            amount = 1.
        elif proportion >= 1:
            amount = 0.
        else:
            radial = min(u, 1 - u)
            t = _unit((radial - proportion * .5) / transition + .5)
            amount = t * t * (3 - 2 * t)
        rgb = _mix(a, b, amount)
        if mode == "prism" and saturation > .001:
            energy = max(rgb)
            rgb = QColor.fromHsvF((hue + u) % 1., saturation, energy).getRgbF()[:3]
        energy = max(rgb)
        if energy <= 1e-6:
            return QColor(0, 0, 0, 0)
        highlight = 1.
        if mode == "orbit":
            comet = math.exp(10 * (math.cos(2 * math.pi * (u - .43)) - 1))
            highlight = .83 + .17 * comet
        elif mode == "wave":
            highlight = .87 + .13 * (.5 + .5 * math.sin(u * 2 * math.pi))
        # RGB / energy, alpha = energy reproduces requested RGB on black;
        # black cannot darken another desktop's pixels.
        return QColor.fromRgbF(*(value / energy for value in rgb),
                               _unit(energy * highlight))

    return sample


@lru_cache(maxsize=6)
def _light_tiles(w, h, band, rim_width, glow_opacity, dpr):
    """Cache independent rim/spill geometry in four non-overlapping strips.

    NumPy runs only when geometry or a control changes. No full-screen field
    is allocated. Animated frames use Qt's interpolated brushes.
    """
    import numpy as np
    radius = min(16 * dpr, min(w, h) / 4)

    def tile(x0, y0, width, height):
        x = np.arange(x0, x0 + width, dtype=np.float32)[None, :] + .5
        y = np.arange(y0, y0 + height, dtype=np.float32)[:, None] + .5
        qx = np.abs(x - w / 2) - (w / 2 - radius)
        qy = np.abs(y - h / 2) - (h / 2 - radius)
        sdf = (np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
               + np.minimum(np.maximum(qx, qy), 0) - radius)
        coverage = np.clip(.5 - sdf, 0, 1)
        depth = np.maximum(0, -sdf)
        core = np.clip(rim_width - depth + .5, 0, 1)
        masks = []
        for spread in (1., .58):
            def falloff(distance):
                t = np.minimum(1, distance / max(1, band * spread))
                return np.exp(-3.4 * t * t) * np.power(1 - t, 1.1)
            horizontal = falloff(np.minimum(x, w - x))
            vertical = falloff(np.minimum(y, h - y))
            # A smooth weighted maximum keeps a corner equal to one edge,
            # rather than adding two glows or exposing the nearest-edge
            # distance field's derivative crease along the inward diagonal.
            field = ((horizontal ** 8 + vertical ** 8)
                     / (horizontal ** 7 + vertical ** 7 + 1e-20))
            spill = field * glow_opacity
            alpha = (1 - (1 - core) * (1 - spill)) * coverage
            rgba = np.full((height, width, 4), 255, dtype=np.uint8)
            rgba[:, :, 3] = np.rint(alpha * 255)
            mask = QImage(rgba.data, width, height, rgba.strides[0], QImage.Format.Format_RGBA8888)
            mask = mask.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            mask.setDevicePixelRatio(dpr)
            masks.append(mask)
        return (x0 / dpr, y0 / dpr, *masks)

    tiles = [tile(0, 0, w, band), tile(0, h - band, w, band)]
    if h > 2 * band:
        tiles.extend([tile(0, band, band, h - 2 * band),
                      tile(w - band, band, band, h - 2 * band)])
    return tuple(tiles)


def _perimeter_brushes(w, h, sample):
    """Four straight sections and four circular arcs share one distance axis.

    Colour travels in pixels along the path, not polar angle from the screen
    centre. Native interpolation avoids quantised spatial bands at 4K.
    """
    r = min(16., min(w, h) / 4)
    horizontal, vertical = w - 2 * r, h - 2 * r
    arc = math.pi * r / 2
    length = 2 * (horizontal + vertical) + 4 * arc
    right_start = horizontal + arc
    bottom_start = right_start + vertical + arc
    left_start = bottom_start + horizontal + arc

    def linear(x1, y1, x2, y2, start, distance):
        gradient = QLinearGradient(x1, y1, x2, y2)
        count = max(12, min(320, math.ceil(distance / 12)))
        for i in range(count + 1):
            u = i / count
            gradient.setColorAt(u, sample((start + u * distance) / length))
        return gradient

    top = linear(r, 0, w - r, 0, 0, horizontal)
    right = linear(w, r, w, h - r, right_start, vertical)
    bottom = linear(w - r, h, r, h, bottom_start, horizontal)
    left = linear(0, h - r, 0, r, left_start, vertical)

    def corner(x, y, first_angle, start):
        # Qt's conical coordinate goes counter-clockwise; our path goes
        # clockwise, so distance runs in reverse quarter-arc stop order.
        gradient = QConicalGradient(QPointF(x, y), 0)
        first = first_angle / 360
        beginning, ending = sample(start / length), sample((start + arc) / length)
        gradient.setColorAt(0., ending)
        gradient.setColorAt(1., beginning)
        for i in range(17):
            u = i / 16
            gradient.setColorAt(first + u * .25, sample((start + (1 - u) * arc) / length))
        if first == .75:
            gradient.setColorAt(0., beginning)
        return gradient

    corners = (
        (QRectF(w - r, 0, r, r), corner(w - r, r, 0, horizontal)),
        (QRectF(w - r, h - r, r, r), corner(w - r, h - r, 270, right_start + vertical)),
        (QRectF(0, h - r, r, r), corner(r, h - r, 180, bottom_start + horizontal)),
        (QRectF(0, 0, r, r), corner(r, r, 90, left_start + vertical)),
    )
    return top, right, bottom, left, corners


@lru_cache(maxsize=8)
def _corner_weights(band, dpr):
    """Complementary spill weights meet both straight strips with no crease."""
    import numpy as np
    depth = (np.arange(band, dtype=np.float32) + .5) / band
    light = (np.exp(-3.4 * depth * depth) * np.power(1 - depth, 1.1)) ** 3
    side = light[None, :] / (light[None, :] + light[:, None] + 1e-20)
    result = []
    for weight in (side, side[:, ::-1], side[::-1, ::-1], side[::-1, :]):
        pair = []
        for alpha in (1 - weight, weight):
            rgba = np.full((band, band, 4), 255, dtype=np.uint8)
            rgba[:, :, 3] = np.rint(alpha * 255)
            image = QImage(rgba.data, band, band, rgba.strides[0], QImage.Format.Format_RGBA8888)
            image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            pair.append(image)
        result.append(tuple(pair))
    return tuple(result)


def _paint_corner_spill(painter, rect, horizontal_source, vertical, weights, dpr):
    """Blend two native brushes in one small corner, preserving premultiplied RGB."""
    layers = []
    for index, mask in enumerate(weights):
        layer = horizontal_source if index == 0 else QImage(mask.size(), QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        paint = QPainter(layer)
        if index:
            paint.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            paint.translate(-rect.x(), -rect.y())
            paint.fillRect(rect, vertical)
            paint.resetTransform()
        paint.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        paint.drawImage(QPointF(0, 0), mask)
        paint.end()
        layers.append(layer)
    blend = QPainter(layers[0])
    blend.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    blend.drawImage(QPointF(0, 0), layers[1])
    blend.end()
    painter.drawImage(rect.topLeft(), layers[0])


def paint_edge_glow(p, w, h, c):
    """Paint a saturated rim, independent soft spill and transparent centre."""
    intensity = _unit(c.intensity / 100)
    if intensity == 0 or min(w, h) < 4:
        return
    mode = getattr(c, "halo_mode", "aura")
    if mode not in {spec[0] for spec in HALO_MODES}:
        mode = "aura"
    animation = getattr(c, "halo_animation", "flow")
    phase = _phase(c)
    beat = _unit(c.pulse) if animation == "music" and not getattr(c, "reduced_motion", False) else 0.
    sample = _colour_function(c, mode, phase)
    top, right, bottom, left, corners = _perimeter_brushes(w, h, sample)
    dpr = max(1., p.device().devicePixelRatioF())
    pixel_w, pixel_h = round(w * dpr), round(h * dpr)
    rim_width = max(1., min(12., float(getattr(c, "rim_width", 3)))) * dpr
    band = max(1, min(round(max(c.glow_width * dpr, rim_width + 1)), min(pixel_w, pixel_h) // 2))
    opacity = _unit(getattr(c, "glow_opacity", 65) / 100)
    strength = intensity * (.78 + .22 * beat if animation == "music" else 1.)
    breath = .5 - .5 * math.cos(phase * math.pi * 4)
    width_mix = .32 + .68 * max(breath, beat) if mode == "pulse" else 1.
    if animation == "still":
        width_mix = .7 if mode == "pulse" else 1.
    logical_band = band / dpr
    spill_corners = (
        (QRectF(0, 0, logical_band, logical_band), top, left),
        (QRectF(w - logical_band, 0, logical_band, logical_band), top, right),
        (QRectF(w - logical_band, h - logical_band, logical_band, logical_band), bottom, right),
        (QRectF(0, h - logical_band, logical_band, logical_band), bottom, left),
    )
    corner_weights = _corner_weights(band, dpr)
    p.save()
    p.setOpacity(p.opacity() * strength)
    for x, y, broad, tight in _light_tiles(pixel_w, pixel_h, band, rim_width, opacity, dpr):
        layer = QImage(broad.size(), QImage.Format.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.translate(-x, -y)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        box = QRectF(x, y, layer.width() / dpr, layer.height() / dpr)
        horizontal_tile = y == 0 or y > h / 2
        painter.fillRect(box, top if y == 0 else bottom if horizontal_tile else left if x == 0 else right)
        if horizontal_tile:
            for (rect, horizontal, vertical), weights in zip(spill_corners, corner_weights):
                if box.intersects(rect):
                    # Reuse the already-rasterised straight brush. Repainting
                    # it in a small clipped device can introduce Qt's fixed-
                    # point gradient sampling offsets along the patch boundary.
                    source = layer.copy(round((rect.x() - x) * dpr),
                                        round((rect.y() - y) * dpr), band, band)
                    _paint_corner_spill(painter, rect, source, vertical, weights, dpr)
        for rect, brush in corners:
            if box.intersects(rect):
                painter.fillRect(rect, brush)
        painter.resetTransform()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        if width_mix == 1.:
            painter.drawImage(QPointF(0, 0), broad)
        else:
            # A blend of two cached spill widths keeps the crisp rim invariant.
            mask = QImage(broad.size(), QImage.Format.Format_ARGB32_Premultiplied)
            mask.setDevicePixelRatio(dpr)
            mask.fill(Qt.GlobalColor.transparent)
            mask_painter = QPainter(mask)
            mask_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            mask_painter.setOpacity(width_mix)
            mask_painter.drawImage(QPointF(0, 0), broad)
            mask_painter.setOpacity(1 - width_mix)
            mask_painter.drawImage(QPointF(0, 0), tight)
            mask_painter.end()
            painter.drawImage(QPointF(0, 0), mask)
        painter.end()
        p.drawImage(QPointF(x, y), layer)
    p.restore()


def paint_halo_preview(p, rect, c, mode=None, motion_time=None, *, motion_phase=None):
    """Draw the desktop engine in a live thumbnail; caller owns its backdrop."""
    rect = QRectF(rect)
    fields = dict(
        primary=c.primary, secondary=c.secondary,
        intensity=getattr(c, "intensity", 75), pulse=getattr(c, "pulse", 0.),
        glow_width=min(18., rect.height() * .23), rim_width=min(2., getattr(c, "rim_width", 3)),
        glow_opacity=getattr(c, "glow_opacity", 65),
        halo_mode=mode or getattr(c, "halo_mode", "orbit"),
        halo_animation=getattr(c, "halo_animation", "flow"),
        motion_speed=getattr(c, "motion_speed", 45),
        motion_time=getattr(c, "motion_time", 0.) if motion_time is None else motion_time,
        reduced_motion=getattr(c, "reduced_motion", False),
        primary_brightness=getattr(c, "primary_brightness", 100),
        secondary_brightness=getattr(c, "secondary_brightness", 100),
        color_mix=getattr(c, "color_mix", 60),
        halo_primary=getattr(c, "halo_primary", c.primary),
        halo_secondary=getattr(c, "halo_secondary", c.secondary),
    )
    if motion_phase is not None:
        fields["motion_phase"] = motion_phase
    elif motion_time is None and hasattr(c, "motion_phase"):
        fields["motion_phase"] = c.motion_phase
    preview = SimpleNamespace(**fields)
    p.save()
    p.translate(rect.topLeft())
    paint_edge_glow(p, rect.width(), rect.height(), preview)
    p.restore()
