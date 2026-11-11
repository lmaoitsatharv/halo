"""Estimated word timing: a song's own pace decides when each line's singing ends, not the next line's start."""
import unittest

from halo.lyric_rendering import WordTimeline
from halo.models import LyricLine, LyricWord
from halo.word_pace import DEFAULT_PACE, paced_spans, song_pace, syllables, word_units


class SyllableTests(unittest.TestCase):
    def test_english_words_count_their_vowel_sounds(self):
        for word, count in (("light", 1), ("water", 2), ("original", 4), ("make", 1), ("little", 2), ("the", 1),
                            ("beautiful", 3), ("I'm", 1), ("rhythm", 1), ("hmm", 1), ("fire,", 1), ("évidemment", 4)):
            with self.subTest(word=word):
                self.assertEqual(syllables(word), count)

    def test_other_scripts_count_their_letters_not_latin_vowels(self):
        self.assertEqual(syllables("तुम"), 2)
        self.assertEqual(syllables("प्यार"), 2)   # a joined consonant is one beat, not two
        self.assertEqual(syllables("愛"), 1)
        self.assertEqual(syllables("24"), 2)
        self.assertEqual(syllables("♪"), 1)

    def test_longer_words_weigh_a_little_more_than_their_syllables(self):
        self.assertGreater(word_units("strengths"), word_units("to"))
        self.assertGreater(word_units("original"), word_units("strengths"))


class PaceTests(unittest.TestCase):
    def lines(self):
        """Four full lines of four one-syllable words in 2 s, then one with a long break after it."""
        rows = [("la la la la", 0.), ("da da da da", 2.), ("la la la la", 4.), ("da da da da", 6.), ("la la la la", 8.)]
        return [(text.split(), start, start + (2. if start < 8 else 10.)) for text, start in rows]

    def test_the_pace_comes_from_the_fullest_lines(self):
        lines = self.lines()
        full = sum(word_units(word) for word in lines[0][0]) / 2.
        self.assertAlmostEqual(song_pace(lines), full, places=6)

    def test_a_song_too_short_to_judge_uses_a_typical_pace(self):
        self.assertEqual(song_pace(self.lines()[:2]), DEFAULT_PACE)
        self.assertEqual(song_pace([]), DEFAULT_PACE)

    def test_a_line_before_a_long_break_ends_when_the_singing_would(self):
        words, start, end = self.lines()[-1]
        spans = paced_spans(words, start, end, song_pace(self.lines()))
        self.assertEqual(spans[0][0], start)
        # Sung at the song's pace, the four words are over in about 2.4 s, not spread across 10 s.
        self.assertLess(spans[-1][1], start + 3.)
        self.assertLess(spans[-1][0], start + 2.)
        for (begin, finish), (following, _) in zip(spans, spans[1:]):
            self.assertEqual(finish, following)
            self.assertLess(begin, finish)

    def test_a_full_line_still_fills_its_slot_and_never_runs_past_it(self):
        words, start, end = self.lines()[0]
        spans = paced_spans(words, start, end, song_pace(self.lines()))
        self.assertEqual(spans[-1][1], end)
        fast = paced_spans(["one", "two", "three", "four", "five", "six"], 0., .6, 2.)
        self.assertEqual(fast[-1][1], .6)

    def test_the_last_word_is_held_longer_than_the_others(self):
        spans = paced_spans("la la la la".split(), 0., 2., 2.)
        lengths = [finish - begin for begin, finish in spans]
        self.assertAlmostEqual(lengths[0], lengths[1])
        self.assertAlmostEqual(lengths[-1], 2 * lengths[0])

    def test_degenerate_lines_stay_ordered(self):
        self.assertEqual(paced_spans([], 0., 1., 4.), [])
        (begin, finish), = paced_spans(["hey"], 3., 3., 4.)
        self.assertEqual(begin, 3.)
        self.assertGreater(finish, begin)


class TimelineTests(unittest.TestCase):
    def test_estimated_words_follow_the_songs_pace_and_stop_before_a_break(self):
        lines = [LyricLine(0., "la la la la"), LyricLine(2., "da da da da"), LyricLine(4., "la la la la"),
                 LyricLine(6., "da da da da"), LyricLine(8., "la la la la"), LyricLine(18., "da da da da")]
        timeline = WordTimeline(lines, 30)
        start, end = timeline.ranges[4]
        words = timeline.words[start:end]
        self.assertEqual(words[0].begin, 8.)
        self.assertLess(words[-1].begin, 10.)
        self.assertLess(words[-1].finish, 11.)
        # A full line is unchanged in extent: it still runs to the next line.
        start, end = timeline.ranges[0]
        self.assertEqual(timeline.words[end - 1].finish, 2.)

    def test_supplied_word_timing_is_never_re_estimated(self):
        timed = LyricLine(0., "one two", (LyricWord("one", .5, 1.), LyricWord(" two", 1.5, 1.9)))
        timeline = WordTimeline([timed, LyricLine(4., "la la la la"), LyricLine(6., "da da da da")], 10)
        self.assertEqual([(word.begin, word.finish) for word in timeline.words[:2]], [(.5, 1.), (1.5, 1.9)])


if __name__ == "__main__":
    unittest.main()
