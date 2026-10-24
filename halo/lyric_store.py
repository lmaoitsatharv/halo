"""Small, bounded local records for a listener's explicit lyric corrections."""
from dataclasses import asdict
from itertools import islice
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import unicodedata

from .models import Lyrics, LyricLine, validate_lyric_lines, MAX_LYRIC_WORDS

MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 512
MAX_OFFSET_MS = 10_000


def recording_key(track):
    """Unknown duration never shares a correction with a known recording."""
    if (not track.connected or not track.title or not track.artist
            or not math.isfinite(track.duration) or not 1 <= track.duration <= 86400):
        return None
    def clean(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return [clean(track.title), clean(track.artist), clean(track.album), round(track.duration)]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid lyric timestamp.")
    if not -60 <= value <= 86400:
        raise ValueError("Lyric timestamps are out of range.")
    return float(value)


def lyrics_to_data(lyrics):
    validate_lyric_lines(lyrics.lines)
    return {"lines": [asdict(line) for line in lyrics.lines],
            "message": str(lyrics.message)[:500], "source_id": str(getattr(lyrics, "source_id", ""))[:100],
            "selected_record": getattr(lyrics, "selected_record", {})}


def lyrics_from_data(data):
    from .models import LyricWord
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise ValueError("Invalid saved lyrics.")
    if not 1 <= len(data["lines"]) <= 2000:
        raise ValueError("Invalid saved lyric count.")
    lines, word_count, previous = [], 0, -math.inf
    for item in data["lines"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("Invalid saved lyric line.")
        start = _number(item.get("time"))
        if start < previous:
            raise ValueError("Saved lyrics are out of order.")
        previous = start
        end = None if item.get("end") is None else _number(item["end"])
        if end is not None and end < start:
            raise ValueError("Invalid saved line end.")
        raw_words = item.get("words", [])
        if not isinstance(raw_words, (list, tuple)) or len(raw_words) > 256:
            raise ValueError("Invalid saved words.")
        words, previous_word = [], -math.inf
        for raw in raw_words:
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or len(raw["text"]) > 2000:
                raise ValueError("Invalid saved word.")
            a = _number(raw.get("start"))
            b = None if raw.get("end") is None else _number(raw["end"])
            # Preserve the parser's source intervals, including overlapping
            # vocals whose first segment precedes its parent's line cue.
            if a < previous_word or (b is not None and b < a):
                raise ValueError("Invalid saved word order.")
            previous_word = a
            words.append(LyricWord(raw["text"], a, b))
        word_count += len(words)
        if word_count > MAX_LYRIC_WORDS:
            raise ValueError("Too many saved lyric words.")
        lines.append(LyricLine(start, item["text"], tuple(words), end))
    validate_lyric_lines(lines)
    selected = data.get("selected_record", {})
    if not isinstance(selected, dict):
        raise ValueError("Invalid saved source.")
    return Lyrics(lines, str(data.get("message", "Saved timed lyrics"))[:500],
                  source_id=str(data.get("source_id", ""))[:100], selected_record=selected)


class LyricStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, key):
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()
        return self.directory / (digest + ".json")

    def load(self, track):
        key = recording_key(track)
        if key is None:
            return {}
        try:
            with self._path(key).open("rb") as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                return {}
            data = json.loads(raw)
            if data.get("version") != 1 or data.get("recording") != key:
                return {}
            offset = data.get("offset", 0)
            if isinstance(offset, bool) or not isinstance(offset, int) or abs(offset) > MAX_OFFSET_MS:
                return {}
            result = {"offset": offset}
            if data.get("lyrics") is not None:
                result["lyrics"] = lyrics_from_data(data["lyrics"])
                result["kind"] = "imported" if data.get("kind") == "imported" else "selected"
            return result
        except (OSError, ValueError, TypeError, KeyError, RecursionError, AttributeError):
            return {}

    def save(self, track, offset, lyrics=None, kind="selected"):
        key = recording_key(track)
        if key is None:
            raise ValueError("Wait for Spotify to provide the song and its duration before saving lyrics.")
        offset = int(offset)
        if abs(offset) > MAX_OFFSET_MS:
            raise ValueError("Keep the song correction within 10 seconds.")
        document = {"version": 1, "recording": key, "offset": offset,
                    "lyrics": lyrics_to_data(lyrics) if lyrics is not None else None, "kind": kind}
        # Validate before touching the previous, known-good file.
        if lyrics is not None:
            lyrics_from_data(document["lyrics"])
        raw = json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("These lyrics are too large to save safely.")
        destination = self._path(key)
        if lyrics is None and offset == 0:
            destination.unlink(missing_ok=True)
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        if not destination.exists() and sum(1 for _ in islice(self.directory.glob("*.json"), MAX_RECORDS)) >= MAX_RECORDS:
            raise ValueError("The saved lyric library is full. Remove an older saved correction before adding another.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".lyrics-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def clear_lyrics(self, track, offset=0):
        key = recording_key(track)
        if key is not None:
            self.save(track, offset)
