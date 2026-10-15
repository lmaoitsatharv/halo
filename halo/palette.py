"""Artwork colours and continuous palette fades, independent of UI accents."""
import math
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage


def valid_colour(value, fallback):
    colour = QColor(value)
    return colour if colour.isValid() else QColor(fallback)


def artwork_colours(data):
    """Select two distinct colours present in the artwork; preserve dark pixels."""
    image = QImage()
    if not data or not image.loadFromData(data):
        return QColor("#b7e4ad"), QColor("#54ad9f")
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
    if not buckets:
        return QColor("#b7e4ad"), QColor("#54ad9f")
    samples = [(count, QColor.fromRgbF(r / count, g / count, b / count))
               for count, r, g, b in buckets.values()]
    samples.sort(key=lambda item: item[0], reverse=True)
    primary = samples[0][1]
    minimum = sum(item[0] for item in samples) * .025
    pr, pg, pb, _ = primary.getRgbF()
    def score(sample):
        count, colour = sample
        r, g, b, _ = colour.getRgbF()
        difference = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        return math.sqrt(count) * difference * (.25 + .75 * colour.hsvSaturationF())
    candidates = [item for item in samples[1:] if item[0] >= minimum]
    secondary = max(candidates, key=score)[1] if candidates else QColor(primary)
    return primary, secondary


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
