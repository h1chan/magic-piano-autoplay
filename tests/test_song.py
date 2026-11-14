import unittest

from magic_piano.song import parse


class SongTest(unittest.TestCase):
    def test_parses_tempo_and_tokens(self):
        song = parse("// hi\nbpm 100\n1 1 5 5 | 6 6 5\n")
        self.assertEqual(song.bpm, 100)
        self.assertEqual(song.tokens, ["1", "1", "5", "5", "6", "6", "5"])
        self.assertAlmostEqual(song.beat_seconds, 0.6)

    def test_beat_directive(self):
        self.assertAlmostEqual(parse("beat 0.5\n1").bpm, 120)

    def test_note_names_allowed(self):
        self.assertEqual(parse("C4 D#4").tokens, ["C4", "D#4"])

    def test_empty_song_fails(self):
        with self.assertRaises(ValueError):
            parse("// only a comment\n")


if __name__ == "__main__":
    unittest.main()
