"""Automatic updates: versions, picking release files, checksums, staging, and the helper's swap and rollback.

No network: GitHub is a fake opener. No real install: the helper works on fake folders.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
import zipfile

from halo import updater, update_helper
from halo.update_helper import PROTOCOL, read_json, write_json
from halo.updater import UpdateError, UpdatePaths

ROOT = Path(__file__).resolve().parents[1]
PREFIX = updater.DOWNLOAD_PREFIX + "v0.7.0/"


def make_zip(version="0.7.0", extra=None, exe=b"new exe", version_text=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Halo/Halo.exe", exe)
        archive.writestr("Halo/_internal/base_library.zip", b"new library")
        archive.writestr("Halo/_internal/PySide6/Qt6Core.dll", b"new qt")
        archive.writestr("Halo/licenses/LICENSE", b"licence")
        archive.writestr("Halo/README.md", b"readme")
        archive.writestr("Halo/VERSION.txt", (version_text if version_text is not None else version) + "\r\n")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def release_json(version="0.7.0", size=100, digest=None, **changes):
    tag = "v" + version
    data = {"tag_name": tag, "name": f"Halo {version}", "draft": False, "prerelease": False,
            "html_url": f"https://github.com/lmaoitsatharv/halo/releases/tag/{tag}",
            "body": "Halo gets better.\r\n\r\n## Download and run\r\n\r\n1. Download it.\r\n\r\n## What's new\r\n\r\n"
                    "- **Updates.** Halo updates itself.\r\n  - a detail\r\n- **Faster** start.\r\n",
            "assets": [{"name": "Halo-Windows-x64.zip", "size": size,
                        "browser_download_url": updater.DOWNLOAD_PREFIX + f"{tag}/Halo-Windows-x64.zip",
                        **({"digest": "sha256:" + digest} if digest else {})},
                       {"name": "SHA256SUMS.txt", "size": 87,
                        "browser_download_url": updater.DOWNLOAD_PREFIX + f"{tag}/SHA256SUMS.txt"}]}
    data.update(changes)
    return data


class FakeResponse(io.BytesIO):
    def __init__(self, data, url, headers=None):
        super().__init__(data)
        self.url, self.headers = url, headers or {}

    def geturl(self):
        return self.url


class FakeWeb:
    """Answers requests from a table; records them so tests can check what was sent.

    An answer is bytes, an exception to raise, ("redirect", final address) or (bytes, headers).
    """
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.routes[request.full_url]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple) and answer[0] == "redirect":
            return FakeResponse(b"<html>", answer[1])
        if isinstance(answer, tuple):
            return FakeResponse(answer[0], request.full_url, answer[1])
        return FakeResponse(answer, request.full_url)


def tree(folder):
    """Every file under folder with its contents, for before/after comparisons."""
    folder = Path(folder)
    return {str(path.relative_to(folder)).replace("\\", "/"): path.read_bytes()
            for path in sorted(folder.rglob("*")) if path.is_file()}


class Scratch(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".cache"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="halo-update-", dir=scratch)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class VersionTests(unittest.TestCase):
    def test_newer_versions_are_recognised(self):
        self.assertTrue(updater.is_newer("v0.7.0", "0.6.0"))
        self.assertTrue(updater.is_newer("0.10.0", "0.9.9"))
        self.assertTrue(updater.is_newer("1.0", "0.99.99"))
        self.assertTrue(updater.is_newer("0.6.1", "0.6"))

    def test_same_or_older_versions_are_not_newer(self):
        self.assertFalse(updater.is_newer("v0.6.0", "0.6.0"))
        self.assertFalse(updater.is_newer("0.6", "0.6.0"))
        self.assertFalse(updater.is_newer("0.5.9", "0.6.0"))

    def test_a_preview_sorts_before_its_release(self):
        self.assertFalse(updater.is_newer("0.7.0-beta.1", "0.7.0"))
        self.assertTrue(updater.is_newer("0.7.0", "0.7.0-rc.2"))
        self.assertTrue(updater.is_newer("0.7.0-rc.10", "0.7.0-rc.2"))

    def test_unreadable_versions_are_never_newer(self):
        for text in ("", "latest", "v", "Halo 0.7", None, "0.7.0 now", "1" * 40):
            self.assertIsNone(updater.parse_version(text), text)
            self.assertFalse(updater.is_newer(text, "0.6.0"))
        self.assertFalse(updater.is_newer("0.7.0", "garbage"))


class ReleaseTests(unittest.TestCase):
    def test_the_zip_and_checksums_are_picked_with_a_one_line_summary(self):
        release = updater.pick_release(release_json(digest="ab" * 32))
        self.assertEqual(release.version, "0.7.0")
        self.assertEqual(release.tag, "v0.7.0")
        self.assertEqual(release.zip_url, PREFIX + "Halo-Windows-x64.zip")
        self.assertEqual(release.sums_url, PREFIX + "SHA256SUMS.txt")
        self.assertEqual(release.zip_size, 100)
        self.assertEqual(release.zip_digest, "ab" * 32)
        self.assertEqual(release.notes, "Halo gets better.")

    def test_a_release_without_its_checksum_list_is_refused(self):
        data = release_json()
        data["assets"] = data["assets"][:1]
        with self.assertRaisesRegex(UpdateError, "SHA256SUMS"):
            updater.pick_release(data)

    def test_a_release_without_the_portable_zip_is_refused(self):
        data = release_json()
        data["assets"][0]["name"] = "Halo-Setup.exe"
        with self.assertRaisesRegex(UpdateError, "Halo-Windows-x64.zip"):
            updater.pick_release(data)

    def test_files_from_anywhere_but_the_projects_downloads_are_refused(self):
        for url in ("https://example.com/Halo-Windows-x64.zip",
                    "http://github.com/lmaoitsatharv/halo/releases/download/v0.7.0/Halo-Windows-x64.zip",
                    "https://github.com/someone/halo/releases/download/v0.7.0/Halo-Windows-x64.zip",
                    None):
            data = release_json()
            data["assets"][0]["browser_download_url"] = url
            with self.assertRaises(UpdateError):
                updater.pick_release(data)

    def test_previews_drafts_and_odd_sizes_are_refused(self):
        for changes in ({"prerelease": True}, {"draft": True}, {"tag_name": "nightly"}):
            with self.assertRaises(UpdateError):
                updater.pick_release(release_json(**changes))
        for size in (0, -1, True, "100", updater.MAX_PACKAGE_BYTES + 1):
            with self.assertRaises(UpdateError):
                updater.pick_release(release_json(size=size))
        with self.assertRaises(UpdateError):
            updater.pick_release(["not", "a", "release"])

    def test_the_summary_is_one_short_plain_line(self):
        line = updater.summary_line("Intro with [a link](https://x.test) and `code`.\n\n## What's new\n\n"
                                    "- **Bold** <b>tag</b> point\n* second\n")
        self.assertEqual(line, "Intro with a link and code.")
        self.assertEqual(updater.summary_line(None), "")
        self.assertEqual(updater.summary_line("   "), "")
        # Without an opening paragraph, the first point stands in.
        self.assertEqual(updater.summary_line("## What's new\n- **Bold** <b>tag</b> point\n- second"), "Bold tag point")
        # Long openings keep whole sentences while they fit, and never run past the limit.
        long = "Halo has three new rooms to listen in. " * 6
        self.assertEqual(updater.summary_line(long), ("Halo has three new rooms to listen in. " * 3).strip())
        cut = updater.summary_line("word " * 60)
        self.assertLessEqual(len(cut), 140)
        self.assertTrue(cut.endswith("…"))
        # The opening paragraph ends at its first blank line or heading; numbered steps below are never used.
        self.assertEqual(updater.summary_line("Short.\nStill the opening.\n\n1. Download it."), "Short. Still the opening.")
        self.assertEqual(updater.summary_line("## Download and run\n\n1. Download it.\n\n## What's new\n- Rooms."), "Rooms.")

    def test_a_local_feed_can_stand_in_for_github_for_testing(self):
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: "http://127.0.0.1:8123/latest.json"}):
            self.assertEqual(updater.feed()[:2], ("http://127.0.0.1:8123/latest.json", "http://127.0.0.1:8123/"))
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: "http://example.com/latest.json"}):
            self.assertEqual(updater.feed()[0], updater.LATEST_URL)  # plain http only on this PC
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}):
            self.assertEqual(updater.feed(), (updater.LATEST_URL, updater.DOWNLOAD_PREFIX, updater.RELEASES_PAGE))


class NetworkTests(Scratch):
    def test_the_check_sends_only_a_generic_user_agent(self):
        web = FakeWeb({updater.LATEST_URL: json.dumps(release_json()).encode()})
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}):
            release = updater.latest_release(opener=web)
        self.assertEqual(release.version, "0.7.0")
        request = web.requests[0]
        self.assertEqual(request.get_header("User-agent"), "Halo-Updater")
        self.assertEqual(set(request.headers), {"User-agent", "Accept"})
        self.assertEqual(request.data, None)

    def test_github_errors_become_readable_messages(self):
        cases = ((HTTPError(updater.LATEST_URL, 404, "Not Found", {}, None), "No release"),
                 (HTTPError(updater.LATEST_URL, 403, "Forbidden", {}, None), "limiting"),
                 (URLError("offline"), "Couldn't reach GitHub"),
                 (TimeoutError("slow"), "Couldn't reach GitHub"))
        busy_page = HTTPError(updater.RELEASES_PAGE, 429, "Too Many Requests", {}, None)
        for error, words in cases:
            web = FakeWeb({updater.LATEST_URL: error, updater.RELEASES_PAGE: busy_page})
            with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}), self.assertRaisesRegex(UpdateError, words):
                updater.latest_release(opener=web)
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}), self.assertRaisesRegex(UpdateError, "unexpected"):
            updater.latest_release(opener=FakeWeb({updater.LATEST_URL: b"<html>"}))

    def test_a_used_up_api_allowance_falls_back_to_the_release_page(self):
        limited = HTTPError(updater.LATEST_URL, 403, "rate limit exceeded", {}, None)
        web = FakeWeb({updater.LATEST_URL: limited,
                       updater.RELEASES_PAGE: ("redirect", "https://github.com/lmaoitsatharv/halo/releases/tag/v0.7.0")})
        with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}):
            release = updater.latest_release(opener=web)
        self.assertEqual((release.version, release.tag, release.zip_size, release.notes), ("0.7.0", "v0.7.0", 0, ""))
        self.assertEqual(release.zip_url, PREFIX + "Halo-Windows-x64.zip")
        self.assertEqual(release.sums_url, PREFIX + "SHA256SUMS.txt")
        self.assertEqual([request.get_header("User-agent") for request in web.requests], ["Halo-Updater"] * 2)
        for final in ("https://github.com/login?return_to=x", "https://github.com/lmaoitsatharv/halo/releases/tag/nightly",
                      "https://github.com/lmaoitsatharv/halo/releases/tag/v0.7.0/../../evil"):
            web.routes[updater.RELEASES_PAGE] = ("redirect", final)
            with mock.patch.dict(os.environ, {updater.FEED_VARIABLE: ""}), self.assertRaises(UpdateError):
                updater.latest_release(opener=web)

    def test_a_download_of_unknown_size_uses_the_servers_length(self):
        url = PREFIX + "Halo-Windows-x64.zip"
        destination = self.root / "Halo.zip"
        seen = []
        updater.download(url, destination, 0, progress=lambda got, total: seen.append(total),
                         opener=FakeWeb({url: (b"0123456789", {"Content-Length": "10"})}), chunk=4)
        self.assertEqual((destination.read_bytes(), seen[-1]), (b"0123456789", 10))
        with self.assertRaises(UpdateError):
            updater.download(url, self.root / "short.zip", 0, opener=FakeWeb({url: (b"01234", {"Content-Length": "10"})}))
        updater.download(url, self.root / "unsized.zip", 0, opener=FakeWeb({url: b"0123"}))  # the checksum decides
        self.assertEqual((self.root / "unsized.zip").read_bytes(), b"0123")
        with self.assertRaises(UpdateError):
            updater.download(url, self.root / "empty.zip", 0, opener=FakeWeb({url: b""}))

    def test_a_download_is_kept_only_when_complete(self):
        destination = self.root / "Halo.zip"
        url = PREFIX + "Halo-Windows-x64.zip"
        updater.download(url, destination, 10, opener=FakeWeb({url: b"0123456789"}), chunk=3)
        self.assertEqual(destination.read_bytes(), b"0123456789")
        for data in (b"short", b"far too long for this"):
            with self.assertRaises(UpdateError):
                updater.download(url, self.root / "bad.zip", 10, opener=FakeWeb({url: data}), chunk=4)
            self.assertEqual(list(self.root.glob("bad.zip*")), [])

    def test_a_cancelled_download_leaves_nothing(self):
        seen, url = [], PREFIX + "Halo-Windows-x64.zip"
        with self.assertRaises(updater.UpdateCancelled):
            updater.download(url, self.root / "Halo.zip", 10, progress=lambda got, total: seen.append(got),
                             cancelled=lambda: len(seen) >= 2, opener=FakeWeb({url: b"0123456789"}), chunk=2)
        self.assertEqual(list(self.root.iterdir()), [])


class ChecksumTests(Scratch):
    def test_checksum_lines_are_read_in_both_forms(self):
        sums = updater.parse_sums("AB" * 32 + "  Halo-Windows-x64.zip\r\n" + "cd" * 32 + " *other.zip\nnot a line\n")
        self.assertEqual(sums, {"Halo-Windows-x64.zip": "ab" * 32, "other.zip": "cd" * 32})
        with self.assertRaises(UpdateError):
            updater.parse_sums("ab" * 32 + "  a.zip\n" + "cd" * 32 + "  a.zip\n")

    def test_the_expected_checksum_must_agree_with_github(self):
        sums = "ab" * 32 + "  Halo-Windows-x64.zip\n"
        self.assertEqual(updater.expected_digest(sums, updater.pick_release(release_json())), "ab" * 32)
        self.assertEqual(updater.expected_digest(sums, updater.pick_release(release_json(digest="ab" * 32))), "ab" * 32)
        with self.assertRaisesRegex(UpdateError, "disagree"):
            updater.expected_digest(sums, updater.pick_release(release_json(digest="cd" * 32)))
        with self.assertRaisesRegex(UpdateError, "no line"):
            updater.expected_digest("ab" * 32 + "  other.zip\n", updater.pick_release(release_json()))

    def test_a_file_that_fails_its_checksum_is_deleted(self):
        good = self.root / "good.zip"
        good.write_bytes(b"halo")
        updater.verify(good, hashlib.sha256(b"halo").hexdigest())
        self.assertTrue(good.exists())
        with self.assertRaisesRegex(UpdateError, "deleted"):
            updater.verify(good, hashlib.sha256(b"something else").hexdigest())
        self.assertFalse(good.exists())


class StagingTests(Scratch):
    def serve(self, package, sums_digest=None, api_digest=None):
        digest = sums_digest or hashlib.sha256(package).hexdigest()
        release = updater.pick_release(release_json(size=len(package), digest=api_digest))
        web = FakeWeb({release.zip_url: package,
                       release.sums_url: f"{digest}  Halo-Windows-x64.zip\n".encode()})
        return release, web

    def test_a_verified_release_is_unpacked_once(self):
        release, web = self.serve(make_zip())
        paths = UpdatePaths(self.root / "updates")
        progress = []
        package, stated = updater.prepare(release, paths, progress=lambda got, total: progress.append(got), opener=web)
        self.assertEqual(stated, "0.7.0")
        self.assertEqual((package / "Halo.exe").read_bytes(), b"new exe")
        self.assertEqual(package, paths.version_folder("0.7.0") / "Halo")
        self.assertEqual(progress[-1], release.zip_size)
        self.assertEqual(list(paths.root.glob("*.zip*")), [])  # the ZIP goes once unpacked
        again, _ = updater.prepare(release, paths, opener=FakeWeb({}))  # no network needed the second time
        self.assertEqual(again, package)

    def test_a_download_that_fails_its_checksum_is_never_staged(self):
        release, web = self.serve(make_zip(), sums_digest="00" * 32)
        paths = UpdatePaths(self.root / "updates")
        with self.assertRaisesRegex(UpdateError, "checksum"):
            updater.prepare(release, paths, opener=web)
        self.assertEqual(tree(paths.root), {})
        self.assertIsNone(updater.staged_package(paths, release))

    def test_a_package_must_be_complete_and_the_right_version(self):
        cases = ((make_zip(version_text="0.6.9"), "version 0.6.9"),
                 (make_zip(exe=b"x", extra={"Halo/../evil.txt": b"x"}), "outside"),
                 (make_zip(extra={"Elsewhere/file.txt": b"x"}), "outside"),
                 (make_zip(extra={"Halo/C:/evil.txt": b"x"}), "outside"),
                 (b"PK not a zip at all", "damaged"))
        for package, words in cases:
            release, web = self.serve(package)
            paths = UpdatePaths(self.root / "updates")
            with self.assertRaisesRegex(UpdateError, words):
                updater.prepare(release, paths, opener=web)
            self.assertFalse((self.root / "evil.txt").exists())
            self.assertEqual([path for path in paths.root.rglob("*") if path.is_file()], [])

    def test_a_release_found_without_the_api_is_still_checked(self):
        package = make_zip()
        page = updater.Release("0.7.0", "v0.7.0", "Halo 0.7.0", "", updater.RELEASES_PAGE,
                               PREFIX + "Halo-Windows-x64.zip", 0, "", PREFIX + "SHA256SUMS.txt")
        paths = UpdatePaths(self.root / "updates")
        bad = FakeWeb({page.zip_url: package, page.sums_url: ("00" * 32 + "  Halo-Windows-x64.zip\n").encode()})
        with self.assertRaisesRegex(UpdateError, "checksum"):
            updater.prepare(page, paths, opener=bad)
        good = FakeWeb({page.zip_url: package,
                        page.sums_url: f"{hashlib.sha256(package).hexdigest()}  Halo-Windows-x64.zip\n".encode()})
        package_dir, stated = updater.prepare(page, paths, opener=good)
        self.assertEqual(stated, "0.7.0")
        self.assertEqual(updater.staged_package(paths, page)[0], package_dir)

    def test_a_tampered_staged_copy_is_not_reused(self):
        release, web = self.serve(make_zip())
        paths = UpdatePaths(self.root / "updates")
        package, _ = updater.prepare(release, paths, opener=web)
        (package / "_internal" / "extra.dll").write_bytes(b"?")
        self.assertIsNone(updater.staged_package(paths, release))

    def test_staging_a_newer_release_drops_the_older_copy(self):
        paths = UpdatePaths(self.root / "updates")
        release, web = self.serve(make_zip())
        updater.prepare(release, paths, opener=web)
        package = make_zip("0.7.1")
        newer = updater.pick_release(release_json("0.7.1", size=len(package)))
        web = FakeWeb({newer.zip_url: package,
                       newer.sums_url: f"{hashlib.sha256(package).hexdigest()}  Halo-Windows-x64.zip\n".encode()})
        updater.prepare(newer, paths, opener=web)
        self.assertEqual(sorted(path.name for path in paths.root.iterdir() if path.is_dir()), ["0.7.1"])


class InstallCheckTests(Scratch):
    def make_app(self, name="Halo.exe"):
        app = self.root / "Halo"
        (app / "_internal").mkdir(parents=True)
        (app / name).write_bytes(b"old exe")
        return app / name

    def test_only_a_packaged_writable_copy_updates_itself(self):
        exe = self.make_app()
        data = self.root / "data"
        self.assertIn("source", updater.install_blocker(exe, data, frozen=False))
        self.assertEqual(updater.install_blocker(exe, data, frozen=True), "")
        self.assertEqual(list(exe.parent.glob(".halo-write-test*")), [])
        self.assertIn("settings", updater.install_blocker(exe, exe.parent / "_internal" / "data", frozen=True))
        with mock.patch.object(Path, "write_bytes", side_effect=PermissionError("denied")):
            self.assertIn("administrator", updater.install_blocker(exe, data, frozen=True))

    def test_a_renamed_program_does_not_update_itself(self):
        exe = self.make_app("MyHalo.exe")
        self.assertIn("Halo.exe", updater.install_blocker(exe, self.root / "data", frozen=True))

    def test_the_helper_is_started_from_the_new_copy_with_a_plan(self):
        paths = UpdatePaths(self.root / "updates")
        paths.root.mkdir()
        paths.healthy.write_text("{}")
        commands = []
        updater.start_helper(paths, self.root / "staged" / "Halo", self.root / "Halo", 4321, "0.6.0", "0.7.0",
                             start=commands.append)
        self.assertEqual(commands, [[str(self.root / "staged" / "Halo" / "Halo.exe"), "--apply-update", str(paths.plan)]])
        plan = read_json(paths.plan)
        self.assertEqual((plan["protocol"], plan["pid"], plan["from_version"], plan["to_version"]),
                         (PROTOCOL, 4321, "0.6.0", "0.7.0"))
        self.assertEqual(plan["target"], str((self.root / "Halo").resolve()))
        self.assertFalse(paths.healthy.exists())
        self.assertEqual(read_json(paths.state)["phase"], "starting")

    def test_a_helper_that_never_starts_is_cancelled(self):
        paths = UpdatePaths(self.root / "updates")
        paths.root.mkdir()
        write_json(paths.state, {"phase": "starting", "updated_at": time.time()})
        process = mock.Mock()
        process.poll.return_value = None
        updater.cancel_helper(paths, process)
        process.terminate.assert_called_once()
        self.assertTrue(paths.cancel.exists())
        self.assertEqual(read_json(paths.state)["phase"], "cancelled")

    def test_cleaning_keeps_a_newer_staged_copy_and_a_running_helper(self):
        paths = UpdatePaths(self.root / "updates")
        for name in ("0.5.0", "0.6.0", "0.7.0.part", "0.7.0"):
            (paths.root / name).mkdir(parents=True)
        (paths.root / "Halo-0.7.0.zip.part").write_bytes(b"x")
        app = self.root / "Halo"
        (app / ".halo-previous" / "_internal").mkdir(parents=True)
        write_json(paths.state, {"phase": "verifying", "updated_at": time.time()})
        updater.clean(paths, "0.6.0", app)
        self.assertEqual(len(list(paths.root.iterdir())), 6)  # a helper may still be running: touch nothing
        write_json(paths.state, {"phase": "done", "updated_at": time.time()})
        updater.clean(paths, "0.6.0", app)
        self.assertEqual(sorted(path.name for path in paths.root.iterdir()), ["0.7.0", "state.json"])
        self.assertFalse((app / ".halo-previous").exists())
        write_json(paths.state, {"phase": "verifying", "updated_at": time.time() - 3600})
        self.assertFalse(updater.helper_active(read_json(paths.state)))  # a long-silent helper is gone


class HelperTests(Scratch):
    def setUp(self):
        super().setUp()
        self.target = self.root / "Halo"
        (self.target / "_internal" / "PySide6").mkdir(parents=True)
        (self.target / "Halo.exe").write_bytes(b"old exe")
        (self.target / "_internal" / "base_library.zip").write_bytes(b"old library")
        (self.target / "_internal" / "PySide6" / "old-only.dll").write_bytes(b"old dll")
        (self.target / "docs").mkdir()
        (self.target / "docs" / "modes.md").write_bytes(b"old docs")
        (self.target / "VERSION.txt").write_bytes(b"0.6.0\n")
        (self.target / "My notes.txt").write_bytes(b"the person's own file")
        self.source = self.root / "updates" / "0.7.0" / "Halo"
        (self.source / "_internal" / "PySide6").mkdir(parents=True)
        (self.source / "Halo.exe").write_bytes(b"new exe")
        (self.source / "_internal" / "base_library.zip").write_bytes(b"new library")
        (self.source / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(b"new qt")
        (self.source / "VERSION.txt").write_bytes(b"0.7.0\n")
        (self.source / "README.md").write_bytes(b"new readme")
        self.before = tree(self.target)
        self.new = tree(self.source)

    def test_a_swap_replaces_the_program_and_keeps_the_old_one_aside(self):
        backup = update_helper.backup_folder(self.target)
        moved, installed = update_helper.swap(self.target, self.source, backup, sleep=lambda _: None)
        after = tree(self.target)
        for name, data in self.new.items():
            self.assertEqual(after[name], data)
        self.assertNotIn("_internal/PySide6/old-only.dll", after)  # stale libraries go with the old copy
        self.assertNotIn("docs/modes.md", after)                    # a package entry the new copy dropped
        self.assertEqual(after["My notes.txt"], b"the person's own file")
        self.assertEqual(tree(backup)["Halo.exe"], b"old exe")
        self.assertEqual(moved[-1], "Halo.exe")
        self.assertEqual(installed[-1], "Halo.exe")
        self.assertEqual(tree(self.source), self.new)  # the staged copy is copied, not moved

    def test_a_failed_copy_puts_every_old_file_back(self):
        copied = []

        def failing_copy(source, destination):
            copied.append(source.name)
            if source.name == "VERSION.txt":
                (destination).write_bytes(b"half")
                raise OSError(28, "No space left on device")
            update_helper.copy_entry(source, destination)

        backup = update_helper.backup_folder(self.target)
        with self.assertRaises(OSError):
            update_helper.swap(self.target, self.source, backup, copy=failing_copy, sleep=lambda _: None)
        self.assertIn("_internal", copied)
        self.assertEqual(tree(self.target), self.before)
        self.assertFalse(backup.exists())

    def test_a_locked_old_file_leaves_everything_as_it_was(self):
        real_replace = os.replace

        def locked(source, destination):
            if Path(source).name == "docs":
                raise PermissionError(32, "The file is being used by another process")
            return real_replace(source, destination)

        backup = update_helper.backup_folder(self.target)
        with mock.patch.object(update_helper.os, "replace", side_effect=locked):
            with self.assertRaises(PermissionError):
                update_helper.swap(self.target, self.source, backup, sleep=lambda _: None)
        self.assertEqual(tree(self.target), self.before)

    def test_backup_folders_never_collide(self):
        (self.target / ".halo-previous").mkdir()
        self.assertEqual(update_helper.backup_folder(self.target).name, ".halo-previous-1")

    def plan(self, **changes):
        updates = self.root / "updates"
        plan = {"protocol": PROTOCOL, "pid": 999999, "target": str(self.target), "source": str(self.source),
                "from_version": "0.6.0", "to_version": "0.7.0", "state": str(updates / "state.json"),
                "ready": str(updates / "helper-ready.json"), "cancel": str(updates / "cancel"),
                "healthy": str(updates / "healthy.json"), "log": str(updates / "update.log")}
        plan.update(changes)
        write_json(updates / "plan.json", plan)
        return updates / "plan.json", plan

    class Process:
        """A started Halo: it reports healthy, closes early, or hangs."""
        def __init__(self, behaviour, healthy=None, version="0.7.0"):
            self.behaviour, self.healthy, self.version = behaviour, healthy, version
            self.terminated = False
            self.polls = 0

        def poll(self):
            self.polls += 1
            if self.behaviour == "healthy" and self.healthy is not None:
                write_json(self.healthy, {"version": self.version})
            if self.behaviour == "crash" and self.polls > 2 or self.terminated:
                return 1
            return None

        def terminate(self):
            self.terminated = True

    def run_plan(self, behaviour, old_exits=True, **changes):
        path, plan = self.plan(**changes)
        started, processes = [], []

        def start(exe):
            started.append((Path(exe).read_bytes()))
            process = self.Process(behaviour if not processes else "healthy", Path(plan["healthy"]))
            processes.append(process)
            return process

        clock = iter(range(0, 100000, 1))
        code = update_helper.run(path, wait_exit=lambda pid, timeout: old_exits, start=start,
                                 sleep=lambda _: None, clock=lambda: next(clock), health_timeout=50)
        return code, started, processes, plan

    def test_a_healthy_new_version_is_kept_and_the_backup_removed(self):
        code, started, _, plan = self.run_plan("healthy")
        self.assertEqual(code, 0)
        self.assertEqual(started, [b"new exe"])
        self.assertEqual(tree(self.target)["Halo.exe"], b"new exe")
        self.assertEqual(list(self.target.glob(".halo-previous*")), [])
        state = read_json(plan["state"])
        self.assertEqual((state["phase"], state["result"]), ("done", "updated"))
        self.assertTrue(read_json(plan["ready"]).get("helper_pid"))

    def test_a_new_version_that_closes_while_starting_is_rolled_back(self):
        code, started, _, plan = self.run_plan("crash")
        self.assertEqual(code, 17)
        self.assertEqual(started, [b"new exe", b"old exe"])  # the old Halo opens again
        self.assertEqual(tree(self.target), self.before)
        state = read_json(plan["state"])
        self.assertEqual((state["phase"], state["result"]), ("done", "rolled_back"))
        self.assertIn("closed", state["reason"])

    def test_a_new_version_stuck_on_an_error_is_stopped_and_rolled_back(self):
        code, started, processes, plan = self.run_plan("hang")
        self.assertEqual(code, 17)
        self.assertTrue(processes[0].terminated)
        self.assertEqual(tree(self.target), self.before)
        self.assertEqual(read_json(plan["state"])["result"], "rolled_back")

    def test_nothing_changes_if_halo_never_closes_or_cancels(self):
        code, started, _, plan = self.run_plan("healthy", old_exits=False)
        self.assertEqual((code, started), (12, []))
        self.assertEqual(tree(self.target), self.before)
        self.assertEqual(read_json(plan["state"])["phase"], "aborted")
        Path(plan["cancel"]).write_text("cancelled")
        code, started, _, plan = self.run_plan("healthy")
        self.assertEqual((code, started), (13, []))
        self.assertEqual(tree(self.target), self.before)

    def test_unsafe_or_unknown_plans_are_refused(self):
        for changes in ({"protocol": 2}, {"source": str(self.target / "_internal")}, {"target": "relative"},
                        {"source": str(self.root / "missing")}, {"pid": "1"}):
            path, _ = self.plan(**changes)
            self.assertEqual(update_helper.run(path, wait_exit=lambda *a: self.fail("must not wait")), 10)
        self.assertEqual(tree(self.target), self.before)

    def test_state_files_survive_a_reader_holding_them_open(self):
        # Found in a packaged run: replacing state.json failed while another process was reading it.
        path = self.root / "state.json"
        write_json(path, {"phase": "swapping"})
        real_replace, refusals = os.replace, []

        def busy_then_free(source, destination):
            if len(refusals) < 3:
                refusals.append(destination)
                raise PermissionError(5, "Access is denied")
            return real_replace(source, destination)

        with mock.patch.object(update_helper.os, "replace", side_effect=busy_then_free):
            write_json(path, {"phase": "verifying"}, sleep=lambda _: None)
        self.assertEqual((len(refusals), read_json(path)["phase"]), (3, "verifying"))
        real_read, reads = Path.read_text, []

        def locked_once(self_, *args, **kwargs):
            reads.append(self_)
            if len(reads) == 1:
                raise PermissionError(32, "The process cannot access the file")
            return real_read(self_, *args, **kwargs)

        with mock.patch.object(Path, "read_text", locked_once):
            self.assertEqual(read_json(path, sleep=lambda _: None)["phase"], "verifying")
        self.assertEqual(read_json(self.root / "missing.json"), {})

    def test_child_processes_start_as_their_own_program(self):
        env = update_helper.child_environment({"_PYI_APPLICATION_HOME_DIR": "old", "_PYI_ARCHIVE_FILE": "old",
                                               "QT_PLUGIN_PATH": "old", "PATH": "C:\\Windows", "HALO_DATA_DIR": "d"})
        self.assertEqual(env, {"PATH": "C:\\Windows", "HALO_DATA_DIR": "d", "PYINSTALLER_RESET_ENVIRONMENT": "1"})

    def test_waiting_for_a_real_process_to_exit(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertFalse(update_helper.wait_for_exit(process.pid, .2))
            process.kill()
            self.assertTrue(update_helper.wait_for_exit(process.pid, 10))
        finally:
            process.kill()
            process.wait()

    def test_the_entry_point_runs_the_helper_without_qt(self):
        path, _ = self.plan(protocol=0)
        result = subprocess.run([sys.executable, "-X", "importtime", str(ROOT / "main.py"), "--apply-update", str(path)],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 10)
        self.assertNotIn("PySide6", result.stderr)
        self.assertIn("Plan refused", (path.parent / "update.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
