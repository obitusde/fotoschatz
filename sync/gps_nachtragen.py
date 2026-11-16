"""Fotoschatz - GPS nachtragen (alle Fotos ohne GPS auf einmal).

Baut EINE GPS-Spur (GPX) fuer alle Fotos ohne GPS im Lightroom-Katalog - die Zuordnung machst du danach einmal
in Lightroom (Map > Tracklog > Auto-Tag). Quellen, beste zuerst:
  1. Garmin-Aktivitaeten (GPS-Uhr): nur die, die zeitlich zu Fotos ohne GPS passen (±1 h), werden geladen
     und in _sync\\garmin\\ aufbewahrt (beim naechsten Lauf nicht noch einmal)
  2. Fotos MIT GPS aus dem ganzen Katalog (meist Handyfotos)
  3. Google-Zeitachse (_sync\\google\\*.json)
Liegt vor und nach einer Luecke (bis 3 h) derselbe Ort (<= 1 km), wird sie aufgefuellt (z. B. Kaffee nach der Tour).
Ergebnis: gpx\\ohne_gps.gpx (bleibt auf dem PC) und gps_nachtragen.txt (Anzahlen, Ordner, Dateinamen - keine
Koordinaten). Schreibt nie in Fotos, Katalog oder Originale.
Scans (Aufnahme vor 2000, meist Ersatzdatum) kommen nicht in die Spur - nur in die Liste zum Selbst-Zuordnen.
Lightroom zieht bei Auto-Tag ueber JEDE Luecke eine gerade Linie (am PC gesehen 16.11.2026) - deshalb: Luecken mit
Ort davor und danach <= 5 km (bis 24 h) werden ueberbrueckt (ungefaehr), alle anderen Fotos bleiben offen, und die
Auswahl in Lightroom geht ueber eine Liste der Dateinamen (nur gute und ungefaehre Fotos).
Seit 0.7.25 eine GPX-Datei je Ordner (gpx\\nachtragen\\<Ordner>.gpx, Spur heisst wie der Ordner, alle Tage in
einer Spur) - so sieht man auf der Karte, was man an diesen Tagen gemacht hat.
"""
__version__ = "0.7.25"

import json
import struct
import sys
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import katalog
import garmin_test as garmin
import gps_test

SCRIPT_DIR = Path(__file__).resolve().parent
GARMIN_DIR = SCRIPT_DIR / "garmin"
GOOGLE_DIR = SCRIPT_DIR / "google"
GPX_FILE = SCRIPT_DIR / "gpx" / "ohne_gps.gpx"         # bis 0.7.24 eine Datei fuer alles - wird geloescht
GPX_DIR = SCRIPT_DIR / "gpx" / "nachtragen"             # seit 0.7.25 eine Datei je Ordner
OUT_FILE = SCRIPT_DIR / "gps_nachtragen.txt"
DEFAULTS = {"catalog": katalog.DEFAULT_CATALOG, "originals_dir": r"D:\Bilder - Raw"}

NEAR = timedelta(hours=1)            # Garmin-Aktivitaet hoechstens so weit vor/nach einem Foto -> laden
CONTEXT = timedelta(hours=24)        # Handyfotos/Zeitachse so weit um die Fotos herum (fuer Luecken: Punkt davor/danach)
SEGMENT_GAP = timedelta(hours=1)     # laengere Luecke (nicht aufgefuellt) = Spur unterbrochen -> Foto bleibt offen
GARMIN_STEP = 10                     # Garmin-Punkte hoechstens alle 10 s (Datei bleibt klein, genau genug)
GOOD = timedelta(minutes=15)         # Punkt so nah am Foto -> Ort gut
MAX_OPEN_LIST = 300                  # so viele offene Fotos werden mit Dateinamen aufgezaehlt
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
SCAN_BEFORE = datetime(2000, 1, 1)    # aelter = Scan (Aufnahmezeit meist Ersatzdatum) -> nicht ueber die Spur
SOURCE_ORDER = ["Garmin", "Handyfoto", "Zeitachse", "Lücke aufgefüllt"]
BRIDGE_TIME = timedelta(hours=24)    # Luecke so lang und ...
BRIDGE_DIST = 5000                   # ... Ort davor und danach hoechstens so weit auseinander -> ueberbruecken (ungefaehr)
PICK_CHUNK = 40                      # so viele Dateinamen je Zeile fuer den Lightroom-Filter
FILE_CONTEXT = timedelta(hours=3)    # Spur je Ordner: Punkte so weit um seine Fotos herum

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def save_and_exit(code):
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nErgebnis gespeichert: {OUT_FILE}")
    sys.exit(code)


# ---------------------------------------------------------------- FIT-Datei lesen (nur GPS-Punkte)

def fit_points(data):
    """GPS-Punkte (UTC, lat, lng) aus einer FIT-Datei (Garmin). Gelesen werden nur 'record'-Nachrichten
    (Nr. 20) mit Zeit (Feld 253) und Position (Felder 0/1, Semicircles). Mehrere FIT-Teile hintereinander gehen."""
    pts = []
    pos = 0
    while pos + 12 <= len(data):
        head_size = data[pos]
        if data[pos + 8:pos + 12] != b".FIT" or head_size < 12:
            break
        data_size = struct.unpack_from("<I", data, pos + 4)[0]
        start, end = pos + head_size, min(pos + head_size + data_size, len(data))
        _read_fit_records(data, start, end, pts)
        pos = end + 2                                   # 2 Byte Pruefsumme
    return pts


def _read_fit_records(data, i, end, pts):
    defs = {}                                           # lokale Nr. -> (Endian, globale Nr., Felder, Zusatzbytes)
    last_ts = None
    while i < end:
        h = data[i]
        i += 1
        if h & 0x80:                                    # kompakter Zeitstempel
            local = (h >> 5) & 0x03
            offset = h & 0x1F
            if last_ts is not None:
                ts = (last_ts & ~0x1F) + offset
                if offset < (last_ts & 0x1F):
                    ts += 0x20
                last_ts = ts
            d = defs.get(local)
            if d is None:
                return
            i = _read_fit_data(data, i, d, pts, last_ts)
            continue
        local = h & 0x0F
        if h & 0x40:                                    # Definition
            if i + 5 > end:
                return
            endian = ">" if data[i + 1] == 1 else "<"
            gnum = struct.unpack_from(endian + "H", data, i + 2)[0]
            n = data[i + 4]
            i += 5
            fields = []
            for _ in range(n):
                fields.append((data[i], data[i + 1]))   # Feldnummer, Groesse
                i += 3
            extra = 0
            if h & 0x20:                                # Entwicklerfelder
                nd = data[i]
                i += 1
                for _ in range(nd):
                    extra += data[i + 1]
                    i += 3
            defs[local] = (endian, gnum, fields, extra)
        else:
            d = defs.get(local)
            if d is None:
                return
            ts_before = last_ts
            i, ts = _read_fit_data(data, i, d, pts, None, want_ts=True)
            last_ts = ts if ts is not None else ts_before


def _read_fit_data(data, i, d, pts, ts, want_ts=False):
    endian, gnum, fields, extra = d
    lat = lng = None
    own_ts = None
    for num, size in fields:
        if num == 253 and size == 4:
            v = struct.unpack_from(endian + "I", data, i)[0]
            if v != 0xFFFFFFFF:
                own_ts = v
        elif gnum == 20 and num in (0, 1) and size == 4:
            v = struct.unpack_from(endian + "i", data, i)[0]
            if v != 0x7FFFFFFF:
                if num == 0:
                    lat = v * 180.0 / 2 ** 31
                else:
                    lng = v * 180.0 / 2 ** 31
        i += size
    i += extra
    t = own_ts if own_ts is not None else ts
    if gnum == 20 and t is not None and lat is not None and lng is not None \
            and -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0):
        pts.append((FIT_EPOCH + timedelta(seconds=t), lat, lng))
    return (i, own_ts) if want_ts else i


# ---------------------------------------------------------------- Hilfen

def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return cfg


def windows_merge(times, pad):
    """Zeitpunkte -> zusammengelegte Zeitfenster [t - pad, t + pad]."""
    res = []
    for t in sorted(times):
        a, b = t - pad, t + pad
        if res and a <= res[-1][1]:
            res[-1][1] = max(res[-1][1], b)
        else:
            res.append([a, b])
    return res


def inside(windows, t):
    k = bisect_right([w[0] for w in windows], t) - 1
    return k >= 0 and t <= windows[k][1]


def fill_gaps(points):
    """Wie gps_test.fill_gaps, aber mit Quelle: (Ortszeit, lat, lng, Quelle)."""
    pts = sorted(points)
    extra, gaps = [], 0
    for a, b in zip(pts, pts[1:]):
        span = b[0] - a[0]
        if gps_test.GAP_FILL_MIN < span <= gps_test.GAP_FILL_MAX and \
                gps_test.distance_m(a[1], a[2], b[1], b[2]) <= gps_test.GAP_FILL_DIST:
            gaps += 1
            k = 1
            while a[0] + gps_test.STAY_STEP * k < b[0]:
                f = (gps_test.STAY_STEP * k) / span
                extra.append((a[0] + gps_test.STAY_STEP * k, a[1] + (b[1] - a[1]) * f,
                              a[2] + (b[2] - a[2]) * f, "Lücke aufgefüllt"))
                k += 1
    return sorted(pts + extra), gaps


def segments(points):
    """Abschnitte der Spur (Zeit von, bis) - getrennt bei Luecken > SEGMENT_GAP."""
    segs = []
    for p in points:
        if segs and p[0] - segs[-1][1] <= SEGMENT_GAP:
            segs[-1][1] = p[0]
        else:
            segs.append([p[0], p[0]])
    return segs


def pc_offset(local):
    """UTC-Abstand der PC-Zeitzone fuer eine Ortszeit ohne Zeitzone (so liest Lightroom die Aufnahmezeit).
    Windows kann das vor 1970 nicht (OSError 22) -> dann derselbe Kalendertag im Jahr 2000."""
    try:
        return local.astimezone().utcoffset()
    except (OSError, OverflowError, ValueError):
        return local.replace(year=2000).astimezone().utcoffset()


def xml_text(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def safe_name(text):
    """Dateiname fuer Windows: verbotene Zeichen ersetzen."""
    out_ = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in text).strip(" .")
    return out_ or "Ordner"


def write_gpx(path, points, name):
    """GPS-Spur; Zeiten = Ortszeit der Fotos, umgerechnet ueber die PC-Zeitzone (so liest Lightroom die
    Aufnahmezeit - am PC bestaetigt 01.10.2026 mit gps_test). Neuer Abschnitt nach Luecken > SEGMENT_GAP."""
    path.parent.mkdir(exist_ok=True)
    w = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="Fotoschatz gps_nachtragen" xmlns="http://www.topografix.com/GPX/1/1">',
         f"<trk><name>{xml_text(name)}</name>"]                   # eine Spur je Ordner, alle Tage zusammen
    last, nseg = None, 0
    for local, lat, lng, _src in points:
        if last is None or local - last > SEGMENT_GAP:
            if last is not None:
                w.append("</trkseg>")
            nseg += 1
            w.append("<trkseg>")
        utc = local - pc_offset(local)                  # naive = PC-Zeitzone
        w.append(f'<trkpt lat="{lat:.6f}" lon="{lng:.6f}"><time>{utc:%Y-%m-%dT%H:%M:%SZ}</time></trkpt>')
        last = local
    if last is not None:
        w.append("</trkseg>")
    w.append("</trk></gpx>")
    path.write_text("\n".join(w), encoding="utf-8")
    return nseg


def nearest(times, t):
    i = bisect_left(times, t)
    cands = [j for j in (i - 1, i) if 0 <= j < len(times)]
    return min(cands, key=lambda j: abs(times[j] - t)) if cands else None


def list_scans(scans):
    if not scans:
        return
    import lightroom_pruefen
    out(f"\n== Scans vor 2000 ({len(scans)}) – von Hand auf die Karte ziehen oder Stichwort ort-egal")
    by = defaultdict(list)
    for i in scans:
        by[lightroom_pruefen.show(i["folder"])].append(i)
    for folder in sorted(by):
        out(f"   {folder}")
        for i in sorted(by[folder], key=lambda x: x["time"]):
            out(f"     {i['file']}  ({i['time']:%d.%m.%Y %H:%M}, {i['model']})")


# ---------------------------------------------------------------- Ablauf

def main():
    started = time.time()
    out(f"gps_nachtragen.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')}")
    out("Baut eine GPS-Spur für alle Fotos ohne GPS. Ändert nichts – die Zuordnung machst du in Lightroom.")
    cfg = load_config()

    # --- 1. Katalog
    out("\n== 1. Lightroom-Katalog (Kopie)")
    try:
        _catalog, _copy, db = katalog.prepare(cfg["catalog"], protected=[cfg["originals_dir"]])
    except katalog.CatalogError as err:
        out(f"   FEHLER: {err}")
        save_and_exit(1)
    import lightroom_pruefen                   # spaet, wie in uebersicht.py
    c = lightroom_pruefen.read_catalog(db, cfg)
    db.close()
    imgs = [i for i in c["images"] if i["time"]]
    targets = [i for i in imgs if i["gallery"] and i["pick"] != -1 and not i["gps"] and not i["ok"]]
    out(f"   Fotos ohne GPS (Galerie, ohne ort-egal): {len(targets)}")
    scans = [i for i in targets if i["time"] < SCAN_BEFORE]
    targets = [i for i in targets if i["time"] >= SCAN_BEFORE]
    if scans:
        out(f"   davon Scans (Aufnahme vor 2000): {len(scans)} – nicht über die Spur (Datum meist geschätzt), "
            "Liste unten")
    if not targets:
        out("   Nichts zu tun.")
        list_scans(scans)
        save_and_exit(0)
    first_t, last_t = min(i["time"] for i in targets), max(i["time"] for i in targets)
    near_win = windows_merge([i["time"] for i in targets], NEAR)
    ctx_win = windows_merge([i["time"] for i in targets], CONTEXT)
    phone = sorted((i["time"], float(i["lat"]), float(i["lng"]), i["file"]) for i in imgs
                   if i["gps"] and i["lat"] is not None and i["lng"] is not None and i["time"] >= SCAN_BEFORE)

    # --- 2. Garmin
    out("\n== 2. Garmin (GPS-Uhr)")
    garmin_pts, garmin_spans, garmin_offsets = [], [], []
    key = garmin.read_key()
    if not key:
        out(f"   kein API-Schlüssel in {garmin.KEY_FILE.name} – Garmin wird übersprungen "
            "(Anleitung steht in der Datei, siehe garmin_test.bat)")
    else:
        try:
            auth = garmin.login(key)
            acts, _pages = garmin.list_activities(auth)
        except garmin.GarminError as err:
            out(f"   FEHLER: {err} – Garmin wird übersprungen")
            acts, auth = [], None
        wanted = []
        for a in acts:
            t0 = garmin.parse_local(a.get("startTimeLocal"))
            g0 = garmin.parse_local(a.get("startTimeGMT"))
            if not t0 or not (a.get("hasPolyline") or a.get("startLatitude") is not None):
                continue
            try:
                dur = float(a.get("elapsedDuration") or a.get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0.0
            if dur > 100000:
                dur /= 1000.0
            t1 = t0 + timedelta(seconds=dur)
            # passt zu einem Foto ohne GPS: Foto zwischen Start - 1 h und Ende + 1 h
            if any(t0 - NEAR <= w[1] and w[0] <= t1 + NEAR for w in near_win):
                offset = (t0 - g0) if g0 else None
                if offset is not None:
                    offset = timedelta(minutes=round(offset.total_seconds() / 900) * 15)
                wanted.append((t0, t1, a.get("activityId"), offset))
        out(f"   Aktivitäten bei Garmin: {len(acts)} · passend zu Fotos ohne GPS (±1 h): {len(wanted)}")
        GARMIN_DIR.mkdir(exist_ok=True)
        loaded = cached = failed = 0
        for t0, t1, aid, offset in sorted(wanted):
            path = GARMIN_DIR / f"{int(aid)}.fit"
            if path.exists() and path.stat().st_size > 0:
                fit = path.read_bytes()
                cached += 1
            else:
                try:
                    fit = garmin.download_fit(auth, aid)
                except garmin.GarminError as err:
                    out(f"   ⚠ Aktivität vom {t0:%d.%m.%Y %H:%M} nicht geladen: {err}")
                    failed += 1
                    continue
                if not fit:
                    out(f"   ⚠ Aktivität vom {t0:%d.%m.%Y %H:%M}: keine FIT-Datei im Download")
                    failed += 1
                    continue
                path.write_bytes(fit)
                loaded += 1
            pts = fit_points(fit)
            if not pts:
                continue
            if offset is None:                       # Ortszeit unbekannt -> aus Startzeit und erstem Punkt schaetzen
                offset = timedelta(minutes=round(((t0 - pts[0][0].replace(tzinfo=None)).total_seconds()) / 900) * 15)
            garmin_offsets.append((t0, offset))
            last = None
            seg = []
            for utc, lat, lng in pts:
                if last is not None and (utc - last).total_seconds() < GARMIN_STEP:
                    continue
                seg.append((utc.replace(tzinfo=None) + offset, lat, lng, "Garmin"))
                last = utc
            if seg[-1][0] != pts[-1][0].replace(tzinfo=None) + offset:     # letzten Punkt immer behalten
                utc, lat, lng = pts[-1]
                seg.append((utc.replace(tzinfo=None) + offset, lat, lng, "Garmin"))
            garmin_pts += seg
            garmin_spans.append((seg[0][0], seg[-1][0]))
        out(f"   geladen: {loaded} neu · {cached} schon da (_sync\\garmin\\)" + (f" · {failed} Fehler" if failed else "")
            + f" · {len(garmin_pts)} Punkte")

    # --- 3. Handyfotos + Google-Zeitachse um die Fotos herum
    out("\n== 3. Fotos mit GPS und Google-Zeitachse")
    garmin_spans.sort()
    span_starts = [s[0] for s in garmin_spans]

    def in_garmin(t):
        k = bisect_right(span_starts, t) - 1
        return k >= 0 and t <= garmin_spans[k][1]

    refs = [(t, lat, lng, "Handyfoto") for t, lat, lng, _f in phone if inside(ctx_win, t) and not in_garmin(t)]
    out(f"   Fotos mit GPS im Umfeld (±24 h): {len(refs)}")
    files = sorted(GOOGLE_DIR.glob("*.json")) if GOOGLE_DIR.is_dir() else []
    tl_count = 0
    if not files:
        out("   keine Google-Zeitachse (_sync\\google\\*.json)")
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as err:
            out(f"   {f.name}: nicht lesbar ({err})")
            continue
        pts, _info = gps_test.timeline_points(data)
        del data
        n0 = len(refs)
        refs += [(p[0], p[2], p[3], "Zeitachse") for p in pts if inside(ctx_win, p[0]) and not in_garmin(p[0])]
        tl_count += len(refs) - n0
        out(f"   {f.name}: {len(pts)} Punkte, davon im Umfeld der Fotos {len(refs) - n0}")

    # --- 4. Spur bauen
    points, gaps = fill_gaps(garmin_pts + refs)
    times = [p[0] for p in points]
    segs = segments(points)
    seg_starts = [s[0] for s in segs]

    def covered(t):
        k = bisect_right(seg_starts, t) - 1
        return k >= 0 and t <= segs[k][1]

    result = Counter()
    by_folder = defaultdict(Counter)
    open_list = defaultdict(list)
    gap_rows = defaultdict(list)          # Ordner -> (Foto, Luecke, km, Art) fuer Fotos zwischen zwei Abschnitten
    bridges = set()
    pick = defaultdict(list)              # Ordner -> Dateinamen (ohne Endung) fuer die Auswahl in Lightroom
    folder_times = defaultdict(list)      # Ordner -> Aufnahmezeiten seiner Fotos ohne GPS
    for i in sorted(targets, key=lambda x: x["time"]):
        t = i["time"]
        j = nearest(times, t)
        gap = abs(times[j] - t) if j is not None else None
        folder = lightroom_pruefen.show(i["folder"])
        if gap is not None and gap <= GOOD:
            kind = points[j][3]
        elif gap is not None and covered(t):
            kind = "ungefähr"
        else:
            # zwischen zwei Abschnitten: Lightroom wuerde eine gerade Linie ziehen - taugt das?
            k = bisect_right(times, t)
            if 0 < k < len(points):
                a, b = points[k - 1], points[k]
                span = b[0] - a[0]
                dist = gps_test.distance_m(a[1], a[2], b[1], b[2])
                kind = "überbrückt" if span <= BRIDGE_TIME and dist <= BRIDGE_DIST else "offen"
                if kind == "überbrückt":
                    bridges.add((k - 1, k))
                gap_rows[folder].append((i, span, dist, kind))
            else:
                kind = "offen"
                gap_rows[folder].append((i, None, None, kind))
        if kind == "offen":
            open_list[folder].append(i)
        else:
            pick[folder].append(Path(i["file"]).stem)
        folder_times[folder].append(t)
        result[kind] += 1
        by_folder[folder][kind] += 1

    # ueberbrueckte Luecken als Punkte in die Spur (alle 10 min, gerade Linie wie Lightroom)
    extra = []
    for k0, k1 in sorted(bridges):
        a, b = points[k0], points[k1]
        span, n = b[0] - a[0], 1
        while a[0] + gps_test.STAY_STEP * n < b[0]:
            f = (gps_test.STAY_STEP * n) / span
            extra.append((a[0] + gps_test.STAY_STEP * n, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f,
                          "Lücke überbrückt"))
            n += 1
    points = sorted(points + extra)

    ok = sum(result[s] for s in SOURCE_ORDER)
    out(f"\n== 4. Ergebnis für {len(targets)} Fotos ohne GPS")
    out(f"   Ort gut (Punkt ≤ 15 min daneben): {ok}"
        + (" – " + ", ".join(f"{s} {result[s]}" for s in SOURCE_ORDER if result[s]) if ok else ""))
    out(f"   ungefähr: {result['ungefähr'] + result['überbrückt']} – zwischen zwei Punkten bis 1 h: {result['ungefähr']}, "
        f"Lücke überbrückt (Ort davor und danach ≤ 5 km, bis 24 h): {result['überbrückt']}")
    out(f"   offen (keine Spur in der Nähe oder Ort davor/danach weit auseinander): {result['offen']}")
    if gaps:
        out(f"   Lücken aufgefüllt: {gaps} (Ort davor und danach ≤ 1 km, Lücke ≤ 3 h)")

    out("\n   je Ordner (gut · ungefähr · offen · von):")
    for folder, c_ in sorted(by_folder.items(), key=lambda x: (-sum(x[1][s] for s in SOURCE_ORDER), x[0])):
        good = sum(c_[s] for s in SOURCE_ORDER)
        src = ", ".join(f"{s} {c_[s]}" for s in SOURCE_ORDER if c_[s])
        out(f"     {folder}: {good} · {c_['ungefähr'] + c_['überbrückt']} · {c_['offen']} · von {sum(c_.values())}"
            + (f"  ({src})" if src else ""))

    if gap_rows:
        out("\n   Fotos zwischen zwei Abschnitten der Spur – Lightroom würde hier eine gerade Linie ziehen:")
        out("   (Lücke = Zeit zwischen dem Punkt davor und danach · Abstand = wie weit diese beiden Punkte auseinanderliegen)")
        shown = 0
        for folder in sorted(gap_rows):
            out(f"   {folder}")
            for i, span, dist, kind in gap_rows[folder]:
                if shown >= MAX_OPEN_LIST:
                    break
                shown += 1
                if span is None:
                    why = "vor dem ersten bzw. nach dem letzten Punkt der Spur → offen"
                else:
                    h = span.total_seconds() / 3600
                    lucke = f"{h:.1f} h".replace(".", ",") if h < 48 else f"{h / 24:.0f} Tage"
                    km = f"{dist / 1000:.1f} km".replace(".", ",")
                    why = f"Lücke {lucke}, Abstand {km} → " + (
                        "überbrückt (ungefähr richtig)" if kind == "überbrückt" else
                        "offen (zu weit auseinander – Lightroom würde raten)" if span <= BRIDGE_TIME else
                        "offen (Lücke zu lang)")
                out(f"     {i['file']}  ({i['time']:%d.%m.%Y %H:%M}): {why}")

    # --- 5. Kamera-Uhr (wie gps_test): falsche Uhr -> Spur passt nicht
    out("\n== 5. Kamera-Uhr")
    phone_files = [(t, f) for t, _lat, _lng, f in phone]
    groups = defaultdict(list)
    for i in targets:
        groups[(lightroom_pruefen.show(i["folder"]), i["model"])].append({"t": i["time"], "file": i["file"]})
    warned = 0
    for (folder, model), group in sorted(groups.items()):
        mid = sorted(g["t"] for g in group)[len(group) // 2]
        delta = None
        near = [o for t0, o in garmin_offsets if abs(t0 - mid) <= timedelta(days=1)]
        if near:
            home = pc_offset(mid)
            delta = round((near[0] - home).total_seconds() / 3600)
        res = gps_test.clock_check(group, phone_files, delta)
        if res["kind"] in ("shift", "odd", "weak"):
            warned += 1
            out(f"   {folder} · {model} ({len(group)} Fotos): {res['text']}")
            if res["kind"] in ("shift", "odd"):
                out(f"     In Lightroom: diese Fotos markieren › Metadata › Edit Capture Time… › Shift by set number "
                    f"of hours: {res['shift']:+g} – danach gps_nachtragen.bat noch einmal.")
            for line in res["evidence"]:
                out(f"     {res['label']}: {line}")
    if not warned:
        out("   keine Hinweise auf eine falsche Kamera-Uhr")

    # --- 6. GPX je Ordner schreiben
    GPX_DIR.mkdir(parents=True, exist_ok=True)
    for old in GPX_DIR.glob("*.gpx"):                 # nur eigene, alte Dateien dieses Unterordners
        old.unlink()
    if GPX_FILE.exists():                             # alte Gesamt-Datei (bis 0.7.24)
        GPX_FILE.unlink()
    ptimes = [p[0] for p in points]
    files, used = {}, set()
    for folder in sorted(pick):
        sel = []
        for a, b in windows_merge(folder_times[folder], FILE_CONTEXT):
            sel += points[bisect_left(ptimes, a):bisect_right(ptimes, b)]
        if not sel:
            continue
        label = folder.replace("/", "\\").split("\\")[-1]
        fname = safe_name(label)
        n = 2
        while fname.lower() in used:
            fname = f"{safe_name(label)} ({n})"
            n += 1
        used.add(fname.lower())
        write_gpx(GPX_DIR / f"{fname}.gpx", sel, label)
        files[folder] = f"{fname}.gpx"
    out(f"\n== 6. GPS-Spuren: {len(files)} Dateien, je Ordner eine → _sync\\gpx\\nachtragen\\ (bleiben auf dem PC)")

    out("\n== So geht's in Lightroom – je Ordner")
    out("   Wichtig: nur die Fotos markieren, die unten genannt sind. Lightroom zieht sonst über jede Lücke eine")
    out("   gerade Linie und rät den Ort.")
    out("   1. Library › Folders › den Ordner anklicken")
    out("   2. Fotos markieren:")
    out("      „alle ohne GPS“ → Library Filter (Taste \\) › Metadata › GPS Data › No Coordinates › Strg+A")
    out("      sonst          → Library Filter › Text › Filename › Contains › die Zeile mit den Namen einfügen › Strg+A")
    out("                       (unten im Filmstreifen sollte etwa die genannte Anzahl stehen)")
    out("   3. Map-Modul › Map › Tracklog › Load Tracklog… › die Datei des Ordners (Spur heißt wie der Ordner)")
    out("   4. Map › Tracklog › Auto-Tag Photos – auf der Karte prüfen (sonst Strg+Z)")
    out("   Zum Schluss gps_nachtragen.bat noch einmal (zeigt, was offen ist), dann Publish und sync.bat.")
    out("   Offene Fotos: in Lightroom auf die Karte ziehen oder Stichwort ort-egal.")
    for folder in sorted(files):
        c_ = by_folder[folder]
        good = sum(c_[x] for x in SOURCE_ORDER)
        approx = c_["ungefähr"] + c_["überbrückt"]
        out(f"\n   ▸ {folder}  ({good} gut, {approx} ungefähr, {c_['offen']} offen)")
        out(f"     Spur: _sync\\gpx\\nachtragen\\{files[folder]}")
        names = pick[folder]
        if not c_["offen"]:
            out(f"     Markieren: alle ohne GPS ({len(names)} Fotos)")
        else:
            chunks = [names[k:k + PICK_CHUNK] for k in range(0, len(names), PICK_CHUNK)]
            for n, chunk in enumerate(chunks, 1):
                part = f" – Teil {n} von {len(chunks)}" if len(chunks) > 1 else ""
                out(f"     Markieren ({len(chunk)} Fotos{part}), Filename › Contains:")
                out("     " + " ".join(chunk))

    if open_list:
        out(f"\n== Offen ({result['offen']}) – Dateien je Ordner")
        shown = 0
        for folder in sorted(open_list):
            out(f"   {folder}")
            for i in open_list[folder]:
                if shown >= MAX_OPEN_LIST:
                    break
                out(f"     {i['file']}  ({i['time']:%d.%m.%Y %H:%M}, {i['model']})")
                shown += 1
        if result["offen"] > shown:
            out(f"   … und {result['offen'] - shown} weitere")

    list_scans(scans)

    out(f"\nFertig in {time.time() - started:.0f} s. Diese Datei (gps_nachtragen.txt) kann an Claude – keine Koordinaten.")
    save_and_exit(0)


if __name__ == "__main__":
    main()
