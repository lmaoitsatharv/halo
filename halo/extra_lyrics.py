"""Optional native lyric compositions for Halo's mode library.

The catalogue is importable before lyric_rendering has finished initialising.
All glyph shaping, source timing and bounded caches stay on the shared canvas.
"""
import math
from collections import OrderedDict

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap


EXTRA_LYRIC_STYLES = (
    ("lyric_monument", "Monument", "A moving typographic poster: immense verses, fine rules and an editorial cue rail."),
    ("lyric_marquee", "Marquee", "A flowing horizontal ribbon of words passing through a luminous focal slit."),
    ("lyric_afterimage", "Afterimage", "A bold word leaves delicate outline echoes, framed by quiet neighbouring verses."),
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
    for context, y in ((_context(c.lyrics.lines, index - 1, -1), h * .14),
                       (_context(c.lyrics.lines, index + 1, 1), h * .86)):
        if context is None:
            continue
        shape = canvas._shape(c.lyrics.lines[context].text, max(1, w * .82), max(1, h * .12),
                              max(10, base * .34), "center")
        canvas._text(p, shape, w / 2, y, c.primary, .27)
        _hit(canvas, shape, w / 2, y, 1, context)
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
    else:
        _afterimage(canvas, painter, index, word_index, phase, transition)
    painter.restore()
    return True
