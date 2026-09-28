#!/usr/bin/env python3
"""Fotoschatz - Diagnose-Skript (Phase 0)

Liest alle exportierten JPGs eines Ordners mit exiftool aus und prueft sie
so, wie es spaeter das Sync-Tool tut. Ergebnis (neben diesem Skript):
  diagnose_report.txt       lesbarer Bericht
  diagnose_korrekturen.csv  Tabelle (Excel) der Bilder mit Problemen

Aufruf:
    python diagnose.py [Export-Ordner]
Ohne Angabe wird der Ordner oberhalb des Skript-Ordners verwendet
(z. B. Skript in D:\\Fotoschatz\\_sync -> prueft D:\\Fotoschatz).
"""

__version__ = "0.1.3"

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from shutil import which

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_FILE = SCRIPT_DIR / "diagnose_report.txt"
CSV_FILE = SCRIPT_DIR / "diagnose_korrekturen.csv"

# <Lightroom-Ordner>_JJJJ-MM-TT_hh-mm-ss[-N].jpg  (von hinten gelesen)
FILENAME_RE = re.compile(
    r"^(?P<folder>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})"
    r"(?:-(?P<dup>\d+))?\.jpe?g$",
    re.IGNORECASE,
)
YEAR_FOLDER_RE = re.compile(r"^(\d{4})$")
EVENT_FOLDER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) .+$")
YEAR_RANGE_RE = re.compile(r"^(\d{4})-(\d{4})\b")
LEADING_YEAR_RE = re.compile(r"^(\d{4})\b")

MIN_PLAUSIBLE_YEAR = 1995

SCHWER = "SCHWER"
HINWEIS = "Hinweis"

KEYWORD_FIELDS = ["XMP-dc:Subject", "IPTC:Keywords"]
PERSON_FIELDS = ["XMP-iptcExt:PersonInImage", "XMP-mwg-rs:RegionName"]
ORIGINAL_NAME_FIELDS = ["XMP-xmpMM:PreservedFileName", "XMP-crs:RawFileName"]

FIELD_OVERVIEW = [
    ("Stichwoerter", "XMP-dc:Subject"),
    ("Stichwoerter", "IPTC:Keywords"),
    ("Personen", "XMP-iptcExt:PersonInImage"),
    ("Personen", "XMP-mwg-rs:RegionName"),
    ("Originaldatei", "XMP-xmpMM:PreservedFileName"),
    ("Originaldatei", "XMP-crs:RawFileName"),
    ("GPS", "Composite:GPSLatitude"),
    ("Bewertung", "XMP-xmp:Rating"),
    ("Titel", "XMP-dc:Title"),
    ("Beschreibung", "XMP-dc:Description"),
    ("Beschreibung", "IPTC:Caption-Abstract"),
    ("Ort", "IPTC:Sub-location"),
    ("Ort", "XMP-iptcCore:Location"),
    ("Stadt", "XMP-photoshop:City"),
    ("Bundesland", "XMP-photoshop:State"),
    ("Land", "XMP-photoshop:Country"),
    ("Masse", "File:ImageWidth"),
]


def as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def first_list(entry, keys):
    for key in keys:
        values = as_list(entry.get(key))
        if values:
            return values
    return []


def interpret_folder(name):
    """Liefert (Online-Ordnername, erlaubte Aufnahmejahre, Problem oder None)."""
    if name.startswith("_"):
        return None, set(), "Ordner beginnt mit '_' und darf nicht exportiert werden"
    m = YEAR_FOLDER_RE.match(name)
    if m:
        year = int(m.group(1))
        return f"{year} Weitere Bilder", {year}, None
    m = EVENT_FOLDER_RE.match(name)
    if m:
        year = int(m.group(1))
        try:
            datetime(year, int(m.group(2)), int(m.group(3)))
        except ValueError:
            return name, {year, year + 1}, "Datum im Ordnernamen ist ungueltig"
        return name, {year, year + 1}, None
    m = YEAR_RANGE_RE.match(name)
    if m and int(m.group(1)) <= int(m.group(2)):
        return name, set(range(int(m.group(1)), int(m.group(2)) + 1)), None
    m = LEADING_YEAR_RE.match(name)
    if m:
        year = int(m.group(1))
        return name, {year, year + 1}, None
    return None, set(), "Ordnername beginnt nicht mit einer Jahreszahl"


def analyze(entry, now):
    fname = entry.get("System:FileName", "")
    originals = first_list(entry, ORIGINAL_NAME_FIELDS)
    rec = {
        "file": fname,
        "lr_folder": "",
        "online_folder": "",
        "taken": None,
        "dup": False,
        "original": originals[0] if originals else "",
        "persons": first_list(entry, PERSON_FIELDS),
        "keywords": first_list(entry, KEYWORD_FIELDS),
        "problems": [],
    }

    m = FILENAME_RE.match(fname)
    if not m:
        rec["problems"].append(
            (SCHWER, "Dateiname passt nicht zum Muster <Ordner>_JJJJ-MM-TT_hh-mm-ss.jpg")
        )
        return rec

    rec["lr_folder"] = m.group("folder")
    rec["dup"] = m.group("dup") is not None

    try:
        rec["taken"] = datetime.strptime(
            f"{m.group('date')} {m.group('time')}", "%Y-%m-%d %H-%M-%S"
        )
    except ValueError:
        rec["problems"].append((SCHWER, "Aufnahmezeit im Dateinamen ist kein gueltiges Datum"))

    online, years, folder_problem = interpret_folder(rec["lr_folder"])
    rec["online_folder"] = online or ""
    if folder_problem:
        severity = SCHWER if online is None else HINWEIS
        rec["problems"].append((severity, folder_problem))

    taken = rec["taken"]
    if taken:
        if taken.year < MIN_PLAUSIBLE_YEAR or taken > now:
            rec["problems"].append(
                (HINWEIS, f"Aufnahmezeit unplausibel ({taken:%Y-%m-%d}) - Kamerauhr falsch?")
            )
        elif years and taken.year not in years:
            rec["problems"].append(
                (HINWEIS, f"Aufnahmejahr {taken.year} passt nicht zum Ordner")
            )

    if entry.get("Composite:GPSLatitude") in (None, ""):
        rec["problems"].append((HINWEIS, "keine GPS-Daten"))

    return rec


def find_exiftool():
    exe = which("exiftool") or which("exiftool.exe")
    if not exe:
        print("FEHLER: exiftool wurde nicht gefunden (nicht im PATH).")
        print("Installieren mit: winget install OliverBetz.ExifTool")
        sys.exit(1)
    return exe


def read_metadata(exiftool, folder):
    cmd = [
        exiftool, "-json", "-n", "-G1", "-a",
        "-charset", "filename=utf8",
        "-ext", "jpg", "-ext", "jpeg",
        str(folder),
    ]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if not result.stdout.strip():
        print("FEHLER: exiftool hat keine Bilder geliefert.")
        print(result.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def folder_sort_key(lr_folder):
    return (lr_folder[:4], 1 if YEAR_FOLDER_RE.match(lr_folder) else 0, lr_folder)


def taken_str(rec):
    return f"{rec['taken']:%Y-%m-%d %H:%M:%S}" if rec["taken"] else ""


def problem_rows(records):
    rows = []
    for rec in records:
        for severity, text in rec["problems"]:
            rows.append((severity, rec["lr_folder"], rec["original"], taken_str(rec), rec["file"], text))
    rows.sort(key=lambda r: (folder_sort_key(r[1]), r[3], r[4]))
    return rows


def write_csv(rows):
    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(
            ["Schwere", "Lightroom-Ordner", "Originaldatei", "Aufnahmezeit", "Exportdatei", "Problem"]
        )
        writer.writerows(rows)


def build_report(folder, metadata, records, rows, file_count):
    lines = []
    add = lines.append
    total = len(records)
    schwer = sum(1 for r in records if any(s == SCHWER for s, _ in r["problems"]))
    hinweis = sum(
        1 for r in records if r["problems"] and all(s == HINWEIS for s, _ in r["problems"])
    )

    add(f"Fotoschatz Diagnose-Bericht (diagnose.py v{__version__})")
    add(f"Erstellt: {datetime.now():%Y-%m-%d %H:%M}")
    add(f"Export-Ordner: {folder}")
    add("")
    add("=== Zusammenfassung ===")
    add(f"Bilder gelesen:              {total}")
    if file_count != total:
        add(f"ACHTUNG: im Ordner liegen {file_count} JPGs, exiftool hat aber {total} gelesen.")
    add(f"ohne Probleme:               {total - schwer - hinweis}")
    add(f"mit Hinweisen (Upload ja):   {hinweis}")
    add(f"SCHWER (Upload nein):        {schwer}")
    add(f"mit Zusatz -2/-3 im Namen:   {sum(1 for r in records if r['dup'])}")
    add(f"Korrektur-Tabelle:           {CSV_FILE.name} ({len(rows)} Zeilen)")
    add("")

    add("=== Ordner: Lightroom -> online ===")
    folders = Counter((r["lr_folder"], r["online_folder"]) for r in records if r["lr_folder"])
    for (lr, online), count in sorted(folders.items(), key=lambda x: folder_sort_key(x[0][0])):
        target = online if online else "(wird nicht hochgeladen)"
        add(f"  {lr}  ->  {target}  ({count} Bilder)")
    add("")

    add("=== Probleme (auch in der CSV-Tabelle) ===")
    if rows:
        for severity, lr, original, taken, file, text in rows:
            add(f"  [{severity}] {lr} | {original or '-'} | {taken or '-'} | {text}")
            add(f"           Exportdatei: {file}")
    else:
        add("  keine")
    add("")

    add("=== Feldbelegung ===")
    for label, key in FIELD_OVERVIEW:
        count = sum(1 for e in metadata if as_list(e.get(key)))
        add(f"  {label:<14} {key:<32} {count}/{total}")
    add("")

    person_counter = Counter(p for r in records for p in r["persons"])
    person_names = {p.casefold() for p in person_counter}
    add(f"=== Personen ({len(person_counter)}) ===")
    for name, count in sorted(person_counter.items(), key=lambda x: (-x[1], x[0].casefold())):
        add(f"  {count:>5}  {name}")
    add("")

    keyword_counter = Counter(k for r in records for k in r["keywords"])
    add(f"=== Stichwoerter ({len(keyword_counter)}) - '(Person)' = auch als Person markiert ===")
    for name, count in sorted(keyword_counter.items(), key=lambda x: (-x[1], x[0].casefold())):
        mark = "  (Person)" if name.casefold() in person_names else ""
        add(f"  {count:>5}  {name}{mark}")
    add("")

    add("=== Alle Bilder: Exportdatei -> Online-Ordner | Aufnahmezeit ===")
    for rec in sorted(records, key=lambda r: (folder_sort_key(r["lr_folder"]), taken_str(r), r["file"])):
        add(f"  {rec['file']}")
        add(f"      -> {rec['online_folder'] or '(nicht hochladen)'} | {taken_str(rec) or '-'}")
    add("")

    return "\n".join(lines)


def main():
    if len(sys.argv) > 2:
        print("Aufruf: python diagnose.py [Export-Ordner]")
        sys.exit(1)
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else SCRIPT_DIR.parent
    if not folder.is_dir():
        print(f"FEHLER: Ordner nicht gefunden: {folder}")
        sys.exit(1)

    file_count = sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg"))
    if file_count == 0:
        print(f"FEHLER: keine JPG-Dateien in {folder} gefunden.")
        sys.exit(1)

    print(f"diagnose.py v{__version__}")
    print(f"Pruefe {file_count} Bilder in {folder} ...")

    metadata = read_metadata(find_exiftool(), folder)
    now = datetime.now()
    records = [analyze(entry, now) for entry in metadata]
    rows = problem_rows(records)

    write_csv(rows)
    report = build_report(folder, metadata, records, rows, file_count)
    REPORT_FILE.write_text(report, encoding="utf-8")

    summary_end = report.index("=== Ordner")
    print()
    print(report[:summary_end].rstrip())
    print()
    print(f"Bericht:           {REPORT_FILE}")
    print(f"Korrektur-Tabelle: {CSV_FILE}")


if __name__ == "__main__":
    main()
