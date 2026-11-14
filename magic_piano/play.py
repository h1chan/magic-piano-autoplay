"""CLI entry point.

    python3 -m magic_piano.play --list-layout
    python3 -m magic_piano.play --list-windows
    python3 -m magic_piano.play songs/twinkle.song --dry-run
    python3 -m magic_piano.play songs/fur_elise.mid --speed 0.8
    python3 -m magic_piano.play songs/fur_elise.mid --global

By default keys are delivered to the Sober window only, through Hyprland.
``--global`` falls back to a system-wide uinput keyboard for other targets.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

from . import layout as layout_mod
from . import loader
from . import midi_file
from .hypr import (
    DEFAULT_TARGET,
    Hyprland,
    HyprlandError,
    HyprlandKeyboard,
    Window,
)
from .player import (
    PlaybackAborted,
    Player,
    format_events,
)
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


def _print_windows(hypr: Hyprland) -> None:
    windows = hypr.windows()
    if not windows:
        print("no windows")
        return
    for window in windows:
        print(f"{window.address}  {window.class_name:<32}  {window.title}")


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
    loaded = loader.load(
        path,
        mapping,
        transpose=args.transpose,
        fit=not args.no_fit,
        gate=args.gate,
        speed=args.speed,
        tracks=args.tracks,
        drums=args.drums,
    )
    print(loaded.summary(), file=sys.stderr)
    return loaded.events


def _load_song(path: str, args, mapping):
    loaded = loader.load(
        path,
        mapping,
        bpm=args.bpm,
        gate=args.gate,
        speed=args.speed,
    )
    if loaded.skipped:
        print(f"skipped outside range: {' '.join(loaded.skipped)}", file=sys.stderr)
    print(f"{loaded.notes} notes, {loaded.bpm:g} bpm", file=sys.stderr)
    return loaded.events


def _resolve_target(args) -> tuple[str | None, str, Hyprland | None]:
    """Return (selector, label, client); selector None means system-wide."""
    if args.global_input:
        try:
            hypr = Hyprland()
        except HyprlandError:
            hypr = None
        return None, "system-wide (uinput)", hypr

    hypr = Hyprland()
    selector = args.window or DEFAULT_TARGET
    window = hypr.find(selector)
    if window is None:
        raise HyprlandError(
            f"window not found: {selector}. "
            "Use --list-windows to see open windows, or --global for system-wide input."
        )
    return selector, window.label, hypr


def _safe_release(player: Player) -> None:
    try:
        player.release_all()
    except HyprlandError:
        pass


def _focus_guard(hypr: Hyprland, target: Window):
    def guard() -> bool:
        active = hypr.active()
        return active is not None and active.address == target.address

    return guard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Play a song into the Sober window (or the whole system)."
    )
    parser.add_argument("song", nargs="?", help="path to a .song or .mid file")
    parser.add_argument("--list-layout", action="store_true", help="print the note/key table")
    parser.add_argument("--list-windows", action="store_true", help="print Hyprland windows")
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
        "--window",
        metavar="SELECTOR",
        help="target window: class:NAME, title:NAME or address:0x... "
        f"(default {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--global",
        dest="global_input",
        action="store_true",
        help="send keys system-wide through uinput instead of one window",
    )
    parser.add_argument(
        "--no-guard",
        action="store_true",
        help="with --global: keep typing after focus leaves the game window",
    )
    parser.add_argument(
        "--no-shift-pause",
        action="store_true",
        help="uinput only: keep Shift held while pressing white keys (old behavior)",
    )
    parser.add_argument("--info", action="store_true", help="show MIDI tracks and exit")
    parser.add_argument("--countdown", type=float, default=3.0, help="seconds before playing")
    parser.add_argument("--dry-run", action="store_true", help="print the timeline, send nothing")
    args = parser.parse_args(argv)
    if args.global_input and args.window:
        parser.error("--window and --global are mutually exclusive")

    mapping = layout_mod.build_layout(_start_note(args.start_note))

    if args.list_layout:
        _print_layout(mapping)
        return 0

    if args.list_windows:
        try:
            _print_windows(Hyprland())
        except HyprlandError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
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

    try:
        selector, label, hypr = _resolve_target(args)
    except HyprlandError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    guard = None
    if args.global_input:
        if hypr is not None and not args.no_guard:
            target = hypr.active()
            if target is not None:
                guard = _focus_guard(hypr, target)
        where = "system-wide (uinput)"
        where += ", guard on" if guard else ", guard off"
    else:
        where = label

    if args.countdown > 0:
        print(f"target: {where}; starting in {args.countdown:g}s...", file=sys.stderr)
        time.sleep(args.countdown)

    if args.global_input:
        keyboard = VirtualKeyboard(pause_shift=not args.no_shift_pause)
    else:
        keyboard = HyprlandKeyboard(selector, client=hypr)

    player = Player(keyboard)

    try:
        with keyboard:
            player.play(events, guard=guard)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        _safe_release(player)
    except PlaybackAborted:
        print("focus left the game window: keys released, playback stopped", file=sys.stderr)
        return 1
    except HyprlandError as error:
        _safe_release(player)
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
