import unittest
from halo.models import floating_geometry


class PositionTests(unittest.TestCase):
    def test_all_positions_stay_within_monitor_and_taskbar_area(self):
        for screen in [(0, 0, 1536, 824), (-1920, 80, 1920, 1000), (100, -1080, 720, 1040), (0, 0, 320, 180)]:
            sx, sy, sw, sh = screen
            for horizontal in (0, 50, 100):
                for vertical in (0, 50, 100):
                    x, y, w, h = floating_geometry(screen, horizontal, vertical)
                    self.assertGreaterEqual(x, sx)
                    self.assertGreaterEqual(y, sy)
                    self.assertLessEqual(x + w, sx + sw)
                    self.assertLessEqual(y + h, sy + sh)

    def test_center_uses_correct_secondary_monitor_origin(self):
        x, y, w, h = floating_geometry((-1600, 80, 1600, 900), 50, 50)
        self.assertAlmostEqual(x + w / 2, -800, delta=1)
        self.assertAlmostEqual(y + h / 2, 530, delta=1)

    def test_out_of_range_preferences_are_clamped(self):
        screen = (0, 0, 1536, 824)
        self.assertEqual(floating_geometry(screen, -100, 500), floating_geometry(screen, 0, 100))


if __name__ == "__main__":
    unittest.main()
