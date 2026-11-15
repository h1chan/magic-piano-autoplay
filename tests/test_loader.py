import tempfile
import unittest
from pathlib import Path

from magic_piano import loader
from magic_piano.layout import build_layout


def vlq(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def event(delta, data):
    return vlq(delta) + data


def tiny_midi(path):
    track = (
        event(0, b"\xff\x51\x03" + (500_000).to_bytes(3, "big"))
        + event(0, b"\x90\x3c\x40")
        + event(480, b"\x80\x3c\x40")
        + event(0, b"\xff\x2f\x00")
    )
    header = (
        b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big")
        + (1).to_bytes(2, "big") + (480).to_bytes(2, "big")
    )
    Path(path).write_bytes(header + b"MTrk" + len(track).to_bytes(4, "big") + track)


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mapping = build_layout(48)

    def test_midi(self):
        path = self.root / "one.mid"
        tiny_midi(path)
        loaded = loader.load(path, self.mapping)
        self.assertEqual(loaded.notes, 1)
        self.assertEqual(len(loaded.events), 2)
        self.assertAlmostEqual(loaded.duration, 0.5)
        self.assertIn("1 notes", loaded.summary())

    def test_song_and_speed(self):
        path = self.root / "two.song"
        path.write_text("bpm 120\n1 2\n")
        normal = loader.load(path, self.mapping)
        fast = loader.load(path, self.mapping, speed=2.0)
        self.assertEqual(normal.notes, 2)
        self.assertEqual(normal.bpm, 120)
        self.assertAlmostEqual(normal.events[-1].time, 0.95)
        self.assertAlmostEqual(fast.events[-1].time, normal.events[-1].time / 2)
        self.assertAlmostEqual(fast.duration, normal.duration / 2)

    def test_midi_duration_follows_speed(self):
        path = self.root / "one.mid"
        tiny_midi(path)
        normal = loader.load(path, self.mapping)
        fast = loader.load(path, self.mapping, speed=2.0)
        self.assertAlmostEqual(normal.duration, 0.5)
        self.assertAlmostEqual(fast.duration, 0.25)

    def test_transpose_moves_pitch(self):
        path = self.root / "one.mid"
        tiny_midi(path)
        normal = loader.load(path, self.mapping)
        shifted = loader.load(path, self.mapping, transpose=12)
        self.assertEqual(normal.events[0].char, "8")   # C4
        self.assertEqual(shifted.events[0].char, "t")  # C5


if __name__ == "__main__":
    unittest.main()
