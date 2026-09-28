#!/usr/bin/env python3
"""Fotoschatz - Diagnose-Skript (Phase 0.3)

Liest mit exiftool alle Testbilder in einem Ordner aus und erstellt
einen lesbaren Bericht: welche Metadatenfelder sind gefuellt, wie
heissen sie genau, und passen die Dateinamen zum erwarteten Muster.

Aufruf:
    python diagnose.py <Ordner-mit-Testbildern>
"""

__version__ = "0.1.2"

import json
import re
import subprocess
import sys
from pathlib import Path

# Erwartetes Dateinamen-Muster aus CLAUDE.md Abschnitt 7:
# YYYY-MM-DD Ordnername_Dateiname.jpg
FILENAME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}) (.+?)_(.+)\.jpg$", re.IGNORECASE)

# Kandidatenfelder aus CLAUDE.md Abschnitt 7 (Tag-Namen wie exiftool
# sie mit -G1 ausgibt: <Gruppe>:<Tag>)
CANDIDATE_FIELDS = [
    ("Stichwoerter", ["XMP-dc:Subject", "IPTC:Keywords"]),
    ("Hierarchie", ["XMP-lr:HierarchicalSubject"]),
    ("Personen", ["XMP-iptcExt:PersonInImage", "XMP-mwg-rs:RegionName"]),
    ("Aufnahmedatum", ["EXIF:DateTimeOriginal", "Composite:DateTimeOriginal"]),
    ("GPS", ["Composite:GPSLatitude", "Composite:GPSLongitude",
             "EXIF:GPSLatitude", "EXIF:GPSLongitude"]),
    ("Bewertung", ["XMP-xmp:Rating"]),
    ("Titel", ["XMP-dc:Title"]),
    ("Beschreibung", ["XMP-dc:Description", "IPTC:Caption-Abstract"]),
    ("Ort (Stadt)", ["IPTC:City", "XMP-photoshop:City"]),
    ("Ort (Land)", ["IPTC:Country-PrimaryLocationName", "XMP-photoshop:Country"]),
    ("Bildmasse", ["File:ImageWidth", "File:ImageHeight",
                    "EXIF:ImageWidth", "EXIF:ImageHeight"]),
]


def find_exiftool() -> str:
    from shutil import which
    exe = which("exiftool") or which("exiftool.exe")
    if not exe:
        print("FEHLER: exiftool wurde nicht gefunden (nicht im PATH).")
        print("Installieren mit: winget install OliverBetz.ExifTool")
        sys.exit(1)
    return exe


def read_metadata(exiftool: str, files: list) -> list:
    cmd = [exiftool, "-json", "-n", "-G1", "-a", *[str(f) for f in files]]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and not result.stdout:
        print("FEHLER beim Ausfuehren von exiftool:")
        print(result.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def check_filenames(files: list) -> list:
    warnings = []
    for f in files:
        if not FILENAME_PATTERN.match(f.name):
            warnings.append(f.name)
    return warnings


def build_report(files: list, metadata: list, filename_warnings: list) -> str:
    lines = []
    lines.append(f"Fotoschatz Diagnose-Bericht (diagnose.py v{__version__})")
    lines.append(f"Anzahl Bilder: {len(files)}")
    lines.append("")

    lines.append("--- Dateinamen-Muster ---")
    if filename_warnings:
        lines.append(
            f"{len(filename_warnings)} Datei(en) passen NICHT zum Muster "
            "'YYYY-MM-DD Ordnername_Dateiname.jpg':"
        )
        for w in filename_warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Alle Dateinamen passen zum erwarteten Muster.")
    lines.append("")

    lines.append("--- Alle in den Bildern gefundenen Metadaten-Felder ---")
    all_keys = set()
    for entry in metadata:
        all_keys.update(entry.keys())
    all_keys.discard("SourceFile")
    for key in sorted(all_keys):
        lines.append(f"  {key}")
    lines.append("")

    lines.append("--- Kandidatenfelder aus CLAUDE.md ---")
    for label, keys in CANDIDATE_FIELDS:
        lines.append(f"\n{label}:")
        found_any = False
        for key in keys:
            count = sum(1 for entry in metadata if entry.get(key) not in (None, "", []))
            if count > 0:
                found_any = True
                example = next(
                    (entry[key] for entry in metadata if entry.get(key) not in (None, "", [])),
                    None,
                )
                lines.append(f"  {key}: {count}/{len(metadata)} Bilder gefuellt. Beispiel: {example}")
            else:
                lines.append(f"  {key}: in keinem Bild gefuellt")
        if not found_any:
            lines.append(
                "  -> KEIN Feld aus dieser Kandidatenliste ist gefuellt, "
                "ggf. anderer Feldname noetig (siehe Gesamtliste oben)."
            )
    lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        print("Aufruf: python diagnose.py <Ordner-mit-Testbildern>")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.is_dir():
        print(f"FEHLER: Ordner nicht gefunden: {folder}")
        sys.exit(1)

    files = sorted(set(folder.glob("*.jpg")) | set(folder.glob("*.JPG")))
    if not files:
        print(f"FEHLER: keine .jpg Dateien in {folder} gefunden.")
        sys.exit(1)

    print(f"diagnose.py v{__version__}")
    print(f"{len(files)} Bilder gefunden in {folder}")

    exiftool = find_exiftool()
    metadata = read_metadata(exiftool, files)
    filename_warnings = check_filenames(files)

    report = build_report(files, metadata, filename_warnings)
    print("\n" + report)

    out_file = folder / "diagnose_report.txt"
    out_file.write_text(report, encoding="utf-8")
    print(f"\nBericht gespeichert unter: {out_file}")


if __name__ == "__main__":
    main()
