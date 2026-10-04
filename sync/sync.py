#!/usr/bin/env python3
"""Fotoschatz - Sync-Tool (Phase 1)

Bringt die exportierten JPGs aus dem Export-Ordner nach Cloudflare R2:
pruefen -> Aenderungen erkennen -> Vorschaubilder -> index.json -> Upload.

Aufruf:
    python sync.py            echter Lauf
    python sync.py --dry-run  Probelauf: zeigt nur, was passieren wuerde
Einstellungen (optional): config.local.json neben diesem Skript.
Geheimes Praefix: aus fotoschatz-secrets.ps1 im Benutzerordner.
"""

__version__ = "0.6.31"

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import regeln

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULTS = {
    "export_dir": str(SCRIPT_DIR.parent),
    "work_dir": str(SCRIPT_DIR / "work"),
    "secrets_file": str(Path(os.environ.get("USERPROFILE", Path.home())) / "fotoschatz-secrets.ps1"),
    "rclone_remote": "r2:fotoschatz",
    "thumb_long_edge": 400,
    "thumb_quality": 70,
    "max_delete": 100,
    "transfers": 8,
    "ignore_keywords": ["google-fotos-uploaded", "Person", "Persons", "location-ok", "ort-egal", "personen-egal"],
}

CSV_FILE = SCRIPT_DIR / "korrekturen.csv"
KEYWORD_FILE = SCRIPT_DIR / "stichwoerter.txt"
PLACES_FILE = SCRIPT_DIR / "orte.txt"
LOG_FILE = SCRIPT_DIR / "letzter_lauf.txt"

# Erhoehen, wenn extract_metadata neue Felder liefert -> Metadaten aller Bilder werden neu gelesen
META_VERSION = 2

PREFIX_RE = re.compile(r"^[A-Za-z0-9]{32,}$")
CACHE_IMMUTABLE = "Cache-Control: public, max-age=31536000, immutable"
CACHE_NO_CACHE = "Cache-Control: no-cache"

_log_lines = []


def log(text=""):
    print(text, flush=True)
    _log_lines.append(text)


def fail(text):
    log("")
    log(f"ABBRUCH: {text}")
    write_log()
    sys.exit(1)


def write_log():
    LOG_FILE.write_text("\n".join(_log_lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Einstellungen

def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except json.JSONDecodeError as err:
            fail(f"config.local.json ist fehlerhaft: {err}")
    return cfg


def read_text_any(path):
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig", errors="replace")


def load_prefix(secrets_file):
    path = Path(secrets_file)
    if not path.exists():
        fail(f"Geheimnis-Datei nicht gefunden: {path}")
    m = re.search(r"\$env:FOTOSCHATZ_R2_PREFIX\s*=\s*[\"']([^\"']*)[\"']", read_text_any(path), re.IGNORECASE)
    if not m:
        fail(f"In {path} steht kein $env:FOTOSCHATZ_R2_PREFIX = \"...\"")
    prefix = m.group(1).strip()
    if not PREFIX_RE.match(prefix):
        fail("Das Praefix ist ungueltig (erlaubt: mind. 32 Zeichen, nur A-Z, a-z, 0-9).")
    return prefix


# ---------------------------------------------------------------- Zustand

def load_state(path):
    if not path.exists():
        return {"files": {}, "known_keywords": [], "upload_pending": False}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, data, compact=False):
    tmp = path.with_suffix(path.suffix + ".tmp")
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=1)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def photo_id(fname):
    return hashlib.sha1(unicodedata.normalize("NFC", fname).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- Dateien im Staging

def make_thumb(src, dst, long_edge, quality):
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((long_edge, long_edge), Image.LANCZOS)
        if im.mode != "RGB":
            im = im.convert("RGB")
        tmp = dst.with_suffix(".tmp")
        im.save(tmp, "WEBP", quality=quality, method=4)
    os.replace(tmp, dst)


def link_or_copy(src, dst):
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def clean_dir(directory, keep):
    removed = 0
    for path in directory.iterdir():
        if path.name not in keep:
            path.unlink()
            removed += 1
    return removed


# ---------------------------------------------------------------- index.json

def build_index(files, analyses, ignore_keywords):
    known_persons = {}
    for rec in files.values():
        for person in rec["meta"].get("p", []):
            known_persons.setdefault(person.casefold(), person)
    ignore = {k.casefold() for k in ignore_keywords}

    photos = []
    folders = {}
    for name, rec in files.items():
        a = analyses[name]
        meta = rec["meta"]
        persons = list(meta.get("p", []))
        person_keys = {p.casefold() for p in persons}
        keywords = []
        for kw in meta.get("kw", []):
            key = kw.casefold()
            if key in ignore:
                continue
            if key in known_persons:
                if key not in person_keys:
                    persons.append(known_persons[key])
                    person_keys.add(key)
                continue
            keywords.append(kw)

        photo = {"id": rec["id"], "h": rec["hash"], "f": a["online_folder"],
                 "t": a["taken"].strftime("%Y-%m-%dT%H:%M:%S")}
        for key in ("w", "ht"):
            if key in meta:
                photo[key] = meta[key]
        if persons:
            photo["p"] = persons
        if keywords:
            photo["kw"] = keywords
        for key in ("de", "sl", "ci", "st", "co", "la", "lo", "r", "fp"):
            if key in meta:
                photo[key] = meta[key]
        photos.append(photo)

        folder = folders.setdefault(a["online_folder"], {
            "n": a["online_folder"], "y": a["year"], "d": a["folder_date"],
            "rest": a["rest"], "photos": [],
        })
        folder["photos"].append(photo)

    folder_list = []
    for folder in folders.values():
        members = folder["photos"]
        cover = min(members, key=lambda p: (-p.get("r", 0), p["t"]))
        entry = {"n": folder["n"], "y": folder["y"],
                 "d": folder["d"] or min(p["t"] for p in members)[:10],
                 "c": len(members), "cover": cover["id"]}
        if folder["rest"]:
            entry["x"] = 1
        folder_list.append(entry)

    photos.sort(key=lambda p: (p["t"], p["id"]))
    folder_list.sort(key=lambda f: (f["y"], f.get("x", 0), f["d"], f["n"]))
    return {
        "v": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(photos),
        "folders": folder_list,
        "photos": photos,
    }


# ---------------------------------------------------------------- Ausgabedateien

def write_csv(rows):
    with open(CSV_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Schwere", "Lightroom-Ordner", "Originaldatei", "Aufnahmezeit", "Exportdatei", "Problem"])
        writer.writerows(rows)


def write_keyword_file(counter, persons, ignore):
    ignore_keys = {k.casefold() for k in ignore}
    person_keys = {p.casefold() for p in persons}
    lines = [f"Fotoschatz Stichwoerter ({datetime.now():%Y-%m-%d %H:%M}) - sync.py v{__version__}",
             "Markierung: [ignoriert] = steht in ignore_keywords, [Person] = wird als Person gezaehlt",
             ""]
    for kw, count in sorted(counter.items(), key=lambda x: (-x[1], x[0].casefold())):
        mark = ""
        if kw.casefold() in ignore_keys:
            mark = "  [ignoriert]"
        elif kw.casefold() in person_keys:
            mark = "  [Person]"
        lines.append(f"{count:>6}  {kw}{mark}")
    KEYWORD_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_places_file(records):
    """Alle Ortsnamen als Baum Land > Bundesland > Stadt > Ort mit Anzahl (fuer die Uebersetzung in der App)."""
    tree = {}
    for rec in records:
        meta = rec["meta"]
        node = tree
        last = None
        for key in ("co", "st", "ci", "sl"):
            value = meta.get(key)
            if not value or value == last:
                continue
            last = value
            entry = node.setdefault(value, {"n": 0, "sub": {}})
            entry["n"] += 1
            node = entry["sub"]
    lines = [f"Fotoschatz Orte ({datetime.now():%Y-%m-%d %H:%M}) - sync.py v{__version__}",
             "So wie Lightroom sie schreibt: Land > Bundesland > Stadt > Ort, mit Anzahl Bilder.",
             "Ab und zu an Claude schicken - englische Namen werden dann in der App uebersetzt.",
             ""]

    def walk(node, depth):
        for name, entry in sorted(node.items(), key=lambda x: (-x[1]["n"], x[0].casefold())):
            lines.append(f"{entry['n']:>6}  {'  ' * depth}{name}")
            walk(entry["sub"], depth + 1)

    walk(tree, 0)
    if len(lines) == 4:
        lines.append("(keine Ortsangaben)")
    PLACES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Upload

def run_rclone(rclone, args, label):
    log(f"  > {label}")
    result = subprocess.run([rclone] + args)
    if result.returncode != 0:
        fail(f"rclone meldet Fehler (Code {result.returncode}). Nichts ist verloren - "
             "beim naechsten Lauf wird der Upload wiederholt.")


def upload(cfg, prefix, staging):
    rclone = regeln.find_tool("rclone", "Installieren mit: winget install Rclone.Rclone")
    remote = f"{cfg['rclone_remote']}/{prefix}"
    common = ["--size-only", "--transfers", str(cfg["transfers"]), "--checkers", "16",
              "--stats", "5s", "--stats-one-line", "-P"]

    log("Upload 1/3: neue Bilder und Vorschaubilder")
    for sub in ("img", "thumb"):
        run_rclone(rclone, ["copy", str(staging / sub), f"{remote}/{sub}",
                            "--header-upload", CACHE_IMMUTABLE] + common, f"hochladen: {sub}/")
    log("Upload 2/3: index.json")
    run_rclone(rclone, ["copyto", str(staging / "index.json"), f"{remote}/index.json",
                        "--header-upload", CACHE_NO_CACHE, "--ignore-times"], "hochladen: index.json")
    log("Upload 3/3: alte Dateien online entfernen")
    for sub in ("img", "thumb"):
        run_rclone(rclone, ["sync", str(staging / sub), f"{remote}/{sub}",
                            "--header-upload", CACHE_IMMUTABLE,
                            "--max-delete", str(cfg["max_delete"])] + common, f"abgleichen: {sub}/")


def confirm_deletions(removed, limit, dry):
    """Mehr Loeschungen als max_delete: Beispiele zeigen und nachfragen (v0.6.31, statt Abbruch).
    Schutz vor einem leeren oder falschen Export-Ordner bleibt: ohne "j" wird nichts geaendert."""
    log(f"\nACHTUNG: {len(removed)} Bilder wuerden online geloescht (Schutzgrenze max_delete = {limit}).")
    log("Sie waren beim letzten Sync dabei und fehlen jetzt im Export-Ordner, z. B.:")
    for name in removed[:10]:
        log(f"  - {name}")
    if len(removed) > 10:
        log(f"  ... und {len(removed) - 10} weitere")
    if dry:
        log("Probelauf: beim echten Lauf (sync.bat) wird hier nachgefragt.")
        return
    if not (sys.stdin and sys.stdin.isatty()):
        fail("Keine Rueckfrage moeglich (kein Konsolenfenster). Bitte sync.bat per Doppelklick starten.")
    answer = input("Ist der Export-Ordner vollstaendig und sollen diese Bilder online geloescht werden? (j/n): ")
    if answer.strip().lower() not in ("j", "ja", "y", "yes"):
        fail("Abgebrochen - es wurde nichts hochgeladen und nichts geloescht.")
    log(f"OK - {len(removed)} Bilder werden online entfernt.")


# ---------------------------------------------------------------- Hauptablauf

def main():
    parser = argparse.ArgumentParser(description="Fotoschatz Sync-Tool")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts veraendern")
    args = parser.parse_args()
    dry = args.dry_run
    started = time.time()
    now = datetime.now()

    log(f"Fotoschatz sync.py v{__version__}" + ("  --  PROBELAUF (--dry-run), es wird nichts veraendert" if dry else ""))
    log(f"Start: {now:%Y-%m-%d %H:%M:%S}")

    cfg = load_config()
    prefix = load_prefix(cfg["secrets_file"])
    export_dir = Path(cfg["export_dir"])
    work_dir = Path(cfg["work_dir"])
    staging = work_dir / "staging"
    state_file = work_dir / "state.json"
    log(f"Export-Ordner: {export_dir}")
    log(f"Ziel:          {cfg['rclone_remote']}/<Praefix, {len(prefix)} Zeichen>/")

    if not export_dir.is_dir():
        fail(f"Export-Ordner nicht gefunden: {export_dir}")
    jpgs = sorted((p for p in export_dir.iterdir() if regeln.is_jpg(p)), key=lambda p: p.name)
    if not jpgs:
        fail("Im Export-Ordner liegen keine JPGs. Zum Schutz vor dem Leeren des Buckets wird abgebrochen.")
    exiftool = regeln.find_exiftool()
    state = load_state(state_file)
    old_files = state["files"]
    first_run = not old_files

    # 1. Dateinamen pruefen
    analyses = {p.name: regeln.analyze_name(p.name, now) for p in jpgs}
    ok_paths = [p for p in jpgs if not regeln.is_severe(analyses[p.name]["problems"])]
    severe_paths = [p for p in jpgs if regeln.is_severe(analyses[p.name]["problems"])]

    # 2. Aenderungen erkennen
    new_files = {}
    to_process = []
    to_refresh = []
    counts = Counter()
    for path in ok_paths:
        stat = path.stat()
        prev = old_files.get(path.name)
        unchanged = prev and prev["size"] == stat.st_size and prev["mtime_ns"] == stat.st_mtime_ns
        if not unchanged:
            sha = sha1_file(path)
            if prev and prev["sha1"] == sha:
                prev = dict(prev, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                unchanged = True
        if unchanged:
            new_files[path.name] = prev
            counts["unveraendert"] += 1
            if prev.get("mv") != META_VERSION:
                to_refresh.append(path)
            continue
        to_process.append((path, sha, stat, "ersetzt" if prev else "neu"))
    removed = sorted(name for name in old_files if name not in {p.name for p in ok_paths})

    log(f"Bilder im Export-Ordner: {len(jpgs)}  (davon SCHWER, werden nicht hochgeladen: {len(severe_paths)})")
    log(f"neu: {sum(1 for t in to_process if t[3] == 'neu')}  ersetzt: {sum(1 for t in to_process if t[3] == 'ersetzt')}"
        f"  unveraendert: {counts['unveraendert']}  entfernt: {len(removed)}")

    if len(removed) > cfg["max_delete"]:
        confirm_deletions(removed, cfg["max_delete"], dry)
        cfg["max_delete"] = len(removed)      # nur fuer diesen Lauf (auch fuer rclone --max-delete)

    # 3. Metadaten der neuen/geaenderten (und der SCHWER-Bilder fuer die Tabelle)
    exif_paths = [t[0] for t in to_process] + to_refresh + severe_paths
    exif = {}
    if to_refresh:
        log(f"Metadaten-Format erneuert: {len(to_refresh)} vorhandene Bilder werden neu gelesen (kein Bild-Upload)")
    if exif_paths:
        log(f"Metadaten lesen: {len(exif_paths)} Bilder ...")
        exif = regeln.read_exif(exiftool, exif_paths,
                                progress=lambda done, total: log(f"  {done}/{total}"))
    refreshed = 0
    for path in to_refresh:
        entry = exif.get(path.name)
        if entry:
            new_files[path.name] = dict(new_files[path.name], meta=regeln.extract_metadata(entry), mv=META_VERSION)
            refreshed += 1

    # 4. Verarbeiten
    if not dry:
        for sub in ("img", "thumb"):
            (staging / sub).mkdir(parents=True, exist_ok=True)
    known_ids = {rec["id"]: name for name, rec in new_files.items()}
    unreadable = {}
    for i, (path, sha, stat, status) in enumerate(to_process, 1):
        entry = exif.get(path.name)
        meta = regeln.extract_metadata(entry) if entry else {}
        pid = photo_id(path.name)
        if pid in known_ids and known_ids[pid] != path.name:
            fail(f"ID-Kollision zwischen {path.name} und {known_ids[pid]} - bitte melden.")
        known_ids[pid] = path.name
        rec = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha1": sha,
               "id": pid, "hash": sha[:8], "meta": meta, "mv": META_VERSION}
        if not entry:
            analyses[path.name]["problems"].append((regeln.HINWEIS, "Metadaten nicht lesbar"))
        if not dry:
            base = f"{pid}.{rec['hash']}"
            try:
                thumb = staging / "thumb" / f"{base}.webp"
                if not thumb.exists():
                    make_thumb(path, thumb, cfg["thumb_long_edge"], cfg["thumb_quality"])
                link_or_copy(path, staging / "img" / f"{base}.jpg")
            except Exception as err:  # defektes Bild: nicht hochladen, in die Tabelle
                unreadable[path.name] = str(err)
                analyses[path.name]["problems"].append((regeln.SCHWER, f"Bild nicht lesbar: {err}"))
                continue
            if i % 50 == 0 or i == len(to_process):
                log(f"  verarbeitet {i}/{len(to_process)}")
        new_files[path.name] = rec
    counts["neu"] = sum(1 for t in to_process if t[3] == "neu" and t[0].name not in unreadable)
    counts["ersetzt"] = sum(1 for t in to_process if t[3] == "ersetzt" and t[0].name not in unreadable)

    # 5. Hinweise aus den Metadaten und neue Stichwoerter
    keyword_counter = Counter()
    all_persons = set()
    for name, rec in new_files.items():
        analyses[name]["problems"] += regeln.metadata_problems(rec["meta"])
        keyword_counter.update(rec["meta"].get("kw", []))
        all_persons.update(rec["meta"].get("p", []))
    known_kw = {k.casefold() for k in state.get("known_keywords", [])}
    ignore_keys = {k.casefold() for k in cfg["ignore_keywords"]}
    person_keys = {p.casefold() for p in all_persons}
    if not first_run:
        for name, rec in new_files.items():
            for kw in rec["meta"].get("kw", []):
                key = kw.casefold()
                if key not in known_kw and key not in ignore_keys and key not in person_keys:
                    analyses[name]["problems"].append(
                        (regeln.HINWEIS, f"neues Stichwort '{kw}' - ggf. in ignore_keywords aufnehmen"))

    # 6. Korrektur-Tabelle und Stichwortliste
    rows = []
    for path in jpgs:
        a = analyses[path.name]
        rec = new_files.get(path.name)
        meta = rec["meta"] if rec else (regeln.extract_metadata(exif[path.name]) if path.name in exif else {})
        taken = f"{a['taken']:%Y-%m-%d %H:%M:%S}" if a["taken"] else ""
        for severity, text in a["problems"]:
            rows.append((severity, a["lr_folder"], meta.get("orig", ""), taken, path.name, text))
    rows.sort(key=lambda r: (regeln.folder_sort_key(r[1]), r[3], r[4]))
    write_csv(rows)
    write_keyword_file(keyword_counter, all_persons, cfg["ignore_keywords"])
    write_places_file(new_files.values())
    severe_total = sum(1 for p in jpgs if regeln.is_severe(analyses[p.name]["problems"]))
    hint_total = sum(1 for p in jpgs if analyses[p.name]["problems"]
                     and not regeln.is_severe(analyses[p.name]["problems"]))

    if dry:
        log("")
        log("PROBELAUF beendet - nichts wurde veraendert.")
        if removed:
            log("Wuerde online entfernen:")
            for name in removed[:20]:
                log(f"  - {name}")
            if len(removed) > 20:
                log(f"  ... und {len(removed) - 20} weitere")
        summary(counts, removed, severe_total, hint_total, rows, started, uploaded=False)
        return

    for name in unreadable:
        new_files.pop(name, None)

    # 7. Staging aufraeumen und vervollstaendigen
    img_keep, thumb_keep = set(), set()
    for name, rec in new_files.items():
        base = f"{rec['id']}.{rec['hash']}"
        img_keep.add(f"{base}.jpg")
        thumb_keep.add(f"{base}.webp")
        img, thumb = staging / "img" / f"{base}.jpg", staging / "thumb" / f"{base}.webp"
        if not img.exists():
            link_or_copy(export_dir / name, img)
        if not thumb.exists():
            make_thumb(export_dir / name, thumb, cfg["thumb_long_edge"], cfg["thumb_quality"])
    clean_dir(staging / "img", img_keep)
    clean_dir(staging / "thumb", thumb_keep)

    # 8. index.json
    index = build_index(new_files, analyses, cfg["ignore_keywords"])
    write_json_atomic(staging / "index.json", index, compact=True)
    index_kb = (staging / "index.json").stat().st_size / 1024
    log(f"index.json: {index['count']} Bilder, {len(index['folders'])} Ordner, {index_kb:.0f} KB")

    changed = counts["neu"] or counts["ersetzt"] or removed or refreshed
    state = {
        "tool_version": __version__,
        "files": new_files,
        "known_keywords": sorted(set(state.get("known_keywords", [])) | set(keyword_counter)),
        "upload_pending": bool(state.get("upload_pending") or changed or first_run),
    }
    write_json_atomic(state_file, state)

    # 9. Upload
    uploaded = False
    if state["upload_pending"]:
        log("")
        upload(cfg, prefix, staging)
        state["upload_pending"] = False
        write_json_atomic(state_file, state)
        uploaded = True
    else:
        log("Keine Aenderungen - kein Upload noetig.")

    summary(counts, removed, severe_total, hint_total, rows, started, uploaded)


def summary(counts, removed, severe_total, hint_total, rows, started, uploaded):
    log("")
    log("=== Zusammenfassung ===")
    log(f"neu:          {counts['neu']}")
    log(f"ersetzt:      {counts['ersetzt']}")
    log(f"entfernt:     {len(removed)}")
    log(f"unveraendert: {counts['unveraendert']}")
    log(f"SCHWER (nicht hochgeladen): {severe_total}")
    log(f"mit Hinweisen (hochgeladen): {hint_total}")
    log(f"Upload: {'ja' if uploaded else 'nein'}")
    log(f"Laufzeit: {time.time() - started:.0f} s   Tool-Version: {__version__}")
    if rows:
        log(f"Korrektur-Tabelle: {CSV_FILE} ({len(rows)} Zeilen)")
    log(f"Stichwortliste:    {KEYWORD_FILE}")
    log(f"Ortsliste:         {PLACES_FILE}")
    write_log()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    main()
