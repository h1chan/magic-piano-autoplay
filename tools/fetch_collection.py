#!/usr/bin/env python3
"""Import a curated piano collection from the ADL Piano MIDI dataset.

The dataset is a public archive of piano MIDI files organised by genre. This
tool downloads it once, then picks a hand-curated list of beautiful pieces,
validates every file with this project's MIDI reader and copies the good ones
into ``songs/``.

    python3 tools/fetch_collection.py --report     # show what would be picked
    python3 tools/fetch_collection.py --write      # write songs + COLLECTION.md

Files are for personal use; rights belong to the original composers and to
the authors of the MIDI arrangements.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magic_piano import arrange, midi_file  # noqa: E402
from magic_piano.layout import build_layout  # noqa: E402

DATASET = "https://raw.githubusercontent.com/lucasnfe/adl-piano-midi/master/midi/adl-piano-midi.zip"
CACHE = Path.home() / ".cache" / "magic-piano" / "adl-piano-midi.zip"
SONGS = Path(__file__).resolve().parent.parent / "songs"
LAYOUT = build_layout(48)

# (category, title as written to disk, source path fragments)
COLLECTION: list[tuple[str, str, tuple[str, ...]]] = [
    # --- Classical ---------------------------------------------------------
    ("Classical", "Bach - Air on the G String", ("Johann Sebastian Bach/Air on a G string.mid",)),
    ("Classical", "Bach - Prelude in C Major", ("Das Wohltemperierte Clavier I, Praeludium I.mid",)),
    ("Classical", "Bach - Jesu, Joy of Man's Desiring", ("Jesu bleibet meine Freude",)),
    ("Classical", "Beethoven - Moonlight Sonata", ("Moonlight Sonata 1st movement.mid",)),
    ("Classical", "Beethoven - Fur Elise", ("Ludwig Van Beethoven/Fur Elise.mid",)),
    ("Classical", "Beethoven - Ode to Joy", ("Ludwig Van Beethoven/Ode to Joy.mid",)),
    ("Classical", "Beethoven - Pathetique", ("1CPathétique 1D.mid",)),
    ("Classical", "Beethoven - Adagio Cantabile", ("Adagio Cantabile.mid",)),
    ("Classical", "Mozart - Eine Kleine Nachtmusik", ("Eine Kleine Nachtmusik (Serenade).mid",)),
    ("Classical", "Mozart - Rondo Alla Turca", ("Wolfgang Amadeus Mozart/Turkish March.mid",)),
    ("Classical", "Mozart - Piano Concerto No 21", ("Piano Concerto No21.mid", "Elvira Madigan.mid")),
    ("Classical", "Mozart - Lacrimosa", ("Lacrimosa.mid",)),
    ("Classical", "Mozart - Ave Verum", ("Ave Verum.mid",)),
    ("Classical", "Chopin - Nocturne Op 9 No 2", ("Nocturne Op 9, No 2.mid",)),
    ("Classical", "Chopin - Nocturne No 19", ("Nocturne No 19 in E minor.mid",)),
    ("Classical", "Chopin - Fantaisie-Impromptu", ("Fantaisie-Impromptu.mid",)),
    ("Classical", "Chopin - Prelude Op 28 No 4", ("Prelude Op 28 No 4.mid",)),
    ("Classical", "Chopin - Prelude Op 28 No 15", ("Prelude Op 28, No 15.mid",)),
    ("Classical", "Chopin - Minute Waltz", ("Minute Waltz.mid",)),
    ("Classical", "Chopin - Waltz Op 18", ("Waltz in E-flat Major (Op 18).mid",)),
    ("Classical", "Chopin - Etude Op 10 No 3", ("Etude Op 10 no 3.mid",)),
    ("Classical", "Debussy - Clair de Lune", ("Clair De Lune.mid",)),
    ("Classical", "Debussy - Arabesque No 1", ("Arabesque n 1.mid",)),
    ("Classical", "Debussy - En Bateau", ("Petite Suite - I En bateau.mid",)),
    ("Classical", "Liszt - Liebestraum No 3", ("Van Cliburn/Liebestraum No 3.mid",)),
    ("Classical", "Rachmaninoff - Vocalise", ("Minnesota Orchestra/Vocalise.mid",)),
    ("Classical", "Rachmaninoff - Paganini Rhapsody", ("Rhapsody on a Theme of Paganini.mid",)),
    ("Classical", "Satie - Gymnopedie No 1", ("Gymnopédie No 1.mid",)),
    ("Classical", "Satie - Gymnopedie No 3", ("Gymnopédie No 3.mid",)),
    ("Classical", "Tchaikovsky - Swan Lake Waltz", ("Walts from Swan Lake.mid",)),
    ("Classical", "Tchaikovsky - Sugar Plum Fairy", ("Sugar Plum Fairy.mid",)),
    ("Classical", "Tchaikovsky - Waltz of the Flowers", ("Walts of the Flowers.mid",)),
    ("Classical", "Tchaikovsky - October", ("October - Autumn Song.mid",)),
    ("Classical", "Schubert - Ave Maria", ("Franz Schubert/Ave Maria.mid",)),
    ("Classical", "Schubert - Serenade", ("Franz Schubert/Serenade.mid",)),
    ("Classical", "Schubert - Impromptu in A-flat", ("Impromptu in As-dur.mid",)),
    ("Classical", "Schumann - Traumerei", ("Martha Argerich/Kinderszenen",)),
    ("Classical", "Schumann - Widmung", ("Robert Schumann/Widmung.mid",)),
    ("Classical", "Mendelssohn - Wedding March", ("Wedding March.mid",)),
    ("Classical", "Mendelssohn - Song Without Words", ("Lied Ohne Worte - Opus 102, No 3.mid",)),
    ("Classical", "Brahms - Intermezzo Op 118 No 2", ("Johannes Brahms/Intermezzo.mid",)),
    ("Classical", "Brahms - Hungarian Dance No 7", ("Hungarian Dance N 7.mid",)),
    ("Classical", "Saint-Saens - The Swan", ("The Swan.mid",)),
    ("Classical", "Faure - Pavane", ("Gabriel Faure/Pavane.mid",)),
    ("Classical", "Faure - Apres un Reve", ("Après un Rêve.mid",)),
    ("Classical", "Grieg - Morning Mood", ("Morning Mood from Peer Gynt",)),
    ("Classical", "Pachelbel - Canon in D", ("Johann Pachelbel/Canon in D.mid",)),
    ("Classical", "Albinoni - Adagio in G minor", ("Tomaso Albinoni/Adagio in G minor.mid",)),
    ("Classical", "Vivaldi - Spring", ("Antonio Vivaldi/Spring.mid",)),
    ("Classical", "Handel - Air from Water Music", ("Air, The Water Music.mid",)),
    ("Classical", "Einaudi - Nuvole Bianche", ("Nuvole Bianche.mid",)),
    ("Classical", "Einaudi - Divenire", ("Ludovico Einaudi/Divenire.mid",)),
    ("Classical", "Einaudi - Primavera", ("Ludovico Einaudi/Primavera.mid",)),
    ("Classical", "Yiruma - River Flows in You", ("Rivers Flow in You.mid",)),
    ("Classical", "Tiersen - Comptine d'un autre ete", ("Comptine Dun Autre Ete.mid",)),
    ("Classical", "Tiersen - La Valse d'Amelie", ("La Valse dAmelie.mid",)),
    ("Classical", "Sakamoto - Aqua", ("Ryuichi Sakamoto/Aqua.mid",)),
    ("Classical", "Clayderman - Ballade pour Adeline", ("Ballade Pour Adeline.mid",)),
    ("Classical", "Clayderman - Mariage d'Amour", ("Marriage DAmour.mid",)),
    ("Classical", "Mansell - Lux Aeterna", ("Clint Mansell/Lux Aeterna.mid",)),

    # --- Game soundtracks --------------------------------------------------
    ("Game", "Zelda Ocarina of Time - Zelda's Lullaby", ("Zeldas_Lullaby_by_BlueSCD.mid",)),
    ("Game", "Zelda Ocarina of Time - Kakariko Village", ("Kakariko_Village_by_BlueSCD.mid",)),
    ("Game", "Zelda Ocarina of Time - Song of Storms", ("Song_of_Storms_by_BlueSCD.mid",)),
    ("Game", "Zelda Wind Waker - Farewell Hyrule King", ("FarewellHyruleKing.mid",)),
    ("Game", "Zelda Wind Waker - Windfall Island", ("WindfallIsland.mid",)),
    ("Game", "Zelda Twilight Princess - Midna's Theme", ("MidnasTheme.mid",)),
    ("Game", "Zelda Twilight Princess - Hyrule Field", ("Twilight_Princess_HyruleField.mid",)),
    ("Game", "Super Mario 64 - Dire Dire Docks", ("DireDireDocks.mid",)),
    ("Game", "Super Mario Galaxy - Rosetta's Comet Observatory", ("RosettasCometObservatory1.mid",)),
    ("Game", "Super Mario Galaxy - Good Egg Galaxy", ("GoodEggGalaxy.mid",)),
    ("Game", "Super Mario Galaxy - Gusty Garden Galaxy", ("Gusty_Garden_Galaxy.mid",)),
    ("Game", "Super Mario RPG - Beware the Forest's Mushrooms", ("BewaretheForestsMushrooms.mid",)),
    ("Game", "Final Fantasy 7 - Ahead on Our Way", ("AheadOnOurWayRemix.mid",)),
    ("Game", "Final Fantasy 8 - Eyes on Me", ("EyesonMe.mid",)),
    ("Game", "Final Fantasy 8 - Liberi Fatali", ("LiberiFataliPiano.mid",)),
    ("Game", "Final Fantasy 9 - You're Not Alone", ("YoureNotAlone.mid",)),
    ("Game", "Final Fantasy 9 - A Place to Call Home", ("APlacetoCallHome.mid",)),
    ("Game", "Final Fantasy 10 - To Zanarkand", ("AtZanarkand.mid",)),
    ("Game", "Final Fantasy 10 - Suteki da ne", ("SutekiDaNe.mid",)),
    ("Game", "Chrono Trigger - Corridors of Time", ("CorridorsofTime.mid",)),
    ("Game", "Chrono Trigger - Secret of the Forest", ("SecretoftheForest.mid",)),
    ("Game", "Chrono Cross - Radical Dreamers", ("RadicalDreamersUnstolenGem.mid",)),
    ("Game", "Kingdom Hearts - Dearly Beloved", ("DearlyBeloved.mid",)),
    ("Game", "Kingdom Hearts - Hikari", ("Kingdom_Hearts_Hikari.mid",)),
    ("Game", "Secret of Mana - A Wish", ("Secret_of_Mana_AWish.mid",)),
    ("Game", "Legend of Mana - Nostalgic Song", ("NostalgicSong.mid",)),
    ("Game", "Xenogears - Bonds of Sea and Fire", ("BondsofSeaandFire.mid",)),
    ("Game", "Xenogears - Tears of the Stars", ("TearsoftheStarsHeartsofthePeople.mid",)),
    ("Game", "Castlevania SotN - Lost Painting", ("LostPainting.mid",)),
    ("Game", "Terranigma - Sadness", ("Terranigma_Sadness.mid",)),

    # --- Film, musical and easy listening ----------------------------------
    ("Film", "Forrest Gump - Main Theme", ("Alan Silvestri/Forest Gump Theme.mid",)),
    ("Film", "Titanic - My Heart Will Go On", ("James Horner/My Heart will Go On.mid",)),
    ("Film", "Star Wars - Main Title", ("John Williams/Star Wars Main Title.mid",)),
    ("Film", "Schindler's List - Theme", ("Theme From Schindlers List.mid",)),
    ("Film", "Love Story - Theme", ("Francis Lai/Theme From Love Story.mid",)),
    ("Film", "Beauty and the Beast", ("Alan Menken/Beauty and the Beast.mid",)),
    ("Film", "Aladdin - A Whole New World", ("Alan Menken/A Whole New World.mid",)),
    ("Film", "The Phantom of the Opera - The Music of the Night", ("The Music of the Night.mid",)),
    ("Film", "Moon River", ("Henry Mancini  His Orchestra/Moon River.mid",)),
    ("Film", "Somewhere Over the Rainbow", ("Arlen And Harburg/Somewhere over the Rainbow.mid",)),
]


@dataclass
class Candidate:
    path: str
    notes: int
    duration: float
    polyphony: int
    conflicts: int
    folded: int
    dropped: int
    score: float


def _download(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {DATASET} -> {target}", file=sys.stderr)
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(DATASET, tmp)
    tmp.replace(target)


def _matches(names: list[str], patterns: tuple[str, ...]) -> list[str]:
    found = []
    for name in names:
        low = name.lower()
        if any(pattern.lower() in low for pattern in patterns):
            found.append(name)
    return found


def _evaluate(archive: zipfile.ZipFile, path: str) -> Candidate | None:
    try:
        data = archive.read(path)
    except KeyError:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as handle:
        handle.write(data)
        temp = handle.name
    try:
        notes = midi_file.read_notes(temp)
    except (midi_file.MidiError, OSError, ValueError):
        return None
    finally:
        os.unlink(temp)
    if not notes:
        return None

    duration = max(note.start + note.duration for note in notes)
    if duration < 15:
        return None

    points = sorted({note.start for note in notes})
    # Cheap polyphony estimate: notes sounding at the same start.
    from collections import Counter

    starts = Counter(round(note.start, 3) for note in notes)
    polyphony = max(starts.values())

    _, report = arrange.prepare(notes, LAYOUT, fit=True, gate=1.0)
    density = len(notes) / duration if duration else 0
    score = 0.0
    score -= report.conflicts * 2.0
    score -= report.folded * 0.05
    score -= report.dropped * 0.5
    score -= max(0.0, density - 5.0) * 6.0
    score -= max(0.0, 0.8 - density) * 6.0
    score -= max(0, polyphony - 8) * 1.0
    score += min(duration, 240.0) / 60.0
    if duration > 420:
        score -= (duration - 420) / 60.0

    return Candidate(
        path=path,
        notes=len(notes),
        duration=duration,
        polyphony=polyphony,
        conflicts=report.conflicts,
        folded=report.folded,
        dropped=report.dropped,
        score=score,
    )


def _safe_name(title: str) -> str:
    name = unicodedata.normalize("NFC", title)
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    return f"{name}.mid"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the curated piano collection.")
    parser.add_argument("--zip", default=str(CACHE), help="dataset zip path")
    parser.add_argument("--report", action="store_true", help="only print the selection")
    parser.add_argument("--write", action="store_true", help="write songs and manifest")
    parser.add_argument("--refresh", action="store_true", help="re-download the dataset")
    args = parser.parse_args(argv)

    archive_path = Path(args.zip)
    if args.refresh or not archive_path.exists():
        _download(archive_path)

    chosen: list[tuple[str, str, Candidate]] = []
    missing: list[str] = []
    duplicates: list[str] = []
    warnings: list[str] = []
    sources: dict[str, str] = {}

    with zipfile.ZipFile(archive_path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith((".mid", ".midi"))]
        for category, title, patterns in COLLECTION:
            matches = _matches(names, patterns)
            best = None
            for path in matches:
                candidate = _evaluate(archive, path)
                if candidate is None:
                    continue
                if best is None or candidate.score > best.score:
                    best = candidate
            if best is None:
                missing.append(f"{category}: {title}  (patterns: {patterns})")
                continue
            if best.path in sources:
                duplicates.append(f"{title}  ==  {sources[best.path]}  ({best.path})")
                continue
            sources[best.path] = title
            chosen.append((category, title, best))
            if best.duration < 30:
                warnings.append(f"{title}: only {best.duration:.0f} s")
            if best.conflicts > 20:
                warnings.append(f"{title}: {best.conflicts} key conflicts")

        print(f"{'category':<10} {'title':<58} {'notes':>6} {'dur':>6} {'poly':>5} {'conf':>5}")
        for category, title, item in chosen:
            print(
                f"{category:<10} {title[:58]:<58} {item.notes:>6} "
                f"{item.duration:>5.0f}s {item.polyphony:>5} {item.conflicts:>5}"
            )

        if missing:
            print("\nmissing or unreadable:")
            for line in missing:
                print("  ", line)

        if duplicates:
            print("\nduplicates:")
            for line in duplicates:
                print("  ", line)

        if warnings:
            print("\nquality warnings:")
            for line in warnings:
                print("  ", line)

        total_time = sum(item.duration for _, _, item in chosen)
        print(
            f"\nselected {len(chosen)} / {len(COLLECTION)}"
            f"  ({total_time / 60:.0f} min of music)"
        )
        if args.write and len(chosen) != len(COLLECTION):
            print("nothing written: selection is incomplete", file=sys.stderr)
            return 1

        if args.write:
            SONGS.mkdir(exist_ok=True)
            manifest = [
                "# Piano collection",
                "",
                "100 pieces: classical, game soundtracks and film themes.",
                "Source: ADL Piano MIDI dataset "
                "(https://github.com/lucasnfe/adl-piano-midi).",
                "MIDI arrangements belong to their authors; files are for personal use.",
                "",
                "| # | piece | file | category | length | notes |",
                "|---|-------|------|----------|--------|-------|",
            ]
            for index, (category, title, item) in enumerate(chosen, start=1):
                filename = _safe_name(f"{category} - {title}")
                target = SONGS / filename
                target.write_bytes(archive.read(item.path))
                manifest.append(
                    f"| {index} | {title} | `{filename}` | {category} "
                    f"| {item.duration:.0f} s | {item.notes} |"
                )
            (SONGS / "COLLECTION.md").write_text("\n".join(manifest) + "\n")
            print(f"wrote {len(chosen)} files and songs/COLLECTION.md")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
