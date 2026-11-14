"""Turn a song or MIDI notes into timed key events and play them."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .layout import describe, token_to_stroke


class Keyboard(Protocol):
    """What the player needs from an input driver."""

    def press(self, key: str, shift: bool) -> None: ...

    def release(self, key: str, shift: bool) -> None: ...

    def release_all(self) -> None: ...


class PlaybackAborted(RuntimeError):
    """The focus guard stopped playback before a key could go elsewhere."""


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
    def __init__(self, keyboard: Keyboard):
        self.keyboard = keyboard
        self._held: dict[str, bool] = {}

    def _press(self, char: str, shift: bool) -> bool:
        # The same key cannot sound twice, and a sharp cannot be added while
        # its natural key is held (Shift would retrigger the same key).
        if char in self._held:
            return False
        self._held[char] = shift
        self.keyboard.press(char, shift)
        return True

    def _release(self, char: str, shift: bool) -> None:
        if self._held.get(char) != shift:
            return
        del self._held[char]
        self.keyboard.release(char, shift)

    def play(self, events: list[Event], delay: float = 0.0, guard=None) -> None:
        start = time.perf_counter() + delay
        for event in events:
            wait_until(start + event.time)
            if guard is not None and not guard():
                self.release_all()
                raise PlaybackAborted("focus left the target window")
            if event.down:
                self._press(event.char, event.shift)
            else:
                self._release(event.char, event.shift)

    def release_all(self) -> None:
        for char, shift in list(self._held.items()):
            self._release(char, shift)
        self.keyboard.release_all()


def format_events(events: list[Event]) -> str:
    lines = []
    for event in events:
        mark = "DOWN" if event.down else "up  "
        label = describe((event.char, event.shift))
        lines.append(f"{event.time:8.3f}s  {mark}  {label}")
    return "\n".join(lines)
