"""Momentum: each beat pushes the halo's colours around the rim, then they coast."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from halo.app import Controller
from halo.glow import HALO_MODES, paint_edge_glow, paint_halo_preview
from halo.models import Track
from halo.momentum import Momentum

TICK = .016


def beat_accent(t, spacing):
    """Halo's detector output for a clean beat: a hit that decays over 80 ms."""
    age = t - math.floor(t / spacing) * spacing
    return math.exp(-age / .08)


def run(momentum, seconds, accent=lambda t: 0., speed=45):
    """Step the model like the controller's 16 ms tick; return laps travelled and rates seen."""
    laps, rates, t = 0., [], 0.
    while t < seconds - 1e-9:
        momentum.step(TICK, accent(t))
        rate = momentum.rate(speed)
        laps += rate * TICK
        rates.append(rate)
        t += TICK
    return laps, rates


class MomentumModelTests(unittest.TestCase):
    def test_without_beats_it_crawls_at_lumns_rest_speed(self):
        laps, rates = run(Momentum(), 2.)
        self.assertAlmostEqual(rates[-1], .07, places=6)
        self.assertAlmostEqual(laps, .14, places=3)

    def test_motion_speed_scales_the_whole_motion(self):
        self.assertAlmostEqual(Momentum().rate(90), .14, places=6)
        self.assertEqual(Momentum().rate(0), 0.)

    def test_a_beat_pushes_hard_then_coasts_back_to_rest(self):
        momentum = Momentum()
        _, rates = run(momentum, 1., accent=lambda t: math.exp(-t / .08))
        self.assertGreater(max(rates[:10]), .75)
        self.assertLess(rates[-1], .1)

    def test_hits_closer_than_the_gap_count_as_one_push(self):
        def two_hits(gap):
            return lambda t: max(math.exp(-t / .08), math.exp(-(t - gap) / .08) if t >= gap else 0.)
        one, _ = run(Momentum(), 1.2, accent=lambda t: math.exp(-t / .08))
        hat, _ = run(Momentum(), 1.2, accent=two_hits(.13))
        second_beat, _ = run(Momentum(), 1.2, accent=two_hits(.5))
        self.assertAlmostEqual(hat, one, places=6)
        self.assertGreater(second_beat, one * 1.3)

    def test_a_steady_beat_averages_lumns_measured_speed(self):
        # Lumn's demo surged about every 0.4 s and averaged 0.42 to 0.46 laps a second.
        laps, rates = run(Momentum(), 8., accent=lambda t: beat_accent(t, .4))
        self.assertGreater(laps / 8., .38)
        self.assertLess(laps / 8., .52)
        self.assertGreater(max(rates), .8)
        self.assertLess(min(rates[60:]), .12)


def light(mode="orbit", **changes):
    values = dict(intensity=80, pulse=0., primary=QColor("#ff2d8a"), secondary=QColor("#ff2d8a"),
                  glow_width=40, rim_width=3, glow_opacity=65, primary_brightness=100,
                  secondary_brightness=100, color_mix=60, halo_mode=mode, halo_animation="momentum",
                  motion_phase=.3, surge=0., reduced_motion=False)
    values.update(changes)
    return SimpleNamespace(**values)


def render(c, w=480, h=300):
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        paint_edge_glow(painter, w, h, c)
    finally:
        painter.end()
    return image


def total_light(image):
    bits = image.constBits()
    data = memoryview(bits).cast("B")
    return sum(data[i + 3] for i in range(0, len(data), 4 * 7))


def lit_top_edge(image):
    return sum(image.pixelColor(x, 1).alpha() > 80 for x in range(image.width()))


class MomentumGlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_push_lifts_every_light_to_full_without_blooming(self):
        # Each beat must show in the light, not only in the motion: without
        # this lift Momentum read as flat (a beat changed the light by ~1%).
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                flow = total_light(render(light(mode, halo_animation="flow")))
                rest = total_light(render(light(mode, surge=0.)))
                push = total_light(render(light(mode, surge=1.)))
                self.assertGreater(rest, 0)
                self.assertAlmostEqual(push / flow, 1., delta=.02)
                self.assertGreater(push / rest, 1.06)
                self.assertLess(push / rest, 1.12)

    def test_music_sync_still_flashes_far_more_than_momentum(self):
        quiet = total_light(render(light(halo_animation="music", pulse=0.)))
        hit = total_light(render(light(halo_animation="music", pulse=1.)))
        self.assertGreater(hit / quiet, 2.)

    def test_a_push_widens_the_lit_colour(self):
        # With the primary switched off, only a wider lit colour can add light.
        colours = dict(primary=QColor("#3a6bff"), primary_brightness=0, secondary=QColor("#0a5cff"))
        for mode in ("orbit", "neon"):
            with self.subTest(mode=mode):
                rest = total_light(render(light(mode, surge=0., **colours)))
                push = total_light(render(light(mode, surge=1., **colours)))
                self.assertGreater(push / rest, 1.05)
        rest = lit_top_edge(render(light(surge=0., **colours)))
        push = lit_top_edge(render(light(surge=1., **colours)))
        self.assertGreater(push, rest + 40)

    def test_reduced_motion_holds_the_light_at_rest(self):
        moving = render(light(surge=1., reduced_motion=True))
        rest = render(light(surge=0.))
        self.assertEqual(total_light(moving), total_light(rest))

    def test_mode_previews_follow_the_push(self):
        def preview(surge):
            image = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                paint_halo_preview(painter, QRectF(0, 0, 320, 200), light(surge=surge, **colours), "orbit",
                                   motion_phase=.3)
            finally:
                painter.end()
            return total_light(image)
        colours = dict(primary=QColor("#3a6bff"), primary_brightness=0, secondary=QColor("#0a5cff"))
        self.assertGreater(preview(1.) / preview(0.), 1.05)


class MomentumControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-momentum-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.
        clock = patch("halo.app.time", SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for c in self.controllers:
            c.close()
            c.audio.thread.join(1)

    def controller(self, values=None):
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        for name, value in (values or {}).items():
            settings.setValue(name, value)
        c = Controller(settings, offline=True)
        c.timer.stop()
        self.controllers.append(c)
        return c

    def playing(self, values=None):
        c = self.controller(values)
        # Supply deterministic detector output without opening the audio device.
        c.audio.close()
        c.audio.thread.join(1)
        c.track = Track(playing=True, connected=True, observed_at=self.now)
        return c

    def test_momentum_is_a_saved_animation_that_listens_to_audio(self):
        c = self.controller()
        self.assertEqual(c.audio.accent, 0.)
        c.set("halo_animation", "momentum")
        self.assertTrue(c.reactive)
        c.set("reactive", True)
        self.assertEqual(c.halo_animation, "momentum")
        c.settings.sync()
        restored = self.controller()
        self.assertEqual(restored.halo_animation, "momentum")
        self.assertTrue(restored.reactive)
        restored.set("reactive", False)
        self.assertEqual(restored.halo_animation, "flow")

    def test_beats_push_the_rim_and_quiet_lets_it_crawl(self):
        c = self.playing({"halo_animation": "momentum"})
        start = c.motion_phase
        for _ in range(30):
            self.now += TICK
            c.tick()
        self.assertTrue(c.audio.enabled)
        crawl = c.motion_phase - start
        self.assertAlmostEqual(crawl, 30 * TICK * .07, places=4)
        start, hit_at = c.motion_phase, self.now
        for _ in range(30):
            self.now += TICK
            c.audio.accent = math.exp(-(self.now - hit_at) / .08)
            c.tick()
        self.assertGreater(c.motion_phase - start, crawl * 3)
        self.assertGreater(c.surge, 0.)

    def test_reduced_motion_freezes_momentum(self):
        c = self.playing({"halo_animation": "momentum", "reduced_motion": True})
        start = c.motion_phase
        c.audio.accent = 1.
        for _ in range(10):
            self.now += TICK
            c.tick()
        self.assertEqual(c.motion_phase, start)
        self.assertEqual(c.surge, 0.)


class MomentumControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_animation_list_offers_momentum(self):
        from test_color_controls import SettingsController
        from halo.color_controls import LightControls
        c = SettingsController()
        controls = LightControls(c)
        index = controls.animation_select.findData("momentum")
        self.assertGreaterEqual(index, 0)
        self.assertEqual(controls.animation_select.itemText(index), "Momentum")
        controls.animation_select.setCurrentIndex(index)
        self.assertEqual(c.writes[-1], ("halo_animation", "momentum"))

    def test_the_settings_preview_pushes_on_a_sample_beat_without_music(self):
        from halo.settings_ui import PreviewController
        now = [50.]
        source = SimpleNamespace(lyrics=SimpleNamespace(lines=[]), track=Track(), reduced_motion=False,
                                 halo_animation="momentum", motion_speed=45, pulse=0., surge=0., position=0.)
        with patch("halo.settings_ui.time", SimpleNamespace(monotonic=lambda: now[0])):
            proxy = PreviewController(source)
            surges = []
            for _ in range(125):
                now[0] += TICK
                proxy.advance()
                surges.append(proxy.surge)
        # Two seconds of a sample beat travel well beyond the 0.14 laps of a crawl.
        self.assertGreater(proxy.motion_phase, .5)
        self.assertGreater(max(surges), .5)
        self.assertLess(min(surges[40:]), .2)


if __name__ == "__main__":
    unittest.main()
