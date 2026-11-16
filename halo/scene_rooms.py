"""Three rooms built from the song itself: Flow, Vinyl and Horizon.

Each follows the scene contract in scene_extras: a layout of native child
rectangles plus a painter for everything behind them, so the Immersive room,
the Modes library and the Settings preview all show the real room.
Nothing here is decoration for its own sake: the colours come from the cover,
the motion stops when the music stops, the swell follows the music when Halo
is listening, and Vinyl's tonearm and Horizon's sun follow the song's progress.
"""
from collections import OrderedDict
import math
from types import SimpleNamespace

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QImage, QLinearGradient, QPainter,
                          QPainterPath, QPen, QPixmap, QRadialGradient)

from .room_light import (CoverField, _artwork_image, colour, mix, paint_grain, progress, swell, vivid)


ROOM_SCENES = (
    ("flow", "Flow", "Your cover melts into a slow river of colour that fills the screen and swells with the music."),
    ("vinyl", "Vinyl", "A turntable up close with its sleeve beside it: your cover turns on the label and the tonearm follows the song."),
    ("horizon", "Horizon", "A sun in your song's colours sets over still water as the song plays."),
)

ROOM_CAPTIONS = {
    "flow": "POURED FROM THE COVER",
    "vinyl": "ON THE TURNTABLE",
    "horizon": "TILL THE SUN GOES DOWN",
}

RPM = 8  # A slow, calm turn (one every 7.5 s); a real 33⅓ looked hurried on screen.
# Rooms that are whole scenes, so your own Background (image, video or cover) does not show in them.
OWN_BACKDROP = frozenset({"vinyl", "horizon"})


def _body(w, h):
    margin = max(28, min(76, round(w * .04)))
    top = 92 if h < 720 else 108
    bottom = max(top + 120, h - (140 if h < 720 else 164))
    return margin, top, bottom, bottom - top


def _rect(x, y, width, height):
    return QRect(round(x), round(y), max(1, round(width)), max(1, round(height)))


def _phase(controller, supplied):
    if getattr(controller, "reduced_motion", False):
        return 0.
    if not getattr(controller.track, "playing", False):
        return float(getattr(controller, "motion_time", 0.))
    return float(supplied)


# --- layouts ---------------------------------------------------------------------------

def _flow_layout(w, h):
    margin, top, bottom, body = _body(w, h)
    size = max(110, min(round(w * .27), body - 118, 460))
    x = margin + round(w * .025)
    y = top + max(8, (body - size - 104) // 2)
    song_y = y + size + 28
    lyric_x = x + size + max(48, round(w * .055))
    return {
        "cover": _rect(x, y, size, size),
        "canvas": _rect(lyric_x, top + 8, w - lyric_x - margin, body - 16),
        "song": _rect(x, song_y, size, 46),
        "artist": _rect(x, song_y + 50, size, 24),
        "album": _rect(x, song_y + 77, size, 20),
        "status": _rect(lyric_x + 8, bottom - 22, w - lyric_x - margin - 16, 18),
        "alignment": "left",
    }


def _vinyl_stage(w, h):
    """Where everything on the turntable sits; the layout and the painter share it.

    A close view from above: the deck runs off the bottom-left of the screen, its
    sleeve lies on the table above it, and the words have the right-hand side.
    """
    margin, top, bottom, body = _body(w, h)
    radius = max(70., min(h * .36, w * .21))
    centre = QPointF(w * .2, h * .74)
    deck = QRectF(centre.x() - radius * 1.32, centre.y() - radius * 1.18, radius * 2.94, radius * 2.62)
    pivot = QPointF(centre.x() + radius * 1.18, centre.y() - radius * .8)
    size = max(80., min(h * .22, w * .15))
    sleeve = QRectF(margin + 4, top - 16, size, size)
    key_y = centre.y() + radius * .58
    speed_keys = (QRectF(centre.x() + radius * 1.12, key_y, radius * .16, radius * .085),
                  QRectF(centre.x() + radius * 1.34, key_y, radius * .16, radius * .085))
    return SimpleNamespace(margin=margin, top=top, bottom=bottom, body=body, radius=radius, centre=centre,
                           deck=deck, pivot=pivot, sleeve=sleeve, speed_keys=speed_keys)


def _vinyl_layout(w, h):
    s = _vinyl_stage(w, h)
    credit_x = s.sleeve.right() + max(24, w * .02)
    credit_width = max(60, s.deck.right() - credit_x - 10)
    credit_y = s.sleeve.top() + s.sleeve.height() * .16
    lyric_x = s.deck.right() + max(36, w * .035)
    return {
        # The cover is shown whole on the sleeve (and as the turning label), both painted by the room.
        "cover": _rect(s.sleeve.x(), s.sleeve.y(), s.sleeve.width(), s.sleeve.height()),
        "canvas": _rect(lyric_x, s.top + 8, w - lyric_x - s.margin, s.body - 16),
        "song": _rect(credit_x, credit_y, credit_width, 34),
        "artist": _rect(credit_x, credit_y + 38, credit_width, 22),
        "album": _rect(credit_x, credit_y + 62, credit_width, 18),
        "status": _rect(lyric_x + 8, s.bottom - 22, w - lyric_x - s.margin - 16, 18),
        "alignment": "left",
        "paints_cover": True,
    }


def _horizon_y(w, h):
    margin, top, bottom, body = _body(w, h)
    return top + round(body * .78)


def _sun_radius(w, h):
    margin, top, bottom, body = _body(w, h)
    return min(w * .1, body * .19)


def _horizon_layout(w, h):
    margin, top, bottom, body = _body(w, h)
    horizon = _horizon_y(w, h)
    credit_y = bottom - 52
    # The words stay in the sky; the sun rises no higher than just under the line after the one being sung.
    words_bottom = horizon - _sun_radius(w, h) * 1.2
    return {
        "cover": _rect(margin + 6, credit_y, 48, 48),
        "canvas": _rect(w * .1, top + 4, w * .8, words_bottom - top - 4),
        "song": _rect(margin + 68, credit_y, min(w * .37, 440), 19),
        "artist": _rect(margin + 68, credit_y + 21, min(w * .37, 440), 16),
        "album": _rect(margin + 68, credit_y + 38, min(w * .37, 440), 14),
        "status": _rect(w - margin - 210, credit_y + 30, 210, 18),
        "alignment": "center",
    }


LAYOUTS = {"flow": _flow_layout, "vinyl": _vinyl_layout, "horizon": _horizon_layout}


def room_layout(scene, w, h):
    if scene not in LAYOUTS:
        return None
    return LAYOUTS[scene](max(480, int(w)), max(400, int(h)))


# --- per-surface state ----------------------------------------------------------------

_FIELDS = OrderedDict()
_LAYERS = OrderedDict()
_LABELS = OrderedDict()


def _bounded(store, key, make, limit):
    if key in store:
        store.move_to_end(key)
        return store[key]
    value = store[key] = make()
    while len(store) > limit:
        store.popitem(last=False)
    return value


def _field(controller, scene):
    # Each painting surface keeps its own field, so a library card never disturbs the room's crossfade.
    return _bounded(_FIELDS, (id(controller), scene), CoverField, 12)


def _layer(key, w, h, paint):
    """A cached full-size layer, rebuilt only when its size or colours change."""
    def make():
        pixmap = QPixmap(max(1, round(w)), max(1, round(h)))
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint(p)
        p.end()
        return pixmap
    return _bounded(_LAYERS, key, make, 8)


# --- Flow ------------------------------------------------------------------------------

def _soft_shadow(p, rect, alpha):
    """A shadow with no edges: an ellipse that fades out well past the rectangle it protects."""
    p.save()
    p.translate(rect.center())
    p.scale(1., rect.height() / max(1., rect.width()))
    radius = rect.width() * .72
    shade = QRadialGradient(QPointF(), radius)
    shade.setColorAt(0, QColor(0, 0, 0, alpha))
    shade.setColorAt(.6, QColor(0, 0, 0, round(alpha * .55)))
    shade.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(-radius, -radius, radius * 2, radius * 2), shade)
    p.restore()


FLOW_LOOK = {"brightness": .82, "saturation": 1.65, "level": .36, "knee": .5, "glow": .34}


def _flow(p, w, h, c, phase, layout, backdrop=False):
    energy = swell(c)
    a, b = vivid(c)
    room = QRectF(0, 0, w, h)
    if not backdrop:
        # With your own Background on, Flow keeps it and only adds its light and shading.
        _field(c, "flow").paint(p, room, c, phase, energy, **FLOW_LOOK)
    art, words = QRectF(layout["cover"]), QRectF(layout["canvas"])
    # The cover's own light gathers behind it, a little brighter on the swell.
    bloom = QRadialGradient(art.center() + QPointF(0, art.height() * .08), art.width() * .92)
    bloom.setColorAt(0, colour(mix(a, QColor("#ffffff"), .15), .3 + .14 * energy))
    bloom.setColorAt(.55, colour(b, .1 + .05 * energy))
    bloom.setColorAt(1, colour(b, 0))
    p.fillRect(art.adjusted(-art.width(), -art.height(), art.width(), art.height()), bloom)
    # The colour stays bright across the room; only a soft shadow sits right behind the words.
    p.save()
    centre = words.center()
    p.translate(centre)
    p.scale(1., words.height() / max(1., words.width()) * 1.1)
    shadow = QRadialGradient(QPointF(), words.width() * .62)
    shadow.setColorAt(0, QColor(0, 0, 0, 132))
    shadow.setColorAt(.55, QColor(0, 0, 0, 92))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(-words.width() * .7, -words.width() * .7, words.width() * 1.4, words.width() * 1.4), shadow)
    p.restore()
    # The same soft shadow keeps the song's credits readable on bright colour.
    credits = QRectF(layout["song"]).united(QRectF(layout["album"]))
    _soft_shadow(p, credits.adjusted(-credits.width() * .08, -10, credits.width() * .08, 12), 128)
    floor = QLinearGradient(0, h * .6, 0, h)
    floor.setColorAt(0, QColor(0, 0, 0, 0))
    floor.setColorAt(1, QColor(0, 0, 0, 70))
    p.fillRect(room, floor)
    vignette = QRadialGradient(w * .5, h * .46, max(w, h) * .76)
    vignette.setColorAt(.62, QColor(0, 0, 0, 0))
    vignette.setColorAt(1, QColor(0, 0, 0, 80))
    p.fillRect(room, vignette)
    paint_grain(p, room)


# --- Vinyl -----------------------------------------------------------------------------

def _label_image(image, diameter):
    """The cover cropped to a round record label, cached at the size it is drawn."""
    diameter = max(8, int(round(diameter)))
    def make():
        label = QImage(diameter, diameter, QImage.Format.Format_ARGB32_Premultiplied)
        label.fill(Qt.GlobalColor.transparent)
        q = QPainter(label)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, diameter, diameter))
        q.setClipPath(path)
        side = min(image.width(), image.height())
        q.drawImage(QRectF(0, 0, diameter, diameter), image,
                    QRectF((image.width() - side) / 2, (image.height() - side) / 2, side, side))
        q.end()
        return label
    return _bounded(_LABELS, (image.cacheKey(), diameter), make, 4)


def _shadow(p, path, offset, spread, strength):
    """A soft drop shadow made of a few widening, faint copies of a shape."""
    p.save()
    p.translate(offset)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(6, 0, -1):
        p.setPen(QPen(QColor(0, 0, 0, round(strength / 6)), spread * i / 3, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
    p.fillPath(path, QColor(0, 0, 0, strength))
    p.restore()


def _sleeve(p, rect, image, a, b):
    """The record's sleeve lying on the table: the whole square cover, tilted, with a little wear."""
    size = rect.width()
    p.save()
    p.translate(rect.center())
    p.rotate(-6)
    local = QRectF(-size / 2, -size / 2, size, size)
    outline = QPainterPath()
    outline.addRoundedRect(local, size * .012, size * .012)
    _shadow(p, outline, QPointF(size * .025, size * .045), size * .02, 90)
    p.save()
    p.setClipPath(outline)
    if not image.isNull():
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = min(image.width(), image.height())
        p.drawImage(local, image, QRectF((image.width() - side) / 2, (image.height() - side) / 2, side, side))
    else:
        art = QLinearGradient(local.topLeft(), local.bottomRight())
        art.setColorAt(0, mix(a, QColor("#ffffff"), .1))
        art.setColorAt(1, mix(b, QColor("#000000"), .45))
        p.fillRect(local, art)
        p.setPen(QPen(QColor(255, 255, 255, 46), max(1., size * .008)))
        for i in range(7):
            radius = size * (.1 + i * .055)
            p.drawEllipse(QPointF(size * .08, size * .1), radius, radius)
    # Ring wear from the record inside, and the lamp's light across the card.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 16), max(1., size * .018)))
    p.drawEllipse(QPointF(), size * .45, size * .45)
    light = QLinearGradient(local.topLeft(), local.bottomRight())
    light.setColorAt(0, QColor(255, 255, 255, 46))
    light.setColorAt(.5, QColor(255, 255, 255, 0))
    light.setColorAt(1, QColor(0, 0, 0, 60))
    p.fillRect(local, light)
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 50), 1))
    p.drawPath(outline)
    p.restore()


def _vinyl_back(p, w, h, c, image):
    """Everything on the table that stands still: the light, the sleeve, the deck and the record's grooves."""
    s = _vinyl_stage(w, h)
    radius, centre, deck = s.radius, s.centre, s.deck
    a, b = vivid(c)
    room = QRectF(0, 0, w, h)
    # A table washed in the song's colours: a warm lamp over the deck and a second light over the words.
    p.fillRect(room, mix(QColor("#0e0c12"), b, .24))
    lamp = QRadialGradient(w * .16, -h * .08, max(w, h) * .82)
    lamp.setColorAt(0, colour(mix(a, QColor("#ffffff"), .2), .46))
    lamp.setColorAt(.42, colour(a, .16))
    lamp.setColorAt(1, colour(a, 0))
    p.fillRect(room, lamp)
    far = QRadialGradient(w * .92, h * .5, w * .52)
    far.setColorAt(0, colour(b, .2))
    far.setColorAt(1, colour(b, 0))
    p.fillRect(room, far)
    _sleeve(p, QRectF(s.sleeve), image, a, b)
    # The deck: a graphite plinth that runs off the corner of the screen, lit along its top edge.
    corner = radius * .07
    plinth = QPainterPath()
    plinth.addRoundedRect(deck, corner, corner)
    _shadow(p, plinth, QPointF(radius * .03, radius * .06), radius * .03, 120)
    body = QLinearGradient(deck.topLeft(), deck.bottomLeft())
    body.setColorAt(0, mix(QColor("#2e2d34"), a, .16))
    body.setColorAt(1, mix(QColor("#141318"), b, .12))
    p.fillPath(plinth, body)
    p.save()
    p.setClipPath(plinth)
    step = max(2., radius / 140)
    y = deck.top()
    p.setPen(QPen(QColor(255, 255, 255, 6), 1))
    while y < deck.bottom():
        p.drawLine(QPointF(deck.left(), y), QPointF(deck.right(), y))
        y += step
    spill = QRadialGradient(w * .16, -h * .08, max(w, h) * .7)
    spill.setColorAt(0, colour(mix(a, QColor("#ffffff"), .25), .22))
    spill.setColorAt(1, colour(a, 0))
    p.fillRect(deck, spill)
    p.restore()
    rim = QLinearGradient(deck.topLeft(), deck.bottomRight())
    rim.setColorAt(0, colour(mix(a, QColor("#ffffff"), .45), .7))
    rim.setColorAt(.45, colour(a, .12))
    rim.setColorAt(1, colour(a, 0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(rim, max(1.2, radius * .008)))
    p.drawPath(plinth)
    # Speed keys (the 33's light is drawn each frame) and the tonearm's rest.
    for key in s.speed_keys:
        p.setPen(QPen(QColor(0, 0, 0, 140), 1))
        keycap = QLinearGradient(key.topLeft(), key.bottomLeft())
        keycap.setColorAt(0, QColor("#4a4952"))
        keycap.setColorAt(1, QColor("#26252b"))
        p.setBrush(keycap)
        p.drawRoundedRect(key, key.height() * .3, key.height() * .3)
    font = QFont("Segoe UI")
    font.setPixelSize(max(7, round(radius * .05)))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor(222, 224, 230, 190))
    for key, text in zip(s.speed_keys, ("33", "45")):
        p.drawText(key, Qt.AlignmentFlag.AlignCenter, text)
    rest = s.pivot + QPointF(radius * .03, radius * .72)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 110))
    p.drawEllipse(rest + QPointF(radius * .015, radius * .03), radius * .04, radius * .04)
    post = QRadialGradient(rest - QPointF(radius * .01, radius * .01), radius * .045)
    post.setColorAt(0, QColor("#e4e7ec"))
    post.setColorAt(1, QColor("#5d6169"))
    p.setBrush(post)
    p.drawEllipse(rest, radius * .035, radius * .035)
    # The platter's metal edge shows around the record.
    platter = QConicalGradient(centre, 30)
    for stop, tone in ((0., "#5f636b"), (.13, "#d8dce2"), (.3, "#6b6f77"), (.5, "#3e4148"),
                       (.63, "#c9cdd4"), (.8, "#62666e"), (1., "#5f636b")):
        platter.setColorAt(stop, QColor(tone))
    p.setPen(QPen(QColor(0, 0, 0, 160), 1))
    p.setBrush(platter)
    p.drawEllipse(centre, radius * 1.035, radius * 1.035)
    # The vinyl: near-black, with grooves, the gaps between tracks and a smooth run-out.
    record = QRadialGradient(centre, radius)
    record.setColorAt(0, QColor("#141318"))
    record.setColorAt(1, QColor("#08080a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(record)
    p.drawEllipse(centre, radius, radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    step = max(1.6, radius / 120)
    r = radius * .965
    index = 0
    while r > radius * .43:
        p.setPen(QPen(QColor(255, 255, 255, 13 if index % 2 else 7), .8))
        p.drawEllipse(centre, r, r)
        r -= step
        index += 1
    for gap in (.88, .76, .64, .53):
        p.setPen(QPen(QColor(0, 0, 0, 170), max(1.2, radius * .011)))
        p.drawEllipse(centre, radius * gap, radius * gap)
        p.setPen(QPen(QColor(255, 255, 255, 18), .8))
        p.drawEllipse(centre, radius * gap + step * .8, radius * gap + step * .8)
    # Light catches the grooves in two opposite fans tinted by the lamp; they stay still as the record turns.
    sheen = QConicalGradient(centre, 38)
    glint = mix(QColor("#ffffff"), a, .45)
    for start, peak in ((0., .07), (.5, .57)):
        sheen.setColorAt(start, colour(glint, 0))
        sheen.setColorAt(peak, colour(glint, .3))
        sheen.setColorAt(peak + .07, colour(glint, 0))
    sheen.setColorAt(1., colour(glint, 0))
    ring = QPainterPath()
    ring.addEllipse(centre, radius * .985, radius * .985)
    inner = QPainterPath()
    inner.addEllipse(centre, radius * .4, radius * .4)
    p.fillPath(ring.subtracted(inner), sheen)
    disc = QPainterPath()
    disc.addEllipse(centre, radius, radius)
    pool = QRadialGradient(centre - QPointF(radius * .55, radius * .75), radius * 1.5)
    pool.setColorAt(0, colour(mix(a, QColor("#ffffff"), .2), .16))
    pool.setColorAt(1, colour(a, 0))
    p.fillPath(disc, pool)
    p.setPen(QPen(QColor(255, 255, 255, 28), 1))
    p.drawEllipse(centre, radius * .995, radius * .995)


def _stylus(centre, radius, pivot, reach, length):
    """Where the needle sits when it is `reach` from the spindle, on the arm's arc."""
    dx, dy = centre.x() - pivot.x(), centre.y() - pivot.y()
    distance = math.hypot(dx, dy)
    cosine = max(-1., min(1., (distance * distance + length * length - reach * reach) / (2 * distance * length)))
    towards = math.atan2(dy, dx)
    turn = math.acos(cosine)
    options = [QPointF(pivot.x() + math.cos(towards + s * turn) * length,
                       pivot.y() + math.sin(towards + s * turn) * length) for s in (1, -1)]
    # The arm swings in from the right of the record, as on a real deck.
    return max(options, key=lambda point: point.x())


def _tonearm(p, c, radius, centre, pivot):
    length = radius
    connected = bool(getattr(c.track, "connected", True))
    reach = radius * (.93 - .5 * progress(c)) if connected else radius * 1.12
    needle = _stylus(centre, radius, pivot, reach, length)
    direction = QPointF((needle.x() - pivot.x()) / length, (needle.y() - pivot.y()) / length)
    angle = math.degrees(math.atan2(direction.y(), direction.x()))
    tube = max(2., radius * .022)
    shadow_offset = QPointF(radius * .035, radius * .06)
    for shadow in (True, False):
        offset = shadow_offset if shadow else QPointF()
        start = pivot - direction * (radius * .3) + offset
        end = needle - direction * (radius * .11) + offset
        if shadow:
            p.setPen(QPen(QColor(0, 0, 0, 90), tube * 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        else:
            metal = QLinearGradient(start, end)
            metal.setColorAt(0, QColor("#8d929b"))
            metal.setColorAt(.5, QColor("#e9ecf1"))
            metal.setColorAt(1, QColor("#a7acb5"))
            p.setPen(QPen(metal, tube, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(start, end)
        # The headshell, angled the way real ones are, and the counterweight behind the pivot.
        p.save()
        p.translate(needle - direction * (radius * .055) + offset)
        p.rotate(angle + 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90) if shadow else QColor("#c9cdd4"))
        p.drawRoundedRect(QRectF(-radius * .085, -radius * .033, radius * .17, radius * .066), radius * .015, radius * .015)
        if not shadow:
            p.setBrush(colour(vivid(c)[0], .9))
            p.drawRect(QRectF(radius * .03, -radius * .033, radius * .02, radius * .066))
        p.restore()
        p.save()
        p.translate(pivot - direction * (radius * .24) + offset)
        p.rotate(angle)
        weight = QLinearGradient(0, -radius * .06, 0, radius * .06)
        weight.setColorAt(0, QColor("#2c2f35"))
        weight.setColorAt(.45, QColor("#6d727b"))
        weight.setColorAt(1, QColor("#1c1e22"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90) if shadow else weight)
        p.drawRoundedRect(QRectF(-radius * .075, -radius * .06, radius * .15, radius * .12), radius * .02, radius * .02)
        p.restore()
    base = QRadialGradient(pivot - QPointF(radius * .03, radius * .03), radius * .13)
    base.setColorAt(0, QColor("#f1f3f6"))
    base.setColorAt(.6, QColor("#8e939b"))
    base.setColorAt(1, QColor("#3a3d43"))
    p.setPen(QPen(QColor(0, 0, 0, 120), 1))
    p.setBrush(base)
    p.drawEllipse(pivot, radius * .1, radius * .1)
    p.setBrush(QColor("#2a2c31"))
    p.drawEllipse(pivot, radius * .04, radius * .04)


def _vinyl(p, w, h, c, phase, layout, backdrop=False):
    s = _vinyl_stage(max(480, w), max(400, h))
    radius, centre = s.radius, s.centre
    a, b = vivid(c)
    image = _artwork_image(getattr(c.track, "artwork", b""))
    key = ("vinyl", round(w), round(h), a.rgb(), b.rgb(), image.cacheKey())
    p.drawPixmap(QPointF(0, 0), _layer(key, w, h, lambda q: _vinyl_back(q, max(480, w), max(400, h), c, image)))
    energy = swell(c)
    if energy > .01:
        breath = QRadialGradient(w * .16, -h * .08, max(w, h) * .7)
        breath.setColorAt(0, colour(a, .14 * energy))
        breath.setColorAt(1, colour(a, 0))
        p.fillRect(QRectF(0, 0, w, h), breath)
    turn = (phase * RPM * 6.) % 360.
    # Dots on the platter's edge turn with it, as on a real deck.
    p.save()
    p.translate(centre)
    p.rotate(turn)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 22, 26, 170))
    dot = max(.8, radius * .005)
    for i in range(72):
        angle = i * math.tau / 72
        p.drawEllipse(QPointF(math.cos(angle) * radius * 1.018, math.sin(angle) * radius * 1.018), dot, dot)
    p.restore()
    # The label is the cover, turning slowly while the song plays and resting where it stopped.
    label_radius = radius * .36
    transform = p.worldTransform()
    # Rasterise the label at the size it reaches the screen (previews are drawn scaled).
    pixels = label_radius * 2 * max(.25, min(2., math.hypot(transform.m11(), transform.m12())))
    p.save()
    p.translate(centre)
    p.rotate(turn)
    target = QRectF(-label_radius, -label_radius, label_radius * 2, label_radius * 2)
    if not image.isNull():
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(target, _label_image(image, 4 * round(pixels / 4)))
    else:
        paper = QRadialGradient(QPointF(), label_radius)
        paper.setColorAt(0, mix(a, QColor("#ffffff"), .2))
        paper.setColorAt(1, b)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(paper)
        p.drawEllipse(QPointF(), label_radius, label_radius)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 70), max(1., label_radius * .02)))
        p.drawArc(target.adjusted(label_radius * .2, label_radius * .2, -label_radius * .2, -label_radius * .2), 20 * 16, 140 * 16)
    p.restore()
    # The label's edge, a soft gloss that stays put, and the spindle.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 150), max(1., radius * .008)))
    p.drawEllipse(centre, label_radius, label_radius)
    gloss = QRadialGradient(centre - QPointF(label_radius * .35, label_radius * .45), label_radius * 1.1)
    gloss.setColorAt(0, QColor(255, 255, 255, 34))
    gloss.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gloss)
    p.drawEllipse(centre, label_radius, label_radius)
    spindle = QRadialGradient(centre - QPointF(radius * .008, radius * .008), radius * .03)
    spindle.setColorAt(0, QColor("#ffffff"))
    spindle.setColorAt(1, QColor("#5b6068"))
    p.setBrush(spindle)
    p.drawEllipse(centre, radius * .024, radius * .024)
    # The 33 key's light, in the song's colour, glowing a little more on the swell.
    key = s.speed_keys[0]
    led = QPointF(key.center().x(), key.top() - key.height() * .55)
    glow = QRadialGradient(led, key.height() * (.9 + .4 * energy))
    glow.setColorAt(0, colour(mix(a, QColor("#ffffff"), .3), .55 + .3 * energy))
    glow.setColorAt(1, colour(a, 0))
    p.fillRect(QRectF(led.x() - key.height() * 1.4, led.y() - key.height() * 1.4, key.height() * 2.8, key.height() * 2.8), glow)
    p.setBrush(mix(a, QColor("#ffffff"), .45))
    p.drawEllipse(led, max(1.2, radius * .011), max(1.2, radius * .011))
    _tonearm(p, c, radius, centre, s.pivot)
    paint_grain(p, QRectF(0, 0, w, h))


# --- Horizon ---------------------------------------------------------------------------

def _stars(w, horizon, count=110):
    """Fixed star positions, so the sky is the same sky every night."""
    stars = []
    for i in range(count):
        x = ((i * 7919) % 1000) / 1000 * w
        y = (((i * 104729) % 997) / 997) ** 1.6 * (horizon * .8)
        size = .6 + ((i * 31) % 7) / 7 * 1.1
        stars.append((x, y, size, (i * 2.399) % (2 * math.pi), .25 + ((i * 13) % 11) / 11 * .9))
    return stars


def _hills(p, w, horizon, height, seed, fill):
    path = QPainterPath()
    path.moveTo(0, horizon + 2)
    steps = 96
    for i in range(steps + 1):
        x = w * i / steps
        middle = abs(x / w - .5)
        # The middle of the bay stays open for the sun and its reflection.
        shoulder = max(0., min(1., (middle - .14) / .2))
        rise = (.55 + .25 * math.sin(i * .21 + seed) + .2 * math.sin(i * .53 + seed * 2.3)) * shoulder
        path.lineTo(x, horizon - rise * height)
    path.lineTo(w, horizon + 2)
    path.closeSubpath()
    p.fillPath(path, fill)


def _horizon_back(p, w, h, c, horizon):
    a, b = vivid(c)
    sky = QLinearGradient(0, 0, 0, horizon)
    sky.setColorAt(0, mix(QColor("#04050a"), b, .1))
    sky.setColorAt(.55, mix(QColor("#070814"), b, .3))
    sky.setColorAt(1, mix(QColor("#120c14"), a, .5))
    p.fillRect(QRectF(0, 0, w, horizon + 1), sky)


def _horizon_front(p, w, h, c, horizon):
    a, b = vivid(c)
    _hills(p, w, horizon, h * .075, 1.7, mix(QColor("#0d0b14"), b, .22))
    _hills(p, w, horizon, h * .045, 4.1, mix(QColor("#060509"), a, .08))
    water = QLinearGradient(0, horizon, 0, h)
    water.setColorAt(0, mix(QColor("#0c0910"), a, .16))
    water.setColorAt(.25, mix(QColor("#07070c"), b, .12))
    water.setColorAt(1, QColor("#030305"))
    p.fillRect(QRectF(0, horizon, w, h - horizon), water)
    line = QLinearGradient(0, 0, w, 0)
    line.setColorAt(0, colour(a, 0))
    line.setColorAt(.5, colour(mix(a, QColor("#ffffff"), .4), .55))
    line.setColorAt(1, colour(a, 0))
    p.fillRect(QRectF(0, horizon - .5, w, 1.4), line)


def _horizon(p, w, h, c, phase, layout, backdrop=False):
    margin, top, bottom, body = _body(max(480, w), max(400, h))
    horizon = _horizon_y(max(480, w), max(400, h))
    a, b = vivid(c)
    energy = swell(c)
    room = QRectF(0, 0, w, h)
    key = (round(w), round(h), a.rgb(), b.rgb())
    p.drawPixmap(QPointF(0, 0), _layer(("horizon-back",) + key, w, h, lambda q: _horizon_back(q, w, h, c, horizon)))
    # Stars twinkle slowly and fade into the warm air above the horizon.
    p.setPen(Qt.PenStyle.NoPen)
    for x, y, size, seed, depth in _stars(w, horizon):
        twinkle = .55 + .45 * math.sin(phase * (.4 + depth * .5) + seed)
        fade = max(0., 1. - y / (horizon * .82))
        p.setBrush(QColor(236, 236, 255, round(150 * twinkle * fade * depth)))
        p.drawEllipse(QPointF(x, y), size * .7, size * .7)
    # The sun sets as the song plays: high at the first note, nearly gone by the last.
    sun_radius = _sun_radius(max(480, w), max(400, h))
    sun = QPointF(w * .5, horizon - sun_radius * (.55 - progress(c)))
    air = QRadialGradient(QPointF(w * .5, horizon), w * .62)
    air.setColorAt(0, colour(a, .34 + .12 * energy))
    air.setColorAt(.35, colour(mix(a, b, .5), .12 + .05 * energy))
    air.setColorAt(1, colour(b, 0))
    p.fillRect(QRectF(0, 0, w, horizon), air)
    p.save()
    p.setClipRect(QRectF(0, 0, w, horizon))
    corona = QRadialGradient(sun, sun_radius * (2.4 + .3 * energy))
    corona.setColorAt(0, colour(mix(a, QColor("#ffffff"), .3), .5))
    corona.setColorAt(.4, colour(a, .16))
    corona.setColorAt(1, colour(a, 0))
    p.fillRect(QRectF(sun.x() - sun_radius * 3, sun.y() - sun_radius * 3, sun_radius * 6, sun_radius * 6), corona)
    disc = QLinearGradient(0, sun.y() - sun_radius, 0, sun.y() + sun_radius)
    disc.setColorAt(0, mix(a, QColor("#fff4e0"), .35))
    disc.setColorAt(.6, mix(a, b, .3))
    disc.setColorAt(1, mix(b, QColor("#000000"), .25))
    p.setBrush(disc)
    p.setOpacity(.8)
    p.drawEllipse(sun, sun_radius, sun_radius)
    p.setOpacity(1.)
    p.restore()
    p.drawPixmap(QPointF(0, 0), _layer(("horizon-front",) + key, w, h, lambda q: _horizon_front(q, w, h, c, horizon)))
    # Its reflection breaks into slow ripples on the water; the music stretches them.
    visible = max(0., min(1., (horizon - (sun.y() - sun_radius)) / (2 * sun_radius)))
    if visible > 0:
        depth_room = h - horizon
        glow = QRadialGradient(QPointF(w * .5, horizon), sun_radius * 1.6)
        glow.setColorAt(0, colour(a, .3 * visible))
        glow.setColorAt(1, colour(a, 0))
        p.save()
        p.translate(w * .5, horizon)
        p.scale(1., depth_room / (sun_radius * 1.6))
        p.translate(-w * .5, -horizon)
        p.fillRect(QRectF(w * .5 - sun_radius * 1.6, horizon, sun_radius * 3.2, sun_radius * 1.6), glow)
        p.restore()
        p.setPen(Qt.PenStyle.NoPen)
        light = mix(a, QColor("#fff4e0"), .35)
        row, y = 0, horizon + 3
        while y < h and row < 24:
            fade = (1 - (y - horizon) / depth_room) ** 1.4
            reach = sun_radius * (1.0 - row * .025) * (.5 + .5 * math.sin(phase * .9 + row * 1.7)) * (1 + .3 * energy)
            if reach > 2:
                drift = math.sin(phase * .5 + row * .9) * sun_radius * .08
                thickness = 1.4 + row * .28
                streak = QLinearGradient(w * .5 - reach + drift, 0, w * .5 + reach + drift, 0)
                streak.setColorAt(0, colour(light, 0))
                streak.setColorAt(.5, colour(light, .62 * fade * visible))
                streak.setColorAt(1, colour(light, 0))
                p.setBrush(streak)
                p.drawRoundedRect(QRectF(w * .5 - reach + drift, y, reach * 2, thickness), thickness / 2, thickness / 2)
            y += 3.5 + row * 1.25
            row += 1
    vignette = QRadialGradient(w * .5, h * .55, max(w, h) * .72)
    vignette.setColorAt(.6, QColor(0, 0, 0, 0))
    vignette.setColorAt(1, QColor(0, 0, 0, 110))
    p.fillRect(room, vignette)
    paint_grain(p, room)


PAINTERS = {"flow": _flow, "vinyl": _vinyl, "horizon": _horizon}


def paint_room(p, w, h, controller, scene, phase, backdrop=False):
    """backdrop: your own Background has already been painted underneath."""
    layout = room_layout(scene, w, h)
    if layout is None:
        return False
    phase = _phase(controller, phase)
    p.save()
    PAINTERS[scene](p, w, h, controller, phase, layout, backdrop)
    p.restore()
    return True
