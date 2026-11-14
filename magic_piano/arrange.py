"""Turn MIDI notes into playable key events.

Raw MIDI does not fit a 5-octave keyboard: notes fall outside the range, the
same physical key is needed twice, and sustained notes overlap. This module
decides what to keep, what to fold by an octave and what to drop, with the
melody protected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .player import Event

TIE_EPS = 0.001        # gap between two notes on the same key


@dataclass(frozen=True)
class Report:
    shift: int = 0
    folded: int = 0
    dropped: int = 0
    conflicts: int = 0


def melody_flags(notes) -> list[bool]:
    """Mark a note as melody when it is the top voice sounding at its onset.

    Looking at sustained notes (not just the same onset) prevents bass or
    accompaniment notes from being promoted to melody just because they play
    alone between melody notes.
    """
    flags = [False] * len(notes)
    pitches = sorted(note.pitch for note in notes)
    # An isolated low bass note is technically the top voice, but it is not
    # the melody. Only upper-register top notes get the melody weight.
    threshold = pitches[min(len(pitches) - 1, int(0.75 * len(pitches)))]
    order = sorted(
        range(len(notes)), key=lambda index: (notes[index].start, -notes[index].pitch)
    )
    active: list[tuple[float, int]] = []  # (end time, pitch)
    for index in order:
        note = notes[index]
        active = [item for item in active if item[0] > note.start + 1e-6]
        is_top = not active or note.pitch >= max(item[1] for item in active)
        if is_top and note.pitch >= threshold:
            flags[index] = True
        active.append((note.start + max(note.duration, 0.0), note.pitch))
    return flags


def choose_shift(notes, flags: list[bool], low: int, high: int) -> int:
    """Octave shift that keeps the most music, melody weighted highest."""
    weights = [4 if flag else 1 for flag in flags]
    best_shift, best_score = 0, -1
    for shift in range(-60, 61, 12):
        score = sum(
            weight
            for note, weight in zip(notes, weights)
            if low <= note.pitch + shift <= high
        )
        if score > best_score or (score == best_score and abs(shift) < abs(best_shift)):
            best_shift, best_score = shift, score
    return best_shift


def _fold(pitch: int, low: int, high: int) -> int | None:
    """Move a pitch by octaves until it fits, keeping its pitch class."""
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch if low <= pitch <= high else None


def _resolve_conflicts(items):
    """Fix overlaps on one physical key.

    Same Shift state: shorten the earlier note so the retrigger is audible.
    Different Shift state (q vs Q): keep the melody, drop the other note.
    """
    by_char: dict[str, list] = defaultdict(list)
    for item in items:
        by_char[item[2]].append(item)

    kept: list[tuple] = []
    conflicts = 0
    for group in by_char.values():
        group.sort(key=lambda item: item[0])
        current = None
        for item in group:
            if current is None:
                current = item
                continue
            if item[0] >= current[1]:
                kept.append(current)
                current = item
                continue
            if item[3] == current[3]:
                end = item[0] - TIE_EPS
                if end > current[0] + 0.01:
                    kept.append((current[0], end, current[2], current[3], current[4]))
                current = item
            else:
                conflicts += 1
                if item[4] and not current[4]:
                    current = item
        if current is not None:
            kept.append(current)
    return kept, conflicts


def prepare(
    notes,
    layout: dict[int, tuple[str, bool]],
    transpose: int = 0,
    fit: bool = True,
    gate: float = 1.0,
    speed: float = 1.0,
    fold: bool = True,
) -> tuple[list[Event], Report]:
    """Build a playable timeline from MIDI notes."""
    if not notes:
        return [], Report()

    flags = melody_flags(notes)
    low, high = min(layout), max(layout)
    shift = choose_shift(notes, flags, low, high) if fit else 0

    items = []
    folded = dropped = 0
    for note, is_melody in zip(notes, flags):
        pitch = note.pitch + transpose + shift
        if not low <= pitch <= high:
            if not fold:
                dropped += 1
                continue
            folded_pitch = _fold(pitch, low, high)
            if folded_pitch is None:
                dropped += 1
                continue
            pitch = folded_pitch
            folded += 1
        char, needs_shift = layout[pitch]
        end = note.start + max(note.duration * gate, 0.02)
        items.append((note.start, end, char, needs_shift, is_melody))

    kept, conflicts = _resolve_conflicts(items)
    events: list[Event] = []
    for start, end, char, needs_shift, _ in kept:
        events.append(Event(start / speed, True, char, needs_shift))
        events.append(Event(end / speed, False, char, needs_shift))
    events.sort(key=lambda event: (event.time, event.down, event.shift))
    return events, Report(shift, folded, dropped, conflicts)
