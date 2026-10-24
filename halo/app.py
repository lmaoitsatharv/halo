import argparse
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
from dataclasses import replace
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QSettings, QLockFile, QThread, QEvent
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QCursor, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QCheckBox, QSlider,
    QFileDialog, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QVBoxLayout,
    QListWidget, QPushButton, QPlainTextEdit)
from .models import Track, Lyrics, parse_lrc, load_lrc, DEMO_LRC
from .spotify import SpotifyWorker
from .lyrics import LyricsWorker
from .lyric_store import LyricStore, recording_key, MAX_OFFSET_MS
from .audio import AudioMeter
from .artwork import ArtworkWorker
from .widgets import EdgeOverlay, FloatingLyrics, AmbientBackdrop, artwork_palette
from .positioning import PositionDialog

from .frontend import STYLE, build_main
from .immersive import Immersive, IMMERSIVE_SCENES
from .glow import HALO_MODES
from .lyric_rendering import LYRIC_STYLES, LYRIC_STYLE_ALIASES, canonical_lyric_style
from .mode_catalog import MODE_FIELDS, all_modes, find_mode, read_collection
from .palette import PaletteTransition, valid_colour, readable_accent, envelope
from .backgrounds import (BACKGROUND_DEFAULTS, BACKGROUND_PRESETS, BACKGROUND_RANGES,
                          validate_background_file)

HALO_ANIMATIONS = (("flow", "Flow"), ("music", "Music sync"), ("idle", "Idle"), ("still", "Still"))

BACKGROUND_CHOICES = {
    "background_source": {"ambient", "artwork", "image", "video"},
    "background_fit": {"cover", "contain"},
    "background_motion": {"still", "drift", "breathe"},
    "background_playback": {"music", "always"},
    "background_art_source": {"spotify", "online"},
}
def background_value(name, value):
    default = BACKGROUND_DEFAULTS[name]
    if name in BACKGROUND_CHOICES:
        return value if isinstance(value, str) and value in BACKGROUND_CHOICES[name] else default
    if name in BACKGROUND_RANGES:
        try:
            number = int(value) if not isinstance(value, bool) else default
        except (TypeError, ValueError, OverflowError):
            number = default
        low, high = BACKGROUND_RANGES[name]
        return max(low, min(high, number))
    return value[:4096] if isinstance(value, str) else default



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
    requestChoices = Signal(object, int)
    requestLyricSelection = Signal(object, int, str)
    lyricChoicesChanged = Signal()
    requestArtwork = Signal(object)
    settingChanged = Signal()
    paletteChanged = Signal()
    backgroundChanged = Signal()
    modeLibraryChanged = Signal()

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
        self.artwork_online = settings.value("artwork_online", False, type=bool)
        self.artwork_fallback = None
        self.artwork_pending = None
        self.artwork_retry_at = 0.
        self.background_artwork = b""
        self.background_error = ""
        for name, default in BACKGROUND_DEFAULTS.items():
            setattr(self, name, background_value(name, settings.value(name, default)))
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
        # Existing installation-wide calibration remains the baseline. New
        # corrections belong only to this exact recording.
        self.global_offset = max(-3000, min(3000, settings.value("offset", 0, type=int)))
        self.song_offset = 0
        self.offset = self.global_offset
        self.lyric_store = LyricStore(Path(settings.fileName()).parent / "saved-lyrics")
        self.saved_lyric_kind = ""
        self.lyric_save_error = ""
        self.lyric_choices = []
        self.lyric_choices_status = ""
        self.selection_generation = None
        self.choice_generation = None
        self.palette = settings.value("palette", "Album colours", type=str)
        self.halo_mode = self.choice("halo_mode", HALO_MODES, "orbit")
        saved_style = settings.value("lyric_style", "fisheye_visual", type=str)
        self.lyric_style = canonical_lyric_style(saved_style)
        if saved_style != self.lyric_style:
            settings.setValue("lyric_style", self.lyric_style)
        self.immersive_mode = self.choice("immersive_mode", IMMERSIVE_SCENES, "studio")
        self.added_modes = read_collection(settings.value("added_modes", "{}", type=str))
        recovered_mode = False
        for kind, field in MODE_FIELDS.items():
            selected = find_mode(kind, getattr(self, field))
            if selected and not selected.included and selected.key not in self.added_modes[kind]:
                self.added_modes[kind].append(selected.key)
                recovered_mode = True
        if recovered_mode:
            self._save_mode_collection()
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
        self.requestChoices.connect(self.lyrics_worker.list_choices)
        self.requestLyricSelection.connect(self.lyrics_worker.select_candidate)
        self.lyrics_worker.choices_ready.connect(self.accept_lyric_choices)
        self.lyrics_worker.ready.connect(self.accept_lyrics)
        self.lyrics_thread.finished.connect(self.lyrics_worker.deleteLater)
        self.lyrics_thread.start()
        self.artwork_thread = QThread()
        self.artwork_worker = ArtworkWorker()
        self.artwork_worker.moveToThread(self.artwork_thread)
        self.requestArtwork.connect(self.artwork_worker.fetch)
        self.artwork_worker.ready.connect(self.accept_artwork)
        self.artwork_thread.finished.connect(self.artwork_worker.deleteLater)
        self.artwork_thread.start()
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

    def _save_mode_collection(self):
        self.settings.setValue("added_modes", json.dumps(self.added_modes, sort_keys=True))

    def mode_specs(self, field):
        return tuple((spec.key, spec.title, spec.description) for spec in all_modes()
                     if spec.field == field and self.has_mode(spec.kind, spec.key))

    def has_mode(self, kind, key):
        spec = find_mode(kind, key)
        return bool(spec and (spec.included or key in self.added_modes.get(kind, [])))

    def add_mode(self, kind, key):
        spec = find_mode(kind, key)
        if spec is None:
            return False
        if not self.has_mode(kind, key):
            self.added_modes[kind].append(key)
            self.added_modes[kind].sort()
            self._save_mode_collection()
            self.modeLibraryChanged.emit()
        return True

    def remove_mode(self, kind, key):
        spec = find_mode(kind, key)
        if spec is None or spec.included or not self.has_mode(kind, key):
            return False
        self.added_modes[kind].remove(key)
        self._save_mode_collection()
        if getattr(self, spec.field) == key:
            default = {"lyrics": "ship_visual", "scenes": "studio", "halo": "orbit"}[kind]
            self.set(spec.field, default)
        self.modeLibraryChanged.emit()
        return True

    def accept_status(self, message):
        self.error = message

    def accept_track(self, track):
        self.live_track = track
        if self.demo:
            return
        self.artwork_worker.latest_key = track.key if (self.artwork_online or self._background_online_enabled()) and track.connected else None
        if self.artwork_fallback and self.artwork_fallback[0] != track.key:
            self.artwork_fallback = None
        if not track.artwork and track.connected and self.artwork_fallback:
            track = replace(track, artwork=self.artwork_fallback[1])
        previous = self.track
        changed = (previous.key != track.key or previous.connected != track.connected
                   or recording_key(previous) != recording_key(track))
        artwork_changed = previous.artwork != track.artwork
        self.track = track
        self.error = ""
        if changed:
            self.background_artwork = b""
            saved = self.lyric_store.load(track)
            self.song_offset = saved.get("offset", 0)
            self.offset = self.global_offset + self.song_offset
            self.saved_lyric_kind = saved.get("kind", "")
            self.lyric_save_error = ""
            self.lyric_choices = []
            self.lyric_choices_status = ""
            self.selection_generation = self.choice_generation = None
            self.artwork_pending = None
            self.artwork_retry_at = 0.
            self.update_palette()
            self.generation += 1
            self.lookup_signature = None
            self.lyrics = saved.get("lyrics") or Lyrics(message="Finding timed lyrics…" if track.connected else
                                 "Play a song in Spotify, or try the demo below.")
            self.trackChanged.emit()
            self.lyricsChanged.emit()
            self.settingChanged.emit()
            self.lyricChoicesChanged.emit()
            self.backgroundChanged.emit()
        elif artwork_changed:
            self.update_palette()
            self.trackChanged.emit()
        elif previous.playing != track.playing:
            self.trackChanged.emit()
        # Wait for a useful duration before matching. Never query on every poll.
        signature = (*track.key, round(track.duration))
        if track.connected and track.title and signature != self.lookup_signature:
            self.lookup_signature = signature
            if not self.saved_lyric_kind:
                self.generation += 1
                self.lyrics_worker.latest_generation = self.generation
                self.requestLyrics.emit(track, self.generation)
        self.find_artwork()

    def find_artwork(self):
        track = self.track
        wants_background = self._background_online_enabled() and not self.background_artwork
        wants_cover = self.artwork_online and not track.artwork
        if (self.demo or not (wants_background or wants_cover) or not track.connected
                or not 1 <= track.duration <= 3600 or not track.album or not track.artist
                or self.artwork_pending == track.key or time.monotonic() < self.artwork_retry_at):
            return
        self.artwork_worker.latest_key = track.key
        self.artwork_pending = track.key
        self.requestArtwork.emit(track)

    def accept_artwork(self, key, data):
        if self.artwork_pending == key:
            self.artwork_pending = None
        if self.demo or not (self.artwork_online or self._background_online_enabled()) or not self.track.connected or self.track.key != key:
            return
        if not data:
            self.artwork_retry_at = time.monotonic() + 60.
        else:
            if self._background_online_enabled():
                self.background_artwork = data
                self.backgroundChanged.emit()
            if self.artwork_online and not self.track.artwork:
                self.artwork_fallback = (key, data)
                self.accept_track(replace(self.track, artwork=data))

    def _background_online_enabled(self):
        return self.background_source == "artwork" and self.background_art_source == "online"

    def _background_lookup_changed(self):
        self.artwork_worker.latest_key = self.track.key if (self.artwork_online or self._background_online_enabled()) and not self.demo else None
        self.artwork_pending = None
        self.artwork_retry_at = 0.
        if not self._background_online_enabled():
            self.background_artwork = b""
        self.find_artwork()

    def set_background_file(self, filename, source):
        try:
            path = validate_background_file(filename, source)
        except (OSError, ValueError) as error:
            self.background_error = str(error)
            self.backgroundChanged.emit()
            raise ValueError(str(error)) from error
        self.background_path, self.background_source = path, source
        self.settings.setValue("background_path", path)
        self.settings.setValue("background_source", source)
        self.background_error = ""
        self._background_lookup_changed()
        self.settingChanged.emit()
        self.backgroundChanged.emit()

    def apply_background_preset(self, key):
        values = next((entry[2] for entry in BACKGROUND_PRESETS if entry[0] == key), None)
        if values is None:
            return
        for name, value in values.items():
            if name in BACKGROUND_DEFAULTS and name not in {"background_source", "background_path", "background_art_source"}:
                value = background_value(name, value)
                setattr(self, name, value)
                self.settings.setValue(name, value)
        self.settingChanged.emit()
        self.backgroundChanged.emit()

    def reset_background(self):
        for name, default in BACKGROUND_DEFAULTS.items():
            setattr(self, name, default)
            self.settings.setValue(name, default)
        self.background_error = ""
        self._background_lookup_changed()
        self.settingChanged.emit()
        self.backgroundChanged.emit()

    def accept_lyrics(self, generation, lyrics):
        if generation == self.generation and not self.demo:
            if generation == self.selection_generation:
                self.selection_generation = None
                if not lyrics.lines:
                    self.lyric_choices_status = lyrics.message
                    self.lyricChoicesChanged.emit()
                    return
                try:
                    self.lyric_store.save(self.track, self.song_offset, lyrics, "selected")
                except (OSError, ValueError, TypeError) as error:
                    self.lyric_choices_status = f"Could not save this choice: {error}"
                    self.lyricChoicesChanged.emit()
                    return
                self.saved_lyric_kind = "selected"
                self.lyric_save_error = ""
                self.lyric_choices_status = "Saved for this recording."
                self.lyricChoicesChanged.emit()
            self.lyrics = lyrics
            self.lyricsChanged.emit()

    def can_correct_lyrics(self):
        return not self.demo and recording_key(self.track) is not None

    def set_song_offset(self, value):
        if not self.can_correct_lyrics():
            return
        value = max(-MAX_OFFSET_MS, min(MAX_OFFSET_MS, int(value)))
        saved = self.lyric_store.load(self.track)
        try:
            self.lyric_store.save(self.track, value, saved.get("lyrics"), saved.get("kind", "selected"))
        except (OSError, ValueError, TypeError) as error:
            self.lyric_save_error = self.error = f"Could not save lyric timing: {error}"
            self.settingChanged.emit()
            return
        self.song_offset = value
        self.lyric_save_error = ""
        self.offset = self.global_offset + value
        self.settingChanged.emit()

    def adjust_lyrics(self, milliseconds):
        self.set_song_offset(self.song_offset + milliseconds)

    def find_lyric_choices(self):
        if not self.can_correct_lyrics():
            return
        self.generation += 1
        self.lyrics_worker.latest_generation = self.generation
        self.choice_generation = self.generation
        self.selection_generation = None
        self.lyric_choices = []
        self.lyric_choices_status = "Looking for matching recordings…"
        self.lyricChoicesChanged.emit()
        self.requestChoices.emit(self.track, self.generation)

    def accept_lyric_choices(self, generation, choices):
        if generation != self.generation or generation != self.choice_generation or self.demo:
            return
        self.lyric_choices = choices
        self.lyric_choices_status = "Choose the lyrics that match this recording." if choices else "No other matching timed lyrics found. Try importing a corrected lyric file."
        self.lyricChoicesChanged.emit()
        # Opening the picker supersedes an in-flight automatic lookup. If no
        # result was displayed yet, continue it so closing the picker cannot
        # leave the main view permanently saying "Finding timed lyrics".
        if (generation == self.generation and not self.saved_lyric_kind
                and not self.lyrics.lines and self.lyrics.message.startswith("Finding")):
            self.requestLyrics.emit(self.track, generation)

    def select_lyric_source(self, source_id):
        if not self.can_correct_lyrics() or not any(str(item["id"]) == str(source_id) for item in self.lyric_choices):
            return
        self.generation += 1
        self.lyrics_worker.latest_generation = self.generation
        self.selection_generation = self.generation
        self.lyric_choices_status = "Loading your choice…"
        self.lyricChoicesChanged.emit()
        self.requestLyricSelection.emit(self.track, self.generation, str(source_id))

    def import_lyrics(self, filename):
        from .word_lyrics import load_lyrics_file
        if not self.can_correct_lyrics():
            raise ValueError("Play a song in Spotify and wait for its duration before importing lyrics.")
        lyrics = load_lyrics_file(filename)
        if not lyrics.lines:
            raise ValueError("This file has no valid timed lyrics.")
        self.lyric_store.save(self.track, self.song_offset, lyrics, "imported")
        self.generation += 1
        self.lyrics_worker.latest_generation = self.generation
        self.selection_generation = self.choice_generation = None
        self.saved_lyric_kind = "imported"
        self.lyric_save_error = ""
        self.lyrics = lyrics
        self.lyricsChanged.emit()

    def use_automatic_lyrics(self):
        if not self.can_correct_lyrics():
            return
        try:
            self.lyric_store.clear_lyrics(self.track, self.song_offset)
        except (OSError, ValueError) as error:
            self.lyric_save_error = self.error = f"Could not reset saved lyrics: {error}"
            self.settingChanged.emit()
            return
        self.saved_lyric_kind = ""
        self.lyric_save_error = ""
        self.retry_lyrics()

    def retry_lyrics(self):
        if self.demo or not self.track.connected:
            return
        # Retrying a network lookup never discards a deliberate saved choice.
        if self.saved_lyric_kind:
            self.lyricsChanged.emit()
            return
        self.generation += 1
        self.lyrics_worker.latest_generation = self.generation
        self.selection_generation = self.choice_generation = None
        self.lyric_choices_status = ""
        self.lyrics = Lyrics(message="Finding timed lyrics…")
        self.lyricsChanged.emit()
        self.lyricChoicesChanged.emit()
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
        if name == "lyric_style":
            value = canonical_lyric_style(value)
        kind = next((kind for kind, field in MODE_FIELDS.items() if field == name), None)
        if kind is not None:
            if find_mode(kind, value) is None:
                return
            self.add_mode(kind, value)
        if name in BACKGROUND_DEFAULTS:
            value = background_value(name, value)
            setattr(self, name, value)
            self.settings.setValue(name, value)
            self.background_error = ""
            if name in {"background_source", "background_art_source"}:
                self._background_lookup_changed()
            self.settingChanged.emit()
            self.backgroundChanged.emit()
            return
        if name == "song_offset":
            self.set_song_offset(value)
            return
        if name == "offset":
            self.set_song_offset(int(value) - self.global_offset)
            return
        setattr(self, name, value)
        self.settings.setValue("width" if name == "glow_width" else name, value)
        if name == "halo_animation":
            self.reactive = value == "music"
            self.settings.setValue("reactive", self.reactive)
        elif name == "reactive":
            self.halo_animation = "music" if value else "flow"
            self.settings.setValue("halo_animation", self.halo_animation)
        elif name == "artwork_online":
            self._background_lookup_changed()
        if name in {"palette", "custom_primary", "custom_secondary"}:
            self.update_palette()
        self.settingChanged.emit()

    def set_demo(self, enabled):
        self.demo = enabled
        self.generation += 1
        if enabled:
            self.background_artwork = b""
            self.song_offset = 0
            self.offset = self.global_offset
            self.saved_lyric_kind = ""
            self.artwork_worker.latest_key = None
            self.artwork_pending = None
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
        self.settingChanged.emit()

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
            if self.halo_animation == "music":
                # Round each accent into a swell, with a lingering light trail.
                self.pulse = envelope(self.pulse, target, elapsed, attack=.045, release=.22)
            else:
                self.pulse = envelope(self.pulse, target, elapsed)

    def close(self):
        self.timer.stop()
        self.audio.close()
        self.spotify.stop()
        self.spotify.wait(5500)
        self.artwork_worker.closing = True
        self.artwork_thread.quit()
        self.artwork_thread.wait(22000)
        self.lyrics_worker.closing = True
        self.lyrics_thread.quit()
        self.lyrics_thread.wait(18000)
        self.settings.sync()


class LyricChoiceDialog(QDialog):
    """Inspect alternate sources without replacing the playing song's lyrics."""
    def __init__(self, owner, controller):
        super().__init__(owner)
        self.c = controller
        self.setWindowTitle("Halo · Choose lyrics")
        self.setMinimumSize(560, 420)
        self.resize(660, 500)
        layout = QVBoxLayout(self)
        self.song = label("")
        self.song.setTextFormat(Qt.TextFormat.PlainText)
        self.song.setWordWrap(True)
        layout.addWidget(self.song)
        self.status = label("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.choices = QListWidget()
        self.choices.setAccessibleName("Matching lyric recordings")
        self.choices.currentRowChanged.connect(self.preview_choice)
        layout.addWidget(self.choices, 1)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Selected lyric text preview")
        self.preview.setMaximumHeight(150)
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        self.choose = QPushButton("Use these lyrics")
        self.choose.clicked.connect(self.save_choice)
        buttons.addWidget(self.choose)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._choice_ids = []
        self.c.lyricChoicesChanged.connect(self.sync)
        self.c.trackChanged.connect(self.sync)
        self.c.lyricsChanged.connect(self.sync)
        self.sync()

    def sync(self):
        self.song.setText(f"{self.c.track.title} · {self.c.track.artist}")
        self.status.setText(self.c.lyric_choices_status)
        ids = [str(item["id"]) for item in self.c.lyric_choices]
        if ids != self._choice_ids:
            self._choice_ids = ids
            self.choices.clear()
            for item in self.c.lyric_choices:
                seconds = max(0, round(item.get("duration", 0)))
                duration = f"{seconds // 60}:{seconds % 60:02}"
                timing = "Word timed" if item.get("word_synced") else "Line timed" if item.get("timed") else "No timed lyrics"
                self.choices.addItem(f"{item.get('title', '')}\n{item.get('artist', '')} · {item.get('album') or 'Album not supplied'} · {duration} · {timing}")
            if ids:
                self.choices.setCurrentRow(0)
            else:
                self.preview.clear()
        self.preview_choice(self.choices.currentRow())

    def preview_choice(self, index):
        valid = 0 <= index < len(self.c.lyric_choices)
        self.choose.setEnabled(valid and self.c.lyric_choices[index].get("timed", False)
                               and self.c.can_correct_lyrics() and self.c.selection_generation is None)
        self.preview.setPlainText(str(self.c.lyric_choices[index].get("preview", "")) if valid else "")

    def save_choice(self):
        index = self.choices.currentRow()
        if 0 <= index < len(self.c.lyric_choices):
            self.c.select_lyric_source(self.c.lyric_choices[index]["id"])


class MainWindow(AmbientBackdrop):
    def __init__(self, controller):
        super().__init__(controller)
        self.c = controller
        self.exiting = False
        self.position_dialog = None
        self.lyric_choice_dialog = None
        self.mode_library = None
        self._mode_return_settings = None
        self._mode_return_immersive = False
        self._return_to_immersive_settings = False
        self._initial_placed = False
        self._placing_initial = False
        self._return_maximized = controller.settings.value("window_maximized", False, type=bool)
        self.setWindowTitle("Halo · Spotify companion")
        self.setWindowIcon(make_icon())
        build_main(self, controller)
        self.settings_shortcut = QShortcut(QKeySequence("Ctrl+,"), self)
        self.settings_shortcut.activated.connect(self.open_settings)

        self.immersive = Immersive(controller)
        self.immersive.setWindowIcon(self.windowIcon())
        self.immersive.exited.connect(self.reopen)
        self.immersive.backgroundRequested.connect(self.open_background_settings)
        self.immersive.modesRequested.connect(lambda: self.open_modes("scenes"))
        self.settings_dialog.finished.connect(self._restore_immersive_after_settings)
        self.overlay = FloatingLyrics(controller)
        self.edges = []
        self.rebuild_edges()
        QApplication.instance().screenAdded.connect(lambda _: self.rebuild_edges())
        QApplication.instance().screenRemoved.connect(lambda _: self.rebuild_edges())
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("Halo · Spotify companion")
        menu = QMenu()
        menu.addAction("Open Halo", self.reopen)
        menu.addAction("Settings", self.open_settings)
        menu.addAction("Modes", self.open_modes)
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
        slider.valueChanged.connect(lambda value: (self.c.set(name, value), value_label.setText(str(getattr(self.c, name)) + suffix)))
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

    def open_settings(self):
        if self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
        else:
            self.settings_dialog.open_studio()

    def open_modes(self, kind="all"):
        from .mode_library import ModeLibrary
        kind = kind if isinstance(kind, str) else "all"
        if self.mode_library is None:
            self.mode_library = ModeLibrary(self, self.c)
            self.mode_library.finished.connect(self._restore_after_modes)
        if not self.mode_library.isVisible():
            self._mode_return_settings = self.settings_dialog.section if self.settings_dialog.isVisible() else None
            self._mode_return_immersive = self.immersive.isVisible()
            if self._mode_return_settings:
                self.settings_dialog.hide()
            if self._mode_return_immersive:
                self.immersive.hide()
        self.mode_library.open_page(kind)

    def _restore_after_modes(self, *_):
        if not self.exiting:
            if self._mode_return_immersive:
                self.immersive.showFullScreen()
                self.immersive.raise_()
                self.immersive.activateWindow()
            if self._mode_return_settings:
                self.settings_dialog.open_studio(self._mode_return_settings)
            elif not self._mode_return_immersive:
                self.reopen()
        self._mode_return_settings = None
        self._mode_return_immersive = False

    def open_background_settings(self):
        self._return_to_immersive_settings = self.immersive.isVisible()
        self.settings_dialog.open_backgrounds()

    def _restore_immersive_after_settings(self, *_):
        if self._return_to_immersive_settings and not self.exiting and self.immersive.isVisible():
            self.immersive.raise_()
            self.immersive.activateWindow()
        self._return_to_immersive_settings = False

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
            word_lines = sum(bool(getattr(line, "words", ())) for line in self.c.lyrics.lines if line.text.strip())
            line_count = sum(bool(line.text.strip()) for line in self.c.lyrics.lines)
            status = "Word synced" if word_lines and word_lines == line_count else "Mixed timing" if word_lines else "Line synced · words estimated"
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
        modes_visible = self.mode_library is not None and self.mode_library.isVisible()
        for edge in self.edges:
            should_show = c.glow and visible and not immersive_visible and c.intensity > 0
            if should_show != edge.isVisible():
                edge.setVisible(should_show)
            if should_show:
                edge.update()
        preview = bool(self.position_dialog and self.position_dialog.isVisible()
                       and self.position_dialog.desktop_preview.isChecked())
        self.overlay.previewing = preview
        should_float = not immersive_visible and not modes_visible and (preview or
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
        self._remember_window_state()
        self.settings_dialog.hide()
        if self.position_dialog:
            self.position_dialog.close()
        self.immersive.refresh()
        self.immersive.showFullScreen()
        self.immersive.activateWindow()

    def import_lrc(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import timed lyrics for this song", "", "Timed lyrics (*.lrc *.elrc *.lyricsfile.yaml *.yaml *.yml)")
        if not filename:
            return
        try:
            self.c.import_lyrics(filename)
        except Exception as error:
            QMessageBox.warning(self, "Couldn't import lyrics", str(error))

    def choose_lyrics(self):
        if not self.c.can_correct_lyrics():
            return
        if self.lyric_choice_dialog is None:
            self.lyric_choice_dialog = LyricChoiceDialog(self, self.c)
        self.lyric_choice_dialog.show()
        self.lyric_choice_dialog.raise_()
        self.lyric_choice_dialog.activateWindow()
        self.c.find_lyric_choices()

    def reopen(self):
        self.showMaximized() if self._return_maximized else self.showNormal()
        self.raise_()
        self.activateWindow()

    def _remember_window_state(self):
        if not self.isMinimized():
            self._return_maximized = self.isMaximized()
        self.c.settings.setValue("window_maximized", self._return_maximized)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_placed:
            self._initial_placed = True
            requested_maximized = self._return_maximized or self.isMaximized()
            screen = QApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
            area = screen.availableGeometry()
            self._placing_initial = True
            try:
                self.resize(min(self.width(), area.width() - 64), min(self.height(), area.height() - 80))
                bounds = self.frameGeometry()
                bounds.moveCenter(area.center())
                self.move(bounds.topLeft())
            finally:
                self._placing_initial = False
            self._return_maximized = requested_maximized
            if requested_maximized:
                QTimer.singleShot(0, self, self.showMaximized)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_return_maximized")
                and not self._placing_initial):
            self._remember_window_state()

    def quit(self):
        self._remember_window_state()
        self.exiting = True
        self._return_to_immersive_settings = False
        self._mode_return_settings = None
        self._mode_return_immersive = False
        if self.mode_library is not None:
            self.mode_library.hide()
        self.settings_dialog.hide()
        self.immersive.hide()
        self.immersive.media_background.close()
        self.overlay.hide()
        for edge in self.edges:
            edge.hide()
        QApplication.quit()

    def closeEvent(self, event):
        self._remember_window_state()
        if not self.exiting and self.tray.isSystemTrayAvailable():
            event.ignore()
            self.settings_dialog.hide()
            self.hide()
        else:
            self.quit()
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="Halo · Windows Spotify companion")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--offline", action="store_true", help="Disable the Windows media bridge")
    parser.add_argument("--settings", action="store_true", help="Open Halo settings on launch")
    parser.add_argument("--modes", action="store_true", help="Open the Modes library on launch")
    parser.add_argument("--mode-category", choices=("all", "lyrics", "scenes", "halo", "mine"), default="all")
    parser.add_argument("--snapshot", help="Save a UI preview and quit (for development)")
    parser.add_argument("--snapshot-view", choices=("main", "immersive", "position", "settings", "modes"), default="main",
                        help="Choose the view for a development snapshot")
    parser.add_argument("--settings-section", choices=("general", "halo", "lyrics", "scenes"), default="general",
                        help="Choose a settings section for a development snapshot")
    parser.add_argument("--report", help="Write a live validation report and quit after 12 seconds")
    parser.add_argument("--halo-mode", choices=[item[0] for item in HALO_MODES], help="Choose a halo mode")
    parser.add_argument("--lyric-style", type=lambda value: LYRIC_STYLE_ALIASES.get(value, value),
                        choices=[item[0] for item in LYRIC_STYLES], help="Choose a lyric animation")
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
    if args.settings:
        QTimer.singleShot(0, window.open_settings)
    if args.modes and not args.snapshot:
        QTimer.singleShot(0, lambda: window.open_modes(args.mode_category))
    if args.demo:
        c.set_demo(True)
    if args.snapshot and not args.report:
        if args.snapshot_view == "immersive":
            window.fullscreen()
        elif args.snapshot_view == "position":
            window.open_position_settings()
        elif args.snapshot_view == "settings":
            window.open_settings()
            index = [section[0] for section in window.settings_dialog.SECTIONS].index(args.settings_section)
            window.settings_dialog.select(index)
        elif args.snapshot_view == "modes":
            window.open_modes(args.mode_category)
        def snapshot():
            target = window.immersive if args.snapshot_view == "immersive" else (
                     window.position_dialog if args.snapshot_view == "position" else
                     window.settings_dialog if args.snapshot_view == "settings" else
                     window.mode_library if args.snapshot_view == "modes" else window)
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
