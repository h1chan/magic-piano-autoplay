"""The key table must match the Roblox Magic Piano keyboard exactly.

The expected labels below were read from a screenshot of the game: an
88-key piano whose 61 playable keys start at C2 and use the classic
virtual-piano layout.
"""

import unittest

from magic_piano.layout import build_layout, describe, midi_to_note, note_to_midi

# note, label printed on the key in the game
GAME_KEYS = [
    ("C2", "1"), ("C#2", "Shift+1"), ("D2", "2"), ("D#2", "Shift+2"),
    ("E2", "3"), ("F2", "4"), ("F#2", "Shift+4"), ("G2", "5"),
    ("G#2", "Shift+5"), ("A2", "6"), ("A#2", "Shift+6"), ("B2", "7"),
    ("C3", "8"), ("C#3", "Shift+8"), ("D3", "9"), ("D#3", "Shift+9"),
    ("E3", "0"), ("F3", "q"), ("F#3", "Q"), ("G3", "w"),
    ("G#3", "W"), ("A3", "e"), ("A#3", "E"), ("B3", "r"),
    ("C4", "t"), ("C#4", "T"), ("D4", "y"), ("D#4", "Y"),
    ("E4", "u"), ("F4", "i"), ("F#4", "I"), ("G4", "o"),
    ("G#4", "O"), ("A4", "p"), ("A#4", "P"), ("B4", "a"),
    ("C5", "s"), ("C#5", "S"), ("D5", "d"), ("D#5", "D"),
    ("E5", "f"), ("F5", "g"), ("F#5", "G"), ("G5", "h"),
    ("G#5", "H"), ("A5", "j"), ("A#5", "J"), ("B5", "k"),
    ("C6", "l"), ("C#6", "L"), ("D6", "z"), ("D#6", "Z"),
    ("E6", "x"), ("F6", "c"), ("F#6", "C"), ("G6", "v"),
    ("G#6", "V"), ("A6", "b"), ("A#6", "B"), ("B6", "n"),
    ("C7", "m"),
]


class GameLayoutTest(unittest.TestCase):
    def setUp(self):
        self.layout = build_layout()

    def test_matches_the_game_keyboard(self):
        self.assertEqual(len(GAME_KEYS), 61)
        for note, label in GAME_KEYS:
            with self.subTest(note=note):
                stroke = self.layout[note_to_midi(note)]
                self.assertEqual(describe(stroke), label)

    def test_range_is_exactly_c2_to_c7(self):
        notes = sorted(self.layout)
        self.assertEqual(notes[0], note_to_midi("C2"))
        self.assertEqual(notes[-1], note_to_midi("C7"))
        self.assertEqual(len(notes), 61)
        self.assertEqual(midi_to_note(notes[0]), "C2")
        self.assertEqual(midi_to_note(notes[-1]), "C7")

    def test_default_octave_matches_the_game(self):
        self.assertEqual(describe(build_layout()[note_to_midi("C4")]), "t")
        self.assertEqual(describe(build_layout()[note_to_midi("C#4")]), "T")


if __name__ == "__main__":
    unittest.main()
