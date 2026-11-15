"""Interactive terminal interface for the piano player.

    python3 -m magic_piano            # or: python3 -m magic_piano.tui

Browse songs with the keyboard, filter them, play into the Sober window and
stop at any time. No third-party packages: only ``curses`` from the standard
library.
"""

from __future__ import annotations

import argparse
import curses
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import layout as layout_mod
from . import loader, midi_file
from . import song as song_mod
from .hypr import DEFAULT_TARGET, Hyprland, HyprlandError, HyprlandKeyboard, Window
from .player import PlaybackStopped, Player
from .vkbd import VirtualKeyboard

SONG_DIR = Path(__file__).resolve().parent.parent / "songs"
CATEGORIES = ("All", "Classical", "Game", "Film", "Other")
MIDI_SUFFIXES = (".mid", ".midi")
SONG_SUFFIXES = (".song",)

HELP_LINES = (
    ("Up/Down, j/k", "move through the list"),
    ("PgUp/PgDn", "move one page"),
    ("Home/End, g/G", "first or last song"),
    ("Enter, Space", "play selected / stop playback"),
    ("s", "stop playback"),
    ("+ / -", "playback speed (0.25 - 3.00)"),
    ("t / T", "transpose down / up one semitone"),
    ("0", "reset speed and transpose"),
    ("/", "search by title"),
    ("c", "next category"),
    ("w", "choose target window"),
    ("u", "toggle targeted input / system-wide uinput"),
    ("r", "rescan the songs folder"),
    ("q", "quit (stops playback)"),
)


@dataclass
class Track:
    path: Path
    title: str
    category: str
    kind: str
    notes: int | None = None
    duration: float | None = None
    tracks: int | None = None
    error: str = ""
    scanned: bool = False


@dataclass
class TrackInfo:
    notes: int
    duration: float
    tracks: int


def category_of(title: str) -> str:
    prefix, separator, _ = title.partition(" - ")
    if separator and prefix in ("Classical", "Game", "Film"):
        return prefix
    return "Other"


def scan_tracks(directory: str | Path) -> list[Track]:
    directory = Path(directory)
    tracks = []
    for path in sorted(directory.iterdir()):
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in MIDI_SUFFIXES + SONG_SUFFIXES:
            continue
        tracks.append(
            Track(
                path=path,
                title=path.stem,
                category=category_of(path.stem),
                kind="MIDI" if suffix in MIDI_SUFFIXES else "Song",
            )
        )
    return sorted(tracks, key=lambda track: track.title.casefold())


def filter_tracks(
    tracks: list[Track], query: str = "", category: str = "All"
) -> list[Track]:
    needle = query.casefold().strip()
    result = []
    for track in tracks:
        if category != "All" and track.category != category:
            continue
        if needle and needle not in track.title.casefold():
            continue
        result.append(track)
    return result


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def window_selector(window: Window, windows: list[Window]) -> str:
    """Prefer a class selector when it is unique, otherwise the address."""
    same_class = [item for item in windows if item.class_name == window.class_name]
    if len(same_class) == 1:
        return f"class:{window.class_name}"
    return f"address:{window.address}"


def read_track_info(path: str | Path) -> TrackInfo:
    path = Path(path)
    if path.suffix.lower() in MIDI_SUFFIXES:
        info = midi_file.inspect(str(path))
        notes = midi_file.read_notes(str(path))
        duration = max((note.start + note.duration for note in notes), default=0.0)
        return TrackInfo(notes=len(notes), duration=duration, tracks=len(info.tracks))
    song = song_mod.load(str(path))
    return TrackInfo(
        notes=len(song.tokens),
        duration=len(song.tokens) * song.beat_seconds,
        tracks=1,
    )


class Library:
    """Song list plus a background thread filling in note counts and lengths."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.tracks: list[Track] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def reload(self) -> list[Track]:
        self.stop()
        try:
            self.tracks = scan_tracks(self.directory)
        except OSError:
            self.tracks = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._scan, daemon=True)
        self._thread.start()
        return self.tracks

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _scan(self) -> None:
        for track in self.tracks:
            if self._stop.is_set():
                return
            try:
                info = read_track_info(track.path)
            except (OSError, ValueError) as error:
                track.error = str(error)
            else:
                track.notes = info.notes
                track.duration = info.duration
                track.tracks = info.tracks
            track.scanned = True


class Playback:
    """Run one song in a thread and expose its state to the interface."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = "idle"          # idle / loading / playing / done / stopped / error
        self.title = ""
        self.path: Path | None = None
        self.error = ""
        self.where = ""
        self.total = 0.0
        self.events_done = 0
        self.events_total = 0
        self.started_at = 0.0
        self.elapsed_at_stop = 0.0
        self.countdown_left = 0.0

    def start(
        self,
        path: str | Path,
        mapping: dict[int, tuple[str, bool]],
        *,
        speed: float = 1.0,
        transpose: int = 0,
        gate: float | None = None,
        selector: str = DEFAULT_TARGET,
        global_input: bool = False,
        countdown: float = 0.0,
    ) -> None:
        self.stop(wait=True)
        self._stop = threading.Event()
        self.title = Path(path).stem
        self.path = Path(path)
        self.state = "loading"
        self.error = ""
        self.where = ""
        self.total = 0.0
        self.events_done = 0
        self.events_total = 0
        self.started_at = 0.0
        self.elapsed_at_stop = 0.0
        self.countdown_left = countdown
        self._thread = threading.Thread(
            target=self._run,
            args=(
                path, mapping, speed, transpose, gate, selector,
                global_input, countdown,
            ),
            daemon=True,
        )
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        if self.state in ("loading", "countdown", "playing"):
            if self.state == "playing" and self.started_at:
                self.elapsed_at_stop = min(
                    self.total, max(0.0, time.perf_counter() - self.started_at)
                )
            self._stop.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        if self.state in ("loading", "countdown", "playing"):
            self.state = "stopped"

    def elapsed(self) -> float:
        if self.state == "playing":
            return min(self.total, max(0.0, time.perf_counter() - self.started_at))
        if self.state == "done":
            return self.total
        if self.state == "stopped":
            return self.elapsed_at_stop
        return 0.0

    def _run(
        self,
        path: str | Path,
        mapping,
        speed: float,
        transpose: int,
        gate: float | None,
        selector: str,
        global_input: bool,
        countdown: float,
    ) -> None:
        try:
            loaded = loader.load(
                path,
                mapping,
                speed=speed,
                transpose=transpose,
                gate=gate,
            )
            if not loaded.events:
                raise ValueError("no playable notes")
            self.total = loaded.duration
            self.events_total = len(loaded.events)
            if self._stop.is_set():
                self.state = "stopped"
                return

            if countdown > 0:
                self.state = "countdown"
                deadline = time.perf_counter() + countdown
                while time.perf_counter() < deadline:
                    if self._stop.is_set():
                        self.state = "stopped"
                        return
                    self.countdown_left = max(0.0, deadline - time.perf_counter())
                    time.sleep(0.05)
                self.countdown_left = 0.0
                if self._stop.is_set():
                    self.state = "stopped"
                    return

            guard = None
            if global_input:
                keyboard = VirtualKeyboard()
                self.where = "system-wide (uinput)"
                try:
                    hypr = Hyprland()
                    # Prefer the game window: if focus is still in the
                    # terminal after the countdown, the guard aborts instead
                    # of typing the song into the terminal.
                    target = hypr.find(DEFAULT_TARGET) or hypr.active()
                except HyprlandError:
                    target = None
                if target is not None:
                    start_address = target.address
                    checked = [0.0]

                    def guard() -> bool:
                        # Do not type into the terminal if focus moves away.
                        now = time.perf_counter()
                        if now - checked[0] < 0.2:
                            return True
                        checked[0] = now
                        current = hypr.active()
                        return current is not None and current.address == start_address
            else:
                hypr = Hyprland()
                window = hypr.find(selector)
                if window is None:
                    raise HyprlandError(
                        f"window not found: {selector}. "
                        "Press w to choose another window."
                    )
                keyboard = HyprlandKeyboard(
                    selector, client=hypr, address=window.address
                )
                self.where = window.title or window.class_name

            player = Player(keyboard)
            self.state = "playing"
            self.started_at = time.perf_counter()
            with keyboard:
                player.play(
                    loaded.events,
                    guard=guard,
                    stop=self._stop.is_set,
                    on_event=self._progress,
                )
        except PlaybackStopped:
            self.state = "stopped"
        except (HyprlandError, OSError, ValueError, RuntimeError) as error:
            self.state = "error"
            self.error = str(error)
        finally:
            if self.state == "playing":
                self.state = "done"

    def _progress(self, done: int, total: int) -> None:
        self.events_done = done
        self.events_total = total


def _clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "~"


def _wrap(text: str, width: int) -> list[str]:
    if width <= 0:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class App:
    def __init__(
        self,
        songs: str | Path = SONG_DIR,
        *,
        selector: str = DEFAULT_TARGET,
        global_input: bool = False,
    ):
        self.library = Library(songs)
        self.playback = Playback()
        self.mapping = layout_mod.build_layout()
        self.selector = selector
        self.target_label = "Sober"
        self.global_input = global_input
        self.query = ""
        self.category = "All"
        self.searching = False
        self.cursor = 0
        self.offset = 0
        self.speed = 1.0
        self.transpose = 0
        self.message = ""
        self.message_kind = "info"   # info / warn / error
        self.overlay: str | None = None
        self.picker: list[Window] = []
        self.picker_index = 0
        self.running = True

    # --- lifecycle -----------------------------------------------------

    def run(self, screen) -> int:
        self.screen = screen
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        screen.timeout(100)
        self._init_colors()
        self.library.reload()
        self._refresh_target()
        try:
            while self.running:
                self._draw()
                key = screen.getch()
                if key == -1:
                    continue
                if key == 3:
                    self.running = False
                    continue
                if key == curses.KEY_RESIZE:
                    self._clamp()
                    continue
                if self.overlay is not None:
                    self._overlay_key(key)
                elif self.searching:
                    self._search_key(key)
                else:
                    self._normal_key(key)
        finally:
            self.playback.stop(wait=True)
            self.library.stop()
        return 0

    def _init_colors(self) -> None:
        if not curses.has_colors():
            self.colors = False
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_MAGENTA, -1)
            self.colors = True
        except curses.error:
            self.colors = False

    def _color(self, pair: int, fallback: int = 0) -> int:
        return curses.color_pair(pair) if self.colors else fallback

    # --- state ---------------------------------------------------------

    def filtered(self) -> list[Track]:
        return filter_tracks(self.library.tracks, self.query, self.category)

    def current(self) -> Track | None:
        tracks = self.filtered()
        if not tracks:
            return None
        self.cursor = max(0, min(self.cursor, len(tracks) - 1))
        return tracks[self.cursor]

    def _refresh_target(self) -> None:
        if self.global_input:
            self.target_label = "system-wide"
            return
        try:
            window = Hyprland().find(self.selector)
        except HyprlandError:
            self.target_label = "Hyprland?"
            return
        if window is not None:
            self.target_label = window.title or window.class_name
        else:
            self.target_label = "not found"

    def _set_message(self, text: str, kind: str = "info") -> None:
        self.message = text
        self.message_kind = kind

    def _clamp(self) -> None:
        tracks = self.filtered()
        self.cursor = max(0, min(self.cursor, max(0, len(tracks) - 1)))

    # --- actions -------------------------------------------------------

    def _play(self) -> None:
        track = self.current()
        if track is None:
            return
        if track.error:
            self._set_message(f"cannot play: {track.error}", "error")
            return
        self.playback.start(
            track.path,
            self.mapping,
            speed=self.speed,
            transpose=self.transpose,
            selector=self.selector,
            global_input=self.global_input,
            countdown=3.0 if self.global_input else 0.0,
        )
        if self.global_input:
            self._set_message("starting in 3s - focus the game window", "warn")
        else:
            self._set_message(f"playing {track.title}", "info")

    def _stop(self) -> None:
        if self.playback.state in ("loading", "countdown", "playing"):
            self.playback.stop(wait=False)
            self._set_message("stopped", "info")

    def _toggle_play(self) -> None:
        if self.playback.state in ("loading", "countdown", "playing"):
            self._stop()
        else:
            self._play()

    def _change_speed(self, delta: float) -> None:
        self.speed = round(min(3.0, max(0.25, self.speed + delta)), 2)
        suffix = " (next play)" if self.playback.state == "playing" else ""
        self._set_message(f"speed {self.speed:.2f}x{suffix}", "info")

    def _change_transpose(self, delta: int) -> None:
        self.transpose = min(24, max(-24, self.transpose + delta))
        suffix = " (next play)" if self.playback.state == "playing" else ""
        self._set_message(f"transpose {self.transpose:+d}{suffix}", "info")

    def _cycle_category(self) -> None:
        index = CATEGORIES.index(self.category)
        self.category = CATEGORIES[(index + 1) % len(CATEGORIES)]
        self.cursor = 0
        self.offset = 0
        self._set_message(f"category: {self.category}", "info")

    def _choose_window(self) -> None:
        try:
            windows = Hyprland().windows()
        except HyprlandError as error:
            self._set_message(f"window list failed: {error}", "error")
            return
        if not windows:
            self._set_message("no windows found", "warn")
            return
        self.picker = windows
        self.picker_index = 0
        self.overlay = "window"

    def _select_window(self) -> None:
        window = self.picker[self.picker_index]
        self.selector = window_selector(window, self.picker)
        self.global_input = False
        self.target_label = window.title or window.class_name
        self.overlay = None
        self._set_message(f"target: {window.class_name} - {window.title}", "info")

    def _toggle_global(self) -> None:
        self.global_input = not self.global_input
        self._refresh_target()
        if self.global_input:
            self._set_message("system-wide uinput: 3s countdown, focus guard", "warn")
        else:
            self._set_message(f"target: {self.target_label}", "info")

    def _rescan(self) -> None:
        self.library.reload()
        self.cursor = 0
        self.offset = 0
        self._set_message(f"found {len(self.library.tracks)} songs", "info")

    def _move(self, delta: int) -> None:
        tracks = self.filtered()
        if not tracks:
            return
        self.cursor = max(0, min(len(tracks) - 1, self.cursor + delta))

    # --- input ---------------------------------------------------------

    def _search_key(self, key: int) -> None:
        if key in (10, 13, curses.KEY_ENTER):
            self.searching = False
            self._set_message(
                f"{len(self.filtered())} match(es)" if self.query else "filter cleared"
            )
        elif key == 27:
            self.searching = False
            self.query = ""
            self.cursor = 0
            self.offset = 0
            self._set_message("filter cleared")
        elif key in (curses.KEY_BACKSPACE, 8, 127):
            self.query = self.query[:-1]
            self.cursor = 0
            self.offset = 0
        elif key == 21:  # Ctrl-U
            self.query = ""
            self.cursor = 0
            self.offset = 0
        elif key == curses.KEY_UP:
            self._move(-1)
        elif key == curses.KEY_DOWN:
            self._move(1)
        elif 32 <= key < 127:
            self.query += chr(key)
            self.cursor = 0
            self.offset = 0

    def _normal_key(self, key: int) -> None:
        if key in (curses.KEY_UP, ord("k")):
            self._move(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move(1)
        elif key == curses.KEY_PPAGE:
            self._move(-self._page())
        elif key == curses.KEY_NPAGE:
            self._move(self._page())
        elif key in (curses.KEY_HOME, ord("g")):
            self.cursor = 0
        elif key in (curses.KEY_END, ord("G")):
            self.cursor = max(0, len(self.filtered()) - 1)
        elif key in (10, 13, curses.KEY_ENTER):
            self._play()
        elif key == ord(" "):
            self._toggle_play()
        elif key == ord("s"):
            self._stop()
        elif key in (ord("+"), ord("=")):
            self._change_speed(0.05)
        elif key == ord("-"):
            self._change_speed(-0.05)
        elif key == ord("t"):
            self._change_transpose(-1)
        elif key == ord("T"):
            self._change_transpose(1)
        elif key == ord("0"):
            self.speed, self.transpose = 1.0, 0
            self._set_message("speed 1.00x, transpose +0")
        elif key == ord("/"):
            self.searching = True
        elif key == ord("c"):
            self._cycle_category()
        elif key == ord("w"):
            self._choose_window()
        elif key == ord("u"):
            self._toggle_global()
        elif key == ord("r"):
            self._rescan()
            self._refresh_target()
        elif key == 27:
            if self.query:
                self.query = ""
                self.cursor = 0
                self.offset = 0
                self._set_message("filter cleared")
        elif key == ord("?"):
            self.overlay = "help"
        elif key in (ord("q"), 3):
            self.running = False

    def _page(self) -> int:
        height = max(1, self.screen.getmaxyx()[0] - 6)
        return max(1, height - 1)

    def _overlay_key(self, key: int) -> None:
        if key in (27, ord("q")):
            self.overlay = None
        elif self.overlay == "help":
            self.overlay = None
        elif key in (curses.KEY_UP, ord("k")):
            self.picker_index = max(0, self.picker_index - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.picker_index = min(len(self.picker) - 1, self.picker_index + 1)
        elif key in (10, 13, curses.KEY_ENTER):
            self._select_window()

    # --- drawing -------------------------------------------------------

    def _add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        try:
            self.screen.addnstr(y, x, text, max(0, width - x), attr)
        except curses.error:
            pass

    def _hline(self, y: int, char: str = "-") -> None:
        height, width = self.screen.getmaxyx()
        if 0 <= y < height:
            self._add(y, 0, char * (width - 1))

    def _draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 10 or width < 40:
            self._add(0, 0, "terminal too small")
            self.screen.refresh()
            return

        status_y = height - 3
        if self.overlay is not None:
            self._draw_header(width)
            self._hline(2)
            self._draw_help(height - 1, width)
        else:
            self._draw_header(width)
            self._draw_filter(width)
            self._hline(2)
            show_details = width >= 84
            list_width = int(width * 0.58) if show_details else width - 2
            body_top = 3
            body_height = status_y - body_top
            self._draw_list(body_top, list_width, body_height)
            if show_details:
                for row in range(body_height):
                    self._add(body_top + row, list_width, "|", curses.A_DIM)
                self._draw_details(
                    body_top, list_width + 2, width - list_width - 2, body_height
                )
            self._draw_status(status_y, width)
            self._draw_progress(height - 2, width)
            self._draw_help(height - 1, width)

        if self.overlay == "help":
            self._draw_help_overlay(height, width)
        elif self.overlay == "window":
            self._draw_window_overlay(height, width)

        self.screen.refresh()

    def _draw_header(self, width: int) -> None:
        mode = "GLOBAL" if self.global_input else "target"
        line = (
            f" Magic Piano  {len(self.filtered())}/{len(self.library.tracks)}"
            f"  |  {mode}: {self.target_label}"
            f"  |  {self.speed:.2f}x  |  transpose {self.transpose:+d}"
        )
        self._add(0, 0, _clip(line, width - 1), curses.A_BOLD | self._color(1))

    def _draw_filter(self, width: int) -> None:
        if self.searching:
            line = f" Search: {self.query}_"
            attr = self._color(3)
        else:
            shown = self.query if self.query else "-"
            line = f" Filter: {shown}   Category: {self.category}"
            attr = self._color(5)
        self._add(1, 0, _clip(line, width - 1), attr)

    def _draw_list(self, top: int, width: int, height: int) -> None:
        tracks = self.filtered()
        if not tracks:
            self._add(top, 1, "nothing matches the filter")
            return
        if self.cursor < self.offset:
            self.offset = self.cursor
        if self.cursor >= self.offset + height:
            self.offset = self.cursor - height + 1
        self.offset = max(0, min(self.offset, max(0, len(tracks) - height)))

        duration_width = 7
        notes_width = 6
        title_width = max(8, width - duration_width - notes_width - 6)
        for row, track in enumerate(tracks[self.offset:self.offset + height]):
            index = self.offset + row
            selected = index == self.cursor
            playing = (
                self.playback.path == track.path
                and self.playback.state in ("loading", "countdown", "playing")
            )
            marker = ">" if selected else " "
            dot = "*" if playing else " "
            length = format_duration(track.duration)
            notes = str(track.notes) if track.notes is not None else "..."
            line = (
                f"{marker}{dot} {track.title[:title_width]:<{title_width}} "
                f"{length:>{duration_width}} {notes:>{notes_width}}"
            )
            attr = curses.A_REVERSE if selected else 0
            if playing:
                attr |= self._color(2)
            if track.error:
                attr |= self._color(4)
            self._add(top + row, 0, _clip(line, width - 1), attr)

    def _draw_details(self, top: int, x: int, width: int, height: int) -> None:
        track = self.current()
        if track is None:
            return
        rows = []
        rows.append((track.title, curses.A_BOLD))
        rows.append((f"{track.category}  |  {track.kind}", self._color(1)))
        rows.append(("", 0))
        for line in _wrap(str(track.path), width - 1):
            rows.append((line, curses.A_DIM))
        rows.append(("", 0))
        if track.error:
            for line in _wrap(f"error: {track.error}", width - 1):
                rows.append((line, self._color(4)))
        else:
            length = format_duration(track.duration)
            notes = track.notes if track.notes is not None else "..."
            if track.scanned:
                rows.append((f"{length}   {notes} notes   {track.tracks} tracks", 0))
            else:
                rows.append(("reading file...", curses.A_DIM))
        rows.append(("", 0))
        if self.playback.path == track.path:
            state = self.playback.state
            if state in ("loading", "countdown", "playing"):
                rows.append(("now playing", curses.A_BOLD | self._color(2)))
            elif state == "done":
                rows.append(("finished", self._color(2)))
            elif state == "stopped":
                rows.append(("stopped", self._color(3)))
            elif state == "error":
                for line in _wrap(self.playback.error, width - 1):
                    rows.append((line, self._color(4)))
        rows.append(("Enter or Space: play", curses.A_DIM))

        for row, (text, attr) in enumerate(rows[:height]):
            self._add(top + row, x, _clip(text, width - 1), attr)

    def _draw_status(self, y: int, width: int) -> None:
        playback = self.playback
        if playback.state == "loading":
            text = f"loading {playback.title}..."
            kind = "info"
        elif playback.state == "countdown":
            left = max(1, int(playback.countdown_left + 0.999))
            text = f"starting in {left}s - focus the game window"
            kind = "warn"
        elif playback.state == "playing":
            text = f"playing {playback.title}  ->  {playback.where}"
            kind = "ok"
        elif playback.state == "done":
            text = f"finished {playback.title}"
            kind = "ok"
        elif playback.state == "error":
            text = f"error: {playback.error}"
            kind = "error"
        elif self.message:
            text = self.message
            kind = self.message_kind
        else:
            text = "ready"
            kind = "info"

        colors = {"ok": self._color(2), "warn": self._color(3),
                  "error": self._color(4), "info": 0}
        self._add(y, 0, _clip(" " + text, width - 1), colors.get(kind, 0))

    def _draw_progress(self, y: int, width: int) -> None:
        state = self.playback.state
        if state not in ("loading", "countdown", "playing", "done", "stopped"):
            total = sum(t.duration or 0.0 for t in self.library.tracks)
            scanned = sum(1 for t in self.library.tracks if t.scanned)
            text = (
                f" {len(self.library.tracks)} pieces, {format_duration(total)} total"
                f"  ({scanned}/{len(self.library.tracks)} scanned)"
            )
            self._add(y, 0, _clip(text, width - 1), curses.A_DIM)
            return
        elapsed = self.playback.elapsed()
        total = self.playback.total
        bar_width = max(10, min(40, width - 24))
        ratio = 0.0 if total <= 0 else min(1.0, elapsed / total)
        filled = int(ratio * bar_width)
        bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
        text = f" {bar} {format_duration(elapsed)} / {format_duration(total)}"
        attr = self._color(2) if state == "playing" else curses.A_DIM
        self._add(y, 0, _clip(text, width - 1), attr)

    def _draw_help(self, y: int, width: int) -> None:
        if width >= 115:
            line = (
                " Up/Down move  Enter play  s stop  +/- speed  t/T transpose"
                "  / search  c category  w window  ? help  q quit"
            )
        elif width >= 85:
            line = (
                " Up/Down move  Enter play  s stop  +/- speed  / search"
                "  c category  w window  ? help  q quit"
            )
        else:
            line = (
                " Up/Down move  Enter play  s stop  +/- speed"
                "  / search  ? help  q quit"
            )
        self._add(y, 0, _clip(line, width - 1), curses.A_DIM)

    def _panel(self, height: int, width: int, title: str) -> tuple[int, int, int, int]:
        box_h = min(height - 4, len(HELP_LINES) + 6)
        box_w = min(width - 4, 64)
        top = max(0, (height - box_h) // 2)
        left = max(0, (width - box_w) // 2)
        for row in range(box_h):
            self._add(top + row, left, " " * box_w, self._color(1))
        border = "+" + "-" * (box_w - 2) + "+"
        self._add(top, left, border, self._color(1))
        self._add(top + box_h - 1, left, border, self._color(1))
        for row in range(1, box_h - 1):
            self._add(top + row, left, "|", self._color(1))
            self._add(top + row, left + box_w - 1, "|", self._color(1))
        self._add(top, left + 2, f" {title} ", curses.A_BOLD | self._color(1))
        return top, left, box_h, box_w

    def _draw_help_overlay(self, height: int, width: int) -> None:
        top, left, box_h, box_w = self._panel(height, width, "keys")
        row = top + 2
        for key, description in HELP_LINES:
            if row >= top + box_h - 1:
                break
            self._add(row, left + 2, f"{key:<14} {description}"[: box_w - 3])
            row += 1

    def _draw_window_overlay(self, height: int, width: int) -> None:
        rows = max(1, min(len(self.picker), height - 7))
        box_h = rows + 5
        box_w = min(width - 4, 84)
        top = max(0, (height - box_h) // 2)
        left = max(0, (width - box_w) // 2)
        for row in range(box_h):
            self._add(top + row, left, " " * box_w, self._color(1))
        border = "+" + "-" * (box_w - 2) + "+"
        self._add(top, left, border, self._color(1))
        self._add(top + box_h - 1, left, border, self._color(1))
        for row in range(1, box_h - 1):
            self._add(top + row, left, "|", self._color(1))
            self._add(top + row, left + box_w - 1, "|", self._color(1))
        self._add(top, left + 2, " target window ", curses.A_BOLD | self._color(1))

        start = getattr(self, "_picker_offset", 0)
        if self.picker_index < start:
            start = self.picker_index
        elif self.picker_index >= start + rows:
            start = self.picker_index - rows + 1
        self._picker_offset = start

        for row, window in enumerate(self.picker[start:start + rows]):
            index = start + row
            line = f"{window.class_name}  |  {window.title}"
            attr = curses.A_REVERSE if index == self.picker_index else 0
            self._add(top + 1 + row, left + 2, _clip(line, box_w - 4), attr)
        self._add(
            top + box_h - 2,
            left + 2,
            _clip("Enter select   Esc cancel   Up/Down move", box_w - 4),
            curses.A_DIM,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Browse and play the piano collection in a terminal."
    )
    parser.add_argument("--songs", default=str(SONG_DIR), help="folder with songs")
    parser.add_argument(
        "--window",
        default=DEFAULT_TARGET,
        help=f"target window selector (default {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--global",
        dest="global_input",
        action="store_true",
        help="start in system-wide uinput mode",
    )
    args = parser.parse_args(argv)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("error: the interface needs a terminal", file=sys.stderr)
        return 2

    os.environ.setdefault("ESCDELAY", "25")
    app = App(args.songs, selector=args.window, global_input=args.global_input)
    try:
        return curses.wrapper(app.run)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
