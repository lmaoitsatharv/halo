"""Light-led lyric compositions: Cascade, Starline, Neon and Impact.

Each word's glow is drawn once into a bounded raster, so moving it only costs a blit. A frame
comes entirely from the timeline, the song position and the decoration clock, which leaves a
seek or a pause no stale state to unwind.
"""
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from functools import lru_cache
from itertools import groupby
import math
from operator import attrgetter
import random
from typing import NamedTuple
import zlib

import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                           QRadialGradient)

from .extra_lyrics import _alpha, _clamp, _hit, _mix, _neighbours, _smooth
from .lyric_rendering import symbol_kind


GLOW_RASTERS = 128
GLOW_PIXELS = 6_000_000
BLOOM_RESOLUTION = .34
HOT = QColor("#f4f4ef")
CASCADE_WORDS = 5
STAR_WORDS = 16
STAR_FLOATING_WORDS = 8
STAR_HOLD = .16       # share of a word gap the newly lit star keeps the line before it sets off
STAR_TRAVEL = 1.7     # the longest stroke, in the verse's typical gaps between words
STAR_SETTLE = .42     # seconds for a lit star and its word to cool once the next word takes over
STAR_CATCH = .07      # seconds to finish a stroke when a followed word begins before it was due
STAR_LINGER = .3      # a finished verse holds its sky this long into a break before fading
STAR_FADE = .7        # and fades over at most this long, gone before the next verse's first word
STAR_BLEND = .36      # verses that run straight on hand the sky over across this long
STAR_QUIET = .35      # the quiet lines of a break give way to the first star over this long
NEON_WORDS = 12
NEON_STRIKES = (.16, .9, .3, 1., .55, 1.)
NEON_STRIKE = .24
NEON_CHANGE = .18
IMPACT_LAND = .16
IMPACT_RING_SPAN = .2
IMPACT_RING_LIFE = .5


def _luminance(colour):
    def channel(value):
        return value / 12.92 if value <= .03928 else ((value + .055) / 1.055) ** 2.4
    return .2126 * channel(colour.redF()) + .7152 * channel(colour.greenF()) + .0722 * channel(colour.blueF())


def _soften(mask, radius):
    """Three box passes along each axis, which is close to a Gaussian of about this radius."""
    size = radius * 2 + 1
    for _ in range(6):
        total = np.cumsum(np.pad(mask, ((radius + 1, radius), (0, 0))), axis=0)
        mask = ((total[size:] - total[:-size]) / size).T
    return mask


def _bloom(shape, colour, width, height, resolution, origin, spread):
    """A tight glow inside a wide one, blurred from the word's small silhouette.

    Stroking wide outlines took up to 30 ms a word, which shows as a stutter at each entrance.
    """
    silhouette = QImage(width, height, QImage.Format.Format_Alpha8)
    silhouette.fill(0)
    ink = QPainter(silhouette)
    ink.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink.scale(resolution, resolution)
    ink.translate(origin)
    ink.setPen(Qt.PenStyle.NoPen)
    ink.setBrush(QColor("#ffffff"))
    ink.drawPath(shape.path)
    ink.end()
    rows = np.frombuffer(silhouette.constBits(), np.uint8).reshape(height, silhouette.bytesPerLine())
    mask = rows[:, :width].astype(np.float32) / 255
    reach = spread * resolution
    light = np.minimum(1, 1.5 * _soften(mask, max(1, round(reach * .1))) + 1.5 * _soften(mask, max(1, round(reach * .3))))
    # The window composites premultiplied, so each channel is scaled by the light itself.
    pixels = np.empty((height, width, 4), np.uint8)
    for channel, value in enumerate((colour.blueF(), colour.greenF(), colour.redF(), 1.)):
        pixels[..., channel] = light * value * 255
    return QPixmap.fromImage(QImage(pixels.data, width, height, width * 4, QImage.Format.Format_ARGB32_Premultiplied))


def _inked(shape, layer, colour, width, height, resolution, origin, floating):
    raster = QPixmap(width, height)
    raster.fill(Qt.GlobalColor.transparent)
    ink = QPainter(raster)
    ink.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink.scale(resolution, resolution)
    ink.translate(origin)

    def stroke(pen_colour, pen_width):
        ink.setPen(QPen(pen_colour, pen_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        ink.drawPath(shape.path)
    ink.setBrush(Qt.BrushStyle.NoBrush)
    if layer == "tube":
        if floating:
            stroke(_alpha(QColor("#000000"), .55), 3.2)
        stroke(colour, 1.2)
    else:
        # Only light ink needs help against a bright desktop; dark ink sits on its own block.
        if floating and _luminance(colour) > .179:
            stroke(_alpha(QColor("#000000"), .8), 3.8)
        ink.setPen(Qt.PenStyle.NoPen)
        ink.setBrush(colour)
        ink.drawPath(shape.path)
    ink.end()
    return raster


def _raster(canvas, shape, layer, colour):
    """A word's cached layer: "face" is solid, "tube" an outline and "bloom" a soft halo.

    Retain the shape with its raster, so recycled object IDs cannot collide. The entry and
    pixel limits bound memory at 24 MiB. None when the raster alone is over the pixel limit.
    Bloom is held small, as upscaling only softens it further.
    """
    dpr = canvas.devicePixelRatioF()
    floating = canvas.mode == "floating"
    key = (id(shape), layer, colour.rgba(), dpr, floating)
    cache = getattr(canvas, "_glow_rasters", None)
    if cache is None:
        cache = canvas._glow_rasters = OrderedDict()
        canvas._glow_pixels = 0
    entry = cache.get(key)
    if entry is not None:
        cache.move_to_end(key)
        return entry
    spread = _clamp(shape.bounds.height() * .52, 7, 46) if layer == "bloom" else 5
    resolution = dpr * BLOOM_RESOLUTION if layer == "bloom" else dpr
    padding = math.ceil(spread) + 3
    raster_w = max(1, math.ceil((shape.bounds.width() + padding * 2) * resolution))
    raster_h = max(1, math.ceil((shape.bounds.height() + padding * 2) * resolution))
    pixels = raster_w * raster_h
    if pixels > GLOW_PIXELS:
        return None
    origin = QPointF(padding - shape.bounds.left(), padding - shape.bounds.top())
    if layer == "bloom":
        raster = _bloom(shape, colour, raster_w, raster_h, resolution, origin, spread)
    else:
        raster = _inked(shape, layer, colour, raster_w, raster_h, resolution, origin, floating)
    entry = cache[key] = (shape, raster, pixels, padding, resolution)
    canvas._glow_pixels += pixels
    while len(cache) > GLOW_RASTERS or canvas._glow_pixels > GLOW_PIXELS:
        _, removed = cache.popitem(last=False)
        canvas._glow_pixels -= removed[2]
    return entry


def _stamp(canvas, p, shape, layer, colour, x, y, opacity=1, scale=1):
    """Centre a cached layer on a point; a word too big to cache still gets its face."""
    if opacity < .012:
        return
    entry = _raster(canvas, shape, layer, colour)
    if entry is None:
        if layer == "face":
            canvas._text(p, shape, x, y, colour, opacity, scale)
        return
    _, raster, _, padding, resolution = entry
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(_clamp(opacity))
    p.translate(x, y)
    p.scale(scale / resolution, scale / resolution)
    p.drawPixmap(QPointF((-shape.bounds.width() / 2 - padding) * resolution,
                         (-shape.bounds.height() / 2 - padding) * resolution), raster)
    p.restore()


def _halo(p, centre, radius, colour, opacity):
    gradient = QRadialGradient(centre, radius)
    gradient.setColorAt(0, _alpha(colour, opacity))
    gradient.setColorAt(.32, _alpha(colour, opacity * .36))
    gradient.setColorAt(1, _alpha(colour, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawEllipse(centre, radius, radius)


def _position(canvas):
    c = canvas.controller
    return c.position + c.offset / 1000


def _reduced(canvas):
    return bool(getattr(canvas.controller, "reduced_motion", False))


def _level(canvas):
    """Captured loudness, 0 when reactive audio is off; Reduce motion holds the last value, so it is ignored."""
    return 0. if _reduced(canvas) else _clamp(getattr(canvas.controller, "pulse", 0.))


def _sung(canvas, index, word_index):
    """The word holding the stage: the current one, or the last one through a gap inside a line."""
    words = canvas.timeline.display_words
    if not 0 <= word_index < len(words):
        return -1
    if words[word_index].text != "♪":
        return word_index
    inside_line = canvas.controller.lyrics.lines[index].text.strip()
    return word_index - 1 if inside_line and word_index and words[word_index - 1].text != "♪" else -1


def _hash01(value):
    return zlib.crc32(value.to_bytes(4, "little")) / 0xffffffff


def block_ink(colour):
    """The readable text colour for a highlight block, at the luminance where black and white cross."""
    return QColor("#000000") if _luminance(colour) > .179 else QColor("#ffffff")


def _block(p, x, y, width, height, grow, colour, opacity):
    """A slanted highlight that wipes in from the left."""
    slant, left, top = height * .14, x - width / 2, y - height / 2
    path = QPainterPath(QPointF(left + slant, top))
    path.lineTo(left + slant + width * grow, top)
    path.lineTo(left + width * grow, top + height)
    path.lineTo(left, top + height)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_alpha(colour, opacity))
    p.drawPath(path)


def _cascade_step(rank):
    """Scale, rise and opacity for a word this many places behind the newest; negative is still arriving."""
    if rank <= 0:
        return 1., rank * .9, 1 + rank
    settled = _smooth(rank)
    behind = max(0., rank - 1)
    return (1 - .4 * settled - .05 * behind, min(rank, 1.) * .98 + behind * .68,
            (1 - .16 * settled) * _clamp(1 - behind / (CASCADE_WORDS - 2)))


def _cascade(canvas, p, index, word_index, phase, transition):
    """Words climb a loose stack; the newest is large, lit on a block, with its symbol beside it."""
    active = _sung(canvas, index, word_index)
    if active < 0:
        _neighbours(canvas, p, index)
        return
    c, words = canvas.controller, canvas.timeline.display_words
    w, h = canvas.width(), canvas.height()
    size = canvas._base_size() * 1.3
    reduced = _reduced(canvas)
    shown = [i for i in range(active, -1, -1) if words[i].text != "♪"][:CASCADE_WORDS]
    lag = 0. if reduced else _clamp(active - canvas._word_visual, 0, 1)
    sway = 0. if reduced else math.sin(phase * 1.7) * min(2.5, h * .007)
    grow, pop = _smooth(transition), 1 + .05 * _level(canvas)
    ink = block_ink(c.primary)
    for rank in range(len(shown) - 1, -1, -1):
        i, word = shown[rank], words[shown[rank]]
        scale, rise, opacity = _cascade_step(rank - lag)
        scale *= pop if rank == 0 else 1
        y = h * .62 - rise * size + sway
        shape = canvas._shape(word.text, w * .8, size * 1.5, size, "center")
        width, height = shape.bounds.width() * scale, shape.bounds.height() * scale
        opacity *= canvas._edge_opacity(y, shape.bounds.height(), scale)
        symbol = symbol_kind(word.text) != "star"
        radius = size * .36 * scale if symbol else 0.
        half = width / 2 + (radius * 3.2 if symbol else 0)
        x = w / 2 + (_hash01(i) * 2 - 1) * min(w * .07, size * .8)
        x = _clamp(x, min(w / 2, half + 8), max(w / 2, w - half - 8))
        lit = 1 - _clamp((rank - lag) / .6)
        pad = max(5, size * .13)
        if lit > .02:
            _block(p, x, y, width + pad * 2, height + pad * 1.3, grow if rank == 0 else 1, c.primary, .94 * opacity * lit)
        # The ink swaps only once the block can carry it, so a fading block never holds dark text.
        dark = _smooth((lit - .5) / .4)
        if dark > .02:
            _stamp(canvas, p, shape, "face", ink, x, y, opacity * dark, scale)
        if dark < .98:
            _stamp(canvas, p, shape, "face", c.primary, x, y, opacity * (1 - dark), scale)
        if symbol and opacity > .012:
            canvas._symbol(p, word.text, x - width / 2 - pad - radius * 1.5, y, radius, opacity * .9, phase)
        _hit(canvas, shape, x, y, scale, word.line)


def star_groups(words, limit):
    """Display indexes per map, ending a map at a blank line or before a line that would overflow it."""
    groups, current = [], []

    def close():
        if current:
            groups.append(tuple(current))
            current.clear()
    for _, entries in groupby(enumerate(words), key=lambda entry: entry[1].line):
        real = [i for i, word in entries if word.text != "♪"]
        if not real:
            close()
        while real:
            if current and len(current) + len(real) > limit:
                close()
            current.extend(real[:limit])
            real = real[limit:]
    close()
    return groups


def star_label_side(field, k):
    """Which side of a star keeps its label off the thread: -1 above, 1 below."""
    near = [field[j][1] - field[k][1] for j in (k - 1, k + 1) if 0 <= j < len(field)]
    return -1 if sum(near) > 0 else 1


@lru_cache(maxsize=64)
def star_field(text, count):
    """Scatter stars over a unit box from the verse's text, so a repeated chorus redraws its own map.

    Each star stays within reach of the last and prefers open sky, so the thread wanders
    rather than crossing the whole map on every word.
    """
    chance = random.Random(zlib.crc32(text.encode("utf-8", "replace")))
    field = [(chance.uniform(.3, .7), chance.uniform(.25, .75))]
    for _ in range(count - 1):
        last, best, room = field[-1], None, -1.
        for _ in range(24):
            angle, reach = chance.uniform(0, math.tau), chance.uniform(.16, .38)
            x, y = last[0] + math.cos(angle) * reach, last[1] + math.sin(angle) * reach * 1.5
            if 0 <= x <= 1 and 0 <= y <= 1:
                space = min(math.hypot(x - a, (y - b) / 1.5) for a, b in field)
                if space > room:
                    best, room = (x, y), space
        field.append(best or (chance.random(), chance.random()))
    return tuple(field)


@lru_cache(maxsize=1)
def _star_path():
    path = QPainterPath()
    for point in range(8):
        reach, angle = 1 if point % 2 == 0 else .22, point * math.pi / 4
        vertex = QPointF(math.sin(angle) * reach, -math.cos(angle) * reach)
        path.lineTo(vertex) if point else path.moveTo(vertex)
    path.closeSubpath()
    return path


def _star_groups(canvas):
    """The song's maps and each word's map number, rebuilt only for a new timeline or surface."""
    limit = STAR_FLOATING_WORDS if canvas.mode == "floating" else STAR_WORDS
    state = getattr(canvas, "_star_state", None)
    if state is None or state[0] is not canvas.timeline or state[1] != limit:
        groups = star_groups(canvas.timeline.display_words, limit)
        state = canvas._star_state = (canvas.timeline, limit, groups,
                                      {i: g for g, ids in enumerate(groups) for i in ids})
    return state[2], state[3]


def _star_ink(canvas, p, point, size, colour, opacity):
    p.save()
    p.translate(point)
    p.scale(size, size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_alpha(colour, opacity))
    p.drawPath(_star_path())
    p.restore()


def star_tempo(onsets):
    """The verse's typical gap between word onsets: the pace its line travels at."""
    gaps = sorted(b - a for a, b in zip(onsets, onsets[1:]) if b - a > .02)
    return _clamp(gaps[len(gaps) // 2], .12, 1.2) if gaps else .45


def star_travel(lit, arrive, tempo):
    """(leave, arrive): the line sets off from a star lit at lit and reaches the next exactly at arrive.

    It holds a moment on the new star, and never takes longer than the verse's pace allows, so in
    a long gap it waits at the star and then travels rather than crawling the whole way.
    """
    gap = max(0., arrive - lit)
    return arrive - min(gap * (1 - STAR_HOLD), max(.16, tempo * STAR_TRAVEL)), arrive


def star_reach(position, leave, arrive):
    """How far along its stroke the line is: 0 as it leaves, and exactly 1 as the next word begins."""
    if position >= arrive:
        return 1.
    if position <= leave or arrive <= leave:
        return 0.
    t = (position - leave) / (arrive - leave)
    # Brisk off the star and easing toward the next, yet still moving as it lands, so the landing
    # reads as the beat rather than the line coming to rest and then a star appearing.
    return .35 * t + .35 * (1 - (1 - t) ** 2) + .3 * _smooth(t)


class StarIgnition(NamedTuple):
    """A star landing: its size against its lit size, the flash, the shock ring's progress, and its word."""
    scale: float
    flash: float
    ring: float | None
    label: float


def star_ignition(age, pop):
    """From a spark to a little over its size and home, with a flash and a ring, its word fading up."""
    age = max(0., age)
    t = _clamp(age / pop) - 1
    over = 1 + 2.7 * t ** 3 + 1.7 * t ** 2
    ring = age / (pop * 2.6)
    # The word follows the spark, so its glow never sits over the brightest moment of the flash.
    return StarIgnition(.3 + .7 * over, math.exp(-age / (pop * .55)), ring if ring < 1 else None,
                        _smooth((age - pop * .35) / (pop * 1.1)))


RESTED = StarIgnition(1., 0., None, 1.)


def _star_breaks(canvas, groups):
    """Map numbers that end at a break in the singing (a blank line), rather than running straight on."""
    words = canvas.timeline.display_words
    return {g for g in range(len(groups) - 1) if words[groups[g + 1][0]].line - words[groups[g][-1]].line > 1}


def star_presence(words, groups, breaks, number, position):
    """How much of a verse's sky is showing, from the clock alone, so every path through a frame agrees.

    Into a break it lingers on its last word, then fades, gone before the next verse's first star.
    A verse that runs straight on hands its sky over around the next verse's first word.
    """
    last = words[groups[number][-1]]
    if number + 1 >= len(groups):
        start, span = last.finish + STAR_LINGER, STAR_FADE
    else:
        following = words[groups[number + 1][0]].begin
        if number in breaks:
            end = min(last.finish + STAR_LINGER + STAR_FADE, following)
            span = min(STAR_FADE, max(.12, end - last.begin - .1))
            start = end - span
        else:
            lead = _clamp(following - last.begin - .25, 0, STAR_BLEND * .6)
            start, span = following - lead, STAR_BLEND
    return 1 - _smooth((position - start) / span)


def _thread(canvas, p, points, colour, width, opacity):
    """The verse's finished line: a soft glow under a fine bright core."""
    if len(points) < 2 or opacity < .012:
        return
    trail = QPolygonF(points)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if canvas.mode == "floating":
        p.setPen(QPen(_alpha(QColor("#000000"), .45 * opacity), width + 2.4, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(trail)
    p.setPen(QPen(_alpha(colour, .1 * opacity), width * 4.5, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline(trail)
    p.setPen(QPen(_alpha(colour, .62 * opacity), width, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline(trail)


def _stroke(canvas, p, start, tip, colour, width, opacity, level):
    """The line on its way: it brightens toward its tip, and nothing rides on the end of it."""
    if opacity < .012 or (tip - start).manhattanLength() < .5:
        return
    hot = _mix(colour, HOT, .55 + .25 * level)

    def pen(alpha_tail, alpha_tip, size):
        gradient = QLinearGradient(start, tip)
        gradient.setColorAt(0, _alpha(colour, alpha_tail * opacity))
        gradient.setColorAt(.7, _alpha(colour, (alpha_tail + alpha_tip) * .5 * opacity))
        gradient.setColorAt(1, _alpha(hot, alpha_tip * opacity))
        return QPen(gradient, size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if canvas.mode == "floating":
        p.setPen(QPen(_alpha(QColor("#000000"), .45 * opacity), width + 2.4, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(start, tip)
    p.setPen(pen(.1, .26, width * 5))
    p.drawLine(start, tip)
    p.setPen(pen(.62, 1., width * 1.15))
    p.drawLine(start, tip)


def _glint(p, point, length, colour, opacity):
    """Four fine rays thrown out by a landing star, fading along their length."""
    if opacity < .02 or length < 1:
        return
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        end = point + QPointF(dx * length, dy * length)
        gradient = QLinearGradient(point, end)
        gradient.setColorAt(0, _alpha(colour, opacity))
        gradient.setColorAt(1, _alpha(colour, 0))
        p.setPen(QPen(gradient, max(1., length * .045), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(point, end)


def _lerp(a, b, amount):
    return a + (b - a) * amount


def _star_map(canvas, p, ids, reach, phase, presence, live, age=0., following=None):
    """One verse's sky, lit up to star number reach.

    A live map also draws the line on its way to the next star, timed to land as that word begins.
    age is how long the newest word has sounded; following is when the word after this map begins.
    """
    c, words = canvas.controller, canvas.timeline.display_words
    w, h = canvas.width(), canvas.height()
    base = canvas._base_size()
    reduced = _reduced(canvas)
    position = _position(canvas)
    level = _level(canvas)
    field = star_field(" ".join(words[i].text for i in ids), len(ids))
    points = [QPointF(w * (.1 + .8 * x), h * (.15 + .58 * y)) for x, y in field]
    onsets = [words[i].begin for i in ids]
    tempo = star_tempo(onsets)
    pop = _clamp(tempo * .7, .16, .34)
    lit_at = position - age if live else onsets[reach]
    # The stroke into the newest star is whole, or finishes quickly if its word came early.
    into = 1.
    if live and reach and not reduced:
        due = star_reach(lit_at, *star_travel(onsets[reach - 1], onsets[reach], tempo))
        into = due + (1 - due) * _smooth(age / STAR_CATCH)
    out = 0.
    if live and not reduced and reach + 1 < len(ids):
        # Held just short until its word begins, so a late word never leaves a line ending in empty sky.
        out = min(.985, star_reach(position, *star_travel(lit_at, onsets[reach + 1], tempo)))
    if out > 0:
        tip = points[reach] + (points[reach + 1] - points[reach]) * out
    elif into < 1:
        tip = points[reach - 1] + (points[reach] - points[reach - 1]) * into
    else:
        tip = points[reach]
    # The sky leans a little toward the line, with a slow drift under it.
    centre = QPointF(w / 2, h / 2)
    pan = QPointF() if reduced else (tip - centre) * .1 + QPointF(math.sin(phase * .31) * min(6, w * .008),
                                                                  math.cos(phase * .23) * min(4, h * .008))
    points = [point - pan for point in points]
    tip -= pan
    width = max(1., base * .026)
    if into < 1:
        _thread(canvas, p, points[:reach], c.primary, width, presence)
        _stroke(canvas, p, points[reach - 1], tip, c.primary, width, presence, level)
    else:
        _thread(canvas, p, points[:reach + 1], c.primary, width, presence)
        if out > 0:
            _stroke(canvas, p, points[reach], tip, c.primary, width, presence, level)
    for k in range(reach + 1):
        point, word = points[k], words[ids[k]]
        current = live and k == reach
        hero = symbol_kind(word.text) != "star"
        twinkle = 1. if reduced else .74 + .26 * math.sin(phase * 2.4 + k * 1.7)
        # A star cools once the next word takes over: smaller, in the song's colour, its word set back.
        if current:
            cool = 0.
        elif reduced:
            cool = 1. if k < reach or live else 0.
        elif live and k == reach - 1:
            cool = _smooth(age / STAR_SETTLE)
        else:
            later = onsets[k + 1] if k + 1 < len(ids) else following
            cool = 0. if later is None else _smooth((position - later) / STAR_SETTLE)
        land = star_ignition(age, pop) if current and not reduced else RESTED
        size = _lerp(base * .26, base * (.17 if hero else .11), cool)
        colour = _mix(HOT, c.primary, cool)
        if cool < 1:
            _halo(p, point, base * (.62 + .3 * level), c.primary, .6 * (1 - cool) * (1 - .5 * land.flash) * presence)
        if land.flash > .02:
            _halo(p, point, base * (.16 + .26 * land.flash), _mix(c.primary, HOT, .85), .95 * land.flash * presence)
        if land.ring is not None:
            ring = base * (.28 + 1.05 * (1 - (1 - land.ring) ** 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_alpha(_mix(c.primary, HOT, .4), (1 - land.ring) ** 2 * .5 * presence), 1.))
            p.drawEllipse(point, ring, ring)
        _glint(p, point, base * (.3 + .95 * land.flash) * land.scale, _mix(c.primary, HOT, .8),
               .9 * land.flash * presence)
        _star_ink(canvas, p, point, size * land.scale, colour, presence * _lerp(1., .9 * twinkle, cool))
        lettering = base * .86
        shape = canvas._shape(word.text, w * .42, lettering * 1.5, lettering, "center")
        scale = _lerp(1., .64 if hero else .46, cool) * (.88 + .12 * land.label)
        half_w, half_h = shape.bounds.width() * scale / 2, shape.bounds.height() * scale / 2
        side = star_label_side(field, k)
        x = _clamp(point.x(), min(w / 2, half_w + 3), max(w / 2, w - half_w - 3))
        # The word rises out from its star as it lands.
        y = point.y() + side * (size + half_h + 2) - side * (1 - land.label) * base * .16
        y = _clamp(y, half_h + 3, h - half_h - 3)
        show = presence * land.label
        if cool < 1:
            # The glow comes up after the letters, so a word fading in never reads as a grey smudge.
            _stamp(canvas, p, shape, "bloom", c.primary, x, y, .7 * (1 - cool) * show * land.label ** 2, scale)
        _stamp(canvas, p, shape, "face", colour, x, y, show * _lerp(1., .86 if hero else .6, cool), scale)
        if live:
            _hit(canvas, shape, x, y, scale, word.line)


def _latest_group(words, groups, position):
    """The last map whose first word has begun, or -1 before the first verse."""
    return bisect_right([words[ids[0]].begin for ids in groups], position) - 1


def _starline(canvas, p, index, word_index, phase):
    """Each word lands as a star where the line arrives, timed to the singing; a verse clears for the next."""
    words, position = canvas.timeline.display_words, _position(canvas)
    groups, owner = _star_groups(canvas)
    breaks = _star_breaks(canvas, groups)
    reduced = _reduced(canvas)
    active = _sung(canvas, index, word_index)
    w, h = canvas.width(), canvas.height()

    def following(number):
        return words[groups[number + 1][0]].begin if number + 1 < len(groups) else None

    def leaving(number, presence):
        """A verse on its way out, lit to its last star and drifting a little toward the viewer."""
        away = 1 - presence
        p.save()
        p.translate(w / 2, h / 2)
        p.scale(1 + .12 * away, 1 + .12 * away)
        p.translate(-w / 2, -h / 2)
        _star_map(canvas, p, groups[number], len(groups[number]) - 1, phase, presence, False,
                  following=following(number))
        p.restore()
    if active < 0:
        # A break: the last verse's sky lingers, then fades as the quiet lines come up around the gap.
        number = _latest_group(words, groups, position) if groups else -1
        presence = 0. if number < 0 or reduced else star_presence(words, groups, breaks, number, position)
        if presence > .012:
            leaving(number, presence)
        _neighbours(canvas, p, index, 1 - presence)
        return
    number = owner[active]
    ids = groups[number]
    if not reduced:
        since = position - words[ids[0]].begin
        if number == 0 or number - 1 in breaks:
            # The quiet lines of the break give way as the verse's first star lands.
            _neighbours(canvas, p, words[ids[0]].line - 1, 1 - _smooth(since / STAR_QUIET))
        else:
            before = star_presence(words, groups, breaks, number - 1, position)
            if before > .012:
                leaving(number - 1, before)
    presence = 1. if reduced else star_presence(words, groups, breaks, number, position)
    _star_map(canvas, p, ids, bisect_left(ids, active), phase, presence, True,
              max(0., canvas.word_elapsed(active, position)), following(number))


def neon_flicker(age):
    """How lit a tube is this long after it was struck: a few fast blinks, then steady."""
    if age >= NEON_STRIKE:
        return 1.
    return NEON_STRIKES[int(max(0., age) / NEON_STRIKE * len(NEON_STRIKES))]


def _neon_pages(canvas, line):
    """A line's words, split so a long line lights one short sign at a time."""
    words = canvas.timeline.display_words
    ids = range(bisect_left(words, line, key=attrgetter("line")), bisect_right(words, line, key=attrgetter("line")))
    real = [i for i in ids if words[i].text != "♪"]
    return [real[start:start + NEON_WORDS] for start in range(0, len(real), NEON_WORDS)]


def _neon_layout(canvas, ids):
    """Centred rows of words as (display index, shape, x, y, scale), shrunk as one sign to fit."""
    words = canvas.timeline.display_words
    w, h = canvas.width(), canvas.height()
    size, row_width = canvas._base_size() * 1.2, w * .86
    gap, lead = size * .3, size * 1.24
    rows = [[]]
    used = 0.
    for i in ids:
        shape = canvas._shape(words[i].text, row_width, size * 1.5, size, "center")
        width = max(6., shape.bounds.width())
        if rows[-1] and used + gap + width > row_width:
            rows.append([])
            used = 0.
        rows[-1].append((i, shape, width))
        used += width + (gap if len(rows[-1]) > 1 else 0)
    scale = min(1., h * .78 / (lead * len(rows)))
    placed = []
    for k, row in enumerate(rows):
        total = sum(entry[2] for entry in row) + gap * (len(row) - 1)
        x = w / 2 - total * scale / 2
        y = h * .5 + (k - (len(rows) - 1) / 2) * lead * scale
        for i, shape, width in row:
            placed.append((i, shape, x + width * scale / 2, y, scale))
            x += (width + gap) * scale
    return placed


def _neon_sign(canvas, p, ids, active, phase, tube, lit, drop, live):
    """One sign: unlit tubes everywhere, with light in every word up to the active one."""
    c, words = canvas.controller, canvas.timeline.display_words
    reduced, position, level = _reduced(canvas), _position(canvas), _level(canvas)
    warm, hot = _mix(c.primary, HOT, .2), _mix(c.primary, HOT, .84)
    for i, shape, x, y, scale in _neon_layout(canvas, ids):
        y += drop
        sung = i <= active
        _stamp(canvas, p, shape, "tube", c.primary, x, y, (.2 if sung else .55) * tube, scale)
        if sung:
            word, current = words[i], i == active
            age = canvas.word_elapsed(i, position)
            pace = NEON_STRIKE / max(.05, (word.finish - word.begin) * .6)
            hum = 1. if reduced else .94 + .06 * math.sin(phase * 11 + i * 1.9)
            strike = 1. if reduced else neon_flicker(age * max(1., pace))
            glow = (1 if current else .66) * strike * hum * lit
            _stamp(canvas, p, shape, "bloom", c.primary, x, y, glow * (.8 + .2 * level), scale)
            _stamp(canvas, p, shape, "face", hot if current else warm, x, y, glow if current else glow * 1.4, scale)
        if live:
            _hit(canvas, shape, x, y, scale, words[i].line)


def _neon(canvas, p, index, word_index, phase):
    """The line waits as unlit glass, and each sung word strikes on and stays lit."""
    words, lines = canvas.timeline.display_words, canvas.controller.lyrics.lines
    pages = _neon_pages(canvas, index) if index >= 0 else []
    if not pages:
        _neighbours(canvas, p, index)
        return
    active = word_index if word_index >= 0 and words[word_index].text != "♪" else -1
    page = max(0, min(len(pages) - 1, bisect_right([ids[0] for ids in pages], active) - 1))
    position = _position(canvas)
    since = position - (words[pages[page][0]].begin if page else lines[index].time)
    change = 1. if _reduced(canvas) else _smooth(since / NEON_CHANGE)
    if change < 1:
        before = pages[page - 1] if page else (_neon_pages(canvas, index - 1) or [[]])[-1]
        if before:
            fade = (1 - change) ** 2
            _neon_sign(canvas, p, before, before[-1], phase, fade, fade, -canvas.height() * .08 * change, False)
    _neon_sign(canvas, p, pages[page], active, phase, change, 1., (1 - change) * canvas.height() * .03, True)


class ImpactPose(NamedTuple):
    """How a word lands: its scale and opacity, the colour split, and the ring's progress or None."""
    scale: float
    opacity: float
    split: float
    ring: float | None


def impact_pose(age, span, pulse, reduced):
    """A word falls in from above the screen, dents on landing, and sits a little larger when loud."""
    if reduced:
        return ImpactPose(1., 1., 0., None)
    land = _clamp(age / min(IMPACT_LAND, max(.05, span * .6)))
    fall = (1 - land) ** 3
    dent = math.sin(math.pi * _clamp((age - IMPACT_LAND) / IMPACT_LAND)) * .035
    ring = age / IMPACT_RING_LIFE if span >= IMPACT_RING_SPAN and age < IMPACT_RING_LIFE else None
    return ImpactPose(1 + .62 * fall - dent + .05 * _clamp(pulse), _smooth(land * 2.5), fall, ring)


def _impact(canvas, p, index, word_index, phase, transition):
    """One huge word at a time, thrown at the screen with a shockwave and a colour split."""
    active = _sung(canvas, index, word_index)
    if active < 0:
        _neighbours(canvas, p, index)
        return
    c, words = canvas.controller, canvas.timeline.display_words
    w, h = canvas.width(), canvas.height()
    size = canvas._base_size() * 1.9
    word = words[active]
    reduced, level = _reduced(canvas), _level(canvas)
    age = max(0., canvas.word_elapsed(active, _position(canvas)))
    pose = impact_pose(age, word.finish - word.begin, level, reduced)
    shape = canvas._word_shape(word.text, w * .84, h * .5, size)
    unit = min(14, w * .016)
    x = w / 2 + math.sin(age * 61) * unit * pose.split
    y = h * .5 + math.cos(age * 47) * unit * .6 * pose.split
    scale = pose.scale * (1. if reduced else 1 + .012 * math.sin(phase * 2.3))
    last = canvas._previous_word
    if not reduced and transition < 1 and 0 <= last < len(words) and words[last].text != "♪":
        gone = canvas._word_shape(words[last].text, w * .84, h * .5, size)
        _stamp(canvas, p, gone, "bloom", c.primary, w / 2, h * .5, (1 - transition) * .8, 1 + .5 * transition)
    if pose.ring is not None:
        for delay in (0., .22):
            wave = _clamp((pose.ring - delay) / (1 - delay))
            if wave > 0:
                _stamp(canvas, p, shape, "tube", c.primary, w / 2, h * .5, (1 - wave) ** 2 * .9,
                       1 + 1.1 * (1 - (1 - wave) ** 3))
    _stamp(canvas, p, shape, "bloom", c.primary, x, y, (.55 + .45 * level + .45 * pose.split) * pose.opacity, scale)
    if pose.split > .02:
        apart = unit * 2.4 * pose.split
        _stamp(canvas, p, shape, "face", c.secondary, x - apart, y + apart * .3, .7 * pose.opacity, scale)
        _stamp(canvas, p, shape, "face", c.primary, x + apart, y - apart * .3, .7 * pose.opacity, scale)
    _stamp(canvas, p, shape, "face", _mix(c.primary, HOT, .8), x, y, pose.opacity, scale)
    _hit(canvas, shape, x, y, min(1., scale), word.line)


def paint_glow_mode(canvas, p, style, index, word_index, phase, transition):
    if style == "lyric_cascade":
        _cascade(canvas, p, index, word_index, phase, transition)
    elif style == "lyric_starline":
        _starline(canvas, p, index, word_index, phase)
    elif style == "lyric_neon":
        _neon(canvas, p, index, word_index, phase)
    else:
        _impact(canvas, p, index, word_index, phase, transition)
