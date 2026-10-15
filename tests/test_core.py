import unittest
import numpy as np
from halo.models import Track, Lyrics, TimelineClock, parse_lrc, eligible_match, audio_energy


class LyricsTests(unittest.TestCase):
    def test_lrc_fraction_multiple_timestamps_offset_and_empty_cue(self):
        lines = parse_lrc("[ar:Example]\n[offset:-100]\n[00:02.50][00:05.5]Hello\n[00:01.005]First\n[00:07.00]")
        self.assertEqual([round(line.time, 3) for line in lines], [.905, 2.4, 5.4, 6.9])
        self.assertEqual([line.text for line in lines], ["First", "Hello", "Hello", ""])

    def test_before_first_line_and_seek_backwards(self):
        lyrics = Lyrics(parse_lrc("[00:02]One\n[00:05]Two\n[00:07]"))
        self.assertEqual(lyrics.index_at(0), -1)
        self.assertEqual(lyrics.index_at(5), 1)
        self.assertEqual(lyrics.index_at(3), 0)
        self.assertEqual(lyrics.index_at(7), 2)

    def test_reject_wrong_artist_and_recording(self):
        track = Track("Home", "Example Artist", duration=180)
        self.assertTrue(eligible_match({"trackName": "Home", "artistName": "Example Artist", "duration": 181}, track))
        self.assertFalse(eligible_match({"trackName": "Home", "artistName": "Another Artist", "duration": 180}, track))
        self.assertFalse(eligible_match({"trackName": "Home", "artistName": "Example Artist", "duration": 240}, track))


class ClockTests(unittest.TestCase):
    def test_join_existing_playback_timestamp(self):
        clock = TimelineClock()
        self.assertEqual(clock.update(10, "first", True, 200, 0, 60), 70)
        self.assertEqual(clock.update(10, "first", True, 200, 3, 63), 73)

    def test_pause_and_resume_before_timeline_update(self):
        clock = TimelineClock()
        clock.update(10, "first", True, 200, 0)
        self.assertEqual(clock.update(10, "first", False, 200, 5), 15)
        self.assertEqual(clock.update(10, "first", False, 200, 20), 15)
        self.assertEqual(clock.update(10, "first", True, 200, 25), 15)
        self.assertEqual(clock.update(10, "first", True, 200, 27), 17)

    def test_seek_and_duration_clamp(self):
        clock = TimelineClock()
        clock.update(50, 1, True, 200, 0)
        self.assertEqual(clock.update(20, 2, True, 200, 8), 20)
        self.assertEqual(clock.update(20, 2, True, 200, 300), 200)


class MeterTests(unittest.TestCase):
    def test_silence_stereo_and_clipping(self):
        self.assertEqual(audio_energy(np.zeros((100, 2))), 0)
        self.assertAlmostEqual(audio_energy(np.full((100, 2), .1)), .7)
        self.assertEqual(audio_energy(np.ones((100, 2))), 1)
        self.assertEqual(audio_energy(np.zeros((0, 2))), 0)


if __name__ == "__main__":
    unittest.main()
