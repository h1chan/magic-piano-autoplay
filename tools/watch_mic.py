#!/usr/bin/env python3
"""Log every change of the default microphone volume, with the active window.

WirePlumber does not log volume changes, so the only way to find what changes
the microphone level is to watch it and correlate the moment with the window
that has focus.

    python3 tools/watch_mic.py            # watch until Ctrl+C
    python3 tools/watch_mic.py --log mic.log

The tool is read-only: it never sets the volume. No third-party packages.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime

SOURCE = "@DEFAULT_AUDIO_SOURCE@"


def _run(*command: str) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=1.5
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def mic_state() -> dict[str, str]:
    line = _run("wpctl", "get-volume", SOURCE)
    volume = ""
    muted = "no"
    if line.startswith("Volume:"):
        parts = line[len("Volume:"):].split()
        if parts:
            volume = parts[0]
        muted = "yes" if "[MUTED]" in line else "no"
    device = _run("wpctl", "inspect", SOURCE)
    name = ""
    for row in device.splitlines():
        row = row.strip().lstrip("*").strip()
        if row.startswith("node.name"):
            name = row.split("=", 1)[-1].strip().strip('"')
            break
    return {"volume": volume, "muted": muted, "source": name}


def active_window() -> str:
    raw = _run("hyprctl", "activewindow", "-j")
    if not raw:
        return "?"
    try:
        window = json.loads(raw)
    except json.JSONDecodeError:
        return "?"
    if not window:
        return "?"
    return f"{window.get('class', '?')} — {window.get('title', '?')}"


def describe(state: dict[str, str]) -> str:
    volume = state["volume"] or "?"
    muted = "MUTED" if state["muted"] == "yes" else "unmuted"
    return f"{volume} {muted} ({state['source'] or 'unknown source'})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch the microphone volume.")
    parser.add_argument("--interval", type=float, default=0.2, help="poll interval, seconds")
    parser.add_argument("--log", help="also append lines to this file")
    args = parser.parse_args(argv)

    def report(text: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {text}"
        print(line, flush=True)
        if args.log:
            with open(args.log, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    previous = mic_state()
    report(f"watching; now {describe(previous)}; window: {active_window()}")
    try:
        while True:
            time.sleep(args.interval)
            current = mic_state()
            if current != previous:
                report(f"{describe(previous)}  ->  {describe(current)}; window: {active_window()}")
                previous = current
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
