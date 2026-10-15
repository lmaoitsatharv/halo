import unittest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from halo.palette import artwork_colours, PaletteTransition, readable_accent, envelope, valid_colour


class PaletteTests(unittest.TestCase):
    def image_data(self, primary, secondary=None):
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        image.fill(QColor(primary))
        if secondary:
            for y in range(32):
                for x in range(20, 32):
                    image.setPixelColor(x, y, QColor(secondary))
        data = QBuffer()
        data.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(data, "PNG")
        return bytes(data.data())

    def test_artwork_preserves_real_dark_and_saturated_colours(self):
        primary, secondary = artwork_colours(self.image_data("#0a0d14", "#005dff"))
        self.assertEqual(primary.name(), "#0a0d14")
        self.assertEqual(secondary.name(), "#005dff")

    def test_monochrome_and_transparent_artwork_do_not_invent_a_hue(self):
        primary, secondary = artwork_colours(self.image_data("#343434"))
        self.assertEqual(primary.name(), "#343434")
        self.assertEqual(secondary.name(), "#343434")
        self.assertTrue(all(colour.isValid() for colour in artwork_colours(b"not an image")))

    def test_readable_ui_accent_does_not_mutate_raw_halo_colour(self):
        raw = QColor("#000000")
        accent = readable_accent(raw, QColor("#005dff"))
        self.assertEqual(raw.name(), "#000000")
        self.assertGreater(accent.valueF(), .89)

    def test_palette_fade_has_exact_endpoints_and_no_abrupt_start(self):
        fade = PaletteTransition(QColor("#000000"), QColor("#005dff"), now=10)
        fade.retarget(QColor("#ef227a"), QColor("#13d6a5"), 11)
        self.assertEqual(fade.at(11)[0].name(), "#000000")
        middle = fade.at(11.45)
        self.assertNotEqual(middle[0].name(), "#000000")
        self.assertNotEqual(middle[0].name(), "#ef227a")
        self.assertEqual([c.name() for c in fade.at(12)], ["#ef227a", "#13d6a5"])

    def test_interrupted_palette_fade_starts_at_the_visible_colour(self):
        fade = PaletteTransition(QColor("#000000"), QColor("#005dff"))
        fade.retarget(QColor("#ef227a"), QColor("#13d6a5"), 1)
        visible = fade.at(1.4)
        fade.retarget(QColor("#ff9900"), QColor("#5700ff"), 1.4)
        self.assertEqual(visible, fade.at(1.4))

    def test_repeated_same_target_does_not_restart_transition(self):
        fade = PaletteTransition(QColor("#000000"), QColor("#005dff"))
        fade.retarget(QColor("#ef227a"), QColor("#13d6a5"), 1)
        fade.retarget(QColor("#ef227a"), QColor("#13d6a5"), 1.4)
        self.assertEqual(fade.started, 1)
        self.assertEqual(fade.at(2)[0].name(), "#ef227a")

    def test_output_envelope_is_independent_of_frame_rate(self):
        for target, initial in ((1., 0.), (0., 1.)):
            outcomes = []
            for fps in (24, 30, 60, 120):
                value = initial
                for _ in range(fps):
                    value = envelope(value, target, 1 / fps)
                outcomes.append(value)
            for value in outcomes:
                self.assertAlmostEqual(value, outcomes[0], places=12)
        self.assertGreater(envelope(0., 1., .05), .6)
        self.assertGreater(envelope(1., 0., .05), .8)

    def test_invalid_custom_colour_recovers_without_changing_valid_black(self):
        self.assertEqual(valid_colour("invalid", "#005dff").name(), "#005dff")
        self.assertEqual(valid_colour("#000000", "#005dff").name(), "#000000")


if __name__ == "__main__":
    unittest.main()
