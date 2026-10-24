"""Instrumental breaks focus empty space while retaining surrounding lyrics."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from halo.lyric_rendering import LYRIC_STYLES, WordTimeline
from halo.models import Lyrics, LyricLine, LyricWord, Track, parse_lrc
from halo.widgets import LyricCanvas

CORE_STYLES = tuple(spec for spec in LYRIC_STYLES if spec[0] in {"ship_visual", "fisheye_visual", "visual"})


class LyricGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self, style="ship", position=6):
        return SimpleNamespace(
            lyrics=Lyrics(parse_lrc("[00:00]\n[00:02]An original ocean\n"
                                    "[00:05]\n[00:07]   \n[00:10]A new quiet moon\n[00:14]")),
            track=Track(duration=20, playing=True), position=position, offset=0,
            motion_time=10., generation=1, lyric_style=style, reduced_motion=True,
            primary=QColor("#bddbd0"), secondary=QColor("#bd9ec8"),
            seek=lambda value: None)

    def canvas(self, c, surface="preview"):
        canvas = LyricCanvas(c, surface)
        canvas.resize(800, 500)
        self.addCleanup(canvas.close)
        return canvas

    def test_display_resolution_retains_consecutive_and_trailing_blank_slots(self):
        c = self.controller()
        timeline = WordTimeline(c.lyrics.lines, c.track.duration)
        for position, expected in ((0, 0), (1.9, 0), (2, 1), (5, 2), (7, 3),
                                   (9.999, 3), (10, 4), (14, 5), (20, 5)):
            with self.subTest(position=position):
                raw_index = c.lyrics.index_at(position)
                self.assertEqual(timeline.display_at(raw_index, position)[0], expected)
        self.assertEqual(c.lyrics.index_at(7), 3, "Source cues remain unmodified")

    def test_word_styles_focus_a_blank_until_the_next_real_word_start(self):
        lines = [LyricLine(1, "Our ocean", (LyricWord("Our ", 1, 2), LyricWord("ocean", 2, 3))),
                 LyricLine(4, ""), LyricLine(6, "New moon", (LyricWord("New ", 8, 9),
                                                                          LyricWord("moon", 9, 10)))]
        lyrics = Lyrics(lines)
        timeline = WordTimeline(lines, 12)
        for position, expected_line, expected_word in ((5, 1, 2), (6, 2, 3), (7.999, 2, 3),
                                                      (8, 2, 4), (9, 2, 5)):
            with self.subTest(position=position):
                result = timeline.display_at(lyrics.index_at(position), position)
                self.assertEqual(result[:2], (expected_line, expected_word))
        self.assertEqual(timeline.display_at(2, 6)[0], 2, "Whole-line modes honor line starts")

    def test_intro_is_blank_without_advancing_word_animation(self):
        c = self.controller()
        timeline = WordTimeline(c.lyrics.lines, 20)
        self.assertEqual(timeline.display_at(-1, -2), (-1, -1, 0.))
        for position in (0, 1.99):
            line, word, _ = timeline.display_at(c.lyrics.index_at(position), position)
            self.assertEqual(line, 0)
            self.assertEqual(timeline.display_words[word].text, "♪")

    def test_every_style_and_surface_focuses_blank_cues_without_waiting_dots(self):
        for style, _, _ in CORE_STYLES:
            for surface in ("preview", "floating", "immersive"):
                with self.subTest(style=style, surface=surface):
                    c = self.controller(style)
                    canvas = self.canvas(c, surface)
                    with patch.object(canvas, "_instrumental") as dots, \
                         patch.object(canvas, "_text", wraps=canvas._text) as text:
                        for position, expected in ((0, 0), (3, 1), (6, 2), (9, 3), (10, 4), (17, 5)):
                            c.position = position
                            c.motion_time += .1
                            canvas.grab()
                            self.assertEqual(canvas.visual_index, expected)
                            self.assertEqual(text.called, style != "visual" or expected in (1, 4))
                            text.reset_mock()
                        dots.assert_not_called()

    def test_blank_rows_do_not_turn_into_music_note_placeholders(self):
        for style in ("ship", "ship_visual"):
            c = self.controller(style)
            canvas = self.canvas(c)
            with patch.object(canvas, "_shape", wraps=canvas._shape) as shapes:
                canvas.grab()
                self.assertTrue(shapes.called)
                self.assertTrue(all(call.args[0].strip() and call.args[0] != "♪"
                                    for call in shapes.call_args_list))

    def test_direct_seek_into_gap_and_backwards_uses_the_correct_song_cue(self):
        for style, _, _ in CORE_STYLES:
            c = self.controller(style, 17)
            canvas = self.canvas(c)
            canvas.grab()
            self.assertEqual(canvas.visual_index, 5)
            c.position = 8
            canvas.grab()
            self.assertEqual(canvas.visual_index, 3)
            c.position = 0
            canvas.grab()
            self.assertEqual(canvas.visual_index, 0)

    def test_animated_playback_scrolls_smoothly_into_the_blank_slot(self):
        for style, _, _ in CORE_STYLES:
            with self.subTest(style=style):
                c = self.controller(style, 4.99)
                c.reduced_motion = False
                canvas = self.canvas(c)
                canvas.grab()
                previous_line = canvas.visual_index
                previous_word = canvas._word_visual
                with patch.object(canvas, "_text", wraps=canvas._text) as text, \
                     patch.object(canvas, "_instrumental") as dots:
                    for position in (5.001, 5.03, 5.1, 5.25, 5.5):
                        c.motion_time += position - c.position
                        c.position = position
                        canvas.grab()
                        self.assertGreaterEqual(canvas.visual_index, previous_line)
                        self.assertLess(canvas.visual_index, 2)
                        self.assertGreaterEqual(canvas._word_visual, previous_word)
                        self.assertLess(canvas._word_visual, 4)
                        self.assertEqual(canvas._active_word, 4)
                        self.assertEqual(text.called, style != "visual")
                        previous_line, previous_word = canvas.visual_index, canvas._word_visual
                        text.reset_mock()
                    dots.assert_not_called()

    def test_new_song_intro_never_retains_the_previous_song(self):
        for style, _, _ in CORE_STYLES:
            c = self.controller(style)
            canvas = self.canvas(c)
            canvas.grab()
            c.lyrics = Lyrics(parse_lrc("[00:00]\n[00:04]An entirely new song"))
            c.generation += 1
            c.position = 0
            with patch.object(canvas, "_shape", wraps=canvas._shape) as shapes, \
                 patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
                canvas.grab()
                rendered = [call.args[0] for call in shapes.call_args_list + words.call_args_list]
                self.assertEqual(bool(rendered), style != "visual")
                self.assertTrue(all("ocean" not in text and "moon" not in text for text in rendered))
            self.assertEqual(canvas.visual_index, 0)

    def test_offset_and_pause_focus_the_correct_gap(self):
        c = self.controller(position=9.5)
        c.offset = 600
        canvas = self.canvas(c)
        canvas.grab()
        self.assertEqual(canvas.visual_index, 4)
        c.offset = -600
        canvas.grab()
        self.assertEqual(canvas.visual_index, 3)
        c.track.playing = False
        before = canvas.grab().toImage()
        c.motion_time += 10
        self.assertEqual(before, canvas.grab().toImage())

    def test_blank_track_has_no_placeholder_dots_or_stale_lyrics(self):
        c = self.controller()
        canvas = self.canvas(c)
        canvas.grab()
        c.lyrics = Lyrics(parse_lrc("[00:00]\n[00:10]"))
        c.generation += 1
        with patch.object(canvas, "_empty", wraps=canvas._empty) as empty, \
             patch.object(canvas, "_text") as text, \
             patch.object(canvas, "_instrumental") as dots:
            canvas.grab()
            empty.assert_not_called()
            text.assert_not_called()
            dots.assert_not_called()
        self.assertEqual(canvas.visual_index, 0)

    def test_gap_keeps_context_above_and_below_a_clear_centre(self):
        for style, _, _ in CORE_STYLES:
            if style == "visual":
                continue  # This style intentionally shows only one word.
            for surface in ("preview", "floating", "immersive"):
                with self.subTest(style=style, surface=surface):
                    c = self.controller(style)
                    c.lyrics = Lyrics(parse_lrc("[00:02]An original ocean\n[00:05]\n[00:10]A new quiet moon"))
                    canvas = self.canvas(c, surface)
                    with patch.object(canvas, "_text", wraps=canvas._text) as text, \
                         patch.object(canvas, "_cutout") as cutout:
                        canvas.grab()
                        centres = [call.args[3] for call in text.call_args_list]
                        self.assertTrue(any(y < canvas.height() / 2 - 20 for y in centres))
                        self.assertTrue(any(y > canvas.height() / 2 + 20 for y in centres))
                        self.assertTrue(all(abs(y - canvas.height() / 2) > 20 for y in centres))
                        cutout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
