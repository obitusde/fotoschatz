#!/usr/bin/env python3
"""Fotoschatz - Zeitachse pruefen: passen Aufnahmezeit und GPS der Fotos zur Google-Zeitachse und zu den Handyfotos?

Ueber den ganzen Katalog (nur Bilder fuer die Galerie):
  1. Kamera-Uhr: fuer jeden Ordner und jede Kamera ohne eigenes GPS dieselbe Pruefung wie in gps_test
     (Kamera- und Handyfoto derselben Szene, Tageszeit). Gemeldet werden nur Verdachtsfaelle.
  2. GPS gegen Zeitachse (ab 04/2017): liegt der Ort im Foto weit weg von dem Ort, an dem die Zeitachse
     zur selben Zeit war? -> falsch platziert, falsche Uhr oder Foto von jemand anderem.

Liest eine KOPIE des Lightroom-Katalogs (Lightroom muss geschlossen sein) und _sync\\google\\*.json.
Es wird nichts geaendert. Ergebnis: zeitachse_pruefen.html neben diesem Skript (bleibt auf dem PC;
enthaelt Dateinamen und Abstaende, keine Koordinaten). Korrigiert wird in Lightroom.

Aufruf: zeitachse_pruefen.bat (Doppelklick) oder python zeitachse_pruefen.py
"""

__version__ = "0.6.26"

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
FAR_M = 3000                          # GPS weiter als 3 km von der Zeitachse -> pruefen
NEIGHBOUR = timedelta(minutes=15)     # Zeitachsen-Punkte davor und danach so nah -> Ort dazwischen berechnen
NEAREST = timedelta(minutes=5)        # sonst: ein Punkt hoechstens so weit weg
PHONE_MIN, PHONE_SHARE = 20, 0.8      # "Handy": Kamera mit >= 20 Fotos, davon >= 80 % mit GPS
MIN_YEAR = 2000                       # Uhr-Pruefung erst fuer Digitalfotos (keine Scans)
MAX_LIST = 40                         # so viele Fotos je Ordner werden einzeln aufgelistet


def load_timeline():
    """Alle Punkte der Zeitachse: sortiert (Ortszeit, lat, lng) und (UTC, Stunden zu UTC) fuer die Zeitzone."""
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
    sonst der naechste Punkt (<= 5 min), sonst None."""
    j = bisect.bisect_left(times, t)
    a = pts[j - 1] if j > 0 else None
    b = pts[j] if j < len(pts) else None
    if a and b and t - a[0] <= NEIGHBOUR and b[0] - t <= NEIGHBOUR:
        span = (b[0] - a[0]).total_seconds()
        f = (t - a[0]).total_seconds() / span if span else 0
        return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
    near = [p for p in (a, b) if p and abs(p[0] - t) <= NEAREST]
    if near:
        p = min(near, key=lambda p: abs(p[0] - t))
        return p[1], p[2]
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

    # Welche Kameras sind Handys (fast immer mit GPS)? Deren Fotos mit GPS sind die Bezugspunkte fuer die Uhr.
    per_model = defaultdict(Counter)
    for i in images:
        per_model[i["model"]]["n"] += 1
        per_model[i["model"]]["gps"] += i["gps"]
    phones = {m for m, n in per_model.items() if n["n"] >= PHONE_MIN and n["gps"] >= PHONE_SHARE * n["n"]}
    refs = sorted((i["time"], i["file"]) for i in images if i["gps"] and i["model"] in phones)
    ref_times = [r[0] for r in refs]
    times = [p[0] for p in pts]
    zone_times = [z[0] for z in zones]
    tl_first = times[0] if times else None

    by_folder = defaultdict(list)
    for i in gallery:
        by_folder[i["folder"]].append(i)

    clock_rows, gps_rows = [], []
    stats = Counter()
    for folder, items in by_folder.items():
        # --- 1. Kamera-Uhr je Kamera (ohne Handys und unbekannte Kameras, ab 2000)
        for model in sorted({i["model"] for i in items}):
            if model in phones or model == "(unbekannt)":
                continue
            group = [{"t": i["time"], "file": i["file"], "gps": i["gps"]} for i in items
                     if i["model"] == model and i["time"].year >= MIN_YEAR]
            if len(group) < 5:
                continue
            first, last = min(g["t"] for g in group), max(g["t"] for g in group)
            lo, hi = first - timedelta(days=1), last + timedelta(days=1)
            phone_files = refs[bisect.bisect_left(ref_times, lo):bisect.bisect_right(ref_times, hi)]
            delta = zone_delta(zones, zone_times, lo, hi)
            res = G.clock_check(group, phone_files, delta)
            stats["clock_checked"] += 1
            stats[f"clock_{res['kind']}"] += 1
            if res["kind"] in ("shift", "odd", "weak"):
                clock_rows.append({"folder": folder, "model": model, "n": len(group),
                                   "with_gps": sum(g["gps"] for g in group), "res": res})

        # --- 2. GPS gegen Zeitachse
        checked, dists, far = 0, [], []
        for i in items:
            if not (i["gps"] and i["lat"] is not None and i["lng"] is not None):
                continue
            if tl_first is None or i["time"] < tl_first:
                stats["gps_before_timeline"] += 1
                continue
            pos = position_at(pts, times, i["time"])
            if pos is None:
                stats["gps_no_point"] += 1
                continue
            d = G.distance_m(i["lat"], i["lng"], pos[0], pos[1])
            checked += 1
            dists.append(d)
            if d > FAR_M:
                far.append((i, d))
        stats["gps_checked"] += checked
        stats["gps_far"] += len(far)
        if far:
            dists.sort()
            gps_rows.append({"folder": folder, "checked": checked, "far": sorted(far, key=lambda x: x[0]["time"]),
                             "median": dists[len(dists) // 2]})
    clock_order = {"shift": 0, "odd": 1, "weak": 2}
    clock_rows.sort(key=lambda r: (clock_order[r["res"]["kind"]], r["folder"].casefold(), r["model"]))
    gps_rows.sort(key=lambda r: (-len(r["far"]), r["folder"].casefold()))
    return clock_rows, gps_rows, stats, sorted(phones)


def km(d):
    return f"{d / 1000:.1f} km" if d < 100000 else f"{d / 1000:.0f} km"


def build_page(catalog_path, tl_info, pts, clock_rows, gps_rows, stats, phones, started):
    esc, fmt = U.esc, U.fmt
    out = []
    w = out.append
    w("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>Fotoschatz Zeitachse prüfen</title><style>{U.CSS}{LP.CSS_EXTRA}"
      "table.list td{vertical-align:top}ul.ev{margin:2px 0;padding-left:16px;font-size:.8rem}</style>"
      f"<script>{LP.JS}</script></head><body><main>")
    w("<h1>Fotoschatz – passen Zeit und Ort zur Zeitachse?</h1>")
    tl = (f"Zeitachse: {esc(', '.join(tl_info['files']))} · {fmt(len(pts))} Punkte "
          f"{pts[0][0]:%m/%Y}–{pts[-1][0]:%m/%Y}") if pts else "keine Zeitachse in _sync\\google gefunden"
    w(f"<div class='muted small'>Stand {datetime.now():%d.%m.%Y %H:%M} · zeitachse_pruefen.py v{__version__} · "
      f"Katalog: {esc(catalog_path.name)} (Kopie) · {tl} · Handys (Bezug für die Uhr): {esc(', '.join(phones) or '–')} "
      f"· {time.time() - started:.0f} s</div>")
    for err in tl_info["errors"]:
        w(f"<div class='warn'>{esc(err)}</div>")
    n_far = sum(len(r["far"]) for r in gps_rows)
    w("<div class='cards'>")
    w(f"<div class='card'><b style='color:var(--warn)'>{fmt(len([r for r in clock_rows if r['res']['kind'] != 'weak']))}"
      f"</b><span>Kameras mit falscher Uhr (Verdacht), dazu {fmt(len([r for r in clock_rows if r['res']['kind'] == 'weak']))}"
      f" unklar – von {fmt(stats['clock_checked'])} geprüften Kamera-Ordner-Paaren</span></div>")
    w(f"<div class='card'><b style='color:var(--warn)'>{fmt(n_far)}</b><span>Fotos mit GPS mehr als {FAR_M // 1000} km "
      f"neben der Zeitachse, in {fmt(len(gps_rows))} Ordnern – von {fmt(stats['gps_checked'])} geprüften</span></div>")
    w(f"<div class='card'><b class='muted'>{fmt(stats['gps_before_timeline'] + stats['gps_no_point'])}</b><span>Fotos mit "
      f"GPS ohne Vergleich (vor der Zeitachse oder kein Punkt ≤ 15 min)</span></div>")
    w("</div>")

    # ---- Kamera-Uhr
    w(f"<h2>Kamera-Uhr ({fmt(len(clock_rows))})</h2>")
    w("<div class='todo'>Geprüft wie in gps_test: Kamera- und Handyfoto derselben Szene (≤ 2 min) und Tageszeit "
      "(8–20 Uhr). <b style='color:inherit'>Erst prüfen</b> (in Lightroom nach Aufnahmezeit sortieren und die Belege "
      "vergleichen), dann korrigieren: Ordner öffnen › <i>Photo › Stacking › Expand All Stacks</i> › "
      "<i>Library Filter › Metadata › Camera</i> › Strg+A › <i>Metadata › Edit Capture Time… › Shift by set number of "
      "hours</i>. Haben die Fotos schon GPS aus einer Spur, ist das GPS dann auch falsch: GPS-Feld leeren, gps_test.bat "
      "neu, Auto-Tag. Danach exportieren, sync.bat, aufraeumen.bat.</div>")
    if not clock_rows:
        w("<div class='none'>Keine Hinweise auf eine falsche Kamera-Uhr.</div>")
    else:
        w("<div class='inner' style='padding:0'><table class='list'><tr><th>Ordner</th><th>Kamera</th>"
          "<th class='num'>Fotos</th><th>Befund</th></tr>")
        for r in clock_rows:
            res = r["res"]
            gps_note = (f"<div class='warn'>{fmt(r['with_gps'])} davon haben schon GPS – nach der Korrektur neu "
                        "zuordnen</div>") if r["with_gps"] and res["kind"] != "weak" else ""
            if res["kind"] != "weak":
                gps_note = (f"<div><b>Edit Capture Time › Shift by set number of hours: {res['shift']:+g}</b></div>"
                            + gps_note)
            ev = "".join(f"<li>{esc(res['label'])}: {esc(e)}</li>" for e in res["evidence"])
            w(f"<tr><td>{esc(LP.show(r['folder']))}</td><td>{esc(r['model'])}</td><td class='num'>{fmt(r['n'])}</td>"
              f"<td>{esc(res['text'])}{gps_note}{f'<ul class=ev>{ev}</ul>' if ev else ''}</td></tr>")
        w("</table></div>")

    # ---- GPS gegen Zeitachse
    w(f"<h2>GPS passt nicht zur Zeitachse ({fmt(n_far)} Fotos)</h2>")
    w(f"<div class='todo'>Der Ort im Foto liegt mehr als {FAR_M // 1000} km von dem Ort entfernt, an dem die Zeitachse "
      "zur selben Zeit war. Mögliche Gründe: Foto von Hand an die falsche Stelle gezogen · Kamera-Uhr falsch · Foto "
      "von jemand anderem (z. B. per WhatsApp) – dann ist es richtig so · Zeitachse selbst ungenau (Flug, Funkloch). "
      "Prüfen: Foto in Lightroom öffnen › Map-Modul. Falsch: an den richtigen Ort ziehen.</div>")
    if not gps_rows:
        w("<div class='none'>Alle geprüften Fotos passen zur Zeitachse.</div>")
    for r in gps_rows:
        far = r["far"]
        w(f"<details class='task'><summary><span class='t'>{esc(LP.show(r['folder']))}</span>"
          f"<span class='warn'>{fmt(len(far))} von {fmt(r['checked'])} weit weg · Median aller {km(r['median'])}"
          "</span></summary><div class='inner'><table><tr><th>Datei in Lightroom</th><th>Aufnahmezeit</th>"
          "<th>Kamera</th><th class='num'>Abstand</th></tr>")
        for i, d in far[:MAX_LIST]:
            w(f"<tr><td><b>{esc(i['file'])}</b></td><td>{i['time']:%d.%m.%Y %H:%M:%S}</td><td>{esc(i['model'])}</td>"
              f"<td class='num'>{km(d)}</td></tr>")
        if len(far) > MAX_LIST:
            w(f"<tr><td colspan='4' class='muted'>… und {fmt(len(far) - MAX_LIST)} weitere</td></tr>")
        w("</table></div></details>")
    w("</main></body></html>")
    return "\n".join(out)


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
    clock_rows, gps_rows, stats, phones = check(c, pts, zones)
    OUT_FILE.write_text(build_page(catalog_path, tl_info, pts, clock_rows, gps_rows, stats, phones, started),
                        encoding="utf-8")
    print(f"\nKamera-Uhr: {len(clock_rows)} Hinweise ({stats['clock_checked']} Kamera-Ordner-Paare geprueft)")
    print(f"GPS gegen Zeitachse: {stats['gps_checked']} geprueft, "
          f"{sum(len(r['far']) for r in gps_rows)} weiter als {FAR_M // 1000} km weg")
    print(f"\nErgebnis: {OUT_FILE}")
    if not U.open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")
        sys.exit(2)  # Fenster bleibt offen (zeitachse_pruefen.bat)


if __name__ == "__main__":
    main()
