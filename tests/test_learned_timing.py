"""Learned word times: what is kept, what wins, and what never reaches the disk."""
from pathlib import Path
import json
import tempfile
import unittest

from halo.learned_timing import LearnedStore, MAX_FILE_BYTES, merge
from halo.lyric_rendering import WordTimeline
from halo.lyric_store import LyricStore
from halo.models import LyricLine, LyricWord, Lyrics, Track, validate_lyric_lines


def track(title="Song", duration=200):
    return Track(title=title, artist="Band", album="Album", duration=duration, connected=True)


class LearnedStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.store = LearnedStore(self.root / "learned-timing")

    def test_times_survive_a_reload(self):
        self.store.save(track(), "src", {0: [1., 1.5], 3: [9., 9.2]})
        self.assertEqual(self.store.load(track(), "src"), {0: [1., 1.5], 3: [9., 9.2]})

    def test_a_new_source_discards_learned_timing(self):
        self.store.save(track(), "src", {0: [1., 1.5]})
        self.assertEqual(self.store.load(track(), "other"), {})

    def test_a_later_listen_fills_missing_lines(self):
        self.store.save(track(), "src", {0: [1., 1.5]})
        self.store.save(track(), "src", {4: [20., 21.]})
        self.assertEqual(sorted(self.store.load(track(), "src")), [0, 4])

    def test_a_later_listen_replaces_a_line_it_heard_again(self):
        self.store.save(track(), "src", {0: [1., 1.5]})
        self.store.save(track(), "src", {0: [1.1, 1.6]})
        self.assertEqual(self.store.load(track(), "src"), {0: [1.1, 1.6]})

    def test_nothing_is_written_for_an_empty_result(self):
        self.store.save(track(), "src", {})
        self.assertEqual(list(self.store.directory.glob("*.json")) if self.store.directory.exists() else [], [])

    def test_oldest_song_is_removed_at_the_limit(self):
        store = LearnedStore(self.root / "small", limit=3)
        for number in range(4):
            store.save(track(f"Song {number}"), "src", {0: [1.]})
        self.assertEqual(len(list(store.directory.glob("*.json"))), 3)
        self.assertEqual(store.load(track("Song 0"), "src"), {})
        self.assertTrue(store.load(track("Song 3"), "src"))

    def test_corrections_folder_is_untouched(self):
        corrections = LyricStore(self.root / "saved-lyrics")
        corrections.save(track(), 300)
        self.store.save(track(), "src", {0: [1.]})
        self.store.forget_all()
        self.assertEqual(corrections.load(track())["offset"], 300)

    def test_a_corrupt_file_is_ignored(self):
        self.store.save(track(), "src", {0: [1.]})
        next(self.store.directory.glob("*.json")).write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.load(track(), "src"), {})

    def test_an_oversized_file_is_ignored(self):
        self.store.save(track(), "src", {0: [1.]})
        next(self.store.directory.glob("*.json")).write_bytes(b" " * (MAX_FILE_BYTES + 1))
        self.assertEqual(self.store.load(track(), "src"), {})

    def test_bad_times_are_ignored(self):
        self.store.save(track(), "src", {0: [1.]})
        path = next(self.store.directory.glob("*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["lines"]["0"] = ["soon"]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.store.load(track(), "src"), {})

    def test_an_unknown_recording_is_not_stored(self):
        self.store.save(track(duration=0), "src", {0: [1.]})
        self.assertEqual(self.store.load(track(duration=0), "src"), {})

    def test_nothing_but_times_is_written(self):
        self.store.save(track("Secret Title"), "src", {0: [1., 2.]})
        raw = next(self.store.directory.glob("*.json")).read_text(encoding="utf-8")
        self.assertNotIn("Secret", raw)
        self.assertEqual(sorted(json.loads(raw)), ["lines", "recording", "source", "version"])

    def test_forget_clears_one_song(self):
        self.store.save(track("One"), "src", {0: [1.]})
        self.store.save(track("Two"), "src", {0: [1.]})
        self.store.forget(track("One"))
        self.assertEqual(self.store.load(track("One"), "src"), {})
        self.assertTrue(self.store.load(track("Two"), "src"))

    def test_forget_all_clears_every_song(self):
        self.store.save(track("One"), "src", {0: [1.]})
        self.store.save(track("Two"), "src", {0: [1.]})
        self.store.forget_all()
        self.assertEqual(list(self.store.directory.glob("*.json")), [])


class MergeTests(unittest.TestCase):
    def test_merged_lines_pass_validation(self):
        lyrics = Lyrics([LyricLine(1, "Go,  now! (then)"), LyricLine(5, "we  run")])
        merged = merge(lyrics, {0: [1., 1.3, 1.6], 1: [5., 5.5]})
        validate_lyric_lines(merged.lines)
        self.assertEqual([word.start for word in merged.lines[0].words], [1., 1.3, 1.6])
        self.assertEqual("".join(word.text for word in merged.lines[0].words), "Go,  now! (then)")
        self.assertEqual(merged.timing_source, "learned")

    def test_a_word_ends_where_the_next_begins(self):
        merged = merge(Lyrics([LyricLine(1, "go now")]), {0: [1., 1.4]})
        self.assertEqual(merged.lines[0].words[0].end, 1.4)
        self.assertIsNone(merged.lines[0].words[1].end)

    def test_a_line_starts_with_its_first_word_so_nothing_hops(self):
        lyrics = Lyrics([LyricLine(1, "go now"), LyricLine(5, "we run")])
        merged = merge(lyrics, {0: [1.4, 1.8], 1: [4.9, 5.3]})
        self.assertEqual([line.time for line in merged.lines], [1.4, 4.9])
        self.assertEqual(WordTimeline(merged.lines, 10)._leading_gaps, {})

    def test_a_moved_line_never_crosses_its_neighbours(self):
        lyrics = Lyrics([LyricLine(1, "go now"), LyricLine(2, "we run"), LyricLine(3, "they sing")])
        merged = merge(lyrics, {1: [3.5, 3.8]})
        self.assertEqual([line.time for line in merged.lines], [1, 3, 3])
        validate_lyric_lines(merged.lines)

    def test_lines_with_word_timing_are_untouched(self):
        words = (LyricWord("go", 1.), )
        line = LyricLine(1, "go", words)
        merged = merge(Lyrics([line, LyricLine(5, "run now")]), {0: [9.], 1: [5., 5.5]})
        self.assertEqual(merged.lines[0], line)
        self.assertTrue(merged.lines[1].words)

    def test_a_count_mismatch_is_skipped(self):
        lyrics = Lyrics([LyricLine(1, "go now then")])
        merged = merge(lyrics, {0: [1., 2.]})
        self.assertEqual(merged.lines, lyrics.lines)
        self.assertEqual(merged.timing_source, "")

    def test_a_line_number_past_the_end_is_skipped(self):
        lyrics = Lyrics([LyricLine(1, "go")])
        self.assertEqual(merge(lyrics, {9: [1.]}).lines, lyrics.lines)

    def test_times_out_of_order_are_skipped(self):
        lyrics = Lyrics([LyricLine(1, "go now")])
        self.assertEqual(merge(lyrics, {0: [2., 1.]}).timing_source, "")

    def test_offset_is_not_baked_in(self):
        merged = merge(Lyrics([LyricLine(1, "go now")]), {0: [1., 1.5]})
        self.assertEqual(merged.lines[0].words[0].start, 1.)

    def test_the_source_lyrics_keep_their_identity(self):
        lyrics = Lyrics([LyricLine(1, "go")], "Line-synced lyrics", source_id="42", selected_record={"id": 42})
        merged = merge(lyrics, {0: [1.]})
        self.assertEqual((merged.message, merged.source_id, merged.selected_record), (lyrics.message, "42", {"id": 42}))
        self.assertEqual(lyrics.lines[0].words, ())


if __name__ == "__main__":
    unittest.main()
