"""Optional listening spaces, painted natively behind real artwork and lyrics.

These are complete scene compositions rather than colour presets. Layout and
painting share the same geometry so both the immersive window and the Modes
library can render the real scene at their own logical reference size.
"""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter,
                          QPainterPath, QPen, QRadialGradient)

from .room_light import _artwork_image
from .scene_rooms import ROOM_CAPTIONS, ROOM_SCENES, paint_room, room_layout


EXTRA_SCENES = (
    ("scene_gallery", "Gallery", "A framed album exhibition, luminous walls and an editorial lyric stage."),
    ("scene_runway", "Runway", "A deep light corridor with a moving perspective floor and panoramic lyrics."),
    ("scene_refraction", "Refraction", "Drifting glass facets, spectral ribbons and an offset album portrait."),
)

_EXTRA_CAPTIONS = {
    "scene_gallery": "THE SOUND GALLERY",
    "scene_runway": "FOLLOW THE LIGHT",
    "scene_refraction": "COLOUR IN A DIFFERENT LIGHT",
}
# Every room drawn by a scene painter (the built-in Flow, Vinyl and Horizon, and the extras).
SCENE_CAPTIONS = {**ROOM_CAPTIONS, **_EXTRA_CAPTIONS}
PAINTED_SCENES = tuple(ROOM_SCENES) + EXTRA_SCENES
# Rooms that keep the song's credits small in a lower corner, beside a thumbnail.
COMPACT_CREDITS = frozenset({"cinema", "scene_runway", "horizon"})


def _colour(value, opacity):
    colour = QColor(value)
    colour.setAlphaF(max(0., min(1., opacity)))
    return colour


def _phase(controller, supplied):
    if getattr(controller, "reduced_motion", False):
        return 0.
    if not getattr(controller.track, "playing", False):
        return float(getattr(controller, "motion_time", 0.))
    return float(supplied)


def _body(w, h):
    margin = max(28, min(76, round(w * .04)))
    top = 92 if h < 720 else 108
    bottom = max(top + 120, h - (140 if h < 720 else 164))
    return margin, top, bottom, bottom - top


def _rect(x, y, width, height):
    return QRect(round(x), round(y), max(1, round(width)), max(1, round(height)))


def extra_scene_layout(scene, w, h):
    """Return native child geometry, or None for a scene owned by Halo itself.

    Header and transport remain owned by Immersive. Rectangles are logical
    pixels; the library may paint them at a scaled reference resolution.
    """
    room = room_layout(scene, w, h)
    if room is not None:
        return room
    if scene not in _EXTRA_CAPTIONS:
        return None
    w, h = max(480, int(w)), max(400, int(h))
    margin, top, bottom, body = _body(w, h)
    if scene == "scene_gallery":
        column = round(w * .35)
        size = max(100, min(420, round(w * .28), body - 146))
        x = margin + (column - size) // 2
        y = top + max(16, (body - size - 128) // 2)
        lyric_x = margin + column + max(30, round(w * .025))
        song_y = y + size + 24
        return {
            "cover": _rect(x, y, size, size),
            "canvas": _rect(lyric_x, top + 24, w - lyric_x - margin, body - 40),
            "song": _rect(margin + 8, song_y, column - 16, 46),
            "artist": _rect(margin + 8, song_y + 50, column - 16, 24),
            "album": _rect(margin + 8, song_y + 77, column - 16, 20),
            "status": _rect(lyric_x + 8, top - 5, w - lyric_x - margin - 16, 18),
            "alignment": "left",
        }
    if scene == "scene_runway":
        credit_y = bottom - 55
        return {
            "cover": _rect(margin + 6, credit_y, 48, 48),
            "canvas": _rect(w * .125, top + 8, w * .75, body - 92),
            "song": _rect(margin + 68, credit_y, min(w * .37, 440), 19),
            "artist": _rect(margin + 68, credit_y + 21, min(w * .37, 440), 16),
            "album": _rect(margin + 68, credit_y + 38, min(w * .37, 440), 14),
            "status": _rect(w - margin - 210, credit_y + 30, 210, 18),
            "alignment": "center",
        }
    size = max(104, min(360, round(w * .25), round(body * .48)))
    art_x = round(w * .78 - size * .5)
    art_y = top + max(18, round(body * .13))
    credit_x = max(art_x - 18, round(w * .61))
    credit_width = max(100, w - margin - credit_x)
    song_y = art_y + size + 30
    return {
        "cover": _rect(art_x, art_y, size, size),
        "canvas": _rect(margin + 8, top + 16, w * .55 - margin, body - 32),
        "song": _rect(credit_x, song_y, credit_width, 46),
        "artist": _rect(credit_x, song_y + 51, credit_width, 24),
        "album": _rect(credit_x, song_y + 79, credit_width, 20),
        "status": _rect(margin + 12, top - 8, w * .50 - margin, 18),
        "alignment": "left",
    }


def _image_crop(p, image, rect, opacity=1.):
    if image.isNull():
        return
    ratio = max(rect.width() / image.width(), rect.height() / image.height())
    width, height = rect.width() / ratio, rect.height() / ratio
    source = QRectF((image.width() - width) / 2, (image.height() - height) / 2, width, height)
    p.save()
    p.setOpacity(opacity)
    p.drawImage(rect, image, source)
    p.restore()


def _gallery(p, w, h, c, phase, layout):
    margin, top, bottom, body = _body(w, h)
    art = QRectF(layout["cover"])
    canvas = QRectF(layout["canvas"])
    divider = canvas.left() - 24
    wash = QLinearGradient(0, 0, w, h)
    wash.setColorAt(0, _colour(c.primary, .10))
    wash.setColorAt(.45, QColor(12, 12, 15, 32))
    wash.setColorAt(1, QColor(4, 6, 12, 70))
    p.fillRect(QRectF(0, 0, w, h), wash)
    # Exhibition wall: offset seams, a slow travelling overhead pool of light.
    p.setPen(QPen(_colour(c.primary, .10), 1))
    p.drawLine(QPointF(divider, top - 12), QPointF(divider, bottom + 4))
    p.drawLine(QPointF(margin, top - 12), QPointF(divider - 32, top - 12))
    spot = QRadialGradient(art.center().x() + math.sin(phase * .10) * art.width() * .12,
                           art.top() - art.width() * .15, art.width() * 1.2)
    spot.setColorAt(0, _colour(c.primary, .15))
    spot.setColorAt(.48, _colour(c.secondary, .035))
    spot.setColorAt(1, _colour(c.primary, 0))
    p.fillRect(QRectF(margin - 20, top, divider - margin + 16, body), spot)
    # A real matte and a slim floating frame rather than another rounded card.
    frame = art.adjusted(-15, -15, 15, 15)
    shadow = QLinearGradient(0, frame.bottom(), 0, frame.bottom() + 45)
    shadow.setColorAt(0, QColor(0, 0, 0, 82))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(frame.left() - 8, frame.bottom(), frame.width() + 16, 45), shadow)
    matte = QLinearGradient(frame.topLeft(), frame.bottomRight())
    matte.setColorAt(0, QColor("#d8d0be"))
    matte.setColorAt(.65, QColor("#a7a18e"))
    matte.setColorAt(1, QColor("#e5decc"))
    p.fillRect(frame, matte)
    # A grazing key-light travels over the physical matte, never the lyrics.
    # Its visible scan distinguishes an exhibition from the floating cover room.
    matte_path = QPainterPath()
    matte_path.addRect(frame)
    image_path = QPainterPath()
    image_path.addRect(art)
    scan_x = frame.left() - 60 + (frame.width() + 120) * (.5 + .5 * math.sin(phase * .32))
    sheen = QLinearGradient(scan_x - 48, frame.top(), scan_x + 48, frame.bottom())
    sheen.setColorAt(0, QColor(255, 250, 230, 0))
    sheen.setColorAt(.43, QColor(255, 250, 230, 13))
    sheen.setColorAt(.5, QColor(255, 250, 230, 125))
    sheen.setColorAt(.58, QColor(255, 250, 230, 20))
    sheen.setColorAt(1, QColor(255, 250, 230, 0))
    p.save()
    p.setClipPath(matte_path.subtracted(image_path), Qt.ClipOperation.IntersectClip)
    p.fillRect(frame, sheen)
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 115), 1))
    p.drawRect(frame.adjusted(.5, .5, -.5, -.5))
    p.setPen(QPen(QColor(0, 0, 0, 150), 1))
    p.drawRect(art.adjusted(-2, -2, 2, 2))
    # Quiet typographic rule on the right echoes a printed exhibition label.
    p.setPen(QPen(_colour(c.primary, .22), 1))
    p.drawLine(QPointF(canvas.left() + 8, bottom + 3), QPointF(canvas.left() + min(140, canvas.width() * .27), bottom + 3))


def _runway(p, w, h, c, phase, layout):
    margin, top, bottom, body = _body(w, h)
    horizon = top + body * .76
    centre = w * .5
    p.fillRect(QRectF(0, 0, w, h), QColor(3, 5, 13, 35))
    haze = QRadialGradient(centre, horizon, w * .58)
    haze.setColorAt(0, _colour(c.primary, .16))
    haze.setColorAt(.37, _colour(c.secondary, .045))
    haze.setColorAt(1, _colour(c.secondary, 0))
    p.fillRect(QRectF(0, 0, w, h), haze)
    # Deep side walls leave the centre entirely available to lyrics.
    for side in (-1, 1):
        outer = 0 if side < 0 else w
        inner = w * (.27 if side < 0 else .73)
        panel = QPainterPath()
        panel.moveTo(outer, top - 40)
        panel.lineTo(inner, top + body * .1)
        panel.lineTo(centre + side * w * .16, horizon)
        panel.lineTo(outer, h)
        panel.closeSubpath()
        wall = QLinearGradient(outer, 0, inner, 0)
        wall.setColorAt(0, _colour(c.secondary, .095))
        wall.setColorAt(1, _colour(c.primary, .015))
        p.fillPath(panel, wall)
        for i in range(4):
            fraction = (i + 1) / 5
            x = outer + (inner - outer) * fraction
            depth = top + body * .08 * fraction
            foot = centre + side * w * (.16 + (1 - fraction) * .13)
            glow = .15 + .09 * (.5 + .5 * math.sin(phase * .3 - i * .8))
            colour = c.primary if i % 2 == 0 else c.secondary
            p.setPen(QPen(_colour(colour, glow * .17), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x, depth), QPointF(foot, horizon))
            p.setPen(QPen(_colour(colour, glow), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x, depth), QPointF(foot, horizon))
    # Perspective floor is clipped below the reading stage. Its ruled lines
    # travel towards the listener; no fake volume bars or simulated beat data.
    p.save()
    p.setClipRect(QRectF(0, horizon, w, h - horizon))
    for i in range(-6, 7):
        end = centre + i * w * .18
        p.setPen(QPen(_colour(c.secondary, .085), 1))
        p.drawLine(QPointF(centre + i * w * .025, horizon), QPointF(end, h + 80))
    travel = (phase * .08) % 1
    for i in range(13):
        depth = ((i + travel) / 13) ** 2
        y = horizon + depth * (h - horizon + 24)
        p.setPen(QPen(_colour(c.primary, .035 + depth * .14), .7 + depth * .7))
        p.drawLine(QPointF(0, y), QPointF(w, y))
    p.restore()
    p.setPen(QPen(_colour(c.primary, .16), 1))
    p.drawLine(QPointF(w * .13, horizon), QPointF(w * .87, horizon))
    # A tiny distant source anchors the corridor without crossing lyric text.
    beacon = QRadialGradient(centre, horizon, w * .13)
    beacon.setColorAt(0, _colour(c.primary, .22))
    beacon.setColorAt(.25, _colour(c.secondary, .055))
    beacon.setColorAt(1, _colour(c.primary, 0))
    p.fillRect(QRectF(centre - w * .16, horizon - 20, w * .32, 70), beacon)


_GLASS_LAYERS = {}


def _refraction(p, w, h, c, phase, layout):
    margin, top, bottom, body = _body(w, h)
    art = QRectF(layout["cover"])
    # The glass field is drawn on its own layer and faded out at its edges;
    # a hard clip used to leave a visible rectangle in the room.
    region = QRectF(w * .53, top - 40, w * .47, body + 105)
    transform = p.worldTransform()
    scale = max(.25, min(2., math.hypot(transform.m11(), transform.m12())))
    size = (max(1, round(region.width() * scale)), max(1, round(region.height() * scale)))
    layer = _GLASS_LAYERS.get(size)
    if layer is None:
        # One reusable layer per drawn size avoids a large allocation on every frame.
        if len(_GLASS_LAYERS) >= 3:
            _GLASS_LAYERS.clear()
        layer = _GLASS_LAYERS[size] = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)
    q = QPainter(layer)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    q.scale(scale, scale)
    q.translate(-region.x(), -region.y())
    _glass_field(q, w, c, phase, art, top, bottom, body)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    across = QLinearGradient(w * .53, 0, w * .62, 0)
    across.setColorAt(0, QColor(0, 0, 0, 0))
    across.setColorAt(1, QColor(0, 0, 0, 255))
    q.fillRect(region, across)
    span = body + 95
    down = QLinearGradient(0, top - 35, 0, bottom + 60)
    down.setColorAt(0, QColor(0, 0, 0, 0))
    down.setColorAt(min(.45, 75 / span), QColor(0, 0, 0, 255))
    down.setColorAt(max(.55, 1 - 80 / span), QColor(0, 0, 0, 255))
    down.setColorAt(1, QColor(0, 0, 0, 0))
    q.fillRect(region, down)
    q.end()
    p.drawImage(region, layer)
    # A fine corner bracket turns the foreground artwork into an object.
    p.setPen(QPen(_colour(c.primary, .32), 1))
    for point, dx, dy in ((art.topLeft() - QPointF(9, 9), 1, 1),
                          (art.bottomRight() + QPointF(9, 9), -1, -1)):
        p.drawLine(point, point + QPointF(dx * 26, 0))
        p.drawLine(point, point + QPointF(0, dy * 26))


def _glass_field(p, w, c, phase, art, top, bottom, body):
    image = _artwork_image(getattr(c.track, "artwork", b""))
    x0 = w * .59
    # A diagonal architectural glass field counterbalances the left lyric stage.
    p.save()
    for i in range(7):
        offset = (i - 3) * art.width() * .16
        drift = math.sin(phase * (.09 + i * .005) + i * .65) * art.width() * .025
        path = QPainterPath()
        path.moveTo(x0 + offset + drift, bottom + 60)
        path.lineTo(x0 + art.width() * .73 + offset + drift, top - 35)
        path.lineTo(x0 + art.width() * 1.38 + offset + drift, top - 35)
        path.lineTo(x0 + art.width() * .63 + offset + drift, bottom + 60)
        path.closeSubpath()
        gradient = QLinearGradient(x0 + offset, top, x0 + offset + art.width(), bottom)
        gradient.setColorAt(0, _colour(c.primary, .025 + i * .004))
        gradient.setColorAt(.45, _colour(c.secondary, .035))
        gradient.setColorAt(.72, _colour(c.primary, .075 if i in (1, 4) else .025))
        gradient.setColorAt(1, _colour(c.secondary, 0))
        p.fillPath(path, gradient)
        p.setPen(QPen(_colour(c.primary if i % 2 else c.secondary, .075), .8))
        p.drawLine(QPointF(x0 + offset + drift, bottom + 60),
                   QPointF(x0 + art.width() * .73 + offset + drift, top - 35))
    # Art is echoed through thin, offset panes; the actual cover remains the
    # crisp, untransformed native foreground child.
    for i in range(3):
        pane = art.adjusted(-19 - i * 15, -12 + i * 9, 19 + i * 15, 12 + i * 9)
        p.save()
        p.translate(pane.center())
        p.rotate(-8 + i * 3 + math.sin(phase * .12 + i) * .7)
        local = QRectF(-pane.width() / 2, -pane.height() / 2, pane.width(), pane.height())
        glass = QPainterPath()
        glass.addRoundedRect(local, 5, 5)
        p.setClipPath(glass, Qt.ClipOperation.IntersectClip)
        if not image.isNull():
            _image_crop(p, image, local, .075 + i * .018)
        p.fillRect(local, _colour(c.primary if i % 2 else c.secondary, .035))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_colour(c.primary, .13), 1))
        p.drawRoundedRect(local.adjusted(.5, .5, -.5, -.5), 5, 5)
        p.restore()
    # Fluid ribbons bend independently through the panes, with slow parallax.
    for i in range(3):
        x = art.center().x() + (i - 1) * art.width() * .46
        wave = math.sin(phase * .14 + i * 1.7) * art.width() * .18
        ribbon = QPainterPath()
        ribbon.moveTo(x - art.width() * .25, top - 35)
        ribbon.cubicTo(x + wave + art.width() * .7, top + body * .32,
                      x - wave - art.width() * .6, top + body * .7,
                      x + art.width() * .17, bottom + 45)
        p.setPen(QPen(_colour(c.secondary if i % 2 else c.primary, .022), 22,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(ribbon)
        p.setPen(QPen(_colour(c.secondary if i % 2 else c.primary, .13), 1.1,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(ribbon)
    p.restore()


def paint_extra_scene(p, w, h, controller, scene, phase, backdrop=False):
    """Paint an optional scene behind the real native cover, text and controls."""
    if room_layout(scene, w, h) is not None:
        return paint_room(p, w, h, controller, scene, phase, backdrop)
    layout = extra_scene_layout(scene, w, h)
    if layout is None:
        return False
    phase = _phase(controller, phase)
    p.save()
    if scene == "scene_gallery":
        _gallery(p, w, h, controller, phase, layout)
    elif scene == "scene_runway":
        _runway(p, w, h, controller, phase, layout)
    else:
        _refraction(p, w, h, controller, phase, layout)
    p.restore()
    return True
