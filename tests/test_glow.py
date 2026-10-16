import unittest
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from halo.glow import paint_edge_glow


def render(intensity=100, pulse=0, primary="#ef227a", secondary="#124079", width=60, dpr=1, animation=None):
    image = QImage(round(800 * dpr), round(600 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        controller = SimpleNamespace(intensity=intensity, pulse=pulse,
                        primary=QColor(primary), secondary=QColor(secondary), glow_width=width)
        if animation is not None:
            controller.halo_animation = animation
        paint_edge_glow(painter, 800, 600, controller)
    finally:
        painter.end()
    return image


def brightness(pixel):
    r, g, b, a = pixel.getRgbF()
    return (.2126 * r + .7152 * g + .0722 * b) * a


class GlowTests(unittest.TestCase):
    def test_quiet_audio_keeps_a_crisp_coloured_rim(self):
        image = render()
        self.assertGreater(image.pixelColor(400, 1).alpha(), 220)
        self.assertGreater(image.pixelColor(400, 1).red(), image.pixelColor(400, 1).green() * 3)

    def test_identical_colours_have_uniform_geometry_across_four_sides(self):
        image = render(primary="#ef227a", secondary="#ef227a")
        pixels = [image.pixelColor(x, y) for x, y in [(400, 8), (400, 591), (8, 300), (791, 300)]]
        levels = [brightness(pixel) for pixel in pixels]
        self.assertLess(max(levels) - min(levels), .015)

    def test_corner_has_no_double_strength_hotspot(self):
        image = render(primary="#a8efc7", secondary="#a8efc7")
        edge = image.pixelColor(400, 8).alpha()
        corner = image.pixelColor(10, 10).alpha()
        self.assertLessEqual(corner, edge + 15)
        self.assertGreater(corner, 80)

    def test_soft_fade_and_transparent_centre(self):
        image = render()
        alphas = [image.pixelColor(400, y).alpha() for y in [8, 20, 35, 50, 65]]
        self.assertEqual(alphas, sorted(alphas, reverse=True))
        self.assertEqual(image.pixelColor(400, 300).alpha(), 0)
        self.assertEqual(alphas[-1], 0)

    def test_intensity_and_pulse_controls_remain_effective(self):
        off, low = render(intensity=0), render(intensity=25, animation="music")
        quiet, loud = render(animation="music"), render(animation="music", pulse=1)
        self.assertEqual(off.pixelColor(400, 8).alpha(), 0)
        self.assertLess(low.pixelColor(400, 8).alpha(), quiet.pixelColor(400, 8).alpha())
        self.assertGreater(loud.pixelColor(400, 8).alpha(), quiet.pixelColor(400, 8).alpha())

    def test_scaled_display_retains_even_edges(self):
        for dpr in (1.25, 1.5, 2):
            with self.subTest(display_scale=dpr):
                image = render(dpr=dpr, primary="#ef227a", secondary="#ef227a")
                depth = round(8 * dpr)
                pixels = [image.pixelColor(x, y) for x, y in
                          [(image.width() // 2, depth), (image.width() // 2, image.height() - 1 - depth),
                           (depth, image.height() // 2), (image.width() - 1 - depth, image.height() // 2)]]
                self.assertLess(max(map(brightness, pixels)) - min(map(brightness, pixels)), .015)


if __name__ == "__main__":
    unittest.main()
