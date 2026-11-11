"""When each word of a line is probably sung, for lyrics that only say when lines start.

A line's slot runs to the next line, but the singer has usually finished before then, so spreading
the words across the whole slot places them late. A song's fullest lines show its real pace, and
that pace says when the singing in every other line ends.

Tuned on 40 hand-timed songs and scored on 39 others (JamendoLyrics, four languages): the typical
error fell from 263 ms to 154 ms and the mean from 694 ms to 296 ms. Knowing exactly when each
line's singing ends would only reach about 120 to 140 ms, so this is near what can be done
without listening.
"""
import re
import unicodedata

PACE_QUANTILE = .75   # the song's pace is that of a line fuller than three quarters of its lines
SUNG_TAIL = 1.2       # a line runs this much longer than its pace alone says: breaths and held notes
LAST_HOLD = 2.        # the last word of a line is held about twice as long as the others
LETTER_UNITS = .15    # each letter adds a little to a word's syllables: "strengths" outlasts "to"
DEFAULT_PACE = 4.2    # units a second, the typical pace of the tuning songs, for songs too short to judge
FEWEST_LINES = 3
SHORTEST_SLOT = .3

_VOWELS = re.compile(r"[aeiouyàâäáãåæèéêëìíîïòóôöõøœùúûüýÿ]+", re.I)
_VIRAMA = 9  # the combining class of the sign that joins two consonants into one beat


def syllables(word):
    """Roughly how many beats a word takes to sing, in any script."""
    core = re.sub(r"[^\w']", "", word.lower())
    groups = _VOWELS.findall(core)
    count = len(groups)
    if count:
        # A final "e" is usually silent in English: "make", "fire", but not "little" or "see".
        if count > 1 and core.endswith("e") and not core.endswith(("le", "ee", "ye")) and len(groups[-1]) == 1:
            count -= 1
        return count
    # Joining signs are not word characters, so they are read from the word as written.
    for character in word:
        category = unicodedata.category(character)
        if category in ("Lo", "Nd"):
            count += 1
        elif unicodedata.combining(character) == _VIRAMA:
            count -= 1
    return max(1, count)


def word_units(word):
    """A word's share of its line: its syllables, plus a little for each letter."""
    return syllables(word) + LETTER_UNITS * sum(character.isalnum() for character in word)


def song_pace(lines):
    """Units a second when the singer fills a line, from (words, start, end) for each untimed line."""
    rates = sorted(sum(word_units(word) for word in words) / (end - start)
                   for words, start, end in lines if end - start > SHORTEST_SLOT and len(words) >= 2)
    if len(rates) < FEWEST_LINES:
        return DEFAULT_PACE
    return rates[min(len(rates) - 1, int(PACE_QUANTILE * len(rates)))]


def paced_spans(words, start, end, pace):
    """(begin, finish) for each word: sung at the song's pace from the line's start, never past its slot."""
    if not words:
        return []
    units = [word_units(word) for word in words]
    slot = max(.04, end - start)
    sung = min(slot, sum(units) / pace * SUNG_TAIL) if pace > 0 else slot
    units[-1] *= LAST_HOLD
    total = sum(units)
    edges, passed = [start], 0.
    for unit in units[:-1]:
        passed += unit
        edges.append(start + sung * passed / total)
    edges.append(start + sung)
    return list(zip(edges, edges[1:]))


def estimated_words(lines, duration=0):
    """Each line's word matches and their (begin, finish) spans at the song's pace.

    Returns (matches, spans) per line. spans is None for a line that carries its own word timing,
    and empty for a line with no words. The display and the word timer both read this, so
    learning starts from exactly the times that are shown.
    """
    from .models import lyric_word_matches

    def slot_end(i):
        return (lines[i].end if lines[i].end is not None else
                lines[i + 1].time if i + 1 < len(lines) else max(lines[i].time + 4, duration))
    # A language without spaces still gets expressive, legible word flow.
    matched = [lyric_word_matches(line.text) for line in lines]
    pace = song_pace([([match.group() for match in matches], line.time, slot_end(i))
                      for i, (line, matches) in enumerate(zip(lines, matched)) if matches and not line.words])
    return [(matches, None if line.words else paced_spans([match.group() for match in matches], line.time, slot_end(i), pace))
            for i, (line, matches) in enumerate(zip(lines, matched))]
