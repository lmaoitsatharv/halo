"""The gallery wall: readable song light, wall lettering, comfortable navigation, mini player, share cards."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtCore import QEvent, QSettings, Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo.app import Controller, MainWindow
from halo.gallery import (WALL, CARD, INK, INK_SOFT, INK_MUTED, HANDSET, HANDSET_INK, HANDSET_MUTED,
                          contrast, spotlight_colour, ink_accent, shadow_image, NavTile)
from halo.models import Lyrics, LyricLine, LyricWord
from halo.share_card import render_share_card, fit_lettering, default_file_name, CARD_SIZE
from halo.wall import wall_lines, line_words, sung_word


def cover_bytes(colour="#d9622b"):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class LightAndInkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_spotlight_is_always_a_clear_light_whatever_the_cover(self):
        for value in ("#000000", "#ffffff", "#808080", "#ff0000", "#0a0d14", "#b7e4ad", "#2233ff", "#fff200"):
            hue, saturation, lightness, _ = spotlight_colour(QColor(value)).getHslF()
            self.assertGreaterEqual(saturation, .5, value)
            self.assertTrue(.55 <= lightness <= .71, (value, lightness))

    def test_the_sung_word_reads_on_the_wall_for_every_hue(self):
        for step in range(36):
            colour = QColor.fromHsvF(step / 36, .8, .9)
            self.assertGreaterEqual(contrast(ink_accent(colour), WALL), 4.5, colour.name())
        self.assertGreaterEqual(contrast(ink_accent(QColor("#777777")), WALL), 4.5)

    def test_text_tokens_meet_contrast_on_their_grounds(self):
        for ink in (INK, INK_SOFT, INK_MUTED):
            self.assertGreaterEqual(contrast(ink, WALL), 4.5, ink.name())
            self.assertGreaterEqual(contrast(ink, CARD), 4.5, ink.name())
        for ink in (HANDSET_INK, HANDSET_MUTED):
            self.assertGreaterEqual(contrast(ink, HANDSET), 4.5, ink.name())

    def test_soft_shadows_are_cached_and_have_a_falloff(self):
        first, pad = shadow_image(120, 60, 12, 10, .3)
        again, _ = shadow_image(120, 60, 12, 10, .3)
        self.assertIs(first, again)
        centre = first.pixelColor(pad + 60, pad + 30).alpha()
        edge = first.pixelColor(2, 2).alpha()
        self.assertGreater(centre, 40)
        self.assertLess(edge, centre)


class WallLetteringTests(unittest.TestCase):
    def setUp(self):
        self.lyrics = Lyrics([LyricLine(10, "First light"), LyricLine(14, ""),
                              LyricLine(18, "Every little sound around you"),
                              LyricLine(24, "Timed words here", words=(LyricWord("Timed ", 24), LyricWord("words ", 25), LyricWord("here", 26.5)))])

    def test_the_first_line_waits_before_the_song_reaches_it(self):
        previous, line, index, waiting = wall_lines(self.lyrics, 3)
        self.assertEqual((previous, line.text, index, waiting), ("", "First light", 0, True))

    def test_the_line_before_skips_instrumental_gaps(self):
        previous, line, index, waiting = wall_lines(self.lyrics, 19)
        self.assertEqual(previous, "First light")
        self.assertEqual(line.text, "Every little sound around you")
        self.assertFalse(waiting)

    def test_no_lyrics_shows_nothing_on_the_wall(self):
        self.assertEqual(wall_lines(Lyrics(), 10), ("", None, -1, False))

    def test_timed_words_follow_their_own_starts(self):
        line = self.lyrics.lines[3]
        words = line_words(line)
        self.assertEqual([word for word, _ in words], ["Timed", "words", "here"])
        self.assertEqual(sung_word(line, words, 24.2), 0)
        self.assertEqual(sung_word(line, words, 25.4), 1)
        self.assertEqual(sung_word(line, words, 30), 2)
        self.assertEqual(sung_word(line, words, 23), -1)

    def test_estimated_words_move_forward_through_the_line(self):
        line = self.lyrics.lines[2]
        words = line_words(line)
        seen = [sung_word(line, words, 18 + i * .5, next_time=24) for i in range(12)]
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[0], 0)
        self.assertEqual(seen[-1], len(words) - 1)


class ShareCardRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cards_render_at_feed_size_with_and_without_a_line(self):
        for line in ("Stay a little longer", ""):
            image = render_share_card("In the light we made", "Halo Studio", line, cover_bytes())
            self.assertEqual(image.size(), CARD_SIZE)
            self.assertFalse(image.isNull())

    def test_long_lines_are_lettered_inside_the_block(self):
        text = " ".join(["everything"] * 40)
        font, rows, line_height = fit_lettering(text, 872, 380)
        self.assertLessEqual(len(rows), 5)
        self.assertLessEqual(len(rows) * line_height, 380 + line_height)
        self.assertTrue(rows[-1].endswith("…"))

    def test_file_names_are_safe_on_windows(self):
        self.assertEqual(default_file_name('Wh?t: "is" <this>', "A/B"), "AB - Wht is this.png")
        self.assertEqual(default_file_name("", ""), "Halo lyric card.png")


class GalleryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-gallery-", dir=scratch)
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
        self.app.processEvents()

    def test_every_place_is_labelled_large_enough_and_has_a_key(self):
        for key in ("listening", "modes", "halo", "lyrics", "scenes", "settings"):
            tile = self.window.nav_buttons[key]
            self.assertTrue(tile.isVisible(), key)
            self.assertGreaterEqual(tile.height(), 44, key)
            self.assertTrue(tile.text(), key)
            self.assertTrue(tile.accessibleName(), key)
            self.assertIn("Ctrl+", tile.toolTip(), key)

    def test_number_keys_go_to_each_place_and_only_that_place_is_selected(self):
        expected = {1: ("listening", None), 2: ("modes", None), 3: ("settings", "halo"),
                    4: ("settings", "lyrics"), 5: ("settings", "scenes")}
        keys = {1: Qt.Key.Key_1, 2: Qt.Key.Key_2, 3: Qt.Key.Key_3, 4: Qt.Key.Key_4, 5: Qt.Key.Key_5}
        nav = {1: "listening", 2: "modes", 3: "halo", 4: "lyrics", 5: "scenes"}
        for number, (page, section) in expected.items():
            self.window.place_shortcuts[number - 1].activated.emit()
            self.settle()
            self.assertEqual(self.window.current_page, page)
            if section:
                self.assertEqual(self.window.settings_dialog.section, section)
            checked = [key for key, tile in self.window.nav_buttons.items() if tile.isChecked()]
            self.assertEqual(checked, [nav[number]])

    def test_the_handset_names_the_song_only_away_from_the_label(self):
        self.window.navigate("listening")
        self.settle()
        self.assertFalse(self.window.now_playing.isVisible())
        self.window.open_modes()
        self.settle()
        self.assertTrue(self.window.now_playing.isVisible())

    def test_the_spotlight_hangs_behind_the_print_and_dims_elsewhere(self):
        self.window.navigate("listening")
        self.settle()
        centre, radius, strength, _ = self.window.spotlight()
        frame = self.window.main_art.print_rect().translated(self.window.main_art.mapTo(self.window, self.window.main_art.rect().topLeft()))
        self.assertTrue(frame.contains(centre))
        self.assertGreater(strength, .7)
        self.window.open_settings()
        self.settle()
        self.assertLess(self.window.spotlight()[2], .5)
        self.window.fullscreen()
        self.settle()
        self.assertIsNone(self.window.spotlight())

    def test_play_key_names_what_it_will_do(self):
        self.assertTrue(self.c.track.playing)
        self.assertEqual(self.window.play.accessibleName(), "Pause")
        QTest.mouseClick(self.window.play, Qt.MouseButton.LeftButton)
        self.window.refresh()
        self.assertEqual(self.window.play.accessibleName(), "Play")

    def test_a_click_leaves_no_focus_ring_but_tab_does(self):
        tile = self.window.nav_buttons["modes"]
        self.app.sendEvent(tile, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
        self.assertFalse(tile.keyboard_focus)
        self.app.sendEvent(tile, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        self.assertTrue(tile.keyboard_focus)

    def test_mini_player_rests_the_window_and_never_doubles_floating_words(self):
        self.c.set("floating", True)
        self.window.open_mini_player()
        self.settle()
        mini = self.window.mini_player
        self.assertTrue(mini.isVisible())
        self.assertFalse(self.window.isVisible())
        self.assertTrue(mini.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.window.draw()
        self.assertFalse(self.window.overlay.isVisible())
        before = self.c.track.playing
        QTest.mouseClick(mini.play, Qt.MouseButton.LeftButton)
        self.assertEqual(self.c.track.playing, not before)
        mini.move(mini.x() + 5, mini.y())
        self.window.restore_from_mini()
        self.settle()
        self.assertFalse(mini.isVisible())
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.c.settings.value("mini_position"), f"{mini.x()},{mini.y()}")

    def test_the_mini_player_is_compact_and_rests_with_only_its_play_key(self):
        self.window.open_mini_player()
        self.settle()
        mini = self.window.mini_player
        self.assertLessEqual(mini.width(), 400)
        self.assertLessEqual(mini.height(), 150)
        self.assertTrue(mini.play.isVisible())
        for key in (mini.previous, mini.next, mini.restore_button, mini.close_button):
            self.assertFalse(key.isVisible(), key.accessibleName())
        # The print sits inside the case rather than hanging out of it.
        self.assertTrue(mini.card().contains(mini.frame_rect()))

    def test_hovering_or_tabbing_into_the_mini_player_brings_up_every_key(self):
        self.window.open_mini_player()
        self.settle()
        mini = self.window.mini_player
        self.app.sendEvent(mini, QEvent(QEvent.Type.Enter))
        for _ in range(40):
            mini.tick()
        keys = (mini.previous, mini.next, mini.restore_button, mini.close_button)
        self.assertTrue(all(key.isVisible() for key in keys))
        for key in keys:
            self.assertTrue(mini.rect().contains(key.geometry()), key.accessibleName())
            self.assertFalse(key.geometry().intersects(mini.play.geometry()), key.accessibleName())
        self.app.sendEvent(mini, QEvent(QEvent.Type.Leave))
        for _ in range(40):
            mini.tick()
        self.assertFalse(any(key.isVisible() for key in keys))
        mini.play.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.sendEvent(mini.play, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        for _ in range(40):
            mini.tick()
        self.assertTrue(all(key.isVisible() for key in keys))

    def test_closing_the_mini_player_keeps_music_and_floating_words(self):
        self.c.set("floating", True)
        self.window.open_mini_player()
        self.settle()
        self.window.mini_player.closeRequested.emit()
        self.settle()
        self.assertFalse(self.window.mini_player.isVisible())
        self.assertFalse(self.window.isVisible())
        self.window.draw()
        self.assertTrue(self.window.overlay.isVisible())

    def test_share_card_starts_on_the_sung_line_and_saves_a_png(self):
        self.c.demo_position, self.c.demo_anchor = 21., time.monotonic()
        self.c.tick()
        self.window.open_share_card()
        self.settle()
        dialog = self.window.share_dialog
        self.assertTrue(self.window.sheet.isVisible())
        self.assertIs(self.window.sheet.dialog, dialog)
        lines = dialog.lines()
        position = self.c.position + self.c.offset / 1000
        expected = max(i for i, line in enumerate(lines) if line.time <= position)
        self.assertEqual(dialog.index, expected)
        self.assertEqual(dialog.current_line(), lines[expected].text.strip())
        dialog.step(-1)
        self.assertEqual(dialog.index, expected - 1)
        target = Path(self.temp.name) / "cards" / "card.png"
        dialog.save_to(target)
        saved = QImage(str(target))
        self.assertEqual(saved.size(), CARD_SIZE)
        dialog.copy()
        self.assertEqual(QApplication.clipboard().image().size(), CARD_SIZE)

    def test_share_card_without_lyrics_shares_the_song(self):
        self.c.lyrics = Lyrics(message="No synced lyrics")
        self.window.open_share_card()
        self.settle()
        dialog = self.window.share_dialog
        self.assertEqual(dialog.index, -1)
        self.assertFalse(dialog.earlier.isEnabled())
        self.assertFalse(dialog.later.isEnabled())
        self.assertEqual(dialog.image.size(), CARD_SIZE)

    def test_a_new_song_rehangs_the_print_unless_motion_is_reduced(self):
        self.window.navigate("listening")
        self.settle()
        art = self.window.main_art
        art.grab()
        self.c.track = replace(self.c.track, title="Another song", artwork=cover_bytes())
        self.c.trackChanged.emit()
        self.assertTrue(art.rehanging())
        art.grab()
        self.c.set("reduced_motion", True)
        self.c.track = replace(self.c.track, title="A third song", artwork=cover_bytes("#2255aa"))
        self.c.trackChanged.emit()
        self.assertFalse(art.rehanging())

    def test_the_label_turns_over_for_a_new_song_but_not_for_a_pause(self):
        self.window.navigate("listening")
        self.settle()
        label = self.window.museum_label
        self.c.transport("toggle")
        self.c.trackChanged.emit()
        self.assertFalse(label.turning())
        self.c.track = replace(self.c.track, title="Another song")
        self.c.trackChanged.emit()
        self.assertTrue(label.turning())
        self.assertEqual(self.window.title.full_text, "Another song")
        QTest.qWait(520)
        self.assertFalse(label.turning())
        self.assertEqual(label.content.geometry(), label.rect())
        self.c.set("reduced_motion", True)
        self.c.track = replace(self.c.track, title="A third song")
        self.c.trackChanged.emit()
        self.assertFalse(label.turning())

    def test_wall_lettering_paints_every_state(self):
        canvas = self.window.canvas
        for lyrics in (Lyrics(message="No synced lyrics"), Lyrics([LyricLine(40, "Later")]),
                       Lyrics([LyricLine(0, "")]), self.c.lyrics):
            self.c.lyrics = lyrics
            self.assertFalse(canvas.grab().isNull())


if __name__ == "__main__":
    unittest.main()
