#!/usr/bin/env python3
"""Fotoschatz - Lightroom pruefen: Was ist in Lightroom zu korrigieren, bevor exportiert wird?

Liest eine KOPIE des Lightroom-Katalogs (Lightroom muss geschlossen sein) und D:\\Bilder - Raw nur als
Dateiliste. Es wird nichts korrigiert - weder im Katalog noch an den Originalen. Das Ergebnis ist eine
Aufgabenliste lightroom_pruefen.html neben diesem Skript: was DU in Lightroom aendern sollst.

Fuer "GPS nachtragen" wird zusaetzlich die Google-Zeitachse aus _sync\\google\\*.json gelesen (falls vorhanden) -
nur um zu zaehlen, wie viele Fotos ohne GPS einen Punkt in der Naehe haben. Koordinaten kommen nicht in die Seite.

Aufruf: lightroom_pruefen.bat (Doppelklick) oder python lightroom_pruefen.py
Optional in config.local.json: "catalog", "originals_dir", "ignore_keywords"
"""

__version__ = "0.6.28"


import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import gps_test
import katalog
import regeln
import uebersicht as U

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "lightroom_pruefen.html"
DEFAULTS = {
    "catalog": katalog.DEFAULT_CATALOG,
    "originals_dir": r"D:\Bilder - Raw",
    "ignore_keywords": ["google-fotos-uploaded", "Person", "Persons", "location-ok"],
}
EDIT_RE = re.compile(r"^(?P<base>.+?)(?P<suffix>(?:-(?:edit|bearbeitet|hdr|pano|enhanced|verbessert|nr|rr|sr|ai)"
                     r"(?:-\d+)?)+)$", re.IGNORECASE)
TODO_RENAME = U.TODO_RENAME
TODO_CAPTURE = U.TODO_CAPTURE
FOLDER_FILE = U.FOLDER_FILE
TODO_STACK = ("Beide markieren › Photo › Stacking › Group into Stack (Strg+G); die Fassung für die Galerie im Stapel "
              "anklicken › Photo › Stacking › Move to Top of Stack (Umschalt+S). Oder die überflüssige Fassung "
              "entfernen (Photo › Remove Photo…).")
GPS_REACH = timedelta(minutes=60)       # Foto ohne GPS gilt als "mit Spur", wenn ein Punkt so nah liegt
TODO_LOCATE = ("Bild anklicken › auf das Ausrufezeichen/Fragezeichen oben rechts an der Kachel klicken › Locate… › "
               "die Datei an ihrem neuen Ort auswählen (Häkchen „Find nearby missing photos“ findet die anderen mit)")


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


def norm(text):
    """Vergleichsform: klein, ohne Akzente/Umlaut-Punkte, nur Buchstaben und Ziffern."""
    text = unicodedata.normalize("NFKD", str(text).casefold().replace("ß", "ss"))
    return "".join(c for c in text if c.isalnum())


def slash(path):
    return str(path or "").replace("\\", "/")


def show(rel_posix):
    """'2006/2006-05-26 Paris/' -> Anzeige wie im Explorer '2006\\2006-05-26 Paris'"""
    return rel_posix.strip("/").replace("/", "\\") or "(Wurzelordner)"


def parse_time(value):
    """Lightroom speichert z. B. '2006-06-08T20:11:00', '…:00.368' oder '…+02:00' -> datetime (Ortszeit)."""
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Katalog lesen (nur die Kopie)

def read_catalog(db, cfg):
    q = lambda sql: db.execute(sql).fetchall()
    base = slash(cfg["originals_dir"]).rstrip("/").casefold() + "/"
    c = {"images": [], "outside": Counter(), "outside_path": {}}
    rows = q("""
        SELECT i.id_local AS id, i.captureTime AS captureTime, i.masterImage AS master, i.pick AS pick, i.rating AS rating,
               f.baseName AS baseName, f.extension AS extension, f.sidecarExtensions AS sidecars,
               fo.id_local AS folderId, fo.pathFromRoot AS pathFromRoot,
               r.id_local AS rootId, r.absolutePath AS root, r.name AS rootName,
               s.stack AS stack, s.position AS position,
               e.hasGPS AS hasGPS, e.gpsLatitude AS lat, e.gpsLongitude AS lng, cm.value AS model,
               h.cityRef AS cityRef, ci.value AS cityName, co.value AS countryName,
               fp.lastFaceDetector AS faceDetector
        FROM Adobe_images i
        JOIN AgLibraryFile f ON f.id_local = i.rootFile
        JOIN AgLibraryFolder fo ON fo.id_local = f.folder
        JOIN AgLibraryRootFolder r ON r.id_local = fo.rootFolder
        LEFT JOIN AgLibraryFolderStackImage s ON s.image = i.id_local
        LEFT JOIN AgHarvestedExifMetadata e ON e.image = i.id_local
        LEFT JOIN AgInternedExifCameraModel cm ON cm.id_local = e.cameraModelRef
        LEFT JOIN AgHarvestedIptcMetadata h ON h.image = i.id_local
        LEFT JOIN AgInternedIptcCity ci ON ci.id_local = h.cityRef
        LEFT JOIN AgInternedIptcCountry co ON co.id_local = h.countryRef
        LEFT JOIN Adobe_libraryImageFaceProcessHistory fp ON fp.image = i.id_local""")
    ok_ids = {r[0] for r in q("""SELECT ki.image FROM AgLibraryKeywordImage ki
                                 JOIN AgLibraryKeyword k ON k.id_local = ki.tag
                                 WHERE LOWER(k.name) = 'location-ok'""")}
    for r in rows:
        root = slash(r["root"])
        if not (root.casefold() + "/").replace("//", "/").startswith(base):
            c["outside"][r["rootId"]] += 1
            c["outside_path"][r["rootId"]] = (r["rootName"], root)
            continue
        # Pfad relativ zu D:\Bilder - Raw (falls die Wurzel ein Unterordner davon ist)
        rel_root = root[len(base):] if len(root) >= len(base) else ""
        rel = (rel_root.strip("/") + "/" if rel_root.strip("/") else "") + (r["pathFromRoot"] or "")
        parts = [p for p in rel.split("/") if p]
        ext = (r["extension"] or "").lower()
        img = {
            "id": r["id"], "time": parse_time(r["captureTime"]), "raw_time": r["captureTime"],
            "master": r["master"], "pick": r["pick"] or 0, "rating": int(r["rating"] or 0),
            "base": r["baseName"] or "", "ext": ext,
            "file": (r["baseName"] or "") + (f".{r['extension']}" if r["extension"] else ""),
            "sidecars": [s.strip().lower() for s in (r["sidecars"] or "").split(",") if s.strip()],
            "folder": "/".join(parts), "parts": parts,
            "hidden": any(p.startswith("_") for p in parts),
            "stack": r["stack"], "position": r["position"],
            "gps": bool(r["hasGPS"]), "lat": r["lat"], "lng": r["lng"],
            "model": r["model"] or "(unbekannt)",
            "place": ", ".join(x for x in (r["cityName"], r["countryName"]) if x), "city": r["cityRef"] is not None, "ok": r["id"] in ok_ids,
            "scanned": r["faceDetector"] is not None,
        }
        # In der Galerie landet: nicht in einem _-Ordner und im Stapel oben (bzw. gar nicht gestapelt)
        img["gallery"] = not img["hidden"] and (img["stack"] is None or (img["position"] or 1) <= 1)
        c["images"].append(img)

    # Gesichter: bestaetigt (userPick = 1), nur Vorschlag, ohne Namen
    c["faces"] = defaultdict(Counter)
    for r in q("""SELECT f.image AS image, MAX(COALESCE(kf.userPick, 0)) AS confirmed, COUNT(kf.id_local) AS links
                  FROM AgLibraryFace f LEFT JOIN AgLibraryKeywordFace kf ON kf.face = f.id_local
                  GROUP BY f.id_local"""):
        kind = "confirmed" if r["confirmed"] == 1 else ("suggested" if r["links"] else "unnamed")
        c["faces"][r["image"]][kind] += 1

    # Stichwoerter
    root_tag = q("SELECT value FROM Adobe_variablesTable WHERE name = 'AgLibraryKeyword_rootTagID'")
    root_id = int(float(root_tag[0]["value"])) if root_tag and root_tag[0]["value"] else None
    kws = q("""SELECT k.id_local AS id, k.name AS name, k.parent AS parent, k.keywordType AS type,
                      k.includeOnExport AS export,
                      (SELECT COUNT(*) FROM AgLibraryKeywordImage ki WHERE ki.tag = k.id_local) AS n,
                      (SELECT COUNT(*) FROM AgLibraryKeyword c WHERE c.parent = k.id_local) AS children
               FROM AgLibraryKeyword k""")
    names = {k["id"]: k["name"] for k in kws}
    c["keywords"] = [{"id": k["id"], "name": k["name"], "person": k["type"] == "person", "n": k["n"],
                      "children": k["children"], "export": k["export"] != 0,
                      "parent": names.get(k["parent"]) if k["parent"] not in (None, root_id) else None}
                     for k in kws if k["id"] != root_id and k["name"] is not None]

    # Ortsnamen je Feld mit Anzahl Bilder
    c["places"] = {}
    for label, table, col in (("Land", "AgInternedIptcCountry", "countryRef"),
                              ("Bundesland", "AgInternedIptcState", "stateRef"),
                              ("Stadt", "AgInternedIptcCity", "cityRef"),
                              ("Ort", "AgInternedIptcLocation", "locationRef")):
        c["places"][label] = [(r["value"], r["n"]) for r in q(
            f"""SELECT v.value AS value, COUNT(h.id_local) AS n FROM {table} v
                JOIN AgHarvestedIptcMetadata h ON h.{col} = v.id_local GROUP BY v.id_local""")]
    return c


# ---------------------------------------------------------------- Platte (nur Dateinamen)

def scan_disk(originals):
    """Alle Bilddateien unter D:\\Bilder - Raw: relativer Pfad (klein) -> (Ordner, Dateiname). Nur Verzeichnislisten."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(originals):
        dirnames[:] = [d for d in dirnames if d.casefold() not in U.SKIP_DIRS
                       and not d.casefold().endswith(".lrdata") and not d.startswith(".")]
        rel = slash(os.path.relpath(dirpath, originals))
        rel = "" if rel == "." else rel
        for name in filenames:
            if os.path.splitext(name)[1].casefold() in U.IMAGE_EXT:
                files[f"{rel}/{name}".lstrip("/").casefold()] = (rel, name)
    return files


# ---------------------------------------------------------------- Pruefungen

def add(tasks, folder, kind, file, when, problem, todo):
    tasks[folder].append((kind, file, when, problem, todo))


def nice(dt):
    return f"{dt:%d.%m.%Y %H:%M:%S}" if dt else ""


def check_all(c, disk, now):
    tasks = defaultdict(list)
    images = c["images"]
    gallery = [i for i in images if i["gallery"]]
    by_folder = defaultdict(list)
    for i in gallery:
        by_folder[i["folder"]].append(i)

    # --- Ordner: Aufbau und doppelte Namen (wie bisher in der Uebersicht)
    struct = {"structure": []}
    folders = sorted({i["folder"] for i in images if not i["hidden"] and i["folder"]})
    seen_paths = set()
    for folder in folders:
        parts = folder.split("/")
        for depth in range(1, len(parts) + 1):     # auch die Ordner darueber (z. B. Sammelordner)
            sub = "/".join(parts[:depth])
            if sub not in seen_paths:
                seen_paths.add(sub)
                U.check_folder(struct, Path(*parts[:depth]))
    for rel, problem, todo in struct["structure"]:
        add(tasks, slash(rel), "Ordner", FOLDER_FILE, "", problem, f"{todo} ({TODO_RENAME} oder per Ziehen verschieben)")
    names = defaultdict(set)
    for folder in by_folder:
        names[folder.split("/")[-1].casefold()].add(folder)
    for rels in names.values():
        if len(rels) > 1:
            for rel in rels:
                others = ", ".join(show(x) for x in sorted(rels) if x != rel)
                add(tasks, rel, "Ordnername doppelt", FOLDER_FILE, "",
                    f"gleicher Ordnername auch in: {others} – online würden beide zusammengelegt",
                    f"einen der Ordner eindeutig umbenennen: {TODO_RENAME}")

    # --- Aufnahmezeit: dieselben Regeln wie das Sync-Tool (Dateiname, wie Lightroom ihn exportieren wird)
    for i in gallery:
        folder_name = i["parts"][-1] if i["parts"] else "Bilder"
        if not i["time"]:
            add(tasks, i["folder"], "keine Aufnahmezeit", i["file"], "",
                "Bild hat keine Aufnahmezeit – der Export bekommt keinen gültigen Namen und wird nicht hochgeladen",
                TODO_CAPTURE)
            continue
        a = regeln.analyze_name(f"{folder_name}_{i['time']:%Y-%m-%d_%H-%M-%S}.jpg", now)
        for sev, text in a["problems"]:
            kind = U.SHORT_TYPE.get(U.problem_type(text))
            if kind == "Jahr passt nicht":
                todo = (f"Stimmt das Datum nicht: {TODO_CAPTURE}. Stimmt es doch: Zeitraum im Ordnernamen anpassen "
                        f"({TODO_RENAME}).")
            elif kind == "Datum unplausibel":
                todo = TODO_CAPTURE
            else:
                continue   # Ordner-Probleme stehen schon oben als Ordner-Aufgabe
            add(tasks, i["folder"], kind, i["file"], nice(i["time"]), text, todo)

    # --- zwei Fassungen / Stapel
    in_pair = set()
    stacks = defaultdict(list)
    for i in images:
        if i["stack"] is not None:
            stacks[i["stack"]].append(i)
    same_stack = lambda a, b: a["stack"] is not None and a["stack"] == b["stack"]
    for folder, items in by_folder.items():
        by_base = defaultdict(list)
        for i in items:
            by_base[i["base"].casefold()].append(i)
        for i in items:
            m = EDIT_RE.match(i["base"])
            if not m:
                continue
            for orig in by_base.get(m.group("base").casefold(), []):
                if not same_stack(i, orig):
                    in_pair.update((i["id"], orig["id"]))
                    add(tasks, folder, "2 Fassungen", f"{orig['file']} + {i['file']}", nice(orig["time"]),
                        "Original und Bearbeitung sind nicht gestapelt – beide kommen in die Galerie", TODO_STACK)
        # RAW und JPG (oder andere Endungen) mit gleichem Namen als zwei Kacheln
        for base, group in by_base.items():
            exts = {i["ext"] for i in group}
            if len(group) > 1 and len(exts) > 1 and not all(same_stack(group[0], g) for g in group[1:]):
                in_pair.update(i["id"] for i in group)
                add(tasks, folder, "2 Kacheln", " + ".join(sorted(i["file"] for i in group)), nice(group[0]["time"]),
                    "dasselbe Foto als zwei Dateien (z. B. RAW und JPG), beide sichtbar – beide kommen in die Galerie",
                    "Die überflüssige Kachel entfernen (Photo › Remove Photo…) oder beide stapeln: " + TODO_STACK)
    # Virtuelle Kopien, die nicht mit dem Original gestapelt sind
    by_id = {i["id"]: i for i in images}
    for i in gallery:
        orig = by_id.get(i["master"]) if i["master"] else None
        if orig and orig["gallery"] and not same_stack(i, orig):
            in_pair.update((i["id"], orig["id"]))
            add(tasks, i["folder"], "2 Fassungen", f"{orig['file']} (virtuelle Kopie)", nice(i["time"]),
                "Original und virtuelle Kopie sind nicht gestapelt – beide kommen in die Galerie", TODO_STACK)
    # Stapel, in dem die unbearbeitete Fassung oben liegt
    for members in stacks.values():
        top = min(members, key=lambda i: i["position"] or 1)
        if top["hidden"] or EDIT_RE.match(top["base"]):
            continue
        edits = [i for i in members if i is not top and (m := EDIT_RE.match(i["base"]))
                 and m.group("base").casefold() == top["base"].casefold()]
        if edits:
            add(tasks, top["folder"], "Stapel: Original oben", f"{top['file']} (oben) + {edits[0]['file']}",
                nice(top["time"]),
                "Im Stapel liegt das unbearbeitete Original oben – in die Galerie kommt das Original, nicht die "
                "Bearbeitung",
                "Gewollt: nichts tun. Sonst Stapel aufklappen (S), die Bearbeitung anklicken › Photo › Stacking › "
                "Move to Top of Stack (Umschalt+S)")

    # --- gleiche Aufnahmezeit (z. B. Scans mit Ersatzdatum) -> online zufaellige Reihenfolge
    same = defaultdict(list)
    for i in gallery:
        if i["time"] and i["id"] not in in_pair:
            same[(i["folder"], i["time"])].append(i)
    for (folder, when), group in same.items():
        if len(group) >= 2:
            add(tasks, folder, "gleiche Zeit", ", ".join(sorted(i["file"] for i in group)), nice(when),
                f"{len(group)} verschiedene Fotos mit genau derselben Aufnahmezeit – bei Scans meist ein Ersatzdatum; "
                "online ist die Reihenfolge dann zufällig",
                f"Serienbilder: nichts tun. Scans: je Foto {TODO_CAPTURE}")

    # --- abgelehnt markiert, aber sichtbar
    for i in gallery:
        if i["pick"] < 0:
            add(tasks, i["folder"], "abgelehnt", i["file"], nice(i["time"]),
                "als abgelehnt (X) markiert – beim Export mit Strg+A käme es trotzdem in die Galerie",
                "Entfernen (Photo › Remove Photo…) oder Markierung aufheben (Taste U)")

    # --- vom Handy geloeschte Bilder, die mit importiert wurden
    for i in images:
        if i["base"].startswith(".trashed-"):
            add(tasks, i["folder"], "gelöschtes Handybild", i["file"], nice(i["time"]),
                "vom Handy gelöschtes Bild (Papierkorb-Datei „.trashed-…“), trotzdem importiert",
                "Photo › Remove Photo… › „Delete from Disk“ (bzw. „Remove“, wenn die Datei bleiben soll)")

    # --- Katalog <-> Platte
    in_catalog = set()
    missing = []
    for i in images:
        key = f"{i['folder']}/{i['file']}".lstrip("/").casefold()
        in_catalog.add(key)
        for side in i["sidecars"]:
            in_catalog.add(f"{i['folder']}/{i['base']}.{side}".lstrip("/").casefold())
        if not i["master"] and key not in disk:
            missing.append(i)
    not_imported = {k: v for k, v in disk.items() if k not in in_catalog}
    where_now = defaultdict(list)                  # Dateiname -> Ordner, in denen er nicht importiert liegt
    for folder, name in not_imported.values():
        where_now[name.casefold()].append(folder)
    moved_names = set()
    for i in missing:
        places = where_now.get(i["file"].casefold(), [])
        if places:
            moved_names.add(i["file"].casefold())
            add(tasks, i["folder"], "Datei verschoben", i["file"], nice(i["time"]),
                f"Datei fehlt hier (Fragezeichen in Lightroom) – sie liegt jetzt in {show(places[0])} "
                "(außerhalb von Lightroom verschoben)", TODO_LOCATE)
        else:
            add(tasks, i["folder"], "Datei fehlt", i["file"], nice(i["time"]),
                "Datei ist nicht mehr auf der Platte (Fragezeichen in Lightroom)",
                f"Wurde sie umbenannt oder verschoben: {TODO_LOCATE}. Ist sie wirklich weg: Photo › Remove Photo…")
    hidden_not_imported = Counter()
    for folder, name in not_imported.values():
        if any(p.startswith("_") for p in folder.split("/")):
            hidden_not_imported[folder] += 1
            continue
        if name.casefold() in moved_names:
            continue   # steht schon als "Datei verschoben" beim alten Ordner
        add(tasks, folder, "nicht importiert", name, "",
            "Datei liegt im Ordner, ist aber nicht in Lightroom – kommt nie in die Galerie",
            "Folders-Panel: Rechtsklick auf den Ordner › Synchronize Folder… › „Import new photos“ › Synchronize")

    order = {"Ordner": 0, "Ordnername doppelt": 1, "Datei verschoben": 2, "Datei fehlt": 3, "nicht importiert": 4}
    for rows in tasks.values():
        rows.sort(key=lambda row: (order.get(row[0], 5), row[2][6:10] + row[2][3:5] + row[2][:2] + row[2][11:], row[1]))
    return tasks, hidden_not_imported


def folder_info(c):
    """Nur Info je Ordner (ohne _-Ordner): Gesichter und Orte."""
    info = defaultdict(Counter)
    for i in c["images"]:
        if i["hidden"]:
            continue
        st = info[i["folder"]]
        st["n"] += 1
        faces = c["faces"].get(i["id"], Counter())
        st["faces"] += sum(faces.values())
        st["confirmed"] += faces["confirmed"]
        st["suggested"] += faces["suggested"]
        st["unnamed"] += faces["unnamed"]
        st["unscanned"] += not i["scanned"]
        if i["gallery"]:
            st["g"] += 1
            st["nogps"] += not i["gps"] and not i["ok"]     # location-ok = bewusst ohne GPS, erledigt
            st["gpsok"] += not i["gps"] and i["ok"]
            st["nocity"] += i["gps"] and not i["city"]
    return info


def gps_reach(c, info):
    """Je Ordner: wie viele Fotos ohne GPS (ohne location-ok) haben einen Bezugspunkt <= 1 h daneben -
    einen Punkt der Google-Zeitachse oder ein Foto mit GPS (ganzer Katalog, z. B. Handyfotos)? Zusaetzlich:
    wie viele erst durch gefuellte Luecken (gleicher Ort davor und danach, wie in gps_test.fill_gaps).
    Dort lohnt sich gps_test.bat. Gibt Angaben zur Zeitachse zurueck (nur Anzahlen und Zeitraum)."""
    tl_info = {"files": [], "points": 0, "first": None, "last": None, "errors": []}
    tl_pts = []
    files = sorted(gps_test.GOOGLE_DIR.glob("*.json")) if gps_test.GOOGLE_DIR.is_dir() else []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as err:
            tl_info["errors"].append(f"{f.name}: nicht lesbar ({type(err).__name__})")
            continue
        pts, _ = gps_test.timeline_points(data)
        del data
        tl_info["files"].append(f.name)
        tl_pts += [(p[0], p[2], p[3]) for p in pts]
    tl_pts.sort()
    tl_times = [p[0] for p in tl_pts]
    if tl_times:
        tl_info.update(points=len(tl_times), first=tl_times[0], last=tl_times[-1])
    photo_pts = sorted((i["time"], i["lat"], i["lng"]) for i in c["images"]
                       if i["gps"] and i["time"] and i["lat"] is not None and i["lng"] is not None)
    photo_times = [p[0] for p in photo_pts]
    filled, _ = gps_test.fill_gaps(tl_pts + photo_pts)
    filled_times = [p[0] for p in filled]

    def near(times, t):
        gap = gps_test.nearest_gap(times, t)
        return gap is not None and gap <= GPS_REACH

    for i in c["images"]:
        if not i["gallery"] or i["gps"] or i["ok"] or not i["time"]:
            continue
        st = info[i["folder"]]
        by_tl, by_photo = near(tl_times, i["time"]), near(photo_times, i["time"])
        st["reach_tl"] += by_tl
        st["reach_photo"] += by_photo
        st["reach"] += by_tl or by_photo
        st["reach_gap"] += not (by_tl or by_photo) and near(filled_times, i["time"])
    return tl_info


def keyword_review(c, ignore):
    """Jedes Stichwort mit Empfehlung. Doppelte Namen (gleich bis auf Gross/klein, Akzente, Leerzeichen) zusammenfassen."""
    ignore = {k.casefold() for k in ignore}
    groups = defaultdict(list)
    for k in c["keywords"]:
        groups[norm(k["name"])].append(k)
    rows = []
    for k in c["keywords"]:
        dup = [x for x in groups[norm(k["name"])] if x is not k]
        if dup:
            advice = ("doppelt – zusammenführen (für die Galerie egal, sie behandelt gleiche Namen als eine Person)")
        elif k["n"] == 0 and not k["children"]:
            advice = "kann weg: Metadata › Purge Unused Keywords"
        elif k["name"].casefold() in ignore:
            advice = "Verwaltung – bleibt, die Galerie blendet es aus"
        elif k["children"]:
            advice = "Oberbegriff"
        else:
            advice = ""
        rows.append({**k, "advice": advice, "dup": bool(dup)})
    rows.sort(key=lambda k: (not k["dup"], norm(k["name"]), -k["n"]))
    dup_groups = [g for g in groups.values() if len(g) > 1]
    return rows, dup_groups


def place_variants(c):
    """Ortsnamen, die sich nur in Gross/klein, Akzenten oder Satzzeichen unterscheiden (z. B. Zurich/Zürich)."""
    out = []
    for label, values in c["places"].items():
        groups = defaultdict(list)
        for value, n in values:
            groups[norm(value)].append((value, n))
        out += [(label, sorted(g, key=lambda x: -x[1])) for g in groups.values() if len(g) > 1]
    return out


# ---------------------------------------------------------------- Seite

CSS_EXTRA = """
th.sort{cursor:pointer;white-space:nowrap}th.sort:after{content:" ↕";color:var(--muted)}
td.num,th.num{text-align:right}
details.task>summary>.t{min-width:min(260px,60%)}
.inner{overflow-x:auto}
.big{font-weight:600}
table.gpstab th.sort{white-space:normal;vertical-align:bottom;font-size:.8rem}
table.gpstab td:first-child{min-width:170px}
table.gpstab td:last-child{min-width:190px}
"""

JS = """
function openTasks(v){document.querySelectorAll('details.task').forEach(d=>d.open=v);}
function sortTable(th){const t=th.closest('table'),i=[...th.parentNode.children].indexOf(th),
rows=[...t.querySelectorAll('tr')].slice(1),dir=th.dataset.dir==='a'?'d':'a';th.dataset.dir=dir;
const val=r=>{const s=r.children[i].dataset.v??r.children[i].textContent;const n=parseFloat(s);return isNaN(n)?s.toLowerCase():n;};
rows.sort((a,b)=>{const x=val(a),y=val(b);return (x<y?-1:x>y?1:0)*(dir==='a'?1:-1);});rows.forEach(r=>t.appendChild(r));}
"""


def num(n, big=False):
    """Zahlenzelle; data-v = Rohwert zum Sortieren (Anzeige hat Tausenderpunkte)."""
    return f"<td class='num{' big' if big else ''}' data-v='{n}'>{U.fmt(n)}</td>"


def gps_section(w, info, tl_info):
    """Abschnitt "GPS nachtragen": je Ordner ohne GPS, location-ok, davon mit Spur, Empfehlung."""
    esc, fmt = U.esc, U.fmt
    rows = [(rel, st) for rel, st in info.items() if st["nogps"]]
    total = sum(st["nogps"] for _, st in rows)
    reach = sum(st["reach"] + st["reach_gap"] for _, st in rows)
    ok = sum(st["gpsok"] for st in info.values())
    w(f"<h2>GPS nachtragen ({fmt(total)} Bilder ohne GPS)</h2>")
    if tl_info["files"]:
        w(f"<div class='muted small'>Google-Zeitachse: {esc(', '.join(tl_info['files']))} · {fmt(tl_info['points'])} "
          f"Punkte von {tl_info['first']:%m/%Y} bis {tl_info['last']:%m/%Y}</div>")
    else:
        w("<div class='muted small'>Keine Google-Zeitachse in _sync\\google gefunden – gezählt werden nur Fotos mit "
          "GPS (z. B. Handyfotos).</div>")
    for err in tl_info["errors"]:
        w(f"<div class='warn'>{esc(err)}</div>")
    w(f"<div class='todo'>Ohne GPS zählt nur, was nicht mit <b style='color:inherit'>location-ok</b> markiert ist "
      f"({fmt(ok)} Bilder sind so markiert = erledigt). <b style='color:inherit'>Mit Spur</b> = ein Punkt der "
      "Zeitachse oder ein Foto mit GPS liegt höchstens 1 Stunde daneben; <b style='color:inherit'>+ über Lücke</b> = "
      "erst durch eine gefüllte Lücke (Punkt davor und danach am selben Ort, höchstens 3 h dazwischen). Dort lohnt "
      "sich <i>gps_test.bat</i> "
      f"(davon {fmt(reach)} Bilder). Ging die Kamera-Uhr falsch, stimmt die Zahl nur ungefähr; gps_test prüft die Uhr. "
      "Ohne Spur: im Map-Modul die Fotos markieren und auf den Ort ziehen (Ort oben bei <i>Search Map</i> suchen), "
      "oder Stichwort <i>location-ok</i> vergeben, wenn der Ort unbekannt ist.</div>")
    if not rows:
        w("<div class='none'>Alle Bilder haben GPS oder location-ok.</div>")
        return
    w("<details open><summary><span class='t'>Ordner mit Bildern ohne GPS</span></summary><div class='inner'>"
      "<table class='gpstab'>"
      "<tr><th class='sort' onclick='sortTable(this)'>Ordner in Lightroom</th>"
      "<th class='sort num' onclick='sortTable(this)'>ohne GPS</th>"
      "<th class='sort num' onclick='sortTable(this)'>mit Spur ≤ 1 h</th>"
      "<th class='sort num' onclick='sortTable(this)'>davon Zeitachse</th>"
      "<th class='sort num' onclick='sortTable(this)'>davon Foto mit GPS</th>"
      "<th class='sort num' onclick='sortTable(this)'>+ über Lücke</th>"
      "<th class='sort num' onclick='sortTable(this)'>location-ok</th>"
      "<th class='sort' onclick='sortTable(this)'>Vorschlag</th></tr>")
    for rel, st in sorted(rows, key=lambda x: (-x[1]["reach"] - x[1]["reach_gap"], -x[1]["nogps"], x[0].casefold())):
        name = rel.split("/")[-1] if rel else ""
        n = st["reach"] + st["reach_gap"]
        if n and n * 2 >= st["nogps"]:
            advice = f"gps_test.bat mit „{name}“"
        elif n:
            advice = f"gps_test.bat mit „{name}“, Rest von Hand"
        else:
            advice = "von Hand auf die Karte oder location-ok"
        w(f"<tr><td>{esc(show(rel))}</td>{num(st['nogps'], True)}{num(st['reach'])}{num(st['reach_tl'])}"
          f"{num(st['reach_photo'])}{num(st['reach_gap'])}{num(st['gpsok'])}<td>{esc(advice)}</td></tr>")
    w("</table></div></details>")


def build_page(cfg, catalog_path, c, tasks, hidden_not_imported, info, tl_info, kw_rows, dup_groups, variants,
               started):
    esc, fmt = U.esc, U.fmt
    task_total = sum(len(v) for v in tasks.values())
    tot = sum(info.values(), Counter())
    out = []
    w = out.append
    w("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>Fotoschatz Lightroom prüfen</title><style>{U.CSS}{CSS_EXTRA}</style><script>{JS}</script></head>"
      "<body><main>")
    w("<h1>Fotoschatz – was ist in Lightroom zu korrigieren?</h1>")
    w(f"<div class='muted small'>Stand {datetime.now():%d.%m.%Y %H:%M} · lightroom_pruefen.py v{__version__} · "
      f"Katalog: {esc(catalog_path.name)} (gelesen aus einer Kopie) · Originale: {esc(cfg['originals_dir'])} · "
      f"{time.time() - started:.0f} s</div>")

    w("<div class='cards'>")
    w(f"<div class='card'><b>{fmt(tot['n'])}</b><span>Bilder in Lightroom unter {esc(cfg['originals_dir'])} "
      f"(ohne _-Ordner), davon {fmt(tot['g'])} für die Galerie</span></div>")
    w(f"<div class='card'><b style='color:var(--warn)'>{fmt(task_total)}</b><span>Aufgaben in {fmt(len(tasks))} "
      "Ordnern</span></div>")
    w(f"<div class='card'><b>{fmt(tot['suggested'])}</b><span>Gesichter mit Namensvorschlag, noch nicht bestätigt"
      "</span></div>")
    w(f"<div class='card'><b class='muted'>{fmt(tot['unnamed'])}</b><span>Gesichter ohne Namen (oft Fremde)</span></div>")
    w(f"<div class='card'><b>{fmt(tot['nogps'])}</b><span>Bilder ohne GPS (ohne location-ok), davon "
      f"{fmt(tot['reach'] + tot['reach_gap'])} mit Spur – siehe „GPS nachtragen“</span></div>")
    w(f"<div class='card'><b class='muted'>{fmt(tot['nocity'])}</b><span>Bilder mit GPS, aber ohne Stadt</span></div>")
    w(f"<div class='card'><b class='muted'>{fmt(len(dup_groups))}</b><span>Stichwörter doppelt</span></div>")
    w("</div>")

    # ---- Aufgaben je Ordner
    w(f"<h2>Zu erledigen in Lightroom ({fmt(task_total)})</h2>")
    if not task_total:
        w("<div class='none'>Nichts zu tun.</div>")
    else:
        w("<div class='todo'><b>So gehst du vor:</b> 1. Ordner links im <i>Folders</i>-Panel öffnen (Pfad unter "
          f"{esc(cfg['originals_dir'])} wie angegeben). 2. Bild finden: <i>Library Filter › Text › Filename › contains</i>"
          " und den Dateinamen eintippen. 3. Ändern wie in der Spalte „Was tun“. 4. Danach den Ordner neu exportieren "
          "(<i>Photo › Stacking › Collapse All Stacks</i>, Strg+A, <i>Export</i>), dann sync.bat und aufraeumen.bat. "
          "<b style='color:inherit'>Alles nur in Lightroom ändern – nie im Explorer.</b> Zum Nachprüfen Lightroom "
          "schließen und dieses Tool noch einmal starten.</div>")
        w("<div class='tools'><button onclick=\"openTasks(true)\">Alle aufklappen</button>"
          "<button onclick=\"openTasks(false)\">Alle zuklappen</button></div>")
        for rel in sorted(tasks, key=str.casefold):
            rows = tasks[rel]
            kinds = Counter(kind for kind, *_ in rows)
            badges = " · ".join(f"{fmt(n)} {esc(k)}" for k, n in kinds.most_common())
            w(f"<details class='task'><summary><span class='t'>{esc(show(rel))}</span>"
              f"<span class='warn'>{badges}</span></summary><div class='inner'><table>"
              "<tr><th>Datei in Lightroom</th><th>Aufnahmezeit</th><th>Problem</th><th>Was tun in Lightroom</th></tr>")
            for kind, file, when, problem, todo in rows:
                w(f"<tr><td><b>{esc(file)}</b></td><td class='nowrap'>{esc(when)}</td><td>{esc(problem)}</td>"
                  f"<td>{esc(todo)}</td></tr>")
            w("</table></div></details>")

    # ---- Stichwoerter
    w(f"<h2>Stichwörter ({fmt(len(kw_rows))})</h2>")
    if dup_groups:
        w("<div class='todo'><b>Doppelte Namen zusammenführen</b> (nur für Ordnung in Lightroom – die Galerie behandelt "
          "gleiche Namen schon als eine Person): in der <i>Keyword List</i> beim Stichwort, das weg soll, auf den Pfeil "
          "rechts neben der Anzahl klicken (zeigt alle Bilder damit) › Strg+A › beim Stichwort, das bleibt, das Häkchen "
          "setzen › danach Rechtsklick auf das alte Stichwort › <i>Delete</i>. Behalten: das Personen-Stichwort "
          "(Art „Person“), sonst das mit mehr Bildern. ⚠ Vorher im Katalog „All Photographs“ wählen, damit alle Bilder "
          "erfasst sind.</div>")
    w("<details><summary><span class='t'>Alle Stichwörter mit Empfehlung</span></summary><div class='inner'><table>"
      "<tr><th class='sort' onclick='sortTable(this)'>Stichwort</th><th class='sort' onclick='sortTable(this)'>Art</th>"
      "<th class='sort' onclick='sortTable(this)'>unter</th><th class='sort num' onclick='sortTable(this)'>Bilder</th>"
      "<th class='sort' onclick='sortTable(this)'>Empfehlung</th></tr>")
    for k in kw_rows:
        kind = "Person" if k["person"] else "Stichwort"
        w(f"<tr><td><b>{esc(k['name'])}</b></td><td>{kind}</td><td>{esc(k['parent'] or '')}</td>"
          f"{num(k['n'])}<td{' class=warn' if k['dup'] else ''}>{esc(k['advice'])}</td></tr>")
    w("</table></div></details>")

    # ---- GPS nachtragen
    gps_section(w, info, tl_info)

    # ---- Personen und Orte je Ordner (nur Info)
    w("<h2>Personen und Orte je Ordner – nur Info</h2>")
    w("<div class='todo'>Für die Galerie zählen nur <b style='color:inherit'>bestätigte</b> Namen. Am meisten bringt es, "
      "offene Namensvorschläge zu bestätigen: Ordner öffnen › Taste <b style='color:inherit'>O</b> (<i>People</i>) › "
      "Doppelklick auf eine Person › unter <i>Similar</i> die passenden Gesichter markieren und nach oben zu "
      "<i>Confirmed</i> ziehen bzw. ✓ klicken. Gesichter ohne Namen sind oft Fremde – die kann man lassen. "
      "„GPS ohne Stadt“: Lightroom hat zu den Koordinaten keine Stadt gefunden; bei Bedarf im <i>Metadata</i>-Panel "
      "bei <i>City</i> eintragen. Spalten lassen sich per Klick sortieren. ⚠ Menü-Bezeichnungen am PC prüfen.</div>")
    w("<details open><summary><span class='t'>Tabelle je Ordner</span></summary><div class='inner'><table>"
      "<tr><th class='sort' onclick='sortTable(this)'>Ordner in Lightroom</th>"
      "<th class='sort num' onclick='sortTable(this)'>Bilder</th>"
      "<th class='sort num' onclick='sortTable(this)'>Vorschläge offen</th>"
      "<th class='sort num' onclick='sortTable(this)'>Gesichter ohne Namen</th>"
      "<th class='sort num' onclick='sortTable(this)'>bestätigt</th>"
      "<th class='sort num' onclick='sortTable(this)'>ohne Gesichtserkennung</th>"
      "<th class='sort num' onclick='sortTable(this)'>ohne GPS (ohne location-ok)</th>"
      "<th class='sort num' onclick='sortTable(this)'>GPS ohne Stadt</th></tr>")
    for rel, st in sorted(info.items(), key=lambda x: (-x[1]["suggested"], x[0].casefold())):
        w(f"<tr><td>{esc(show(rel))}</td>{num(st['n'])}{num(st['suggested'], bool(st['suggested']))}"
          f"{num(st['unnamed'])}{num(st['confirmed'])}{num(st['unscanned'])}{num(st['nogps'])}{num(st['nocity'])}</tr>")
    w("</table></div></details>")
    if variants:
        w("<details><summary><span class='t'>Ortsnamen in mehreren Schreibweisen "
          f"({fmt(len(variants))})</span></summary><div class='inner'>"
          "<div class='todo'>Gleicher Ort, unterschiedlich geschrieben – in der Suche erscheinen sie getrennt. "
          "Korrigieren: <i>Library Filter › Metadata</i>, Spalte <i>City</i> (bzw. Country/State/Location), die "
          "seltene Schreibweise wählen › Strg+A › im <i>Metadata</i>-Panel das Feld richtig schreiben.</div><table>"
          "<tr><th>Feld</th><th>Schreibweisen (Bilder)</th></tr>")
        for label, group in variants:
            w(f"<tr><td>{esc(label)}</td><td>{esc(' · '.join(f'{v} ({n})' for v, n in group))}</td></tr>")
        w("</table></div></details>")

    # ---- Weitere Angaben
    w("<h2>Weitere Angaben</h2>")
    if c["outside"]:
        w("<details><summary><span class='t'>Ordner außerhalb von "
          f"{esc(cfg['originals_dir'])} – werden nicht geprüft ({fmt(sum(c['outside'].values()))} Bilder)</span>"
          "</summary><div class='inner'><div class='todo'>Gibt es sie nicht mehr oder sollen sie nicht in den Katalog: "
          "<i>Folders</i>-Panel › Rechtsklick auf den obersten Ordner › <i>Remove…</i> (entfernt nur aus dem Katalog, "
          "nicht von der Platte; vorher eine Katalog-Sicherung machen). Sollen sie in die Galerie: im Folders-Panel "
          f"nach {esc(cfg['originals_dir'])} ziehen.</div><table><tr><th>Ordner</th><th>Bilder</th></tr>")
        for root_id, n in c["outside"].most_common():
            name, path = c["outside_path"][root_id]
            w(f"<tr><td>{esc(path)}</td><td class='num'>{fmt(n)}</td></tr>")
        w("</table></div></details>")
    hidden = Counter(i["folder"] for i in c["images"] if i["hidden"])
    w(f"<details><summary><span class='t'>_-Ordner (z. B. _Import) – bewusst nicht in der Galerie "
      f"({fmt(sum(hidden.values()))} Bilder)</span></summary><div class='inner'><table>"
      "<tr><th>Ordner</th><th>Bilder in Lightroom</th><th>Dateien nicht importiert</th></tr>")
    for rel in sorted(set(hidden) | set(hidden_not_imported), key=str.casefold):
        w(f"<tr><td>{esc(show(rel))}</td><td class='num'>{fmt(hidden[rel])}</td>"
          f"<td class='num'>{fmt(hidden_not_imported[rel])}</td></tr>")
    w("</table></div></details>")
    w("</main></body></html>")
    return "\n".join(out), task_total


def main():
    started = time.time()
    cfg = load_config()
    print(f"lightroom_pruefen.py v{__version__}")
    originals = Path(cfg["originals_dir"])
    if not originals.is_dir():
        fail(f"Originalordner nicht gefunden: {originals}")
    if U.inside(SCRIPT_DIR, originals):
        fail("Das Skript liegt im Originalordner - dort wird nichts geschrieben. Abbruch.")
    try:
        print("Kopiere den Lightroom-Katalog (nur lesen) ...")
        catalog_path, copy, db = katalog.prepare(cfg["catalog"], protected=[originals])
    except katalog.CatalogError as err:
        fail(str(err))
    print(f"  {catalog_path}")
    try:
        c = read_catalog(db, cfg)
    except Exception as err:   # Aufbau des Katalogs anders als erwartet
        fail(f"Katalog nicht lesbar ({type(err).__name__}: {err}). Bitte katalog_diagnose.bat laufen lassen und "
             "katalog_diagnose.txt an Claude schicken.")
    finally:
        db.close()
    print(f"  {len(c['images'])} Bilder unter {originals}")
    print(f"Lese Dateinamen unter {originals} ...")
    disk = scan_disk(originals)
    print(f"  {len(disk)} Bilddateien")

    tasks, hidden_not_imported = check_all(c, disk, datetime.now())
    info = folder_info(c)
    print("Lese Google-Zeitachse (falls vorhanden) ...")
    tl_info = gps_reach(c, info)
    print(f"  {tl_info['points']} Punkte" if tl_info["files"] else "  keine gefunden")
    kw_rows, dup_groups = keyword_review(c, cfg["ignore_keywords"])
    variants = place_variants(c)
    page, task_total = build_page(cfg, catalog_path, c, tasks, hidden_not_imported, info, tl_info, kw_rows,
                                  dup_groups, variants, started)
    OUT_FILE.write_text(page, encoding="utf-8")

    kinds = Counter(kind for rows in tasks.values() for kind, *_ in rows)
    print(f"\nAufgaben in Lightroom: {task_total} in {len(tasks)} Ordnern")
    for kind, n in kinds.most_common():
        print(f"  {n:6}  {kind}")
    print(f"Stichwoerter doppelt: {len(dup_groups)}")
    tot = sum(info.values(), Counter())
    print(f"Ohne GPS (ohne location-ok): {tot['nogps']}, davon mit Spur <= 1 h: {tot['reach']}, "
          f"dazu ueber gefuellte Luecken: {tot['reach_gap']}")
    print(f"\nErgebnis: {OUT_FILE}")
    if not U.open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")
        sys.exit(2)  # Fenster bleibt offen (lightroom_pruefen.bat)


if __name__ == "__main__":
    main()
