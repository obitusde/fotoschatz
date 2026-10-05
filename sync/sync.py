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

__version__ = "0.6.36"

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
BIRTHDAY_FILE = SCRIPT_DIR / "geburtstage.txt"     # bleibt auf dem PC (nicht im Repo)
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


def step(no, text):
    """Ueberschrift eines Arbeitsschritts mit kurzer Erklaerung (v0.6.32)."""
    log("")
    log(f"[{no}/6] {text}")


# ---------------------------------------------------------------- Fortschritt (v0.6.32)

def num(n):
    """3291 -> 3.291"""
    return f"{n:,}".replace(",", ".")


def bilder(n):
    """1 -> 1 Bild, 3291 -> 3.291 Bilder"""
    return f"{num(n)} Bild" if n == 1 else f"{num(n)} Bilder"


def size_text(b):
    if b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GB".replace(".", ",")
    if b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.0f} MB"
    return f"{max(1, round(b / 1024))} KB" if b else "0 KB"


def clock(seconds):
    """Dauer als m:ss bzw. h:mm:ss"""
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def remaining(seconds):
    if seconds < 60:
        return "unter 1 min"
    if seconds < 3600:
        return f"ca. {round(seconds / 60)} min"
    h, m = divmod(round(seconds / 60), 60)
    return f"ca. {h} h {m:02d} min"


class LiveLine:
    """Eine Zeile, die sich im Konsolenfenster laufend selbst ueberschreibt.
    Ins Protokoll (letzter_lauf.txt) kommt nur das Endergebnis. Ohne Konsole: hoechstens alle 30 s eine Zeile."""

    def __init__(self):
        self.live = sys.stdout.isatty()
        self.width = 0
        self.last = time.time()      # kurze Schritte zeigen gar keine Zwischenzeile

    def due(self):
        """True, wenn die Zeile wieder erneuert werden darf (Konsole: alle 0,5 s, sonst alle 30 s)."""
        now = time.time()
        if now - self.last < (0.5 if self.live else 30):
            return False
        self.last = now
        return True

    def show(self, text):
        if not self.due():
            return
        self.write(text)

    def write(self, text):
        if not self.live:
            print(text, flush=True)
            return
        cols = shutil.get_terminal_size((100, 25)).columns - 1
        text = text[:cols]
        sys.stdout.write("\r" + text.ljust(self.width))
        sys.stdout.flush()
        self.width = max(self.width, len(text))

    def clear(self):
        if self.live and self.width:
            sys.stdout.write("\r" + " " * self.width + "\r")
            sys.stdout.flush()
        self.width = 0

    def finish(self, text):
        self.clear()
        log(text)


class Progress:
    """Fortschritt mit Anzahl, Prozent, vergangener und geschaetzter Restzeit."""

    def __init__(self, label, total):
        self.label, self.total = label, total
        self.start = time.time()
        self.line = LiveLine()

    def update(self, done):
        if not self.line.due():
            return
        elapsed = time.time() - self.start
        pct = done * 100 // max(self.total, 1)
        text = f"    {self.label}: {num(done)} von {num(self.total)} ({pct} %) · {clock(elapsed)} vergangen"
        if 0 < done < self.total and elapsed >= 3:
            text += f" · noch {remaining(elapsed / done * (self.total - done))}"
        self.line.write(text)

    def finish(self, text=None):
        if text is None:
            text = f"    {self.label}: {bilder(self.total)} in {clock(time.time() - self.start)}"
        self.line.finish(text)

    def close(self):
        self.line.clear()


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

def build_index(files, analyses, ignore_keywords, birthdays=None):
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
        if meta.get("orig"):
            photo["o"] = meta["orig"]      # Originaldatei in Lightroom (v0.6.35, fuer die Bild-Infos in der App)
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
    index = {
        "v": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(photos),
        "folders": folder_list,
        "photos": photos,
    }
    # Geburtsdaten (v0.6.36): einmal je Person, fuer das Alter in den Bild-Infos der App.
    # Nur Personen, die auch auf Bildern vorkommen; Schluessel = Schreibweise wie in "p".
    bd = {}
    for photo in photos:
        for person in photo.get("p", []):
            date = (birthdays or {}).get(person.casefold())
            if date:
                bd[person] = date
    if bd:
        index["bd"] = dict(sorted(bd.items(), key=lambda x: x[0].casefold()))
    return index


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


BIRTHDAY_HEAD = [
    "# Fotoschatz Geburtstage - für das Alter der Personen in den Bild-Infos der App",
    "#",
    "# Eine Zeile je Person:   Name ; Geburtsdatum",
    "#   Datum als TT.MM.JJJJ (z. B. 12.03.1975) oder nur das Jahr (1975 -> App zeigt \"ca. 45\").",
    "#   Unbekannt -> leer lassen, dann zeigt die App kein Alter.",
    "#   Name genau wie in Lightroom (groß/klein egal). Alles hinter # ist nur Kommentar.",
    "# Neue Personen hängt sync.bat unten an (häufigste zuerst, Anzahl Bilder als Kommentar).",
    "# Nach dem Eintragen sync.bat starten - dann ist das Alter in der App zu sehen.",
    "# Die Datei bleibt auf deinem PC. Online stehen die Daten nur im geschützten index.json.",
    "",
]


def parse_birthday(text):
    """'12.03.1975', '12.3.1975', '1975-03-12' -> '1975-03-12'; '1975' -> '1975'; leer -> None; sonst ValueError."""
    text = text.strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        day, month, year = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if m:
            year, month, day = int(m[1]), int(m[2]), int(m[3])
        elif re.fullmatch(r"\d{4}", text):
            if not 1800 <= int(text) <= datetime.now().year:
                raise ValueError(text)
            return text
        else:
            raise ValueError(text)
    born = datetime(year, month, day)       # ValueError bei z. B. 31.02.
    if not 1800 <= year or born > datetime.now():
        raise ValueError(text)
    return born.strftime("%Y-%m-%d")


def update_birthday_file(person_counts):
    """geburtstage.txt lesen; fehlt sie, mit allen Personen anlegen, sonst neue Personen unten anhaengen.
    person_counts: Name -> Anzahl Bilder. Gibt (Geburtsdaten casefold -> Datum, Meldungen fuers Protokoll) zurueck."""
    notes = []
    text, encoding = "", "utf-8"
    created = not BIRTHDAY_FILE.exists()
    if not created:
        raw = BIRTHDAY_FILE.read_bytes()
        try:
            text, encoding = raw.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = raw.decode("cp1252"), "cp1252"      # mit dem Windows-Editor als ANSI gespeichert
        text = text.replace("\r\n", "\n").replace("\r", "\n")    # write_text macht unter Windows wieder \r\n daraus

    birthdays, listed, bad = {}, set(), []
    for no, line in enumerate(text.splitlines(), 1):
        content = line.split("#", 1)[0].strip()
        if not content:
            continue
        name, _, date = content.partition(";")
        name = " ".join(name.split())
        if not name:
            continue
        key = name.casefold()
        listed.add(key)
        try:
            value = parse_birthday(date)
        except ValueError:
            bad.append(f"Zeile {no}: '{date.strip()}'")      # ohne Namen, das Protokoll geht manchmal an Claude
            continue
        if value and key not in birthdays:
            birthdays[key] = value

    names = {}
    for name, count in person_counts.items():
        entry = names.setdefault(name.casefold(), [name, 0])
        entry[1] += count
    missing = sorted((v for k, v in names.items() if k not in listed), key=lambda x: (-x[1], x[0].casefold()))
    if missing:
        width = max(len(n) for n, _ in missing)
        lines = [f"{n:<{width}} ;              # {num(c)} {'Bild' if c == 1 else 'Bilder'}" for n, c in missing]
        if created:
            new_text = "\n".join(BIRTHDAY_HEAD + lines) + "\n"
        else:
            new_text = text + ("" if not text or text.endswith("\n") else "\n")
            new_text += f"\n# neu am {datetime.now():%d.%m.%Y} (sync.py)\n" + "\n".join(lines) + "\n"
        BIRTHDAY_FILE.write_text(new_text, encoding=encoding, errors="replace")

    with_date = sum(1 for k in names if k in birthdays)
    if created and missing:
        notes.append(f"    geburtstage.txt angelegt mit {num(len(missing))} Personen - Geburtsdaten eintragen,"
                     " dann zeigt die App das Alter")
    elif names:
        notes.append(f"    geburtstage.txt: {num(with_date)} von {num(len(names))} Personen mit Geburtsdatum"
                     " (für das Alter in der App)")
        if missing:
            notes.append(f"    {num(len(missing))} neue Personen unten angehängt - Geburtsdatum eintragen, wenn bekannt")
    for b in bad:
        notes.append(f"    geburtstage.txt {b} - Datum nicht verstanden (TT.MM.JJJJ oder JJJJ), wird ignoriert")
    return birthdays, notes


# ---------------------------------------------------------------- Upload

RCLONE_STATS = ["--use-json-log", "--stats", "2s", "--stats-log-level", "NOTICE"]


def rclone_line(label, st, kind):
    """Eigene deutsche Fortschrittszeile aus den rclone-Statistiken."""
    done, total = st.get("transfers", 0), st.get("totalTransfers", 0)
    if kind == "sync" and not total:
        return f"    {label}: {num(st.get('deletes', 0))} gelöscht · {num(st.get('checks', 0))} Dateien geprüft"
    if not total:
        return f"    {label}: prüfe, was schon online ist ({num(st.get('checks', 0))} Dateien)"
    b, tb = st.get("bytes", 0), st.get("totalBytes", 0)
    pct = b * 100 // tb if tb else done * 100 // total
    text = f"    {label}: {num(done)} von {num(total)} ({pct} %) · {size_text(b)} von {size_text(tb)}"
    speed = st.get("speed") or 0
    if speed >= 1024 ** 2:
        text += f" · {speed / 1024 ** 2:.0f} MB/s"
    elif speed:
        text += " · unter 1 MB/s"
    if st.get("eta") is not None and done < total:
        text += f" · noch {remaining(st['eta'])}"
    return text


def rclone_done(label, st, kind, seconds):
    done, deletes = st.get("transfers", 0), st.get("deletes", 0)
    if kind == "index":
        return f"    {label} hochgeladen – ab jetzt zeigt die App den neuen Stand"
    parts = []
    if done:
        parts.append(f"{num(done)} hochgeladen ({size_text(st.get('bytes', 0))})")
    if kind == "sync":
        parts.append(f"{num(deletes)} gelöscht" if deletes else "nichts zu löschen")
    if not parts:
        parts.append("nichts Neues – alles schon online")
    return f"    {label}: {', '.join(parts)} · in {clock(seconds)}"


def run_rclone(rclone, args, label, kind, prefix):
    """rclone starten. Statt der englischen rclone-Ausgabe erscheint eine deutsche Fortschrittszeile;
    Fehlermeldungen von rclone werden gezeigt (Praefix unkenntlich gemacht)."""
    started = time.time()
    line = LiveLine()
    stats = {}
    proc = subprocess.Popen([rclone] + args + RCLONE_STATS, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace")
    for raw in proc.stderr:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            entry = {"level": "error", "msg": raw}
        if "stats" in entry:
            stats = entry["stats"]
            line.show(rclone_line(label, stats, kind))
            continue
        msg = str(entry.get("msg", "")).strip()
        if not msg or "Config file" in msg and "not found" in msg:
            continue
        if entry.get("object"):
            msg = f"{entry['object']}: {msg}"
        line.clear()
        log(f"    rclone meldet: {msg.replace(prefix, '<Praefix>')}")
    proc.wait()
    if proc.returncode != 0:
        line.clear()
        fail(f"rclone meldet Fehler (Code {proc.returncode}), siehe Meldungen oben. Nichts ist verloren - "
             "beim nächsten Lauf wird der Upload wiederholt.")
    line.finish(rclone_done(label, stats, kind, time.time() - started))


def upload(cfg, prefix, staging):
    rclone = regeln.find_tool("rclone", "Installieren mit: winget install Rclone.Rclone")
    remote = f"{cfg['rclone_remote']}/{prefix}"
    common = ["--size-only", "--transfers", str(cfg["transfers"]), "--checkers", "16"]
    names = {"img": "große Bilder", "thumb": "Vorschaubilder"}

    log("    a) Neue Bilder hochladen (was schon online ist, wird übersprungen)")
    for sub in ("img", "thumb"):
        run_rclone(rclone, ["copy", str(staging / sub), f"{remote}/{sub}",
                            "--header-upload", CACHE_IMMUTABLE] + common, names[sub], "copy", prefix)
    log("    b) Inhaltsverzeichnis hochladen")
    run_rclone(rclone, ["copyto", str(staging / "index.json"), f"{remote}/index.json",
                        "--header-upload", CACHE_NO_CACHE, "--ignore-times"], "index.json", "index", prefix)
    log("    c) Alte Dateien online löschen (Bilder, die nicht mehr im Export-Ordner sind, und alte Fassungen)")
    for sub in ("img", "thumb"):
        run_rclone(rclone, ["sync", str(staging / sub), f"{remote}/{sub}",
                            "--header-upload", CACHE_IMMUTABLE,
                            "--max-delete", str(cfg["max_delete"])] + common, names[sub], "sync", prefix)


def confirm_deletions(removed, limit, dry):
    """Mehr Loeschungen als max_delete: Beispiele zeigen und nachfragen (v0.6.31, statt Abbruch).
    Schutz vor einem leeren oder falschen Export-Ordner bleibt: ohne "j" wird nichts geaendert."""
    log("")
    log(f"    ACHTUNG: {bilder(len(removed))} würden online gelöscht (Schutzgrenze max_delete = {limit}).")
    log("    Sie waren beim letzten Sync dabei und fehlen jetzt im Export-Ordner, z. B.:")
    for name in removed[:10]:
        log(f"      - {name}")
    if len(removed) > 10:
        log(f"      ... und {num(len(removed) - 10)} weitere")
    log("    Hinweis: Im Export-Ordner müssen ALLE Exporte bleiben - was dort fehlt, wird auch online gelöscht.")
    if dry:
        log("    Probelauf: beim echten Lauf (sync.bat) wird hier nachgefragt.")
        return
    if not (sys.stdin and sys.stdin.isatty()):
        fail("Keine Rückfrage möglich (kein Konsolenfenster). Bitte sync.bat per Doppelklick starten.")
    answer = input("    Ist der Export-Ordner vollständig und sollen diese Bilder online gelöscht werden? (j/n): ")
    if answer.strip().lower() not in ("j", "ja", "y", "yes"):
        fail("Abgebrochen - es wurde nichts hochgeladen und nichts gelöscht.")
    log(f"    OK - {bilder(len(removed))} werden online entfernt.")


# ---------------------------------------------------------------- Hauptablauf

def main():
    parser = argparse.ArgumentParser(description="Fotoschatz Sync-Tool")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts veraendern")
    args = parser.parse_args()
    dry = args.dry_run
    started = time.time()
    now = datetime.now()

    cfg = load_config()
    export_dir = Path(cfg["export_dir"])
    log(f"Fotoschatz Sync {__version__}  ({now:%d.%m.%Y %H:%M})"
        + ("  --  PROBELAUF: zeigt nur an, ändert nichts" if dry else ""))
    log(f"Bringt die Exporte aus {export_dir} in die Online-Galerie.")
    log("Online ist danach genau das, was im Export-Ordner liegt: Neues kommt dazu,")
    log("Geändertes wird ersetzt, was im Ordner fehlt, wird online gelöscht.")

    prefix = load_prefix(cfg["secrets_file"])
    work_dir = Path(cfg["work_dir"])
    staging = work_dir / "staging"
    state_file = work_dir / "state.json"
    log(f"Ziel: {cfg['rclone_remote']}/<Präfix, {len(prefix)} Zeichen>/")

    if not export_dir.is_dir():
        fail(f"Export-Ordner nicht gefunden: {export_dir}")
    jpgs = sorted((p for p in export_dir.iterdir() if regeln.is_jpg(p)), key=lambda p: p.name)
    if not jpgs:
        fail("Im Export-Ordner liegen keine JPGs. Zum Schutz vor dem Leeren des Buckets wird abgebrochen.")
    exiftool = regeln.find_exiftool()
    state = load_state(state_file)
    old_files = state["files"]
    first_run = not old_files

    # 1. Dateinamen pruefen und Aenderungen erkennen
    step(1, "Exporte prüfen: Dateinamen lesen und mit dem letzten Lauf vergleichen")
    analyses = {p.name: regeln.analyze_name(p.name, now) for p in jpgs}
    ok_paths = [p for p in jpgs if not regeln.is_severe(analyses[p.name]["problems"])]
    severe_paths = [p for p in jpgs if regeln.is_severe(analyses[p.name]["problems"])]

    new_files = {}
    to_process = []
    to_refresh = []
    counts = Counter()
    progress = Progress("Exporte vergleichen", len(ok_paths))
    for i, path in enumerate(ok_paths, 1):
        progress.update(i)
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
    progress.close()
    removed = sorted(name for name in old_files if name not in {p.name for p in ok_paths})
    n_new = sum(1 for t in to_process if t[3] == "neu")
    n_repl = len(to_process) - n_new

    log(f"    {num(len(jpgs))} Exporte im Ordner")
    log(f"    {num(n_new)} neu · {num(n_repl)} geändert (werden ersetzt) · {num(counts['unveraendert'])} unverändert"
        f" · {num(len(removed))} nicht mehr im Ordner (werden online gelöscht)")
    if severe_paths:
        log(f"    {num(len(severe_paths))} mit unbrauchbarem Dateinamen - werden nicht hochgeladen (siehe korrekturen.csv)")
    if to_refresh:
        log(f"    {num(len(to_refresh))} unveränderte Bilder: Infos werden neu gelesen (neues Format, kein neuer Bild-Upload)")

    if len(removed) > cfg["max_delete"]:
        confirm_deletions(removed, cfg["max_delete"], dry)
        cfg["max_delete"] = len(removed)      # nur fuer diesen Lauf (auch fuer rclone --max-delete)

    # 2. Metadaten der neuen/geaenderten (und der SCHWER-Bilder fuer die Tabelle)
    step(2, "Infos aus den Bildern lesen (Personen, Ort, GPS, Beschreibung) - nur neue und geänderte")
    exif_paths = [t[0] for t in to_process] + to_refresh + severe_paths
    exif = {}
    if exif_paths:
        progress = Progress("Infos lesen", len(exif_paths))
        exif = regeln.read_exif(exiftool, exif_paths, progress=lambda done, total: progress.update(done))
        progress.finish()
    else:
        log("    nichts zu tun")
    refreshed = 0
    for path in to_refresh:
        entry = exif.get(path.name)
        if entry:
            new_files[path.name] = dict(new_files[path.name], meta=regeln.extract_metadata(entry), mv=META_VERSION)
            refreshed += 1

    # 3. Verarbeiten
    step(3, "Vorschaubilder erstellen (kleine Bilder fürs Raster in der App), große Bilder bereitlegen")
    if not dry:
        for sub in ("img", "thumb"):
            (staging / sub).mkdir(parents=True, exist_ok=True)
    known_ids = {rec["id"]: name for name, rec in new_files.items()}
    unreadable = {}
    progress = Progress("Vorschaubilder", len(to_process))
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
            progress.update(i)
        new_files[path.name] = rec
    if dry:
        log("    Probelauf: übersprungen")
    elif to_process:
        progress.finish()
    else:
        log("    nichts zu tun")
    if unreadable:
        log(f"    {bilder(len(unreadable))} nicht lesbar - werden nicht hochgeladen (siehe korrekturen.csv)")
    counts["neu"] = sum(1 for t in to_process if t[3] == "neu" and t[0].name not in unreadable)
    counts["ersetzt"] = sum(1 for t in to_process if t[3] == "ersetzt" and t[0].name not in unreadable)

    # 4. Hinweise aus den Metadaten, neue Stichwoerter, Korrektur-Tabelle
    step(4, "Prüfliste schreiben: was in Lightroom zu verbessern ist")
    keyword_counter = Counter()
    person_counter = Counter()
    for name, rec in new_files.items():
        analyses[name]["problems"] += regeln.metadata_problems(rec["meta"])
        keyword_counter.update(rec["meta"].get("kw", []))
        person_counter.update(rec["meta"].get("p", []))
    all_persons = set(person_counter)
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
    log(f"    korrekturen.csv: {bilder(severe_total)} schwer (nicht hochgeladen),"
        f" {num(hint_total)} mit Hinweis (trotzdem hochgeladen, z. B. ohne GPS)")
    log("    stichwoerter.txt und orte.txt aktualisiert")
    birthdays, birthday_notes = update_birthday_file(person_counter)
    for line in birthday_notes:
        log(line)

    if dry:
        step(5, "Inhaltsverzeichnis für die App - im Probelauf übersprungen")
        step(6, "Hochladen - im Probelauf übersprungen")
        if removed:
            log("    Würde online entfernen:")
            for name in removed[:20]:
                log(f"      - {name}")
            if len(removed) > 20:
                log(f"      ... und {num(len(removed) - 20)} weitere")
        summary(counts, removed, severe_total, hint_total, rows, started, dry=True)
        return

    for name in unreadable:
        new_files.pop(name, None)

    # 5. Staging aufraeumen und vervollstaendigen, index.json
    step(5, "Inhaltsverzeichnis für die App bauen (index.json: alle Bilder mit Datum, Ort, Personen)")
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

    index = build_index(new_files, analyses, cfg["ignore_keywords"], birthdays)
    index_changed = True     # Inhalt anders als beim letzten Mal (z. B. neues Feld) -> index.json neu hochladen
    try:
        old_index = json.loads((staging / "index.json").read_text(encoding="utf-8"))
        index_changed = (old_index.get("photos") != index["photos"] or old_index.get("folders") != index["folders"]
                         or old_index.get("bd") != index.get("bd"))
    except (OSError, ValueError):
        pass
    write_json_atomic(staging / "index.json", index, compact=True)
    index_kb = (staging / "index.json").stat().st_size / 1024
    log(f"    {bilder(index['count'])} in {num(len(index['folders']))} Ordnern · {index_kb:,.0f} KB".replace(",", "."))

    changed = counts["neu"] or counts["ersetzt"] or removed or refreshed or index_changed
    state = {
        "tool_version": __version__,
        "files": new_files,
        "known_keywords": sorted(set(state.get("known_keywords", [])) | set(keyword_counter)),
        "upload_pending": bool(state.get("upload_pending") or changed or first_run),
    }
    write_json_atomic(state_file, state)

    # 6. Upload
    uploaded = False
    if state["upload_pending"]:
        step(6, "Hochladen zu Cloudflare R2 (Online-Speicher der Galerie)")
        upload(cfg, prefix, staging)
        state["upload_pending"] = False
        write_json_atomic(state_file, state)
        uploaded = True
    else:
        step(6, "Hochladen - nicht nötig, online ist schon alles aktuell")

    summary(counts, removed, severe_total, hint_total, rows, started, uploaded=uploaded, index=index)


def summary(counts, removed, severe_total, hint_total, rows, started, uploaded=False, dry=False, index=None):
    log("")
    took = clock(time.time() - started)
    if dry:
        log(f"=== Probelauf fertig nach {took} - nichts wurde verändert ===")
        log(f"Beim echten Lauf: {num(counts['neu'])} neu · {num(counts['ersetzt'])} ersetzt"
            f" · {num(len(removed))} gelöscht · {num(counts['unveraendert'])} unverändert")
    else:
        log(f"=== Fertig nach {took} ===")
        if index is not None:
            log(f"Online jetzt: {bilder(index['count'])} in {num(len(index['folders']))} Ordnern"
                + ("" if uploaded else " (unverändert)"))
        log(f"Dieser Lauf: {num(counts['neu'])} neu · {num(counts['ersetzt'])} ersetzt"
            f" · {num(len(removed))} gelöscht · {num(counts['unveraendert'])} unverändert")
    log(f"Nicht hochgeladen (Dateiname oder Bild unbrauchbar): {num(severe_total)}")
    log(f"Mit Hinweis (trotzdem hochgeladen): {num(hint_total)}")
    if rows:
        log(f"-> In Lightroom verbessern: {CSV_FILE} ({num(len(rows))} Zeilen, mit Excel öffnen)")
    log(f"Protokoll: {LOG_FILE}  ·  Sync-Version {__version__}")
    write_log()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    main()
