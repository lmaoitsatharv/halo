"""Optional, conservatively matched cover lookup for missing Windows artwork."""
import json
import logging
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import UUID
from PySide6.QtCore import QObject, Signal, Slot, QBuffer, QIODevice
from PySide6.QtGui import QImageReader
from .models import normalize_name

log = logging.getLogger(__name__)
MAX_ARTWORK_BYTES = 5_000_000
MAX_CATALOG_BYTES = 2_000_000


def valid_artwork(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ARTWORK_BYTES:
        return False
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    return (0 < size.width() <= 4096 and 0 < size.height() <= 4096
            and not reader.read().isNull())


def _allowed_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    return (parts.scheme == "https" and not parts.username and not parts.password
            and parts.port in (None, 443)
            and (host in {"musicbrainz.org", "coverartarchive.org", "archive.org"}
                 or host.endswith(".archive.org")))


class _ArtworkRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not _allowed_url(newurl):
            raise ValueError("Unexpected artwork redirect")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def read_public(url, limit, accept):
    if not _allowed_url(url):
        raise ValueError("Unexpected artwork service")
    request = Request(url, headers={"User-Agent": "Halo/0.1 (Windows Spotify companion)", "Accept": accept})
    with build_opener(_ArtworkRedirect()).open(request, timeout=5) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Artwork response is too large")
    return data


def _title_parts(title):
    # A credited collaborator may be stored in Spotify's title but separately
    # in the catalog. Retain every other qualifier, including live/remix tags.
    match = re.search(r"\s*[([](?:with|feat\.?|featuring)\s+(.+?)[)\]]\s*$", title, re.I)
    return (title[:match.start()].strip(), match.group(1)) if match else (title, "")


def matching_releases(records, track):
    """Require title, credited artist, album and duration; prefer digital art."""
    title, collaborator = _title_parts(track.title)
    if not all((normalize_name(title), normalize_name(track.artist), normalize_name(track.album))):
        return []
    matches = {}
    for record in records:
        if not isinstance(record, dict) or normalize_name(record.get("title") or "") != normalize_name(title):
            continue
        credits = record.get("artist-credit") or []
        names = {normalize_name(name) for credit in credits if isinstance(credit, dict)
                 for name in (credit.get("name") or "", (credit.get("artist") or {}).get("name") or "")}
        joined = normalize_name(" ".join(credit.get("name") or "" for credit in credits if isinstance(credit, dict)))
        if normalize_name(track.artist) not in names | {joined}:
            continue
        if collaborator and normalize_name(collaborator) not in names:
            continue
        try:
            duration = float(record.get("length")) / 1000
        except (TypeError, ValueError):
            continue
        if not math.isfinite(duration) or abs(duration - track.duration) > 4:
            continue
        for release in record.get("releases") or []:
            if not isinstance(release, dict) or normalize_name(release.get("title") or "") != normalize_name(track.album):
                continue
            if release.get("status") != "Official":
                continue
            try:
                mbid = str(UUID(release.get("id") or ""))
            except (ValueError, TypeError, AttributeError):
                continue
            formats = {medium.get("format") for medium in release.get("media") or [] if isinstance(medium, dict)}
            priority = (0 if "Digital Media" in formats else 1 if "CD" in formats else 2,
                        0 if release.get("country") == "XW" else 1)
            matches[mbid] = priority
    return sorted(matches, key=matches.get)[:3]


class ArtworkWorker(QObject):
    ready = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.latest_key = None
        self.closing = False
        self.cache = {}
        self.last_search = 0.

    def obsolete(self, key):
        return self.closing or self.latest_key != key

    @Slot(object)
    def fetch(self, track):
        key = track.key
        if self.obsolete(key):
            return
        cached = self.cache.get(key)
        now = time.monotonic()
        if cached and now < cached[0]:
            self.ready.emit(key, cached[1])
            return
        data = b""
        ttl = 600
        try:
            title, _ = _title_parts(track.title)
            def quoted(text):
                return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'
            query = f"recording:{quoted(title)} AND artist:{quoted(track.artist)}"
            # MusicBrainz permits one search per second per client.
            delay = self.last_search + 1.1 - now
            if delay > 0:
                time.sleep(delay)
            if self.obsolete(key):
                return
            self.last_search = time.monotonic()
            url = "https://musicbrainz.org/ws/2/recording/?" + urlencode({"query": query, "fmt": "json", "limit": 20})
            payload = json.loads(read_public(url, MAX_CATALOG_BYTES, "application/json"))
            releases = matching_releases(payload.get("recordings") or [], track)
            for mbid in releases:
                if self.obsolete(key):
                    return
                try:
                    candidate = read_public(f"https://coverartarchive.org/release/{mbid}/front-500",
                                            MAX_ARTWORK_BYTES, "image/*")
                    if valid_artwork(candidate):
                        data, ttl = candidate, 3600
                        break
                except HTTPError as error:
                    if error.code != 404:
                        raise
        except Exception:
            log.debug("Online cover unavailable", exc_info=True)
            ttl = 60
        if self.obsolete(key):
            return
        self.cache[key] = (time.monotonic() + ttl, data)
        if len(self.cache) > 64:
            self.cache.pop(next(iter(self.cache)))
        self.ready.emit(key, data)
