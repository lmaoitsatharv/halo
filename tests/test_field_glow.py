"""Rendered contracts for Neon and Liquid, the per-pixel field lights."""
import hashlib
import time
from types import SimpleNamespace
import unittest

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from halo.glow import HALO_MODES, paint_edge_glow, paint_halo_preview
from halo.glow_extras import EXTRA_HALO_MODES
from halo.glow_field import FIELD_HALO_MODES, paint_field_glow
from halo.mode_catalog import BASE_MODE_KEYS


def controller(mode="neon", **changes):
    values = dict(primary=QColor("#ff2d8a"), secondary=QColor("#7a5cff"),
                  intensity=100, pulse=0., glow_width=40, rim_width=3,
                  glow_opacity=65, primary_brightness=100, secondary_brightness=100,
                  color_mix=60, halo_mode=mode, halo_animation="flow",
                  motion_phase=.31, motion_time=0., motion_speed=45, reduced_motion=False)
    values.update(changes)
    return SimpleNamespace(**values)


def render(c, width=640, height=420, dpr=1., backdrop=None):
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor(backdrop) if backdrop else Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        paint_edge_glow(painter, width, height, c)
    finally:
        painter.end()
    return image


def fingerprint(image):
    return hashlib.sha256(image.constBits()).hexdigest()


def hue(colour):
    return colour.hsvHue()


MODES = [key for key, _, _ in FIELD_HALO_MODES]


class FieldCatalogueTests(unittest.TestCase):
    def test_neon_and_liquid_follow_the_originals_and_join_the_main_list(self):
        self.assertEqual(MODES, ["neon", "liquid"])
        self.assertEqual([key for key, _, _ in HALO_MODES[:5]], ["aura", "orbit", "wave", "pulse", "prism"])
        self.assertEqual(HALO_MODES[5:7], FIELD_HALO_MODES)
        self.assertEqual(HALO_MODES[-3:], EXTRA_HALO_MODES)
        self.assertEqual(BASE_MODE_KEYS["halo"], ("aura", "orbit", "wave", "pulse", "prism", "neon", "liquid"))


class NeonTests(unittest.TestCase):
    def test_tube_has_a_white_hot_filament_inside_saturated_glass(self):
        image = render(controller())
        # The tube floats just inside the bezel: its filament is whiter than the glow beside it.
        core = min((image.pixelColor(320, y) for y in range(2, 10)), key=lambda c: c.hsvSaturationF())
        glow = image.pixelColor(320, 16)
        self.assertGreater(core.alpha(), 230)
        self.assertGreater(glow.alpha(), 20)
        self.assertLess(core.hsvSaturationF(), glow.hsvSaturationF() - .2)

    def test_top_and_bottom_are_one_colour_and_the_sides_the_other(self):
        image = render(controller())
        pink, violet = QColor("#ff2d8a").hsvHue(), QColor("#7a5cff").hsvHue()
        for x, y, expected in ((320, 16, pink), (320, 403, pink), (16, 210, violet), (623, 210, violet)):
            with self.subTest(point=(x, y)):
                self.assertLess(abs(hue(image.pixelColor(x, y)) - expected), 8)

    def test_tubes_strike_on_after_a_song_change_and_then_stay_lit(self):
        lit = render(controller())
        striking = render(controller(halo_struck_at=time.monotonic() - .02))
        settled = render(controller(halo_struck_at=time.monotonic() - 3.))
        self.assertLess(striking.pixelColor(320, 5).alpha(), lit.pixelColor(320, 5).alpha() * .3)
        self.assertEqual(fingerprint(settled), fingerprint(lit))
        # Reduce motion, Still and a paused song never play the flicker.
        for changes in (dict(reduced_motion=True), dict(halo_animation="still", motion_phase=0.),
                        dict(track=SimpleNamespace(playing=False))):
            with self.subTest(**changes):
                calm = render(controller(**changes))
                self.assertEqual(fingerprint(render(controller(halo_struck_at=time.monotonic() - .02, **changes))),
                                 fingerprint(calm))

    @staticmethod
    def song_lines(count=240, seed=4):
        import random
        rng = random.Random(seed)
        lines, t = [], 2.
        for _ in range(count):
            lines.append(t)
            t += rng.uniform(2.2, 4.8)
        return lines

    def test_tubes_struggle_often_on_lyric_lines_and_sung_words(self):
        from halo.glow_field import _lyric_anchors, _tube_levels
        times = self.song_lines()
        lines = [SimpleNamespace(time=t, words=()) for t in times]
        anchors, chances = _lyric_anchors(lines)
        # Every line is a candidate, and longer lines add one more between.
        self.assertTrue(set(times) <= set(anchors))
        self.assertGreater(len(anchors), len(times) * 1.3)
        frames, now = [], 0.
        while now < times[-1]:
            frames.append((now, _tube_levels(now, anchors, 3.7, chances, True)))
            now += 1 / 60
        # Something struggles to start every few seconds, and only on those moments.
        starts = [t for (_, before), (t, levels) in zip(frames, frames[1:])
                  if ((levels < 1.) & (before == 1.)).any()]
        self.assertGreater(len(starts), times[-1] / 4.)
        for start in starts:
            anchor = max(a for a in anchors if a <= start + 1e-6)
            self.assertLessEqual(start - anchor, 4.5)
        struggling = sum(bool((levels < 1.).any()) for _, levels in frames) / len(frames)
        self.assertGreater(struggling, .3)
        # Hard flicker: nearly black between near-full flashes.
        values = [value for _, frame in frames for value in frame]
        self.assertLessEqual(min(values), .05)
        self.assertTrue(any(.9 <= value < 1. for value in values))
        # Paused, Reduce motion or Still: steady. The same moment always looks the same.
        self.assertTrue(all((_tube_levels(t, anchors, 3.7, chances, False) == 1.).all() for t, _ in frames[::97]))
        for t, frame in frames[::53]:
            self.assertTrue((_tube_levels(t, anchors, 3.7, chances, True) == frame).all())

    def test_most_lines_set_tubes_off_and_starts_land_exactly_on_them(self):
        from halo.glow_field import _active_starts, _lyric_anchors
        times = self.song_lines()
        anchors, chances = _lyric_anchors([SimpleNamespace(time=t, words=()) for t in times])
        triggered = [t for t in times if any(abs(begin - t) < 1e-9 for begin, _ in
                                             _active_starts(t + 1e-3, anchors, 3.7, chances))]
        self.assertGreater(len(triggered), len(times) * .7)

    def test_sung_words_inside_a_line_are_start_points(self):
        from halo.glow_field import _lyric_anchors
        words = tuple(SimpleNamespace(start=10. + k * .5) for k in range(12))
        lines = [SimpleNamespace(time=10., words=words), SimpleNamespace(time=16.5, words=())]
        anchors, _ = _lyric_anchors(lines)
        inside = [a for a in anchors if 10. < a < 16.5]
        self.assertTrue(inside)
        self.assertTrue(all(any(abs(a - word.start) < 1e-9 for word in words) for a in inside))

    def test_random_groups_of_tubes_take_random_times_to_start(self):
        from collections import Counter
        from halo.glow_field import _start_plan
        sizes, groups, lengths = Counter(), set(), []
        for i in range(400):
            tubes, duration = _start_plan(3.7 + i * 7.31)
            sizes[len(tubes)] += 1
            groups.add(tuple(sorted(tubes)))
            lengths.append(duration)
        # One tube, a pair, three or all four; left and right together, top and left...
        self.assertEqual(set(sizes), {1, 2, 3, 4})
        self.assertGreater(sizes[4], 80)
        self.assertGreater(len(groups), 12)
        for group in ((1, 3), (0, 3), (0, 1, 2, 3)):
            self.assertIn(group, groups)
        # Sometimes a quick catch, sometimes a long struggle.
        self.assertLess(min(lengths), .7)
        self.assertGreater(max(lengths), 3.)
        self.assertGreater(sum(length > 2. for length in lengths), 80)

    def test_with_react_to_audio_the_struggling_tubes_flash_on_the_beat(self):
        from halo.glow_field import _lyric_anchors, _tube_levels
        times = self.song_lines()
        anchors, chances = _lyric_anchors([SimpleNamespace(time=t, words=()) for t in times])
        checked = 0
        for line in times:
            moment = line + .25
            quiet = _tube_levels(moment, anchors, 3.7, chances, True, beat=0., music=True)
            loud = _tube_levels(moment, anchors, 3.7, chances, True, beat=1., music=True)
            struggling = quiet < 1.
            if struggling.any():
                checked += 1
                self.assertTrue((quiet[struggling] <= .05).all())
                self.assertTrue((loud[struggling] >= .9).all())
        self.assertGreater(checked, 60)

    def test_songs_without_synced_lyrics_follow_their_own_timeline(self):
        from halo.glow_field import _tube_levels
        frames, now = [], 0.
        while now < 400.:
            frames.append((now, _tube_levels(now, 2.8, 1.9, .75, True)))
            now += 1 / 60
        starts = [t for (_, before), (t, levels) in zip(frames, frames[1:])
                  if ((levels < 1.) & (before == 1.)).any()]
        self.assertGreater(len(starts), 400 / 5.)
        for t, frame in frames[::61]:
            self.assertTrue((_tube_levels(t, 2.8, 1.9, .75, True) == frame).all())

    def test_neon_follows_the_song_position_and_its_lyrics(self):
        from halo.glow_field import _lyric_anchors, _song_seed, _tube_levels
        lines = self.song_lines(60)
        song = dict(position=0., offset=0., track=SimpleNamespace(playing=True, key=("Song", "Artist", "Album")),
                    lyrics=SimpleNamespace(lines=[SimpleNamespace(time=t) for t in lines]))
        anchors, chances = _lyric_anchors(song["lyrics"].lines)
        moments = [t + .2 for t in lines
                   if (_tube_levels(t + .2, anchors, _song_seed(song["track"].key), chances, True) < 1.).any()]
        self.assertTrue(moments)
        moment = moments[0]
        struggling = render(controller(**{**song, "position": moment}))
        steady = render(controller(**{**song, "position": moment, "reduced_motion": True}))
        self.assertNotEqual(fingerprint(struggling), fingerprint(steady))
        self.assertEqual(fingerprint(struggling), fingerprint(render(controller(**{**song, "position": moment}))))


class LiquidTests(unittest.TestCase):
    def test_drops_bulge_inward_and_move_with_the_phase(self):
        first, later = render(controller("liquid", motion_phase=.1)), render(controller("liquid", motion_phase=.17))
        self.assertNotEqual(fingerprint(first), fingerprint(later))
        # A thin film everywhere, and pools reaching well past it somewhere.
        def deepest(image):
            best = 0
            for x in range(20, 620, 4):
                for y in range(0, 40):
                    if image.pixelColor(x, y).alpha() > 200:
                        best = max(best, y)
            return best
        self.assertGreater(max(deepest(first), deepest(later)), 14)
        self.assertGreater(first.pixelColor(320, 2).alpha(), 150)

    def test_liquid_stays_close_to_the_edge(self):
        for phase in (0., .13, .29, .52, .77):
            image = render(controller("liquid", motion_phase=phase, halo_animation="music", pulse=1.))
            # Away from the side rims, nothing reaches past the glow spread.
            for x in range(48, 592, 8):
                self.assertEqual(image.pixelColor(x, 41).alpha(), 0)
                self.assertEqual(image.pixelColor(x, 420 - 42).alpha(), 0)

    def test_drops_are_glossy(self):
        # Highlights sit where a drop's surface faces the key light, so they
        # come and go as the drops travel; over a loop they must appear.
        whitest = 1.
        for phase in (.1, .31, .5, .77):
            image = render(controller("liquid", primary=QColor("#ff2d8a"), secondary=QColor("#ff2d8a"),
                                      motion_phase=phase))
            whitest = min([whitest] + [image.pixelColor(x, y).hsvSaturationF()
                                       for x in range(640) for y in range(0, 40)
                                       if image.pixelColor(x, y).alpha() > 200])
        self.assertLess(whitest, .3)

    def test_colour_mix_endpoints_keep_one_colour(self):
        image = render(controller("liquid", color_mix=100))
        pink = QColor("#ff2d8a").hsvHue()
        for x in range(30, 610, 20):
            colour = image.pixelColor(x, 3)
            if colour.alpha() > 80 and colour.hsvSaturationF() > .4:
                self.assertLess(abs(hue(colour) - pink), 8)


class SharedFieldTests(unittest.TestCase):
    def test_black_is_unlit_and_neutrals_stay_neutral(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                black = render(controller(mode, primary=QColor("#000000"), secondary=QColor("#000000")))
                self.assertFalse(any(bytes(black.constBits())))
                grey = render(controller(mode, primary=QColor("#888888"), secondary=QColor("#555555")))
                for x in range(0, 640, 9):
                    for y in (0, 3, 6, 12, 24):
                        colour = grey.pixelColor(x, y)
                        self.assertEqual(colour.red(), colour.green())
                        self.assertEqual(colour.green(), colour.blue())

    def test_brightness_sliders_dim_the_light_and_its_highlights(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                full = render(controller(mode))
                dim = render(controller(mode, primary_brightness=20, secondary_brightness=20))
                total = lambda image: sum(image.pixelColor(x, y).alpha()
                                          for x in range(0, 640, 3) for y in range(0, 40))
                self.assertLess(total(dim), total(full) * .45)

    def test_light_reach_follows_glow_spread_and_the_centre_stays_clear(self):
        for mode in MODES:
            for width in (20, 40, 90):
                with self.subTest(mode=mode, width=width):
                    image = render(controller(mode, glow_width=width, halo_animation="music", pulse=1.))
                    self.assertEqual(image.pixelColor(320, width + 2).alpha(), 0)
                    self.assertEqual(image.pixelColor(320, 210).alpha(), 0)

    def test_hi_dpi_and_fractional_scales_keep_the_same_shape(self):
        for mode in MODES:
            base = render(controller(mode))
            for dpr in (1.25, 2.):
                with self.subTest(mode=mode, dpr=dpr):
                    scaled = render(controller(mode), dpr=dpr)
                    for x, y in ((320, 3), (320, 12), (40, 210), (600, 210)):
                        a, b = base.pixelColor(x, y), scaled.pixelColor(round(x * dpr), round(y * dpr))
                        self.assertLess(abs(a.alpha() - b.alpha()), 40)

    def test_strips_join_without_a_seam(self):
        # The light is drawn in four strips; where they meet beside the corners
        # neighbouring pixels must stay continuous.
        for mode in MODES:
            image = render(controller(mode, glow_width=60))
            for x in (2, 5, 9, 634, 637):
                above, below = image.pixelColor(x, 60), image.pixelColor(x, 62)
                self.assertLess(abs(above.alpha() - below.alpha()), 12)

    def test_painter_state_and_the_controller_are_left_untouched(self):
        for mode in MODES:
            image = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            c = controller(mode)
            painter = QPainter(image)
            try:
                painter.setOpacity(.8)
                transform = painter.transform()
                paint_halo_preview(painter, QRectF(10, 10, 300, 180), c, mode, motion_phase=.2)
                self.assertEqual(painter.transform(), transform)
                self.assertEqual(painter.opacity(), .8)
                self.assertFalse(painter.hasClipping())
                self.assertEqual(painter.compositionMode(), QPainter.CompositionMode.CompositionMode_SourceOver)
            finally:
                painter.end()
            self.assertEqual(image.pixelColor(160, 100).alpha(), 0)
            self.assertGreater(image.pixelColor(160, 12).alpha(), 40)
            self.assertEqual((c.halo_mode, c.motion_phase), (mode, .31))

    def test_field_painter_ignores_other_modes(self):
        image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            self.assertFalse(paint_field_glow(painter, 64, 64, controller("orbit"), "orbit"))
        finally:
            painter.end()
        self.assertFalse(any(bytes(image.constBits())))


class SameSettingsSameBrightnessTests(unittest.TestCase):
    """Neon and Liquid share the halo settings, so they share its brightness."""

    EXISTING = ("aura", "orbit", "wave", "pulse", "prism")

    @staticmethod
    def light(mode, primary, secondary, **settings):
        import numpy as np
        c = controller(mode, primary=QColor(primary), secondary=QColor(secondary), reduced_motion=True,
                       **{"intensity": 75, **settings})
        image = render(c)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(420, 640, 4).astype(np.float32) / 255
        yy, xx = np.mgrid[0:420, 0:640]
        band = np.minimum(np.minimum(xx, 639 - xx), np.minimum(yy, 419 - yy)) < c.glow_width
        luma = pixels[..., 2] * .2126 + pixels[..., 1] * .7152 + pixels[..., 0] * .0722
        return float(luma[band].mean()), float(np.percentile(pixels[..., 3][band], 99.5))

    def test_new_lights_match_the_existing_ones_across_colours_and_settings(self):
        palettes = (("#ff2d8a", "#7a5cff"), ("#5a3a2c", "#2e2420"), ("#a9ead4", "#5498cb"))
        variants = (dict(), dict(intensity=40), dict(glow_width=70), dict(glow_opacity=20), dict(rim_width=8),
                    dict(primary_brightness=40, secondary_brightness=40))
        for primary, secondary in palettes:
            for settings in variants:
                existing = [self.light(mode, primary, secondary, **settings) for mode in self.EXISTING]
                mean = sum(luma for luma, _ in existing) / len(existing)
                peak = max(top for _, top in existing)
                for mode in MODES:
                    with self.subTest(mode=mode, palette=primary, **settings):
                        luma, top = self.light(mode, primary, secondary, **settings)
                        self.assertGreater(luma, mean * .8)
                        self.assertLess(luma, mean * 1.2)
                        self.assertLessEqual(top, peak + .02)


class FieldGPUTests(unittest.TestCase):
    """The GPU shader and the NumPy fallback draw the same light."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_gpu_and_numpy_paths_match(self):
        import numpy as np
        from halo import glow_field
        from halo.glow_field_gpu import FieldRenderer
        renderer = FieldRenderer()
        self.addCleanup(renderer.close)
        if not renderer.available:
            self.skipTest(f"No OpenGL light renderer on this PC: {renderer.reason}")
        for mode in MODES:
            with self.subTest(mode=mode):
                c = controller(mode, reduced_motion=True, intensity=75)
                a = glow_field._light_colour(c.primary, 100)
                b = glow_field._light_colour(c.secondary, 100)
                light = dict(mode=mode, w=640., h=420., band=40., phase=.31, beat=0., music=False, strength=.75,
                             a=a, b=b, mix=.6, opacity=.65, rim=3., levels=np.ones(4),
                             calibration=(glow_field.NEON_TUBE, glow_field.NEON_FILAMENT, glow_field.NEON_GLASS,
                                          glow_field.NEON_WHITE, glow_field.NEON_GLOW, glow_field.NEON_HAZE,
                                          glow_field.LIQUID_FILM, glow_field.LIQUID_BODY, glow_field.LIQUID_GLOW),
                             drops=glow_field._drops(640., 420., 40., .31, 0., a, b, .6) if mode == "liquid" else None)
                sx, sy, blocks = glow_field.strip_layout(640., 420., 40., 1.)
                gpu = [np.array(pixels, copy=True) for _, pixels in renderer.render(light, sx, sy, blocks)]
                cpu = [pixels for _, _, pixels in glow_field._cpu_images(light, 1.)]
                for fast, slow in zip(gpu, cpu):
                    difference = np.abs(fast.astype(np.int16) - slow.astype(np.int16))
                    self.assertLessEqual(np.percentile(difference, 99), 3)
                    self.assertLessEqual(difference.max(), 40)


class NeonStrikeControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-strike-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.now = 500.
        clock = patch("halo.app.time", SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)

    def test_choosing_a_light_and_changing_song_strike_the_tubes(self):
        from PySide6.QtCore import QSettings
        from halo.app import Controller
        from halo.models import Track
        from pathlib import Path
        c = Controller(QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat), offline=True)
        c.timer.stop()
        self.addCleanup(lambda: (c.close(), c.audio.thread.join(1)))
        c.requestLyrics.disconnect(c.lyrics_worker.fetch)
        self.now = 510.
        c.set("halo_mode", "neon")
        self.assertEqual(c.halo_struck_at, 510.)
        self.now = 520.
        c.accept_track(Track("Song", "Artist", "Album", 200, 30, True, True, observed_at=520.))
        self.assertEqual(c.halo_struck_at, 520.)
        # Playback updates within the same song do not strike again.
        self.now = 530.
        c.accept_track(Track("Song", "Artist", "Album", 200, 40, True, True, observed_at=530.))
        self.assertEqual(c.halo_struck_at, 520.)


if __name__ == "__main__":
    unittest.main()
