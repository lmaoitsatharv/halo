import argparse
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QSettings, QLockFile, QThread
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QCheckBox, QSlider,
    QFileDialog, QSystemTrayIcon, QMenu, QMessageBox)
from .models import Track, Lyrics, parse_lrc, load_lrc, DEMO_LRC
from .spotify import SpotifyWorker
from .lyrics import LyricsWorker
from .audio import AudioMeter
from .widgets import EdgeOverlay, FloatingLyrics, AmbientBackdrop, artwork_palette
from .positioning import PositionDialog

from .frontend import STYLE, build_main
from .immersive import Immersive, IMMERSIVE_SCENES
from .glow import HALO_MODES
from .lyric_rendering import LYRIC_STYLES
from .palette import PaletteTransition, valid_colour, readable_accent, envelope

HALO_ANIMATIONS = (("flow", "Flow"), ("music", "Music sync"), ("idle", "Idle"), ("still", "Still"))



def label(text, name=None):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    return item


def make_icon():
    image = QPixmap(64, 64)
    image.fill(QColor("#15251b"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#c8e8ad"), 4))
    p.drawEllipse(12, 12, 40, 40)
    p.setPen(QPen(QColor("#67b9a0"), 3))
    p.drawArc(20, 20, 24, 24, 30 * 16, 220 * 16)
    p.end()
    return QIcon(image)


class Controller(QObject):
    trackChanged = Signal()
    lyricsChanged = Signal()
    requestLyrics = Signal(object, int)
    settingChanged = Signal()
    paletteChanged = Signal()

    def __init__(self, settings, offline=False):
        super().__init__()
        self.settings = settings
        self.track = Track()
        self.live_track = Track()
        self.lyrics = Lyrics()
        self.position = 0.0
        self.generation = 0
        self.lookup_signature = None
        self.demo = False
        self.demo_anchor = time.monotonic()
        self.demo_position = 0.0
        self.demo_playing = True
        self.primary = QColor("#b7e4ad")
        self.secondary = QColor("#54ad9f")
        self.halo_primary = QColor(self.primary)
        self.halo_secondary = QColor(self.secondary)
        self.palette_transition = PaletteTransition(self.halo_primary, self.halo_secondary, time.monotonic())
        self.palette_initialized = False
        self.glow = settings.value("glow", True, type=bool)
        self.floating = settings.value("floating", False, type=bool)
        self.floating_x = max(0, min(100, settings.value("floating_x", 50, type=int)))
        self.floating_y = max(0, min(100, settings.value("floating_y", 90, type=int)))
        self.floating_screen = settings.value("floating_screen", "", type=str)
        self.reactive = settings.value("reactive", False, type=bool)
        self.intensity = max(0, min(100, settings.value("intensity", 62, type=int)))
        self.glow_width = max(12, min(160, settings.value("width", 40, type=int)))
        self.rim_width = max(1, min(12, settings.value("rim_width", 3, type=int)))
        self.glow_opacity = max(0, min(100, settings.value("glow_opacity", 65, type=int)))
        self.primary_brightness = max(0, min(100, settings.value("primary_brightness", 100, type=int)))
        self.secondary_brightness = max(0, min(100, settings.value("secondary_brightness", 100, type=int)))
        self.color_mix = max(0, min(100, settings.value("color_mix", 60, type=int)))
        self.custom_primary = valid_colour(settings.value("custom_primary", "#0a0d14", type=str), "#0a0d14").name()
        self.custom_secondary = valid_colour(settings.value("custom_secondary", "#005dff", type=str), "#005dff").name()
        self.offset = settings.value("offset", 0, type=int)
        self.palette = settings.value("palette", "Album colours", type=str)
        self.halo_mode = self.choice("halo_mode", HALO_MODES, "orbit")
        self.lyric_style = self.choice("lyric_style", LYRIC_STYLES, "fisheye_visual")
        self.immersive_mode = self.choice("immersive_mode", IMMERSIVE_SCENES, "studio")
        self.motion_speed = max(0, min(100, settings.value("motion_speed", 45, type=int)))
        self.halo_animation = self.choice("halo_animation", HALO_ANIMATIONS, "music" if self.reactive else "flow")
        self.reactive = self.halo_animation == "music"
        self.reduced_motion = settings.value("reduced_motion", False, type=bool)
        self.motion_time = 0.0
        self.motion_phase = 0.0
        self.last_tick_at = time.monotonic()
        self.pulse = 0.0
        self.error = ""
        self.audio = AudioMeter()
        self.lyrics_thread = QThread()
        self.lyrics_worker = LyricsWorker()
        self.lyrics_worker.moveToThread(self.lyrics_thread)
        self.requestLyrics.connect(self.lyrics_worker.fetch)
        self.lyrics_worker.ready.connect(self.accept_lyrics)
        self.lyrics_thread.finished.connect(self.lyrics_worker.deleteLater)
        self.lyrics_thread.start()
        self.spotify = SpotifyWorker()
        self.spotify.changed.connect(self.accept_track)
        self.spotify.status.connect(self.accept_status)
        if not offline:
            self.spotify.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.update_palette()

    def choice(self, setting, choices, default):
        value = self.settings.value(setting, default, type=str)
        return value if value in {item[0] for item in choices} else default

    def accept_status(self, message):
        self.error = message

    def accept_track(self, track):
        self.live_track = track
        if self.demo:
            return
        previous = self.track
        changed = previous.key != track.key or previous.connected != track.connected
        self.track = track
        self.error = ""
        if changed:
            self.update_palette()
            self.generation += 1
            self.lookup_signature = None
            self.lyrics = Lyrics(message="Finding timed lyrics…" if track.connected else
                                 "Play a song in Spotify, or try the demo below.")
            self.trackChanged.emit()
            self.lyricsChanged.emit()
        elif previous.playing != track.playing:
            self.trackChanged.emit()
        # Wait for a useful duration before matching. Never query on every poll.
        signature = (*track.key, round(track.duration))
        if track.connected and track.title and signature != self.lookup_signature:
            self.lookup_signature = signature
            self.generation += 1
            self.lyrics_worker.latest_generation = self.generation
            self.requestLyrics.emit(track, self.generation)

    def accept_lyrics(self, generation, lyrics):
        if generation == self.generation and not self.demo:
            self.lyrics = lyrics
            self.lyricsChanged.emit()

    def retry_lyrics(self):
        if self.demo or not self.track.connected:
            return
        self.generation += 1
        self.lyrics_worker.latest_generation = self.generation
        self.lyrics = Lyrics(message="Finding timed lyrics…")
        self.lyricsChanged.emit()
        self.requestLyrics.emit(self.track, self.generation)

    def update_palette(self):
        palettes = {"Violet hour": ("#d4b5ff", "#7576eb"),
                    "Sea glass": ("#a9ead4", "#5498cb"),
                    "Ember": ("#ffcb93", "#c36381")}
        if self.palette == "Custom":
            a, b = QColor(self.custom_primary), QColor(self.custom_secondary)
        elif self.palette in palettes:
            a, b = palettes[self.palette]
            a, b = QColor(a), QColor(b)
        else:
            a, b = artwork_palette(self.track.artwork)
        now = time.monotonic()
        self.palette_transition.retarget(a, b, now, immediate=not self.palette_initialized)
        self.palette_initialized = True
        self.halo_primary, self.halo_secondary = self.palette_transition.at(now)
        self.primary, self.secondary = readable_accent(a, b), readable_accent(b, a)
        self.paletteChanged.emit()

    def set(self, name, value):
        setattr(self, name, value)
        self.settings.setValue("width" if name == "glow_width" else name, value)
        if name == "halo_animation":
            self.reactive = value == "music"
            self.settings.setValue("reactive", self.reactive)
        elif name == "reactive":
            self.halo_animation = "music" if value else "flow"
            self.settings.setValue("halo_animation", self.halo_animation)
        if name in {"palette", "custom_primary", "custom_secondary"}:
            self.update_palette()
        self.settingChanged.emit()

    def set_demo(self, enabled):
        self.demo = enabled
        self.generation += 1
        if enabled:
            self.demo_position = 8.0
            self.demo_anchor = time.monotonic()
            self.demo_playing = True
            self.track = Track("In the light we made", "Halo Studio · visual demo", "Sound in colour",
                               60, 8, True, True, observed_at=time.monotonic())
            self.lyrics = Lyrics(parse_lrc(DEMO_LRC), "Original demo text · line-synced")
        else:
            self.lookup_signature = None
            self.track = Track()
            self.accept_track(self.live_track)
        self.update_palette()
        self.trackChanged.emit()
        self.lyricsChanged.emit()

    def transport(self, action):
        if self.demo:
            if action == "toggle":
                self.demo_position = self.position
                self.demo_anchor = time.monotonic()
                self.demo_playing = not self.demo_playing
                self.track.playing = self.demo_playing
            else:
                self.demo_position = (self.position + (5 if action == "next" else -5)) % 60
                self.demo_anchor = time.monotonic()
            self.trackChanged.emit()
        else:
            self.spotify.command(action)

    def seek(self, seconds):
        if self.demo:
            self.demo_position = seconds
            self.demo_anchor = time.monotonic()
        else:
            self.spotify.command("seek", seconds)

    def tick(self):
        now = time.monotonic()
        elapsed = max(0, min(.1, now - self.last_tick_at))
        self.last_tick_at = now
        if self.track.connected and self.track.playing and not self.reduced_motion:
            self.motion_time += elapsed
            if self.halo_animation != "still":
                rate = self.motion_speed / 45 / 26.28
                if self.halo_animation == "idle":
                    rate *= .18
                elif self.halo_animation == "music":
                    rate *= .4 + 1.4 * self.pulse
                self.motion_phase = (self.motion_phase + elapsed * rate) % 1.
        self.halo_primary, self.halo_secondary = self.palette_transition.at(now)
        if self.demo:
            self.position = (self.demo_position + (now - self.demo_anchor if self.demo_playing else 0)) % 60
        else:
            self.position = self.track.position + (max(0, now - self.track.observed_at) if self.track.playing else 0)
            if self.track.duration:
                self.position = min(self.position, self.track.duration)
        # Stop capturing output when Spotify is paused, absent, or demo is active.
        self.audio.enabled = (self.reactive and self.track.playing and not self.demo
                              and not self.reduced_motion and self.halo_animation != "still")
        target = self.audio.level if self.audio.enabled and not self.audio.error else 0.
        if self.demo and self.demo_playing:
            target = .25 + .65 * max(0, math.sin(now * 3.6)) ** 6
        if not self.reduced_motion:
            self.pulse = envelope(self.pulse, target, elapsed)

    def close(self):
        self.timer.stop()
        self.audio.close()
        self.spotify.stop()
        self.spotify.wait(5500)
        self.lyrics_worker.closing = True
        self.lyrics_thread.quit()
        self.lyrics_thread.wait(18000)
        self.settings.sync()


class MainWindow(AmbientBackdrop):
    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.exiting = False
        self.position_dialog = None
        self.setWindowTitle("Halo · Spotify companion")
        self.setWindowIcon(make_icon())
        build_main(self, controller)

        self.immersive = Immersive(controller)
        self.immersive.setWindowIcon(self.windowIcon())
        self.immersive.exited.connect(self.reopen)
        self.overlay = FloatingLyrics(controller)
        self.edges = []
        self.rebuild_edges()
        QApplication.instance().screenAdded.connect(lambda _: self.rebuild_edges())
        QApplication.instance().screenRemoved.connect(lambda _: self.rebuild_edges())
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("Halo · Spotify companion")
        menu = QMenu()
        menu.addAction("Open Halo", self.reopen)
        menu.addAction("Immersive view", self.fullscreen)
        menu.addSeparator()
        self.tray_glow = menu.addAction("Screen-edge glow")
        self.tray_glow.setCheckable(True)
        self.tray_glow.setChecked(controller.glow)
        self.tray_glow.triggered.connect(self.glow.setChecked)
        menu.addSeparator()
        menu.addAction("Quit Halo", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reopen() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        controller.trackChanged.connect(self.refresh)
        controller.lyricsChanged.connect(self.refresh_lyrics)
        controller.settingChanged.connect(lambda: self.tray_glow.setChecked(controller.glow))
        controller.settingChanged.connect(self.place_overlay)
        self.draw_timer = QTimer(self)
        self.draw_timer.timeout.connect(self.draw)
        self.draw_timer.start(16)
        self.refresh()
        self.refresh_lyrics()

    def checkbox(self, text, setting, layout, tooltip):
        check = QCheckBox(text)
        check.setChecked(getattr(self.c, setting))
        check.setToolTip(tooltip)
        check.toggled.connect(lambda value: self.c.set(setting, value))
        layout.addWidget(check)
        self.setting_controls[setting] = check
        return check

    def slider(self, layout, text, name, low, high, suffix):
        row = QHBoxLayout()
        row.addWidget(label(text, "muted"))
        row.addStretch()
        value_label = label(str(getattr(self.c, name)) + suffix, "muted")
        row.addWidget(value_label)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setAccessibleName(text)
        slider.setRange(low, high)
        slider.setValue(getattr(self.c, name))
        slider.valueChanged.connect(lambda value: (self.c.set(name, value), value_label.setText(str(value) + suffix)))
        layout.addWidget(slider)

    def rebuild_edges(self):
        for edge in self.edges:
            edge.close()
            edge.deleteLater()
        self.edges = [EdgeOverlay(self.c, screen) for screen in QApplication.screens()]
        self.place_overlay()

    def overlay_screen(self):
        return next((screen for screen in QApplication.screens() if screen.name() == self.c.floating_screen),
                    QApplication.primaryScreen())

    def place_overlay(self):
        self.overlay.place(self.overlay_screen())

    def open_position_settings(self):
        if self.position_dialog is None:
            self.position_dialog = PositionDialog(self.c, self)
        self.position_dialog.show()
        self.position_dialog.raise_()
        self.position_dialog.activateWindow()

    def refresh(self):
        self.title.setText(self.c.track.title)
        self.artist.setText(self.c.track.artist)
        self.badge.setText("◉  Visual demo" if self.c.demo else
                           ("●  Spotify connected" if self.c.track.connected else "○  Waiting for Spotify"))
        self.play.setText("Ⅱ" if self.c.track.playing else "▶")
        for item in [self.play, self.previous, self.next, self.progress]:
            item.setEnabled(self.c.track.connected)
        self.demo_button.setText("Return to Spotify" if self.c.demo else "Try the visual demo")
        self.immersive.refresh()

    def refresh_lyrics(self):
        message = self.c.lyrics.message
        if self.c.demo:
            status = "Demo lyrics"
        elif self.c.lyrics.lines:
            status = "Line synced"
        elif not self.c.track.connected:
            status = "Waiting for a song"
        elif message.startswith("Finding"):
            status = "Finding lyrics…"
        elif "untimed" in message:
            status = "Untimed lyrics only"
        elif "instrumental" in message:
            status = "Instrumental"
        elif "busy" in message or "unavailable" in message or "reach" in message:
            status = "Service unavailable"
        else:
            status = "No synced lyrics"
        self.lyrics_badge.setText(status)
        self.lyrics_badge.setToolTip(message)
        self.retry_button.setEnabled(self.c.track.connected and not self.c.demo)

    def draw(self):
        c = self.c
        visible = c.track.connected and c.track.playing
        main_visible = self.isVisible() and not self.isMinimized()
        immersive_visible = self.immersive.isVisible() and not self.immersive.isMinimized()
        for edge in self.edges:
            should_show = c.glow and visible and not immersive_visible and c.intensity > 0
            if should_show != edge.isVisible():
                edge.setVisible(should_show)
            if should_show:
                edge.update()
        preview = bool(self.position_dialog and self.position_dialog.isVisible()
                       and self.position_dialog.desktop_preview.isChecked())
        self.overlay.previewing = preview
        should_float = not immersive_visible and (preview or
                       (c.floating and visible and bool(c.lyrics.lines) and not main_visible))
        if should_float != self.overlay.isVisible():
            self.overlay.setVisible(should_float)
        if should_float:
            self.overlay.update()
        if main_visible:
            self.mark.update()
            for tile in self.mode_tiles:
                if tile.isVisible():
                    tile.update()
            self.canvas.update()
            if not self.progress.isSliderDown():
                self.progress.setValue(int(1000 * c.position / c.track.duration) if c.track.duration else 0)
            def stamp(seconds):
                value = max(0, int(seconds))
                return f"{value // 60}:{value % 60:02}"
            self.time_label.setText(stamp(c.position) + " / " + stamp(c.track.duration))
            message = c.error or (c.audio.error if c.reactive and not c.demo else "")
            self.footer.setText(message or "No Spotify login needed · close to keep Halo in the tray")
        if immersive_visible:
            self.immersive.tick()

    def fullscreen(self):
        if self.position_dialog:
            self.position_dialog.close()
        self.immersive.refresh()
        self.immersive.showFullScreen()
        self.immersive.activateWindow()

    def import_lrc(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import timed lyrics for this song", "", "Timed lyrics (*.lrc)")
        if not filename:
            return
        try:
            lines = load_lrc(filename)
            if not lines:
                raise ValueError("This file has no valid [mm:ss.xx] timestamps.")
            self.c.generation += 1
            self.c.lyrics = Lyrics(lines, "Imported .lrc · current song only")
            self.c.lyricsChanged.emit()
        except Exception as error:
            QMessageBox.warning(self, "Couldn't import lyrics", str(error))

    def reopen(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.exiting = True
        self.immersive.hide()
        self.overlay.hide()
        for edge in self.edges:
            edge.hide()
        QApplication.quit()

    def closeEvent(self, event):
        if not self.exiting and self.tray.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            self.quit()
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="Halo · Windows Spotify companion")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Disable the Windows media bridge")
    parser.add_argument("--snapshot", help="Save a UI preview and quit (for development)")
    parser.add_argument("--snapshot-view", choices=("main", "immersive", "position"), default="main",
                        help="Choose the view for a development snapshot")
    parser.add_argument("--report", help="Write a live validation report and quit after 12 seconds")
    parser.add_argument("--halo-mode", choices=[item[0] for item in HALO_MODES], help="Choose a halo mode")
    parser.add_argument("--lyric-style", choices=[item[0] for item in LYRIC_STYLES], help="Choose a lyric animation")
    parser.add_argument("--immersive-mode", choices=[item[0] for item in IMMERSIVE_SCENES], help="Choose an immersive scene")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parent.parent
    default_data = Path(os.getenv("LOCALAPPDATA", str(source_root))) / "Halo" if getattr(sys, "frozen", False) else source_root / ".data"
    data_dir = Path(os.getenv("HALO_DATA_DIR", str(default_data)))
    data_dir.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(data_dir / "halo.log", maxBytes=500_000, backupCount=2)])
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Halo")
    app.setOrganizationName("Halo")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)
    lock = QLockFile(str(data_dir / "instance.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Halo is already running", "Open Halo from the system tray next to the clock.")
        return 0
    settings = QSettings(str(data_dir / "settings.ini"), QSettings.Format.IniFormat)
    c = Controller(settings, offline=args.offline)
    for setting in ("halo_mode", "lyric_style", "immersive_mode"):
        if getattr(args, setting):
            c.set(setting, getattr(args, setting))
    window = MainWindow(c)
    app.aboutToQuit.connect(c.close)
    window.show()
    if args.demo:
        c.set_demo(True)
    if args.snapshot and not args.report:
        if args.snapshot_view == "immersive":
            window.fullscreen()
        elif args.snapshot_view == "position":
            window.open_position_settings()
        def snapshot():
            target = window.immersive if args.snapshot_view == "immersive" else (
                     window.position_dialog if args.snapshot_view == "position" else window)
            target.grab().save(args.snapshot)
            window.quit()
        QTimer.singleShot(2300 if args.snapshot_view == "immersive" else 1600, snapshot)
    if args.report:
        def report():
            result = {"connected": c.track.connected, "playing": c.track.playing,
                      "title": c.track.title, "duration": c.track.duration,
                      "position": c.position, "artwork_bytes": len(c.track.artwork),
                      "lyrics_lines": len(c.lyrics.lines), "lyrics_status": c.lyrics.message,
                      "media_error": c.error, "audio_error": c.audio.error}
            Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
            if args.snapshot:
                window.grab().save(args.snapshot)
            window.quit()
        QTimer.singleShot(12000, report)
    result = app.exec()
    lock.unlock()
    return result
