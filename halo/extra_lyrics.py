"""Optional native lyric compositions for Halo's mode library.

The catalogue is importable before lyric_rendering has finished initialising.
All glyph shaping, source timing and bounded caches stay on the shared canvas.
"""
import math
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from operator import attrgetter
from typing import NamedTuple

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap, QTransform


EXTRA_LYRIC_STYLES = (
    ("lyric_monument", "Monument", "A moving typographic poster: immense verses, fine rules and an editorial cue rail."),
    ("lyric_marquee", "Marquee", "A flowing horizontal ribbon of words passing through a luminous focal slit."),
    ("lyric_afterimage", "Afterimage", "A bold word leaves delicate outline echoes, framed by quiet neighbouring verses."),
    ("lyric_strata", "Strata", "A wall of words swings through space, snapping to each new line."),
    ("lyric_cascade", "Cascade", "Words climb a rising stack, the newest large and lit on a bold block."),
    ("lyric_starline", "Starline", "Each word lands as a star, and a bright thread draws the verse into a map."),
    ("lyric_neon", "Neon", "A line of unlit glass tubes that strike on word by word in the album's colour."),
    ("lyric_impact", "Impact", "One huge word at a time, thrown at the screen with a shockwave and a colour split."),
)
LINE_BASED_STYLES = frozenset({"lyric_monument"})


def _clamp(value, low=0., high=1.):
    return min(high, max(low, value))


def _smooth(value):
    value = _clamp(value)
    return value * value * (3 - 2 * value)


def _alpha(colour, opacity):
    value = QColor(colour)
    value.setAlphaF(_clamp(opacity))
    return value


def _mix(a, b, amount):
    amount = _clamp(amount)
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * amount,
                          a.greenF() + (b.greenF() - a.greenF()) * amount,
                          a.blueF() + (b.blueF() - a.blueF()) * amount)


def _phase(canvas, style, motion):
    """One bounded decoration clock; even standalone previews freeze on pause."""
    c = canvas.controller
    key = (style, id(c.lyrics.lines), c.generation)
    state = getattr(canvas, "_extra_lyric_motion", None)
    if state is None or state[0] != key:
        phase = 0.
    else:
        phase = state[2]
        if c.track.playing and not getattr(c, "reduced_motion", False):
            phase += _clamp(motion - state[1], 0, .1)
    if getattr(c, "reduced_motion", False):
        phase = 0.
    canvas._extra_lyric_motion = (key, motion, phase)
    return phase


def _hit(canvas, shape, x, y, scale, line):
    if line < 0:
        return
    box = QRectF(x - shape.bounds.width() * scale / 2,
                 y - shape.bounds.height() * scale / 2,
                 shape.bounds.width() * scale, shape.bounds.height() * scale).adjusted(-9, -7, 9, 7)
    box = box.intersected(QRectF(canvas.rect()))
    if box.width() > 0 and box.height() > 0:
        canvas._hit_rows.append((QRectF(box.toAlignedRect()), line))


def _context(lines, index, direction):
    for _ in range(8):
        if not 0 <= index < len(lines):
            break
        if lines[index].text.strip():
            return index
        index += direction
    return None


def _neighbours(canvas, p, index, opacity=1.):
    """Quiet verses above and below, framing the word or the break between them."""
    if opacity < .012:
        return
    c = canvas.controller
    w, h = canvas.width(), canvas.height()
    for context, y in ((_context(c.lyrics.lines, index - 1, -1), h * .14),
                       (_context(c.lyrics.lines, index + 1, 1), h * .86)):
        if context is None:
            continue
        shape = canvas._shape(c.lyrics.lines[context].text, max(1, w * .82), max(1, h * .12),
                              max(10, canvas._base_size() * .34), "center")
        canvas._text(p, shape, w / 2, y, c.primary, .27 * _clamp(opacity))
        if opacity > .4:
            _hit(canvas, shape, w / 2, y, 1, context)


def _monument(canvas, p, index, phase):
    """An asymmetric editorial poster, with entire verses changing as units."""
    c = canvas.controller
    w, h = canvas.width(), canvas.height()
    margin = max(13, min(58, w * .065))
    gutter = min(48, max(24, w * .09))
    left = margin + gutter
    width = max(1, w - left - margin)
    base = canvas._base_size()
    spacing = max(38, h * .36)
    size = base * 1.34
    reduced = bool(getattr(c, "reduced_motion", False))
    # A fine asymmetric frame leaves the typography open to the wallpaper.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_alpha(c.primary, .16), .9))
    rail_x = margin + gutter * .36
    p.drawLine(QPointF(rail_x, h * .16), QPointF(rail_x, h * .84))
    p.drawLine(QPointF(left + width * .67, h * .10), QPointF(w - margin, h * .10))
    p.drawLine(QPointF(w - margin, h * .10), QPointF(w - margin, h * .10 + min(22, h * .07)))
    p.drawLine(QPointF(left + width * .78, h * .90), QPointF(w - margin, h * .90))
    for i in range(max(0, index - 2), min(len(c.lyrics.lines), index + 3)):
        line = c.lyrics.lines[i]
        if not line.text.strip():
            continue
        delta = i - canvas.visual_index
        focus = math.exp(-delta * delta * 2.1)
        scale = .38 + .62 * focus
        y = h * .50 + delta * spacing
        shape = canvas._shape(line.text, width, max(1, h * .34), size, "left")
        opacity = max(0, 1 - abs(delta) * .56) * canvas._edge_opacity(y, shape.bounds.height(), scale)
        if opacity < .012:
            continue
        x = left + shape.bounds.width() * scale / 2
        # A restrained, staggered shadow reads like layered printed ink.
        if focus > .45 and canvas.mode != "floating":
            offset = 2 if reduced else 2 + math.sin(phase * .65) * .55
            canvas._text(p, shape, x + offset, y + offset, c.secondary, opacity * focus * .15, scale)
        canvas._text(p, shape, x, y, c.primary, opacity, scale)
        _hit(canvas, shape, x, y, scale, i)
        if focus > .08:
            number = canvas._shape(f"{i + 1:02}", max(10, gutter * .68), max(16, h * .11),
                                   max(10, base * .25), "center")
            canvas._text(p, number, rail_x, y - shape.bounds.height() * scale / 2 + number.bounds.height() / 2,
                         c.primary, opacity * (.24 + .5 * focus))
            p.setPen(QPen(_alpha(c.secondary, opacity * focus * .65), max(1.3, base * .025),
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            cap_y = y + shape.bounds.height() * scale / 2 + max(7, base * .18)
            p.drawLine(QPointF(left, cap_y), QPointF(left + min(width * .15, base * 1.4), cap_y))


def _marquee(canvas, p, index, word_index, phase):
    """Words travel horizontally through a fixed, open scanner-like focus."""
    c = canvas.controller
    w, h = canvas.width(), canvas.height()
    words = canvas.timeline.display_words
    if not words:
        return
    base = canvas._base_size()
    size = base * 1.42
    visual = _clamp(canvas._word_visual, -1, len(words) - 1)
    first = max(0, math.floor(visual) - 5)
    last = min(len(words), math.floor(visual) + 7)
    gap = max(13, min(34, base * .42))
    blank_width = max(38, w * .25)
    rows = []
    cursor = 0.
    for i in range(first, last):
        word = words[i]
        shape = None if word.text == "♪" else canvas._word_shape(
            word.text, max(1, w * .64), max(1, h * .43), size)
        width = blank_width if shape is None else max(12, shape.bounds.width())
        centre = cursor + width / 2
        rows.append((i, word, shape, centre, width))
        cursor += width + gap
    if not rows:
        return
    positions = {row[0]: row[3] for row in rows}
    anchor = math.floor(visual)
    if anchor < first:
        focal = rows[0][3] - (rows[0][4] + blank_width) / 2 - gap
    else:
        focal = positions.get(anchor, rows[-1][3])
        if anchor + 1 in positions:
            focal += (positions[anchor + 1] - focal) * (visual - anchor)
    center_y = h * .49
    # Two hairline meridians, not a word box, define the fixed viewing slit.
    slit = min(w * .22, max(36, base * .92))
    line_top, line_bottom = center_y - h * .24, center_y + h * .24
    p.setPen(QPen(_alpha(c.primary, .18), .8))
    for x in (w / 2 - slit, w / 2 + slit):
        p.drawLine(QPointF(x, line_top), QPointF(x, line_top + min(12, h * .05)))
        p.drawLine(QPointF(x, line_bottom - min(12, h * .05)), QPointF(x, line_bottom))
    for i, word, shape, local_x, _ in rows:
        if shape is None:
            continue
        x = w / 2 + local_x - focal
        delta = i - visual
        focus = math.exp(-delta * delta * 1.45)
        scale = .66 + .34 * focus
        edge = _smooth((w * .53 - abs(x - w / 2)) / max(1, w * .27))
        opacity = edge * (.19 + .81 * focus)
        if opacity < .012:
            continue
        drift = math.sin(delta * .95 + phase * .55) * min(7, h * .025) * (1 - focus)
        y = center_y + drift
        colour = _mix(c.primary, QColor("#f4f4ef"), focus * .8)
        canvas._text(p, shape, x, y, colour, opacity, scale)
        _hit(canvas, shape, x, y, scale, word.line)
    gradient = QLinearGradient(w * .18, 0, w * .82, 0)
    gradient.setColorAt(0, _alpha(c.primary, 0))
    gradient.setColorAt(.5, _alpha(c.primary, .31))
    gradient.setColorAt(1, _alpha(c.primary, 0))
    p.setPen(QPen(gradient, .9))
    p.drawLine(QPointF(w * .18, h * .80), QPointF(w * .82, h * .80))


def _outline(canvas, p, shape, x, y, colour, opacity, scale, width=1.):
    """Cache fine outline ink once; moving three impressions stays inexpensive."""
    dpr = canvas.devicePixelRatioF()
    key = (id(shape), colour.rgba(), dpr, width)
    cache = getattr(canvas, "_afterimage_outlines", None)
    if cache is None:
        cache = canvas._afterimage_outlines = OrderedDict()
        canvas._afterimage_outline_pixels = 0
    entry = cache.get(key)
    if entry is None:
        padding = 4
        raster_w = max(1, math.ceil((shape.bounds.width() + padding * 2) * dpr))
        raster_h = max(1, math.ceil((shape.bounds.height() + padding * 2) * dpr))
        pixels = raster_w * raster_h
        if pixels <= 2_000_000:
            raster = QPixmap(raster_w, raster_h)
            raster.setDevicePixelRatio(dpr)
            raster.fill(Qt.GlobalColor.transparent)
            ink = QPainter(raster)
            ink.setRenderHint(QPainter.RenderHint.Antialiasing)
            ink.translate(padding - shape.bounds.left(), padding - shape.bounds.top())
            ink.setBrush(Qt.BrushStyle.NoBrush)
            ink.setPen(QPen(colour, width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            ink.drawPath(shape.path)
            ink.end()
            entry = (shape, raster, pixels, padding)
            cache[key] = entry
            canvas._afterimage_outline_pixels += pixels
            while len(cache) > 12 or canvas._afterimage_outline_pixels > 2_000_000:
                _, removed = cache.popitem(last=False)
                canvas._afterimage_outline_pixels -= removed[2]
    else:
        cache.move_to_end(key)
    if entry is not None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(_clamp(opacity))
        p.translate(x, y)
        p.scale(scale, scale)
        p.drawPixmap(QPointF(-shape.bounds.width() / 2 - entry[3],
                            -shape.bounds.height() / 2 - entry[3]), entry[1])
        p.restore()
        return
    p.save()
    p.translate(x, y)
    p.scale(scale, scale)
    p.translate(-shape.bounds.center().x(), -shape.bounds.center().y())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_alpha(colour, opacity), width / max(.1, scale),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(shape.path)
    p.restore()


def _afterimage(canvas, p, index, word_index, phase, transition):
    """A solid hero word emerges from finely offset outline impressions."""
    c = canvas.controller
    w, h = canvas.width(), canvas.height()
    base = canvas._base_size()
    _neighbours(canvas, p, index)
    words = canvas.timeline.display_words
    if not 0 <= word_index < len(words) or words[word_index].text == "♪":
        return
    word = words[word_index]
    shape = canvas._word_shape(word.text, max(1, w * .72), max(1, h * .37), base * 1.62)
    unit = min(19, max(5, w * .022))
    breathe = math.sin(phase * .7) * min(2, h * .006)
    # Ghost impressions live behind the glyph, not in a circle or spotlight.
    for depth in (3, 2, 1):
        _outline(canvas, p, shape, w / 2 - unit * depth, h * .50 - unit * depth * .47 + breathe,
                 c.secondary, .14 + .08 * (3 - depth), 1 - depth * .035,
                 1. if canvas.mode != "floating" else 1.3)
    settle = _smooth(transition)
    canvas._text(p, shape, w / 2, h * .50 + breathe, c.primary, .78 + .22 * settle, .97 + .03 * settle)
    _hit(canvas, shape, w / 2, h * .50 + breathe, .97 + .03 * settle, word.line)
    # A split baseline gives this composition its own quiet visual signature.
    p.setPen(QPen(_alpha(c.primary, .4), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    y = h * .735
    for sign in (-1, 1):
        p.drawLine(QPointF(w / 2 + sign * w * .055, y), QPointF(w / 2 + sign * w * .13, y))


class StrataPose(NamedTuple):
    """The wall's tilt in degrees about each axis, and its scale."""
    yaw: float
    pitch: float
    roll: float
    scale: float


STRATA_WHIP = .35
STRATA_WORDS = 48
STRATA_FLOATING_WORDS = 24
STRATA_RASTERS = 96
STRATA_RASTER_PIXELS = 2_000_000
STRATA_READABLE = .6
STRATA_CURRENT = QColor("#f4f4ef")


def strata_pose(phase, line, since_line, pulse, reduced):
    """Three drifting sways, a whip to the opposite side at each new line, and a beat of pulse."""
    if reduced:
        return StrataPose(-24., 8., 0., 1.)
    pulse = _clamp(pulse)
    # The whip runs from the previous line's offset to this line's, overshooting on the way.
    u = _clamp(since_line / STRATA_WHIP) - 1
    ease = 1 + 2.2 * u ** 3 + 1.2 * u ** 2
    swing = (1 if line % 2 == 0 else -1) * (2 * ease - 1)
    turn = math.tau * phase
    return StrataPose(_clamp(14 * math.sin(turn / 7.1) + 18 * swing, -32, 32),
                      _clamp(6 * math.sin(turn / 8.9) - 6 * swing, -12, 12) + 6 * pulse,
                      4 * math.sin(turn / 6.3), 1 + .04 * pulse)


def _since_line(canvas, index, phase):
    """Seconds on the decoration clock since the wall changed line; a new clock starts settled."""
    state = getattr(canvas, "_strata_state", None)
    if state is None or phase < state[1]:
        state = (index, -STRATA_WHIP)
    elif state[0] != index:
        state = (index, phase)
    canvas._strata_state = state
    return phase - state[1]


def _strata_words(canvas, index, word_index):
    """Display indexes on the wall: lines index-1 to index+2, dropping whole lines to stay within the word limit."""
    words = canvas.timeline.display_words
    limit = STRATA_FLOATING_WORDS if canvas.mode == "floating" else STRATA_WORDS
    spans = {}
    for line in range(max(0, index - 1), min(len(canvas.timeline.ranges), index + 3)):
        spans[line] = list(range(bisect_left(words, line, key=attrgetter("line")),
                                 bisect_right(words, line, key=attrgetter("line"))))

    def drawn(ids):
        return [i for i in ids if words[i].text != "♪"]
    for line in (index + 2, index - 1, index + 1):
        if sum(len(drawn(ids)) for ids in spans.values()) <= limit:
            break
        spans.pop(line, None)
    shown = [i for ids in spans.values() for i in ids]
    if len(drawn(shown)) > limit:
        shown = drawn(shown)
        start = bisect_left(shown, word_index) - limit // 2
        start = min(max(0, start), len(shown) - limit)
        shown = shown[start:start + limit]
    return shown


def _strata_layout(canvas, index, shown, size):
    """Wrap the words into rows of one plane, as (display index, shape or None, x, y) in canvas terms."""
    words = canvas.timeline.display_words
    w, h = canvas.width(), canvas.height()
    plane, gap = max(1., w * .86), size * .3
    rows = []
    for i in shown:
        word = words[i]
        shape = None if word.text == "♪" else canvas._word_shape(word.text, plane, size * 1.7, size)
        width = 0. if shape is None else max(8., shape.bounds.width())
        if not rows or rows[-1][0] != word.line or (
                shape is not None and rows[-1][1] and rows[-1][1] + gap + width > plane):
            rows.append([word.line, 0., []])
        row = rows[-1]
        row[2].append((i, shape, width))
        if shape is not None:
            row[1] += width + (gap if row[1] else 0.)
    anchor = next((k for k, row in enumerate(rows) if row[0] >= index), 0)
    placed = []
    for k, (_, used, entries) in enumerate(rows):
        x = 0. if not used else -plane / 2 if canvas.alignment == "left" else -used / 2
        for i, shape, width in entries:
            placed.append((i, shape, w / 2 + x + width / 2, h / 2 + (k - anchor) * size * 1.35))
            if shape is not None:
                x += width + gap
    return placed


def _strata_pan(canvas, placed, reduced):
    """The plane point the camera follows: the spring-smoothed word, or its row under Reduce motion."""
    order = [entry[0] for entry in placed]
    visual = _clamp(canvas._word_visual, order[0], order[-1])
    k = max(0, bisect_right(order, visual) - 1)
    a, b = placed[k], placed[min(k + 1, len(placed) - 1)]
    if reduced:
        return QPointF(canvas.width() / 2, a[3])
    mix = (visual - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.
    return QPointF(a[2] + (b[2] - a[2]) * mix, a[3] + (b[3] - a[3]) * mix)


def _strata_transform(w, h, pose, pan, scale):
    t = QTransform()
    t.translate(w / 2, h / 2)
    distance = max(1024., w * 1.1)
    t.rotate(pose.yaw, Qt.Axis.YAxis, distance)
    t.rotate(pose.pitch, Qt.Axis.XAxis, distance)
    t.rotate(pose.roll, Qt.Axis.ZAxis)
    t.scale(scale, scale)
    t.translate(-pan.x(), -pan.y())
    return t


def _mapped_width(t, shape, x, y):
    half = shape.bounds.width() / 2
    a, b = t.map(QPointF(x - half, y)), t.map(QPointF(x + half, y))
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def _strata_fit(canvas, pose, pan, active):
    """Keep the current word readable: wide enough, and inside the middle 60% of the canvas."""
    w, h = canvas.width(), canvas.height()
    scale = pose.scale
    t = _strata_transform(w, h, pose, pan, scale)
    if active is None:
        return t
    _, shape, x, y = active
    flat = max(1., shape.bounds.width())
    for _ in range(3):
        ratio = _mapped_width(t, shape, x, y) / flat
        if ratio >= STRATA_READABLE:
            break
        scale *= STRATA_READABLE / ratio * 1.01
        t = _strata_transform(w, h, pose, pan, scale)
    # Perspective can outrun any scale for a word far from the pan, so the pan comes closer.
    for share in (.25, .5, .75, 1.):
        if _mapped_width(t, shape, x, y) / flat >= STRATA_READABLE:
            break
        t = _strata_transform(w, h, pose, pan + (QPointF(x, y) - pan) * share, scale)
    centre = t.map(QPointF(x, y))
    dx = _clamp(centre.x(), w * .2, w * .8) - centre.x()
    dy = _clamp(centre.y(), h * .2, h * .8) - centre.y()
    return t * QTransform.fromTranslate(dx, dy) if dx or dy else t


def _strata_layer(canvas, shape, face):
    """A word's cached raster: its dark outline when face is None, else its solid face in that colour.

    Retain the shape with its raster, so recycled object IDs cannot collide. The entry and
    pixel limits bound memory, as for Afterimage's outlines. None when the raster is too big.
    """
    dpr = canvas.devicePixelRatioF()
    key = (id(shape), None if face is None else face.rgba(), dpr)
    cache = getattr(canvas, "_strata_rasters", None)
    if cache is None:
        cache = canvas._strata_rasters = OrderedDict()
        canvas._strata_raster_pixels = 0
    entry = cache.get(key)
    if entry is not None:
        cache.move_to_end(key)
        return entry
    padding = 7
    raster_w = max(1, math.ceil((shape.bounds.width() + padding * 2) * dpr))
    raster_h = max(1, math.ceil((shape.bounds.height() + padding * 2) * dpr))
    pixels = raster_w * raster_h
    if pixels > STRATA_RASTER_PIXELS:
        return None
    raster = QPixmap(raster_w, raster_h)
    raster.setDevicePixelRatio(dpr)
    raster.fill(Qt.GlobalColor.transparent)
    ink = QPainter(raster)
    ink.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink.translate(padding - shape.bounds.left(), padding - shape.bounds.top())
    if face is None:
        ink.setPen(QPen(QColor(0, 0, 0, 204), 3.8, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        ink.setBrush(QColor(0, 0, 0, 128))
        ink.translate(0, 1.5)
    else:
        ink.setPen(Qt.PenStyle.NoPen)
        ink.setBrush(face)
    ink.drawPath(shape.path)
    ink.end()
    entry = cache[key] = (shape, raster, pixels, padding)
    canvas._strata_raster_pixels += pixels
    while len(cache) > STRATA_RASTERS or canvas._strata_raster_pixels > STRATA_RASTER_PIXELS:
        _, removed = cache.popitem(last=False)
        canvas._strata_raster_pixels -= removed[2]
    return entry


def _strata_raster(canvas, p, shape, x, y, colour, opacity):
    """Draw a floating word from cached rasters, dark outline first; stroking it every frame is too slow."""
    face = QColor(colour)
    face.setAlpha(255)
    layers = [_strata_layer(canvas, shape, None), _strata_layer(canvas, shape, face)]
    if None in layers:
        canvas._text(p, shape, x, y, colour, opacity)
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(_clamp(opacity))
    for _, raster, _, padding in layers:
        p.drawPixmap(QPointF(x - shape.bounds.width() / 2 - padding, y - shape.bounds.height() / 2 - padding), raster)
    p.restore()


def _strata(canvas, p, index, word_index, phase):
    """Nearby words share one tilted plane that sways in 3D and whips to each new line."""
    c = canvas.controller
    if not canvas.timeline.display_words:
        return
    w = canvas.width()
    size = canvas._base_size() * 1.05
    placed = _strata_layout(canvas, index, _strata_words(canvas, index, word_index), size)
    if not placed:
        return
    reduced = bool(getattr(c, "reduced_motion", False))
    pose = strata_pose(phase, index, _since_line(canvas, index, phase), getattr(c, "pulse", 0.), reduced)
    active = next((entry for entry in placed if entry[0] == word_index and entry[1] is not None), None)
    t = _strata_fit(canvas, pose, _strata_pan(canvas, placed, reduced), active)
    screen = QRectF(canvas.rect())
    words = canvas.timeline.display_words
    p.save()
    p.setTransform(t, True)
    for i, shape, x, y in placed:
        if shape is None:
            continue
        mapped = t.mapRect(QRectF(x - shape.bounds.width() / 2, y - shape.bounds.height() / 2,
                                  shape.bounds.width(), shape.bounds.height()))
        if not mapped.intersects(screen):
            continue
        word = words[i]
        if i == word_index:
            colour, opacity = STRATA_CURRENT, 1.
        else:
            past = i < word_index if word_index >= 0 else word.line < index
            reach = _smooth((2.5 - abs(word.line - canvas.visual_index)) / 1.2)
            edge = canvas._edge_opacity(mapped.center().y(), mapped.height())
            side = _smooth(min(mapped.left(), w - mapped.right()) / max(12, w * .06))
            colour, opacity = c.primary, (.34 if past else .72) * reach * edge * side
        if opacity >= .012 and canvas.mode == "floating":
            _strata_raster(canvas, p, shape, x, y, colour, opacity)
        elif opacity >= .012:
            canvas._text(p, shape, x, y, colour, opacity)
        box = mapped.adjusted(-9, -7, 9, 7).intersected(screen)
        if box.width() > 0 and box.height() > 0:
            canvas._hit_rows.append((QRectF(box.toAlignedRect()), word.line))
    p.restore()


def paint_lyric_mode(canvas, painter, style, index, word_index, fraction, motion, transition):
    """Paint a supported optional mode, using the already advanced lyric state."""
    if style not in {entry[0] for entry in EXTRA_LYRIC_STYLES}:
        return False
    phase = _phase(canvas, style, motion)
    painter.save()
    painter.setClipRect(QRectF(canvas.rect()))
    if style == "lyric_monument":
        _monument(canvas, painter, index, phase)
    elif style == "lyric_marquee":
        _marquee(canvas, painter, index, word_index, phase)
    elif style == "lyric_strata":
        _strata(canvas, painter, index, word_index, phase)
    elif style == "lyric_afterimage":
        _afterimage(canvas, painter, index, word_index, phase, transition)
    else:
        # Imported here because these painters build on this module's helpers.
        from .glow_lyrics import paint_glow_mode
        paint_glow_mode(canvas, painter, style, index, word_index, phase, transition)
    painter.restore()
    return True
