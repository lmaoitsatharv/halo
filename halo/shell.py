"""The single-window gallery: a place nav on top, the wall in the middle, the handset below.

Playback stays outside the page stack, so every page controls the same song.
"""
from PySide6.QtCore import Qt, QRectF, QPointF, QSize
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QScrollArea, QSizePolicy, QSizeGrip, QLabel)

from .glass import GlassPanel, SeekSlider, icon
from .gallery import (INK, INK_SOFT, INK_MUTED, HANDSET_INK, HANDSET_MUTED, NavTile, PlaceNav, HandsetButton, tint)
from .wall import FramedPrint, MuseumLabel, WallLyrics, PrintThumb, StatusDot
from .frontend import text_label, action, FittedTitle, ElidedLabel, HaloMark, TransportButton
from .theme import style, pick


PLACES = (("listening", "Listening", "listening", "Ctrl+1"),
          ("modes", "Modes", "modes", "Ctrl+2"),
          ("halo", "Lighting", "halo", "Ctrl+3"),
          ("lyrics", "Lyrics", "lyrics", "Ctrl+4"),
          ("scenes", "Immersive", "scenes", "Ctrl+5"))


class ListeningPage(QWidget):
    """The print, its label and the wall lettering, composed by hand so the artwork always leads."""
    def __init__(self, window, c):
        super().__init__()
        self.host = window
        self.c = c
        window.main_art = self.print = FramedPrint(c)
        self.print.setParent(self)
        self.print.clicked.connect(window.fullscreen)

        self.label = MuseumLabel(self, c)
        window.museum_label = self.label
        card = QVBoxLayout(self.label.content)
        card.setContentsMargins(30, 22, 30, 30)
        card.setSpacing(4)
        window.title = FittedTitle("Waiting for music")
        window.title.setMaximumHeight(80)
        window.title.setMinimumHeight(38)
        card.addWidget(window.title)
        window.artist = ElidedLabel("Play something you love.")
        style(window.artist, "font-size: 15px; color: #3e4c47;")
        card.addWidget(window.artist)
        window.album_label = ElidedLabel("")
        style(window.album_label, "font-size: 12px; color: #55625e;")
        card.addWidget(window.album_label)
        card.addSpacing(10)
        status = QHBoxLayout()
        status.setSpacing(8)
        window.status_dot = StatusDot()
        status.addWidget(window.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        window.badge = text_label("Waiting for music", "badge")
        status.addWidget(window.badge)
        status.addStretch()
        window.demo_button = action("Try the visual demo", lambda: c.set_demo(not c.demo), "ghost")
        window.demo_button.setToolTip("Preview Halo with original sample lyrics. No audio plays.")
        status.addWidget(window.demo_button)
        card.addLayout(status)

        window.canvas = self.lyrics = WallLyrics(c)
        self.lyrics.setParent(self)

        self.tools = QWidget(self)
        tools = QHBoxLayout(self.tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        window.lyrics_badge = text_label("Waiting for a song", "muted")
        style(window.lyrics_badge, "font-size: 12px; color: #55625e;")
        tools.addWidget(window.lyrics_badge)
        # The lyric style is chosen in Immersive's menu, on the Lyrics page and in Modes, not on this wall.
        tools.addStretch()
        window.retry_button = action("", c.retry_lyrics, "ghost")
        window.retry_button.setIcon(icon("refresh", "#1c2a26", 18))
        window.retry_button.setIconSize(QSize(18, 18))
        window.retry_button.setFixedSize(40, 40)
        window.retry_button.setToolTip("Look for lyrics again")
        window.retry_button.setAccessibleName("Retry lyrics")
        tools.addWidget(window.retry_button)
        imports = action("", window.import_lrc, "ghost")
        imports.setIcon(icon("import", "#1c2a26", 18))
        imports.setIconSize(QSize(18, 18))
        imports.setFixedSize(40, 40)
        imports.setToolTip("Import timed lyrics for this song")
        imports.setAccessibleName("Import timed lyrics")
        tools.addWidget(imports)
        self.setTabOrder(self.print, window.demo_button)

    def composition(self):
        """Where the print, the label and the lyric sit at this page size."""
        w, h = self.width(), self.height()
        side = max(170., min(h * .74, w * .4, 600.))
        gap = max(36., min(72., w * .045))
        column = max(260., min(560., w - side * 1.16 - gap - 72))
        group = side * 1.16 + gap + column
        left = max(24., (w - group) / 2 - w * .02)
        top = (h - side * 1.22) / 2 + side * .04
        return left, top, side, gap, column

    def resizeEvent(self, event):
        super().resizeEvent(event)
        left, top, side, gap, column = self.composition()
        self.print.setGeometry(round(left), round(top), round(side * 1.16), round(side * 1.22))
        frame = self.print.print_rect().translated(self.print.pos())
        x = frame.right() + gap
        label_height = 172 if self.height() >= 470 else 150
        self.label.setGeometry(round(x - 8), round(frame.top() - 4), round(min(column, 440) + 16), label_height)
        lyric_top = frame.top() + label_height + 8
        tools_height = 40
        lyric_bottom = frame.bottom() - tools_height - 6
        self.lyrics.setGeometry(round(x), round(lyric_top), round(column), max(110, round(lyric_bottom - lyric_top)))
        self.tools.setGeometry(round(x), round(frame.bottom() - tools_height + 2), round(column), tools_height)

    def spotlight(self):
        """The pool of song light behind the print, in page coordinates."""
        frame = self.print.print_rect().translated(self.print.pos())
        return frame.center() - QPointF(0, frame.height() * .06), frame.width() * 1.02


class SheetLayer(QWidget):
    """A native dialog's controls, presented as a card inside the existing window."""
    def __init__(self, parent):
        super().__init__(parent)
        self.dialog = None
        self.preferred_width = 620
        self.setObjectName("sheetLayer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.addStretch()
        self.panel = GlassPanel(radius=18, variant="sheet")
        self.panel.setMaximumWidth(680)
        self.panel.setMinimumWidth(440)
        content = QVBoxLayout(self.panel)
        content.setContentsMargins(22, 14, 18, 18)
        heading = QHBoxLayout()
        self.title = text_label("", "panelTitle")
        heading.addWidget(self.title)
        heading.addStretch()
        close = action("", self.dismiss, "ghost")
        close.setIcon(icon("close", "#1c2a26", 16))
        close.setIconSize(QSize(16, 16))
        close.setFixedSize(40, 40)
        close.setAccessibleName("Close")
        close.setToolTip("Close  ·  Esc")
        heading.addWidget(close)
        content.addLayout(heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.addWidget(self.scroll, 1)
        layout.addWidget(self.panel, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.hide()

    def present(self, dialog, title):
        if self.dialog is not None and self.dialog is not dialog:
            self.dialog.reject()
        old = self.scroll.takeWidget()
        if old is not None:
            old.hide()
            old.setParent(self.parentWidget())
        self.dialog = dialog
        self.preferred_width = min(800, max(620, dialog.minimumSizeHint().width() + 44))
        self.title.setText(title)
        dialog.setParent(self.scroll)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        dialog.setMinimumSize(0, 0)
        dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.scroll.setWidget(dialog)
        self.panel.setFixedWidth(min(self.preferred_width, self.parentWidget().width() - 64))
        self.panel.setFixedHeight(min(self.parentWidget().height() - 46, max(430, dialog.sizeHint().height() + 100)))
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        dialog.show()
        dialog.setFocus(Qt.FocusReason.OtherFocusReason)

    def dismiss(self):
        if self.dialog is not None:
            self.dialog.reject()

    def finished(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
            self.hide()

    def resizeEvent(self, event):
        self.panel.setFixedWidth(min(self.preferred_width, self.width() - 64))
        if self.dialog is not None:
            self.panel.setFixedHeight(min(self.height() - 46, max(430, self.dialog.sizeHint().height() + 100)))
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(28, 42, 38, 96) if pick(True, False) else QColor(0, 0, 0, 150))


def build_shell(window, c):
    window.resize(1280, 800)
    window.setMinimumSize(960, 640)
    window.current_page = "listening"
    window.nav_buttons = {}
    root = QVBoxLayout(window)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    window.app_stack = QStackedWidget()
    root.addWidget(window.app_stack)
    window.shell = QWidget()
    window.app_stack.addWidget(window.shell)
    shell = QVBoxLayout(window.shell)
    # The top margin clears Windows' own keys when the wall runs up under them (MainWindow._fit_title_strip).
    shell.setContentsMargins(22, 14, 22, 6)
    window.shell_layout = shell
    shell.setSpacing(6)

    header = QGridLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setColumnStretch(0, 1)
    header.setColumnStretch(2, 1)
    brand = QHBoxLayout()
    brand.setSpacing(8)
    window.mark = HaloMark(c)
    window.mark.setFixedSize(36, 36)
    brand.addWidget(window.mark)
    # The name and what Halo is, stacked beside the mark; the window's title bar stays empty.
    names = QVBoxLayout()
    names.setSpacing(0)
    names.setContentsMargins(0, 0, 0, 0)
    wordmark = QLabel("halo")
    style(wordmark, "font-size: 24px; font-weight: 600; letter-spacing: 3px; color: #1c2a26;")
    names.addWidget(wordmark)
    window.tagline = QLabel("Your listening space")
    window.tagline.setObjectName("brandTagline")
    style(window.tagline, "font-size: 12px; color: #55625e; padding-left: 1px;")
    names.addWidget(window.tagline)
    brand.addLayout(names)
    brand.addStretch()
    header.addLayout(brand, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    window.place_nav = PlaceNav()
    callbacks = {"listening": lambda: window.navigate("listening"),
                 "modes": window.open_modes}
    for key, text, glyph, hint in PLACES:
        tile = NavTile(text, glyph, hint, c)
        callback = callbacks.get(key) or (lambda checked=False, section=key: window.open_settings_section(section))
        tile.clicked.connect(callback)
        if key == "scenes":
            tile.setToolTip(f"Immersive  ·  set up the full-screen rooms  ·  {hint}")
            tile.setAccessibleName("Immersive settings")
        window.nav_buttons[key] = window.place_nav.add(tile)
    window.modes_button = window.nav_buttons["modes"]
    window.modes_button.setAccessibleName("Browse modes")
    header.addWidget(window.place_nav, 0, 1, Qt.AlignmentFlag.AlignCenter)

    window.settings_button = NavTile("Settings", "settings", "Ctrl+,", c, standalone=True)
    window.settings_button.setAccessibleName("Open settings")
    window.settings_button.clicked.connect(window.open_settings)
    window.nav_buttons["settings"] = window.settings_button
    header.addWidget(window.settings_button, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    shell.addLayout(header)

    window.page_stack = QStackedWidget()
    window.page_stack.setObjectName("workspacePages")
    window.listening_page = ListeningPage(window, c)
    window.page_stack.addWidget(window.listening_page)
    shell.addWidget(window.page_stack, 1)

    # The audio-guide handset: the same controls on every page.
    window.player = GlassPanel(radius=26, variant="player")
    window.player.setFixedHeight(84)
    window.player.setMaximumWidth(1080)
    player = QHBoxLayout(window.player)
    player.setContentsMargins(16, 8, 16, 14)
    player.setSpacing(10)
    window.now_playing = QWidget()
    now = QHBoxLayout(window.now_playing)
    now.setContentsMargins(0, 0, 6, 0)
    now.setSpacing(10)
    window.player_art = PrintThumb(c, 42)
    now.addWidget(window.player_art)
    info = QVBoxLayout()
    info.setSpacing(1)
    window.player_title = ElidedLabel("Waiting for music")
    window.player_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #f2f4ef;")
    window.player_title.setFixedWidth(170)
    window.player_artist = ElidedLabel("Spotify, a browser or any player")
    window.player_artist.setStyleSheet("font-size: 11px; color: #aab7b1;")
    window.player_artist.setFixedWidth(170)
    info.addWidget(window.player_title)
    info.addWidget(window.player_artist)
    now.addLayout(info)
    player.addWidget(window.now_playing)
    window.previous = TransportButton("previous", lambda: c.transport("previous"), c)
    window.play = TransportButton("play", lambda: c.transport("toggle"), c)
    window.next = TransportButton("next", lambda: c.transport("next"), c)
    for item in (window.previous, window.play, window.next):
        player.addWidget(item, 0, Qt.AlignmentFlag.AlignVCenter)
    player.addSpacing(8)
    window.time_label = QLabel("0:00")
    window.time_label.setStyleSheet("font-size: 12px; color: #aab7b1;")
    window.time_label.setMinimumWidth(38)
    window.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    player.addWidget(window.time_label)
    window.progress = SeekSlider()
    window.progress.setRange(0, 1000)
    window.progress.setAccessibleName("Track position")
    window.progress.setToolTip("Track position  ·  drag, or use the arrow keys")
    window.progress.sliderReleased.connect(lambda: c.seek(window.progress.value() / 1000 * c.track.duration))
    player.addWidget(window.progress, 1)
    window.duration_label = QLabel("0:00")
    window.duration_label.setStyleSheet("font-size: 12px; color: #aab7b1;")
    window.duration_label.setMinimumWidth(38)
    player.addWidget(window.duration_label)
    player.addSpacing(6)
    window.share_button = HandsetButton("share", window.open_share_card, c, "Ctrl+Shift+S")
    window.mini_button = HandsetButton("mini", window.open_mini_player, c, "Ctrl+Shift+M")
    window.immersive_button = HandsetButton("fullscreen", window.fullscreen, c, "F11")
    for item in (window.share_button, window.mini_button, window.immersive_button):
        player.addWidget(item, 0, Qt.AlignmentFlag.AlignVCenter)
    handset_row = QHBoxLayout()
    handset_row.addStretch()
    handset_row.addWidget(window.player, 12)
    handset_row.addStretch()
    shell.addLayout(handset_row)

    footer = QHBoxLayout()
    footer.setContentsMargins(6, 0, 0, 0)
    window.footer = ElidedLabel("No login needed · close to keep Halo in the tray")
    style(window.footer, "font-size: 11px; color: #55625e;")
    footer.addWidget(window.footer, 1)
    grip = QSizeGrip(window)
    grip.setFixedSize(12, 12)
    footer.addWidget(grip)
    shell.addLayout(footer)

    from .settings_ui import SettingsStudio
    window.settings_dialog = SettingsStudio(window, c, embedded=True)
    window.page_stack.addWidget(window.settings_dialog)
    window.settings_pages = window.settings_dialog.pages
    window.sheet = SheetLayer(window)
    window.nav_buttons["listening"].setChecked(True)
    window.page_stack.setCurrentWidget(window.listening_page)
