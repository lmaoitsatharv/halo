"""Original-text checks for estimated timing, animation and native lyric layouts."""
import hashlib
from types import SimpleNamespace
import unittest

from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.lyric_rendering import LYRIC_STYLES, TypeCache, WordTimeline, spring
from halo.models import LyricLine, Lyrics, Track
from halo.widgets import LyricCanvas


class LyricModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self):
        return SimpleNamespace(
            lyrics=Lyrics([LyricLine(0, "Original light and colours"),
                           LyricLine(4, "Our waves find their way"),
                           LyricLine(8, ""), LyricLine(12, "A new original horizon")]),
            track=Track(duration=17, playing=True), position=1.8, offset=0,
            motion_time=10., generation=1, lyric_style="fisheye_visual",
            reduced_motion=False, primary=QColor("#e9b7a1"), secondary=QColor("#c494aa"),
            seek=lambda value: None,
        )

    def test_spring_is_independent_of_refresh_rate(self):
        outcomes = []
        for fps in (24, 30, 60, 120):
            value, velocity = 0., 0.
            for _ in range(fps):
                value, velocity = spring(value, velocity, 1., 1 / fps)
            outcomes.append((value, velocity))
        for value, velocity in outcomes:
            self.assertAlmostEqual(value, outcomes[0][0], places=12)
            self.assertAlmostEqual(velocity, outcomes[0][1], places=12)

    def test_word_estimates_reanchor_at_each_line_and_preserve_empty_cue(self):
        c = self.controller()
        timeline = WordTimeline(c.lyrics.lines, c.track.duration)
        self.assertEqual(timeline.at(-1, -1), (-1, 0.))
        for line_index, line in enumerate(c.lyrics.lines):
            word_index, fraction = timeline.at(line_index, line.time)
            self.assertEqual(word_index, timeline.ranges[line_index][0])
            self.assertAlmostEqual(fraction, 0.)
        self.assertEqual(timeline.words[timeline.at(2, 9)[0]].text, "♪")
        self.assertEqual(timeline.words[timeline.at(3, 100)[0]].text, "horizon")

    def test_seeks_reset_springs_in_both_directions(self):
        c = self.controller()
        canvas = LyricCanvas(c)
        canvas._advance(0, 1, 1.8, 10)
        canvas._advance(3, 11, 12.8, 10.033)
        self.assertEqual(canvas.visual_index, 3.)
        self.assertEqual(canvas._word_visual, 11.)
        canvas._advance(0, 0, .1, 10.066)
        self.assertEqual(canvas.visual_index, 0.)
        self.assertEqual(canvas._word_visual, 0.)
        canvas.close()

    def test_pause_and_reduced_motion(self):
        c = self.controller()
        canvas = LyricCanvas(c)
        canvas._advance(0, 0, 0, 10)
        canvas._advance(1, 4, .033, 10.033)
        before = (canvas.visual_index, canvas._word_visual)
        c.track.playing = False
        canvas._advance(1, 4, .033, 10.033)
        self.assertEqual(before, (canvas.visual_index, canvas._word_visual))
        c.reduced_motion = True
        canvas._advance(1, 4, .033, 10.033)
        self.assertEqual((canvas.visual_index, canvas._word_visual), (1., 4.))
        canvas.close()

    def test_visual_paused_initial_frame_does_not_disappear_on_repaint(self):
        c = self.controller()
        c.track.playing = False
        c.lyric_style = "visual"
        canvas = LyricCanvas(c)
        canvas.resize(420, 240)
        first = canvas.grab().toImage()
        second = canvas.grab().toImage()
        self.assertEqual(first, second)
        canvas.close()

    def test_type_cache_fits_long_unicode_and_unbroken_lines(self):
        cache = TypeCache(limit=8)
        for text in ("An original sentence " * 30, "Horizon" * 65,
                     "原创文字照亮我们的天空" * 18, "हवा में नई रोशनी " * 12):
            shape = cache.get(text, 170, 45, 42)
            self.assertLessEqual(shape.bounds.width(), 170.01)
            self.assertLessEqual(shape.bounds.height(), 45.01)
        for i in range(20):
            cache.get("Original " + str(i), 170, 45, 7, QFont.Weight.Normal)
        self.assertEqual(len(cache.items), 8)

    def test_clicking_a_visible_cue_seeks_with_offset(self):
        c = self.controller()
        c.lyric_style = "ship"
        c.offset = 250
        positions = []
        c.seek = positions.append
        canvas = LyricCanvas(c, "preview")
        canvas.resize(500, 260)
        canvas.grab()
        rect, line = next((rect, line) for rect, line in canvas._hit_rows if line == 1)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(positions, [c.lyrics.lines[line].time - .25])
        canvas.close()

    def test_four_styles_render_distinctly_on_all_surfaces(self):
        for surface, size in (("preview", (420, 220)), ("floating", (350, 140)),
                              ("immersive", (800, 500))):
            hashes = set()
            for style, _, _ in LYRIC_STYLES:
                c = self.controller()
                c.lyric_style = style
                canvas = LyricCanvas(c, surface)
                canvas.resize(*size)
                image = canvas.grab().toImage()
                hashes.add(hashlib.sha256(image.constBits()).hexdigest())
                c.position = 9
                canvas.grab()  # Instrumental blank cue.
                c.position = .1
                c.generation += 1
                canvas.grab()  # Backward seek and replacement lyrics generation.
                self.assertEqual(canvas.visual_index, 0.)
                canvas.close()
            self.assertEqual(len(hashes), 4, surface)


if __name__ == "__main__":
    unittest.main()
