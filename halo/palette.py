"""Artwork colours and continuous palette fades, independent of UI accents."""
import math
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage


def valid_colour(value, fallback):
    colour = QColor(value)
    return colour if colour.isValid() else QColor(fallback)


FALLBACK = ("#b7e4ad", "#54ad9f")
# The dimmest an album colour may light the rim; brighter colours are kept as they are.
LIGHT_FLOOR = .85


def _artwork_samples(data):
    """The cover's average colours per RGB bucket, most common first; empty if unreadable."""
    image = QImage()
    if not data or not image.loadFromData(data):
        return []
    image = image.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    buckets = {}
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alphaF() < .05:
                continue
            r, g, b, weight = colour.getRgbF()
            key = tuple(min(7, int(channel * 8)) for channel in (r, g, b))
            total, red, green, blue = buckets.get(key, (0., 0., 0., 0.))
            buckets[key] = (total + weight, red + r * weight, green + g * weight, blue + b * weight)
    samples = [(count, QColor.fromRgbF(r / count, g / count, b / count))
               for count, r, g, b in buckets.values()]
    samples.sort(key=lambda item: item[0], reverse=True)
    return samples


def _lift(colour):
    """Raise a dark colour to the light floor, keeping its hue and saturation."""
    hue, saturation, value, _ = colour.getHsvF()
    if value >= LIGHT_FLOOR:
        return QColor(colour)
    return QColor.fromHsvF(max(0., hue), saturation, LIGHT_FLOOR)


def artwork_light_colours(data):
    """Two colours for the halo light: the cover's most vivid tones, lifted so a dark cover still glows.

    The most common colour is often a dark background, which lights the rim
    dimly at any intensity. Here a colour counts by its coverage and its
    vividness (saturation times brightness); the second is the most vivid
    colour that differs from the first. Lyrics and interface accents tint
    from the same pair through readable_accent; Custom colours bypass this.
    """
    samples = _artwork_samples(data)
    if not samples:
        return _lift(QColor(FALLBACK[0])), _lift(QColor(FALLBACK[1]))
    minimum = sum(count for count, _ in samples) * .015
    candidates = [item for item in samples if item[0] >= minimum] or samples[:1]

    def vivid(item):
        count, colour = item
        return math.sqrt(count) * (.08 + colour.hsvSaturationF() * colour.valueF())

    first = max(candidates, key=vivid)
    primary = _lift(first[1])
    pr, pg, pb, _ = primary.getRgbF()

    def contrast(item):
        r, g, b, _ = _lift(item[1]).getRgbF()
        return vivid(item) * ((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2)

    others = [item for item in candidates if item is not first]
    second = max(others, key=contrast) if others else first
    return primary, _lift(second[1])


def readable_accent(colour, counterpart=None):
    """Readable lyric/UI tint; this is never used as the halo's raw colour."""
    value = QColor(colour)
    if value.valueF() < .15 and counterpart is not None:
        value = QColor(counterpart)
    hue, saturation, brightness, _ = value.getHsvF()
    if hue < 0:
        return QColor("#d3d9de")
    return QColor.fromHsvF(hue, min(.55, saturation), max(.90, brightness))


class PaletteTransition:
    def __init__(self, primary, secondary, now=0., duration=.9):
        self.start = (QColor(primary), QColor(secondary))
        self.target = (QColor(primary), QColor(secondary))
        self.started = now
        self.duration = max(.001, duration)

    def at(self, now):
        amount = max(0., min(1., (now - self.started) / self.duration))
        amount = amount * amount * (3 - 2 * amount)
        result = []
        for before, after in zip(self.start, self.target):
            a, b = before.getRgbF(), after.getRgbF()
            result.append(QColor.fromRgbF(*(x + (y - x) * amount for x, y in zip(a, b))))
        return tuple(result)

    def retarget(self, primary, secondary, now, immediate=False):
        target = (QColor(primary), QColor(secondary))
        if not immediate and target == self.target:
            return
        self.start = target if immediate else self.at(now)
        self.target = target
        self.started = now - self.duration if immediate else now


def envelope(value, target, elapsed, attack=.045, release=.28):
    """Time-based output-energy envelope; equal response at any refresh rate."""
    value, target = max(0., min(1., value)), max(0., min(1., target))
    constant = attack if target > value else release
    return target + (value - target) * math.exp(-max(0., elapsed) / constant)
