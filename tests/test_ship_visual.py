"""Original lyric fixtures exercise the separate whole-line illustrated mode."""
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.lyric_rendering import LYRIC_STYLES, line_symbol_kind
from halo.models import LyricLine, LyricWord, Lyrics, Track
from halo.widgets import LyricCanvas


class ShipVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self):
        return SimpleNamespace(
            lyrics=Lyrics([LyricLine(0, "Our original ocean finds the shore"),
                           LyricLine(4, "A quiet moon above the room"),
                           LyricLine(8, ""),
                           LyricLine(12, "Let this new light find a home")]),
            track=Track(duration=18, playing=True), position=1.2, offset=0,
            motion_time=10., generation=1, lyric_style="ship_visual",
            reduced_motion=False, primary=QColor("#bddbd0"), secondary=QColor("#bd9ec8"),
            seek=lambda value: None,
        )

    def canvas(self, controller, surface="immersive", size=(800, 500)):
        canvas = LyricCanvas(controller, surface)
        canvas.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        canvas.resize(*size)
        self.addCleanup(canvas.close)
        return canvas

    def test_only_illustrated_modes_remain_with_simple_names(self):
        self.assertEqual([(key, label) for key, label, _ in LYRIC_STYLES[:3]],
                         [("ship_visual", "Ship"), ("fisheye_visual", "Fisheye"), ("visual", "Visual")])
        self.assertNotIn("ship", {key for key, _, _ in LYRIC_STYLES})
        self.assertNotIn("fisheye", {key for key, _, _ in LYRIC_STYLES})

    def test_wrapped_lyric_symbols_align_with_first_ink_line_and_remain_clickable(self):
        for words in ("Our original heart stays close while this long quiet sentence wraps onto another line",
                      "हमारी नई कहानी रोशनी के साथ धीरे धीरे आगे बढ़ती रहती है और फिर घर लौट आती है"):
            with self.subTest(words=words[:12]):
                c = self.controller()
                c.lyrics = Lyrics([LyricLine(2, words)])
                c.position = 3
                c.reduced_motion = True
                positions = []
                c.seek = positions.append
                canvas = self.canvas(c, "immersive", (700, 450))
                with patch.object(canvas, "_text", wraps=canvas._text) as text, \
                     patch.object(canvas, "_line_emblem", wraps=canvas._line_emblem) as emblems:
                    canvas.grab()
                    shape = text.call_args.args[1]
                    scale = text.call_args.args[6]
                    text_y = text.call_args.args[3]
                    symbol_y = emblems.call_args.args[3]
                    expected = text_y + (shape.first_line_center - shape.bounds.center().y()) * scale
                    self.assertLess(symbol_y, text_y - 5)
                    self.assertAlmostEqual(symbol_y, expected)
                    point = QPointF(emblems.call_args.args[2], symbol_y).toPoint()
                QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
                self.assertEqual(positions, [2])

    def test_cue_illustration_prefers_imagery_over_common_pronouns(self):
        self.assertEqual(line_symbol_kind("You and the ocean"), "wave")
        self.assertEqual(line_symbol_kind("Our original moon"), "moon")
        self.assertEqual(line_symbol_kind("An original quiet heart"), "heart")
        self.assertEqual(line_symbol_kind("An original quiet phrase"), "star")
        for i in range(400):
            line_symbol_kind("Original phrase " + str(i))
        self.assertLessEqual(line_symbol_kind.cache_info().currsize, 256)

    def test_context_lines_are_smaller_and_quieter_than_the_focused_line(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(0, "A quiet original heart"),
                           LyricLine(4, "A quiet original heart"),
                           LyricLine(8, "A quiet original heart")])
        c.position = 5
        c.reduced_motion = True
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                canvas = self.canvas(c, surface)
                with patch.object(canvas, "_text", wraps=canvas._text) as text:
                    canvas.grab()
                    active = min(text.call_args_list, key=lambda call: abs(call.args[3] - canvas.height() / 2))
                    self.assertEqual(active.args[6], 1.)
                    context = [call for call in text.call_args_list if call is not active]
                    self.assertEqual(len(context), 2)
                    for call in context:
                        self.assertLess(call.args[6], active.args[6] * .75)
                        self.assertLess(call.args[5], active.args[5] * .55)

    def test_symbols_have_no_enclosing_circles_arcs_or_orbiting_pins(self):
        c = self.controller()
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                canvas = self.canvas(c, surface)
                image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                spy = Mock(wraps=painter)
                try:
                    canvas._line_emblem(spy, "heart", 80, 80, 20, 1, 1, 2)
                    self.assertTrue(spy.drawPath.called)
                    spy.drawArc.assert_not_called()
                    spy.drawEllipse.assert_not_called()
                finally:
                    painter.end()

    def test_legacy_names_render_the_same_retained_illustrated_modes(self):
        for old, retained in (("ship", "ship_visual"), ("fisheye", "fisheye_visual")):
            for surface in ("preview", "floating", "immersive"):
                with self.subTest(old=old, surface=surface):
                    c = self.controller()
                    c.reduced_motion = True
                    c.lyric_style = old
                    old_image = self.canvas(c, surface).grab().toImage()
                    c.lyric_style = retained
                    self.assertEqual(old_image, self.canvas(c, surface).grab().toImage())

    def test_distinct_render_for_every_style_on_all_native_surfaces(self):
        for surface, size in (("preview", (420, 220)), ("floating", (350, 140)),
                              ("immersive", (960, 600))):
            with self.subTest(surface=surface):
                hashes = set()
                for style, _, _ in LYRIC_STYLES:
                    c = self.controller()
                    c.lyric_style = style
                    image = self.canvas(c, surface, size).grab().toImage()
                    hashes.add(hashlib.sha256(image.constBits()).hexdigest())
                self.assertEqual(len(hashes), len(LYRIC_STYLES))

    def test_line_text_and_cue_illustration_ignore_word_changes(self):
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                c = self.controller()
                canvas = self.canvas(c, surface)
                with patch.object(canvas, "_text", wraps=canvas._text) as text, \
                     patch.object(canvas, "_line_emblem", wraps=canvas._line_emblem) as emblems, \
                     patch.object(canvas, "_cutout") as cutout:
                    canvas.grab()
                    first_text = [call.args[2:] for call in text.call_args_list]
                    first_emblems = [call.args[1] for call in emblems.call_args_list]
                    text.reset_mock()
                    emblems.reset_mock()
                    c.position = 3.8
                    c.motion_time += 2.6
                    canvas.grab()
                    self.assertEqual(first_text, [call.args[2:] for call in text.call_args_list])
                    self.assertEqual(first_emblems, [call.args[1] for call in emblems.call_args_list])
                    self.assertTrue(all(call.args[4] == c.primary for call in text.call_args_list))
                    cutout.assert_not_called()

    def test_old_ship_name_uses_the_illustrated_whole_line_mode(self):
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                c = self.controller()
                c.lyric_style = "ship"
                c.reduced_motion = True
                canvas = self.canvas(c, surface)
                with patch.object(canvas, "_line_emblem") as emblem:
                    first = canvas.grab().toImage()
                    c.position = 3.8
                    c.motion_time += 2.6
                    self.assertEqual(first, canvas.grab().toImage())
                    self.assertTrue(emblem.called)

    def test_word_heavy_cues_scroll_smoothly_and_seek_resets(self):
        c = self.controller()
        canvas = self.canvas(c)
        canvas._advance(0, 0, 0, 10)
        canvas._advance(1, 60, .033, 10.033)
        self.assertGreater(canvas.visual_index, 0)
        self.assertLess(canvas.visual_index, .1)
        canvas._advance(3, 70, 12.1, 10.066)
        self.assertEqual(canvas.visual_index, 3)
        canvas._advance(0, 1, .1, 10.099)
        self.assertEqual(canvas.visual_index, 0)
        c.generation += 1
        canvas._advance(1, 62, .133, 10.132)
        self.assertEqual(canvas.visual_index, 1)
        self.assertEqual(canvas._line_velocity, 0)

    def test_pause_freezes_ambient_motion_and_partial_scroll(self):
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                c = self.controller()
                c.position = 3.99
                canvas = self.canvas(c, surface)
                canvas.grab()
                c.position = 4.01
                c.motion_time += .033
                canvas.grab()
                c.track.playing = False
                before = canvas.grab().toImage()
                state = (canvas.visual_index, canvas._line_art_motion)
                c.motion_time += 10  # Even a badly behaved external preview clock.
                self.assertEqual(before, canvas.grab().toImage())
                self.assertEqual(state, (canvas.visual_index, canvas._line_art_motion))
                c.track.playing = True
                c.motion_time += .016
                canvas.grab()
                self.assertGreater(canvas.visual_index, state[0])
                self.assertLess(canvas._line_art_motion - state[1], .02)

    def test_reduced_motion_has_no_drift_but_updates_cue_immediately(self):
        c = self.controller()
        c.reduced_motion = True
        canvas = self.canvas(c)
        first = canvas.grab().toImage()
        c.motion_time += 2
        c.position = 3.2
        self.assertEqual(first, canvas.grab().toImage())
        c.motion_time += .033
        c.position = 4.01
        self.assertNotEqual(first, canvas.grab().toImage())
        self.assertEqual(canvas.visual_index, 1)
        self.assertEqual(canvas._line_art_motion, 0)

    def test_line_boundary_has_no_discrete_colour_or_illustration_swap(self):
        c = self.controller()
        c.position = 3.999
        canvas = self.canvas(c)
        first = canvas.grab().toImage()
        c.position = 4.0001
        self.assertEqual(first, canvas.grab().toImage())

    def test_supplied_word_start_does_not_hide_whole_line(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(0, "Original light", (LyricWord("Original ", 1, 2),
                                                         LyricWord("light", 2, 4)))])
        c.position = .1
        canvas = self.canvas(c)
        with patch.object(canvas, "_ship_visual", wraps=canvas._ship_visual) as full_line, \
             patch.object(canvas, "_instrumental") as waiting:
            canvas.grab()
            full_line.assert_called_once()
            waiting.assert_not_called()

    def test_clicking_text_or_illustration_seeks_with_correction(self):
        c = self.controller()
        c.offset = 250
        positions = []
        c.seek = positions.append
        canvas = self.canvas(c, "preview", (500, 260))
        canvas.grab()
        rect, line = next((rect, line) for rect, line in canvas._hit_rows if line == 1)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
        self.assertEqual(positions, [c.lyrics.lines[line].time - .25])
        positions.clear()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton,
                         pos=(rect.topLeft() + (rect.bottomLeft() - rect.topLeft()) * .5).toPoint())
        self.assertEqual(positions, [c.lyrics.lines[line].time - .25])

    def test_long_unicode_and_narrow_surfaces_fit_without_unbounded_cache(self):
        for surface, size in (("preview", (230, 140)), ("floating", (350, 140)),
                              ("immersive", (800, 500))):
            for text in ("Original horizon " * 20, "原创文字照亮我们的天空" * 12,
                         "हवा में नई रोशनी " * 12, "Original" * 50):
                with self.subTest(surface=surface, text=text[:12]):
                    c = self.controller()
                    c.lyrics = Lyrics([LyricLine(0, text)])
                    canvas = self.canvas(c, surface, size)
                    with patch.object(canvas, "_text", wraps=canvas._text) as shaped:
                        canvas.grab()
                        self.assertTrue(shaped.call_args_list)
                        for call in shaped.call_args_list:
                            shape, x, y, _, _, scale = call.args[1:7]
                            self.assertGreaterEqual(x - shape.bounds.width() * scale / 2, 0)
                            self.assertLessEqual(x + shape.bounds.width() * scale / 2, canvas.width())
                            self.assertGreaterEqual(y - shape.bounds.height() * scale / 2, 0)
                            self.assertLessEqual(y + shape.bounds.height() * scale / 2, canvas.height())
                    self.assertLessEqual(len(canvas.type_cache.items), canvas.type_cache.limit)

    def test_instrumental_focuses_blank_row_and_new_generation_replaces_emblems(self):
        c = self.controller()
        canvas = self.canvas(c)
        canvas.grab()
        c.position = 8.5
        c.motion_time += .033
        with patch.object(canvas, "_line_emblem", wraps=canvas._line_emblem) as emblem, \
             patch.object(canvas, "_instrumental", wraps=canvas._instrumental) as waiting:
            canvas.grab()
            self.assertTrue(emblem.called)
            self.assertEqual(canvas.visual_index, 2)
            waiting.assert_not_called()
        c.lyrics = Lyrics([LyricLine(0, "A new original heart")])
        c.position = .1
        c.generation += 1
        with patch.object(canvas, "_line_emblem", wraps=canvas._line_emblem) as emblem:
            canvas.grab()
            self.assertEqual(emblem.call_args.args[1], "heart")
            self.assertEqual(canvas.visual_index, 0)
            self.assertEqual(canvas._line_art_motion, 0)

    def test_floating_outline_cache_reuses_work_and_is_bounded_across_palettes(self):
        c = self.controller()
        canvas = self.canvas(c, "floating", (680, 220))
        canvas.grab()
        rasters = [entry[1].cacheKey() for entry in canvas._line_text_rasters.values()]
        self.assertTrue(rasters)
        canvas.grab()
        self.assertEqual(rasters, [entry[1].cacheKey() for entry in canvas._line_text_rasters.values()])
        for hue in range(30):
            c.primary = QColor.fromHsl(hue * 10, 100, 200)
            canvas.grab()
            self.assertLessEqual(len(canvas._line_text_rasters), 12)
            self.assertLessEqual(canvas._line_text_pixels, 2_000_000)
        c.lyrics = Lyrics([LyricLine(0, "An original new ocean")])
        c.generation += 1
        canvas.grab()
        self.assertEqual(len(canvas._line_text_rasters), 1)
        self.assertEqual(canvas._line_text_pixels,
                         sum(entry[2] for entry in canvas._line_text_rasters.values()))


if __name__ == "__main__":
    unittest.main()
