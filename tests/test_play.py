"""Tests for the command-line entry point helpers."""

import unittest

from magic_piano.hypr import Window
from magic_piano.play import _countdown_seconds, _focus_guard, _start_note


class StartNoteTest(unittest.TestCase):
    def test_note_name(self):
        self.assertEqual(_start_note("C2"), 36)
        self.assertEqual(_start_note("C3"), 48)

    def test_midi_number(self):
        self.assertEqual(_start_note("60"), 60)
        self.assertEqual(_start_note("36"), 36)

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            _start_note("H2")


class CountdownTest(unittest.TestCase):
    def test_targeted_input_does_not_wait(self):
        self.assertEqual(_countdown_seconds(None, False), 0.0)

    def test_system_wide_input_waits_three_seconds(self):
        self.assertEqual(_countdown_seconds(None, True), 3.0)

    def test_explicit_value_wins(self):
        self.assertEqual(_countdown_seconds(5.0, True), 5.0)
        self.assertEqual(_countdown_seconds(0.0, True), 0.0)

    def test_negative_is_clamped(self):
        self.assertEqual(_countdown_seconds(-2.0, False), 0.0)


class FakeHypr:
    def __init__(self, active):
        self.current = active
        self.calls = 0

    def active(self):
        self.calls += 1
        return self.current


class FocusGuardTest(unittest.TestCase):
    def setUp(self):
        self.game = Window("0x1", "org.vinegarhq.Sober", "Sober")
        self.other = Window("0x2", "kitty", "terminal")

    def test_true_while_the_game_is_focused(self):
        guard = _focus_guard(FakeHypr(self.game), self.game, interval=0)
        self.assertTrue(guard())

    def test_false_after_focus_moves_away(self):
        hypr = FakeHypr(self.game)
        guard = _focus_guard(hypr, self.game, interval=0)
        self.assertTrue(guard())
        hypr.current = self.other
        self.assertFalse(guard())

    def test_false_when_nothing_is_focused(self):
        guard = _focus_guard(FakeHypr(None), self.game, interval=0)
        self.assertFalse(guard())

    def test_checks_are_throttled(self):
        hypr = FakeHypr(self.game)
        guard = _focus_guard(hypr, self.game, interval=60.0)
        for _ in range(5):
            self.assertTrue(guard())
        self.assertEqual(hypr.calls, 1)


if __name__ == "__main__":
    unittest.main()
