"""Native lyric typography with source word timings or explicit line estimates.

The original mode names follow the Verci-inspired modes documented by the independent
theaestheticslyrics project. The linked official site (https://verci.xyz) was
unreachable during research, so these animations are Halo's own interpretation.
Ordinary LRC supplies line timestamps only; estimates remain a fallback.
"""
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import math
import re

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainterPath, QTextLayout, QTextOption, QTransform
from .models import lyric_word_matches, validate_lyric_lines
from .word_pace import estimated_words
from .extra_lyrics import EXTRA_LYRIC_STYLES
from .svg_path import icon_path
from .symbol_lexicon import KINDS, WEAK_WORDS, WORD_KINDS


LYRIC_STYLES = (
    ("ship_visual", "Ship", "Flowing full lines with delicate illustrations and a quiet, spacious focus."),
    ("fisheye_visual", "Fisheye", "The flowing word lens with expressive illustrated symbols."),
    ("visual", "Visual", "One bold word at a time, paired with a floating symbol."),
) + EXTRA_LYRIC_STYLES
FLOW_SECONDS = .35
LYRIC_STYLE_ALIASES = {"ship": "ship_visual", "fisheye": "fisheye_visual"}


def canonical_lyric_style(value):
    """Preserve old saved choices while exposing only the illustrated modes."""
    if not isinstance(value, str):
        return "fisheye_visual"
    value = LYRIC_STYLE_ALIASES.get(value, value)
    return value if value in {item[0] for item in LYRIC_STYLES} else "fisheye_visual"


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
    """Honor supplied word boundaries; otherwise estimate each line's words at the song's own pace."""
    def __init__(self, lines, duration=0):
        validate_lyric_lines(lines)
        self.words = []
        self.ranges = []
        self.timed_lines = set()
        estimates = estimated_words(lines, duration)
        for i, line in enumerate(lines):
            matches, spans = estimates[i]
            end_time = (line.end if line.end is not None else
                        lines[i + 1].time if i + 1 < len(lines) else max(line.time + 4, duration))
            start = len(self.words)
            if line.words:
                self.timed_lines.add(i)
                offset = 0
                for j, segment in enumerate(line.words):
                    # Segment whitespace belongs to the source line, but the
                    # glyph animation only needs visible characters.
                    text = segment.text.strip()
                    leading = len(segment.text) - len(segment.text.lstrip())
                    finish = (segment.end if segment.end is not None else
                              line.words[j + 1].start if j + 1 < len(line.words) else end_time)
                    if text:
                        self.words.append(Word(text, i, offset + leading, offset + leading + len(text),
                                               segment.start, max(segment.start, finish)))
                    offset += len(segment.text)
                if len(self.words) == start:
                    self.words.append(Word("♪", i, 0, 0, line.time, end_time))
                self.ranges.append((start, len(self.words)))
                continue
            for match, (begin, finish) in zip(matches, spans):
                self.words.append(Word(match.group(), i, match.start(), match.end(), begin, finish))
            if not matches:
                self.words.append(Word("♪", i, 0, 0, line.time, end_time))
            self.ranges.append((start, len(self.words)))
        # Keep source-word indexes/times intact. The display gets an extra
        # invisible slot when a line starts before its first actual word.
        self.display_words = []
        self._display_indexes = []
        self._leading_gaps = {}
        for i, (start, end) in enumerate(self.ranges):
            if i in self.timed_lines and self.words[start].begin > lines[i].time:
                self._leading_gaps[i] = len(self.display_words)
                self.display_words.append(Word("♪", i, 0, 0, lines[i].time, self.words[start].begin))
            for word in self.words[start:end]:
                self._display_indexes.append(len(self.display_words))
                self.display_words.append(word)

    def at(self, line, position):
        if line < 0 or not self.ranges:
            return -1, 0.0
        start, end = self.ranges[min(line, len(self.ranges) - 1)]
        if line in self.timed_lines and position < self.words[start].begin:
            return -1, 0.0
        index = max(start, min(end - 1, bisect_right([w.begin for w in self.words[start:end]], position) + start - 1))
        word = self.words[index]
        span = word.finish - word.begin
        if line in self.timed_lines:
            # Short syllables are valid source intervals. A display minimum
            # must not stretch their progress beyond the declared end.
            progress = (position - word.begin) / span if span > 0 else float(position >= word.begin)
        else:
            progress = (position - word.begin) / max(.04, span)
        return index, clamp(progress)

    def flowing(self, word_index, position):
        """A position that moves towards the next word just before it is sung, for timing known in advance."""
        words = self.display_words
        following = words[word_index + 1] if word_index + 1 < len(words) else None
        if following is None or following.line != words[word_index].line or following.text == "♪":
            return float(word_index)
        reach = min(following.begin - words[word_index].begin, FLOW_SECONDS)
        return word_index + smooth((position - following.begin + reach) / reach) if reach > 0 else float(word_index)

    def display_word(self, line, ordinal):
        """The display index of a line's word, by its place in the line."""
        start, end = self.ranges[line]
        return self._display_indexes[min(start + ordinal, end - 1)]

    def display_at(self, line, position):
        """Focus a blank slot during breaks, retaining the surrounding lyrics."""
        if line < 0 or not self.ranges:
            return -1, -1, 0.0
        line = min(line, len(self.ranges) - 1)
        word_index, fraction = self.at(line, position)
        if word_index < 0:
            return line, self._leading_gaps.get(line, -1), 0.0
        return line, self._display_indexes[word_index], fraction


@dataclass
class TextShape:
    path: QPainterPath
    bounds: QRectF
    word_boxes: list
    pixels: int
    first_line_center: float = 0.


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
                first_line = QPainterPath()
                for run in layout.glyphRuns():
                    raw = run.rawFont()
                    for glyph, position in zip(run.glyphIndexes(), run.positions()):
                        glyph_path = raw.pathForGlyph(glyph)
                        glyph_path.translate(position)
                        path.addPath(glyph_path)
                        if rows and position.y() < rows[0].height() * 1.07:
                            first_line.addPath(glyph_path)
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
                    first_line = transform.map(first_line)
                    boxes = [(a, b, transform.mapRect(box)) for a, b, box in boxes]
                first_center = (first_line.boundingRect().center().y() if not first_line.isEmpty()
                                else path.boundingRect().center().y())
                result = TextShape(path, path.boundingRect(), boxes, pixels, first_center)
                break
        self.items[key] = result
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return result


def alpha(color, opacity):
    value = QColor(color)
    value.setAlphaF(clamp(opacity))
    return value


# Endings tried in turn on a word that is not listed, each with what the stem may have lost
# before it: a final e (danc-ing, lov-in, di-ed), a y (sk-ies), or nothing, as in a plain plural.
# The e comes back first, and -s is tried before -es, so "caring" and "cares" find care rather
# than car. -ing and -ed can also double the stem's last consonant (swimm-ing, dropp-ed).
_ENDINGS = (("'s", ("",)), ("’s", ("",)), ("ing", ("e", "")), ("in", ("e", "")), ("ed", ("e", "")),
            ("s", ("",)), ("es", ("",)), ("ies", ("y",)))
_DOUBLING_ENDINGS = ("ing", "ed")


def _lexicon_word(word):
    """The listed word a lyric word stands for, exactly or with an ending removed, else None."""
    value = word.lower().strip(".,!?;:'\"’()“”…—")
    if value in WORD_KINDS:
        return value
    for ending, restored in _ENDINGS:
        if value.endswith(ending):
            stem = value[:-len(ending)]
            candidates = [stem + letter for letter in restored]
            if ending in _DOUBLING_ENDINGS and stem[-2:-1] == stem[-1:] and stem[-1:] not in "aeiou":
                candidates.append(stem[:-1])
            for candidate in candidates:
                if len(candidate) >= 3 and candidate in WORD_KINDS:
                    return candidate
    return None


@lru_cache(maxsize=1024)
def symbol_kind(word):
    """The illustration kind for a lyric word, or the star fallback."""
    base = _lexicon_word(word)
    return WORD_KINDS[base] if base else "star"


@lru_cache(maxsize=256)
def line_symbol_kind(text):
    """Choose one deliberate illustration per cue, independent of word timing.

    Concrete imagery wins over common pronouns, so "you and the ocean" gets
    waves rather than a heart. The bounded cache only sees validated lyrics.
    """
    candidates = []
    for match in re.finditer(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text.lower()):
        word = match.group()
        kind = symbol_kind(word)
        if kind != "star":
            priority = 0 if _lexicon_word(word) in WEAK_WORDS else 1
            candidates.append((priority, kind))
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else "star"


def symbol_path(kind):
    """The Lucide outline for a kind, in a unit box around the origin; unknown kinds raise KeyError."""
    from .lucide_data import ICONS
    return icon_path(ICONS[KINDS[kind]])


class SymbolPaths(Mapping[str, QPainterPath]):
    """Symbol outlines by kind, each built the first time it is asked for."""
    def __init__(self):
        self._paths = {}

    @property
    def built(self):
        return len(self._paths)

    def __getitem__(self, kind):
        path = self._paths.get(kind)
        if path is None:
            path = self._paths[kind] = symbol_path(kind)
        return path

    def __contains__(self, kind):
        return kind in KINDS

    def __iter__(self):
        return iter(KINDS)

    def __len__(self):
        return len(KINDS)


SYMBOLS = SymbolPaths()
