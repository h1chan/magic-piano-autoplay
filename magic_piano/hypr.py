"""Send key events to one Hyprland window instead of the whole system.

Hyprland can deliver a key press to a specific window:

    hl.dsp.send_key_state({ mods = "SHIFT", key = "q", state = "down", window = w })

The window keeps its focus and every other application stays untouched. The
call is executed through the compositor's IPC socket, so no external tools
are needed and no third-party Python packages are used.

Modifiers are applied to that single event: holding Shift for a black note
does not leak into the next white note, which makes mixed chords safe.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass

DEFAULT_TARGET = "class:org.vinegarhq.Sober"
SELECTOR_FIELDS = ("class", "title", "address")


class HyprlandError(RuntimeError):
    """Hyprland is not running, or the IPC request failed."""


@dataclass(frozen=True)
class Window:
    address: str
    class_name: str
    title: str

    @property
    def label(self) -> str:
        return f"{self.class_name} — {self.title} ({self.address})"


def lua_string(value: str) -> str:
    """Quote a Python string as a Lua string literal (UTF-8 passthrough)."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def parse_selector(selector: str) -> tuple[str, str]:
    """Split ``class:foo``/``title:foo``/``address:0x...`` into field, value.

    A bare value is treated as a window class, which is the common case
    (``--window org.vinegarhq.Sober``).
    """
    if ":" in selector:
        kind, value = selector.split(":", 1)
        if kind in SELECTOR_FIELDS and value:
            return kind, value
    return "class", selector


def _socket_candidates() -> list[str]:
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    candidates: list[str] = []
    if signature:
        candidates.append(f"{runtime}/hypr/{signature}/.socket.sock")
        candidates.append(f"/tmp/hypr/{signature}/.socket.sock")
    # A stale environment can happen when the compositor was restarted;
    # fall back to any live instance of this user.
    for base in (f"{runtime}/hypr", "/tmp/hypr"):
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            path = f"{base}/{entry}/.socket.sock"
            if os.path.exists(path):
                candidates.append(path)
    return candidates


class Hyprland:
    """Minimal Hyprland IPC client (commands + JSON queries)."""

    def __init__(self, socket_path: str | None = None, timeout: float = 2.0):
        self.socket_path = socket_path or self._find_socket()
        self.timeout = timeout

    @staticmethod
    def _find_socket() -> str:
        for path in _socket_candidates():
            if os.path.exists(path):
                return path
        raise HyprlandError(
            "Hyprland IPC socket not found; is Hyprland running? "
            "Use --global to fall back to system-wide uinput."
        )

    def _request(self, request: str) -> str:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(request.encode())
                chunks = []
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
        except OSError as error:
            raise HyprlandError(f"Hyprland IPC failed: {error}") from error
        return b"".join(chunks).decode("utf-8", "replace")

    def eval(self, code: str) -> None:
        reply = self._request("eval " + code).strip()
        if reply != "ok":
            raise HyprlandError(reply or "Hyprland rejected the Lua snippet")

    def _json(self, request: str):
        reply = self._request(request).strip()
        try:
            return json.loads(reply)
        except json.JSONDecodeError as error:
            raise HyprlandError(f"bad Hyprland reply: {reply[:80]}") from error

    def windows(self) -> list[Window]:
        result = self._json("j/clients")
        return [
            Window(
                address=item.get("address", ""),
                class_name=item.get("class", ""),
                title=item.get("title", ""),
            )
            for item in result
            if not item.get("hidden", False)
        ]

    def active(self) -> Window | None:
        item = self._json("j/activewindow")
        if not item or not item.get("address"):
            return None
        return Window(
            address=item.get("address", ""),
            class_name=item.get("class", ""),
            title=item.get("title", ""),
        )

    def find(self, selector: str) -> Window | None:
        kind, value = parse_selector(selector)
        for window in self.windows():
            if getattr(window, "class_name" if kind == "class" else kind) == value:
                return window
        return None


class HyprlandKeyboard:
    """Keyboard driver that sends every key to one Hyprland window."""

    def __init__(
        self,
        selector: str | None = None,
        client: Hyprland | None = None,
        address: str | None = None,
    ):
        self.selector = parse_selector(selector) if selector else None
        self.address = address
        self.client = client or Hyprland()
        self._held: set[tuple[str, bool]] = set()

    def _call(self, key: str, shift: bool, state: str, targeted: bool) -> str:
        mods = "SHIFT" if shift else ""
        args = (
            f"mods={lua_string(mods)}, key={lua_string(key)}, "
            f"state={lua_string(state)}"
        )
        if targeted:
            args += ", window=w"
        return f"hl.dispatch(hl.dsp.send_key_state({{{args}}}))"

    def _snippet(self, actions: list[tuple[str, bool, str]]) -> str:
        targeted = self.selector is not None or self.address is not None
        body = "; ".join(
            self._call(key, shift, state, targeted)
            for key, shift, state in actions
        )
        if not targeted:
            return body
        if self.address is not None:
            # Addresses are unique: two windows with the same class can never
            # steal each other's notes.
            kind, value = "address", self.address
        else:
            kind, value = self.selector
        return (
            "local w=nil; for _,v in ipairs(hl.get_windows()) do "
            f"if v.{kind}=={lua_string(value)} then w=v end end; "
            f"if w then {body} end"
        )

    def send_many(self, actions: list[tuple[str, bool, str]]) -> None:
        """Send several key states in one IPC round-trip (used for chords)."""
        if not actions:
            return
        # Update the bookkeeping first so a failed dispatch still leaves the
        # keys in the set that release_all() lifts.
        for key, shift, state in actions:
            if state == "down":
                self._held.add((key, shift))
            else:
                self._held.discard((key, shift))
        self.client.eval(self._snippet(actions))

    def _send(self, key: str, shift: bool, state: str) -> None:
        self.send_many([(key, shift, state)])

    def press(self, key: str, shift: bool) -> None:
        if (key, shift) in self._held:
            return
        self._send(key, shift, "down")

    def release(self, key: str, shift: bool) -> None:
        if (key, shift) not in self._held:
            return
        self._send(key, shift, "up")

    def release_all(self) -> None:
        for key, shift in sorted(self._held, key=lambda item: not item[1]):
            self.release(key, shift)

    def close(self) -> None:
        try:
            self.release_all()
        except HyprlandError:
            pass

    def __enter__(self) -> "HyprlandKeyboard":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
