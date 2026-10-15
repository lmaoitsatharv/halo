from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from halo.app import Controller


class HaloControllerPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        self.temp = tempfile.TemporaryDirectory(prefix="halo-polish-settings-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.
        clock = patch("halo.app.time", SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for c in self.controllers:
            c.close()
            c.audio.thread.join(1)

    def controller(self, values=None):
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        for name, value in (values or {}).items():
            settings.setValue(name, value)
        c = Controller(settings, offline=True)
        c.timer.stop()
        self.controllers.append(c)
        return c

    def test_custom_black_is_preserved_while_lyrics_remain_readable(self):
        c = self.controller({"palette": "Custom", "custom_primary": "#000000", "custom_secondary": "#005dff"})
        self.assertEqual(c.halo_primary.name(), "#000000")
        self.assertEqual(c.halo_secondary.name(), "#005dff")
        self.assertGreater(c.primary.valueF(), .89)

    def test_independent_controls_persist_and_old_width_setting_migrates(self):
        c = self.controller({"width": 89})
        self.assertEqual(c.glow_width, 89)
        selected = {"rim_width": 7, "glow_opacity": 40, "primary_brightness": 30,
                    "secondary_brightness": 90, "color_mix": 73,
                    "custom_primary": "#000000", "custom_secondary": "#005dff"}
        for name, value in selected.items():
            c.set(name, value)
        c.settings.sync()
        restored = self.controller()
        for name, value in selected.items():
            self.assertEqual(getattr(restored, name), value)
        self.assertEqual(restored.glow_width, 89)

    def test_animation_and_audio_checkbox_do_not_contradict_each_other(self):
        c = self.controller()
        c.set("reactive", True)
        self.assertEqual(c.halo_animation, "music")
        c.set("halo_animation", "idle")
        self.assertFalse(c.reactive)
        c.set("halo_animation", "music")
        self.assertTrue(c.reactive)
        c.set("reactive", False)
        self.assertEqual(c.halo_animation, "flow")

    def test_speed_changes_preserve_phase_and_pause_cannot_accumulate_a_leap(self):
        c = self.controller()
        c.set_demo(True)
        self.now += .016
        c.tick()
        phase = c.motion_phase
        c.set("motion_speed", 100)
        self.assertEqual(c.motion_phase, phase)
        self.now += .016
        c.tick()
        self.assertAlmostEqual(c.motion_phase - phase, .016 * 100 / 45 / 26.28)
        c.transport("toggle")
        paused = c.motion_phase
        self.now += 90
        c.tick()
        self.assertEqual(c.motion_phase, paused)
        c.transport("toggle")
        self.now += .016
        c.tick()
        self.assertLess(c.motion_phase - paused, .002)

    def test_palette_change_is_continuous_and_finishes_while_still(self):
        c = self.controller({"palette": "Custom", "custom_primary": "#000000"})
        c.set("halo_animation", "still")
        c.set("custom_primary", "#ff0000")
        self.assertEqual(c.halo_primary.name(), "#000000")
        self.now += .45
        c.tick()
        self.assertNotIn(c.halo_primary.name(), ("#000000", "#ff0000"))
        self.now += .45
        c.tick()
        self.assertEqual(c.halo_primary.name(), "#ff0000")
        self.assertEqual(c.motion_phase, 0.)


if __name__ == "__main__":
    unittest.main()
