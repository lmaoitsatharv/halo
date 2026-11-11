"""Lyric share cards: one line of the song, lettered large on the gallery wall under the cover's light.

The card is composed like the Listening page: the print with its museum label beside it, and the
line below as wall lettering. It comes on the light wall or the dark one. Cards are drawn on this
PC and only leave it when the listener copies or saves one.
"""
import re
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QStandardPaths, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QFont, QFontMetricsF, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QFileDialog,
                               QButtonGroup)

from .gallery import (INK, INK_SOFT, INK_MUTED, CARD, face, tint, paint_wall, paint_spotlight,
                      paint_shadow, ink_accent)
from .wall import paint_framed_print
from . import theme

CARD_SIZE = QSize(1080, 1350)
MARGIN = 88


def _wrap(text, font, width):
    metrics = QFontMetricsF(font)
    rows, row = [], ""
    for word in text.split():
        trial = f"{row} {word}".strip()
        if row and metrics.horizontalAdvance(trial) > width:
            rows.append(row)
            row = word
        else:
            row = trial
    if row:
        rows.append(row)
    return rows


def fit_lettering(text, width, height, largest=136, smallest=44, max_rows=5):
    """The largest wall lettering that keeps the line inside its block."""
    size = largest
    while True:
        font = face(size, QFont.Weight.DemiBold, display=True)
        rows = _wrap(text, font, width)
        line_height = QFontMetricsF(font).height() * 1.0
        if (len(rows) <= max_rows and len(rows) * line_height <= height) or size <= smallest:
            if size <= smallest and len(rows) > max_rows:
                rows = rows[:max_rows]
                rows[-1] = rows[-1].rstrip(" ,.;:") + "…"
            return font, rows, line_height
        size -= 2


def _clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _paint_label(p, left, top, width, title, artist, album, sung_at):
    """The museum label: title, artist, album, and where in the song the line is sung. Returns its rect."""
    pad_x, pad_top, pad_bottom = 32, 30, 30
    inner = width - pad_x * 2
    title_font = face(36, QFont.Weight.DemiBold, display=True)
    rows = _wrap(title or "Untitled", title_font, inner)[:3]
    title_height = QFontMetricsF(title_font).height() * 1.02
    artist_font, album_font, note_font = face(24), face(20), face(19, QFont.Weight.Medium)
    lines = [(artist_font, INK_SOFT, artist)] if artist else []
    if album:
        lines.append((album_font, INK_MUTED, album))
    height = pad_top + len(rows) * title_height + 8
    height += sum(QFontMetricsF(font).height() + 4 for font, _, _ in lines)
    if sung_at is not None:
        height += 30 + QFontMetricsF(note_font).height()
    height += pad_bottom
    label = QRectF(left, top, width, height)
    paint_shadow(p, label, 4, 14, .2, 6)
    paint_shadow(p, label, 4, 3, .12, 1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(CARD)
    p.drawRoundedRect(label, 4, 4)
    y = top + pad_top
    p.setFont(title_font)
    p.setPen(INK)
    metrics = QFontMetricsF(title_font)
    for index, row in enumerate(rows):
        if index == len(rows) - 1 and len(_wrap(title or "Untitled", title_font, inner)) > len(rows):
            row = metrics.elidedText(row + " …", Qt.TextElideMode.ElideRight, inner)
        p.drawText(QPointF(left + pad_x, y + metrics.ascent()), row)
        y += title_height
    y += 8
    for font, colour, text in lines:
        metrics = QFontMetricsF(font)
        p.setFont(font)
        p.setPen(colour)
        p.drawText(QPointF(left + pad_x, y + metrics.ascent()),
                   metrics.elidedText(text, Qt.TextElideMode.ElideRight, inner))
        y += metrics.height() + 4
    if sung_at is not None:
        y += 14
        p.setPen(QPen(tint(INK, 40), 1))
        p.drawLine(QPointF(left + pad_x, y), QPointF(left + pad_x + 48, y))
        y += 16
        p.setFont(note_font)
        p.setPen(INK_MUTED)
        p.drawText(QPointF(left + pad_x, y + QFontMetricsF(note_font).ascent()), f"Sung at {_clock(sung_at)}")
    return label


def _paint_mark(p, centre, primary):
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(tint(INK, 46), 6))
    p.drawEllipse(centre, 22, 22)
    p.setPen(QPen(ink_accent(primary, target=3.2), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(centre.x() - 22, centre.y() - 22, 44, 44), 40 * 16, 245 * 16)
    p.setFont(face(30, QFont.Weight.DemiBold))
    p.setPen(INK)
    p.drawText(QPointF(centre.x() + 34, centre.y() + 11), "halo")


def render_share_card(title, artist, line, artwork=b"", primary=QColor("#b7e4ad"), secondary=QColor("#54ad9f"),
                      dark=False, album="", sung_at=None):
    """A 1080x1350 PNG-ready image: the wall, the song's light, the print and its label, and the line."""
    with theme.rendering(dark):
        return _render(title, artist, (line or "").strip(), artwork, QColor(primary), QColor(secondary), album, sung_at, dark)


def _render(title, artist, line, artwork, primary, secondary, album, sung_at, dark):
    width, height = CARD_SIZE.width(), CARD_SIZE.height()
    image = QImage(CARD_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#141b18" if dark else "#e7ece6"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    paint_wall(p, QRectF(0, 0, width, height))
    pixmap = QPixmap()
    if artwork:
        pixmap.loadFromData(artwork)
    left, right = float(MARGIN), float(width - MARGIN)
    if line:
        side = 468.
        frame = QRectF(left, 100, side, side)
        # The light spills from the print down across the lettering in the song's second colour.
        paint_spotlight(p, QPointF(width * .7, height * .76), 560, secondary, primary, .42 if dark else .5, 3.)
        paint_spotlight(p, frame.center() - QPointF(0, 24), side * 1.24, primary, secondary, .92 if dark else 1., 0.)
        paint_framed_print(p, frame, pixmap, primary)
        column = frame.right() + 48
        _paint_label(p, column, frame.top(), right - column, title, artist, album, sung_at)
        _paint_mark(p, QPointF(column + 24, frame.bottom() - 24), primary)
        top, bottom = frame.bottom() + 92, height - 96.
        font, rows, line_height = fit_lettering(line, right - left, bottom - top)
        ascent = QFontMetricsF(font).ascent()
        block = len(rows) * line_height
        y = top + max(0., (bottom - top - block) * .42)
        p.setFont(font)
        p.setPen(INK)
        for index, row in enumerate(rows):
            p.drawText(QPointF(left, y + index * line_height + ascent), row)
    else:
        side = 620.
        # Print, gap and label (about 190px) sit as one group in the middle of the card.
        frame = QRectF((width - side) / 2, (height - (side + 96 + 190)) / 2, side, side)
        paint_spotlight(p, frame.center() - QPointF(0, 24), side * 1.2, primary, secondary, .92 if dark else 1., 0.)
        paint_framed_print(p, frame, pixmap, primary)
        label = _paint_label(p, left, frame.bottom() + 96, right - left - 230, title, artist, album, None)
        _paint_mark(p, QPointF(right - 120, label.center().y()), primary)
    p.end()
    return image


def default_file_name(title, artist):
    stem = " - ".join(part for part in (artist, title) if part) or "Halo lyric card"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", stem).strip(" .") or "Halo lyric card"
    return stem[:120] + ".png"


def default_folder():
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return Path(pictures or Path.home()) / "Halo"


class ShareCardDialog(QDialog):
    """Pick a line and a wall, see the card, then copy it or save it as a PNG."""
    def __init__(self, owner, controller):
        super().__init__(owner)
        from .frontend import action, text_label
        from .glass import icon
        self.owner, self.c = owner, controller
        self.index = -1
        self.dark = theme.is_dark()
        self.image = QImage()
        self.setObjectName("shareCard")
        self.setStyleSheet("QDialog#shareCard { background: transparent; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(22)
        self.preview = QLabel()
        self.preview.setFixedSize(288, 360)
        self.preview.setAccessibleName("Lyric card preview")
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        side.setSpacing(10)
        self.line_label = QLabel()
        self.line_label.setWordWrap(True)
        theme.style(self.line_label, "font-size: 15px; color: #1c2a26;")
        self.line_label.setMinimumHeight(64)
        self.line_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        side.addWidget(self.line_label)
        stepper = QHBoxLayout()
        self.earlier = action("Earlier line", lambda: self.step(-1))
        self.earlier.setIcon(icon("back", "#1c2a26", 16))
        self.later = action("Later line", lambda: self.step(1))
        self.later.setIcon(icon("forward", "#1c2a26", 16))
        stepper.addWidget(self.earlier)
        stepper.addWidget(self.later)
        side.addLayout(stepper)
        walls = QHBoxLayout()
        walls.setSpacing(6)
        self.walls = QButtonGroup(self)
        self.light_wall = action("Light wall", lambda: self.set_dark(False))
        self.dark_wall = action("Dark wall", lambda: self.set_dark(True))
        for button in (self.light_wall, self.dark_wall):
            button.setCheckable(True)
            self.walls.addButton(button)
            walls.addWidget(button)
        self.light_wall.setAccessibleName("Card on the light wall")
        self.dark_wall.setAccessibleName("Card on the dark wall")
        side.addLayout(walls)
        side.addSpacing(6)
        self.copy_button = action("Copy image", self.copy, "primary")
        self.copy_button.setIcon(icon("copy", "#f2f4ef", 18))
        side.addWidget(self.copy_button)
        self.save_button = action("Save PNG…", self.save)
        self.save_button.setIcon(icon("save", "#1c2a26", 18))
        side.addWidget(self.save_button)
        self.status = QLabel("Made on this PC. Nothing is uploaded.")
        self.status.setWordWrap(True)
        theme.style(self.status, "font-size: 12px; color: #55625e;")
        side.addWidget(self.status)
        side.addStretch()
        layout.addLayout(side, 1)

    def lines(self):
        return [line for line in getattr(self.c.lyrics, "lines", []) or [] if line.text.strip()]

    def start(self):
        """Begin on the line being sung now (or the song alone when there are no lyrics), on the app's wall."""
        lines = self.lines()
        self.index = -1
        if lines:
            position = self.c.position + getattr(self.c, "offset", 0) / 1000
            started = [i for i, line in enumerate(lines) if line.time <= position]
            self.index = started[-1] if started else 0
        self.dark = theme.is_dark()
        self.status.setText("Made on this PC. Nothing is uploaded.")
        self.render()

    def step(self, direction):
        lines = self.lines()
        if lines:
            self.index = max(0, min(len(lines) - 1, self.index + direction))
            self.render()

    def set_dark(self, dark):
        if bool(dark) != self.dark:
            self.dark = bool(dark)
            self.render()

    def current_line(self):
        lines = self.lines()
        return lines[self.index].text.strip() if 0 <= self.index < len(lines) else ""

    def render(self):
        lines = self.lines()
        text = self.current_line()
        self.line_label.setText(f"“{text}”" if text else "No timed lyrics for this song, so the card shows the song on its own.")
        self.earlier.setEnabled(bool(lines) and self.index > 0)
        self.later.setEnabled(bool(lines) and self.index < len(lines) - 1)
        self.light_wall.setChecked(not self.dark)
        self.dark_wall.setChecked(self.dark)
        track = self.c.track
        sung_at = lines[self.index].time if text and 0 <= self.index < len(lines) else None
        self.image = render_share_card(track.title, track.artist, text, track.artwork,
                                       getattr(self.c, "halo_primary", self.c.primary),
                                       getattr(self.c, "halo_secondary", self.c.secondary),
                                       dark=self.dark, album=track.album, sung_at=sung_at)
        ratio = self.devicePixelRatioF()
        preview = QPixmap.fromImage(self.image.scaled(round(self.preview.width() * ratio), round(self.preview.height() * ratio),
                                                      Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        preview.setDevicePixelRatio(ratio)
        self.preview.setPixmap(preview)

    def copy(self):
        QApplication.clipboard().setImage(self.image)
        self.status.setText("Copied. Paste it anywhere you like.")

    def save_to(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.image.save(str(path), "PNG"):
            raise OSError(f"Couldn't write {path}")
        self.status.setText(f"Saved to {path}")
        return path

    def save(self):
        folder = default_folder()
        suggested = folder / default_file_name(self.c.track.title, self.c.track.artist)
        filename, _ = QFileDialog.getSaveFileName(self, "Save lyric card", str(suggested), "PNG image (*.png)")
        if not filename:
            return
        if not filename.lower().endswith(".png"):
            filename += ".png"
        try:
            self.save_to(filename)
        except OSError as error:
            self.status.setText(str(error))
