#!/usr/bin/env python3
"""Fotoschatz - Aufraeumen: ueberfluessige Exporte aus D:\\Fotoschatz entfernen.

Findet dieselben Faelle wie die Uebersicht (Exporte ohne Original, doppelte Exporte,
nicht verwendbare Exporte), fragt je Gruppe nach und VERSCHIEBT die Dateien nach
_sync\\geloescht\\<Datum>\\ (nicht endgueltig loeschen - Ordner spaeter selbst leeren).
Beim naechsten sync.bat verschwinden sie online.

Sicherheit: Es werden ausschliesslich .jpg-Dateien direkt im Export-Ordner bewegt.
Der Originalordner (D:\\Bilder - Raw) wird nur gelesen - dort wird nie etwas veraendert.

Aufruf: aufraeumen.bat (Doppelklick) oder python aufraeumen.py
"""

__version__ = "0.7.7"

import shutil
from datetime import datetime
from pathlib import Path

import uebersicht as U

TRASH_DIR = U.SCRIPT_DIR / "geloescht"
LOG_FILE = U.SCRIPT_DIR / "aufraeumen_protokoll.txt"
SHOW = 25


def safe_source(name, export_dir, originals):
    """Nur .jpg direkt im Export-Ordner, nie etwas unter dem Originalordner."""
    path = (export_dir / name)
    if path.parent.resolve() != export_dir.resolve():
        raise SystemExit(f"FEHLER: {name} liegt nicht direkt im Export-Ordner - Abbruch.")
    if U.inside(path, originals):
        raise SystemExit(f"FEHLER: {path} liegt im Originalordner - dort wird nie etwas veraendert. Abbruch.")
    if path.suffix.lower() not in (".jpg", ".jpeg") or not path.is_file():
        raise SystemExit(f"FEHLER: {path} ist keine JPG-Datei - Abbruch.")
    return path


def ask(question):
    try:
        return input(f"{question} (j/n): ").strip().lower() in ("j", "ja", "y")
    except EOFError:
        return False


def main():
    cfg = U.load_config()
    print(f"aufraeumen.py v{__version__}")
    originals, export_dir = U.check_paths(cfg)
    if U.inside(TRASH_DIR, originals):
        U.fail("Der Ablage-Ordner laege im Originalordner - Abbruch.")
    # Seit Lightroom Publish (v0.7.7) verwaltet Lightroom die Exporte in Unterordnern selbst. Dateien dort
    # wegzuschieben wuerde Lightroom durcheinanderbringen -> nicht anfassen.
    if any(p.parent != export_dir for p in U.regeln.find_exports(export_dir)[0]):
        U.fail("Die Exporte liegen in Unterordnern (Lightroom Publish). Die verwaltet Lightroom selbst - "
               "aufraeumen.bat wird nicht mehr gebraucht. Bilder entfernen: in Lightroom aus dem Published "
               "Folder nehmen oder Rejected setzen, dann Publish und sync.bat.")
    r = U.analyze(cfg)
    groups = [
        ("Exporte ohne passendes Original (Ordner/Datei in Lightroom umbenannt oder geloescht)", r["orphans"]),
        ("Doppelt exportiert - aelterer Export aus einem frueheren Durchgang", r["dups"]),
        ("RAW und JPG beide exportiert - der Export aus der JPG-Datei", r["pair_exports"]),
        ("Nicht verwendbare Exporte (werden nie hochgeladen)", r["unusable"]),
    ]
    if not any(items for _, items in groups):
        print("\nNichts aufzuraeumen - alle Exporte passen zu einem Original.")
        return

    chosen = []
    for title, items in groups:
        if not items:
            continue
        print(f"\n=== {title}: {len(items)} ===")
        for e, reason in sorted(items, key=lambda x: x[0]["file"])[:SHOW]:
            print(f"  {e['file']}   [{'online' if e['online'] else 'nicht online'}] {reason}")
        if len(items) > SHOW:
            print(f"  ... und {len(items) - SHOW} weitere (alle stehen in der Uebersicht)")
        if ask("Diese Gruppe nach _sync\\geloescht verschieben?"):
            chosen += items

    if not chosen:
        print("\nNichts verschoben.")
        return
    target = TRASH_DIR / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for e, reason in chosen:
        source = safe_source(e["file"], export_dir, originals)
        shutil.move(str(source), str(target / source.name))
        moved.append((e, reason))
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"\n{datetime.now():%Y-%m-%d %H:%M} aufraeumen.py v{__version__}: {len(moved)} Dateien nach {target}\n")
        for e, reason in moved:
            log.write(f"  {e['file']}  -  {reason}\n")

    online = sum(1 for e, _ in moved if e["online"])
    print(f"\n{len(moved)} Dateien verschoben nach: {target}")
    print("Rueckgaengig: Dateien von dort zurueck nach D:\\Fotoschatz verschieben.")
    if online:
        print(f"{online} davon sind online - sie verschwinden beim naechsten sync.bat.")
        if online > int(cfg.get("max_delete", 100)):
            print(f"ACHTUNG: Das sind mehr als max_delete = {cfg.get('max_delete', 100)}. Der Sync bricht zum Schutz ab.")
            print("         Fuer diesen einen Lauf in config.local.json \"max_delete\" hoeher setzen.")


if __name__ == "__main__":
    main()
