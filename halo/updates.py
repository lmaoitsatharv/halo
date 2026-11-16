"""Updates inside Halo: the background checker, and the card that asks before installing.

The work itself is in updater.py (find, download, verify, stage) and update_helper.py (swap the
files once Halo has closed). This module schedules it, keeps its state for the tray and
Settings, shows the "Update ready" card in Halo's own sheet, and the Update history.
"""
import logging
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, QPointF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from . import __version__
from . import updater
from .frontend import action, text_label
from .release_history import RELEASES
from .theme import hexc, style
from .update_helper import read_json

STARTUP_DELAY_MS = 20_000          # let Halo settle and find the song first
INTERVAL_MS = 6 * 60 * 60 * 1000   # then every six hours while it runs
HANDSHAKE_MS = 60_000              # how long the new copy may take to say its helper started
HEALTHY_DELAY_MS = 3_000           # after an update: running this long counts as a good start
BUSY = ("checking", "downloading", "installing")

AUTO_UPDATE_HINT = ("Halo asks GitHub for its newest release when it starts and every six hours, and downloads it "
                    "in the background. Nothing installs until you choose Update now. Only a generic app name is "
                    "sent, with no song, account or PC details; GitHub sees your IP address, as any website does.")


def ago(seconds):
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 86400:
        hours = round(seconds / 3600)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    return "over a day ago"


class UpdateService(QObject):
    """Checks GitHub, downloads and verifies in the background, and installs when asked.

    states: idle, checking, current, available (newer, but this copy can't install it),
    downloading, ready (verified and staged), installing, error.
    """
    changed = Signal()
    offer = Signal(bool)         # an update waits for an answer; True when the person asked for it
    notice = Signal(str, str)    # a short result worth telling: title, message
    quitRequested = Signal()     # the helper has started: Halo should close now
    _finished = Signal(object)
    _progressed = Signal(int, int)

    def __init__(self, controller, data_dir=None, frozen=None, executable=None, version=__version__,
                 opener=None, parent=None):
        super().__init__(parent)
        self.c = controller
        self.version = version
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        self.executable = Path(sys.executable if executable is None else executable)
        self.data_dir = Path(data_dir) if data_dir is not None else Path(controller.settings.fileName()).parent
        self.paths = updater.UpdatePaths(self.data_dir / "updates")
        self.opener = opener
        self.state = "idle"
        self.release = None
        self.package = None
        self.stated = None
        self.blocker = ""
        self.message = ""
        self.progress = 0.
        self.checked_at = None
        self.deferred = None
        self.install_error = ""
        self.started = False
        self._thread = None
        self._closing = False
        self._helper = None
        self._handshake_until = 0.
        self._last_percent = -1
        self._finished.connect(self._finish)
        self._progressed.connect(self._progress)
        self.first = QTimer(self)
        self.first.setSingleShot(True)
        self.first.setInterval(STARTUP_DELAY_MS)
        self.first.timeout.connect(lambda: self.check())
        self.timer = QTimer(self)
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(lambda: self.check())
        self.handshake = QTimer(self)
        self.handshake.setInterval(150)
        self.handshake.timeout.connect(self._await_helper)
        if hasattr(controller, "settingChanged"):
            controller.settingChanged.connect(self._sync_schedule)

    # Scheduling -----------------------------------------------------------------------------------------

    @property
    def automatic(self):
        return self.frozen and bool(getattr(self.c, "update_auto", True))

    def start(self):
        """Called once Halo is on screen: finish an update that just happened, then check on schedule."""
        if self.started:
            return
        self.started = True
        QTimer.singleShot(0, self, self._after_launch)
        self._sync_schedule()

    def _sync_schedule(self):
        on = self.started and self.automatic and not self._closing
        if on and not self.timer.isActive():
            self.timer.start()
            self.first.start()
        elif not on and self.timer.isActive():
            self.timer.stop()
            self.first.stop()

    def close(self):
        self._closing = True
        self.timer.stop()
        self.first.stop()
        self.handshake.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(2.)

    # After an update ------------------------------------------------------------------------------------

    def _after_launch(self):
        if not self.frozen:
            return
        state = read_json(self.paths.state)
        identity = f"{state.get('helper_pid')}:{state.get('to_version')}:{state.get('from_version')}"
        seen = self.c.settings.value("update_seen", "", type=str) == identity
        # The helper starts this version only once the files are in place, so "swapping" here just
        # means its last note didn't get written; either way it is waiting to hear we started.
        if state.get("phase") in ("swapping", "verifying") and updater.same_version(state.get("to_version"), self.version):
            self.c.settings.setValue("update_seen", identity)
            QTimer.singleShot(HEALTHY_DELAY_MS, self, lambda: self._report_healthy(announce=not seen))
            return
        if state.get("phase") != "done" or seen:
            return
        self.c.settings.setValue("update_seen", identity)
        result, to, previous = state.get("result"), str(state.get("to_version") or ""), state.get("from_version")
        reason = str(state.get("reason") or "").strip()
        if result == "rolled_back" and updater.same_version(previous, self.version):
            # Don't offer the same broken version again by itself; Check now still can.
            self.c.settings.setValue("update_failed_version", to)
            self.message = f"Halo {to} didn't start properly, so Halo went back to {self.version}."
            self.notice.emit("The update was undone", self.message)
        elif result == "unchanged" and updater.same_version(previous, self.version):
            self.message = f"The update to {to} couldn't finish, so Halo stayed on {self.version}. {reason}".strip()
            self.notice.emit("The update didn't finish", self.message)
        elif result == "broken":
            self.message = f"The last update hit a problem. {reason}".strip()
            self.notice.emit("The update hit a problem", self.message)
        self.changed.emit()

    def _report_healthy(self, announce=True):
        """Tell the waiting helper this version started properly, and say it once."""
        try:
            updater.mark_healthy(self.paths, self.version)
        except OSError as error:
            logging.warning("Could not confirm the update: %s", error)
            return
        if announce:
            self.message = f"Halo updated itself to {self.version}."
            self.notice.emit("Halo is up to date", self.message)
            self.changed.emit()

    # Checking and downloading --------------------------------------------------------------------------

    def busy(self):
        return self.state in BUSY

    def check(self, manual=False):
        """Ask GitHub now. A manual check reports its result and offers what it finds."""
        if self.busy() or self._closing:
            return False
        if self.state == "ready" and self.package is not None:
            if manual:
                self.offer.emit(True)
            return False
        self.state, self.message, self.progress = "checking", "Checking GitHub for a newer release…", 0.
        self._last_percent = -1
        failed = self.c.settings.value("update_failed_version", "", type=str)
        self._thread = threading.Thread(target=self._work, args=(manual, failed), name="halo-updates", daemon=True)
        self._thread.start()
        self.changed.emit()
        return True

    def _work(self, manual, failed):
        """Runs off the UI thread; reports through _finished."""
        result = {"manual": manual}
        try:
            opener = {} if self.opener is None else {"opener": self.opener}
            if self.frozen:
                updater.clean(self.paths, self.version, self.executable.parent)
            release = updater.latest_release(**opener)
            result["release"] = release
            if not updater.is_newer(release.version, self.version):
                result["state"] = "current"
            else:
                blocker = updater.install_blocker(self.executable, self.data_dir, self.frozen)
                if blocker:
                    result.update(state="available", blocker=blocker)
                elif not manual and updater.same_version(release.version, failed):
                    result.update(state="available", blocker="It didn't start properly last time, so Halo kept "
                                  "the version you have. Choose Check now to try it again.")
                else:
                    self._progressed.emit(0, release.zip_size)
                    package, stated = updater.prepare(release, self.paths, self._report_progress,
                                                      lambda: self._closing, **opener)
                    result.update(state="ready", package=package, stated=stated)
        except updater.UpdateCancelled:
            result["state"] = "idle"
        except updater.UpdateError as error:
            result.update(state="error", message=str(error))
        except Exception as error:  # an update check must never take Halo down
            logging.exception("Update check failed")
            result.update(state="error", message=f"Halo couldn't check for updates ({type(error).__name__}).")
        if not self._closing:
            self._finished.emit(result)

    def _report_progress(self, received, total):
        if total <= 0:
            return  # size not known: the bar waits rather than guess
        percent = int(received * 100 / total)
        if percent != self._last_percent:
            self._last_percent = percent
            self._progressed.emit(received, total)

    def _progress(self, received, total):
        if self.state in ("checking", "downloading"):
            self.state = "downloading"
            self.progress = received / max(1, total)
            self.changed.emit()

    def _finish(self, result):
        self._thread = None
        manual, state = result.get("manual", False), result.get("state", "error")
        release = result.get("release")
        self.checked_at = time.time()
        if release is not None:
            self.release = release
        self.blocker = result.get("blocker", "")
        self.state = state
        if state == "current":
            self.message = f"You have the newest version. Checked {ago(0)}."
            if manual:
                self.notice.emit("Halo is up to date", f"You have the newest version, {self.version}.")
        elif state == "available":
            self.message = f"Halo {release.version} is available. {self.blocker}"
            if manual:
                self.offer.emit(True)
            elif self.deferred != release.version:
                self.deferred = release.version
                self.notice.emit(f"Halo {release.version} is available", self.blocker)
        elif state == "ready":
            self.package, self.stated = result["package"], result["stated"]
            self.message = f"Halo {release.version} is downloaded and checked. It installs when you choose Update now."
            if manual or self.deferred != release.version:
                self.offer.emit(manual)
        elif state == "error":
            self.message = result.get("message") or "Halo couldn't check for updates."
            if manual:
                self.notice.emit("Couldn't check for updates", self.message)
        else:
            self.message = ""
        self.changed.emit()

    def defer(self):
        """Later: don't ask again about this version until Halo starts again or someone asks."""
        if self.release is not None:
            self.deferred = self.release.version

    # Text for the tray and Settings ----------------------------------------------------------------------

    def status_text(self):
        if self.state == "idle" and not self.message:
            if not self.frozen:
                return "Running from source: a check only reports the newest release. Update with your source tools."
            return "Not checked yet." if self.automatic else "Automatic checks are off."
        if self.state == "current" and self.checked_at is not None:
            return f"You have the newest version. Checked {ago(time.time() - self.checked_at)}."
        if self.state == "downloading" and self.release is not None:
            return f"Downloading Halo {self.release.version} in the background: {round(self.progress * 100)}%."
        return self.message

    def button_text(self):
        return {"checking": "Checking…",
                "downloading": f"Downloading {round(self.progress * 100)}%",
                "ready": "Update now",
                "available": "Get it",
                "installing": "Updating…"}.get(self.state, "Check now")

    def action_text(self):
        """The tray menu entry."""
        version = self.release.version if self.release is not None else ""
        return {"checking": "Checking for updates…",
                "downloading": f"Downloading Halo {version}… {round(self.progress * 100)}%",
                "ready": f"Update to Halo {version}…",
                "available": f"Get Halo {version}…",
                "installing": "Updating Halo…"}.get(self.state, "Check for updates")

    # Installing -----------------------------------------------------------------------------------------

    def install(self):
        """Start the helper from the new copy, then ask Halo to close once it is running."""
        if self.state != "ready" or self.package is None:
            return False
        self.blocker = updater.install_blocker(self.executable, self.data_dir, self.frozen)
        if self.blocker:
            self.state = "available"
            self.message = f"Halo {self.release.version} is available. {self.blocker}"
            self.changed.emit()
            return False
        try:
            self._helper = updater.start_helper(self.paths, self.package, self.executable.parent, os.getpid(),
                                                self.version, self.stated)
        except OSError as error:
            self.install_error = self.message = f"The update couldn't start: {error}"
            self.changed.emit()
            return False
        self.install_error = ""
        self.state, self.message = "installing", "Starting the new version's installer…"
        self._handshake_until = time.monotonic() + HANDSHAKE_MS / 1000
        self.handshake.start()
        self.changed.emit()
        return True

    def _await_helper(self):
        if updater.helper_ready(self.paths):
            self.handshake.stop()
            self.message = "Closing Halo to update. It opens again in a moment."
            self.changed.emit()
            self.quitRequested.emit()
            return
        exited = self._helper is not None and self._helper.poll() is not None
        if exited or time.monotonic() > self._handshake_until:
            self.handshake.stop()
            updater.cancel_helper(self.paths, self._helper)
            reason = str(read_json(self.paths.state).get("reason") or "")
            self.state = "ready"
            self.message = f"The update couldn't start, so Halo stays on {self.version}. {reason}".strip()
            self.install_error = self.message
            self.notice.emit("The update didn't start", self.message)
            self.changed.emit()


class UpdatePrompt(QDialog):
    """Asks before installing, in a few words: the new version, one line about it, Update now or Later.

    Presented in the window's sheet, like Halo's other dialogs, sized to its few lines. The full notes are on GitHub.
    """
    sheet_minimum_height = 0
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("updatePrompt")
        # The sheet's card paints the background, in both light and dark.
        self.setStyleSheet("QDialog#updatePrompt { background: transparent; }")
        self.setWindowTitle("Halo · Update")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 4)
        layout.setSpacing(8)
        self.headline = text_label("", "title")
        self.headline.setAccessibleName("New version")
        layout.addWidget(self.headline)
        # One line about the version, then one line about what happens; nothing more.
        self.notes = text_label("", "updateNotes")
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.notes.setAccessibleName("What's new")
        layout.addWidget(self.notes)
        self.summary = text_label("", "muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.status = text_label("", "badge")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.full_notes = action("Full notes on GitHub", self.open_page, "ghost")
        self.full_notes.setToolTip("Open this release's page in your browser")
        buttons.addWidget(self.full_notes)
        buttons.addStretch()
        self.later_button = action("Later", self.later)
        self.later_button.setToolTip("Keep this version for now. The update stays ready in the tray menu and Settings.")
        buttons.addWidget(self.later_button)
        self.update_button = action("Update now", self.update_now, "primary")
        self.update_button.setMinimumWidth(132)
        self.update_button.setToolTip("Halo closes, puts the new version in place and opens again. Your settings, "
                                      "saved lyrics and modes stay. If the new version doesn't start, this one comes back.")
        buttons.addWidget(self.update_button)
        layout.addLayout(buttons)
        self.rejected.connect(service.defer)
        service.changed.connect(self.sync)
        self.sync()

    def title(self):
        return "Update available" if self.service.state == "available" else "Update ready"

    def sync(self):
        service, release = self.service, self.service.release
        if release is None:
            return
        available, installing = service.state == "available", service.state == "installing"
        self.headline.setText(f"Halo {release.version}")
        if available:
            self.summary.setText(service.blocker or f"Download it from GitHub to replace {service.version}.")
        else:
            self.summary.setText("Halo restarts and is back in a few seconds.")
        self.notes.setText(release.notes)
        self.notes.setVisible(bool(release.notes))
        self.update_button.setText("Open download page" if available else "Updating…" if installing else "Update now")
        self.update_button.setEnabled(service.state in ("ready", "available"))
        self.later_button.setEnabled(not installing)
        self.status.setText(service.message if installing else service.install_error)
        self.status.setVisible(bool(self.status.text()))

    def open_page(self):
        if self.service.release is not None:
            QDesktopServices.openUrl(QUrl(self.service.release.page))

    def update_now(self):
        if self.service.state == "available":
            self.open_page()
            self.accept()
        elif self.service.install():
            self.sync()

    def later(self):
        self.reject()


class _Rail(QWidget):
    """The timeline beside one version: a dot, and the line down to the next."""
    def __init__(self, newest, last, parent=None):
        super().__init__(parent)
        self.newest, self.last = newest, last
        self.setFixedWidth(22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = self.width() / 2, 13.
        if not self.last:
            p.setPen(QPen(hexc("#c9d2cc"), 2))
            p.drawLine(QPointF(x, y), QPointF(x, self.height()))
        p.setPen(QPen(hexc("#1c2a26") if self.newest else hexc("#a7b1ac"), 2))
        p.setBrush(hexc("#1c2a26") if self.newest else hexc("#e7ece6"))
        p.drawEllipse(QPointF(x, y), 5.5, 5.5)


HISTORY_CSS = """
QFrame#historyBanner { background: #ffffff; border: 1px solid rgba(28,42,38,40); border-radius: 14px; }
QFrame#historyCard { background: #ffffff; border: 1px solid rgba(28,42,38,26); border-radius: 12px; }
QLabel#historyVersion { color: #1c2a26; font-size: 15px; font-weight: 600; }
QLabel#historyBannerTitle { color: #1c2a26; font-size: 15px; font-weight: 600; }
QLabel#historyBadge { color: #24685b; background: rgba(36,104,91,26); border-radius: 9px; padding: 1px 9px;
                      font-size: 11px; font-weight: 600; }
QLabel#historyDate { color: #55625e; font-size: 12px; }
QLabel#historyText { color: #1c2a26; font-size: 13px; }
"""


class UpdateHistory(QDialog):
    """What changed in each version, newest first, with the waiting update on top.

    Each version has its date and one short line. The lines ship with Halo, so the history reads
    offline; a newer release found on GitHub joins the top with its own one-line summary.
    """
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("updateHistory")
        self.setWindowTitle("Halo · Update history")
        style(self, "QDialog#updateHistory { background: transparent; }" + HISTORY_CSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 4)
        layout.setSpacing(14)
        self.banner = QFrame(self)
        self.banner.setObjectName("historyBanner")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(18, 14, 14, 14)
        row.setSpacing(14)
        words = QVBoxLayout()
        words.setSpacing(3)
        self.banner_title = text_label("", "historyBannerTitle")
        self.banner_text = text_label("", "historyDate")
        self.banner_text.setWordWrap(True)
        words.addWidget(self.banner_title)
        words.addWidget(self.banner_text)
        row.addLayout(words, 1)
        self.banner_button = action("Update now", self.update_now, "primary")
        self.banner_button.setMinimumWidth(132)
        row.addWidget(self.banner_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.banner)
        self.timeline = QVBoxLayout()
        self.timeline.setSpacing(0)
        layout.addLayout(self.timeline)
        layout.addStretch()
        self.entries = []
        service.changed.connect(self.sync)
        self.sync()

    def versions(self):
        """(version, date, line, badges) newest first: a newer release from GitHub, then Halo's own list."""
        service, release = self.service, self.service.release
        rows = [list(item) for item in RELEASES]
        known = {item[0] for item in RELEASES}
        if release is not None and release.version not in known and updater.is_newer(release.version, rows[0][0]):
            rows.insert(0, [release.version, "Ready to install" if service.state == "ready" else "Available",
                            release.notes or "See the full notes on GitHub."])
        result = []
        for index, (version, date, line) in enumerate(rows):
            badges = []
            if index == 0:
                badges.append("Newest")
            if version == service.version:
                badges.append("This version")
            result.append((version, date, line, badges))
        return result

    def sync(self):
        service, release = self.service, self.service.release
        waiting = service.state in ("ready", "available", "installing") and release is not None
        self.banner.setVisible(waiting)
        if waiting:
            available, installing = service.state == "available", service.state == "installing"
            self.banner_title.setText(f"Halo {release.version} is {'out' if available else 'ready'}")
            self.banner_text.setText(service.blocker if available and service.blocker else
                                     "Halo restarts and is back in a few seconds.")
            self.banner_button.setText("Open download page" if available else "Updating…" if installing else "Update now")
            self.banner_button.setEnabled(service.state in ("ready", "available"))
        rows = self.versions()
        if [row[:3] + (tuple(row[3]),) for row in rows] == self.entries:
            return
        self.entries = [row[:3] + (tuple(row[3]),) for row in rows]
        while self.timeline.count():
            item = self.timeline.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, (version, date, line, badges) in enumerate(rows):
            self.timeline.addWidget(self._entry(version, date, line, badges, index == 0, index == len(rows) - 1))

    def _entry(self, version, date, line, badges, newest, last):
        entry = QWidget(self)
        row = QHBoxLayout(entry)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(_Rail(newest, last, entry))
        column = QVBoxLayout()
        column.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = text_label(f"Halo {version}" if version[:1].isdigit() else f"Halo {version.lower()}", "historyVersion")
        head.addWidget(title)
        for badge in badges:
            head.addWidget(text_label(badge, "historyBadge"))
        head.addWidget(text_label(date, "historyDate"))
        head.addStretch()
        column.addLayout(head)
        card = QFrame(entry)
        card.setObjectName("historyCard")
        inside = QVBoxLayout(card)
        inside.setContentsMargins(16, 12, 16, 12)
        words = text_label(line, "historyText")
        words.setWordWrap(True)
        words.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inside.addWidget(words)
        column.addWidget(card)
        if not last:
            column.addSpacing(18)  # inside the row, so the rail's line runs on to the next version
        row.addLayout(column, 1)
        entry.setAccessibleName(f"Halo {version}, {date}: {line}")
        return entry

    def update_now(self):
        if self.service.state == "available":
            if self.service.release is not None:
                QDesktopServices.openUrl(QUrl(self.service.release.page))
        elif self.service.install():
            self.sync()
