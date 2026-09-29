#!/usr/bin/env python3
"""Fotoschatz - Diagnose-Skript

Prueft alle exportierten JPGs mit denselben Regeln wie das Sync-Tool,
laedt aber nichts hoch. Ergebnis (neben diesem Skript):
  diagnose_report.txt       lesbarer Bericht
  diagnose_korrekturen.csv  Tabelle (Excel) der Bilder mit Problemen
  gesichter_test\           Kopien mit eingezeichneten Gesichtsbereichen und
                            dem quadratischen Vorschau-Ausschnitt (Pruefung Stufe 2)

Aufruf:
    python diagnose.py [Export-Ordner]
Ohne Angabe wird der Ordner oberhalb des Skript-Ordners verwendet
(z. B. Skript in D:\\Fotoschatz\\_sync -> prueft D:\\Fotoschatz).
"""

__version__ = "0.6.6"

import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import regeln

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_FILE = SCRIPT_DIR / "diagnose_report.txt"
CSV_FILE = SCRIPT_DIR / "diagnose_korrekturen.csv"
FACE_DIR = SCRIPT_DIR / "gesichter_test"
FACE_SAMPLES = 40

FIELD_OVERVIEW = [
    ("Stichwoerter", "XMP-dc:Subject"),
    ("Stichwoerter", "IPTC:Keywords"),
    ("Personen", "XMP-iptcExt:PersonInImage"),
    ("Personen", "XMP-mwg-rs:RegionName"),
    ("Originaldatei", "XMP-crs:RawFileName"),
    ("Originaldatei", "XMP-xmpMM:PreservedFileName"),
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


def taken_str(a):
    return f"{a['taken']:%Y-%m-%d %H:%M:%S}" if a["taken"] else ""


def write_face_images(files, exif):
    """Zeichnet Gesichtsbereiche (rot) und den geplanten Vorschau-Ausschnitt (gelb) in Kopien ein."""
    from PIL import Image, ImageDraw, ImageOps
    FACE_DIR.mkdir(exist_ok=True)
    for old in FACE_DIR.glob("*.jpg"):
        old.unlink()
    candidates = []
    for path in files:
        entry = exif.get(path.name)
        if entry and regeln.face_regions(entry):
            cropped = str(entry.get("XMP-crs:HasCrop")).lower() in ("true", "1")
            candidates.append((0 if cropped else 1, path, entry))
    candidates.sort(key=lambda c: (c[0], c[1].name))
    written = 0
    for _, path, entry in candidates[:FACE_SAMPLES]:
        regions = regeln.face_regions(entry)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            scale = 900 / max(im.size)
            im = im.resize((round(im.width * scale), round(im.height * scale)))
            draw = ImageDraw.Draw(im)
            w, h = im.size
            line = max(2, w // 300)
            for r in regions:
                box = ((r["x"] - r["w"] / 2) * w, (r["y"] - r["h"] / 2) * h,
                       (r["x"] + r["w"] / 2) * w, (r["y"] + r["h"] / 2) * h)
                draw.rectangle(box, outline=(255, 0, 0), width=line)
                draw.text((box[0] + 4, box[3] + 2), r["name"], fill=(255, 0, 0))
            left, top, edge = regeln.square_crop(w, h, regeln.focus_point(regions))
            draw.rectangle((left, top, left + edge - 1, top + edge - 1), outline=(255, 220, 0), width=line)
            im.save(FACE_DIR / path.name, quality=80)
        written += 1
    return len(candidates), written


def face_section(files, exif, add):
    total = len(files)
    with_regions = [p for p in files if exif.get(p.name) and regeln.face_regions(exif[p.name])]
    cropped = [p for p in with_regions
               if str(exif[p.name].get("XMP-crs:HasCrop")).lower() in ("true", "1")]
    add("=== Gesichtsbereiche (Pruefung Stufe 2) ===")
    add(f"Bilder mit Gesichtsbereichen: {len(with_regions)}/{total}  (davon in Lightroom zugeschnitten: {len(cropped)})")
    add("Masse: Bild (Export) vs. Bezugsgroesse der Gesichtsbereiche (AppliedToDimensions)")
    for p in with_regions[:15]:
        e = exif[p.name]
        applied = f"{e.get('XMP-mwg-rs:RegionAppliedToDimensionsW')}x{e.get('XMP-mwg-rs:RegionAppliedToDimensionsH')}"
        crop = "zugeschnitten" if p in cropped else "-"
        add(f"  {e.get('File:ImageWidth')}x{e.get('File:ImageHeight')} | {applied} | {crop} | "
            f"{len(regeln.face_regions(e))} Gesicht(er) | {p.name}")
    add(f"Eingezeichnete Kopien: Ordner {FACE_DIR.name} (rot = Gesicht laut Lightroom, gelb = Vorschau-Ausschnitt)")
    add("")


def main():
    if len(sys.argv) > 2:
        print("Aufruf: python diagnose.py [Export-Ordner]")
        sys.exit(1)
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else SCRIPT_DIR.parent
    if not folder.is_dir():
        print(f"FEHLER: Ordner nicht gefunden: {folder}")
        sys.exit(1)

    files = sorted((p for p in folder.iterdir() if regeln.is_jpg(p)), key=lambda p: p.name)
    if not files:
        print(f"FEHLER: keine JPG-Dateien in {folder} gefunden.")
        sys.exit(1)

    print(f"diagnose.py v{__version__}")
    print(f"Pruefe {len(files)} Bilder in {folder} ...")

    exif = regeln.read_exif(regeln.find_exiftool(), files,
                            progress=lambda done, total: print(f"  {done}/{total}"))
    now = datetime.now()
    records = []
    for path in files:
        a = regeln.analyze_name(path.name, now)
        entry = exif.get(path.name)
        meta = regeln.extract_metadata(entry) if entry else {}
        if entry:
            a["problems"] += regeln.metadata_problems(meta)
        else:
            a["problems"].append((regeln.HINWEIS, "Metadaten nicht lesbar"))
        a["meta"] = meta
        records.append(a)

    rows = []
    for a in records:
        for severity, text in a["problems"]:
            rows.append((severity, a["lr_folder"], a["meta"].get("orig", ""), taken_str(a), a["file"], text))
    rows.sort(key=lambda r: (regeln.folder_sort_key(r[1]), r[3], r[4]))

    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Schwere", "Lightroom-Ordner", "Originaldatei", "Aufnahmezeit", "Exportdatei", "Problem"])
        writer.writerows(rows)

    total = len(records)
    schwer = sum(1 for a in records if regeln.is_severe(a["problems"]))
    hinweis = sum(1 for a in records if a["problems"] and not regeln.is_severe(a["problems"]))

    lines = []
    add = lines.append
    add(f"Fotoschatz Diagnose-Bericht (diagnose.py v{__version__})")
    add(f"Erstellt: {now:%Y-%m-%d %H:%M}")
    add(f"Export-Ordner: {folder}")
    add("")
    add("=== Zusammenfassung ===")
    add(f"Bilder gelesen:              {total}")
    if len(exif) != total:
        add(f"ACHTUNG: exiftool hat nur {len(exif)} von {total} Bildern gelesen.")
    add(f"ohne Probleme:               {total - schwer - hinweis}")
    add(f"mit Hinweisen (Upload ja):   {hinweis}")
    add(f"SCHWER (Upload nein):        {schwer}")
    add(f"mit Zusatz (-2, -Edit ...):   {sum(1 for a in records if a['dup'])}")
    add(f"Korrektur-Tabelle:           {CSV_FILE.name} ({len(rows)} Zeilen)")
    add("")

    add("=== Ordner: Lightroom -> online ===")
    folders = Counter((a["lr_folder"], a["online_folder"]) for a in records if a["lr_folder"])
    for (lr, online), count in sorted(folders.items(), key=lambda x: regeln.folder_sort_key(x[0][0])):
        add(f"  {lr}  ->  {online or '(wird nicht hochgeladen)'}  ({count} Bilder)")
    add("")

    add("=== Probleme (auch in der CSV-Tabelle) ===")
    for severity, lr, original, taken, file, text in rows:
        add(f"  [{severity}] {lr} | {original or '-'} | {taken or '-'} | {text}")
        add(f"           Exportdatei: {file}")
    if not rows:
        add("  keine")
    add("")

    face_section(files, exif, add)

    add("=== Feldbelegung ===")
    for label, key in FIELD_OVERVIEW:
        count = sum(1 for e in exif.values() if regeln.as_list(e.get(key)))
        add(f"  {label:<14} {key:<32} {count}/{total}")
    add("")

    person_counter = Counter(p for a in records for p in a["meta"].get("p", []))
    person_names = {p.casefold() for p in person_counter}
    add(f"=== Personen ({len(person_counter)}) ===")
    for name, count in sorted(person_counter.items(), key=lambda x: (-x[1], x[0].casefold())):
        add(f"  {count:>5}  {name}")
    add("")

    keyword_counter = Counter(k for a in records for k in a["meta"].get("kw", []))
    add(f"=== Stichwoerter ({len(keyword_counter)}) - '(Person)' = auch als Person markiert ===")
    for name, count in sorted(keyword_counter.items(), key=lambda x: (-x[1], x[0].casefold())):
        mark = "  (Person)" if name.casefold() in person_names else ""
        add(f"  {count:>5}  {name}{mark}")
    add("")

    add("=== Alle Bilder: Exportdatei -> Online-Ordner | Aufnahmezeit ===")
    for a in sorted(records, key=lambda a: (regeln.folder_sort_key(a["lr_folder"]), taken_str(a), a["file"])):
        add(f"  {a['file']}")
        add(f"      -> {a['online_folder'] or '(nicht hochladen)'} | {taken_str(a) or '-'}")
    add("")

    face_found, face_written = write_face_images(files, exif)

    report = "\n".join(lines)
    REPORT_FILE.write_text(report, encoding="utf-8")
    print()
    print(report[:report.index("=== Ordner")].rstrip())
    print()
    print(f"Bericht:           {REPORT_FILE}")
    print(f"Korrektur-Tabelle: {CSV_FILE}")
    print(f"Gesichter-Test:    {FACE_DIR}  ({face_written} von {face_found} Bildern mit Gesichtern)")


if __name__ == "__main__":
    main()
