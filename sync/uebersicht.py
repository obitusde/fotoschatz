#!/usr/bin/env python3
"""Fotoschatz - Uebersicht: Was ist auf der Platte, was exportiert, was online - und was ist zu pruefen?

Vergleicht drei Staende und schreibt eine aufklappbare Seite uebersicht.html
(neben diesem Skript, wird nicht hochgeladen):
  Originale   D:\\Bilder - Raw    (nur Datei- und Ordnernamen - dort wird NIE etwas geschrieben oder geoeffnet)
  Exporte     D:\\Fotoschatz       (Name der Originaldatei aus den Metadaten)
  Online      _sync\\work\\state.json (Stand des letzten erfolgreichen Syncs)

Dazu Pruefungen zum Nachbessern in Lightroom (Ordnerstruktur, Hinweise je Bild) und eine
Liste ueberfluessiger Exporte, die aufraeumen.bat entfernen kann.

Aufruf: uebersicht.bat (Doppelklick) oder python uebersicht.py
Optional in config.local.json: "originals_dir": "D:\\\\Bilder - Raw"
"""

__version__ = "0.6.10"

import html
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import regeln

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "uebersicht.html"

DEFAULTS = {
    "export_dir": str(SCRIPT_DIR.parent),
    "work_dir": str(SCRIPT_DIR / "work"),
    "originals_dir": r"D:\Bilder - Raw",
    "max_delete": 100,
}

RAW_EXT = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2", ".raf",
           ".dng", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mef", ".mos", ".mrw", ".rwl", ".iiq"}
IMAGE_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".png", ".psd", ".webp", ".gif", ".bmp"} | RAW_EXT
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mts", ".m2ts", ".m4v", ".3gp", ".mpg", ".mpeg", ".wmv", ".mkv"}
SKIP_DIRS = {"$recycle.bin", "system volume information"}
YEAR_DIR_RE = re.compile(r"^\d{4}$")
DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
SAME_RUN_SECONDS = 600   # Exporte vom selben Original innerhalb von 10 Minuten = gewollte virtuelle Kopien
JPG_LIKE_EXT = {".jpg", ".jpeg", ".heic", ".heif"}
EDIT_SUFFIX_RE = re.compile(r"^(?:-(?:" + regeln.SUFFIX_WORDS + r"))+$", re.IGNORECASE)


def fail(text):
    print(f"\nFEHLER: {text}")
    sys.exit(1)


def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except json.JSONDecodeError as err:
            fail(f"config.local.json ist fehlerhaft: {err}")
    return cfg


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def check_paths(cfg):
    """Schutz: in den Originalordner wird nie geschrieben; Export- und Originalordner getrennt."""
    originals, export_dir = Path(cfg["originals_dir"]), Path(cfg["export_dir"])
    if not originals.is_dir():
        fail(f"Originalordner nicht gefunden: {originals}")
    if not export_dir.is_dir():
        fail(f"Export-Ordner nicht gefunden: {export_dir}")
    if inside(SCRIPT_DIR, originals):
        fail("Das Skript liegt im Originalordner - dort wird nichts geschrieben. Abbruch.")
    if inside(export_dir, originals) or inside(originals, export_dir):
        fail("Export-Ordner und Originalordner ueberschneiden sich - bitte getrennt halten. Abbruch.")
    return originals, export_dir


# ---------------------------------------------------------------- Originale (nur lesen)

def scan_originals(root):
    """Liest nur Verzeichnisse (Namen). Bild = Ordner + Dateiname ohne Endung
    (RAW und JPG mit gleichem Namen zaehlen als ein Bild). Prueft dabei die Ordnerstruktur."""
    r = {
        "folders": {},            # Ordnername (klein) -> {"name", "rel", "images": {stamm_klein: {"stem", "ext"}}}
        "duplicates": defaultdict(set),
        "skipped": Counter(),     # _Import usw.: Anzahl Bilder
        "videos": Counter(),
        "ext_count": Counter(),
        "structure": [],          # (Ordner, Problem, Was tun)
        "undated": defaultdict(list),  # Ordner -> Originale ohne Datumsnamen
        "empty": [],
    }
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as err:
            print(f"  Hinweis: Ordner nicht lesbar: {current} ({err})")
            continue
        rel = Path(current).relative_to(root)
        hidden = any(part.startswith("_") for part in rel.parts)
        if rel.parts and not hidden:
            check_folder(r, rel)
        images_here = 0
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                low = entry.name.casefold()
                if low in SKIP_DIRS or low.endswith(".lrdata") or entry.name.startswith("."):
                    continue
                stack.append(entry.path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            ext = os.path.splitext(entry.name)[1].casefold()
            r["ext_count"][ext or "(ohne)"] += 1
            if not rel.parts:
                continue  # Dateien direkt im Wurzelordner gehoeren zu keinem Lightroom-Ordner
            if ext in VIDEO_EXT:
                r["videos"][str(rel)] += 1
                continue
            if ext not in IMAGE_EXT:
                continue
            images_here += 1
            if hidden:
                r["skipped"][str(rel)] += 1
                continue
            key = rel.name.casefold()
            folder = r["folders"].get(key)
            if folder is None:
                folder = r["folders"][key] = {"name": rel.name, "rel": str(rel), "images": {}}
            elif folder["rel"] != str(rel):
                r["duplicates"][rel.name].update({folder["rel"], str(rel)})
            stem = os.path.splitext(entry.name)[0]
            image = folder["images"].setdefault(stem.casefold(), {"stem": stem, "ext": set()})
            if not image["ext"] and not DATE_STEM_RE.match(stem):
                r["undated"][str(rel)].append(stem)
            image["ext"].add(ext)
        if len(rel.parts) >= 2 and not hidden and not images_here and not any(
                e.is_dir(follow_symlinks=False) for e in entries):
            r["empty"].append(str(rel))
    return r


def check_folder(r, rel):
    name = rel.name
    depth = len(rel.parts)
    add = lambda problem, todo: r["structure"].append((str(rel), problem, todo))
    if name != name.strip() or "  " in name:
        add("Leerzeichen am Anfang/Ende oder doppelt im Ordnernamen", "Ordner in Lightroom umbenennen")
    if depth == 1:
        # oben: Jahresordner (2006) oder Sammelordner mit Jahreszahl (1912-1985 Göbel und Schäfer)
        if not regeln.LEADING_YEAR_RE.match(name):
            add("Ordner auf oberster Ebene beginnt nicht mit einer Jahreszahl – Bilder direkt darin werden nicht hochgeladen",
                "in Lightroom umbenennen (z. B. „1990-2000 Name“) oder mit „_“ beginnen lassen, wenn er nicht online soll")
        return
    info = regeln.interpret_folder(name)
    if info["problem"] and info["problem"][0] == regeln.SCHWER:
        add("Ordnername beginnt nicht mit einer Jahreszahl – Exporte daraus werden nicht hochgeladen",
            "Ordner in Lightroom umbenennen, z. B. „JJJJ-MM-TT Name“")
    elif info["problem"]:
        add(info["problem"][1], "Ordner in Lightroom umbenennen")
    parent = rel.parts[0]
    if depth == 2 and YEAR_DIR_RE.match(parent) and info["year"] and info["year"] != int(parent):
        add(f"liegt im Jahresordner {parent}, der Name beginnt aber mit {info['year']}",
            "Ordner in Lightroom in den richtigen Jahresordner verschieben oder umbenennen")


# ---------------------------------------------------------------- Exporte und Online-Stand

def scan_exports(export_dir, state):
    """Je Export: Lightroom-Ordner, Originaldatei, Hinweise, online ja/nein."""
    files = state.get("files", {})
    pending = bool(state.get("upload_pending"))
    now = datetime.now()
    exports = []
    need_exif = []
    for path in sorted(p for p in Path(export_dir).iterdir() if regeln.is_jpg(p)):
        a = regeln.analyze_name(path.name, now)
        stat = path.stat()
        rec = files.get(path.name)
        synced = bool(rec and rec.get("size") == stat.st_size and rec.get("mtime_ns") == stat.st_mtime_ns)
        e = {
            "file": path.name,
            "folder": a["lr_folder"],
            "stem": a["stem"],
            "stamp": a["taken"].strftime("%Y-%m-%d_%H-%M-%S") if a["taken"] else "",
            "severe": regeln.is_severe(a["problems"]),
            "problems": list(a["problems"]),
            "online": synced and not pending,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "meta": (rec or {}).get("meta") if synced else None,
        }
        if e["meta"] is None:
            need_exif.append(path)
        exports.append(e)
    if need_exif:
        print(f"  Lese Metadaten aus {len(need_exif)} noch nicht synchronisierten Exporten (exiftool) ...")
        try:
            exif = regeln.read_exif(regeln.find_exiftool(), need_exif,
                                    progress=lambda done, total: print(f"    {done}/{total}"))
        except SystemExit:
            exif = {}
            print("  Hinweis: exiftool nicht verfuegbar - Zuordnung nur ueber den Dateinamen.")
        by_name = {e["file"]: e for e in exports}
        for name, entry in exif.items():
            if name in by_name:
                by_name[name]["meta"] = regeln.extract_metadata(entry)
    for e in exports:
        e["orig"] = (e["meta"] or {}).get("orig", "")
        if e["meta"] is not None and not e["severe"]:
            e["problems"] += regeln.metadata_problems(e["meta"])
    return exports


def match(folders, exports):
    """Ordnet jeden Export einem Original zu: Ordnername + Originaldatei ohne Endung,
    ersatzweise der Name aus dem Export (Aufnahmezeit + Zusaetze wie -Edit)."""
    by_key = defaultdict(list)
    orphans, unusable = [], []
    for e in exports:
        if e["severe"]:
            reason = next(text for sev, text in e["problems"] if sev == regeln.SCHWER)
            unusable.append((e, reason))
            continue
        folder = folders.get(e["folder"].casefold())
        candidates = [c.casefold() for c in (os.path.splitext(e["orig"])[0] if e["orig"] else "", e["stem"], e["stamp"]) if c]
        hit = next((c for c in candidates if c in folder["images"]), None) if folder else None
        if hit is None:
            reason = "Lightroom-Ordner nicht gefunden (umbenannt oder gelöscht?)" if not folder \
                else "Originaldatei nicht gefunden (umbenannt oder gelöscht?)"
            orphans.append((e, reason))
            continue
        e["key"] = (e["folder"].casefold(), hit)
        by_key[e["key"]].append(e)
    status, dups, pair_exports, copies = {}, [], [], []
    ext_of = lambda e: os.path.splitext(e["orig"])[1].casefold() if e["orig"] else ""
    for key, group in by_key.items():
        group.sort(key=lambda x: x["mtime"], reverse=True)   # neuester Export gilt
        raws = [e for e in group if ext_of(e) in RAW_EXT]
        if raws and len(raws) < len(group):
            # RAW und JPG desselben Fotos beide exportiert -> Foto online doppelt; die JPG-Fassung ist ueberfluessig
            for e in group:
                if ext_of(e) not in RAW_EXT:
                    pair_exports.append((e, f"gleiches Foto wie {raws[0]['file']} (aus der RAW-Datei {raws[0]['orig']})"))
            group = raws
        keep = group[0]
        status[key] = "online" if keep["online"] else "exportiert"
        for other in group[1:]:
            if keep["mtime"] - other["mtime"] <= SAME_RUN_SECONDS:
                copies.append((other, f"im selben Export wie {keep['file']} – wohl gewollte virtuelle Kopie"))
            else:
                dups.append((other, f"dasselbe Original wie {keep['file']}, aber ein älterer Export (z. B. vor dem Umbenennen)"))
    # Original gilt als erledigt, wenn seine bearbeitete Fassung (…-Edit, …-HDR usw.) exportiert ist
    for (folder_key, stem), state in list(status.items()):
        for other in folders[folder_key]["images"]:
            if other != stem and stem.startswith(other) and EDIT_SUFFIX_RE.match(stem[len(other):]) \
                    and (folder_key, other) not in status:
                status[(folder_key, other)] = state
    return status, orphans, dups, unusable, pair_exports, copies


def same_time_groups(exports):
    """Mehrere verschiedene Originale mit exakt gleicher Aufnahmezeit im selben Ordner (z. B. Scans mit Ersatzdatum)."""
    groups = defaultdict(dict)
    for e in exports:
        if e.get("key") and e["stamp"]:
            groups[(e["folder"], e["stamp"])][e["key"][1]] = e["orig"] or e["stem"]
    return {k: sorted(v.values()) for k, v in groups.items() if len(v) >= 2}


def known_persons(exports):
    """Alle als Person markierten Namen (klein -> Schreibweise), wie im Sync-Tool."""
    known = {}
    for e in exports:
        for person in (e["meta"] or {}).get("p", []):
            known.setdefault(person.casefold(), person)
    return known


def persons_of(meta, known):
    """Personen eines Bildes: markierte Personen plus Stichwoerter, die einem bekannten Personennamen entsprechen."""
    persons = list(meta.get("p", []))
    keys = {p.casefold() for p in persons}
    for kw in meta.get("kw", []):
        if kw.casefold() in known and kw.casefold() not in keys:
            persons.append(known[kw.casefold()])
            keys.add(kw.casefold())
    return persons


def meta_stats(r):
    """Je Lightroom-Ordner: exportierte Bilder mit Metadaten, davon ohne GPS, ohne Personen (je Original einmal)."""
    known = known_persons(r["exports"])
    seen = set()
    stats = defaultdict(Counter)
    for e in r["exports"]:
        if e.get("key") and e["meta"] is not None and e["key"] not in seen:
            seen.add(e["key"])
            st = stats[e["key"][0]]
            st["n"] += 1
            st["gps"] += "la" not in e["meta"]
            st["p"] += not persons_of(e["meta"], known)
    return stats


# ---------------------------------------------------------------- Vorschlaege fuer neue Ordner

MIN_EVENT = 8                          # ab so vielen Fotos lohnt ein eigener Ordner
EVENT_GAP = timedelta(days=2)          # Fotos mit hoechstens 2 Tagen Abstand gehoeren zusammen
EVENT_SPAN_MAX = timedelta(days=31)    # laengere Ketten werden an der groessten Luecke geteilt
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


def split_events(items):
    """Zeitlich sortierte Fotos in Ereignisse teilen: Luecke > 2 Tage trennt, Ereignisse bis 31 Tage."""
    groups, current = [], [items[0]]
    for a, b in zip(items, items[1:]):
        if b["time"] - a["time"] > EVENT_GAP:
            groups.append(current)
            current = [b]
        else:
            current.append(b)
    groups.append(current)
    result = []
    while groups:
        g = groups.pop()
        if len(g) > 1 and g[-1]["time"] - g[0]["time"] > EVENT_SPAN_MAX:
            cut = max(range(1, len(g)), key=lambda i: g[i]["time"] - g[i - 1]["time"])
            groups += [g[:cut], g[cut:]]
        else:
            result.append(g)
    return result


def folder_items(r, known):
    """Je Lightroom-Ordner alle Fotos mit Aufnahmezeit: exportierte (Zeit aus dem Export, mit Metadaten)
    und nicht exportierte Originale, deren Dateiname mit dem Datum beginnt."""
    items = defaultdict(dict)
    for e in sorted(r["exports"], key=lambda x: x["mtime"]):   # neuester Export gewinnt
        if e.get("key") and e["stamp"]:
            key, stem = e["key"]
            meta = e["meta"] or {}
            items[key][stem] = {"name": e["orig"] or e["stem"], "time": datetime.strptime(e["stamp"], "%Y-%m-%d_%H-%M-%S"),
                                "file": e["file"], "meta": meta, "persons": persons_of(meta, known)}
    for key, folder in r["folders"].items():
        for stem, img in folder["images"].items():
            if stem in items[key] or (key, stem) in r["status"]:
                continue
            m = DATE_STEM_RE.match(img["stem"])
            if not m:
                continue
            try:
                taken = datetime.strptime(m[0], "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue
            ext = sorted(img["ext"])[0].upper() if img["ext"] else ""
            items[key][stem] = {"name": img["stem"] + ext, "time": taken, "file": None, "meta": {}, "persons": []}
    return {key: sorted(v.values(), key=lambda x: x["time"]) for key, v in items.items()}


def most_common(values):
    """Haeufigster (nicht leerer) Wert und wie oft er vorkommt."""
    values = [v for v in values if v]
    return Counter(values).most_common(1)[0] if values else ("", 0)


def describe(group, total):
    """Ort, Personen, Beschreibung einer Gruppe (fuer Anzeige und Namensvorschlag)."""
    place, place_n = most_common(i["meta"].get("sl") or i["meta"].get("ci") or i["meta"].get("st") or i["meta"].get("co")
                                  for i in group)
    desc, desc_n = most_common(i["meta"].get("de") for i in group)
    persons = Counter(p for i in group for p in i["persons"])
    return {"place": place, "place_n": place_n, "desc": desc, "desc_n": desc_n,
            "persons": [(p, c) for p, c in persons.most_common(5)], "total": total}


def name_proposal(start, info, folder_name):
    text = ""
    if info["desc"] and info["desc_n"] * 2 >= info["total"] and len(info["desc"]) <= 40 \
            and info["desc"].casefold() != folder_name.casefold():
        text = info["desc"]
    elif info["place"] and info["place_n"] * 2 >= info["total"]:
        text = info["place"]
    text = re.sub(r"\s+", " ", BAD_NAME_CHARS.sub(" ", text)).strip() or "Name"
    return f"{start:%Y-%m-%d} {text}"


def suggest_folders(r):
    """Vorschlaege fuer neue Ereignisordner in Sammelordnern und bei losen Bildern im Jahresordner:
    1. zeitliche Haeufung (>= 8 Fotos, hoechstens 2 Tage Abstand), 2. gleiche Beschreibung bei >= 8 Fotos.
    Nur Vorschlaege - es wird nichts angelegt oder verschoben."""
    known = known_persons(r["exports"])
    all_items = folder_items(r, known)
    folders = r["folders"]
    ranges = {key: (items[0]["time"], items[-1]["time"]) for key, items in all_items.items() if items}
    suggestions = []
    for key, items in all_items.items():
        folder = folders[key]
        if regeln.EVENT_FOLDER_RE.match(folder["name"]) or len(items) < MIN_EVENT:
            continue   # Ereignisordner "JJJJ-MM-TT Name" sind schon ein Ereignis
        info = regeln.interpret_folder(folder["name"])
        if info["problem"] and info["problem"][0] == regeln.SCHWER:
            continue
        loose = info["rest"]
        fitting = [i for i in items if not info["years"] or i["time"].year in info["years"]]
        # vorhandene Unterordner, die selbst ein Ereignis sind (hoechstens 31 Tage) - evtl. gehoeren die Fotos dorthin
        children = [k for k, f in folders.items() if f["rel"].startswith(folder["rel"] + os.sep) and k in ranges
                    and ranges[k][1] - ranges[k][0] <= EVENT_SPAN_MAX]
        used = set()
        # 1. zeitliche Haeufungen
        for group in split_events(fitting) if fitting else []:
            same_stamp = Counter(i["time"] for i in group).most_common(1)[0][1]
            if len(group) < MIN_EVENT or same_stamp * 2 >= len(group):
                continue   # zu wenige, oder meist dieselbe Zeit (Ersatzdatum bei Scans)
            if not loose and len(group) == len(items):
                continue   # der ganze Ordner ist dieses Ereignis
            start, end = group[0]["time"], group[-1]["time"]
            existing = [folders[k]["rel"] for k in children
                        if ranges[k][0] - timedelta(days=1) <= end and ranges[k][1] + timedelta(days=1) >= start]
            descr = describe(group, len(group))
            suggestions.append({"rel": folder["rel"], "folder": folder["name"], "kind": "time", "items": group,
                                "start": start, "end": end, "info": descr, "existing": existing,
                                "name": name_proposal(start, descr, folder["name"])})
            used.update(id(i) for i in group)
        # 2. gleiche Beschreibung (z. B. Scans mit Ersatzdatum, aber beschriftet)
        by_desc = defaultdict(list)
        for i in items:
            desc = (i["meta"].get("de") or "").strip()
            if desc and desc.casefold() not in (folder["name"].casefold(), regeln.LEADING_YEAR_RE.sub("", folder["name"]).strip().casefold()):
                by_desc[desc.casefold()].append(i)
        for group in by_desc.values():
            if len(group) < MIN_EVENT or (not loose and len(group) * 10 >= len(items) * 9):
                continue
            if sum(id(i) in used for i in group) * 2 >= len(group):
                continue   # steckt schon in einem zeitlichen Vorschlag
            group.sort(key=lambda i: i["time"])
            descr = describe(group, len(group))
            suggestions.append({"rel": folder["rel"], "folder": folder["name"], "kind": "desc", "items": group,
                                "start": group[0]["time"], "end": group[-1]["time"], "info": descr, "existing": [],
                                "name": name_proposal(group[0]["time"], descr, folder["name"])})
    suggestions.sort(key=lambda s: (s["rel"].casefold(), s["start"]))
    return suggestions


def analyze(cfg, quiet=False):
    say = (lambda *a: None) if quiet else print
    originals, export_dir = check_paths(cfg)
    say(f"Lese Originale (nur Namen): {originals} ...")
    r = scan_originals(originals)
    say(f"  {sum(len(f['images']) for f in r['folders'].values())} Bilder in {len(r['folders'])} Ordnern")
    state_file = Path(cfg["work_dir"]) / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    say(f"Lese Exporte: {export_dir} ...")
    r["exports"] = scan_exports(export_dir, state)
    say(f"  {len(r['exports'])} exportierte Bilder")
    r["status"], r["orphans"], r["dups"], r["unusable"], r["pair_exports"], r["copies"] = match(r["folders"], r["exports"])
    r["same_time"] = same_time_groups(r["exports"])
    # RAW + JPG desselben Fotos liegen beide im Originalordner
    r["raw_jpg"] = {f["rel"]: sorted((img["stem"], sorted(img["ext"])) for img in f["images"].values()
                                     if img["ext"] & RAW_EXT and img["ext"] & JPG_LIKE_EXT)
                    for f in r["folders"].values()}
    r["raw_jpg"] = {rel: stems for rel, stems in r["raw_jpg"].items() if stems}
    r["stats"] = meta_stats(r)
    r["suggestions"] = suggest_folders(r)
    return r


# ---------------------------------------------------------------- Seite

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1d21;--muted:#5f6570;--line:#e2e5ea;--ok:#1e8e3e;--wait:#c58a00;
--part:#e8710a;--none:#c5221f;--bar:#e3e6eb;--warn:#b06000}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--text:#e8eaed;--muted:#9aa0a6;--line:#262a31;
--ok:#5bb974;--wait:#fdd663;--part:#fcad70;--none:#f28b82;--bar:#262a31;--warn:#fcad70}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:1.4rem;margin:0 0 4px}
h2{font-size:1.1rem;margin:28px 0 6px}
.muted{color:var(--muted)}.small{font-size:.85rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.card b{display:block;font-size:1.5rem}.card span{color:var(--muted);font-size:.85rem}
.bar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--bar);min-width:120px}
.bar i{display:block;height:100%}.i-ok{background:var(--ok)}.i-wait{background:var(--wait)}
.i-part{background:var(--part)}.i-none{background:var(--none)}
.tools{display:flex;gap:8px;align-items:center;margin:8px 0 14px;flex-wrap:wrap}
.tools button{font:inherit;padding:6px 14px;border-radius:16px;border:1px solid var(--line);background:var(--card);color:inherit;cursor:pointer}
.tools button.on{border-color:var(--text);font-weight:600}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:6px 0}
details details{border-radius:8px;margin:4px 0}
summary{cursor:pointer;padding:10px 12px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";width:12px;flex:none;color:var(--muted)}
details[open]>summary::before{content:"▾"}
summary>:first-child{flex:1;min-width:0}
summary .t{font-weight:600}.inner{padding:0 10px 10px 36px}
.year>summary .t{font-size:1.1rem}
.row{display:flex;gap:10px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
.nums{color:var(--muted);font-size:.85rem;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}
.s-ok{background:var(--ok)}.s-wait{background:var(--wait)}.s-part{background:var(--part)}.s-none{background:var(--none)}
.plain{padding:9px 12px 9px 36px;border:1px solid var(--line);border-radius:8px;margin:4px 0;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.plain>:first-child{flex:1;min-width:0}
ul.files{columns:3 220px;margin:6px 0 4px;padding-left:18px;font-size:.85rem}
table{border-collapse:collapse;font-size:.85rem;margin:6px 0;width:100%}td,th{padding:4px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.todo{margin:2px 0 8px;font-size:.9rem}.todo b{color:var(--warn)}
.warn{color:var(--warn);font-size:.85rem}
.gps{color:var(--muted);font-size:.85rem;white-space:nowrap}
.row>span+span{margin-left:2px}
.hide-done .done{display:none}
.legend span{margin-right:14px;white-space:nowrap}
.none{padding:10px 12px;color:var(--muted)}
.nowrap{white-space:nowrap}
details.task table td:first-child{overflow-wrap:anywhere;min-width:170px}
.only-fewp .year:not(.fewp),.only-fewp .folder:not(.fewp),.only-fewp .plain:not(.fewp){display:none}
.thumbs{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.thumbs img{width:120px;height:90px;object-fit:cover;border-radius:6px;background:var(--bar)}
.proposal{font-weight:600;white-space:nowrap}
"""

JS = """
function setFilter(mode){document.body.classList.toggle('hide-done',mode==='open');
document.body.classList.toggle('only-fewp',mode==='fewp');
['all','open','fewp'].forEach(m=>document.getElementById('f-'+m).classList.toggle('on',m===mode));}
function openAll(v){document.querySelectorAll('details.year').forEach(d=>d.open=v);}
function openTasks(v){document.querySelectorAll('details.task').forEach(d=>d.open=v);}
function openSuggestions(v){document.querySelectorAll('details.sug').forEach(d=>d.open=v);}
"""

LABEL = {"ok": "komplett online", "wait": "exportiert, Sync fehlt", "part": "teilweise exportiert", "none": "nicht exportiert"}


def esc(text):
    return html.escape(str(text))


def fmt(n):
    return f"{n:,}".replace(",", ".")


def bar(ok, wait, rest, total):
    if not total:
        return '<div class="bar"></div>'
    parts = [(ok, "i-ok"), (wait, "i-wait"), (rest, "i-none")]
    return '<div class="bar">' + "".join(
        f'<i class="{cls}" style="width:{100 * n / total:.2f}%"></i>' for n, cls in parts if n) + "</div>"


def folder_state(n, exported, online):
    if n and online == n:
        return "ok"
    if n and exported == n:
        return "wait"
    if exported:
        return "part"
    return "none"


def problem_type(text):
    """Hinweise zusammenfassen: Zahlen und Klammern entfernen (z. B. 'Aufnahmejahr 1915 passt nicht zum Ordner')."""
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)|\d+|'.*?'", "", text)).strip()


GPS_HINT = "keine GPS-Daten"
SHORT_TYPE = {
    "Aufnahmejahr passt nicht zum Ordner": "Jahr passt nicht",
    "Aufnahmezeit unplausibel - Kamerauhr falsch?": "Datum unplausibel",
    "Datum im Ordnernamen ist ungueltig": "Ordnerdatum ungültig",
}


def hint_badges(warn, st):
    """'⚠ 3 Jahr passt nicht · 1 Datum unplausibel' und grau '📍 40 % ohne GPS · 👤 70 % ohne Personen'."""
    out = ""
    if warn:
        kinds = Counter(SHORT_TYPE.get(problem_type(text), problem_type(text)) for _, text in warn)
        out += "<span class='warn'>⚠ " + " · ".join(f"{fmt(c)} {esc(k)}" for k, c in kinds.most_common()) + "</span>"
    return out + meta_badge(st)


def percent(part, whole):
    """Prozent ohne Rundung auf 0 bzw. 100, solange es nicht ganz stimmt."""
    if not whole:
        return "–"
    value = round(100 * part / whole)
    if part and not value:
        return "<1 %"
    if part < whole and value == 100:
        return ">99 %"
    return f"{value} %"


def meta_badge(st):
    """Anteil der exportierten Bilder ohne GPS / ohne Personen (nur Info)."""
    if not st or not st["n"]:
        return "<span class='gps' title='noch nichts exportiert – Angaben kommen aus den Exporten'>📍 – · 👤 –</span>"
    title = (f"{fmt(st['n'])} exportierte Bilder: {fmt(st['gps'])} ohne GPS, {fmt(st['p'])} ohne markierte Personen")
    return (f"<span class='gps' title='{esc(title)}'>📍 {esc(percent(st['gps'], st['n']))} ohne GPS · "
            f"👤 {esc(percent(st['p'], st['n']))} ohne Personen</span>")


def few_persons(st):
    return bool(st and st["n"] and st["p"] * 2 >= st["n"])


def section(w, title, count, todo, body):
    w(f"<details><summary><span class='t'>{esc(title)} ({fmt(count)})</span></summary><div class='inner'>")
    w(f"<div class='todo'><b>Was tun:</b> {todo}</div>")
    body()
    w("</div></details>")


FOLDER_FILE = "(ganzer Ordner)"
TODO_RENAME = "Folders-Panel: Rechtsklick auf den Ordner › Rename…"
TODO_CAPTURE = "Bild markieren › Metadata › Edit Capture Time… und das richtige (ggf. geschätzte) Datum setzen"


def nice_time(stamp):
    """'1914-01-01_12-24-37' -> '01.01.1914 12:24:37'"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", stamp or "")
    return f"{m[3]}.{m[2]}.{m[1]} {m[4]}:{m[5]}:{m[6]}" if m else ""


def build_tasks(r, hints_by_folder):
    """Alles, was vor dem Export in Lightroom zu aendern ist - je Lightroom-Ordner (Pfad unter D:\\Bilder - Raw).
    Zeile: (Art, Datei in Lightroom, Aufnahmezeit, Problem, Was tun)."""
    folders = r["folders"]
    rel_of_name = {f["name"].casefold(): f["rel"] for f in folders.values()}
    tasks = defaultdict(list)
    # Ordner: Struktur und doppelte Namen
    for rel, problem, todo in r["structure"]:
        tasks[rel].append(("Ordner", FOLDER_FILE, "", problem, f"{todo} ({TODO_RENAME} oder per Ziehen verschieben)"))
    for name, rels in r["duplicates"].items():
        for rel in rels:
            others = ", ".join(sorted(x for x in rels if x != rel))
            tasks[rel].append(("Ordnername doppelt", FOLDER_FILE, "", f"gleicher Ordnername auch in: {others} – online "
                               "würden beide zusammengelegt", f"einen der Ordner eindeutig umbenennen: {TODO_RENAME}"))
    # Hinweise zu Bildern (Datum)
    for key, items in hints_by_folder.items():
        for e, text in items:
            kind = SHORT_TYPE.get(problem_type(text), problem_type(text))
            if kind == "Jahr passt nicht":
                todo = (f"Stimmt das Datum nicht: {TODO_CAPTURE}. Stimmt es doch: Zeitraum im Ordnernamen anpassen "
                        f"({TODO_RENAME}).")
            elif kind == "Datum unplausibel":
                todo = TODO_CAPTURE
            elif kind == "Ordnerdatum ungültig":
                todo = f"Datum im Ordnernamen korrigieren: {TODO_RENAME}"
            else:
                todo = "prüfen"
            tasks[folders[key]["rel"]].append((kind, e["orig"] or e["stem"], nice_time(e["stamp"]), text, todo))
    # zwei sichtbare Fassungen vom selben Original
    copies = defaultdict(list)
    for e, _ in r["copies"]:
        copies[e["key"]].append(e)
    for (folder_key, _), items in copies.items():
        e = items[0]
        tasks[folders[folder_key]["rel"]].append((
            "2 Fassungen", e["orig"] or e["stem"], nice_time(e["stamp"]),
            f"{len(items) + 1} sichtbare Fassungen vom selben Original (Original + virtuelle Kopie, nicht gestapelt) "
            "– alle werden exportiert",
            "Alle Fassungen markieren › Photo › Stacking › Group into Stack (Strg+G); die Fassung für die Galerie "
            "im Stapel anklicken › Photo › Stacking › Move to Top of Stack (Umschalt+S). Oder die überflüssige "
            "virtuelle Kopie löschen."))
    # RAW + JPG desselben Fotos im Ordner
    for rel, items in r["raw_jpg"].items():
        for stem, exts in items:
            names = " + ".join(f"{stem}{x.upper()}" for x in exts)
            tasks[rel].append(("RAW + JPG", names, "", "RAW und JPG vom selben Foto liegen im Ordner – "
                               "erscheinen sie in Lightroom als zwei Bilder, kommen beide in die Galerie",
                               "Sind es zwei Kacheln: die JPG-Kachel entfernen (Photo › Remove Photo…), oder "
                               "Edit › Preferences › General › „Treat JPEG files next to raw files as separate photos“ "
                               "ausschalten. Ist es nur eine Kachel (RAW+JPEG), ist alles in Ordnung."))
    # mehrere verschiedene Fotos mit exakt gleicher Aufnahmezeit (Scans mit Ersatzdatum)
    for (folder_name, stamp), names in r["same_time"].items():
        rel = rel_of_name.get(folder_name.casefold(), folder_name)
        tasks[rel].append(("gleiche Zeit", ", ".join(names), nice_time(stamp),
                           f"{len(names)} verschiedene Fotos mit genau derselben Aufnahmezeit – bei Scans meist ein "
                           "Ersatzdatum; online ist die Reihenfolge dann zufällig",
                           f"Serienbilder: nichts tun. Scans: je Foto {TODO_CAPTURE}"))
    order = {"Ordner": 0, "Ordnername doppelt": 1}
    for rows in tasks.values():
        rows.sort(key=lambda row: (order.get(row[0], 2), row[2][6:10] + row[2][3:5] + row[2][:2] + row[2][11:], row[1]))
    return tasks


def day_range(start, end):
    if start.date() == end.date():
        return f"{start:%d.%m.%Y}"
    return f"{start:%d.%m.}–{end:%d.%m.%Y}" if start.year == end.year else f"{start:%d.%m.%Y}–{end:%d.%m.%Y}"


def write_suggestion(w, sug, cfg):
    items, info = sug["items"], sug["info"]
    when = day_range(sug["start"], sug["end"])
    facts = [f"{fmt(len(items))} Fotos", when]
    if info["place"]:
        facts.append(f"📍 {info['place']}")
    if info["persons"]:
        facts.append("👤 " + ", ".join(p for p, _ in info["persons"][:3]))
    target = f"in vorhandenen Ordner „{sug['existing'][0]}“?" if sug["existing"] else f"„{sug['name']}“"
    w(f"<details class='sug'><summary><span><span class='t'>{esc(sug['rel'])}</span> → "
      f"<span class='proposal'>{esc(target)}</span></span><span class='nums'>{esc(' · '.join(facts))}</span>"
      "</summary><div class='inner'>")
    thumbs = [i for i in items if i["file"]]
    if thumbs:
        step = max(1, len(thumbs) // 6)
        w("<div class='thumbs'>")
        for i in thumbs[::step][:6]:
            src = (Path(cfg["export_dir"]) / i["file"]).as_uri()
            w(f"<img src='{esc(src)}' loading='lazy' alt='' title='{esc(i['name'])}'>")
        w("</div>")
    w("<table>")
    why = ("zeitliche Häufung" if sug["kind"] == "time" else "gleiche Beschreibung")
    w(f"<tr><th>Gefunden durch</th><td>{why}: {fmt(len(items))} Fotos, {esc(when)}</td></tr>")
    if info["desc"]:
        w(f"<tr><th>Beschreibung</th><td>„{esc(info['desc'])}“ ({fmt(info['desc_n'])} von {fmt(len(items))})</td></tr>")
    if info["place"]:
        w(f"<tr><th>Ort</th><td>{esc(info['place'])} ({fmt(info['place_n'])} von {fmt(len(items))})</td></tr>")
    if info["persons"]:
        w("<tr><th>Personen</th><td>" + esc(", ".join(f"{p} ({c})" for p, c in info["persons"])) + "</td></tr>")
    missing = sum(1 for i in items if not i["file"])
    if missing:
        w(f"<tr><th>Nicht exportiert</th><td>{fmt(missing)} (nur Datum aus dem Dateinamen, ohne Ort und Personen)</td></tr>")
    if sug["kind"] == "desc":
        w("<tr><th>⚠ Datum</th><td>Die Fotos wurden über die Beschreibung gefunden – das Datum im Namensvorschlag "
          "ist das früheste; bei Scans mit Ersatzdatum bitte anpassen.</td></tr>")
    w("</table>")
    if sug["kind"] == "time":
        pick = (f"Library Filter › <i>Metadata</i> › Spalte <i>Date</i>: {esc(when)} auswählen (mehrere Tage mit "
                "Strg), dann Strg+A")
    else:
        pick = (f"Library Filter › <i>Text</i> › <i>Caption</i> › <i>contains</i> „{esc(info['desc'])}“, dann Strg+A")
    if sug["existing"]:
        move = (f"die markierten Bilder im Folders-Panel auf den vorhandenen Ordner „{esc(sug['existing'][0])}“ ziehen "
                "(passt er nicht: neuen Ordner wie unten)")
    else:
        move = (f"im Folders-Panel Rechtsklick auf „{esc(sug['folder'])}“ › <i>Create Folder inside “{esc(sug['folder'])}”…</i>"
                f" › Name z. B. <b style='color:inherit'>{esc(sug['name'])}</b>, Häkchen <i>Include selected photos</i>"
                " › <i>Create</i> (verschiebt die Bilder)")
    w(f"<div class='todo'><b>Was tun in Lightroom:</b> 1. Ordner „{esc(sug['rel'])}“ öffnen. 2. {pick}. 3. {move}. "
      "4. Den neuen Ordner exportieren, dann sync.bat und aufraeumen.bat (räumt die alten Exporte weg).</div>")
    w("<div class='small muted'>Fotos:</div><ul class='files'>")
    for i in items:
        mark = "" if i["file"] else " <span class='muted'>(nicht exportiert)</span>"
        w(f"<li>{esc(i['name'])} <span class='muted'>{i['time']:%d.%m.%Y %H:%M}</span>{mark}</li>")
    w("</ul></div></details>")


def build_page(cfg, r, started):
    folders, status = r["folders"], r["status"]
    hints_by_folder = defaultdict(list)   # ohne GPS: das sind die echten Warnungen
    gps_by_folder = defaultdict(list)     # fehlendes GPS: nur Info (Ort oft unbekannt)
    for e in r["exports"]:
        if not e["severe"] and e.get("key"):
            for sev, text in e["problems"]:
                if sev == regeln.HINWEIS:
                    (gps_by_folder if text == GPS_HINT else hints_by_folder)[e["key"][0]].append((e, text))

    groups = defaultdict(list)
    totals = Counter()
    for key, folder in folders.items():
        images = folder["images"]
        n = len(images)
        online = sum(1 for stem in images if status.get((key, stem)) == "online")
        exported = sum(1 for stem in images if (key, stem) in status)
        missing = sorted((img for stem, img in images.items() if (key, stem) not in status),
                         key=lambda img: img["stem"].casefold())
        state = folder_state(n, exported, online)
        parts = folder["rel"].split(os.sep)
        groups[parts[0]].append({"name": folder["name"], "rel": folder["rel"], "sub": os.sep.join(parts[1:]),
                                 "n": n, "exp": exported, "online": online, "missing": missing, "state": state,
                                 "hints": hints_by_folder.get(key, []), "gps": gps_by_folder.get(key, []),
                                 "st": r["stats"].get(key)})
        totals["n"] += n
        totals["online"] += online
        totals["wait"] += exported - online
        totals["none"] += n - exported

    stats = r["stats"]
    st_all = sum(stats.values(), Counter())
    exported_folders = [st for st in stats.values() if st["n"]]
    no_gps_folders = sum(1 for st in exported_folders if st["gps"] == st["n"])
    no_person_folders = sum(1 for st in exported_folders if st["p"] == st["n"])
    suggestions = r["suggestions"]
    cleanup = r["orphans"] + r["dups"] + r["pair_exports"] + r["unusable"]
    tasks = build_tasks(r, hints_by_folder)
    check_total = sum(len(v) for v in tasks.values())

    out = []
    w = out.append
    w("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>Fotoschatz Übersicht</title><style>{CSS}</style><script>{JS}</script></head><body><main>")
    w("<h1>Fotoschatz – was ist online?</h1>")
    w(f"<div class='muted small'>Stand {datetime.now():%d.%m.%Y %H:%M} · uebersicht.py v{__version__} · "
      f"Originale: {esc(cfg['originals_dir'])} · Exporte: {esc(cfg['export_dir'])} · {time.time() - started:.0f} s</div>")

    n = totals["n"]
    pct = f" ({100 * totals['online'] / n:.0f} %)" if n else ""
    w("<div class='cards'>")
    w(f"<div class='card'><b>{fmt(n)}</b><span>Bilder in Lightroom-Ordnern</span></div>")
    w(f"<div class='card'><b style='color:var(--ok)'>{fmt(totals['online'])}</b><span>online{pct}</span></div>")
    w(f"<div class='card'><b style='color:var(--wait)'>{fmt(totals['wait'])}</b><span>exportiert, Sync fehlt noch</span></div>")
    w(f"<div class='card'><b style='color:var(--none)'>{fmt(totals['none'])}</b><span>noch nicht exportiert</span></div>")
    w(f"<div class='card'><b style='color:var(--warn)'>{fmt(check_total)}</b><span>Aufgaben in Lightroom</span></div>")
    w(f"<div class='card'><b style='color:var(--warn)'>{fmt(len(cleanup))}</b><span>überflüssige Exporte (aufraeumen.bat)</span></div>")
    w(f"<div class='card'><b>{fmt(len(suggestions))}</b><span>Vorschläge für neue Ordner</span></div>")
    w(f"<div class='card'><b class='muted'>📍 {esc(percent(st_all['gps'], st_all['n']))}</b><span>der exportierten Bilder ohne GPS · "
      f"{fmt(no_gps_folders)} von {fmt(len(exported_folders))} Ordnern ganz ohne</span></div>")
    w(f"<div class='card'><b class='muted'>👤 {esc(percent(st_all['p'], st_all['n']))}</b><span>der exportierten Bilder ohne "
      f"Personen · {fmt(no_person_folders)} von {fmt(len(exported_folders))} Ordnern ganz ohne</span></div>")
    w("</div>")
    w(bar(totals["online"], totals["wait"], totals["none"], n))

    # ---- Aufgaben in Lightroom, je Ordner
    w(f"<h2>Zu erledigen in Lightroom ({fmt(check_total)})</h2>")
    if not check_total:
        w("<div class='none'>Nichts zu tun.</div>")
    else:
        w("<div class='todo'><b>So gehst du vor:</b> 1. Ordner links im <i>Folders</i>-Panel öffnen (Pfad unter "
          "D:\\Bilder - Raw wie angegeben). 2. Bild finden: <i>Library Filter › Text › Filename › contains</i> und den "
          "Dateinamen eintippen. 3. Ändern wie in der Spalte „Was tun“. 4. Danach den Ordner neu exportieren "
          "(<i>Photo › Stacking › Collapse All Stacks</i>, Strg+A, <i>Export</i>), dann sync.bat und aufraeumen.bat. "
          "Ordner nur in Lightroom umbenennen oder verschieben, nie im Explorer.</div>")
        w("<div class='tools'><button onclick=\"openTasks(true)\">Alle aufklappen</button>"
          "<button onclick=\"openTasks(false)\">Alle zuklappen</button></div>")
        for rel in sorted(tasks, key=str.casefold):
            rows = tasks[rel]
            kinds = Counter(kind for kind, *_ in rows)
            badges = " · ".join(f"{fmt(c)} {esc(k)}" for k, c in kinds.most_common())
            w(f"<details class='task'><summary><span class='t'>{esc(rel)}</span>"
              f"<span class='warn'>{badges}</span></summary><div class='inner'><table>"
              "<tr><th>Datei in Lightroom</th><th>Aufnahmezeit</th><th>Problem</th><th>Was tun in Lightroom</th></tr>")
            for kind, file, when, problem, todo in rows:
                w(f"<tr><td><b>{esc(file)}</b></td><td class='nowrap'>{esc(when)}</td><td>{esc(problem)}</td>"
                  f"<td>{esc(todo)}</td></tr>")
            w("</table></div></details>")
    if exported_folders:
        w(f"<details><summary><span class='t gps'>Ohne GPS / ohne Personen je Ordner – nur Info</span></summary>"
          "<div class='inner'><div class='todo'>Gezählt werden die exportierten Bilder. Oft ist der Ort unbekannt, und "
          "Landschaftsbilder haben keine Personen – das ist in Ordnung. Wer mag, setzt in Lightroom den Ort nach (Map) "
          "oder benennt Gesichter (Taste O, <i>People</i>).</div>"
          "<table><tr><th>Ordner in Lightroom</th><th>exportiert</th><th>ohne GPS</th><th>ohne Personen</th></tr>")
        for key, st in sorted(stats.items(), key=lambda x: folders[x[0]]["rel"].casefold()):
            w(f"<tr><td>{esc(folders[key]['rel'])}</td><td>{fmt(st['n'])}</td>"
              f"<td class='nowrap'>{fmt(st['gps'])} ({esc(percent(st['gps'], st['n']))})</td>"
              f"<td class='nowrap'>{fmt(st['p'])} ({esc(percent(st['p'], st['n']))})</td></tr>")
        w("</table></div></details>")

    # ---- Vorschlaege fuer neue Ordner
    w(f"<h2>Vorschläge für neue Ordner ({fmt(len(suggestions))})</h2>")
    w(f"<div class='todo'>Nur Vorschläge – das Tool legt nichts an und verschiebt nichts. Gesucht wird in Sammelordnern "
      f"(z. B. „1963-1974 …“) und bei losen Bildern im Jahresordner: mindestens {MIN_EVENT} Fotos, die höchstens "
      f"{EVENT_GAP.days} Tage auseinanderliegen, oder mit gleicher Beschreibung. ⚠ Scans mit Ersatzdatum und ohne "
      "Beschreibung erkennt es nicht.</div>")
    if not suggestions:
        w("<div class='none'>Keine Vorschläge.</div>")
    else:
        w("<div class='tools'><button onclick=\"openSuggestions(true)\">Alle aufklappen</button>"
          "<button onclick=\"openSuggestions(false)\">Alle zuklappen</button></div>")
    for sug in suggestions:
        write_suggestion(w, sug, cfg)

    # ---- Aufraeumen
    w("<h2>Aufräumen in D:\\Fotoschatz</h2>")
    if not cleanup:
        w("<div class='none'>Keine überflüssigen Exporte.</div>")
    else:
        w("<div class='todo'><b>Was tun:</b> <b style='color:inherit'>aufraeumen.bat</b> doppelklicken – es fragt je Gruppe "
          "nach und verschiebt die Dateien nach _sync\\geloescht\\ (nicht endgültig gelöscht). Beim nächsten sync.bat "
          "verschwinden sie online. Die Originale in Lightroom bleiben unberührt.</div>")
    for title, items, note in [
        ("Exporte ohne passendes Original", r["orphans"], "Ordner oder Datei wurde in Lightroom umbenannt oder gelöscht. "
         "Nach dem Aufräumen den Ordner neu exportieren, falls die Bilder online sein sollen."),
        ("Doppelt exportiert (älterer Export)", r["dups"], "Zwei Exporte vom selben Original aus verschiedenen "
         "Export-Durchgängen – der neueste bleibt. Exporte aus demselben Durchgang (virtuelle Kopien) stehen nicht hier."),
        ("RAW und JPG beide exportiert", r["pair_exports"], "Dasselbe Foto wurde aus der RAW- und aus der JPG-Datei "
         "exportiert und wäre online doppelt. Der Export aus der RAW-Datei bleibt."),
        ("Nicht verwendbare Exporte", r["unusable"], "Werden nie hochgeladen (Dateiname oder Ordner passt nicht). "
         "Ursache in Lightroom beheben (siehe Grund), dann neu exportieren."),
    ]:
        if not items:
            continue
        w(f"<details><summary><span class='t'>{esc(title)} ({fmt(len(items))})</span></summary><div class='inner'>"
          f"<div class='small muted'>{esc(note)}</div><table>"
          "<tr><th>Exportdatei</th><th>Originaldatei</th><th>online</th><th>Grund</th></tr>")
        for e, reason in sorted(items, key=lambda x: x[0]["file"]):
            w(f"<tr><td>{esc(e['file'])}</td><td>{esc(e['orig'] or '–')}</td>"
              f"<td>{'ja' if e['online'] else 'nein'}</td><td>{esc(reason)}</td></tr>")
        w("</table></div></details>")

    # ---- Ordner wie in Lightroom
    w("<h2>Ordner wie in Lightroom</h2>")
    w("<div class='tools'>"
      "<button id='f-all' class='on' onclick=\"setFilter('all')\">Alle Ordner</button>"
      "<button id='f-open' onclick=\"setFilter('open')\">Nur offene</button>"
      "<button id='f-fewp' onclick=\"setFilter('fewp')\">Viele ohne Personen</button>"
      "<button onclick='openAll(true)'>Alle aufklappen</button>"
      "<button onclick='openAll(false)'>Alle zuklappen</button></div>")
    w("<div class='legend small muted'>"
      + "".join(f"<span><i class='dot s-{k}'></i>{v}</span>" for k, v in LABEL.items())
      + "<span class='warn'>⚠ Hinweise</span><span class='gps'>📍 ohne GPS · 👤 ohne Personen: Anteil der exportierten "
      "Bilder (nur Info)</span></div>")
    # oberste Ebene wie unter D:\Bilder - Raw, neueste zuerst; Namen ohne Jahreszahl zuletzt
    for top in sorted(groups, key=lambda g: (g[:1].isdigit(), g.casefold()), reverse=True):
        items = sorted(groups[top], key=lambda f: f["sub"].casefold(), reverse=True)
        items.sort(key=lambda f: not f["sub"])  # Bilder direkt im oberen Ordner ans Ende
        y = Counter()
        states_count = Counter()   # getrennt von y, sonst vermischt sich "wait" (Bilder) mit "wait" (Ordner)
        warn_all, st_top = [], Counter()
        for f in items:
            y["n"] += f["n"]
            y["online"] += f["online"]
            y["wait"] += f["exp"] - f["online"]
            warn_all += f["hints"]
            st_top += f["st"] or Counter()
            states_count[f["state"]] += 1
        done = " done" if all(f["state"] == "ok" and not f["hints"] for f in items) else ""
        states = " · ".join(f"<i class='dot s-{k}'></i>{states_count[k]}" for k in LABEL if states_count[k])
        warn = hint_badges(warn_all, st_top)
        if any(few_persons(f["st"]) for f in items):
            done += " fewp"
        w(f"<details class='year{done}'><summary><span class='t'>{esc(top)}</span><span class='row'>{warn}"
          f"<span class='nums'>{fmt(y['n'])} Bilder · {fmt(y['online'])} online · Ordner: {states}</span>"
          f"{bar(y['online'], y['wait'], y['n'] - y['online'] - y['wait'], y['n'])}</span></summary><div class='inner'>")
        for f in items:
            if f["sub"]:
                name = f["sub"]
            elif YEAR_DIR_RE.match(top):
                name = f"lose Bilder → „{top} Weitere Bilder“"
            else:
                name = "Bilder direkt in diesem Ordner"
            nums = f"{fmt(f['n'])} Bilder · {fmt(f['exp'])} exportiert · {fmt(f['online'])} online"
            warn = hint_badges(f["hints"], f["st"])
            head = f"<span><i class='dot s-{f['state']}'></i>{esc(name)}</span>{warn}<span class='nums'>{nums}</span>"
            cls = " done" if f["state"] == "ok" and not f["hints"] else ""
            cls += " fewp" if few_persons(f["st"]) else ""
            if not f["missing"] and not f["hints"] and not f["gps"]:
                w(f"<div class='plain{cls}'>{head}</div>")
                continue
            w(f"<details class='folder{cls}'><summary>{head}</summary><div class='inner'>")
            w(f"<div class='small muted'>Ordner in Lightroom: {esc(f['rel'])}</div>")
            if f["hints"] or f["gps"]:
                w("<table><tr><th>Originaldatei</th><th>Hinweis</th></tr>")
                for e, text in sorted(f["hints"], key=lambda x: x[0]["file"]) + sorted(f["gps"], key=lambda x: x[0]["file"]):
                    w(f"<tr><td>{esc(e['orig'] or e['stem'])}</td><td>{esc(text)}</td></tr>")
                w("</table>")
            if f["missing"]:
                w(f"<div class='small muted'>Nicht exportiert ({fmt(len(f['missing']))}):</div><ul class='files'>")
                for img in f["missing"]:
                    exts = " + ".join(sorted(x.lstrip(".").upper() for x in img["ext"]))
                    w(f"<li>{esc(img['stem'])} <span class='muted'>{esc(exts)}</span></li>")
                w("</ul>")
            w("</div></details>")
        w("</div></details>")

    # ---- Weitere Angaben
    w("<h2>Weitere Angaben</h2>")
    if r["empty"]:
        w(f"<details><summary><span class='t'>Leere Ordner ({len(r['empty'])})</span></summary><div class='inner'><table>")
        for rel in sorted(r["empty"]):
            w(f"<tr><td>{esc(rel)}</td></tr>")
        w("</table></div></details>")
    if r["skipped"]:
        w(f"<details><summary><span class='t'>Bewusst nicht online: Ordner mit „_“ ({fmt(sum(r['skipped'].values()))} Bilder)</span>"
          "</summary><div class='inner'><table>")
        for rel, count in sorted(r["skipped"].items()):
            w(f"<tr><td>{esc(rel)}</td><td>{fmt(count)}</td></tr>")
        w("</table></div></details>")
    if r["videos"]:
        w(f"<details><summary><span class='t'>Videos (nicht im Projekt, {fmt(sum(r['videos'].values()))})</span></summary>"
          "<div class='inner'><table>")
        for rel, count in sorted(r["videos"].items()):
            w(f"<tr><td>{esc(rel)}</td><td>{fmt(count)}</td></tr>")
        w("</table></div></details>")
    w("<details><summary><span class='t'>Dateiarten im Originalordner</span></summary><div class='inner'><table>")
    for ext, count in r["ext_count"].most_common():
        kind = ("RAW" if ext in RAW_EXT else "Bild" if ext in IMAGE_EXT else "Video" if ext in VIDEO_EXT else "sonstige")
        w(f"<tr><td>{esc(ext)}</td><td>{kind}</td><td>{fmt(count)}</td></tr>")
    w("</table><div class='small muted'>RAW und JPG mit gleichem Namen im selben Ordner zählen als ein Bild.</div>"
      "</div></details>")
    w("</main></body></html>")
    return "\n".join(out), totals, check_total, len(cleanup), len(suggestions)


# ---------------------------------------------------------------- Browser

def default_browser_command():
    """Befehl des Standard-Browsers (Programm fuer Internet-Links), nicht das Programm fuer .html-Dateien."""
    import winreg
    for scheme in ("https", "http"):
        try:
            key = rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                prog_id = winreg.QueryValueEx(k, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as k:
                return winreg.QueryValueEx(k, "")[0]
        except OSError:
            continue
    return None


def open_in_browser(path):
    """Oeffnet die Seite im Standard-Browser. True, wenn das geklappt hat."""
    if os.name != "nt":
        return False
    url = path.as_uri()  # Leerzeichen/Umlaute werden kodiert -> keine Anfuehrungszeichen noetig
    try:
        cmd = default_browser_command()
        if cmd:
            subprocess.Popen(cmd.replace("%1", url) if "%1" in cmd else f"{cmd} {url}")
            return True
    except OSError:
        pass
    for exe in ("msedge", "chrome"):  # Notloesung
        try:
            subprocess.Popen(f'cmd /c start "" {exe} "{url}"', shell=False)
            return True
        except OSError:
            continue
    return False


def main():
    started = time.time()
    cfg = load_config()
    print(f"uebersicht.py v{__version__}")
    r = analyze(cfg)
    page, totals, check_total, cleanup_total, suggestion_total = build_page(cfg, r, started)
    OUT_FILE.write_text(page, encoding="utf-8")

    print()
    print(f"Bilder in Lightroom-Ordnern: {totals['n']}")
    print(f"  online:                    {totals['online']}")
    print(f"  exportiert, Sync fehlt:    {totals['wait']}")
    print(f"  noch nicht exportiert:     {totals['none']}")
    print(f"Aufgaben in Lightroom:       {check_total}")
    print(f"Aufzuraeumen (aufraeumen.bat): {cleanup_total}")
    print(f"Vorschlaege fuer neue Ordner: {suggestion_total}")
    print(f"\nUebersicht: {OUT_FILE}")
    if not open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")
        sys.exit(2)  # Fenster bleibt offen (uebersicht.bat)


if __name__ == "__main__":
    main()
