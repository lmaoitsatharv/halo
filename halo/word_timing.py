"""Place known lyric words on model output, with hindsight, once a line has ended.

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
# The singing-trained model reports words about 12 ms later than the speech-trained one did.
SAVED_CORRECTION = .109
SPELLABLE_SHARE = .6
FEWEST_FRAMES_PER_TOKEN, MOST_FRAMES_PER_TOKEN = 1.5, 30.
# A line beats scrambled copies of its own letters by this much per token, as a median over three
# neighbouring lines. Chosen where a single line with another line's words is rejected 80% of the
# time, the level the speech-trained model's 0.55 gave; the singing-trained model scores every line
# higher, wrong words included, so its threshold is higher, and it still keeps 73% of true lines
# where the old model kept 60%.
TRUSTED_EVIDENCE = .67
# A line that fits no better than scrambled letters is never kept, however good its neighbours are.
LEAST_LINE_EVIDENCE = 0.
EVIDENCE_LINES = 3
SCRAMBLES = 2
# How hard a word's estimated time steers its placement: the price per second away, and the most it
# can cost. Tuned on half of the Jamendo songs with the singing-trained model, scored as a replay
# (learned timing for trusted lines, the estimate for the rest): the mean error on the other half
# fell from 226 ms to about 200 ms, and the typical error from 67 ms to 63 ms. Steering three times
# as hard pulled well-heard lines off their true times and was worse than none.
STEER_PER_SECOND = 3.
STEER_LIMIT = 12.


def _distinct(tokens):
    """Whether each state's token differs from the one before, so it can follow straight on."""
    return np.concatenate(([False], tokens[1:] != tokens[:-1]))


def _start(count):
    ink, gap = np.full(count + 1, -np.inf), np.full(count + 1, -np.inf)
    gap[0] = 0.
    return ink, gap


def _step(ink, gap, frame, tokens, distinct, entry=0.):
    """One frame's move. Returns the new states and where each new state's score came from.

    entry is added to a token's score only on the frame it is first entered.
    """
    kept, gapped = ink[1:], gap[:-1] + entry
    direct = np.where(distinct, ink[:-1], -np.inf) + entry
    best = np.maximum(np.maximum(kept, gapped), direct)
    source = np.where(best == kept, KEPT, np.where(best == gapped, FROM_GAP, FROM_INK))
    next_ink = np.concatenate(([-np.inf], frame[tokens] + best))
    next_gap = frame[BLANK] + np.maximum(gap, ink)
    return next_ink, next_gap, source, ink > gap


def steering(away_frames):
    """The price, in log probability, of starting a word this many frames from where it is expected."""
    return -np.minimum(STEER_LIMIT, STEER_PER_SECOND * STEP_SECONDS * np.abs(away_frames))


def expected_entry(frames, count, starts, expected_frames):
    """Entry prices for a whole clip: each word's first token is steered towards its expected frame.

    Where the model hears the words, a few frames of clear letters outweigh the price and the
    word goes where it was heard. Where it hears nothing, the word stays at its estimate
    instead of landing wherever the noise happens to fit.
    """
    entry = np.zeros((frames, count))
    entry[:, list(starts)] = steering(np.arange(frames)[:, None] - np.asarray(expected_frames, float)[None])
    return entry


def viterbi(log_probs, tokens, entry=None):
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
        ink, gap, ink_source[t], gap_source[t] = _step(ink, gap, log_probs[t], tokens, distinct,
                                                       0. if entry is None else entry[t])
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


def place_line(log_probs, plan, first_frame_time, expected=None):
    """Word starts with hindsight, or None if the spacing could not be singing.

    expected, when given, is the estimated start in seconds of every word of the line. It steers
    the placement, but the line's evidence is still measured on the audio alone.
    """
    if len(log_probs) < len(plan.tokens):
        return None
    entry = None
    if expected is not None:
        # The model reports a word a moment after it starts, so that is where its letters are expected.
        heard = [(expected[index] + SAVED_CORRECTION - first_frame_time) / STEP_SECONDS for index in plan.word_indexes]
        entry = expected_entry(len(log_probs), len(plan.tokens), plan.starts, heard)
    first = viterbi(log_probs, plan.tokens, entry)
    spacing = float(np.median(np.diff(first)))
    if not FEWEST_FRAMES_PER_TOKEN <= spacing <= MOST_FRAMES_PER_TOKEN:
        return None
    times = np.maximum(0., first_frame_time + first[list(plan.starts)] * STEP_SECONDS - SAVED_CORRECTION)
    starts = np.interp(range(plan.word_count), plan.word_indexes, times)
    pace = (first[-1] - first[0]) / max(1, len(plan.tokens) - 1)
    return PlacedLine(tuple(float(start) for start in starts), float(np.clip(pace, 1, MOST_FRAMES_PER_TOKEN)),
                      line_evidence(log_probs, plan.tokens))
