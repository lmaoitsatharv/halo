"""Mini player styles: every style opens, tucks its keys away, switches in place, and reads clearly."""
from pathlib import Path
import re
import tempfile
import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt, QTime, QLocale
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow
from halo.gallery import contrast, song_light
from halo.mini_player import MINI_STYLES, MINI_STYLE_KEYS, MiniPlayer, readable_light, next_mini_style
from halo.mini_styles import (MINI_CLASSES, NotchPlayer, DiscPlayer, NEON, NOTCH_PANEL, ON_ACCENT, GLASS_TOP,
                              create_mini, time_of_day, vivid, wrap_words)

HUES = [i / 12 for i in range(12)]


class MiniStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-mini-", dir=scratch)
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
        self.window.resize(1280, 800)
        self.settle()

    def tearDown(self):
        self.window.exiting = True
        if self.window.mini_player is not None:
            self.window.mini_player.hide()
            self.window.mini_player.deleteLater()
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
        QTest.qWait(20)
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def open(self, style):
        self.c.set("mini_style", style)
        self.window.open_mini_player()
        self.settle()
        return self.window.mini_player

    def reveal(self, mini, hovered=True):
        mini.hovered = hovered
        for _ in range(40):
            mini.tick()

    def all_keys(self, mini):
        return (mini.previous, mini.play, mini.next, mini.restore_button, mini.close_button)

    # --- every style ----------------------------------------------------------------------

    def test_every_style_has_a_class_a_name_and_a_description(self):
        self.assertEqual(tuple(MINI_CLASSES), MINI_STYLE_KEYS)
        self.assertEqual(MINI_STYLE_KEYS[0], "case")
        for key, name, description in MINI_STYLES:
            self.assertEqual(MINI_CLASSES[key].STYLE, key)
            self.assertTrue(name and description, key)

    def test_every_style_opens_on_top_and_tucks_its_keys_away_until_hovered(self):
        for style in MINI_STYLE_KEYS:
            with self.subTest(style=style):
                mini = self.open(style)
                self.assertEqual(mini.STYLE, style)
                self.assertTrue(mini.isVisible())
                self.assertFalse(self.window.isVisible())
                self.assertTrue(mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
                for key in mini.hidden_keys:
                    self.assertFalse(key.isVisible(), key.accessibleName())
                for key in set(self.all_keys(mini)) - set(mini.hidden_keys):
                    self.assertTrue(key.isVisible(), key.accessibleName())
                self.reveal(mini)
                keys = self.all_keys(mini)
                for key in keys:
                    self.assertTrue(key.isVisible(), key.accessibleName())
                    self.assertTrue(mini.rect().contains(key.geometry()), key.accessibleName())
                    for other in keys:
                        if other is not key:
                            self.assertFalse(key.geometry().intersects(other.geometry()),
                                             f"{key.accessibleName()} / {other.accessibleName()}")
                self.reveal(mini, hovered=False)
                self.assertFalse(any(key.isVisible() for key in mini.hidden_keys))
                self.window.restore_from_mini()
                self.settle()
                self.assertFalse(mini.isVisible())
                self.assertTrue(self.window.isVisible())

    def test_every_style_plays_and_pauses_from_its_play_key(self):
        for style in MINI_STYLE_KEYS:
            with self.subTest(style=style):
                mini = self.open(style)
                self.reveal(mini)
                before = self.c.track.playing
                QTest.mouseClick(mini.play, Qt.MouseButton.LeftButton)
                self.assertEqual(self.c.track.playing, not before)
                mini.refresh()
                self.assertEqual(mini.play.accessibleName(), "Pause" if self.c.track.playing else "Play")
                self.window.close_mini_player()
                self.settle()

    def test_a_click_on_the_cover_brings_halo_back_in_every_style(self):
        for style in MINI_STYLE_KEYS:
            with self.subTest(style=style):
                mini = self.open(style)
                restored = []
                mini.restoreRequested.connect(lambda: restored.append(True))
                spot = mini.art_rect().center().toPoint()
                if mini.childAt(spot) is not None:
                    spot += QPoint(0, round(mini.art_rect().height() * .3))
                self.assertIsNone(mini.childAt(spot))
                QTest.mouseClick(mini, Qt.MouseButton.LeftButton, pos=spot)
                self.assertEqual(restored, [True])
                self.window.close_mini_player()
                self.settle()

    # --- choosing a style -----------------------------------------------------------------

    def test_an_unknown_style_falls_back_to_the_case(self):
        self.c.settings.setValue("mini_style", "spaceship")
        other = Controller(self.c.settings, offline=True)
        try:
            self.assertEqual(other.mini_style, "case")
        finally:
            other.timer.stop()
            other.close()
            other.audio.thread.join(1)
        self.c.set("mini_style", "spaceship")
        self.assertEqual(self.c.mini_style, "case")
        self.assertIsInstance(create_mini(self.c, "spaceship"), MiniPlayer)

    def test_switching_style_while_open_swaps_it_in_the_same_corner(self):
        case = self.open("case")
        before = case.frameGeometry()
        self.c.set("mini_style", "notch")
        self.assertFalse(case.isVisible())
        self.settle()
        notch = self.window.mini_player
        self.assertIsInstance(notch, NotchPlayer)
        self.assertTrue(notch.isVisible())
        self.assertFalse(self.window.isVisible())
        after = notch.frameGeometry()
        # The case opens in the lower right, so the new style keeps to the same right and bottom edges.
        self.assertEqual(after.right(), before.right())
        self.assertEqual(after.bottom(), before.bottom())
        self.assertEqual(self.c.settings.value("mini_style"), "notch")
        self.assertEqual(self.c.settings.value("mini_position"), f"{notch.x()},{notch.y()}")

    def test_switching_style_while_closed_only_changes_the_next_one(self):
        mini = self.open("case")
        self.window.close_mini_player()
        self.c.set("mini_style", "disc")
        self.settle()
        self.assertIsNone(self.window.mini_player)
        self.window.open_mini_player()
        self.settle()
        self.assertIsInstance(self.window.mini_player, DiscPlayer)
        self.assertIsNot(self.window.mini_player, mini)

    def test_the_right_click_menu_lists_every_style_and_switches(self):
        mini = self.open("case")
        mini.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        menu = mini.open_menu(mini.mapToGlobal(QPoint(20, 20)))
        try:
            entry = menu.entries[0]
            self.assertEqual((entry.kind, entry.text, entry.detail()), ("submenu", "Style", "Case"))
            styles = entry.submenu()
            self.assertEqual([item.text for item in styles], [name for _, name, _ in MINI_STYLES])
            self.assertEqual([item.is_on() for item in styles], [key == "case" for key in MINI_STYLE_KEYS])
            texts = [item.text for item in menu.entries]
            self.assertIn("Back to Halo", texts)
            self.assertIn("Close to the tray", texts)
            styles[MINI_STYLE_KEYS.index("poster")].run()
        finally:
            menu.close()
        self.settle()
        self.assertEqual(self.c.mini_style, "poster")
        self.assertEqual(self.window.mini_player.STYLE, "poster")
        self.assertTrue(self.window.mini_player.isVisible())

    def test_ctrl_shift_m_steps_through_the_styles(self):
        self.assertEqual([next_mini_style(key) for key in MINI_STYLE_KEYS], list(MINI_STYLE_KEYS[1:]) + ["case"])
        mini = self.open("case")
        mini.next_style()
        self.settle()
        self.assertEqual(self.window.mini_player.STYLE, "notch")

    def test_the_tray_and_settings_offer_every_style(self):
        self.assertEqual(tuple(self.window.tray_mini_styles), MINI_STYLE_KEYS)
        self.c.set("mini_style", "capsule")
        self.assertEqual([action.isChecked() for action in self.window.tray_mini_styles.values()],
                         [key == "capsule" for key in MINI_STYLE_KEYS])
        select = self.window.setting_controls["mini_style"]
        self.assertEqual([select.itemData(i) for i in range(select.count())], list(MINI_STYLE_KEYS))
        self.assertEqual(select.currentData(), "capsule")
        select.setCurrentIndex(MINI_STYLE_KEYS.index("disc"))
        self.assertEqual(self.c.mini_style, "disc")
        self.window.tray_mini_styles["notch"].trigger()
        self.settle()
        self.assertEqual(self.c.mini_style, "notch")
        self.assertIsInstance(self.window.mini_player, NotchPlayer)
        self.assertTrue(self.window.mini_player.isVisible())

    # --- the Notch ------------------------------------------------------------------------

    def test_the_notch_is_laid_out_like_its_reference(self):
        mini = self.open("notch")
        card = mini.card_path().boundingRect()
        panel = mini.panel()
        # Halo's tab rises above the step; the bright clock tab sits on the step; the lyric panel juts past the card.
        self.assertLess(card.top(), mini.STEP)
        self.assertGreater(panel.right(), card.right())
        self.assertGreaterEqual(mini.tab_rect().left(), mini.tab_right)
        self.assertEqual(mini.tab_rect().bottom(), panel.top())
        self.assertTrue(panel.contains(mini.art_rect()))
        self.assertTrue(panel.contains(mini.stack_rect()))
        # Previous, play, next sit in a row under the seek bar, always visible; only the window keys hide.
        self.assertEqual(set(mini.hidden_keys), {mini.restore_button, mini.close_button})
        y = {key.geometry().center().y() for key in (mini.previous, mini.play, mini.next)}
        self.assertEqual(len(y), 1)
        self.assertLess(mini.bar().bottom(), mini.play.geometry().top())
        self.assertLessEqual(mini.bar().right(), card.right() - 8)
        # The window keys come up on the clock tab.
        self.reveal(mini)
        for key in (mini.restore_button, mini.close_button):
            self.assertTrue(mini.tab_rect().contains(QPointF(key.geometry().center())), key.accessibleName())

    def test_the_notch_clock_is_the_local_time_written_tight(self):
        text = time_of_day()
        expected = QLocale.system().toString(QTime.currentTime(), QLocale.FormatType.ShortFormat)
        self.assertEqual(re.sub(r"\s", "", text), re.sub(r"[\s  ]", "", expected))
        self.assertNotRegex(text, r"\s")

    def test_the_notch_shows_the_lines_around_the_one_being_sung(self):
        mini = self.open("notch")
        lines = self.c.lyrics.lines
        sung = [i for i, line in enumerate(lines) if line.text.strip()]
        middle = sung[len(sung) // 2]
        self.c.seek(lines[middle].time + .05)
        self.c.tick()
        text, _, _, index = mini.line()
        self.assertEqual(index, middle)
        before, after = mini.neighbours(index)
        self.assertEqual(before, lines[sung[sung.index(middle) - 1]].text.strip())
        self.assertEqual(after, lines[sung[sung.index(middle) + 1]].text.strip())

    def test_clicking_the_notch_seek_bar_moves_through_the_song(self):
        mini = self.open("notch")
        bar = mini.bar()
        QTest.mouseClick(mini, Qt.MouseButton.LeftButton, pos=QPointF(bar.left() + bar.width() * .5, bar.center().y()).toPoint())
        self.c.tick()
        self.assertAlmostEqual(self.c.position / self.c.track.duration, .5, delta=.03)
        self.assertTrue(mini.isVisible())

    def test_the_notch_accent_is_green_or_the_songs_own_colour(self):
        mini = self.open("notch")
        self.assertEqual(mini.accent().name(), NEON.name())
        self.c.set("mini_song_accent", True)
        accent = mini.accent()
        self.assertNotEqual(accent.name(), NEON.name())
        self.assertAlmostEqual(accent.hslHueF(), song_light(self.c).hslHueF(), delta=.03)
        self.assertTrue(self.c.settings.value("mini_song_accent", type=bool))
        toggle = [entry for entry in mini.menu_entries() if entry.text == "Song colour accent"]
        self.assertEqual(len(toggle), 1)
        self.assertTrue(toggle[0].is_on())

    # --- reading clearly and moving gently ------------------------------------------------

    def test_lettering_and_dark_glyphs_read_on_every_accent(self):
        for hue in HUES:
            for saturation in (.15, .6, 1.):
                for value in (.3, .7, 1.):
                    colour = QColor.fromHsvF(hue, saturation, value)
                    accent = vivid(colour)
                    with self.subTest(colour=colour.name()):
                        self.assertGreaterEqual(contrast(ON_ACCENT, accent), 4.5)
                        self.assertGreaterEqual(contrast(readable_light(accent, NOTCH_PANEL, 4.5), NOTCH_PANEL), 4.5)
                        self.assertGreaterEqual(contrast(readable_light(colour, GLASS_TOP, 4.5), GLASS_TOP), 4.5)
        self.assertGreaterEqual(contrast(ON_ACCENT, NEON), 4.5)

    def test_the_record_turns_only_while_playing_and_holds_still_with_reduced_motion(self):
        mini = self.open("disc")
        mini.advance_time(1., False)
        self.assertGreater(mini.angle, 0)
        held = mini.angle
        mini.advance_time(1., True)
        self.assertEqual(mini.angle, held)
        self.c.transport("toggle")
        self.assertFalse(self.c.track.playing)
        mini.advance_time(1., False)
        self.assertEqual(mini.angle, held)

    def test_long_lines_wrap_into_rows_that_fit(self):
        from halo.gallery import face
        from PySide6.QtGui import QFontMetricsF
        metrics = QFontMetricsF(face(18))
        words = "every little sound around you finds a place to land tonight".split()
        placed, rows = wrap_words(words, metrics, 160)
        self.assertGreater(rows, 1)
        for (row, left), word in zip(placed, words):
            self.assertLessEqual(left + metrics.horizontalAdvance(word), 160 + 1e-6 if left else 10_000)
        self.assertEqual([row for row, _ in placed], sorted(row for row, _ in placed))


if __name__ == "__main__":
    unittest.main()
