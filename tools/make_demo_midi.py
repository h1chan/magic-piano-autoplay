"""Generate songs/ode_to_joy.mid: a public-domain Beethoven melody with chords.

    python3 tools/make_demo_midi.py

Format 1, 480 ticks per quarter, 120 bpm, three tracks (tempo, melody, chords).
"""

from __future__ import annotations

from pathlib import Path

DIVISION = 480
TEMPO_US = 500_000  # 120 bpm


def vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


# (start_beat, duration_beats, midi_note)
MELODY = [
    (0, 1, 64), (1, 1, 64), (2, 1, 65), (3, 1, 67),
    (4, 1, 67), (5, 1, 65), (6, 1, 64), (7, 1, 62),
    (8, 1, 60), (9, 1, 60), (10, 1, 62), (11, 1, 64),
    (12, 1.5, 64), (13.5, 0.5, 62), (14, 2, 62),
    (16, 1, 64), (17, 1, 64), (18, 1, 65), (19, 1, 67),
    (20, 1, 67), (21, 1, 65), (22, 1, 64), (23, 1, 62),
    (24, 1, 60), (25, 1, 60), (26, 1, 62), (27, 1, 64),
    (28, 1.5, 62), (29.5, 0.5, 60), (30, 2, 60),
]

C_MAJOR = (48, 52, 55)   # C3 E3 G3
G_MAJOR = (55, 59, 62)   # G3 B3 D4

# (start_beat, duration_beats, chord) — one chord per bar, split in bars 4 and 8.
HARMONY = [
    (0, 4, C_MAJOR), (4, 4, G_MAJOR), (8, 4, C_MAJOR), (12, 2, G_MAJOR), (14, 2, C_MAJOR),
    (16, 4, C_MAJOR), (20, 4, G_MAJOR), (24, 4, C_MAJOR), (28, 2, G_MAJOR), (30, 2, C_MAJOR),
]
CHORDS = [
    (start, duration, pitch)
    for start, duration, chord in HARMONY
    for pitch in chord
]


def encode_track(notes) -> bytes:
    events = []
    for start, duration, pitch in notes:
        events.append((start * DIVISION, 1, 0x90, pitch, 80))
        events.append(((start + duration) * DIVISION, 0, 0x80, pitch, 0))
    # Releases first at the same tick so retriggers never stack up.
    events.sort(key=lambda item: (item[0], item[1], item[3]))

    data = bytearray()
    last_tick = 0
    for tick, _, status, pitch, velocity in events:
        tick = int(round(tick))
        data += vlq(tick - last_tick)
        data += bytes((status, pitch, velocity))
        last_tick = tick
    data += vlq(0) + b"\xff\x2f\x00"
    return bytes(data)


def chunk(track: bytes) -> bytes:
    return b"MTrk" + len(track).to_bytes(4, "big") + track


def main() -> None:
    tempo = bytearray()
    tempo += vlq(0) + b"\xff\x51\x03" + TEMPO_US.to_bytes(3, "big")
    tempo += vlq(0) + b"\xff\x2f\x00"

    header = (
        b"MThd" + (6).to_bytes(4, "big")
        + (1).to_bytes(2, "big")
        + (3).to_bytes(2, "big")
        + DIVISION.to_bytes(2, "big")
    )
    content = header + chunk(bytes(tempo)) + chunk(encode_track(MELODY)) + chunk(encode_track(CHORDS))
    target = Path(__file__).resolve().parent.parent / "songs" / "ode_to_joy.mid"
    target.write_bytes(content)
    print(f"wrote {target} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
