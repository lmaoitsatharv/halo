"""Rendered contracts for optional light choreographies, using native Qt."""
import hashlib
import math
from types import SimpleNamespace
import unittest

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from halo.glow import HALO_MODES, _colour_function, paint_edge_glow, paint_halo_preview
from halo.glow_extras import EXTRA_HALO_MODES, _meteor_heads, extra_colour_function, extra_spill


def controller(mode="aurora", **changes):
    values = dict(primary=QColor("#eaa390"), secondary=QColor("#637bd4"),
                  intensity=100, pulse=0., glow_width=58, rim_width=3,
                  glow_opacity=80, primary_brightness=100, secondary_brightness=100,
                  color_mix=60, halo_mode=mode, halo_animation="flow",
                  motion_phase=.17, motion_time=0., motion_speed=45, reduced_motion=False)
    values.update(changes)
    return SimpleNamespace(**values)


def render(c, width=640, height=420, dpr=1.):
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        paint_edge_glow(painter, width, height, c)
    finally:
        painter.end()
    return image


def fingerprint(image):
    return hashlib.sha256(image.constBits()).hexdigest()


def alpha_sum(image):
    return sum(image.pixelColor(x, y).alpha()
               for y in (1, 8, 24, image.height() - 9)
               for x in range(20, image.width() - 20, 6))


class ExtraGlowTests(unittest.TestCase):
    def test_original_catalogue_order_is_preserved_and_extras_are_unique(self):
        self.assertEqual([key for key, _, _ in HALO_MODES[:5]],
                         ["aura", "orbit", "wave", "pulse", "prism"])
        self.assertEqual(HALO_MODES[-3:], EXTRA_HALO_MODES)
        self.assertEqual(len({key for key, _, _ in HALO_MODES}), len(HALO_MODES))

    def test_extra_helpers_do_not_intercept_original_modes(self):
        for mode, _, _ in HALO_MODES[:5]:
            self.assertIsNone(extra_colour_function(mode, .1, (1., 0., 0.), (0., 0., 1.), .6))
            self.assertIsNone(extra_spill(mode, .1, .2, True))

    def test_patterns_are_different_even_in_one_colour(self):
        for phase in (0., .17, .53):
            with self.subTest(phase=phase):
                frames = [fingerprint(render(controller(mode, primary=QColor("#ccbbaa"),
                                                        secondary=QColor("#ccbbaa"), motion_phase=phase)))
                          for mode, _, _ in EXTRA_HALO_MODES]
                self.assertEqual(len(set(frames)), len(frames))

    def test_motion_changes_spatial_distribution_not_only_global_opacity(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                first = _colour_function(controller(mode), mode, .05)
                later = _colour_function(controller(mode), mode, .25)
                before = [first(i / 96).alphaF() for i in range(96)]
                after = [later(i / 96).alphaF() for i in range(96)]
                ratios = [b / a for a, b in zip(before, after) if a > .03]
                self.assertGreater(max(ratios) - min(ratios), .25)
                self.assertNotEqual(fingerprint(render(controller(mode, motion_phase=.05))),
                                    fingerprint(render(controller(mode, motion_phase=.25))))

    def test_loop_seam_has_identical_colour_and_light(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                sample = _colour_function(controller(mode), mode, .23)
                self.assertEqual(sample(0.), sample(1.))
                self.assertEqual(sample(.125), sample(1.125))

    def test_animation_phase_wrap_has_no_colour_or_brightness_jump(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                start = _colour_function(controller(mode), mode, 0.)
                end = _colour_function(controller(mode), mode, 1. - 1e-7)
                for i in range(96):
                    self.assertLess(max(abs(a - b) for a, b in zip(start(i / 96).getRgbF(),
                                                                  end(i / 96).getRgbF())), .001)

    def test_meteor_heads_remain_separated_through_the_whole_orbit(self):
        for phase in [i / 240 for i in range(240)]:
            heads = sorted(_meteor_heads(phase))
            separations = [(heads[(i + 1) % 3] - heads[i]) % 1. for i in range(3)]
            self.assertGreater(min(separations), .27)

    def test_meteor_has_visible_dark_breaks_between_its_light_trails(self):
        c = controller("meteor", primary=QColor("#ffffff"), secondary=QColor("#ffffff"))
        for phase in (0., .17, .39, .71):
            sample = _colour_function(c, "meteor", phase)
            levels = [sample(i / 240).alphaF() for i in range(240)]
            self.assertGreater(max(levels), .6)
            self.assertLess(min(levels), .07)
            self.assertGreater(sum(level < .12 for level in levels), len(levels) * .35)

    def test_black_stays_transparent_and_neutrals_keep_their_hue(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                black = render(controller(mode, primary=QColor("#000000"), secondary=QColor("#000000")))
                self.assertFalse(any(bytes(black.constBits())))
                grey = _colour_function(controller(mode, primary=QColor("#888888"),
                                                   secondary=QColor("#444444")), mode, .2)
                for i in range(32):
                    color = grey(i / 32)
                    self.assertEqual(color.red(), color.green())
                    self.assertEqual(color.green(), color.blue())

    def test_palette_endpoints_and_brightness_controls_are_respected(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                blue = controller(mode, primary=QColor("#005dff"), secondary=QColor("#cc1100"), color_mix=100)
                sample = _colour_function(blue, mode, .4)
                for i in range(32):
                    color = sample(i / 32)
                    self.assertEqual(color.red(), 0)
                    self.assertAlmostEqual(color.green() / max(1, color.blue()), 93 / 255, delta=.007)
                dim = render(controller(mode, primary_brightness=20, secondary_brightness=20))
                full = render(controller(mode))
                self.assertLess(alpha_sum(dim), alpha_sum(full) * .25)

    def test_audio_blooms_grow_inside_the_band_without_filling_the_centre(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                quiet = render(controller(mode, halo_animation="music", pulse=0))
                hit = render(controller(mode, halo_animation="music", pulse=1))
                self.assertGreater(alpha_sum(hit), alpha_sum(quiet) * 3)
                self.assertEqual(hit.pixelColor(320, 210).alpha(), 0)
                self.assertEqual(hit.pixelColor(320, 60).alpha(), 0)

    def test_pause_reduced_motion_and_still_keep_the_shared_frozen_phase(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            with self.subTest(mode=mode):
                initial = render(controller(mode))
                self.assertEqual(initial, render(controller(mode, motion_time=500)))
                self.assertEqual(initial, render(controller(mode, reduced_motion=True, motion_time=500)))
                self.assertEqual(render(controller(mode, halo_animation="still", motion_phase=.1)),
                                 render(controller(mode, halo_animation="still", motion_phase=.9, pulse=1)))

    def test_spill_profiles_stay_finite_bounded_and_geometry_cacheable(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            for phase in (0., .2, .5, .9):
                for beat in (0., .3, 1.):
                    width, tight = extra_spill(mode, phase, beat, True)
                    self.assertTrue(math.isfinite(width) and math.isfinite(tight))
                    self.assertGreaterEqual(width, 0.)
                    self.assertLessEqual(width, 1.)
                    self.assertIn(tight, (.42, .58))

    def test_scaled_displays_keep_the_centre_and_outside_band_clear(self):
        for mode, _, _ in EXTRA_HALO_MODES:
            for dpr in (1., 1.25, 2.):
                image = render(controller(mode), dpr=dpr)
                for x, y in ((320, 210), (60, 210), (320, 60), (580, 210)):
                    self.assertEqual(image.pixelColor(round(x * dpr), round(y * dpr)).alpha(), 0)

    def test_live_preview_uses_extra_mode_and_preserves_the_callers_state(self):
        hashes = set()
        c = controller("aura")
        for mode, _, _ in EXTRA_HALO_MODES:
            image = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                painter.setOpacity(.8)
                original = painter.transform()
                paint_halo_preview(painter, QRectF(10, 10, 300, 180), c, mode, motion_phase=.17)
                self.assertEqual(painter.transform(), original)
                self.assertEqual(painter.opacity(), .8)
            finally:
                painter.end()
            self.assertEqual(image.pixelColor(160, 100).alpha(), 0)
            hashes.add(fingerprint(image))
        self.assertEqual(len(hashes), 3)
        self.assertEqual(c.halo_mode, "aura")


if __name__ == "__main__":
    unittest.main()
