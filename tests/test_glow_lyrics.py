"""Cascade, Starline, Neon and Impact, tested with original text and the shared lyric fixtures."""
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from qt_support import channels_over_alpha, ensure_system_fonts
import test_extra_lyrics as shared
from halo import glow_lyrics
from halo.extra_lyrics import EXTRA_LYRIC_STYLES, LINE_BASED_STYLES
from halo.glow_lyrics import (CASCADE_WORDS, GLOW_PIXELS, GLOW_RASTERS, IMPACT_RING_SPAN, NEON_CHANGE, NEON_WORDS,
                              STAR_FLOATING_WORDS, STAR_WORDS, block_ink, impact_pose, neon_flicker, star_field,
                              star_groups, star_label_side)
from halo.lyric_rendering import WordTimeline, symbol_kind
from halo.mode_catalog import BASE_MODE_KEYS
from halo.models import LyricLine, LyricWord, Lyrics

GLOW_STYLES = ("lyric_cascade", "lyric_starline", "lyric_neon", "lyric_impact")
SURFACES = (("preview", (420, 220)), ("floating", (350, 140)), ("immersive", (1000, 620)))


def luminance(colour):
    def channel(value):
        return value / 12.92 if value <= .03928 else ((value + .055) / 1.055) ** 2.4
    return .2126 * channel(colour.redF()) + .7152 * channel(colour.greenF()) + .0722 * channel(colour.blueF())


class GlowLyricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def controller(self, style):
        return shared.ExtraLyricTests.controller(self, style)

    def canvas(self, c, mode="immersive", size=(800, 500)):
        return shared.ExtraLyricTests.canvas(self, c, mode, size)

    def stamps(self, canvas):
        """Every stamp of one paint, each with the word it shows."""
        real_stamp, real_shape, real_word, seen, names = (glow_lyrics._stamp, canvas._shape, canvas._word_shape, [], {})

        def note(real):
            def shaped(text, *args, **kwargs):
                shape = real(text, *args, **kwargs)
                names[id(shape)] = text
                return shape
            return shaped

        def stamp(owner, p, shape, layer, colour, x, y, opacity=1, scale=1):
            seen.append(SimpleNamespace(text=names.get(id(shape)), shape=shape, layer=layer, colour=colour,
                                        x=x, y=y, opacity=opacity, scale=scale))
            return real_stamp(owner, p, shape, layer, colour, x, y, opacity, scale)
        with patch.object(glow_lyrics, "_stamp", side_effect=stamp), \
             patch.object(canvas, "_shape", side_effect=note(real_shape)), \
             patch.object(canvas, "_word_shape", side_effect=note(real_word)):
            canvas.grab()
        return seen

    @staticmethod
    def texts(stamps, layer):
        return [stamp.text for stamp in stamps if stamp.layer == layer]

    @staticmethod
    def digest(canvas):
        image = canvas.grab().toImage()
        return hashlib.sha256(image.constBits()).hexdigest()

    def test_the_new_modes_are_optional_word_modes(self):
        keys = {row[0] for row in EXTRA_LYRIC_STYLES}
        for style in GLOW_STYLES:
            self.assertIn(style, keys)
            self.assertNotIn(style, BASE_MODE_KEYS["lyrics"])
            self.assertNotIn(style, LINE_BASED_STYLES)

    def test_the_current_word_stays_inside_the_canvas_on_every_surface(self):
        for style in GLOW_STYLES:
            for surface, size in SURFACES:
                for position in (.4, 2.5, 5.6, 7.5, 13):
                    with self.subTest(style=style, surface=surface, position=position):
                        c = self.controller(style)
                        c.position = position
                        canvas = self.canvas(c, surface, size)
                        stamps = self.stamps(canvas)
                        word = canvas.timeline.display_at(c.lyrics.index_at(position), position)[1]
                        current = canvas.timeline.display_words[word].text
                        faces = [stamp for stamp in stamps if stamp.layer == "face" and stamp.text == current]
                        self.assertTrue(faces)
                        for face in faces:
                            width = face.shape.bounds.width() * face.scale
                            height = face.shape.bounds.height() * face.scale
                            box = QRectF(face.x - width / 2, face.y - height / 2, width, height)
                            self.assertTrue(QRectF(canvas.rect()).adjusted(-2, -2, 2, 2).contains(box), box)

    def test_floating_ink_stays_valid_on_a_transparent_window(self):
        for style in GLOW_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.reduced_motion = False
                image = self.canvas(c, "floating", (350, 140)).grab().toImage()
                self.assertEqual(channels_over_alpha(image), 0)

    def test_a_pause_mid_entrance_holds_the_frame(self):
        for style in GLOW_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.reduced_motion = False
                canvas = self.canvas(c)
                canvas.grab()
                word = canvas.timeline.display_words[canvas.timeline.display_at(1, c.position)[1]]
                c.position = word.begin + .05
                c.motion_time += .05
                canvas.grab()
                c.track.playing = False
                before = canvas.grab().toImage()
                c.motion_time += 20
                self.assertEqual(before, canvas.grab().toImage())

    def test_seeking_away_and_back_redraws_the_same_frame(self):
        for style in GLOW_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                canvas = self.canvas(c)
                first = self.digest(canvas)
                c.position = .2
                canvas.grab()
                c.position = 5.6
                self.assertEqual(first, self.digest(canvas))

    def test_glow_rasters_are_reused_and_bounded(self):
        for style in GLOW_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                canvas = self.canvas(c)
                canvas.grab()
                keys = [entry[1].cacheKey() for entry in canvas._glow_rasters.values()]
                self.assertTrue(keys)
                canvas.grab()
                self.assertEqual(keys, [entry[1].cacheKey() for entry in canvas._glow_rasters.values()])
                for hue in range(24):
                    c.primary = QColor.fromHsl(hue * 15, 120, 180)
                    canvas.grab()
                    self.assertLessEqual(len(canvas._glow_rasters), GLOW_RASTERS)
                    self.assertLessEqual(canvas._glow_pixels, GLOW_PIXELS)

    def test_a_shape_too_big_to_cache_is_still_drawn(self):
        c = self.controller("lyric_impact")
        canvas = self.canvas(c)
        with patch.object(glow_lyrics, "GLOW_PIXELS", 1), patch.object(canvas, "_text", wraps=canvas._text) as ink:
            canvas.grab()
        self.assertTrue(ink.called)
        self.assertFalse(canvas._glow_rasters)

    def test_cascade_stacks_older_words_above_a_larger_newest_word(self):
        c = self.controller("lyric_cascade")
        stamps = [stamp for stamp in self.stamps(self.canvas(c)) if stamp.layer == "face"]
        self.assertGreater(len(stamps), 2)
        self.assertLessEqual(len(stamps), CASCADE_WORDS)
        stamps.sort(key=lambda stamp: stamp.y)
        self.assertEqual(max(stamps, key=lambda stamp: stamp.scale), stamps[-1])
        self.assertEqual(len({stamp.y for stamp in stamps}), len(stamps))

    def test_cascade_never_shows_a_word_before_it_is_sung(self):
        c = self.controller("lyric_cascade")
        c.position = 4.2
        words = self.texts(self.stamps(self.canvas(c)), "face")
        self.assertIn("Our", words)
        self.assertNotIn("longer", words)

    def test_cascade_draws_symbols_only_for_words_it_knows(self):
        c = self.controller("lyric_cascade")
        c.lyrics = Lyrics([LyricLine(0, "Seasons change and our love went cold")])
        c.position = 17
        canvas = self.canvas(c)
        with patch.object(canvas, "_symbol", wraps=canvas._symbol) as symbol:
            canvas.grab()
        words = [call.args[1] for call in symbol.call_args_list]
        self.assertTrue(words)
        self.assertTrue(all(symbol_kind(word) != "star" for word in words))

    def test_highlight_text_is_readable_on_any_block_colour(self):
        for colour in ("#b7e4ad", "#54ad9f", "#9b88cf", "#2a1a5e", "#ffffff", "#000000"):
            with self.subTest(colour=colour):
                block, ink = luminance(QColor(colour)), luminance(block_ink(QColor(colour)))
                self.assertGreaterEqual((max(block, ink) + .05) / (min(block, ink) + .05), 4.5)

    def test_star_field_is_stable_and_stays_in_its_box(self):
        field = star_field("the evening finds a quiet home", 16)
        self.assertEqual(field, star_field("the evening finds a quiet home", 16))
        self.assertNotEqual(field, star_field("our original light", 16))
        self.assertEqual(len(field), 16)
        self.assertEqual(len(set(field)), 16)
        self.assertTrue(all(0 <= x <= 1 and 0 <= y <= 1 for x, y in field))

    def test_star_groups_keep_every_word_and_clear_at_a_break(self):
        lines = [LyricLine(0, "one two three four"), LyricLine(4, "five six seven"), LyricLine(8, ""),
                 LyricLine(12, "eight nine"), LyricLine(16, "word " * 40)]
        timeline = WordTimeline(lines, 40)
        groups = star_groups(timeline.display_words, STAR_WORDS)
        flat = [i for group in groups for i in group]
        self.assertEqual(flat, [i for i, word in enumerate(timeline.display_words) if word.text != "♪"])
        self.assertTrue(all(len(group) <= STAR_WORDS for group in groups))
        self.assertEqual(timeline.display_words[groups[0][-1]].text, "seven")
        self.assertEqual(timeline.display_words[groups[1][0]].text, "eight")

    def test_star_groups_start_a_new_map_at_a_line_that_would_not_fit(self):
        lines = [LyricLine(0, "one two three"), LyricLine(4, "four five six")]
        timeline = WordTimeline(lines, 8)
        groups = star_groups(timeline.display_words, 4)
        self.assertEqual([len(group) for group in groups], [3, 3])

    def test_starline_reveals_a_star_only_once_its_word_is_sung(self):
        c = self.controller("lyric_starline")
        c.position = 4.2
        early = self.texts(self.stamps(self.canvas(c)), "face")
        c = self.controller("lyric_starline")
        c.position = 7.5
        late = self.texts(self.stamps(self.canvas(c)), "face")
        self.assertNotIn("longer", early)
        self.assertIn("longer", late)
        self.assertGreater(len(late), len(early))

    def test_starline_keeps_fewer_stars_on_the_floating_window(self):
        c = self.controller("lyric_starline")
        c.lyrics = Lyrics([LyricLine(0, "word " * 30)])
        c.position = 3.9
        self.assertLessEqual(len(self.texts(self.stamps(self.canvas(c, "floating", (350, 140))), "face")),
                             STAR_FLOATING_WORDS)

    def test_neon_shows_the_whole_line_and_lights_only_sung_words(self):
        c = self.controller("lyric_neon")
        c.position = 4.2
        stamps = self.stamps(self.canvas(c))
        self.assertEqual(self.texts(stamps, "tube"), "Our original light stays a little longer".split())
        lit = self.texts(stamps, "bloom")
        self.assertIn("Our", lit)
        self.assertNotIn("longer", lit)

    def test_neon_pages_a_long_line_around_the_current_word(self):
        c = self.controller("lyric_neon")
        c.lyrics = Lyrics([LyricLine(0, " ".join(f"word{i}" for i in range(30)))])
        c.position = 3.9
        canvas = self.canvas(c)
        tubes = self.texts(self.stamps(canvas), "tube")
        self.assertLessEqual(len(tubes), NEON_WORDS)
        self.assertIn(canvas.timeline.display_words[canvas.timeline.display_at(0, 3.9)[1]].text, tubes)

    def test_neon_previews_a_timed_line_before_its_first_word(self):
        c = self.controller("lyric_neon")
        c.lyrics = Lyrics([LyricLine(0, "quiet light", (LyricWord("quiet ", 2, 3), LyricWord("light", 3, 4)))])
        c.position = 1
        stamps = self.stamps(self.canvas(c))
        self.assertEqual(self.texts(stamps, "tube"), ["quiet", "light"])
        self.assertEqual(self.texts(stamps, "bloom"), [])

    def test_neon_flicker_stays_in_range_and_settles_fully_lit(self):
        steps = [neon_flicker(tenth / 100) for tenth in range(0, 100)]
        self.assertTrue(all(0 <= value <= 1 for value in steps))
        self.assertLess(min(steps), .6)
        self.assertEqual(neon_flicker(.5), 1)

    def test_impact_slams_in_and_settles(self):
        start, settled = impact_pose(0, .5, 0, False), impact_pose(1, .5, 0, False)
        self.assertGreater(start.scale, 1.4)
        self.assertLess(start.opacity, 1)
        self.assertGreater(start.split, settled.split)
        self.assertAlmostEqual(settled.scale, 1)
        self.assertEqual(settled.opacity, 1)
        self.assertEqual(settled.split, 0)

    def test_impact_scale_stays_bounded_at_any_age_and_level(self):
        for age in range(0, 300):
            for pulse in (0, .5, 1, 4):
                self.assertTrue(.9 <= impact_pose(age / 100, .3, pulse, False).scale <= 1.9)

    def test_impact_ring_only_follows_a_word_with_room_for_it(self):
        self.assertIsNotNone(impact_pose(.1, IMPACT_RING_SPAN, 0, False).ring)
        self.assertIsNone(impact_pose(.1, IMPACT_RING_SPAN - .01, 0, False).ring)
        self.assertIsNone(impact_pose(5, IMPACT_RING_SPAN, 0, False).ring)

    def test_impact_grows_with_level_but_not_under_reduce_motion(self):
        self.assertGreater(impact_pose(1, .5, 1, False).scale, impact_pose(1, .5, 0, False).scale)
        self.assertEqual(impact_pose(0, .5, 1, True), impact_pose(9, .5, 0, True))
        still = impact_pose(0, .5, 1, True)
        self.assertEqual((still.scale, still.opacity, still.split, still.ring), (1, 1, 0, None))

    def test_impact_shockwave_echoes_the_word_itself(self):
        c = self.controller("lyric_impact")
        c.reduced_motion = False
        canvas = self.canvas(c)
        canvas.grab()
        word = canvas.timeline.display_words[canvas.timeline.display_at(1, c.position)[1]]
        c.position = word.begin + .1
        echoes = [stamp for stamp in self.stamps(canvas) if stamp.layer == "tube"]
        self.assertTrue(echoes)
        self.assertTrue(all(stamp.text == word.text and stamp.scale > 1 for stamp in echoes))

    def test_neon_old_sign_is_gone_before_the_first_word_settles(self):
        c = self.controller("lyric_neon")
        c.reduced_motion = False
        canvas = self.canvas(c)
        c.position = 4.03
        self.assertIn("evening", self.texts(self.stamps(canvas), "tube"))
        c.position = 4 + NEON_CHANGE
        self.assertNotIn("evening", self.texts(self.stamps(canvas), "tube"))
        self.assertLess(NEON_CHANGE, .2)

    def test_star_label_sits_away_from_its_thread(self):
        field = ((.2, .8), (.5, .2), (.8, .8), (.9, .1))
        self.assertEqual(star_label_side(field, 1), -1)
        self.assertEqual(star_label_side(field, 0), 1)
        self.assertEqual(star_label_side(field, 3), -1)

    def test_bloom_is_cached_small_so_a_new_word_costs_little(self):
        canvas = self.canvas(self.controller("lyric_impact"))
        canvas.grab()
        sizes = {key[1]: entry[2] for key, entry in canvas._glow_rasters.items()}
        self.assertLess(sizes["bloom"], sizes["face"])

    def test_impact_responds_to_the_captured_level_and_renders_without_one(self):
        c = self.controller("lyric_impact")
        c.reduced_motion = False
        canvas = self.canvas(c)
        quiet = self.digest(canvas)
        c.pulse = .9
        self.assertNotEqual(quiet, self.digest(canvas))


if __name__ == "__main__":
    unittest.main()
