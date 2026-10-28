"""Original text exercises the optional library's three distinct lyric stages."""
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_support import ensure_system_fonts
from halo.extra_lyrics import EXTRA_LYRIC_STYLES, LINE_BASED_STYLES, paint_lyric_mode
from halo.lyric_rendering import WordTimeline
from halo.models import Lyrics, LyricLine, Track
from halo.widgets import LyricCanvas


class LibraryLyricCanvas(LyricCanvas):
    """Exercise the optional painter without relying on catalogue integration."""
    def paintEvent(self, event):
        c = self.controller
        key = (id(c.lyrics.lines), c.generation, c.track.duration)
        if self._timeline_key != key:
            self.timeline = WordTimeline(c.lyrics.lines, c.track.duration)
            self._timeline_key = key
            self.type_cache.clear()
            self._last_motion = None
        index, word, fraction = self.timeline.display_at(c.lyrics.index_at(c.position), c.position)
        transition = self._advance(index, word, c.position, c.motion_time)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hit_rows = []
        paint_lyric_mode(self, p, c.lyric_style, index, word, fraction, c.motion_time, transition)
        p.end()


class ExtraLyricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def controller(self, style="lyric_monument"):
        return SimpleNamespace(
            lyrics=Lyrics([LyricLine(0, "The evening finds a quiet home"),
                           LyricLine(4, "Our original light stays a little longer"),
                           LyricLine(8, ""), LyricLine(12, "Let the moon return to the water")]),
            track=Track(duration=18, playing=True), position=5.6, offset=0,
            generation=1, motion_time=10., lyric_style=style, reduced_motion=True,
            primary=QColor("#e0d4f0"), secondary=QColor("#9b88cf"), seek=lambda value: None)

    def canvas(self, c, mode="immersive", size=(800, 500)):
        canvas = LibraryLyricCanvas(c, mode)
        canvas.scene_mode = "lyrics"
        canvas.resize(*size)
        canvas.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.addCleanup(canvas.close)
        return canvas

    def test_catalogue_has_three_original_compositions_and_line_based_metadata(self):
        self.assertEqual([row[1] for row in EXTRA_LYRIC_STYLES], ["Monument", "Marquee", "Afterimage"])
        self.assertEqual(len({row[0] for row in EXTRA_LYRIC_STYLES}), 3)
        self.assertEqual(LINE_BASED_STYLES, {"lyric_monument"})

    def test_unknown_style_does_not_touch_the_painter(self):
        canvas = self.canvas(self.controller())
        painter = Mock()
        self.assertFalse(paint_lyric_mode(canvas, painter, "unknown", 0, 0, 0, 0, 0))
        self.assertEqual(painter.mock_calls, [])

    def test_all_three_compositions_render_distinctly_on_each_surface(self):
        for surface, size in (("preview", (420, 220)), ("floating", (350, 140)),
                              ("immersive", (1000, 620))):
            with self.subTest(surface=surface):
                hashes = set()
                for style, _, _ in EXTRA_LYRIC_STYLES:
                    canvas = self.canvas(self.controller(style), surface, size)
                    image = canvas.grab().toImage()
                    self.assertTrue(any(image.pixelColor(x, y).alpha() for x in range(0, image.width(), 4)
                                        for y in range(0, image.height(), 4)))
                    hashes.add(hashlib.sha256(image.constBits()).hexdigest())
                self.assertEqual(len(hashes), 3)

    def test_blank_break_keeps_context_and_never_shapes_a_music_note(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.position = 9
                canvas = self.canvas(c)
                with patch.object(canvas, "_shape", wraps=canvas._shape) as lines, \
                     patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words, \
                     patch.object(canvas, "_text", wraps=canvas._text) as ink:
                    canvas.grab()
                    self.assertTrue(ink.called)
                    self.assertTrue(all(call.args[0] != "♪" for call in lines.call_args_list + words.call_args_list))
                    for call in ink.call_args_list:
                        x, y = call.args[2:4]
                        self.assertTrue(abs(x - canvas.width() / 2) > 60 or abs(y - canvas.height() / 2) > 35)

    def test_pause_freezes_decoration_even_with_an_external_clock(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.reduced_motion = False
                canvas = self.canvas(c)
                canvas.grab()
                c.motion_time += 1
                canvas.grab()
                c.track.playing = False
                before = canvas.grab().toImage()
                phase = canvas._extra_lyric_motion[2]
                c.motion_time += 20
                self.assertEqual(before, canvas.grab().toImage())
                self.assertEqual(canvas._extra_lyric_motion[2], phase)

    def test_reduced_motion_has_no_ambient_drift(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                canvas = self.canvas(c)
                first = canvas.grab().toImage()
                c.motion_time += 10
                self.assertEqual(first, canvas.grab().toImage())
                self.assertEqual(canvas._extra_lyric_motion[2], 0)

    def test_each_design_has_live_motion_without_a_new_word(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.reduced_motion = False
                canvas = self.canvas(c)
                first = canvas.grab().toImage()
                c.motion_time += .08
                self.assertNotEqual(first, canvas.grab().toImage())

    def test_seeking_and_new_song_use_current_data_without_stale_text(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                canvas = self.canvas(c)
                canvas.grab()
                c.position = 0.2
                canvas.grab()
                self.assertEqual(canvas.visual_index, 0)
                c.lyrics = Lyrics([LyricLine(0, "New original horizon")])
                c.position = .2
                c.generation += 1
                with patch.object(canvas, "_shape", wraps=canvas._shape) as lines, \
                     patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
                    canvas.grab()
                    content = [call.args[0] for call in lines.call_args_list + words.call_args_list]
                    self.assertTrue(content)
                    self.assertFalse(any("evening" in text or "moon" in text for text in content))
                self.assertEqual(canvas._extra_lyric_motion[2], 0)

    def test_long_unicode_fits_and_work_is_bounded_per_frame(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            for text in ("Original horizon " * 18, "原创文字照亮我们的天空" * 12,
                         "हवा में नई रोशनी " * 12, "Original" * 45):
                with self.subTest(style=style, text=text[:8]):
                    c = self.controller(style)
                    c.lyrics = Lyrics([LyricLine(0, text), LyricLine(8, text)])
                    c.position = 3
                    canvas = self.canvas(c, "preview", (230, 140))
                    with patch.object(canvas, "_shape", wraps=canvas._shape) as lines, \
                         patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as words:
                        canvas.grab()
                        self.assertLessEqual(len(lines.call_args_list) + len(words.call_args_list), 20)
                    self.assertLessEqual(len(canvas.type_cache.items), canvas.type_cache.limit)

    def test_visible_text_clicks_use_the_existing_seek_contract(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            with self.subTest(style=style):
                c = self.controller(style)
                c.offset = 250
                positions = []
                c.seek = positions.append
                canvas = self.canvas(c)
                canvas.grab()
                self.assertTrue(canvas._hit_rows)
                rect, line = min(canvas._hit_rows, key=lambda hit: abs(hit[0].center().y() - canvas.height() / 2))
                QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
                self.assertEqual(positions, [max(0, c.lyrics.lines[line].time - .25)])

    def test_rendering_does_not_mutate_source_lines_or_word_boundaries(self):
        for style, _, _ in EXTRA_LYRIC_STYLES:
            c = self.controller(style)
            before = tuple(c.lyrics.lines)
            canvas = self.canvas(c)
            canvas.grab()
            self.assertEqual(tuple(c.lyrics.lines), before)
            self.assertEqual(canvas.timeline.words[0].begin, 0)
            self.assertTrue(all(0 <= line < len(c.lyrics.lines) for _, line in canvas._hit_rows))

    def test_afterimage_outline_cache_reuses_ink_and_has_a_pixel_budget(self):
        c = self.controller("lyric_afterimage")
        canvas = self.canvas(c)
        canvas.grab()
        keys = [entry[1].cacheKey() for entry in canvas._afterimage_outlines.values()]
        self.assertTrue(keys)
        canvas.grab()
        self.assertEqual(keys, [entry[1].cacheKey() for entry in canvas._afterimage_outlines.values()])
        for hue in range(24):
            c.secondary = QColor.fromHsl(hue * 15, 120, 180)
            canvas.grab()
            self.assertLessEqual(len(canvas._afterimage_outlines), 12)
            self.assertLessEqual(canvas._afterimage_outline_pixels, 2_000_000)


if __name__ == "__main__":
    unittest.main()
