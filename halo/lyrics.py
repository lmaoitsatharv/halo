import json
import logging
import math
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from PySide6.QtCore import QObject, Signal, Slot
from .models import Track, Lyrics, title_search_variants, LyricsLimitError
from .lyric_matching import recording_match, record_id, album_rank, candidate_metadata

log = logging.getLogger(__name__)
MAX_LYRICS_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SEARCH_RECORDS = 200
MAX_CHOICES = 30


class LyricsWorker(QObject):
    ready = Signal(object, object)
    choices_ready = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.cache = {}
        self.retry_after = 0.0
        self.last_request = 0.0
        self.latest_generation = None
        self.closing = False
        self.choice_key = None
        self.choice_records = {}

    def obsolete(self, generation):
        return self.closing or (self.latest_generation is not None and generation != self.latest_generation)

    @staticmethod
    def timed_lines(record):
        try:
            from .word_lyrics import parse_lyrics_record
            lines = parse_lyrics_record(record or {}).lines
        except LyricsLimitError:
            return []
        # One line can still be synchronized when it includes real word cues.
        return lines if (any(line.words for line in lines)
                         or len({line.time for line in lines if line.text}) >= 2) else []

    @staticmethod
    def track_key(track):
        try:
            duration = float(track.duration)
            duration = round(duration) if math.isfinite(duration) and duration >= 0 else 0
        except (TypeError, ValueError, OverflowError):
            duration = 0
        return (*track.key, duration)

    @staticmethod
    def result_for(record):
        if not record:
            return Lyrics(message="No timed lyrics found. You can import a lyrics file.")
        from .word_lyrics import parse_lyrics_record
        result = parse_lyrics_record(record)
        # One line at one instant cannot synchronize a complete recording.
        if not result.has_word_timing and len({line.time for line in result.lines if line.text}) < 2:
            result.lines = []
            if record.get("instrumental"):
                result.message = "No words needed. This track is instrumental."
            elif record.get("plainLyrics") or record.get("syncedLyrics"):
                result.message = "Only untimed lyrics are available. Import a lyrics file to sync this track."
            else:
                result.message = "No timed lyrics found. You can import a lyrics file."
        result.source_id = record_id(record)
        result.selected_record = candidate_metadata(record, result)
        return result

    def collect(self, track, generation, all_choices=False):
        """Bound requests and retained payloads, and keep stale work off the UI."""
        records_by_key = {}
        parsed = {}
        record_sizes = {}
        payload_bytes = 0

        def candidate_rank(identity, record, result):
            return (not bool(result.lines), *album_rank(record, track)[:2],
                    not result.has_word_timing, not bool(record.get("instrumental")),
                    not bool(record.get("plainLyrics")), str(identity))

        def add(record):
            nonlocal payload_bytes
            if not recording_match(record, track):
                return
            album = record.get("albumName")
            identity = record_id(record) or (record["trackName"], record["artistName"],
                                              album if isinstance(album, str) else "", float(record["duration"]))
            if identity in records_by_key:
                return
            size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
            if size > MAX_LYRICS_RESPONSE_BYTES:
                return
            try:
                result = self.result_for(record)
            except (LyricsLimitError, ValueError, TypeError):
                return
            worst = None
            if len(records_by_key) >= MAX_CHOICES:
                worst = max(records_by_key, key=lambda key:
                            candidate_rank(key, records_by_key[key], parsed[key]))
                if candidate_rank(identity, record, result) >= candidate_rank(worst, records_by_key[worst], parsed[worst]):
                    return
            released = record_sizes[worst] if worst is not None else 0
            if payload_bytes - released + size > MAX_LYRICS_RESPONSE_BYTES:
                return
            if worst is not None:
                payload_bytes -= record_sizes.pop(worst)
                del records_by_key[worst]
                del parsed[worst]
            payload_bytes += size
            records_by_key[identity] = record
            parsed[identity] = result
            record_sizes[identity] = size

        for variant in title_search_variants(track.title)[:3]:
            if self.obsolete(generation):
                return None
            records = self.request("search", {"track_name": variant, "artist_name": track.artist}) or []
            if self.obsolete(generation):
                return None
            if isinstance(records, list):
                eligible = [item for item in records[:MAX_SEARCH_RECORDS] if recording_match(item, track)]
                for record in sorted(eligible, key=lambda item: album_rank(item, track)):
                    add(record)
            if not all_choices and any(item.lines for item in parsed.values()):
                break
        if not any(item.lines for item in parsed.values()):
            if self.obsolete(generation):
                return None
            params = {"track_name": track.title, "artist_name": track.artist}
            if track.album:
                params["album_name"] = track.album
            if 1 <= track.duration <= 3600:
                params["duration"] = round(track.duration, 3)
            add(self.request("get", params))
            if self.obsolete(generation):
                return None
        ordered = sorted(records_by_key, key=lambda key:
                         candidate_rank(key, records_by_key[key], parsed[key]))
        pairs = [(records_by_key[key], parsed[key]) for key in ordered]
        # Only the current recording's alternatives are retained: no growing
        # catalogue cache of raw lyric responses across a listening session.
        self.choice_key = self.track_key(track)
        self.choice_records = {record_id(record): record for record, _ in pairs if record_id(record)}
        return pairs

    @Slot(object, int)
    def list_choices(self, track, generation):
        if self.obsolete(generation):
            return
        if time.monotonic() < self.retry_after:
            self.choices_ready.emit(generation, [])
            return
        try:
            pairs = self.collect(track, generation, all_choices=True)
            if pairs is None or self.obsolete(generation):
                return
            choices = [candidate_metadata(record, lyrics) for record, lyrics in pairs if record_id(record)]
        except Exception:
            log.exception("Lyrics alternatives lookup failed")
            choices = []
        if not self.obsolete(generation):
            self.choices_ready.emit(generation, choices)

    @Slot(object, int, str)
    def select_candidate(self, track, generation, identity):
        if self.obsolete(generation):
            return
        record = self.choice_records.get(str(identity)) if self.choice_key == self.track_key(track) else None
        if not record or not recording_match(record, track):
            result = Lyrics(message="That lyrics choice is no longer available. Open Wrong lyrics again.")
        else:
            try:
                result = self.result_for(record)
                result.candidates = [candidate_metadata(item, self.result_for(item))
                                     for item in self.choice_records.values()]
            except (LyricsLimitError, ValueError, TypeError):
                result = Lyrics(message="That lyrics choice could not be loaded. Try another version.")
        if not self.obsolete(generation):
            self.ready.emit(generation, result)

    def trim_cache(self):
        while len(self.cache) > 80:
            self.cache.pop(next(iter(self.cache)))

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
        key = self.track_key(track)
        if key in self.cache:
            self.ready.emit(generation, self.cache[key])
            return
        if time.monotonic() < self.retry_after:
            self.ready.emit(generation, Lyrics(message="Lyrics service is busy. Try again shortly."))
            return
        try:
            pairs = self.collect(track, generation)
            if pairs is None or self.obsolete(generation):
                return
            record, result = pairs[0] if pairs else (None, self.result_for(None))
            result.candidates = [candidate_metadata(item, lyrics) for item, lyrics in pairs if record_id(item)]
            if result.lines or (record and record.get("instrumental")):
                self.cache[key] = result
            self.trim_cache()
        except LyricsLimitError as error:
            result = Lyrics(message=str(error))
        except HTTPError as error:
            log.warning("Lyrics service returned HTTP %s", error.code)
            result = Lyrics(message="Lyrics service is temporarily unavailable. Use Retry lyrics in a moment."
                            if error.code in (429, 503) else "Lyrics lookup failed. Try again or import an .lrc file.")
        except Exception:
            log.exception("Lyrics lookup failed")
            result = Lyrics(message="Couldn't reach the lyrics service. Check your connection or import an .lrc file.")
        if not self.obsolete(generation):
            self.ready.emit(generation, result)
