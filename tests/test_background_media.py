"""Media boundaries, frame treatment and actual silent-video lifecycle checks."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from halo import backgrounds
from halo.backgrounds import BackgroundRenderer, BACKGROUND_DEFAULTS, validate_background_file
from halo.models import Track


APP = QApplication.instance() or QApplication([])
TEMP_ROOT = Path(__file__).resolve().parents[1] / ".cache" / "background-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def image_bytes(colour, size=(80, 60)):
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def controller(**values):
    state = dict(BACKGROUND_DEFAULTS)
    state.update(track=Track(playing=True, connected=True), reduced_motion=False,
                 primary=QColor("#98c0b0"), background_artwork=b"")
    state.update(values)
    return SimpleNamespace(**state)


def painted(renderer, width=160, height=90, phase=0.):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#b71c1c"))
    painter = QPainter(image)
    rendered = renderer.paint(painter, QRectF(0, 0, width, height), phase)
    painter.end()
    return image, rendered


class BackgroundMediaTests(unittest.TestCase):
    def setUp(self):
        self.files = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.directory = Path(self.files.name)
        self.image = self.directory / "wallpaper.png"
        self.image.write_bytes(image_bytes("#3070c0"))
        self.renderer = BackgroundRenderer()

    def tearDown(self):
        self.renderer.close()
        APP.processEvents()
        self.files.cleanup()

    def test_only_local_regular_files_are_accepted(self):
        self.assertEqual(validate_background_file(self.image, "image"), str(self.image.resolve()))
        for value in ("https://example.com/image.png", "file:///C:/image.png", "//server/image.png",
                      "\\\\server\\image.png", "", self.directory, self.directory / "gone.png"):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                validate_background_file(value, "image")
        with self.assertRaises(ValueError):
            validate_background_file(self.image, "ambient")

    def test_image_dimensions_bytes_and_content_are_bounded(self):
        with patch.object(backgrounds, "MAX_IMAGE_BYTES", 1), self.assertRaises(ValueError):
            validate_background_file(self.image, "image")
        with patch.object(backgrounds, "MAX_IMAGE_PIXELS", 1), self.assertRaises(ValueError):
            validate_background_file(self.image, "image")
        bad = self.directory / "bad.png"
        bad.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            validate_background_file(bad, "image")
        svg = self.directory / "image.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"/>')
        with self.assertRaises(ValueError):
            validate_background_file(svg, "image")

    def test_video_validation_checks_local_extension_and_size(self):
        file = self.directory / "small.mp4"
        file.write_bytes(b"invalid content rejected asynchronously by the decoder")
        self.assertEqual(validate_background_file(file, "video"), str(file.resolve()))
        with patch.object(backgrounds, "MAX_VIDEO_BYTES", 1), self.assertRaises(ValueError):
            validate_background_file(file, "video")
        with self.assertRaises(ValueError):
            validate_background_file(self.image, "video")

    def test_missing_media_clears_previous_song_immediately(self):
        c = controller(background_source="artwork", track=Track(artwork=image_bytes("blue"), playing=True))
        self.renderer.sync(c, active=True)
        self.assertTrue(self.renderer.has_media)
        c.track = Track(title="A new song", playing=True)
        self.renderer.sync(c, active=True)
        self.assertFalse(self.renderer.has_media)
        self.assertFalse(painted(self.renderer)[1])
        self.assertTrue(self.renderer._previous.isNull())

    def test_invalid_custom_file_returns_to_ambient_without_decoder(self):
        c = controller(background_source="image", background_path=str(self.image))
        self.renderer.sync(c, active=True)
        c.background_path = str(self.directory / "missing.png")
        self.renderer.sync(c, active=True)
        self.assertFalse(self.renderer.has_media)
        self.assertIn("unavailable", self.renderer.status)
        self.assertIsNone(self.renderer._player)

    def test_online_cover_is_preferred_and_spotify_is_the_waiting_fallback(self):
        c = controller(background_source="artwork", background_art_source="online",
            track=Track(artwork=image_bytes("blue"), playing=True), background_blur=0,
            background_dim=0, background_tint=0, background_vignette=0)
        self.renderer.sync(c, active=True)
        self.assertEqual(painted(self.renderer)[0].pixelColor(80, 45).name(), "#0000ff")
        c.background_artwork = image_bytes("red")
        c.reduced_motion = True
        self.renderer.sync(c, active=True)
        self.assertEqual(painted(self.renderer)[0].pixelColor(80, 45).name(), "#ff0000")
        self.assertEqual(self.renderer.status, "Online cover")

    def test_identical_sync_and_paints_reuse_image_preparation(self):
        c = controller(background_source="image", background_path=str(self.image))
        self.renderer.sync(c, active=True)
        key = self.renderer._current.cacheKey()
        with patch.object(self.renderer, "_prepare", wraps=self.renderer._prepare) as prepare:
            self.renderer.sync(c, active=True)
            for phase in (0, 1, 2):
                painted(self.renderer, phase=phase)
            prepare.assert_not_called()
        self.assertEqual(key, self.renderer._current.cacheKey())
        c.background_saturation = 0
        self.renderer.sync(c, active=True)
        colour = self.renderer._current.pixelColor(0, 0)
        self.assertEqual(colour.red(), colour.blue())
        self.assertEqual(colour.green(), colour.blue())
        self.assertLessEqual(len(self.renderer._cache), 4)

    def test_valid_song_change_crossfades_for_650_ms(self):
        c = controller(background_source="artwork", background_blur=0,
            background_dim=0, background_tint=0, background_vignette=0,
            track=Track(artwork=image_bytes("blue"), playing=True))
        with patch.object(backgrounds.time, "monotonic", return_value=10.):
            self.renderer.sync(c, active=True)
        c.track.artwork = image_bytes("red")
        with patch.object(backgrounds.time, "monotonic", return_value=11.):
            self.renderer.sync(c, active=True)
            first = painted(self.renderer)[0].pixelColor(80, 45)
        with patch.object(backgrounds.time, "monotonic", return_value=11.325):
            middle = painted(self.renderer)[0].pixelColor(80, 45)
        with patch.object(backgrounds.time, "monotonic", return_value=11.7):
            last = painted(self.renderer)[0].pixelColor(80, 45)
        self.assertEqual(first.name(), "#0000ff")
        self.assertAlmostEqual(middle.red(), 127, delta=2)
        self.assertAlmostEqual(middle.blue(), 127, delta=2)
        self.assertEqual(last.name(), "#ff0000")
        self.assertTrue(self.renderer._previous.isNull())

    def test_pause_and_reduced_motion_freeze_fades_and_motion(self):
        c = controller(background_source="artwork", track=Track(artwork=image_bytes("blue"), playing=True))
        with patch.object(backgrounds.time, "monotonic", return_value=10.):
            self.renderer.sync(c, active=True)
            c.track.artwork = image_bytes("red")
            self.renderer.sync(c, active=True)
            painted(self.renderer, phase=0)
        with patch.object(backgrounds.time, "monotonic", return_value=10.2):
            c.track.playing = False
            self.renderer.sync(c, active=True)
        fade = self.renderer._fade
        phase = self.renderer._phase
        with patch.object(backgrounds.time, "monotonic", return_value=11.):
            painted(self.renderer, phase=100)
        self.assertEqual(self.renderer._fade, fade)
        self.assertEqual(self.renderer._phase, phase)
        self.assertFalse(self.renderer._timer.isActive())
        c.reduced_motion = True
        self.renderer.sync(c, active=True)
        self.assertEqual(self.renderer._fade, 1.)
        self.assertTrue(self.renderer._previous.isNull())

    def test_frame_dimensions_and_preparation_cache_are_bounded(self):
        from PySide6.QtMultimedia import QVideoFrame
        self.renderer._active = True
        self.renderer._playing = True
        self.renderer._media_source = "video"
        self.renderer._path = "original.mp4"
        self.renderer.settings["background_blur"] = 0
        image = QImage(3840, 2160, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        self.renderer._receive_frame(QVideoFrame(image), self.renderer._generation)
        self.assertEqual(self.renderer._raw.size(), QSize(1920, 1080))
        for i in range(5):
            image.fill(QColor(i * 20, 100, 200))
            with patch.object(backgrounds.time, "monotonic", return_value=100 + i):
                self.renderer._receive_frame(QVideoFrame(image), self.renderer._generation)
        self.assertLessEqual(len(self.renderer._cache), 2)
        old = self.renderer._raw.cacheKey()
        self.renderer._receive_frame(QVideoFrame(image), self.renderer._generation - 1)
        self.assertEqual(self.renderer._raw.cacheKey(), old)

    def test_frame_delivery_is_capped_at_30_per_second(self):
        from PySide6.QtMultimedia import QVideoFrame
        self.renderer._active = True
        self.renderer._playing = True
        self.renderer._media_source = "video"
        self.renderer._path = "original.mp4"
        frame = QVideoFrame(QImage.fromData(image_bytes("blue")))
        with patch.object(backgrounds.time, "monotonic", return_value=100.):
            self.renderer._receive_frame(frame, self.renderer._generation)
        with patch.object(self.renderer, "_set_image", wraps=self.renderer._set_image) as setter:
            with patch.object(backgrounds.time, "monotonic", return_value=100.01):
                self.renderer._receive_frame(frame, self.renderer._generation)
            setter.assert_not_called()
            with patch.object(backgrounds.time, "monotonic", return_value=100.04):
                self.renderer._receive_frame(frame, self.renderer._generation)
            setter.assert_called_once()

    def test_close_is_reusable_and_releases_media(self):
        c = controller(background_source="image", background_path=str(self.image))
        self.renderer.sync(c, active=True)
        self.renderer.close()
        self.assertFalse(self.renderer.has_media)
        self.assertIsNone(self.renderer._player)
        self.assertFalse(self.renderer._timer.isActive())
        self.renderer.sync(c, active=True)
        self.assertTrue(self.renderer.has_media)

    def test_contain_keeps_whole_image_visible_even_with_zoom_and_motion(self):
        c = controller(background_source="image", background_path=str(self.image),
                       background_fit="contain", background_zoom=150, background_motion="breathe")
        self.renderer.sync(c, active=True)
        target = QRectF(0, 0, 500, 200)
        for phase in (0, 20, 100):
            destination = self.renderer._destination(self.renderer._current, target, phase)
            self.assertTrue(target.contains(destination))

    def test_video_saturation_work_is_limited_to_960_by_540(self):
        self.renderer._media_source = "video"
        self.renderer.settings.update(background_saturation=160, background_blur=0)
        image = QImage(1920, 1080, QImage.Format.Format_RGB32)
        image.fill(QColor("#3070c0"))
        prepared = self.renderer._prepare(image)
        self.assertEqual(prepared.size(), QSize(960, 540))

    def test_presets_and_numeric_settings_keep_within_shared_ranges(self):
        c = controller(background_blur=float("nan"), background_source="unknown")
        self.renderer.sync(c)
        self.assertEqual(self.renderer.settings["background_blur"], 22)
        self.assertEqual(self.renderer.settings["background_source"], "ambient")
        for _, _, settings in backgrounds.BACKGROUND_PRESETS:
            for name, value in settings.items():
                if name in backgrounds.BACKGROUND_RANGES:
                    lo, hi = backgrounds.BACKGROUND_RANGES[name]
                    self.assertLessEqual(lo, value)
                    self.assertLessEqual(value, hi)


class ActualVideoLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.clip = Path(cls.files.name) / "original-fixture.mp4"
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError, RuntimeError):
                raise unittest.SkipTest("An ffmpeg executable is needed to generate the original video fixture.")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=320x180:rate=30", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
            "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", "-y", str(cls.clip)], check=True, capture_output=True, timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.files.cleanup()

    def setUp(self):
        self.renderer = BackgroundRenderer()
        self.c = controller(background_source="video", background_path=str(self.clip))

    def tearDown(self):
        self.renderer.close()
        APP.processEvents()
        QTest.qWait(20)

    def wait_for(self, condition, timeout=4000):
        deadline = time.monotonic() + timeout / 1000
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertTrue(condition(), self.renderer.status)

    def test_real_video_loops_without_audio_and_stops_hidden(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.renderer.sync(self.c, active=False)
        self.assertIsNone(self.renderer._player)
        self.renderer.set_active(True)
        self.wait_for(lambda: self.renderer.has_media)
        player = self.renderer._player
        self.assertIsNone(player.audioOutput())
        self.assertEqual(player.activeAudioTrack(), -1)
        self.assertEqual(player.loops(), QMediaPlayer.Infinite)
        self.assertTrue(painted(self.renderer)[1])
        QTest.qWait(1200)
        self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.renderer.set_active(False)
        self.wait_for(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        position = player.position()
        QTest.qWait(120)
        self.assertLessEqual(abs(player.position() - position), 40)
        self.renderer.close()
        self.assertIsNone(self.renderer._player)
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: self.renderer.has_media)

    def test_music_pause_always_and_reduced_motion_hold_actual_frames(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: self.renderer.has_media)
        player = self.renderer._player
        self.c.track.playing = False
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        self.c.background_playback = "always"
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.c.reduced_motion = True
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        frame = self.renderer._raw.cacheKey()
        QTest.qWait(120)
        self.assertEqual(self.renderer._raw.cacheKey(), frame)

    def test_initial_reduced_motion_shows_one_poster_and_remains_frozen(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.c.reduced_motion = True
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: self.renderer.has_media)
        self.wait_for(lambda: self.renderer._player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        frame = self.renderer._raw.cacheKey()
        QTest.qWait(150)
        self.assertEqual(self.renderer._raw.cacheKey(), frame)

    def test_bad_video_falls_back_and_retry_count_is_bounded(self):
        invalid = Path(self.files.name) / "bad-video.mp4"
        invalid.write_bytes(b"invalid video data")
        self.c.background_path = str(invalid)
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: self.renderer._retry_count >= 2)
        self.assertFalse(self.renderer.has_media)
        self.assertIsNone(self.renderer._player)
        self.assertIn("could not be played", self.renderer.status)
        for _ in range(3):
            self.renderer.sync(self.c, active=True)
        self.assertEqual(self.renderer._retry_count, 2)
        self.assertIsNone(self.renderer._player)

    def test_artwork_to_actual_video_crossfades_after_first_frame(self):
        self.c.background_source = "artwork"
        self.c.track.artwork = image_bytes("blue")
        self.renderer.sync(self.c, active=True)
        self.c.background_source = "video"
        self.renderer.sync(self.c, active=True)
        self.wait_for(lambda: self.renderer.has_media)
        self.assertFalse(self.renderer._previous.isNull())
        self.assertLess(self.renderer._fade, .4)
        QTest.qWait(300)
        self.assertGreater(self.renderer._fade, .25)
        self.assertLess(self.renderer._fade, 1.)
        QTest.qWait(450)
        self.assertEqual(self.renderer._fade, 1.)
        self.assertTrue(self.renderer._previous.isNull())


if __name__ == "__main__":
    unittest.main()
