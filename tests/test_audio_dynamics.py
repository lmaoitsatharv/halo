"""Audio-to-accent checks using generated signals, without device access."""
import unittest

import numpy as np

from halo.audio import AudioDynamics
from halo.models import audio_energy


def music(seconds=4., volume=1.):
    rate = 48000
    t = np.arange(round(seconds * rate)) / rate
    signal = .38 * np.sin(2 * np.pi * 1600 * t)
    for start in np.arange(1., seconds - .1, .5):
        age = t - start
        kick = np.where(age >= 0, np.exp(-np.maximum(0, age) / .045), 0.)
        signal += .48 * kick * np.sin(2 * np.pi * 65 * age)
    return np.column_stack((signal, signal)) * volume


def analyse(samples):
    detector = AudioDynamics()
    levels = []
    raw = []
    for start in range(0, len(samples) - 1023, 1024):
        block = samples[start:start + 1024]
        levels.append(detector.process(block))
        raw.append(audio_energy(block))
    return np.array(levels), np.array(raw)


class AudioDynamicsTests(unittest.TestCase):
    def test_mastered_music_does_not_flatline_at_the_old_gain_limit(self):
        levels, raw = analyse(music())
        self.assertTrue(np.all(np.minimum(1., raw * 7) == 1.))
        times = np.arange(len(levels)) * 1024 / 48000
        for start in np.arange(1., 3.9, .5):
            self.assertGreater(levels[(times >= start) & (times < start + .1)].max(), .75)
            self.assertLess(np.median(levels[(times > start + .30) & (times < start + .47)]), .3)

    def test_quiet_and_loud_versions_keep_the_same_accents(self):
        loud, _ = analyse(music(volume=1.))
        quiet, _ = analyse(music(volume=.02))
        self.assertTrue(np.allclose(loud, quiet, atol=1e-8))

    def test_steady_tones_do_not_create_continuous_false_hits(self):
        t = np.arange(48000 * 2) / 48000
        for volume in (.001, .03, .4):
            samples = volume * np.sin(2 * np.pi * 440 * t)
            levels, _ = analyse(np.column_stack((samples, samples)))
            self.assertLess(levels[48:].max(), .25)

    def test_bass_accents_can_pulse_without_a_large_total_volume_change(self):
        t = np.arange(48000 * 2) / 48000
        bass = np.where((t >= 1.) & (t < 1.12), .8, 0.)
        samples = .4 * (np.sqrt(1 - bass ** 2) * np.sin(2 * np.pi * 1600 * t)
                         + bass * np.sin(2 * np.pi * 65 * t))
        levels, raw = analyse(np.column_stack((samples, samples)))
        self.assertGreater(levels[47:53].max(), .8)
        self.assertLess(abs(raw[47:53].mean() - raw[20:40].mean()), .025)

    def test_opposite_phase_stereo_cannot_cancel_accents(self):
        samples = music()
        regular, _ = analyse(samples)
        samples[:, 1] *= -1
        opposed, _ = analyse(samples)
        self.assertTrue(np.allclose(regular, opposed, atol=1e-10))

    def test_silence_and_inaudible_noise_stay_quiet_and_hits_release(self):
        detector = AudioDynamics()
        self.assertEqual(detector.process(np.zeros((1024, 2))), 0.)
        noise = np.random.default_rng(7).normal(0, 1e-7, (1024, 2))
        for _ in range(30):
            self.assertEqual(detector.process(noise), 0.)
        for block in np.array_split(music(seconds=2.), 96):
            detector.process(block)
        for _ in range(30):
            result = detector.process(np.zeros((1024, 2)))
        self.assertLess(result, .001)
        cleaned = detector.process(np.full((1024, 2), np.nan))
        self.assertTrue(np.isfinite(cleaned))
        self.assertLessEqual(cleaned, result)


if __name__ == "__main__":
    unittest.main()
