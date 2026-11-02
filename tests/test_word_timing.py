"""Word placement on model output, live and with hindsight."""
from pathlib import Path
import unittest

import numpy as np

from halo.word_model import ALPHABET, BLANK, BOUNDARY, TOKEN, encode
from halo.word_timing import (SAVED_CORRECTION, TRUSTED_EVIDENCE, LinePlan, Live, PaceFollower, line_evidence, line_plan,
                              place_line, trusted_lines, viterbi)

FIRM = Live(sharpness=.5, threshold=.5, late=1.5, eager=.25)


def posteriors(path, sharp=8.):
    logits = np.zeros((len(path), len(ALPHABET)))
    logits[np.arange(len(path)), path] = sharp
    return logits - np.logaddexp.reduce(logits, axis=1, keepdims=True)


def spoken(tokens, gap=4, lead=10):
    path = [BLANK] * lead
    for token in tokens:
        path += [token] + [BLANK] * (gap - 1)
    return path + [BLANK] * lead


def follow(tokens, starts, frames, pace, wait=5., settings=FIRM):
    follower = PaceFollower(tokens, starts, pace, wait, settings)
    opened, seen = [None] * len(starts), 0
    for t, frame in enumerate(frames):
        count = follower.step(frame)
        for word in range(seen, count):
            opened[word] = t
        seen = count
    return opened


class ViterbiTests(unittest.TestCase):
    def test_finds_each_token_after_blanks(self):
        tokens, _ = encode(["go"])
        path = [BLANK, BLANK, tokens[0], BLANK, tokens[1], tokens[1], BLANK, tokens[2], BLANK, tokens[3], BLANK]
        self.assertEqual(list(viterbi(posteriors(path), tokens)), [2, 4, 7, 9])

    def test_a_repeated_letter_needs_a_blank_between(self):
        path = [TOKEN["l"], TOKEN["l"], BLANK, TOKEN["l"], BLANK]
        self.assertEqual(list(viterbi(posteriors(path), [TOKEN["l"], TOKEN["l"]])), [0, 3])

    def test_too_few_frames_is_refused(self):
        with self.assertRaises(ValueError):
            viterbi(posteriors([BLANK]), [TOKEN["a"], TOKEN["b"]])


class PaceFollowerTests(unittest.TestCase):
    def test_clear_words_open_when_they_are_heard(self):
        tokens, starts = encode(["go", "now"])
        opened = follow(tokens, starts, posteriors(spoken(tokens, 3, 12)), pace=3.)
        for word, frame in enumerate(opened):
            self.assertLessEqual(abs(frame - (12 + 3 * starts[word])), 4, opened)

    def test_with_no_evidence_it_keeps_the_pace(self):
        tokens, starts = encode(["one", "two", "three"])
        opened = follow(tokens, starts, posteriors([BLANK] * 120), pace=6., wait=6.)
        self.assertLessEqual(abs(opened[2] - (6 + 6 * FIRM.late * (starts[2] + 1))), 2)

    def test_hearing_a_word_early_beats_a_slow_pace(self):
        tokens, starts = encode(["go", "now"])
        self.assertLess(follow(tokens, starts, posteriors(tokens + [BLANK] * 5), pace=20., wait=2.)[1], 12)

    def test_the_deadline_counts_from_the_last_word_heard(self):
        tokens, starts = encode(["go", "now", "then"])
        opened = follow(tokens, starts, posteriors(tokens[:4] + [BLANK] * 200), pace=10.)
        self.assertLessEqual(abs(opened[1] - (opened[0] + (starts[1] - starts[0]) * 10 * FIRM.late)), 3, opened)

    def test_a_missed_start_does_not_stop_it(self):
        tokens, starts = encode(["fast", "words", "here"])
        self.assertNotIn(None, follow(tokens, starts, posteriors([BLANK] * 200), pace=5.))

    def test_the_tuned_defaults_keep_words_in_order_and_never_stall(self):
        tokens, starts = encode(["fast", "words", "here"])
        opened = follow(tokens, starts, posteriors([BLANK] * 200), pace=5., settings=Live())
        self.assertNotIn(None, opened)
        self.assertEqual(opened, sorted(opened))

    def test_words_only_ever_open_in_order(self):
        tokens, starts = encode(["hello", "world", "again"])
        noise = np.random.default_rng(5).normal(size=(200, len(ALPHABET)))
        noise -= np.logaddexp.reduce(noise, axis=1, keepdims=True)
        follower = PaceFollower(tokens, starts, 4., 5.)
        counts = [follower.step(frame) for frame in noise]
        self.assertEqual(counts, sorted(counts))

    def test_belief_stays_a_probability(self):
        tokens, starts = encode(["go"])
        follower = PaceFollower(tokens, starts, 3., 2.)
        for frame in posteriors(spoken(tokens, 2, 2)):
            follower.step(frame)
            self.assertAlmostEqual(float(follower.belief.sum()), 1.)
            self.assertTrue((follower.belief >= 0).all())


class LinePlanTests(unittest.TestCase):
    def test_a_plain_line_tracks_every_word(self):
        plan = line_plan("go now")
        self.assertEqual(plan.word_indexes, (0, 1))
        self.assertEqual(plan.word_count, 2)

    def test_a_non_latin_line_has_no_plan(self):
        self.assertIsNone(line_plan("तुम ही हो"))
        self.assertIsNone(line_plan("原创文字"))

    def test_a_mostly_spelled_line_keeps_its_gaps(self):
        plan = line_plan("go -- now now now")
        self.assertEqual(plan.word_indexes, (0, 2, 3, 4))
        self.assertEqual(plan.word_count, 5)


class PlaceLineTests(unittest.TestCase):
    def test_correction_is_applied(self):
        plan = line_plan("go now")
        placed = place_line(posteriors(spoken(plan.tokens)), plan, 10.)
        self.assertAlmostEqual(placed.starts[0], 10 + (10 + 4 * plan.starts[0]) * .02 - SAVED_CORRECTION)
        self.assertGreater(placed.starts[1], placed.starts[0])

    def test_a_word_placed_at_the_very_start_is_never_negative(self):
        plan = line_plan("go now")
        placed = place_line(posteriors(spoken(plan.tokens, 4, 0)), plan, 0.)
        self.assertGreaterEqual(min(placed.starts), 0.)

    def test_unspellable_words_are_interpolated(self):
        plan = line_plan("go -- now then")
        placed = place_line(posteriors(spoken(plan.tokens)), plan, 0.)
        self.assertEqual(len(placed.starts), 4)
        self.assertLess(placed.starts[0], placed.starts[1])
        self.assertLess(placed.starts[1], placed.starts[2])

    def test_silence_is_rejected(self):
        plan = line_plan("go now then")
        self.assertIsNone(place_line(posteriors([BLANK] * 300), plan, 0.))

    def test_impossible_spacing_is_rejected(self):
        plan = line_plan("go now then")
        self.assertIsNone(place_line(posteriors(list(plan.tokens) + [BLANK] * 2), plan, 0.))
        self.assertIsNone(place_line(posteriors(spoken(plan.tokens, 40, 2)), plan, 0.))

    def test_too_little_audio_is_rejected(self):
        plan = line_plan("go now then")
        self.assertIsNone(place_line(posteriors([BLANK] * 3), plan, 0.))

    def test_clear_words_beat_their_own_letters_scrambled(self):
        plan = line_plan("go now then")
        self.assertGreater(place_line(posteriors(spoken(plan.tokens)), plan, 0.).evidence, TRUSTED_EVIDENCE)

    def test_real_output_favours_its_own_words(self):
        data = np.load(Path(__file__).parent / "fixtures" / "word_timing_line.npz")
        self.assertGreaterEqual(line_evidence(data["log_probs"], data["right_tokens"]), TRUSTED_EVIDENCE)
        self.assertLess(line_evidence(data["log_probs"], data["wrong_tokens"]), TRUSTED_EVIDENCE)

    def test_evidence_does_not_change_between_runs(self):
        plan = line_plan("go now then")
        frames = posteriors(spoken(plan.tokens))
        self.assertEqual(line_evidence(frames, plan.tokens), line_evidence(frames, plan.tokens))


class TrustedLinesTests(unittest.TestCase):
    strong, weak = TRUSTED_EVIDENCE + 1, TRUSTED_EVIDENCE / 2

    def test_one_weak_line_among_strong_ones_is_kept(self):
        self.assertEqual(trusted_lines({0: self.strong, 1: self.weak, 2: self.strong, 3: self.strong}), {0, 1, 2, 3})

    def test_a_weak_run_is_dropped(self):
        evidence = {0: self.strong, 1: self.strong, 2: self.strong, 3: self.weak, 4: self.weak, 5: self.weak}
        self.assertEqual(trusted_lines(evidence), {0, 1, 2})

    def test_another_app_playing_saves_nothing(self):
        self.assertEqual(trusted_lines({k: self.weak for k in range(8)}), set())

    def test_a_line_worse_than_scrambled_is_dropped_among_strong_ones(self):
        self.assertEqual(trusted_lines({0: self.strong, 1: -5., 2: self.strong, 3: self.strong}), {0, 2, 3})

    def test_too_few_lines_saves_nothing(self):
        self.assertEqual(trusted_lines({0: self.strong, 1: self.strong}), set())


if __name__ == "__main__":
    unittest.main()
