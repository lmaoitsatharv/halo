import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PySide6.QtCore import QObject, Signal, Slot
from .models import Track, Lyrics, parse_lrc, eligible_match, title_search_variants, LyricsLimitError

log = logging.getLogger(__name__)
MAX_LYRICS_RESPONSE_BYTES = 4 * 1024 * 1024


class LyricsWorker(QObject):
    ready = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.cache = {}
        self.retry_after = 0.0
        self.last_request = 0.0
        self.latest_generation = None
        self.closing = False

    def obsolete(self, generation):
        return self.closing or (self.latest_generation is not None and generation != self.latest_generation)

    @staticmethod
    def timed_lines(record):
        try:
            lines = parse_lrc((record or {}).get("syncedLyrics") or "")
        except LyricsLimitError:
            return []
        # A single cue containing the entire text cannot provide line synchronization.
        return lines if len({line.time for line in lines if line.text}) >= 2 else []

    def request(self, endpoint, params):
        from urllib.parse import urlencode
        delay = self.last_request + .3 - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        request = Request("https://lrclib.net/api/" + endpoint + "?" + urlencode(params),
                          headers={"User-Agent": "Halo/0.1 (Windows Spotify companion; https://lrclib.net/docs)",
                                   "Accept": "application/json"})
        try:
            with urlopen(request, timeout=8) as response:
                data = response.read(MAX_LYRICS_RESPONSE_BYTES + 1)
                if len(data) > MAX_LYRICS_RESPONSE_BYTES:
                    raise LyricsLimitError()
                return json.loads(data)
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (429, 503):
                try:
                    seconds = max(1, float(error.headers.get("Retry-After", "60")))
                except ValueError:
                    seconds = 60
                self.retry_after = time.monotonic() + seconds
            raise

    @Slot(object, int)
    def fetch(self, track: Track, generation: int):
        # Requests are serialized in this worker. UI rejects obsolete generations.
        if self.obsolete(generation):
            return
        key = (*track.key, round(track.duration))
        if key in self.cache:
            self.ready.emit(generation, self.cache[key])
            return
        if time.monotonic() < self.retry_after:
            self.ready.emit(generation, Lyrics(message="Lyrics service is busy. Try again shortly."))
            return
        try:
            params = {"track_name": track.title, "artist_name": track.artist}
            if track.album:
                params["album_name"] = track.album
            if 1 <= track.duration <= 3600:
                params["duration"] = round(track.duration, 3)
            record = None
            candidates = []
            # Catalog search can return existing timed records even while the
            # signature endpoint's upstream fetching service is unavailable.
            for variant in title_search_variants(track.title):
                if self.obsolete(generation):
                    return
                records = self.request("search", {"track_name": variant, "artist_name": track.artist}) or []
                if self.obsolete(generation):
                    return
                candidates.extend(r for r in records if eligible_match(r, track))
                timed = [r for r in candidates if self.timed_lines(r)]
                if timed:
                    timed.sort(key=lambda r: (r.get("albumName") != track.album,
                                             abs(float(r.get("duration", 0)) - track.duration)))
                    record = timed[0]
                    break
            else:
                # Retain the signature endpoint as a fallback when catalog
                # searches cannot supply a usable timed record.
                record = self.request("get", params)
                if not record:
                    candidates.sort(key=lambda r: (not bool(r.get("plainLyrics")),
                                                   r.get("albumName") != track.album,
                                                   abs(float(r.get("duration", 0)) - track.duration)))
                    record = candidates[0] if candidates else None
            if self.obsolete(generation):
                return
            if record and record.get("instrumental"):
                result = Lyrics(message="No words needed. This track is instrumental.")
            elif self.timed_lines(record):
                result = Lyrics(self.timed_lines(record), "Line-synced lyrics · LRCLIB")
            elif record and record.get("plainLyrics"):
                result = Lyrics(message="Only untimed lyrics are available. Import an .lrc file to sync this track.")
            else:
                result = Lyrics(message="No timed lyrics found. You can import an .lrc file.")
            if result.lines or (record and record.get("instrumental")):
                self.cache[key] = result
            if len(self.cache) > 80:
                self.cache.pop(next(iter(self.cache)))
        except LyricsLimitError as error:
            result = Lyrics(message=str(error))
        except HTTPError as error:
            log.warning("Lyrics service returned HTTP %s", error.code)
            result = Lyrics(message="Lyrics service is temporarily unavailable. Use Retry lyrics in a moment."
                            if error.code in (429, 503) else "Lyrics lookup failed. Try again or import an .lrc file.")
        except Exception:
            log.exception("Lyrics lookup failed")
            result = Lyrics(message="Couldn't reach the lyrics service. Check your connection or import an .lrc file.")
        self.ready.emit(generation, result)
