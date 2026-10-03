#!/usr/bin/env python3
"""Fotoschatz - Zeitachse pruefen: wo liegen Fotos mit GPS weit weg von dem Ort, an dem du laut Google-Zeitachse
zur Aufnahmezeit warst? Liste der groessten Ausreisser zuerst - zum Kontrollieren und ggf. Korrigieren in Lightroom.

Je Foto: Abstand, Ort in Lightroom, Ort laut Google (zum Kopieren in das GPS-Feld in Lightroom), Kartenlinks.
Dazu (zugeklappt) die Kamera-Uhr-Pruefung je Ordner und Kamera wie in gps_test.

Liest eine KOPIE des Lightroom-Katalogs (Lightroom muss geschlossen sein) und _sync\\google\\*.json.
Es wird nichts geaendert. Ausgaben neben diesem Skript, bleiben auf dem PC:
  - zeitachse_pruefen.html  mit Koordinaten (nicht weitergeben)
  - zeitachse_pruefen.txt   nur Anzahlen und Abstaende, keine Koordinaten - diese Datei an Claude schicken

Aufruf: zeitachse_pruefen.bat (Doppelklick) oder python zeitachse_pruefen.py
"""

__version__ = "0.6.27"

import bisect
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import gps_test as G
import katalog
import lightroom_pruefen as LP
import uebersicht as U

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "zeitachse_pruefen.html"
TXT_FILE = SCRIPT_DIR / "zeitachse_pruefen.txt"
MIN_M = 1000                          # ab 1 km Abstand kommt ein Foto in die Liste
NEIGHBOUR = timedelta(minutes=15)     # Zeitachsen-Punkte davor und danach so nah -> Ort dazwischen berechnen
NEAREST = timedelta(minutes=5)        # sonst: ein Punkt hoechstens so weit weg
PHONE_MIN, PHONE_SHARE = 20, 0.8      # "Handy": Kamera mit >= 20 Fotos, davon >= 80 % mit GPS
MIN_YEAR = 2000                       # Uhr-Pruefung erst fuer Digitalfotos (keine Scans)
MAX_ROWS = 3000                       # mehr Zeilen zeigt die Seite nicht


def load_timeline():
    """Alle Punkte der Zeitachse: sortiert (Ortszeit, lat, lng) und (Ortszeit, Stunden zu UTC) fuer die Zeitzone."""
    info = {"files": [], "errors": []}
    pts, zones = [], []
    files = sorted(G.GOOGLE_DIR.glob("*.json")) if G.GOOGLE_DIR.is_dir() else []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as err:
            info["errors"].append(f"{f.name}: nicht lesbar ({type(err).__name__})")
            continue
        raw, _ = G.timeline_points(data)
        del data
        info["files"].append(f.name)
        for local, utc, lat, lng, _src in raw:
            pts.append((local, lat, lng))
            zones.append((local, (local - utc.replace(tzinfo=None)).total_seconds() / 3600))
    pts.sort()
    zones.sort()
    return pts, zones, info


def position_at(pts, times, t):
    """Ort laut Zeitachse zur Zeit t: zwischen den Punkten davor und danach (je <= 15 min) gleichmaessig,
    sonst der naechste Punkt (<= 5 min). Gibt (lat, lng, Minuten zum naechsten Punkt) oder None."""
    j = bisect.bisect_left(times, t)
    a = pts[j - 1] if j > 0 else None
    b = pts[j] if j < len(pts) else None
    if a and b and t - a[0] <= NEIGHBOUR and b[0] - t <= NEIGHBOUR:
        span = (b[0] - a[0]).total_seconds()
        f = (t - a[0]).total_seconds() / span if span else 0
        gap = min(t - a[0], b[0] - t).total_seconds() / 60
        return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, gap
    near = [p for p in (a, b) if p and abs(p[0] - t) <= NEAREST]
    if near:
        p = min(near, key=lambda p: abs(p[0] - t))
        return p[1], p[2], abs(p[0] - t).total_seconds() / 60
    return None


def zone_delta(zones, zone_times, lo, hi):
    """Ortszeit - Heimatzeit (PC-Zeitzone) in Stunden fuer den Zeitraum, aus der Zeitachse (oder None)."""
    i, j = bisect.bisect_left(zone_times, lo), bisect.bisect_right(zone_times, hi)
    if i >= j:
        return None
    local = Counter(round(z[1] * 2) / 2 for z in zones[i:j]).most_common(1)[0][0]
    home = lo.astimezone().utcoffset().total_seconds() / 3600
    return local - home


def check(c, pts, zones):
    images = [i for i in c["images"] if i["time"]]
    gallery = [i for i in images if i["gallery"]]
    times = [p[0] for p in pts]
    stats = Counter()

    # --- 1. GPS gegen Zeitachse: jedes Foto mit GPS (fuer die Galerie), Abstand zum Ort laut Google
    rows = []
    for i in gallery:
        if not (i["gps"] and i["lat"] is not None and i["lng"] is not None):
            continue
        if not times or i["time"] < times[0] or i["time"] > times[-1]:
            stats["no_timeline"] += 1
            continue
        pos = position_at(pts, times, i["time"])
        if pos is None:
            stats["no_point"] += 1
            continue
        d = G.distance_m(i["lat"], i["lng"], pos[0], pos[1])
        stats["checked"] += 1
        if d >= MIN_M:
            rows.append({"i": i, "d": d, "g": pos})
    rows.sort(key=lambda r: -r["d"])

    # --- 2. Kamera-Uhr je Ordner und Kamera (alle Fotos der Kamera, Bezug = Handyfotos mit GPS)
    per_model = defaultdict(Counter)
    for i in images:
        per_model[i["model"]]["n"] += 1
        per_model[i["model"]]["gps"] += i["gps"]
    phones = {m for m, n in per_model.items() if n["n"] >= PHONE_MIN and n["gps"] >= PHONE_SHARE * n["n"]}
    refs = sorted((i["time"], i["file"]) for i in images if i["gps"] and i["model"] in phones)
    ref_times = [r[0] for r in refs]
    zone_times = [z[0] for z in zones]
    by_folder = defaultdict(list)
    for i in gallery:
        by_folder[i["folder"]].append(i)
    clock_rows = []
    for folder, items in by_folder.items():
        for model in sorted({i["model"] for i in items}):
            if model in phones or model == "(unbekannt)":
                continue
            group = [{"t": i["time"], "file": i["file"], "gps": i["gps"]} for i in items
                     if i["model"] == model and i["time"].year >= MIN_YEAR]
            if len(group) < 5:
                continue
            lo = min(g["t"] for g in group) - timedelta(days=1)
            hi = max(g["t"] for g in group) + timedelta(days=1)
            phone_files = refs[bisect.bisect_left(ref_times, lo):bisect.bisect_right(ref_times, hi)]
            res = G.clock_check(group, phone_files, zone_delta(zones, zone_times, lo, hi))
            stats["clock_checked"] += 1
            if res["kind"] in ("shift", "odd", "weak"):
                clock_rows.append({"folder": folder, "model": model, "n": len(group),
                                   "with_gps": sum(g["gps"] for g in group), "res": res})
    order = {"shift": 0, "odd": 1, "weak": 2}
    clock_rows.sort(key=lambda r: (order[r["res"]["kind"]], r["folder"].casefold(), r["model"]))
    return rows, clock_rows, stats, sorted(phones)


# ---------------------------------------------------------------- Seite

def km(d):
    return f"{d / 1000:,.1f} km".replace(",", ".") if d < 100000 else f"{d / 1000:,.0f} km".replace(",", ".")


def ll(lat, lng):
    return f"{lat:.6f}, {lng:.6f}"


CSS = """
.bar2{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.bar2 button{font:inherit;padding:5px 12px;border-radius:14px;border:1px solid var(--line);background:var(--card);
color:inherit;cursor:pointer}.bar2 button.on{border-color:var(--text);font-weight:600}
table.out{border-collapse:collapse;width:100%;font-size:.85rem}
table.out th{position:sticky;top:0;background:var(--bg);text-align:left;padding:6px 8px;border-bottom:2px solid var(--line)}
table.out td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
table.out tr.done td{opacity:.35}
.dist{font-weight:700;white-space:nowrap;font-size:1rem}
.cp{font:inherit;font-size:.8rem;padding:2px 8px;margin:2px 0;border-radius:6px;border:1px solid var(--line);
background:var(--card);color:inherit;cursor:pointer;white-space:nowrap}
.cp.ok{border-color:var(--ok);color:var(--ok)}
.coord{font-family:ui-monospace,Consolas,monospace;font-size:.8rem;white-space:nowrap}
a{color:inherit}.small a{margin-right:8px}
.steps{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:10px 0}
.steps ol{margin:4px 0;padding-left:20px}
@media (max-width:700px){table.out .hide-s{display:none}}
"""

JS = """
function copyText(btn,text){
  const done=()=>{btn.classList.add('ok');const t=btn.textContent;btn.textContent='kopiert ✓';
    setTimeout(()=>{btn.textContent=t;btn.classList.remove('ok')},1200)};
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(done,()=>fallback())}
  else fallback();
  function fallback(){const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);
    ta.select();try{document.execCommand('copy');done()}catch(e){prompt('Kopieren mit Strg+C:',text)}ta.remove()}
}
function store(){try{return JSON.parse(localStorage.getItem('fotoschatz.zeitachse.done')||'{}')}catch(e){return {}}}
function toggleDone(cb){const s=store();if(cb.checked)s[cb.dataset.k]=1;else delete s[cb.dataset.k];
  try{localStorage.setItem('fotoschatz.zeitachse.done',JSON.stringify(s))}catch(e){}
  cb.closest('tr').classList.toggle('done',cb.checked);filter()}
let minKm=1,hideDone=false;
function setMin(btn,v){minKm=v;document.querySelectorAll('.fmin').forEach(b=>b.classList.toggle('on',b===btn));filter()}
function setHide(btn){hideDone=!hideDone;btn.classList.toggle('on',hideDone);filter()}
function filter(){let n=0;document.querySelectorAll('table.out tr[data-km]').forEach(tr=>{
  const show=+tr.dataset.km>=minKm&&!(hideDone&&tr.classList.contains('done'));tr.style.display=show?'':'none';if(show)n++});
  document.getElementById('count').textContent=n}
window.addEventListener('DOMContentLoaded',()=>{const s=store();document.querySelectorAll('input.done').forEach(cb=>{
  if(s[cb.dataset.k]){cb.checked=true;cb.closest('tr').classList.add('done')}});filter()});
"""


def build_page(catalog_path, tl_info, pts, rows, clock_rows, stats, phones, started):
    esc, fmt = U.esc, U.fmt
    out = []
    w = out.append
    w("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>Fotoschatz Zeitachse prüfen</title><style>{U.CSS}{LP.CSS_EXTRA}{CSS}</style>"
      f"<script>{JS}</script></head><body><main style='max-width:1250px'>")
    w("<h1>GPS-Ausreißer – Foto liegt weit weg von dem Ort laut Google-Zeitachse</h1>")
    tl = (f"Zeitachse: {esc(', '.join(tl_info['files']))} · {fmt(len(pts))} Punkte "
          f"{pts[0][0]:%m/%Y}–{pts[-1][0]:%m/%Y}") if pts else "keine Zeitachse in _sync\\google gefunden"
    w(f"<div class='muted small'>Stand {datetime.now():%d.%m.%Y %H:%M} · zeitachse_pruefen.py v{__version__} · "
      f"Katalog: {esc(catalog_path.name)} (Kopie) · {tl} · {fmt(stats['checked'])} Fotos mit GPS verglichen · "
      f"{time.time() - started:.0f} s · <b>Enthält Koordinaten – nicht weitergeben.</b></div>")
    for err in tl_info["errors"]:
        w(f"<div class='warn'>{esc(err)}</div>")

    w("<div class='steps'><b>So prüfst du ein Foto (größte Abstände stehen oben):</b><ol>"
      "<li>In Lightroom links <i>Catalog › All Photographs</i> wählen.</li>"
      "<li>Bei <b>Datei</b> auf <i>Kopieren</i> klicken › in Lightroom <i>Library Filter › Text › Filename › Contains</i> "
      "› Strg+V.</li>"
      "<li>Foto ansehen, Kartenlinks vergleichen: Wo war es wirklich?"
      "<ul><li><b>Lightroom stimmt</b> (z. B. Foto von jemand anderem, Zeitachse ungenau): nichts tun, Häkchen "
      "<i>erledigt</i> setzen.</li>"
      "<li><b>Google stimmt:</b> bei <b>Laut Google</b> auf <i>Kopieren</i> › in Lightroom rechts im <i>Metadata</i>-Panel "
      "ins Feld <i>GPS</i> klicken › Strg+V › Enter. ⚠ Format am PC prüfen.</li>"
      "<li><b>Ganze Serie daneben</b> (gleicher Ordner, gleiche Kamera, ähnlicher Abstand): eher die Kamera-Uhr – siehe "
      "unten „Kamera-Uhr“.</li></ul></li>"
      "<li>Danach exportieren, sync.bat.</li></ol>"
      "<span class='muted small'>„erledigt“ merkt sich dieser Browser. Kartenlinks öffnen Google Maps.</span></div>")

    w("<div class='bar2'>Zeigen ab: ")
    for v, label in ((1, "1 km"), (5, "5 km"), (20, "20 km"), (100, "100 km")):
        w(f"<button class='fmin{' on' if v == 1 else ''}' onclick='setMin(this,{v})'>{label}</button>")
    w(f"<button onclick='setHide(this)'>Erledigte ausblenden</button> <span><b id='count'>{fmt(len(rows))}</b> Fotos"
      "</span></div>")
    if not rows:
        w("<div class='none'>Keine Ausreißer – alle verglichenen Fotos liegen höchstens 1 km neben der Zeitachse.</div>")
    else:
        w("<table class='out'><tr><th>Abstand</th><th>Datei</th><th>Aufnahme</th><th class='hide-s'>Ordner</th>"
          "<th>Jetzt in Lightroom</th><th>Laut Google</th><th>Karte</th><th>erledigt</th></tr>")
        for r in rows[:MAX_ROWS]:
            i, (glat, glng, gap) = r["i"], r["g"]
            key = f"{i['folder']}/{i['file']}/{i['time']:%Y%m%d%H%M%S}"
            here, there = ll(i["lat"], i["lng"]), ll(glat, glng)
            maps = "https://www.google.com/maps/search/?api=1&query="
            route = (f"https://www.google.com/maps/dir/?api=1&origin={i['lat']:.6f},{i['lng']:.6f}"
                     f"&destination={glat:.6f},{glng:.6f}")
            w(f"<tr data-km='{r['d'] / 1000:.3f}'><td class='dist'>{km(r['d'])}</td>"
              f"<td><b>{esc(i['file'])}</b><br><button class='cp' data-c='{esc(i['base'])}' onclick='copyText(this,this.dataset.c)'>Kopieren</button>"
              f"<div class='muted small'>{esc(i['model'])}</div></td>"
              f"<td style='white-space:nowrap'>{i['time']:%d.%m.%Y}<br>{i['time']:%H:%M:%S}</td>"
              f"<td class='hide-s'>{esc(LP.show(i['folder']))}</td>"
              f"<td>{esc(i['place']) or '<span class=muted>(ohne Ort)</span>'}<div class='coord'>{here}</div>"
              f"<a href='{maps}{i['lat']:.6f},{i['lng']:.6f}' target='_blank' rel='noopener'>Karte</a></td>"
              f"<td><div class='coord'>{there}</div><button class='cp' data-c='{there}' onclick='copyText(this,this.dataset.c)'>Kopieren</button>"
              f" <a href='{maps}{glat:.6f},{glng:.6f}' target='_blank' rel='noopener'>Karte</a>"
              f"<div class='muted small'>Zeitachse ±{gap:.0f} min</div></td>"
              f"<td><a href='{route}' target='_blank' rel='noopener'>beide</a></td>"
              f"<td><input type='checkbox' class='done' data-k='{esc(key)}' onchange='toggleDone(this)'></td></tr>")
        w("</table>")
        if len(rows) > MAX_ROWS:
            w(f"<div class='muted'>… und {fmt(len(rows) - MAX_ROWS)} weitere mit kleinerem Abstand</div>")

    # ---- Kamera-Uhr (zugeklappt)
    w(f"<details style='margin-top:24px'><summary><span class='t'>Kamera-Uhr: {fmt(len(clock_rows))} Verdachtsfälle "
      f"(von {fmt(stats['clock_checked'])} Ordner/Kamera-Paaren)</span></summary><div class='inner'>")
    w("<div class='todo'>Vergleich Kamera- ↔ Handyfoto derselben Szene (≤ 2 min) und Tageszeit, wie in gps_test. "
      "Erst die Belege in Lightroom vergleichen, dann: Ordner › <i>Photo › Stacking › Expand All Stacks</i> › "
      "<i>Library Filter › Metadata › Camera</i> › Strg+A › <i>Metadata › Edit Capture Time… › Shift by set number of "
      f"hours</i>. Handys (Bezug): {esc(', '.join(phones) or '–')}.</div>")
    if clock_rows:
        w("<table><tr><th>Ordner</th><th>Kamera</th><th class='num'>Fotos</th><th>Befund</th></tr>")
        for r in clock_rows:
            res = r["res"]
            extra = ""
            if res["kind"] != "weak":
                extra = f"<div><b>Shift by set number of hours: {res['shift']:+g}</b></div>"
                if r["with_gps"]:
                    extra += (f"<div class='warn'>{fmt(r['with_gps'])} davon haben schon GPS – danach GPS-Feld leeren, "
                              "gps_test.bat, Auto-Tag</div>")
            ev = "".join(f"<li>{esc(res['label'])}: {esc(e)}</li>" for e in res["evidence"])
            w(f"<tr><td>{esc(LP.show(r['folder']))}</td><td>{esc(r['model'])}</td><td class='num'>{fmt(r['n'])}</td>"
              f"<td>{esc(res['text'])}{extra}{f'<ul class=ev>{ev}</ul>' if ev else ''}</td></tr>")
        w("</table>")
    else:
        w("<div class='none'>Keine Hinweise auf eine falsche Kamera-Uhr.</div>")
    w("</div></details></main></body></html>")
    return "\n".join(out)


def write_txt(tl_info, pts, rows, clock_rows, stats):
    """Zusammenfassung fuer Claude: nur Anzahlen, Abstaende, Ordner und Dateinamen - keine Koordinaten."""
    lines = [f"zeitachse_pruefen.py v{__version__} · {datetime.now():%d.%m.%Y %H:%M}",
             f"Zeitachse: {len(pts)} Punkte" + (f" {pts[0][0]:%m/%Y}–{pts[-1][0]:%m/%Y}" if pts else ""),
             f"Fotos mit GPS verglichen: {stats['checked']} · ausserhalb der Zeitachse: {stats['no_timeline']} · "
             f"kein Punkt <= 15 min: {stats['no_point']}", ""]
    buckets = [(1, 5), (5, 20), (20, 100), (100, 1000), (1000, 10 ** 9)]
    lines.append("Ausreisser nach Abstand: " + " · ".join(
        f"{a}–{b if b < 10 ** 9 else '∞'} km: {sum(1 for r in rows if a <= r['d'] / 1000 < b)}" for a, b in buckets))
    per_folder = Counter(r["i"]["folder"] for r in rows)
    lines += ["", "Ordner mit den meisten Ausreissern (>= 1 km):"]
    lines += [f"  {n:5}  {LP.show(f)}" for f, n in per_folder.most_common(25)]
    lines += ["", "Die 30 groessten:"]
    lines += [f"  {km(r['d']):>10}  {r['i']['time']:%d.%m.%Y %H:%M}  {r['i']['model']}  {LP.show(r['i']['folder'])}  "
              f"{r['i']['file']}" for r in rows[:30]]
    lines += ["", f"Kamera-Uhr: {len(clock_rows)} Hinweise ({stats['clock_checked']} Ordner/Kamera-Paare geprueft)"]
    lines += [f"  {r['res']['kind']:6} {r['res']['shift']:+g} h  {r['model']}  {LP.show(r['folder'])}" for r in clock_rows]
    TXT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    started = time.time()
    cfg = LP.load_config()
    print(f"zeitachse_pruefen.py v{__version__}")
    originals = Path(cfg["originals_dir"])
    if U.inside(SCRIPT_DIR, originals):
        LP.fail("Das Skript liegt im Originalordner - dort wird nichts geschrieben. Abbruch.")
    try:
        print("Kopiere den Lightroom-Katalog (nur lesen) ...")
        catalog_path, copy, db = katalog.prepare(cfg["catalog"], protected=[originals])
    except katalog.CatalogError as err:
        LP.fail(str(err))
    try:
        c = LP.read_catalog(db, cfg)
    except Exception as err:   # Aufbau des Katalogs anders als erwartet
        LP.fail(f"Katalog nicht lesbar ({type(err).__name__}: {err}). Bitte katalog_diagnose.bat laufen lassen und "
                "katalog_diagnose.txt an Claude schicken.")
    finally:
        db.close()
    print(f"  {len(c['images'])} Bilder")
    print("Lese Google-Zeitachse ...")
    pts, zones, tl_info = load_timeline()
    print(f"  {len(pts)} Punkte" if pts else "  keine gefunden - nur die Uhr-Pruefung mit Handyfotos")
    print("Pruefe ...")
    rows, clock_rows, stats, phones = check(c, pts, zones)
    OUT_FILE.write_text(build_page(catalog_path, tl_info, pts, rows, clock_rows, stats, phones, started),
                        encoding="utf-8")
    write_txt(tl_info, pts, rows, clock_rows, stats)
    print(f"\nFotos mit GPS verglichen: {stats['checked']}, davon {len(rows)} mehr als {MIN_M // 1000} km neben der "
          f"Zeitachse (groesster: {km(rows[0]['d']) if rows else '-'})")
    print(f"Kamera-Uhr: {len(clock_rows)} Hinweise")
    print(f"\nErgebnis: {OUT_FILE}  (enthaelt Koordinaten - bleibt auf dem PC)")
    print(f"Fuer Claude: {TXT_FILE.name} (ohne Koordinaten)")
    if not U.open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")
        sys.exit(2)  # Fenster bleibt offen (zeitachse_pruefen.bat)


if __name__ == "__main__":
    main()
