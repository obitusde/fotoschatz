#!/usr/bin/env python3
"""Fotoschatz - Zugriff auf den Lightroom-Katalog, NUR ueber eine Kopie.

Der Original-Katalog (*.lrcat) wird ausschliesslich gelesen, um ihn zu kopieren - er wird nie
mit SQLite geoeffnet (SQLite koennte daneben Hilfsdateien anlegen). Gearbeitet wird nur mit der
Kopie in _sync\\katalog\\. Lightroom muss dafuer geschlossen sein, sonst fehlen evtl. die letzten
Aenderungen.

Wird von katalog_diagnose.py (und spaeter von der Lightroom-Pruefung) benutzt.
"""

__version__ = "0.6.29"

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
COPY_DIR = SCRIPT_DIR / "katalog"
DEFAULT_CATALOG = r"C:\Daten\Lightroom Catalog"


# Merker-Stichwoerter (Entscheidung 03.10.2026): "bewusst ohne ..., schon entschieden" - die Pruef-Tools melden
# solche Bilder nicht mehr. Alte Namen gelten in der Uebergangszeit weiter.
ORT_EGAL = ("ort-egal", "location-ok")
PERSONEN_EGAL = ("personen-egal", "personen-ok")


def sql_names(names):
    """('a', 'b') -> "'a', 'b'" fuer WHERE LOWER(name) IN (...)"""
    return ", ".join("'" + n.replace("'", "''") + "'" for n in names)


class CatalogError(Exception):
    pass


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def find_catalog(setting):
    """Pfad aus der Einstellung -> die .lrcat-Datei. Erlaubt: die Datei selbst, der Ordner,
    in dem sie liegt, oder der Name ohne Endung. Liegen im Ordner mehrere Kataloge, gilt der
    zuletzt geaenderte (Entscheidung 29.09.2026: die anderen sind alte Kataloge)."""
    path = Path(setting)
    if path.is_file() and path.suffix.lower() == ".lrcat":
        return path
    with_ext = path.with_name(path.name + ".lrcat")
    if with_ext.is_file():
        return with_ext
    if path.is_dir():
        found = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".lrcat"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if found:
            return found[0]   # mehrere (alte Kataloge nach Lightroom-Updates): der zuletzt geaenderte
        raise CatalogError(f"Im Ordner {path} liegt keine .lrcat-Datei.")
    raise CatalogError(f"Lightroom-Katalog nicht gefunden: {path}")


def other_catalogs(catalog):
    """Weitere .lrcat-Dateien im selben Ordner (werden nicht benutzt, nur angezeigt)."""
    catalog = Path(catalog)
    return sorted((p for p in catalog.parent.iterdir()
                   if p.is_file() and p.suffix.lower() == ".lrcat" and p.name != catalog.name),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def lightroom_running():
    """True, wenn Lightroom laeuft (nur unter Windows pruefbar)."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             errors="replace", timeout=30).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return '"lightroom.exe"' in out


def copy_catalog(catalog, protected=()):
    """Kopiert den Katalog nach _sync\\katalog\\ und gibt den Pfad der Kopie zurueck.
    Abbruch, wenn Lightroom offen ist. `protected`: Ordner, in die nie geschrieben werden darf."""
    catalog = Path(catalog)
    lock = catalog.with_name(catalog.name + ".lock")
    if lock.exists() or lightroom_running():
        raise CatalogError("Lightroom ist noch offen. Bitte Lightroom schliessen und dann nochmal starten.")
    for folder in [catalog.parent, *protected]:
        if inside(COPY_DIR, folder):
            raise CatalogError(f"Die Kopie laege in {folder} - dort wird nichts geschrieben. Abbruch.")

    COPY_DIR.mkdir(exist_ok=True)
    target = COPY_DIR / catalog.name
    for old in COPY_DIR.glob(catalog.name + "*"):   # alte Kopie samt Hilfsdateien der Kopie
        old.unlink()
    before = catalog.stat()
    shutil.copyfile(catalog, target)                # Original wird nur gelesen
    # Nach einem Absturz kann noch ein Teil der Daten im Protokoll (-wal) stehen: mitkopieren
    wal = catalog.with_name(catalog.name + "-wal")
    if wal.exists():
        shutil.copyfile(wal, target.with_name(target.name + "-wal"))
    after = catalog.stat()
    if (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime):
        raise CatalogError("Der Katalog hat sich waehrend des Kopierens geaendert (Lightroom offen?). Bitte nochmal.")
    return target


def open_copy(path):
    """Oeffnet NUR die Kopie in _sync\\katalog\\ (Sicherung gegen Verwechslung)."""
    if not inside(path, COPY_DIR):
        raise CatalogError(f"Nur die Kopie in {COPY_DIR} darf geoeffnet werden, nicht {path}.")
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    return db


def prepare(setting, protected=()):
    """Katalog finden, kopieren, Kopie oeffnen. Gibt (Original-Pfad, Kopie-Pfad, Verbindung) zurueck."""
    catalog = find_catalog(setting)
    copy = copy_catalog(catalog, protected)
    return catalog, copy, open_copy(copy)


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
