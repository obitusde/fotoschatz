#!/usr/bin/env python3
"""Fotoschatz - Personen pruefen: welche Ordner und welche Bilder haben (noch) keine Person?

Ziel: alle wichtigen Bilder haben benannte Personen. Liest eine KOPIE des Lightroom-Katalogs (Lightroom muss
geschlossen sein) und aendert nichts. Geprueft werden nur Bilder fuer die Galerie.

Diagnose: Woher kommen die Personen? (bestaetigtes Gesicht und/oder Stichwort mit Personennamen)
Liste: je Ordner die Bilder ohne Person, mit Grund und Weg in Lightroom:
  - Name vorgeschlagen, nicht bestaetigt      -> People-Ansicht (O), bestaetigen
  - Gesicht erkannt, ohne Namen               -> Namen eintragen
  - kein Gesicht erkannt                      -> selbst ansehen, ggf. Draw Face Region
  - noch nicht nach Gesichtern durchsucht     -> Gesichtserkennung laufen lassen
Dazu: Gesicht bestaetigt, aber Stichwort fehlt (bekannter Lightroom-Fehler) -> Name anklicken, Enter.
Sterne (Entscheidung 03.10.2026): 1 = wichtig, 2 = Lieblingsbild - diese stehen oben in eigener Liste.
Stichwort "personen-egal" = bewusst ohne Personen, wird nicht gemeldet.

Ausgaben neben diesem Skript, bleiben auf dem PC:
  - personen_pruefen.html  mit Dateinamen und Personennamen
  - personen_pruefen.txt   nur Anzahlen je Ordner - diese Datei an Claude schicken

Aufruf: personen_pruefen.bat (Doppelklick) oder python personen_pruefen.py
"""

__version__ = "0.6.29"

import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import katalog
import lightroom_pruefen as LP
import uebersicht as U

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_FILE = SCRIPT_DIR / "personen_pruefen.html"
TXT_FILE = SCRIPT_DIR / "personen_pruefen.txt"
PERSON_PARENTS = {"person", "persons", "personen", "people"}   # Oberbegriffe fuer von Hand angelegte Namen
PEOPLE_SHARE = 0.2      # Ordner mit mindestens 20 % Bildern mit Person gelten als "Ordner mit Personen"
MAX_LIST = 300          # so viele Bilder je Ordner werden aufgelistet

# Gruende fuer "keine Person", in dieser Reihenfolge (schnellste Abhilfe zuerst)
REASONS = {
    "suggested": ("Name vorgeschlagen", "Taste O (People) › bei „Similar“ bzw. am Gesicht den Vorschlag mit ✓ "
                                        "bestätigen"),
    "unnamed": ("Gesicht ohne Namen", "Bild öffnen (E) › Draw Face Region › Namen am Rahmen eintippen › Enter"),
    "noface": ("kein Gesicht erkannt", "Ansehen: ist jemand Wichtiges drauf? Dann Draw Face Region › Rahmen ums "
                                       "Gesicht ziehen › Namen eintippen › Enter"),
    "unscanned": ("nicht nach Gesichtern durchsucht", "Ordner wählen › Taste O (People) – Lightroom sucht dann; "
                                                      "oder Catalog Settings › Metadata › Face Detection"),
}


def read_people(db):
    """Stichwoerter je Bild und bestaetigte Gesichter (mit Stichwort) je Bild aus der Katalog-Kopie."""
    q = lambda sql: db.execute(sql).fetchall()
    kws = {r["id"]: r for r in q("SELECT id_local AS id, name, keywordType AS type, parent FROM AgLibraryKeyword")}
    img_kw = defaultdict(set)
    for r in q("SELECT image, tag FROM AgLibraryKeywordImage"):
        img_kw[r["image"]].add(r["tag"])
    conf_tags = defaultdict(set)     # Bild -> Stichwoerter bestaetigter Gesichter
    for r in q("""SELECT f.image AS image, kf.tag AS tag FROM AgLibraryFace f
                  JOIN AgLibraryKeywordFace kf ON kf.face = f.id_local WHERE kf.userPick = 1"""):
        conf_tags[r["image"]].add(r["tag"])
    # Bekannte Personennamen: Personen-Stichwoerter, Stichwoerter unter "Person", Namen bestaetigter Gesichter
    names = set()
    for k in kws.values():
        parent = kws.get(k["parent"])
        if k["name"] and (k["type"] == "person" or (parent and str(parent["name"] or "").casefold() in PERSON_PARENTS)):
            names.add(k["name"].casefold())
    for tags in conf_tags.values():
        names.update(kws[t]["name"].casefold() for t in tags if t in kws and kws[t]["name"])
    names -= PERSON_PARENTS | set(katalog.PERSONEN_EGAL) | set(katalog.ORT_EGAL)
    return kws, img_kw, conf_tags, names


def classify(c, kws, img_kw, conf_tags, names):
    """Je Bild fuer die Galerie: Quelle der Personen bzw. Grund, warum keine Person da ist."""
    stats = Counter()
    folders = defaultdict(lambda: {"items": [], "n": 0, "with": 0, "egal": 0, "reasons": Counter(), "rated": 0})
    for i in c["images"]:
        if not i["gallery"]:
            continue
        iid = i["id"]
        tags = img_kw.get(iid, set())
        kw_names = sorted({kws[t]["name"] for t in tags if t in kws and kws[t]["name"]
                           and kws[t]["name"].casefold() in names}, key=str.casefold)
        face_tags = conf_tags.get(iid, set())
        face_names = sorted({kws[t]["name"] for t in face_tags if t in kws and kws[t]["name"]}, key=str.casefold)
        missing_kw = sorted({kws[t]["name"] for t in face_tags - tags if t in kws and kws[t]["name"]}, key=str.casefold)
        faces = c["faces"].get(iid, Counter())
        f = folders[i["folder"]]
        f["n"] += 1
        f["rated"] += i["rating"] >= 1
        stats["n"] += 1
        stats[f"stars{i['rating']}"] += 1
        if face_names and kw_names:
            stats["both"] += 1
        elif face_names:
            stats["face_only"] += 1
        elif kw_names:
            stats["kw_only"] += 1
        if missing_kw:
            stats["missing_kw"] += 1
            f["reasons"]["missing_kw"] += 1
        if face_names or kw_names:
            stats[f"rated_with{min(i['rating'], 2)}"] += 1
            f["with"] += 1
            if missing_kw:      # hat Person, aber Lightroom-Fehler: in der Liste mit aufnehmen
                f["items"].append({"i": i, "reason": "missing_kw", "names": missing_kw, "faces": faces})
            continue
        if any(t in kws and str(kws[t]["name"] or "").casefold() in katalog.PERSONEN_EGAL for t in tags):
            stats["egal"] += 1          # bewusst ohne Personen - erledigt
            f["egal"] += 1
            continue
        stats["none"] += 1
        stats[f"rated_none{min(i['rating'], 2)}"] += 1
        if faces["suggested"]:
            reason = "suggested"
        elif faces["unnamed"]:
            reason = "unnamed"
        elif i["scanned"]:
            reason = "noface"
        else:
            reason = "unscanned"
        stats[reason] += 1
        f["reasons"][reason] += 1
        f["items"].append({"i": i, "reason": reason, "names": [], "faces": faces})
    order = {"missing_kw": 0, "suggested": 1, "unnamed": 2, "noface": 3, "unscanned": 4}
    for f in folders.values():
        f["share"] = f["with"] / f["n"] if f["n"] else 0
        f["todo"] = sum(v for k, v in f["reasons"].items() if k != "missing_kw")
        f["items"].sort(key=lambda x: (order[x["reason"]], -x["i"]["rating"], x["i"]["time"] or datetime.min))
    return folders, stats


# ---------------------------------------------------------------- Seite

CSS = """
.bar2{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.bar2 button{font:inherit;padding:5px 12px;border-radius:14px;border:1px solid var(--line);background:var(--card);
color:inherit;cursor:pointer}.bar2 button.on{border-color:var(--text);font-weight:600}
.cp{font:inherit;font-size:.8rem;padding:2px 8px;margin:2px 0;border-radius:6px;border:1px solid var(--line);
background:var(--card);color:inherit;cursor:pointer;white-space:nowrap}.cp.ok{border-color:var(--ok);color:var(--ok)}
.steps{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:10px 0}
.steps ul{margin:4px 0;padding-left:20px}.stars{color:var(--wait);white-space:nowrap}
.r-missing_kw{color:var(--none)}.r-suggested{color:var(--ok)}.r-unnamed{color:var(--warn)}
td.reason{white-space:nowrap}
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
let minStars=0;
function setStars(btn,v){minStars=v;document.querySelectorAll('.fst').forEach(b=>b.classList.toggle('on',b===btn));filter()}
function filter(){document.querySelectorAll('tr[data-st]').forEach(tr=>{tr.style.display=(+tr.dataset.st>=minStars)?'':'none'})}
function copyFolder(btn){const t=btn.closest('details');const names=[...t.querySelectorAll('tr[data-st]')]
  .filter(tr=>tr.style.display!=='none').map(tr=>tr.dataset.b);copyText(btn,names.join(' '))}
"""


def stars(n):
    return "★" * n if n else ""


def row_cells(it):
    """Zellen Datei · Aufnahme · Sterne · Grund · Erkannt fuer ein Bild ohne Person."""
    esc = U.esc
    i, faces, key = it["i"], it["faces"], it["reason"]
    label = "Stichwort fehlt" if key == "missing_kw" else REASONS[key][0]
    info = []
    if it["names"]:
        info.append("benannt: " + ", ".join(it["names"]))
    if faces["suggested"]:
        info.append(f"{faces['suggested']} Vorschlag")
    if faces["unnamed"]:
        info.append(f"{faces['unnamed']} ohne Namen")
    when = f"{i['time']:%d.%m.%Y %H:%M}" if i["time"] else ""
    return (f"<td><b>{esc(i['file'])}</b> <button class='cp' data-c='{esc(i['base'])}' "
            f"onclick='copyText(this,this.dataset.c)'>Kopieren</button></td><td>{when}</td>"
            f"<td class='stars'>{stars(i['rating'])}</td><td class='reason r-{key}'>{esc(label)}</td>"
            f"<td class='small'>{esc(' · '.join(info))}</td>")


def build_page(catalog_path, folders, stats, names, started):
    esc, fmt = U.esc, U.fmt
    out = []
    w = out.append
    w("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    w("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    w(f"<title>Fotoschatz Personen prüfen</title><style>{U.CSS}{LP.CSS_EXTRA}{CSS}</style><script>{JS}</script>"
      "</head><body><main style='max-width:1150px'>")
    w("<h1>Personen – welche Bilder haben noch keine Person?</h1>")
    w(f"<div class='muted small'>Stand {datetime.now():%d.%m.%Y %H:%M} · personen_pruefen.py v{__version__} · "
      f"Katalog: {esc(catalog_path.name)} (Kopie) · nur Bilder für die Galerie · {fmt(len(names))} bekannte "
      f"Personennamen · {time.time() - started:.0f} s · enthält Namen – bleibt auf dem PC</div>")

    n = stats["n"] or 1
    w("<div class='cards'>")
    for value, label in ((stats["both"], "Person über Gesicht und Stichwort"),
                         (stats["face_only"], "nur über bestätigtes Gesicht"),
                         (stats["kw_only"], "nur über Stichwort (von Hand, ohne Gesichtsrahmen)"),
                         (stats["none"], "ohne Person")):
        w(f"<div class='card'><b>{fmt(value)}</b><span>{label} · {value / n:.0%}</span></div>")
    w(f"<div class='card'><b style='color:var(--none)'>{fmt(stats['missing_kw'])}</b><span>Gesicht bestätigt, aber "
      "Stichwort fehlt (Lightroom-Fehler)</span></div>")
    fav = sum(stats[f"stars{s}"] for s in range(2, 6))
    w(f"<div class='card'><b>{fmt(stats['stars1'])} · {fmt(fav)}</b><span>★ wichtig · ★★ Lieblingsbild "
      f"(ab 2 Sternen) – davon ohne Person: {fmt(stats['rated_none1'])} · {fmt(stats['rated_none2'])}</span></div>")
    w(f"<div class='card'><b class='muted'>{fmt(stats['egal'])}</b><span>mit <i>personen-egal</i> markiert "
      "(bewusst ohne Personen, erledigt)</span></div>")
    w("</div>")

    w("<div class='steps'><b>Ohne Person – Gründe und was du in Lightroom tust</b> (schnellste zuerst):<ul>")
    w(f"<li><span class='r-missing_kw'><b>Stichwort fehlt</b></span> ({fmt(stats['missing_kw'])}): Gesicht ist "
      "benannt, aber Lightroom hat das Stichwort nicht gesetzt. Bild öffnen (E) › Draw Face Region › auf den Namen am "
      "Rahmen klicken › Enter.</li>")
    for key, (label, todo) in REASONS.items():
        w(f"<li><span class='r-{key}'><b>{label}</b></span> ({fmt(stats[key])}): {esc(todo)}</li>")
    w("<li><b>Gar keine Person auf dem Bild</b> (wichtiges Bild, z. B. Landschaft): Stichwort <i>personen-egal</i> "
      "setzen – dann wird es nicht mehr gemeldet.</li>")
    w("</ul>Bild finden: <i>Kopieren</i> beim Bild (Dateiname ohne Endung) › in Lightroom <i>Catalog › All Photographs</i> "
      "› <i>Library Filter › Text › Filename › Contains</i> › Strg+V. Beim Ordner kopiert <i>alle Dateinamen</i> die "
      "angezeigten Bilder auf einmal (mit Leerzeichen getrennt) – ⚠ am PC prüfen, ob Lightroom dann alle zeigt.</div>")

    w("<div class='bar2'>Zeigen: <button class='fst on' onclick='setStars(this,0)'>alle</button>"
      "<button class='fst' onclick='setStars(this,1)'>★ wichtig und ★★</button>"
      "<button class='fst' onclick='setStars(this,2)'>nur ★★ Lieblingsbilder</button></div>")

    # ---- Wichtige und Lieblingsbilder ohne Person, ueber alle Ordner (das, was zuerst stimmen soll)
    order = {"missing_kw": 0, "suggested": 1, "unnamed": 2, "noface": 3, "unscanned": 4}
    top = sorted(((rel, it) for rel, f in folders.items() for it in f["items"] if it["i"]["rating"] >= 1),
                 key=lambda x: (-min(x[1]["i"]["rating"], 2), order[x[1]["reason"]], x[0].casefold(),
                                x[1]["i"]["time"] or datetime.min))
    w(f"<h2>★★ Lieblingsbilder und ★ wichtige Bilder ohne Person ({fmt(len(top))})</h2>")
    if not top:
        w("<div class='none'>Keine – alle bewerteten Bilder haben eine Person oder <i>personen-egal</i>.</div>")
    else:
        w("<details class='task' open><summary><span class='t'>Liste</span><span class='nums'>Lieblingsbilder zuerst"
          "</span></summary><div class='inner'><button class='cp' onclick='copyFolder(this)'>alle Dateinamen "
          "kopieren</button><table><tr><th>Ordner</th><th>Datei</th><th>Aufnahme</th><th>Sterne</th><th>Grund</th>"
          "<th>Erkannt</th></tr>")
        for rel, it in top[:MAX_LIST * 3]:
            w(f"<tr data-st='{it['i']['rating']}' data-b='{esc(it['i']['base'])}'><td>{esc(LP.show(rel))}</td>"
              + row_cells(it) + "</tr>")
        w("</table></div></details>")

    people = sorted((x for x in folders.items() if x[1]["share"] >= PEOPLE_SHARE and x[1]["items"]),
                    key=lambda x: (-x[1]["todo"], x[0].casefold()))
    other = sorted((x for x in folders.items() if x[1]["share"] < PEOPLE_SHARE and x[1]["items"]),
                   key=lambda x: (-x[1]["todo"], x[0].casefold()))

    def folder_block(rel, f):
        badges = " · ".join(f"<span class='r-{k}'>{fmt(f['reasons'][k])} "
                            f"{esc(REASONS[k][0] if k in REASONS else 'Stichwort fehlt')}</span>"
                            for k in ("missing_kw", "suggested", "unnamed", "noface", "unscanned") if f["reasons"][k])
        w(f"<details class='task'><summary><span class='t'>{esc(LP.show(rel))}</span><span class='nums'>"
          f"{fmt(f['todo'])} ohne Person von {fmt(f['n'])} · {f['share']:.0%} mit Person</span>"
          f"<span class='small'>{badges}</span></summary><div class='inner'>"
          "<button class='cp' onclick='copyFolder(this)'>alle Dateinamen kopieren</button><table>"
          "<tr><th>Datei</th><th>Aufnahme</th><th>Sterne</th><th>Grund</th><th>Erkannt</th></tr>")
        for it in f["items"][:MAX_LIST]:
            w(f"<tr data-st='{it['i']['rating']}' data-b='{esc(it['i']['base'])}'>" + row_cells(it) + "</tr>")
        if len(f["items"]) > MAX_LIST:
            w(f"<tr><td colspan='5' class='muted'>… und {fmt(len(f['items']) - MAX_LIST)} weitere</td></tr>")
        w("</table></div></details>")

    w(f"<h2>Ordner mit Personen ({fmt(len(people))})</h2>")
    w(f"<div class='muted small'>Mindestens {PEOPLE_SHARE:.0%} der Bilder haben eine Person – hier fehlen Namen "
      "am ehesten. Sortiert nach Anzahl ohne Person.</div>")
    for rel, f in people:
        folder_block(rel, f)
    w(f"<h2>Ordner mit wenig Personen ({fmt(len(other))})</h2>")
    w("<div class='muted small'>Vermutlich Landschaft, Reise, Street – meist ist hier nichts zu tun.</div>")
    w("<details><summary><span class='t'>aufklappen</span></summary><div class='inner'>")
    for rel, f in other:
        folder_block(rel, f)
    w("</div></details></main></body></html>")
    return "\n".join(out)


def write_txt(folders, stats, names):
    """Zusammenfassung fuer Claude: nur Anzahlen und Ordnernamen - keine Personennamen, keine Dateinamen."""
    n = stats["n"] or 1
    lines = [f"personen_pruefen.py v{__version__} · {datetime.now():%d.%m.%Y %H:%M}",
             f"Bilder fuer die Galerie: {stats['n']} · bekannte Personennamen: {len(names)}",
             f"Person ueber Gesicht und Stichwort: {stats['both']} · nur Gesicht: {stats['face_only']} · "
             f"nur Stichwort: {stats['kw_only']} · ohne Person: {stats['none']} ({stats['none'] / n:.0%})",
             f"Gesicht bestaetigt, Stichwort fehlt: {stats['missing_kw']}",
             "Ohne Person nach Grund: " + " · ".join(f"{REASONS[k][0]}: {stats[k]}" for k in REASONS),
             "Sterne: " + " · ".join(f"{s}: {stats[f'stars{s}']}" for s in range(5, -1, -1)),
             f"Bewertet ohne Person: wichtig (1) {stats['rated_none1']} · Lieblingsbild (2+) {stats['rated_none2']} · "
             f"personen-egal: {stats['egal']}", "",
             "Ordner (ohne Person / Bilder / Anteil mit Person / Vorschlag / ohne Namen / kein Gesicht / nicht durchsucht):"]
    for rel, f in sorted(folders.items(), key=lambda x: (-x[1]["todo"], x[0].casefold()))[:60]:
        r = f["reasons"]
        lines.append(f"  {f['todo']:5} {f['n']:5} {f['share']:5.0%}  {r['suggested']:4} {r['unnamed']:4} "
                     f"{r['noface']:5} {r['unscanned']:5}  {LP.show(rel)}")
    TXT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    started = time.time()
    cfg = LP.load_config()
    print(f"personen_pruefen.py v{__version__}")
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
        kws, img_kw, conf_tags, names = read_people(db)
    except Exception as err:   # Aufbau des Katalogs anders als erwartet
        LP.fail(f"Katalog nicht lesbar ({type(err).__name__}: {err}). Bitte katalog_diagnose.bat laufen lassen und "
                "katalog_diagnose.txt an Claude schicken.")
    finally:
        db.close()
    folders, stats = classify(c, kws, img_kw, conf_tags, names)
    OUT_FILE.write_text(build_page(catalog_path, folders, stats, names, started), encoding="utf-8")
    write_txt(folders, stats, names)
    print(f"\n{stats['n']} Bilder fuer die Galerie: {stats['none']} ohne Person "
          f"(Vorschlag {stats['suggested']}, ohne Namen {stats['unnamed']}, kein Gesicht {stats['noface']}, "
          f"nicht durchsucht {stats['unscanned']}); Stichwort fehlt trotz Gesicht: {stats['missing_kw']}")
    print(f"\nErgebnis: {OUT_FILE}  (enthaelt Namen - bleibt auf dem PC)")
    print(f"Fuer Claude: {TXT_FILE.name} (nur Anzahlen)")
    if not U.open_in_browser(OUT_FILE):
        print("Bitte die Datei in den Browser ziehen (z. B. Chrome), um sie anzusehen.")
        sys.exit(2)  # Fenster bleibt offen (personen_pruefen.bat)


if __name__ == "__main__":
    main()
