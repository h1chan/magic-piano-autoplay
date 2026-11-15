import glob
import os
import unittest

from magic_piano.vkbd import KEY_CODES, SHIFT, VirtualKeyboard


def _device_names():
    for path in glob.glob("/sys/class/input/input*/name"):
        try:
            with open(path, encoding="utf-8") as handle:
                yield handle.read().strip()
        except OSError:
            continue


@unittest.skipUnless(os.access("/dev/uinput", os.W_OK), "/dev/uinput not writable")
class VirtualKeyboardTest(unittest.TestCase):
    def test_device_is_registered(self):
        name = "magic-piano-test"
        with VirtualKeyboard(name=name):
            self.assertIn(name, list(_device_names()))


class FakeUinput(VirtualKeyboard):
    """VirtualKeyboard with the device layer replaced by a recorder."""

    def __init__(self, pause_shift=True):
        self.name = "test"
        self.pause_shift = pause_shift
        self._held = set()
        self._shift_refs = 0
        self._fd = None
        self.calls = []

    def key_down(self, code):
        self.calls.append(("down", code))

    def key_up(self, code):
        self.calls.append(("up", code))


class ShiftTest(unittest.TestCase):
    def test_sharp_wraps_key_in_shift(self):
        keyboard = FakeUinput()
        keyboard.press("1", True)
        keyboard.release("1", True)
        self.assertEqual(
            keyboard.calls,
            [
                ("down", SHIFT),
                ("down", KEY_CODES["1"]),
                ("up", KEY_CODES["1"]),
                ("up", SHIFT),
            ],
        )

    def test_overlapping_sharps_hold_shift_once(self):
        keyboard = FakeUinput()
        keyboard.press("1", True)
        keyboard.press("2", True)
        keyboard.release("1", True)
        keyboard.release("2", True)
        self.assertEqual(
            keyboard.calls,
            [
                ("down", SHIFT),
                ("down", KEY_CODES["1"]),
                ("down", KEY_CODES["2"]),
                ("up", KEY_CODES["1"]),
                ("up", KEY_CODES["2"]),
                ("up", SHIFT),
            ],
        )

    def test_white_key_lifts_shift_temporarily(self):
        keyboard = FakeUinput()
        keyboard.press("1", True)
        keyboard.press("3", False)
        keyboard.release("3", False)
        keyboard.release("1", True)
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
        keyboard = FakeUinput(pause_shift=False)
        keyboard.press("1", True)
        keyboard.press("3", False)
        self.assertEqual(
            keyboard.calls,
            [
                ("down", SHIFT),
                ("down", KEY_CODES["1"]),
                ("down", KEY_CODES["3"]),
            ],
        )

    def test_release_all_releases_notes_and_shift(self):
        keyboard = FakeUinput()
        keyboard.press("1", True)
        keyboard.press("3", False)
        keyboard.release_all()
        self.assertEqual(keyboard._held, set())
        self.assertEqual(keyboard._shift_refs, 0)
        self.assertEqual(keyboard.calls[-1], ("up", KEY_CODES["3"]))

    def test_release_with_wrong_shift_is_ignored(self):
        keyboard = FakeUinput()
        keyboard.press("1", True)
        keyboard.release("1", False)
        self.assertEqual(
            keyboard.calls, [("down", SHIFT), ("down", KEY_CODES["1"])]
        )


if __name__ == "__main__":
    unittest.main()
