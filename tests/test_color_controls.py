"""Native halo controls preserve raw colours and synchronize external changes."""
import unittest
import warnings
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog
from PySide6.QtTest import QTest

from halo.color_controls import LightControls, PALETTES


class SettingsController(QObject):
    settingChanged = Signal()
    trackChanged = Signal()
    paletteChanged = Signal()

    def __init__(self):
        super().__init__()
        self.palette = "Album colours"
        self.primary, self.secondary = QColor("#e1c2ff"), QColor("#b8e9e4")
        self.halo_primary, self.halo_secondary = QColor("#081121"), QColor("#124dad")
        self.custom_primary, self.custom_secondary = "#0a0d14", "#005dff"
        self.primary_brightness, self.secondary_brightness, self.color_mix = 100, 100, 60
        self.rim_width, self.glow_width, self.glow_opacity = 3, 40, 65
        self.intensity, self.motion_speed, self.halo_animation = 62, 45, "flow"
        self.reactive = False
        self.writes = []

    def set(self, name, value):
        self.writes.append((name, value))
        setattr(self, name, value)
        self.settingChanged.emit()


class FakeDialog(QObject):
    colorSelected = Signal(QColor)
    finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.opened = False

    def setWindowTitle(self, value):
        self.title = value

    def setOption(self, option, value):
        pass

    def open(self):
        self.opened = True


class ColorControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.c = SettingsController()
        self.controls = LightControls(self.c)
        self.controls.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.controls.resize(290, 420)
        self.controls.show()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.app.setActiveWindow(self.controls)
        self.app.processEvents()

    def tearDown(self):
        self.controls.hide()
        self.controls.deleteLater()
        self.app.processEvents()

    def test_preset_wells_use_actual_raw_halo_colours_not_readable_ui_accents(self):
        self.assertEqual(self.controls.primary_well.hex_color, "#081121")
        self.assertEqual(self.controls.secondary_well.hex_color, "#124dad")
        self.assertNotEqual(self.controls.primary_well.hex_color, self.c.primary.name())
        self.c.halo_primary = QColor("#03070d")
        self.c.paletteChanged.emit()
        self.assertEqual(self.controls.primary_well.hex_color, "#03070d")
        self.assertEqual(self.c.writes, [])

    def test_custom_wells_keep_saved_dark_colours_while_raw_halo_transitions(self):
        self.c.set("palette", "Custom")
        self.c.halo_primary = QColor("#bda7ff")
        self.c.primary_brightness = 20
        self.c.secondary_brightness = 35
        self.c.trackChanged.emit()
        self.controls._refresh_live_wells()
        self.assertEqual(self.controls.primary_well.hex_color, "#0a0d14")
        self.assertEqual(self.controls.secondary_well.hex_color, "#005dff")
        self.assertEqual(self.controls.primary_well.text(), "#0A0D14")

    def test_primary_choice_switches_to_custom_without_changing_secondary_or_brightness(self):
        self.c.primary_brightness, self.c.secondary_brightness = 21, 73
        self.controls.set_custom_color("primary", QColor("#020409"))
        self.assertEqual(self.c.writes, [("custom_primary", "#020409"), ("palette", "Custom")])
        self.assertEqual(self.c.custom_secondary, "#005dff")
        self.assertEqual((self.c.primary_brightness, self.c.secondary_brightness, self.c.color_mix), (21, 73, 60))
        self.assertEqual(self.c.primary.name(), "#e1c2ff")
        self.assertEqual(self.controls.primary_well.hex_color, "#020409")

    def test_secondary_choice_preserves_primary_and_does_not_rewrite_custom_palette(self):
        self.c.set("palette", "Custom")
        self.c.writes.clear()
        self.controls.set_custom_color("secondary", "#2255ff")
        self.assertEqual(self.c.writes, [("custom_secondary", "#2255ff")])
        self.assertEqual(self.c.custom_primary, "#0a0d14")
        self.c.set("palette", "Ember")
        self.c.trackChanged.emit()
        self.assertEqual((self.c.custom_primary, self.c.custom_secondary), ("#0a0d14", "#2255ff"))

    def test_external_settings_sync_without_recursive_writes(self):
        self.c.set("rim_width", 11)
        self.c.set("glow_width", 155)
        self.c.set("glow_opacity", 18)
        self.c.set("primary_brightness", 42)
        self.c.set("secondary_brightness", 12)
        self.c.set("color_mix", 82)
        self.assertEqual(len(self.c.writes), 6)
        for field, expected in (("rim_width", 11), ("glow_width", 155), ("glow_opacity", 18),
                                ("primary_brightness", 42), ("secondary_brightness", 12), ("color_mix", 82)):
            self.assertEqual(self.controls.sliders[field].value(), expected)
        self.assertEqual(self.controls.mix_balance.text(), "Primary 82%  ·  Secondary 18%")
        self.assertEqual(self.controls.value_labels["rim_width"].text(), "11 px")

    def test_animation_still_remembers_speed_and_ui_does_not_write_separate_audio_setting(self):
        self.c.set("motion_speed", 77)
        self.c.set("halo_animation", "still")
        self.assertFalse(self.controls.sliders["motion_speed"].isEnabled())
        self.assertEqual(self.controls.sliders["motion_speed"].value(), 77)
        self.controls.animation_select.setCurrentIndex(self.controls.animation_select.findData("music"))
        self.assertTrue(self.controls.sliders["motion_speed"].isEnabled())
        self.assertEqual(self.c.motion_speed, 77)
        self.assertFalse(self.c.reactive)
        self.assertEqual(self.c.writes[-1], ("halo_animation", "music"))
        self.assertFalse(any(name == "reactive" for name, value in self.c.writes))

    def test_ranges_and_presets_remain_available(self):
        self.assertEqual((self.controls.sliders["rim_width"].minimum(), self.controls.sliders["rim_width"].maximum()), (1, 12))
        self.assertEqual((self.controls.sliders["glow_width"].minimum(), self.controls.sliders["glow_width"].maximum()), (12, 160))
        for field in ("glow_opacity", "intensity", "primary_brightness", "secondary_brightness", "color_mix", "motion_speed"):
            self.assertEqual((self.controls.sliders[field].minimum(), self.controls.sliders[field].maximum()), (0, 100))
        self.assertEqual([self.controls.palette_select.itemText(i) for i in range(self.controls.palette_select.count())], list(PALETTES))

    def test_colour_wells_are_keyboard_actionable_and_tabs_stay_synchronized(self):
        self.controls.pages.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(self.controls.tabs.checkedId(), 1)
        self.controls.primary_well.setFocus(Qt.FocusReason.TabFocusReason)
        with patch.object(self.controls, "_choose_color") as choose:
            QTest.keyClick(self.controls.primary_well, Qt.Key.Key_Space)
            choose.assert_called_once_with("primary")
        self.assertIn("primary", self.controls.primary_well.accessibleName())
        self.assertIn("#", self.controls.primary_well.accessibleName())

    def test_dialog_cancel_has_no_write_and_accept_persists_selected_colour(self):
        option = QColorDialog.ColorDialogOption
        for accept in (False, True):
            with self.subTest(accept=accept):
                dialog = FakeDialog()
                with patch("halo.color_controls.QColorDialog", return_value=dialog) as factory:
                    factory.ColorDialogOption = option
                    self.controls._choose_color("secondary")
                    self.assertTrue(dialog.opened)
                    self.assertEqual(factory.call_args.args[0], QColor("#124dad"))
                    if accept:
                        dialog.colorSelected.emit(QColor("#145aff"))
                    dialog.finished.emit(1 if accept else 0)
                self.assertIsNone(self.controls.color_dialog)
                if accept:
                    self.assertEqual(self.c.custom_secondary, "#145aff")
                    self.assertEqual(self.c.palette, "Custom")
                else:
                    self.assertEqual(self.c.writes, [])

    def test_invalid_colour_and_side_cannot_modify_settings(self):
        with self.assertRaises(ValueError):
            self.controls.set_custom_color("other", "#ffffff")
        with self.assertRaises(ValueError):
            self.controls.set_custom_color("primary", "invalid")
        self.assertEqual(self.c.writes, [])


if __name__ == "__main__":
    unittest.main()
