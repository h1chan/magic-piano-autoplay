import os
import tempfile
import unittest

from magic_piano.arrange import choose_shift, melody_flags, prepare
from magic_piano.layout import build_layout
from magic_piano.midi_file import MidiError, Note, inspect, read_notes
from magic_piano.player import Event


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

    def test_choose_shift_keeps_high_notes_in_range(self):
        notes = [Note(0, 1, pitch, 64, 0) for pitch in (120, 121, 122)]
        shift = choose_shift(notes, [False] * 3, 48, 109)
        self.assertLess(shift, 0)
        self.assertTrue(all(48 <= note.pitch + shift <= 109 for note in notes))

    def test_melody_weight_beats_bass_count(self):
        melody = [Note(0, 1, 100, 64, 0), Note(1, 1, 101, 64, 0), Note(2, 1, 102, 64, 0)]
        bass = [Note(0.5 + index, 0.5, 30, 64, 0) for index in range(8)]
        notes = melody + bass
        shift = choose_shift(notes, melody_flags(notes), 48, 109)
        self.assertEqual(shift, 0)
        self.assertTrue(all(48 <= note.pitch + shift <= 109 for note in melody))

    def test_events_keep_note_length(self):
        events, report = prepare(
            [Note(1.0, 0.5, 60, 64, 0)], self.layout, fit=False, gate=1.0
        )
        self.assertEqual(report.shift, 0)
        self.assertEqual(report.dropped, 0)
        self.assertEqual(events[0], Event(1.0, True, "8", False))
        self.assertAlmostEqual(events[1].time, 1.5)

    def test_out_of_range_dropped_without_folding(self):
        events, report = prepare(
            [Note(0, 1, 20, 64, 0)], self.layout, fit=False, fold=False
        )
        self.assertEqual(events, [])
        self.assertEqual(report.dropped, 1)

    def test_out_of_range_folded_by_octave(self):
        events, report = prepare(
            [Note(0, 1, 20, 64, 0)], self.layout, fit=False, fold=True
        )
        self.assertTrue(events)
        self.assertEqual(report.folded, 1)
        self.assertEqual(report.dropped, 0)

    def test_shift_conflict_keeps_melody(self):
        # F4 and F#4 share the physical key 'q'; the higher note is melody.
        events, report = prepare(
            [Note(0, 1, 65, 64, 0), Note(0, 1, 66, 64, 0)], self.layout, fit=False
        )
        self.assertEqual(report.conflicts, 1)
        downs = [event for event in events if event.down]
        self.assertEqual(len(downs), 1)
        self.assertTrue(downs[0].shift)

    def test_retrigger_is_not_lost(self):
        events, report = prepare(
            [Note(0, 0.6, 60, 64, 0), Note(0.5, 0.6, 60, 64, 0)],
            self.layout,
            fit=False,
            gate=1.0,
        )
        downs = [event for event in events if event.down]
        self.assertEqual(len(downs), 2)
        self.assertEqual(report.conflicts, 0)


if __name__ == "__main__":
    unittest.main()
