"""Word placement on model output, live and with hindsight."""
from pathlib import Path
import unittest

import numpy as np

from halo.word_model import ALPHABET, BLANK, BOUNDARY, TOKEN, encode
from halo.word_timing import (SAVED_CORRECTION, TRUSTED_EVIDENCE, LinePlan, line_evidence, line_plan,
                              place_line, trusted_lines, viterbi)

def posteriors(path, sharp=8.):
    logits = np.zeros((len(path), len(ALPHABET)))
    logits[np.arange(len(path)), path] = sharp
    return logits - np.logaddexp.reduce(logits, axis=1, keepdims=True)


def spoken(tokens, gap=4, lead=10):
    path = [BLANK] * lead
    for token in tokens:
        path += [token] + [BLANK] * (gap - 1)
    return path + [BLANK] * lead


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


class SteeredPlacementTests(unittest.TestCase):
    """The estimated time of each word steers the alignment where the model hears nothing clear."""
    def flat(self, frames):
        return np.full((frames, len(ALPHABET)), -np.log(len(ALPHABET)))

    def test_with_nothing_to_hear_words_land_on_their_expected_frames(self):
        from halo.word_timing import expected_entry
        tokens, starts = encode(["one", "two", "three"])
        expected = [20, 60, 100]
        first = viterbi(self.flat(140), tokens, expected_entry(140, len(tokens), starts, expected))
        self.assertEqual([int(first[start]) for start in starts], expected)

    def test_without_steering_the_same_silence_puts_words_anywhere(self):
        tokens, starts = encode(["one", "two", "three"])
        first = viterbi(self.flat(140), tokens)
        self.assertNotEqual([int(first[start]) for start in starts], [20, 60, 100])

    def test_clear_singing_far_from_the_estimate_still_wins(self):
        from halo.word_timing import expected_entry
        tokens, starts = encode(["something", "wonderful"])
        frames = posteriors(spoken(tokens, 4, 60))
        first = viterbi(frames, tokens, expected_entry(len(frames), len(tokens), starts, [5, 25]))
        self.assertEqual(list(first), list(viterbi(frames, tokens)))

    def test_steering_never_strays_far_from_a_slightly_wrong_estimate(self):
        from halo.word_timing import expected_entry
        tokens, starts = encode(["go", "now"])
        frames = posteriors(spoken(tokens, 3, 30), sharp=1.)   # faintly heard near frame 30
        first = viterbi(frames, tokens, expected_entry(len(frames), len(tokens), starts, [26, 40]))
        self.assertLessEqual(abs(int(first[starts[0]]) - 30), 4)

    def test_place_line_takes_expected_seconds_for_every_word(self):
        plan = line_plan("go now")
        frames = posteriors(spoken(list(plan.tokens), 4, 30))
        steered = place_line(frames, plan, 100., expected=[100.3, 100.9])
        plain = place_line(frames, plan, 100.)
        self.assertEqual(steered.starts, plain.starts)
        # Evidence is measured without the steering, so an estimate can never vouch for a line.
        self.assertEqual(steered.evidence, plain.evidence)

    def test_an_unheard_line_is_still_rejected_not_saved_as_its_estimate(self):
        plan = line_plan("one two three")
        self.assertIsNone(place_line(self.flat(140), plan, 0., expected=[.4, 1.2, 2.]))
