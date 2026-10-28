"""Original-text timing, compatibility and bounded parsing checks."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from halo.lyric_rendering import WordTimeline
from halo.models import (LyricLine, LyricWord, Lyrics, LyricsLimitError, Track,
                         MAX_LRC_BYTES, parse_lrc)
from halo.widgets import LyricCanvas
from halo.word_lyrics import (LyricsFormatError, load_lyrics_file,
                              parse_lyrics_record, parse_lyricsfile)


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def document(lines, **metadata):
    return yaml.dump({"version": "1.0", "metadata": {
        "title": "Original example", "artist": "Halo tests", **metadata}, "lines": lines},
        allow_unicode=True, Dumper=_NoAliasDumper)


class WordLyricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def original(self):
        return document([{"text": "Our light stays", "start_ms": 1000, "end_ms": 8000,
                          "words": [{"text": "Our ", "start_ms": 1500, "end_ms": 1800},
                                    {"text": "light ", "start_ms": 2100, "end_ms": 2500},
                                    {"text": "stays", "start_ms": 7000, "end_ms": 7900}]},
                         {"text": "A second line", "start_ms": 9000}], duration_ms=12000)

    def test_real_source_word_boundaries_drive_timeline_without_redistribution(self):
        lyrics = parse_lyricsfile(self.original())
        self.assertTrue(lyrics.has_word_timing)
        self.assertEqual(lyrics.lines[0].end, 8.)
        self.assertEqual([word.start for word in lyrics.lines[0].words], [1.5, 2.1, 7.])
        timeline = WordTimeline(lyrics.lines, 12.)
        self.assertEqual(timeline.at(0, 1.25), (-1, 0.))
        self.assertEqual(timeline.at(0, 1.65)[0], 0)
        self.assertAlmostEqual(timeline.at(0, 1.65)[1], .5)
        self.assertEqual(timeline.at(0, 6.9)[0], 1)
        self.assertEqual(timeline.at(0, 7.)[0], 2)
        self.assertEqual([(word.begin, word.finish) for word in timeline.words[:3]],
                         [(1.5, 1.8), (2.1, 2.5), (7., 7.9)])
        self.assertEqual([word.text for word in timeline.words[:3]], ["Our", "light", "stays"])

    def test_missing_ends_are_inferred_for_display_without_changing_source_model(self):
        lyrics = parse_lyricsfile(document([
            {"text": "First second", "start_ms": 0, "end_ms": 4500,
             "words": [{"text": "First ", "start_ms": 0}, {"text": "second", "start_ms": 4100}]}]))
        timeline = WordTimeline(lyrics.lines, 20)
        self.assertEqual([word.finish for word in timeline.words], [4.1, 4.5])
        self.assertEqual([word.end for word in lyrics.lines[0].words], [None, None])

    def test_fast_real_segments_complete_at_their_declared_end(self):
        # Singing sources may split a fast word into several short segments.
        # A 40 ms animation floor must not distort these 20 ms boundaries.
        line = LyricLine(1, "One two", (LyricWord("One ", 1, 1.02),
                                       LyricWord("two", 1.05, 1.05)))
        timeline = WordTimeline([line], 2)
        self.assertEqual(timeline.at(0, .999), (-1, 0.))
        self.assertAlmostEqual(timeline.at(0, 1.01)[1], .5)
        self.assertEqual(timeline.at(0, 1.02), (0, 1.))
        self.assertEqual(timeline.at(0, 1.05), (1, 1.))

    def test_equal_starts_and_overlapping_intervals_are_preserved(self):
        lyrics = parse_lyricsfile(document([
            {"text": "One two", "start_ms": 0, "end_ms": 4000,
             "words": [{"text": "One ", "start_ms": 1000, "end_ms": 3000},
                       {"text": "two", "start_ms": 1000, "end_ms": 2000}]},
            {"text": "Another voice", "start_ms": 2000, "end_ms": 5000}]))
        self.assertEqual(lyrics.lines[0].end, 4.)
        timeline = WordTimeline(lyrics.lines)
        self.assertEqual([(word.begin, word.finish) for word in timeline.words[:2]], [(1., 3.), (1., 2.)])

    def test_yaml_offset_is_not_silently_interpreted_while_the_spec_is_unresolved(self):
        lyrics = parse_lyricsfile(document([{"text": "Original", "start_ms": 2000}], offset_ms=700))
        self.assertEqual(lyrics.lines[0].time, 2.)

    def test_legacy_lrc_still_estimates_words_and_preserves_empty_repeated_cues(self):
        lines = parse_lrc("[offset:-100]\n[00:01][00:03]Original light\n[00:05]")
        self.assertEqual([round(line.time, 1) for line in lines], [.9, 2.9, 4.9])
        self.assertFalse(any(line.words for line in lines))
        self.assertEqual(len(WordTimeline(lines).words), 5)

    def test_enhanced_lrc_uses_absolute_boundaries_and_repeated_offset_cues(self):
        lines = parse_lrc("[offset:-100]\n[00:00][00:10]<00:00>Our <00:00.500>light<00:02>")
        self.assertEqual([line.text for line in lines], ["Our light", "Our light"])
        self.assertEqual([word.start for word in lines[0].words], [0., .4])
        self.assertEqual([word.start for word in lines[1].words], [9.9, 10.4])
        self.assertEqual([line.end for line in lines], [1.9, 11.9])
        self.assertEqual([word.begin for word in WordTimeline(lines).words], [0., .4, 9.9, 10.4])

    def test_enhanced_lrc_supports_implicit_first_boundary_and_no_space_languages(self):
        line = parse_lrc("[00:01]Our <00:02>light")[0]
        self.assertEqual([(word.text, word.start) for word in line.words], [("Our ", 1.), ("light", 2.)])
        line = parse_lrc("[00:01]<00:01>光<00:03>波<00:04>")[0]
        self.assertEqual(line.text, "光波")
        self.assertEqual([word.start for word in line.words], [1., 3.])

    def test_record_prefers_actual_words_and_falls_back_from_malformed_yaml(self):
        record = {"id": 123, "trackName": "Original example", "artistName": "Halo tests",
                  "lyricsfile": self.original(), "syncedLyrics": "[00:01]Fallback\n[00:09]Second"}
        result = parse_lyrics_record(record)
        self.assertTrue(result.has_word_timing)
        self.assertEqual(result.source_id, "123")
        self.assertEqual(result.selected_record["id"], 123)
        for invalid in ("not yaml", "version: '2.0'", "!!python/object:object {}",
                        "version: '1.0'\nversion: '1.0'", "x: &x [*x]"):
            with self.subTest(invalid=invalid):
                record["lyricsfile"] = invalid
                result = parse_lyrics_record(record)
                self.assertFalse(result.has_word_timing)
                self.assertEqual(result.lines[0].text, "Fallback")

    def test_yaml_rejects_aliases_tags_duplicate_keys_and_multiple_documents(self):
        invalid = ["x: &x [*x]", "x: &x hi\ny: *x", "x: !!str hi", "x: !thing hi",
                   "version: '1.0'\nversion: '1.0'", "x: hi\n---\nx: bye",
                   "x:\n  a: 1\n  a: 2"]
        for text in invalid:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_lyricsfile(text)

    def test_yaml_rejects_deep_structures_before_python_object_construction(self):
        text = "x: " + "[" * 1000 + "0" + "]" * 1000
        with self.assertRaises(LyricsLimitError):
            parse_lyricsfile(text)

    def test_yaml_requires_official_integer_timestamps_consistent_text_and_schema(self):
        for line in ({"text": "Original", "start_ms": -1},
                     {"text": "Original", "start_ms": 1.5},
                     {"text": "Original", "start_ms": True},
                     {"text": "Original", "start_ms": 2000, "end_ms": 1000},
                     {"text": "Original", "start_ms": 0, "words": [{"text": "Other", "start_ms": 0}]},
                     {"text": "One two", "start_ms": 0, "words": [
                         {"text": "One ", "start_ms": 3000}, {"text": "two", "start_ms": 1000}]}):
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    parse_lyricsfile(document([line]))

    def test_yaml_enforces_cue_word_character_and_input_budgets(self):
        for payload in ("x" * (MAX_LRC_BYTES + 1),
                        document([{"text": "", "start_ms": 0}] * 2001),
                        document([{"text": "a" * 2001, "start_ms": 0}]),
                        document([{"text": "a " * 257, "start_ms": 0}]),
                        document([{"text": "a" * 126, "start_ms": 0}] * 2000),
                        document([{"text": "a " * 200, "start_ms": 0}] * 101)):
            with self.subTest(size=len(payload)):
                with self.assertRaises(LyricsLimitError):
                    parse_lyricsfile(payload)

    def test_word_segments_cannot_bypass_renderer_limits_even_with_tiny_text(self):
        line = LyricLine(0, "a", tuple(LyricWord("", 0) for _ in range(257)))
        with patch("halo.lyric_rendering.Word", side_effect=AssertionError("Unexpected allocation")):
            with self.assertRaises(LyricsLimitError):
                WordTimeline([line])
        line = LyricLine(0, "a", (LyricWord("a", float("inf")),))
        with self.assertRaises(ValueError):
            WordTimeline([line])

    def test_bounded_file_imports_preserve_yaml_and_enhanced_lrc_word_data(self):
        work = Path(__file__).resolve().parents[1] / ".staging"
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as folder:
            path = Path(folder) / "original.lyricsfile.yaml"
            path.write_text(self.original(), encoding="utf-8-sig")
            self.assertTrue(load_lyrics_file(path).has_word_timing)
            path = Path(folder) / "original.elrc"
            path.write_text("[00:01]<00:01>Our <00:04>light", encoding="utf-8")
            self.assertEqual(load_lyrics_file(path).lines[0].words[-1].start, 4.)
            path.write_bytes(b"x" * (MAX_LRC_BYTES + 1))
            with self.assertRaises(LyricsLimitError):
                load_lyrics_file(path)

    def test_true_word_data_does_not_restore_ship_karaoke_or_box(self):
        for surface in ("preview", "floating", "immersive"):
            with self.subTest(surface=surface):
                c = SimpleNamespace(lyrics=parse_lyricsfile(self.original()),
                                    track=Track(duration=12, playing=True), position=1.6,
                                    offset=0, motion_time=10., generation=1, lyric_style="ship",
                                    reduced_motion=True, primary=QColor("#e9b7a1"), secondary=QColor("#c494aa"))
                canvas = LyricCanvas(c, surface)
                canvas.resize(800, 500)
                first = canvas.grab().toImage()
                c.position = 7.2
                c.motion_time += 5.6
                self.assertEqual(first, canvas.grab().toImage())
                canvas.close()

    def test_visual_leaves_a_blank_before_first_real_word(self):
        c = SimpleNamespace(lyrics=parse_lyricsfile(self.original()),
                            track=Track(duration=12, playing=True), position=1.25,
                            offset=0, motion_time=10., generation=1, lyric_style="visual",
                            reduced_motion=True, primary=QColor("#e9b7a1"), secondary=QColor("#c494aa"))
        canvas = LyricCanvas(c)
        canvas.resize(420, 240)
        with patch.object(canvas, "_visual") as words, patch.object(canvas, "_ship_visual") as preview, \
             patch.object(canvas, "_instrumental") as waiting:
            canvas.grab()
            words.assert_not_called()
            preview.assert_not_called()
            waiting.assert_not_called()
        canvas.close()

    def test_fast_source_words_finish_visual_transition_before_replacement(self):
        line = LyricLine(1, "One two three", (LyricWord("One ", 1, 1.08),
                                             LyricWord("two ", 1.08, 1.16),
                                             LyricWord("three", 1.16, 1.24)))
        c = SimpleNamespace(lyrics=Lyrics([line]), track=Track(duration=2, playing=True),
                            position=1., offset=0, motion_time=10., generation=1,
                            lyric_style="visual", reduced_motion=False,
                            primary=QColor("#e9b7a1"), secondary=QColor("#c494aa"))
        canvas = LyricCanvas(c)
        canvas.timeline = WordTimeline(c.lyrics.lines, 2)
        canvas._advance(0, 0, 1., 10.)
        canvas._advance(0, 1, 1.08, 10.08)
        self.assertAlmostEqual(canvas._advance(0, 1, 1.10, 10.10), .5)
        self.assertEqual(canvas._advance(0, 1, 1.12, 10.12), 1.)
        # If repaint starts late, use source time rather than restarting fade.
        self.assertEqual(canvas._advance(0, 2, 1.21, 10.21), 1.)
        c.track.playing = False
        self.assertEqual(canvas._advance(0, 2, 1.21, 10.21), 1.)
        canvas.close()

    def test_fast_source_fisheye_center_keeps_up_without_changing_ship_spring(self):
        segments = tuple(LyricWord("one " if i < 35 else "one", 1 + i * .08,
                                   1 + (i + 1) * .08) for i in range(36))
        c = SimpleNamespace(lyrics=Lyrics([LyricLine(1, "".join(w.text for w in segments), segments)]),
                            track=Track(duration=5, playing=True), generation=1,
                            lyric_style="fisheye", reduced_motion=False)
        canvas = LyricCanvas(c)
        canvas.timeline = WordTimeline(c.lyrics.lines, 5)
        maximum_lag = 0
        for frame in range(168):
            position = 1 + frame / 60
            word, _ = canvas.timeline.at(0, position)
            canvas._advance(0, word, position, 10 + frame / 60)
            if frame > 30:
                maximum_lag = max(maximum_lag, word - canvas._word_visual)
        self.assertLess(maximum_lag, .8)
        canvas.close()


if __name__ == "__main__":
    unittest.main()
