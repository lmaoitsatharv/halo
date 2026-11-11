from dataclasses import dataclass, field
from bisect import bisect_right
from itertools import islice
from pathlib import Path
import re
import unicodedata
import math


class TimelineClock:
    """Interpolate Windows' timestamped timeline without drifting on pause/resume."""
    def __init__(self):
        self.signature = None
        self.anchor = 0.0
        self.anchor_at = 0.0
        self.playing = False

    def update(self, raw, stamp, playing, duration, now, wall_elapsed=0):
        signature = (raw, stamp)
        old_position = self.anchor + (max(0, now - self.anchor_at) if self.playing else 0)
        if signature != self.signature:
            self.anchor = raw + (max(0, wall_elapsed) if playing else 0)
            self.anchor_at = now
            self.signature = signature
        elif playing != self.playing:
            # A playback-state event may arrive before a timeline event.
            self.anchor = old_position
            self.anchor_at = now
        self.playing = playing
        position = self.anchor + (max(0, now - self.anchor_at) if playing else 0)
        return max(0, min(position, duration) if duration else position)


@dataclass
class Track:
    title: str = "Waiting for music"
    artist: str = "Play something in Spotify, a browser or any music app."
    album: str = ""
    duration: float = 0
    position: float = 0
    playing: bool = False
    connected: bool = False
    artwork: bytes = b""
    observed_at: float = 0
    source: str = ""      # the player's everyday name, such as "Spotify" or "Brave"
    browser: bool = False  # a web player, whose reported length may not be the recording's

    @property
    def key(self):
        return (self.title, self.artist, self.album)


@dataclass(frozen=True)
class LyricWord:
    text: str
    start: float
    end: float | None = None


@dataclass(frozen=True)
class LyricLine:
    time: float
    text: str
    words: tuple[LyricWord, ...] = ()
    end: float | None = None


@dataclass
class Lyrics:
    lines: list[LyricLine] = field(default_factory=list)
    message: str = "Your lyrics will appear here."
    source_id: str = ""
    candidates: list[dict] = field(default_factory=list)
    selected_record: dict = field(default_factory=dict)
    timing_source: str = ""

    @property
    def has_word_timing(self):
        return any(line.words for line in self.lines)

    def index_at(self, position: float) -> int:
        return bisect_right([line.time for line in self.lines], position) - 1


def floating_geometry(screen_rect, horizontal=50, vertical=90):
    """Position the entire overlay within the monitor's usable area."""
    sx, sy, sw, sh = screen_rect
    margin = max(0, min(20, sw // 10, sh // 10))
    width = max(1, min(860, sw - 2 * margin))
    height = max(1, min(220, sh - 2 * margin))
    x = sx + margin + round(max(0, sw - 2 * margin - width) * max(0, min(100, horizontal)) / 100)
    y = sy + margin + round(max(0, sh - 2 * margin - height) * max(0, min(100, vertical)) / 100)
    return x, y, width, height


STAMP = re.compile(r"\[(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?\]")
WORD_STAMP = re.compile(r"<(\d{1,3}):([0-5]?\d)(?:[.:](\d{1,3}))?>")

MAX_LRC_BYTES = 512 * 1024
MAX_LYRIC_CUES = 2000
MAX_TIMESTAMPS_PER_LINE = 32
MAX_LYRIC_LINE_CHARS = 2000
MAX_LYRIC_WORDS_PER_LINE = 256
MAX_LYRIC_WORDS = 20_000
MAX_LYRIC_EXPANDED_CHARS = 250_000


class LyricsLimitError(ValueError):
    def __init__(self):
        super().__init__("These lyrics are too large or complex to display safely. Try a smaller .lrc file.")


def lyric_word_matches(text):
    if not isinstance(text, str) or len(text) > MAX_LYRIC_LINE_CHARS:
        raise LyricsLimitError()
    matches = list(islice(re.finditer(r"\S+", text), MAX_LYRIC_WORDS_PER_LINE + 1))
    if len(matches) == 1 and any("\u3400" <= ch <= "\u9fff" for ch in text):
        matches = list(islice(re.finditer(r"\S", text), MAX_LYRIC_WORDS_PER_LINE + 1))
    if len(matches) > MAX_LYRIC_WORDS_PER_LINE:
        raise LyricsLimitError()
    return matches


def validate_lyric_lines(lines):
    """Bound renderer work even when callers construct cues without the LRC parser."""
    if len(lines) > MAX_LYRIC_CUES:
        raise LyricsLimitError()
    words = characters = 0
    for line in lines:
        word_count = len(lyric_word_matches(line.text))
        if not isinstance(line.words, (tuple, list)) or len(line.words) > MAX_LYRIC_WORDS_PER_LINE:
            raise LyricsLimitError()
        if line.words:
            segment_chars = 0
            previous = -1
            for word in line.words:
                if not isinstance(word.text, str):
                    raise ValueError("Invalid timed lyric segment.")
                segment_chars += len(word.text)
                if segment_chars > MAX_LYRIC_LINE_CHARS:
                    raise LyricsLimitError()
                if (not _valid_time(word.start) or word.start < previous or
                        (word.end is not None and (not _valid_time(word.end) or word.end < word.start))):
                    raise ValueError("Invalid lyric word timestamps.")
                previous = word.start
            if "".join(word.text for word in line.words) != line.text:
                raise ValueError("Timed segments do not match their lyric line.")
        if not _valid_time(line.time) or (line.end is not None and
                (not _valid_time(line.end) or line.end < line.time)):
            raise ValueError("Invalid lyric line timestamps.")
        words += max(1, word_count, len(line.words))
        characters += len(line.text)
        if words > MAX_LYRIC_WORDS or characters > MAX_LYRIC_EXPANDED_CHARS:
            raise LyricsLimitError()


def _valid_time(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    except (ValueError, OverflowError):
        return False


def _stamp_seconds(stamp):
    fraction = float("0." + stamp.group(3)) if stamp.group(3) else 0
    return int(stamp.group(1)) * 60 + int(stamp.group(2)) + fraction


def _enhanced_content(content, line_time, shift):
    """Preserve absolute Enhanced LRC boundaries and source whitespace."""
    stamps = list(islice(WORD_STAMP.finditer(content), MAX_LYRIC_WORDS_PER_LINE + 2))
    if not stamps:
        return content, (), None
    if len(stamps) > MAX_LYRIC_WORDS_PER_LINE + 1:
        raise LyricsLimitError()
    pieces = []
    if stamps[0].start():
        pieces.append((content[:stamps[0].start()], line_time, _stamp_seconds(stamps[0])))
    for index, stamp in enumerate(stamps):
        next_stamp = stamps[index + 1] if index + 1 < len(stamps) else None
        segment = content[stamp.end():next_stamp.start() if next_stamp else len(content)]
        if segment:
            pieces.append((segment, _stamp_seconds(stamp), _stamp_seconds(next_stamp) if next_stamp else None))
    if len(pieces) > MAX_LYRIC_WORDS_PER_LINE:
        raise LyricsLimitError()
    # Match ordinary LRC's outer trimming, without discarding separators
    # between words or inventing new word boundaries.
    text = "".join(piece[0] for piece in pieces)
    left, right = len(text) - len(text.lstrip()), len(text.rstrip())
    offset = 0
    words = []
    for segment, begin, finish in pieces:
        begin_char, end_char = max(0, left - offset), min(len(segment), right - offset)
        if end_char > begin_char:
            words.append(LyricWord(segment[begin_char:end_char], begin + shift,
                                   finish + shift if finish is not None else None))
        offset += len(segment)
    end = _stamp_seconds(stamps[-1]) + shift if stamps[-1].end() == len(content) else None
    return text.strip(), tuple(words), end


def load_lrc(filename):
    with Path(filename).open("rb") as stream:
        data = stream.read(MAX_LRC_BYTES + 1)
    if len(data) > MAX_LRC_BYTES:
        raise LyricsLimitError()
    return parse_lrc(data.decode("utf-8-sig"))


def parse_lrc(text: str) -> list[LyricLine]:
    """Read ordinary or Enhanced LRC, repeated cues and global LRC offset."""
    if not isinstance(text, str) or len(text) > MAX_LRC_BYTES or len(text.encode("utf-8")) > MAX_LRC_BYTES:
        raise LyricsLimitError()
    offset = re.search(r"\[offset:([+-]?\d+)\]", text, re.I)
    shift = int(offset.group(1)) / 1000 if offset else 0
    lines = []
    words = characters = 0
    for raw in text.splitlines():
        matches = list(islice(STAMP.finditer(raw), MAX_TIMESTAMPS_PER_LINE + 1))
        if not matches:
            continue
        if len(matches) > MAX_TIMESTAMPS_PER_LINE or len(lines) + len(matches) > MAX_LYRIC_CUES:
            raise LyricsLimitError()
        content, timed_words, end = _enhanced_content(raw[matches[-1].end():].strip(),
                                                     _stamp_seconds(matches[0]), shift)
        words += len(matches) * max(1, len(lyric_word_matches(content)), len(timed_words))
        characters += len(matches) * len(content)
        if words > MAX_LYRIC_WORDS or characters > MAX_LYRIC_EXPANDED_CHARS:
            raise LyricsLimitError()
        for stamp in matches:
            seconds = _stamp_seconds(stamp) + shift
            delta = _stamp_seconds(stamp) - _stamp_seconds(matches[0])
            shifted_words = tuple(LyricWord(word.text, max(0, word.start + delta),
                                           max(0, word.end + delta) if word.end is not None else None)
                                  for word in timed_words)
            lines.append(LyricLine(max(0, seconds), content, shifted_words,
                                   max(0, end + delta) if end is not None else None))
    lines.sort(key=lambda line: line.time)
    validate_lyric_lines(lines)
    return lines


CONTRACTIONS = {
    "fallin": "falling", "goin": "going", "dancin": "dancing", "lovin": "loving",
    "livin": "living", "feelin": "feeling", "rollin": "rolling", "runnin": "running",
    "walkin": "walking", "talkin": "talking", "cryin": "crying", "flyin": "flying",
    "rockin": "rocking", "workin": "working", "waitin": "waiting", "dreamin": "dreaming",
    "thinkin": "thinking", "lookin": "looking", "callin": "calling", "leavin": "leaving",
    "comin": "coming", "gettin": "getting", "holdin": "holding", "standin": "standing",
}
COMPOUNDS = {"rain drops": "raindrops", "sun shine": "sunshine", "moon light": "moonlight",
             "some body": "somebody", "every body": "everybody", "good bye": "goodbye"}


def normalize_name(value: str) -> str:
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", value).casefold())


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"\b(" + "|".join(CONTRACTIONS) + r")\b[’']?",
                  lambda m: CONTRACTIONS[m.group(1)], text)
    return normalize_name(text)


def title_search_variants(title: str) -> list[str]:
    """Bounded spelling alternatives, never a fuzzy title/artist substitution."""
    base = title.replace("’", "'")
    for separated, joined in COMPOUNDS.items():
        base = re.sub(r"\b" + separated + r"\b", joined, base, flags=re.I)
    expanded = re.sub(r"\b(" + "|".join(CONTRACTIONS) + r")\b'?",
                      lambda m: CONTRACTIONS[m.group(1).lower()], base, flags=re.I)
    reverse = {expanded: short for short, expanded in CONTRACTIONS.items()}
    contracted = re.sub(r"\b(" + "|".join(reverse) + r")\b",
                        lambda m: reverse[m.group(1).lower()] + "'", expanded, flags=re.I)
    variants = []
    for variant in (title, expanded, contracted):
        if variant.casefold() not in {v.casefold() for v in variants}:
            variants.append(variant)
    return variants


def eligible_match(record: dict, track: Track) -> bool:
    if not isinstance(record, dict):
        return False
    title, artist = record.get("trackName"), record.get("artistName")
    if not isinstance(title, str) or not isinstance(artist, str):
        return False
    try:
        duration = float(record.get("duration"))
    except (TypeError, ValueError, OverflowError):
        return False
    # A missing catalog duration cannot establish that this is the same recording.
    return (math.isfinite(duration) and duration >= 0
            and normalize_title(title) == normalize_title(track.title)
            and normalize_name(artist) == normalize_name(track.artist)
            and (not track.duration or abs(duration - track.duration) <= 3))


def audio_energy(samples) -> float:
    import numpy as np
    if samples.size == 0:
        return 0.0
    # Preserve raw dynamics. Fixed gain clipped ordinary mastered music at 1,
    # erasing every accent before the renderer could react to it.
    return min(1.0, float(np.sqrt(np.mean(np.square(samples)))))


DEMO_LRC = """[00:00.00]Let the room fall quiet
[00:05.00]Let the colours find their way
[00:10.00]Every little sound around you
[00:15.00]Turns the edges into waves
[00:20.00]Stay a little longer
[00:25.00]In the light we made
[00:30.00]Let the room fall quiet
[00:35.00]Let the colours find their way
[00:40.00]Every little sound around you
[00:45.00]Turns the edges into waves
[00:50.00]Stay a little longer
[00:55.00]In the light we made
"""
