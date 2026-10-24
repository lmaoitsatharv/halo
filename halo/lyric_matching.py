"""Conservative recording identity and presentation for the lyrics catalogue."""
import math
import re
from .models import eligible_match, normalize_name


# These change the performance/edit, unlike a compilation or deluxe album name.
_VERSIONS = {
    "live": r"\blive\b", "acoustic": r"\bacoustic\b|\bunplugged\b",
    "remix": r"\bremix(?:ed)?\b", "karaoke": r"\bkaraoke\b",
    "instrumental": r"\binstrumental\b", "radio edit": r"\bradio\s+(?:edit|version)\b",
    "edit": r"\bedit(?:ed)?\b", "cover": r"\bcover(?:s)?\b|\btribute\b",
    "extended": r"\bextended\b", "slowed": r"\bslowed\b",
    "sped up": r"\bsped\s*up\b|\bspeed\s*up\b",
}


def version_labels(title, album=""):
    title = title if isinstance(title, str) else ""
    album = album if isinstance(album, str) else ""
    # Album-level Live At/From/In and explicit bracketed labels are reliable
    # hints; arbitrary words in album names (e.g. Live Through This) are not.
    album_tags = " ".join(re.findall(r"[\[(]([^\])]+)[\])]", album))
    if re.search(r"\blive\s+(?:at|from|in)\b", album, re.I) or album.casefold().strip() == "live":
        album_tags += " live"
    if album.casefold().strip() in {"acoustic", "unplugged", "instrumental", "karaoke"}:
        album_tags += " " + album
    # A song called Live Forever is not itself a live-performance label.
    title_tags = " ".join(re.findall(r"[\[(]([^\])]+)[\])]", title))
    title_tags += " " + " ".join(re.split(r"\s+[–—-]\s+", title)[1:])
    text = title_tags + " " + album_tags
    return frozenset(name for name, pattern in _VERSIONS.items() if re.search(pattern, text, re.I))


def recording_match(record, track):
    """Every lookup route must pass the same artist/title/duration/version gate."""
    try:
        if not isinstance(track.duration, (int, float)) or not math.isfinite(track.duration) or track.duration < 0:
            return False
        if isinstance(record, dict) and isinstance(record.get("duration"), bool):
            return False
        return (eligible_match(record, track)
                and version_labels(record.get("trackName"), record.get("albumName"))
                == version_labels(track.title, track.album))
    except (TypeError, ValueError, OverflowError):
        return False


def record_id(record):
    value = record.get("id")
    if isinstance(value, bool):
        return ""
    text = str(value)
    return text if text.isascii() and text.isdecimal() and 0 < len(text) <= 18 and int(text) > 0 else ""


def album_rank(record, track):
    album = record.get("albumName")
    album = album if isinstance(album, str) else ""
    exact = bool(track.album) and normalize_name(album) == normalize_name(track.album)
    duration = float(record["duration"])
    delta = abs(duration - track.duration) if track.duration and math.isfinite(track.duration) else 0
    return (not exact, delta, record_id(record))


def candidate_metadata(record, lyrics):
    def clean(key):
        value = record.get(key)
        return value[:500] if isinstance(value, str) else ""
    return {"id": record_id(record), "title": clean("trackName"), "artist": clean("artistName"),
            "album": clean("albumName"), "duration": float(record["duration"]),
            "timed": bool(lyrics.lines),
            "word_synced": any(bool(getattr(line, "words", ())) for line in lyrics.lines),
            "preview": " / ".join(line.text for line in lyrics.lines[:2])[:200]}
