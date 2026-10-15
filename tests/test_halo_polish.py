"""Rendered contracts for palette contrast, geometry and continuous motion."""
import math
from types import SimpleNamespace
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from halo.glow import HALO_MODES, balanced_glow_colour, paint_edge_glow


def controller(**changes):
    values = dict(primary=QColor("#000000"), secondary=QColor("#005dff"),
                  intensity=100, pulse=0., glow_width=65, rim_width=3,
                  glow_opacity=65, primary_brightness=100, secondary_brightness=100,
                  color_mix=60, halo_mode="orbit", halo_animation="flow",
                  motion_phase=0., motion_time=0., motion_speed=45, reduced_motion=False)
    values.update(changes)
    return SimpleNamespace(**values)


def render(c=None, w=800, h=600, dpr=1.):
    image = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        paint_edge_glow(painter, w, h, c or controller())
    finally:
        painter.end()
    return image


def pixels(image):
    return bytes(image.constBits())


class HaloPolishTests(unittest.TestCase):
    def test_palette_helper_preserves_dark_saturated_and_neutral_colours(self):
        for value in ("#000000", "#124079", "#ef227a", "#005dff", "#777777"):
            self.assertEqual(balanced_glow_colour(QColor(value)).name(), value)

    def test_black_is_unlit_in_every_mode(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                image = render(controller(halo_mode=mode, secondary=QColor("#000000"), motion_phase=.23))
                self.assertFalse(any(pixels(image)))

    def test_saturated_blue_survives_the_rim_without_white_admixture(self):
        image = render(controller(halo_mode="aura", primary=QColor("#005dff")))
        colour = image.pixelColor(400, 1)
        self.assertEqual(colour.alpha(), 255)
        self.assertEqual(colour.red(), 0)
        self.assertAlmostEqual(colour.green(), 93, delta=1)
        self.assertEqual(colour.blue(), 255)

    def test_grey_never_gains_an_invented_red_hue(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                image = render(controller(halo_mode=mode, primary=QColor("#666666"),
                                           secondary=QColor("#aaaaaa"), motion_phase=.23))
                for point in ((200, 1), (798, 200), (500, 598), (1, 400)):
                    colour = image.pixelColor(*point)
                    self.assertEqual(colour.red(), colour.green())
                    self.assertEqual(colour.green(), colour.blue())

    def test_each_colour_has_its_own_brightness(self):
        primary_on = render(controller(halo_mode="aura", primary=QColor("#ff2200"),
                                       secondary_brightness=0))
        secondary_on = render(controller(halo_mode="aura", primary=QColor("#ff2200"),
                                         primary_brightness=0))
        self.assertGreater(primary_on.pixelColor(40, 1).alpha(), 200)
        self.assertEqual(secondary_on.pixelColor(40, 1).alpha(), 0)
        self.assertEqual(primary_on.pixelColor(760, 598).alpha(), 0)
        self.assertGreater(secondary_on.pixelColor(760, 598).alpha(), 200)

    def test_colour_mix_changes_the_lit_share_of_the_perimeter(self):
        mostly_blue = render(controller(color_mix=20))
        mostly_black = render(controller(color_mix=80))
        def border_energy(image):
            return (sum(image.pixelColor(x, y).alpha() for x in range(20, 780) for y in (1, 598))
                    + sum(image.pixelColor(x, y).alpha() for y in range(20, 580) for x in (1, 798)))
        self.assertGreater(border_energy(mostly_blue), border_energy(mostly_black) * 2)

    def test_rim_thickness_and_glow_spread_are_independent(self):
        blue = QColor("#005dff")
        thin = render(controller(primary=blue, halo_mode="aura", rim_width=2, glow_opacity=0))
        thick = render(controller(primary=blue, halo_mode="aura", rim_width=9, glow_opacity=0))
        self.assertEqual(thin.pixelColor(400, 5).alpha(), 0)
        self.assertEqual(thick.pixelColor(400, 5).alpha(), 255)
        narrow = render(controller(primary=blue, halo_mode="aura", glow_width=30))
        broad = render(controller(primary=blue, halo_mode="aura", glow_width=90))
        self.assertEqual(narrow.pixelColor(400, 40).alpha(), 0)
        self.assertGreater(broad.pixelColor(400, 40).alpha(), 20)
        self.assertEqual(narrow.pixelColor(400, 1), broad.pixelColor(400, 1))

    def test_glow_opacity_does_not_weaken_the_crisp_rim(self):
        blue = QColor("#005dff")
        crisp = render(controller(primary=blue, halo_mode="aura", glow_opacity=0))
        glowing = render(controller(primary=blue, halo_mode="aura", glow_opacity=100))
        self.assertEqual(crisp.pixelColor(400, 1), glowing.pixelColor(400, 1))
        self.assertEqual(crisp.pixelColor(400, 18).alpha(), 0)
        self.assertGreater(glowing.pixelColor(400, 18).alpha(), 100)

    def test_controller_phase_is_not_rescaled_when_speed_changes(self):
        first = render(controller(motion_phase=.23, motion_speed=0, motion_time=0.))
        second = render(controller(motion_phase=.23, motion_speed=100, motion_time=500.))
        self.assertEqual(pixels(first), pixels(second))

    def test_still_ignores_time_phase_and_audio_in_all_modes(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                first = render(controller(halo_mode=mode, halo_animation="still", motion_phase=.13, pulse=0.))
                later = render(controller(halo_mode=mode, halo_animation="still", motion_phase=.71, pulse=1.))
                self.assertEqual(pixels(first), pixels(later))

    def test_reduced_motion_keeps_the_frozen_controller_phase(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                normal = render(controller(halo_mode=mode, motion_phase=.23))
                frozen = render(controller(halo_mode=mode, motion_phase=.23, reduced_motion=True,
                                            motion_time=40., pulse=1.))
                self.assertEqual(pixels(normal), pixels(frozen))

    def test_light_travels_equal_physical_distances_on_different_edges(self):
        r, w, h = 16., 800., 600.
        arc = math.pi * r / 2
        length = 2 * (w + h - 4 * r) + 4 * arc
        top_distance = 200.5 - r
        right_distance = w - 2 * r + arc + 200.5 - r
        phase = top_distance / length - .30
        top = render(controller(motion_phase=phase))
        right = render(controller(motion_phase=phase + (right_distance - top_distance) / length))
        top_colour, right_colour = top.pixelColor(200, 1), right.pixelColor(798, 200)
        self.assertGreater(top_colour.alpha(), 70)
        self.assertLess(top_colour.alpha(), 180)
        self.assertAlmostEqual(top_colour.alpha(), right_colour.alpha(), delta=3)
        self.assertAlmostEqual(top_colour.green(), right_colour.green(), delta=2)

    def test_corner_brushes_join_the_straight_rim_at_fractional_scales(self):
        for dpr in (1., 1.25, 2.):
            image = render(controller(motion_phase=.17), dpr=dpr)
            for first, second in (((782, 1), (785, 1)), ((798, 582), (798, 585)),
                                  ((18, 598), (15, 598)), ((1, 18), (1, 15))):
                a = image.pixelColor(round(first[0] * dpr), round(first[1] * dpr))
                b = image.pixelColor(round(second[0] * dpr), round(second[1] * dpr))
                self.assertLessEqual(abs(a.alpha() - b.alpha()), 8)
                self.assertLessEqual(abs(a.blue() * a.alpha() - b.blue() * b.alpha()) / 255, 8)

    def test_4k_transition_has_no_coarse_coordinate_bands(self):
        image = render(controller(motion_phase=0., glow_opacity=0), 3840, 2160)
        levels = [image.pixelColor(x, 1).alpha() for x in range(40, 3800)]
        self.assertGreater(max(levels) - min(levels), 100)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(levels, levels[1:])), 3)

    def test_corner_spill_has_no_diagonal_partition_crease(self):
        image = render(controller(primary=QColor("#0a0d14")), 870, 696)
        for depth in (20, 30, 40):
            # Mirror points across the inward diagonal have equal geometric
            # depth. Their light must change gradually, not switch brushes.
            a = image.pixelColor(870 - depth, depth - 1)
            b = image.pixelColor(871 - depth, depth)
            for first, second in zip(a.getRgb()[:3], b.getRgb()[:3]):
                self.assertLessEqual(abs(first * a.alpha() - second * b.alpha()) / 255, 3)


if __name__ == "__main__":
    unittest.main()
