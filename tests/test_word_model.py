"""The numpy word model must match the trained PyTorch model and be safe to stream."""
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

from halo.word_model import ALPHABET, WordModel, encode, spell

REFERENCE = np.load(Path(__file__).parent / "fixtures" / "word_model_reference.npz")


class WordModelTests(unittest.TestCase):
    def noise(self, seconds=2.):
        rate = 48000
        return np.random.default_rng(1).normal(scale=.1, size=int(rate * seconds)).astype(np.float32), rate

    def test_outputs_match_pytorch(self):
        output = WordModel().push_features(REFERENCE["features"])
        expected = REFERENCE["log_probs"][:len(output)]
        self.assertGreaterEqual(len(output), 190)
        # 16-bit weights move log scores for rare letters, so compare probabilities.
        self.assertLessEqual(float(np.abs(np.exp(output) - np.exp(expected)).max()), .001)

    def test_chunk_size_changes_nothing(self):
        samples, rate = self.noise()
        whole = WordModel().push(samples, rate)
        model = WordModel()
        parts = [model.push(samples[start:start + 1024], rate) for start in range(0, len(samples), 1024)]
        self.assertTrue(np.allclose(whole, np.concatenate(parts), atol=1e-4))

    def test_each_step_has_every_token(self):
        samples, rate = self.noise()
        output = WordModel().push(samples, rate)
        self.assertEqual(output.shape[1], len(ALPHABET))
        self.assertTrue(np.allclose(np.exp(output).sum(axis=1), 1, atol=1e-3))

    def test_short_blocks_return_nothing_yet(self):
        self.assertEqual(len(WordModel().push(np.zeros(100, np.float32), 48000)), 0)

    def test_reset_clears_state(self):
        samples, rate = self.noise()
        model = WordModel()
        first = model.push(samples, rate)
        model.reset()
        self.assertTrue(np.allclose(first, model.push(samples, rate), atol=1e-6))

    def test_weights_load_only_on_first_use(self):
        code = ("import sys; import halo.word_model as m; assert 'halo.word_model_weights' not in sys.modules; "
                "m.WordModel(); assert 'halo.word_model_weights' in sys.modules")
        subprocess.run([sys.executable, "-c", code], check=True, cwd=Path(__file__).parents[1])

    def test_spelling_matches_training(self):
        self.assertEqual(spell("I’m at a pay-phone, CAFÉ!"), ["i'm", "at", "a", "payphone", "cafe"])
        tokens, starts = encode(["go", "do"])
        self.assertEqual(starts, [1, 4])
        self.assertEqual(len(tokens), 7)


if __name__ == "__main__":
    unittest.main()
