"""Updates: find Halo's newest release on GitHub, download it, check it, and stage it.

Nothing here replaces any program files. A running program can't replace itself, so the
helper in update_helper.py does that after Halo closes, from the staged copy made here.

Only GitHub is contacted, with a generic User-Agent ("Halo-Updater"): no song, account, PC or
version details are sent. A download is offered only after its SHA-256 matches the release's
SHA256SUMS.txt (and GitHub's own record of the file, when it has one); anything else is deleted.

Standard library only, so it can be tested without Qt or a network.
"""
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen
import zipfile

from .update_helper import (ACTIVE_PHASES, BACKUP_PREFIX, EXE, PACKAGE_NAMES, PROTOCOL, child_environment,
                            read_json, remove, write_json)

REPOSITORY = "lmaoitsatharv/halo"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
ASSET_NAME = "Halo-Windows-x64.zip"
SUMS_NAME = "SHA256SUMS.txt"
PACKAGE_DIR = "Halo"
USER_AGENT = "Halo-Updater"
# For testing a whole update against a local copy of a release: a JSON file shaped like
# GitHub's latest-release answer, served from this PC (or any https address).
FEED_VARIABLE = "HALO_UPDATE_FEED"
MAX_RELEASE_BYTES = 1 << 20
MAX_SUMS_BYTES = 64 << 10
MAX_PACKAGE_BYTES = 1 << 30
MAX_UNPACKED_BYTES = 3 << 30
STALE_SECONDS = 15 * 60  # an update helper that has said nothing for this long is gone


class UpdateError(Exception):
    """Why there is no update to offer, in words for the person."""


class RateLimited(UpdateError):
    """GitHub's API turned the request away (60 an hour per address without an account)."""


class UpdateCancelled(Exception):
    """Halo is closing; stop downloading."""


# Versions ---------------------------------------------------------------------------------------------

_VERSION = re.compile(r"^v?(\d{1,6}(?:\.\d{1,6}){0,3})(?:-([0-9A-Za-z][0-9A-Za-z.-]{0,40})|([A-Za-z][0-9A-Za-z.-]{0,40}))?$")


def parse_version(text):
    """A sortable key for "v0.7.0", "0.7", "0.7.0-beta.2" and the like, or None.

    Missing parts count as zero (0.7 == 0.7.0), and a pre-release sorts before its release.
    """
    if not isinstance(text, str):
        return None
    match = _VERSION.match(text.strip().split("+", 1)[0])
    if not match:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    numbers += (0,) * (4 - len(numbers))
    label = match.group(2) or match.group(3)
    if label is None:
        return numbers + ((1,),)
    parts = tuple((0, int(part), "") if part.isdigit() else (1, 0, part.lower())
                  for part in re.split(r"[.-]", label) if part)
    return numbers + ((0,) + parts,)


def is_newer(candidate, current):
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def same_version(a, b):
    a, b = parse_version(a), parse_version(b)
    return a is not None and a == b


# The release ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    title: str
    notes: str
    page: str
    zip_url: str
    zip_size: int
    zip_digest: str
    sums_url: str


def feed():
    """(release address, the prefix every download must start with, the release page fallback)."""
    override = os.environ.get(FEED_VARIABLE, "").strip()
    if override:
        parts = urlsplit(override)
        local = False
        try:
            local = parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname or "").is_loopback
        except ValueError:
            pass
        if (parts.scheme == "https" and parts.hostname) or (parts.scheme == "http" and local):
            return override, f"{parts.scheme}://{parts.netloc}/", override
    return LATEST_URL, DOWNLOAD_PREFIX, RELEASES_PAGE


_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]{0,200}>")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def plain(text):
    """Markdown to one plain line: links keep their words, emphasis and code marks go."""
    text = _CONTROL.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _TAG.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return " ".join(text.split())


def shorten(text, limit=170, minimum=40):
    """The first sentence when it is a reasonable length, otherwise a clean cut at a word."""
    if len(text) <= limit:
        return text
    for match in re.finditer(r"[.!?](?=\s)", text):
        if minimum <= match.end() <= limit:
            return text[:match.end()]
    cut = text[:limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut).rstrip(" ,;:") + "…"


def short_notes(body, bullets=6):
    """The release's opening paragraph and its "What's new" points, as short plain text."""
    if not isinstance(body, str) or not body.strip():
        return ""
    lines = body[:20000].replace("\r\n", "\n").replace("\r", "\n").split("\n")
    intro, section, points, in_new = [], None, [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip().casefold()
            in_new = "new" in section or "change" in section
            continue
        if section is None:
            if stripped:
                intro.append(stripped)
            elif intro:
                section = ""  # the opening paragraph ends at its first blank line
            continue
        if in_new and re.match(r"^[-*+] ", line):  # top-level points only
            point = plain(stripped[2:])
            if point:
                points.append(shorten(point))
    text = shorten(plain(" ".join(intro)), limit=320, minimum=60) if intro else ""
    if points:
        listed = "\n".join("• " + point for point in points[:bullets])
        if len(points) > bullets:
            listed += "\n…and more in the full notes."
        text = (text + "\n\n" + listed) if text else listed
    if not text:
        text = shorten(plain(body), limit=320, minimum=60)
    return text


def pick_release(data, prefix=DOWNLOAD_PREFIX, page_fallback=RELEASES_PAGE):
    """The ZIP and checksum list of GitHub's latest-release answer, or UpdateError."""
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent an unexpected answer.")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError("The newest release is a preview.")
    tag = data.get("tag_name")
    if parse_version(tag) is None:
        raise UpdateError("The newest release has no version number.")
    assets = [item for item in data.get("assets") or [] if isinstance(item, dict)] \
        if isinstance(data.get("assets"), list) else []

    def asset(name):
        return next((item for item in assets if item.get("name") == name), None)

    package, sums = asset(ASSET_NAME), asset(SUMS_NAME)
    if package is None:
        raise UpdateError(f"The newest release has no {ASSET_NAME}.")
    if sums is None:
        raise UpdateError(f"The newest release has no {SUMS_NAME}, so its download can't be checked.")
    zip_url, sums_url = package.get("browser_download_url"), sums.get("browser_download_url")
    for url in (zip_url, sums_url):
        if not isinstance(url, str) or not url.startswith(prefix) or any(ch.isspace() for ch in url):
            raise UpdateError("The newest release's files aren't in its GitHub downloads.")
    size = package.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_PACKAGE_BYTES:
        raise UpdateError("The newest release's download has an unexpected size.")
    digest = str(package.get("digest") or "").lower()
    digest = digest[7:] if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) else ""
    page = data.get("html_url")
    if not isinstance(page, str) or not page.startswith(f"https://github.com/{REPOSITORY}/"):
        page = page_fallback
    version = tag.strip()
    version = version[1:] if version[:1] in "vV" else version
    return Release(version=version, tag=tag.strip(), title=plain(str(data.get("name") or ""))[:120],
                   notes=short_notes(data.get("body")), page=page, zip_url=zip_url, zip_size=size,
                   zip_digest=digest, sums_url=sums_url)


# Checksums --------------------------------------------------------------------------------------------

def parse_sums(text):
    """SHA256SUMS.txt lines ("<64 hex>  name", or "*name" for binary mode) as {name: digest}."""
    sums = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9A-Fa-f]{64})\s+\*?(\S(?:.*\S)?)\s*$", line)
        if not match:
            continue
        name, digest = match.group(2), match.group(1).lower()
        if sums.get(name, digest) != digest:
            raise UpdateError(f"{SUMS_NAME} lists {name} twice with different checksums.")
        sums[name] = digest
    return sums


def expected_digest(sums_text, release):
    """The checksum the ZIP must have. GitHub's own record, when present, must agree."""
    digest = parse_sums(sums_text).get(ASSET_NAME)
    if digest is None:
        raise UpdateError(f"{SUMS_NAME} has no line for {ASSET_NAME}.")
    if release.zip_digest and release.zip_digest != digest:
        raise UpdateError(f"{SUMS_NAME} and GitHub disagree about the download's checksum.")
    return digest


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path, digest):
    """Keep the file only if it matches; a file that fails is deleted, never installed."""
    if sha256_file(path) != digest:
        Path(path).unlink(missing_ok=True)
        raise UpdateError("The download didn't match its published checksum, so it was deleted.")


# The network ------------------------------------------------------------------------------------------

def _request(url, accept):
    # Only a generic name: GitHub asks every client for one. Nothing about the person or this PC.
    return Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})


def _network_error(error):
    if isinstance(error, HTTPError):
        if error.code == 404:
            return UpdateError("No release has been published yet.")
        if error.code in (403, 429):
            return RateLimited("GitHub is limiting requests right now. Halo will try again later.")
        return UpdateError(f"GitHub answered with an error ({error.code}).")
    return UpdateError("Couldn't reach GitHub. Check your connection and try again.")


def fetch(url, limit, accept="application/octet-stream", opener=urlopen, timeout=20):
    try:
        with opener(_request(url, accept), timeout=timeout) as response:
            data = response.read(limit + 1)
    except (HTTPError, URLError, OSError, ValueError) as error:
        raise _network_error(error) from error
    if len(data) > limit:
        raise UpdateError("GitHub sent more than expected.")
    return data


def latest_release(opener=urlopen):
    url, prefix, page = feed()
    try:
        answer = fetch(url, MAX_RELEASE_BYTES, "application/vnd.github+json", opener)
    except RateLimited:
        if url != LATEST_URL:
            raise
        # Many people share one internet address (mobile and some home networks), so the API's
        # allowance can be used up by others. The release page itself isn't counted.
        return latest_from_page(opener)
    try:
        data = json.loads(answer.decode("utf-8"))
    except ValueError as error:  # includes UnicodeDecodeError
        raise UpdateError("GitHub sent an unexpected answer.") from error
    return pick_release(data, prefix, page)


def latest_from_page(opener=urlopen):
    """The latest release from where GitHub's "latest release" page redirects, without the API.

    This gives the tag only: the download addresses follow from it, and there are no notes.
    The size is learned from the download and, as always, the checksum list decides.
    """
    try:
        with opener(_request(RELEASES_PAGE, "text/html"), timeout=20) as response:
            final = response.geturl()
    except (HTTPError, URLError, OSError, ValueError) as error:
        raise _network_error(error) from error
    stem = f"https://github.com/{REPOSITORY}/releases/tag/"
    tag = unquote(final[len(stem):]) if isinstance(final, str) and final.startswith(stem) else ""
    if not re.fullmatch(r"[0-9A-Za-z.+-]{1,64}", tag) or parse_version(tag) is None:
        raise UpdateError("GitHub sent an unexpected answer.")
    version = tag[1:] if tag[:1] in "vV" else tag
    base = f"{DOWNLOAD_PREFIX}{quote(tag)}/"
    return Release(version=version, tag=tag, title=f"Halo {version}", notes="", page=final,
                   zip_url=base + ASSET_NAME, zip_size=0, zip_digest="", sums_url=base + SUMS_NAME)


def _announced_size(response):
    try:
        size = int(getattr(response, "headers", {}).get("Content-Length") or 0)
    except (TypeError, ValueError, AttributeError):
        size = 0
    return size if 0 < size <= MAX_PACKAGE_BYTES else 0


def download(url, destination, size, progress=None, cancelled=None, opener=urlopen, chunk=1 << 18):
    """Stream a file to destination; a partial file is removed whatever goes wrong.

    size 0 means "not known yet": the server's Content-Length is used if it gives one.
    """
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    received = 0
    try:
        try:
            response = opener(_request(url, "application/octet-stream"), timeout=30)
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise _network_error(error) from error
        if size <= 0:
            size = _announced_size(response)
        known = size > 0
        limit = size if known else MAX_PACKAGE_BYTES
        with response:
            try:
                out = open(partial, "wb")
            except OSError as error:
                raise UpdateError(f"The download couldn't be saved: {error}") from error
            with out:
                while True:
                    if cancelled is not None and cancelled():
                        raise UpdateCancelled()
                    try:
                        block = response.read(chunk)
                    except OSError as error:
                        raise _network_error(error) from error
                    if not block:
                        break
                    received += len(block)
                    if received > limit:
                        raise UpdateError("The download is larger than GitHub said it would be.")
                    try:
                        out.write(block)
                    except OSError as error:
                        raise UpdateError(f"The download couldn't be saved: {error}") from error
                    if progress is not None:
                        progress(received, size)
        if known and received != size or received == 0:
            raise UpdateError("The download stopped early. Halo will try again later.")
        os.replace(partial, destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


# Staging ----------------------------------------------------------------------------------------------

def check_package(package, version):
    """A complete Halo folder of exactly this version."""
    package = Path(package)
    if not (package / EXE).is_file() or not (package / "_internal").is_dir():
        raise UpdateError("The download isn't a complete Halo package.")
    try:
        stated = (package / "VERSION.txt").read_text(encoding="utf-8-sig").strip()
    except OSError:
        raise UpdateError("The download doesn't say which version it is.") from None
    if not same_version(stated, version):
        raise UpdateError(f"The download says it is version {stated[:20]}, not {version}.")
    return stated


def _member_path(name):
    """The parts of a ZIP entry, or None if it could land anywhere but inside Halo/."""
    if not name or "\\" in name or ":" in name or name.startswith("/"):
        return None
    parts = PurePosixPath(name).parts
    if not parts or parts[0] != PACKAGE_DIR or any(part in ("..", ".", "") for part in parts):
        return None
    return parts


def unpack(archive_path, destination, version):
    """Unpack a verified ZIP into destination/Halo, refusing any entry that could land outside it."""
    destination = Path(destination)
    partial = destination.with_name(destination.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members, total = archive.infolist(), 0
            for info in members:
                if _member_path(info.filename) is None or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError("The download contains a file outside Halo's folder.")
                total += info.file_size
                if total > MAX_UNPACKED_BYTES:
                    raise UpdateError("The download unpacks to more than expected.")
            root = partial.resolve()
            for info in members:
                target = partial.joinpath(*_member_path(info.filename))
                if not target.resolve().is_relative_to(root):
                    raise UpdateError("The download contains a file outside Halo's folder.")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out, 1 << 20)
        stated = check_package(partial / PACKAGE_DIR, version)
        shutil.rmtree(destination, ignore_errors=True)
        os.replace(partial, destination)
    except zipfile.BadZipFile as error:
        shutil.rmtree(partial, ignore_errors=True)
        raise UpdateError("The download is damaged.") from error
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return destination / PACKAGE_DIR, stated


def tree_summary(folder):
    files = [path for path in Path(folder).rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


@dataclass(frozen=True)
class UpdatePaths:
    """Everything an update keeps, in an "updates" folder beside Halo's settings."""
    root: Path

    @property
    def state(self):
        return self.root / "state.json"

    @property
    def plan(self):
        return self.root / "plan.json"

    @property
    def ready(self):
        return self.root / "helper-ready.json"

    @property
    def cancel(self):
        return self.root / "cancel"

    @property
    def healthy(self):
        return self.root / "healthy.json"

    @property
    def log(self):
        return self.root / "update.log"

    def version_folder(self, version):
        return self.root / re.sub(r"[^0-9A-Za-z.-]", "_", version)[:40]


def staged_package(paths, release):
    """The already unpacked and checked copy of this release, or None."""
    folder = paths.version_folder(release.version)
    marker = read_json(folder / "staged.json")
    package = folder / PACKAGE_DIR
    if (marker.get("version") != release.version or marker.get("zip_url") != release.zip_url
            or not marker.get("zip_sha256") or release.zip_digest and marker["zip_sha256"] != release.zip_digest):
        return None
    try:
        check_package(package, release.version)
        if list(tree_summary(package)) != [marker.get("files"), marker.get("bytes")]:
            return None
    except (UpdateError, OSError):
        return None
    return package, marker


def prepare(release, paths, progress=None, cancelled=None, opener=urlopen):
    """Download, verify and unpack a release once. Returns (package folder, version it states)."""
    paths.root.mkdir(parents=True, exist_ok=True)
    staged = staged_package(paths, release)
    if staged is not None:
        return staged[0], staged[1].get("stated", release.version)
    sums = fetch(release.sums_url, MAX_SUMS_BYTES, "text/plain", opener)
    try:
        digest = expected_digest(sums.decode("utf-8-sig"), release)
    except UnicodeDecodeError as error:
        raise UpdateError(f"{SUMS_NAME} isn't readable.") from error
    archive = paths.root / f"Halo-{paths.version_folder(release.version).name}.zip"
    download(release.zip_url, archive, release.zip_size, progress, cancelled, opener)
    try:
        verify(archive, digest)
        folder = paths.version_folder(release.version)
        package, stated = unpack(archive, folder, release.version)
        files, size = tree_summary(package)
        write_json(folder / "staged.json", {"version": release.version, "stated": stated, "zip_sha256": digest,
                                            "zip_url": release.zip_url, "files": files, "bytes": size,
                                            "release": asdict(release)})
    finally:
        archive.unlink(missing_ok=True)
    # Only the newest staged copy is worth keeping.
    for child in paths.root.iterdir():
        if child.is_dir() and child != folder and parse_version(child.name.removesuffix(".part")) is not None:
            try:
                remove(child)
            except OSError:
                pass
    return package, stated


# Installing -------------------------------------------------------------------------------------------

def install_blocker(executable, data_dir, frozen):
    """Why this copy of Halo can't update itself in place, or "" when it can."""
    if not frozen:
        return "Halo is running from source, so it doesn't replace its own files."
    executable = Path(executable)
    if executable.name.casefold() != EXE.casefold():
        return f"Halo updates itself only when its program is named {EXE}."
    app_dir = executable.parent
    if not (app_dir / "_internal").is_dir():
        return "Halo's folder doesn't look like the portable download."
    try:
        data = Path(data_dir).resolve()
        if any(data.is_relative_to((app_dir / name).resolve()) for name in PACKAGE_NAMES):
            return "Halo's settings are inside a folder an update would replace."
    except OSError:
        pass
    probe = app_dir / f".halo-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return "Halo's folder can't be changed without administrator rights."
    return ""


def start_helper(paths, package, app_dir, pid, current, stated, start=None):
    """Write the plan and start the new copy's helper. Returns the helper's process."""
    for stale in (paths.ready, paths.cancel, paths.healthy):
        stale.unlink(missing_ok=True)
    plan = {"protocol": PROTOCOL, "pid": int(pid), "target": str(Path(app_dir).resolve()),
            "source": str(Path(package).resolve()), "from_version": current, "to_version": stated,
            "state": str(paths.state), "ready": str(paths.ready), "cancel": str(paths.cancel),
            "healthy": str(paths.healthy), "log": str(paths.log)}
    write_json(paths.plan, plan)
    write_json(paths.state, {"protocol": PROTOCOL, "phase": "starting", "from_version": current,
                             "to_version": stated, "updated_at": time.time()})
    command = [str(Path(package) / EXE), "--apply-update", str(paths.plan)]
    if start is not None:
        return start(command)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(command, cwd=str(package), env=child_environment(), creationflags=flags,
                            close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def helper_ready(paths):
    return bool(read_json(paths.ready).get("helper_pid"))


def cancel_helper(paths, process):
    """Stop a helper that never said it was ready, so it can't swap files later."""
    try:
        paths.cancel.write_text("cancelled", encoding="utf-8")
    except OSError:
        pass
    try:
        if process.poll() is None:
            process.terminate()
    except OSError:
        pass
    state = read_json(paths.state)
    if state.get("phase") in ("starting",) + ACTIVE_PHASES:
        state.update(phase="cancelled", result="unchanged", reason="The update didn't start", updated_at=time.time())
        try:
            write_json(paths.state, state)
        except OSError:
            pass


def helper_active(state, now=None):
    now = time.time() if now is None else now
    try:
        recent = now - float(state.get("updated_at", 0)) < STALE_SECONDS
    except (TypeError, ValueError):
        recent = False
    return state.get("phase") in ("starting",) + ACTIVE_PHASES and recent


def mark_healthy(paths, version):
    """The new version started properly: tell a waiting helper."""
    write_json(paths.healthy, {"version": version, "pid": os.getpid(), "at": time.time()})


def clean(paths, current, app_dir=None):
    """Remove staged copies and backups that are no longer needed. Leaves a running helper's files,
    and a staged copy newer than this version (it may still be installed)."""
    if not paths.root.is_dir() or helper_active(read_json(paths.state)):
        return
    for child in paths.root.iterdir():
        name = child.name
        try:
            if child.is_dir():
                base = name[:-5] if name.endswith(".part") else name
                if parse_version(base) is not None and (name.endswith(".part") or not is_newer(base, current)):
                    remove(child)
            elif name.endswith((".zip", ".zip.part", ".tmp")):
                remove(child)
            elif child in (paths.plan, paths.ready, paths.cancel, paths.healthy):
                remove(child)
        except OSError:
            pass
    if app_dir is not None:
        for backup in Path(app_dir).glob(BACKUP_PREFIX + "*"):
            try:
                remove(backup)
            except OSError:
                pass
