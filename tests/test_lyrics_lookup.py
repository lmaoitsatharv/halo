import unittest
from unittest.mock import Mock
from halo.lyrics import LyricsWorker
from halo.models import Track, eligible_match, title_search_variants


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.track = Track("Falling in Moon Light", "Example Artist", "Original release", 120)
        self.worker = LyricsWorker()
        self.results = []
        self.worker.ready.connect(lambda generation, result: self.results.append(result))
        self.plain = {"trackName": self.track.title, "artistName": self.track.artist,
                      "albumName": self.track.album, "duration": 120, "plainLyrics": "Original untimed text"}
        self.timed = {"trackName": "Fallin' in Moonlight", "artistName": self.track.artist,
                      "albumName": "Another release", "duration": 121,
                      "syncedLyrics": "[00:02]First original line\n[00:07]Second original line"}

    def test_plain_exact_result_does_not_stop_timed_search(self):
        self.worker.request = Mock(return_value=[self.plain, self.timed])
        self.worker.fetch(self.track, 1)
        self.assertEqual(len(self.results[0].lines), 2)
        self.assertEqual(self.worker.request.call_count, 1)

    def test_spelling_search_finds_contracted_compound_title(self):
        def request(endpoint, params):
            if endpoint == "get":
                return self.plain
            return [self.timed] if params["track_name"] == "fallin' in moonlight" else []
        self.worker.request = Mock(side_effect=request)
        self.worker.fetch(self.track, 1)
        self.assertEqual(len(self.results[0].lines), 2)
        self.assertIn("fallin' in moonlight", title_search_variants(self.track.title))

    def test_wrong_artist_or_longer_recording_cannot_override_plain(self):
        other_artist = {**self.timed, "artistName": "Cover Artist"}
        longer = {**self.timed, "duration": 135}
        self.worker.request = Mock(side_effect=lambda endpoint, params:
                                   self.plain if endpoint == "get" else [self.plain, other_artist, longer])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].lines, [])
        self.assertIn("untimed", self.results[0].message)

    def test_single_cue_is_not_claimed_as_synced(self):
        single = {**self.plain, "syncedLyrics": "[00:00]All original text in one cue"}
        self.worker.request = Mock(side_effect=lambda endpoint, params: single if endpoint == "get" else [single])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].lines, [])

    def test_good_catalog_record_needs_no_signature_request(self):
        self.worker.request = Mock(return_value=[self.timed])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.worker.request.call_count, 1)
        self.assertEqual(len(self.results[0].lines), 2)

    def test_incomplete_catalog_records_do_not_block_valid_lyrics(self):
        broken = [{**self.timed, "duration": value} for value in (None, "", "unknown", float("nan"), float("inf"))]
        broken.extend([{**self.timed, "trackName": None}, {**self.timed, "artistName": None}, None])
        self.worker.request = Mock(return_value=[*broken, self.timed])
        self.worker.fetch(self.track, 1)
        self.assertEqual(len(self.results[0].lines), 2)
        self.assertEqual(self.worker.request.call_count, 1)

    def test_missing_duration_rejected_even_without_spotify_duration(self):
        unknown_duration = Track(self.track.title, self.track.artist)
        self.assertFalse(eligible_match({**self.timed, "duration": None}, unknown_duration))
        self.assertTrue(eligible_match({**self.timed, "duration": "121"}, self.track))

    def test_empty_catalog_retains_signature_fallback(self):
        self.worker.request = Mock(side_effect=lambda endpoint, params: self.timed if endpoint == "get" else [])
        self.worker.fetch(self.track, 1)
        self.assertEqual(len(self.results[0].lines), 2)
        self.assertEqual(self.worker.request.call_args.args[0], "get")

    def test_stale_lookup_stops_before_next_search(self):
        def request(endpoint, params):
            self.worker.latest_generation = 2
            return [self.plain]
        self.worker.latest_generation = 1
        self.worker.request = Mock(side_effect=request)
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.worker.request.call_count, 1)
        self.assertFalse(self.results)

    def test_known_spelling_changes_and_suffix_rejection(self):
        track = Track("Rain Drops Keep Falling on My Head", "B.J. Thomas", duration=169.687)
        match = {"trackName": "Raindrops Keep Fallin’ on My Head", "artistName": "B.J.Thomas", "duration": 172}
        self.assertTrue(eligible_match(match, track))
        self.assertFalse(eligible_match({**match, "trackName": match["trackName"] + " (Live)"}, track))


if __name__ == "__main__":
    unittest.main()
