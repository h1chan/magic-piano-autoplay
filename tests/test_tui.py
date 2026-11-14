import os
import tempfile
import unittest
from pathlib import Path

from magic_piano.hypr import Window
from magic_piano.tui import (
    App,
    Track,
    category_of,
    filter_tracks,
    format_duration,
    read_track_info,
    scan_tracks,
    window_selector,
)


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


class FakeScreen:
    def __init__(self, height=24, width=100):
        self.height = height
        self.width = width
        self.lines = {}
        self.refreshed = False

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.lines.clear()

    def addnstr(self, y, x, text, n, attr=0):
        if not 0 <= y < self.height or not 0 <= x < self.width:
            raise AssertionError(f"write outside screen: {y},{x}")
        self.lines[(y, x)] = text[:n]

    def refresh(self):
        self.refreshed = True

    def text(self):
        return "\n".join(
            line for _, line in sorted(self.lines.items(), key=lambda item: item[0])
        )


class FormattingTest(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(format_duration(None), "--:--")
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(65), "1:05")
        self.assertEqual(format_duration(3725), "1:02:05")

    def test_category(self):
        self.assertEqual(category_of("Classical - Bach - Air"), "Classical")
        self.assertEqual(category_of("Game - Zelda"), "Game")
        self.assertEqual(category_of("Film - Moon River"), "Film")
        self.assertEqual(category_of("Attack on Titan - Jiyuu"), "Other")
        self.assertEqual(category_of("plain"), "Other")


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        tiny_midi(root / "Game - Zelda.mid")
        (root / "Classical - Bach.song").write_text("bpm 100\n1 2 3\n")
        (root / "notes.txt").write_text("not a song")
        self.tracks = scan_tracks(root)

    def test_finds_only_songs(self):
        self.assertEqual(
            [track.title for track in self.tracks],
            ["Classical - Bach", "Game - Zelda"],
        )

    def test_reads_midi_and_song_info(self):
        midi = next(track for track in self.tracks if track.kind == "MIDI")
        song = next(track for track in self.tracks if track.kind == "Song")
        midi_info = read_track_info(midi.path)
        self.assertEqual(midi_info.notes, 1)
        self.assertAlmostEqual(midi_info.duration, 0.5)
        song_info = read_track_info(song.path)
        self.assertEqual(song_info.notes, 3)
        self.assertAlmostEqual(song_info.duration, 1.8)

    def test_filters(self):
        self.assertEqual(len(filter_tracks(self.tracks, "", "Classical")), 1)
        self.assertEqual(len(filter_tracks(self.tracks, "zelda")), 1)
        self.assertEqual(filter_tracks(self.tracks, "mozart"), [])


class WindowSelectorTest(unittest.TestCase):
    def test_unique_class(self):
        window = Window("0x1", "Sober", "Magic Piano")
        self.assertEqual(window_selector(window, [window]), "class:Sober")

    def test_duplicate_class_uses_address(self):
        first = Window("0x1", "Sober", "one")
        second = Window("0x2", "Sober", "two")
        self.assertEqual(window_selector(first, [first, second]), "address:0x1")


class DrawTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(self.tmp.name)
        self.app.colors = False
        self.app.screen = FakeScreen()
        self.app.library.tracks = [
            Track(
                path=Path(self.tmp.name) / "Classical - Bach.mid",
                title="Classical - Bach",
                category="Classical",
                kind="MIDI",
                notes=10,
                duration=65.0,
                tracks=2,
                scanned=True,
            ),
            Track(
                path=Path(self.tmp.name) / "Game - Zelda.mid",
                title="Game - Zelda",
                category="Game",
                kind="MIDI",
                notes=20,
                duration=125.0,
                tracks=3,
                scanned=True,
            ),
        ]

    def test_draws_header_list_and_details(self):
        self.app._draw()
        text = self.app.screen.text()
        self.assertIn("Magic Piano", text)
        self.assertIn("Classical - Bach", text)
        self.assertIn("1:05", text)
        self.assertIn("2 tracks", text)
        self.assertTrue(self.app.screen.refreshed)

    def test_search_and_overlays(self):
        self.app.searching = True
        self.app.query = "zelda"
        self.app._draw()
        self.assertIn("Search: zelda", self.app.screen.text())

        self.app.searching = False
        self.app.picker = [Window("0x1", "org.vinegarhq.Sober", "Sober")]
        self.app.overlay = "window"
        self.app._draw()
        self.assertIn("org.vinegarhq.Sober", self.app.screen.text())

        self.app.overlay = "help"
        self.app._draw()
        text = self.app.screen.text()
        self.assertIn("stop playback", text)
        self.assertNotIn("Game - Zelda", text)

    def test_small_terminal_does_not_crash(self):
        self.app.screen = FakeScreen(height=8, width=30)
        self.app._draw()
        self.assertIn("terminal too small", self.app.screen.text())

    def test_filter_applies_to_list(self):
        self.app.query = "zelda"
        self.app._draw()
        text = self.app.screen.text()
        self.assertIn("Game - Zelda", text)
        self.assertNotIn("Classical - Bach", text)
        self.assertIn("1/2", text)

    def test_q_closes_overlay_without_quitting(self):
        self.app.overlay = "window"
        self.app.picker = [Window("0x1", "Sober", "Magic Piano")]
        self.app._overlay_key(ord("q"))
        self.assertIsNone(self.app.overlay)
        self.assertTrue(self.app.running)


if __name__ == "__main__":
    unittest.main()
