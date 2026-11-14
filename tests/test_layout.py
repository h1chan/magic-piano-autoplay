import unittest

from magic_piano.layout import (
    build_layout,
    describe,
    midi_to_note,
    note_to_midi,
    token_to_stroke,
)


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.layout = build_layout(48)  # C3 on the first white key

    def test_first_white_key_is_start_note(self):
        self.assertEqual(self.layout[48], ("1", False))

    def test_black_key_is_shift_of_left_white_key(self):
        self.assertEqual(self.layout[49], ("1", True))   # C#
        self.assertEqual(self.layout[51], ("2", True))   # D#
        self.assertEqual(self.layout[54], ("4", True))   # F#

    def test_e_and_b_have_no_black_key(self):
        # The semitone above E is F and above B is C, both white keys.
        self.assertEqual(self.layout[53], ("4", False))
        self.assertEqual(self.layout[60], ("8", False))

    def test_layout_covers_every_semitone(self):
        notes = sorted(self.layout)
        self.assertEqual(notes, list(range(notes[0], notes[-1] + 1)))

    def test_strokes_are_unique(self):
        self.assertEqual(len(set(self.layout.values())), len(self.layout))

    def test_note_names(self):
        self.assertEqual(note_to_midi("C4"), 60)
        self.assertEqual(note_to_midi("A#3"), 58)
        self.assertEqual(note_to_midi("Bb3"), 58)
        self.assertEqual(midi_to_note(60), "C4")
        self.assertEqual(midi_to_note(58), "A#3")

    def test_tokens(self):
        self.assertEqual(token_to_stroke("1", self.layout), ("1", False))
        self.assertEqual(token_to_stroke("Q", self.layout), ("q", True))
        self.assertEqual(token_to_stroke("!", self.layout), ("1", True))
        self.assertEqual(token_to_stroke("C4", self.layout), ("8", False))
        self.assertIsNone(token_to_stroke("C9", self.layout))
        with self.assertRaises(ValueError):
            token_to_stroke("nope", self.layout)

    def test_describe(self):
        self.assertEqual(describe(("q", True)), "Q")


if __name__ == "__main__":
    unittest.main()
