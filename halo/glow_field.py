"""Neon and Liquid: halo lights evaluated per pixel as a light field.

One model draws them on the desktop overlay, in immersive view and in every
preview. Each frame evaluates the light in four thin strips along the rounded
screen edge, at up to display resolution, and draws them with smooth scaling.
Geometry that depends only on the screen and the glow spread is cached; the
animation changes small per-perimeter tables and fourteen drops.
"""
from bisect import bisect_left, bisect_right
from functools import lru_cache
import math
import time
import zlib

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from .glow_field_gpu import shared_field_renderer
from .momentum import light_share


FIELD_HALO_MODES = (
    ("neon", "Neon", "A glass tube just inside the bezel with a white-hot filament. It strikes on when a song starts."),
    ("liquid", "Liquid", "Glossy drops of light cling to the edges, drift, pinch off and merge, mixing your two colours."),
)
FIELD_HALO_IDS = frozenset(spec[0] for spec in FIELD_HALO_MODES)

_TAU = math.tau
_RADIUS = 16.
_LOOP_SECONDS = 26.28       # one phase loop at the default motion speed
_CPU_PIXEL_BUDGET = 60_000  # NumPy fallback: rendered pixels per frame across the four strips
_GPU_PIXEL_BUDGET = 2_500_000
_TABLE = 4096               # perimeter samples for colour and striation tables
_DROP_SPEED = (1, -1, 2, -1, 1, -2, 1, -1, 2, 1, -2, -1, 1, -1, 2, -1, 1, -2, 1, 1, -1, 2, -1, -2)
_DROP_RISE = (2, 3, 2, 4, 3, 2, 3, 4, 2, 5, 3, 4, 3, 2, 4, 3, 5, 2, 3, 4, 2, 3, 5, 4)
# Neon's four tubes (top, right, bottom, left) behave like tubelights that
# sometimes fail to start: a random group goes dark, flashes a few times and
# catches, taking a random time. Starts land on the song: on its lyric lines
# when it has synced lyrics, otherwise on a pattern along its own timeline, so
# a song plays the same light show each time. With React to audio, a
# struggling tube's flashes fall on the beat.
_LINE_START_CHANCE, _WORD_START_CHANCE = .85, .55
_WORD_START_GAP = 1.4       # seconds between start points inside one line
_FREE_START_SPACING, _FREE_START_CHANCE = 2.8, .75
_PREVIEW_START_SPACING = 2.5
_START_LONGEST = 4.6        # longest struggle, per-tube stretch, delay and one late dip
# One drop per this much rim (px), 8 to 24 drops, so their light per length of
# edge is the same on every screen size, as the other modes' light is.
_DROP_SPACING = 284.
# Calibrated against the original modes so the same intensity, rim width, glow
# spread and glow opacity give the same light.
NEON_TUBE, NEON_FILAMENT, NEON_GLASS, NEON_WHITE, NEON_GLOW, NEON_HAZE = .85, .7, .7, .5, .55, .45
LIQUID_FILM, LIQUID_DROP_LENGTH, LIQUID_DROP_GROWTH, LIQUID_BODY, LIQUID_GLOW = 1., 46., .3, .35, 1.35


def _unit_vector(*values):
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


# Liquid's wet-gel lighting: a key light from the upper left, a faint second one.
_KEY = _unit_vector(-.45, -.65, .62)
_SHINE = _unit_vector(*(_KEY + np.array((0., 0., 1.), dtype=np.float32)))
_SHINE2 = _unit_vector(*(_unit_vector(.55, .5, .66) + np.array((0., 0., 1.), dtype=np.float32)))


def _hash(x):
    value = math.sin(x * 127.1 + 3.7) * 43758.5453
    return value - math.floor(value)


def _light_colour(colour, brightness):
    """Premultiplied light energy, exactly as the other halo modes read a colour.

    A dark colour makes dim light and black makes none; each colour's own
    brightness control scales it.
    """
    red, green, blue, alpha = QColor(colour).getRgbF()
    level = max(0., min(1., brightness / 100)) * alpha
    return np.array((red, green, blue), dtype=np.float32) * level


def _normalised(colour):
    """Split light into its colour at full energy and that energy, per table entry."""
    energy = colour.max(axis=1)
    lit = energy > 1e-6
    unit = np.zeros_like(colour)
    unit[lit] = colour[lit] / energy[lit, None]
    return unit, energy.astype(np.float32)


def _palette_amount(coordinate, proportion, softness):
    if proportion <= 0:
        return np.ones_like(coordinate)
    if proportion >= 1:
        return np.zeros_like(coordinate)
    coordinate = coordinate % 1.
    transition = min(softness, proportion, 1. - proportion)
    t = np.clip((np.minimum(coordinate, 1. - coordinate) - proportion * .5) / transition + .5, 0., 1.)
    return t * t * (3. - 2. * t)


def _whiten(colour, energy, amount):
    """Mix toward white of the colour's own energy, so black never turns white."""
    return colour + (energy - colour) * amount


def _knee(value):
    """Highlights roll off softly; a saturated channel caps first, so cores turn white-hot."""
    over = value > .8
    if over.any():
        value = value.copy()
        value[over] = .8 + .2 * (1. - np.exp(-(value[over] - .8) / .2))
    return value


def _rim_point(w, h, s, depth):
    """Point and clockwise tangent at perimeter fraction s, depth pixels inside the rim."""
    r = min(_RADIUS, min(w, h) / 4)
    straight_w, straight_h = w - 2 * r, h - 2 * r
    arc = math.pi * r / 2
    distance = (s % 1.) * (2 * (straight_w + straight_h) + 4 * arc)
    straights = ((r, 0., 1, 0, 0, 1, straight_w), (w, r, 0, 1, -1, 0, straight_h),
                 (w - r, h, -1, 0, 0, -1, straight_w), (0., h - r, 0, -1, 1, 0, straight_h))
    corners = ((w - r, r, -math.pi / 2), (w - r, h - r, 0.), (r, h - r, math.pi / 2), (r, r, math.pi))
    for (x, y, dx, dy, nx, ny, size), (cx, cy, angle) in zip(straights, corners):
        if distance <= size:
            return x + dx * distance + nx * depth, y + dy * distance + ny * depth, dx, dy
        distance -= size
        if distance <= arc:
            theta = angle + distance / r
            return (cx + (r - depth) * math.cos(theta), cy + (r - depth) * math.sin(theta),
                    -math.sin(theta), math.cos(theta))
        distance -= arc
    return r, depth, 1., 0.


def strip_layout(w, h, band, scale):
    """The four edge strips in render pixels: scales and (c0, c1, r0, r1) blocks.

    The light ends at the glow spread, so nothing is evaluated beyond it.
    """
    cols, rows = max(1, round(w * scale)), max(1, round(h * scale))
    sx, sy = cols / w, rows / h
    reach = min(band + 1., min(w, h) / 2)
    depth_rows, depth_cols = min(math.ceil(reach * sy), rows // 2), min(math.ceil(reach * sx), cols // 2)
    blocks = ((0, cols, 0, depth_rows), (0, cols, rows - depth_rows, rows),
              (0, depth_cols, depth_rows, rows - depth_rows), (cols - depth_cols, cols, depth_rows, rows - depth_rows))
    return sx, sy, tuple(block for block in blocks if block[1] > block[0] and block[3] > block[2])


@lru_cache(maxsize=6)
def _geometry(w, h, band, scale):
    """Per-pixel geometry for the four edge strips at one render scale.

    Each pixel knows its depth inside the rounded rim, its distance along the
    perimeter as seen from the nearest horizontal and vertical edge, and a
    soft corner weight between them, so light meets on the diagonal smoothly.
    """
    r = min(_RADIUS, min(w, h) / 4)
    length = 2 * (w + h - 4 * r) + _TAU * r
    arc = math.pi * r / 2
    straight_w, straight_h = w - 2 * r, h - 2 * r
    sx, sy, blocks = strip_layout(w, h, band, scale)
    strips = []
    for c0, c1, r0, r1 in blocks:
        xs = (np.arange(c0, c1, dtype=np.float32) + .5) / sx
        ys = (np.arange(r0, r1, dtype=np.float32) + .5) / sy
        x, y = np.meshgrid(xs, ys)
        qx, qy = np.abs(x - w / 2) - (w / 2 - r), np.abs(y - h / 2) - (h / 2 - r)
        outside = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
        sdf = outside + np.minimum(np.maximum(qx, qy), 0) - r
        depth = np.maximum(-sdf, 0)
        dh, dv = np.minimum(y, h - y), np.minimum(x, w - x)
        corner = depth - np.minimum(dh, dv)
        d_h, d_v = np.maximum(dh + corner, 0), np.maximum(dv + corner, 0)
        cx, cy = np.clip(x, r, w - r), np.clip(y, r, h - r)
        top, left = y < h / 2, x < w / 2
        s_h = np.where(top, cx - r, straight_w + straight_h + 2 * arc + (w - r - cx))
        s_v = np.where(left, 2 * straight_w + straight_h + 3 * arc + (h - r - cy), straight_w + arc + (cy - r))
        rounded = (qx > 0) & (qy > 0)
        span = np.maximum(np.hypot(qx, qy), 1e-6)
        horizontal = qx > qy
        # Depth increases inward, against the rounded rectangle's outward normal.
        grad_x = -np.where(rounded, qx / span, horizontal.astype(np.float32)) * np.sign(x - w / 2)
        grad_y = -np.where(rounded, qy / span, (~horizontal).astype(np.float32)) * np.sign(y - h / 2)
        fade = np.clip((band - depth) / (.1 * band), 0., 1.)
        strips.append(dict(
            rect=QRectF(c0 / sx, r0 / sy, (c1 - c0) / sx, (r1 - r0) / sy), xs=xs, ys=ys,
            depth=depth, cover=np.clip(.5 - sdf * min(sx, sy), 0., 1.),
            d_h=d_h, d_v=d_v, grad_x=grad_x.astype(np.float32), grad_y=grad_y.astype(np.float32),
            i_h=(s_h / length * _TABLE).astype(np.int32) % _TABLE,
            i_v=(s_v / length * _TABLE).astype(np.int32) % _TABLE,
            tube_h=np.where(top, 0, 2).astype(np.int8), tube_v=np.where(left, 3, 1).astype(np.int8),
            w_h=(1. / (1. + np.exp(np.clip(3. * (d_h - d_v) / (.4 * band), -60., 60.)))).astype(np.float32),
            fade=(fade * fade * (3. - 2. * fade)).astype(np.float32),
            sx=sx, sy=sy, origin=(c0, r0)))
    return length, r, tuple(strips)


@lru_cache(maxsize=6)
def _neon_profiles(w, h, band, scale, rim):
    """Depth profiles of the tube's filament, glass, glow and haze for both edges.

    The glass is about as thick as the other modes' crisp rim at the same rim
    width, and the glow and haze stand in for their spill.
    """
    _, _, strips = _geometry(w, h, band, scale)
    tube = max(2.5, rim * NEON_TUBE)
    centre = tube * .5 + 1.
    filament_width = max(.7, tube * .15)
    profiles = []
    for strip in strips:
        sides = {}
        for key in ("h", "v"):
            d = strip["d_" + key]
            offset = d - centre
            side = np.where(d < centre, tube * .8, .2 * band)
            hazes = []
            for spread in (1., 1.25):
                t = np.clip(d / (band * spread), 0., 1.)
                hazes.append(((1. - t) ** 1.6 * np.exp(-1.6 * t * t)).astype(np.float32))
            sides[key] = (
                (NEON_FILAMENT * np.exp(-(offset / filament_width) ** 2)).astype(np.float32),
                (NEON_GLASS * np.exp(-(np.abs(offset) / (tube * .5)) ** 4)).astype(np.float32),
                (NEON_GLOW * np.exp(-(np.abs(offset) / side) ** 1.3)).astype(np.float32),
                *hazes)
        profiles.append(sides)
    return tuple(profiles)


@lru_cache(maxsize=6)
def _liquid_film(w, h, band, scale, rim):
    """The thin film clinging to the rim, and its slope, for each strip.

    It is about as thick as the other modes' crisp rim at the same rim width.
    """
    _, _, strips = _geometry(w, h, band, scale)
    thickness = max(1.5, rim * LIQUID_FILM)
    films = []
    for strip in strips:
        film = np.exp(-(strip["depth"] - thickness) / (.07 * band)).astype(np.float32)
        slope = film * (-1. / (.07 * band))
        films.append((film, slope * strip["grad_x"], slope * strip["grad_y"]))
    return tuple(films)


def _song_seed(key):
    """A stable seed per song, so each song keeps its own light show."""
    return zlib.crc32(repr(key).encode("utf-8")) % 9973 / 13.


def _start_plan(seed):
    """Which tubes one start takes (top, right, bottom, left) and how long they take to catch."""
    pick = _hash(seed + .21)
    size = 1 if pick < .2 else 2 if pick < .5 else 3 if pick < .7 else 4
    tubes = sorted(range(4), key=lambda tube: _hash(seed + 1.7 * tube + .5))[:size]
    length, spread = _hash(seed + .37), _hash(seed + .43)
    if length < .3:
        duration = .5 + .4 * spread
    elif length < .7:
        duration = 1. + .9 * spread
    else:
        duration = 2. + 1.6 * spread
    return tuple(tubes), duration


def _struggle(seed, duration, t, beat, music):
    """One tube starting, t seconds in: black, hard flashes coming faster, then lit.

    Some gaps keep only the faint glow at the tube's ends, and some tubes dip
    once more just after catching, as real ones do.
    """
    if t >= duration:
        # With React to audio the beat drives every flash, so there is no late dip.
        late = t - duration - .1
        return .3 if not music and 0. <= late < .12 and _hash(seed + .9) < .35 else 1.
    dark = .01 + .03 * _hash(seed + .3)
    if music:
        return .9 + .1 * _hash(seed + .7) if beat > .45 else dark
    clock = .05 + .15 * _hash(seed + .1)
    if t < clock:
        return dark
    step = 0
    while clock < duration:
        key = seed + step * 2.9
        flash = .06 + .14 * _hash(key + .11)
        if t < clock + flash:
            return .9 + .1 * _hash(key + .23)
        clock += flash
        clock += (.08 + .37 * _hash(key + .37)) * (1. - .7 * clock / duration)
        if t < clock:
            return .22 + .08 * _hash(key + .5) if _hash(key + .61) < .25 else dark
        step += 1
    return 1.


def _start_levels(levels, seed, local, beat, music, plan=None):
    tubes, duration = plan or _start_plan(seed)
    for order, tube in enumerate(tubes):
        delay = 0. if order == 0 else .12 * _hash(seed + tube * .9)
        t = local - delay
        if t >= 0.:
            own = duration * (.85 + .3 * _hash(seed + tube * 1.3))
            levels[tube] = min(levels[tube], _struggle(seed + tube * 3.3, own, t, beat, music))


def _active_starts(now, starts, seed, chance):
    """The starts that fired and are still playing out: (begin, seed) pairs.

    starts are sorted times (chance a matching sequence or one share), or a
    spacing in seconds for evenly spread candidates on the song's timeline.
    """
    active = []
    if isinstance(starts, (int, float)):
        for k in range(math.floor((now - _START_LONGEST) / starts) - 1, math.floor(now / starts) + 1):
            begin = k * starts + .6 * starts * _hash(seed + k * .77)
            moment = seed + k * 7.31
            # The timeline opens lit; a song's own start strike covers its first moments.
            if 1. <= begin <= now < begin + _START_LONGEST and _hash(moment + .05) < chance:
                active.append((begin, moment))
        return active
    for i in range(bisect_left(starts, now - _START_LONGEST), bisect_right(starts, now)):
        moment = seed + i * 7.31
        if _hash(moment + .05) < (chance[i] if isinstance(chance, (list, tuple)) else chance):
            active.append((starts[i], moment))
    return active


def _tube_levels(now, starts, seed, chance, motion, struck_since=None, beat=0., music=False):
    """How lit each tube is at this moment of the song.

    A song change, or choosing Neon, starts all four. Reduce motion, Still and
    a paused song leave every tube steadily lit, and the same moment always
    gives the same frame.
    """
    levels = np.ones(4, dtype=np.float32)
    if not motion:
        return levels
    if struck_since is not None and 0. <= struck_since < _START_LONGEST:
        strike = seed + 911.
        _start_levels(levels, strike, struck_since, beat, False, ((0, 1, 2, 3), 1.1 + .7 * _hash(strike + .2)))
    for begin, moment in _active_starts(now, starts, seed, chance):
        _start_levels(levels, moment, now - begin, beat, music)
    return levels


def _lyric_anchors(lines):
    """Where tubes may start in a song with synced lyrics: (times, chances).

    Every lyric line, plus sung words inside longer lines, at least
    _WORD_START_GAP apart. Without word timing a long line adds its midpoint.
    """
    points = []
    for index, line in enumerate(lines):
        points.append((line.time, _LINE_START_CHANCE))
        end = lines[index + 1].time if index + 1 < len(lines) else line.time + 4.
        words = [word.start for word in getattr(line, "words", ()) or ()
                 if line.time + 1.2 <= word.start <= end - .8]
        last = line.time
        for start in words:
            if start - last >= _WORD_START_GAP:
                points.append((start, _WORD_START_CHANCE))
                last = start
        if not words and end - line.time >= 2.6:
            points.append(((line.time + end) / 2, _WORD_START_CHANCE))
    points.sort(key=lambda point: point[0])
    return [time for time, _ in points], [chance for _, chance in points]


_anchor_cache = {}


def _neon_timeline(c, phase):
    """Where the song is and where tubes may start: (now, starts, seed, chance)."""
    track, position = getattr(c, "track", None), getattr(c, "position", None)
    if track is None or position is None:
        # Previews and thumbnails have no song: their own animation clock stands in.
        return getattr(c, "motion_cycles", phase) * _LOOP_SECONDS, _PREVIEW_START_SPACING, 0., _FREE_START_CHANCE
    seed = _song_seed(getattr(track, "key", None))
    lines = getattr(getattr(c, "lyrics", None), "lines", None) or ()
    if len(lines) > 1:
        key = (id(lines), len(lines))
        if key not in _anchor_cache:
            _anchor_cache.clear()
            _anchor_cache[key] = _lyric_anchors(lines)
        times, chances = _anchor_cache[key]
        return float(position) + getattr(c, "offset", 0) / 1000, times, seed, chances
    return float(position), _FREE_START_SPACING, seed, _FREE_START_CHANCE


def _neon(geometry, profiles, w, phase, a, b, proportion, beat, music, opacity, levels):
    """Light in units of the local colour at full energy, and that energy, per strip."""
    length, r, strips = geometry
    u = (np.arange(_TABLE, dtype=np.float32) + .5) / _TABLE
    top_centre = (w * .5 - r) / length
    amount = _palette_amount((u - top_centre) * 2. + .03 * math.sin(_TAU * phase), proportion, .08)
    colour, energy = _normalised((a + (b - a) * amount[:, None]).astype(np.float32))
    hot = _whiten(colour, 1., NEON_WHITE)
    # Gas striations travel along the tube and ripple its glow, as in a real discharge.
    striation = (1. + .1 * np.sin(_TAU * (u * math.floor(length / 34.) - 5. * phase))).astype(np.float32)
    tube_gain, glow_gain = (.75 + .45 * beat, .5 + beat) if music else (1., 1.)
    spread = beat if music else 0.
    lights = []
    for strip, sides in zip(strips, profiles):
        parts = []
        for key in ("h", "v"):
            index = strip["i_" + key]
            filament, glass, glow, haze, wide_haze = sides[key]
            if spread:
                haze = haze + (wide_haze - haze) * spread
            stripes = striation[index] * tube_gain
            lit = levels[strip["tube_" + key]]
            core = filament * stripes * lit
            body = (glass * stripes + (glow * striation[index] + NEON_HAZE * haze) * opacity * glow_gain) * lit
            parts.append((hot[index] * core[..., None] + colour[index] * body[..., None], energy[index]))
        (horizontal, energy_h), (vertical, energy_v) = parts
        w_h = strip["w_h"]
        lights.append((vertical + (horizontal - vertical) * w_h[..., None], energy_v + (energy_h - energy_v) * w_h))
    return lights


def _drops(w, h, band, phase, beat, a, b, proportion):
    r = min(_RADIUS, min(w, h) / 4)
    length = 2 * (w + h - 4 * r) + _TAU * r
    count = max(8, min(len(_DROP_SPEED), round(length / _DROP_SPACING)))
    stretch = length / count / _DROP_SPACING
    drops = []
    for i in range(count):
        s = i / count + .05 * _hash(i) + _DROP_SPEED[i] * phase
        # Mostly clinging; now and then a drop leans inward far enough to pinch off.
        lean = (.5 + .5 * math.sin(_TAU * (_DROP_RISE[i] * phase + _hash(i + 7)))) ** 3
        depth = band * (.1 + .32 * lean + .18 * beat * _hash(i + 5))
        x, y, tx, ty = _rim_point(w, h, s, depth)
        size = .8 + .45 * _hash(i + 3)
        # Drops lengthen more slowly than they deepen, so the light grows with the
        # glow spread about as the other modes' spill does.
        along = LIQUID_DROP_LENGTH * stretch * (band / 40.) ** LIQUID_DROP_GROWTH
        drops.append((x, y, tx, ty, along * size * (1. + .12 * beat), band * .27 * size * (1. + .22 * beat),
                      1.8 + .4 * _hash(i + 9), a if _hash(i * .618 + 2) < proportion else b, s % 1.))
    return drops


def _liquid(geometry, films, drops, band, a, b, beat, music, opacity):
    length, _, strips = geometry
    # Colour flows along the rim from each drop; far from every drop the film
    # settles on an even mix rather than switching colour abruptly.
    along = (np.arange(_TABLE, dtype=np.float32) + .5) / _TABLE * length
    calm = .002
    paint = np.repeat(((a + b) * .5 * calm)[None, :], _TABLE, axis=0)
    total = np.full(_TABLE, calm, dtype=np.float32)
    for x, y, tx, ty, along_size, _, strength, colour, s in drops:
        gap = (along - s * length + length / 2) % length - length / 2
        weight = strength * np.exp(-.5 * (gap / (1.6 * along_size)) ** 2)
        paint += weight[:, None] * colour
        total += weight
    table, table_energy = _normalised((paint / total[:, None]).astype(np.float32))
    gloss = band * .32
    # The drops are this mode's glow, so glow opacity sets how strongly they shine.
    body_gain = (LIQUID_BODY + (1. - LIQUID_BODY) * opacity) * (.85 + .3 * beat if music else 1.)
    lights = []
    for strip, (film, film_x, film_y) in zip(strips, films):
        field, slope_x, slope_y = film.copy(), film_x.copy(), film_y.copy()
        xs, ys, sx, sy = strip["xs"], strip["ys"], strip["sx"], strip["sy"]
        for x, y, tx, ty, size_a, size_b, strength, _, _ in drops:
            reach = 3. * size_a
            c_lo, c_hi = np.searchsorted(xs, (x - reach, x + reach))
            r_lo, r_hi = np.searchsorted(ys, (y - reach, y + reach))
            if c_hi <= c_lo or r_hi <= r_lo:
                continue
            dx = xs[c_lo:c_hi][None, :] - x
            dy = ys[r_lo:r_hi][:, None] - y
            along_d = dx * tx + dy * ty
            across = dy * tx - dx * ty
            g = strength * np.exp(-.5 * (along_d * along_d / (size_a * size_a) + across * across / (size_b * size_b)))
            pull_a, pull_b = -along_d / (size_a * size_a) * g, -across / (size_b * size_b) * g
            field[r_lo:r_hi, c_lo:c_hi] += g
            slope_x[r_lo:r_hi, c_lo:c_hi] += pull_a * tx - pull_b * ty
            slope_y[r_lo:r_hi, c_lo:c_hi] += pull_a * ty + pull_b * tx
        light = np.zeros(field.shape + (3,), dtype=np.float32)
        energy_v = table_energy[strip["i_v"]]
        light_energy = energy_v + (table_energy[strip["i_h"]] - energy_v) * strip["w_h"]
        lit = field > .02
        if lit.any():
            f = field[lit]
            gx, gy = slope_x[lit], slope_y[lit]
            inside = np.clip((f - 1.) / np.maximum(np.hypot(gx, gy), 1e-4) + .5, 0., 1.)
            # Wet-gel shading: the field's slope is the surface normal.
            nx, ny = -gx * gloss, -gy * gloss
            nz = 1. / np.sqrt(nx * nx + ny * ny + 1.)
            nx, ny = nx * nz, ny * nz
            diffuse = np.maximum(nx * _KEY[0] + ny * _KEY[1] + nz * _KEY[2], 0.)
            spec = np.maximum(nx * _SHINE[0] + ny * _SHINE[1] + nz * _SHINE[2], 0.) ** 46
            spec2 = np.maximum(nx * _SHINE2[0] + ny * _SHINE2[1] + nz * _SHINE2[2], 0.) ** 90
            rim = (1. - nz) ** 2
            w_h = strip["w_h"][lit][:, None]
            near_v = table[strip["i_v"][lit]]
            colour = near_v + (table[strip["i_h"][lit]] - near_v) * w_h
            energy = colour.max(axis=1, keepdims=True)
            body = ((colour * (.66 + .34 * diffuse)[:, None] + _whiten(colour, energy, .5) * (rim * .4)[:, None])
                    * body_gain + energy * (spec * .85 + spec2 * .35)[:, None])
            glow = colour * (LIQUID_GLOW * opacity * np.clip(f, 0., 1.) ** 2 * (1. - inside))[:, None]
            light[lit] = body * inside[:, None] + glow
        lights.append((light, light_energy))
    return lights


def _cpu_images(light, scale):
    """The light strips drawn with NumPy: (logical rect, image, pixel buffer) for each."""
    w, h, band = light["w"], light["h"], light["band"]
    geometry = _geometry(w, h, band, scale)
    if light["mode"] == "neon":
        lights = _neon(geometry, _neon_profiles(w, h, band, scale, light["rim"]), w, light["phase"], light["a"],
                       light["b"], light["mix"], light["beat"], light["music"], light["opacity"], light["levels"])
    else:
        lights = _liquid(geometry, _liquid_film(w, h, band, scale, light["rim"]), light["drops"], band, light["a"],
                         light["b"], light["beat"], light["music"], light["opacity"])
    images = []
    for strip, (field, energy) in zip(geometry[2], lights):
        # Highlights roll off in the colour's own units, then take its energy and the
        # shared strength, so the brightest pixel matches the other modes' crisp rim.
        rgb = _knee(field) * (energy * strip["fade"] * strip["cover"] * light["strength"])[..., None]
        rows, cols = rgb.shape[:2]
        pixels = np.empty((rows, cols, 4), dtype=np.uint8)
        # Premultiplied light: alpha is the brightest channel, so rgb never exceeds it.
        pixels[..., 3] = np.rint(rgb.max(axis=2) * 255)
        pixels[..., :3] = np.rint(rgb[..., ::-1] * 255)
        image = QImage(pixels.data, cols, rows, cols * 4, QImage.Format.Format_ARGB32_Premultiplied)
        images.append((strip["rect"], image, pixels))
    return images


def _render_scale(w, h, band, ceiling, budget):
    reach = band + 1.
    area = 2 * w * reach + 2 * max(0., h - 2 * reach) * reach
    return max(.25, round(min(ceiling, math.sqrt(budget / max(area, 1.))) * 32) / 32)


def paint_field_glow(p, w, h, c, mode, phase=0., beat=0., music=False, strength=1.):
    """Draw Neon or Liquid; returns False for every other mode.

    The caller supplies the shared animation phase, beat and overall strength,
    exactly as the other halo modes receive them. The GPU draws at display
    resolution; without OpenGL 3.3 the same model runs in NumPy at a lower one.
    """
    if mode not in FIELD_HALO_IDS:
        return False
    if strength <= 0 or min(w, h) < 4:
        return True
    w, h = float(w), float(h)
    band = max(4., min(float(getattr(c, "glow_width", 40)), min(w, h) / 2))
    a = _light_colour(getattr(c, "halo_primary", c.primary), getattr(c, "primary_brightness", 100))
    b = _light_colour(getattr(c, "halo_secondary", c.secondary), getattr(c, "secondary_brightness", 100))
    proportion = light_share(c, float(a.max()), float(b.max()))
    # A paused song holds its frame, like every other halo light; previews have no track and always move.
    playing = getattr(getattr(c, "track", None), "playing", True)
    motion = playing and not getattr(c, "reduced_motion", False) and getattr(c, "halo_animation", "flow") != "still"
    struck_at = getattr(c, "halo_struck_at", None)
    struck_since = time.monotonic() - struck_at if struck_at is not None else None
    light = dict(
        mode=mode, w=w, h=h, band=band, phase=phase, beat=beat if music else 0., music=bool(music),
        strength=strength, a=a, b=b, mix=proportion,
        opacity=max(0., min(1., getattr(c, "glow_opacity", 65) / 100)),
        rim=max(1., min(12., float(getattr(c, "rim_width", 3)))),
        levels=(_tube_levels(*_neon_timeline(c, phase), motion, struck_since, beat if music else 0., bool(music))
                if mode == "neon" else np.ones(4)),
        calibration=(NEON_TUBE, NEON_FILAMENT, NEON_GLASS, NEON_WHITE, NEON_GLOW, NEON_HAZE,
                     LIQUID_FILM, LIQUID_BODY, LIQUID_GLOW),
        drops=_drops(w, h, band, phase, beat if music else 0., a, b, proportion) if mode == "liquid" else None)
    dpr = max(1., p.device().devicePixelRatioF())
    drawn = None
    renderer = shared_field_renderer()
    if renderer is not None and renderer.available:
        scale = _render_scale(w, h, band, dpr * renderer.budget.scale, _GPU_PIXEL_BUDGET)
        sx, sy, blocks = strip_layout(w, h, band, scale)
        started = time.perf_counter()
        images = renderer.render(light, sx, sy, blocks)
        if images is not None:
            renderer.budget.record((time.perf_counter() - started) * 1000)
            drawn = [(QRectF(c0 / sx, r0 / sy, (c1 - c0) / sx, (r1 - r0) / sy), image, pixels)
                     for (c0, c1, r0, r1), (image, pixels) in zip(blocks, images)]
    if drawn is None:
        drawn = _cpu_images(light, _render_scale(w, h, band, dpr, _CPU_PIXEL_BUDGET))
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for rect, image, _ in drawn:
        p.drawImage(rect, image)
    p.restore()
    return True
