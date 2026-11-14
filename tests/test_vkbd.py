import glob
import os
import unittest

from magic_piano.vkbd import VirtualKeyboard


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


if __name__ == "__main__":
    unittest.main()
