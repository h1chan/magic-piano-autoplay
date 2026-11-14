"""Song files: a tiny text format that keeps the MVP readable.

Example (``songs/twinkle.song``)::

    # comment
    bpm 100
    1 1 5 5 6 6 5
    4 4 3 3 2 2 1

Every token is one beat. A token is either a Virtual Piano key ('1', 'q',
'Q', '!') or a note name ('C4', 'D#4'). Bars ('|') and blank lines are
ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Song:
    bpm: float = 120.0
    tokens: list[str] = field(default_factory=list)

    @property
    def beat_seconds(self) -> float:
        return 60.0 / self.bpm


def parse(text: str) -> Song:
    song = Song()
    for line in text.splitlines():
        # '//' rather than '#' because '#' is part of sharp note names.
        line = line.split("//", 1)[0].strip()
        if not line:
            continue
        words = line.replace("|", " ").split()
        if len(words) == 2 and words[0].lower() == "bpm":
            song.bpm = float(words[1])
            continue
        if len(words) == 2 and words[0].lower() == "beat":
            song.bpm = 60.0 / float(words[1])
            continue
        song.tokens.extend(words)
    if not song.tokens:
        raise ValueError("song has no notes")
    return song


def load(path: str) -> Song:
    with open(path, encoding="utf-8") as handle:
        return parse(handle.read())
