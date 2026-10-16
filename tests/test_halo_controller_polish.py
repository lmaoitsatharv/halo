from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from halo.app import Controller


class HaloControllerPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".cache"
        self.temp = tempfile.TemporaryDirectory(prefix="halo-polish-settings-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.
        clock = patch("halo.app.time", SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.controllers = []
        self.addCleanup(self.close_controllers)

    def close_controllers(self):
        for c in self.controllers:
            c.close()
            c.audio.thread.join(1)

    def controller(self, values=None):
        settings = QSettings(str(Path(self.temp.name) / "settings.ini"), QSettings.Format.IniFormat)
        for name, value in (values or {}).items():
            settings.setValue(name, value)
        c = Controller(settings, offline=True)
        c.timer.stop()
        self.controllers.append(c)
        return c

    def test_custom_black_is_preserved_while_lyrics_remain_readable(self):
        c = self.controller({"palette": "Custom", "custom_primary": "#000000", "custom_secondary": "#005dff"})
        self.assertEqual(c.halo_primary.name(), "#000000")
        self.assertEqual(c.halo_secondary.name(), "#005dff")
        self.assertGreater(c.primary.valueF(), .89)

    def test_late_cover_refreshes_artwork_and_palette_without_resetting_lyrics(self):
        from dataclasses import replace
        from halo.models import Track, Lyrics, LyricLine
        from halo.widgets import Artwork
        from test_session_artwork import cover
        c = self.controller()
        c.requestLyrics.disconnect(c.lyrics_worker.fetch)
        lookups = []
        c.requestLyrics.connect(lambda *args: lookups.append(args))
        track = Track("Song", "Artist", "Album", 200, 30, True, True)
        c.accept_track(track)
        lyrics = Lyrics([LyricLine(0., "Original demo words")])
        c.lyrics = lyrics
        generation, signature = c.generation, c.lookup_signature
        widget = Artwork(c)
        self.addCleanup(widget.close)
        self.assertTrue(widget.pixmap.isNull())
        with patch.object(c, "update_palette", wraps=c.update_palette) as palette:
            c.accept_track(replace(track, artwork=cover("#ee1177")))
            palette.assert_called_once()
        self.assertFalse(widget.pixmap.isNull())
        self.assertIs(c.lyrics, lyrics)
        self.assertEqual(c.generation, generation)
        self.assertEqual(c.lookup_signature, signature)
        self.assertEqual(len(lookups), 1)

    def test_online_cover_is_opt_in_and_late_results_cannot_replace_native_or_next_song(self):
        from dataclasses import replace
        from halo.models import Track
        from test_session_artwork import cover
        c = self.controller()
        c.requestLyrics.disconnect(c.lyrics_worker.fetch)
        c.requestArtwork.disconnect(c.artwork_worker.fetch)
        requests = []
        c.requestArtwork.connect(lambda track: requests.append(track))
        first = Track("First", "Artist", "Album", 200, connected=True)
        c.accept_track(first)
        self.assertEqual(requests, [])
        c.set("artwork_online", True)
        self.assertEqual([t.key for t in requests], [first.key])
        fallback, native = cover("red"), cover("blue")
        c.accept_artwork(first.key, fallback)
        c.accept_track(replace(first, position=10))
        self.assertEqual(c.track.artwork, fallback)
        c.accept_track(replace(first, artwork=native))
        c.accept_artwork(first.key, fallback)
        self.assertEqual(c.track.artwork, native)
        second = replace(first, title="Second", artwork=b"")
        c.accept_track(second)
        c.accept_artwork(first.key, fallback)
        self.assertEqual(c.track.key, second.key)
        self.assertEqual(c.track.artwork, b"")
        c.set("artwork_online", False)
        c.accept_artwork(second.key, fallback)
        self.assertEqual(c.track.artwork, b"")

    def test_independent_controls_persist_and_old_width_setting_migrates(self):
        c = self.controller({"width": 89})
        self.assertEqual(c.glow_width, 89)
        selected = {"rim_width": 7, "glow_opacity": 40, "primary_brightness": 30,
                    "secondary_brightness": 90, "color_mix": 73,
                    "custom_primary": "#000000", "custom_secondary": "#005dff"}
        for name, value in selected.items():
            c.set(name, value)
        c.settings.sync()
        restored = self.controller()
        for name, value in selected.items():
            self.assertEqual(getattr(restored, name), value)
        self.assertEqual(restored.glow_width, 89)

    def test_animation_and_audio_checkbox_do_not_contradict_each_other(self):
        c = self.controller()
        c.set("reactive", True)
        self.assertEqual(c.halo_animation, "music")
        c.set("halo_animation", "idle")
        self.assertFalse(c.reactive)
        c.set("halo_animation", "music")
        self.assertTrue(c.reactive)
        c.set("reactive", False)
        self.assertEqual(c.halo_animation, "flow")

    def test_speed_changes_preserve_phase_and_pause_cannot_accumulate_a_leap(self):
        c = self.controller()
        c.set_demo(True)
        self.now += .016
        c.tick()
        phase = c.motion_phase
        c.set("motion_speed", 100)
        self.assertEqual(c.motion_phase, phase)
        self.now += .016
        c.tick()
        self.assertAlmostEqual(c.motion_phase - phase, .016 * 100 / 45 / 26.28)
        c.transport("toggle")
        paused = c.motion_phase
        self.now += 90
        c.tick()
        self.assertEqual(c.motion_phase, paused)
        c.transport("toggle")
        self.now += .016
        c.tick()
        self.assertLess(c.motion_phase - paused, .002)

    def test_music_envelope_rounds_accents_and_leaves_a_smooth_tail(self):
        from halo.models import Track
        c = self.controller({"halo_animation": "music"})
        # Supply deterministic meter levels without opening the audio device.
        c.audio.close()
        c.audio.thread.join(1)
        c.track = Track(playing=True, connected=True, observed_at=self.now)
        c.audio.level = 1.
        self.now += .016
        c.tick()
        # A hit must be visible immediately without snapping near full light
        # in a single display frame, then reach a strong rounded crest.
        self.assertGreater(c.pulse, .15)
        self.assertLess(c.pulse, .5)
        self.now += .059
        c.tick()
        self.assertGreater(c.pulse, .65)
        self.assertLess(c.pulse, .9)
        c.audio.level = 0.
        self.now += .1
        c.tick()
        self.assertGreater(c.pulse, .35)
        self.assertLess(c.pulse, .65)
        for _ in range(2):
            self.now += .1
            c.tick()
        self.assertGreater(c.pulse, .1)
        self.assertLess(c.pulse, .3)
        for _ in range(6):
            self.now += .1
            c.tick()
        self.assertLess(c.pulse, .03)
        c.set("reduced_motion", True)
        frozen = c.pulse
        c.audio.level = 1.
        self.now += .1
        c.tick()
        self.assertEqual(c.pulse, frozen)
        self.assertFalse(c.audio.enabled)

    def test_palette_change_is_continuous_and_finishes_while_still(self):
        c = self.controller({"palette": "Custom", "custom_primary": "#000000"})
        c.set("halo_animation", "still")
        c.set("custom_primary", "#ff0000")
        self.assertEqual(c.halo_primary.name(), "#000000")
        self.now += .45
        c.tick()
        self.assertNotIn(c.halo_primary.name(), ("#000000", "#ff0000"))
        self.now += .45
        c.tick()
        self.assertEqual(c.halo_primary.name(), "#ff0000")
        self.assertEqual(c.motion_phase, 0.)


if __name__ == "__main__":
    unittest.main()
