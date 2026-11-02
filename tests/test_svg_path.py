"""SVG element conversion for the bundled Lucide icon set."""
import unittest

from PySide6.QtWidgets import QApplication

from halo.svg_path import element_path, icon_path, parse_path_data


class SvgPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_relative_lines_and_close(self):
        box = parse_path_data("M2 2h20v20H2z").boundingRect()
        self.assertEqual((box.x(), box.y(), box.width(), box.height()), (2, 2, 20, 20))

    def test_compact_numbers_and_arc_flags(self):
        self.assertFalse(parse_path_data("M3 3a1 1 0 00-2 0l.5.5").isEmpty())

    def test_half_circle_arc_bounds(self):
        box = parse_path_data("M12 2a10 10 0 0 1 0 20").boundingRect()
        self.assertAlmostEqual(box.right(), 22, 1)
        self.assertAlmostEqual(box.height(), 20, 1)

    def test_smooth_curve_reflects_previous_control(self):
        end = parse_path_data("M0 0c0 5 5 5 5 0s5-5 5 0").currentPosition()
        self.assertEqual((end.x(), end.y()), (10, 0))

    def test_quadratic_and_shorthand_commands_end_correctly(self):
        end = parse_path_data("M0 0q5 5 10 0t10 0").currentPosition()
        self.assertEqual((end.x(), end.y()), (20, 0))

    def test_each_element_kind_builds(self):
        cases = {"circle": {"cx": "12", "cy": "12", "r": "2"},
                 "ellipse": {"cx": "12", "cy": "12", "rx": "4", "ry": "2"},
                 "line": {"x1": "2", "y1": "2", "x2": "9", "y2": "9"},
                 "rect": {"x": "2", "y": "2", "width": "8", "height": "6", "rx": "2"},
                 "polyline": {"points": "2 2 8 8 2 12"},
                 "polygon": {"points": "2 2 8 8 2 12"},
                 "path": {"d": "M2 2h4"}}
        for tag, attrs in cases.items():
            self.assertFalse(element_path(tag, attrs).isEmpty(), tag)

    def test_unknown_element_and_bad_data_raise(self):
        with self.assertRaises(ValueError):
            element_path("image", {})
        with self.assertRaises(ValueError):
            parse_path_data("M2 2 Q")

    def test_icon_path_maps_grid_to_unit_box(self):
        box = icon_path([("line", {"x1": "2", "y1": "12", "x2": "22", "y2": "12"})]).boundingRect()
        self.assertEqual((box.left(), box.right()), (-1, 1))


if __name__ == "__main__":
    unittest.main()
