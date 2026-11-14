import os
import tempfile
import unittest

from magic_piano.layout import build_layout
from magic_piano.midi_file import MidiError, inspect, read_notes
from magic_piano.player import Event, build_events_from_notes, fit_octave


def vlq(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def event(delta, data):
    return vlq(delta) + data


def smf(tracks, division=480):
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + (1 if len(tracks) > 1 else 0).to_bytes(2, "big")
        + len(tracks).to_bytes(2, "big")
        + division.to_bytes(2, "big")
    )
    chunks = b"".join(b"MTrk" + len(t).to_bytes(4, "big") + t for t in tracks)
    return header + chunks


TEMPO_500K = event(0, b"\xff\x51\x03" + (500_000).to_bytes(3, "big"))
END = event(0, b"\xff\x2f\x00")


class MidiTest(unittest.TestCase):
    def setUp(self):
        self.layout = build_layout(48)
        self.tmp = tempfile.NamedTemporaryFile(suffix=".mid", delete=False)
        self.tmp.close()
        self.addCleanup(os.unlink, self.tmp.name)

    def write(self, data):
        with open(self.tmp.name, "wb") as handle:
            handle.write(data)

    def test_single_note_timing(self):
        track = (
            TEMPO_500K
            + event(0, b"\x90\x3c\x40")   # C4 on
            + event(480, b"\x80\x3c\x40")  # C4 off after one quarter
            + END
        )
        self.write(smf([track]))
        notes = read_notes(self.tmp.name)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].pitch, 60)
        self.assertAlmostEqual(notes[0].start, 0.0)
        self.assertAlmostEqual(notes[0].duration, 0.5)

    def test_running_status_and_velocity_zero(self):
        track = (
            event(0, b"\x90\x3c\x40")
            + event(0, b"\x40\x40")        # running status: E4 on
            + event(480, b"\x3c\x00")      # C4 off (velocity 0)
            + event(0, b"\x40\x00")        # E4 off
            + END
        )
        self.write(smf([track]))
        notes = read_notes(self.tmp.name)
        self.assertEqual([note.pitch for note in notes], [60, 64])
        self.assertTrue(all(note.duration == 0.5 for note in notes))

    def test_tempo_change(self):
        track = (
            TEMPO_500K
            + event(0, b"\x90\x3c\x40")
            + event(480, b"\x80\x3c\x40")
            + event(0, b"\xff\x51\x03" + (1_000_000).to_bytes(3, "big"))
            + event(0, b"\x90\x3e\x40")
            + event(480, b"\x80\x3e\x40")
            + END
        )
        self.write(smf([track]))
        notes = read_notes(self.tmp.name)
        self.assertAlmostEqual(notes[0].start, 0.0)
        self.assertAlmostEqual(notes[1].start, 0.5)
        self.assertAlmostEqual(notes[1].duration, 1.0)

    def test_chord(self):
        track = (
            TEMPO_500K
            + event(0, b"\x90\x3c\x40")
            + event(0, b"\x90\x3e\x40")
            + event(0, b"\x90\x40\x40")
            + event(480, b"\x80\x3c\x40")
            + event(0, b"\x80\x3e\x40")
            + event(0, b"\x80\x40\x40")
            + END
        )
        self.write(smf([track]))
        notes = read_notes(self.tmp.name)
        self.assertEqual(len(notes), 3)
        self.assertEqual({note.start for note in notes}, {0.0})

    def test_drums_are_skipped_by_default(self):
        track = (
            TEMPO_500K
            + event(0, b"\x99\x24\x40")   # channel 10 note on
            + event(480, b"\x89\x24\x40")
            + END
        )
        self.write(smf([track]))
        self.assertEqual(read_notes(self.tmp.name), [])

    def test_metadata(self):
        track = event(0, b"\xff\x03\x05Piano") + TEMPO_500K + END
        self.write(smf([track]))
        info = inspect(self.tmp.name)
        self.assertEqual(info.fmt, 0)
        self.assertEqual(info.tracks, ("Piano",))

    def test_bad_file(self):
        self.write(b"not midi at all")
        with self.assertRaises(MidiError):
            read_notes(self.tmp.name)


class ArrangeTest(unittest.TestCase):
    def setUp(self):
        self.layout = build_layout(48)  # C3..C#8

    def test_fit_prefers_shift_inside_range(self):
        high_notes = [120, 121, 122]  # above the C3..C#8 range
        shift = fit_octave(high_notes, 48, 109)
        self.assertLess(shift, 0)
        self.assertTrue(all(48 <= pitch + shift <= 109 for pitch in high_notes))

    def test_events_keep_note_length(self):
        from magic_piano.midi_file import Note

        events, shift, dropped = build_events_from_notes(
            [Note(1.0, 0.5, 60, 64, 0)], self.layout, transpose=0, fit=False, gate=1.0
        )
        self.assertEqual(shift, 0)
        self.assertEqual(dropped, 0)
        self.assertEqual(events[0], Event(1.0, True, "8", False))
        self.assertAlmostEqual(events[1].time, 1.5)

    def test_out_of_range_dropped(self):
        from magic_piano.midi_file import Note

        events, _, dropped = build_events_from_notes(
            [Note(0, 1, 20, 64, 0)], self.layout, fit=False
        )
        self.assertEqual(events, [])
        self.assertEqual(dropped, 1)


if __name__ == "__main__":
    unittest.main()
