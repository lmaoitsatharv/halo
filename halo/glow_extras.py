"""Optional light studies, sampled along Halo's continuous screen perimeter.

These are spatial choreographies rather than colour presets. They reuse the
native rim/spill renderer, so animation never allocates a full-screen field.
"""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen


EXTRA_HALO_MODES = (
    ("aurora", "Aurora", "Broad curtains of light fold and drift around the screen."),
    ("echo", "Echo", "Opposing waves meet in luminous, slowly shifting interference."),
    ("meteor", "Meteor", "Three separated comets with bright heads, fading trails and dark space between."),
)
EXTRA_HALO_IDS = frozenset(spec[0] for spec in EXTRA_HALO_MODES)
_TAU = math.tau


def _unit(value):
    return max(0., min(1., value))


def _smooth(value):
    value = _unit(value)
    return value * value * (3. - 2. * value)


def _palette_amount(coordinate, proportion, softness):
    """Retain explicit all-primary/all-secondary and an adjustable light share."""
    if proportion <= 0:
        return 1.
    if proportion >= 1:
        return 0.
    coordinate %= 1.
    transition = min(softness, proportion, 1. - proportion)
    return _smooth((min(coordinate, 1. - coordinate) - proportion * .5) / transition + .5)


def _meteor_heads(phase):
    # One common orbit with bounded, cyclic drift keeps the three heads apart.
    # Independent angular speeds eventually bunched two into an Orbit-like blob.
    return tuple((origin + phase + .018 * math.sin(_TAU * (phase * 2. + origin))) % 1.
                 for origin in (.04, .38, .72))


def extra_colour_function(mode, phase, primary, secondary, proportion):
    """Return an extra-mode sampler, or None for the original five modes.

    The caller supplies brightness-adjusted, premultiplied RGB. Normalising
    back into colour plus alpha preserves saturated hues and transparent black.
    No palette channel or opacity can exceed the listener's requested energy.
    """
    if mode not in EXTRA_HALO_IDS:
        return None
    phase %= 1.

    def sample(distance):
        u = distance % 1.
        if mode == "aurora":
            # A broad slow curtain, with a second fold moving against it. The
            # warp moves colour boundaries organically, rather than rotating
            # one rigid band around the monitor.
            fold = .105 * math.sin(_TAU * (u * 2. - phase))
            fold += .035 * math.sin(_TAU * (u * 5. + phase * 2.))
            coordinate = u - phase + fold
            amount = _palette_amount(coordinate, proportion, .20)
            curtain = (.5 + .5 * math.sin(_TAU * (u * 2. - phase))) ** .8
            undercurrent = .5 + .5 * math.sin(_TAU * (u * 3. + phase * 2.))
            light = .30 + .70 * (.76 * curtain + .24 * undercurrent)
        elif mode == "echo":
            # Two unequal, counter-propagating waves form a changing lattice.
            # Their intersections brighten, split and rejoin without hard cuts.
            outward = .5 + .5 * math.cos(_TAU * (u * 3. - phase))
            returning = .5 + .5 * math.cos(_TAU * (u * 5. + phase * 2.))
            interference = (.62 * outward + .38 * returning) ** 1.65
            light = .17 + .83 * interference
            coordinate = u + phase + .075 * math.sin(_TAU * (u * 2. - phase))
            amount = _palette_amount(coordinate, proportion, .18)
        else:
            # Heads are Gaussian in a cyclic distance axis. A smooth ramp
            # joins each long, one-sided tail, avoiding a flashing cut at the
            # head or at the monitor's top-left wrap point.
            energy = 0.
            for head_at, length, weight in zip(_meteor_heads(phase), (.045, .070, .055), (1., .92, .85)):
                age = (head_at - u) % 1.
                signed = (u - head_at + .5) % 1. - .5
                head = math.exp(-.5 * (signed / .009) ** 2)
                tail = (math.exp(-age / length) * _smooth(age / .025)
                        * (1. - _smooth((age - .40) / .12)))
                energy += weight * (.63 * head + .90 * tail)
            light = .055 + .945 * _unit(energy)
            coordinate = u - phase + .045 * math.sin(_TAU * (u * 3. + phase))
            amount = _palette_amount(coordinate, proportion, .12)
        rgb = tuple(a + (b - a) * amount for a, b in zip(primary, secondary))
        energy = max(rgb)
        if energy <= 1e-6:
            return QColor(0, 0, 0, 0)
        return QColor.fromRgbF(*(channel / energy for channel in rgb),
                               _unit(energy * light))

    # Small preview cards need enough native stops to resolve the bright heads.
    # The renderer retains its fixed stop ceiling at large desktop sizes.
    sample.detail_step = 4. if mode == "meteor" else 12.
    return sample


def extra_spill(mode, phase, beat, music):
    """Broad/tight spill blend; all masks remain bounded and cacheable.

    Audio expands the bloom rather than replacing the spatial choreography.
    Still/reduced-motion states are handled by the caller's frozen phase and
    music gate, exactly as they are for the original light modes.
    """
    if mode == "aurora":
        slow_swell = .5 - .5 * math.cos(_TAU * phase)
        return (.76 + .24 * beat if music else .76 + .24 * slow_swell), .58
    if mode == "echo":
        crossing = .5 - .5 * math.cos(_TAU * phase * 2.)
        return (.42 + .58 * beat if music else .52 + .48 * crossing), .58
    if mode == "meteor":
        wake = .5 - .5 * math.cos(_TAU * phase * 3.)
        return (.38 + .62 * beat if music else .60 + .27 * wake), .42
    return None


def paint_extra_details(painter, w, h, mode, phase, band, strength, opacity, brushes, width_mix):
    """Draw native veil/ripple contours inside the existing spill budget.

    Eight cubic segments per edge replace any per-pixel animation. A strict
    hollow-rectangle clip keeps all decoration inside the configured band.
    The continuous brushes already carry the listener's exact palette/energy.
    """
    if mode not in {"aurora", "echo"} or opacity <= 0 or band < 8:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.setFillRule(Qt.FillRule.OddEvenFill)
    clip.addRect(QRectF(0, 0, w, h))
    if min(w, h) > band * 2:
        clip.addRect(QRectF(band, band, w - band * 2, h - band * 2))
    painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    base_opacity = painter.opacity() * strength * opacity
    spread = .45 + .55 * width_mix
    if mode == "aurora":
        r = min(16., min(w, h) / 4)
        for side, brush in enumerate(brushes):
            length = (w if side % 2 == 0 else h) - 2 * r

            def point_and_tangent(t):
                a = math.tau * (t * 1.7 - phase + side * .19)
                b = math.tau * (t * 3.2 + phase * 2. - side * .13)
                depth = band * spread * (.32 + .10 * math.sin(a) + .04 * math.sin(b))
                derivative = band * spread * math.tau * (.17 * math.cos(a) + .128 * math.cos(b))
                if side == 0:
                    return QPointF(r + length * t, depth), QPointF(length, derivative)
                if side == 1:
                    return QPointF(w - depth, r + length * t), QPointF(-derivative, length)
                if side == 2:
                    return QPointF(w - r - length * t, h - depth), QPointF(-length, -derivative)
                return QPointF(depth, h - r - length * t), QPointF(derivative, -length)

            path = QPainterPath()
            start, tangent = point_and_tangent(0.)
            path.moveTo(start)
            for segment in range(8):
                finish, next_tangent = point_and_tangent((segment + 1) / 8)
                path.cubicTo(start + tangent / 24, finish - next_tangent / 24, finish)
                start, tangent = finish, next_tangent
            for width, alpha in ((max(3., band * .12), .075), (max(1.5, band * .05), .13), (1., .21)):
                painter.setOpacity(base_opacity * alpha)
                painter.setPen(QPen(QBrush(brush), width, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(path)
    else:
        # Each wave fades at both ends of its travel, so wrapping a ripple
        # from the inner edge back to the rim never creates a visible snap.
        for index in range(3):
            travel = (phase + index / 3) % 1.
            fade = math.sin(math.pi * travel) ** 1.2
            depth = band * spread * (.10 + .68 * travel)
            rect = QRectF(depth, depth, w - depth * 2, h - depth * 2)
            for width, alpha in ((4., .08), (1., .22)):
                painter.setOpacity(base_opacity * fade * alpha)
                painter.setPen(QPen(QBrush(brushes[0]), width, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawRoundedRect(rect, max(3., 16. - depth * .2), max(3., 16. - depth * .2))
    painter.restore()
