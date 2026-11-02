"""Fisheye through the GPU lens, with mock renderers and original lyric fixtures."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_support import channels_over_alpha, ensure_system_fonts
from halo.app import Controller, MainWindow
from halo.lens import (LENS_STRENGTH, LensBudget, lens_geometry, lens_status_text, magnification, output_y,
                       shared_lens, shutdown_lens, warp_source)
from halo.models import LyricLine, Lyrics, Track
from halo.widgets import WHITE, LyricCanvas

OFF_TEXT = "The GPU lens is off on this PC, so Fisheye uses standard drawing."


class FisheyeLensTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

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

    def canvas(self, controller, surface="immersive", size=(800, 500)):
        canvas = LyricCanvas(controller, surface)
        canvas.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        canvas.resize(*size)
        self.addCleanup(canvas.close)
        return canvas

    def renderer(self):
        lens = Mock(available=True, budget=LensBudget())

        def warped(image, output):
            result = QImage(output, QImage.Format.Format_ARGB32_Premultiplied)
            result.fill(Qt.GlobalColor.transparent)
            return result
        lens.apply.side_effect = warped
        return lens

    def lensed(self, controller, surface="immersive", size=(800, 500)):
        canvas = self.canvas(controller, surface, size)
        lens = self.renderer()
        patcher = patch.object(LyricCanvas, "_lens_ready", return_value=lens)
        patcher.start()
        self.addCleanup(patcher.stop)
        return canvas, lens

    def text_calls(self, canvas):
        """A _text spy that notes whether each call drew into the lens source. Only grab() can tell them apart."""
        calls = []
        real = canvas._text

        def spy(p, shape, x, y, color, opacity=1, scale=1, angle=0):
            calls.append(SimpleNamespace(source=isinstance(p.device(), QImage), x=x, y=y, at=p.transform().map(QPointF(x, y)),
                                         size=p.transform().m11(), color=color, opacity=opacity, scale=scale))
            real(p, shape, x, y, color, opacity, scale, angle)
        return calls, patch.object(canvas, "_text", side_effect=spy)

    def source_scale(self, canvas, lens):
        return lens_geometry(canvas.width(), canvas.height(), canvas.devicePixelRatioF(),
                             lens.budget.scale).source_per_logical

    def test_hidden_canvas_stays_on_painter(self):
        self.assertIsNone(self.canvas(self.controller())._lens_ready())

    def test_environment_switch_stays_on_painter(self):
        canvas = self.canvas(self.controller())
        canvas.show()
        with patch.dict(os.environ, {"HALO_DISABLE_LENS": "1"}):
            self.assertIsNone(canvas._lens_ready())

    def test_tiny_canvas_stays_on_painter(self):
        canvas = self.canvas(self.controller(), size=(200, 100))
        canvas.show()
        self.assertIsNone(canvas._lens_ready())

    def test_ready_needs_an_available_renderer_within_budget(self):
        canvas = self.canvas(self.controller())
        canvas.show()
        lens = self.renderer()
        with patch("halo.widgets.shared_lens", return_value=lens), patch.dict(os.environ):
            os.environ.pop("HALO_DISABLE_LENS", None)
            self.assertIs(canvas._lens_ready(), lens)
            lens.budget.enabled = False
            self.assertIsNone(canvas._lens_ready())
            lens.budget.enabled = True
            lens.available = False
            self.assertIsNone(canvas._lens_ready())

    def test_paused_frame_reuses_the_last_result(self):
        c = self.controller()
        canvas, lens = self.lensed(c)
        with patch.object(lens.budget, "record", wraps=lens.budget.record) as record:
            canvas.grab()
            canvas.grab()
            self.assertEqual(lens.apply.call_count, 1)
            self.assertEqual(record.call_count, 1)
            c.motion_time += .016
            canvas.grab()
            self.assertEqual(lens.apply.call_count, 2)
            self.assertEqual(record.call_count, 2)

    def test_scene_change_while_paused_redraws_the_source(self):
        c = self.controller()
        canvas, lens = self.lensed(c)
        canvas.resize(1600, 900)
        canvas.grab()
        canvas.scene_mode = "lyrics"
        canvas.grab()
        self.assertEqual(lens.apply.call_count, 2)

    def test_failed_pass_uses_painter_in_the_same_frame(self):
        canvas, lens = self.lensed(self.controller())
        lens.apply.side_effect = None
        lens.apply.return_value = None
        with patch.object(canvas, "_fisheye", wraps=canvas._fisheye) as painter:
            canvas.grab()
        painter.assert_called_once()
        self.assertTrue(canvas._hit_rows)

    def test_break_uses_painter(self):
        canvas, lens = self.lensed(self.controller())
        canvas.grab()
        lens.apply.reset_mock()
        self.assertFalse(canvas._fisheye_lens(Mock(), -1, -1, 10.))
        lens.apply.assert_not_called()

    def test_every_surface_goes_through_the_lens(self):
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                canvas, lens = self.lensed(self.controller(), surface)
                with patch.object(canvas, "_fisheye") as painter:
                    canvas.grab()
                lens.apply.assert_called_once()
                painter.assert_not_called()

    def test_hero_is_drawn_crisp_above_the_lens(self):
        c = self.controller()
        canvas, lens = self.lensed(c)
        calls, spy = self.text_calls(canvas)
        with spy:
            canvas.grab()
        hero = calls[-1]
        self.assertFalse(hero.source)
        self.assertEqual(hero.color, WHITE)
        self.assertAlmostEqual(hero.scale, 1, 3)
        self.assertAlmostEqual(hero.y, canvas.height() / 2, 1)
        self.assertEqual(canvas._word_visual, round(canvas._word_visual))
        neighbours = calls[:-1]
        self.assertTrue(neighbours)
        self.assertTrue(all(call.source for call in neighbours))
        self.assertTrue(all(call.color == c.primary for call in neighbours))
        scale = self.source_scale(canvas, lens)
        self.assertTrue(all(abs(call.at.y() / scale - canvas.height() / 2) > 1 for call in neighbours))

    def test_lens_result_is_under_the_hero(self):
        canvas, lens = self.lensed(self.controller())

        def opaque(image, output):
            result = QImage(output, QImage.Format.Format_ARGB32_Premultiplied)
            result.fill(QColor("#102030"))
            return result
        lens.apply.side_effect = opaque
        image = canvas.grab().toImage()
        row = {image.pixelColor(x, image.height() // 2).rgb() for x in range(image.width())}
        self.assertIn(QColor("#102030").rgb(), row)
        self.assertIn(WHITE.rgb(), row)

    def test_source_uses_the_pinned_layout(self):
        c = self.controller()
        canvas, lens = self.lensed(c)
        calls, spy = self.text_calls(canvas)
        with spy, patch.object(canvas, "_word_shape", wraps=canvas._word_shape) as shapes:
            canvas.grab()
        w, h = canvas.width(), canvas.height()
        flat = 1 - LENS_STRENGTH
        self.assertEqual(shapes.call_args.args[1:], (w * .65 * .46 / flat, h * .125 * 1.16 / flat,
                                                     canvas._base_size() * 1.30))
        scale = self.source_scale(canvas, lens)
        neighbours = calls[:-1]
        self.assertTrue(neighbours)
        for call in neighbours:
            distance = abs(call.at.y() / scale - h / 2) / (h * .125)
            self.assertAlmostEqual(distance, round(distance), 4)
            self.assertAlmostEqual(call.opacity, max(.2, 1 - distance * .2), 4)
            self.assertAlmostEqual(call.size, scale * flat, 6)
            self.assertAlmostEqual(call.at.x() / scale, w * .65 / 2, 4)

    def test_hero_symbol_clears_a_wide_word(self):
        c = self.controller()
        c.lyrics = Lyrics([LyricLine(0, "Understanding quiet mornings")])
        c.position = .1
        canvas, lens = self.lensed(c)
        spots = []
        real = canvas._symbol

        def spy(p, word, x, y, radius, opacity, motion):
            spots.append(p.transform().map(QPointF(x, y)).x())
            real(p, word, x, y, radius, opacity, motion)
        with patch.object(canvas, "_symbol", side_effect=spy), \
             patch.object(canvas, "_text", wraps=canvas._text) as text:
            canvas.grab()
        hero = text.call_args.args[1]
        reach = canvas.width() * .65 / 2
        edge = warp_source(hero.bounds.width() / 2 / reach, 0)[0]
        symbol = (spots[0] / self.source_scale(canvas, lens) - reach) / reach
        self.assertLess(symbol, -edge)

    def test_hero_follows_the_lens_between_words(self):
        c = self.controller()
        canvas, lens = self.lensed(c)
        canvas.grab()
        word_index = canvas._active_word
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        canvas._word_visual = word_index + .3
        calls, spy = self.text_calls(canvas)
        with spy:
            self.assertTrue(canvas._fisheye_lens(painter, 0, word_index, c.motion_time))
        painter.end()
        h = canvas.height()
        ny = output_y(-.3 * .25)
        self.assertAlmostEqual(calls[-1].y, h / 2 + h / 2 * ny, 6)
        self.assertAlmostEqual(calls[-1].scale, magnification(ny) * (1 - LENS_STRENGTH), 6)
        self.assertLess(calls[-1].scale, 1)

    def test_no_hero_over_an_instrumental_gap(self):
        c = self.controller()
        c.position = 9
        canvas, lens = self.lensed(c)
        calls, spy = self.text_calls(canvas)
        with spy:
            canvas.grab()
        lens.apply.assert_called_once()
        self.assertTrue(calls)
        self.assertTrue(all(call.source and call.color == c.primary for call in calls))

    def test_hero_past_the_last_word_is_skipped(self):
        c = self.controller()
        c.position = 16
        canvas, lens = self.lensed(c)
        canvas.grab()
        word_index = canvas._active_word
        canvas._word_visual = word_index + .7
        image = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        calls, spy = self.text_calls(canvas)
        with spy:
            self.assertTrue(canvas._fisheye_lens(painter, 0, word_index, c.motion_time))
        painter.end()
        self.assertTrue(calls)
        self.assertTrue(all(call.color == c.primary for call in calls))

    def test_clicks_follow_the_mapped_positions(self):
        c = self.controller()
        c.position = 3.9
        seeks = []
        c.seek = seeks.append
        canvas, lens = self.lensed(c)
        canvas.grab()
        h = canvas.height()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(canvas.width() // 2, h // 2))
        self.assertEqual(seeks, [0])
        below = round(h / 2 + h / 2 * output_y(.25))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(canvas.width() // 2, below))
        self.assertEqual(seeks, [0, 4])

    def test_clicks_beside_a_word_do_not_seek(self):
        c = self.controller()
        seeks = []
        c.seek = seeks.append
        canvas, lens = self.lensed(c)
        canvas.grab()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(4, canvas.height() // 2))
        self.assertEqual(seeks, [])

    def test_display_scaling_uses_physical_source_size(self):
        canvas, lens = self.lensed(self.controller())
        with patch.object(canvas, "devicePixelRatioF", return_value=1.5):
            canvas.grab()
        image, output = lens.apply.call_args.args
        expected = lens_geometry(800, 500, 1.5, lens.budget.scale)
        self.assertEqual(image.size(), expected.source)
        self.assertEqual(output, expected.output)
        self.assertEqual(image.format(), QImage.Format.Format_RGBA8888_Premultiplied)

    def test_budget_step_changes_the_next_source_size(self):
        canvas, lens = self.lensed(self.controller())
        dpr = canvas.devicePixelRatioF()
        canvas.grab()
        before = lens.apply.call_args.args[0].size()
        lens.budget.scale = 1.
        canvas.grab()
        after = lens.apply.call_args.args[0].size()
        self.assertEqual(after, lens_geometry(800, 500, dpr, 1.).source)
        self.assertLess(after.width(), before.width())

    def test_reduced_motion_keeps_the_lens(self):
        c = self.controller()
        c.reduced_motion = True
        canvas, lens = self.lensed(c)
        canvas.grab()
        lens.apply.assert_called_once()

    def test_ship_never_calls_the_lens(self):
        c = self.controller()
        c.lyric_style = "ship_visual"
        canvas, lens = self.lensed(c)
        with patch.object(canvas, "_fisheye_lens") as path:
            canvas.grab()
        path.assert_not_called()
        lens.apply.assert_not_called()


class RealLensCanvasTests(unittest.TestCase):
    """The real shared renderer behind a visible canvas, which WA_DontShowOnScreen keeps off the screen."""
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_system_fonts()

    def real_canvas(self):
        shutdown_lens()
        self.addCleanup(shutdown_lens)
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("HALO_DISABLE_LENS", None)
        lens = shared_lens()
        if not lens.available:
            self.skipTest(f"No OpenGL lens on this PC: {lens.reason}")
        c = FisheyeLensTests.controller(self)
        canvas = LyricCanvas(c, "immersive")
        canvas.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        canvas.resize(966, 522)
        canvas.show()
        self.addCleanup(canvas.close)
        return c, canvas, lens

    def test_fisheye_paints_through_the_real_lens(self):
        c, canvas, lens = self.real_canvas()
        self.assertTrue(canvas.isVisible())
        with patch.object(lens, "apply", wraps=lens.apply) as apply:
            canvas.grab()
        apply.assert_called_once()
        self.assertEqual(len(lens.budget._frames), 1)
        image = canvas._lens_image
        self.assertEqual(image.size(), lens_geometry(966, 522, canvas.devicePixelRatioF(), lens.budget.scale).output)
        self.assertGreater(max(image.pixelColor(x, y).alpha() for x in range(0, image.width(), 5)
                               for y in range(0, image.height(), 5)), 200)
        self.assertEqual(channels_over_alpha(image), 0)

    def test_the_frame_that_rebuilds_the_lens_stays_out_of_the_budget(self):
        c, canvas, lens = self.real_canvas()
        canvas.grab()
        lens.release()
        c.motion_time += .016
        canvas.grab()
        self.assertIsNotNone(lens._context)
        self.assertEqual(len(lens.budget._frames), 1)
        c.motion_time += .016
        canvas.grab()
        self.assertEqual(len(lens.budget._frames), 2)

    def test_a_budget_that_gives_up_releases_the_gpu_objects_right_away(self):
        c, canvas, lens = self.real_canvas()
        canvas.grab()
        destroyed = Mock()
        lens._context.aboutToBeDestroyed.connect(destroyed)
        lens.budget.scale = 1.
        lens.budget._frames.extend([30] * 29)
        c.motion_time += .016
        canvas.grab()
        self.assertFalse(lens.budget.enabled)
        destroyed.assert_called_once()
        self.assertIsNone(lens._context)
        self.assertEqual(len(lens._targets), 0)
        self.assertEqual(lens_status_text(), OFF_TEXT)
        c.motion_time += .016
        with patch.object(canvas, "_fisheye", wraps=canvas._fisheye) as painter:
            canvas.grab()
        painter.assert_called_once()
        self.assertIsNone(lens._context)


class LensStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_status_text_appears_when_off(self):
        with patch("halo.lens._shared", Mock(available=False)):
            self.assertEqual(lens_status_text(), OFF_TEXT)

    def main_window(self):
        unused = patch("halo.lens._shared", None)
        unused.start()
        self.addCleanup(unused.stop)
        temp = tempfile.TemporaryDirectory(prefix="halo-lens-", dir=Path(__file__).resolve().parents[1] / ".cache")
        self.addCleanup(temp.cleanup)
        settings = QSettings(str(Path(temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        c = Controller(settings, offline=True)
        c.timer.stop()
        window = MainWindow(c)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.settings_dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)

        def clean_window():
            window.settings_dialog.hide()
            window.draw_timer.stop()
            window.tray.hide()
            for widget in [window.immersive, window.overlay, *window.edges]:
                widget.hide()
                widget.deleteLater()
            c.close()
            c.audio.thread.join(1)
            window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        self.addCleanup(clean_window)
        return window

    def test_settings_line_shows_only_while_off(self):
        studio = self.main_window().settings_dialog
        self.assertEqual(studio.lens_status.text(), "")
        self.assertTrue(studio.lens_status.isHidden())
        self.assertTrue(studio.lens_status.wordWrap())
        with patch("halo.lens._shared", Mock(available=False)):
            studio.sync_lyrics()
            self.assertEqual(studio.lens_status.text(), OFF_TEXT)
            self.assertFalse(studio.lens_status.isHidden())
        studio.sync_lyrics()
        self.assertEqual(studio.lens_status.text(), "")
        self.assertTrue(studio.lens_status.isHidden())

    def test_opening_settings_reports_a_lens_that_went_off_since_the_last_sync(self):
        window = self.main_window()
        studio = window.settings_dialog
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()
        self.assertFalse(studio.isVisible())
        self.assertTrue(studio.lens_status.isHidden())
        with patch("halo.lens._shared", Mock(available=False)):
            window.open_settings_section("lyrics")
            self.app.processEvents()
            self.assertEqual(studio.lens_status.text(), OFF_TEXT)
            self.assertTrue(studio.lens_status.isVisible())
            window.navigate("listening")
            self.app.processEvents()
        self.assertFalse(studio.isVisible())
        window.open_settings_section("lyrics")
        self.app.processEvents()
        self.assertEqual(studio.lens_status.text(), "")
        self.assertFalse(studio.lens_status.isVisible())


if __name__ == "__main__":
    unittest.main()
