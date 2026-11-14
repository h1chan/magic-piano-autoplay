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


def fit_octave(pitches: list[int], low: int, high: int) -> int:
    """Octave shift that keeps the most notes inside [low, high]."""
    best_shift, best_inside = 0, -1
    for shift in range(-60, 61, 12):
        inside = sum(1 for pitch in pitches if low <= pitch + shift <= high)
        if inside > best_inside or (inside == best_inside and abs(shift) < abs(best_shift)):
            best_shift, best_inside = shift, inside
    return best_shift


def build_events_from_notes(
    notes,
    layout: dict[int, tuple[str, bool]],
    transpose: int = 0,
    fit: bool = True,
    gate: float = 0.98,
    speed: float = 1.0,
) -> tuple[list[Event], int, int]:
    """Convert MIDI notes to key events.

    Returns (events, octave_shift, dropped_notes). Notes outside the mapped
    keyboard after fitting are dropped.
    """
    if not notes:
        return [], 0, 0
    low, high = min(layout), max(layout)
    shift = fit_octave([note.pitch for note in notes], low, high) if fit else 0

    events: list[Event] = []
    dropped = 0
    for note in notes:
        stroke = layout.get(note.pitch + transpose + shift)
        if stroke is None:
            dropped += 1
            continue
        char, needs_shift = stroke
        start = note.start / speed
        duration = max(note.duration * gate, 0.02)
        events.append(Event(start, True, char, needs_shift))
        events.append(Event(start + duration, False, char, needs_shift))
    events.sort(key=lambda event: (event.time, event.down))
    return events, shift, dropped


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
        self._held: dict[str, bool] = {}
        self._shift_refs = 0

    def _press(self, char: str, shift: bool) -> bool:
        # The same key cannot sound twice, and a sharp cannot be added while
        # its natural key is held (Shift would retrigger the same key).
        if char in self._held:
            return False
        if shift:
            if self._shift_refs == 0:
                self.keyboard.key_down(SHIFT)
            self._shift_refs += 1
        self._held[char] = shift
        self.keyboard.key_down(KEY_CODES[char])
        return True

    def _release(self, char: str, shift: bool) -> None:
        if self._held.get(char) != shift:
            return
        del self._held[char]
        self.keyboard.key_up(KEY_CODES[char])
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
