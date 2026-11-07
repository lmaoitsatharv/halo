"""Album colours for the halo light: vivid tones from the cover, bright enough to light the room."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QBuffer, QIODevice, QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from halo.palette import artwork_light_colours, readable_accent

FLOOR = .85


def cover(*regions):
    """A 32 x 32 cover: each region is (colour, number of columns), filled left to right."""
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    x = 0
    for colour, columns in regions:
        for column in range(x, min(32, x + columns)):
            for y in range(32):
                image.setPixelColor(column, y, QColor(colour))
        x += columns
    data = QBuffer()
    data.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(data, "PNG")
    return bytes(data.data())


def hue_gap(a, b):
    gap = abs(a.hsvHueF() - b.hsvHueF())
    return min(gap, 1 - gap)


class VividLightColourTests(unittest.TestCase):
    def test_a_dark_cover_lights_with_its_colourful_details_not_its_background(self):
        data = cover(("#0a0a0a", 25), ("#d02828", 5), ("#2850d0", 2))
        light = artwork_light_colours(data)
        self.assertLess(hue_gap(light[0], QColor("#d02828")), .02)
        self.assertLess(hue_gap(light[1], QColor("#2850d0")), .02)
        self.assertTrue(all(colour.valueF() >= FLOOR for colour in light))

    def test_dark_muted_colours_keep_their_hue_and_get_bright(self):
        navy, maroon = QColor("#101a38"), QColor("#4a1418")
        light = artwork_light_colours(cover((navy.name(), 22), (maroon.name(), 10)))
        self.assertLess(min(hue_gap(c, navy) for c in light), .03)
        self.assertLess(min(hue_gap(c, maroon) for c in light), .03)
        self.assertTrue(all(colour.valueF() >= FLOOR for colour in light))

    def test_a_black_and_white_cover_gives_white_light_without_inventing_a_hue(self):
        light = artwork_light_colours(cover(("#000000", 22), ("#f4f4f4", 10)))
        self.assertTrue(all(colour.valueF() >= FLOOR for colour in light))
        self.assertTrue(all(colour.hsvSaturationF() < .05 for colour in light))

    def test_bright_colours_are_kept_as_they_are(self):
        light = artwork_light_colours(cover(("#ff2d8a", 20), ("#7a5cff", 12)))
        self.assertEqual(sorted(c.name() for c in light), ["#7a5cff", "#ff2d8a"])

    def test_missing_artwork_still_gives_two_bright_colours(self):
        for data in (b"", b"not an image"):
            light = artwork_light_colours(data)
            self.assertEqual(len(light), 2)
            self.assertTrue(all(colour.isValid() and colour.valueF() >= FLOOR for colour in light))


class AlbumLightControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-vivid-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        clock = patch("halo.app.time", SimpleNamespace(monotonic=lambda: 1000.))
        clock.start()
        self.addCleanup(clock.stop)

    def test_album_light_is_vivid_and_lyric_accents_follow_the_same_colours(self):
        from halo.app import Controller
        from halo.models import Track
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        c = Controller(settings, offline=True)
        c.timer.stop()
        self.addCleanup(lambda: (c.close(), c.audio.thread.join(1)))
        data = cover(("#0a0a0a", 25), ("#d02828", 5), ("#2850d0", 2))
        c.palette = "Album colours"
        c.palette_initialized = False
        c.track = Track("Song", "Artist", "Album", 200, 0, True, True, artwork=data)
        c.update_palette()
        self.assertTrue(all(colour.valueF() >= FLOOR for colour in (c.halo_primary, c.halo_secondary)))
        self.assertLess(hue_gap(c.halo_primary, QColor("#d02828")), .02)
        # Lyrics and the interface tint from the halo's own colours, made readable.
        light = artwork_light_colours(data)
        self.assertEqual(c.primary.name(), readable_accent(light[0], light[1]).name())
        self.assertEqual(c.secondary.name(), readable_accent(light[1], light[0]).name())
        self.assertLess(hue_gap(c.primary, c.halo_primary), .02)
        self.assertLess(hue_gap(c.secondary, c.halo_secondary), .02)


if __name__ == "__main__":
    unittest.main()
