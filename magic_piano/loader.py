"""Load a song or MIDI file into a playable event timeline.

Shared by the command line player and the terminal interface so both apply
exactly the same arrangement rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import arrange, midi_file
from . import song as song_mod
from .player import Event, build_events

MIDI_SUFFIXES = (".mid", ".midi")


@dataclass
class Loaded:
    events: list[Event] = field(default_factory=list)
    notes: int = 0
    duration: float = 0.0
    report: arrange.Report | None = None
    skipped: list[str] = field(default_factory=list)
    bpm: float | None = None

    def summary(self) -> str:
        parts = [f"{self.notes} notes"]
        if self.report is not None:
            if self.report.shift:
                parts.append(f"octave shift {self.report.shift:+d}")
            if self.report.folded:
                parts.append(f"{self.report.folded} folded")
            if self.report.dropped:
                parts.append(f"{self.report.dropped} dropped")
            if self.report.conflicts:
                parts.append(f"{self.report.conflicts} key conflicts")
        if self.bpm:
            parts.append(f"{self.bpm:g} bpm")
        if self.events:
            parts.append(f"{self.events[-1].time:.1f}s")
        return ", ".join(parts)


def is_midi(path: str | Path) -> bool:
    return str(path).lower().endswith(MIDI_SUFFIXES)


def load(
    path: str | Path,
    mapping: dict[int, tuple[str, bool]],
    *,
    bpm: float | None = None,
    gate: float | None = None,
    speed: float = 1.0,
    transpose: int = 0,
    fit: bool = True,
    tracks: set[int] | None = None,
    drums: bool = False,
) -> Loaded:
    """Read ``path`` and arrange it for the given keyboard layout."""
    path = str(path)
    if is_midi(path):
        notes = midi_file.read_notes(path, tracks=tracks, include_drums=drums)
        events, report = arrange.prepare(
            notes,
            mapping,
            transpose=transpose,
            fit=fit,
            gate=gate if gate is not None else 1.0,
            speed=speed,
        )
        duration = max((note.start + note.duration for note in notes), default=0.0)
        return Loaded(
            events=events,
            notes=len(notes),
            duration=duration,
            report=report,
        )

    song = song_mod.load(path)
    song_bpm = bpm or song.bpm
    events, skipped = build_events(
        song.tokens,
        mapping,
        beat=60.0 / song_bpm,
        gate=gate if gate is not None else 0.9,
    )
    if speed != 1.0:
        events = [
            Event(event.time / speed, event.down, event.char, event.shift)
            for event in events
        ]
    duration = events[-1].time if events else 0.0
    return Loaded(
        events=events,
        notes=len(song.tokens),
        duration=duration,
        skipped=skipped,
        bpm=song_bpm,
    )
