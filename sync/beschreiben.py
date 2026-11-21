"""Fotoschatz - Bildbeschreibungen mit einem lokalen KI-Modell (Ollama), Test fuer EINEN Ordner.

Nimmt nur die Lightroom-Exporte (D:\\Fotoschatz, 2048 px - nie die Originale), liest dazu den Kontext aus den
Exporten selbst (Ordnername, Aufnahmezeit, Personen von links nach rechts mit Alter, Ort, vorhandene Beschreibung,
schwarz-weiss ja/nein) und laesst das Modell je Bild 1-3 Saetze und Suchbegriffe schreiben. Misst, wie lange das
dauert, und rechnet hoch.

Ergebnis (bleibt auf dem PC): beschreibungen\\<Ordner> (<Modell>).html (Uebersicht mit Vorschaubildern) und .json,
beschreiben.txt (nur Zeiten und Anzahlen, ohne Namen und Beschreibungen - die kann an Claude).
Aendert nichts an Fotos, Katalog, Exporten oder online. Lightroom darf dabei offen sein.

Aufruf: python beschreiben.py [--modell 9b] [Teil des Ordnernamens]
        (ohne Ordner: sucht selbst einen Ordner mit 30-50 Bildern; ohne Modell: qwen3.5:4b bzw. config.local.json)
"""
__version__ = "0.7.28"

import base64
import hashlib
import html
import io
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import regeln

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "beschreibungen"
TXT_FILE = SCRIPT_DIR / "beschreiben.txt"
BIRTHDAY_FILE = SCRIPT_DIR / "geburtstage.txt"      # von sync.py gepflegt, bleibt auf dem PC
DEFAULTS = {
    "export_dir": str(SCRIPT_DIR.parent),
    "work_dir": str(SCRIPT_DIR / "work"),
    "ollama_url": "http://localhost:11434",
    "ollama_model": "",          # leer = automatisch (qwen3.5 mit 4b bevorzugt)
    "beschreiben_px": 1024,      # so gross geht das Bild ans Modell (lange Kante)
}
MIN_PICK, MAX_PICK, TARGET = 30, 50, 40
THUMB_PX = 360
TIMEOUT = 600
SCAN_BEFORE = 2000           # aelter = meist Scan mit Ersatzdatum: kein Wochentag, keine Uhrzeit, kein Alter
WEEKDAYS = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]

SCHEMA = {
    "type": "object",
    "properties": {
        "beschreibung": {"type": "string"},
        "stichwoerter": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["beschreibung", "stichwoerter"],
}

# Lightroom schreibt Orte englisch - fuer das Modell und die Suche auf Deutsch (nur gaengige Namen)
PLACE_DE = {
    "Germany": "Deutschland", "Switzerland": "Schweiz", "Austria": "Österreich", "France": "Frankreich",
    "Italy": "Italien", "Spain": "Spanien", "Netherlands": "Niederlande", "Belgium": "Belgien",
    "Luxembourg": "Luxemburg", "United Kingdom": "Vereinigtes Königreich", "Scotland": "Schottland",
    "Ireland": "Irland", "Poland": "Polen", "Czechia": "Tschechien", "Czech Republic": "Tschechien",
    "Slovakia": "Slowakei", "Hungary": "Ungarn", "Croatia": "Kroatien", "Slovenia": "Slowenien",
    "Greece": "Griechenland", "Turkey": "Türkei", "Denmark": "Dänemark", "Sweden": "Schweden",
    "Norway": "Norwegen", "Finland": "Finnland", "Iceland": "Island", "Russia": "Russland",
    "Lithuania": "Litauen", "Latvia": "Lettland", "Estonia": "Estland", "India": "Indien",
    "Singapore": "Singapur", "Indonesia": "Indonesien", "Egypt": "Ägypten", "Morocco": "Marokko",
    "Tunisia": "Tunesien", "Canada": "Kanada", "Mexico": "Mexiko", "Brazil": "Brasilien",
    "Argentina": "Argentinien", "Australia": "Australien", "New Zealand": "Neuseeland",
    "South Africa": "Südafrika", "United States": "USA", "United States of America": "USA",
    "North Rhine-Westphalia": "Nordrhein-Westfalen", "Bavaria": "Bayern", "Lower Saxony": "Niedersachsen",
    "Saxony": "Sachsen", "Saxony-Anhalt": "Sachsen-Anhalt", "Thuringia": "Thüringen", "Hesse": "Hessen",
    "Rhineland-Palatinate": "Rheinland-Pfalz", "Mecklenburg-Western Pomerania": "Mecklenburg-Vorpommern",
    "Baden-Wuerttemberg": "Baden-Württemberg",
    "Munich": "München", "Cologne": "Köln", "Nuremberg": "Nürnberg", "Vienna": "Wien", "Zurich": "Zürich",
    "Geneva": "Genf", "Prague": "Prag", "Rome": "Rom", "Venice": "Venedig", "Florence": "Florenz",
    "Milan": "Mailand", "Lisbon": "Lissabon", "Copenhagen": "Kopenhagen", "Brussels": "Brüssel",
    "Warsaw": "Warschau", "Moscow": "Moskau", "Athens": "Athen", "Hanover": "Hannover",
}

lines = []


def out(text=""):
    print(text, flush=True)
    lines.append(str(text))


def save_txt():
    TXT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def stop(text, code=1):
    out(text)
    save_txt()
    print(f"\nGespeichert: {TXT_FILE}")
    sys.exit(code)


def load_config():
    cfg = dict(DEFAULTS)
    path = SCRIPT_DIR / "config.local.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except json.JSONDecodeError as err:
            stop(f"FEHLER: config.local.json ist fehlerhaft: {err}")
    return cfg


def photo_id(fname):      # wie sync.py - fuer eine spaetere Uebernahme in die App
    return hashlib.sha1(unicodedata.normalize("NFC", fname).encode("utf-8")).hexdigest()[:12]


def safe_name(text):
    s = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in text).strip(" .")
    return s or "Ordner"


# ---------------------------------------------------------------- Ollama

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # localhost nie ueber einen Proxy


def ollama(cfg, path, body=None, timeout=30):
    url = cfg["ollama_url"].rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Ollama antwortet mit Fehler {err.code}: {text}") from None
    except (urllib.error.URLError, OSError) as err:
        raise ConnectionError(str(getattr(err, "reason", err))) from None


def choose_model(cfg, wanted=""):
    try:
        tags = ollama(cfg, "/api/tags")
    except ConnectionError as err:
        stop(f"FEHLER: Ollama ist nicht erreichbar ({cfg['ollama_url']}: {err}).\n"
             "   Ollama starten (Startmenü › Ollama) und noch einmal versuchen.")
    names = [m.get("name", "") for m in tags.get("models", [])]
    out(f"   installierte Modelle: {', '.join(names) or '(keine)'}")
    wanted = (wanted or cfg.get("ollama_model") or "").strip()
    if wanted:
        if wanted in names:
            return wanted
        hits = [n for n in names if wanted.lower() in n.lower()]          # z. B. „9b“ -> qwen3.5:9b
        if len(hits) > 1:
            hits = [n for n in hits if "qwen" in n.lower()] or hits
        if len(hits) == 1:
            return hits[0]
        stop(f"FEHLER: Modell „{wanted}“ "
             + ("passt auf mehrere installierte Modelle – bitte genauer angeben." if hits else "ist nicht installiert."))
    for test in (lambda n: "qwen3.5" in n and "4b" in n, lambda n: "qwen3.5" in n,
                 lambda n: "qwen" in n and "vl" in n):
        hits = [n for n in names if test(n.lower())]
        if hits:
            return hits[0]
    stop("FEHLER: kein passendes Modell gefunden (erwartet z. B. qwen3.5:4b).\n"
         "   Beim Start den Modellnamen eintippen oder in config.local.json eintragen: "
         "\"ollama_model\": \"<Name aus der Liste oben>\"")


def check_vision(cfg, model):
    try:
        info = ollama(cfg, "/api/show", {"model": model})
    except (RuntimeError, ConnectionError) as err:
        out(f"   ⚠ Modell-Infos nicht lesbar ({err}) – versuche es trotzdem")
        return True, False
    caps = info.get("capabilities") or []
    out(f"   Fähigkeiten laut Ollama: {', '.join(caps) or '(keine Angabe)'}")
    if caps and "vision" not in caps:
        stop(f"FEHLER: {model} kann laut Ollama keine Bilder ansehen (keine „vision“).\n"
             "   Ein Modell mit Bildverständnis nötig, z. B. qwen3-vl:4b oder gemma3:4b.")
    details = info.get("details") or {}
    if details:
        out(f"   Größe: {details.get('parameter_size', '?')} · Quantisierung: {details.get('quantization_level', '?')}")
    return True, "thinking" in caps


# ---------------------------------------------------------------- Exporte und Kontext

def gallery_exports(cfg):
    """Exporte gruppiert nach Lightroom-Ordner; ohne Bilder, die sync bewusst offline laesst (Stapel unten usw.)."""
    export_dir = Path(cfg["export_dir"])
    if not export_dir.is_dir():
        stop(f"FEHLER: Export-Ordner nicht gefunden: {export_dir}")
    paths, _doubles = regeln.find_exports(export_dir)
    state_path = Path(cfg["work_dir"]) / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
    skipped = set((state.get("skipped") or {}).keys())
    files = state.get("files") or {}
    now = datetime.now()
    folders = defaultdict(list)
    for p in paths:
        if p.name in skipped:
            continue
        a = regeln.analyze_name(p.name, now)
        if not a["lr_folder"] or regeln.is_severe(a["problems"]):
            continue
        folders[a["lr_folder"]].append({"path": p, "taken": a["taken"], "meta": (files.get(p.name) or {}).get("meta") or {}})
    return folders, len(paths) - len(skipped & {p.name for p in paths})


def pick_folder(folders, search):
    if search:
        s = search.lower()
        hits = sorted((n for n in folders if s in n.lower()), key=lambda n: (-len(folders[n]), n))
        if not hits:
            stop(f"FEHLER: kein exportierter Ordner enthält „{search}“.")
        if len(hits) > 1:
            out(f"   {len(hits)} Ordner passen, genommen wird der größte. Weitere: {', '.join(hits[1:6])}")
        return hits[0]
    cands = [n for n, items in folders.items() if MIN_PICK <= len(items) <= MAX_PICK]
    if not cands:
        cands = list(folders)
    # bevorzugt: viele Bilder mit Personen und Ort (dann gibt es Kontext), Anzahl nahe 40, neuere Ordner
    def score(n):
        items = folders[n]
        ctx = sum(1 for it in items if it["meta"].get("p")) + sum(1 for it in items if it["meta"].get("ci"))
        return (-ctx / len(items), abs(len(items) - TARGET), n)
    return sorted(cands, key=score)[0]


def read_birthdays():
    """geburtstage.txt (Name ; TT.MM.JJJJ | JJJJ-MM-TT | JJJJ) -> {name klein: (Jahr, Monat, Tag)}; Monat/Tag None = nur Jahr."""
    if not BIRTHDAY_FILE.exists():
        return {}
    raw = BIRTHDAY_FILE.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    result = {}
    for line in text.splitlines():
        name, _, date = line.split("#", 1)[0].partition(";")
        name, date = " ".join(name.split()), date.strip()
        if not name or not date:
            continue
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date)
        parts = (int(m[3]), int(m[2]), int(m[1])) if m else None
        if not parts:
            m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", date)
            parts = (int(m[1]), int(m[2]), int(m[3])) if m else None
        if not parts and re.fullmatch(r"\d{4}", date):
            parts = (int(date), None, None)
        if not parts:
            continue
        try:
            if parts[1]:
                datetime(*parts)
        except ValueError:
            continue
        result.setdefault(name.casefold(), parts)
    return result


def age_text(birth, taken):
    """Alter bei der Aufnahme als Text fuer das Modell, sonst None."""
    year, month, day = birth
    if month is None:
        years = taken.year - year
        return f"ca. {years} Jahre alt" if years >= 2 else None
    if taken < datetime(year, month, day):
        return None
    months = (taken.year - year) * 12 + taken.month - month - (1 if taken.day < day else 0)
    if months < 1:
        return "wenige Wochen alt"
    if months < 24:
        return f"{months} Monate alt"
    return f"{months // 12} Jahre alt"


def german_place(meta):
    parts = [meta.get(k) for k in ("sl", "ci", "st", "co")]
    return ", ".join(PLACE_DE.get(p, p) for p in parts if p)


def context_for(entry, meta, taken, folder, birthdays):
    """Kontext-Zeilen fuer das Modell: alles, was Lightroom schon sicher weiss."""
    regions = sorted((r for r in regeln.face_regions(entry) if r["name"]), key=lambda r: r["x"])
    persons = []
    for name in [r["name"] for r in regions] + list(meta.get("p") or []):
        if name and name not in persons:
            persons.append(name)
    place = german_place(meta)
    ctx = {"ordner": interpret(folder)}
    scan = bool(taken) and taken.year < SCAN_BEFORE
    if scan:
        ctx["aufnahme"] = "altes Foto (Scan), Datum und Uhrzeit unsicher"
    elif taken:
        ctx["aufnahme"] = f"{WEEKDAYS[taken.weekday()]} {taken:%d.%m.%Y, %H:%M} Uhr"
    if persons:
        ctx["personen"] = persons
        ctx["personen_reihenfolge"] = bool(regions) and len(regions) == len(persons)
        if taken and not scan:
            ages = {}
            for name in persons:
                birth = birthdays.get(name.casefold())
                text = age_text(birth, taken) if birth else None
                if text:
                    ages[name] = text
            if ages:
                ctx["alter"] = ages
    if place:
        ctx["ort"] = place
    if meta.get("de") and meta["de"].strip().lower() != folder.strip().lower():
        ctx["beschreibung_lightroom"] = meta["de"]
    kws = [k for k in (meta.get("kw") or []) if k not in persons]
    if kws:
        ctx["stichwoerter_lightroom"] = kws
    return ctx


def interpret(folder):
    f = regeln.interpret_folder(folder)
    if f.get("rest"):
        return f"{folder} (lose Bilder dieses Jahres, kein bestimmter Anlass)"
    return folder


def prompt_for(ctx):
    rows = [f"- Ordner / Anlass: {ctx['ordner']}"]
    if ctx.get("aufnahme"):
        rows.append(f"- Aufgenommen: {ctx['aufnahme']}")
    if ctx.get("ort"):
        rows.append(f"- Ort: {ctx['ort']}")
    persons = ctx.get("personen") or []
    if persons:
        how = " (von links nach rechts)" if ctx.get("personen_reihenfolge") and len(persons) > 1 else ""
        names = ", ".join(f"{p} ({ctx['alter'][p]})" if p in (ctx.get("alter") or {}) else p for p in persons)
        rows.append(f"- Personen auf dem Bild{how}: {names}")
    else:
        rows.append("- Personen: keine Namen bekannt")
    if ctx.get("bildart"):
        rows.append(f"- Bildart: {ctx['bildart']}")
    if ctx.get("beschreibung_lightroom"):
        rows.append(f"- Vorhandene Beschreibung: {ctx['beschreibung_lightroom']}")
    if ctx.get("stichwoerter_lightroom"):
        rows.append(f"- Stichwörter: {', '.join(ctx['stichwoerter_lightroom'])}")

    if persons:
        names_rule = (f"Nenne jede der oben genannten Personen in der Beschreibung beim Namen (zum Beispiel: "
                      f"„{persons[0]} sitzt am Tisch und malt.“) statt nur „ein Junge“ oder „eine Frau“. ")
        if ctx.get("personen_reihenfolge") and len(persons) > 1:
            names_rule += "Die Namen stehen von links nach rechts – ordne sie den Personen im Bild in dieser Reihenfolge zu. "
        if ctx.get("alter"):
            names_rule += "Das Alter hilft bei der Zuordnung; du musst es nicht nennen. "
        names_rule += "Weitere Personen ohne Namen beschreibst du allgemein (z. B. „eine ältere Frau“). "
    else:
        names_rule = "Personen ohne bekannten Namen beschreibst du allgemein (z. B. „ein Kind“). "
    kind_rule = (f"Das Foto ist laut Analyse: {ctx['bildart']} – erwähne das kurz in der Beschreibung. "
                 if ctx.get("bildart") else "")
    return (
        "Du beschreibst Fotos aus einem privaten Familien-Fotoarchiv, damit man sie später per Textsuche findet.\n\n"
        "Bekannt aus Lightroom (stimmt sicher):\n" + "\n".join(rows) + "\n\n"
        "Aufgabe:\n"
        "1. „beschreibung“: 1 bis 3 sachliche Sätze auf Deutsch, was auf dem Bild zu sehen ist – Personen und was "
        "sie tun, Umgebung, auffällige Gegenstände, Tageszeit oder Wetter, falls erkennbar. "
        + names_rule + kind_rule +
        "Ortsnamen schreibst du auf Deutsch. Erfinde keine Namen, Orte oder Anlässe.\n"
        "2. „stichwoerter“: 5 bis 8 einzelne deutsche Suchbegriffe für das, was wirklich zu sehen ist – konkret "
        "statt allgemein (z. B. Geburtstagskuchen statt Essen, Fahrrad statt Fahrzeug), keine Oberbegriffe wie "
        "Bild, Foto oder Person, keine Personennamen, kein Ortsname.\n"
        "Antworte nur als JSON."
    )


def color_kind(im, year):
    """'schwarz-weiß' (kaum Farbe), 'Sepia / einfarbig getönt' (nur alte Fotos: fast ein Farbton) oder None."""
    small = im.copy()
    small.thumbnail((120, 120))
    h, s, v = small.convert("HSV").split()
    hp, sp, vp = h.tobytes(), s.tobytes(), v.tobytes()
    n = len(sp)
    if not n:
        return None
    mean_s = sum(sp) / n
    if mean_s < 18:
        return "schwarz-weiß"
    if year is None or year < SCAN_BEFORE:
        pts = [hh for hh, ss, vv in zip(hp, sp, vp) if ss > 40 and vv > 40]
        if len(pts) >= 0.4 * n and mean_s < 130:
            counts = [0] * 256
            for x in pts:
                counts[x] += 1
            best = max(sum(counts[(i + d) % 256] for d in range(-14, 15)) for i in range(256))
            if best / len(pts) > 0.9:
                return "Sepia / einfarbig getönt"
    return None


def image_b64(path, max_px, year):
    from PIL import Image, ImageOps
    t0 = time.time()
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        kind = color_kind(im, year)
        big = im.copy()
        big.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        big.save(buf, "JPEG", quality=85)
        thumb = im.copy()
        thumb.thumbnail((THUMB_PX, THUMB_PX))
        tbuf = io.BytesIO()
        thumb.save(tbuf, "JPEG", quality=75)
    return (base64.b64encode(buf.getvalue()).decode("ascii"), base64.b64encode(tbuf.getvalue()).decode("ascii"),
            kind, time.time() - t0)


def describe(cfg, model, prompt, img, think_ok):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [img]}],
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0.2},
        "keep_alive": "10m",
    }
    if think_ok:
        body["think"] = False          # Denkmodus aus: deutlich schneller, fuer Beschreibungen nicht noetig
    t0 = time.time()
    try:
        res = ollama(cfg, "/api/chat", body, timeout=TIMEOUT)
    except RuntimeError as err:
        if "think" in str(err).lower() and "think" in body:
            body.pop("think")
            res = ollama(cfg, "/api/chat", body, timeout=TIMEOUT)
        else:
            raise
    wall = time.time() - t0
    text = ((res.get("message") or {}).get("content") or "").strip()
    try:
        data = json.loads(text)
        desc = str(data.get("beschreibung", "")).strip()
        kws = [str(k).strip() for k in data.get("stichwoerter") or [] if str(k).strip()]
    except ValueError:
        desc, kws = text, []
    ns = 1e9
    stats = {
        "sekunden": round(wall, 2),
        "laden_s": round((res.get("load_duration") or 0) / ns, 2),
        "eingabe_tokens": res.get("prompt_eval_count") or 0,
        "eingabe_s": round((res.get("prompt_eval_duration") or 0) / ns, 2),
        "ausgabe_tokens": res.get("eval_count") or 0,
        "ausgabe_s": round((res.get("eval_duration") or 0) / ns, 2),
    }
    return desc, kws, stats


def add_kind_keyword(kws, kind):
    """Schwarz-weiss/Sepia sicher als Suchbegriff - Python hat es gemessen, das Modell muss es nicht raten."""
    if not kind:
        return kws
    word = "schwarz-weiß" if kind.startswith("schwarz") else "sepia"
    if any(word.split("-")[0] in k.lower() for k in kws):
        return kws
    return kws + [word]


def name_in_text(ctx, text):
    low = text.lower()
    return any(p.lower() in low for p in (ctx.get("personen") or []))


# ---------------------------------------------------------------- Ausgabe

def fmt_s(sec):
    if sec >= 3600:
        return f"{sec / 3600:.1f} h".replace(".", ",")
    if sec >= 120:
        return f"{sec / 60:.0f} min"
    return f"{sec:.1f} s".replace(".", ",")


def write_html(path, folder, model, rows, summary):
    esc = html.escape
    cards = []
    for r in rows:
        ctx = r["kontext"]
        facts = []
        if ctx.get("aufnahme"):
            facts.append(esc(ctx["aufnahme"]))
        if ctx.get("ort"):
            facts.append(esc(ctx["ort"]))
        if ctx.get("personen"):
            ages = ctx.get("alter") or {}
            facts.append("👤 " + esc(", ".join(f"{p} ({ages[p]})" if p in ages else p for p in ctx["personen"])))
        if ctx.get("bildart"):
            facts.append("◐ " + esc(ctx["bildart"]))
        if ctx.get("beschreibung_lightroom"):
            facts.append("Lightroom: " + esc(ctx["beschreibung_lightroom"]))
        if ctx.get("personen") and r.get("beschreibung") and not r.get("name_im_text"):
            facts.append("<span class='err'>⚠ Name nicht im Text</span>")
        kws = "".join(f"<span class='kw'>{esc(k)}</span>" for k in r["stichwoerter"])
        err = f"<p class='err'>Fehler: {esc(r['fehler'])}</p>" if r.get("fehler") else ""
        st = r.get("zeit") or {}
        timing = (f"{fmt_s(st['sekunden'])} · {st['eingabe_tokens']} Token rein, {st['ausgabe_tokens']} raus"
                  if st else "")
        cards.append(
            f"<article><img src='data:image/jpeg;base64,{r['_thumb']}' alt='' loading='lazy'>"
            f"<div><p class='file'>{esc(r['datei'])}</p><p class='desc'>{esc(r['beschreibung']) or '–'}</p>"
            f"<p class='kws'>{kws}</p><p class='facts'>{' · '.join(facts)}</p>{err}"
            f"<p class='time'>{timing}</p></div></article>")
    head = (f"<p class='sum'>{esc(model)} · {summary}</p>"
            "<p class='hint'>Suchen: Strg+F im Browser. Grau = Kontext aus Lightroom, der mitgegeben wurde.</p>")
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Beschreibungen – {esc(folder)}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#1c1f24; --muted:#667085; --kw:#e7eefc; --kwt:#1f4fb3; --line:#e3e6ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161a; --card:#1d2026; --text:#e8eaed; --muted:#9aa3ae;
  --kw:#24324d; --kwt:#a9c3ff; --line:#2b2f36; }} }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui, sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:16px; }}
h1 {{ font-size:22px; margin:8px 0 4px; }} .sum, .hint {{ color:var(--muted); margin:2px 0; }}
article {{ display:grid; grid-template-columns:240px 1fr; gap:16px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:12px; margin:12px 0; }}
article img {{ width:100%; border-radius:6px; }}
.file {{ font-size:12px; color:var(--muted); margin:0 0 4px; }} .desc {{ margin:0 0 8px; font-size:16px; }}
.kw {{ display:inline-block; background:var(--kw); color:var(--kwt); border-radius:12px; padding:1px 9px;
  margin:0 5px 5px 0; font-size:13px; }}
.facts, .time {{ color:var(--muted); font-size:13px; margin:4px 0 0; }} .err {{ color:#c0392b; }}
@media (max-width:640px) {{ article {{ grid-template-columns:1fr; }} }}
</style></head><body><main><h1>{esc(folder)}</h1>{head}{''.join(cards)}</main></body></html>"""
    path.write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- Ablauf

def main():
    started = time.time()
    out(f"beschreiben.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')}")
    out("Lässt ein lokales KI-Modell (Ollama) beschreiben, was auf den Bildern eines Ordners zu sehen ist.")
    out("Nimmt nur die Lightroom-Exporte. Ändert nichts – alles bleibt auf dem PC.")
    cfg = load_config()
    args = sys.argv[1:]
    model_arg = ""
    if "--modell" in args:
        i = args.index("--modell")
        model_arg = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    search = " ".join(args).strip()

    out("\n== 1. Ollama")
    model = choose_model(cfg, model_arg)
    out(f"   Modell: {model}")
    _vision, think_ok = check_vision(cfg, model)

    out("\n== 2. Ordner")
    folders, total = gallery_exports(cfg)
    if not folders:
        stop("FEHLER: keine Exporte gefunden.")
    folder = pick_folder(folders, search)
    items = sorted(folders[folder], key=lambda it: (it["taken"] or datetime.min, it["path"].name))
    how = f"enthält „{search}“" if search else f"automatisch gewählt: {MIN_PICK}–{MAX_PICK} Bilder, viel Kontext"
    out(f"   {folder} – {len(items)} Bilder ({how})")
    out(f"   Exporte insgesamt (Galerie): {total}")
    birthdays = read_birthdays()
    out(f"   geburtstage.txt: {len(birthdays)} Personen mit Geburtsdatum" if BIRTHDAY_FILE.exists()
        else "   geburtstage.txt nicht gefunden – ohne Alter")

    exiftool = regeln.find_exiftool()
    exif = regeln.read_exif(exiftool, [it["path"] for it in items])

    out(f"\n== 3. Beschreiben ({len(items)} Bilder, Bild ans Modell mit {cfg['beschreiben_px']} px)")
    rows, times, prep_times = [], [], []
    for n, it in enumerate(items, 1):
        p = it["path"]
        entry = exif.get(p.name) or {}
        meta = regeln.extract_metadata(entry) if entry else it["meta"]
        ctx = context_for(entry, meta, it["taken"], folder, birthdays)
        row = {"datei": p.name, "id": photo_id(p.name), "kontext": ctx, "beschreibung": "", "stichwoerter": []}
        try:
            img, thumb, kind, prep = image_b64(p, int(cfg["beschreiben_px"]), it["taken"].year if it["taken"] else None)
            row["_thumb"] = thumb
            prep_times.append(prep)
            if kind:
                ctx["bildart"] = kind
            desc, kws, stats = describe(cfg, model, prompt_for(ctx), img, think_ok)
            row.update(beschreibung=desc, stichwoerter=add_kind_keyword(kws, kind), zeit=stats,
                       name_im_text=name_in_text(ctx, desc))
            times.append(stats)
            first = " (inkl. Modell laden)" if n == 1 and stats["laden_s"] > 1 else ""
            print(f"   {n:>3}/{len(items)} {p.name[-30:]:<30} {fmt_s(stats['sekunden']):>7}{first}", flush=True)
        except ConnectionError as err:
            stop(f"FEHLER: Verbindung zu Ollama verloren ({err}) – bisherige Ergebnisse nicht gespeichert.")
        except Exception as err:                      # ein Bild darf scheitern, der Rest laeuft weiter
            row["fehler"] = str(err)[:300]
            row.setdefault("_thumb", "")
            out(f"   {n:>3}/{len(items)} {p.name[-30:]:<30} FEHLER: {str(err)[:120]}")
        rows.append(row)

    # Zeiten
    out("\n== 4. Geschwindigkeit")
    ok = times
    if not ok:
        stop("   keine Beschreibung erhalten – siehe Fehler oben.")
    secs = [t["sekunden"] for t in ok]
    steady = secs[1:] if len(secs) > 2 else secs        # erstes Bild laedt das Modell
    med = statistics.median(steady)
    out(f"   Bilder beschrieben: {len(ok)} von {len(items)}" + (f" · Fehler: {len(items) - len(ok)}" if len(ok) < len(items) else ""))
    out(f"   erstes Bild (mit Modell laden): {fmt_s(secs[0])} · Laden davon: {fmt_s(ok[0]['laden_s'])}")
    out(f"   je Bild danach: Median {fmt_s(med)} · schnellstes {fmt_s(min(steady))} · langsamstes {fmt_s(max(steady))}")
    tin = statistics.median(t["eingabe_tokens"] for t in ok)
    tout = statistics.median(t["ausgabe_tokens"] for t in ok)
    gen = sum(t["ausgabe_tokens"] for t in ok) / max(0.01, sum(t["ausgabe_s"] for t in ok))
    read = sum(t["eingabe_tokens"] for t in ok) / max(0.01, sum(t["eingabe_s"] for t in ok))
    out(f"   Token je Bild (Median): {tin:.0f} rein (Bild + Text), {tout:.0f} raus · "
        f"Lesen {read:.0f} Token/s · Schreiben {gen:.1f} Token/s".replace(".", ","))
    out(f"   Bild vorbereiten (verkleinern): {fmt_s(statistics.median(prep_times))} je Bild")
    out(f"   Hochrechnung: 1.000 Bilder ≈ {fmt_s(med * 1000)} · alle {total} Exporte ≈ {fmt_s(med * total)}")

    out("\n== 5. Qualität (nur Zählungen)")
    lengths = [len(r["beschreibung"]) for r in rows if r["beschreibung"]]
    kwn = [len(r["stichwoerter"]) for r in rows if r["beschreibung"]]
    if lengths:
        out(f"   Beschreibung im Mittel {statistics.mean(lengths):.0f} Zeichen, "
            f"{statistics.mean(kwn):.1f} Suchbegriffe".replace(".", ","))
    with_p = [r for r in rows if r["kontext"].get("personen") and r["beschreibung"]]
    with_o = sum(1 for r in rows if r["kontext"].get("ort"))
    with_a = sum(1 for r in rows if r["kontext"].get("alter"))
    out(f"   Kontext mitgegeben: {len(with_p)} mit Personen, {with_o} mit Ort, {with_a} mit Alter")
    out(f"   Namen im Text: {sum(1 for r in with_p if r['name_im_text'])} von {len(with_p)} Bildern mit Personen")
    kinds = defaultdict(int)
    for r in rows:
        if r["kontext"].get("bildart"):
            kinds[r["kontext"]["bildart"]] += 1
    out("   Bildart erkannt: " + (", ".join(f"{k} {v}" for k, v in kinds.items()) if kinds else "alles Farbe"))

    # Dateien
    OUT_DIR.mkdir(exist_ok=True)
    base = f"{safe_name(folder.replace(chr(92), '/').split('/')[-1])} ({safe_name(model)})"
    summary = (f"{len(ok)} Bilder · Median {fmt_s(med)} je Bild · gesamt {fmt_s(time.time() - started)} · "
               f"{time.strftime('%d.%m.%Y %H:%M')}")
    write_html(OUT_DIR / f"{base}.html", folder, model, rows, summary)
    data = {"version": __version__, "modell": model, "ordner": folder, "erstellt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "bilder": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]}
    (OUT_DIR / f"{base}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    out("\n== 6. Ergebnis (bleibt auf dem PC)")
    out(f"   _sync\\beschreibungen\\{base}.html – Übersicht mit Bildern, Beschreibungen und Kontext")
    out(f"   _sync\\beschreibungen\\{base}.json – dasselbe als Daten (für später)")
    out(f"\nFertig in {fmt_s(time.time() - started)}. beschreiben.txt kann an Claude – nur Zeiten und Anzahlen, "
        "keine Namen, keine Beschreibungen.")
    save_txt()
    try:                       # im Standard-Browser oeffnen (.html ist am PC mit dem Editor verknuepft)
        import uebersicht
        uebersicht.open_in_browser(OUT_DIR / f"{base}.html")
    except Exception:          # Seite liegt trotzdem da
        pass


if __name__ == "__main__":
    main()
