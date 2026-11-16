"""Feedback round: the room says why there are no words, the wheel scrolls pages, Settings always opens, lyric size."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QComboBox, QSlider

from halo.app import Controller, MainWindow
from halo.models import Lyrics, Track, floating_geometry, FLOATING_SIZES, TAGLINE
from halo.widgets import LyricCanvas

NO_LYRICS = "No timed lyrics found. You can import a lyrics file."


class EmptyRoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class Stub:
        def __init__(self, connected, message):
            self.track = Track(title="Tu Hai", artist="Chaitanya Kapadia", connected=connected, playing=connected)
            self.lyrics = Lyrics(message=message)
            self.demo = False

    def test_the_room_shows_the_tagline_whenever_it_has_no_words(self):
        for connected, message in ((True, NO_LYRICS), (True, "Finding timed lyrics…"), (True, ""),
                                   (False, "Waiting for music")):
            canvas = LyricCanvas(self.Stub(connected, message), "immersive")
            self.assertEqual(canvas.empty_text(), TAGLINE, message)

    def test_the_listening_wall_shows_the_tagline_when_no_lyrics_are_found(self):
        from halo.wall import WallLyrics
        stub = self.Stub(True, NO_LYRICS)
        wall = WallLyrics.__new__(WallLyrics)
        wall.c = stub
        self.assertEqual(WallLyrics.empty_text(wall), TAGLINE)
        stub.lyrics = Lyrics(message="Lyrics service busy. Try again shortly.")
        self.assertEqual(WallLyrics.empty_text(wall), TAGLINE)
        stub.lyrics = Lyrics(message="Finding timed lyrics…")
        self.assertEqual(WallLyrics.empty_text(wall), "Finding timed lyrics…")
        stub.track = Track(connected=False)
        self.assertEqual(WallLyrics.empty_text(wall), "Play a song anywhere, and its words will be lettered here.")

    def test_the_mini_player_shows_the_tagline_when_no_lyrics_are_found(self):
        from halo.mini_player import MiniBase
        stub = self.Stub(True, NO_LYRICS)
        mini = MiniBase.__new__(MiniBase)
        mini.c = stub
        self.assertEqual(MiniBase.lyric_status(mini), TAGLINE)
        stub.lyrics = Lyrics(message="Finding timed lyrics…")
        self.assertEqual(MiniBase.lyric_status(mini), "Finding lyrics…")


class FloatingGeometryTests(unittest.TestCase):
    def test_size_scales_the_overlay_and_stays_on_the_screen(self):
        screen = (0, 0, 1920, 1080)
        normal = floating_geometry(screen, 50, 90)
        self.assertEqual(normal[2:], (860, 220))
        self.assertEqual(floating_geometry(screen, 50, 90, 1.)[2:], normal[2:])
        larger = floating_geometry(screen, 50, 90, 1.5)
        self.assertEqual(larger[2:], (1290, 330))
        smaller = floating_geometry(screen, 50, 90, .5)
        self.assertEqual(smaller[2:], (430, 110))
        for scale in (.5, 1., 2.):
            for x, y in ((0, 0), (100, 100), (50, 90)):
                left, top, width, height = floating_geometry((0, 0, 1366, 768), x, y, scale)
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(left + width, 1366)
                self.assertLessEqual(top + height, 768)


class WindowFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-feedback-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.c.set_demo(True)
        self.c.tick()
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
        self.window.resize(1280, 720)
        self.settle()

    def tearDown(self):
        self.window.exiting = True
        if self.window.position_dialog is not None:
            self.window.position_dialog.desktop_preview.setChecked(False)
        self.window.hide()
        self.window.draw_timer.stop()
        self.window.tray.hide()
        self.window.immersive.media_background.close()
        self.c.close()
        self.c.audio.thread.join(1)
        for widget in (self.window.overlay, *self.window.edges, self.window):
            widget.hide()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def settle(self):
        self.app.processEvents()
        QTest.qWait(30)
        self.app.processEvents()

    # --- Settings opens from every section --------------------------------------------------

    def test_the_settings_key_opens_general_from_lighting_lyrics_and_immersive(self):
        for section in ("halo", "lyrics", "scenes"):
            with self.subTest(section=section):
                self.window.open_settings_section(section)
                self.settle()
                self.assertEqual(self.window.settings_dialog.section, section)
                self.window.settings_button.click()
                self.settle()
                self.assertEqual(self.window.current_page, "settings")
                self.assertEqual(self.window.settings_dialog.section, "general")
                checked = [key for key, tile in self.window.nav_buttons.items() if tile.isChecked()]
                self.assertEqual(checked, ["settings"])
        # Already on General, the key just stays there.
        self.window.settings_button.click()
        self.settle()
        self.assertEqual(self.window.settings_dialog.section, "general")

    # --- the wheel ---------------------------------------------------------------------------

    def wheel(self, widget, notches=-1):
        centre = QPointF(widget.rect().center())
        event = QWheelEvent(centre, QPointF(widget.mapToGlobal(centre.toPoint())), QPoint(), QPoint(0, 120 * notches),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
        self.app.processEvents()

    def page_of(self, widget):
        page = widget.parentWidget()
        while page is not None and not isinstance(page, QAbstractScrollArea):
            page = page.parentWidget()
        return page

    def lighting_controls(self):
        self.window.open_settings_section("halo")
        self.settle()
        page = self.window.settings_dialog.pages.currentWidget()
        sliders = [s for s in page.findChildren(QSlider) if s.isVisible() and s.isEnabled()]
        combos = [c for c in page.findChildren(QComboBox) if c.isVisible() and c.isEnabled()]
        self.assertTrue(sliders and combos)
        return sliders[0], combos[0]

    def test_scrolling_over_a_slider_scrolls_the_page_instead_of_changing_it(self):
        slider, _ = self.lighting_controls()
        page = self.page_of(slider)
        self.assertIsNotNone(page)
        bar = page.verticalScrollBar()
        bar.setValue(0)
        value = slider.value()
        self.assertFalse(slider.hasFocus())
        self.wheel(slider)
        self.assertEqual(slider.value(), value)
        if bar.maximum() > 0:
            self.assertGreater(bar.value(), 0)

    def test_scrolling_over_a_dropdown_leaves_it_alone(self):
        _, combo = self.lighting_controls()
        index = combo.currentIndex()
        self.assertNotEqual(combo.focusPolicy(), Qt.FocusPolicy.WheelFocus)
        self.wheel(combo)
        self.wheel(combo, 1)
        self.assertEqual(combo.currentIndex(), index)
        self.assertFalse(combo.hasFocus())

    def test_a_clicked_slider_takes_the_wheel(self):
        slider, _ = self.lighting_controls()
        slider.setValue((slider.minimum() + slider.maximum()) // 2)
        value = slider.value()
        # An off-screen test window never becomes the active window, so nothing in it can hold real focus;
        # stand in for the click that would have focused the slider.
        slider.hasFocus = lambda: True
        try:
            self.wheel(slider, 1)
        finally:
            del slider.hasFocus
        self.assertNotEqual(slider.value(), value)

    def test_scroll_bars_still_scroll(self):
        slider, _ = self.lighting_controls()
        bar = self.page_of(slider).verticalScrollBar()
        if bar.maximum() <= 0:
            self.skipTest("the page fits without scrolling")
        bar.setValue(0)
        self.wheel(bar)
        self.assertGreater(bar.value(), 0)

    # --- floating lyrics size -----------------------------------------------------------------

    def test_floating_lyrics_size_is_kept_in_range_and_saved(self):
        self.assertEqual(self.c.floating_size, 100)
        self.c.set("floating_size", 150)
        self.assertEqual(self.c.floating_size, 150)
        self.assertEqual(self.c.settings.value("floating_size", type=int), 150)
        self.c.set("floating_size", 900)
        self.assertEqual(self.c.floating_size, FLOATING_SIZES[1])
        self.c.set("floating_size", 1)
        self.assertEqual(self.c.floating_size, FLOATING_SIZES[0])

    def test_the_size_slider_grows_the_overlay_and_its_words(self):
        self.window.open_position_settings()
        self.settle()
        dialog = self.window.position_dialog
        slider = dialog.size_slider
        self.assertEqual((slider.minimum(), slider.maximum(), slider.value()), (*FLOATING_SIZES, 100))
        self.assertEqual(slider.accessibleName(), "Floating lyrics size")
        overlay = self.window.overlay
        self.window.place_overlay()
        before = overlay.geometry()
        base = overlay._base_size()
        slider.setValue(150)
        self.settle()
        self.assertEqual(self.c.floating_size, 150)
        after = overlay.geometry()
        self.assertGreater(after.height(), before.height())
        self.assertGreaterEqual(after.width(), before.width())
        self.assertGreater(overlay._base_size(), base)
        slider.setValue(60)
        self.settle()
        self.assertLess(overlay.geometry().height(), before.height())
        self.assertLess(overlay._base_size(), base)
        # Other lyric canvases (the room, previews) keep their own sizes.
        self.assertEqual(self.window.immersive.canvas.text_scale(), 1.)


if __name__ == "__main__":
    unittest.main()
