"""Bounded Lyricsfile 1.0 and Enhanced LRC imports, with legacy fallbacks.

Format source: https://github.com/tranxuanthang/lyricsfile/blob/main/SPECIFICATION.md
Lyricsfile is a draft. Its unresolved metadata.offset_ms is not applied.
"""
from pathlib import Path
import math

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode

from .models import (Lyrics, LyricLine, LyricWord, LyricsLimitError, parse_lrc,
                     validate_lyric_lines, MAX_LRC_BYTES, MAX_LYRIC_CUES,
                     MAX_LYRIC_WORDS_PER_LINE, MAX_LYRIC_LINE_CHARS,
                     MAX_LYRIC_WORDS, MAX_LYRIC_EXPANDED_CHARS, lyric_word_matches)


MAX_YAML_DEPTH = 12
MAX_YAML_NODES = 140_000


class LyricsFormatError(ValueError):
    """A file is not supported synchronized lyrics, rather than a size failure."""


class _BoundedLoader(yaml.SafeLoader):
    """Reject expansion and deep structures before constructing Python objects."""
    def __init__(self, stream):
        super().__init__(stream)
        self._depth = self._nodes = 0

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None) or getattr(event, "tag", None):
            raise LyricsFormatError("Lyricsfile tags, anchors and aliases are unsupported.")
        self._nodes += 1
        self._depth += 1
        try:
            if self._nodes > MAX_YAML_NODES or self._depth > MAX_YAML_DEPTH:
                raise LyricsLimitError()
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):
            raise LyricsFormatError("Expected a Lyricsfile mapping.")
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise LyricsFormatError("Lyricsfile keys must be unique strings.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _bounded_text(text):
    if (not isinstance(text, str) or len(text) > MAX_LRC_BYTES or
            len(text.encode("utf-8")) > MAX_LRC_BYTES):
        raise LyricsLimitError()
    return text.lstrip("\ufeff")


def _plain_yaml_types(value):
    if isinstance(value, dict):
        for item in value.values():
            _plain_yaml_types(item)
    elif isinstance(value, list):
        for item in value:
            _plain_yaml_types(item)
    elif type(value) not in (str, int, bool, type(None)):
        raise LyricsFormatError("Unsupported Lyricsfile value type.")


def _milliseconds(value):
    if type(value) is not int or value < 0:
        raise LyricsFormatError("Lyricsfile timestamps must be nonnegative integer milliseconds.")
    try:
        seconds = value / 1000
    except OverflowError as error:
        raise LyricsFormatError("Invalid Lyricsfile timestamp.") from error
    if not math.isfinite(seconds):
        raise LyricsFormatError("Invalid Lyricsfile timestamp.")
    return seconds


def _interval(item):
    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        raise LyricsFormatError("Lyricsfile lines and segments need text and a start time.")
    start = _milliseconds(item.get("start_ms"))
    end = _milliseconds(item["end_ms"]) if "end_ms" in item else None
    if end is not None and end < start:
        raise LyricsFormatError("Lyricsfile end precedes its start.")
    return start, end


def parse_lyricsfile(text):
    """Read the official Lyricsfile 1.0 draft's millisecond line/word timings."""
    loader = _BoundedLoader(_bounded_text(text))
    try:
        document = loader.get_single_data()
    except yaml.YAMLError as error:
        raise LyricsFormatError("Invalid Lyricsfile YAML.") from error
    finally:
        loader.dispose()
    _plain_yaml_types(document)
    if not isinstance(document, dict) or document.get("version") != "1.0":
        raise LyricsFormatError("Only Lyricsfile version 1.0 is supported.")
    metadata = document.get("metadata")
    if (not isinstance(metadata, dict) or not isinstance(metadata.get("title"), str)
            or not isinstance(metadata.get("artist"), str)):
        raise LyricsFormatError("Lyricsfile metadata needs a title and artist.")
    if "duration_ms" in metadata:
        _milliseconds(metadata["duration_ms"])
    if "offset_ms" in metadata and type(metadata["offset_ms"]) is not int:
        raise LyricsFormatError("Lyricsfile offset must be integer milliseconds.")
    if "instrumental" in metadata and type(metadata["instrumental"]) is not bool:
        raise LyricsFormatError("Lyricsfile instrumental flag must be boolean.")
    raw_lines = document.get("lines", [])
    if not isinstance(raw_lines, list):
        raise LyricsFormatError("Lyricsfile lines must be a sequence.")
    if len(raw_lines) > MAX_LYRIC_CUES:
        raise LyricsLimitError()
    if "plain" in document and not isinstance(document["plain"], str):
        raise LyricsFormatError("Lyricsfile plain lyrics must be text.")
    if metadata.get("instrumental"):
        if raw_lines or document.get("plain"):
            raise LyricsFormatError("Instrumental Lyricsfiles cannot contain vocal lyrics.")
        return Lyrics([], "This track is marked as instrumental.")
    lines = []
    total_words = total_characters = 0
    for raw in raw_lines:
        start, end = _interval(raw)
        text = raw["text"]
        if len(text) > MAX_LYRIC_LINE_CHARS:
            raise LyricsLimitError()
        segments = raw.get("words", [])
        if not isinstance(segments, list):
            raise LyricsFormatError("Lyricsfile words must be a sequence.")
        if len(segments) > MAX_LYRIC_WORDS_PER_LINE:
            raise LyricsLimitError()
        total_words += max(1, len(lyric_word_matches(text)), len(segments))
        total_characters += len(text)
        if total_words > MAX_LYRIC_WORDS or total_characters > MAX_LYRIC_EXPANDED_CHARS:
            raise LyricsLimitError()
        words = []
        segment_characters = 0
        for segment in segments:
            begin, finish = _interval(segment)
            segment_characters += len(segment["text"])
            if segment_characters > MAX_LYRIC_LINE_CHARS:
                raise LyricsLimitError()
            words.append(LyricWord(segment["text"], begin, finish))
        lines.append(LyricLine(start, text, tuple(words), end))
    lines.sort(key=lambda line: line.time)
    validate_lyric_lines(lines)
    result = Lyrics(lines)
    result.message = ("Word-synced lyrics" if result.has_word_timing else
                      "Line-synced lyrics · word timing estimated" if lines else
                      "Only untimed lyrics are available for this track.")
    return result


def parse_lyrics_record(record):
    """Prefer valid Lyricsfile data, then safely fall back to legacy syncedLyrics."""
    if not isinstance(record, dict):
        return Lyrics([], "No synced lyrics found for this track.")
    result = None
    if record.get("lyricsfile"):
        try:
            result = parse_lyricsfile(record["lyricsfile"])
        except (ValueError, TypeError, OverflowError, yaml.YAMLError):
            pass
    if result is None or not result.lines:
        try:
            lines = parse_lrc(record.get("syncedLyrics") or "")
        except (ValueError, TypeError, OverflowError):
            lines = []
        if lines:
            result = Lyrics(lines, "Word-synced lyrics" if any(line.words for line in lines)
                            else "Line-synced lyrics · word timing estimated")
    if result is None:
        message = ("This track is marked as instrumental." if record.get("instrumental") else
                   "Only untimed lyrics are available for this track." if record.get("plainLyrics") else
                   "No synced lyrics found for this track.")
        result = Lyrics([], message)
    record_id = record.get("id")
    result.source_id = str(record_id) if isinstance(record_id, (int, str)) and not isinstance(record_id, bool) else ""
    result.selected_record = {key: record[key] for key in
                              ("id", "trackName", "artistName", "albumName", "duration", "hasWordSync")
                              if key in record}
    return result


def load_lyrics_file(path):
    """Read one bounded UTF-8 Lyricsfile or ordinary/Enhanced LRC import."""
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_LRC_BYTES + 1)
    if len(data) > MAX_LRC_BYTES:
        raise LyricsLimitError()
    text = data.decode("utf-8-sig")
    if path.suffix.casefold() in (".yaml", ".yml") or text.lstrip().startswith("version:"):
        result = parse_lyricsfile(text)
    else:
        lines = parse_lrc(text)
        result = Lyrics(lines, "Imported word-synced lyrics" if any(line.words for line in lines)
                        else "Imported line-synced lyrics · word timing estimated")
    if not result.lines:
        raise LyricsFormatError("This file has no valid synchronized lyrics.")
    result.source_id = "import"
    return result
