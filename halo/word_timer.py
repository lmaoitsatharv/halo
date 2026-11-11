"""Listen to a song's output audio on a background thread, and place each finished line's words.

While a song plays, the display shows the estimate; hearing words live proved less accurate than
that, so nothing here drives the screen. Each line is placed with hindsight once it has ended, and
the trusted lines are saved for the next listen.

Nothing here touches the disk. Model output is held in memory for at most 30 seconds, and only
word times leave this module. Any break in the audio drops the line it falls in.
"""
import logging
import queue
import threading

import numpy as np

from .word_model import WINDOW_SECONDS, WordModel
from .word_pace import estimated_words
from .word_timing import STEP_SECONDS, line_plan, place_line, trusted_lines

log = logging.getLogger(__name__)
QUEUE_BLOCKS = 96
# Half a second of 1,024-sample blocks at 48 kHz.
BLOCK_BACKLOG = 24
MAX_STEPS = 1500
MARGIN_SECONDS = .4
GAP_SECONDS = .15
LAST_LINE_SECONDS = 8.
CENTRE_SECONDS = WINDOW_SECONDS / 2
LINE_SECONDS_LIMIT = MAX_STEPS * STEP_SECONDS - 2 * MARGIN_SECONDS


class WordTimer:
    def __init__(self, model_factory=WordModel):
        self.model_factory = model_factory
        self.model = None
        self.failed = False
        self.queue = queue.Queue(QUEUE_BLOCKS)
        self.key = self.on_done = None
        self.plans = []
        self.rows = []
        self.rows_start = 0.
        self.placed, self.evidence = {}, {}
        self.expected = None
        self.next_close = 0
        self.thread = threading.Thread(target=self.run, name="Halo word timer", daemon=True)
        self.thread.start()

    # Called from other threads. These only post messages, so they can never hold up audio or the UI.
    def start_song(self, key, lines, on_done, duration=0):
        self.queue.put(("song", key, list(lines), on_done, duration))

    def finish_song(self):
        self.queue.put(("finish",))

    def abandon_song(self):
        """End the song without saving what it heard."""
        self.queue.put(("abandon",))

    def feed(self, samples, rate, position, playing):
        try:
            self.queue.put_nowait(("block", np.asarray(samples, np.float32), rate, position, playing))
        except queue.Full:
            self.expected = None

    def settle(self):
        self.queue.join()

    def close(self):
        self.queue.put(("stop",))
        self.thread.join(2)

    # Everything below runs on the worker thread.
    def run(self):
        while True:
            message = self.queue.get()
            try:
                if message[0] == "stop":
                    return
                if not self.failed:
                    getattr(self, "on_" + message[0])(*message[1:])
            except Exception:
                log.exception("Word timing stopped for this session")
                self.failed = True
            finally:
                self.queue.task_done()

    def on_song(self, key, lines, on_done, duration=0):
        if self.model is None:
            self.model = self.model_factory()
        self.key, self.on_done = key, on_done
        self.plans = self.make_plans(lines, duration)
        self.placed, self.evidence = {}, {}
        self.drop_stream()

    @staticmethod
    def make_plans(lines, duration=0):
        """(line number, start, end, plan, estimated start of every word) for each line it can place."""
        plans = []
        estimates = estimated_words(lines, duration)
        for number, line in enumerate(lines):
            plan = None if line.words or not line.text.strip() else line_plan(line.text)
            if plan is None:
                continue
            ends = line.end if line.end is not None else lines[number + 1].time if number + 1 < len(lines) else line.time + LAST_LINE_SECONDS
            ends = max(ends, line.time + .5)
            if ends - line.time <= LINE_SECONDS_LIMIT:
                # The same estimate the display shows, so the placement is steered from what is on screen.
                plans.append((number, line.time, ends, plan, [begin for begin, _ in estimates[number][1]]))
        return plans

    def on_finish(self):
        if self.on_done is not None:
            trusted = trusted_lines(self.evidence)
            self.on_done(self.key, {number: starts for number, starts in self.placed.items() if number in trusted})
        self.key = self.on_done = None
        self.plans = []
        self.drop_stream()

    def on_abandon(self):
        self.on_done = None
        self.on_finish()

    def drop_stream(self):
        """Forget the audio so far: a seek, pause, gap or backlog means the next steps do not follow on."""
        if self.model is not None:
            self.model.reset()
        self.rows = []
        self.expected = None

    def on_block(self, samples, rate, position, playing):
        if self.key is None:
            return
        behind = self.queue.qsize() > BLOCK_BACKLOG
        # A device change gives exact zeros for a while, with the song's clock still running.
        if not playing or behind or not samples.any():
            self.drop_stream()
            return
        seconds = len(samples) / rate
        if self.expected is None or abs(position - self.expected) > GAP_SECONDS:
            self.drop_stream()
            self.rows_start = position + CENTRE_SECONDS
            # A line already under way when the audio picks up is left for another listen.
            self.next_close = sum(entry[1] - MARGIN_SECONDS < position for entry in self.plans)
            self.expected = position
        self.expected += seconds
        mono = samples.mean(axis=1) if samples.ndim > 1 else samples
        for step in self.model.push(mono, rate):
            self.take_step(step)

    def take_step(self, step):
        self.rows.append(step)
        if len(self.rows) > MAX_STEPS:
            del self.rows[0]
            self.rows_start += STEP_SECONDS
        now = self.rows_start + (len(self.rows) - 1) * STEP_SECONDS
        while self.next_close < len(self.plans) and now >= self.plans[self.next_close][2] + MARGIN_SECONDS:
            self.close_line(self.plans[self.next_close])
            self.next_close += 1

    def close_line(self, entry):
        number, start, ends, plan, expected = entry
        first = round((start - MARGIN_SECONDS - self.rows_start) / STEP_SECONDS)
        if first < 0:
            return
        last = round((ends + MARGIN_SECONDS - self.rows_start) / STEP_SECONDS)
        result = place_line(np.stack(self.rows[first:last]), plan, self.rows_start + first * STEP_SECONDS,
                            expected if len(expected) == plan.word_count else None)
        if result is None:
            return
        self.placed[number], self.evidence[number] = list(result.starts), result.evidence
