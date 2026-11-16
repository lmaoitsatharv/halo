"""Living light for the Immersive rooms.

Two things every room can share: the song's own vivid colours and how much the
music is swelling right now, and a colour field poured from the actual cover.
The field is computed small with NumPy and drawn large, so it costs a few
milliseconds a frame however big the screen is.
"""
from functools import lru_cache
import math
import time

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap


FIELD_RATE = 30  # The field changes slowly; 30 updates a second look continuous.
FIELD_CROSSFADE = 1.2  # Seconds for one cover's colours to pour into the next.


@lru_cache(maxsize=4)
def _artwork_image(data):
    """Bound the decorative artwork copies without decoding on every frame."""
    if not isinstance(data, bytes) or not data or len(data) > 12 * 1024 * 1024:
        return QImage()
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() > 12000 or size.height() > 12000 or size.width() * size.height() > 36_000_000:
        return QImage()
    if max(size.width(), size.height()) > 640:
        size.scale(QSize(640, 640), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    return reader.read()


def colour(value, opacity):
    result = QColor(value)
    result.setAlphaF(max(0., min(1., opacity)))
    return result


def mix(a, b, amount):
    amount = max(0., min(1., amount))
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                           a.greenF() + (b.greenF() - a.greenF()) * amount,
                           a.blueF() + (b.blueF() - a.blueF()) * amount)


def vivid(controller):
    """The song's own vivid pair (the halo's colours); the readable accents when there are none."""
    pair = []
    for name, fallback in (("halo_primary", "primary"), ("halo_secondary", "secondary")):
        value = getattr(controller, name, None)
        if not isinstance(value, QColor) or not value.isValid():
            value = getattr(controller, fallback, None)
        pair.append(QColor(value) if isinstance(value, QColor) and value.isValid() else QColor("#9db6c8"))
    return pair[0], pair[1]


def moving(controller):
    return (not getattr(controller, "reduced_motion", False)
            and bool(getattr(getattr(controller, "track", None), "playing", False)))


def swell(controller):
    """0 to 1: how much the music is swelling now. Quiet when paused, still, or not listening."""
    if not moving(controller):
        return 0.
    try:
        value = float(getattr(controller, "pulse", 0.))
    except (TypeError, ValueError):
        return 0.
    return max(0., min(1., value)) if math.isfinite(value) else 0.


def progress(controller):
    """How far through the song we are, 0 to 1; 0 when the length is unknown."""
    track = getattr(controller, "track", None)
    duration = getattr(track, "duration", 0) or 0
    try:
        position = float(getattr(controller, "position", getattr(track, "position", 0)) or 0)
        duration = float(duration)
    except (TypeError, ValueError):
        return 0.
    if not duration > 0 or not math.isfinite(position) or not math.isfinite(duration):
        return 0.
    return max(0., min(1., position / duration))


@lru_cache(maxsize=4)
def cover_texture(data):
    """The cover as a small, softened float RGB array (None without a usable cover)."""
    image = _artwork_image(data)
    if image.isNull():
        return None
    small = image.scaled(QSize(28, 28), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
    rows = np.frombuffer(small.constBits(), dtype=np.uint8).reshape(small.height(), small.bytesPerLine())
    texture = rows[:, :small.width() * 3].reshape(small.height(), small.width(), 3).astype(np.float32) / 255.
    # Two soft box passes melt hard edges and text into colour regions.
    for _ in range(2):
        padded = np.pad(texture, ((1, 1), (1, 1), (0, 0)), mode="edge")
        texture = sum(padded[y:y + texture.shape[0], x:x + texture.shape[1]]
                      for y in range(3) for x in range(3)) / 9.
    texture.setflags(write=False)
    return texture


@lru_cache(maxsize=4)
def _colour_texture(a, b):
    """Without a cover, the field pours from the song's two colours (given as 0xRRGGBB) instead."""
    y, x = np.mgrid[0:16, 0:16].astype(np.float32) / 15.
    amount = (.5 + .5 * np.sin(x * 4.2 + 1.1) * np.cos(y * 3.4))[..., None]
    first = np.array([(a >> 16) & 255, (a >> 8) & 255, a & 255], dtype=np.float32) / 255.
    second = np.array([(b >> 16) & 255, (b >> 8) & 255, b & 255], dtype=np.float32) / 255.
    dark = np.array([.03, .035, .05], dtype=np.float32)
    texture = first * amount + second * (1 - amount)
    shade = (.35 + .65 * (.5 + .5 * np.sin(x * 2.6 - y * 3.1)))[..., None]
    texture = (texture * shade + dark * (1 - shade)).astype(np.float32)
    texture.setflags(write=False)
    return texture


@lru_cache(maxsize=8)
def _grid(columns, rows):
    ys, xs = np.mgrid[0:rows, 0:columns].astype(np.float32)
    aspect = columns / max(1, rows)
    return (xs / max(1, columns - 1) - .5) * aspect, ys / max(1, rows - 1) - .5


def _sample(texture, u, v):
    """Bilinear lookup with mirrored edges, so the field never shows a seam."""
    u = 1. - np.abs(np.mod(u, 2.) - 1.)
    v = 1. - np.abs(np.mod(v, 2.) - 1.)
    height, width = texture.shape[:2]
    fx, fy = u * (width - 1), v * (height - 1)
    x0, y0 = np.floor(fx).astype(np.int32), np.floor(fy).astype(np.int32)
    x1, y1 = np.minimum(x0 + 1, width - 1), np.minimum(y0 + 1, height - 1)
    wx, wy = (fx - x0)[..., None], (fy - y0)[..., None]
    top = texture[y0, x0] * (1 - wx) + texture[y0, x1] * wx
    bottom = texture[y1, x0] * (1 - wx) + texture[y1, x1] * wx
    return top * (1 - wy) + bottom * wy


def field_pixels(texture, columns, rows, phase, energy=0., brightness=.62, saturation=1.35, knee=.46, glow=None):
    """One frame of the poured colour field as a uint8 (rows, columns, 3) array.

    glow: (strength, colour, colour) as 0-1 RGB arrays; the dark folds of the field fill
    with the song's own colours instead of going black.
    """
    x, y = _grid(columns, rows)
    t = float(phase)
    angle = t * .035
    ca, sa = math.cos(angle), math.sin(angle)
    zoom = .7 + .05 * math.sin(t * .05) - .06 * energy
    xr = (x * ca - y * sa) * zoom
    yr = (x * sa + y * ca) * zoom
    # Three octaves of domain warping fold the cover into slow, liquid swirls rather than a plain blur.
    qx = xr + .34 * np.sin(2.2 * yr + t * .19)
    qy = yr + .34 * np.sin(1.9 * xr - t * .16 + 1.3)
    rx = qx + .2 * np.sin(3.6 * qy + t * .27 + 2.)
    ry = qy + .2 * np.sin(3.3 * qx - t * .22 + .7)
    sx = rx + .09 * np.sin(6.1 * ry - t * .31 + 4.1)
    sy = ry + .09 * np.sin(5.7 * rx + t * .35 + 2.6)
    rgb = _sample(texture, sx + .5, sy + .5)
    grey = (rgb @ np.array([.2126, .7152, .0722], dtype=np.float32))[..., None]
    rgb = grey + (rgb - grey) * saturation
    rgb *= brightness + .2 * energy
    weights = np.array([.2126, .7152, .0722], dtype=np.float32)
    if glow is not None:
        strength, first, second = glow
        mixer = (.5 + .5 * np.sin(x * 1.7 + t * .12) * np.cos(y * 2.3 - t * .09))[..., None]
        tint = first * mixer + second * (1 - mixer)
        dark = np.clip(1. - (rgb @ weights)[..., None] / .32, 0., 1.)
        rgb = rgb + tint * dark * strength * (1 + .25 * energy)
    # Roll off the brightest folds so a white eye or a pale sky never glares behind the words.
    luminance = np.maximum((rgb @ weights)[..., None], 1e-4)
    rgb *= np.where(luminance > knee, (knee + (luminance - knee) * .35) / luminance, 1.)
    np.clip(rgb, 0., 1., out=rgb)
    return (rgb * 255. + .5).astype(np.uint8)


FIELD_LEVEL = .26  # The field's average brightness, whatever the cover, so white words always read.


def exposure(texture, brightness, level=FIELD_LEVEL):
    """Scale the field so pale covers darken and dark covers lift towards the same level."""
    luminance = float(np.mean(texture @ np.array([.2126, .7152, .0722], dtype=np.float32)))
    return max(.3, min(brightness * 1.5, level / max(.05, luminance)))


def _rgb(colour_value):
    return np.array([colour_value.redF(), colour_value.greenF(), colour_value.blueF()], dtype=np.float32)


class CoverField:
    """The cover poured into a slowly turning colour field; one per painting surface."""

    def __init__(self, columns=168):
        self.columns = columns
        self._image = QImage()
        self._key = None
        self._made_at = -1.
        self._texture_key = None
        self._texture = None
        self._previous = None
        self._changed_at = 0.

    def _target(self, controller):
        data = getattr(getattr(controller, "track", None), "artwork", b"")
        texture = cover_texture(data) if isinstance(data, bytes) and data else None
        if texture is not None:
            return ("cover", id(texture)), texture
        a, b = (value.rgb() & 0xFFFFFF for value in vivid(controller))
        return ("colours", a, b), _colour_texture(a, b)

    def image(self, controller, width, height, phase, energy=0., brightness=.62, saturation=1.35, now=None,
              level=FIELD_LEVEL, knee=.46, glow=0.):
        """The current field as a small QImage; draw it stretched over the room.

        level is the average brightness it settles at, knee where highlights roll off, and
        glow how strongly the song's colours fill its dark folds.
        """
        now = time.monotonic() if now is None else now
        rows = max(8, round(self.columns * max(1, height) / max(1, width)))
        key, texture = self._target(controller)
        if key != self._texture_key:
            # Keep the frame on screen as the starting point, so a new song pours in.
            # Song colours already glide on their own, so only a cover change crossfades here.
            pour = "cover" in (key[0], (self._texture_key or ("",))[0])
            self._previous = self._texture if self._texture is not None and pour and moving(controller) else None
            self._texture_key, self._texture = key, texture
            self._changed_at = now
            self._key = None
        blend = 1.
        if self._previous is not None:
            blend = min(1., (now - self._changed_at) / FIELD_CROSSFADE)
            if blend >= 1.:
                self._previous = None
        a, b = vivid(controller)
        frame_key = (self._texture_key, self.columns, rows, round(float(phase), 3), round(energy, 2),
                     brightness, saturation, round(blend, 2), level, knee, glow, a.rgb(), b.rgb())
        if frame_key == self._key and not self._image.isNull():
            return self._image
        # Between 30 Hz updates the last frame stands in, but only for a small step of the
        # same flow: a jump in the clock (a seek, another surface) always gets a fresh frame.
        if (not self._image.isNull() and self._previous is None and frame_key[:3] == (self._key or ())[:3]
                and abs(frame_key[3] - self._key[3]) < .1 and now - self._made_at < 1 / FIELD_RATE):
            return self._image
        source = self._texture
        if self._previous is not None and self._previous.shape == source.shape:
            smooth = blend * blend * (3 - 2 * blend)
            source = self._previous * (1 - smooth) + source * smooth
        tint = (glow, _rgb(a), _rgb(b)) if glow > 0 else None
        pixels = np.ascontiguousarray(field_pixels(source, self.columns, rows, phase, energy,
                                                   exposure(source, brightness, level), saturation, knee, tint))
        self._image = QImage(pixels.data, self.columns, rows, self.columns * 3, QImage.Format.Format_RGB888).copy()
        self._key, self._made_at = frame_key, now
        return self._image

    def paint(self, painter, rect, controller, phase, energy=0., brightness=.62, saturation=1.35, **look):
        rect = QRectF(rect)
        image = self.image(controller, rect.width(), rect.height(), phase, energy, brightness, saturation, **look)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, image)
        painter.restore()
        return image


@lru_cache(maxsize=1)
def grain_tile():
    """A fixed, faint film grain that breaks up banding in large dark gradients."""
    size = 128
    generator = np.random.default_rng(7)
    values = generator.integers(0, 256, size=(size, size), dtype=np.uint8)
    alpha = np.where(values > 127, 9, 7).astype(np.uint8)
    pixels = np.dstack((values, values, values, alpha)).astype(np.uint8)
    pixels = np.ascontiguousarray(pixels)
    image = QImage(pixels.data, size, size, size * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(image)


def paint_grain(painter, rect):
    painter.drawTiledPixmap(QRectF(rect), grain_tile())
