"""Flow, Vinyl and Horizon: rooms built from the song, and the light they share."""
import hashlib
import math
from types import SimpleNamespace
import unittest

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from halo import room_light, scene_rooms
from halo.immersive import IMMERSIVE_SCENES, Immersive
from halo.mode_catalog import BASE_MODE_KEYS
from halo.models import Track
from halo.room_light import CoverField, FIELD_CROSSFADE, cover_texture, exposure, field_pixels, swell
from halo.scene_extras import COMPACT_CREDITS, EXTRA_SCENES, SCENE_CAPTIONS, extra_scene_layout, paint_extra_scene
from halo.scene_rooms import ROOM_SCENES

from test_immersive_idle import DemoController

ROOMS = [key for key, _, _ in ROOM_SCENES]
SIZES = ((960, 640), (1000, 625), (1280, 800), (1536, 864), (1920, 1080), (2560, 1440))


def original_art(colours=("#365c9a", "#dd8f9f", "#e6cb79"), size=480):
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(colours[0]))
    p = QPainter(image)
    p.fillRect(QRectF(0, size * .65, size, size * .35), QColor(colours[1]))
    p.setBrush(QColor(colours[2]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(size * .2, size * .15, size * .6, size * .6))
    p.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def controller(playing=True, reduced=False, artwork=b"", position=30., pulse=0.):
    return SimpleNamespace(track=Track("Original room", "Halo tests", "Colour study", 90, position, playing, True, artwork),
                           primary=QColor("#b8dcd3"), secondary=QColor("#a6a4df"),
                           halo_primary=QColor("#f28c5c"), halo_secondary=QColor("#4b7bd8"),
                           reduced_motion=reduced, motion_time=12., position=position, pulse=pulse)


def render(scene, c, phase=12, width=1000, height=625):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#0c1018"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        assert paint_extra_scene(painter, width, height, c, scene, phase)
    finally:
        painter.end()
    return image


def digest(image):
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


def luminance(pixels):
    return (pixels.astype(np.float32) / 255.) @ np.array([.2126, .7152, .0722], dtype=np.float32)


class RoomCatalogueTests(unittest.TestCase):
    def test_three_new_rooms_are_included_after_the_original_four(self):
        self.assertEqual(ROOMS, ["flow", "vinyl", "horizon"])
        self.assertEqual(BASE_MODE_KEYS["scenes"], ("studio", "lyrics", "cinema", "orbit", "flow", "vinyl", "horizon"))
        self.assertEqual([key for key, _, _ in IMMERSIVE_SCENES],
                         ["studio", "lyrics", "cinema", "orbit", *ROOMS, *(key for key, _, _ in EXTRA_SCENES)])
        for key in ROOMS:
            self.assertIn(key, SCENE_CAPTIONS)
        self.assertIn("horizon", COMPACT_CREDITS)


class RoomLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_room_keeps_its_parts_on_screen_apart_and_clear_of_the_handset(self):
        for width, height in SIZES:
            canvases = set()
            for scene in ROOMS:
                with self.subTest(scene=scene, size=(width, height)):
                    layout = extra_scene_layout(scene, width, height)
                    for key in ("cover", "canvas", "song", "artist", "album", "status"):
                        rect = layout[key]
                        self.assertGreater(rect.width(), 0)
                        self.assertGreaterEqual(rect.left(), 0)
                        self.assertGreaterEqual(rect.top(), 65)
                        self.assertLess(rect.right(), width)
                        self.assertLess(rect.bottom(), height - 120)
                    for key in ("cover", "song", "artist", "album"):
                        self.assertFalse(layout[key].intersects(layout["canvas"]), key)
                    self.assertGreaterEqual(layout["canvas"].height(), 160)
                    canvases.add(tuple(layout["canvas"].getRect()))
            self.assertEqual(len(canvases), 3)

    def test_the_turntable_runs_off_the_corner_and_stays_left_of_the_words(self):
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                stage = scene_rooms._vinyl_stage(width, height)
                radius, centre, deck = stage.radius, stage.centre, stage.deck
                layout = extra_scene_layout("vinyl", width, height)
                self.assertTrue(layout["paints_cover"])
                self.assertNotIn("credits", layout)
                # Close up: the deck runs off the left and bottom edges, the record off the bottom.
                self.assertLess(deck.left(), 0)
                self.assertGreater(deck.bottom(), height)
                self.assertGreater(centre.y() + radius, height)
                # The deck, the tonearm's counterweight and the record all stay left of the words.
                reach = max(deck.right(), stage.pivot.x() + radius * .3, centre.x() + radius * 1.035)
                self.assertLess(reach, layout["canvas"].left())
                # The speed keys stay on screen, and the record sits below the sleeve and credits.
                for key in stage.speed_keys:
                    self.assertLess(key.bottom(), height)
                    self.assertLess(key.right(), deck.right())
                self.assertGreater(deck.top(), layout["album"].bottom())

    def test_the_sleeve_shows_the_whole_cover_beside_the_deck(self):
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                stage = scene_rooms._vinyl_stage(width, height)
                layout = extra_scene_layout("vinyl", width, height)
                sleeve = QRectF(layout["cover"])
                self.assertEqual(sleeve, stage.sleeve.toRect().toRectF())
                self.assertAlmostEqual(sleeve.width(), sleeve.height(), delta=1)
                # At most a sliver of the sleeve is tucked under the deck.
                self.assertLess(max(0., sleeve.bottom() - stage.deck.top()), sleeve.height() * .12)
                for key in ("song", "artist", "album"):
                    self.assertGreater(layout[key].left(), sleeve.right())

    def test_the_horizon_sun_never_rises_into_the_line_being_sung(self):
        for width, height in SIZES:
            with self.subTest(size=(width, height)):
                layout = extra_scene_layout("horizon", width, height)
                horizon = scene_rooms._horizon_y(width, height)
                radius = scene_rooms._sun_radius(width, height)
                highest_sun_top = horizon - radius * 1.55
                self.assertGreater(highest_sun_top, layout["canvas"].center().y() + 20)
                self.assertLess(layout["canvas"].bottom(), horizon)
                self.assertGreater(layout["cover"].top(), horizon)


class RoomPaintingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_room_is_its_own_picture(self):
        art = original_art()
        self.assertEqual(len({digest(render(scene, controller(artwork=art))) for scene in ROOMS}), 3)

    def test_rooms_move_while_playing_and_hold_still_when_paused_or_reduced(self):
        art = original_art()
        for scene in ROOMS:
            with self.subTest(scene=scene):
                self.assertNotEqual(digest(render(scene, controller(artwork=art), phase=1)),
                                    digest(render(scene, controller(artwork=art), phase=6)))
                still = controller(artwork=art, reduced=True)
                self.assertEqual(digest(render(scene, still, phase=1)), digest(render(scene, still, phase=6)))
                paused = controller(artwork=art, playing=False)
                self.assertEqual(digest(render(scene, paused, phase=1)), digest(render(scene, paused, phase=99)))

    def test_rooms_use_the_actual_cover_and_ignore_a_broken_one(self):
        art = original_art()
        for scene in ("flow", "vinyl"):
            with self.subTest(scene=scene):
                none = digest(render(scene, controller(reduced=True)))
                self.assertNotEqual(none, digest(render(scene, controller(reduced=True, artwork=art))))
                self.assertEqual(none, digest(render(scene, controller(reduced=True, artwork=b"not an image"))))

    def test_vinyl_tonearm_follows_the_song_from_the_outer_groove_inwards(self):
        stage = scene_rooms._vinyl_stage(1536, 864)
        radius, centre, pivot = stage.radius, stage.centre, stage.pivot
        distances = []
        for fraction in (0., .5, 1.):
            reach = radius * (.93 - .5 * fraction)
            needle = scene_rooms._stylus(centre, radius, pivot, reach, radius)
            self.assertAlmostEqual(math.hypot(needle.x() - centre.x(), needle.y() - centre.y()), reach, delta=.5)
            self.assertAlmostEqual(math.hypot(needle.x() - pivot.x(), needle.y() - pivot.y()), radius, delta=.5)
            distances.append(reach)
        self.assertEqual(distances, sorted(distances, reverse=True))
        start = digest(render("vinyl", controller(reduced=True, position=0)))
        end = digest(render("vinyl", controller(reduced=True, position=90)))
        self.assertNotEqual(start, end)

    def test_the_record_turns_slowly_once_every_seven_and_a_half_seconds(self):
        self.assertEqual(scene_rooms.RPM, 8)
        art = original_art()
        start = digest(render("vinyl", controller(artwork=art), phase=3))
        self.assertNotEqual(start, digest(render("vinyl", controller(artwork=art), phase=4)))
        self.assertEqual(start, digest(render("vinyl", controller(artwork=art), phase=3 + 7.5)))

    def test_horizon_sun_sets_as_the_song_plays(self):
        early = render("horizon", controller(reduced=True, position=5))
        late = render("horizon", controller(reduced=True, position=85))
        self.assertNotEqual(digest(early), digest(late))
        # Just above the horizon, in the middle of the bay, the late sky holds less sunlight.
        horizon = scene_rooms._horizon_y(1000, 625)
        radius = scene_rooms._sun_radius(1000, 625)
        y = round(horizon - radius * 1.2)
        self.assertGreater(QColor(early.pixel(500, y)).lightness(), QColor(late.pixel(500, y)).lightness() + 20)

    def test_refraction_glass_fades_out_instead_of_ending_in_a_hard_rectangle(self):
        image = render("scene_refraction", controller(artwork=original_art()))
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        rows = np.frombuffer(bytes(image.constBits()), np.uint8).reshape(625, image.bytesPerLine())
        light = rows[:, :3000].reshape(625, 1000, 3).astype(float).sum(axis=2)
        # The old clip ended at x = 560 and y = 515 with an average step of about 9 to 11 here.
        left = max(abs((light[120:500, x + 1] - light[120:500, x]).mean()) for x in range(556, 564))
        bottom = max(abs((light[y + 1, 600:980] - light[y, 600:980]).mean()) for y in range(511, 519))
        self.assertLess(left, 2.)
        self.assertLess(bottom, 2.)

    def test_flow_keeps_your_own_background_and_whole_scene_rooms_cover_it(self):
        c = controller(artwork=original_art(), reduced=True)
        def over_red(scene, backdrop):
            image = QImage(1000, 625, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#d02020"))
            painter = QPainter(image)
            paint_extra_scene(painter, 1000, 625, c, scene, 0, backdrop)
            painter.end()
            return QColor(image.pixel(700, 120))
        kept = over_red("flow", True)
        self.assertGreater(kept.red(), kept.green() + 40)
        self.assertNotEqual(over_red("flow", False).rgb(), kept.rgb())
        for scene in ("vinyl", "horizon"):
            with self.subTest(scene=scene):
                self.assertEqual(over_red(scene, True).rgb(), over_red(scene, False).rgb())

    def flow_frames(self, art, frames=range(0, 60, 6), width=1000, height=625):
        """Flow's backdrop for one listener over a minute of play, as linear and display values."""
        scene_rooms._FIELDS.clear()
        c = controller(artwork=art, pulse=.8)
        for phase in frames:
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#000000"))
            painter = QPainter(image)
            paint_extra_scene(painter, width, height, c, "flow", float(phase))
            painter.end()
            image = image.convertToFormat(QImage.Format.Format_RGB888)
            rows = np.frombuffer(bytes(image.constBits()), np.uint8).reshape(height, image.bytesPerLine())
            yield rows[:, :width * 3].reshape(height, width, 3).astype(np.float32) / 255.

    def test_flow_is_colourful_and_dark_covers_glow_instead_of_going_black(self):
        for name, colours in (("bright", ("#365c9a", "#dd8f9f", "#e6cb79")), ("dark", ("#050505", "#0b0b0e", "#c0182a"))):
            with self.subTest(cover=name):
                frames = list(self.flow_frames(original_art(colours), range(0, 60, 12)))
                level = np.mean([frame.mean() for frame in frames])
                chroma = np.mean([(frame.max(axis=2) - frame.min(axis=2)).mean() for frame in frames])
                self.assertGreater(level, .2)
                self.assertGreater(chroma, .2)

    def test_flow_keeps_words_and_credits_readable(self):
        # White text needs the background's relative luminance at or under 0.183 for 4.5:1.
        layout = extra_scene_layout("flow", 1000, 625)
        words, credits = layout["canvas"], layout["song"].united(layout["album"])
        regions = {
            "words": (slice(words.center().y() - 35, words.center().y() + 35),
                      slice(words.left() + words.width() // 5, words.right() - words.width() // 5)),
            "credits": (slice(credits.top(), credits.bottom()),
                        slice(credits.left(), credits.left() + credits.width() * 7 // 10)),
        }
        weights = np.array([.2126, .7152, .0722], dtype=np.float32)
        covers = {"bright": ("#365c9a", "#dd8f9f", "#e6cb79"), "dark": ("#050505", "#0b0b0e", "#c0182a"),
                  "white": ("#ffffff", "#f4f4f4", "#e8e8e8"), "yellow": ("#ffe14d", "#ffd000", "#fff2a8")}
        for name, colours in covers.items():
            worst = dict.fromkeys(regions, 0.)
            for frame in self.flow_frames(original_art(colours)):
                linear = np.where(frame <= .04045, frame / 12.92, ((frame + .055) / 1.055) ** 2.4) @ weights
                for key, (ys, xs) in regions.items():
                    worst[key] = max(worst[key], float(np.percentile(linear[ys, xs], 90)))
            for key, value in worst.items():
                with self.subTest(cover=name, region=key):
                    self.assertLessEqual(value, .183)

    def test_painter_state_is_preserved(self):
        image = QImage(1000, 625, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(image)
        p.translate(2, 3)
        before = p.transform()
        try:
            for scene in ROOMS:
                self.assertTrue(paint_extra_scene(p, 1000, 625, controller(), scene, 1))
                self.assertEqual(p.transform(), before)
                self.assertEqual(p.opacity(), 1.)
        finally:
            p.end()


class RoomLightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_swell_is_quiet_unless_the_music_is_moving(self):
        self.assertEqual(swell(controller(pulse=.7)), .7)
        self.assertEqual(swell(controller(pulse=.7, playing=False)), 0.)
        self.assertEqual(swell(controller(pulse=.7, reduced=True)), 0.)
        self.assertEqual(swell(controller(pulse=float("nan"))), 0.)
        self.assertEqual(swell(controller(pulse=4.)), 1.)
        self.assertEqual(swell(SimpleNamespace(track=Track(playing=True))), 0.)

    def test_progress_handles_unknown_lengths(self):
        self.assertAlmostEqual(room_light.progress(controller(position=45)), .5)
        c = controller(position=45)
        c.track.duration = 0
        self.assertEqual(room_light.progress(c), 0.)
        c.track.duration = 90
        c.position = float("inf")
        self.assertEqual(room_light.progress(c), 0.)

    def test_the_field_reads_behind_white_words_for_pale_dark_and_bright_covers(self):
        covers = {"pale": ("#f1ece2", "#e9e1d4", "#d7cbb8"), "dark": ("#050505", "#0b0b0e", "#c0182a"),
                  "bright": ("#ffd23f", "#ff4f79", "#3bceac")}
        means = {}
        for name, colours in covers.items():
            texture = cover_texture(original_art(colours))
            pixels = field_pixels(texture, 96, 54, 12., 0., exposure(texture, .68))
            level = luminance(pixels)
            means[name] = float(level.mean())
            with self.subTest(cover=name):
                self.assertLess(level.mean(), .34)
                self.assertLess(level.max(), .66)
        # A pale cover is pulled down, a dark one lifted, towards the same level.
        self.assertLess(abs(means["pale"] - means["dark"]), .2)
        self.assertGreater(means["dark"], .05)

    def test_glow_fills_the_dark_folds_with_the_song_colours(self):
        black = np.zeros((8, 8, 3), dtype=np.float32)
        plain = field_pixels(black, 48, 27, 3.)
        self.assertEqual(int(plain.max()), 0)
        orange, blue = np.array([1., .5, .2], dtype=np.float32), np.array([.2, .4, 1.], dtype=np.float32)
        lit = field_pixels(black, 48, 27, 3., glow=(.34, orange, blue)).astype(float) / 255.
        self.assertGreater(lit.mean(), .08)
        self.assertGreater((lit.max(axis=2) - lit.min(axis=2)).mean(), .08)

    def test_a_new_cover_pours_into_the_field_while_playing(self):
        first, second = original_art(), original_art(("#2b6f77", "#e07a5f", "#efe9df"))
        c = controller(artwork=first)
        field = CoverField(columns=48)
        before = field.image(c, 480, 270, 3., now=100.).copy()
        c.track.artwork = second
        # The pour starts from the frame on screen when the new cover arrives.
        self.assertEqual(digest(field.image(c, 480, 270, 3., now=100.3)), digest(before))
        during = field.image(c, 480, 270, 3., now=100.3 + FIELD_CROSSFADE / 2).copy()
        after = field.image(c, 480, 270, 3., now=100.3 + FIELD_CROSSFADE + .5).copy()
        fresh = CoverField(columns=48).image(c, 480, 270, 3., now=0.)
        self.assertNotEqual(digest(during), digest(before))
        self.assertNotEqual(digest(during), digest(fresh))
        self.assertEqual(digest(after), digest(fresh))

    def test_without_a_cover_the_field_pours_from_the_song_colours(self):
        c = controller()
        image = CoverField(columns=32).image(c, 320, 180, 0., now=0.)
        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), 32)

    def test_the_field_updates_at_thirty_frames_a_second_but_never_holds_a_jump(self):
        c = controller(artwork=original_art())
        field = CoverField(columns=32)
        first = digest(field.image(c, 320, 180, 10., now=50.))
        self.assertEqual(digest(field.image(c, 320, 180, 10.016, now=50.016)), first)
        self.assertNotEqual(digest(field.image(c, 320, 180, 10.04, now=50.04)), first)
        self.assertNotEqual(digest(field.image(c, 320, 180, 15., now=50.05)), first)

    def test_the_field_is_computed_small(self):
        c = controller(artwork=original_art())
        image = CoverField().image(c, 3840, 2160, 5., now=0.)
        self.assertLessEqual(image.width() * image.height(), 168 * 95)


class ImmersiveRoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.c = DemoController()
        self.c.track.artwork = original_art()
        self.window = Immersive(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.show()

    def tearDown(self):
        self.window.hide()
        self.window.media_background.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_rooms_place_the_real_widgets_and_vinyl_paints_its_own_label(self):
        for scene in ROOMS:
            self.c.set("immersive_mode", scene)
            for width, height in ((960, 640), (1920, 1080)):
                with self.subTest(scene=scene, size=(width, height)):
                    self.window.resize(width, height)
                    self.window._arrange()
                    layout = extra_scene_layout(scene, width, height)
                    self.assertEqual(self.window.canvas.geometry(), layout["canvas"])
                    self.assertEqual(self.window.cover.isVisible(), scene != "vinyl")
                    self.assertLess(self.window.canvas.geometry().bottom(), self.window.player.geometry().top())
                    self.assertEqual(self.window.scene_caption.text(), SCENE_CAPTIONS[scene])
                    self.assertFalse(self.window.scene_caption.isVisible())
                    self.assertTrue(self.window.title.alignment() & Qt.AlignmentFlag.AlignLeft)
                    self.assertFalse(self.window.grab().isNull())

    def test_no_room_shows_small_print_even_with_the_controls_up(self):
        self.c.lyrics.message = "Line synced"
        for scene, _, _ in IMMERSIVE_SCENES:
            for width in (960, 1536):
                with self.subTest(scene=scene, width=width):
                    self.c.set("immersive_mode", scene)
                    self.window.resize(width, 864)
                    self.window._arrange()
                    self.window._wake_chrome()
                    self.assertTrue(self.window.lyrics_status.text())
                    for label in (self.window.lyrics_status, self.window.scene_caption,
                                  self.window.now_label, self.window.words_label):
                        self.assertFalse(label.isVisible(), label.text())

    def test_original_rooms_drop_their_captions(self):
        for scene in ("studio", "orbit"):
            with self.subTest(scene=scene):
                self.c.set("immersive_mode", scene)
                self.window.resize(1280, 800)
                self.window._arrange()
                self.assertFalse(self.window.now_label.isVisible())
                self.assertFalse(self.window.words_label.isVisible())
                self.assertTrue(self.window.cover.isVisible())

    def test_background_switch_is_off_limits_in_whole_scene_rooms(self):
        self.c.background_source = "image"
        for scene, allowed in (("studio", True), ("flow", True), ("vinyl", False), ("horizon", False)):
            with self.subTest(scene=scene):
                self.c.set("immersive_mode", scene)
                entry = next(item for item in self.window.menu_entries() if item.text == "Background")
                self.assertEqual(entry.enabled(), allowed)
                if not allowed:
                    self.assertFalse(self.window.media_background._active)

    def test_rooms_are_in_the_room_menu(self):
        names = [self.window.scene_select.itemData(i) for i in range(self.window.scene_select.count())]
        for scene in ROOMS:
            self.assertIn(scene, names)


if __name__ == "__main__":
    unittest.main()
