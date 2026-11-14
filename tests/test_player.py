import unittest

from magic_piano.layout import build_layout
from magic_piano.player import Event, Player, build_events
from magic_piano.vkbd import KEY_CODES, SHIFT


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    def key_down(self, code):
        self.calls.append(("down", code))

    def key_up(self, code):
        self.calls.append(("up", code))


class BuildEventsTest(unittest.TestCase):
    def test_timing_and_order(self):
        layout = build_layout(48)
        events, skipped = build_events(["1", "5"], layout, beat=0.5, gate=1.0)
        self.assertEqual(skipped, [])
        self.assertEqual(
            events,
            [
                Event(0.0, True, "1", False),
                Event(0.5, False, "1", False),
                Event(0.5, True, "5", False),
                Event(1.0, False, "5", False),
            ],
        )

    def test_out_of_range_is_skipped_but_keeps_time(self):
        layout = build_layout(48)
        events, skipped = build_events(["1", "C9", "2"], layout, beat=0.5)
        self.assertEqual(skipped, ["C9"])
        downs = [event.time for event in events if event.down]
        self.assertEqual(downs, [0.0, 1.0])

    def test_gate_shortens_notes(self):
        layout = build_layout(48)
        events, _ = build_events(["1"], layout, beat=1.0, gate=0.5)
        self.assertEqual(events[1].time, 0.5)

    def test_chord_events_and_order(self):
        layout = build_layout(48)
        # Mixed chord: white keys must be pressed before Shift is engaged.
        events, skipped = build_events([("1", "!", "3")], layout, beat=1.0)
        self.assertEqual(skipped, [])
        downs = [event for event in events if event.down]
        self.assertEqual([(event.char, event.shift) for event in downs],
                         [("1", False), ("3", False), ("1", True)])


class PlayerTest(unittest.TestCase):
    def test_shift_wraps_sharp_note(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        player.play([Event(0, True, "1", True), Event(0.01, False, "1", True)])
        self.assertEqual(
            keyboard.calls,
            [
                ("down", SHIFT),
                ("down", KEY_CODES["1"]),
                ("up", KEY_CODES["1"]),
                ("up", SHIFT),
            ],
        )

    def test_plain_note_has_no_shift(self):
        keyboard = FakeKeyboard()
        Player(keyboard).play([Event(0, True, "q", False), Event(0.01, False, "q", False)])
        self.assertEqual(keyboard.calls, [("down", KEY_CODES["q"]), ("up", KEY_CODES["q"])])

    def test_overlapping_sharps_keep_shift_held(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        player.play(
            [
                Event(0, True, "1", True),
                Event(0.01, True, "2", True),
                Event(0.02, False, "1", True),
                Event(0.03, False, "2", True),
            ]
        )
        downs = [call for call in keyboard.calls if call[1] == SHIFT and call[0] == "down"]
        ups = [call for call in keyboard.calls if call[1] == SHIFT and call[0] == "up"]
        self.assertEqual(len(downs), 1)
        self.assertEqual(len(ups), 1)
        self.assertEqual(keyboard.calls[-1], ("up", SHIFT))

    def test_white_key_lifts_shift_temporarily(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        player.play(
            [
                Event(0, True, "1", True),    # C#: Shift down
                Event(0.01, True, "3", False),  # E while C# held
                Event(0.02, False, "3", False),
                Event(0.03, False, "1", True),
            ]
        )
        self.assertEqual(
            keyboard.calls,
            [
                ("down", SHIFT),
                ("down", KEY_CODES["1"]),
                ("up", SHIFT),
                ("down", KEY_CODES["3"]),
                ("down", SHIFT),
                ("up", SHIFT),
                ("up", KEY_CODES["3"]),
                ("down", SHIFT),
                ("up", KEY_CODES["1"]),
                ("up", SHIFT),
            ],
        )

    def test_shift_pause_can_be_disabled(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard, pause_shift=False)
        player.play([Event(0, True, "1", True), Event(0.01, True, "3", False)])
        self.assertEqual(
            keyboard.calls,
            [("down", SHIFT), ("down", KEY_CODES["1"]), ("down", KEY_CODES["3"])],
        )

    def test_shift_conflict_is_skipped(self):
        # 'q' and 'Q' are different notes but the same physical key.
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        player.play(
            [
                Event(0, True, "q", False),
                Event(0.01, True, "q", True),
                Event(0.02, False, "q", True),
                Event(0.03, False, "q", False),
            ]
        )
        self.assertEqual(keyboard.calls, [("down", KEY_CODES["q"]), ("up", KEY_CODES["q"])])


if __name__ == "__main__":
    unittest.main()
