"""The symbol vocabulary, its Lucide geometry and the tool that bundles it."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from halo.lucide_data import ICONS, LUCIDE_VERSION
from halo.svg_path import icon_path
from halo.symbol_lexicon import KINDS, WEAK_WORDS, WORD_KINDS, WORDS, _word_kinds

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_symbols", ROOT / "tools" / "build_symbols.py")
build_symbols = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_symbols)

SVG = """<!-- @license lucide-static - ISC -->
<svg class="lucide" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  {body}
</svg>
"""


class SymbolLexiconTests(unittest.TestCase):
    def test_vocabulary_size_matches_spec(self):
        self.assertTrue(250 <= len(set(KINDS.values())) <= 300)
        self.assertTrue(700 <= len(WORD_KINDS) <= 800)

    def test_existing_kind_names_survive(self):
        for kind in ("heart", "moon", "sun", "wave", "leaf", "star", "eye", "dice", "wind", "signature"):
            self.assertIn(kind, KINDS)
        self.assertEqual(KINDS["wave"], "waves")
        self.assertEqual(KINDS["star"], "sparkle")

    def test_bundle_holds_exactly_the_icons_in_use(self):
        self.assertEqual(set(ICONS), set(KINDS.values()))

    def test_every_kind_has_words_and_every_word_has_a_kind(self):
        self.assertEqual(set(WORDS), set(KINDS))
        self.assertTrue(all(WORDS[kind] for kind in KINDS))
        self.assertEqual(sum(len(words) for words in WORDS.values()), len(WORD_KINDS))

    def test_no_icon_is_listed_twice_in_the_source(self):
        tree = ast.parse((ROOT / "halo" / "symbol_lexicon.py").read_text(encoding="utf-8"))
        table = next(node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_ENTRIES")
        keys = [key.value for key in table.keys]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), len(KINDS))

    def test_words_are_lower_case_and_keep_star_fallback_cases(self):
        self.assertTrue(all(word == word.lower() for word in WORD_KINDS))
        self.assertTrue({"original", "quiet", "phrase"}.isdisjoint(WORD_KINDS))

    def test_words_are_plain_letters(self):
        self.assertTrue(all(word.isalpha() and word.isascii() for word in WORD_KINDS))

    def test_function_words_stay_out(self):
        function_words = {"the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for", "with",
                          "from", "by", "as", "is", "are", "was", "were", "be", "been", "am", "do", "does",
                          "did", "have", "has", "had", "will", "would", "can", "could", "i", "me", "my",
                          "we", "our", "he", "she", "it", "his", "her", "they", "them", "their", "this",
                          "that", "these", "those", "not", "no", "so", "if", "then", "than", "when", "while"}
        self.assertTrue(function_words.isdisjoint(WORD_KINDS))

    def test_required_words_map_to_their_kinds(self):
        self.assertEqual(WORD_KINDS["ocean"], "wave")
        self.assertEqual(WORD_KINDS["moon"], "moon")
        self.assertEqual(WORD_KINDS["heart"], "heart")
        for word in ("dream", "love", "burn"):
            self.assertIn(word, WORD_KINDS)

    def test_weak_words_are_mapped(self):
        self.assertTrue({"you", "us", "away", "day", "world", "words"} <= WEAK_WORDS)
        self.assertTrue(WEAK_WORDS <= set(WORD_KINDS))

    def test_weak_words_keep_todays_kinds(self):
        self.assertEqual({word: WORD_KINDS[word] for word in WEAK_WORDS},
                         {"you": "heart", "us": "heart", "away": "wind", "day": "sun",
                          "world": "leaf", "words": "signature"})

    def test_a_word_in_two_kinds_is_refused(self):
        with self.assertRaisesRegex(ValueError, "twice"):
            _word_kinds({"heart": ("love", "dear"), "sun": ("dear",)})

    def test_no_enclosing_shapes(self):
        for name, elements in ICONS.items():
            self.assertFalse(name.startswith(("circle-", "square-")), name)
            for tag, attrs in elements:
                if tag == "circle":
                    self.assertLess(float(attrs["r"]), 9, name)

    def test_every_icon_builds_inside_the_unit_box(self):
        for name, elements in ICONS.items():
            box = icon_path(elements).boundingRect()
            self.assertFalse(box.isEmpty() and box.width() == box.height() == 0, name)
            self.assertLessEqual(max(abs(box.left()), abs(box.right()), abs(box.top()), abs(box.bottom())), 1.3, name)

    def test_licence_notice_covers_both_licences(self):
        text = (ROOT / "third_party/lucide/LICENSE").read_text(encoding="utf-8")
        self.assertIn("ISC", text)
        self.assertIn("Cole Bemis", text)

    def test_version_is_recorded(self):
        self.assertRegex(LUCIDE_VERSION, r"^\d+\.\d+\.\d+$")


class BuildSymbolsTests(unittest.TestCase):
    def package(self, **icons):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        package = Path(folder.name) / "package"
        (package / "icons").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": "9.8.7"}), encoding="utf-8")
        for name, body in icons.items():
            (package / "icons" / f"{name}.svg").write_text(SVG.format(body=body), encoding="utf-8")
        return package

    def generated(self, package, names):
        namespace = {}
        exec(build_symbols.build(package, names), namespace)
        return namespace

    def test_generated_module_has_header_version_and_sorted_icons(self):
        package = self.package(zebra='<path d="M2 2h4" />', apple='<circle cx="12" cy="12" r="3" />\n  <line x1="1" y1="2" x2="3" y2="4"/>')
        source = build_symbols.build(package, ["zebra", "apple"])
        self.assertIn("Generated", source.splitlines()[0])
        namespace = self.generated(package, ["zebra", "apple"])
        self.assertEqual(namespace["LUCIDE_VERSION"], "9.8.7")
        self.assertEqual(list(namespace["ICONS"]), ["apple", "zebra"])
        self.assertEqual(namespace["ICONS"]["apple"],
                         (("circle", {"cx": "12", "cy": "12", "r": "3"}),
                          ("line", {"x1": "1", "y1": "2", "x2": "3", "y2": "4"})))

    def test_extra_icons_in_the_package_are_left_out(self):
        package = self.package(one='<path d="M1 1h2" />', two='<path d="M2 2h2" />')
        self.assertEqual(list(self.generated(package, ["one"])["ICONS"]), ["one"])

    def test_missing_icon_stops_with_its_name(self):
        package = self.package(one='<path d="M1 1h2" />')
        with self.assertRaisesRegex(build_symbols.IconError, "no-such-icon"):
            build_symbols.build(package, ["one", "no-such-icon"])

    def test_every_problem_is_reported_together(self):
        package = self.package(ring='<circle cx="12" cy="12" r="10" />', group='<g><path d="M1 1h2" /></g>')
        with self.assertRaises(build_symbols.IconError) as caught:
            build_symbols.build(package, ["ring", "group", "gone"])
        message = str(caught.exception)
        for name in ("ring", "group", "gone"):
            self.assertIn(name, message)

    def test_enclosing_shapes_are_refused(self):
        for name, body in (("ring", '<circle cx="12" cy="12" r="9" />'),
                           ("oval", '<ellipse cx="12" cy="12" rx="10" ry="4" />'),
                           ("frame", '<rect width="20" height="20" x="2" y="2" rx="2" />')):
            with self.subTest(name=name), self.assertRaisesRegex(build_symbols.IconError, name):
                build_symbols.build(self.package(**{name: body}), [name])
        with self.assertRaisesRegex(build_symbols.IconError, "circle-alert"):
            build_symbols.build(self.package(**{"circle-alert": '<path d="M1 1h2" />'}), ["circle-alert"])
        self.generated(self.package(eye='<circle cx="12" cy="12" r="3" /><rect width="20" height="8" x="2" y="8" />'),
                       ["eye"])

    def test_unsupported_elements_and_transforms_are_refused(self):
        for body in ('<g><path d="M1 1h2" /></g>', '<text x="1">a</text>', '<path d="M1 1h2" transform="scale(2)" />'):
            with self.subTest(body=body), self.assertRaisesRegex(build_symbols.IconError, "bad"):
                build_symbols.build(self.package(bad=body), ["bad"])

    def test_unexpected_canvas_is_refused(self):
        package = self.package()
        (package / "icons" / "odd.svg").write_text(
            SVG.format(body='<path d="M1 1h2" />').replace('viewBox="0 0 24 24"', 'viewBox="0 0 16 16"'),
            encoding="utf-8")
        with self.assertRaisesRegex(build_symbols.IconError, "odd"):
            build_symbols.build(package, ["odd"])

    def test_package_may_be_given_as_the_extraction_folder(self):
        package = self.package(one='<path d="M1 1h2" />')
        self.assertEqual(build_symbols.find_package(package), package)
        self.assertEqual(build_symbols.find_package(package.parent), package)
        with self.assertRaisesRegex(build_symbols.IconError, "icons"):
            build_symbols.find_package(package / "icons")

    def test_bundled_icons_pass_the_tool_rules(self):
        for name, elements in ICONS.items():
            with self.subTest(name=name):
                self.assertEqual(build_symbols.check_icon(name, elements), [])


if __name__ == "__main__":
    unittest.main()
