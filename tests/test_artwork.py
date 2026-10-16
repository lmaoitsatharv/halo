import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from halo.artwork import ArtworkWorker, matching_releases, valid_artwork, read_public
from halo.models import Track
from test_session_artwork import cover

CD = "07928ae6-6d8d-48c6-a75e-99967034b52a"
DIGITAL = "5dad2cd0-fda8-436a-8c18-38ea8a2e9c40"


def catalog():
    return [{"title": "What's Up Danger", "length": 222306,
             "artist-credit": [{"name": "Blackway"}, {"name": "Black Caviar"}],
             "releases": [{"id": CD, "title": "The Album", "status": "Official", "country": "US",
                           "media": [{"format": "CD"}]},
                          {"id": DIGITAL, "title": "The Album", "status": "Official", "country": "XW",
                           "media": [{"format": "Digital Media"}]}]}]


class ArtworkLookupTests(unittest.TestCase):
    def setUp(self):
        self.track = Track("What's Up Danger (with Black Caviar)", "Blackway", "The Album", 222.306,
                           connected=True)

    def test_match_requires_credited_collaborator_and_prefers_digital_cover(self):
        self.assertEqual(matching_releases(catalog(), self.track), [DIGITAL, CD])
        records = catalog()
        records[0]["artist-credit"].pop()
        self.assertEqual(matching_releases(records, self.track), [])

    def test_other_artist_album_version_duration_and_unknown_length_are_rejected(self):
        for field, value in (("title", "What's Up Danger (live)"), ("title", "What's Up Danger (Remix)"),
                             ("artist-credit", [{"name": "A cover artist"}]), ("length", 240000),
                             ("length", None), ("length", float("nan"))):
            with self.subTest(field=field, value=value):
                records = catalog()
                records[0][field] = value
                self.assertEqual(matching_releases(records, self.track), [])
        records = catalog()
        for release in records[0]["releases"]:
            release["title"] = "Other album"
        self.assertEqual(matching_releases(records, self.track), [])

    def test_invalid_image_and_unapproved_urls_are_rejected_before_fetching(self):
        self.assertTrue(valid_artwork(cover("blue")))
        self.assertFalse(valid_artwork(b"<html>not a cover</html>"))
        self.assertFalse(valid_artwork(b"x" * 5_000_001))
        for url in ("http://coverartarchive.org/", "https://example.com/", "https://musicbrainz.org.evil.test/",
                    "file:///C:/Windows/win.ini", "https://user:pass@musicbrainz.org/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                read_public(url, 100, "image/*")

    def worker(self):
        worker = ArtworkWorker()
        worker.latest_key = self.track.key
        output = []
        worker.ready.connect(lambda *args: output.append(args))
        return worker, output

    def test_success_is_cached_and_has_no_second_network_request(self):
        worker, output = self.worker()
        image = cover("purple")
        with patch("halo.artwork.read_public", side_effect=[json.dumps({"recordings": catalog()}).encode(), image]) as read:
            worker.fetch(self.track)
            worker.fetch(self.track)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(output, [(self.track.key, image)] * 2)
        self.assertIn(DIGITAL, read.call_args_list[1].args[0])

    def test_missing_cover_tries_another_matched_release_and_handles_offline(self):
        worker, output = self.worker()
        image = cover("cyan")
        with patch("halo.artwork.read_public", side_effect=[json.dumps({"recordings": catalog()}).encode(),
                   HTTPError("https://coverartarchive.org", 404, "No image", {}, None), image]):
            worker.fetch(self.track)
        self.assertEqual(output, [(self.track.key, image)])
        worker, output = self.worker()
        with patch("halo.artwork.read_public", side_effect=OSError("offline")) as read:
            worker.fetch(self.track)
            worker.fetch(self.track)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(output, [(self.track.key, b"")] * 2)

    def test_song_change_during_search_stops_the_obsolete_download(self):
        worker, output = self.worker()
        def search(*args):
            worker.latest_key = ("Other song", "Other artist", "Other album")
            return json.dumps({"recordings": catalog()}).encode()
        with patch("halo.artwork.read_public", side_effect=search) as read:
            worker.fetch(self.track)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(output, [])
        self.assertEqual(worker.cache, {})
