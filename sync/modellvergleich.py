"""Fotoschatz - Modellvergleich fuer Bildbeschreibungen (Ollama): welches Modell, welche Bildgroesse?

Nimmt ein paar Ordner (Standard: vier Testordner), je Ordner gleichmaessig verteilte Lightroom-Exporte (nie die
Originale), und laesst DIESELBEN Bilder mit zwei Modellen (4b und 9b) beschreiben - mit einem Prompt, der auf die
spaetere SUCHE ausgerichtet ist: was ist zu sehen, Stimmung der Personen, konkrete Suchbegriffe mit Synonymen.
Namen und Ort stehen nicht im Text (die kennt die App schon aus Lightroom). Dazu ein kleiner Groessentest
(4b mit 640 und 1536 px an wenigen Bildern), um die Bildgroesse fuer den grossen Lauf zu waehlen.

Ergebnis (bleibt auf dem PC): beschreibungen\\vergleich.html - je Bild die Texte aller Varianten nebeneinander,
oben eine Zahlen-Tabelle (Zeit, Laenge, Token) und ein Suchfeld: Suchwort eintippen, die Seite zeigt je Variante,
wie viele Bilder es findet. beschreibungen\\vergleich.json (Zwischenstand - ein erneuter Start macht weiter, wo
er aufgehoert hat) und modellvergleich.txt (nur Zahlen - die kann an Claude).
Aendert nichts an Fotos, Katalog, Exporten oder online. Lightroom darf dabei offen sein.

Aufruf: python modellvergleich.py [--bilder 30] [--neu] [--modelle 4b,9b] [--ordner "Teil des Ordnernamens" ...]
"""
__version__ = "0.7.29"

import html
import json
import statistics
import sys
import time
import unicodedata
from datetime import datetime

import beschreiben as B
import regeln

SCRIPT_DIR = B.SCRIPT_DIR
OUT_DIR = B.OUT_DIR
TXT_FILE = SCRIPT_DIR / "modellvergleich.txt"
CACHE_FILE = OUT_DIR / "vergleich.json"
HTML_FILE = OUT_DIR / "vergleich.html"

DEFAULT_FOLDERS = [
    "2002-08-09 Zimmer Wohnheim Zähringer Straße",
    "1988-10-01 Berlin",
    "2020-07-06 Marlies in Morges",
    "2024-10-24 Wanderung ab Les Cases",
]
PER_FOLDER = 30            # Bilder je Ordner (gleichmaessig ueber den Ordner verteilt)
SIZE_PER_FOLDER = 3        # Groessentest: so viele Bilder je Ordner
BASE_PX = 1024             # Standardgroesse fuer beide Modelle
SIZE_TEST_PX = (640, 1536)  # Groessentest nur mit dem kleinen Modell
PROMPT_V = "s1"            # bei geaendertem Prompt hochzaehlen - dann gilt der Zwischenstand nicht mehr

SCHEMA = {
    "type": "object",
    "properties": {
        "beschreibung": {"type": "string"},
        "stimmung": {"type": "array", "items": {"type": "string"}},
        "stichwoerter": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["beschreibung", "stimmung", "stichwoerter"],
}


def nfc(text):
    return unicodedata.normalize("NFC", text).casefold()


# ---------------------------------------------------------------- Prompt

def prompt_suche(ctx):
    rows = [f"- Anlass / Ordner: {ctx['ordner']}"]
    if ctx.get("aufnahme"):
        rows.append(f"- Aufgenommen: {ctx['aufnahme']}")
    if ctx.get("ort"):
        rows.append(f"- Ort: {ctx['ort']}")
    persons = ctx.get("personen") or []
    if persons:
        ages = ctx.get("alter") or {}
        how = " (von links nach rechts)" if ctx.get("personen_reihenfolge") and len(persons) > 1 else ""
        parts = "; ".join(ages.get(p, "Alter unbekannt") for p in persons)
        rows.append(f"- Erkannte Personen auf dem Bild{how}: {len(persons)} – {parts}")
    if ctx.get("bildart"):
        rows.append(f"- Bildart: {ctx['bildart']}")
    if ctx.get("beschreibung_lightroom"):
        rows.append(f"- Vorhandene Beschreibung: {ctx['beschreibung_lightroom']}")
    if ctx.get("stichwoerter_lightroom"):
        rows.append(f"- Stichwörter: {', '.join(ctx['stichwoerter_lightroom'])}")
    kind = (f"Das Foto ist laut Analyse: {ctx['bildart']} – erwähne das kurz. " if ctx.get("bildart") else "")
    return (
        "Du beschreibst Fotos aus einem privaten Familien-Fotoarchiv, damit man sie später per Textsuche findet "
        "(zum Beispiel „Flugzeug“, „Schnee“, „Geburtstagstorte“, „lachende Kinder“, „am Esstisch“).\n\n"
        "Bekannt aus Lightroom (stimmt sicher, nur zum Verständnis – nicht wiederholen):\n" + "\n".join(rows) + "\n\n"
        "Aufgabe – antworte nur als JSON:\n"
        "1. „beschreibung“: ein bis zwei kurze, sachliche Sätze auf Deutsch (höchstens 30 Wörter): Was ist zu sehen, "
        "was tun die Personen, drinnen oder draußen, welche Umgebung, welche auffälligen Gegenstände. "
        + kind + "Keine Personennamen, keine Ortsnamen, nichts erfinden.\n"
        "2. „stimmung“: 0 bis 3 einzelne Wörter für Gesichtsausdruck und Stimmung der Personen, zum Beispiel "
        "fröhlich, lachend, ernst, nachdenklich, müde, traurig, konzentriert, entspannt, stolz, überrascht, "
        "ausgelassen. Nur wenn Personen zu sehen sind, sonst eine leere Liste.\n"
        "3. „stichwoerter“: 6 bis 10 einzelne deutsche Suchbegriffe, nach denen jemand suchen würde: Gegenstände, "
        "Tätigkeit, Art des Ortes (zum Beispiel Flugzeug, Strand, Küche, Wald, Altstadt), Wetter, Jahreszeit, "
        "Tageszeit, Bildart (Porträt, Gruppenfoto, Selfie, Landschaft). Nimm die gängigen deutschen Wörter und bei "
        "Bedarf auch das Synonym (Flugzeug und Flieger). Keine Personennamen, keine Ortsnamen, keine Oberbegriffe "
        "wie Bild, Foto, Person oder Mensch."
    )


def describe_search(cfg, model, prompt, img, think_ok):
    data, text, stats = B.ask(cfg, model, prompt, img, think_ok, SCHEMA)
    if data is None:
        return {"beschreibung": text, "stimmung": [], "stichwoerter": []}, stats

    def words(key):
        seen, res = set(), []
        for w in data.get(key) or []:
            w = str(w).strip()
            if w and w.casefold() not in seen:
                seen.add(w.casefold())
                res.append(w)
        return res
    return {"beschreibung": str(data.get("beschreibung", "")).strip(),
            "stimmung": words("stimmung"), "stichwoerter": words("stichwoerter")}, stats


# ---------------------------------------------------------------- Auswahl und Zwischenstand

def find_folder(folders, wanted):
    low = nfc(wanted)
    for name in folders:
        if nfc(name) == low:
            return name
    hits = sorted((n for n in folders if low in nfc(n)), key=lambda n: (-len(folders[n]), n))
    return hits[0] if hits else None


def pick_even(items, n):
    if len(items) <= n:
        return list(items)
    if n <= 1:
        return [items[len(items) // 2]]
    idx = []
    for i in range(n):
        j = round(i * (len(items) - 1) / (n - 1))
        if j not in idx:
            idx.append(j)
    return [items[j] for j in idx]


def load_cache(fresh):
    if CACHE_FILE.exists() and not fresh:
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if data.get("prompt") == PROMPT_V and isinstance(data.get("varianten"), dict):
                return data
            B.out("   Zwischenstand stammt von einem anderen Prompt – wird neu gemacht.")
        except (OSError, ValueError):
            pass
    return {"prompt": PROMPT_V, "varianten": {}}


def save_cache(cache):
    OUT_DIR.mkdir(exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE_FILE)


# ---------------------------------------------------------------- Auswertung

def variant_stats(var, results, total_exports):
    ok = [r for r in results.values() if r.get("zeit")]
    if not ok:
        return None
    steady = [r["zeit"] for r in ok if r["zeit"]["laden_s"] <= 1] or [r["zeit"] for r in ok]
    secs = [z["sekunden"] for z in steady]
    med = statistics.median(secs)
    descs = [r["beschreibung"] for r in ok if r["beschreibung"]]
    return {
        "bilder": len(ok), "median_s": med,
        "zeichen": statistics.mean(len(d) for d in descs) if descs else 0,
        "stichwoerter": statistics.mean(len(r["stichwoerter"]) for r in ok),
        "stimmung": sum(1 for r in ok if r["stimmung"]),
        "token_rein": statistics.median(z["eingabe_tokens"] for z in steady),
        "token_raus": statistics.median(z["ausgabe_tokens"] for z in steady),
        "lesen_s": statistics.median(z["eingabe_s"] for z in steady),
        "schreiben_s": statistics.median(z["ausgabe_s"] for z in steady),
        "h1000": med * 1000, "h_alle": med * total_exports,
    }


def fnum(x, digits=1):
    return f"{x:.{digits}f}".replace(".", ",")


# ---------------------------------------------------------------- HTML

def write_html(rows, variants, cache, stats, sections):
    esc = html.escape
    head_rows = []
    for v in variants:
        st = stats.get(v["label"])
        if not st:
            continue
        head_rows.append(
            f"<tr><td>{esc(v['label'])}</td><td>{st['bilder']}</td><td>{B.fmt_s(st['median_s'])}</td>"
            f"<td>{st['zeichen']:.0f}</td><td>{fnum(st['stichwoerter'])}</td><td>{st['stimmung']}</td>"
            f"<td>{st['token_rein']:.0f} / {st['token_raus']:.0f}</td>"
            f"<td>{B.fmt_s(st['h1000'])}</td><td>{B.fmt_s(st['h_alle'])}</td></tr>")
    table = ("<table><thead><tr><th>Variante</th><th>Bilder</th><th>Zeit je Bild</th><th>Zeichen</th>"
             "<th>Suchbegriffe</th><th>mit Stimmung</th><th>Token rein / raus</th><th>1.000 Bilder</th>"
             "<th>alle Exporte</th></tr></thead><tbody>" + "".join(head_rows) + "</tbody></table>")
    by_file = {r["datei"]: r for r in rows}
    body = []
    for title, files in sections:
        cards = []
        for fn in files:
            r = by_file[fn]
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
            cols = []
            for vi, v in enumerate(variants):
                res = (cache["varianten"].get(v["label"], {}).get("bilder") or {}).get(fn)
                if not res:
                    continue
                text = " ".join([res["beschreibung"]] + res["stimmung"] + res["stichwoerter"])
                moods = "".join(f"<span class='kw mood'>{esc(k)}</span>" for k in res["stimmung"])
                kws = "".join(f"<span class='kw'>{esc(k)}</span>" for k in res["stichwoerter"])
                z = res["zeit"]
                cols.append(
                    f"<div class='col' data-v='{vi}' data-t='{esc(text, quote=True)}'>"
                    f"<p class='vname'>{esc(v['label'])}</p><p class='desc'>{esc(res['beschreibung']) or '–'}</p>"
                    f"<p class='kws'>{moods}{kws}</p>"
                    f"<p class='time'>{B.fmt_s(z['sekunden'])} · {z['eingabe_tokens']} Token rein, "
                    f"{z['ausgabe_tokens']} raus</p></div>")
            cards.append(
                f"<article><div class='pic'><img src='data:image/jpeg;base64,{r['_thumb']}' alt='' loading='lazy'>"
                f"<p class='file'>{esc(fn)}</p><p class='facts'>{'<br>'.join(facts)}</p></div>"
                f"<div class='cols'>{''.join(cols)}</div></article>")
        body.append(f"<section><h2>{esc(title)} <span class='n'>{len(files)} Bilder</span></h2>{''.join(cards)}</section>")
    legend = "".join(f"<span class='lg'>{esc(v['label'])}: <b data-cnt='{i}'>–</b></span>" for i, v in enumerate(variants))
    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Modellvergleich</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#1c1f24; --muted:#667085; --kw:#e7eefc; --kwt:#1f4fb3; --mood:#fdebd3;
  --moodt:#8a4b00; --line:#e3e6ea; --hit:#e3f5e1; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161a; --card:#1d2026; --text:#e8eaed; --muted:#9aa3ae;
  --kw:#24324d; --kwt:#a9c3ff; --mood:#4a3416; --moodt:#ffd199; --line:#2b2f36; --hit:#1f3a22; }} }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui, sans-serif; }}
main {{ max-width:1500px; margin:0 auto; padding:16px; }}
h1 {{ font-size:22px; margin:8px 0 4px; }} h2 {{ font-size:18px; margin:28px 0 6px; }} .n, .hint {{ color:var(--muted); font-size:13px; }}
table {{ border-collapse:collapse; width:100%; background:var(--card); font-size:13px; margin:10px 0; }}
th, td {{ border:1px solid var(--line); padding:5px 8px; text-align:left; }}
.search {{ position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:5; }}
.search input {{ font-size:16px; padding:8px 10px; width:min(420px,100%); border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--text); }}
.lg {{ display:inline-block; margin:4px 14px 0 0; font-size:13px; color:var(--muted); }} .lg b {{ color:var(--text); }}
article {{ display:grid; grid-template-columns:230px 1fr; gap:14px; background:var(--card); border:1px solid var(--line);
  border-radius:10px; padding:12px; margin:10px 0; }}
.pic img {{ width:100%; border-radius:6px; }} .file {{ font-size:11px; color:var(--muted); margin:4px 0; word-break:break-all; }}
.facts {{ font-size:12px; color:var(--muted); margin:0; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px; }}
.col {{ border:1px solid var(--line); border-radius:8px; padding:8px 10px; }} .col.hit {{ background:var(--hit); }}
.vname {{ font-size:12px; font-weight:600; color:var(--muted); margin:0 0 4px; }} .desc {{ margin:0 0 6px; }}
.kw {{ display:inline-block; background:var(--kw); color:var(--kwt); border-radius:12px; padding:1px 8px; margin:0 4px 4px 0;
  font-size:12px; }} .kw.mood {{ background:var(--mood); color:var(--moodt); }}
.time {{ color:var(--muted); font-size:12px; margin:2px 0 0; }}
@media (max-width:760px) {{ article {{ grid-template-columns:1fr; }} }}
</style></head><body><main><h1>Modellvergleich Bildbeschreibungen</h1>
<p class='hint'>Dieselben Bilder, mehrere Varianten nebeneinander. Orange = Stimmung, blau = Suchbegriffe. Grau unter dem Bild:
was Lightroom schon weiß (nicht im Text). Zeit je Bild ohne das erste Bild (Modell laden).</p>
{table}
<div class='search'><input id='q' type='search' placeholder='Suchwort testen, z. B. Flugzeug, Schnee, lachend …'>
<div id='legend'>{legend}</div></div>
{''.join(body)}
<script>
const norm = s => s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/ß/g, 'ss');
const cols = [...document.querySelectorAll('.col')];
cols.forEach(c => c.dataset.n = norm(c.dataset.t));
const arts = [...document.querySelectorAll('article')];
const secs = [...document.querySelectorAll('section')];
document.getElementById('q').addEventListener('input', e => {{
  const words = norm(e.target.value).split(/\\s+/).filter(Boolean);
  const counts = {{}};
  document.querySelectorAll('[data-cnt]').forEach(b => counts[b.dataset.cnt] = 0);
  arts.forEach(a => {{
    let any = false;
    a.querySelectorAll('.col').forEach(c => {{
      const hit = words.length > 0 && words.every(w => c.dataset.n.includes(w));
      c.classList.toggle('hit', hit);
      if (hit) {{ counts[c.dataset.v]++; any = true; }}
    }});
    a.style.display = (!words.length || any) ? '' : 'none';
  }});
  secs.forEach(s => s.style.display = [...s.querySelectorAll('article')].some(a => a.style.display !== 'none') ? '' : 'none');
  document.querySelectorAll('[data-cnt]').forEach(b => b.textContent = words.length ? counts[b.dataset.cnt] : '–');
}});
</script></main></body></html>"""
    HTML_FILE.write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- Ablauf

def parse_args(argv):
    opt = {"bilder": PER_FOLDER, "neu": False, "modelle": ["4b", "9b"], "ordner": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--neu":
            opt["neu"] = True
        elif a == "--bilder" and i + 1 < len(argv):
            i += 1
            try:
                opt["bilder"] = max(1, int(argv[i]))
            except ValueError:
                pass
        elif a == "--modelle" and i + 1 < len(argv):
            i += 1
            opt["modelle"] = [m.strip() for m in argv[i].split(",") if m.strip()]
        elif a == "--ordner" and i + 1 < len(argv):
            i += 1
            opt["ordner"].append(argv[i])
        i += 1
    return opt


def main():
    started = time.time()
    B.TXT_FILE = TXT_FILE                       # B.out / B.stop schreiben in modellvergleich.txt
    B.out(f"modellvergleich.py v{__version__} · {time.strftime('%d.%m.%Y %H:%M')}")
    B.out("Vergleicht Modelle (und Bildgrößen) für Bildbeschreibungen an denselben Bildern.")
    B.out("Nimmt nur die Lightroom-Exporte. Ändert nichts – alles bleibt auf dem PC.")
    cfg = B.load_config()
    opt = parse_args(sys.argv[1:])

    B.out("\n== 1. Modelle")
    models = []
    for wanted in opt["modelle"]:
        m = B.choose_model(cfg, wanted)
        if m not in models:
            models.append(m)
    think = {}
    for m in models:
        B.out(f"   {m}:")
        think[m] = B.check_vision(cfg, m)[1]

    B.out("\n== 2. Bilder")
    folders, total = B.gallery_exports(cfg)
    if not folders:
        B.stop("FEHLER: keine Exporte gefunden.")
    B.out(f"   Exporte insgesamt (Galerie): {total}")
    selected, sections, size_files = [], [], set()
    for wanted in (opt["ordner"] or DEFAULT_FOLDERS):
        name = find_folder(folders, wanted)
        if not name:
            B.out(f"   ⚠ Ordner nicht gefunden (nicht exportiert?): {wanted}")
            continue
        items = sorted(folders[name], key=lambda it: (it["taken"] or datetime.min, it["path"].name))
        pick = pick_even(items, opt["bilder"])
        for it in pick:
            it["folder"] = name
        for it in pick_even(pick, SIZE_PER_FOLDER):
            size_files.add(it["path"].name)
        selected.extend(pick)
        sections.append((name, [it["path"].name for it in pick]))
        B.out(f"   {name}: {len(pick)} von {len(items)} Bildern")
    if not selected:
        B.stop("FEHLER: keiner der Ordner hat Exporte.")
    birthdays = B.read_birthdays()
    exif = regeln.read_exif(regeln.find_exiftool(), [it["path"] for it in selected])
    rows = []
    for it in selected:
        p = it["path"]
        entry = exif.get(p.name) or {}
        meta = regeln.extract_metadata(entry) if entry else it["meta"]
        ctx = B.context_for(entry, meta, it["taken"], it["folder"], birthdays)
        rows.append({"datei": p.name, "ordner": it["folder"], "kontext": ctx, "_item": it, "_thumb": ""})
    by_file = {r["datei"]: r for r in rows}

    variants = []                                # Reihenfolge = Ablauf (je Modell am Stueck, kein Hin und Her)
    small = models[0]
    for m in models:
        variants.append({"modell": m, "px": BASE_PX, "alle": True})
        if m == small:
            for px in SIZE_TEST_PX:
                variants.append({"modell": m, "px": px, "alle": False})
    for v in variants:
        v["label"] = f"{v['modell']} · {v['px']} px"
        v["bilder"] = [r for r in rows if v["alle"] or r["datei"] in size_files]
    n_all, n_size = len(rows), len(size_files)
    est = (n_all * 5 + n_size * 2 * 5 + n_all * 12) if len(models) > 1 else n_all * 5
    B.out(f"\n   {n_all} Bilder · Größentest an {n_size} Bildern · Varianten: "
          + ", ".join(v["label"] for v in variants))
    B.out(f"   Dauer grob: {B.fmt_s(est)} (nach früheren Messungen; ein Abbruch ist unkritisch – "
          "ein erneuter Start macht weiter)")

    cache = load_cache(opt["neu"])
    done_before = sum(len((c.get("bilder") or {})) for c in cache["varianten"].values())
    if done_before:
        B.out(f"   Zwischenstand gefunden: {done_before} Ergebnisse werden übernommen.")

    B.out("\n== 3. Beschreiben")
    interrupted = False
    try:
        for v in variants:
            store = cache["varianten"].setdefault(
                v["label"], {"modell": v["modell"], "px": v["px"], "bilder": {}})
            todo = [r for r in v["bilder"] if r["datei"] not in store["bilder"]]
            B.out(f"   {v['label']}: {len(todo)} zu tun, {len(v['bilder']) - len(todo)} schon fertig")
            times = []
            for n, r in enumerate(todo, 1):
                it = r["_item"]
                year = it["taken"].year if it["taken"] else None
                try:
                    img, thumb, kind, _prep = B.image_b64(it["path"], v["px"], year)
                    if kind and not r["kontext"].get("bildart"):
                        r["kontext"]["bildart"] = kind
                    res, stats = describe_search(cfg, v["modell"], prompt_suche(r["kontext"]), img, think[v["modell"]])
                    res["stichwoerter"] = B.add_kind_keyword(res["stichwoerter"], r["kontext"].get("bildart"))
                    res["zeit"] = stats
                    store["bilder"][r["datei"]] = res
                    save_cache(cache)
                    times.append(stats["sekunden"])
                    rest = ""
                    if len(times) >= 3:
                        rest = f" · noch ca. {B.fmt_s(statistics.median(times[1:]) * (len(todo) - n))}"
                    print(f"   {v['label']:<22} {n:>3}/{len(todo)} {it['path'].name[-28:]:<28} "
                          f"{B.fmt_s(stats['sekunden']):>7}{rest}", flush=True)
                except ConnectionError as err:
                    save_cache(cache)
                    B.stop(f"FEHLER: Verbindung zu Ollama verloren ({err}). Ergebnisse bisher sind gespeichert – "
                           "nach dem Neustart von Ollama einfach noch einmal starten.")
                except Exception as err:             # ein Bild darf scheitern, der Rest laeuft weiter
                    B.out(f"   {v['label']:<22} {n:>3}/{len(todo)} {it['path'].name[-28:]:<28} FEHLER: {str(err)[:120]}")
    except KeyboardInterrupt:
        interrupted = True
        save_cache(cache)
        B.out("\n   Abgebrochen – gezeigt wird der Zwischenstand (ein erneuter Start macht weiter).")

    B.out("\n== 4. Zahlen")
    stats = {}
    for v in variants:
        st = variant_stats(v, cache["varianten"].get(v["label"], {}).get("bilder") or {}, total)
        if not st:
            continue
        stats[v["label"]] = st
        B.out(f"   {v['label']}: {st['bilder']} Bilder · {B.fmt_s(st['median_s'])} je Bild · "
              f"{st['zeichen']:.0f} Zeichen · {fnum(st['stichwoerter'])} Suchbegriffe · "
              f"{st['stimmung']} mit Stimmung")
        B.out(f"      Token rein {st['token_rein']:.0f} (Lesen {B.fmt_s(st['lesen_s'])}) · "
              f"raus {st['token_raus']:.0f} (Schreiben {B.fmt_s(st['schreiben_s'])}) · "
              f"1.000 Bilder ≈ {B.fmt_s(st['h1000'])} · alle {total} Exporte ≈ {B.fmt_s(st['h_alle'])}")

    for r in rows:                                # Vorschaubilder fuer die Seite
        try:
            _img, thumb, _kind, _prep = B.image_b64(r["_item"]["path"], 256, None)
            r["_thumb"] = thumb
        except Exception:
            r["_thumb"] = ""
    OUT_DIR.mkdir(exist_ok=True)
    cache["version"] = __version__
    cache["bilder"] = {r["datei"]: {"ordner": r["ordner"], "kontext": r["kontext"]} for r in rows}
    cache["erstellt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_cache(cache)
    write_html(rows, variants, cache, stats, sections)
    B.out("\n== 5. Ergebnis (bleibt auf dem PC)")
    B.out("   _sync\\beschreibungen\\vergleich.html – alle Varianten nebeneinander, mit Suchfeld")
    B.out("   _sync\\beschreibungen\\vergleich.json – Daten und Zwischenstand")
    B.out(f"\nFertig in {B.fmt_s(time.time() - started)}. modellvergleich.txt kann an Claude – nur Zahlen, "
          "keine Namen, keine Beschreibungen.")
    B.save_txt()
    try:                       # im Standard-Browser oeffnen (.html ist am PC mit dem Editor verknuepft)
        import uebersicht
        uebersicht.open_in_browser(HTML_FILE)
    except Exception:          # Seite liegt trotzdem da
        pass
    if interrupted:
        sys.exit(1)


if __name__ == "__main__":
    main()
