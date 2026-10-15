"""Native lyric typography and estimated word choreography.

Mode names follow the four Verci-inspired modes documented by the independent
theaestheticslyrics project. The linked official site (https://verci.xyz) was
unreachable during research, so these animations are Halo's own interpretation.
LRC supplies line timestamps only: word timing below is explicitly estimated.
"""
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
import math
import re

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainterPath, QTextLayout, QTextOption, QTransform
from .models import lyric_word_matches, validate_lyric_lines


LYRIC_STYLES = (
    ("ship", "Ship", "A drifting wall of lyrics with a moving word spotlight."),
    ("fisheye", "Fisheye", "Words flow through a lens; the current word swells into focus."),
    ("fisheye_visual", "Fisheye Visual", "The flowing word lens with expressive illustrated symbols."),
    ("visual", "Visual", "One bold word at a time, paired with a floating symbol."),
)


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


def smooth(value):
    value = clamp(value)
    return value * value * (3 - 2 * value)


def spring(value, velocity, target, elapsed, frequency=13.0):
    """Exact critically damped spring solution, independent of repaint rate."""
    if elapsed <= 0:
        return value, velocity
    delta = value - target
    impulse = velocity + frequency * delta
    decay = math.exp(-frequency * elapsed)
    return target + (delta + impulse * elapsed) * decay, (velocity - frequency * impulse * elapsed) * decay


@dataclass(frozen=True)
class Word:
    text: str
    line: int
    start: int
    end: int
    begin: float
    finish: float


class WordTimeline:
    """Bounded, line-anchored word estimates; every new line resynchronizes."""
    def __init__(self, lines, duration=0):
        validate_lyric_lines(lines)
        self.words = []
        self.ranges = []
        for i, line in enumerate(lines):
            # A language without spaces still gets expressive, legible word flow.
            matches = lyric_word_matches(line.text)
            end_time = lines[i + 1].time if i + 1 < len(lines) else max(line.time + 4, duration)
            span = max(.04, end_time - line.time)
            weights = [max(1, len(m.group()) ** .64) + (.6 if m.group()[-1:] in ",;.!?" else 0) for m in matches]
            total = sum(weights) or 1
            start = len(self.words)
            cursor = line.time
            for match, weight in zip(matches, weights):
                finish = cursor + span * weight / total
                self.words.append(Word(match.group(), i, match.start(), match.end(), cursor, finish))
                cursor = finish
            if not matches:
                self.words.append(Word("♪", i, 0, 0, line.time, end_time))
            self.ranges.append((start, len(self.words)))

    def at(self, line, position):
        if line < 0 or not self.ranges:
            return -1, 0.0
        start, end = self.ranges[min(line, len(self.ranges) - 1)]
        index = max(start, min(end - 1, bisect_right([w.begin for w in self.words[start:end]], position) + start - 1))
        word = self.words[index]
        return index, clamp((position - word.begin) / max(.04, word.finish - word.begin))


@dataclass
class TextShape:
    path: QPainterPath
    bounds: QRectF
    word_boxes: list
    pixels: int


class TypeCache:
    """Cache shaped glyph outlines, wrapping and fitted fonts, never per frame."""
    def __init__(self, limit=220):
        self.items = OrderedDict()
        self.limit = limit

    def clear(self):
        self.items.clear()

    def get(self, text, width, height, size, weight=QFont.Weight.DemiBold, alignment="center", expressive=False):
        lyric_word_matches(text)
        width, height = max(1, int(width)), max(1, int(height))
        key = (text, width, height, int(size), weight, alignment, expressive)
        if key in self.items:
            self.items.move_to_end(key)
            return self.items[key]
        result = None
        # Small steps only happen for new content or a window resize.
        minimum = max(7, min(15, int(size * .38)))
        for pixels in range(max(minimum, int(size)), minimum - 1, -1):
            face = QFont("Arial" if expressive else "Segoe UI Variable Display")
            face.setPixelSize(pixels)
            face.setWeight(QFont.Weight.ExtraBold if expressive else weight)
            face.setItalic(expressive)
            if expressive:
                face.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -pixels * .032)
            layout = QTextLayout(text, face)
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            rows = []
            y = 0
            while True:
                row = layout.createLine()
                if not row.isValid():
                    break
                row.setLineWidth(width)
                row.setPosition(QPointF((width - row.naturalTextWidth()) / 2 if alignment == "center" else 0, y))
                rows.append(row)
                y += row.height() * 1.07
            layout.endLayout()
            if y <= height or pixels == minimum:
                path = QPainterPath()
                for run in layout.glyphRuns():
                    raw = run.rawFont()
                    for glyph, position in zip(run.glyphIndexes(), run.positions()):
                        glyph_path = raw.pathForGlyph(glyph)
                        glyph_path.translate(position)
                        path.addPath(glyph_path)
                boxes = []
                row_ends = [row.textStart() + row.textLength() for row in rows]
                for match in re.finditer(r"\S+", text):
                    for row_index in range(bisect_right(row_ends, match.start()), len(rows)):
                        row = rows[row_index]
                        if row.textStart() >= match.end():
                            break
                        a = max(match.start(), row.textStart())
                        b = min(match.end(), row.textStart() + row.textLength())
                        if b > a:
                            x1 = row.cursorToX(a)[0]
                            x2 = row.cursorToX(b)[0]
                            boxes.append((match.start(), match.end(), QRectF(row.position().x() + min(x1, x2), row.y(), abs(x2 - x1), row.height())))
                bounds = path.boundingRect()
                factor = min(1.0, width / max(1, bounds.width()), height / max(1, bounds.height()))
                if factor < 1:
                    transform = QTransform.fromScale(factor, factor)
                    path = transform.map(path)
                    boxes = [(a, b, transform.mapRect(box)) for a, b, box in boxes]
                result = TextShape(path, path.boundingRect(), boxes, pixels)
                break
        self.items[key] = result
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return result


def alpha(color, opacity):
    value = QColor(color)
    value.setAlphaF(clamp(opacity))
    return value


def symbol_kind(word):
    value = word.lower().strip(".,!?;:'\"’")
    if value in {"see", "seen", "eyes", "eye", "look", "watch", "vision"}:
        return "eye"
    if value in {"chance", "chances", "luck", "lucky", "roll", "game"}:
        return "dice"
    if value in {"wind", "blew", "blow", "air", "breath", "breathe", "away"}:
        return "wind"
    if value in {"name", "names", "write", "written", "words", "story"}:
        return "signature"
    if value in {"love", "heart", "loved", "loving", "you", "us"}:
        return "heart"
    if value in {"moon", "night", "dream", "dreams", "sleep", "dark"}:
        return "moon"
    if value in {"sun", "light", "shine", "glow", "gold", "day", "alive"}:
        return "sun"
    if value in {"rain", "ocean", "sea", "water", "river", "flow", "waves", "sound", "music", "song"}:
        return "wave"
    if value in {"home", "world", "earth", "grow", "life", "green", "colours", "colors"}:
        return "leaf"
    return "star"


def symbol_path(kind):
    """Original vector symbols, expressed in a unit box around the origin."""
    path = QPainterPath()
    if kind == "eye":
        path.moveTo(-1, 0)
        path.cubicTo(-.4, -.85, .4, -.85, 1, 0)
        path.cubicTo(.4, .85, -.4, .85, -1, 0)
        path.addEllipse(QRectF(-.25, -.25, .5, .5))
    elif kind == "dice":
        path.addRoundedRect(QRectF(-.78, -.78, 1.56, 1.56), .22, .22)
        for x, y in ((-.4, -.4), (.4, -.4), (0, 0), (-.4, .4), (.4, .4)):
            path.addEllipse(QRectF(x - .075, y - .075, .15, .15))
    elif kind == "wind":
        for row, ending in ((-.38, .15), (0, .7), (.4, -.05)):
            path.moveTo(-1, row)
            path.cubicTo(-.5, row - .14, .2, row + .12, ending, row)
            path.cubicTo(ending + .5, row, ending + .5, row - .58, ending + .15, row - .4)
    elif kind == "signature":
        path.moveTo(-1, .4)
        path.cubicTo(.8, -.75, -.8, -1.2, -.45, .5)
        path.cubicTo(-.2, .9, .5, -.55, .1, .2)
        path.cubicTo(.1, .65, .6, -.5, .5, .2)
        path.cubicTo(.55, .4, .8, .35, 1, .2)
        path.moveTo(-.85, .65)
        path.lineTo(.85, .5)
    elif kind == "heart":
        path.moveTo(0, .82)
        path.cubicTo(-1.7, -.3, -.8, -1.4, 0, -.52)
        path.cubicTo(.8, -1.4, 1.7, -.3, 0, .82)
    elif kind == "moon":
        path.moveTo(.7, -.75)
        path.cubicTo(-.9, -1.2, -1.4, .8, .2, .95)
        path.cubicTo(.55, 1, .85, .75, .95, .42)
        path.cubicTo(-.3, .66, -.4, -.58, .7, -.75)
    elif kind == "leaf":
        path.moveTo(-.8, .8)
        path.cubicTo(-1, -.45, .1, -1, .9, -.85)
        path.cubicTo(1.05, .35, .2, 1.15, -.8, .8)
        path.moveTo(-.7, .65)
        path.lineTo(.45, -.45)
    elif kind == "wave":
        for row in (-.5, 0, .5):
            path.moveTo(-1, row)
            path.cubicTo(-.6, row - .5, -.4, row + .5, 0, row)
            path.cubicTo(.4, row - .5, .6, row + .5, 1, row)
    elif kind == "sun":
        path.addEllipse(QRectF(-.46, -.46, .92, .92))
        for i in range(8):
            angle = i * math.pi / 4
            path.moveTo(math.cos(angle) * .7, math.sin(angle) * .7)
            path.lineTo(math.cos(angle), math.sin(angle))
    else:
        path.moveTo(0, -1)
        for x, y in ((.23, -.23), (1, 0), (.23, .23), (0, 1), (-.23, .23), (-1, 0), (-.23, -.23)):
            path.lineTo(x, y)
        path.closeSubpath()
    return path


SYMBOLS = {name: symbol_path(name) for name in ("heart", "moon", "sun", "wave", "leaf", "star", "eye", "dice", "wind", "signature")}
