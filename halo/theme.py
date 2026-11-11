"""Halo's two lights: the pale gallery wall by day, and the same room after hours.

The light wall is written into the code as plain values. After hours, each of those
values is swapped for its dark counterpart, so one stylesheet or paint routine serves
both. Colours that are not in the table (preview screens, lyric styles, the handset's
own lettering) are the same in both.
"""
import re

from PySide6.QtCore import Qt, QRect, QRectF, QPoint
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


APPEARANCES = (
    ("system", "Match Windows", "Light or dark, following the Windows setting for apps."),
    ("light", "Light", "The pale gallery wall, day and night."),
    ("dark", "Dark", "The gallery after hours: a dark wall under the song's light."),
)

# Light value -> after-hours value.
DARK = {
    "#e7ece6": "#141b18",  # wall
    "#eef2ed": "#19221e",  # wall, top wash
    "#dce3dc": "#0e1412",  # wall, low wash
    "#ffffff": "#1f2925",  # cards and raised controls
    "#fbfcfa": "#26312c",  # raised, hovered
    "#f9fbf8": "#26312c",
    "#f7f9f6": "#26312c",
    "#f3f6f2": "#18201d",  # raised, pressed
    "#eaefe9": "#18201d",
    "#1c2a26": "#e6ece6",  # ink
    "#3e4c47": "#b6c3bc",  # ink, soft
    "#55625e": "#93a29c",  # ink, muted
    "#8d9894": "#66746e",  # disabled lettering
    "#6f7b77": "#7f8d87",
    "#2f5a4f": "#9fd6c4",
    "#f2f4ef": "#121916",  # lettering on ink-filled controls
    "#2b3b36": "#cdd6d0",  # ink-filled, hovered
    "#2f403a": "#cdd6d0",
    "#15201d": "#aab6b0",  # ink-filled, pressed
    "#0f1715": "#bfc9c3",  # ink-filled, edge
    "#2f7d6d": "#5fbfa6",  # focus
    "#24685b": "#8dd5c0",  # accent ink
    "#dcebe3": "#23403a",  # selection
    "#bfe0d2": "#2c5a4e",
    "#c9d2cc": "#33403a",  # switch track, off
    "#b3bdb7": "#45524c",
    "#c3ccc6": "#3a4741",
    "#a7b1ac": "#4d5a54",
    "#8a3b2f": "#f0a08f",  # remove
    "#6d2a20": "#f6bcae",
    "#24342f": "#27332e",  # the handset, lifted a little off the dark wall
    "#1a2723": "#1e2925",
}

# The gallery's named colours, as the light wall has them; after hours they take these values.
DARK_TOKENS = {
    "WALL": "#141b18",
    "WALL_TOP": "#19221e",
    "WALL_LOW": "#0e1412",
    "INK": "#e6ece6",
    "INK_SOFT": "#b6c3bc",
    "INK_MUTED": "#93a29c",
    "CARD": "#1f2925",
    "MAT": "#e8e5dc",
    "FRAME": "#090d0b",
    "FOCUS": "#5fbfa6",
    "ACCENT_INK": "#8dd5c0",
    "SHADOW": "#000000",
    "ON_INK": "#121916",
}

_INK_RGBA = re.compile(r"rgba\(\s*28\s*,\s*42\s*,\s*38\s*,\s*(\d+)\s*\)")
_WHITE_RGBA = re.compile(r"rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*(\d+)\s*\)")
_ACCENT_RGBA = re.compile(r"rgba\(\s*36\s*,\s*104\s*,\s*91\s*,\s*(\d+)\s*\)")
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")

_state = {"dark": False, "styled": False}
_LIGHT_TOKENS = {}


def is_dark():
    return _state["dark"]


def pick(light, dark):
    """The light wall's value, or the after-hours one."""
    return dark if _state["dark"] else light


def hexc(value):
    """A colour written for the light wall, in the current light."""
    if _state["dark"]:
        value = DARK.get(str(value).lower(), value)
    return QColor(value)


def themed(css):
    """A stylesheet written for the light wall, in the current light."""
    if not _state["dark"] or not css:
        return css
    css = _INK_RGBA.sub(lambda m: f"rgba(230, 236, 230, {m.group(1)})", css)
    css = _WHITE_RGBA.sub(lambda m: f"rgba(255, 255, 255, {max(6, round(int(m.group(1)) * .12))})", css)
    css = _ACCENT_RGBA.sub(lambda m: f"rgba(141, 213, 192, {m.group(1)})", css)
    return _HEX.sub(lambda m: DARK.get(m.group(0).lower(), m.group(0)), css)


def style(widget, css):
    """Give a widget a stylesheet that follows the light."""
    widget.setProperty("halo_css", css)
    widget.setStyleSheet(themed(css))
    return widget


def resolve(appearance):
    """Whether this appearance means the dark wall right now."""
    if appearance == "dark":
        return True
    if appearance == "light":
        return False
    hints = QGuiApplication.styleHints() if QGuiApplication.instance() is not None else None
    return hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark


def follow(appearance):
    """Tell Windows which light the window is in, so the title bar matches the wall."""
    if QGuiApplication.instance() is None:
        return
    hints = QGuiApplication.styleHints()
    scheme = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(appearance, Qt.ColorScheme.Unknown)
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(scheme)


def _tokens(dark):
    from . import gallery
    if not _LIGHT_TOKENS:
        _LIGHT_TOKENS.update({name: QColor(getattr(gallery, name)).name() for name in DARK_TOKENS})
    source = DARK_TOKENS if dark else _LIGHT_TOKENS
    for name, value in source.items():
        # The named colours are shared objects: changing them in place reaches every module that uses them.
        getattr(gallery, name).setRgba(QColor(value).rgba())
    gallery.reset_wall()


class rendering:
    """Paint something in a given light without changing the app's, e.g. a share card made after hours."""
    def __init__(self, dark):
        self.dark = bool(dark)
        self.before = None

    def __enter__(self):
        self.before = _state["dark"]
        if self.dark != self.before:
            _state["dark"] = self.dark
            _tokens(self.dark)
        return self

    def __exit__(self, *exc):
        if self.dark != self.before:
            _state["dark"] = self.before
            _tokens(self.before)
        return False


def apply(dark):
    """Switch the whole app to the light or dark wall. Returns True when anything changed."""
    dark = bool(dark)
    changed = dark != _state["dark"]
    _state["dark"] = dark
    _tokens(dark)
    app = QApplication.instance()
    if app is None:
        return changed
    if changed or not _state["styled"]:
        from .glass import APP_STYLE
        app.setStyleSheet(themed(APP_STYLE))
        _state["styled"] = True
    if changed:
        for widget in app.allWidgets():
            css = widget.property("halo_css")
            if isinstance(css, str):
                widget.setStyleSheet(themed(css))
            hook = getattr(widget, "theme_changed", None)
            if callable(hook):
                hook()
            widget.update()
    return changed


class _PaintedIconEngine(QIconEngine):
    """An icon painted when it is shown, so its ink follows the light without making new icons."""
    def __init__(self, paint):
        super().__init__()
        self.paint_icon = paint

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_icon(painter, QRectF(rect), mode)
        painter.restore()

    def pixmap(self, size, mode, state):
        result = QPixmap(size)
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return result

    def clone(self):
        return _PaintedIconEngine(self.paint_icon)


def painted_icon(paint):
    """paint(painter, rect, mode) draws the icon; colours should come from hexc() or the gallery tokens."""
    return QIcon(_PaintedIconEngine(paint))


def line_icon(kind, ink="#1c2a26"):
    def paint(painter, rect, mode):
        from .glass import draw_icon
        colour = hexc(ink)
        if mode == QIcon.Mode.Disabled:
            colour.setAlpha(110)
        draw_icon(painter, kind, rect, colour)
    return painted_icon(paint)
