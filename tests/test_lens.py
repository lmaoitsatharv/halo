"""The Fisheye lens maths, its frame budget and the OpenGL renderer behind it."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, QSize, Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage, QPainter, QSurfaceFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qt_support import channels_over_alpha
import halo.lens
from halo.app import Controller
from halo.lens import (LENS_STRENGTH, MAX_OUTPUT_PIXELS, LensBudget, LensRenderer, lens_disabled, lens_geometry,
                       lens_status_text, magnification, output_y, shared_lens, shutdown_lens, warp_source)

OFF_TEXT = "The GPU lens is off on this PC, so Fisheye uses standard drawing."


class LensMathTests(unittest.TestCase):
    def test_mapping_centre_edge_and_round_trip(self):
        self.assertEqual(warp_source(0, 0), (0, 0))
        self.assertAlmostEqual(warp_source(0, 1)[1], 1)
        self.assertAlmostEqual(magnification(0), 1 / .45, 3)
        for y in (-.9, -.4, 0, .3, .8):
            self.assertAlmostEqual(output_y(warp_source(0, y)[1]), y, 3)

    def test_mapping_counts_across_less_than_down(self):
        sx, _ = warp_source(.5, 0)
        _, sy = warp_source(0, .5)
        self.assertAlmostEqual(sx, .5 * (1 - LENS_STRENGTH + LENS_STRENGTH * .35 * .25))
        self.assertAlmostEqual(sy, .5 * (1 - LENS_STRENGTH + LENS_STRENGTH * .25))
        self.assertLess(sx, sy)

    def test_output_y_is_odd_and_covers_sources_beyond_the_unit_range(self):
        self.assertAlmostEqual(output_y(0), 0, 6)
        self.assertAlmostEqual(output_y(-.6), -output_y(.6), 6)
        self.assertLess(output_y(1.4), 1.4)
        self.assertAlmostEqual(warp_source(0, output_y(1.4))[1], 1.4, 6)

    def test_magnification_is_the_inverse_slope_of_the_mapping(self):
        step = 1e-5
        for y in (-.8, -.2, 0, .5, .9):
            slope = (warp_source(0, y + step)[1] - warp_source(0, y - step)[1]) / (2 * step)
            self.assertAlmostEqual(magnification(y) * slope, 1, 5)
        self.assertGreater(magnification(0), magnification(.9))

    def test_geometry_crops_to_the_word_column(self):
        g = lens_geometry(1920, 1080, 1, 1)
        self.assertEqual((g.column.width(), g.output.width(), g.output.height()), (1248, 1248, 1080))
        self.assertEqual((g.column.x(), g.column.y(), g.column.height()), (336, 0, 1080))

    def test_geometry_uses_physical_pixels_and_source_scale(self):
        g = lens_geometry(1000, 500, 1.5, 1.25)
        self.assertEqual((g.output.width(), g.output.height()), (975, 750))
        self.assertEqual((g.source.width(), g.source.height()), (1219, 938))
        self.assertAlmostEqual(g.source_per_logical, 1.5 * 1.25)

    def test_geometry_caps_output_pixels(self):
        g = lens_geometry(3840, 2160, 1, 1)
        self.assertLessEqual(g.output.width() * g.output.height(), MAX_OUTPUT_PIXELS)
        self.assertGreater(g.output.width() * g.output.height(), MAX_OUTPUT_PIXELS * .98)
        self.assertAlmostEqual(g.output.width() / g.output.height(), 2496 / 2160, 2)
        self.assertAlmostEqual(g.source_per_logical, g.output.width() / g.column.width(), 3)

    def test_geometry_derives_the_source_from_the_capped_output(self):
        g = lens_geometry(3840, 2160, 1, 1.25)
        self.assertEqual(g.source, QSize(round(g.output.width() * 1.25), round(g.output.height() * 1.25)))

    def test_geometry_never_returns_an_empty_size(self):
        g = lens_geometry(.4, .4, 1, 1)
        self.assertEqual((g.output.width(), g.output.height(), g.source.width(), g.source.height()), (1, 1, 1, 1))


class LensBudgetTests(unittest.TestCase):
    def test_sustained_slow_frames_step_down_after_30_frames(self):
        budget = LensBudget()
        for _ in range(29):
            budget.record(30)
        self.assertEqual(budget.scale, 1.25)
        budget.record(30)
        self.assertEqual(budget.scale, 1.)
        for _ in range(30):
            budget.record(30)
        self.assertFalse(budget.enabled)

    def test_one_stall_among_frames_near_the_limit_changes_nothing(self):
        budget = LensBudget()
        for ms in ([11.5] * 14 + [150] + [11.5] * 15) * 3:
            budget.record(ms)
        self.assertEqual((budget.scale, budget.enabled), (1.25, True))

    def test_budget_judges_the_median_rather_than_the_mean(self):
        budget = LensBudget()
        for ms in [9] * 14 + [13] * 16:
            budget.record(ms)
        self.assertEqual(budget.scale, 1.)

    def test_budget_ignores_frames_within_the_limit(self):
        budget = LensBudget()
        for _ in range(90):
            budget.record(11)
        self.assertEqual((budget.scale, budget.enabled), (1.25, True))

    def test_budget_judges_the_new_scale_on_its_own_frames(self):
        budget = LensBudget()
        for _ in range(30):
            budget.record(30)
        self.assertEqual(budget.scale, 1.)
        for _ in range(29):
            budget.record(30)
        self.assertTrue(budget.enabled)

    def test_one_slow_frame_among_fast_ones_changes_nothing(self):
        budget = LensBudget()
        for ms in [100] + [5] * 59:
            budget.record(ms)
        self.assertEqual((budget.scale, budget.enabled), (1.25, True))

    def test_a_disabled_budget_stays_disabled(self):
        budget = LensBudget()
        for _ in range(60):
            budget.record(30)
        self.assertFalse(budget.enabled)
        for _ in range(90):
            budget.record(1)
        self.assertEqual((budget.scale, budget.enabled), (1., False))

    def test_a_skipped_frame_is_left_out_once(self):
        budget = LensBudget()
        budget.skip_next()
        budget.record(500)
        self.assertEqual(len(budget._frames), 0)
        budget.record(5)
        self.assertEqual(list(budget._frames), [5])


class LensRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def renderer(self):
        """A real renderer, or a skipped test on a PC without OpenGL 3.3."""
        renderer = LensRenderer()
        self.addCleanup(renderer.close)
        if not renderer.available:
            self.skipTest(f"No OpenGL lens on this PC: {renderer.reason}")
        return renderer

    @staticmethod
    def source(width, height):
        image = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        return image

    @staticmethod
    def ramp(width, height):
        """Grey that brightens from the top row to the bottom row."""
        image = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
        painter = QPainter(image)
        for y in range(height):
            level = round(255 * (y + .5) / height)
            painter.fillRect(0, y, width, 1, QColor(level, level, level))
        painter.end()
        return image

    def test_environment_switch_disables_the_renderer(self):
        with patch.dict(os.environ, {"HALO_DISABLE_LENS": "1"}):
            self.assertTrue(lens_disabled())
            renderer = LensRenderer()
        self.assertFalse(renderer.available)
        self.assertIn("HALO_DISABLE_LENS", renderer.reason)
        self.assertIsNone(renderer.apply(self.source(10, 10), QSize(10, 10)))

    def test_only_one_turns_the_switch_on(self):
        for value in ("0", "", "true"):
            with patch.dict(os.environ, {"HALO_DISABLE_LENS": value}):
                self.assertFalse(lens_disabled())
        with patch.dict(os.environ):
            os.environ.pop("HALO_DISABLE_LENS", None)
            self.assertFalse(lens_disabled())

    def test_context_failure_turns_lens_off_and_logs_once(self):
        with patch("halo.lens.QOpenGLContext.create", return_value=False):
            with self.assertLogs("halo.lens", "WARNING") as logs:
                renderer = LensRenderer()
        self.assertFalse(renderer.available)
        self.assertIsNone(renderer.apply(QImage(), QSize(10, 10)))
        self.assertEqual(len(logs.records), 1)

    def test_context_asks_to_hear_about_a_gpu_reset(self):
        with patch("halo.lens.QOpenGLContext") as context:
            context.return_value.create.return_value = False
            with self.assertLogs("halo.lens", "WARNING"):
                LensRenderer()
        form = context.return_value.setFormat.call_args.args[0]
        self.assertTrue(form.testOption(QSurfaceFormat.FormatOption.ResetNotification))

    def test_output_size_format_and_edge_fade(self):
        renderer = self.renderer()
        result = renderer.apply(self.source(375, 250), QSize(300, 200))
        self.assertEqual(result.size(), QSize(300, 200))
        self.assertEqual(result.format(), QImage.Format.Format_ARGB32_Premultiplied)
        alpha = [result.pixelColor(150, y).alpha() for y in range(200)]
        self.assertLessEqual(max(alpha[0], alpha[199]), 2)
        self.assertLess(max(alpha[2], alpha[197]), 40)
        self.assertEqual((alpha[20], alpha[100]), (255, 255))
        self.assertEqual(alpha, alpha[::-1])

    def test_gpu_follows_the_python_mapping_and_comes_back_upright(self):
        renderer = self.renderer()
        height = 400
        result = renderer.apply(self.ramp(200, 500), QSize(100, height))
        for column in (50, 92):
            nx = (column + .5) / 100 * 2 - 1
            for row in (60, 130, 200, 260, 360):
                ny = (row + .5) / height * 2 - 1
                expected = 255 * (warp_source(nx, ny)[1] + 1) / 2
                self.assertAlmostEqual(result.pixelColor(column, row).green(), expected, delta=4)
        self.assertLess(result.pixelColor(50, 60).green(), result.pixelColor(50, 360).green())

    def test_transparent_source_stays_transparent(self):
        renderer = self.renderer()
        image = QImage(100, 100, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        result = renderer.apply(image, QSize(80, 80))
        self.assertEqual(max(result.pixelColor(x, y).alpha() for x in range(0, 80, 8) for y in range(0, 80, 8)), 0)

    def test_no_channel_exceeds_alpha_along_hard_edges(self):
        renderer = self.renderer()
        image = QImage(300, 300, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.GlobalColor.white)
        for row in range(12):
            painter.drawLine(10, 25 * row, 290, 25 * row + 4)
            painter.drawLine(25 * row, 10, 25 * row + 4, 290)
        painter.end()
        self.assertEqual(channels_over_alpha(renderer.apply(image, QSize(300, 300))), 0)

    def test_other_source_formats_are_converted(self):
        renderer = self.renderer()
        image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        result = renderer.apply(image, QSize(80, 80))
        self.assertGreater(result.pixelColor(40, 40).alpha(), 200)

    def test_each_source_and_output_pair_gets_its_own_target(self):
        renderer = self.renderer()
        for source, output in (((400, 300), (300, 200)), ((200, 100), (300, 200)), ((400, 300), (150, 100))):
            result = renderer.apply(self.source(*source), QSize(*output))
            self.assertEqual(result.size(), QSize(*output))
            self.assertGreater(result.pixelColor(output[0] // 2, output[1] // 2).alpha(), 200)
        self.assertEqual(len(renderer._targets), 3)
        renderer.apply(self.source(200, 100), QSize(300, 200))
        self.assertEqual(len(renderer._targets), 3)

    def test_lost_context_turns_lens_off(self):
        renderer = self.renderer()
        with patch.object(renderer._context, "makeCurrent", return_value=False):
            with self.assertLogs("halo.lens", "WARNING") as logs:
                self.assertIsNone(renderer.apply(self.source(10, 10), QSize(10, 10)))
        self.assertFalse(renderer.available)
        self.assertTrue(renderer.reason)
        self.assertIsNone(renderer.apply(self.source(10, 10), QSize(10, 10)))
        self.assertEqual(len(logs.records), 1)

    def test_a_failing_pass_turns_lens_off_and_logs_once(self):
        renderer = self.renderer()
        with patch.object(renderer, "_draw", side_effect=RuntimeError("boom")):
            with self.assertLogs("halo.lens", "WARNING") as logs:
                self.assertIsNone(renderer.apply(self.source(10, 10), QSize(10, 10)))
                self.assertIsNone(renderer.apply(self.source(10, 10), QSize(10, 10)))
        self.assertFalse(renderer.available)
        self.assertIn("boom", renderer.reason)
        self.assertEqual(len(logs.records), 1)

    def test_a_framebuffer_that_will_not_bind_is_a_failed_pass(self):
        renderer = self.renderer()
        with patch("halo.lens.QOpenGLFramebufferObject.bind", return_value=False):
            with self.assertLogs("halo.lens", "WARNING"):
                self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assertFalse(renderer.available)
        self.assertIn("bound", renderer.reason)

    def test_a_null_readback_is_a_failed_pass(self):
        renderer = self.renderer()
        with patch("halo.lens.QOpenGLFramebufferObject.toImage", return_value=QImage()):
            with self.assertLogs("halo.lens", "WARNING"):
                self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assertFalse(renderer.available)
        self.assertIn("no image", renderer.reason)

    def assert_released(self, renderer):
        self.assertEqual(len(renderer._targets), 0)
        self.assertEqual((renderer._context, renderer._surface, renderer._program, renderer._vao, renderer._gl),
                         (None, None, None, None, None))
        self.assertFalse(renderer._idle.isActive())

    def test_a_failure_releases_the_gpu_objects_right_away(self):
        renderer = self.renderer()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        destroyed = Mock()
        renderer._context.aboutToBeDestroyed.connect(destroyed)
        with patch("halo.lens.QOpenGLFramebufferObject.bind", return_value=False):
            with self.assertLogs("halo.lens", "WARNING"):
                renderer.apply(self.source(40, 30), QSize(30, 20))
        self.assert_released(renderer)
        destroyed.assert_called_once()

    def test_a_lost_context_releases_the_gpu_objects_right_away(self):
        renderer = self.renderer()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        with patch.object(renderer._context, "makeCurrent", return_value=False):
            with self.assertLogs("halo.lens", "WARNING"):
                self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assert_released(renderer)

    def test_a_budget_that_gave_up_never_rebuilds(self):
        renderer = self.renderer()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        for _ in range(60):
            renderer.budget.record(30)
        renderer.release()
        self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assert_released(renderer)

    def test_each_pass_rearms_a_30_second_idle_timer(self):
        renderer = self.renderer()
        self.assertEqual(renderer._idle.interval(), 30_000)
        self.assertTrue(renderer._idle.isSingleShot())
        self.assertFalse(renderer._idle.isActive())
        renderer.apply(self.source(40, 30), QSize(30, 20))
        self.assertTrue(renderer._idle.isActive())

    def test_idle_release_keeps_the_lens_available_and_the_next_pass_rebuilds(self):
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, text: messages.append(text))
        self.addCleanup(qInstallMessageHandler, previous)
        with patch("halo.lens.IDLE_RELEASE_MS", 20):
            renderer = self.renderer()
        before = renderer.apply(self.ramp(120, 90), QSize(100, 80))
        QTest.qWait(150)
        self.assert_released(renderer)
        self.assertTrue(renderer.available)
        self.assertEqual(renderer.reason, "")
        with self.assertNoLogs("halo.lens", "INFO"):
            after = renderer.apply(self.ramp(120, 90), QSize(100, 80))
        self.assertEqual(before, after)
        self.assertIsNotNone(renderer._context)
        self.assertTrue(renderer._idle.isActive())
        self.assertEqual(messages, [])

    def test_a_rebuild_is_left_out_of_the_budget(self):
        renderer = self.renderer()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        renderer.budget.record(5)
        renderer.release()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        renderer.budget.record(200)
        self.assertEqual(list(renderer.budget._frames), [5])
        renderer.apply(self.source(40, 30), QSize(30, 20))
        renderer.budget.record(6)
        self.assertEqual(list(renderer.budget._frames), [5, 6])

    def test_a_rebuild_that_fails_turns_the_lens_off_and_logs_once(self):
        renderer = self.renderer()
        renderer.apply(self.source(40, 30), QSize(30, 20))
        renderer.release()
        with patch("halo.lens.QOpenGLContext.create", return_value=False):
            with self.assertLogs("halo.lens", "WARNING") as logs:
                self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
                self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assertFalse(renderer.available)
        self.assertEqual(len(logs.records), 1)
        self.assert_released(renderer)

    def test_target_cache_stays_bounded(self):
        renderer = self.renderer()
        for size in ((300, 200), (200, 150), (100, 80), (120, 60), (90, 90), (64, 48)):
            renderer.apply(self.source(size[0] + 20, size[1] + 20), QSize(*size))
        self.assertLessEqual(len(renderer._targets), 4)
        self.assertTrue(renderer.available)

    def test_close_is_safe_twice(self):
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, text: messages.append(text))
        try:
            renderer = LensRenderer()
            if not renderer.available:
                renderer.close()
                self.skipTest(f"No OpenGL lens on this PC: {renderer.reason}")
            renderer.apply(self.source(40, 30), QSize(30, 20))
            renderer.close()
            renderer.close()
        finally:
            qInstallMessageHandler(previous)
        self.assertEqual(messages, [])
        self.assertIsNone(renderer.apply(self.source(40, 30), QSize(30, 20)))
        self.assertFalse(renderer.available)

    def test_empty_input_is_not_a_failure(self):
        renderer = self.renderer()
        self.assertIsNone(renderer.apply(QImage(), QSize(10, 10)))
        self.assertIsNone(renderer.apply(self.source(10, 10), QSize(0, 0)))
        self.assertTrue(renderer.available)


class SharedLensTests(unittest.TestCase):
    def setUp(self):
        shutdown_lens()
        self.addCleanup(shutdown_lens)

    def fake(self, available=True):
        renderer = Mock()
        renderer.available = available
        renderer.budget = LensBudget()
        return renderer

    def test_status_text_is_empty_and_creates_nothing_until_a_lens_is_tried(self):
        with patch("halo.lens.LensRenderer") as made:
            self.assertEqual(lens_status_text(), "")
            made.assert_not_called()

    def test_one_renderer_is_created_on_first_use_and_shared(self):
        with patch("halo.lens.LensRenderer", return_value=self.fake()) as made:
            first, second = shared_lens(), shared_lens()
        self.assertIs(first, second)
        made.assert_called_once()

    def test_shutdown_closes_and_clears_and_is_safe_without_a_lens(self):
        shutdown_lens()
        renderer = self.fake()
        with patch("halo.lens.LensRenderer", return_value=renderer) as made:
            shared_lens()
            shutdown_lens()
            shutdown_lens()
            renderer.close.assert_called_once()
            shared_lens()
            self.assertEqual(made.call_count, 2)
        self.assertEqual(lens_status_text(), "")

    def test_status_text_is_empty_while_the_lens_runs(self):
        with patch("halo.lens.LensRenderer", return_value=self.fake()):
            shared_lens()
        self.assertEqual(lens_status_text(), "")

    def test_status_text_appears_when_the_lens_is_unavailable(self):
        with patch("halo.lens.LensRenderer", return_value=self.fake(available=False)):
            shared_lens()
        self.assertEqual(lens_status_text(), OFF_TEXT)

    def test_status_text_appears_when_the_budget_turns_the_lens_off(self):
        renderer = self.fake()
        with patch("halo.lens.LensRenderer", return_value=renderer):
            shared_lens()
        renderer.budget.enabled = False
        self.assertEqual(lens_status_text(), OFF_TEXT)

    def test_status_text_goes_quiet_after_shutdown(self):
        with patch("halo.lens.LensRenderer", return_value=self.fake(available=False)):
            shared_lens()
        shutdown_lens()
        self.assertEqual(lens_status_text(), "")


class ShutdownStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        shutdown_lens()
        self.addCleanup(shutdown_lens)

    def real_lens(self):
        lens = shared_lens()
        if not lens.available:
            self.skipTest(f"No OpenGL lens on this PC: {lens.reason}")
        image = QImage(40, 30, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        lens.apply(image, QSize(30, 20))
        return lens

    def test_idle_release_leaves_the_settings_line_quiet(self):
        self.real_lens().release()
        self.assertEqual(lens_status_text(), "")

    def test_shutdown_is_safe_in_every_state(self):
        def failed(lens):
            with self.assertLogs("halo.lens", "WARNING"):
                lens._fail("boom")

        def over_budget(lens):
            for _ in range(60):
                lens.budget.record(30)

        def closed(lens):
            lens.close()

        for state in (lambda lens: None, LensRenderer.release, failed, over_budget, closed):
            with self.subTest(state=getattr(state, "__name__", "")):
                lens = self.real_lens()
                state(lens)
                shutdown_lens()
                self.assertIsNone(halo.lens._shared)
                self.assertIsNone(lens._context)
                self.assertFalse(lens._idle.isActive())
                self.assertFalse(lens.available)
                shutdown_lens()


class ControllerCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def closed_controller(self):
        temp = tempfile.TemporaryDirectory(prefix="halo-lens-settings-", dir=Path(__file__).resolve().parents[1] / ".cache")
        self.addCleanup(temp.cleanup)
        c = Controller(QSettings(str(Path(temp.name) / "settings.ini"), QSettings.Format.IniFormat), offline=True)
        c.timer.stop()
        self.addCleanup(c.audio.thread.join, 1)
        return c

    def test_close_shuts_the_lens_down(self):
        c = self.closed_controller()
        with patch("halo.app.shutdown_lens") as shutdown:
            c.close()
        shutdown.assert_called_once_with()

    def test_settings_are_flushed_before_the_lens_shuts_down(self):
        c = self.closed_controller()
        order = []
        with patch.object(c.settings, "sync", side_effect=lambda: order.append("settings")), \
             patch("halo.app.shutdown_lens", side_effect=lambda: order.append("lens")):
            c.close()
        self.assertEqual(order, ["settings", "lens"])

    def test_close_does_not_create_a_lens(self):
        shutdown_lens()
        with patch("halo.lens.LensRenderer") as made:
            self.closed_controller().close()
        made.assert_not_called()
        self.assertIsNone(halo.lens._shared)


if __name__ == "__main__":
    unittest.main()
