"""Update history: every version in one short line, newest first, with any waiting update on top."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QLabel

from halo import __version__, updater
from halo.app import Controller, MainWindow
from halo.release_history import RELEASES
from halo.updates import UpdateHistory
from test_updater import release_json

ROOT = Path(__file__).resolve().parents[1]


def labels(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


class ReleaseHistoryTests(unittest.TestCase):
    def test_every_release_has_a_date_and_one_short_line_newest_first(self):
        numbered = [version for version, _, _ in RELEASES if version[:1].isdigit()]
        self.assertEqual(len(set(numbered)), len(numbered))
        for newer, older in zip(numbered, numbered[1:]):
            self.assertTrue(updater.is_newer(newer, older), (newer, older))
        for version, date, line in RELEASES:
            with self.subTest(version=version):
                self.assertRegex(date, r"^\d{1,2} [A-Z][a-z]+ \d{4}$")
                self.assertLessEqual(len(line), 140)
                self.assertNotIn("\n", line)
                self.assertTrue(line.endswith("."))

    def test_this_version_is_in_the_history(self):
        # A release must add its line before it ships.
        self.assertEqual(RELEASES[0][0], __version__)


class UpdateHistoryWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = ROOT / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-update-history-", dir=scratch)
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("glow", False)
        self.c = Controller(settings, offline=True)
        self.c.timer.stop()
        self.window = MainWindow(self.c)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.draw_timer.stop()
        self.window.show()
        self.window.resize(1280, 800)
        QApplication.processEvents()

    def tearDown(self):
        self.window.exiting = True
        self.window.close()
        self.c.close()
        self.temp.cleanup()

    def open(self):
        self.window.open_update_history()
        self.assertTrue(self.window.sheet.isVisible())
        self.assertEqual(self.window.sheet.title.text(), "Update history")
        history = self.window.sheet.dialog
        self.assertIsInstance(history, UpdateHistory)
        return history

    def test_settings_and_the_tray_open_the_history(self):
        studio = self.window.settings_dialog
        self.assertEqual(studio.history_button.text(), "Update history")
        studio.history_button.click()
        self.assertIsInstance(self.window.sheet.dialog, UpdateHistory)
        self.window.sheet.dismiss()
        tray = [action for action in self.window.tray.contextMenu().actions() if action.text() == "Update history"]
        self.assertEqual(len(tray), 1)
        tray[0].trigger()
        self.assertIsInstance(self.window.sheet.dialog, UpdateHistory)

    def test_with_nothing_waiting_it_lists_every_version_and_marks_this_one(self):
        history = self.open()
        self.assertFalse(history.banner.isVisible())
        rows = history.versions()
        self.assertEqual([row[0] for row in rows], [version for version, _, _ in RELEASES])
        self.assertIn("Newest", rows[0][3])
        mine = [row for row in rows if row[0] == self.window.updates.version]
        self.assertEqual(len(mine), 1)
        self.assertIn("This version", mine[0][3])
        text = labels(history)
        for version, date, line in RELEASES:
            self.assertIn(line, text)
            self.assertIn(date, text)

    def test_a_waiting_update_sits_on_top_with_its_line_and_installs_from_the_banner(self):
        service = self.window.updates
        newer = "9.9.0"
        data = release_json(version=newer, body="A short line about it. More detail.\n\n## In this release\n- x")
        service.release = updater.pick_release(data)
        service.state = "ready"
        service.changed.emit()
        history = self.open()
        self.assertTrue(history.banner.isVisible())
        self.assertEqual(history.banner_title.text(), f"Halo {newer} is ready")
        self.assertEqual(history.banner_text.text(), "Halo restarts and is back in a few seconds.")
        self.assertEqual(history.banner_button.text(), "Update now")
        top = history.versions()[0]
        self.assertEqual(top[:3], (newer, "Ready to install", "A short line about it. More detail."))
        self.assertEqual(top[3], ["Newest"])
        self.assertNotIn("Newest", history.versions()[1][3])
        with mock.patch.object(service, "install", return_value=True) as install:
            history.banner_button.click()
        install.assert_called_once()
        # A copy that can't update itself is pointed at the download page instead.
        service.state, service.blocker = "available", "Halo's folder needs administrator rights."
        service.changed.emit()
        self.assertEqual(history.banner_title.text(), f"Halo {newer} is out")
        self.assertEqual(history.banner_button.text(), "Open download page")
        self.assertIn("administrator", history.banner_text.text())


if __name__ == "__main__":
    unittest.main()
