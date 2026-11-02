"""Convert SVG path data and basic shape elements into Qt painter paths."""
import math
import re
from collections.abc import Iterable, Mapping

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform


_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_SEPARATORS = re.compile(r"[\s,]*")
_LETTERS = "MLHVCSQTAZmlhvcsqtaz"
# One letter per argument: n is a number, f an arc flag (a single 0 or 1 character).
_ARGUMENTS = {"M": "nn", "L": "nn", "H": "n", "V": "n", "C": "nnnnnn", "S": "nnnn",
              "Q": "nnnn", "T": "nn", "A": "nnnffnn", "Z": ""}


class _Reader:
    """Cursor over path data that reads command letters, numbers and arc flags."""
    def __init__(self, text):
        self.text = text
        self.index = 0
        self._skip()

    def _skip(self):
        self.index = _SEPARATORS.match(self.text, self.index).end()

    def done(self):
        return self.index >= len(self.text)

    def command(self):
        """Consume a command letter if one is next, else return None."""
        char = self.text[self.index]
        if char not in _LETTERS:
            return None
        self.index += 1
        self._skip()
        return char

    def number(self):
        match = _NUMBER.match(self.text, self.index)
        if not match:
            raise ValueError(f"expected a number at position {self.index}")
        self.index = match.end()
        self._skip()
        return float(match.group())

    def flag(self):
        char = self.text[self.index:self.index + 1]
        if char not in ("0", "1"):
            raise ValueError(f"expected an arc flag at position {self.index}")
        self.index += 1
        self._skip()
        return char == "1"

    def values(self, kinds):
        return [self.number() if kind == "n" else self.flag() for kind in kinds]


def _reflect(control, current):
    """Mirror the previous control point through the current point, if there was one."""
    return current if control is None else current * 2 - control


def _arc(path, start, rx, ry, rotation, large, sweep, end):
    """Append an SVG arc as cubic segments of at most 90 degrees (SVG 1.1 F.6.5)."""
    rx, ry = abs(rx), abs(ry)
    if start == end:
        return
    if not rx or not ry:
        path.lineTo(end)
        return
    phi = math.radians(rotation % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    half_x, half_y = (start.x() - end.x()) / 2, (start.y() - end.y()) / 2
    x1 = cos_phi * half_x + sin_phi * half_y
    y1 = -sin_phi * half_x + cos_phi * half_y
    excess = x1 ** 2 / rx ** 2 + y1 ** 2 / ry ** 2
    if excess > 1:
        scale = math.sqrt(excess)
        rx, ry = rx * scale, ry * scale
    numerator = rx ** 2 * ry ** 2 - rx ** 2 * y1 ** 2 - ry ** 2 * x1 ** 2
    denominator = rx ** 2 * y1 ** 2 + ry ** 2 * x1 ** 2
    factor = math.sqrt(max(0., numerator / denominator))
    if large == sweep:
        factor = -factor
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos_phi * cx1 - sin_phi * cy1 + (start.x() + end.x()) / 2
    cy = sin_phi * cx1 + cos_phi * cy1 + (start.y() + end.y()) / 2
    theta = math.atan2((y1 - cy1) / ry, (x1 - cx1) / rx)
    delta = math.atan2((-y1 - cy1) / ry, (-x1 - cx1) / rx) - theta
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    segments = max(1, math.ceil(abs(delta) / (math.pi / 2) - 1e-9))
    step = delta / segments
    handle = 4 / 3 * math.tan(step / 4)

    def mapped(ux, uy):
        return QPointF(cx + rx * ux * cos_phi - ry * uy * sin_phi,
                       cy + rx * ux * sin_phi + ry * uy * cos_phi)

    for index in range(segments):
        a = theta + index * step
        b = a + step
        path.cubicTo(mapped(math.cos(a) - handle * math.sin(a), math.sin(a) + handle * math.cos(a)),
                     mapped(math.cos(b) + handle * math.sin(b), math.sin(b) - handle * math.cos(b)),
                     end if index == segments - 1 else mapped(math.cos(b), math.sin(b)))


def parse_path_data(d: str) -> QPainterPath:
    """Build a path from SVG path data; malformed data raises ValueError."""
    path = QPainterPath()
    reader = _Reader(d)
    command = None
    current = start = QPointF(0, 0)
    last_cubic = last_quad = None
    while not reader.done():
        letter = reader.command()
        if letter is not None:
            if command is None and letter not in "Mm":
                raise ValueError("path data must start with a moveto")
            command = letter
        elif command is None or command in "Zz":
            raise ValueError(f"unexpected number at position {reader.index}")
        upper = command.upper()
        args = reader.values(_ARGUMENTS[upper])
        origin = current if command != upper else QPointF(0, 0)
        ox, oy = origin.x(), origin.y()
        previous_cubic, previous_quad = last_cubic, last_quad
        last_cubic = last_quad = None
        if upper == "H":
            points = [QPointF(args[0] + ox, current.y())]
        elif upper == "V":
            points = [QPointF(current.x(), args[0] + oy)]
        elif upper == "A":
            points = [QPointF(args[5] + ox, args[6] + oy)]
        else:
            points = [QPointF(args[i] + ox, args[i + 1] + oy) for i in range(0, len(args), 2)]
        if upper == "M":
            current = start = points[0]
            path.moveTo(current)
            command = "l" if command == "m" else "L"
        elif upper in "LHV":
            current = points[0]
            path.lineTo(current)
        elif upper == "C":
            path.cubicTo(*points)
            last_cubic, current = points[1], points[2]
        elif upper == "S":
            path.cubicTo(_reflect(previous_cubic, current), *points)
            last_cubic, current = points[0], points[1]
        elif upper == "Q":
            path.quadTo(*points)
            last_quad, current = points[0], points[1]
        elif upper == "T":
            last_quad = _reflect(previous_quad, current)
            path.quadTo(last_quad, points[0])
            current = points[0]
        elif upper == "A":
            _arc(path, current, *args[:5], points[0])
            current = points[0]
        else:
            path.closeSubpath()
            current = start
    return path


def _points(text):
    reader = _Reader(text)
    values = []
    while not reader.done():
        values.append(reader.number())
    if len(values) % 2:
        raise ValueError("points need an x and a y for every vertex")
    return [QPointF(x, y) for x, y in zip(values[::2], values[1::2])]


def element_path(tag: str, attrs: Mapping[str, str]) -> QPainterPath:
    """Convert one SVG shape element to a path; unknown tags or bad values raise ValueError."""
    def number(name):
        return float(attrs.get(name, 0))

    path = QPainterPath()
    if tag == "path":
        return parse_path_data(attrs.get("d", ""))
    if tag == "circle":
        if number("r") > 0:
            path.addEllipse(QPointF(number("cx"), number("cy")), number("r"), number("r"))
    elif tag == "ellipse":
        if number("rx") > 0 and number("ry") > 0:
            path.addEllipse(QPointF(number("cx"), number("cy")), number("rx"), number("ry"))
    elif tag == "line":
        path.moveTo(number("x1"), number("y1"))
        path.lineTo(number("x2"), number("y2"))
    elif tag == "rect":
        width, height = number("width"), number("height")
        if width > 0 and height > 0:
            rect = QRectF(number("x"), number("y"), width, height)
            rx = number("rx") if "rx" in attrs else number("ry")
            ry = number("ry") if "ry" in attrs else rx
            rx, ry = min(abs(rx), width / 2), min(abs(ry), height / 2)
            if rx and ry:
                path.addRoundedRect(rect, rx, ry)
            else:
                path.addRect(rect)
    elif tag in ("polyline", "polygon"):
        points = _points(attrs.get("points", ""))
        if points:
            path.moveTo(points[0])
            for point in points[1:]:
                path.lineTo(point)
            if tag == "polygon":
                path.closeSubpath()
    else:
        raise ValueError(f"unsupported SVG element: {tag}")
    return path


def icon_path(elements: Iterable[tuple[str, Mapping[str, str]]]) -> QPainterPath:
    """Combine Lucide elements and map its 24x24 grid to the unit box, (value - 12) / 10."""
    path = QPainterPath()
    for tag, attrs in elements:
        path.addPath(element_path(tag, attrs))
    return QTransform.fromScale(.1, .1).map(path.translated(-12, -12))
