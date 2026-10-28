"""Shared Qt test environment helpers."""
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFontDatabase


def ensure_system_fonts():
    """Headless platforms such as offscreen may start with no fonts at all.

    Glyph checks would then measure missing-glyph boxes, so register the
    operating system's own fonts. Native platforms already have them.
    """
    if QFontDatabase.families():
        return
    for folder in QStandardPaths.standardLocations(QStandardPaths.StandardLocation.FontsLocation):
        for path in sorted(Path(folder).glob("*")):
            if path.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                QFontDatabase.addApplicationFont(str(path))
    if not QFontDatabase.families():
        raise RuntimeError("No fonts are available to the Qt platform")
