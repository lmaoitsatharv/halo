"""Original artwork fixtures verify the optional native immersive compositions."""
import hashlib
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from halo.models import Track
from halo.scene_extras import EXTRA_SCENES, extra_scene_layout, paint_extra_scene, _artwork_image


class ExtraSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self, playing=True, reduced=False, artwork=b""):
        return SimpleNamespace(track=Track("Original room", "Halo tests", "Colour study", 90,
                                          12, playing, True, artwork),
                               primary=QColor("#b8dcd3"), secondary=QColor("#a6a4df"),
                               reduced_motion=reduced, motion_time=12.)

    def render(self, scene, width=1000, height=625, c=None, phase=12):
        c = c or self.controller()
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#0c1018"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self.assertTrue(paint_extra_scene(painter, width, height, c, scene, phase))
        finally:
            painter.end()
        return image

    def digest(self, image):
        return hashlib.sha256(image.constBits()).hexdigest()

    def original_art(self, size=480):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#365c9a"))
        p = QPainter(image)
        p.fillRect(QRectF(0, size * .65, size, size * .35), QColor("#dd8f9f"))
        p.setBrush(QColor("#e6cb79"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(size * .2, size * .15, size * .6, size * .6))
        p.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    def test_three_scenes_have_separate_compositions_and_readable_reserved_regions(self):
        self.assertEqual([entry[0] for entry in EXTRA_SCENES],
                         ["scene_gallery", "scene_runway", "scene_refraction"])
        for width, height in ((960, 640), (1000, 625), (1280, 800), (1920, 1080)):
            layouts = []
            hashes = []
            for scene, _, _ in EXTRA_SCENES:
                with self.subTest(scene=scene, size=(width, height)):
                    layout = extra_scene_layout(scene, width, height)
                    self.assertEqual(set(layout), {"cover", "canvas", "song", "artist", "album", "status", "alignment"})
                    for key in ("cover", "canvas", "song", "artist", "album", "status"):
                        rect = layout[key]
                        self.assertGreater(rect.width(), 0)
                        self.assertGreater(rect.height(), 0)
                        self.assertGreaterEqual(rect.left(), 0)
                        self.assertGreaterEqual(rect.top(), 65)
                        self.assertLess(rect.right(), width)
                        self.assertLess(rect.bottom(), height - 120)
                    self.assertFalse(layout["cover"].intersects(layout["canvas"]))
                    for key in ("song", "artist", "album"):
                        self.assertFalse(layout[key].intersects(layout["canvas"]), key)
                    layouts.append(tuple(layout["canvas"].getRect()))
                    hashes.append(self.digest(self.render(scene, width, height)))
            self.assertEqual(len(set(layouts)), 3)
            self.assertEqual(len(set(hashes)), 3)

    def test_every_scene_has_visible_motion_and_freezes_with_reduced_motion(self):
        for scene, _, _ in EXTRA_SCENES:
            with self.subTest(scene=scene):
                c = self.controller()
                self.assertNotEqual(self.digest(self.render(scene, c=c, phase=1)),
                                    self.digest(self.render(scene, c=c, phase=6)))
                c.reduced_motion = True
                self.assertEqual(self.digest(self.render(scene, c=c, phase=1)),
                                 self.digest(self.render(scene, c=c, phase=6)))

    def test_pause_uses_the_frozen_shared_clock(self):
        for scene, _, _ in EXTRA_SCENES:
            with self.subTest(scene=scene):
                c = self.controller(playing=False)
                self.assertEqual(self.digest(self.render(scene, c=c, phase=1)),
                                 self.digest(self.render(scene, c=c, phase=99)))

    def test_refraction_uses_actual_artwork_and_discards_bad_artwork_safely(self):
        scene = "scene_refraction"
        empty = self.digest(self.render(scene))
        original = self.original_art()
        self.assertNotEqual(empty, self.digest(self.render(scene, c=self.controller(artwork=original))))
        self.assertEqual(empty, self.digest(self.render(scene, c=self.controller(artwork=b"not an image"))))
        self.assertTrue(_artwork_image(b"x" * (12 * 1024 * 1024 + 1)).isNull())

    def test_artwork_decode_is_bounded_and_cached(self):
        data = self.original_art(1500)
        first = _artwork_image(data)
        self.assertLessEqual(first.width(), 640)
        self.assertLessEqual(first.height(), 640)
        self.assertEqual(first.cacheKey(), _artwork_image(data).cacheKey())
        self.assertLessEqual(_artwork_image.cache_info().currsize, 4)

    def test_unknown_scenes_are_not_claimed_and_painter_state_is_preserved(self):
        self.assertIsNone(extra_scene_layout("studio", 1000, 625))
        image = QImage(1000, 625, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.translate(2, 3)
        before = p.transform()
        try:
            self.assertFalse(paint_extra_scene(p, 1000, 625, self.controller(), "studio", 1))
            for scene, _, _ in EXTRA_SCENES:
                self.assertTrue(paint_extra_scene(p, 1000, 625, self.controller(), scene, 1))
                self.assertEqual(p.transform(), before)
        finally:
            p.end()


if __name__ == "__main__":
    unittest.main()
