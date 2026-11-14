"""Turn a song or MIDI notes into timed key events and play them."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .layout import describe, token_to_stroke
from .vkbd import KEY_CODES, SHIFT, VirtualKeyboard


@dataclass(frozen=True)
class Event:
    time: float
    down: bool
    char: str
    shift: bool


def build_events(
    tokens: list[str],
    layout: dict[int, tuple[str, bool]],
    beat: float,
    gate: float = 0.9,
) -> tuple[list[Event], list[str]]:
    """Build a sorted timeline from sheet tokens. Returns (events, skipped)."""
    events: list[Event] = []
    skipped: list[str] = []
    now = 0.0
    for token in tokens:
        parts = token if isinstance(token, tuple) else (token,)
        for part in parts:
            stroke = token_to_stroke(part, layout)
            if stroke is None:
                skipped.append(part)
                continue
            char, shift = stroke
            events.append(Event(now, True, char, shift))
            events.append(Event(now + beat * gate, False, char, shift))
        now += beat
    _sort_events(events)
    return events, skipped


def _sort_events(events: list[Event]) -> None:
    """Order events so Shift is never engaged while a white key is pressed.

    Releases come first at the same instant. Then white keys without Shift,
    then black keys with Shift.
    """
    events.sort(key=lambda event: (event.time, event.down, event.shift))


def wait_until(target: float) -> None:
    """Sleep coarse, then spin, for millisecond-level accuracy."""
    while True:
        remaining = target - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.002:
            time.sleep(remaining - 0.001)


class Player:
    def __init__(self, keyboard: VirtualKeyboard, pause_shift: bool = True):
        self.keyboard = keyboard
        # Roblox reads Shift at key-down. If Shift is held for a black key,
        # a white key pressed meanwhile would sound as a sharp, so lift Shift
        # for that key press and engage it again right after.
        self.pause_shift = pause_shift
        self._held: dict[str, bool] = {}
        self._shift_refs = 0

    def _press(self, char: str, shift: bool) -> bool:
        # The same key cannot sound twice, and a sharp cannot be added while
        # its natural key is held (Shift would retrigger the same key).
        if char in self._held:
            return False
        code = KEY_CODES[char]
        self._held[char] = shift
        if shift:
            if self._shift_refs == 0:
                self.keyboard.key_down(SHIFT)
            self._shift_refs += 1
            self.keyboard.key_down(code)
        elif self.pause_shift and self._shift_refs > 0:
            self.keyboard.key_up(SHIFT)
            self.keyboard.key_down(code)
            self.keyboard.key_down(SHIFT)
        else:
            self.keyboard.key_down(code)
        return True

    def _release(self, char: str, shift: bool) -> None:
        if self._held.get(char) != shift:
            return
        del self._held[char]
        code = KEY_CODES[char]
        if not shift and self.pause_shift and self._shift_refs > 0:
            self.keyboard.key_up(SHIFT)
            self.keyboard.key_up(code)
            self.keyboard.key_down(SHIFT)
        else:
            self.keyboard.key_up(code)
        if shift:
            self._shift_refs -= 1
            if self._shift_refs == 0:
                self.keyboard.key_up(SHIFT)

    def play(self, events: list[Event], delay: float = 0.0) -> None:
        start = time.perf_counter() + delay
        for event in events:
            wait_until(start + event.time)
            if event.down:
                self._press(event.char, event.shift)
            else:
                self._release(event.char, event.shift)

    def release_all(self) -> None:
        for char, shift in list(self._held.items()):
            self._release(char, shift)
        while self._shift_refs > 0:
            self.keyboard.key_up(SHIFT)
            self._shift_refs -= 1


def format_events(events: list[Event]) -> str:
    lines = []
    for event in events:
        mark = "DOWN" if event.down else "up  "
        label = describe((event.char, event.shift))
        lines.append(f"{event.time:8.3f}s  {mark}  {label}")
    return "\n".join(lines)
