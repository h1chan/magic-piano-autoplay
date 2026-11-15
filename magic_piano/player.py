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


class PlaybackStopped(RuntimeError):
    """The caller asked playback to stop."""


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


def wait_until(target: float, stop=None) -> None:
    """Sleep coarse, then spin, for millisecond-level accuracy.

    ``stop`` is polled while waiting so a long note can be interrupted.
    """
    while True:
        if stop is not None and stop():
            raise PlaybackStopped("playback cancelled")
        remaining = target - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.002:
            time.sleep(min(remaining - 0.001, 0.05))


class Player:
    def __init__(self, keyboard: Keyboard):
        self.keyboard = keyboard
        # A key is identified by the character *and* the Shift state: "q"
        # and "Q" are two different notes and may be held at the same time.
        self._held: set[tuple[str, bool]] = set()

    def _press(self, char: str, shift: bool) -> bool:
        # The same key cannot sound twice.
        if (char, shift) in self._held:
            return False
        self._held.add((char, shift))
        self.keyboard.press(char, shift)
        return True

    def _release(self, char: str, shift: bool) -> None:
        if (char, shift) not in self._held:
            return
        self._held.discard((char, shift))
        self.keyboard.release(char, shift)

    def _apply(self, group: list[Event]) -> None:
        """Send all events of one instant, batched when the driver can."""
        send_many = getattr(self.keyboard, "send_many", None)
        if send_many is None:
            for event in group:
                if event.down:
                    self._press(event.char, event.shift)
                else:
                    self._release(event.char, event.shift)
            return

        held = set(self._held)
        actions: list[tuple[str, bool, str]] = []
        for event in group:
            key = (event.char, event.shift)
            if event.down:
                if key in held:
                    continue
                held.add(key)
                actions.append((event.char, event.shift, "down"))
            else:
                if key not in held:
                    continue
                held.discard(key)
                actions.append((event.char, event.shift, "up"))
        if actions:
            # Record the new state before the call: if the driver fails
            # halfway through, release_all() must still know every key that
            # may have reached the game.
            self._held = held
            send_many(actions)

    def play(
        self,
        events: list[Event],
        delay: float = 0.0,
        guard=None,
        stop=None,
        on_event=None,
    ) -> None:
        start = time.perf_counter() + delay
        total = len(events)
        index = 0
        while index < total:
            moment = events[index].time
            try:
                wait_until(start + moment, stop)
            except PlaybackStopped:
                self.release_all()
                raise
            if guard is not None and not guard():
                self.release_all()
                raise PlaybackAborted("focus left the target window")

            # Chords share one timestamp: send them in a single batch so the
            # notes start together instead of a few milliseconds apart.
            end = index + 1
            while end < total and abs(events[end].time - moment) < 1e-6:
                end += 1
            self._apply(events[index:end])
            if on_event is not None:
                for offset in range(end - index):
                    on_event(index + offset + 1, total)
            index = end

    def release_all(self) -> None:
        for char, shift in sorted(self._held, key=lambda item: not item[1]):
            self._release(char, shift)
        self.keyboard.release_all()


def format_events(events: list[Event]) -> str:
    lines = []
    for event in events:
        mark = "DOWN" if event.down else "up  "
        label = describe((event.char, event.shift))
        lines.append(f"{event.time:8.3f}s  {mark}  {label}")
    return "\n".join(lines)
