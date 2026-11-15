import unittest

from magic_piano.layout import build_layout
from magic_piano.player import (
    Event,
    PlaybackAborted,
    PlaybackStopped,
    Player,
    build_events,
)


class FakeKeyboard:
    """Records the player-level calls, not raw key codes."""

    def __init__(self):
        self.calls = []
        self.released = False

    def press(self, key, shift):
        self.calls.append(("press", key, shift))

    def release(self, key, shift):
        self.calls.append(("release", key, shift))

    def release_all(self):
        self.released = True


class BatchKeyboard(FakeKeyboard):
    """Keyboard that receives one call per chord."""

    def __init__(self):
        super().__init__()
        self.batches = []

    def send_many(self, actions):
        self.batches.append(actions)
        for key, shift, state in actions:
            self.calls.append(("press" if state == "down" else "release", key, shift))


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
        self.assertEqual(
            [(event.char, event.shift) for event in downs],
            [("1", False), ("3", False), ("1", True)],
        )


class PlayerTest(unittest.TestCase):
    def test_sharp_note_carries_shift(self):
        keyboard = FakeKeyboard()
        Player(keyboard).play([Event(0, True, "1", True), Event(0.01, False, "1", True)])
        self.assertEqual(
            keyboard.calls,
            [("press", "1", True), ("release", "1", True)],
        )

    def test_plain_note_has_no_shift(self):
        keyboard = FakeKeyboard()
        Player(keyboard).play([Event(0, True, "q", False), Event(0.01, False, "q", False)])
        self.assertEqual(
            keyboard.calls, [("press", "q", False), ("release", "q", False)]
        )

    def test_natural_and_sharp_are_independent(self):
        # 'q' and 'Q' are different notes: the game can sound both at once.
        keyboard = FakeKeyboard()
        Player(keyboard).play(
            [
                Event(0, True, "q", False),
                Event(0.01, True, "q", True),
                Event(0.02, False, "q", True),
                Event(0.03, False, "q", False),
            ]
        )
        self.assertEqual(
            keyboard.calls,
            [
                ("press", "q", False),
                ("press", "q", True),
                ("release", "q", True),
                ("release", "q", False),
            ],
        )

    def test_release_all_clears_held_notes(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        player.play(
            [
                Event(0, True, "1", False),
                Event(0, True, "2", True),
                Event(0.01, False, "1", False),
            ]
        )
        player.release_all()
        self.assertEqual(
            keyboard.calls,
            [
                ("press", "1", False),
                ("press", "2", True),
                ("release", "1", False),
                ("release", "2", True),
            ],
        )
        self.assertTrue(keyboard.released)

    def test_guard_aborts_and_releases(self):
        keyboard = FakeKeyboard()
        player = Player(keyboard)
        with self.assertRaises(PlaybackAborted):
            player.play(
                [Event(0, True, "1", False), Event(0.01, True, "3", False)],
                guard=lambda: False,
            )
        self.assertEqual(keyboard.calls, [])
        self.assertTrue(keyboard.released)

    def test_stop_releases_held_keys(self):
        import threading

        keyboard = FakeKeyboard()
        player = Player(keyboard)
        stop = threading.Event()

        def on_event(done, total):
            self.assertEqual((done, total), (1, 2))
            stop.set()

        with self.assertRaises(PlaybackStopped):
            player.play(
                [
                    Event(0, True, "1", False),
                    Event(0.05, False, "1", False),
                ],
                stop=stop.is_set,
                on_event=on_event,
            )
        self.assertEqual(
            keyboard.calls,
            [("press", "1", False), ("release", "1", False)],
        )
        self.assertTrue(keyboard.released)

    def test_progress_callback_runs_for_every_event(self):
        keyboard = FakeKeyboard()
        seen = []
        Player(keyboard).play(
            [Event(0, True, "1", False), Event(0.001, False, "1", False)],
            on_event=lambda done, total: seen.append((done, total)),
        )
        self.assertEqual(seen, [(1, 2), (2, 2)])

    def test_chord_is_sent_in_one_batch(self):
        keyboard = BatchKeyboard()
        Player(keyboard).play(
            [
                Event(0, True, "1", False),
                Event(0, True, "3", False),
                Event(0.01, False, "1", False),
                Event(0.01, False, "3", False),
            ]
        )
        self.assertEqual(
            keyboard.batches,
            [
                [("1", False, "down"), ("3", False, "down")],
                [("1", False, "up"), ("3", False, "up")],
            ],
        )
        self.assertEqual(
            keyboard.calls,
            [
                ("press", "1", False),
                ("press", "3", False),
                ("release", "1", False),
                ("release", "3", False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
