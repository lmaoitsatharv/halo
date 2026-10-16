"""Four spacious listening scenes sharing a single lyric surface and transport."""
import math

from PySide6.QtCore import Qt, Signal, QEvent, QTimer, QRect, QRectF, QPointF, QPropertyAnimation
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap,
                          QRadialGradient, QLinearGradient, QPainterPath, QShortcut,
                          QKeySequence)
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QFrame, QSlider,
                              QComboBox, QHBoxLayout, QGraphicsOpacityEffect,
                              QGraphicsDropShadowEffect)

from .widgets import Artwork, LyricCanvas, tint
from .glow import paint_edge_glow
from .taskbar import allow_taskbar_reveal


IMMERSIVE_SCENES = (
    ("studio", "Listening room", "Album art and words, in a quiet room of colour."),
    ("lyrics", "Lyrics only", "Just the words. Move your mouse to reveal the controls."),
    ("cinema", "Cinema", "A wide stage of light, with the words at its centre."),
    ("orbit", "Orbit", "A record suspended inside slow, luminous orbits."),
)


SCENE_STYLE = """
QWidget#immersiveRoom { color: #edf3ed; font-family: 'Segoe UI'; }
QLabel { background: transparent; }
QLabel#roomBrand { color: #e5eee7; font-size: 15px; font-weight: 600; letter-spacing: 5px; }
QLabel#roomCaption { color: #a2b5ac; font-size: 10px; letter-spacing: 2px; }
QLabel#roomSong { color: #f2f5ef; font-weight: 600; }
QLabel#roomArtist { color: #b9c8c0; font-size: 15px; }
QLabel#roomAlbum { color: #82968d; font-size: 11px; }
QLabel#roomStatus { color: #81968c; font-size: 10px; }
QFrame#roomPlayer { background: rgba(12, 20, 20, 205); border: 1px solid rgba(208, 229, 218, 34); border-radius: 28px; }
QPushButton#roomExit { background: rgba(18, 29, 28, 140); color: #cedbd3; border: 1px solid rgba(208, 229, 218, 32); border-radius: 14px; padding: 7px 13px; font-size: 11px; }
QPushButton#roomExit:hover { background: rgba(203, 230, 214, 22); border-color: rgba(208, 229, 218, 80); }
QPushButton#roomControl { background: transparent; border: none; border-radius: 22px; padding: 0; color: #c9d8cf; font-size: 27px; }
QPushButton#roomControl:hover { background: rgba(225, 244, 232, 18); }
QPushButton#roomPlay { background: #e4eddd; color: #13241c; border: none; border-radius: 23px; padding: 0; font-size: 17px; }
QPushButton#roomPlay:hover { background: #f5ffee; }
QPushButton:disabled { color: #63746d; }
QComboBox#roomSelect { color: #c6d4cc; background: rgba(16, 26, 25, 165); border: 1px solid rgba(205, 226, 215, 30); border-radius: 12px; padding: 7px 12px; font-size: 11px; }
QComboBox#roomSelect:hover { background: rgba(41, 61, 54, 150); border-color: rgba(205, 226, 215, 65); }
QComboBox#roomSelect::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #14221e; color: #e5eee7; border: 1px solid #3a5147; selection-background-color: #304a3f; padding: 4px; }
QSlider::groove:horizontal { height: 3px; background: rgba(188, 211, 197, 32); border-radius: 1px; }
QSlider::sub-page:horizontal { background: #bdcfaf; border-radius: 1px; }
QSlider::handle:horizontal { width: 9px; margin: -4px 0; border-radius: 4px; background: #e4eddd; }
"""


def _label(parent, text, name):
    widget = QLabel(text, parent)
    widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


class Immersive(QWidget):
    exited = Signal()
    IDLE_INTERVAL = 1500

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("immersiveRoom")
        self.setWindowTitle("Halo · immersive listening")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(800, 580)
        self.setStyleSheet(SCENE_STYLE)
        self.scene = "studio"
        self.scene_key = None
        self.backdrop = QPixmap()
        self.header = QWidget(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)
        self.brand = _label(self.header, "H A L O", "roomBrand")
        header.addWidget(self.brand)
        header.addSpacing(14)
        self.scene_caption = _label(self.header, "THE LISTENING ROOM", "roomCaption")
        header.addWidget(self.scene_caption)
        header.addStretch(1)
        self.scene_select = QComboBox(self.header)
        self.scene_select.setObjectName("roomSelect")
        self.scene_select.setAccessibleName("Immersive scene")
        for scene, name, description in IMMERSIVE_SCENES:
            self.scene_select.addItem(name, scene)
            self.scene_select.setItemData(self.scene_select.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self.scene_select.setFixedWidth(144)
        self.scene_select.currentIndexChanged.connect(self._select_scene)
        header.addWidget(self.scene_select)
        self.style_select = QComboBox(self.header)
        self.style_select.setObjectName("roomSelect")
        self.style_select.setAccessibleName("Lyric animation style")
        self.style_select.setFixedWidth(146)
        self._populate_styles()
        self.style_select.currentIndexChanged.connect(self._select_style)
        header.addWidget(self.style_select)
        self.exit = QPushButton("Return   Esc", self.header)
        self.exit.setObjectName("roomExit")
        self.exit.setAccessibleName("Return to Halo")
        self.exit.clicked.connect(self.leave)
        header.addWidget(self.exit)
        self.back_button = self.exit

        self.left_column = QWidget(self)
        self.cover = Artwork(controller, 280)
        self.cover.setParent(self)
        shadow = QGraphicsDropShadowEffect(self.cover)
        shadow.setBlurRadius(52)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 165))
        self.cover.setGraphicsEffect(shadow)
        self.title = _label(self, "", "roomSong")
        self.song = self.title
        self.title.setWordWrap(True)
        self.artist = _label(self, "", "roomArtist")
        self.album = _label(self, "", "roomAlbum")
        self.artist.setWordWrap(True)
        self.album.setWordWrap(True)
        self.now_label = _label(self, "NOW LISTENING", "roomCaption")
        self.words_label = _label(self, "IN THE WORDS", "roomCaption")
        self.canvas = LyricCanvas(controller, "immersive")
        self.canvas.setParent(self)
        self.canvas.setMinimumHeight(100)
        self.lyrics_status = _label(self, "", "roomStatus")

        self.player = QFrame(self)
        self.player.setObjectName("roomPlayer")
        player_layout = QHBoxLayout(self.player)
        player_layout.setContentsMargins(17, 11, 23, 11)
        player_layout.setSpacing(12)
        self.previous = self._control("‹", "Previous track", "previous")
        self.play = self._control("Ⅱ", "Play or pause", "toggle", True)
        self.next = self._control("›", "Next track", "next")
        for control in (self.previous, self.play, self.next):
            player_layout.addWidget(control)
        player_layout.addSpacing(12)
        self.elapsed = _label(self.player, "0:00", "roomAlbum")
        self.total = _label(self.player, "0:00", "roomAlbum")
        self.elapsed.setMinimumWidth(32)
        self.total.setMinimumWidth(32)
        player_layout.addWidget(self.elapsed)
        self.progress = QSlider(Qt.Orientation.Horizontal, self.player)
        self.progress.setRange(0, 1000)
        self.progress.setAccessibleName("Track position")
        self.progress.sliderReleased.connect(self._seek)
        player_layout.addWidget(self.progress, 1)
        player_layout.addWidget(self.total)
        self.chrome_effects = []
        self.chrome_animations = []
        for widget in (self.header, self.player):
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(1.0)
            widget.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(320)
            self.chrome_effects.append(effect)
            self.chrome_animations.append(animation)
        self.chrome_visible = True
        self._last_mouse_position = None
        self._pointer_pressed = False
        self._pressed_keys = set()
        self._keyboard_navigation = False
        self._idle_deferred = False
        self._cursor_hidden = False
        self._saved_cursors = []
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(self.IDLE_INTERVAL)
        self.idle.timeout.connect(self._hide_chrome)
        self.escape = QShortcut(QKeySequence("Esc"), self)
        self.escape.activated.connect(self.leave)
        self.space = QShortcut(QKeySequence("Space"), self)
        self.space.activated.connect(lambda: self._transport("toggle") if controller.track.connected else None)
        popup_widgets = []
        for combo in (self.scene_select, self.style_select):
            view = combo.view()
            popup_widgets.extend((view, view.viewport(), view.window()))
        self._popup_widgets = popup_widgets
        for widget in [self, *self.findChildren(QWidget), *popup_widgets]:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        controller.trackChanged.connect(self.changed)
        controller.lyricsChanged.connect(self.changed)
        controller.settingChanged.connect(self.changed)
        self.resize(1280, 800)
        self.changed()

    def _populate_styles(self):
        # The canvas owns the supported style catalogue, when available.
        try:
            from .lyric_rendering import LYRIC_STYLES
            styles = LYRIC_STYLES
        except ImportError:
            styles = (("ship", "Ship"), ("fisheye", "Fisheye"),
                      ("fisheye_visual", "Fisheye Visual"), ("visual", "Visual"))
        for entry in styles:
            self.style_select.addItem(entry[1], entry[0])
            if len(entry) > 2:
                self.style_select.setItemData(self.style_select.count() - 1, entry[2], Qt.ItemDataRole.ToolTipRole)

    def _control(self, text, accessible, action, primary=False):
        widget = QPushButton(text, self.player)
        widget.setObjectName("roomPlay" if primary else "roomControl")
        widget.setFixedSize(46, 46)
        widget.setAccessibleName(accessible)
        widget.clicked.connect(lambda: self._transport(action))
        return widget

    def _transport(self, action):
        self._wake_chrome()
        self.controller.transport(action)

    def _seek(self):
        self._wake_chrome()
        self.controller.seek(self.progress.value() / 1000 * self.controller.track.duration)

    def _select_scene(self):
        self.controller.set("immersive_mode", self.scene_select.currentData())

    def _select_style(self):
        self.controller.set("lyric_style", self.style_select.currentData())

    def changed(self, *_):
        c = self.controller
        scene = getattr(c, "immersive_mode", "studio")
        scene = scene if scene in {item[0] for item in IMMERSIVE_SCENES} else "studio"
        scene_changed = self.scene != scene
        self.scene = scene
        self.canvas.scene_mode = scene
        self.canvas.setProperty("immersiveScene", scene)
        if hasattr(self.canvas, "set_alignment"):
            self.canvas.set_alignment("center" if scene in ("lyrics", "cinema") else "left")
        for combo, value in ((self.scene_select, scene), (self.style_select, getattr(c, "lyric_style", "ship"))):
            combo.blockSignals(True)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.scene_caption.setText({"studio": "THE LISTENING ROOM", "lyrics": "JUST THE WORDS", "cinema": "WIDE OPEN SOUND", "orbit": "IN YOUR OWN ORBIT"}[scene])
        self.title.setText(c.track.title)
        self.artist.setText(c.track.artist)
        self.album.setText(c.track.album or "Sound in colour")
        for label in (self.title, self.artist, self.album):
            label.setToolTip(label.text())
        self.lyrics_status.setText("ORIGINAL DEMO · LINE SYNCED" if getattr(c, "demo", False) else "LINE SYNCED" if c.lyrics.lines else "")
        self.play.setText("Ⅱ" if c.track.playing else "▶")
        for control in (self.play, self.previous, self.next, self.progress):
            control.setEnabled(c.track.connected)
        self.cover.track_changed()
        if scene_changed:
            self.scene_key = None
            self._wake_chrome()
        if getattr(c, "reduced_motion", False):
            self._fade_chrome(self.chrome_visible)
        self._arrange()
        self.canvas.update()
        self.update()

    refresh = changed

    def fit_title(self):
        height = max(1, self.title.height())
        width = max(1, self.title.width())
        text = self.controller.track.title
        if self.scene == "cinema":
            face = QFont("Segoe UI")
            face.setPixelSize(14)
            face.setWeight(QFont.Weight.DemiBold)
            self.title.setStyleSheet("font-size: 14px;")
            self.title.setText(QFontMetrics(face).elidedText(text, Qt.TextElideMode.ElideRight, width))
            return
        maximum = 34 if self.scene == "studio" else 26 if self.scene == "orbit" else 22
        for size in range(maximum, 15, -1):
            candidate = QFont("Segoe UI")
            candidate.setPixelSize(size)
            candidate.setWeight(QFont.Weight.DemiBold)
            rect = QFontMetrics(candidate).boundingRect(QRect(0, 0, width, 1000), int(Qt.TextFlag.TextWordWrap), text)
            if rect.height() <= height:
                break
        metrics = QFontMetrics(candidate)
        # Bound unusually long credits while keeping the complete title in its tooltip.
        if rect.height() > height:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                bounds = metrics.boundingRect(QRect(0, 0, width, 1000), int(Qt.TextFlag.TextWordWrap), text[:middle].rstrip() + "…")
                if bounds.height() <= height:
                    low = middle
                else:
                    high = middle - 1
            text = text[:low].rstrip() + "…"
        self.title.setText(text)
        self.title.setStyleSheet(f"font-size: {size}px;")

    def _arrange(self):
        if not hasattr(self, "canvas"):
            return
        w, h = self.width(), self.height()
        margin = max(28, min(64, w // 25))
        compact = h < 720
        self.header.setGeometry(margin, 22 if compact else 30, w - 2 * margin, 38)
        self.scene_caption.setVisible(w >= 1100)
        footer_width = min(940, w - 2 * margin)
        self.player.setGeometry((w - footer_width) // 2, h - 112 if compact else h - 128, footer_width, 72)
        top, bottom = (88 if compact else 108), self.player.y() - (22 if compact else 32)
        body_height = max(200, bottom - top)
        lyrics_only = self.scene == "lyrics"
        for widget in (self.cover, self.title, self.artist, self.album, self.now_label, self.words_label, self.lyrics_status):
            widget.setVisible(not lyrics_only)
        self.left_column.setVisible(False)
        self.title.setWordWrap(self.scene != "cinema")
        self.artist.setStyleSheet("font-size: 11px; color: #9da9a5;" if self.scene == "cinema" else "")
        self.album.setStyleSheet("font-size: 10px;" if self.scene == "cinema" else "")
        shadow = self.cover.graphicsEffect()
        shadow.setBlurRadius(18 if self.scene == "cinema" else 52)
        shadow.setOffset(0, 3 if self.scene == "cinema" else 14)
        if self.scene == "lyrics":
            width = min(1160, w - 2 * margin - 36)
            canvas_height = max(200, self.player.y() - 112)
            self.canvas.setGeometry((w - width) // 2, (h - canvas_height) // 2, width, canvas_height)
        elif self.scene == "studio":
            column_width = max(230, min(382, int(w * .29)))
            art_size = max(108, min(column_width - 12, int(body_height * .59), body_height - (186 if compact else 210), 320))
            x = margin + max(0, (column_width - art_size) // 2)
            content_top = top + max(0, (body_height - art_size - (186 if compact else 210)) // 2)
            self.now_label.setGeometry(x, content_top, column_width, 20)
            self.cover.setFixedSize(art_size, art_size)
            self.cover.move(x, content_top + 32)
            metadata_top = self.cover.y() + art_size + 22
            self.title.setGeometry(x, metadata_top, column_width, 62 if compact else 84)
            self.artist.setGeometry(x, self.title.geometry().bottom() + 5, column_width, 24 if compact else 28)
            self.album.setGeometry(x, self.artist.geometry().bottom() + 3, column_width, 24 if compact else 30)
            lyric_x = margin + column_width + max(30, w // 24)
            lyric_width = w - lyric_x - margin
            self.words_label.setGeometry(lyric_x + 24, top + 14, lyric_width - 48, 20)
            self.canvas.setGeometry(lyric_x, top + 40, lyric_width, body_height - 72)
            self.lyrics_status.setGeometry(lyric_x + 24, bottom - 22, lyric_width - 48, 20)
        elif self.scene == "cinema":
            # Preserve the lyric stage; keep credits discreet in the lower corner.
            lyric_width = min(1250, w - 2 * margin)
            self.canvas.setGeometry((w - lyric_width) // 2, top - 6, lyric_width, max(180, body_height - 106))
            size = 44 if compact else 48
            corner_margin = 28 if compact else 36
            rail_width = min(300 if compact else 340, w - 2 * corner_margin)
            x = corner_margin
            y = h - corner_margin - size
            self.cover.setFixedSize(size, size)
            self.cover.move(x, y)
            text_x, text_width = x + size + 12, rail_width - size - 12
            self.title.setGeometry(text_x, y, text_width, 18)
            self.artist.setGeometry(text_x, y + 18, text_width, 14)
            self.album.setGeometry(text_x, y + 32, text_width, 12)
            # The player can fade in above the credits without covering them.
            self.player.move(self.player.x(), min(self.player.y(), y - self.player.height() - 18))
            self.now_label.hide()
            self.words_label.hide()
            self.lyrics_status.hide()
        else:
            orbit_width = int(w * .43)
            size = max(132, min(270, int(body_height * .49), int(orbit_width * .57)))
            center_x = margin + orbit_width // 2 - 12
            center_y = top + int(body_height * .4)
            self.cover.setFixedSize(size, size)
            self.cover.move(center_x - size // 2, center_y - size // 2)
            self.now_label.setGeometry(margin, top + 8, orbit_width - 24, 20)
            self.now_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.title.setGeometry(margin + 8, top + int(body_height * .72), orbit_width - 40, 66)
            self.artist.setGeometry(margin + 8, self.title.geometry().bottom() + 3, orbit_width - 40, 26)
            self.album.setGeometry(margin + 8, self.artist.geometry().bottom() + 2, orbit_width - 40, 22)
            for label in (self.title, self.artist, self.album):
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lyric_x = margin + orbit_width + 8
            lyric_width = w - lyric_x - margin
            self.words_label.setGeometry(lyric_x + 24, top + 12, lyric_width - 48, 20)
            self.canvas.setGeometry(lyric_x, top + 38, lyric_width, body_height - 64)
            self.lyrics_status.setGeometry(lyric_x + 24, bottom - 20, lyric_width - 48, 20)
        if self.scene != "orbit":
            self.now_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            for label in (self.title, self.artist, self.album):
                label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.fit_title()
        for widget, text in ((self.artist, self.controller.track.artist), (self.album, self.controller.track.album or "Sound in colour")):
            widget.setText(QFontMetrics(widget.font()).elidedText(text, Qt.TextElideMode.ElideRight, widget.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scene_key = None
        self._arrange()

    def event(self, event):
        if event.type() == QEvent.Type.WinIdChange:
            allow_taskbar_reveal(self.effectiveWinId())
        return super().event(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.changed()
        self._wake_chrome()

    def hideEvent(self, event):
        self._set_cursor_hidden(False)
        self.idle.stop()
        self._pointer_pressed = False
        self._pressed_keys.clear()
        self._keyboard_navigation = False
        self._last_mouse_position = None
        super().hideEvent(event)

    def leave(self):
        self.hide()
        self.exited.emit()

    def closeEvent(self, event):
        event.ignore()
        self.leave()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            position = event.globalPosition()
            point = (position.x(), position.y())
            if point != self._last_mouse_position:
                self._last_mouse_position = point
                self._keyboard_navigation = False
                self._wake_chrome()
        elif kind == QEvent.Type.MouseButtonPress:
            self._pointer_pressed = True
            self._keyboard_navigation = False
            self._wake_chrome()
        elif kind == QEvent.Type.MouseButtonRelease:
            self._pointer_pressed = False
            self._wake_chrome()
        elif kind == QEvent.Type.Wheel:
            self._keyboard_navigation = False
            self._wake_chrome()
        elif kind == QEvent.Type.KeyPress:
            if not event.isAutoRepeat():
                self._pressed_keys.add(event.key())
            if self._is_chrome_widget(obj) or event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self._wake_chrome()
        elif kind == QEvent.Type.KeyRelease and not event.isAutoRepeat():
            self._pressed_keys.discard(event.key())
            self._wake_chrome()
        elif kind == QEvent.Type.FocusIn:
            if self._is_chrome_widget(obj) and event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason):
                self._keyboard_navigation = True
                self._wake_chrome()
        elif kind == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._focus_changed)
        elif obj is self and kind == QEvent.Type.WindowDeactivate:
            self._pointer_pressed = False
            self._pressed_keys.clear()
            self._keyboard_navigation = False
            self._wake_chrome()
        elif obj is self and kind == QEvent.Type.WindowActivate:
            self._wake_chrome()
        elif obj in self._popup_widgets and kind in (QEvent.Type.Show, QEvent.Type.Hide):
            # Closing a menu starts a fresh quiet interval rather than using
            # the already-expired timeout from while the menu was open.
            self._wake_chrome()
        return super().eventFilter(obj, event)

    def _is_chrome_widget(self, widget):
        if not isinstance(widget, QWidget):
            return False
        return any(parent is widget or parent.isAncestorOf(widget) for parent in (self.header, self.player, self.scene_select.view(), self.style_select.view()))

    def _focus_changed(self):
        if self._keyboard_navigation and not self._is_chrome_widget(self.focusWidget()):
            self._keyboard_navigation = False
            self._wake_chrome()

    def _interaction_active(self):
        return (self._pointer_pressed or bool(self._pressed_keys) or self.progress.isSliderDown()
                or self.scene_select.view().isVisible() or self.style_select.view().isVisible()
                or (self._keyboard_navigation and self._is_chrome_widget(self.focusWidget())))

    def _wake_chrome(self):
        self._set_cursor_hidden(False)
        self._fade_chrome(True)
        self._idle_deferred = False
        if self.isVisible():
            self.idle.start(self.IDLE_INTERVAL)

    def _hide_chrome(self):
        if self._interaction_active():
            self._idle_deferred = True
            self.idle.start(100)
            return
        if self._idle_deferred:
            self._idle_deferred = False
            self.idle.start(self.IDLE_INTERVAL)
            return
        self._fade_chrome(False)
        self._set_cursor_hidden(True)

    def _set_cursor_hidden(self, hidden):
        if hidden == self._cursor_hidden:
            return
        if hidden:
            if not self.isVisible() or not self.isActiveWindow():
                return
            # Children such as the lyric canvas have their own hand cursor.
            # Save explicit/inherited cursors before blanking this window only.
            self._saved_cursors = [(widget, widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor), widget.cursor())
                                   for widget in [self, *self.findChildren(QWidget)]]
            for widget, _, _ in self._saved_cursors:
                widget.setCursor(Qt.CursorShape.BlankCursor)
        else:
            for widget, explicit, cursor in self._saved_cursors:
                try:
                    if explicit:
                        widget.setCursor(cursor)
                    else:
                        widget.unsetCursor()
                except RuntimeError:
                    pass  # A popup child may have been destroyed while idle.
            self._saved_cursors.clear()
        self._cursor_hidden = hidden

    def _fade_chrome(self, visible):
        if self.chrome_visible == visible:
            if getattr(self.controller, "reduced_motion", False):
                for effect, animation in zip(self.chrome_effects, self.chrome_animations):
                    animation.stop()
                    effect.setOpacity(1.0 if visible else 0.0)
            return
        self.chrome_visible = visible
        for effect, animation in zip(self.chrome_effects, self.chrome_animations):
            animation.stop()
            animation.setDuration(0 if getattr(self.controller, "reduced_motion", False) else 320)
            animation.setStartValue(effect.opacity())
            animation.setEndValue(1.0 if visible else 0.0)
            animation.start()

    def tick(self):
        c = self.controller
        def stamp(seconds):
            value = max(0, int(seconds))
            return f"{value // 60}:{value % 60:02}"
        self.elapsed.setText(stamp(c.position))
        self.total.setText(stamp(c.track.duration))
        if not self.progress.isSliderDown():
            self.progress.setValue(max(0, min(1000, int(1000 * c.position / c.track.duration))) if c.track.duration else 0)
        self.canvas.update()
        self.update()

    def _prepare_backdrop(self):
        c, w, h = self.controller, self.width(), self.height()
        key = (self.scene, w, h, c.primary.rgba(), c.secondary.rgba())
        if key == self.scene_key:
            return
        self.scene_key = key
        self.backdrop = QPixmap(w, h)
        self.backdrop.fill(QColor("#080e10" if self.scene != "lyrics" else "#080b10"))
        painter = QPainter(self.backdrop)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        atmospheres = {
            "studio": [(.18, .53, .6, c.primary, 44), (.85, .22, .75, c.secondary, 29), (.8, 1.2, .65, c.primary, 19)],
            "lyrics": [(.14, .85, .62, c.secondary, 15), (.85, .2, .72, c.primary, 11)],
            "cinema": [(.5, -.22, .88, c.primary, 65), (.09, .62, .63, c.secondary, 32), (.92, .62, .63, c.secondary, 32)],
            "orbit": [(.27, .43, .51, c.primary, 50), (.9, .1, .7, c.secondary, 26)],
        }
        for x, y, radius, color, alpha in atmospheres[self.scene]:
            gradient = QRadialGradient(w * x, h * y, w * radius)
            gradient.setColorAt(0, tint(color, alpha))
            gradient.setColorAt(.48, tint(color, alpha * .34))
            gradient.setColorAt(1, tint(color, 0))
            painter.fillRect(self.backdrop.rect(), gradient)
        if self.scene == "cinema":
            beam = QLinearGradient(0, h * .2, 0, h * .82)
            beam.setColorAt(0, tint(c.primary, 12))
            beam.setColorAt(1, tint(c.primary, 0))
            path = QPainterPath()
            path.moveTo(w * .36, -20)
            path.lineTo(w * .64, -20)
            path.lineTo(w * .91, h * .85)
            path.lineTo(w * .09, h * .85)
            path.closeSubpath()
            painter.fillPath(path, beam)
            painter.setPen(QPen(tint(c.primary, 12), 1))
            painter.drawLine(QPointF(w * .09, h * .82), QPointF(w * .91, h * .82))
        # Restrained, deterministic grain gives the gradients a material surface.
        painter.setPen(QColor(220, 233, 226, 5 if self.scene == "lyrics" else 7))
        for y in range(0, h, 9):
            for x in range((y * 7) % 11, w, 11):
                if (x * 13 + y * 7) % 5 == 0:
                    painter.drawPoint(x, y)
        painter.end()

    def paintEvent(self, event):
        self._prepare_backdrop()
        c, w, h = self.controller, self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self.backdrop)
        phase = 0 if getattr(c, "reduced_motion", False) else getattr(c, "motion_time", 0.0)
        if self.scene == "orbit":
            center = self.cover.geometry().center()
            base = self.cover.width() * .75
            for i in range(8):
                radius = base + i * 8
                p.setPen(QPen(tint(c.primary if i % 2 == 0 else c.secondary, 11 if i else 38), 1))
                p.drawEllipse(QPointF(center), radius, radius)
            for i in range(3):
                radius = base + 16 + i * 13
                angle = phase * (.08 + i * .025) + i * 2.1
                point = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(tint(c.primary, 145 - i * 24))
                p.drawEllipse(point, 2.5, 2.5)
                p.setPen(QPen(tint(c.primary, 80 - i * 12), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), int(-angle * 180 / math.pi * 16), 24 * 16)
        elif self.scene == "studio":
            center = self.cover.geometry().center()
            for i in range(5):
                radius = self.cover.width() * (.72 + i * .065)
                p.setPen(QPen(tint(c.primary, 6 - i), 1))
                p.drawEllipse(QPointF(center), radius, radius)
        elif self.scene == "cinema":
            haze = QRadialGradient(w * (.5 + math.sin(phase * .06) * .035), h * .24, w * .48)
            haze.setColorAt(0, tint(c.primary, 8))
            haze.setColorAt(1, tint(c.primary, 0))
            p.fillRect(self.rect(), haze)
        if getattr(c, "glow", False) and c.track.connected and c.track.playing and getattr(c, "intensity", 0) > 0:
            paint_edge_glow(p, w, h, c)
