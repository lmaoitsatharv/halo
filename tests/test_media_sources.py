"""Any player Windows knows about: which session Halo follows, its name, and cleaned browser titles."""
import unittest

from halo.media_sources import SessionChooser, clean_metadata, is_browser, source_name


SPOTIFY = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
BRAVE = "Brave.R3B3WLJ4IJHTAX5LWM3DTPOC7E"
EDGE = "MSEdge"


class SessionChoiceTests(unittest.TestCase):
    def test_a_playing_browser_wins_over_paused_spotify(self):
        chooser = SessionChooser()
        self.assertEqual(chooser.choose({SPOTIFY: False, BRAVE: True}, SPOTIFY, 0.), BRAVE)

    def test_two_players_at_once_never_flicker_between_them(self):
        chooser = SessionChooser()
        self.assertEqual(chooser.choose({SPOTIFY: True}, SPOTIFY, 0.), SPOTIFY)
        for second in range(1, 20):
            self.assertEqual(chooser.choose({SPOTIFY: True, BRAVE: True}, BRAVE, float(second)), SPOTIFY)

    def test_a_skip_in_the_followed_player_does_not_hand_over_to_another(self):
        chooser = SessionChooser()
        chooser.choose({SPOTIFY: True, BRAVE: True}, SPOTIFY, 0.)
        # Between songs the followed player briefly reports that it is not playing.
        self.assertEqual(chooser.choose({SPOTIFY: False, BRAVE: True}, BRAVE, .5), SPOTIFY)
        self.assertEqual(chooser.choose({SPOTIFY: True, BRAVE: True}, BRAVE, 1.), SPOTIFY)

    def test_pausing_the_followed_player_hands_over_to_the_one_still_playing(self):
        chooser = SessionChooser()
        chooser.choose({SPOTIFY: True, BRAVE: False}, SPOTIFY, 0.)
        chooser.choose({SPOTIFY: False, BRAVE: True}, SPOTIFY, .5)
        self.assertEqual(chooser.choose({SPOTIFY: False, BRAVE: True}, SPOTIFY, 3.), BRAVE)

    def test_with_everything_paused_it_stays_on_the_last_player(self):
        chooser = SessionChooser()
        chooser.choose({SPOTIFY: False, BRAVE: True}, SPOTIFY, 0.)
        self.assertEqual(chooser.choose({SPOTIFY: False, BRAVE: False}, SPOTIFY, 10.), BRAVE)

    def test_a_closed_player_falls_back_to_windows_choice_then_any_other(self):
        chooser = SessionChooser()
        chooser.choose({BRAVE: True}, BRAVE, 0.)
        self.assertEqual(chooser.choose({SPOTIFY: False, EDGE: False}, EDGE, 1.), EDGE)
        self.assertEqual(SessionChooser().choose({SPOTIFY: False}, None, 0.), SPOTIFY)
        self.assertIsNone(SessionChooser().choose({}, None, 0.))

    def test_windows_current_session_breaks_a_tie_between_new_players(self):
        self.assertEqual(SessionChooser().choose({SPOTIFY: True, EDGE: True}, EDGE, 0.), EDGE)


class SourceNameTests(unittest.TestCase):
    def test_known_players_get_their_everyday_names(self):
        for app_id, name in ((SPOTIFY, "Spotify"), (BRAVE, "Brave"), (EDGE, "Edge"), ("Chrome", "Chrome"),
                             ("308046B0AF4A39CB", "Firefox"), ("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App", "Apple Music"),
                             ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Media Player"),
                             ("Vivaldi.ABC123", "Vivaldi"), ("Opera.Stable", "Opera"), ("foobar2000.exe", "foobar2000"),
                             ("", "your player")):
            with self.subTest(app_id=app_id):
                self.assertEqual(source_name(app_id), name)

    def test_browsers_are_told_apart_from_music_apps(self):
        self.assertTrue(is_browser(BRAVE))
        self.assertTrue(is_browser(EDGE))
        self.assertTrue(is_browser("308046B0AF4A39CB"))
        self.assertFalse(is_browser(SPOTIFY))
        self.assertFalse(is_browser("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"))


class CleanMetadataTests(unittest.TestCase):
    def test_music_apps_and_album_carrying_sites_are_left_alone(self):
        self.assertEqual(clean_metadata("Yesterday - Remastered 2009", "The Beatles", "Help!", False),
                         ("Yesterday - Remastered 2009", "The Beatles"))
        self.assertEqual(clean_metadata("Seigfried", "Frank Ocean", "Blonde", True), ("Seigfried", "Frank Ocean"))

    def test_a_youtube_video_title_becomes_the_song(self):
        cases = (
            (("Frank Ocean - Pink + White (Official Audio)", "Frank Ocean"), ("Pink + White", "Frank Ocean")),
            (("Daft Punk - Get Lucky [Official Video] ft. Pharrell Williams", "Daft Punk"), ("Get Lucky", "Daft Punk")),
            (("Sweater Weather (Lyrics)", "The Neighbourhood - Topic"), ("Sweater Weather", "The Neighbourhood")),
            (("Blinding Lights (Official Music Video)", "TheWeekndVEVO"), ("Blinding Lights", "The Weeknd")),
            (("Arijit Singh - Tum Hi Ho | Aashiqui 2 | Full Video Song HD", "T-Series"), ("Tum Hi Ho", "Arijit Singh")),
            (("Glass Animals – Heat Waves (Lyric Video)", "Glass Animals"), ("Heat Waves", "Glass Animals")),
            (("Song Title Official Video HD", "Someone"), ("Song Title", "Someone")),
        )
        for (title, artist), expected in cases:
            with self.subTest(title=title):
                self.assertEqual(clean_metadata(title, artist, "", True), expected)

    def test_a_version_after_a_dash_stays_part_of_the_title(self):
        self.assertEqual(clean_metadata("Yesterday - Remastered 2009", "The Beatles - Topic", "", True),
                         ("Yesterday - Remastered 2009", "The Beatles"))
        self.assertEqual(clean_metadata("Closer - Live", "Someone", "", True), ("Closer - Live", "Someone"))

    def test_cleaning_never_empties_a_title(self):
        self.assertEqual(clean_metadata("(Official Video)", "Someone", "", True), ("(Official Video)", "Someone"))
        self.assertEqual(clean_metadata("", "", "", True), ("", ""))


if __name__ == "__main__":
    unittest.main()
