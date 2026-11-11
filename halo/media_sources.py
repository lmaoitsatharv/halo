"""Any player that reports to Windows' media controls: which one Halo follows, and what it is called.

Spotify, a browser tab (Spotify or Apple Music on the web, YouTube, YouTube Music) and music apps all
publish a media session. Halo follows the one that is playing, holds on to it while another also plays,
and cleans up a video's title so the lyric lookup sees the song rather than the upload.
"""
import re

HOLD = 1.5  # seconds a followed player may stop reporting "playing" (a skip, a buffer) before another takes over

_NAMES = (
    ("spotify", "Spotify"), ("applemusic", "Apple Music"), ("itunes", "iTunes"),
    ("zunemusic", "Media Player"), ("brave", "Brave"), ("msedge", "Edge"), ("chromium", "Chromium"),
    ("chrome", "Chrome"), ("firefox", "Firefox"), ("308046b0af4a39cb", "Firefox"), ("vivaldi", "Vivaldi"),
    ("opera", "Opera"), ("thebrowsercompany", "Arc"), ("tidal", "TIDAL"), ("deezer", "Deezer"),
    ("amazonmusic", "Amazon Music"), ("vlc", "VLC"), ("foobar2000", "foobar2000"), ("musicbee", "MusicBee"),
)
_BROWSERS = {"Brave", "Edge", "Chrome", "Chromium", "Firefox", "Vivaldi", "Opera", "Arc"}

# Words in a video title that describe the upload, not the song.
_NOISE = (r"official(?:\s+(?:music|lyrics?|hd|4k))?\s*(?:video|audio|visuali[sz]er|mv)?|"
          r"(?:music|lyrics?|lyrical|full|hd|4k)\s+(?:video|audio)(?:\s+song)?|"
          r"(?:full\s+)?(?:video|audio)\s+song|full\s+song|lyrics?|visuali[sz]er|audio|video|"
          r"m/?v|hd|hq|4k|uhd|1080p|720p|explicit|clean")
_NOISE_BRACKET = re.compile(r"\s*[\[(【「]\s*(?:" + _NOISE + r")(?:\s*[&/+|,]\s*(?:" + _NOISE + r"))*\s*[\])】」]",
                            re.I)
# Unbracketed, only whole phrases are dropped, so a song called "Video Games" or "Clean" keeps its name.
_TAIL = (r"official\s+(?:music\s+|lyrics?\s+)?(?:video|audio)|(?:official\s+)?lyric(?:s|al)?\s+video|"
         r"full\s+(?:video\s+|audio\s+)?song|(?:video|audio)\s+song|hd|hq|4k|uhd|1080p|720p")
_NOISE_TAIL = re.compile(r"(?:\s+(?:" + _TAIL + r"))+\s*$", re.I)
_FEATURING = re.compile(r"\s*[(\[]?\s*\b(?:feat\.?|ft\.?|featuring)\s+[^)\]]*[)\]]?\s*$", re.I)
_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_VERSION = re.compile(r"\b(?:remaster(?:ed)?|live|remix|mix|edit|version|acoustic|mono|stereo|demo|"
                      r"instrumental|unplugged|session|reprise|slowed|sped|extended|radio)\b", re.I)


def source_name(app_id):
    """The everyday name of the app behind a Windows media session."""
    folded = (app_id or "").casefold()
    if not folded:
        return "your player"
    for needle, name in _NAMES:
        if needle in folded:
            return name
    base = re.split(r"[!_]", app_id)[0]
    base = re.sub(r"\.exe$", "", base, flags=re.I)
    return base.split(".")[-1] or "your player"


def is_browser(app_id):
    return source_name(app_id) in _BROWSERS


def _squash(text):
    return re.sub(r"\W+", "", text or "").casefold()


def _channel(artist):
    """A video channel's name as an artist: no " - Topic", no VEVO, and words split back apart."""
    name = re.sub(r"\s+-\s+Topic\s*$", "", artist or "", flags=re.I).strip()
    if name.endswith("VEVO") and len(name) > 4:
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name[:-4]).strip()
    return name


def clean_metadata(title, artist, album, browser):
    """(title, artist) for the lyric lookup and the wall.

    Only a browser session without an album is treated as a video upload. Spotify or Apple Music
    on the web and YouTube Music send an album with proper song details, so they are left alone.
    """
    title, artist = title or "", artist or ""
    if not browser:
        return title, artist
    channel = _channel(artist)
    if album:
        return title, channel or artist
    song = title.split(" | ")[0].split("｜")[0]
    song = _NOISE_BRACKET.sub("", song)
    song = _FEATURING.sub("", song)
    song = _NOISE_TAIL.sub("", song).strip(" -–—")
    parts = _SEPARATOR.split(song, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        left, right = parts
        if _squash(left) and _squash(left) in (_squash(channel), _squash(artist)):
            song, channel = right, left
        elif not _VERSION.search(right):
            # A video's own title is usually "Artist - Song", whoever uploaded it.
            song, channel = right, left
    song = _NOISE_TAIL.sub("", _FEATURING.sub("", song)).strip()
    if not song:
        return title, channel or artist
    return song, channel or artist


class SessionChooser:
    """Follow whatever is playing; never flick between two players that play at once."""

    def __init__(self, hold=HOLD):
        self.hold = hold
        self.followed = None
        self.playing_at = None

    def choose(self, sessions, current, now):
        """sessions maps app id to whether it is playing; current is Windows' own pick, if any."""
        followed = self.followed if self.followed in sessions else None
        if followed and sessions[followed]:
            self.playing_at = now
            return followed
        playing = [app for app, is_playing in sessions.items() if is_playing]
        held = followed and self.playing_at is not None and now - self.playing_at < self.hold
        if playing and not held:
            choice = current if current in playing else playing[0]
            self.followed, self.playing_at = choice, now
            return choice
        if followed:
            return followed
        choice = current if current in sessions else next(iter(sessions), None)
        self.followed, self.playing_at = choice, (now if choice and sessions[choice] else None)
        return choice
