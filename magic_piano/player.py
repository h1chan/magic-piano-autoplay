"""Turn a song into timed key events and play them."""

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
    """Build a sorted timeline. Returns (events, skipped tokens)."""
    events: list[Event] = []
    skipped: list[str] = []
    now = 0.0
    for token in tokens:
        stroke = token_to_stroke(token, layout)
        if stroke is None:
            skipped.append(token)
            now += beat
            continue
        char, shift = stroke
        events.append(Event(now, True, char, shift))
        events.append(Event(now + beat * gate, False, char, shift))
        now += beat
    # At the same instant release first, then press, so nothing gets stuck.
    events.sort(key=lambda event: (event.time, event.down))
    return events, skipped


def wait_until(target: float) -> None:
    """Sleep coarse, then spin, for millisecond-level accuracy."""
    while True:
        remaining = target - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.002:
            time.sleep(remaining - 0.001)


class Player:
    def __init__(self, keyboard: VirtualKeyboard):
        self.keyboard = keyboard
        self._shift_held = 0

    def _press(self, char: str, shift: bool) -> None:
        if shift:
            if self._shift_held == 0:
                self.keyboard.key_down(SHIFT)
            self._shift_held += 1
        self.keyboard.key_down(KEY_CODES[char])

    def _release(self, char: str, shift: bool) -> None:
        self.keyboard.key_up(KEY_CODES[char])
        if shift:
            self._shift_held -= 1
            if self._shift_held == 0:
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
        # Safety net if play() is interrupted.
        while self._shift_held > 0:
            self.keyboard.key_up(SHIFT)
            self._shift_held -= 1


def format_events(events: list[Event]) -> str:
    lines = []
    for event in events:
        mark = "DOWN" if event.down else "up  "
        label = describe((event.char, event.shift))
        lines.append(f"{event.time:8.3f}s  {mark}  {label}")
    return "\n".join(lines)
