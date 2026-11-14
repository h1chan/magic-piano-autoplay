"""Virtual keyboard backed by Linux uinput.

The compositor treats the created device as a real keyboard, so key events
reach whichever window has focus. That is what we need for Sober/Roblox on
Wayland, where xdotool does not work.

No third-party packages: everything goes straight to /dev/uinput.
"""

from __future__ import annotations

import fcntl
import os
import struct

# ioctl constants from <linux/uinput.h> (x86_64)
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565

EV_SYN = 0
EV_KEY = 1
SYN_REPORT = 0

BUS_USB = 0x03

# Linux input key codes for the keys we need (<linux/input-event-codes.h>).
KEY_CODES = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8,
    "8": 9, "9": 10, "0": 11,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20,
    "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34,
    "h": 35, "j": 36, "k": 37, "l": 38,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50,
    "shift": 42, "space": 57, "enter": 28,
}

SHIFT = KEY_CODES["shift"]

# struct input_event: long sec, long usec, u16 type, u16 code, s32 value.
_EVENT = struct.Struct("llHHi")
# struct uinput_setup: input_id(4 x u16), name[80], u32 ff_effects_max.
_SETUP = struct.Struct("HHHH80sI")


class VirtualKeyboard:
    """Create a uinput keyboard and emit key down/up events."""

    def __init__(self, name: str = "magic-piano", device: str = "/dev/uinput"):
        self.name = name
        self._fd = os.open(device, os.O_WRONLY | os.O_NONBLOCK)
        try:
            self._configure()
        except Exception:
            os.close(self._fd)
            raise

    def _configure(self) -> None:
        fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
        for code in set(KEY_CODES.values()):
            fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)
        setup = _SETUP.pack(BUS_USB, 0x1234, 0x5678, 1, self.name.encode(), 0)
        fcntl.ioctl(self._fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self._fd, UI_DEV_CREATE)

    def _emit(self, type_: int, code: int, value: int) -> None:
        data = _EVENT.pack(0, 0, type_, code, value)
        while data:
            written = os.write(self._fd, data)
            data = data[written:]

    def sync(self) -> None:
        self._emit(EV_SYN, SYN_REPORT, 0)

    def key_down(self, code: int) -> None:
        self._emit(EV_KEY, code, 1)
        self.sync()

    def key_up(self, code: int) -> None:
        self._emit(EV_KEY, code, 0)
        self.sync()

    def tap(self, code: int, duration: float = 0.02) -> None:
        # Kept for manual tests; the player uses key_down/key_up directly.
        import time

        self.key_down(code)
        time.sleep(duration)
        self.key_up(code)

    def close(self) -> None:
        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, UI_DEV_DESTROY)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "VirtualKeyboard":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
