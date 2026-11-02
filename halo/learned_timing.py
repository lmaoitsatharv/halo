"""Word times learned from playback, kept apart from the listener's own lyric corrections.

Files hold only times, a hashed recording key and the lyric source id, never audio or lyric text.
"""
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from .lyric_store import recording_key
from .models import LyricWord, lyric_word_matches, validate_lyric_lines

MAX_SONGS = 512
MAX_FILE_BYTES = 256 * 1024


def _valid_starts(starts):
    return (isinstance(starts, list) and bool(starts)
            and all(type(start) in (int, float) and math.isfinite(start) and start >= 0 for start in starts)
            and all(a <= b for a, b in zip(starts, starts[1:])))


class LearnedStore:
    def __init__(self, directory, limit=MAX_SONGS):
        self.directory = Path(directory)
        self.limit = limit

    def _path(self, key):
        return self.directory / (hashlib.sha256(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest() + ".json")

    def _read(self, key):
        try:
            with self._path(key).open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                return None
            data = json.loads(raw)
            if data.get("version") != 1 or data.get("recording") != hashlib.sha256(str(key).encode("utf-8")).hexdigest():
                return None
            lines = {int(number): starts for number, starts in data["lines"].items()}
            return data["source"], lines if all(_valid_starts(starts) for starts in lines.values()) else None
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return None

    def load(self, track, source_id):
        key = recording_key(track)
        stored = None if key is None else self._read(key)
        return stored[1] if stored and stored[0] == source_id and stored[1] else {}

    def save(self, track, source_id, placed):
        key = recording_key(track)
        if key is None or not placed:
            return
        stored = self._read(key)
        lines = dict(stored[1]) if stored and stored[0] == source_id and stored[1] else {}
        lines.update(placed)
        document = {"version": 1, "recording": hashlib.sha256(str(key).encode("utf-8")).hexdigest(), "source": source_id,
                    "lines": {str(number): [round(float(start), 3) for start in starts] for number, starts in lines.items()}}
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".learned-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(document, allow_nan=False).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path(key))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        files = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        for path in files[:max(0, len(files) - self.limit)]:
            path.unlink(missing_ok=True)

    def forget(self, track):
        key = recording_key(track)
        if key is not None:
            self._path(key).unlink(missing_ok=True)

    def forget_all(self):
        if self.directory.exists():
            for path in self.directory.glob("*.json"):
                path.unlink(missing_ok=True)


def _timed_line(line, starts):
    matches = lyric_word_matches(line.text)
    if line.words or len(matches) != len(starts) or not _valid_starts(list(starts)):
        return None
    words = []
    for k, match in enumerate(matches):
        # Each segment runs to the next word, so the segments rebuild the line exactly.
        stop = matches[k + 1].start() if k + 1 < len(matches) else len(line.text)
        begin = 0 if k == 0 else match.start()
        finish = starts[k + 1] if k + 1 < len(starts) else None
        words.append(LyricWord(line.text[begin:stop], float(starts[k]), None if finish is None else float(finish)))
    return replace(line, words=tuple(words))


def _starting_with_its_words(line, lines, number):
    """Start the line on its first word, or the display inserts a blank step and hops over it."""
    earliest = lines[number - 1].time if number else 0.
    latest = lines[number + 1].time if number + 1 < len(lines) else math.inf
    if line.end is not None:
        latest = min(latest, line.end)
    return replace(line, time=min(max(line.words[0].start, earliest), latest))


def merge(lyrics, placed):
    """Lyrics with learned words added to lines that have no word timing."""
    lines = list(lyrics.lines)
    changed = False
    for number, starts in sorted(placed.items()):
        if 0 <= number < len(lines):
            timed = _timed_line(lines[number], starts)
            if timed is not None:
                lines[number] = _starting_with_its_words(timed, lines, number)
                changed = True
    if not changed:
        return replace(lyrics, lines=lines)
    validate_lyric_lines(lines)
    return replace(lyrics, lines=lines, timing_source="learned")
