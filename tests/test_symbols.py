"""Lyric words choose Lucide symbols, which are built on demand and drawn as outlines."""
import inspect
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from halo.lyric_rendering import SYMBOLS, SymbolPaths, _lexicon_word, line_symbol_kind, symbol_kind, symbol_path
from halo.symbol_lexicon import KINDS, WORD_KINDS
from halo.widgets import LyricCanvas

ROOT = Path(__file__).resolve().parent.parent


class SymbolKindTests(unittest.TestCase):
    def test_endings_find_the_base_word(self):
        self.assertEqual(symbol_kind("Dreaming,"), symbol_kind("dream"))
        self.assertEqual(symbol_kind("hearts"), symbol_kind("heart"))
        self.assertEqual(symbol_kind("lovin’"), symbol_kind("love"))
        self.assertEqual(symbol_kind("burned"), symbol_kind("burn"))

    def test_every_ending_is_removed(self):
        for word, base in (("love's", "love"), ("moon’s", "moon"), ("singing", "sing"), ("crying", "cry"),
                           ("singin", "sing"), ("lovin'", "love"), ("walked", "walk"), ("branches", "branch"),
                           ("wishes", "wish"), ("dies", "die"), ("hugs", "hug")):
            with self.subTest(word=word):
                self.assertFalse(word in WORD_KINDS)
                self.assertEqual(symbol_kind(word), WORD_KINDS[base])

    def test_a_final_e_is_restored_after_ing_in_and_ed_only(self):
        for word, base in (("dancing", "dance"), ("lovin", "love"), ("danced", "dance"), ("tied", "tie")):
            with self.subTest(word=word):
                self.assertFalse(word in WORD_KINDS)
                self.assertEqual(symbol_kind(word), WORD_KINDS[base])
        self.assertEqual(symbol_kind("plans"), "star")
        self.assertEqual(symbol_kind("taps"), "star")

    def test_the_restored_e_wins_over_a_shorter_word(self):
        for word in ("cared", "caring", "carin", "Caring,"):
            with self.subTest(word=word):
                self.assertEqual(symbol_kind(word), "hand-heart")
        self.assertEqual(symbol_kind("car"), "car")
        self.assertEqual(symbol_kind("cars"), "car")
        self.assertEqual(symbol_kind("wining"), symbol_kind("wine"))

    def test_a_plural_finds_the_longer_word_before_the_shorter_one(self):
        self.assertEqual(symbol_kind("cares"), "hand-heart")
        self.assertEqual(symbol_kind("wines"), symbol_kind("wine"))
        self.assertEqual(symbol_kind("breathes"), symbol_kind("breathe"))
        self.assertNotEqual(symbol_kind("wines"), symbol_kind("win"))

    def test_es_plurals_still_reach_their_base_word(self):
        self.assertEqual(symbol_kind("buses"), "bus")
        self.assertEqual(symbol_kind("boxes"), "package")
        self.assertEqual(symbol_kind("branches"), symbol_kind("branch"))

    def test_the_word_itself_is_matched_before_any_ending_is_removed(self):
        self.assertEqual(symbol_kind("glass"), "glass-water")
        self.assertEqual(symbol_kind("glasses"), "glasses")
        self.assertEqual(symbol_kind("buses"), "bus")

    def test_forms_the_endings_cannot_reach_are_listed(self):
        self.assertEqual(symbol_kind("cried"), symbol_kind("cry"))

    def test_stems_shorter_than_three_letters_are_ignored(self):
        self.assertEqual(symbol_kind("uses"), "star")
        self.assertEqual(symbol_kind("added"), "star")
        with patch.dict("halo.lyric_rendering.WORD_KINDS", {"py": "sprout"}):
            self.assertIsNone(_lexicon_word("pies"))

    def test_wrapping_punctuation_is_stripped(self):
        for word, base in (("(love)", "love"), ("“moon”", "moon"), ("heart…", "heart"), ("rain—", "rain"),
                           ("(“dreams”…)", "dreams")):
            with self.subTest(word=word):
                self.assertEqual(symbol_kind(word), WORD_KINDS[base])

    def test_ies_finds_the_word_ending_in_y(self):
        for word, base in (("skies", "sky"), ("cries", "cry"), ("cities", "city"), ("flies", "fly")):
            with self.subTest(word=word):
                self.assertFalse(word in WORD_KINDS)
                self.assertEqual(symbol_kind(word), WORD_KINDS[base])

    def test_tries_reaches_try_once_that_word_is_listed(self):
        self.assertIsNone(_lexicon_word("tries"))
        with patch.dict("halo.lyric_rendering.WORD_KINDS", {"try": "sprout"}):
            self.assertEqual(_lexicon_word("tries"), "try")

    def test_a_word_ending_in_ie_still_wins_over_y(self):
        self.assertEqual(symbol_kind("ties"), WORD_KINDS["tie"])
        self.assertEqual(symbol_kind("movies"), WORD_KINDS["movie"])

    def test_a_doubled_consonant_is_made_single_before_ing_and_ed(self):
        for word, base in (("swimming", "swim"), ("sitting", "sit"), ("winning", "win"), ("dropped", "drop"),
                           ("hugged", "hug"), ("shopping", "shop")):
            with self.subTest(word=word):
                self.assertFalse(word in WORD_KINDS)
                self.assertEqual(symbol_kind(word), WORD_KINDS[base])

    def test_a_listed_form_wins_over_undoubling(self):
        self.assertEqual(symbol_kind("wedding"), "church")
        self.assertEqual(symbol_kind("selling"), WORD_KINDS["sell"])
        self.assertEqual(symbol_kind("kissed"), WORD_KINDS["kiss"])

    def test_only_consonants_are_made_single(self):
        with patch.dict("halo.lyric_rendering.WORD_KINDS", {"fle": "sprout"}):
            self.assertIsNone(_lexicon_word("fleeing"))

    def test_only_ing_and_ed_make_a_consonant_single(self):
        self.assertEqual(symbol_kind("swimms"), "star")
        self.assertEqual(symbol_kind("cabbin"), "star")

    def test_cabin_is_a_house_not_a_cab(self):
        self.assertEqual(WORD_KINDS["cabin"], "house")
        self.assertEqual(symbol_kind("cabin"), "house")
        self.assertEqual(symbol_kind("cab"), WORD_KINDS["cab"])

    def test_unknown_words_use_the_fallback(self):
        for word in ("zzqx", "amor", "", "♪", "original", "quiet", "phrase", "ing", "'s"):
            with self.subTest(word=word):
                self.assertEqual(symbol_kind(word), "star")

    def test_results_are_cached(self):
        self.assertEqual(symbol_kind.cache_info().maxsize, 1024)

    def test_concrete_words_beat_weak_words(self):
        self.assertEqual(line_symbol_kind("You and the ocean"), "wave")
        self.assertEqual(line_symbol_kind("You and us"), "heart")
        self.assertEqual(line_symbol_kind("Days like the ocean"), "wave")

    def test_dreams_and_fire_keep_their_kinds(self):
        self.assertEqual(symbol_kind("dream"), "moon")
        self.assertEqual(symbol_kind("burn"), "flame")


class WordListFixTests(unittest.TestCase):
    def test_pairings_that_misled_use_the_fallback(self):
        for word in ("butterfly", "soccer", "football", "fair", "black", "white", "calendar", "month",
                     "year", "years", "smoke", "roll", "ring", "whiskey", "blind"):
            with self.subTest(word=word):
                self.assertFalse(word in WORD_KINDS)
                self.assertEqual(symbol_kind(word), "star")

    def test_words_from_the_old_mapping_are_back(self):
        for word, kind in (("air", "wind"), ("blew", "wind"), ("glow", "sun"), ("vision", "eye")):
            with self.subTest(word=word):
                self.assertEqual(WORD_KINDS[word], kind)
                self.assertEqual(symbol_kind(word), kind)

    def test_space_and_fair_words_use_icons_that_do_not_read_as_rings(self):
        self.assertFalse({"orbit", "ferris-wheel"} & set(KINDS))
        for word in ("planet", "universe", "cosmos", "space", "galaxy"):
            with self.subTest(word=word):
                self.assertIn(symbol_kind(word), {"rocket", "telescope"})
        for word in ("carnival", "circus"):
            with self.subTest(word=word):
                self.assertEqual(symbol_kind(word), "party-popper")


class SymbolPathTests(unittest.TestCase):
    def test_paths_are_built_only_when_needed(self):
        paths = SymbolPaths()
        self.assertEqual(paths.built, 0)
        self.assertFalse(paths["moon"].isEmpty())
        self.assertEqual(paths.built, 1)
        paths["moon"]
        self.assertEqual(paths.built, 1)
        self.assertEqual(len(paths), len(KINDS))
        self.assertEqual(paths.built, 1)
        with self.assertRaises(KeyError):
            paths["nope"]
        self.assertEqual(set(paths), set(KINDS))

    def test_every_kind_has_a_path_inside_the_unit_box(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertFalse(SYMBOLS[kind].isEmpty())
                box = SYMBOLS[kind].boundingRect()
                self.assertLessEqual(max(abs(box.left()), abs(box.right()), abs(box.top()), abs(box.bottom())), 1.3)

    def test_symbol_path_rejects_an_unknown_kind(self):
        with self.assertRaises(KeyError):
            symbol_path("nope")

    def test_lucide_geometry_loads_with_the_first_path_not_at_import(self):
        code = ("import sys; import halo.lyric_rendering as r; r.symbol_kind('love'); "
                "print('halo.lucide_data' in sys.modules); "
                "r.SYMBOLS['heart']; print('halo.lucide_data' in sys.modules)")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.split(), ["False", "True"])


class SymbolDrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def canvas(self, surface):
        controller = SimpleNamespace(primary=QColor("#bddbd0"), reduced_motion=False)
        canvas = LyricCanvas(controller, surface)
        self.addCleanup(canvas.close)
        return canvas

    def test_symbols_are_outlines_without_a_fill(self):
        for surface in ("preview", "floating", "immersive"):
            for draw in ("symbol", "line_emblem"):
                with self.subTest(surface=surface, draw=draw):
                    canvas = self.canvas(surface)
                    image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    spy = Mock(wraps=painter)
                    try:
                        if draw == "symbol":
                            canvas._symbol(spy, "heart", 80, 80, 20, 1, 1)
                        else:
                            canvas._line_emblem(spy, "heart", 80, 80, 20, 1, 1, 2)
                        brush, drawn = None, 0
                        for call in spy.mock_calls:
                            if call[0] == "setBrush":
                                brush = call.args[0]
                            elif call[0] == "drawPath":
                                drawn += 1
                                self.assertEqual(brush, Qt.BrushStyle.NoBrush)
                        self.assertGreater(drawn, 0)
                    finally:
                        painter.end()

    def test_symbol_no_longer_has_a_subdued_variant(self):
        self.assertNotIn("subdued", inspect.signature(LyricCanvas._symbol).parameters)


if __name__ == "__main__":
    unittest.main()
