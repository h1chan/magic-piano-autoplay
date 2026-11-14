"""CLI entry point.

    python3 -m magic_piano.play --list-layout
    python3 -m magic_piano.play songs/twinkle.song --dry-run
    python3 -m magic_piano.play songs/twinkle.song --bpm 90
"""

from __future__ import annotations

import argparse
import sys

from . import layout as layout_mod
from . import song as song_mod
from .player import Player, build_events, format_events
from .vkbd import KEY_CODES, VirtualKeyboard


def _start_note(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return layout_mod.note_to_midi(value)


def _print_layout(mapping: dict[int, tuple[str, bool]]) -> None:
    notes = sorted(mapping)
    print(f"range: {layout_mod.midi_to_note(notes[0])} .. {layout_mod.midi_to_note(notes[-1])}")
    for note in notes:
        label = layout_mod.describe(mapping[note])
        print(f"{layout_mod.midi_to_note(note):>4}  {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Play a song into the focused window.")
    parser.add_argument("song", nargs="?", help="path to a .song file")
    parser.add_argument("--list-layout", action="store_true", help="print the note/key table")
    parser.add_argument("--start-note", default="C3", help="note of the first white key")
    parser.add_argument("--bpm", type=float, help="override the song tempo")
    parser.add_argument("--gate", type=float, default=0.9, help="note length as a beat fraction")
    parser.add_argument("--countdown", type=float, default=3.0, help="seconds before playing")
    parser.add_argument("--dry-run", action="store_true", help="print the timeline, send nothing")
    args = parser.parse_args(argv)

    mapping = layout_mod.build_layout(_start_note(args.start_note))

    if args.list_layout:
        _print_layout(mapping)
        return 0

    if not args.song:
        parser.error("song file is required (or use --list-layout)")

    loaded = song_mod.load(args.song)
    bpm = args.bpm or loaded.bpm
    beat = 60.0 / bpm
    events, skipped = build_events(loaded.tokens, mapping, beat, args.gate)

    if skipped:
        print(f"skipped outside range: {' '.join(skipped)}", file=sys.stderr)
    duration = events[-1].time if events else 0.0
    print(f"{len(loaded.tokens)} notes, {bpm:g} bpm, {duration:.1f}s", file=sys.stderr)

    if args.dry_run:
        print(format_events(events))
        return 0

    if args.countdown > 0:
        print(f"focus the game window, starting in {args.countdown:g}s...", file=sys.stderr)
        import time

        time.sleep(args.countdown)

    with VirtualKeyboard() as keyboard:
        player = Player(keyboard)
        try:
            player.play(events)
        except KeyboardInterrupt:
            print("interrupted", file=sys.stderr)
            player.release_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
