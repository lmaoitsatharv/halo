"""Immersive-only local media, with bounded frames and no desktop side effects."""
from collections import OrderedDict
import hashlib
import math
import os
from pathlib import Path
import time

import numpy as np
from PySide6.QtCore import (QObject, Signal, QBuffer, QIODevice, QRectF, QSize,
                            Qt, QTimer, QUrl)
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QRadialGradient

try:
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
except ImportError:  # Image backgrounds remain usable in an essentials-only setup.
    QMediaPlayer = QVideoSink = None


BACKGROUND_SOURCES = (("ambient", "Halo ambience"), ("artwork", "Album artwork"),
                      ("image", "Your image"), ("video", "Your video"))
BACKGROUND_FITS = (("cover", "Fill the scene"), ("contain", "Fit the whole image"))
BACKGROUND_MOTIONS = (("still", "Still"), ("drift", "Slow drift"), ("breathe", "Gentle breathing"))
BACKGROUND_PLAYBACK = (("music", "With the music"), ("always", "Keep moving"))
BACKGROUND_ART_SOURCES = (("spotify", "Spotify cover"), ("online", "Online cover"))
BACKGROUND_DEFAULTS = {
    "background_source": "ambient", "background_path": "", "background_fit": "cover",
    "background_motion": "drift", "background_playback": "music",
    "background_art_source": "spotify", "background_blur": 22, "background_dim": 55,
    "background_saturation": 100, "background_zoom": 108, "background_vignette": 55,
    "background_tint": 10, "background_speed": 30,
    "background_focus_x": 50, "background_focus_y": 50,
}
BACKGROUND_RANGES = {
    "background_blur": (0, 60), "background_dim": (0, 90),
    "background_saturation": (0, 160), "background_zoom": (100, 150),
    "background_vignette": (0, 100), "background_tint": (0, 60),
    "background_speed": (0, 100), "background_focus_x": (0, 100),
    "background_focus_y": (0, 100),
}
BACKGROUND_PRESETS = (
    ("cinematic", "Cinematic", {"background_blur": 16, "background_dim": 60,
        "background_saturation": 85, "background_zoom": 112, "background_vignette": 72,
        "background_tint": 12, "background_motion": "drift", "background_speed": 24}),
    ("soft", "Soft focus", {"background_blur": 40, "background_dim": 48,
        "background_saturation": 95, "background_zoom": 115, "background_vignette": 40,
        "background_tint": 8, "background_motion": "breathe", "background_speed": 18}),
    ("vivid", "Vivid", {"background_blur": 5, "background_dim": 40,
        "background_saturation": 145, "background_zoom": 108, "background_vignette": 58,
        "background_tint": 6, "background_motion": "drift", "background_speed": 35}),
    ("monochrome", "Monochrome", {"background_blur": 8, "background_dim": 52,
        "background_saturation": 0, "background_zoom": 108, "background_vignette": 70,
        "background_tint": 0, "background_motion": "still", "background_speed": 20}),
    ("dreamy", "Dreamy", {"background_blur": 32, "background_dim": 42,
        "background_saturation": 120, "background_zoom": 120, "background_vignette": 48,
        "background_tint": 25, "background_motion": "breathe", "background_speed": 22}),
)

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 36_000_000
MAX_IMAGE_SIDE = 12_000
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAME_SIZE = QSize(1920, 1080)
MAX_VIDEO_RATE = 30
IMAGE_FORMATS = {b"png", b"jpeg", b"jpg", b"webp", b"bmp", b"gif", b"avif",
                 b"heif", b"heic", b"tiff", b"tif", b"ico"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}


def _checked_reader(reader, size=MAX_FRAME_SIZE):
    dimensions = reader.size()
    width, height = dimensions.width(), dimensions.height()
    if (bytes(reader.format()).lower() not in IMAGE_FORMATS or not reader.canRead()
            or min(width, height) < 1 or max(width, height) > MAX_IMAGE_SIDE
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("Choose a supported image smaller than 36 megapixels.")
    reader.setAutoTransform(True)
    reader.setScaledSize(dimensions.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError("This image could not be opened. Choose another image.")
    return image


def validate_background_file(path, source):
    """Return an absolute local file path, rejecting remote and oversized media."""
    if source not in {"image", "video"}:
        raise ValueError("Choose an image or video background.")
    try:
        raw = os.fspath(path)
        if not isinstance(raw, str) or not raw.strip() or "://" in raw or raw.startswith(("\\\\", "//")):
            raise ValueError("Choose a file stored on this computer.")
        file = Path(raw).expanduser().resolve(strict=True)
        # Alternate data streams and device paths are not media-file selections.
        if str(file).startswith(("\\\\", "//")) or not file.is_file() or ":" in str(file)[2:]:
            raise ValueError("Choose a local image or video file.")
        size = file.stat().st_size
        limit = MAX_IMAGE_BYTES if source == "image" else MAX_VIDEO_BYTES
        if not 0 < size <= limit:
            raise ValueError("Choose an image under 64 MB or a video under 2 GB.")
        if source == "image":
            _checked_reader(QImageReader(str(file)), QSize(64, 64))
        elif file.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError("Choose an MP4, WebM, MOV, MKV or AVI video.")
        return str(file)
    except (OSError, RuntimeError, TypeError) as error:
        raise ValueError("This file is unavailable. Choose a file stored on this computer.") from error


def _decode_artwork(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("No cover is available for this song yet.")
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return _checked_reader(QImageReader(buffer))


class BackgroundRenderer(QObject):
    """A reusable painter surface; owns no windows and never opens an audio output."""
    changed = Signal()
    CROSSFADE_SECONDS = .65

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = "Halo ambience"
        self.settings = dict(BACKGROUND_DEFAULTS)
        self._signature = None
        self._media_source = "ambient"
        self._path = ""
        self._raw = QImage()
        self._current = QImage()
        self._previous = QImage()
        self._pending_previous = QImage()
        self._cache = OrderedDict()
        self._fade = 1.
        self._last_tick = time.monotonic()
        self._active = False
        self._playing = False
        self._reduced = False
        self._closed = False
        self._phase = 0.
        self._last_phase = None
        self._tint = QColor("#718578")
        self._player = None
        self._sink = None
        self._generation = 0
        self._last_frame_at = 0.
        self._retry_count = 0
        self._timer = QTimer(self)
        self._timer.setInterval(round(1000 / MAX_VIDEO_RATE))
        self._timer.timeout.connect(self._tick)
        self._poster_timeout = QTimer(self)
        self._poster_timeout.setSingleShot(True)
        self._poster_timeout.setInterval(6000)
        self._poster_timeout.timeout.connect(self._poster_failed)

    @property
    def has_media(self):
        return not self._current.isNull()

    @property
    def _can_move(self):
        return (self._active and not self._reduced
                and (self._playing or self.settings["background_playback"] == "always"))

    def sync(self, controller, active=False, preview=False):
        """Sync only on state changes; repeated calls do not reload identical media."""
        self._advance()
        self._closed = False
        old_treatment = (self.settings["background_blur"], self.settings["background_saturation"])
        for key, default in BACKGROUND_DEFAULTS.items():
            value = getattr(controller, key, default)
            if key in BACKGROUND_RANGES:
                lo, hi = BACKGROUND_RANGES[key]
                try:
                    value = max(lo, min(hi, int(value)))
                except (ValueError, TypeError, OverflowError):
                    value = default
            self.settings[key] = value
        source = self.settings["background_source"]
        if source not in dict(BACKGROUND_SOURCES):
            source = self.settings["background_source"] = "ambient"
        self._playing = bool(getattr(getattr(controller, "track", None), "playing", False))
        self._reduced = bool(getattr(controller, "reduced_motion", False))
        self._active = bool(active)
        self._last_tick = time.monotonic()
        palette = getattr(controller, "primary", None)
        if isinstance(palette, QColor) and palette.isValid():
            self._tint = QColor(palette)
        data = b""
        if source == "artwork":
            data = getattr(getattr(controller, "track", None), "artwork", b"")
            if self.settings["background_art_source"] == "online":
                data = getattr(controller, "background_artwork", b"") or data
            signature = (source, hashlib.sha256(data).digest() if isinstance(data, bytes) else b"")
        elif source in {"image", "video"}:
            raw_path = self.settings["background_path"]
            try:
                stat = Path(raw_path).stat()
                signature = (source, str(raw_path), stat.st_mtime_ns, stat.st_size)
            except (OSError, TypeError, ValueError):
                signature = (source, str(raw_path), None)
        else:
            signature = ("ambient",)
        if signature != self._signature:
            self._signature = signature
            self._release_video()
            self._media_source = source
            self._path = ""
            self._retry_count = 0
            try:
                if source == "ambient":
                    self._clear("Halo ambience")
                elif source == "artwork":
                    self._set_image(_decode_artwork(data))
                    self.status = "Online cover" if self.settings["background_art_source"] == "online" and getattr(controller, "background_artwork", b"") else "Spotify cover"
                elif source == "image":
                    self._path = validate_background_file(self.settings["background_path"], "image")
                    self._set_image(_checked_reader(QImageReader(self._path)))
                    self.status = Path(self._path).name
                else:
                    self._path = validate_background_file(self.settings["background_path"], "video")
                    previous = self._current
                    self._clear("Video ready" if not self._active else "Opening video…")
                    self._pending_previous = previous if self._can_move else QImage()
            except ValueError as error:
                self._clear(str(error))
        elif old_treatment != (self.settings["background_blur"], self.settings["background_saturation"]) and not self._raw.isNull():
            self._current = self._prepare(self._raw)
            self._previous = QImage()
            self._fade = 1.
        if self._reduced:
            self._previous = QImage()
            self._fade = 1.
        if source == "artwork" and self.has_media:
            self.status = "Online cover" if self.settings["background_art_source"] == "online" and getattr(controller, "background_artwork", b"") else "Spotify cover"
        self._update_video()
        self._update_timer()
        self.changed.emit()

    def _clear(self, status):
        self.status = status
        self._raw = QImage()
        self._current = QImage()
        self._previous = QImage()
        self._pending_previous = QImage()
        self._cache.clear()
        self._fade = 1.

    def _prepare(self, image):
        blur, saturation = self.settings["background_blur"], self.settings["background_saturation"]
        key = (image.cacheKey(), blur, saturation)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        prepared = image
        if self._media_source == "video" and saturation != 100:
            prepared = image.scaled(QSize(960, 540), Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        if blur:
            # A two-scale pyramid is smooth, predictable and cheaper than a
            # full-resolution blur pass for every decoded video frame.
            factor = 1 + blur * .42
            tiny = QSize(max(12, round(prepared.width() / factor)), max(12, round(prepared.height() / factor)))
            prepared = prepared.scaled(tiny, Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        if saturation != 100:
            rgba = prepared.convertToFormat(QImage.Format.Format_RGBA8888)
            pixels = np.frombuffer(rgba.constBits(), dtype=np.uint8).reshape(rgba.height(), rgba.bytesPerLine())
            pixels = pixels[:, :rgba.width() * 4].reshape(rgba.height(), rgba.width(), 4).copy()
            gray = ((pixels[:, :, 0].astype(np.uint16) * 54
                     + pixels[:, :, 1].astype(np.uint16) * 183
                     + pixels[:, :, 2].astype(np.uint16) * 19) // 256).astype(np.int16)
            # Integer channel passes avoid several full-frame float arrays on
            # the GUI thread. All intermediate values fit signed 16-bit range.
            for channel in range(3):
                original = pixels[:, :, channel].astype(np.int16)
                adjusted = original + (original - gray) * (saturation - 100) // 100
                np.clip(adjusted, 0, 255, out=adjusted)
                pixels[:, :, channel] = adjusted
            prepared = QImage(pixels.data, rgba.width(), rgba.height(), pixels.strides[0], QImage.Format.Format_RGBA8888).copy()
        # Keep blurred frames small: QPainter's smooth scaling performs the final
        # reconstruction without retaining full-size copies in the cache.
        self._cache[key] = prepared
        while len(self._cache) > (2 if self._media_source == "video" else 4):
            self._cache.popitem(last=False)
        return prepared

    def _set_image(self, image, video=False):
        if image.isNull():
            return
        self._advance()
        previous = self._current
        self._raw = image
        self._current = self._prepare(image)
        if not video:
            self._previous = previous if self._can_move else QImage()
            self._fade = 0. if not self._previous.isNull() else 1.
        elif previous.isNull() and not self._pending_previous.isNull():
            self._previous = self._pending_previous
            self._pending_previous = QImage()
            self._fade = 0. if self._can_move else 1.
            self._update_timer()
        self._last_tick = time.monotonic()

    def _release_video(self):
        self._generation += 1
        self._poster_timeout.stop()
        player, sink = self._player, self._sink
        self._player = self._sink = None
        if player is not None:
            player.stop()
            player.setVideoSink(None)
            player.setSource(QUrl())
            player.deleteLater()
        if sink is not None:
            sink.deleteLater()

    def _create_video(self):
        if QMediaPlayer is None:
            self.status = "Video support is unavailable in this Halo installation."
            return
        self._generation += 1
        generation = self._generation
        self._sink = QVideoSink(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(None)
        self._player.setActiveAudioTrack(-1)
        self._player.setLoops(QMediaPlayer.Infinite)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(lambda frame: self._receive_frame(frame, generation))
        self._player.tracksChanged.connect(self._silence_audio)
        self._player.errorOccurred.connect(lambda error, message="": self._video_error(generation))
        self._last_frame_at = 0.
        self._player.setSource(QUrl.fromLocalFile(self._path))
        self._poster_timeout.start()

    def _silence_audio(self):
        if self._player is not None:
            self._player.setActiveAudioTrack(-1)

    def _update_video(self):
        if self._media_source != "video" or not self._path:
            return
        if self._player is None and self._active and self._retry_count < 2:
            self._create_video()
        if self._player is None:
            return
        if self._active and (self._can_move or not self.has_media):
            self._player.play()
        else:
            self._player.pause()
            self._poster_timeout.stop()

    def _receive_frame(self, frame, generation):
        if generation != self._generation or not self._active or not frame.isValid():
            return
        # A native decoder can deliver already queued frames after pause().
        # Keep the first poster, then ignore those deliveries while frozen.
        if self.has_media and not self._can_move:
            return
        now = time.monotonic()
        if self.has_media and now - self._last_frame_at < 1 / MAX_VIDEO_RATE:
            return
        size = frame.size()
        if (size.width() * size.height() > MAX_IMAGE_PIXELS
                or max(size.width(), size.height()) > MAX_IMAGE_SIDE):
            self._video_error(generation)
            return
        image = frame.toImage()
        if image.isNull():
            return
        image = image.scaled(MAX_FRAME_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._last_frame_at = now
        self._set_image(image, video=True)
        self.status = Path(self._path).name
        self._poster_timeout.stop()
        if not self._can_move and self._player is not None:
            self._player.pause()
        self.changed.emit()

    def _poster_failed(self):
        if self._media_source == "video" and not self.has_media:
            self._video_error(self._generation)

    def _video_error(self, generation):
        if generation != self._generation:
            return
        self._retry_count += 1
        self._release_video()
        self._clear("This video could not be played. Try an MP4 or WebM video.")
        self.changed.emit()
        if self._retry_count < 2 and self._active:
            current_generation = self._generation
            QTimer.singleShot(800, lambda: self._retry_video(current_generation))

    def _retry_video(self, generation):
        if generation == self._generation and not self._closed and self._active:
            self._update_video()

    def _advance(self):
        now = time.monotonic()
        elapsed = max(0., min(1., now - self._last_tick))
        self._last_tick = now
        if self._can_move and self._fade < 1.:
            self._fade = min(1., self._fade + elapsed / self.CROSSFADE_SECONDS)
            if self._fade >= 1.:
                self._previous = QImage()

    def _update_timer(self):
        if self._active and self._fade < 1. and self._can_move:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        self._advance()
        self._update_timer()
        self.changed.emit()

    def set_active(self, active):
        self._advance()
        self._active = bool(active)
        self._last_tick = time.monotonic()
        if not self._active:
            self._last_phase = None
        self._update_video()
        self._update_timer()

    def _destination(self, image, rect, phase):
        iw, ih = image.width(), image.height()
        cover = self.settings["background_fit"] != "contain"
        scale = (max if cover else min)(rect.width() / iw, rect.height() / ih)
        zoom = self.settings["background_zoom"] / 100 if cover else 1.
        motion = self.settings["background_motion"]
        if cover and motion == "breathe" and self.settings["background_speed"] > 0:
            zoom *= 1 + (1 + math.sin(phase * .09)) * .013
        width, height = iw * scale * zoom, ih * scale * zoom
        focus_x = self.settings["background_focus_x"] / 100
        focus_y = self.settings["background_focus_y"] / 100
        if motion == "drift" and self.settings["background_speed"] > 0:
            focus_x = max(0., min(1., focus_x + math.sin(phase * .06) * .045))
            focus_y = max(0., min(1., focus_y + math.cos(phase * .043) * .035))
        # Panning operates only on cropped space; contained media stays centred.
        x = rect.x() - max(0., width - rect.width()) * focus_x + max(0., rect.width() - width) / 2
        y = rect.y() - max(0., height - rect.height()) * focus_y + max(0., rect.height() - height) / 2
        return QRectF(x, y, width, height)

    def paint(self, painter, rect, phase=0):
        if not self.has_media:
            return False
        self._advance()
        try:
            phase = float(phase)
            if not math.isfinite(phase):
                phase = 0.
        except (ValueError, TypeError):
            phase = 0.
        if self._last_phase is not None and self._can_move:
            self._phase += max(0., min(1., phase - self._last_phase)) * self.settings["background_speed"] / 30
        self._last_phase = phase
        rect = QRectF(rect)
        painter.save()
        painter.setClipRect(rect)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(rect, QColor("#080b0d"))
        if not self._previous.isNull() and self._fade < 1.:
            painter.drawImage(self._destination(self._previous, rect, self._phase), self._previous)
            # Smoothstep gives crossfades a soft start and finish.
            painter.setOpacity(self._fade * self._fade * (3 - 2 * self._fade))
        painter.drawImage(self._destination(self._current, rect, self._phase), self._current)
        painter.setOpacity(1.)
        tint = QColor(self._tint)
        tint.setAlphaF(self.settings["background_tint"] / 100)
        painter.fillRect(rect, tint)
        painter.fillRect(rect, QColor(3, 6, 8, round(255 * self.settings["background_dim"] / 100)))
        strength = self.settings["background_vignette"] / 100
        if strength:
            gradient = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * .7)
            gradient.setColorAt(0., QColor(0, 0, 0, 0))
            gradient.setColorAt(.48, QColor(0, 0, 0, round(22 * strength)))
            gradient.setColorAt(1., QColor(0, 0, 0, round(220 * strength)))
            painter.fillRect(rect, gradient)
        painter.restore()
        return True

    def close(self):
        """Release decoder resources; sync() can reuse this renderer afterwards."""
        self._closed = True
        self._active = False
        self._timer.stop()
        self._release_video()
        self._signature = None
        self._path = ""
        self._last_phase = None
        self._clear("Halo ambience")
