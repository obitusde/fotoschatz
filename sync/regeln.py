"""Fotoschatz - gemeinsame Regeln fuer Sync-Tool und Diagnose.

Dateinamen lesen, Online-Ordner bestimmen, Bilder pruefen, Metadaten
aus exiftool uebernehmen. Siehe CLAUDE.md Abschnitt 7.
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from shutil import which

SCHWER = "SCHWER"
HINWEIS = "Hinweis"

MIN_PLAUSIBLE_YEAR = 1995

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

FIELDS = {
    "keywords": ["XMP-dc:Subject", "IPTC:Keywords"],
    "persons": ["XMP-iptcExt:PersonInImage", "XMP-mwg-rs:RegionName"],
    "original": ["XMP-crs:RawFileName", "XMP-xmpMM:PreservedFileName"],
    "description": ["XMP-dc:Description", "IPTC:Caption-Abstract"],
    "sublocation": ["IPTC:Sub-location", "XMP-iptcCore:Location"],
    "city": ["XMP-photoshop:City", "IPTC:City"],
    "state": ["XMP-photoshop:State", "IPTC:Province-State"],
    "country": ["XMP-photoshop:Country", "IPTC:Country-PrimaryLocationName"],
}
EXTRA_TAGS = [
    "System:FileName",
    "File:ImageWidth",
    "File:ImageHeight",
    "IFD0:Orientation",
    "Composite:GPSLatitude",
    "Composite:GPSLongitude",
    "XMP-xmp:Rating",
    "XMP-dc:Title",
]
EXIF_TAGS = sorted({t for tags in FIELDS.values() for t in tags} | set(EXTRA_TAGS))

EXIF_BATCH = 500


def is_jpg(path):
    return path.is_file() and path.suffix.lower() in (".jpg", ".jpeg")


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


def first_text(entry, keys):
    values = first_list(entry, keys)
    return values[0] if values else ""


def unique(values):
    seen = set()
    result = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def interpret_folder(name):
    """Online-Ordner, Jahr, erlaubte Aufnahmejahre, 'Weitere Bilder'?, Ordnerdatum, Problem."""
    info = {"online": None, "year": None, "years": set(), "rest": False, "date": None, "problem": None}
    if name.startswith("_"):
        info["problem"] = (SCHWER, "Ordner beginnt mit '_' und darf nicht exportiert werden")
        return info
    m = YEAR_FOLDER_RE.match(name)
    if m:
        year = int(m.group(1))
        info.update(online=f"{year} Weitere Bilder", year=year, years={year}, rest=True)
        return info
    m = EVENT_FOLDER_RE.match(name)
    if m:
        year = int(m.group(1))
        info.update(online=name, year=year, years={year, year + 1})
        try:
            info["date"] = datetime(year, int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            info["problem"] = (HINWEIS, "Datum im Ordnernamen ist ungueltig")
        return info
    m = YEAR_RANGE_RE.match(name)
    if m and int(m.group(1)) <= int(m.group(2)):
        first, last = int(m.group(1)), int(m.group(2))
        info.update(online=name, year=first, years=set(range(first, last + 1)))
        return info
    m = LEADING_YEAR_RE.match(name)
    if m:
        year = int(m.group(1))
        info.update(online=name, year=year, years={year, year + 1})
        return info
    info["problem"] = (SCHWER, "Ordnername beginnt nicht mit einer Jahreszahl")
    return info


def analyze_name(fname, now):
    """Liest Ordner und Aufnahmezeit aus dem Dateinamen und prueft sie."""
    a = {
        "file": fname,
        "lr_folder": "",
        "online_folder": "",
        "year": None,
        "rest": False,
        "folder_date": None,
        "taken": None,
        "dup": False,
        "problems": [],
    }
    m = FILENAME_RE.match(fname)
    if not m:
        a["problems"].append(
            (SCHWER, "Dateiname passt nicht zum Muster <Ordner>_JJJJ-MM-TT_hh-mm-ss.jpg")
        )
        return a

    a["lr_folder"] = m.group("folder")
    a["dup"] = m.group("dup") is not None
    try:
        a["taken"] = datetime.strptime(f"{m.group('date')} {m.group('time')}", "%Y-%m-%d %H-%M-%S")
    except ValueError:
        a["problems"].append((SCHWER, "Aufnahmezeit im Dateinamen ist kein gueltiges Datum"))

    folder = interpret_folder(a["lr_folder"])
    a["online_folder"] = folder["online"] or ""
    a["year"] = folder["year"]
    a["rest"] = folder["rest"]
    a["folder_date"] = folder["date"]
    if folder["problem"]:
        a["problems"].append(folder["problem"])

    taken = a["taken"]
    if taken:
        if taken.year < MIN_PLAUSIBLE_YEAR or taken > now:
            a["problems"].append(
                (HINWEIS, f"Aufnahmezeit unplausibel ({taken:%Y-%m-%d}) - Kamerauhr falsch?")
            )
        elif folder["years"] and taken.year not in folder["years"]:
            a["problems"].append((HINWEIS, f"Aufnahmejahr {taken.year} passt nicht zum Ordner"))
    return a


def is_severe(problems):
    return any(severity == SCHWER for severity, _ in problems)


def extract_metadata(entry):
    """Uebernimmt die genutzten Felder aus einem exiftool-Eintrag (kurze Schluessel wie index.json)."""
    meta = {}
    width, height = entry.get("File:ImageWidth"), entry.get("File:ImageHeight")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        width, height = int(width), int(height)
        if entry.get("IFD0:Orientation") in (5, 6, 7, 8):
            width, height = height, width
        meta["w"], meta["ht"] = width, height

    persons = unique(first_list(entry, FIELDS["persons"]))
    if persons:
        meta["p"] = persons
    keywords = unique(first_list(entry, FIELDS["keywords"]))
    if keywords:
        meta["kw"] = keywords

    for key, field in (("de", "description"), ("sl", "sublocation"), ("ci", "city"),
                       ("st", "state"), ("co", "country"), ("orig", "original")):
        text = first_text(entry, FIELDS[field])
        if text:
            meta[key] = text

    lat, lon = entry.get("Composite:GPSLatitude"), entry.get("Composite:GPSLongitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        meta["la"], meta["lo"] = round(lat, 5), round(lon, 5)

    rating = entry.get("XMP-xmp:Rating")
    if isinstance(rating, (int, float)) and rating > 0:
        meta["r"] = int(rating)
    return meta


def metadata_problems(meta):
    if "la" not in meta:
        return [(HINWEIS, "keine GPS-Daten")]
    return []


def find_tool(name, install_hint):
    exe = which(name) or which(name + ".exe")
    if not exe:
        raise SystemExit(f"FEHLER: {name} wurde nicht gefunden (nicht im PATH). {install_hint}")
    return exe


def find_exiftool():
    return find_tool("exiftool", "Installieren mit: winget install OliverBetz.ExifTool")


def read_exif(exiftool, paths, progress=None):
    """Liest die benoetigten Felder fuer alle Pfade; Ergebnis: {Dateiname: exiftool-Eintrag}."""
    result = {}
    paths = list(paths)
    for start in range(0, len(paths), EXIF_BATCH):
        batch = paths[start:start + EXIF_BATCH]
        fd, argfile = tempfile.mkstemp(suffix=".args", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for path in batch:
                    f.write(f"{path}\n")
            cmd = [exiftool, "-json", "-n", "-G1", "-a", "-charset", "filename=utf8"]
            cmd += [f"-{tag}" for tag in EXIF_TAGS]
            cmd += ["-@", argfile]
            res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        finally:
            os.unlink(argfile)
        if res.stdout.strip():
            for entry in json.loads(res.stdout):
                name = entry.get("System:FileName") or os.path.basename(entry.get("SourceFile", ""))
                result[name] = entry
        if progress:
            progress(min(start + EXIF_BATCH, len(paths)), len(paths))
    return result


def folder_sort_key(lr_folder):
    return (lr_folder[:4], 1 if YEAR_FOLDER_RE.match(lr_folder) else 0, lr_folder)
