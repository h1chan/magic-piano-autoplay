"""CLI entry point.

    python3 -m magic_piano.play --list-layout
    python3 -m magic_piano.play songs/twinkle.song --dry-run
    python3 -m magic_piano.play songs/fur_elise.mid --dry-run
    python3 -m magic_piano.play songs/fur_elise.mid --speed 0.8
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import arrange
from . import layout as layout_mod
from . import midi_file
from . import song as song_mod
from .player import Event, Player, build_events, format_events
from .vkbd import VirtualKeyboard


def _start_note(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return layout_mod.note_to_midi(value)


def _print_layout(mapping: dict[int, tuple[str, bool]]) -> None:
    notes = sorted(mapping)
    print(f"range: {layout_mod.midi_to_note(notes[0])} .. {layout_mod.midi_to_note(notes[-1])}")
    for note in notes:
        print(f"{layout_mod.midi_to_note(note):>4}  {layout_mod.describe(mapping[note])}")


def _parse_tracks(value: str | None) -> set[int] | None:
    if not value:
        return None
    return {int(part) for part in value.replace(",", " ").split()}


def _print_midi_info(path: str, include_drums: bool) -> None:
    info = midi_file.inspect(path)
    notes = midi_file.read_notes(path, include_drums=include_drums)
    by_track: dict[int, list] = defaultdict(list)
    for note in notes:
        by_track[note.track].append(note)

    print(f"format {info.fmt}, division {info.division}")
    for index, name in enumerate(info.tracks, start=1):
        track_notes = by_track.get(index - 1, [])
        if not track_notes:
            print(f"  {index}: {name} — no playable notes")
            continue
        pitches = [note.pitch for note in track_notes]
        end = max(note.start + note.duration for note in track_notes)
        low, high = layout_mod.midi_to_note(min(pitches)), layout_mod.midi_to_note(max(pitches))
        print(f"  {index}: {name} — {len(track_notes)} notes, {low}..{high}, {end:.1f}s")


def _load_midi(path: str, args, mapping):
    if args.info:
        _print_midi_info(path, args.drums)
        return None
    notes = midi_file.read_notes(
        path, tracks=args.tracks, include_drums=args.drums
    )
    events, report = arrange.prepare(
        notes,
        mapping,
        transpose=args.transpose,
        fit=not args.no_fit,
        gate=args.gate if args.gate is not None else 1.0,
        speed=args.speed,
    )
    parts = [f"{len(notes)} notes"]
    if report.shift:
        parts.append(f"octave shift {report.shift:+d}")
    if report.folded:
        parts.append(f"{report.folded} folded")
    if report.dropped:
        parts.append(f"{report.dropped} dropped")
    if report.conflicts:
        parts.append(f"{report.conflicts} key conflicts")
    if events:
        parts.append(f"{events[-1].time:.1f}s")
    print(", ".join(parts), file=sys.stderr)
    return events


def _load_song(path: str, args, mapping):
    loaded = song_mod.load(path)
    bpm = args.bpm or loaded.bpm
    gate = args.gate if args.gate is not None else 0.9
    events, skipped = build_events(
        loaded.tokens, mapping, beat=60.0 / bpm, gate=gate
    )
    if args.speed != 1.0:
        events = [
            Event(event.time / args.speed, event.down, event.char, event.shift)
            for event in events
        ]
    if skipped:
        print(f"skipped outside range: {' '.join(skipped)}", file=sys.stderr)
    print(f"{len(loaded.tokens)} notes, {bpm:g} bpm", file=sys.stderr)
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play a song into the focused window.")
    parser.add_argument("song", nargs="?", help="path to a .song or .mid file")
    parser.add_argument("--list-layout", action="store_true", help="print the note/key table")
    parser.add_argument("--start-note", default="C3", help="note of the first white key")
    parser.add_argument("--bpm", type=float, help="override tempo for .song files")
    parser.add_argument(
        "--gate", type=float, help="note length fraction (song 0.9, midi 1.0)"
    )
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed multiplier")
    parser.add_argument("--transpose", type=int, default=0, help="semitone shift (MIDI)")
    parser.add_argument("--no-fit", action="store_true", help="do not auto-select octave (MIDI)")
    parser.add_argument("--tracks", help="1-based track list for MIDI, e.g. 1,2")
    parser.add_argument("--drums", action="store_true", help="include MIDI channel 10")
    parser.add_argument(
        "--no-shift-pause",
        action="store_true",
        help="keep Shift held while pressing white keys (old behavior)",
    )
    parser.add_argument("--info", action="store_true", help="show MIDI tracks and exit")
    parser.add_argument("--countdown", type=float, default=3.0, help="seconds before playing")
    parser.add_argument("--dry-run", action="store_true", help="print the timeline, send nothing")
    args = parser.parse_args(argv)

    mapping = layout_mod.build_layout(_start_note(args.start_note))

    if args.list_layout:
        _print_layout(mapping)
        return 0

    if not args.song:
        parser.error("song file is required (or use --list-layout)")

    is_midi = args.song.lower().endswith((".mid", ".midi"))
    try:
        if is_midi:
            args.tracks = _parse_tracks(args.tracks)
            events = _load_midi(args.song, args, mapping)
            if events is None:
                return 0
        else:
            events = _load_song(args.song, args, mapping)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(format_events(events))
        return 0

    if args.countdown > 0:
        print(f"focus the game window, starting in {args.countdown:g}s...", file=sys.stderr)
        import time

        time.sleep(args.countdown)

    with VirtualKeyboard() as keyboard:
        player = Player(keyboard, pause_shift=not args.no_shift_pause)
        try:
            player.play(events)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            player.release_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
