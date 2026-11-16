"""Updates in the app: the background service, the "Update ready" card, the tray entry and Settings."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from halo import updater
from halo.app import Controller, MainWindow
from halo.update_helper import read_json, write_json
from halo.updates import UpdatePrompt, UpdateService
from test_updater import FakeWeb, make_zip, release_json

ROOT = Path(__file__).resolve().parents[1]


def settle(condition, seconds=10.):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    QApplication.processEvents()
    return condition()


class UpdateServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = ROOT / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-update-ui-", dir=scratch)
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "data" / "settings.ini"), QSettings.Format.IniFormat)
        self.settings.setValue("glow", False)
        self.c = Controller(self.settings, offline=True)
        self.c.timer.stop()
        self.app_dir = self.root / "Halo"
        (self.app_dir / "_internal").mkdir(parents=True)
        (self.app_dir / "Halo.exe").write_bytes(b"old exe")
        self.package = make_zip()
        self.release = updater.pick_release(release_json(size=len(self.package)))
        self.web = FakeWeb({updater.LATEST_URL: json.dumps(release_json(size=len(self.package))).encode(),
                            self.release.zip_url: self.package,
                            self.release.sums_url: f"{hashlib.sha256(self.package).hexdigest()}  Halo-Windows-x64.zip\n".encode()})
        self.feed = mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""})
        self.feed.start()
        self.offers, self.notices = [], []

    def tearDown(self):
        self.feed.stop()
        self.c.close()
        self.temp.cleanup()

    def service(self, frozen=True, version="0.6.0"):
        service = UpdateService(self.c, data_dir=self.root / "data", frozen=frozen,
                                executable=self.app_dir / "Halo.exe", version=version, opener=self.web)
        service.offer.connect(self.offers.append)
        service.notice.connect(lambda title, text: self.notices.append(title))
        return service

    def test_a_source_run_never_checks_by_itself_and_only_reports(self):
        service = self.service(frozen=False)
        service.start()
        self.assertFalse(service.timer.isActive())
        self.assertIn("source", service.status_text())
        self.assertTrue(service.check(manual=True))
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "available")
        self.assertIn("source", service.blocker)
        self.assertEqual(self.offers, [True])
        self.assertEqual([request.full_url for request in self.web.requests], [updater.LATEST_URL])  # nothing downloaded
        self.assertEqual(service.action_text(), "Get Halo 0.7.0…")

    def test_the_packaged_app_checks_on_a_schedule_it_can_turn_off(self):
        service = self.service()
        service.start()
        self.assertTrue(service.timer.isActive())
        self.assertEqual(service.timer.interval(), 6 * 60 * 60 * 1000)
        self.assertTrue(service.first.isActive())
        self.c.set("update_auto", False)
        self.assertFalse(service.timer.isActive())
        self.assertFalse(self.settings.value("update_auto", True, type=bool))
        self.assertEqual(service.status_text(), "Automatic checks are off.")
        self.c.set("update_auto", True)
        self.assertTrue(service.timer.isActive())

    def test_a_new_release_is_downloaded_verified_and_offered(self):
        service = self.service()
        service.check()
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "ready", service.message)
        self.assertEqual(service.stated, "0.7.0")
        self.assertTrue((service.package / "Halo.exe").is_file())
        self.assertEqual(self.offers, [False])
        self.assertEqual(service.action_text(), "Update to Halo 0.7.0…")
        self.assertEqual(service.button_text(), "Update now")
        service.defer()
        self.assertFalse(service.check())  # waiting for an answer: no new download
        service.check(manual=True)
        self.assertEqual(self.offers, [False, True])

    def test_later_waits_until_the_next_start(self):
        service = self.service()
        service.deferred = "0.7.0"
        service.check()
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual((service.state, self.offers), ("ready", []))

    def test_an_up_to_date_copy_says_so_when_asked(self):
        service = self.service(version="0.7.0")
        service.check(manual=True)
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "current")
        self.assertEqual(self.notices, ["Halo is up to date"])
        self.assertTrue(service.status_text().startswith("You have the newest version."))

    def test_a_failed_check_is_quiet_unless_asked(self):
        self.web.routes[updater.LATEST_URL] = OSError("offline")
        service = self.service()
        service.check()
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual((service.state, self.notices), ("error", []))
        service.check(manual=True)
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(self.notices, ["Couldn't check for updates"])
        self.assertIn("Couldn't reach GitHub", service.status_text())

    def test_a_version_that_failed_to_start_is_not_fetched_again_by_itself(self):
        self.settings.setValue("update_failed_version", "0.7.0")
        service = self.service()
        service.check()
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "available")
        self.assertIn("didn't start properly", service.blocker)
        self.assertNotIn(self.release.zip_url, [request.full_url for request in self.web.requests])
        service.check(manual=True)
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "ready")

    def ready_service(self):
        service = self.service()
        service.check()
        self.assertTrue(settle(lambda: not service.busy()))
        self.assertEqual(service.state, "ready")
        return service

    def test_install_closes_halo_once_the_helper_has_started(self):
        service = self.ready_service()
        quits = []
        service.quitRequested.connect(lambda: quits.append(True))
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(updater, "start_helper", return_value=process) as start:
            self.assertTrue(service.install())
        self.assertEqual(start.call_args.args[2:], (self.app_dir, os.getpid(), "0.6.0", "0.7.0"))
        self.assertEqual(service.state, "installing")
        service._await_helper()
        self.assertEqual(quits, [])
        write_json(service.paths.ready, {"helper_pid": 42})
        service._await_helper()
        self.assertEqual(quits, [True])
        self.assertFalse(service.handshake.isActive())

    def test_a_helper_that_does_not_start_leaves_halo_running(self):
        service = self.ready_service()
        quits = []
        service.quitRequested.connect(lambda: quits.append(True))
        process = mock.Mock()
        process.poll.return_value = 1
        with mock.patch.object(updater, "start_helper", return_value=process):
            service.install()
        service._await_helper()
        self.assertEqual(quits, [])
        self.assertEqual(service.state, "ready")
        self.assertIn("stays on 0.6.0", service.install_error)
        self.assertTrue(service.paths.cancel.exists())
        self.assertIn("The update didn't start", self.notices)

    def test_after_an_update_the_new_version_reports_a_good_start(self):
        service = self.service(version="0.7.0")
        service.paths.root.mkdir(parents=True)
        write_json(service.paths.state, {"phase": "verifying", "to_version": "0.7.0", "from_version": "0.6.0",
                                         "helper_pid": 7, "updated_at": time.time()})
        service._after_launch()
        self.assertFalse(service.paths.healthy.exists())  # only once it has run a moment
        service._report_healthy()
        self.assertEqual(read_json(service.paths.healthy)["version"], "0.7.0")
        self.assertEqual(self.notices, ["Halo is up to date"])
        write_json(service.paths.state, {"phase": "done", "result": "updated", "to_version": "0.7.0",
                                         "from_version": "0.6.0", "helper_pid": 7})
        service._after_launch()
        self.assertEqual(self.notices, ["Halo is up to date"])  # told once

    def test_a_good_start_is_reported_even_if_the_helper_could_not_note_verifying(self):
        service = self.service(version="0.7.0")
        service.paths.root.mkdir(parents=True)
        write_json(service.paths.state, {"phase": "swapping", "to_version": "0.7.0", "from_version": "0.6.0",
                                         "helper_pid": 8, "updated_at": time.time()})
        with mock.patch("halo.updates.QTimer.singleShot") as later:
            service._after_launch()
        later.call_args.args[-1]()
        self.assertEqual(read_json(service.paths.healthy)["version"], "0.7.0")
        write_json(service.paths.state, {"phase": "swapping", "to_version": "0.8.0", "from_version": "0.7.0",
                                         "helper_pid": 9, "updated_at": time.time()})
        service.paths.healthy.unlink()
        with mock.patch("halo.updates.QTimer.singleShot") as later:
            service._after_launch()
        later.assert_not_called()  # a different version's swap is none of this copy's business

    def test_after_a_rollback_the_old_version_says_what_happened_once(self):
        service = self.service()
        service.paths.root.mkdir(parents=True)
        write_json(service.paths.state, {"phase": "done", "result": "rolled_back", "to_version": "0.7.0",
                                         "from_version": "0.6.0", "helper_pid": 9, "reason": "closed"})
        service._after_launch()
        service._after_launch()
        self.assertEqual(self.notices, ["The update was undone"])
        self.assertEqual(self.settings.value("update_failed_version", "", type=str), "0.7.0")
        self.assertIn("went back to 0.6.0", service.status_text())

    def test_the_prompt_is_short_and_later_defers(self):
        service = self.ready_service()
        prompt = UpdatePrompt(service)
        self.assertEqual(prompt.title(), "Update ready")
        self.assertEqual(prompt.headline.text(), "Halo 0.7.0")
        # One line about the version and one about what happens: no list, no checksum talk.
        self.assertEqual(prompt.notes.text(), "Halo gets better.")
        self.assertEqual(prompt.summary.text(), "Halo restarts and is back in a few seconds.")
        self.assertIn("comes back", prompt.update_button.toolTip())
        self.assertEqual(prompt.update_button.text(), "Update now")
        self.assertTrue(prompt.update_button.isEnabled())
        prompt.later()
        self.assertEqual(service.deferred, "0.7.0")
        with mock.patch.object(service, "install", return_value=True) as install:
            prompt.update_now()
        install.assert_called_once()


class UpdateWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = ROOT / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-update-window-", dir=scratch)
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

    def test_the_tray_and_settings_offer_a_check_and_never_check_by_themselves(self):
        self.assertEqual(self.window.tray_update.text(), "Check for updates")
        self.assertFalse(self.window.updates.started)
        self.assertFalse(self.window.updates.timer.isActive())
        studio = self.window.settings_dialog
        self.assertEqual(studio.update_button.text(), "Check now")
        self.assertIn("source", studio.update_status.text())
        self.assertIs(self.window.setting_controls["update_auto"], studio.switches["update_auto"])
        studio.switches["update_auto"].click()
        self.assertFalse(self.c.update_auto)

    def test_a_waiting_update_opens_its_card_from_the_tray(self):
        service = self.window.updates
        package = make_zip()
        service.release = updater.pick_release(release_json(size=len(package)))
        service.state, service.package, service.stated = "ready", Path(self.temp.name), "0.7.0"
        service.changed.emit()
        self.assertEqual(self.window.tray_update.text(), "Update to Halo 0.7.0…")
        self.assertEqual(self.window.settings_dialog.update_button.text(), "Update now")
        self.assertEqual(self.window.settings_dialog.update_button.objectName(), "primary")
        self.window.update_clicked()
        self.assertTrue(self.window.sheet.isVisible())
        self.assertIsInstance(self.window.sheet.dialog, UpdatePrompt)
        self.assertEqual(self.window.sheet.title.text(), "Update ready")
        self.window.sheet.dismiss()
        self.assertFalse(self.window.sheet.isVisible())
        self.assertEqual(service.deferred, "0.7.0")

    def test_an_unasked_offer_waits_for_the_room_to_close(self):
        service = self.window.updates
        service.release = updater.pick_release(release_json())
        service.state = "ready"
        with mock.patch.object(self.window, "_immersive_active", return_value=True), \
                mock.patch.object(self.window.tray, "showMessage") as message:
            self.window.offer_update(False)
        self.assertFalse(self.window.sheet.isVisible())
        message.assert_called_once()
        self.window._tray_message_clicked()  # clicking the notification opens the card
        self.assertTrue(self.window.sheet.isVisible())
        self.assertIsInstance(self.window.sheet.dialog, UpdatePrompt)


if __name__ == "__main__":
    unittest.main()
