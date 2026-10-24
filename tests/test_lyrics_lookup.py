import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from halo.lyrics import LyricsWorker
from halo.models import Track, eligible_match, title_search_variants
from halo.lyric_matching import MAX_METADATA_CHARS, recording_match, version_labels


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

    def test_signature_route_rejects_wrong_recording(self):
        for change in ({"artistName": "Cover Artist"}, {"duration": 150},
                       {"trackName": self.track.title + " (Live)"},
                       {"albumName": "Live at the Example Hall"}):
            with self.subTest(change=change):
                worker = LyricsWorker()
                found = []
                worker.ready.connect(lambda _, result: found.append(result))
                worker.request = Mock(side_effect=lambda endpoint, params:
                                      {**self.timed, **change} if endpoint == "get" else [])
                worker.fetch(self.track, 1)
                self.assertFalse(found[0].lines)

    def test_bad_signature_does_not_erase_valid_plain_candidate(self):
        self.worker.request = Mock(side_effect=lambda endpoint, params:
                                   {**self.timed, "artistName": "Cover Artist"}
                                   if endpoint == "get" else [self.plain])
        self.worker.fetch(self.track, 1)
        self.assertIn("untimed", self.results[0].message)

    def test_album_ranking_normalizes_punctuation_and_case(self):
        close_duration = {**self.timed, "id": 2, "duration": 120}
        correct_album = {**self.timed, "id": 3, "albumName": "ORIGINAL RELEASE!", "duration": 121}
        self.worker.request = Mock(return_value=[close_duration, correct_album])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "3")

    def test_album_labels_do_not_confuse_arbitrary_album_names(self):
        self.assertEqual(version_labels("Original", "Live Through This"), frozenset())
        self.assertEqual(version_labels("Live Forever", "Definitely Maybe"), frozenset())
        self.assertIn("live", version_labels("Original", "Live at Example Hall"))
        self.assertIn("acoustic", version_labels("Original", "Original (Acoustic)"))
        self.assertFalse(recording_match({**self.timed, "albumName": "Original (Acoustic)"}, self.track))

    def test_oversized_catalogue_metadata_is_rejected_before_identity_or_regex_work(self):
        for field in ("trackName", "artistName", "albumName"):
            with self.subTest(field=field), patch("halo.lyric_matching.eligible_match") as identity:
                with patch("halo.lyric_matching.version_labels") as labels:
                    self.assertFalse(recording_match({**self.timed, field: "[" * (MAX_METADATA_CHARS + 1)}, self.track))
                    identity.assert_not_called()
                    labels.assert_not_called()

    def test_rejected_large_metadata_does_not_hide_a_good_worker_result(self):
        malformed = {**self.timed, "id": 1, "albumName": "[" * 8000}
        good = {**self.timed, "id": 2}
        self.worker.request = Mock(return_value=[malformed, good])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "2")
        self.assertEqual(len(self.results[0].lines), 2)

    def test_unclosed_brackets_and_regular_version_labels_remain_safe(self):
        self.assertEqual(version_labels("Original", "[" * MAX_METADATA_CHARS), frozenset())
        self.assertEqual(version_labels("Original (Live)", "[" * MAX_METADATA_CHARS), frozenset({"live"}))
        self.assertIn("acoustic", version_labels("Original", "Release [Edition (Acoustic)]"))

    def test_version_label_scans_bound_each_field_before_parsing(self):
        with patch("halo.lyric_matching._bracketed_labels", return_value=[]) as labels:
            version_labels("x" * (MAX_METADATA_CHARS * 4), "y" * (MAX_METADATA_CHARS * 4))
        self.assertEqual([len(call.args[0]) for call in labels.call_args_list], [MAX_METADATA_CHARS] * 2)

    def test_choices_are_safe_bounded_metadata_and_selection_keeps_automatic_lookup_separate(self):
        choices = []
        self.worker.choices_ready.connect(lambda _, items: choices.extend(items))
        records = [{**self.timed, "id": i, "albumName": "Release " + str(i)} for i in range(1, 45)]
        records.extend([{**self.timed, "id": 99, "artistName": "Cover Artist"}])
        self.worker.request = Mock(return_value=records)
        self.worker.list_choices(self.track, 1)
        self.assertEqual(len(choices), 30)
        self.assertTrue(all(isinstance(item["id"], str) and "syncedLyrics" not in item for item in choices))
        self.worker.select_candidate(self.track, 1, "2")
        self.assertEqual(self.results[-1].source_id, "2")
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[-1].source_id, "1")

    def test_choice_cannot_be_reused_for_another_recording_or_unknown_id(self):
        self.worker.request = Mock(return_value=[{**self.timed, "id": 123}])
        self.worker.list_choices(self.track, 1)
        self.worker.select_candidate(Track("Different Song", self.track.artist, duration=120), 1, "123")
        self.assertFalse(self.results[-1].lines)
        self.worker.select_candidate(self.track, 1, "777")
        self.assertFalse(self.results[-1].lines)
        self.assertEqual(self.worker.request.call_count, len(title_search_variants(self.track.title)))

    def test_stale_choices_never_emit_or_overwrite_current_choices(self):
        found = []
        self.worker.choices_ready.connect(lambda _, items: found.append(items))
        self.worker.latest_generation = 1
        def request(endpoint, params):
            self.worker.latest_generation = 2
            return [{**self.timed, "id": 123}]
        self.worker.request = Mock(side_effect=request)
        self.worker.list_choices(self.track, 1)
        self.assertFalse(found)
        self.assertIsNone(self.worker.choice_key)

    def test_search_and_get_results_are_deduplicated(self):
        self.worker.request = Mock(return_value=[{**self.timed, "id": 123}] * 100)
        found = []
        self.worker.choices_ready.connect(lambda _, items: found.extend(items))
        self.worker.list_choices(self.track, 1)
        self.assertEqual(len(found), 1)

    def test_stale_http_failure_is_not_emitted(self):
        self.worker.latest_generation = 1
        def request(endpoint, params):
            self.worker.latest_generation = 2
            raise HTTPError("https://lrclib.net/api/search", 503, "busy", {}, None)
        self.worker.request = Mock(side_effect=request)
        self.worker.fetch(self.track, 1)
        self.assertFalse(self.results)

    def test_invalid_current_duration_cannot_crash_worker_or_select_any_recording(self):
        for duration in (float("nan"), float("inf"), -1):
            with self.subTest(duration=duration):
                track = Track(self.track.title, self.track.artist, duration=duration)
                worker = LyricsWorker()
                found = []
                worker.ready.connect(lambda _, result: found.append(result))
                worker.request = Mock(return_value=[self.timed])
                worker.fetch(track, 1)
                self.assertFalse(found[0].lines)

    def test_exact_album_survives_large_search_before_choice_limit(self):
        distractors = [{**self.timed, "id": i, "albumName": "Other release"} for i in range(1, 40)]
        self.worker.request = Mock(return_value=[*distractors, {**self.timed, "id": 99,
                                      "albumName": self.track.album}])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "99")

    def test_true_word_timing_wins_when_recording_confidence_is_equal(self):
        line_record = {**self.timed, "id": 1}
        word_record = {**self.timed, "id": 2,
                       "syncedLyrics": "[00:02]<00:02>First <00:03>line\n[00:07]<00:07>Second <00:08>line"}
        self.worker.request = Mock(return_value=[line_record, word_record])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "2")
        self.assertTrue(self.results[0].selected_record["word_synced"])

    def test_malformed_optional_album_does_not_block_valid_recording(self):
        self.worker.request = Mock(return_value=[{**self.timed, "albumName": ["Malformed"]},
                                                 {**self.timed, "id": 2, "albumName": self.track.album}])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "2")

    def test_single_line_with_actual_word_cues_is_usable(self):
        record = {**self.timed, "id": 1, "syncedLyrics": "[00:02]<00:02>First <00:03>line"}
        self.worker.request = Mock(return_value=[record])
        self.worker.fetch(self.track, 1)
        self.assertTrue(self.results[0].has_word_timing)
        self.assertEqual(len(self.results[0].lines), 1)

    def test_user_edits_and_cover_labels_rejected_but_remasters_remain_eligible(self):
        for album in (self.track.album + " (AshMV edit)", self.track.album + " (Cover)"):
            with self.subTest(album=album):
                self.assertFalse(recording_match({**self.timed, "albumName": album}, self.track))
        for album in (self.track.album + " (2011 Remastered)", self.track.album + " (Deluxe Edition)"):
            with self.subTest(album=album):
                self.assertTrue(recording_match({**self.timed, "albumName": album}, self.track))

    def test_later_spelling_query_can_replace_full_choices_with_exact_album(self):
        distractors = [{**self.timed, "id": i, "albumName": "Other release"} for i in range(1, 31)]
        desired = {**self.timed, "id": 999, "albumName": self.track.album}
        self.worker.request = Mock(side_effect=lambda endpoint, params:
                                   distractors if params["track_name"] == self.track.title else [desired])
        choices = []
        self.worker.choices_ready.connect(lambda _, found: choices.extend(found))
        self.worker.list_choices(self.track, 1)
        self.assertEqual(len(choices), 30)
        self.assertEqual(choices[0]["id"], "999")

    def test_real_word_candidate_beyond_initial_choice_limit_survives(self):
        distractors = [{**self.timed, "id": i} for i in range(1, 31)]
        desired = {**self.timed, "id": 999,
                   "syncedLyrics": "[00:02]<00:02>First <00:03>line\n[00:07]<00:07>Second <00:08>line"}
        self.worker.request = Mock(return_value=[*distractors, desired])
        self.worker.fetch(self.track, 1)
        self.assertEqual(self.results[0].source_id, "999")


if __name__ == "__main__":
    unittest.main()
