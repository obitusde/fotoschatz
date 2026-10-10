#!/usr/bin/env python3
"""Fotoschatz - Katalog-Diagnose: Kann das Tool den Lightroom-Katalog lesen und richtig verstehen?

Kopiert den Katalog nach _sync\\katalog\\ (Lightroom muss geschlossen sein) und liest NUR die Kopie.
Der Original-Katalog und D:\\Bilder - Raw werden nie veraendert (Originalordner: nur Dateinamen lesen).
Schreibt katalog_diagnose.txt neben dieses Skript - diese Datei bitte an Claude schicken.
Sie enthaelt vor allem Anzahlen und Tabellenaufbau, dazu wenige Beispiele (Ordner, Stichwoerter).

Aufruf: katalog_diagnose.bat (Doppelklick) oder python katalog_diagnose.py
Optional in config.local.json: "catalog": "C:\\\\Daten\\\\Lightroom Catalog"
"""

__version__ = "0.7.7"

import json
import os
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import katalog
from uebersicht import IMAGE_EXT, VIDEO_EXT, SKIP_DIRS

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "katalog_diagnose.txt"
DEFAULTS = {"catalog": katalog.DEFAULT_CATALOG, "originals_dir": r"D:\Bilder - Raw"}
EXAMPLES = 10

# Tabellen, deren Aufbau vollstaendig ausgegeben wird (dazu alle mit Face/Keyword/Stack/Iptc im Namen)
DETAIL_TABLES = ["Adobe_images", "AgLibraryFile", "AgLibraryFolder", "AgLibraryRootFolder", "AgLibraryKeyword",
                 "AgLibraryKeywordImage", "AgHarvestedExifMetadata", "AgHarvestedIptcMetadata", "AgLibraryIPTC",
                 "AgLibraryFolderStack", "AgLibraryFolderStackImage", "AgLibraryFolderStackData",
                 "AgLibraryCollection", "Adobe_AdditionalMetadata", "Adobe_imageProperties", "Adobe_variablesTable"]
DETAIL_WORDS = ("face", "keyword", "stack", "iptc", "location", "interned", "publish", "remote")

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def short(value, n=45):
    text = str(value).replace("\n", " ")
    return text if len(text) <= n else text[:n - 1] + "…"


def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return cfg


def q(db, sql, *args):
    return db.execute(sql, args).fetchall()


def one(db, sql, *args):
    row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def section(title, fn, *args):
    out()
    out("=" * 70)
    out(title)
    out("=" * 70)
    started = time.time()
    try:
        fn(*args)
    except Exception as err:   # Diagnose soll weiterlaufen, der Fehler selbst ist die Information
        out(f"  FEHLER: {type(err).__name__}: {err}")
    out(f"  ({time.time() - started:.1f} s)")


def norm(text):
    """Vergleichsform: klein, ohne Akzente/Umlaute-Unterschiede, ohne Leerzeichen und Satzzeichen."""
    text = unicodedata.normalize("NFKD", str(text).casefold().replace("ß", "ss"))
    return "".join(c for c in text if c.isalnum())


# ---------------------------------------------------------------- Aufbau

def tables(db):
    return [r[0] for r in q(db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def columns(db, table):
    return [(r[1], r[2]) for r in q(db, f'PRAGMA table_info("{table}")')]


def has(db, table, column=None):
    if table not in tables(db):
        return False
    return column is None or column in [c for c, _ in columns(db, table)]


def show_overview(db):
    for t in tables(db):
        count = one(db, 'SELECT COUNT(*) FROM "%s"' % t)
        out(f"  {t:45} {count:>9} Zeilen")
    hits = [f"{t}.{c}" for t in tables(db) for c, _ in columns(db, t)
            if "face" in c.lower() and "face" not in t.lower()]
    out(f"  Spalten mit 'face' in anderen Tabellen: {', '.join(hits) or '-'}")


def show_table(db, table):
    total = one(db, f'SELECT COUNT(*) FROM "{table}"')
    out(f"\n  [{table}] {total} Zeilen")
    for col, typ in columns(db, table):
        c = f'"{col}"'
        longest = one(db, f'SELECT MAX(LENGTH({c})) FROM "{table}"') or 0
        filled = one(db, f'SELECT COUNT({c}) FROM "{table}"')
        if longest > 200:
            out(f"    {col:32} {typ:8} gefüllt {filled:>7}  (langer Text/Blob, bis {longest} Zeichen)")
            continue
        distinct = one(db, f'SELECT COUNT(DISTINCT {c}) FROM "{table}"')
        info = f"    {col:32} {typ:8} gefüllt {filled:>7}  verschieden {distinct:>7}"
        if 0 < distinct <= 12:
            vals = q(db, f'SELECT {c}, COUNT(*) FROM "{table}" GROUP BY {c} ORDER BY COUNT(*) DESC')
            info += "  Werte: " + ", ".join(f"{short(v, 30)!s}={n}" for v, n in vals)
        elif distinct:
            lo, hi = q(db, f'SELECT MIN({c}), MAX({c}) FROM "{table}"')[0]
            info += f"  von {short(lo, 30)} bis {short(hi, 30)}"
        out(info)


def show_structure(db):
    for t in tables(db):
        if t in DETAIL_TABLES or any(w in t.lower() for w in DETAIL_WORDS):
            show_table(db, t)


# ---------------------------------------------------------------- gezielte Pruefungen

def image_rows(db):
    """Alle Bilder mit Datei, Ordner, Wurzelordner (Kernverknuepfung, die die Pruefung braucht)."""
    return q(db, """
        SELECT i.id_local AS id, i.masterImage AS master, i.copyName AS copyName, i.captureTime AS captureTime,
               i.fileFormat AS fileFormat, i.pick AS pick, i.rating AS rating,
               f.baseName AS baseName, f.extension AS extension, f.originalFilename AS originalFilename,
               f.sidecarExtensions AS sidecars,
               fo.id_local AS folderId, fo.pathFromRoot AS pathFromRoot, r.absolutePath AS root
        FROM Adobe_images i
        LEFT JOIN AgLibraryFile f ON f.id_local = i.rootFile
        LEFT JOIN AgLibraryFolder fo ON fo.id_local = f.folder
        LEFT JOIN AgLibraryRootFolder r ON r.id_local = fo.rootFolder""")


def full_path(row):
    if row["root"] is None or row["baseName"] is None:
        return None
    ext = f".{row['extension']}" if row["extension"] else ""
    return (row["root"] + (row["pathFromRoot"] or "") + row["baseName"] + ext).replace("\\", "/")


def check_version(db):
    for name in ("Adobe_DBVersion", "Adobe_storeProviderID", "AgLibraryKeyword_rootTagID"):
        out(f"  {name}: {one(db, 'SELECT value FROM Adobe_variablesTable WHERE name=?', name)}")
    out(f"  SQLite quick_check der Kopie: {one(db, 'PRAGMA quick_check')}")


def check_roots(db, cfg):
    originals = str(cfg["originals_dir"]).replace("\\", "/").rstrip("/").casefold() + "/"
    for r in q(db, """SELECT r.id_local, r.name, r.absolutePath,
                             (SELECT COUNT(*) FROM AgLibraryFolder fo WHERE fo.rootFolder = r.id_local) AS folders,
                             (SELECT COUNT(*) FROM AgLibraryFile f JOIN AgLibraryFolder fo ON fo.id_local = f.folder
                              WHERE fo.rootFolder = r.id_local) AS files
                      FROM AgLibraryRootFolder r ORDER BY r.absolutePath"""):
        where = "unter Originalordner" if str(r["absolutePath"]).replace("\\", "/").casefold().startswith(originals) \
            else "AUSSERHALB des Originalordners"
        out(f"  Wurzel {r['absolutePath']!r} (Name {r['name']!r}): {r['folders']} Ordner, {r['files']} Dateien – {where}")


def check_images(db, rows):
    out(f"  Bilder im Katalog: {len(rows)}")
    out(f"  davon virtuelle Kopien (masterImage gesetzt): {sum(1 for r in rows if r['master'])}")
    out(f"  Verknüpfung Bild→Datei→Ordner→Wurzel vollständig: {sum(1 for r in rows if full_path(r))}")
    out(f"  Dateiformat: {dict(Counter(r['fileFormat'] for r in rows).most_common())}")
    out(f"  Dateiendung: {dict(Counter((r['extension'] or '').lower() for r in rows).most_common(15))}")
    out(f"  Markierung pick (1=Flagge, -1=abgelehnt): {dict(Counter(r['pick'] for r in rows).most_common())}")
    out(f"  Bewertung: {dict(Counter(r['rating'] for r in rows).most_common())}")
    out(f"  Begleitdateien (sidecarExtensions): {dict(Counter(r['sidecars'] or '' for r in rows).most_common(10))}")
    times = [r["captureTime"] for r in rows if r["captureTime"]]
    out(f"  Aufnahmezeit fehlt: {len(rows) - len(times)}")
    shapes = Counter("".join("9" if ch.isdigit() else ch for ch in t) for t in times)
    out(f"  Aufnahmezeit-Formen: {dict(shapes.most_common(8))}")
    if times:
        out(f"  Aufnahmezeit von {min(times)} bis {max(times)}")
    same = Counter(t for t in times)
    out(f"  Aufnahmezeiten, die bei ≥ 5 Bildern gleich sind: {sum(1 for c in same.values() if c >= 5)} "
        f"(Beispiele: {', '.join(f'{t} ×{c}' for t, c in same.most_common(5) if c >= 5) or '-'})")
    underscore = sum(1 for r in rows if any(p.startswith("_") for p in (r["pathFromRoot"] or "").split("/")))
    out(f"  Bilder in Ordnern mit '_' (z. B. _Import): {underscore}")
    ren = sum(1 for r in rows if r["originalFilename"] and r["baseName"]
              and not r["originalFilename"].casefold().startswith(r["baseName"].casefold()))
    out(f"  Dateiname beim Import geändert (originalFilename ≠ baseName): {ren}")


def check_disk(db, rows, cfg):
    """Vergleich Katalog <-> Festplatte, nur ueber Verzeichnislisten (nichts wird geoeffnet)."""
    originals = Path(cfg["originals_dir"])
    if not originals.is_dir():
        out(f"  Originalordner nicht gefunden: {originals} – übersprungen")
        return
    base = str(originals).replace("\\", "/").rstrip("/") + "/"
    on_disk = {}
    for dirpath, dirnames, filenames in os.walk(originals):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for name in filenames:
            p = (os.path.join(dirpath, name)).replace("\\", "/")
            on_disk[p.casefold()] = p
    in_catalog = set()
    missing = []
    for r in rows:
        p = full_path(r)
        if not p or r["master"]:
            continue
        in_catalog.add(p.casefold())
        for side in (r["sidecars"] or "").split(","):
            if side.strip():
                in_catalog.add((p.rsplit(".", 1)[0] + "." + side.strip()).casefold())
        if p.casefold().startswith(base.casefold()) and p.casefold() not in on_disk:
            missing.append(p)
    out(f"  Dateien auf der Platte unter {originals}: {len(on_disk)}")
    out(f"  Katalog-Bilder, deren Datei fehlt (Fragezeichen in Lightroom): {len(missing)}")
    for p in missing[:EXAMPLES]:
        out(f"    fehlt: {p[len(base):]}")
    not_imported = Counter()
    examples = []
    for key, p in on_disk.items():
        ext = os.path.splitext(p)[1].lower()
        if key in in_catalog or ext not in IMAGE_EXT | VIDEO_EXT:
            continue
        rel = p[len(base):]
        kind = "Video" if ext in VIDEO_EXT else "Bild"
        where = "in _-Ordner" if any(part.startswith("_") for part in rel.split("/")[:-1]) else "normal"
        not_imported[(kind, where)] += 1
        if kind == "Bild" and where == "normal" and len(examples) < EXAMPLES:
            examples.append(rel)
    out(f"  Dateien auf der Platte, die NICHT im Katalog sind: {dict(not_imported)}")
    for rel in examples:
        out(f"    nicht importiert: {rel}")


def check_stacks(db, rows):
    if not has(db, "AgLibraryFolderStackImage"):
        out("  Tabelle AgLibraryFolderStackImage fehlt")
        return
    st = {r["image"]: (r["stack"], r["position"]) for r in
          q(db, "SELECT image, stack, position FROM AgLibraryFolderStackImage")}
    out(f"  Bilder in Stapeln: {len(st)}, Stapel: {len(set(s for s, _ in st.values()))}")
    out(f"  Position im Stapel: {dict(Counter(p for _, p in st.values()).most_common(6))}")
    if has(db, "AgLibraryFolderStack", "collapsed"):
        out(f"  Stapel zugeklappt: {dict(Counter(r[0] for r in q(db, 'SELECT collapsed FROM AgLibraryFolderStack')))}")
    copies = [r for r in rows if r["master"]]
    same = sum(1 for r in copies if r["id"] in st and r["master"] in st and st[r["id"]][0] == st[r["master"]][0])
    out(f"  Virtuelle Kopien: {len(copies)} – mit dem Original gestapelt: {same}, nicht gestapelt: {len(copies) - same}")
    top_copy = sum(1 for r in copies if r["id"] in st and st[r["id"]][1] == 1)
    out(f"  Virtuelle Kopien oben im Stapel: {top_copy}")
    edits = [r for r in rows if (r["extension"] or "").lower() in ("tif", "tiff", "psd") and not r["master"]]
    out(f"  TIF/PSD-Dateien (meist Bearbeitungen): {len(edits)}, davon in einem Stapel: "
        f"{sum(1 for r in edits if r['id'] in st)}")


def check_keywords(db):
    root = one(db, "SELECT value FROM Adobe_variablesTable WHERE name='AgLibraryKeyword_rootTagID'")
    kws = q(db, """SELECT k.*, (SELECT COUNT(*) FROM AgLibraryKeywordImage ki WHERE ki.tag = k.id_local) AS n
                   FROM AgLibraryKeyword k""")
    kws = [k for k in kws if str(k["id_local"]) != str(root)]
    keys = kws[0].keys() if kws else []
    out(f"  Stichwörter: {len(kws)}")
    if "keywordType" in keys:
        out(f"  keywordType: {dict(Counter(k['keywordType'] for k in kws))}")
    for col in ("includeOnExport", "includeParents", "includeSynonyms"):
        if col in keys:
            out(f"  {col}: {dict(Counter(k[col] for k in kws))}")
    nested = [k for k in kws if k["parent"] is not None and str(k["parent"]) != str(root)]
    out(f"  mit übergeordnetem Stichwort (Hierarchie): {len(nested)}")
    unused = [k for k in kws if k["n"] == 0]
    out(f"  ohne Bild: {len(unused)} – Beispiele: {', '.join(short(k['name'], 30) for k in unused[:EXAMPLES]) or '-'}")
    if "includeOnExport" in keys:
        hidden = [k for k in kws if k["includeOnExport"] == 0]
        names = ", ".join("%s (%d)" % (short(k["name"], 30), k["n"]) for k in hidden[:20])
        out(f"  nicht beim Export: {names or '-'}")
    groups = defaultdict(list)
    for k in kws:
        groups[norm(k["name"])].append(k)
    dups = [g for g in groups.values() if len(g) > 1]
    out(f"  fast gleiche Namen (Groß/klein, Umlaute, Leerzeichen): {len(dups)} Gruppen")
    for g in dups[:EXAMPLES]:
        out("    " + " | ".join(f"{k['name']} ({k['n']})" for k in g))
    top = sorted(kws, key=lambda k: -k["n"])[:15]
    out("  häufigste: " + ", ".join(f"{short(k['name'], 25)} ({k['n']})" for k in top))


def check_faces(db, rows):
    if not has(db, "AgLibraryFace"):
        out("  Tabelle AgLibraryFace fehlt")
        return
    faces = q(db, "SELECT id_local, image FROM AgLibraryFace")
    out(f"  Gesichtsbereiche: {len(faces)} auf {len(set(f['image'] for f in faces))} Bildern")
    links = defaultdict(list)
    if has(db, "AgLibraryKeywordFace"):
        kf_cols = [c for c, _ in columns(db, "AgLibraryKeywordFace")]
        pick = "userPick" if "userPick" in kf_cols else "NULL"
        reject = "userReject" if "userReject" in kf_cols else "NULL"
        for r in q(db, f"SELECT face, tag, {pick} AS pick, {reject} AS reject FROM AgLibraryKeywordFace"):
            links[r["face"]].append(r)
        out(f"  Verknüpfungen Gesicht→Stichwort: {sum(len(v) for v in links.values())}, "
            f"userPick: {dict(Counter(r['pick'] for v in links.values() for r in v))}, "
            f"userReject: {dict(Counter(r['reject'] for v in links.values() for r in v))}")
    named = {f["id_local"] for f in faces if any(r["pick"] == 1 for r in links.get(f["id_local"], []))}
    suggested = {f["id_local"] for f in faces if links.get(f["id_local"]) and f["id_local"] not in named}
    nothing = [f for f in faces if not links.get(f["id_local"])]
    out(f"  benannt (bestätigt): {len(named)}, nur Vorschlag: {len(suggested)}, ohne Namen: {len(nothing)}")
    # Personen-Stichwoerter am Bild ohne Gesichtsbereich (z. B. von Hand vergeben)
    if has(db, "AgLibraryKeyword", "keywordType"):
        person_imgs = {r[0] for r in q(db, """SELECT DISTINCT ki.image FROM AgLibraryKeywordImage ki
                                              JOIN AgLibraryKeyword k ON k.id_local = ki.tag
                                              WHERE k.keywordType = 'person'""")}
        out(f"  Bilder mit Personen-Stichwort: {len(person_imgs)}")
    # Je Ordner: Gesichter ohne Namen
    folder_of = {r["id"]: r["pathFromRoot"] or "(Wurzelordner)" for r in rows}
    per = defaultdict(Counter)
    for f in faces:
        c = per[folder_of.get(f["image"], "?")]
        c["faces"] += 1
        c["unnamed"] += f["id_local"] not in named
    per_img = defaultdict(set)
    for r in rows:
        per_img[r["pathFromRoot"] or "(Wurzelordner)"].add(r["id"])
    face_imgs = {f["image"] for f in faces}
    no_faces = [k for k, ids in per_img.items() if len(ids) >= 10 and not ids & face_imgs]
    out(f"  Ordner (≥ 10 Bilder) ganz ohne Gesichtsbereiche – evtl. Gesichtserkennung nicht gelaufen: {len(no_faces)}")
    worst = sorted(per.items(), key=lambda x: -x[1]["unnamed"])[:EXAMPLES]
    out("  Ordner mit den meisten Gesichtern ohne Namen:")
    for folder, c in worst:
        out(f"    {c['unnamed']:>5} von {c['faces']:>5}  {short(folder, 70)}")


def check_places(db, rows):
    total = len(rows)
    if has(db, "AgHarvestedExifMetadata", "hasGPS"):
        out(f"  hasGPS: {dict(Counter(r[0] for r in q(db, 'SELECT hasGPS FROM AgHarvestedExifMetadata')))} (von {total} Bildern)")
    if has(db, "AgHarvestedIptcMetadata"):
        cols = [c for c, _ in columns(db, "AgHarvestedIptcMetadata")]
        for col in cols:
            if col.endswith("Ref") or col in ("locationDataOrigination", "locationGPSSensitivity"):
                out(f"  AgHarvestedIptcMetadata.{col} gefüllt: {one(db, f'SELECT COUNT({col}) FROM AgHarvestedIptcMetadata')}")
        if "cityRef" in cols and has(db, "AgHarvestedExifMetadata", "hasGPS"):
            n = one(db, """SELECT COUNT(*) FROM AgHarvestedExifMetadata e
                           LEFT JOIN AgHarvestedIptcMetadata p ON p.image = e.image
                           WHERE e.hasGPS = 1 AND p.cityRef IS NULL""")
            out(f"  GPS vorhanden, aber keine Stadt: {n}")
    for t in tables(db):
        if t.startswith("AgInternedIptc"):
            vals = [r[0] for r in q(db, f'SELECT value FROM "{t}" ORDER BY value')] if has(db, t, "value") else []
            out(f"  {t}: {len(vals)} Werte" + (f" – z. B. {', '.join(short(v, 25) for v in vals[:8])}" if vals else ""))
    if has(db, "AgLibraryIPTC", "caption"):
        n = one(db, "SELECT COUNT(*) FROM AgLibraryIPTC WHERE TRIM(COALESCE(caption, '')) <> ''")
        out(f"  Beschreibung (caption) gefüllt: {n}")


def check_collections(db):
    if has(db, "AgLibraryCollection", "creationId"):
        out(f"  Sammlungen nach Art: {dict(Counter(r[0] for r in q(db, 'SELECT creationId FROM AgLibraryCollection')))}")


def check_publish(db):
    """Lightroom Publish (v0.7.7): wo merkt sich Lightroom, was veroeffentlicht ist und was neu muss?
    Zeigt die Zeilen der Publish-Tabellen (gekuerzt) - fuer die Warnung "x Bilder warten auf Publish"."""
    names = [t for t in tables(db) if "publish" in t.lower() or "remote" in t.lower()]
    for t in names:
        total = one(db, f'SELECT COUNT(*) FROM "{t}"')
        out(f"\n  [{t}] {total} Zeilen – Beispiele:")
        cols = [c for c, _ in columns(db, t)]
        for row in q(db, f'SELECT * FROM "{t}" LIMIT 6'):
            out("    " + " | ".join(f"{c}={short(v, 120)}" for c, v in zip(cols, row)))
    if has(db, "AgRemotePhoto", "collection"):
        out("\n  Veröffentlichte Bilder je Published Folder:")
        for row in q(db, """SELECT r.collection, c.name, COUNT(*) FROM AgRemotePhoto r
                            LEFT JOIN AgLibraryCollection c ON c.id_local = r.collection GROUP BY r.collection"""):
            out(f"    Folder {row[0]} ({row[1]}): {row[2]} Bilder")
    flags = [c for c, _ in columns(db, "AgRemotePhoto")] if has(db, "AgRemotePhoto") else []
    for col in flags:
        if any(w in col.lower() for w in ("need", "update", "dirty", "modified", "digest", "count")):
            vals = q(db, f'SELECT "{col}", COUNT(*) FROM AgRemotePhoto GROUP BY "{col}" ORDER BY COUNT(*) DESC LIMIT 8')
            out(f"  AgRemotePhoto.{col}: " + ", ".join(f"{short(v, 40)}={n}" for v, n in vals))


def main():
    started = time.time()
    cfg = load_config()
    out(f"katalog_diagnose.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')}")
    try:
        catalog, copy, db = katalog.prepare(cfg["catalog"], protected=[cfg["originals_dir"]])
    except katalog.CatalogError as err:
        out(f"\nFEHLER: {err}")
        OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
        sys.exit(1)
    out(f"Katalog: {catalog} ({catalog.stat().st_size / 1e6:.0f} MB) → Kopie: {copy}")
    stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(catalog.stat().st_mtime))
    out(f"  zuletzt geändert {stamp} – benutzt, weil zuletzt geändert")
    for other in katalog.other_catalogs(catalog):
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(other.stat().st_mtime))
        out(f"  nicht benutzt (älter): {other.name}, zuletzt geändert {when}")

    rows = []
    section("1. Version", check_version, db)
    section("2. Alle Tabellen", show_overview, db)
    section("3. Wurzelordner", check_roots, db, cfg)
    try:
        rows = image_rows(db)
    except Exception as err:
        out(f"\nFEHLER beim Lesen der Bilder: {type(err).__name__}: {err}")
    section("4. Bilder", check_images, db, rows)
    section("5. Katalog ↔ Festplatte (nur Dateinamen)", check_disk, db, rows, cfg)
    section("6. Stapel und virtuelle Kopien", check_stacks, db, rows)
    section("7. Stichwörter", check_keywords, db)
    section("8. Gesichter und Personen", check_faces, db, rows)
    section("9. Orte, GPS, Beschreibung", check_places, db, rows)
    section("10. Sammlungen", check_collections, db)
    section("11. Aufbau der wichtigen Tabellen", show_structure, db)
    section("12. Lightroom Publish (Published Folder, veröffentlichte Bilder)", check_publish, db)
    db.close()
    out(f"\nFertig in {time.time() - started:.0f} s. Bitte diese Datei an Claude schicken: {OUT_FILE}")
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
