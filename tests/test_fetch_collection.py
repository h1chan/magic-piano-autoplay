import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import fetch_collection as fc


class CollectionListTest(unittest.TestCase):
    def test_has_one_hundred_pieces(self):
        self.assertEqual(len(fc.COLLECTION), 100)

    def test_titles_are_unique(self):
        titles = [title for _, title, _ in fc.COLLECTION]
        self.assertEqual(len(titles), len(set(titles)))

    def test_categories(self):
        self.assertEqual({category for category, _, _ in fc.COLLECTION},
                         {"Classical", "Game", "Film"})

    def test_every_entry_has_patterns(self):
        for category, title, patterns in fc.COLLECTION:
            with self.subTest(title=title):
                self.assertTrue(patterns)
                self.assertTrue(all(pattern.strip() for pattern in patterns))


class MatchingTest(unittest.TestCase):
    def test_matches_ignores_case(self):
        names = ["a/Classical/Nocturne Op 9.mid", "b/other.mid"]
        self.assertEqual(fc._matches(names, ("nocturne op 9",)),
                         ["a/Classical/Nocturne Op 9.mid"])

    def test_matches_keeps_archive_order(self):
        names = ["z.mid", "a/x.mid", "m.mid"]
        self.assertEqual(fc._matches(names, ("x.mid", "m.mid")),
                         ["a/x.mid", "m.mid"])


class SafeNameTest(unittest.TestCase):
    def test_strips_path_separators(self):
        name = fc._safe_name('Classical - a/b:c*d?e"f<g>h|i')
        self.assertTrue(name.endswith(".mid"))
        for forbidden in '/\\:*?"<>|':
            self.assertNotIn(forbidden, name)

    def test_collapses_spaces(self):
        self.assertEqual(fc._safe_name("  A   B  "), "A B.mid")


if __name__ == "__main__":
    unittest.main()
