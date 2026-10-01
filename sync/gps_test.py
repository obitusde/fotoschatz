#!/usr/bin/env python3
"""Fotoschatz - GPS-Test: Koennen Fotos ohne GPS ihren Ort aus Handyfotos und Google-Zeitachse bekommen?

Alles bleibt auf dem PC. Gelesen werden:
  - eine KOPIE des Lightroom-Katalogs (Lightroom muss geschlossen sein)
  - die Google-Zeitachse aus _sync\\google\\*.json (Export vom Handy)
Geschrieben werden nur Dateien in _sync:
  - gps_test.txt          nur Anzahlen, keine Koordinaten (diese Datei an Claude schicken)
  - gpx\\<Ordner>.gpx      GPS-Spur zum Ausprobieren in Lightroom (Map › Tracklog) - bleibt auf dem PC
Es wird nichts an Fotos, Katalog oder Originalen geaendert - den Ort setzt spaeter Lightroom selbst.

Aufruf: gps_test.bat (fragt nach einem Teil des Ordnernamens, z. B. Japan)
        oder python gps_test.py Japan
"""

__version__ = "0.6.15"

import bisect
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import katalog

SCRIPT_DIR = Path(__file__).resolve().parent
GOOGLE_DIR = SCRIPT_DIR / "google"
GPX_DIR = SCRIPT_DIR / "gpx"
OUT_FILE = SCRIPT_DIR / "gps_test.txt"
DEFAULTS = {"catalog": katalog.DEFAULT_CATALOG, "originals_dir": r"D:\Bilder - Raw"}
LATLNG_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*,\s*(-?\d+(?:\.\d+)?)")
SEGMENT_GAP = timedelta(hours=2)        # laengere Luecken trennen die Spur (keine Linie quer durchs Land)
MATCH = timedelta(minutes=10)           # fuer die Suche nach der Kamera-Zeitverschiebung

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return cfg


def parse_time(value):
    """Lightroom-Zeit -> naive Ortszeit (wie auf der Kamera eingestellt)."""
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def parse_iso(value):
    """Zeitstempel aus der Zeitachse -> (Ortszeit naiv, UTC). Ohne Zeitzone gilt die PC-Zeitzone."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)          # mehr als 6 Nachkommastellen kann Python nicht
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt, dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None), dt.astimezone(timezone.utc)


def parse_latlng(value):
    if isinstance(value, dict):
        if "latitudeE7" in value:
            return value["latitudeE7"] / 1e7, value["longitudeE7"] / 1e7
        value = value.get("latLng") or value.get("LatLng")
    m = LATLNG_RE.search(str(value or "").replace("geo:", ""))
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


# ---------------------------------------------------------------- Google-Zeitachse

def timeline_points(data):
    """Alle Punkte (Ortszeit, UTC, lat, lng, Quelle) aus den bekannten Export-Formaten:
    Android-Export (semanticSegments/rawSignals), iPhone-Export (Liste), alter Takeout (locations)."""
    pts = []
    zones = []        # (UTC, Abstand zu UTC) aus Abschnitten mit echter Ortszeit
    info = Counter()

    def add(stamp, latlng, source, offset_min=None):
        t = parse_iso(stamp)
        p = parse_latlng(latlng)
        if not (t and p):
            return
        if offset_min is not None:
            # Android-Export: die Zeitangaben tragen die Zeitzone des Handys beim EXPORT, die echte
            # Ortszeit steht in ...TimezoneUtcOffsetMinutes
            local = t[1].replace(tzinfo=None) + timedelta(minutes=float(offset_min))
            zones.append((t[1], local - t[1].replace(tzinfo=None)))
            pts.append([local, t[1], p[0], p[1], source, False])
            return
        utc_only = str(stamp).strip().endswith(("Z", "+00:00"))
        if not utc_only:
            zones.append((t[1], t[0] - t[1].replace(tzinfo=None)))
        pts.append([t[0], t[1], p[0], p[1], source, utc_only])

    if isinstance(data, dict):
        for seg in data.get("semanticSegments", []) or []:
            so = seg.get("startTimeTimezoneUtcOffsetMinutes")
            eo = seg.get("endTimeTimezoneUtcOffsetMinutes", so)
            info["mit Zeitzonen-Feld" if so is not None else "ohne Zeitzonen-Feld"] += 1
            for p in seg.get("timelinePath", []) or []:
                add(p.get("time"), p.get("point"), "Weg", so)
            visit = seg.get("visit")
            if visit:
                loc = (visit.get("topCandidate") or {}).get("placeLocation")
                add(seg.get("startTime"), loc, "Aufenthalt", so)
                add(seg.get("endTime"), loc, "Aufenthalt", eo)
            act = seg.get("activity")
            if act:
                add(seg.get("startTime"), act.get("start"), "Bewegung", so)
                add(seg.get("endTime"), act.get("end"), "Bewegung", eo)
        for sig in data.get("rawSignals", []) or []:
            pos = sig.get("position")
            if pos:
                add(pos.get("timestamp"), pos.get("LatLng") or pos.get("latLng"), "Rohsignal")
        for loc in data.get("locations", []) or []:
            stamp = loc.get("timestamp")
            if not stamp and loc.get("timestampMs"):
                stamp = datetime.fromtimestamp(int(loc["timestampMs"]) / 1000, timezone.utc).isoformat()
            add(stamp, loc, "Takeout")
    elif isinstance(data, list):                         # iPhone-Format
        for seg in data:
            if not isinstance(seg, dict):
                continue
            start = parse_iso(seg.get("startTime"))
            visit = seg.get("visit")
            if visit:
                loc = (visit.get("topCandidate") or {}).get("placeLocation")
                add(seg.get("startTime"), loc, "Aufenthalt")
                add(seg.get("endTime"), loc, "Aufenthalt")
            act = seg.get("activity")
            if act:
                add(seg.get("startTime"), act.get("start"), "Bewegung")
                add(seg.get("endTime"), act.get("end"), "Bewegung")
            for p in seg.get("timelinePath", []) or []:
                if start and p.get("durationMinutesOffsetFromStartTime") is not None:
                    offset = timedelta(minutes=float(p["durationMinutesOffsetFromStartTime"]))
                    p_local, p_utc = start[0] + offset, start[1] + offset
                    ll = parse_latlng(p.get("point"))
                    if ll:
                        pts.append([p_local, p_utc, ll[0], ll[1], "Weg", False])
    # Punkte nur mit UTC (z. B. Rohsignale): Ortszeit ueber die Zeitzone der Abschnitte daneben
    zones.sort()
    zone_times = [z[0] for z in zones]
    for p in pts:
        if p[5] and zones:
            j = nearest_index(zone_times, p[1])
            if abs(zone_times[j] - p[1]) <= timedelta(hours=36):
                p[0] = p[1].replace(tzinfo=None) + zones[j][1]
    return [tuple(p[:5]) for p in pts], info


def describe_format(data):
    if isinstance(data, dict):
        return "Android-Export" if "semanticSegments" in data else (
            "Google Takeout (alt)" if "locations" in data else "unbekannt: " + ", ".join(list(data)[:6]))
    if isinstance(data, list):
        return "iPhone-Export (Liste)"
    return f"unbekannt ({type(data).__name__})"


# ---------------------------------------------------------------- Hilfen

def distance_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_gap(times, t):
    """Abstand zum naechsten Zeitpunkt in der sortierten Liste."""
    i = bisect.bisect_left(times, t)
    gaps = [abs(times[j] - t) for j in (i - 1, i) if 0 <= j < len(times)]
    return min(gaps) if gaps else None


def nearest_index(times, t):
    i = bisect.bisect_left(times, t)
    cands = [j for j in (i - 1, i) if 0 <= j < len(times)]
    return min(cands, key=lambda j: abs(times[j] - t)) if cands else None


def bucket(gap):
    if gap is None:
        return "kein Punkt"
    m = gap.total_seconds() / 60
    return "≤ 5 min" if m <= 5 else "≤ 15 min" if m <= 15 else "≤ 60 min" if m <= 60 else "≤ 3 h" if m <= 180 else "> 3 h"


BUCKETS = ["≤ 5 min", "≤ 15 min", "≤ 60 min", "≤ 3 h", "> 3 h", "kein Punkt"]


def write_gpx(path, points):
    """GPS-Spur; Zeiten als Ortszeit der Fotos, umgerechnet ueber die PC-Zeitzone (so rechnet auch Lightroom)."""
    points = sorted(points)
    segs, cur, last = [], [], None
    for p in points:
        if last is not None and p[0] - last > SEGMENT_GAP:
            segs.append(cur)
            cur = []
        cur.append(p)
        last = p[0]
    if cur:
        segs.append(cur)
    w = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="Fotoschatz gps_test" xmlns="http://www.topografix.com/GPX/1/1">',
         "<trk><name>Fotoschatz</name>"]
    for seg in segs:
        w.append("<trkseg>")
        for local, lat, lng in seg:
            utc = local.astimezone(timezone.utc)          # naive = PC-Zeitzone, wie Lightroom ohne Zeitzonen-Angabe
            w.append(f'<trkpt lat="{lat:.6f}" lon="{lng:.6f}"><time>{utc:%Y-%m-%dT%H:%M:%SZ}</time></trkpt>')
        w.append("</trkseg>")
    w.append("</trk></gpx>")
    path.write_text("\n".join(w), encoding="utf-8")
    return len(segs)


# ---------------------------------------------------------------- Ablauf

def main():
    started = time.time()
    cfg = load_config()
    search = " ".join(sys.argv[1:]).strip() or "Japan"
    out(f"gps_test.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')} · Ordner enthält: „{search}“")

    # --- Katalog (Kopie)
    try:
        catalog, copy, db = katalog.prepare(cfg["catalog"], protected=[cfg["originals_dir"]])
    except katalog.CatalogError as err:
        out(f"\nFEHLER: {err}")
        OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
        sys.exit(1)
    rows = db.execute("""
        SELECT i.id_local AS id, i.captureTime AS t, fo.pathFromRoot AS path, r.absolutePath AS root,
               e.hasGPS AS hasGPS, e.gpsLatitude AS lat, e.gpsLongitude AS lng, m.value AS model
        FROM Adobe_images i
        JOIN AgLibraryFile f ON f.id_local = i.rootFile
        JOIN AgLibraryFolder fo ON fo.id_local = f.folder
        JOIN AgLibraryRootFolder r ON r.id_local = fo.rootFolder
        LEFT JOIN AgHarvestedExifMetadata e ON e.image = i.id_local
        LEFT JOIN AgInternedExifCameraModel m ON m.id_local = e.cameraModelRef""").fetchall()
    ok_ids = {r[0] for r in db.execute("""SELECT ki.image FROM AgLibraryKeywordImage ki
                                          JOIN AgLibraryKeyword k ON k.id_local = ki.tag
                                          WHERE LOWER(k.name) = 'location-ok'""")}
    db.close()

    photos = []
    for r in rows:
        t = parse_time(r["t"])
        if not t:
            continue
        has = bool(r["hasGPS"]) and r["lat"] is not None and r["lng"] is not None
        photos.append({"id": r["id"], "t": t, "folder": r["path"] or "",
                       "root": r["root"] or "", "gps": (r["lat"], r["lng"]) if has else None,
                       "model": r["model"] or "(unbekannt)", "ok": r["id"] in ok_ids})
    wanted = [p for p in photos if search.casefold() in p["folder"].casefold()
              and not any(x.startswith("_") for x in p["folder"].split("/"))]
    if not wanted:
        out(f"\nKein Ordner gefunden, der „{search}“ enthält.")
        OUT_FILE.write_text("\n".join(lines), encoding="utf-8")
        sys.exit(1)
    folders = Counter(p["folder"].strip("/").replace("/", "\\") for p in wanted)
    out("\n== Ordner")
    for f, n in folders.most_common():
        out(f"  {f}: {n} Bilder")
    first, last = min(p["t"] for p in wanted), max(p["t"] for p in wanted)
    lo, hi = first - timedelta(days=1), last + timedelta(days=1)
    out(f"  Zeitraum der Fotos: {first:%d.%m.%Y %H:%M} – {last:%d.%m.%Y %H:%M}")

    targets = [p for p in wanted if not p["gps"] and not p["ok"]]
    out("\n== Fotos im Ordner nach Kamera")
    by_model = defaultdict(Counter)
    for p in wanted:
        by_model[p["model"]]["mit GPS" if p["gps"] else ("location-ok" if p["ok"] else "ohne GPS")] += 1
    for model, c in sorted(by_model.items(), key=lambda x: -sum(x[1].values())):
        out(f"  {model}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    out(f"  → ohne GPS (ohne location-ok): {len(targets)}")

    # --- Bezugspunkte 1: Fotos MIT GPS im Zeitraum (aus dem ganzen Katalog, z. B. Handyfotos)
    phone = sorted((p["t"], p["gps"][0], p["gps"][1]) for p in photos if p["gps"] and lo <= p["t"] <= hi)
    out(f"\n== Fotos mit GPS im Zeitraum (±1 Tag, ganzer Katalog): {len(phone)}")

    # --- Bezugspunkte 2: Google-Zeitachse
    tl = []
    files = sorted(GOOGLE_DIR.glob("*.json")) if GOOGLE_DIR.is_dir() else []
    out(f"\n== Google-Zeitachse ({GOOGLE_DIR})")
    if not files:
        out("  keine .json-Datei gefunden")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as err:
            out(f"  {f.name}: nicht lesbar ({err})")
            continue
        pts, info = timeline_points(data)
        out(f"  {f.name}: {f.stat().st_size / 1e6:.1f} MB, Format {describe_format(data)}, {len(pts)} Punkte")
        if info:
            out("    Abschnitte: " + ", ".join(f"{k} {v}" for k, v in info.most_common()))
        if pts:
            out(f"    gesamt von {min(p[0] for p in pts):%d.%m.%Y} bis {max(p[0] for p in pts):%d.%m.%Y}")
            years = Counter(p[0].year for p in pts)
            out("    Punkte je Jahr: " + ", ".join(f"{y}: {n}" for y, n in sorted(years.items())))
            inside = [p for p in pts if lo <= p[0] <= hi]
            out(f"    im Zeitraum der Fotos: {len(inside)} – nach Art: "
                + (", ".join(f"{k} {v}" for k, v in Counter(p[4] for p in inside).most_common()) or "-"))
            offsets = Counter(round((p[0] - p[1].replace(tzinfo=None)).total_seconds() / 3600, 1) for p in inside)
            if offsets:
                out("    Zeitzonen im Zeitraum (Stunden zu UTC): "
                    + ", ".join(f"{o:+g} h ×{n}" for o, n in offsets.most_common(4)))
            tl += [(p[0], p[2], p[3]) for p in inside]
    tl.sort()

    # --- Selbstkontrolle Zeitzone: passt die Zeitachse zeitlich zu den Fotos mit GPS?
    if tl and phone:
        def median_dist(shift_h):
            shifted = [(t + timedelta(hours=shift_h), lat, lng) for t, lat, lng in tl]
            times = [p[0] for p in shifted]
            d = []
            for t, lat, lng in phone:
                j = nearest_index(times, t)
                if j is not None and abs(times[j] - t) <= timedelta(minutes=5):
                    d.append(distance_m(lat, lng, shifted[j][1], shifted[j][2]))
            d.sort()
            return (d[len(d) // 2], len(d)) if len(d) >= 10 else (None, len(d))
        results = {h: median_dist(h) for h in range(-14, 15)}
        valid = [(m, h) for h, (m, n) in results.items() if m is not None]
        m0 = results[0][0]
        out("\n== Zeitzone der Zeitachse (Abstand zu Fotos mit GPS, Median)")
        if valid:
            best_m, best_h = min(valid)
            out(f"  ohne Verschiebung: {'–' if m0 is None else f'{m0:.0f} m'} · beste Verschiebung {best_h:+d} h: "
                f"{best_m:.0f} m ({results[best_h][1]} Vergleiche)")
            if best_h != 0 and (m0 is None or best_m < m0 / 2):
                tl = [(t + timedelta(hours=best_h), lat, lng) for t, lat, lng in tl]
                out(f"  → Zeitachse um {best_h:+d} h verschoben (Zeitzone im Export passte nicht)")
        else:
            out("  zu wenige Vergleiche")

    # --- Genauigkeit: Zeitachse gegen Fotos mit GPS
    if tl and phone:
        tl_times = [p[0] for p in tl]
        dists = []
        for t, lat, lng in phone:
            j = nearest_index(tl_times, t)
            if j is not None and abs(tl_times[j] - t) <= timedelta(minutes=5):
                dists.append(distance_m(lat, lng, tl[j][1], tl[j][2]))
        if dists:
            dists.sort()
            med, p90 = dists[len(dists) // 2], dists[int(len(dists) * 0.9)]
            out(f"\n== Genauigkeit Zeitachse (gegen {len(dists)} Fotos mit GPS, Abstand ≤ 5 min): "
                f"Median {med:.0f} m, 90 % unter {p90:.0f} m")

    # --- Kamera-Uhr: welche Verschiebung passt am besten zu den Handyfotos?
    out("\n== Kamera-Uhr (Fotos ohne GPS gegen Fotos mit GPS, Treffer = Handyfoto ≤ 10 min)")
    phone_times = [p[0] for p in phone]
    best_shift = {}
    for model in sorted({p["model"] for p in targets}):
        group = [p for p in targets if p["model"] == model]
        scores = []
        for h in range(-12, 13):
            shift = timedelta(hours=h)
            hits = sum(1 for p in group if (g := nearest_gap(phone_times, p["t"] + shift)) is not None and g <= MATCH)
            scores.append((hits, -abs(h), h))
        scores.sort(reverse=True)
        best = scores[0][2] if scores and scores[0][0] else 0
        best_shift[model] = best
        at0 = next(s[0] for s in scores if s[2] == 0)
        top = ", ".join(f"{s[2]:+d} h: {s[0]}" for s in scores[:3])
        out(f"  {model} ({len(group)} ohne GPS): ohne Verschiebung {at0} Treffer · beste: {top}")
        if best != 0 and scores[0][0] > at0 * 1.5:
            out(f"    ⚠ Die Kamera-Uhr ging vermutlich um {abs(best)} h {'nach' if best > 0 else 'vor'} "
                f"(z. B. Heimatzeit statt Ortszeit).")

    # --- Abdeckung: wie nah liegt ein Bezugspunkt?
    all_ref = sorted([p[0] for p in phone] + [p[0] for p in tl])
    out("\n== Abdeckung der Fotos ohne GPS (Abstand zum nächsten Punkt)")
    for label, ref, use_shift in (("nur Fotos mit GPS", phone_times, False),
                                  ("Fotos mit GPS + Zeitachse", all_ref, False),
                                  ("Fotos mit GPS + Zeitachse, Kamera-Uhr korrigiert", all_ref, True)):
        if use_shift and not any(best_shift.values()):
            continue
        c = Counter(bucket(nearest_gap(ref, p["t"] + timedelta(hours=best_shift.get(p["model"], 0) if use_shift else 0)))
                    for p in targets)
        out(f"  {label}: " + " · ".join(f"{b} {c[b]}" for b in BUCKETS if c[b]))

    # --- GPS-Spur zum Ausprobieren
    points = [(t, lat, lng) for t, lat, lng in phone] + tl
    if points:
        GPX_DIR.mkdir(exist_ok=True)
        name = re.sub(r'[\\/:*?"<>|]+', "_", folders.most_common(1)[0][0].split("\\")[-1])
        gpx = GPX_DIR / f"{name}.gpx"
        segs = write_gpx(gpx, points)
        out(f"\n== GPS-Spur geschrieben: {len(points)} Punkte in {segs} Abschnitten → gpx\\{gpx.name} "
            "(bleibt auf dem PC)")
    out(f"\nFertig in {time.time() - started:.0f} s. Bitte nur diese Datei an Claude schicken: {OUT_FILE.name} "
        "(enthält keine Koordinaten).")
    OUT_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
