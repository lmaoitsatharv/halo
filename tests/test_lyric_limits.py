import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from halo.lyric_rendering import TypeCache, WordTimeline
from halo.lyrics import LyricsWorker, MAX_LYRICS_RESPONSE_BYTES
from halo.models import (LyricLine, LyricsLimitError, MAX_LRC_BYTES,
                         MAX_LYRIC_LINE_CHARS, load_lrc, parse_lrc)


class LyricLimitsTests(unittest.TestCase):
    def test_small_multi_timestamp_payload_cannot_expand_into_millions_of_words(self):
        payload = "[00:00][00:01]" * 1000 + "a " * 2000
        self.assertLess(len(payload), 32_000)
        with self.assertRaises(LyricsLimitError):
            parse_lrc(payload)

    def test_expansion_budget_applies_across_individually_valid_rows(self):
        row = "[00:00]" * 32 + "a " * 256
        with self.assertRaises(LyricsLimitError):
            parse_lrc("\n".join([row] * 4))

    def test_cue_count_is_bounded_even_for_empty_lines(self):
        with self.assertRaises(LyricsLimitError):
            parse_lrc("[00:00]\n" * 2001)

    def test_renderer_rejects_direct_cues_before_allocating_word_objects(self):
        lines = [LyricLine(0, "a " * 200)] * 101
        with patch("halo.lyric_rendering.Word", side_effect=AssertionError("Unexpected allocation")):
            with self.assertRaises(LyricsLimitError):
                WordTimeline(lines)

    def test_cjk_word_work_and_type_shaping_are_bounded(self):
        with self.assertRaises(LyricsLimitError):
            parse_lrc("[00:00]" + "\u5149" * 257)
        with self.assertRaises(LyricsLimitError):
            TypeCache().get("a" * (MAX_LYRIC_LINE_CHARS + 1), 400, 200, 40)

    def test_import_reads_only_a_bounded_number_of_bytes(self):
        work = Path(__file__).resolve().parents[1] / ".staging"
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(work.resolve()))
            path = Path(folder) / "lyrics.lrc"
            path.write_bytes(b"x" * (MAX_LRC_BYTES + 1))
            with self.assertRaises(LyricsLimitError):
                load_lrc(path)
            path.write_text("\ufeff[offset:-100]\n[00:01][00:03]Original light\n[00:05]", encoding="utf-8")
            lines = load_lrc(path)
            self.assertEqual([round(line.time, 1) for line in lines], [.9, 2.9, 4.9])
            self.assertEqual(len(WordTimeline(lines).words), 5)

    def test_http_response_is_bounded_before_json_decoding(self):
        response = MagicMock()
        response.read.return_value = b" " * (MAX_LYRICS_RESPONSE_BYTES + 1)
        response.__enter__.return_value = response
        with patch("halo.lyrics.urlopen", return_value=response), patch("halo.lyrics.json.loads") as decode:
            with self.assertRaises(LyricsLimitError):
                LyricsWorker().request("search", {"track_name": "Original"})
        response.read.assert_called_once_with(MAX_LYRICS_RESPONSE_BYTES + 1)
        decode.assert_not_called()

    def test_unsafe_downloaded_record_is_skipped_and_normal_cues_still_work(self):
        self.assertEqual(LyricsWorker.timed_lines({"syncedLyrics": "[00:00]" * 2000 + "a " * 2000}), [])
        lines = parse_lrc("[00:00][00:04]Original light\n[00:08]\u5149\u6ce2\n[00:12]")
        self.assertEqual(len(lines), 4)
        self.assertEqual(len(WordTimeline(lines).words), 7)


if __name__ == "__main__":
    unittest.main()
