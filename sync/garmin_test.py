"""Fotoschatz - Garmin-Test (Diagnose, aendert nichts).

Prueft, ob Garmin-Aktivitaeten (GPS-Uhr) Fotos ohne GPS einen Ort geben koennen:
  1. Persoenlichen API-Schluessel aus _sync\\garmin_api_key.txt lesen (bleibt auf dem PC)
  2. Bei Garmin anmelden (nur lesen) und die Liste aller Aktivitaeten holen
  3. Probe: die neueste Aktivitaet mit GPS herunterladen - nur im Speicher, wird NICHT gespeichert
  4. Katalog-Kopie lesen: wie viele Fotos ohne GPS liegen zeitlich in einer Aktivitaet?
Ergebnis: garmin_test.txt (nur Anzahlen, Jahre, Ordnernamen - keine Koordinaten, kein Schluessel).
Schreibt nie in Fotos, Katalog oder Originale.
"""
__version__ = "0.7.21"

import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import katalog

SCRIPT_DIR = Path(__file__).resolve().parent
KEY_FILE = SCRIPT_DIR / "garmin_api_key.txt"
OUT_FILE = SCRIPT_DIR / "garmin_test.txt"
DEFAULTS = {"catalog": katalog.DEFAULT_CATALOG, "originals_dir": r"D:\Bilder - Raw"}
BASE_URL = (os.environ.get("GARMIN_PERSONAL_API_BASE_URL") or "https://personal.connectapi.garmin.com").rstrip("/")
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
LIST_PATH = "/activitylist-service/activities/search/activities"
DOWNLOAD_PATH = "/download-service/files/activity/{}"
PAGE = 100                    # Aktivitaeten je Abfrage (Garmin liefert evtl. weniger - dann eben mehr Abfragen)
MAX_PAGES = 1000
NEAR = timedelta(hours=1)     # Foto hoechstens so weit vor/nach einer Aktivitaet
USER_AGENT = "fotoschatz-garmin-test/" + __version__

KEY_HELP = """# Fotoschatz - persoenlicher Garmin-API-Schluessel
# Diese Datei bleibt auf deinem PC (sie kommt nie ins Repo und wird von aktualisieren.bat nicht angefasst).
#
# So geht's:
#   1. Garmin Connect (Webseite) > Einstellungen > Persoenlicher API-Schluessel > Schluessel kopieren
#   2. Den Schluessel unten in eine eigene Zeile einfuegen (ohne # davor), speichern
#   3. garmin_test.bat noch einmal doppelklicken
#
# Zeilen mit # am Anfang werden ignoriert.

"""

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def save_and_exit(code):
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nErgebnis gespeichert: {OUT_FILE}")
    sys.exit(code)


def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return cfg


def read_key():
    """Schluessel aus garmin_api_key.txt; fehlt die Datei, wird sie mit Anleitung angelegt."""
    if not KEY_FILE.exists():
        KEY_FILE.write_text(KEY_HELP, encoding="utf-8")
        return None
    raw = KEY_FILE.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("apikey "):        # falls mit "ApiKey " davor kopiert
            line = line[7:].strip()
        return line.strip("\"'") or None
    return None


class GarminError(Exception):
    pass


def request(method, path, headers, params=None, accept="application/json"):
    url = BASE_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None,
                                 headers=dict(headers, Accept=accept, **{"User-Agent": USER_AGENT}))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        body = ""
        try:
            body = err.read().decode("utf-8", "replace").strip().replace("\n", " ")[:200]
        except Exception:
            pass
        raise GarminError(f"Garmin antwortet {err.code} {err.reason} auf {path}" + (f" – {body}" if body else ""))
    except urllib.error.URLError as err:
        raise GarminError(f"Keine Verbindung zu Garmin ({err.reason})")


def parse_local(value):
    """'2023-05-08 07:43:01' oder '2023-05-08T07:43:01.0' -> datetime"""
    try:
        return datetime.strptime(str(value).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def type_key(act):
    t = act.get("activityType")
    if isinstance(t, dict):
        return t.get("typeKey") or "(unbekannt)"
    return str(t or "(unbekannt)")


def years_text(counter):
    return ", ".join(f"{y}: {n}" for y, n in sorted(counter.items()))


def main():
    started = time.time()
    out(f"garmin_test.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')}")
    out("Prüft nur – speichert keine Garmin-Daten und ändert nichts.")

    # --- 1. Schluessel
    key = read_key()
    if not key:
        out(f"\nKein API-Schlüssel gefunden. Die Datei ist jetzt angelegt:\n  {KEY_FILE}")
        out("Dort den Schlüssel einfügen (Anleitung steht in der Datei), speichern, garmin_test.bat noch einmal starten.")
        save_and_exit(1)
    out(f"\n== 1. API-Schlüssel: gefunden ({len(key)} Zeichen)")

    # --- 2. Anmelden + Aktivitaeten
    try:
        token = request("POST", TOKEN_PATH, {"Authorization": f"ApiKey {key}"}, accept="*/*").decode("ascii", "replace").strip()
    except GarminError as err:
        out(f"\nFEHLER bei der Anmeldung: {err}")
        out("Schlüssel abgelaufen, gelöscht oder falsch kopiert? In Garmin Connect prüfen.")
        save_and_exit(1)
    if token.count(".") != 2:
        out(f"\nFEHLER: Garmin hat keinen gültigen Zugangsschein geschickt (Antwort {len(token)} Zeichen).")
        save_and_exit(1)
    out("== 2. Anmeldung bei Garmin: ok")
    auth = {"Authorization": f"Bearer {token}"}

    acts, seen, start, pages = [], set(), 0, 0
    first_keys = []
    try:
        while pages < MAX_PAGES:
            data = json.loads(request("GET", LIST_PATH, auth, {"start": start, "limit": PAGE}) or b"[]")
            pages += 1
            if isinstance(data, dict):                    # falls in einer Huelle geliefert
                data = data.get("activities") or data.get("activityList") or []
            if not data:
                break
            new = [a for a in data if isinstance(a, dict) and a.get("activityId") not in seen]
            if not new:
                break
            if not first_keys:
                first_keys = sorted(new[0].keys())
            for a in new:
                seen.add(a.get("activityId"))
            acts.extend(new)
            start += len(data)
            print(f"\r  Aktivitäten geholt: {len(acts)} …", end="", flush=True)
    except (GarminError, json.JSONDecodeError) as err:
        print()
        out(f"\nFEHLER beim Holen der Aktivitäten (nach {len(acts)}): {err}")
        save_and_exit(1)
    print()
    out(f"   Aktivitäten gesamt: {len(acts)} ({pages} Abfragen)")
    if not acts:
        out("   Garmin liefert keine Aktivitäten – nichts zu tun.")
        save_and_exit(0)

    windows = []          # (Start Ortszeit, Ende Ortszeit, hat GPS, Typ)
    no_time = 0
    for a in acts:
        t0 = parse_local(a.get("startTimeLocal"))
        if not t0:
            no_time += 1
            continue
        dur = a.get("elapsedDuration") or a.get("duration") or 0
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = 0.0
        if dur > 100000:               # manche Felder kommen in Millisekunden
            dur /= 1000.0
        has_gps = bool(a.get("hasPolyline")) or a.get("startLatitude") is not None
        windows.append((t0, t0 + timedelta(seconds=dur), has_gps, type_key(a), a.get("activityId")))
    windows.sort()
    with_gps = [w for w in windows if w[2]]
    out(f"   Zeitraum: {windows[0][0]:%d.%m.%Y} – {windows[-1][0]:%d.%m.%Y}" + (f" ({no_time} ohne Startzeit)" if no_time else ""))
    out(f"   mit GPS-Spur: {len(with_gps)} · ohne (z. B. Laufband, Krafttraining): {len(windows) - len(with_gps)}")
    out("   je Jahr (mit GPS): " + years_text(Counter(w[0].year for w in with_gps)))
    out("   Arten (mit GPS): " + ", ".join(f"{k} {n}" for k, n in Counter(w[3] for w in with_gps).most_common(12)))
    hours = sum((w[1] - w[0]).total_seconds() for w in with_gps) / 3600
    out(f"   Dauer mit GPS zusammen: {hours:.0f} h")
    out("   Felder je Aktivität (nur Namen, zur Kontrolle): " + ", ".join(first_keys))

    # --- 3. Download-Probe (nur im Speicher)
    out("\n== 3. Probe-Download (neueste Aktivität mit GPS, nur im Speicher, nicht gespeichert)")
    if not with_gps:
        out("   übersprungen – keine Aktivität mit GPS")
    else:
        probe = with_gps[-1]
        try:
            blob = request("GET", DOWNLOAD_PATH.format(probe[4]), auth,
                           accept="application/zip, application/x-zip-compressed, application/octet-stream")
            out(f"   {probe[3]} vom {probe[0]:%d.%m.%Y}: {len(blob) / 1024:.0f} KB")
            if blob[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    for info in z.infolist():
                        head = z.read(info.filename)[:14]
                        fit = len(head) >= 12 and head[8:12] == b".FIT"
                        out(f"   im ZIP: Endung {Path(info.filename).suffix.lower() or '(keine)'}, "
                            f"{info.file_size / 1024:.0f} KB" + (" – FIT-Datei erkannt" if fit else ""))
            else:
                out(f"   kein ZIP (Anfang {blob[:4]!r})")
        except (GarminError, zipfile.BadZipFile) as err:
            out(f"   FEHLER: {err}")

    # --- 4. Katalog: Fotos ohne GPS in einer Aktivitaet?
    out("\n== 4. Fotos ohne GPS im Lightroom-Katalog (Kopie)")
    cfg = load_config()
    try:
        _catalog, _copy, db = katalog.prepare(cfg["catalog"], protected=[cfg["originals_dir"]])
    except katalog.CatalogError as err:
        out(f"   FEHLER: {err}")
        save_and_exit(1)
    import lightroom_pruefen                   # spaet, wie in uebersicht.py
    c = lightroom_pruefen.read_catalog(db, cfg)
    db.close()
    imgs = [i for i in c["images"] if i["gallery"] and i["pick"] != -1 and i["time"]]
    targets = [i for i in imgs if not i["gps"] and not i["ok"]]
    out(f"   Bilder für die Galerie: {len(imgs)} · ohne GPS (ohne ort-egal): {len(targets)}")

    starts = [w[0] for w in with_gps]
    first_act = starts[0] if starts else None

    def classify(t):
        """inside = waehrend einer Aktivitaet, near = hoechstens 1 h davor/danach, None = nichts"""
        k = bisect_right(starts, t + NEAR)
        best = None
        for w in with_gps[max(0, k - 50):k]:
            if w[0] <= t <= w[1]:
                return "inside"
            if w[0] - NEAR <= t <= w[1] + NEAR:
                best = "near"
        return best

    result = Counter()
    by_folder = {}
    by_year = {}
    for i in targets:
        if first_act and i["time"] < first_act - NEAR:
            kind = "before"
        else:
            kind = classify(i["time"]) or "none"
        result[kind] += 1
        f = lightroom_pruefen.show(i["folder"])
        by_folder.setdefault(f, Counter())[kind] += 1
        by_year.setdefault(i["time"].year, Counter())[kind] += 1

    if first_act:
        out(f"   erste Garmin-Aktivität mit GPS: {first_act:%d.%m.%Y}")
    out(f"   → während einer Aktivität:        {result['inside']}")
    out(f"   → bis 1 h davor/danach:            {result['near']}")
    out(f"   → keine Aktivität in der Nähe:     {result['none']}")
    out(f"   → vor der ersten Garmin-Aktivität: {result['before']}")
    out("\n   je Jahr (während · ±1 h · nichts · vorher):")
    for y in sorted(by_year):
        c_ = by_year[y]
        out(f"     {y}: {c_['inside']} · {c_['near']} · {c_['none']} · {c_['before']}")
    hits = sorted(((f, c_) for f, c_ in by_folder.items() if c_["inside"] + c_["near"]),
                  key=lambda x: -(x[1]["inside"] + x[1]["near"]))
    out(f"\n   Ordner mit Treffern ({len(hits)}; während · ±1 h · von ohne GPS):")
    for f, c_ in hits[:40]:
        out(f"     {f}: {c_['inside']} · {c_['near']} · von {sum(c_.values())}")
    if len(hits) > 40:
        out(f"     … und {len(hits) - 40} weitere Ordner")
    out("\n   Hinweis: Ging die Kamera-Uhr falsch, stimmen die Zahlen nicht (gps_test prüft die Uhr).")

    out(f"\nFertig in {time.time() - started:.0f} s. Bitte garmin_test.txt an Claude schicken (enthält keine Koordinaten und keinen Schlüssel).")
    save_and_exit(0)


if __name__ == "__main__":
    main()
