"""Minimal Standard MIDI File reader.

Supports formats 0 and 1, running status, tempo changes and note on/off
(including note-on with velocity 0). SMPTE time division and format 2 are
rejected with a clear error instead of producing wrong timings.
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass

DRUM_CHANNEL = 9


class MidiError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    start: float      # seconds
    duration: float   # seconds
    pitch: int        # MIDI note 0..127
    velocity: int
    track: int


@dataclass(frozen=True)
class MidiInfo:
    fmt: int
    division: int
    tracks: tuple[str, ...]


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 2], "big")


def _u32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 4], "big")


def _vlq(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    while True:
        if pos >= len(data):
            raise MidiError("truncated variable-length quantity")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def _parse_track(body: bytes):
    """Yield ('on'|'off'|'tempo'|'name'|'end', tick, ...) events."""
    pos = 0
    tick = 0
    running: int | None = None
    while pos < len(body):
        delta, pos = _vlq(body, pos)
        tick += delta
        status = body[pos]
        if status < 0x80:
            if running is None:
                raise MidiError("data byte without running status")
            status = running
        else:
            pos += 1
            if status < 0xF0:
                running = status

        if status == 0xFF:
            meta = body[pos]
            pos += 1
            length, pos = _vlq(body, pos)
            payload = body[pos:pos + length]
            pos += length
            running = None
            if meta == 0x51 and len(payload) == 3:
                yield ("tempo", tick, int.from_bytes(payload, "big"))
            elif meta == 0x03:
                yield ("name", tick, payload.decode("utf-8", "replace"))
            elif meta == 0x2F:
                yield ("end", tick)
                return
        elif status in (0xF0, 0xF7):
            length, pos = _vlq(body, pos)
            pos += length
            running = None
        elif status >= 0xF0:
            raise MidiError(f"unsupported system event 0x{status:02x}")
        else:
            kind = status & 0xF0
            channel = status & 0x0F
            size = 1 if kind in (0xC0, 0xD0) else 2
            payload = body[pos:pos + size]
            if len(payload) < size:
                raise MidiError("truncated channel event")
            pos += size
            if kind == 0x90 and payload[1] > 0:
                yield ("on", tick, channel, payload[0], payload[1])
            elif kind == 0x80 or (kind == 0x90 and payload[1] == 0):
                yield ("off", tick, channel, payload[0], payload[1])


class _TimeMap:
    def __init__(self, tempos: list[tuple[int, int]], division: int):
        # (start_tick, start_seconds, us_per_quarter)
        self.segments = [(0, 0.0, 500_000)]
        last_tick, last_seconds, tempo = 0, 0.0, 500_000
        for tick, new_tempo in sorted(tempos):
            last_seconds += (tick - last_tick) * tempo / (division * 1e6)
            last_tick, tempo = tick, new_tempo
            self.segments.append((tick, last_seconds, tempo))
        self._starts = [segment[0] for segment in self.segments]
        self._division = division

    def seconds(self, tick: int) -> float:
        index = bisect.bisect_right(self._starts, tick) - 1
        start_tick, start_seconds, tempo = self.segments[index]
        return start_seconds + (tick - start_tick) * tempo / (self._division * 1e6)


def _read_chunks(data: bytes) -> tuple[int, int, list[bytes]]:
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("not a MIDI file (missing MThd)")
    header_len = _u32(data, 4)
    fmt = _u16(data, 8)
    division = _u16(data, 12)
    if division & 0x8000:
        raise MidiError("SMPTE time division is not supported")
    if fmt == 2:
        raise MidiError("format 2 is not supported")

    pos = 8 + header_len
    bodies: list[bytes] = []
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_len = _u32(data, pos + 4)
        pos += 8
        body = data[pos:pos + chunk_len]
        pos += chunk_len
        if chunk_id == b"MTrk":
            bodies.append(body)
    if not bodies:
        raise MidiError("no MTrk chunks")
    return fmt, division, bodies


def inspect(path: str) -> MidiInfo:
    with open(path, "rb") as handle:
        data = handle.read()
    fmt, division, bodies = _read_chunks(data)
    names: list[str] = []
    for index, body in enumerate(bodies):
        name = ""
        for event in _parse_track(body):
            if event[0] == "name":
                name = event[2]
                break
        names.append(name or f"track {index + 1}")
    return MidiInfo(fmt, division, tuple(names))


def read_notes(
    path: str,
    tracks: set[int] | None = None,
    include_drums: bool = False,
) -> list[Note]:
    """Read notes from a .mid file.

    ``tracks`` is a set of 1-based track numbers; None means all tracks.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    _fmt, division, bodies = _read_chunks(data)

    parsed = []
    tempos: list[tuple[int, int]] = []
    for index, body in enumerate(bodies):
        events = list(_parse_track(body))
        parsed.append(events)
        tempos.extend((tick, us) for kind, tick, *rest in events
                      if kind == "tempo" for us in rest)

    clock = _TimeMap(tempos, division)
    notes: list[Note] = []
    for index, events in enumerate(parsed):
        if tracks is not None and index + 1 not in tracks:
            continue
        active: dict[tuple[int, int], deque] = {}
        last_tick = 0
        for event in events:
            kind, tick = event[0], event[1]
            last_tick = tick
            if kind == "on":
                _, _, channel, pitch, velocity = event
                if channel == DRUM_CHANNEL and not include_drums:
                    continue
                active.setdefault((channel, pitch), deque()).append((tick, velocity))
            elif kind == "off":
                _, _, channel, pitch, _ = event
                stack = active.get((channel, pitch))
                if not stack:
                    continue
                start_tick, velocity = stack.popleft()
                notes.append(_make_note(clock, index, start_tick, tick, pitch, velocity))
        # Notes without a matching note-off end at the last event.
        for (_channel, pitch), stack in active.items():
            while stack:
                start_tick, velocity = stack.popleft()
                notes.append(_make_note(clock, index, start_tick, last_tick, pitch, velocity))

    notes.sort(key=lambda note: (note.start, note.pitch))
    return notes


def _make_note(clock: _TimeMap, track: int, start_tick: int, end_tick: int,
               pitch: int, velocity: int) -> Note:
    start = clock.seconds(start_tick)
    end = clock.seconds(end_tick)
    return Note(start, max(end - start, 0.0), pitch, velocity, track)
