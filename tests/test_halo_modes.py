"""Rendered checks for the native halo modes and their accessibility controls."""
import unittest
from types import SimpleNamespace

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from halo.glow import HALO_MODES, paint_edge_glow, paint_halo_preview


def render(mode="orbit", seconds=0., speed=45, reduced=False, intensity=100,
           pulse=0., dpr=1., width=52, animation="flow"):
    image = QImage(round(640 * dpr), round(420 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    controller = SimpleNamespace(
        primary=QColor("#ef227a"), secondary=QColor("#124079"),
        intensity=intensity, pulse=pulse, glow_width=width,
        halo_mode=mode, motion_time=seconds, motion_speed=speed,
        reduced_motion=reduced,
        halo_animation=animation,
    )
    painter = QPainter(image)
    try:
        paint_edge_glow(painter, 640, 420, controller)
    finally:
        painter.end()
    return image


def fingerprint(image):
    return bytes(image.constBits())


class HaloModeTests(unittest.TestCase):
    def test_each_animated_mode_changes_the_rendered_rim(self):
        for mode, _, _ in HALO_MODES:
            if mode == "aura":
                continue
            with self.subTest(mode=mode):
                initial, later = render(mode), render(mode, seconds=4.)
                self.assertNotEqual(fingerprint(initial), fingerprint(later))
                # Flow moves actual colour, not just the entire rim's opacity.
                colours = [(320, 8), (631, 210), (320, 411), (8, 210)]
                self.assertTrue(any(initial.pixelColor(x, y).rgb()
                                    != later.pixelColor(x, y).rgb() for x, y in colours))

    def test_modes_have_distinct_visual_output(self):
        frames = [fingerprint(render(mode, seconds=2.7)) for mode, _, _ in HALO_MODES]
        self.assertEqual(len(set(frames)), len(HALO_MODES))

    def test_aura_and_unknown_mode_keep_a_compatible_static_glow(self):
        aura = fingerprint(render("aura"))
        self.assertEqual(aura, fingerprint(render("aura", seconds=15.)))
        self.assertEqual(aura, fingerprint(render("unknown")))

    def test_reduced_motion_and_zero_speed_freeze_every_animated_mode(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(fingerprint(render(mode, seconds=0., reduced=True)),
                                 fingerprint(render(mode, seconds=11., reduced=True)))
                self.assertEqual(fingerprint(render(mode, seconds=0., speed=0)),
                                 fingerprint(render(mode, seconds=11., speed=0)))

    def test_motion_speed_changes_flow_without_changing_mask_geometry(self):
        for mode in ("orbit", "wave", "prism"):
            with self.subTest(mode=mode):
                slow, fast = render(mode, seconds=3., speed=20), render(mode, seconds=3., speed=85)
                self.assertNotEqual(fingerprint(slow), fingerprint(fast))
                for frame in (slow, fast):
                    self.assertEqual(frame.pixelColor(320, 53).alpha(), 0)
                    self.assertGreater(frame.pixelColor(320, 1).alpha(), 0)

    def test_centre_and_beyond_the_band_stay_transparent_at_display_scales(self):
        for dpr in (1., 1.25, 1.5, 2.):
            for mode, _, _ in HALO_MODES:
                with self.subTest(dpr=dpr, mode=mode):
                    image = render(mode, seconds=1.8, dpr=dpr)
                    for x, y in ((320, 210), (320, 54), (54, 210), (580, 210)):
                        self.assertEqual(image.pixelColor(round(x * dpr), round(y * dpr)).alpha(), 0)

    def test_intensity_audio_and_no_corner_hotspot(self):
        for mode, _, _ in HALO_MODES:
            with self.subTest(mode=mode):
                off, low, quiet, loud = (render(mode, intensity=0), render(mode, intensity=25),
                                         render(mode, animation="music"), render(mode, pulse=1., animation="music"))
                self.assertEqual(off.pixelColor(320, 8).alpha(), 0)
                self.assertLess(low.pixelColor(320, 8).alpha(), quiet.pixelColor(320, 8).alpha())
                self.assertGreater(loud.pixelColor(320, 8).alpha(), quiet.pixelColor(320, 8).alpha())
                self.assertGreater(quiet.pixelColor(10, 10).alpha(), 0)
                # Spatial highlights can vary, but the corner never stacks two glows.
                self.assertLessEqual(quiet.pixelColor(10, 10).alpha(), 205)

    def test_pulse_blooms_inward_while_its_centre_stays_clear(self):
        narrow, broad = render("pulse", seconds=0.), render("pulse", seconds=4.36)
        self.assertGreater(broad.pixelColor(320, 28).alpha(), narrow.pixelColor(320, 28).alpha() * 2)
        self.assertEqual(broad.pixelColor(320, 210).alpha(), 0)

    def test_thumbnail_uses_the_same_modes_and_restores_painter_state(self):
        image = QImage(300, 160, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        controller = SimpleNamespace(primary=QColor("#ef227a"), secondary=QColor("#124079"),
                                     halo_mode="orbit", motion_time=0., intensity=100, pulse=.2)
        painter = QPainter(image)
        try:
            painter.setOpacity(.7)
            transform = painter.transform()
            paint_halo_preview(painter, QRectF(20, 20, 200, 110), controller, "wave", 2.)
            self.assertEqual(painter.transform(), transform)
            self.assertEqual(painter.opacity(), .7)
        finally:
            painter.end()
        self.assertGreater(image.pixelColor(120, 24).alpha(), 50)
        self.assertEqual(image.pixelColor(120, 75).alpha(), 0)
        self.assertEqual(controller.halo_mode, "orbit")
        self.assertEqual(controller.motion_time, 0.)


if __name__ == "__main__":
    unittest.main()
