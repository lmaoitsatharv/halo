"""Settings interaction, isolated live previews and window restoration."""
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import Qt, QSettings, QEvent, QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from halo.app import Controller, MainWindow


class SettingsStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-studio-", dir=Path(__file__).resolve().parents[1] / ".cache")
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.studio = self.window.settings_dialog
        self.studio.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.studio.hide()
        self.window.hide()
        self.window.draw_timer.stop()
        self.window.tray.hide()
        for widget in [self.window.immersive, self.window.overlay, *self.window.edges]:
            widget.hide()
            widget.deleteLater()
        self.c.close()
        self.c.audio.thread.join(1)
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def open_studio(self):
        QTest.mouseClick(self.window.settings_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def test_familiar_settings_entry_opens_general_and_navigation_changes_preview(self):
        self.open_studio()
        self.assertTrue(self.studio.isVisible())
        self.assertEqual(self.studio.section, "general")
        self.assertEqual(self.studio.pages.currentIndex(), 0)
        self.assertEqual(self.window.settings_shortcut.key().toString(), "Ctrl+,")
        for index, (key, title, _) in enumerate(self.studio.SECTIONS):
            QTest.mouseClick(self.studio.nav_buttons[index], Qt.MouseButton.LeftButton)
            self.assertEqual(self.studio.section, key)
            self.assertEqual(self.studio.page_title.text(), title)
            self.assertEqual(self.studio.preview.scene.section, key)
        self.studio.close()
        self.open_studio()
        self.assertEqual(self.studio.section, "general")

    def test_switches_sliders_and_mode_changes_reach_saved_preferences_and_preview(self):
        self.open_studio()
        self.c.set("reduced_motion", True)
        self.studio.select(1)
        preview = self.studio.preview.scene
        off = bytes(preview.grab().toImage().constBits())
        QTest.mouseClick(self.studio.switches["glow"], Qt.MouseButton.LeftButton)
        self.assertTrue(self.c.glow)
        on = bytes(preview.grab().toImage().constBits())
        self.assertNotEqual(off, on)
        self.studio.light_controls.sliders["glow_width"].setValue(97)
        self.assertEqual(self.c.glow_width, 97)
        self.assertEqual(self.c.settings.value("width", type=int), 97)
        self.studio.halo_style.setCurrentIndex(self.studio.halo_style.findData("pulse"))
        self.assertEqual(self.c.halo_mode, "pulse")
        self.assertEqual(self.studio.preview.caption.text(), "Pulse")
        self.c.set("glow", False)
        self.assertFalse(self.studio.switches["glow"].isChecked())
        self.assertEqual(self.studio.switches["glow"].knob, 0.)

    def test_preview_samples_do_not_start_demo_or_modify_song_and_lyrics(self):
        track, lyrics = self.c.track, self.c.lyrics
        before = {key: self.c.settings.value(key) for key in self.c.settings.allKeys()}
        self.open_studio()
        self.studio.select(2)
        QTest.qWait(80)
        self.studio.preview.scene.grab()
        self.assertIs(self.c.track, track)
        self.assertIs(self.c.lyrics, lyrics)
        self.assertFalse(self.c.demo)
        self.assertFalse(self.c.audio.enabled)
        self.assertEqual(before, {key: self.c.settings.value(key) for key in self.c.settings.allKeys()})
        self.assertTrue(self.studio.preview.scene.proxy.uses_sample)

    def test_transitions_settle_and_reduce_motion_stops_them_immediately(self):
        self.open_studio()
        self.studio.select(1)
        self.assertEqual(self.studio.curtain.animation.state(), QAbstractAnimation.State.Running)
        self.assertEqual(self.studio.nav_animation.state(), QAbstractAnimation.State.Running)
        self.assertEqual(self.studio.preview.transition.animation.state(), QAbstractAnimation.State.Running)
        QTest.qWait(300)
        self.assertFalse(self.studio.curtain.isVisible())
        self.assertEqual(self.studio.selection.geometry(), self.studio.nav_buttons[1].geometry())
        self.studio.select(2)
        self.c.set("reduced_motion", True)
        self.assertEqual(self.studio.curtain.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(self.studio.nav_animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(self.studio.preview.transition.animation.state(), QAbstractAnimation.State.Stopped)
        self.studio.select(3)
        self.assertFalse(self.studio.curtain.isVisible())
        self.assertEqual(self.studio.selection.geometry(), self.studio.nav_buttons[3].geometry())

    def test_preview_stops_when_closed_and_escape_returns_to_main(self):
        self.open_studio()
        self.assertTrue(self.studio.preview.timer.isActive())
        QTest.keyClick(self.studio, Qt.Key.Key_Escape)
        self.assertFalse(self.studio.isVisible())
        self.assertFalse(self.studio.preview.timer.isActive())
        self.assertTrue(self.window.isVisible())

    def test_first_window_is_centered_inside_the_available_screen(self):
        area = self.window.screen().availableGeometry()
        frame = self.window.frameGeometry()
        self.assertLessEqual(abs(frame.center().x() - area.center().x()), 3)
        self.assertLessEqual(abs(frame.center().y() - area.center().y()), 3)
        self.assertTrue(area.contains(frame))

    def test_maximized_window_stays_maximized_after_immersive_and_minimize(self):
        self.window.showMaximized()
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.window.fullscreen()
        self.app.processEvents()
        self.window.immersive.leave()
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.c.settings.value("window_maximized", type=bool))
        self.window.showMinimized()
        self.app.processEvents()
        self.window.reopen()
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())

    def test_normal_window_retains_its_position_and_size_after_immersive(self):
        self.window.resize(910, 620)
        self.window.move(self.window.x() + 17, self.window.y() + 13)
        self.app.processEvents()
        geometry = self.window.geometry()
        self.window.fullscreen()
        self.app.processEvents()
        self.window.immersive.leave()
        self.app.processEvents()
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.geometry(), geometry)
