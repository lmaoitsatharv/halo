"""Strata: a tilted wall of words, tested with original text and the shared lyric fixtures."""
import hashlib
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_support import ensure_system_fonts
import test_extra_lyrics as shared
from halo import extra_lyrics
from halo.extra_lyrics import EXTRA_LYRIC_STYLES, LINE_BASED_STYLES, StrataPose, strata_pose
from halo.mode_catalog import BASE_MODE_KEYS
from halo.models import LyricLine, LyricWord, Lyrics

CURRENT = QColor("#f4f4ef")
WALL_LINES = ("Original light and colours drifting over the quiet water tonight",
              "Our waves find their way along a long and winding silver coast",
              "Every small horizon opens on a new and brighter morning sky",
              "A new original horizon leaves the harbour lanterns burning low",
              "We keep the slow river moving through the valley after dark")


class StrataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def controller(self):
        return shared.ExtraLyricTests.controller(self, "lyric_strata")

    def canvas(self, c, mode="immersive", size=(800, 500)):
        return shared.ExtraLyricTests.canvas(self, c, mode, size)

    def drawn(self, canvas):
        """Every word inked in one paint, with the painter transform it was drawn under."""
        real_text, real_raster, seen = canvas._text, extra_lyrics._strata_raster, []

        def note(p, shape, x, y, colour, opacity):
            seen.append(SimpleNamespace(transform=QTransform(p.transform()), shape=shape, x=x, y=y,
                                        colour=colour, opacity=opacity))

        def text(p, shape, x, y, colour, opacity=1, scale=1, angle=0):
            note(p, shape, x, y, colour, opacity)
            return real_text(p, shape, x, y, colour, opacity, scale, angle)

        def raster(owner, p, shape, x, y, colour, opacity):
            note(p, shape, x, y, colour, opacity)
            return real_raster(owner, p, shape, x, y, colour, opacity)
        with patch.object(canvas, "_text", side_effect=text), \
             patch.object(extra_lyrics, "_strata_raster", side_effect=raster):
            canvas.grab()
        return seen

    @staticmethod
    def centre(word):
        return word.transform.map(QPointF(word.x, word.y))

    @staticmethod
    def width(word):
        """The word's width on screen against the same word laid flat."""
        half = word.shape.bounds.width() / 2
        a = word.transform.map(QPointF(word.x - half, word.y))
        b = word.transform.map(QPointF(word.x + half, word.y))
        return math.hypot(b.x() - a.x(), b.y() - a.y())

    @staticmethod
    def middle(size):
        """The centre 60% of a canvas, with room for the rounding of a word held on its edge."""
        return QRectF(size[0] * .2, size[1] * .2, size[0] * .6, size[1] * .6).adjusted(-1e-6, -1e-6, 1e-6, 1e-6)

    @staticmethod
    def digest(canvas):
        image = canvas.grab().toImage()
        return hashlib.sha256(image.constBits()).hexdigest()

    def test_strata_is_optional(self):
        self.assertIn("lyric_strata", {row[0] for row in EXTRA_LYRIC_STYLES})
        self.assertNotIn("lyric_strata", BASE_MODE_KEYS["lyrics"])
        self.assertNotIn("lyric_strata", LINE_BASED_STYLES)

    def test_pose_stays_within_limits_across_the_motion_range(self):
        for tenth in range(0, 3000):
            pose = strata_pose(tenth / 10, tenth // 40, .2, 0, False)
            self.assertLessEqual(abs(pose.yaw), 32)
            self.assertLessEqual(abs(pose.pitch), 12)
            self.assertLessEqual(abs(pose.roll), 4)

    def test_sway_follows_its_three_unrelated_periods(self):
        rest = strata_pose(0, 0, 1, 0, False)
        self.assertEqual(rest, StrataPose(18, -6, 0, 1))
        self.assertEqual(strata_pose(0, 1, 1, 0, False), StrataPose(-18, 6, 0, 1))
        for period, field, amplitude in ((7.1, "yaw", 14), (8.9, "pitch", 6), (6.3, "roll", 4)):
            with self.subTest(field=field):
                start = getattr(rest, field)
                self.assertAlmostEqual(getattr(strata_pose(period, 0, 1, 0, False), field), start)
                self.assertAlmostEqual(getattr(strata_pose(period / 4, 0, 1, 0, False), field), start + amplitude)
                self.assertAlmostEqual(getattr(strata_pose(period * .75, 0, 1, 0, False), field), start - amplitude)

    def test_new_line_whips_with_overshoot(self):
        start = strata_pose(5, 2, 0, 0, False).yaw
        peak = max(abs(strata_pose(5, 2, t / 100, 0, False).yaw - start) for t in range(0, 36))
        settled = abs(strata_pose(5, 2, .35, 0, False).yaw - start)
        self.assertGreater(peak, settled)

    def test_whip_starts_at_the_previous_lines_offset_and_ends_on_the_new_one(self):
        self.assertAlmostEqual(strata_pose(0, 3, 0, 0, False).yaw, strata_pose(0, 2, 1, 0, False).yaw)
        self.assertAlmostEqual(strata_pose(0, 3, .35, 0, False).yaw, strata_pose(0, 3, 9, 0, False).yaw)

    def test_pulse_adds_pitch_and_scale(self):
        base, loud = strata_pose(5, 2, 1, 0, False), strata_pose(5, 2, 1, 1, False)
        self.assertAlmostEqual(loud.pitch - base.pitch, 6)
        self.assertAlmostEqual(loud.scale, base.scale * 1.04)

    def test_reduced_motion_holds_a_fixed_pose(self):
        self.assertEqual(strata_pose(9, 3, .1, 1, True), StrataPose(-24, 8, 0, 1))

    def test_current_word_stays_in_the_centre_and_readable(self):
        for surface, size in (("immersive", (1000, 620)), ("floating", (350, 140))):
            with self.subTest(surface=surface):
                c = self.controller()
                c.reduced_motion = False
                c.position = .2
                canvas = self.canvas(c, surface, size)
                middle = self.middle(size)
                seen = 0
                for _ in range(300):
                    c.motion_time += .1
                    c.position += .05
                    current = [word for word in self.drawn(canvas) if word.colour == CURRENT]
                    self.assertLessEqual(len(current), 1)
                    for word in current:
                        seen += 1
                        self.assertTrue(middle.contains(self.centre(word)), (self.centre(word), middle))
                        self.assertGreaterEqual(self.width(word), word.shape.bounds.width() * .6 - 1e-6)
                self.assertGreater(seen, 200)

    def long_wall(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(5 * i, line) for i, line in enumerate(WALL_LINES)])
        c.track.duration = 5 * len(WALL_LINES)
        return c

    def test_reduced_motion_moves_the_wall_only_when_it_must(self):
        for surface, size, most in (("immersive", (968, 524), 70), ("floating", (860, 220), 40)):
            with self.subTest(surface=surface):
                c = self.long_wall()
                canvas = self.canvas(c, surface, size)
                canvas.grab()
                wall = QPointF(size[0] / 2, size[1] / 2)
                spots = []
                for word in canvas.timeline.display_words:
                    c.position = word.begin + .001
                    current = [seen for seen in self.drawn(canvas) if seen.colour == CURRENT]
                    self.assertEqual(len(current), 1)
                    self.assertTrue(self.middle(size).contains(self.centre(current[0])), word.text)
                    spots.append(current[0].transform.map(wall))
                moves = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in zip(spots, spots[1:])]
                self.assertLess(sum(moves) / len(moves), most)
                self.assertLess(max(moves), size[0] * .3)
                self.assertGreater(sum(move < 2 for move in moves), len(moves) / 2)

    def test_current_word_keeps_its_width_on_large_canvases(self):
        poses = [StrataPose(yaw, pitch, roll, 1.) for yaw in (-32, -20, 20, 32) for pitch in (-12, 0, 18)
                 for roll in (-4, 4)]
        for size in ((1944, 1100), (2787, 1100), (3170, 1820)):
            with self.subTest(size=size):
                c = self.long_wall()
                canvas = self.canvas(c, "immersive", size)
                canvas.grab()
                px = canvas._base_size() * 1.05
                words = canvas.timeline.display_words
                for line in (1, 2):
                    spoken = [i for i, word in enumerate(words) if word.line == line]
                    for word_index in (spoken[0], spoken[len(spoken) // 2], spoken[-1]):
                        placed = extra_lyrics._strata_layout(
                            canvas, line, extra_lyrics._strata_words(canvas, line, word_index), px)
                        active = next(entry for entry in placed if entry[0] == word_index)
                        flat = active[1].bounds.width()
                        for pan in placed:
                            for pose in poses:
                                t = extra_lyrics._strata_fit(canvas, pose, QPointF(pan[2], pan[3]), active)
                                self.assertGreaterEqual(extra_lyrics._mapped_width(t, *active[1:]) / flat,
                                                        .6 - 1e-6, (pose, pan[2:]))

    def test_words_wear_the_pinned_colours(self):
        c = self.controller()
        words = self.drawn(self.canvas(c))
        current = [word for word in words if word.colour == CURRENT]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].opacity, 1)
        at = words.index(current[0])
        self.assertTrue(all(word.colour == c.primary for word in words if word is not current[0]))
        self.assertAlmostEqual(max(word.opacity for word in words[:at]), .34)
        self.assertAlmostEqual(max(word.opacity for word in words[at + 1:]), .72)

    def test_wall_shows_one_line_before_and_two_after(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(4 * i, word) for i, word in
                           enumerate(("amber", "birch", "cedar", "dune", "ember", "frost", "grove"))])
        c.track.duration = 30
        c.position = 13
        canvas = self.canvas(c)
        with patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
            canvas.grab()
        self.assertEqual({call.args[0] for call in words.call_args_list}, {"cedar", "dune", "ember", "frost"})

    def test_strata_freezes_when_paused(self):
        c = self.controller()
        c.reduced_motion = False
        canvas = self.canvas(c)
        playing = self.digest(canvas)
        c.motion_time += 1
        self.assertNotEqual(playing, self.digest(canvas))
        c.track.playing = False
        paused = self.digest(canvas)
        c.motion_time += 20
        self.assertEqual(paused, self.digest(canvas))

    def test_clicks_seek_to_the_word_line(self):
        c = self.controller()
        c.offset = 250
        positions = []
        c.seek = positions.append
        canvas = self.canvas(c)
        words = self.drawn(canvas)
        current = next(word for word in words if word.colour == CURRENT)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=self.centre(current).toPoint())
        self.assertEqual(positions, [max(0, c.lyrics.lines[1].time - .25)])
        past = next(word for word in words if word.opacity < .5 and canvas.rect().contains(self.centre(word).toPoint()))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=self.centre(past).toPoint())
        self.assertEqual(positions[1:], [max(0, c.lyrics.lines[0].time - .25)])

    def test_hit_areas_sit_on_every_word_that_is_on_screen(self):
        c = self.controller()
        c.reduced_motion = False
        canvas = self.canvas(c)
        for _ in range(60):
            c.motion_time += .1
            words = self.drawn(canvas)
            for word in words:
                point = self.centre(word)
                if canvas.rect().contains(point.toPoint()):
                    self.assertTrue(any(rect.contains(point) for rect, _ in canvas._hit_rows), point)
            for rect, line in canvas._hit_rows:
                self.assertTrue(QRectF(canvas.rect()).contains(rect))
                self.assertTrue(0 <= line < len(c.lyrics.lines))

    def test_strata_survives_break_and_empty_lyrics(self):
        timed = LyricLine(0, "Quiet light", (LyricWord("Quiet ", 1.5), LyricWord("light", 2.5)), 4)
        for name, lines, position in (("before the first line", [LyricLine(5, "Original horizon")], 1),
                                      ("blank line", None, 9),
                                      ("music note slot", [timed, LyricLine(6, "Original horizon")], .5),
                                      ("empty lyrics", [], 3)):
            with self.subTest(name):
                c = self.controller()
                if lines is not None:
                    c.lyrics = Lyrics(lines)
                c.position = position
                canvas = self.canvas(c)
                canvas.grab()
                if name != "empty lyrics":
                    self.assertTrue(canvas._hit_rows)

    def test_floating_draws_at_most_24_words_and_other_surfaces_up_to_48(self):
        texts = ("Original horizon " * 18, ("原创文字照亮我们的天空" * 24)[:256])
        for text in texts:
            c = self.controller()
            c.lyrics = Lyrics([LyricLine(0, text), LyricLine(8, text)])
            c.position = 3
            for surface, size, most in (("floating", (860, 220), 24), ("preview", (420, 220), 48),
                                        ("immersive", (1000, 620), 48)):
                with self.subTest(text=text[:8], surface=surface):
                    canvas = self.canvas(c, surface, size)
                    with patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
                        seen = self.drawn(canvas)
                    self.assertLessEqual(len(words.call_args_list), most)
                    self.assertLessEqual(len(seen), most)
                    if surface != "floating":
                        self.assertGreater(len(words.call_args_list), 24)
                    current = [word for word in seen if word.colour == CURRENT]
                    self.assertEqual(len(current), 1)
                    self.assertTrue(self.middle(size).contains(self.centre(current[0])))

    def test_floating_keeps_whole_lines_when_they_fit_the_limit(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(4 * i, f"{word} {word}x") for i, word in
                           enumerate(("amber", "birch", "cedar", "dune", "ember", "frost"))])
        c.track.duration = 30
        c.position = 9
        canvas = self.canvas(c, "floating", (860, 220))
        with patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
            canvas.grab()
        self.assertEqual(len(words.call_args_list), 8)

    def test_floating_words_come_from_cached_rasters_and_repeat_paints_reuse_them(self):
        canvas = self.canvas(self.controller(), "floating", (860, 220))
        with patch.object(canvas, "_text", wraps=canvas._text) as direct:
            canvas.grab()
            cache = canvas._strata_rasters
            keys = list(cache)
            rasters = [entry[1].cacheKey() for entry in cache.values()]
            self.assertTrue(keys)
            canvas.grab()
        self.assertEqual(direct.call_count, 0)
        self.assertEqual(keys, list(cache))
        self.assertEqual(rasters, [entry[1].cacheKey() for entry in cache.values()])
        immersive = self.canvas(self.controller())
        immersive.grab()
        self.assertFalse(hasattr(immersive, "_strata_rasters"))

    def test_floating_raster_cache_stays_within_its_bounds(self):
        c = self.controller()
        canvas = self.canvas(c, "floating", (860, 220))
        for hue in range(36):
            c.primary = QColor.fromHsl(hue * 10, 120, 180)
            canvas.grab()
            cache = canvas._strata_rasters
            self.assertLessEqual(len(cache), extra_lyrics.STRATA_RASTERS)
            self.assertLessEqual(canvas._strata_raster_pixels, extra_lyrics.STRATA_RASTER_PIXELS)
            self.assertEqual(canvas._strata_raster_pixels, sum(entry[2] for entry in cache.values()))
        small = self.canvas(self.controller(), "floating", (860, 220))
        with patch.object(extra_lyrics, "STRATA_RASTERS", 5):
            small.grab()
        self.assertEqual(len(small._strata_rasters), 5)
        self.assertEqual(small._strata_raster_pixels, sum(entry[2] for entry in small._strata_rasters.values()))

    def test_floating_word_too_big_for_the_cache_is_drawn_directly(self):
        canvas = self.canvas(self.controller(), "floating", (860, 220))
        with patch.object(extra_lyrics, "STRATA_RASTER_PIXELS", 10), \
             patch.object(canvas, "_text", wraps=canvas._text) as direct:
            canvas.grab()
        self.assertTrue(direct.called)
        self.assertEqual(len(canvas._strata_rasters), 0)

    def test_floating_raster_keeps_the_look_of_direct_drawing(self):
        c = self.controller()
        canvas = self.canvas(c, "floating", (430, 140))
        cached = canvas.grab().toImage()
        with patch.object(extra_lyrics, "_strata_raster",
                          side_effect=lambda owner, p, shape, x, y, colour, opacity: owner._text(p, shape, x, y, colour, opacity)):
            direct = canvas.grab().toImage()
        inked = off = dark = 0
        for y in range(cached.height()):
            for x in range(cached.width()):
                a, b = cached.pixelColor(x, y), direct.pixelColor(x, y)
                if a.alpha() or b.alpha():
                    inked += 1
                    off += max(abs(a.alpha() - b.alpha()), abs(a.red() - b.red()),
                               abs(a.green() - b.green()), abs(a.blue() - b.blue())) > 64
                    dark += a.alpha() > 100 and a.lightness() < 40
        self.assertGreater(inked, 5000)
        self.assertLess(off / inked, .05)
        self.assertGreater(dark, 200)

    def test_strata_bounds_long_unspaced_line(self):
        # Halo accepts at most 256 words a line, and a CJK line without spaces counts every character.
        text = ("原创文字照亮我们的天空" * 24)[:256]
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(0, text), LyricLine(8, text)])
        c.position = 3
        for size in ((230, 140), (1000, 620)):
            with self.subTest(size=size):
                canvas = self.canvas(c, "preview", size)
                with patch.object(canvas, "_shape", wraps=canvas._shape) as lines, \
                     patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
                    seen = self.drawn(canvas)
                self.assertEqual(len(lines.call_args_list), 0)
                self.assertLessEqual(len(words.call_args_list), 48)
                self.assertLessEqual(len(seen), 48)
                current = [word for word in seen if word.colour == CURRENT]
                self.assertEqual(len(current), 1)
                self.assertTrue(canvas.rect().contains(self.centre(current[0]).toPoint()))


if __name__ == "__main__":
    unittest.main()
