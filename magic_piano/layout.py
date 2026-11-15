"""Note <-> keyboard mapping for Virtual Piano style games.

White piano keys are played with the unshifted keys of this sequence:

    1 2 3 4 5 6 7 8 9 0 q w e r t y u i o p a s d f g h j k l z x c v b n m

A black key is Shift plus the white key immediately to its left, so the same
character in upper case (or the shifted digit) plays the sharp:

    1=C  !=C#  2=D  @=D#  3=E  4=F  $=F#  5=G  %=G#  6=A  ^=A#  7=B

This is the layout used by virtualpiano.net and by Roblox piano games that
copy it. The default first key is C2, which matches the 61 playable keys of
the Roblox Magic Piano keyboard (the extra keys at both ends of its 88-key
piano are mouse-only and reuse the same labels). If the game disagrees, only
this module needs to change.
"""

from __future__ import annotations

import re

WHITE_KEYS = "1234567890qwertyuiopasdfghjklzxcvbnm"
WHITE_SEMITONES = (0, 2, 4, 5, 7, 9, 11)  # C D E F G A B

SHIFTED_DIGITS = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_to_midi(name: str) -> int:
    """'C4' -> 60, 'A#3' -> 58, 'Bb3' -> 58."""
    match = _NOTE_RE.match(name)
    if not match:
        raise ValueError(f"not a note name: {name!r}")
    letter, accidental, octave = match.groups()
    value = _PITCH_CLASS[letter.upper()] + 12 * (int(octave) + 1)
    if accidental == "#":
        value += 1
    elif accidental == "b":
        value -= 1
    return value


def midi_to_note(value: int) -> str:
    return f"{NOTE_NAMES[value % 12]}{value // 12 - 1}"


def build_layout(start_note: int = 36) -> dict[int, tuple[str, bool]]:
    """Map MIDI note -> (key char, shift needed).

    ``start_note`` is the note played by the first white key (default C2,
    matching the Roblox Magic Piano keyboard).
    """
    if not 0 <= start_note <= 127:
        raise ValueError(f"start note out of MIDI range: {start_note}")

    result: dict[int, tuple[str, bool]] = {}
    for index, char in enumerate(WHITE_KEYS):
        octave, step = divmod(index, 7)
        white = start_note + 12 * octave + WHITE_SEMITONES[step]
        result[white] = (char, False)
        # E and B have no black key above them, and the black key above the
        # last white key would fall outside the mapped range.
        if index + 1 < len(WHITE_KEYS) and WHITE_SEMITONES[step] not in (4, 11):
            result[white + 1] = (char, True)
    return result


def token_to_stroke(
    token: str, layout: dict[int, tuple[str, bool]]
) -> tuple[str, bool] | None:
    """Turn a sheet token into (key char, shift).

    Accepts Virtual Piano keys ('1', 'q', 'Q', '!') and note names ('C4').
    Returns None when the note lies outside the mapped range.
    """
    if len(token) == 1:
        if token in WHITE_KEYS:
            return token, False
        if token.lower() in WHITE_KEYS and token.isupper():
            return token.lower(), True
        if token in SHIFTED_DIGITS:
            return SHIFTED_DIGITS[token], True
    if _NOTE_RE.match(token):
        return layout.get(note_to_midi(token))
    raise ValueError(f"cannot read token: {token!r}")


def describe(stroke: tuple[str, bool]) -> str:
    char, shift = stroke
    if not shift:
        return char
    return char.upper() if char.isalpha() else f"Shift+{char}"
