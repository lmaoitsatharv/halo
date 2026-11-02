"""Place known lyric words on model output, with hindsight for saved timing or live on a first listen.

Standard CTC: each token is held on "ink" (it is being emitted) or "gap" (a blank followed it), so the
same letter twice in a row, as in "falling", needs a blank between its two copies.
"""
from dataclasses import dataclass
import zlib

import numpy as np

from .models import lyric_word_matches
from .word_model import BLANK, HOP_SECONDS, STRIDE, encode, spell

KEPT, FROM_GAP, FROM_INK = 0, 1, 2
STEP_SECONDS = HOP_SECONDS * STRIDE
# Hindsight places words this many seconds late, measured on songs kept apart from the scoring songs.
SAVED_CORRECTION = .097
SPELLABLE_SHARE = .6
FEWEST_FRAMES_PER_TOKEN, MOST_FRAMES_PER_TOKEN = 1.5, 30.
# A line beats scrambled copies of its own letters by this much per token, as a median over three
# neighbouring lines, in 62% of real lines and 10% of wrong ones on the tuning songs.
TRUSTED_EVIDENCE = .55
# A line that fits no better than scrambled letters is never kept, however good its neighbours are.
LEAST_LINE_EVIDENCE = 0.
EVIDENCE_LINES = 3
SCRAMBLES = 2


@dataclass(frozen=True)
class Live:
    """Live tracking choices, tuned on songs that are never used to report its score."""
    sharpness: float = .4
    threshold: float = .1
    late: float = 1.1
    eager: float = .5
    skip: float = .02


def _distinct(tokens):
    """Whether each state's token differs from the one before, so it can follow straight on."""
    return np.concatenate(([False], tokens[1:] != tokens[:-1]))


def _start(count):
    ink, gap = np.full(count + 1, -np.inf), np.full(count + 1, -np.inf)
    gap[0] = 0.
    return ink, gap


def _step(ink, gap, frame, tokens, distinct):
    """One frame's move. Returns the new states and where each new state's score came from."""
    kept, gapped = ink[1:], gap[:-1]
    direct = np.where(distinct, ink[:-1], -np.inf)
    best = np.maximum(np.maximum(kept, gapped), direct)
    source = np.where(best == kept, KEPT, np.where(best == gapped, FROM_GAP, FROM_INK))
    next_ink = np.concatenate(([-np.inf], frame[tokens] + best))
    next_gap = frame[BLANK] + np.maximum(gap, ink)
    return next_ink, next_gap, source, ink > gap


def viterbi(log_probs, tokens):
    """The frame each token first appears, using the whole clip. Tokens must fit, at one frame each."""
    tokens = np.asarray(tokens)
    frames, count = len(log_probs), len(tokens)
    if frames < count:
        raise ValueError("Too few frames for these tokens")
    distinct = _distinct(tokens)
    ink, gap = _start(count)
    ink_source = np.zeros((frames, count), np.int8)
    gap_source = np.zeros((frames, count + 1), bool)
    for t in range(frames):
        ink, gap, ink_source[t], gap_source[t] = _step(ink, gap, log_probs[t], tokens, distinct)
    first = np.zeros(count, int)
    state, on_ink = count, bool(ink[count] > gap[count])
    for t in range(frames - 1, -1, -1):
        if on_ink:
            source = ink_source[t, state - 1]
            if source != KEPT:
                first[state - 1] = t
                state -= 1
                on_ink = bool(source == FROM_INK)
        else:
            on_ink = bool(gap_source[t, state])
    return first


class PaceFollower:
    """A running belief over which token is being sung, for the first listen.

    Entering a token takes hearing that token, so a word opens when its first sound arrives. A
    deadline counted from the last word opened, at the song's pace, moves on if a start is
    missed, so nothing can stall, and each new line starts fresh.
    """
    def __init__(self, tokens, starts, frames_per_token, wait_frames, settings=Live()):
        self.tokens = np.asarray(tokens)
        self.starts = np.asarray(starts) + 1
        self.settings = settings
        self.pace, self.wait = max(1., frames_per_token), max(1., wait_frames)
        count = len(tokens)
        self.leave = np.full(count + 1, settings.eager)
        self.leave[count] = 0.
        self.belief = np.zeros(count + 1)
        self.belief[0] = 1.
        self.opened = 0
        self.frames = 0
        self.anchor_frame, self.anchor_state = self.wait, 0

    def _open(self, state):
        self.opened += 1
        self.anchor_frame, self.anchor_state = self.frames, state

    def step(self, frame):
        """Take one frame of log probabilities. Returns how many words have started."""
        probs = np.exp(frame) ** self.settings.sharpness
        blank = np.exp(frame[BLANK]) ** self.settings.sharpness
        entering = probs[self.tokens]
        staying = blank + np.concatenate(([0.], entering))
        moved = self.belief * self.leave
        belief = (self.belief - moved) * staying
        belief[1:] += moved[:-1] * entering * (1 - self.settings.skip)
        belief[2:] += moved[:-2] * entering[1:] * self.settings.skip
        self.belief = belief / belief.sum()
        self.frames += 1
        reached = np.cumsum(self.belief[::-1])[::-1]
        while self.opened < len(self.starts) and reached[self.starts[self.opened]] >= self.settings.threshold:
            self._open(self.starts[self.opened])
        while self.opened < len(self.starts):
            state = self.starts[self.opened]
            if self.frames < self.anchor_frame + (state - self.anchor_state) * self.pace * self.settings.late:
                break
            self.belief[state] += self.belief[:state].sum()
            self.belief[:state] = 0.
            self._open(state)
        return self.opened


@dataclass(frozen=True)
class LinePlan:
    """What to listen for in a line: tokens, each tracked word's first token, and its place in the line."""
    tokens: tuple
    starts: tuple
    word_indexes: tuple
    word_count: int


@dataclass(frozen=True)
class PlacedLine:
    """Start seconds for every word of a line, its pace in frames per token, and its evidence."""
    starts: tuple
    pace: float
    evidence: float


def line_plan(text):
    """The listening plan for a line, or None when too little of it can be spelled."""
    words = [spell(match.group()) for match in lyric_word_matches(text)]
    tracked = [(index, spelled[0]) for index, spelled in enumerate(words) if spelled]
    if not tracked or len(tracked) < SPELLABLE_SHARE * len(words):
        return None
    tokens, starts = encode([word for _, word in tracked])
    return LinePlan(tuple(tokens), tuple(starts), tuple(index for index, _ in tracked), len(words))


def _path_score(log_probs, tokens):
    distinct = _distinct(tokens)
    ink, gap = _start(len(tokens))
    for frame in log_probs:
        ink, gap, _, _ = _step(ink, gap, frame, tokens, distinct)
    return float(max(ink[-1], gap[-1]))


def line_evidence(log_probs, tokens):
    """How much better a line fits the audio than the same letters scrambled, per token.

    A free alignment can fit almost any words, so an absolute score says little. Scrambling keeps
    the letters and length, which also cancels the song's loudness and mix.
    """
    tokens = np.asarray(tokens)
    chooser = np.random.default_rng(zlib.crc32(tokens.tobytes()))
    scrambled = [np.concatenate((tokens[:1], chooser.permutation(tokens[1:-1]), tokens[-1:])) for _ in range(SCRAMBLES)]
    return (_path_score(log_probs, tokens) - float(np.mean([_path_score(log_probs, row) for row in scrambled]))) / len(tokens)


def trusted_lines(evidence):
    """Which line numbers to keep: one line carries too little evidence, so each is judged with its neighbours."""
    numbers = sorted(evidence)
    scores = [evidence[number] for number in numbers]
    if len(scores) < EVIDENCE_LINES:
        return set()
    trusted = set()
    for k, number in enumerate(numbers):
        start = min(max(0, k - EVIDENCE_LINES // 2), len(scores) - EVIDENCE_LINES)
        if scores[k] > LEAST_LINE_EVIDENCE and np.median(scores[start:start + EVIDENCE_LINES]) >= TRUSTED_EVIDENCE:
            trusted.add(number)
    return trusted


def place_line(log_probs, plan, first_frame_time):
    """Word starts with hindsight, or None if the spacing could not be singing."""
    if len(log_probs) < len(plan.tokens):
        return None
    first = viterbi(log_probs, plan.tokens)
    spacing = float(np.median(np.diff(first)))
    if not FEWEST_FRAMES_PER_TOKEN <= spacing <= MOST_FRAMES_PER_TOKEN:
        return None
    times = np.maximum(0., first_frame_time + first[list(plan.starts)] * STEP_SECONDS - SAVED_CORRECTION)
    starts = np.interp(range(plan.word_count), plan.word_indexes, times)
    pace = (first[-1] - first[0]) / max(1, len(plan.tokens) - 1)
    return PlacedLine(tuple(float(start) for start in starts), float(np.clip(pace, 1, MOST_FRAMES_PER_TOKEN)),
                      line_evidence(log_probs, plan.tokens))
