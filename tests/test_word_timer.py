"""The background word timer, driven by a scripted model so timing is exact."""
import threading
import unittest

import numpy as np

from halo.models import LyricLine, LyricWord
from halo.word_model import ALPHABET, BLANK
from halo.word_timer import BLOCK_BACKLOG, MAX_STEPS, QUEUE_BLOCKS, WordTimer
from halo.word_timing import line_plan

RATE = 48000
BLOCK = 960
STEP = .02


def row(token):
    logits = np.zeros(len(ALPHABET))
    logits[token] = 8.
    return logits - np.logaddexp.reduce(logits)


class ScriptedModel:
    """One output step per block; the block's first sample carries the token to emit."""
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def push(self, samples, rate):
        return row(int(samples[0] + .5))[None]


def song(lines, gap=3.):
    return [LyricLine(k * gap + 1, text) for k, text in enumerate(lines)]


def tokens_at(lines):
    """Which token sounds at each step, with a line's letters spaced out from its start."""
    script = {}
    for line in lines:
        plan = line_plan(line.text)
        if plan:
            for k, token in enumerate(plan.tokens):
                script[round((line.time + k * .08) / STEP)] = token
    return script


class WordTimerTests(unittest.TestCase):
    def setUp(self):
        self.model = ScriptedModel()
        self.timer = WordTimer(lambda: self.model)
        self.addCleanup(self.timer.close)
        self.done = []

    def on_done(self, key, placed):
        self.done.append((key, placed))

    def start(self, lines, key="song"):
        self.script = tokens_at(lines)
        self.timer.start_song(key, lines, self.on_done)

    def play(self, start, stop, playing=True):
        for step in range(round(start / STEP), round(stop / STEP)):
            # A tiny signal, so a blank block is not digital silence.
            block = np.full((BLOCK, 2), float(self.script.get(step, BLANK)) + .001, np.float32)
            self.timer.feed(block, RATE, step * STEP, playing)
            self.timer.settle()

    def finish(self):
        self.timer.finish_song()
        self.timer.settle()
        return self.done[-1][1]

    def test_finished_lines_are_placed(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 19)
        placed = self.finish()
        self.assertEqual(sorted(placed), [0, 1, 2, 3])
        self.assertAlmostEqual(placed[0][0], 1.08, delta=.13)
        self.assertLess(placed[0][0], placed[0][1])

    def test_a_song_too_short_to_judge_saves_nothing(self):
        self.start(song(["go now then"]))
        self.play(0, 6)
        self.assertEqual(self.finish(), {})

    def test_lines_with_real_word_timing_are_left_alone(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        lines[1] = LyricLine(lines[1].time, "we run home", (LyricWord("we run home", lines[1].time),))
        self.start(lines)
        self.play(0, 14)
        self.assertNotIn(1, self.finish())

    def test_lines_it_cannot_spell_are_skipped(self):
        lines = song(["go now then", "तुम ही हो", "we run home", "they sing loud"])
        self.start(lines)
        self.play(0, 14)
        self.assertNotIn(1, self.finish())

    def test_seek_drops_the_line(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long", "one more time"])
        self.start(lines)
        self.play(0, 5)
        self.play(30, 31)
        self.assertNotIn(1, self.finish())
        self.assertGreater(self.model.resets, 1)

    def test_pause_drops_the_line(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 4.3)
        self.play(4.3, 4.5, playing=False)
        self.play(4.5, 14)
        self.assertNotIn(1, self.finish())

    def test_a_capture_gap_drops_the_line(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 4.3)
        self.play(5.3, 14)
        placed = self.finish()
        self.assertNotIn(1, placed)
        self.assertGreater(self.model.resets, 1)

    def test_a_short_capture_gap_drops_the_line(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 4.3)
        self.play(4.5, 19)
        self.assertNotIn(1, self.finish())

    def test_slow_drift_cannot_build_up(self):
        lines = song(["go now then", "we run home", "they sing loud"])
        self.start(lines)
        for step in range(round(5 / STEP)):
            block = np.full((BLOCK, 2), float(self.script.get(step, BLANK)) + .001, np.float32)
            self.timer.feed(block, RATE, step * STEP * 1.05, True)
            self.timer.settle()
        self.assertGreater(self.model.resets, 2)

    def test_digital_silence_counts_as_a_gap(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 4.3)
        resets = self.model.resets
        self.timer.feed(np.zeros((BLOCK, 2), np.float32), RATE, 4.3, True)
        self.timer.settle()
        self.assertGreater(self.model.resets, resets)

    def test_abandoning_a_song_saves_nothing(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 14)
        self.timer.abandon_song()
        self.timer.finish_song()
        self.timer.settle()
        self.assertEqual(self.done, [])

    def test_track_change_never_credits_the_new_song(self):
        old = song(["go now then", "we run home", "they sing loud"])
        self.start(old, "old")
        self.play(0, 5)
        new = song(["all night long", "one more time", "here we go"])
        self.timer.finish_song()
        self.start(new, "new")
        self.play(.2, .6)
        self.timer.settle()
        self.assertEqual(self.done[0][0], "old")
        self.play(.6, 16)
        self.assertEqual(sorted(self.finish()), [0, 1, 2])

    def test_memory_is_bounded_to_30_seconds(self):
        self.assertLessEqual(MAX_STEPS * STEP, 30)
        self.start(song(["go now then"]))
        self.play(0, 40)
        self.assertLessEqual(len(self.timer.rows), MAX_STEPS)

    def test_feed_never_blocks(self):
        entered, release = threading.Event(), threading.Event()

        class Stuck(ScriptedModel):
            def push(inner, samples, rate):
                entered.set()
                release.wait(5)
                return row(BLANK)[None]
        self.timer = WordTimer(Stuck)
        self.addCleanup(self.timer.close)
        self.addCleanup(release.set)
        self.start(song(["go now then"]))
        block = np.zeros((BLOCK, 2), np.float32)
        self.timer.feed(block, RATE, 0., True)
        entered.wait(5)
        finished = threading.Event()

        def fill():
            for k in range(QUEUE_BLOCKS * 2):
                self.timer.feed(block, RATE, k * STEP, True)
            finished.set()
        threading.Thread(target=fill, daemon=True).start()
        self.assertTrue(finished.wait(2))

    def test_a_backlog_drops_the_line(self):
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 4.3)
        gate = threading.Event()
        pushed = self.model.push
        self.model.push = lambda samples, rate: (gate.wait(5), pushed(samples, rate))[1]
        block = np.zeros((BLOCK, 2), np.float32)
        for k in range(BLOCK_BACKLOG + 5):
            self.timer.feed(block, RATE, 4.3 + k * STEP, True)
        gate.set()
        self.timer.settle()
        self.model.push = pushed
        self.play(5, 14)
        self.assertNotIn(1, self.finish())

    def test_a_failure_is_contained(self):
        lines = song(["go now then"])
        self.start(lines)
        self.model.push = lambda samples, rate: 1 / 0
        with self.assertLogs("halo.word_timer", "ERROR"):
            self.play(0, .2)
        self.timer.feed(np.ones((BLOCK, 2), np.float32), RATE, 1., True)
        self.timer.settle()
        self.assertTrue(self.timer.failed)

    def test_close_stops_the_thread(self):
        self.start(song(["go now then"]))
        self.timer.close()
        self.assertFalse(self.timer.thread.is_alive())

    def test_every_line_is_placed_with_its_estimate(self):
        from unittest.mock import patch
        from halo import word_timer
        from halo.lyric_rendering import WordTimeline
        lines = song(["go now then", "we run home", "they sing loud", "all night long"])
        seen = []
        real = word_timer.place_line

        def spy(log_probs, plan, first_frame_time, expected=None):
            seen.append(expected)
            return real(log_probs, plan, first_frame_time, expected)
        with patch.object(word_timer, "place_line", side_effect=spy):
            self.start(lines)
            self.play(0, 19)
            self.finish()
        self.assertEqual(len(seen), 4)
        # The same estimate the display uses for these lines, so learning starts from what is shown.
        timeline = WordTimeline(lines, 0)
        for number, expected in enumerate(seen[:3]):
            start, end = timeline.ranges[number]
            self.assertEqual([round(value, 6) for value in expected],
                             [round(word.begin, 6) for word in timeline.words[start:end]])

    def test_unspellable_lines_do_not_upset_the_songs_pace(self):
        lines = song(["go now then", "तुम ही हो", "we run home", "they sing loud", "all night long"])
        self.start(lines)
        self.play(0, 22)
        self.assertEqual(sorted(self.finish()), [0, 2, 3, 4])

if __name__ == "__main__":
    unittest.main()
