"""Each lyric style and room card shows itself, drawn by its real renderer on the sample words."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6.QtCore import QEvent, QRect, QSettings
from PySide6.QtWidgets import QApplication

from halo.app import Controller
from halo.frontend import ModeTile
from halo.immersive import IMMERSIVE_SCENES
from halo.lyric_rendering import LYRIC_STYLES
from halo.mode_library import CARD_CLOCK, CARD_LOOP
from halo.models import LyricLine, Lyrics, Track


LYRIC_PREVIEW = QRect(9, 7, 312, 45)
ROOM_PREVIEW = QRect(53, 7, 224, 140)


class StyleCardTests(unittest.TestCase):
    SETTING, SPECS, PREVIEW = "lyric_style", LYRIC_STYLES, LYRIC_PREVIEW

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-style-cards-", dir=scratch)
        path = str(Path(self.temp.name) / "settings.ini")
        self.c = Controller(QSettings(path, QSettings.Format.IniFormat), offline=True)
        self.c.reduced_motion = True
        self.tiles = []
        CARD_CLOCK.elapsed, CARD_CLOCK.last = 6., None

    def tearDown(self):
        for tile in self.tiles:
            tile.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.c.close()
        self.c.audio.thread.join(1)
        self.temp.cleanup()

    def tile(self, spec):
        tile = ModeTile(self.c, self.SETTING, spec)
        tile.resize(330, tile.height())
        self.tiles.append(tile)
        return tile

    def frame(self, tile):
        # The image has to outlive the read, since the bits are only borrowed from it.
        image = tile.grab().toImage().copy(self.PREVIEW)
        return bytes(image.constBits())

    def thumbnail(self, spec):
        return self.frame(self.tile(spec))

    def fresh_frame(self, tile):
        tile.preview_cache_at = 0.
        return self.frame(tile)

    def test_no_two_styles_share_a_card(self):
        cards = {spec[1]: self.thumbnail(spec) for spec in self.SPECS}
        self.assertEqual(len(set(cards.values())), len(self.SPECS), sorted(cards))

    def test_a_card_shows_its_own_style_not_the_chosen_one(self):
        neon = next(spec for spec in LYRIC_STYLES if spec[0] == "lyric_neon")
        self.c.lyric_style = "ship_visual"
        before = self.thumbnail(neon)
        self.c.lyric_style = "lyric_impact"
        self.assertEqual(self.thumbnail(neon), before)

    def test_cards_keep_the_sample_words_during_a_song(self):
        spec = self.SPECS[0]
        before = self.thumbnail(spec)
        self.c.track = Track("Song", "Band", "Album", 200, 30, True, True)
        self.c.lyrics = Lyrics([LyricLine(0, "completely different words")])
        self.assertEqual(self.thumbnail(spec), before)

    def test_cards_never_touch_playback(self):
        before = (self.c.track, self.c.lyrics, self.c.position, self.c.generation, self.c.lyric_style, self.c.immersive_mode)
        for spec in self.SPECS:
            self.thumbnail(spec)
        self.assertEqual((self.c.track, self.c.lyrics, self.c.position, self.c.generation, self.c.lyric_style, self.c.immersive_mode), before)

    def test_cards_move(self):
        self.c.reduced_motion = False
        tile = self.tile(self.SPECS[1])
        first = self.fresh_frame(tile)
        CARD_CLOCK.elapsed += 2.
        self.assertNotEqual(self.fresh_frame(tile), first)

    def test_reduced_motion_holds_a_card_still(self):
        tile = self.tile(self.SPECS[1])
        first = self.fresh_frame(tile)
        for _ in range(3):
            CARD_CLOCK.last -= 1.
            self.assertEqual(self.fresh_frame(tile), first)

    def test_a_card_is_never_empty_through_its_loop(self):
        self.c.reduced_motion = False
        for spec in self.SPECS:
            tile = self.tile(spec)
            # Steps as small as a real card's, starting just after the first word's own entrance.
            for step in range(1, int(CARD_LOOP) * 10):
                CARD_CLOCK.elapsed, CARD_CLOCK.last = step / 10, None
                pixels = np.frombuffer(self.fresh_frame(tile), np.uint8).reshape(-1, 4)[:, :3]
                with self.subTest(spec[1], at=step / 10):
                    self.assertGreater(int(pixels.max()) - int(pixels.min()), 60)


class RoomCardTests(StyleCardTests):
    SETTING, SPECS, PREVIEW = "immersive_mode", IMMERSIVE_SCENES, ROOM_PREVIEW

    def test_a_card_shows_its_own_style_not_the_chosen_one(self):
        orbit = next(spec for spec in IMMERSIVE_SCENES if spec[0] == "orbit")
        self.c.immersive_mode = "studio"
        before = self.thumbnail(orbit)
        self.c.immersive_mode = "cinema"
        self.assertEqual(self.thumbnail(orbit), before)

    def test_a_room_card_shows_the_whole_room(self):
        self.assertGreater(self.tile(IMMERSIVE_SCENES[0]).height(), 140)

    def test_a_narrow_room_card_stays_inside_its_border(self):
        tile = self.tile(IMMERSIVE_SCENES[0])
        tile.resize(130, tile.height())
        tile.grab()
        self.assertEqual(tile.preview_cache.width(), 112)

    def test_a_room_card_uses_the_chosen_lyric_style(self):
        tile = self.tile(IMMERSIVE_SCENES[1])
        first = self.fresh_frame(tile)
        self.c.lyric_style = "lyric_neon"
        self.assertNotEqual(self.fresh_frame(tile), first)


if __name__ == "__main__":
    unittest.main()
