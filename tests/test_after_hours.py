"""After hours: the dark wall, the Appearance setting, the lit mini player case, and cards on either wall."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QSettings, Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from halo import theme
from halo.app import Controller, MainWindow
from halo.gallery import (WALL, CARD, INK, INK_SOFT, INK_MUTED, FOCUS, ACCENT_INK, ON_INK, HANDSET_INK, HANDSET_MUTED,
                          contrast, luminance, ink_accent)
from halo.glass import icon
from halo.share_card import render_share_card, CARD_SIZE


def cover_bytes(colour="#d9622b"):
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def lightness(image, x, y):
    return QColor(image.pixel(round(x), round(y))).lightness()


class DarkWallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        theme.apply(False)

    def test_the_dark_wall_keeps_every_lettering_readable(self):
        theme.apply(True)
        self.assertTrue(theme.is_dark())
        self.assertLess(luminance(WALL), .05)
        for ground in (WALL, CARD):
            for ink in (INK, INK_SOFT, INK_MUTED):
                self.assertGreaterEqual(contrast(ink, ground), 4.5, (ink.name(), ground.name()))
            self.assertGreaterEqual(contrast(FOCUS, ground), 3., ground.name())
            self.assertGreaterEqual(contrast(ACCENT_INK, ground), 4.5, ground.name())
        # Ink-filled controls flip to light, so their lettering flips to dark.
        self.assertGreaterEqual(contrast(ON_INK, INK), 7.)

    def test_the_sung_word_reads_on_the_dark_wall_for_every_hue(self):
        theme.apply(True)
        for step in range(36):
            colour = QColor.fromHslF(step / 36, .8, .5)
            self.assertGreaterEqual(contrast(ink_accent(colour), WALL), 4.5, colour.name())
        self.assertGreaterEqual(contrast(ink_accent(QColor("#808080")), WALL), 4.5)

    def test_switching_back_restores_the_light_wall_exactly(self):
        before = {"wall": WALL.name(), "ink": INK.name(), "card": CARD.name()}
        theme.apply(True)
        theme.apply(False)
        self.assertEqual({"wall": WALL.name(), "ink": INK.name(), "card": CARD.name()}, before)
        self.assertEqual(theme.themed("color: #1c2a26;"), "color: #1c2a26;")

    def test_stylesheets_follow_the_light(self):
        css = ("QWidget { color: #1c2a26; background: #ffffff; border: 1px solid rgba(28, 42, 38, 46); } "
               "QFrame { background: #11171a; }")
        theme.apply(True)
        dark = theme.themed(css)
        self.assertIn("color: #e6ece6", dark)
        self.assertIn("background: #1f2925", dark)
        self.assertIn("rgba(230, 236, 230, 46)", dark)
        # Preview screens are dark in both lights and are left alone.
        self.assertIn("#11171a", dark)

    def test_the_mini_player_sung_word_reads_on_its_case_for_every_hue(self):
        from halo.gallery import spotlight_colour
        from halo.mini_player import readable_light, CASE_TOP, CASE_LOW
        for step in range(36):
            light = spotlight_colour(QColor.fromHslF(step / 36, .8, .5))
            for ground in (CASE_TOP, CASE_LOW):
                self.assertGreaterEqual(contrast(readable_light(light, ground), ground), 4.5, light.name())

    def test_the_handset_lettering_never_changes(self):
        light = (HANDSET_INK.name(), HANDSET_MUTED.name())
        theme.apply(True)
        self.assertEqual((HANDSET_INK.name(), HANDSET_MUTED.name()), light)

    def test_icons_redraw_in_the_current_light(self):
        def brightest(image):
            return max(QColor(image.pixel(x, y)).lightness() for x in range(image.width()) for y in range(image.height())
                       if QColor.fromRgba(image.pixel(x, y)).alpha() > 200)
        glyph = icon("close", "#1c2a26", 24)
        light = glyph.pixmap(48, 48).toImage()
        theme.apply(True)
        dark = glyph.pixmap(48, 48).toImage()
        self.assertLess(brightest(light), 80)
        self.assertGreater(brightest(dark), 180)

    def test_cards_come_on_either_wall_without_changing_the_app(self):
        light = render_share_card("Song", "Artist", "A line to share", cover_bytes(), dark=False, album="Album", sung_at=62)
        dark = render_share_card("Song", "Artist", "A line to share", cover_bytes(), dark=True, album="Album", sung_at=62)
        self.assertEqual(dark.size(), CARD_SIZE)
        self.assertFalse(theme.is_dark())
        corner = (CARD_SIZE.width() - 6, CARD_SIZE.height() - 6)
        self.assertGreater(lightness(light, *corner), 150)
        self.assertLess(lightness(dark, *corner), 60)
        theme.apply(True)
        render_share_card("Song", "Artist", "", cover_bytes(), dark=False)
        self.assertTrue(theme.is_dark())
        self.assertLess(luminance(WALL), .05)


class AppearanceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-after-hours-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        settings.setValue("appearance", "light")
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.c.set_demo(True)
        self.c.tick()
        theme.apply(False)
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
        self.window.resize(1280, 800)
        QTest.qWait(30)

    def tearDown(self):
        self.window.exiting = True
        if self.window.mini_player is not None:
            self.window.mini_player.hide()
            self.window.mini_player.deleteLater()
        self.window.hide()
        self.window.tray.hide()
        self.window.immersive.media_background.close()
        self.c.close()
        self.c.audio.thread.join(1)
        for widget in (self.window.overlay, *self.window.edges, self.window):
            widget.hide()
            widget.deleteLater()
        theme.follow("system")
        theme.apply(False)
        QApplication.processEvents()
        self.temp.cleanup()

    def test_appearance_switches_the_whole_window_and_is_remembered(self):
        self.assertFalse(theme.is_dark())
        self.c.set("appearance", "dark")
        self.assertTrue(theme.is_dark())
        self.assertIn("#e6ece6", QApplication.instance().styleSheet())
        self.assertIn("#93a29c", self.window.album_label.styleSheet())
        self.assertEqual(self.c.settings.value("appearance"), "dark")
        dark_shot = self.window.grab().toImage()
        self.assertLess(lightness(dark_shot, dark_shot.width() - 30, dark_shot.height() // 2), 60)
        self.c.set("appearance", "light")
        self.assertFalse(theme.is_dark())
        light_shot = self.window.grab().toImage()
        self.assertGreater(lightness(light_shot, light_shot.width() - 30, light_shot.height() // 2), 170)

    def test_other_settings_never_flip_the_light(self):
        self.c.set("reduced_motion", True)
        self.assertFalse(theme.is_dark())

    def test_the_settings_page_offers_the_appearance(self):
        select = self.window.setting_controls["appearance"]
        self.assertEqual([select.itemData(i) for i in range(select.count())], ["system", "light", "dark"])
        select.setCurrentIndex(select.findData("dark"))
        self.assertEqual(self.c.appearance, "dark")
        self.assertTrue(theme.is_dark())

    def test_the_mini_player_case_is_dark_and_its_print_brings_halo_back(self):
        self.window.open_mini_player()
        QTest.qWait(30)
        mini = self.window.mini_player
        shot = mini.grab().toImage()
        ratio = shot.devicePixelRatio()
        card = mini.card()
        # Sampled beside the play key, on the bare case.
        self.assertLess(lightness(shot, (card.right() - 8) * ratio, card.center().y() * ratio), 70)
        # The print sits inside the case.
        self.assertTrue(card.contains(mini.frame_rect()))
        restored = []
        mini.restoreRequested.connect(lambda: restored.append(True))
        QTest.mouseClick(mini, Qt.MouseButton.LeftButton, pos=mini.frame_rect().center().toPoint())
        self.assertEqual(restored, [True])

    def test_the_share_sheet_starts_on_the_app_wall_and_can_switch(self):
        self.c.set("appearance", "dark")
        self.window.open_share_card()
        QTest.qWait(30)
        dialog = self.window.share_dialog
        self.assertTrue(dialog.dark)
        self.assertTrue(dialog.dark_wall.isChecked())
        QTest.mouseClick(dialog.light_wall, Qt.MouseButton.LeftButton)
        self.assertFalse(dialog.dark)
        self.assertTrue(theme.is_dark())
        self.assertGreater(lightness(dialog.image, CARD_SIZE.width() - 6, CARD_SIZE.height() - 6), 150)


if __name__ == "__main__":
    unittest.main()
