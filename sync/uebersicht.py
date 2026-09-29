#!/usr/bin/env python3
"""Fotoschatz - Uebersicht: Was ist auf der Platte, was exportiert, was online?

Vergleicht drei Staende und schreibt eine aufklappbare Seite uebersicht.html
(neben diesem Skript, wird nicht hochgeladen):
  Originale   D:\\Bilder - Raw    (nur Datei- und Ordnernamen - es wird dort NICHTS geschrieben oder geoeffnet)
  Exporte     D:\\Fotoschatz       (Name der Originaldatei aus den Metadaten)
  Online      _sync\\work\\state.json (Stand des letzten erfolgreichen Syncs)

Aufruf: uebersicht.bat (Doppelklick) oder python uebersicht.py
Optional in config.local.json: "originals_dir": "D:\\\\Bilder - Raw"
"""

__version__ = "0.6.5"

import html
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import regeln

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "uebersicht.html"

DEFAULTS = {
    "export_dir": str(SCRIPT_DIR.parent),
    "work_dir": str(SCRIPT_DIR / "work"),
    "originals_dir": r"D:\Bilder - Raw",
}

RAW_EXT = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2", ".raf",
           ".dng", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mef", ".mos", ".mrw", ".rwl", ".iiq"}
IMAGE_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".png", ".psd", ".webp", ".gif", ".bmp"} | RAW_EXT
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mts", ".m2ts", ".m4v", ".3gp", ".mpg", ".mpeg", ".wmv", ".mkv"}
SKIP_DIRS = {"$recycle.bin", "system volume information"}


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
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- Originale (nur lesen)

def scan_originals(root):
    """Liest nur Verzeichnisse (Namen, Groessen). Bild = Ordner + Dateiname ohne Endung
    (RAW und JPG mit gleichem Namen zaehlen als ein Bild)."""
    folders = {}        # Ordnername (klein) -> {"name", "rel", "images": {stamm_klein: {"stem", "ext": set}}}
    duplicates = defaultdict(set)
    skipped = Counter()  # _Import usw.: Anzahl Bilder
    videos = Counter()   # Ordnername -> Anzahl Videos
    ext_count = Counter()
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
            ext_count[ext or "(ohne)"] += 1
            if current == str(root):
                continue  # Dateien direkt im Wurzelordner gehoeren zu keinem Lightroom-Ordner
            if ext in VIDEO_EXT:
                videos[str(rel)] += 1
                continue
            if ext not in IMAGE_EXT:
                continue
            if hidden:
                skipped[str(rel)] += 1
                continue
            key = rel.name.casefold()
            folder = folders.get(key)
            if folder is None:
                folder = folders[key] = {"name": rel.name, "rel": str(rel), "images": {}}
            elif folder["rel"] != str(rel):
                duplicates[rel.name].update({folder["rel"], str(rel)})
            stem = os.path.splitext(entry.name)[0]
            image = folder["images"].setdefault(stem.casefold(), {"stem": stem, "ext": set()})
            image["ext"].add(ext)
    return folders, duplicates, skipped, videos, ext_count


# ---------------------------------------------------------------- Exporte und Online-Stand

def scan_exports(export_dir, state):
    """Je Export: Lightroom-Ordner, Originaldatei (aus state.json oder exiftool), online ja/nein."""
    files = state.get("files", {})
    pending = bool(state.get("upload_pending"))
    exports = []
    need_exif = []
    for path in sorted(p for p in Path(export_dir).iterdir() if regeln.is_jpg(p)):
        a = regeln.analyze_name(path.name, datetime.now())
        stat = path.stat()
        rec = files.get(path.name)
        synced = bool(rec and rec.get("size") == stat.st_size and rec.get("mtime_ns") == stat.st_mtime_ns)
        e = {
            "file": path.name,
            "folder": a["lr_folder"],
            "stamp": a["taken"].strftime("%Y-%m-%d_%H-%M-%S") if a["taken"] else "",
            "severe": regeln.is_severe(a["problems"]),
            "online": synced and not pending,
            "orig": (rec or {}).get("meta", {}).get("orig", "") if synced else "",
        }
        if not e["orig"] and not e["severe"]:
            need_exif.append(path)
        exports.append(e)
    if need_exif:
        print(f"  Lese Originalnamen aus {len(need_exif)} noch nicht synchronisierten Exporten (exiftool) ...")
        try:
            exif = regeln.read_exif(regeln.find_exiftool(), need_exif,
                                    progress=lambda done, total: print(f"    {done}/{total}"))
        except SystemExit:
            exif = {}
            print("  Hinweis: exiftool nicht verfuegbar - Zuordnung nur ueber die Aufnahmezeit.")
        by_name = {e["file"]: e for e in exports}
        for name, entry in exif.items():
            if name in by_name:
                by_name[name]["orig"] = regeln.extract_metadata(entry).get("orig", "")
    return exports


def match(folders, exports):
    """Ordnet jeden Export einem Original zu: Ordnername + Originaldatei ohne Endung,
    ersatzweise Aufnahmezeit = Dateiname des Originals (bei dir so benannt)."""
    status = {}  # (ordner_klein, stamm_klein) -> "online" | "exportiert"
    orphans = []
    for e in exports:
        if e["severe"]:
            orphans.append((e, "Dateiname passt nicht zum Muster - wird nicht hochgeladen"))
            continue
        folder = folders.get(e["folder"].casefold())
        candidates = []
        if e["orig"]:
            candidates.append(os.path.splitext(e["orig"])[0].casefold())
        if e["stamp"]:
            candidates.append(e["stamp"].casefold())
        hit = None
        if folder:
            hit = next((c for c in candidates if c in folder["images"]), None)
        if hit is None:
            reason = "Lightroom-Ordner nicht gefunden" if not folder else "Originaldatei nicht gefunden"
            orphans.append((e, reason))
            continue
        key = (e["folder"].casefold(), hit)
        if e["online"] or status.get(key) != "online":
            status[key] = "online" if e["online"] else status.get(key, "exportiert")
    return status, orphans


# ---------------------------------------------------------------- Seite

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1d21;--muted:#5f6570;--line:#e2e5ea;--ok:#1e8e3e;--wait:#c58a00;
--part:#e8710a;--none:#c5221f;--bar:#e3e6eb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--text:#e8eaed;--muted:#9aa0a6;--line:#262a31;
--ok:#5bb974;--wait:#fdd663;--part:#fcad70;--none:#f28b82;--bar:#262a31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:1.4rem;margin:0 0 4px}
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
table{border-collapse:collapse;font-size:.85rem;margin:6px 0}td,th{padding:3px 10px;border-bottom:1px solid var(--line);text-align:left}
.hide-done .done{display:none}
.legend span{margin-right:14px;white-space:nowrap}
"""

JS = """
function setFilter(open){document.body.classList.toggle('hide-done',open);
document.getElementById('f-all').classList.toggle('on',!open);document.getElementById('f-open').classList.toggle('on',open);}
function openAll(v){document.querySelectorAll('details.year').forEach(d=>d.open=v);}
"""

LABEL = {"ok": "komplett online", "wait": "exportiert, Sync fehlt", "part": "teilweise exportiert", "none": "nicht exportiert"}


def esc(text):
    return html.escape(str(text))


def fmt(n):
    return f"{n:,}".replace(",", ".")


def bar(ok, wait, part, total):
    if not total:
        return '<div class="bar"></div>'
    parts = [(ok, "i-ok"), (wait, "i-wait"), (part, "i-none")]
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


def build_page(cfg, folders, duplicates, skipped, videos, ext_count, status, orphans, started):
    years = defaultdict(list)
    totals = Counter()
    for key, folder in folders.items():
        images = folder["images"]
        n = len(images)
        online = sum(1 for stem in images if status.get((key, stem)) == "online")
        exported = sum(1 for stem in images if (key, stem) in status)
        missing = sorted((img for stem, img in images.items() if (key, stem) not in status),
                         key=lambda img: img["stem"].casefold())
        state = folder_state(n, exported, online)
        year = folder["rel"].split(os.sep)[0][:4] if folder["rel"][:4].isdigit() else "ohne Jahr"
        years[year].append({"name": folder["name"], "rel": folder["rel"], "n": n, "exp": exported,
                            "online": online, "missing": missing, "state": state})
        totals["n"] += n
        totals["online"] += online
        totals["wait"] += exported - online
        totals["none"] += n - exported

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
    w("</div>")
    w(bar(totals["online"], totals["wait"], totals["none"], n))
    w("<div class='tools'>"
      "<button id='f-all' class='on' onclick='setFilter(false)'>Alle Ordner</button>"
      "<button id='f-open' onclick='setFilter(true)'>Nur offene</button>"
      "<button onclick='openAll(true)'>Alle Jahre aufklappen</button>"
      "<button onclick='openAll(false)'>Alle zuklappen</button></div>")
    w("<div class='legend small muted'>"
      + "".join(f"<span><i class='dot s-{k}'></i>{v}</span>" for k, v in LABEL.items()) + "</div>")

    for year in sorted(years, reverse=True):
        items = sorted(years[year], key=lambda f: f["rel"].casefold(), reverse=True)
        items.sort(key=lambda f: f["rel"] == year)  # lose Bilder ans Ende des Jahres
        y = Counter()
        for f in items:
            y["n"] += f["n"]
            y["online"] += f["online"]
            y["wait"] += f["exp"] - f["online"]
            y[f["state"]] += 1
        done = " done" if all(f["state"] == "ok" for f in items) else ""
        states = " · ".join(f"<i class='dot s-{k}'></i>{y[k]}" for k in LABEL if y[k])
        w(f"<details class='year{done}'><summary><span class='t'>{esc(year)}</span><span class='row'>"
          f"<span class='nums'>{fmt(y['n'])} Bilder · {fmt(y['online'])} online · Ordner: {states}</span>"
          f"{bar(y['online'], y['wait'], y['n'] - y['online'] - y['wait'], y['n'])}</span></summary><div class='inner'>")
        for f in items:
            name = f["name"] if f["rel"] != year else f"{f['name']} (lose Bilder → „{year} Weitere Bilder“)"
            nums = f"{fmt(f['n'])} Bilder · {fmt(f['exp'])} exportiert · {fmt(f['online'])} online"
            head = f"<span><i class='dot s-{f['state']}'></i>{esc(name)}</span><span class='nums'>{nums}</span>"
            cls = " done" if f["state"] == "ok" else ""
            if not f["missing"]:
                w(f"<div class='plain{cls}'>{head}</div>")
                continue
            w(f"<details class='folder{cls}'><summary>{head}</summary><div class='inner'>")
            w(f"<div class='small muted'>Nicht exportiert ({fmt(len(f['missing']))}) – Ordner in Lightroom: "
              f"{esc(f['rel'])}</div><ul class='files'>")
            for img in f["missing"]:
                w(f"<li>{esc(img['stem'])} <span class='muted'>{esc(' + '.join(sorted(e.lstrip('.').upper() for e in img['ext'])))}</span></li>")
            w("</ul></div></details>")
        w("</div></details>")

    w("<h2 style='font-size:1.05rem;margin-top:28px'>Weitere Angaben</h2>")
    if orphans:
        w(f"<details><summary><span class='t'>Exporte ohne passendes Original ({fmt(len(orphans))})</span></summary>"
          "<div class='inner small muted'>Meist: Ordner oder Datei in Lightroom umbenannt oder gelöscht – "
          "dann den alten Export in D:\\Fotoschatz löschen und neu exportieren.</div><div class='inner'><table>"
          "<tr><th>Exportdatei</th><th>Originaldatei</th><th>online</th><th>Grund</th></tr>")
        for e, reason in sorted(orphans, key=lambda x: x[0]["file"]):
            w(f"<tr><td>{esc(e['file'])}</td><td>{esc(e['orig'] or '–')}</td>"
              f"<td>{'ja' if e['online'] else 'nein'}</td><td>{esc(reason)}</td></tr>")
        w("</table></div></details>")
    if skipped:
        w(f"<details><summary><span class='t'>Bewusst nicht online: Ordner mit „_“ ({fmt(sum(skipped.values()))} Bilder)</span>"
          "</summary><div class='inner'><table>")
        for rel, count in sorted(skipped.items()):
            w(f"<tr><td>{esc(rel)}</td><td>{fmt(count)}</td></tr>")
        w("</table></div></details>")
    if videos:
        w(f"<details><summary><span class='t'>Videos (nicht im Projekt, {fmt(sum(videos.values()))})</span></summary>"
          "<div class='inner'><table>")
        for rel, count in sorted(videos.items()):
            w(f"<tr><td>{esc(rel)}</td><td>{fmt(count)}</td></tr>")
        w("</table></div></details>")
    if duplicates:
        w(f"<details><summary><span class='t'>Achtung: gleicher Ordnername mehrfach ({len(duplicates)})</span></summary>"
          "<div class='inner small muted'>Exporte tragen nur den Ordnernamen – diese Ordner werden online "
          "zusammengelegt. Besser in Lightroom eindeutig umbenennen.</div><div class='inner'><table>")
        for name, rels in sorted(duplicates.items()):
            w(f"<tr><td>{esc(name)}</td><td>{esc(', '.join(sorted(rels)))}</td></tr>")
        w("</table></div></details>")
    w("<details><summary><span class='t'>Dateiarten im Originalordner</span></summary><div class='inner'><table>")
    for ext, count in ext_count.most_common():
        kind = ("RAW" if ext in RAW_EXT else "Bild" if ext in IMAGE_EXT else "Video" if ext in VIDEO_EXT else "sonstige")
        w(f"<tr><td>{esc(ext)}</td><td>{kind}</td><td>{fmt(count)}</td></tr>")
    w("</table><div class='small muted'>RAW und JPG mit gleichem Namen im selben Ordner zählen als ein Bild.</div>"
      "</div></details>")
    w("</main></body></html>")
    return "\n".join(out), totals


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
    originals = Path(cfg["originals_dir"])
    export_dir = Path(cfg["export_dir"])
    print(f"uebersicht.py v{__version__}")
    if not originals.is_dir():
        fail(f"Originalordner nicht gefunden: {originals}")
    if not export_dir.is_dir():
        fail(f"Export-Ordner nicht gefunden: {export_dir}")
    # Schutz: in den Originalordner wird nie geschrieben
    if inside(OUT_FILE, originals) or inside(SCRIPT_DIR, originals):
        fail("Das Skript liegt im Originalordner - dort wird nichts geschrieben. Abbruch.")
    if inside(export_dir, originals) or inside(originals, export_dir):
        fail("Export-Ordner und Originalordner ueberschneiden sich - bitte getrennt halten. Abbruch.")

    print(f"Lese Originale (nur Namen): {originals} ...")
    folders, duplicates, skipped, videos, ext_count = scan_originals(originals)
    print(f"  {sum(len(f['images']) for f in folders.values())} Bilder in {len(folders)} Ordnern")

    state_file = Path(cfg["work_dir"]) / "state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    print(f"Lese Exporte: {export_dir} ...")
    exports = scan_exports(export_dir, state)
    print(f"  {len(exports)} exportierte Bilder")

    status, orphans = match(folders, exports)
    page, totals = build_page(cfg, folders, duplicates, skipped, videos, ext_count, status, orphans, started)
    OUT_FILE.write_text(page, encoding="utf-8")

    print()
    print(f"Bilder in Lightroom-Ordnern: {totals['n']}")
    print(f"  online:                    {totals['online']}")
    print(f"  exportiert, Sync fehlt:    {totals['wait']}")
    print(f"  noch nicht exportiert:     {totals['none']}")
    if orphans:
        print(f"Exporte ohne passendes Original: {len(orphans)} (siehe Seite)")
    print(f"\nUebersicht: {OUT_FILE}")
    if not open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")


if __name__ == "__main__":
    main()
