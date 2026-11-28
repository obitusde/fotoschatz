"use strict";

const APP_VERSION = "0.8.16";
const R2_PUBLIC_URL = "https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev";
const SECRET_KEY = "fotoschatz.secret";
// Link: #<Praefix>-<Schluessel> (seit v0.7.15: eigener Link, Gaeste-Link, Ordner-Freigaben – je ein
// Inhaltsverzeichnis index-<Schluessel>.json); alter Link nur mit Praefix -> index.json
const SECRET_RE = /^[A-Za-z0-9]{32,}(-[A-Za-z0-9]{16,})?$/;
const INFO_KEY = "fotoschatz.info";
const INSTALL_KEY = "fotoschatz.install-hidden";
const ORDER_KEY = "fotoschatz.order";   // Bilder (Suche, Alle Bilder, im Ordner): "asc" = aelteste zuerst (Standard), "desc" = neueste zuerst
const STARS_KEY = "fotoschatz.stars";   // "0" alle, "1" = ★ und ★★, "2" = nur ★★ (Ordner, Alle Bilder, Suche; v0.7.15)
const FOLDER_ORDER_KEY = "fotoschatz.folder-order";   // Ordnerliste: "desc" = neueste zuerst (Standard), "asc" = aelteste zuerst
const VORDER_KEY = "fotoschatz.video-order";   // Videos: "asc" = aelteste zuerst, sonst neueste zuerst (v0.8.0)
const HEADER_H = 44;
const GAP = 2;
const MAX_ZOOM = 4;
const DOUBLE_TAP_MS = 280;

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

/* ---------------------------------------------------------------- Geheimnis */

// Seit v0.7.15 merkt sich die App ALLE auf diesem Geraet geoeffneten Links (z. B. mehrere geteilte Ordner)
// und zeigt sie zusammen. Der zuletzt geoeffnete steht vorne.
const LINKS_KEY = "fotoschatz.links";

function storedLinks() {
  try {
    const list = JSON.parse(localStorage.getItem(LINKS_KEY) || "[]");
    return Array.isArray(list) ? list.filter((x) => typeof x === "string" && SECRET_RE.test(x)) : [];
  } catch (e) {
    return [];
  }
}

function saveLinks(list) {
  try { localStorage.setItem(LINKS_KEY, JSON.stringify(list.slice(0, 50))); } catch (e) { /* privat */ }
}

function takeLinks() {
  let list = storedLinks();
  try {   // bis v0.7.15 gab es nur einen gespeicherten Link
    const old = localStorage.getItem(SECRET_KEY);
    if (old && SECRET_RE.test(old) && !list.includes(old)) list.push(old);
    localStorage.removeItem(SECRET_KEY);
  } catch (e) { /* privat */ }
  const fromHash = decodeURIComponent(location.hash.slice(1)).trim();
  if (fromHash) {
    history.replaceState(null, "", location.pathname + location.search);
    if (SECRET_RE.test(fromHash)) list = [fromHash, ...list.filter((x) => x !== fromHash)];
  }
  saveLinks(list);
  return list;
}

/* Deep-Link (v0.7.26): ?f=<Ordnername>&b=<Bild-id>#<Link>, z. B. aus der Sport-App (obitusde/sport).
   Wird vor takeLinks() gelesen und aus der Adresse entfernt, damit Neuladen nicht wieder springt. */
function takeDeepLink() {
  const q = new URLSearchParams(location.search);
  if (!q.has("f") && !q.has("b")) return null;
  const f = (q.get("f") || "").trim();
  const b = (q.get("b") || "").trim();
  q.delete("f");
  q.delete("b");
  const rest = q.toString();
  history.replaceState(history.state, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
  return f || b ? { f, b } : null;
}

// Nach dem Laden: Ordner (und Bild) oeffnen wie von Hand - Zurueck fuehrt zum Ordner, dann zur Ordnerliste
function openDeepLink({ f, b }) {
  let folder = f ? DATA.folderByName.get(f) : null;
  let photo = b ? DATA.photos.find((p) => p.id === b) || null : null;
  if (f && !folder) {
    toast("Ordner nicht gefunden");
    return;
  }
  if (!folder) {
    folder = photo ? DATA.folderByName.get(photo.f) : null;
    if (!folder) {
      toast("Bild nicht gefunden");
      return;
    }
  }
  if (photo && photo.f !== folder.n) photo = null;
  if (photo && !passStars(photo)) writePref(STARS_KEY, "0");   // Sternefilter wuerde das Bild verstecken
  navigate({ v: "folder", f: folder.n });
  if (!b) return;
  const i = photo && mounted && mounted.list ? mounted.list.indexOf(photo) : -1;
  if (i < 0) {
    toast("Bild nicht gefunden");
    return;
  }
  openViewer(i);
}

function dropLink(link) {
  saveLinks(storedLinks().filter((x) => x !== link));
}

function readPref(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* privat */ }
}


/* ---------------------------------------------------------------- Formate */

const fmtDay = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "long", year: "numeric" });
const fmtFull = new Intl.DateTimeFormat("de-DE", {
  weekday: "short", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
});

function parseLocal(t) {
  const [d, time = "00:00:00"] = t.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [h, mi, s] = time.split(":").map(Number);
  return new Date(y, m - 1, day, h, mi, s || 0);
}

function countLabel(n) {
  return n === 1 ? "1 Bild" : `${n.toLocaleString("de-DE")} Bilder`;
}

function folderLabel(f) {
  if (f.x) return { name: "Weitere Bilder", date: "" };
  let m = f.n.match(/^\d{4}-\d{2}-\d{2} (.+)$/);
  if (m) return { name: m[1], date: fmtDay.format(parseLocal(f.d)) };
  m = f.n.match(/^(\d{4})-(\d{4}) (.+)$/);
  if (m) return { name: m[3], date: `${m[1]}–${m[2]}` };
  m = f.n.match(/^\d{4}\S* (.+)$/);
  if (m) return { name: m[1], date: fmtDay.format(parseLocal(f.d)) };
  return { name: f.n, date: "" };
}

/* ---------------------------------------------------------------- Daten */

let BASE = "";
let DATA = null;
let LINK_PREFIX = "";     // geheimer Teil vor dem Schluessel (fuer Teilen-Links)
let OWNER = false;        // dein Link: Verzeichnis mit Teilen-Schluesseln (v0.7.15)

const thumbUrl = (p) => `${BASE}/thumb/${p.id}.${p.h}.webp`;
const imageUrl = (p) => `${BASE}/img/${p.id}.${p.h}.jpg`;

/* ---------------------------------------------------------------- Orte deutsch */

// Laendernamen, die der Browser anders schreibt als Lightroom (englisch -> ISO-Code)
const COUNTRY_ALIASES = {
  "USA": "US", "United States of America": "US", "Czech Republic": "CZ", "Turkey": "TR", "Türkiye": "TR",
  "Macedonia": "MK", "Holland": "NL", "The Netherlands": "NL", "UK": "GB", "Great Britain": "GB",
  "Russian Federation": "RU", "Republic of Korea": "KR", "Ivory Coast": "CI", "Cape Verde": "CV",
  "Burma": "MM", "Swaziland": "SZ", "Vatican City": "VA", "Kingdom of Denmark": "DK",
};
const PLACE_KEYS = ["co", "st", "ci", "sl"];
const SEARCH_PLACE_KEYS = ["co", "ci", "sl"];   // Suche: Land › Stadt › Ort, ohne Bundesland (v0.6.37; Freitext findet es weiter)

// Laender: aus dem Browser (Intl.DisplayNames). Bundeslaender, Staedte, Orte: Tabelle PLACE_DE (orte.js).
function makePlaceTranslator() {
  const countries = new Map();
  const places = new Map();
  try {
    const en = new Intl.DisplayNames(["en"], { type: "region", fallback: "none" });
    const de = new Intl.DisplayNames(["de"], { type: "region", fallback: "none" });
    const addCountry = (name, code) => {
      const german = de.of(code);
      if (german) countries.set(normText(name), german);
    };
    for (let a = 65; a <= 90; a++) {
      for (let b = 65; b <= 90; b++) {
        const code = String.fromCharCode(a, b);
        let name;
        try { name = en.of(code); } catch (e) { continue; }
        if (!name || name === code) continue;
        addCountry(name, code);
        if (name.includes("&")) addCountry(name.replace(/&/g, "and"), code);
        if (name.startsWith("St. ")) addCountry(`Saint ${name.slice(4)}`, code);
      }
    }
    for (const [name, code] of Object.entries(COUNTRY_ALIASES)) addCountry(name, code);
  } catch (e) { /* alter Browser: Laender bleiben wie in Lightroom */ }
  if (typeof PLACE_DE === "object") {
    for (const [name, german] of Object.entries(PLACE_DE)) places.set(normText(name), german);
  }
  return (key, value) => (key === "co" && countries.get(normText(value))) || places.get(normText(value)) || value;
}

// Land > Bundesland > Stadt > Ort ohne leere und doppelte Stufen (z. B. Wien/Wien)
function placePath(p, keys = PLACE_KEYS) {
  const path = [];
  const seen = new Set();
  for (const key of keys) {
    const value = p[key];
    if (!value) continue;
    const norm = normText(value);
    if (!norm || seen.has(norm)) continue;
    seen.add(norm);
    path.push(value);
  }
  return path;
}

// Mehrere Inhaltsverzeichnisse (z. B. mehrere geteilte Ordner) zu einem zusammenlegen (v0.7.15)
function mergeIndexes(list) {
  if (list.length === 1) return list[0];
  const photos = new Map();
  const folders = new Map();
  for (const ix of list) {
    for (const p of ix.photos) if (!photos.has(p.id)) photos.set(p.id, p);
    for (const f of ix.folders) if (!folders.has(f.n)) folders.set(f.n, { ...f, c: 0 });
  }
  for (const p of photos.values()) {
    const f = folders.get(p.f);
    if (f) f.c += 1;
  }
  return {
    v: 1,
    generated: list.map((ix) => ix.generated || "").sort().pop(),
    count: photos.size,
    folders: [...folders.values()].filter((f) => f.c),
    photos: [...photos.values()],
    bd: Object.assign({}, ...list.map((ix) => ix.bd || {})),
    me: [...new Set(list.flatMap((ix) => ix.me || []))],      // persoenlicher Link (v0.7.20)
  };
}

function prepare(index) {
  const translate = makePlaceTranslator();
  for (const p of index.photos) {
    for (const key of PLACE_KEYS) {
      if (!p[key]) continue;
      const german = translate(key, p[key]);
      if (german !== p[key]) {
        (p._en || (p._en = [])).push(p[key]);
        p[key] = german;
      }
    }
  }
  const photos = index.photos.slice().sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  const byFolder = new Map();
  const perYear = new Map();
  for (const p of photos) {
    perYear.set(p.t.slice(0, 4), (perYear.get(p.t.slice(0, 4)) || 0) + 1);
    if (!byFolder.has(p.f)) byFolder.set(p.f, []);
    byFolder.get(p.f).push(p);
  }
  return {
    index,
    photos,
    byFolder,
    perYear,
    birthdays: index.bd || {},
    me: new Set((index.me || []).map(normText)),           // wer die App nutzt (persoenlicher Link, v0.7.20)
    meNames: index.me || [],
    bdNorm: new Map(Object.entries(index.bd || {}).map(([name, birth]) => [normText(name), birth])),
    folderByName: new Map(index.folders.map((f) => [f.n, f])),
    allDesc: photos.slice().reverse(),
  };
}

// Alter einer Person bei der Aufnahme (v0.6.36), aus index.bd ("1975-03-12" oder nur "1975"):
// ab 18 Monaten volle Jahre, darunter Monate, im ersten Monat Wochen. Vor der Geburt -> nichts.
function ageAt(birth, taken) {
  if (!birth) return "";
  const ty = +taken.slice(0, 4), tm = +taken.slice(5, 7), td = +taken.slice(8, 10);
  if (birth.length === 4) {
    const years = ty - +birth;
    return years >= 2 ? `ca. ${years}` : "";
  }
  const by = +birth.slice(0, 4), bm = +birth.slice(5, 7), bd = +birth.slice(8, 10);
  const months = (ty - by) * 12 + (tm - bm) - (td < bd ? 1 : 0);
  if (months < 0) return "";
  if (months >= 18) return String(Math.floor(months / 12));
  if (months >= 1) return months === 1 ? "1 Monat" : `${months} Monate`;
  const days = Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(by, bm - 1, bd)) / 86400000);
  if (days < 0) return "";
  if (days < 7) return "neugeboren";
  return days < 14 ? "1 Woche" : `${Math.floor(days / 7)} Wochen`;
}

// Alter als Text mit Einheit: "46" -> "46 Jahre", "ca. 45" -> "ca. 45 Jahre", "14 Monate" bleibt
function ageText(age) {
  if (/^\d+$/.test(age)) return age === "1" ? "1 Jahr" : `${age} Jahre`;
  if (age.startsWith("ca. ")) return `${age} Jahre`;
  return age;
}

// Alter als Spanne fuer eine Jahresueberschrift (v0.7.16): erstes bis letztes Bild des Jahres ("30–31 Jahre")
function ageSpan(birth, first, last) {
  const a = ageAt(birth, first);
  const z = ageAt(birth, last);
  if (!z) return "";
  if (!a || a === z) return ageText(z);
  if (/^\d+$/.test(a) && /^\d+$/.test(z)) return `${a}–${z} Jahre`;
  return `${ageText(a)} – ${ageText(z)}`;
}

// Geburtsdatum einer Person (Schreibweise egal)
const birthOf = (name) => (DATA.bdNorm.get(normText(name)) || "");

// Ueberschrift je Jahr fuer ein Raster; mit Geburtsdatum zusaetzlich das Alter ("2006 · Uli 30–31 Jahre · 39 Bilder")
function yearSectionOf(list, birth = "", name = "") {
  const info = new Map();
  for (const p of list) {
    const y = p.t.slice(0, 4);
    const e = info.get(y);
    if (!e) info.set(y, { n: 1, a: p.t, z: p.t });
    else {
      e.n += 1;
      if (p.t < e.a) e.a = p.t;
      if (p.t > e.z) e.z = p.t;
    }
  }
  const labels = new Map();
  for (const [y, e] of info) {
    const age = birth ? ageSpan(birth, e.a, e.z) : "";
    labels.set(y, [y, age && (name ? `${name} ${age}` : age), countLabel(e.n)].filter(Boolean).join(" · "));
  }
  return (p) => labels.get(p.t.slice(0, 4));
}

// Heutiges Datum als "JJJJ-MM-TT" (Ortszeit)
function localDay(d = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Zufall, der fuer denselben Text immer gleich ist (Erinnerungen wechseln einmal am Tag, nicht bei jedem Oeffnen)
function seeded(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  h ^= h >>> 13;
  h = Math.imul(h, 1597334677);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

// Wie gut sich ein Bild als Vorschlag eignet: ★★ vor ★, Personen leicht bevorzugt, dazu Tages-Zufall
const photoScore = (p, seed) => ((p.r || 0) >= 2 ? 3 : p.r === 1 ? 1.5 : 0) + (p.p && p.p.length ? 0.5 : 0) + seeded(seed + p.id);

// Persoenlicher Link (v0.7.20): ist die Person, fuer die der Link gemacht ist, auf dem Bild?
const isMine = (p) => DATA.me.size > 0 && Boolean(p.p) && p.p.some((n) => DATA.me.has(normText(n)));
const byTime = (a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0);
// Bilder mit der Person zuerst, sonst nach Aufnahmezeit
const mineFirst = (list) => list.slice().sort((a, b) => (isMine(b) - isMine(a)) || byTime(a, b));

// Die n besten Bilder; schon gezeigte (shown(p) = true) kommen zuletzt dran (v0.7.18),
// beim persoenlichen Link Bilder mit der Person zuerst (v0.7.20)
function bestPhotos(list, n, seed, shown = null) {
  return mineFirst(list.map((p) => [photoScore(p, seed) + (isMine(p) ? 50 : 0) - (shown && shown(p) ? 100 : 0), p])
    .sort((a, b) => b[0] - a[0]).slice(0, n).map((x) => x[1]));
}

// Tage von Kalendertag b bis a ("MM-TT"), -182 … 182 (negativ = a liegt vor b), ueber den Jahreswechsel hinweg
function dayOffset(a, b) {
  const doy = (md) => {
    const [m, d] = md.split("-").map(Number);
    return (Date.UTC(2001, m - 1, Math.min(d, m === 2 ? 28 : d)) - Date.UTC(2001, 0, 1)) / 86400000;
  };
  let diff = doy(a) - doy(b);
  if (diff > 182) diff -= 365;
  if (diff < -182) diff += 365;
  return diff;
}

// Abstand zweier Kalendertage ("MM-TT") in Tagen, ueber den Jahreswechsel hinweg
function dayDistance(a, b) {
  const doy = (md) => {
    const [m, d] = md.split("-").map(Number);
    return (Date.UTC(2001, m - 1, Math.min(d, m === 2 ? 28 : d)) - Date.UTC(2001, 0, 1)) / 86400000;
  };
  const diff = Math.abs(doy(a) - doy(b));
  return Math.min(diff, 365 - diff);
}

/* ---------------------------------------------------------------- Kopfzeile & Leiste */

const oldestFirst = () => readPref(ORDER_KEY) !== "desc";
const foldersOldestFirst = () => readPref(FOLDER_ORDER_KEY) === "asc";
const orderLabel = (asc = oldestFirst()) => (asc ? "⇅ älteste zuerst" : "⇅ neueste zuerst");

function toggleOrder() {
  writePref(ORDER_KEY, oldestFirst() ? "desc" : "asc");
}

// Sternefilter (v0.6.38, drei Stufen seit v0.7.15): 0 = alle, 1 = ★ und ★★, 2 = nur ★★
// (Feld r aus Lightroom; alte Bewertungen mit 3–5 Sternen zaehlen wie ★★)
const starLevel = () => {
  const v = readPref(STARS_KEY);
  return v === "2" ? 2 : v === "1" ? 1 : 0;
};
const starsOnly = () => starLevel() > 0;
const passStars = (p) => (p.r || 0) >= starLevel();
const withStars = (list) => (starsOnly() ? list.filter(passStars) : list);
const starText = () => (starLevel() === 2 ? "mit ★★" : "mit ★ oder ★★");

function toggleStars() {
  writePref(STARS_KEY, String((starLevel() + 1) % 3));
}

function showStarButton() {
  const btn = $("#stars");
  const level = starLevel();
  btn.textContent = ["☆", "★", "★★"][level];
  btn.classList.toggle("on", level > 0);
  btn.setAttribute("aria-pressed", String(level > 0));
  btn.title = ["Alle Bilder – antippen: nur ★ und ★★", "Bilder mit ★ oder ★★ – antippen: nur ★★",
    "Nur Bilder mit ★★ – antippen: alle"][level];
  btn.hidden = false;
}

function toggleFolderOrder() {
  writePref(FOLDER_ORDER_KEY, foldersOldestFirst() ? "desc" : "asc");
}

// Knopf rechts in der Kopfzeile fuer eine eigene Aktion (z. B. Karte -> Laender)
function showHeaderAction(m, label, action) {
  const btn = $("#order");
  btn.textContent = label;
  btn.title = "";
  btn.hidden = false;
  m.headerAction = action;
}

// Kleiner Umschalter rechts in der Kopfzeile (Ordnerliste, Ordner, Alle Bilder) – je Ansicht eigene Aktion
// Am Handy kurz ("alt→neu"), damit der Titel Platz hat (v0.7.16); am PC ausgeschrieben
function showOrderButton(m, asc, toggle) {
  const order = $("#order");
  order.replaceChildren(el("span", { class: "ord-long", text: orderLabel(asc) }),
    el("span", { class: "ord-short", text: asc ? "alt→neu" : "neu→alt" }));
  order.title = `${asc ? "Älteste" : "Neueste"} zuerst – antippen zum Umdrehen`;
  order.hidden = false;
  m.toggleOrder = toggle;
}

function setHeader(title, subtitle = "", back = false) {
  const order = $("#order");
  if (order) order.hidden = true;
  const stars = $("#stars");
  if (stars) stars.hidden = true;
  const share = $("#share");
  if (share) share.hidden = true;
  $("#title").textContent = title;
  $("#subtitle").textContent = subtitle;
  $("#back").hidden = !back;
}

function updateNav(view) {
  const active = view === "folder" ? "folders" : ["mapgrid", "world", "countries"].includes(view) ? "map"
    : view === "memory" ? "memories" : ["people", "person"].includes(view) ? "search" : view;
  for (const btn of document.querySelectorAll("#nav button")) {
    btn.classList.toggle("active", btn.dataset.view === active);
  }
}

/* ---------------------------------------------------------------- Ordnerliste */

function folderListView() {
  const wrap = el("div", { class: "folders" });
  const years = new Map();
  for (const f of DATA.index.folders) {
    if (!years.has(f.y)) years.set(f.y, []);
    years.get(f.y).push(f);
  }
  // Standard neueste zuerst, umschaltbar (v0.6.37); "Weitere Bilder" immer am Ende des Jahres
  const dir = foldersOldestFirst() ? 1 : -1;
  for (const year of [...years.keys()].sort((a, b) => dir * (a - b))) {
    const folders = years.get(year).sort((a, b) => {
      if ((a.x || 0) !== (b.x || 0)) return (a.x || 0) - (b.x || 0);
      return a.d < b.d ? -dir : a.d > b.d ? dir : a.n.localeCompare(b.n, "de");
    });
    const total = folders.reduce((sum, f) => sum + f.c, 0);
    wrap.append(el("h2", { class: "year" }, String(year), el("small", { text: countLabel(total) })));
    for (const f of folders) {
      const label = folderLabel(f);
      const meta = label.date ? `${label.date} · ${countLabel(f.c)}` : countLabel(f.c);
      wrap.append(el("button", {
        type: "button",
        class: "folder-row" + (f.x ? " rest" : ""),
        onclick: () => navigate({ v: "folder", f: f.n }),
      }, el("div", { class: "name", text: label.name }), el("div", { class: "meta", text: meta })));
    }
  }
  const generated = DATA.index.generated ? fmtDay.format(new Date(DATA.index.generated)) : "?";
  if (OWNER && DATA.index.gk) {
    wrap.append(el("div", { class: "share-app" },
      el("button", {
        type: "button", class: "search-action",
        onclick: () => shareLink("Fotoschatz", "Unsere Fotos", linkFor(DATA.index.gk)),
      }, "App teilen (Gäste-Link)"),
      el("p", { class: "muted", text: "Zeigt alle Bilder außer denen aus ausblenden.txt." })));
  }
  wrap.append(el("p", {
    class: "footer-note",
    text: `${countLabel(DATA.photos.length)} · Stand ${generated} · Version ${APP_VERSION} · Anzeige: ${displayMode()}`,
  }));
  return wrap;
}

// Wie die App gerade laeuft (zur Kontrolle der installierten App)
function displayMode() {
  const modes = [["fullscreen", "Vollbild"], ["standalone", "Fenster"], ["minimal-ui", "Fenster mit Leiste"]];
  for (const [mode, label] of modes) {
    if (window.matchMedia(`(display-mode: ${mode})`).matches) return label;
  }
  return "Browser";
}

/* ---------------------------------------------------------------- Raster (virtuell) */

// Quadratischer Ausschnitt um den Fokuspunkt (Gesichter aus Lightroom); ohne Punkt gilt die CSS-Regel.
function focusStyle(p) {
  if (!p.fp || !p.w || !p.ht || p.w === p.ht) return null;
  const clamp = (v) => Math.max(0, Math.min(1, v));
  if (p.w > p.ht) {
    const visible = p.ht / p.w;
    return `object-position:${(clamp((p.fp[0] - visible / 2) / (1 - visible)) * 100).toFixed(1)}% 50%`;
  }
  const visible = p.w / p.ht;
  return `object-position:50% ${(clamp((p.fp[1] - visible / 2) / (1 - visible)) * 100).toFixed(1)}%`;
}

class Grid {
  constructor(container, list, sectionOf = null, onSection = null) {
    this.container = container;
    this.list = list;
    this.sectionOf = sectionOf;
    this.onSection = onSection;
    this.root = el("div", { class: "grid" });
    container.append(this.root);
    this.mounted = new Map();
    this.width = 0;
    this.frame = 0;
    this.lastSection = null;
    this.onScroll = () => this.schedule();
    this.onResize = () => {
      if (this.root.clientWidth !== this.width) this.layout();
      else this.schedule();
    };
    window.addEventListener("scroll", this.onScroll, { passive: true });
    window.addEventListener("resize", this.onResize);
    this.layout();
  }

  layout() {
    this.width = this.root.clientWidth || window.innerWidth;
    this.cols = this.width < 600 ? 4 : Math.max(4, Math.round(this.width / 170));
    this.tile = (this.width - GAP * (this.cols - 1)) / this.cols;
    const rowH = this.tile + GAP;
    this.rows = [];
    this.rowOfPhoto = new Int32Array(this.list.length);
    let y = 0;
    let section = null;
    let current = [];
    const flush = () => {
      if (!current.length) return;
      this.rows.push({ type: "r", items: current, top: y, h: rowH, section });
      for (const i of current) this.rowOfPhoto[i] = this.rows.length - 1;
      y += rowH;
      current = [];
    };
    this.list.forEach((p, i) => {
      if (this.sectionOf) {
        const s = this.sectionOf(p);
        if (s !== section) {
          flush();
          section = s;
          this.rows.push({ type: "h", label: s, top: y, h: HEADER_H, section: s });
          y += HEADER_H;
        }
      }
      current.push(i);
      if (current.length === this.cols) flush();
    });
    flush();
    this.root.style.height = `${y}px`;
    for (const node of this.mounted.values()) node.remove();
    this.mounted.clear();
    this.render();
  }

  schedule() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      this.render();
    });
  }

  originY() {
    return this.root.getBoundingClientRect().top + window.scrollY;
  }

  render() {
    const origin = this.originY();
    const buffer = window.innerHeight;
    const top = window.scrollY - origin - buffer;
    const bottom = window.scrollY - origin + window.innerHeight + buffer;
    const rows = this.rows;
    let lo = 0;
    let hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid].top + rows[mid].h < top) lo = mid + 1;
      else hi = mid;
    }
    const wanted = new Set();
    for (let r = lo; r < rows.length && rows[r].top <= bottom; r++) {
      wanted.add(r);
      if (!this.mounted.has(r)) {
        const node = this.renderRow(rows[r]);
        this.mounted.set(r, node);
        this.root.append(node);
      }
    }
    for (const [r, node] of this.mounted) {
      if (!wanted.has(r)) {
        node.remove();
        this.mounted.delete(r);
      }
    }
    if (this.onSection) {
      const visibleTop = window.scrollY - origin + 1;
      let r = lo;
      while (r < rows.length - 1 && rows[r].top + rows[r].h <= visibleTop) r++;
      const section = rows[r] ? rows[r].section : null;
      if (section !== this.lastSection) {
        this.lastSection = section;
        this.onSection(section);
      }
    }
  }

  renderRow(row) {
    if (row.type === "h") {
      return el("div", { class: "grid-head", style: `top:${row.top}px;height:${row.h}px` }, row.label);
    }
    const node = el("div", {
      class: "grid-row",
      style: `top:${row.top}px;height:${this.tile}px;grid-template-columns:repeat(${this.cols},1fr)`,
    });
    for (const i of row.items) {
      const p = this.list[i];
      node.append(el("button", {
        type: "button",
        class: "tile",
        "aria-label": fmtFull.format(parseLocal(p.t)),
        onclick: () => openViewer(i),
      }, el("img", { src: thumbUrl(p), alt: "", loading: "lazy", decoding: "async", style: focusStyle(p) })));
    }
    return node;
  }

  scrollToPhoto(i) {
    const row = this.rows[this.rowOfPhoto[i]];
    if (!row) return;
    const y = this.originY() + row.top;
    const bar = $(".search-bar");
    const topLimit = window.scrollY + $("#top").offsetHeight + (bar ? bar.offsetHeight : 0);
    const bottomLimit = window.scrollY + window.innerHeight - $("#nav").offsetHeight;
    if (y < topLimit || y + row.h > bottomLimit) {
      window.scrollTo(0, Math.max(0, y - window.innerHeight / 2 + row.h / 2));
    }
  }

  destroy() {
    window.removeEventListener("scroll", this.onScroll);
    window.removeEventListener("resize", this.onResize);
    if (this.frame) cancelAnimationFrame(this.frame);
  }
}

/* ---------------------------------------------------------------- Vollbild */

const NEXT_KEYS = new Set(["ArrowRight", "PageDown", " "]);   // Praesentations-Klicker: Bild ab / Bild auf
const PREV_KEYS = new Set(["ArrowLeft", "PageUp"]);
const clampNum = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

const Viewer = {
  list: [],
  i: 0,
  open: false,
  pointers: new Map(),
  gesture: null,
  zoom: { s: 1, x: 0, y: 0 },
  lastTap: null,
  tapTimer: 0,

  init() {
    this.root = $("#viewer");
    this.stage = $(".v-stage", this.root);
    this.img = $(".v-photo", this.root);
    this.info = $(".v-info", this.root);
    this.counter = $(".v-counter", this.root);
    this.infoBtn = $(".v-info-btn", this.root);
    this.fsBtn = $(".v-fs-btn", this.root);
    this.themeMetas = [...document.querySelectorAll('meta[name="theme-color"]')];
    this.themeColors = this.themeMetas.map((m) => m.content);
    this.setInfo(readPref(INFO_KEY) === "1");
    // Handy: installierte App laeuft ohnehin im Vollbild (Manifest), Vollbild per Knopf
    // wuerde nur Chromes Hinweis einblenden -> Knopf nur am PC.
    const touch = window.matchMedia("(hover: none) and (pointer: coarse)").matches;
    if (touch || !document.documentElement.requestFullscreen) this.fsBtn.hidden = true;

    $(".v-close", this.root).addEventListener("click", () => history.back());
    $(".v-prev", this.root).addEventListener("click", () => this.go(-1));
    $(".v-next", this.root).addEventListener("click", () => this.go(1));
    this.infoBtn.addEventListener("click", () => this.setInfo(!this.infoOn, true));
    this.fsBtn.addEventListener("click", () => this.toggleFullscreen());
    $(".v-share-btn", this.root).addEventListener("click", () => shareImage(this.list[this.i]));
    this.stage.addEventListener("pointerdown", (e) => this.down(e));
    this.stage.addEventListener("pointermove", (e) => this.move(e));
    this.stage.addEventListener("pointerup", (e) => this.up(e));
    this.stage.addEventListener("pointercancel", () => this.reset());
    this.stage.addEventListener("wheel", (e) => this.wheel(e), { passive: false });
    window.addEventListener("resize", () => { if (this.open) this.resetZoom(); });
    document.addEventListener("keydown", (e) => {
      if (!this.open || e.ctrlKey || e.altKey || e.metaKey) return;
      if (NEXT_KEYS.has(e.key)) this.go(1);
      else if (PREV_KEYS.has(e.key)) this.go(-1);
      else if (e.key === "Escape") history.back();
      else if (e.key === "i") this.setInfo(!this.infoOn, true);
      else if (e.key === "f") this.toggleFullscreen();
      else return;
      e.preventDefault();
    });
  },

  setInfo(on, remember = false) {
    this.infoOn = on;
    this.root.classList.toggle("info-on", on);
    this.infoBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (remember) writePref(INFO_KEY, on ? "1" : "0");
  },

  setThemeColor(dark) {
    this.themeMetas.forEach((m, i) => { m.content = dark ? "#000000" : this.themeColors[i]; });
  },

  enterFullscreen() {
    const doc = document.documentElement;
    if (!doc.requestFullscreen || document.fullscreenElement) return;
    doc.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  },

  exitFullscreen() {
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
  },

  toggleFullscreen() {
    if (document.fullscreenElement) this.exitFullscreen();
    else this.enterFullscreen();
  },

  show(list, i) {
    this.list = list;
    if (!this.open) {
      this.open = true;
      this.root.hidden = false;
      this.root.classList.remove("ui-hidden");
      document.body.classList.add("noscroll");
      // Kein automatisches Vollbild (Chrome blendet sonst jedes Mal einen Hinweis ein).
      // Stattdessen die Statusleiste schwarz faerben -> in der installierten App fast wie Vollbild.
      this.setThemeColor(true);
      Cast.load();      // Chromecast-Bibliothek erst jetzt laden (v0.7.15)
      Cast.update();
    }
    this.display(i);
  },

  hide() {
    if (!this.open) return;
    this.open = false;
    this.root.hidden = true;
    this.img.removeAttribute("src");
    clearTimeout(this.tapTimer);
    this.reset();
    document.body.classList.remove("noscroll");
    this.setThemeColor(false);
    this.exitFullscreen();
    if (mounted && mounted.grid) mounted.grid.scrollToPhoto(this.i);
  },

  display(i) {
    this.i = Math.max(0, Math.min(i, this.list.length - 1));
    const p = this.list[this.i];
    if (!p) return;
    this.resetZoom(false);
    this.img.src = thumbUrl(p);
    const full = new Image();
    full.onload = () => {
      if (this.open && this.list[this.i] === p) this.img.src = full.src;
    };
    full.src = imageUrl(p);
    for (const n of [this.i - 1, this.i + 1]) {
      if (this.list[n]) new Image().src = imageUrl(this.list[n]);
    }
    this.counter.textContent = `${this.i + 1} / ${this.list.length}`;
    $(".v-prev", this.root).style.visibility = this.i > 0 ? "" : "hidden";
    $(".v-next", this.root).style.visibility = this.i < this.list.length - 1 ? "" : "hidden";
    this.renderInfo(p);
    Cast.send();        // laeuft der Fernseher, zeigt er dasselbe Bild
  },

  // Infos zum Bild, jede Zeile mit Bezeichnung (v0.6.35)
  renderInfo(p) {
    const folder = DATA.folderByName.get(p.f);
    const label = folder ? folderLabel(folder) : { name: p.f, date: "" };
    const place = placePath(p).reverse().join(", ");
    const rows = [["Aufnahme", fmtFull.format(parseLocal(p.t)), "when"]];
    rows.push(["Ordner", p.f]);      // voller Name, wie in Lightroom (bei losen Bildern „JJJJ Weitere Bilder“)
    if (p.p && p.p.length) {
      rows.push(["Personen", p.p.map((n) => {
        const age = ageAt(DATA.birthdays[n], p.t);
        return age ? `${n} (${age})` : n;
      }).join(", ")]);
    }
    // Ort mit Link zur Karte (v0.7.0)
    const mapLink = hasGps(p) ? el("button", {
      type: "button", class: "v-maplink", text: "auf Karte",
      onclick: () => navigate({ v: "map", at: [p.la, p.lo] }),
    }) : null;
    if (place || mapLink) rows.push(["Ort", [place, place && mapLink ? " · " : "", mapLink]]);
    if (p.de && p.de !== label.name && p.de !== p.f) rows.push(["Beschreibung", p.de]);
    if (p.r) rows.push(["Bewertung", p.r === 1 ? "★ gut" : p.r === 2 ? "★★ sehr gut" : "★".repeat(p.r)]);
    if (p.o) rows.push(["Datei", p.o]);
    this.info.replaceChildren(...rows.map(([name, value, cls]) => el("div", { class: "row" + (cls ? ` ${cls}` : "") },
      el("span", { class: "label", text: name }), el("span", { class: "value" }, ...[].concat(value)))));
  },

  go(delta) {
    const next = this.i + delta;
    if (next < 0 || next >= this.list.length) {
      if (this.zoom.s === 1) this.img.style.transform = "";
      return;
    }
    history.replaceState({ ...history.state, viewer: { i: next } }, "");
    this.display(next);
  },

  /* ---- Zoom: transform = translate(x, y) scale(s), Ursprung oben links ---- */

  applyZoom(clamp = true) {
    const z = this.zoom;
    if (clamp) this.clampZoom();
    this.img.style.transform = z.s === 1 && !z.x && !z.y ? "" : `translate(${z.x}px, ${z.y}px) scale(${z.s})`;
    this.root.classList.toggle("zoomed", z.s > 1);
  },

  // Bild darf nicht aus dem Bildschirm geschoben werden; kleiner als der Bildschirm -> mittig.
  clampZoom() {
    const z = this.zoom;
    z.s = clampNum(z.s, 1, MAX_ZOOM);
    const p = this.list[this.i];
    const W = this.stage.clientWidth;
    const H = this.stage.clientHeight;
    const ratio = p && p.w && p.ht ? p.w / p.ht : W / H;
    const fit = Math.min(W / ratio, H);
    const cw = fit * ratio;
    const ch = fit;
    const axis = (pos, size, content) => {
      const off = (size - content) / 2;
      const scaled = content * z.s;
      if (scaled <= size) return (size - scaled) / 2 - off * z.s;
      return clampNum(pos, size - (off + content) * z.s, -off * z.s);
    };
    z.x = axis(z.x, W, cw);
    z.y = axis(z.y, H, ch);
  },

  zoomAt(s, cx, cy) {
    const z = this.zoom;
    const next = clampNum(s, 1, MAX_ZOOM);
    z.x = cx - (cx - z.x) * next / z.s;
    z.y = cy - (cy - z.y) * next / z.s;
    z.s = next;
    this.applyZoom();
  },

  resetZoom(animate = true) {
    if (!animate) this.root.classList.add("dragging");
    this.zoom = { s: 1, x: 0, y: 0 };
    this.applyZoom(false);
    if (!animate) {
      void this.img.offsetWidth;
      if (!this.pointers.size) this.root.classList.remove("dragging");
    }
  },

  wheel(e) {
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002));
    this.zoomAt(this.zoom.s * factor, e.clientX, e.clientY);
    if (this.zoom.s < 1.02) this.resetZoom();
  },

  /* ---- Gesten: Wischen, Tippen, Doppeltippen, zwei Finger ---- */

  down(e) {
    this.stage.setPointerCapture(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    this.root.classList.add("dragging");
    if (this.pointers.size === 2) {
      const [a, b] = [...this.pointers.values()];
      if (this.zoom.s === 1) this.img.style.transform = "";
      this.gesture = {
        type: "pinch",
        d0: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        m0: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        s0: this.zoom.s, x0: this.zoom.x, y0: this.zoom.y,
      };
    } else if (this.pointers.size === 1) {
      this.startDrag(e.pointerId, e.clientX, e.clientY, false);
    }
  },

  startDrag(id, x, y, moved) {
    this.gesture = { type: "drag", id, x0: x, y0: y, dx: 0, dy: 0, zx: this.zoom.x, zy: this.zoom.y, moved };
  },

  move(e) {
    const pt = this.pointers.get(e.pointerId);
    if (!pt) return;
    pt.x = e.clientX;
    pt.y = e.clientY;
    const g = this.gesture;
    if (!g) return;
    if (g.type === "pinch") {
      const [a, b] = [...this.pointers.values()];
      const s = clampNum(g.s0 * Math.hypot(a.x - b.x, a.y - b.y) / g.d0, 1, MAX_ZOOM);
      const m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      this.zoom = { s, x: m.x - (g.m0.x - g.x0) * s / g.s0, y: m.y - (g.m0.y - g.y0) * s / g.s0 };
      this.applyZoom(false);
      return;
    }
    if (g.id !== e.pointerId) return;
    g.dx = e.clientX - g.x0;
    g.dy = e.clientY - g.y0;
    if (Math.abs(g.dx) > 8 || Math.abs(g.dy) > 8) g.moved = true;
    if (this.zoom.s > 1) {
      this.zoom.x = g.zx + g.dx;
      this.zoom.y = g.zy + g.dy;
      this.applyZoom();
    } else if (g.moved) {
      const horizontal = Math.abs(g.dx) > Math.abs(g.dy);
      this.img.style.transform = horizontal ? `translateX(${g.dx}px)` : `translateY(${Math.max(0, g.dy)}px)`;
    }
  },

  up(e) {
    if (!this.pointers.delete(e.pointerId)) return;
    const g = this.gesture;
    if (!this.pointers.size) this.root.classList.remove("dragging");
    if (g && g.type === "pinch") {
      if (this.pointers.size === 1) {
        const [[id, p]] = [...this.pointers];
        this.startDrag(id, p.x, p.y, true);
      } else {
        this.gesture = null;
      }
      if (this.zoom.s < 1.05) this.resetZoom();
      else this.applyZoom();
      return;
    }
    if (!g || g.id !== e.pointerId) return;
    this.gesture = null;
    if (!g.moved) {
      this.tap(e.clientX, e.clientY);
      return;
    }
    if (this.zoom.s > 1) return;
    this.img.style.transform = "";
    const { dx, dy } = g;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 60) this.go(dx < 0 ? 1 : -1);
    else if (dy > 120 && Math.abs(dy) > Math.abs(dx)) history.back();
  },

  // Rand antippen blaettert sofort. Mitte (und alles, solange vergroessert):
  // einmal = Bedienelemente aus/ein, zweimal schnell = Zoom ein/aus.
  tap(x, y) {
    const rel = x / window.innerWidth;
    if (this.zoom.s === 1 && (rel < 0.3 || rel > 0.7)) {
      this.lastTap = null;
      this.go(rel < 0.3 ? -1 : 1);
      return;
    }
    const now = performance.now();
    const last = this.lastTap;
    if (last && now - last.t < DOUBLE_TAP_MS && Math.hypot(x - last.x, y - last.y) < 40) {
      clearTimeout(this.tapTimer);
      this.lastTap = null;
      if (this.zoom.s > 1) this.resetZoom();
      else this.zoomAt(2.5, x, y);
      return;
    }
    this.lastTap = { t: now, x, y };
    clearTimeout(this.tapTimer);
    this.tapTimer = setTimeout(() => {
      this.lastTap = null;
      if (this.open) this.root.classList.toggle("ui-hidden");
    }, DOUBLE_TAP_MS);
  },

  reset() {
    this.pointers.clear();
    this.gesture = null;
    this.root.classList.remove("dragging");
    if (this.zoom.s > 1) this.applyZoom();
    else this.resetZoom();
  },
};

/* ---------------------------------------------------------------- Chromecast (v0.7.15) */

// Bild auf den Fernseher (Google TV mit Chromecast) ueber Googles fertigen Empfaenger
// (Default Media Receiver, keine Anmeldung; zeigt Bilder laut Google hoechstens in 1280 × 720).
// Die Cast-Bibliothek gibt es nur direkt von Google und ohne feste Version. Sie wird erst geladen,
// wenn das erste Bild geoeffnet wird. Findet Chrome kein Cast-Geraet im WLAN, bleibt der Knopf versteckt.
// Ein Geraet auswaehlen muss man im Chrome-Fenster selbst (Browser-Regel); danach verbindet die App
// beim naechsten Start von allein wieder (ORIGIN_SCOPED).
const CAST_SDK = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";

const Cast = {
  state: "off",       // off | loading | ready
  btns: [],           // Cast-Knoepfe: Bildbetrachter und Video-Player (v0.8.6)
  ctx: null,
  timer: 0,
  sent: "",           // zuletzt gesendetes Bild (id.hash)

  init() {
    this.addButton($(".v-cast-btn"));
  },

  addButton(btn) {
    this.btns.push(btn);
    btn.addEventListener("click", () => this.click());
    this.update();
  },

  load() {
    if (this.state !== "off" || !window.chrome) return;   // Cast gibt es nur in Chrome
    this.state = "loading";
    window.__onGCastApiAvailable = (ok) => {
      if (ok && window.cast && cast.framework) this.setup();
      else this.state = "off";
    };
    const script = document.createElement("script");
    script.src = CAST_SDK;
    script.async = true;
    script.onerror = () => { this.state = "off"; };       // z. B. ohne Netz: einfach kein Knopf
    document.head.append(script);
  },

  setup() {
    const cf = cast.framework;
    try {
      this.ctx = cf.CastContext.getInstance();
    } catch (e) {
      this.state = "off";
      return;
    }
    // Erst alle Zuhoerer anmelden, dann setOptions (v0.8.8): setOptions kann eine alte Verbindung sofort wieder
    // aufnehmen (ORIGIN_SCOPED) – vorher kam diese Meldung zu frueh, die App wusste nichts davon, der Fernseher
    // spielte weiter und am Handy fehlte die Fernbedienung.
    this.ctx.addEventListener(cf.CastContextEventType.CAST_STATE_CHANGED, () => this.update());
    this.ctx.addEventListener(cf.CastContextEventType.SESSION_STATE_CHANGED, (e) => {
      if (e.sessionState === cf.SessionState.SESSION_STARTED || e.sessionState === cf.SessionState.SESSION_RESUMED) {
        this.joined();
      }
      if (e.sessionState === cf.SessionState.SESSION_ENDED) {
        this.sent = "";
      }
      this.update();
    });
    try {
      this.ctx.setOptions({
        receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
        autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
      });
    } catch (e) {
      this.state = "off";
      return;
    }
    this.state = "ready";
    if (this.connected()) this.joined();        // Verbindung stand schon, bevor die App zuhoerte
    this.update();
  },

  // Verbunden (neu oder wieder aufgenommen): das offene Bild auf den Fernseher
  joined() {
    this.sent = "";
    this.send(true);
  },

  connected() {
    return this.state === "ready" && this.ctx.getCastState() === cast.framework.CastState.CONNECTED;
  },

  update() {
    if (this.state !== "ready") {
      for (const btn of this.btns) btn.hidden = true;
      return;
    }
    const castState = this.ctx.getCastState();
    const on = castState === cast.framework.CastState.CONNECTED;
    const label = on ? "Läuft auf dem Fernseher – antippen zum Beenden" : "Auf dem Fernseher zeigen";
    for (const btn of this.btns) {
      btn.hidden = castState === cast.framework.CastState.NO_DEVICES_AVAILABLE;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", String(on));
      btn.title = label;
      btn.setAttribute("aria-label", label);
    }
  },

  click() {
    if (this.state !== "ready") return;
    if (this.connected()) this.ctx.endCurrentSession(true);
    else this.ctx.requestSession().catch(() => {});      // Auswahl abgebrochen: kein Fehler
  },

  // Aktuelles Bild des Betrachters an den Fernseher; beim schnellen Blaettern nur das letzte senden
  send(now = false) {
    clearTimeout(this.timer);
    if (!this.connected() || !Viewer.open) return;
    this.timer = setTimeout(() => this.push(), now ? 0 : 300);
  },

  push() {
    const session = this.ctx.getCurrentSession();
    const p = Viewer.open && Viewer.list ? Viewer.list[Viewer.i] : null;
    if (!session || !p) return;
    const key = `${p.id}.${p.h}`;
    if (key === this.sent) return;
    this.sent = key;
    const info = new chrome.cast.media.MediaInfo(imageUrl(p), "image/jpeg");
    const meta = new chrome.cast.media.PhotoMediaMetadata();
    meta.title = p.f;
    meta.creationDateTime = p.t;
    const place = placePath(p).reverse().join(", ");
    if (place) meta.location = place;
    info.metadata = meta;
    const done = session.loadMedia(new chrome.cast.media.LoadRequest(info));
    if (done && done.catch) done.catch(() => { if (this.sent === key) this.sent = ""; });
  },
};

function openViewer(i) {
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  navigate({ ...history.state, viewer: { i } });
}

/* ---------------------------------------------------------------- Suche */

// Begriffe: p = Person, o = Ort (Knoten im Baum Land > Bundesland > Stadt > Ort), f = Ordner, y = Jahr, k = Stichwort
const TERM_TYPES = ["p", "o", "f", "y", "k"];
const TERM_GROUP = { p: "Personen", o: "Orte", f: "Ordner", y: "Jahre", k: "Stichwörter" };
const SUGGEST_LIMIT = { p: 6, o: 6, f: 5, y: 4, k: 4 };
const PICK_LIMIT = 12;

// Kleinbuchstaben, ohne Akzente (é -> e, ä -> a, ß -> ss), Satzzeichen -> Leerzeichen
function normText(s) {
  return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/ß/g, "ss").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

const words = (s) => normText(s).split(" ").filter(Boolean);

let SEARCH = null;

// Einmal aufbauen: Begriff -> Positionen in DATA.allDesc (neueste zuerst), je Bild Suchtext und Begriffe.
function buildSearch() {
  const list = DATA.allDesc;
  const terms = new Map();
  const children = new Map();
  const add = (type, key, i, props) => {
    let t = terms.get(key);
    if (!t) {
      t = { key, type, ids: [], ...props };
      terms.set(key, t);
    }
    if (t.ids[t.ids.length - 1] !== i) t.ids.push(i);
    return t;
  };
  const folderInfo = new Map();
  for (const f of DATA.index.folders) {
    const label = folderLabel(f);
    folderInfo.set(f.n, f.x ? { name: f.n, sub: String(f.y) } : { name: label.name, sub: label.date || String(f.y) });
  }
  const text = new Array(list.length);
  const photoTerms = new Array(list.length);
  const starred = [];
  list.forEach((p, i) => {
    const mine = [];
    for (const name of p.p || []) {
      const norm = normText(name);
      if (norm) mine.push(add("p", `p:${norm}`, i, { label: name, sub: "", norm }).key);
    }
    let path = "";
    const labels = [];
    for (const place of placePath(p, SEARCH_PLACE_KEYS)) {
      const norm = normText(place);
      const parent = path;
      path = path ? `${path}|${norm}` : norm;
      const key = `o:${path}`;
      if (!terms.has(key)) {
        if (!children.has(parent)) children.set(parent, []);
        children.get(parent).push(key);
      }
      mine.push(add("o", key, i, { label: place, sub: labels.slice().reverse().join(", "), norm, parent }).key);
      labels.push(place);
    }
    const fi = folderInfo.get(p.f) || { name: p.f, sub: "" };
    add("f", `f:${p.f}`, i, { label: fi.name, sub: fi.sub, norm: normText(`${p.f} ${fi.name}`) });
    const year = p.t.slice(0, 4);
    mine.push(add("y", `y:${year}`, i, { label: year, sub: "", norm: year }).key);
    const decade = `${year.slice(0, 3)}0er`;   // Jahrzehnt, z. B. "2010er" (v0.6.37)
    mine.push(add("y", `y:${decade}`, i, { label: decade, sub: `${year.slice(0, 3)}0–${year.slice(0, 3)}9`, norm: decade, decade: true }).key);
    for (const k of p.kw || []) {
      const norm = normText(k);
      if (norm) mine.push(add("k", `k:${norm}`, i, { label: k, sub: "", norm }).key);
    }
    photoTerms[i] = mine;
    if (p.r) starred.push(i);
    const parts = [p.de, p.sl, p.ci, p.st, p.co, p.f, ...(p.p || []), ...(p.kw || []), ...(p._en || [])];
    text[i] = ` ${normText(parts.filter(Boolean).join(" "))} `;
  });
  return { terms, children, text, photoTerms, starred };
}

// Gewaehlte Begriffe (UND) plus Freitext (alle Woerter muessen vorkommen). null = keine Suche.
function searchPositions(keys, freeText) {
  const chosen = keys.map((k) => SEARCH.terms.get(k)).filter(Boolean).sort((a, b) => a.ids.length - b.ids.length);
  let pos = null;
  if (chosen.length) {
    pos = chosen[0].ids;
    for (const t of chosen.slice(1)) {
      const set = t.set || (t.set = new Set(t.ids));
      pos = pos.filter((i) => set.has(i));
    }
  }
  if (starsOnly()) pos = (pos || SEARCH.starred).filter((i) => passStars(DATA.allDesc[i]));
  const w = words(freeText);
  if (w.length) {
    const base = pos || DATA.allDesc.map((_, i) => i);
    pos = base.filter((i) => w.every((x) => SEARCH.text[i].includes(x)));
  }
  return pos;
}

// Anzahl je Begriff innerhalb der aktuellen Treffer
function termCounts(pos) {
  const counts = new Map();
  const count = (i) => {
    for (const key of SEARCH.photoTerms[i]) counts.set(key, (counts.get(key) || 0) + 1);
  };
  if (pos) pos.forEach(count);
  else for (let i = 0; i < SEARCH.photoTerms.length; i++) count(i);
  return counts;
}

function suggestTerms(query, keys) {
  const w = words(query);
  if (!w.length) return [];
  const within = searchPositions(keys, "");
  let member = null;
  if (within) {
    member = new Uint8Array(DATA.allDesc.length);
    for (const i of within) member[i] = 1;
  }
  const hits = [];
  for (const t of SEARCH.terms.values()) {
    if (keys.includes(t.key) || !w.every((x) => t.norm.includes(x))) continue;
    let count = t.ids.length;
    if (member) {
      count = 0;
      for (const i of t.ids) count += member[i];
    }
    if (!count) continue;
    const padded = ` ${t.norm}`;
    const starts = t.norm === w.join(" ") ? 0 : w.every((x) => padded.includes(` ${x}`)) ? 1 : 2;
    hits.push({ t, count, starts });
  }
  const out = [];
  for (const type of TERM_TYPES) {
    const group = hits.filter((h) => h.t.type === type)
      .sort((a, b) => a.starts - b.starts || b.count - a.count || a.t.label.localeCompare(b.t.label, "de"))
      .slice(0, SUGGEST_LIMIT[type]);
    if (group.length) out.push({ type, items: group });
  }
  // Gruppe mit exaktem Treffer (z. B. "2019" -> Jahr) nach oben
  return out.sort((a, b) => (a.items[0].starts === 0 ? 0 : 1) - (b.items[0].starts === 0 ? 0 : 1));
}

let lastSearch = { q: [], t: "" };

const ICON_SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/></svg>';
const ICON_X = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
const ICON_CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5.5 15.5 12 9 18.5"/></svg>';

function svgNode(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup;
  return t.content.firstChild;
}

// Zwei Modi: "select" (Begriffe waehlen, Anzahl sichtbar, keine Bilder) und "results" (Raster).
// "Anzeigen" legt einen neuen Verlaufseintrag an -> Zurueck-Taste fuehrt vom Raster zur Auswahl.
function mountSearch(main, state, m) {
  if (!SEARCH) SEARCH = buildSearch();
  const s = { keys: [], text: "", mode: "select", panel: false, shown: null, open: new Set(), allPersons: false, allPlaces: null, pending: null };

  const chips = el("div", { class: "chips" });
  const input = el("input", {
    type: "search", placeholder: "Person, Ort, Ordner, Jahr oder Text …", enterkeyhint: "search",
    autocomplete: "off", autocapitalize: "off", spellcheck: "false", "aria-label": "Suchbegriff",
  });
  const clear = el("button", { type: "button", class: "icon-btn search-clear", "aria-label": "Eingabe löschen" }, svgNode(ICON_X));
  const countText = el("span", { class: "search-count" });
  const order = el("button", { type: "button", class: "search-order", hidden: true });
  const action = el("button", { type: "button", class: "search-action" });
  const bar = el("div", { class: "search-bar" },
    chips,
    el("div", { class: "search-field" }, svgNode(ICON_SEARCH), input, clear),
    el("div", { class: "search-status" }, countText, order, action));
  const body = el("div", { class: "search-body" });
  const results = el("div", { class: "search-results" });
  main.append(bar, body, results);

  const hasFilter = () => s.keys.length > 0 || words(s.text).length > 0 || starsOnly();

  // Kleiner Umschalter im Raster: aelteste / neueste zuerst (gemerkt, gilt auch fuer Alle Bilder)
  function renderOrder() {
    order.hidden = s.mode !== "results";
    order.textContent = orderLabel();
    order.title = "Reihenfolge umdrehen";
  }
  order.addEventListener("click", () => {
    toggleOrder();
    renderOrder();
    renderResults();
  });

  // Aenderungen im Raster-Modus: erst zur Auswahl zurueck (Verlauf), dann ausfuehren
  const edit = (fn) => {
    if (s.mode === "results") {
      s.pending = fn;
      history.back();
    } else {
      fn();
    }
  };

  const addKey = (key) => edit(() => {
    s.keys.push(key);
    s.text = "";
    input.value = "";
    s.panel = false;
    input.blur();
    update();
  });

  const removeKey = (key) => edit(() => {
    s.keys = s.keys.filter((k) => k !== key);
    update();
  });

  function showResults() {
    if (!hasFilter()) return;
    s.panel = false;
    input.blur();
    navigate({ v: "search", q: s.keys.slice(), t: s.text, r: 1 });
  }

  const pick = (t, count) => el("button", { type: "button", class: "pick", onclick: () => addKey(t.key) },
    t.label, el("small", { text: count.toLocaleString("de-DE") }));

  function renderChips() {
    chips.replaceChildren(...s.keys.map((key) => {
      const t = SEARCH.terms.get(key);
      return el("button", {
        type: "button", class: "chip", title: `${TERM_GROUP[t.type]} – entfernen`, onclick: () => removeKey(key),
      }, el("span", { text: t.label }), svgNode(ICON_X));
    }));
    clear.hidden = !s.text;
  }

  function renderStatus(pos) {
    const n = pos ? pos.length : DATA.allDesc.length;
    if (s.mode === "results") {
      countText.textContent = countLabel(n);
      action.textContent = "Ändern";
      action.disabled = false;
      action.onclick = () => history.back();
    } else if (hasFilter()) {
      countText.textContent = n ? `${countLabel(n)} passen` : "Keine Bilder passen";
      action.textContent = "Anzeigen";
      action.disabled = n === 0;
      action.onclick = showResults;
    } else {
      countText.textContent = `${countLabel(n)} – Begriffe wählen`;
      action.textContent = "Anzeigen";
      action.disabled = true;
      action.onclick = null;
    }
  }

  function renderPanel() {
    const nodes = [];
    const free = searchPositions(s.keys, s.text);
    nodes.push(el("button", {
      type: "button", class: "sg-row sg-free", onclick: () => { s.panel = false; input.blur(); update(); },
    }, el("span", { class: "name", text: `Alle Bilder mit „${s.text.trim()}“ (Text)` }),
    el("span", { class: "meta", text: free && free.length ? countLabel(free.length) : "keine Treffer" })));
    for (const group of suggestTerms(s.text, s.keys)) {
      nodes.push(el("div", { class: "sg-head", text: TERM_GROUP[group.type] }));
      for (const { t, count } of group.items) {
        nodes.push(el("button", { type: "button", class: "sg-row", onclick: () => addKey(t.key) },
          el("span", { class: "name", text: t.label }),
          el("span", { class: "meta", text: t.sub ? `${t.sub} · ${countLabel(count)}` : countLabel(count) })));
      }
    }
    body.replaceChildren(...nodes);
  }

  // Orte wie die Personen als kleine Knoepfe mit Anzahl (v0.7.17): erst Laender, nach der Wahl eines
  // Landes dessen Staedte, nach der Wahl einer Stadt deren Orte; die 12 haeufigsten, "alle … zeigen"
  function placePicks(counts) {
    const chosen = s.keys.filter((k) => k.startsWith("o:")).map((k) => k.slice(2))
      .sort((a, b) => b.split("|").length - a.split("|").length);
    const parent = chosen[0] || "";
    const kids = (SEARCH.children.get(parent) || []).filter((k) => counts.get(k) && !s.keys.includes(k))
      .sort((a, b) => counts.get(b) - counts.get(a) || SEARCH.terms.get(a).label.localeCompare(SEARCH.terms.get(b).label, "de"));
    if (!kids.length) return [];
    const all = s.allPlaces === parent;
    const shown = all ? kids : kids.slice(0, PICK_LIMIT);
    const box = el("div", { class: "picks" }, ...shown.map((k) => pick(SEARCH.terms.get(k), counts.get(k))));
    if (kids.length > PICK_LIMIT) {
      box.append(el("button", {
        type: "button", class: "pick pick-more",
        onclick: () => { s.allPlaces = all ? null : parent; renderFacets(); },
      }, all ? "weniger" : `alle ${kids.length} zeigen`));
    }
    const depth = parent ? parent.split("|").length : 0;
    const head = !parent ? "Orte" : `${depth === 1 ? "Städte" : "Orte"} in ${SEARCH.terms.get(`o:${parent}`).label}`;
    return [el("div", { class: "sg-head", text: head }), box];
  }

  // Jahre (v0.6.37): aktuelles Jahrzehnt direkt, davor aufklappbare Jahrzehnte ("2010er" -> 2019 … 2010, "Ganz 2010er")
  function yearNodes(counts) {
    const current = `${String(new Date().getFullYear()).slice(0, 3)}0er`;
    const yearKeys = [...counts.keys()].filter((k) => /^y:\d{4}$/.test(k)).sort().reverse();
    const decadeOf = (k) => `y:${k.slice(2, 5)}0er`;
    const picks = (keys) => keys.filter((k) => !s.keys.includes(k)).map((k) => pick(SEARCH.terms.get(k), counts.get(k)));
    const nodes = [];
    const recent = picks(yearKeys.filter((k) => decadeOf(k) === `y:${current}`));
    if (recent.length) nodes.push(el("div", { class: "picks" }, ...recent));
    const decades = [...new Set(yearKeys.map(decadeOf))].filter((d) => d !== `y:${current}`);
    const rows = [];
    for (const key of decades) {
      const t = SEARCH.terms.get(key);
      const n = counts.get(key);
      const isChosen = s.keys.includes(key);
      const inner = picks(yearKeys.filter((k) => decadeOf(k) === key));
      const open = isChosen || s.open.has(key) || s.keys.some((k) => /^y:\d{4}$/.test(k) && decadeOf(k) === key);
      rows.push(el("button", {
        type: "button",
        class: "tree-row" + (open ? " open" : "") + (isChosen ? " chosen" : ""),
        "aria-expanded": String(open),
        onclick: () => {
          if (isChosen) return;
          if (s.open.has(key)) s.open.delete(key);
          else s.open.add(key);
          renderFacets();
        },
      }, el("span", { class: "name", text: t.label }), el("span", { class: "meta", text: n.toLocaleString("de-DE") }),
      svgNode(ICON_CHEVRON)));
      if (!open) continue;
      if (!isChosen) {
        rows.push(el("button", {
          type: "button", class: "tree-row tree-all", style: "padding-left:36px", onclick: () => addKey(key),
        }, el("span", { class: "name", text: `Ganz ${t.label} (${t.sub})` }), el("span", { class: "meta", text: n.toLocaleString("de-DE") }),
        el("span", { class: "chev-space" })));
      }
      if (inner.length) rows.push(el("div", { class: "picks tree-picks" }, ...inner));
    }
    if (rows.length) nodes.push(el("div", { class: "tree" }, ...rows));
    return nodes;
  }

  function renderFacets() {
    const counts = termCounts(searchPositions(s.keys, s.text));
    const ofType = (type) => [...counts.keys()].filter((k) => k.startsWith(`${type}:`) && !s.keys.includes(k))
      .map((k) => SEARCH.terms.get(k));
    const byCount = (a, b) => counts.get(b.key) - counts.get(a.key) || a.label.localeCompare(b.label, "de");
    const nodes = [];

    const persons = ofType("p").sort(byCount);
    if (persons.length) {
      const shown = s.allPersons ? persons : persons.slice(0, PICK_LIMIT);
      const box = el("div", { class: "picks" }, ...shown.map((t) => pick(t, counts.get(t.key))));
      if (persons.length > PICK_LIMIT) {
        box.append(el("button", {
          type: "button", class: "pick pick-more",
          onclick: () => { s.allPersons = !s.allPersons; renderFacets(); },
        }, s.allPersons ? "weniger" : `alle ${persons.length} zeigen`));
      }
      box.append(el("button", { type: "button", class: "pick pick-more", onclick: () => navigate({ v: "people" }) }, "Personenseite ›"));
      nodes.push(el("div", { class: "sg-head", text: "Personen" }), box);
    }
    nodes.push(...placePicks(counts));
    const years = yearNodes(counts);
    if (years.length) nodes.push(el("div", { class: "sg-head", text: "Jahre" }), ...years);
    const keywords = ofType("k").sort(byCount).slice(0, 30);
    if (keywords.length) nodes.push(el("div", { class: "sg-head", text: "Stichwörter" }), el("div", { class: "picks" }, ...keywords.map((t) => pick(t, counts.get(t.key)))));
    if (!nodes.length) nodes.push(el("p", { class: "center muted", text: "Nichts weiter einzugrenzen." }));
    body.replaceChildren(...nodes);
  }

  function renderResults() {
    const signature = JSON.stringify([s.keys, words(s.text), oldestFirst(), starLevel()]);
    if (signature === s.shown) {
      if (m.grid) {
        m.grid.render();
        $("#subtitle").textContent = m.grid.lastSection || "";
      }
      return;
    }
    s.shown = signature;
    if (m.grid) m.grid.destroy();
    m.grid = null;
    results.replaceChildren();
    const pos = searchPositions(s.keys, s.text) || [];
    m.list = pos.map((i) => DATA.allDesc[i]);
    if (oldestFirst()) m.list.reverse();
    window.scrollTo(0, 0);
    if (!m.list.length) {
      results.append(el("p", { class: "center muted", text: "Keine Bilder gefunden." }));
      return;
    }
    // Ueberschrift je Jahr; das Jahr oben im Bild steht im Untertitel der Kopfzeile
    // genau eine Person gewaehlt und Geburtsdatum bekannt: Alter in der Ueberschrift (v0.7.16)
    const personKeys = s.keys.filter((k) => k.startsWith("p:"));
    const person = personKeys.length === 1 ? SEARCH.terms.get(personKeys[0]).label : "";
    const yearOf = yearSectionOf(m.list, person ? birthOf(person) : "", person);
    m.grid = new Grid(results, m.list, yearOf, (year) => {
      if (s.mode === "results") $("#subtitle").textContent = year || "";
    });
  }

  function update() {
    lastSearch = { q: s.keys.slice(), t: s.text };
    if (s.mode === "select") history.replaceState({ v: "search", q: lastSearch.q, t: s.text }, "");
    renderChips();
    const pos = searchPositions(s.keys, s.text);
    renderStatus(pos);
    renderOrder();
    if (s.mode === "results") {
      $("#subtitle").textContent = "";
      body.replaceChildren();
      results.hidden = false;
      renderResults();
      return;
    }
    $("#subtitle").textContent = "";
    results.hidden = true;
    if (s.panel && s.text.trim()) renderPanel();
    else renderFacets();
  }

  function apply(st) {
    const mode = st.r ? "results" : "select";
    s.keys = (st.q || lastSearch.q).filter((k) => SEARCH.terms.has(k));
    s.text = st.t !== undefined ? st.t : lastSearch.t;
    if (input.value !== s.text) input.value = s.text;
    if (mode !== s.mode) {
      s.mode = mode;
      s.panel = false;
      if (mode === "select") window.scrollTo(0, 0);
    }
    update();
    const fn = s.pending;
    s.pending = null;
    if (fn && s.mode === "select") fn();
  }

  input.addEventListener("input", () => {
    s.text = input.value;
    s.panel = true;
    update();
  });
  input.addEventListener("focus", () => {
    if (s.mode === "results") {
      edit(() => {});
      return;
    }
    if (s.text.trim() && !s.panel) {
      s.panel = true;
      update();
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (hasFilter() && searchPositions(s.keys, s.text).length) showResults();
    else { s.panel = false; input.blur(); update(); }
  });
  clear.addEventListener("click", () => edit(() => {
    s.text = "";
    input.value = "";
    s.panel = false;
    update();
  }));

  m.search = { apply };
  m.toggleStars = () => {
    toggleStars();
    showStarButton();
    apply(history.state || { v: "search" });
  };
  apply(state);
}

/* ---------------------------------------------------------------- Karte (v0.7.0) */

// Leaflet + Gruppierung liegen fest versioniert unter docs/vendor/ und werden erst beim Oeffnen der Karte geladen.
const LEAFLET_DIR = "vendor/leaflet-1.9.4";
const CLUSTER_DIR = "vendor/leaflet.markercluster-1.5.3";
const MAP_VIEW_KEY = "fotoschatz.map";   // letzte Kartenansicht "lat,lng,zoom"
const RADII = [1, 5, 20, 50];            // Umkreis in km
const ICON_LOCATE = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>';

let MAP = null;
let leafletLoading = null;

const hasGps = (p) => typeof p.la === "number" && typeof p.lo === "number" && !(p.la === 0 && p.lo === 0);

function quantile(values, q) {
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
}

function distanceKm(a, b, c, d) {
  const rad = Math.PI / 180;
  const x = Math.sin((c - a) * rad / 2) ** 2 + Math.cos(a * rad) * Math.cos(c * rad) * Math.sin((d - b) * rad / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(Math.min(1, x)));
}

function loadLeaflet() {
  if (!leafletLoading) {
    const script = (src) => new Promise((resolve, reject) => {
      document.head.append(el("script", { src, onload: resolve, onerror: () => reject(new Error(src)) }));
    });
    document.head.append(el("link", { rel: "stylesheet", href: `${LEAFLET_DIR}/leaflet.css` }),
      el("link", { rel: "stylesheet", href: `${CLUSTER_DIR}/MarkerCluster.css` }));
    leafletLoading = script(`${LEAFLET_DIR}/leaflet.js`).then(() => script(`${CLUSTER_DIR}/leaflet.markercluster.js`));
    leafletLoading.catch(() => { leafletLoading = null; });
  }
  return leafletLoading;
}

// Orte aus den eigenen Bildern (Land › Stadt › Ort, wie in der Suche); Mitte = Median der GPS-Punkte
function mapPlaces() {
  if (MAP.places) return MAP.places;
  const byKey = new Map();
  for (const p of MAP.points) {
    const path = placePath(p, SEARCH_PLACE_KEYS);
    let key = "";
    path.forEach((name, depth) => {
      key += `|${normText(name)}`;
      let e = byKey.get(key);
      if (!e) {
        e = { label: name, sub: path.slice(0, depth).reverse().join(", "), norm: normText(name), country: depth === 0, la: [], lo: [] };
        byKey.set(key, e);
      }
      e.la.push(p.la);
      e.lo.push(p.lo);
    });
  }
  MAP.places = [...byKey.values()].map((e) => ({
    label: e.label, sub: e.sub, norm: e.norm, country: e.country, n: e.la.length,
    center: [quantile(e.la, 0.5), quantile(e.lo, 0.5)],
    bounds: [[quantile(e.la, 0.02), quantile(e.lo, 0.02)], [quantile(e.la, 0.98), quantile(e.lo, 0.98)]],
  }));
  return MAP.places;
}

function findPlaces(query) {
  const w = words(query);
  if (!w.length) return [];
  return mapPlaces().filter((pl) => w.every((x) => pl.norm.includes(x)))
    .map((pl) => ({ pl, starts: pl.norm.startsWith(w[0]) ? 0 : 1 }))
    .sort((a, b) => a.starts - b.starts || b.pl.n - a.pl.n)
    .slice(0, 8).map((x) => x.pl);
}

// Kachel auf der Karte: Vorschaubild, bei Gruppen mit Anzahl
function pinIcon(p, count) {
  const style = focusStyle(p);
  const img = `<img src="${thumbUrl(p)}" alt="" loading="lazy" decoding="async"${style ? ` style="${style}"` : ""}>`;
  const size = count ? 42 : 36;
  return L.divIcon({
    html: count ? `${img}<span>${count.toLocaleString("de-DE")}</span>` : img,
    className: count ? "map-pin map-group" : "map-pin",
    iconSize: [size, size],
  });
}

// Titelbild einer Gruppe: am liebsten ★★, dann ★, dann das neueste
function groupPhoto(cluster) {
  if (cluster.fsPhoto) return cluster.fsPhoto;
  let best = null;
  if (cluster.getChildCount() <= 300) {
    for (const marker of cluster.getAllChildMarkers()) {
      const p = marker.photo;
      if (!best || (p.r || 0) > (best.r || 0) || ((p.r || 0) === (best.r || 0) && p.t > best.t)) best = p;
    }
  } else {
    let c = cluster;
    while (!c._markers.length && c._childClusters.length) c = c._childClusters[0];
    best = (c._markers[0] || cluster.getAllChildMarkers()[0]).photo;
  }
  cluster.fsPhoto = best;
  return best;
}

function mapView() {
  if (MAP) return MAP;
  const input = el("input", {
    type: "search", placeholder: "Ort suchen …", enterkeyhint: "search",
    autocomplete: "off", autocapitalize: "off", spellcheck: "false", "aria-label": "Ort suchen",
  });
  const clear = el("button", { type: "button", class: "icon-btn search-clear", "aria-label": "Eingabe löschen", hidden: true }, svgNode(ICON_X));
  const suggest = el("div", { class: "map-suggest", hidden: true });
  const radius = el("div", { class: "map-radius", hidden: true });
  const canvas = el("div", { class: "map-canvas" });
  const locate = el("button", { type: "button", class: "map-locate", title: "In meiner Nähe", "aria-label": "In meiner Nähe" }, svgNode(ICON_LOCATE));
  const bar = el("button", { type: "button", class: "map-bar", disabled: true, text: "Karte wird geladen …" });
  const wrap = el("div", { class: "map-wrap" }, canvas,
    el("div", { class: "map-top" }, el("div", { class: "search-field map-field" }, svgNode(ICON_SEARCH), input, clear), suggest, radius),
    locate, bar);
  MAP = {
    wrap, canvas, input, clear, suggest, radius, locate, bar,
    map: null, cluster: null, circle: null,
    points: DATA.photos.filter(hasGps), places: null,
    center: null, label: "", km: 5, result: [], shown: null,
  };

  const showSuggest = () => {
    const found = findPlaces(input.value);
    clear.hidden = !input.value;
    suggest.hidden = !found.length && !words(input.value).length;
    suggest.replaceChildren(...(found.length ? found.map((pl) => el("button", {
      type: "button", class: "sg-row", onclick: () => choosePlace(pl),
    }, el("span", { class: "name", text: pl.label }),
    el("span", { class: "meta", text: pl.sub ? `${pl.sub} · ${countLabel(pl.n)}` : countLabel(pl.n) })))
      : [el("p", { class: "sg-empty", text: "Kein Ort mit Bildern gefunden – oder lange auf die Karte drücken." })]));
  };
  input.addEventListener("input", showSuggest);
  input.addEventListener("focus", () => { if (input.value) showSuggest(); });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const first = findPlaces(input.value)[0];
    if (first) choosePlace(first);
  });
  clear.addEventListener("click", () => {
    input.value = "";
    clear.hidden = true;
    suggest.hidden = true;
    clearCenter();
  });
  locate.addEventListener("click", () => {
    if (!navigator.geolocation) return flashBar("Standort ist hier nicht verfügbar.");
    bar.textContent = "Standort wird gesucht …";
    navigator.geolocation.getCurrentPosition(
      (pos) => setCenter([pos.coords.latitude, pos.coords.longitude], "deinen Standort"),
      () => flashBar("Standort nicht verfügbar – Erlaubnis im Browser prüfen."),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 });
  });
  bar.addEventListener("click", () => {
    if (!MAP.result.length) return;
    MAP.shown = { list: MAP.result, sub: barText() };
    navigate({ v: "mapgrid" });
  });
  return MAP;
}

function initMap() {
  const M = MAP;
  const map = L.map(M.canvas, { zoomControl: false, preferCanvas: true, worldCopyJump: true, maxZoom: 18 });
  map.attributionControl.setPrefix(false);
  // Kartenbilder von OpenStreetMap (v0.7.2 wieder, CARTO verlangte am Handy einen API-Schluessel)
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
    referrerPolicy: "strict-origin-when-cross-origin",   // OSM verlangt einen Referer; das Geheimnis steht im Hash und wird nie gesendet
  }).addTo(map);
  const cluster = L.markerClusterGroup({
    chunkedLoading: true, showCoverageOnHover: false, zoomToBoundsOnClick: false, spiderfyOnMaxZoom: false,
    maxClusterRadius: 80, iconCreateFunction: (c) => pinIcon(groupPhoto(c), c.getChildCount()),
  });
  cluster.addLayers(M.points.map((p) => {
    const marker = L.marker([p.la, p.lo], { icon: pinIcon(p, 0), keyboard: false });
    marker.photo = p;
    return marker;
  }));
  // Gruppe antippen: hineinzoomen; liegen alle Bilder an einer Stelle, gleich als Raster zeigen
  cluster.on("clusterclick", (e) => {
    const c = e.layer;
    const b = c.getBounds();
    if (map.getZoom() >= map.getMaxZoom() || b.getNorthEast().equals(b.getSouthWest(), 0.0002)) {
      const list = c.getAllChildMarkers().map((mk) => mk.photo).sort((x, y) => (x.t < y.t ? -1 : 1));
      MAP.shown = { list, sub: `${countLabel(list.length)} an dieser Stelle` };
      navigate({ v: "mapgrid" });
    } else {
      c.zoomToBounds({ padding: [48, 48] });
    }
  });
  cluster.on("click", (e) => openMapPhoto(e.layer.photo));
  map.addLayer(cluster);
  map.on("moveend", () => {
    const c = map.getCenter();
    writePref(MAP_VIEW_KEY, `${c.lat.toFixed(5)},${c.lng.toFixed(5)},${map.getZoom()}`);
    updateBar();
  });
  map.on("contextmenu", (e) => setCenter([e.latlng.lat, e.latlng.lng], "den markierten Punkt", false));
  map.on("click", () => { M.suggest.hidden = true; M.input.blur(); });
  M.map = map;
  M.cluster = cluster;

  const saved = (readPref(MAP_VIEW_KEY) || "").split(",").map(Number);
  if (saved.length === 3 && saved.every(Number.isFinite)) map.setView([saved[0], saved[1]], saved[2]);
  else if (M.points.length) {
    const la = M.points.map((p) => p.la);
    const lo = M.points.map((p) => p.lo);
    map.fitBounds([[quantile(la, 0.01), quantile(lo, 0.01)], [quantile(la, 0.99), quantile(lo, 0.99)]], { padding: [40, 40] });
  } else map.setView([30, 10], 2);
}

function accentColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f6fdb";
}

function setCenter(center, label, fit = true) {
  const M = MAP;
  M.center = center;
  M.label = label;
  if (!M.circle) {
    M.circle = L.circle(center, { radius: M.km * 1000, color: accentColor(), weight: 2, fillOpacity: 0.08, interactive: false }).addTo(M.map);
  } else {
    M.circle.setLatLng(center);
    M.circle.setRadius(M.km * 1000);
  }
  renderRadius();
  if (fit) M.map.fitBounds(M.circle.getBounds(), { padding: [24, 24] });
  updateBar();
}

function clearCenter() {
  const M = MAP;
  if (M.circle) M.circle.remove();
  M.circle = null;
  M.center = null;
  renderRadius();
  updateBar();
}

function choosePlace(pl) {
  const M = MAP;
  M.input.value = pl.label;
  M.clear.hidden = false;
  M.suggest.hidden = true;
  M.input.blur();
  if (pl.country) {
    clearCenter();
    M.map.fitBounds(pl.bounds, { padding: [32, 32], maxZoom: 12 });
  } else {
    setCenter(pl.center, pl.label);
  }
}

function renderRadius() {
  const M = MAP;
  M.radius.hidden = !M.center;
  if (!M.center) return;
  M.radius.replaceChildren(
    el("span", { class: "map-radius-label", text: "Umkreis" }),
    ...RADII.map((km) => el("button", {
      type: "button", class: "r" + (km === M.km ? " on" : ""), text: `${km} km`,
      onclick: () => {
        M.km = km;
        setCenter(M.center, M.label);
      },
    })),
    el("button", { type: "button", class: "icon-btn r-off", "aria-label": "Umkreis aus", onclick: clearCenter }, svgNode(ICON_X)));
}

// Bilder im Umkreis (wenn gesetzt) bzw. im sichtbaren Kartenausschnitt, aelteste zuerst
function mapResult() {
  const M = MAP;
  if (M.center) {
    const [a, b] = M.center;
    return M.points.filter((p) => distanceKm(a, b, p.la, p.lo) <= M.km);
  }
  const bounds = M.map.getBounds();
  const west = bounds.getWest();
  const east = bounds.getEast();
  if (east - west >= 360) return M.points.filter((p) => p.la >= bounds.getSouth() && p.la <= bounds.getNorth());
  const shift = (lo) => (lo < west ? lo + 360 : lo > east ? lo - 360 : lo);
  return M.points.filter((p) => p.la >= bounds.getSouth() && p.la <= bounds.getNorth()
    && shift(p.lo) >= west && shift(p.lo) <= east);
}

function barText() {
  const M = MAP;
  const n = M.result.length;
  if (M.center) return `${countLabel(n)} im Umkreis von ${M.km} km um ${M.label}`;
  return n ? `${countLabel(n)} hier` : "Keine Bilder in diesem Ausschnitt";
}

function updateBar() {
  const M = MAP;
  if (!M || !M.map) return;
  M.result = mapResult();
  if (mounted && mounted.key === "map") mounted.list = M.result;
  M.bar.disabled = !M.result.length;
  M.bar.textContent = M.result.length ? `${barText()} ›` : barText();
}

function flashBar(text) {
  MAP.bar.textContent = text;
  setTimeout(updateBar, 3000);
}

// Einzelnes Bild antippen: Betrachter mit den Bildern im Umkreis bzw. Ausschnitt (zum Weiterblättern)
function openMapPhoto(p) {
  updateBar();
  let i = MAP.result.indexOf(p);
  if (i < 0) {
    MAP.result = [p];
    i = 0;
  }
  mounted.list = MAP.result;
  openViewer(i);
}

function focusMapAt(at) {
  if (!MAP || !MAP.map) return;
  clearCenter();
  MAP.map.setView(at, 17);
}

/* ---------------------------------------------------------------- Weltkarte (v0.7.3) */

// "Wann war ich wo?": Laender aus dem Lightroom-Feld Land (auch Bilder ohne GPS), Jahre aus der Aufnahmezeit.
// Ohne Kartenbilder – nur Laenderumrisse (Natural Earth, gemeinfrei, docs/vendor/natural-earth/laender.json).
const WORLD_FILE = "vendor/natural-earth/laender.json";
const WORLD_SINCE = "1978-04-06";   // nur Bilder ab meiner Geburt (Wunsch 07.10.2026, v0.7.4)
let WORLD = null;
let countryCodes = null;
// alte bzw. Sammel-Codes, die der Browser auch kennt (DD = DDR heisst auf Deutsch auch "Deutschland")
const OLD_REGION_CODES = new Set(["DD", "FX", "YU", "CS", "SU", "ZR", "TP", "BU", "NT", "VD", "YD", "AN", "NH", "RH", "BU", "DY", "HV", "EU", "EZ", "UN", "QO", "ZZ", "XA", "XB"]);
const UK_PARTS = { "England": "GB", "Scotland": "GB", "Wales": "GB", "Northern Ireland": "GB", "Schottland": "GB" };

// Laendername (englisch wie in Lightroom oder schon deutsch) -> ISO-Code
function countryCodeOf(name) {
  if (!countryCodes) {
    countryCodes = new Map();
    try {
      const en = new Intl.DisplayNames(["en"], { type: "region", fallback: "none" });
      const de = new Intl.DisplayNames(["de"], { type: "region", fallback: "none" });
      for (let a = 65; a <= 90; a++) {
        for (let b = 65; b <= 90; b++) {
          const code = String.fromCharCode(a, b);
          if (OLD_REGION_CODES.has(code)) continue;
          for (const names of [en, de]) {
            let n;
            try { n = names.of(code); } catch (e) { continue; }
            // erster Code gewinnt: "France" ist FR, nicht FX (Metropolitan France)
            if (!n || n === code) continue;
            for (const variant of [n, n.replace(/&/g, "and"), n.replace(/&/g, "und"), n.replace(/^St\. /, "Saint ")]) {
              if (!countryCodes.has(normText(variant))) countryCodes.set(normText(variant), code);
            }
          }
        }
      }
    } catch (e) { /* alter Browser: Laender ohne Umriss */ }
    for (const [n, code] of Object.entries({ ...COUNTRY_ALIASES, ...UK_PARTS })) countryCodes.set(normText(n), code);
  }
  return countryCodes.get(normText(name)) || null;
}

function countryName(code) {
  try {
    return new Intl.DisplayNames(["de"], { type: "region", fallback: "none" }).of(code) || code;
  } catch (e) {
    return code;
  }
}

// [1997, 1998, 1999, 2006] -> "1997–1999 · 2006"
function yearRanges(years) {
  const sorted = [...years].sort((a, b) => a - b);
  const parts = [];
  for (let i = 0; i < sorted.length; i++) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(j > i ? `${sorted[i]}–${sorted[j]}` : String(sorted[i]));
    i = j;
  }
  return parts.join(" · ");
}

// je Land: Name, Code, Jahre, Anzahl Bilder; sortiert nach erstem Besuch
function worldCountries() {
  if (WORLD && WORLD.countries) return WORLD.countries;
  const byKey = new Map();
  for (const p of DATA.photos) {
    if (!p.co || p.t < WORLD_SINCE) continue;
    const code = countryCodeOf(p.co);
    const key = code || `?${normText(p.co)}`;
    let c = byKey.get(key);
    if (!c) {
      c = { key, code, name: p.co, years: new Set(), n: 0 };
      byKey.set(key, c);
    }
    c.years.add(+p.t.slice(0, 4));
    c.n++;
  }
  const list = [...byKey.values()].map((c) => ({
    ...c, first: Math.min(...c.years), last: Math.max(...c.years), ranges: yearRanges(c.years),
  }));
  list.sort((a, b) => a.first - b.first || a.name.localeCompare(b.name, "de"));
  return list;
}

function worldView() {
  if (WORLD) return WORLD;
  const canvas = el("div", { class: "world-canvas" });
  const card = el("div", { class: "world-card", hidden: true });
  const bar = el("button", { type: "button", class: "map-bar", text: "Liste aller Länder ›", onclick: () => navigate({ v: "countries" }) });
  WORLD = { wrap: el("div", { class: "map-wrap" }, canvas, card, bar), canvas, card, bar, map: null, layer: null, countries: null, focus: null };
  WORLD.countries = worldCountries();
  WORLD.byCode = new Map(WORLD.countries.filter((c) => c.code).map((c) => [c.code, c]));
  return WORLD;
}

function worldColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return { visited: v("--accent"), land: v("--world-land"), line: v("--bg") };
}

function worldStyle(feature) {
  const c = worldColors();
  const visited = WORLD.byCode.has(feature.properties.c);
  const chosen = WORLD.chosen === feature.properties.c;
  return {
    fillColor: visited ? c.visited : c.land, fillOpacity: visited ? (chosen ? 1 : 0.75) : 1,
    color: chosen ? c.visited : c.line, weight: chosen ? 2.5 : 0.6,
  };
}

function showCountry(code) {
  const W = WORLD;
  W.chosen = code;
  if (W.layer) W.layer.setStyle(worldStyle);
  const c = W.byCode.get(code);
  W.card.hidden = false;
  W.card.replaceChildren(...[
    el("div", { class: "world-card-name", text: c ? c.name : countryName(code) }),
    c ? el("div", { class: "world-card-years", text: c.ranges })
      : el("div", { class: "world-card-meta", text: "Hier gibt es noch keine Bilder." }),
    c ? el("div", { class: "world-card-meta", text: `${countLabel(c.n)} · ${c.years.size === 1 ? "1 Jahr" : `${c.years.size} Jahre`}` }) : null,
    el("button", { type: "button", class: "icon-btn world-card-close", "aria-label": "Schließen", onclick: hideCountry }, svgNode(ICON_X)),
  ].filter(Boolean));
}

function hideCountry() {
  WORLD.chosen = null;
  WORLD.card.hidden = true;
  if (WORLD.layer) WORLD.layer.setStyle(worldStyle);
}

async function initWorld() {
  const W = WORLD;
  const res = await fetch(WORLD_FILE);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const shapes = await res.json();
  const map = L.map(W.canvas, {
    zoomControl: false, preferCanvas: true, minZoom: 1, maxZoom: 6, zoomSnap: 0.25,
    worldCopyJump: false, maxBounds: [[-80, -200], [88, 200]], maxBoundsViscosity: 0.8,
  });
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('Grenzen: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noopener">Natural Earth</a>');
  W.layer = L.geoJSON(shapes, {
    style: worldStyle,
    onEachFeature: (feature, layer) => layer.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      showCountry(feature.properties.c);
    }),
  }).addTo(map);
  map.on("click", hideCountry);
  W.map = map;
  W.shapes = new Map();
  W.layer.eachLayer((layer) => W.shapes.set(layer.feature.properties.c, layer));
  // Start: alle besuchten Laender im Blick
  let bounds = null;
  for (const code of W.byCode.keys()) {
    const layer = W.shapes.get(code);
    if (layer) bounds = bounds ? bounds.extend(layer.getBounds()) : L.latLngBounds(layer.getBounds().getSouthWest(), layer.getBounds().getNorthEast());
  }
  if (bounds) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 4 });
  else map.setView([30, 10], 1);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => W.layer.setStyle(worldStyle));
}

function focusCountry(code) {
  const layer = WORLD.shapes && WORLD.shapes.get(code);
  if (layer) WORLD.map.fitBounds(layer.getBounds(), { padding: [40, 40], maxZoom: 5 });
  showCountry(code);
}

function countryListView() {
  const list = worldCountries();
  const wrap = el("div", { class: "country-list" });
  for (const c of list) {
    wrap.append(el("button", {
      type: "button", class: "folder-row country-row",
      onclick: () => {
        if (!c.code) return;
        WORLD.focus = c.code;
        history.back();
      },
    }, el("div", { class: "name", text: c.name }),
    el("div", { class: "meta", text: `${c.ranges} · ${countLabel(c.n)}${c.code && !(WORLD.shapes && WORLD.shapes.has(c.code)) && WORLD.shapes ? " · nicht auf der Karte" : c.code ? "" : " · Land unbekannt"}` })));
  }
  if (!list.length) wrap.append(el("p", { class: "center muted", text: "Noch keine Bilder mit Land." }));
  return wrap;
}

/* ---------------------------------------------------------------- Weitere Ordner (v0.7.16) */

// Unter einem Ordner: davor/danach in der Zeit, dazu bis zu 4 passende Ordner
// (gleicher Anlass laut Name, gleicher Ort, dieselben Personen, gleicher Monat)
const NAME_STOPWORDS = new Set(("mit und der die das den dem des ein eine einer bei beim von vom zum zur fur auf aus nach " +
  "uber unter ohne the and with weitere bilder familie teil").split(" "));
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

function folderSummaries() {
  if (DATA.fsum) return DATA.fsum;
  const sums = new Map();
  for (const f of DATA.index.folders) {
    const list = DATA.byFolder.get(f.n) || [];
    const gps = list.filter(hasGps);
    const cities = new Map();
    const persons = new Map();
    for (const p of list) {
      if (p.ci) cities.set(p.ci, (cities.get(p.ci) || 0) + 1);
      for (const name of p.p || []) persons.set(name, (persons.get(name) || 0) + 1);
    }
    const label = folderLabel(f);
    sums.set(f.n, {
      f,
      c: list.length || 1,
      la: gps.length ? quantile(gps.map((p) => p.la), 0.5) : null,
      lo: gps.length ? quantile(gps.map((p) => p.lo), 0.5) : null,
      city: [...cities].sort((a, b) => b[1] - a[1]).map((x) => x[0])[0] || "",
      persons,
      month: f.d ? +f.d.slice(5, 7) : 0,
      words: new Set(f.x ? [] : words(label.name).filter((w) => w.length >= 3 && !/^\d+$/.test(w) && !NAME_STOPWORDS.has(w))),
    });
  }
  DATA.fsum = sums;
  return sums;
}

function folderSuggestions(f) {
  const sums = folderSummaries();
  const me = sums.get(f.n);
  const all = DATA.index.folders.slice().sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : a.n.localeCompare(b.n, "de")));
  const at = all.findIndex((x) => x.n === f.n);
  const prev = at > 0 ? all[at - 1] : null;
  const next = at >= 0 && at < all.length - 1 ? all[at + 1] : null;
  const others = [...sums.values()].filter((s) => s.f.n !== f.n && !s.f.x);
  const yearGap = (s) => Math.abs((+s.f.d.slice(0, 4) || 0) - (+f.d.slice(0, 4) || 0));
  const cap = (w) => w.charAt(0).toUpperCase() + w.slice(1);

  const byName = me.words.size ? others.map((s) => ({ s, shared: [...s.words].filter((w) => me.words.has(w)) }))
    .filter((x) => x.shared.length).sort((a, b) => b.shared.length - a.shared.length || yearGap(a.s) - yearGap(b.s))
    .map((x) => ({ f: x.s.f, why: `Gleicher Anlass: „${cap(x.shared[0])}“` })) : [];

  let byPlace = [];
  if (me.la !== null) {
    byPlace = others.filter((s) => s.la !== null).map((s) => ({ s, km: distanceKm(me.la, me.lo, s.la, s.lo) }))
      .filter((x) => x.km <= 20).sort((a, b) => a.km - b.km)
      .map((x) => ({ f: x.s.f, why: x.s.city || me.city ? `Auch in ${x.s.city || me.city}` : "Auch hier in der Nähe" }));
  } else if (me.city) {
    byPlace = others.filter((s) => s.city === me.city).sort((a, b) => yearGap(a) - yearGap(b))
      .map((s) => ({ f: s.f, why: `Auch in ${me.city}` }));
  }

  const mine = [...me.persons].filter(([, n]) => n / me.c >= 0.2).sort((a, b) => b[1] - a[1]).slice(0, 3).map((x) => x[0]);
  const byPersons = mine.length ? others.map((s) => {
    const names = mine.filter((name) => (s.persons.get(name) || 0) / s.c >= 0.15);
    return { s, names, score: names.reduce((sum, name) => sum + s.persons.get(name) / s.c, 0) };
  }).filter((x) => x.names.length).sort((a, b) => b.names.length - a.names.length || b.score - a.score)
    .map((x) => ({ f: x.s.f, why: `Auch mit ${x.names.length > 1 ? `${x.names.slice(0, -1).join(", ")} und ${x.names[x.names.length - 1]}` : x.names[0]}` })) : [];

  const bySeason = me.month ? others.filter((s) => s.month === me.month && s.f.y !== f.y)
    .sort((a, b) => seeded(f.n + a.f.n) - seeded(f.n + b.f.n))
    .map((s) => ({ f: s.f, why: `Auch im ${MONTHS[me.month - 1]}` })) : [];

  // erst je Gruppe hoechstens 2 (Reihenfolge wie oben), dann auffuellen; jeder Ordner nur einmal, hoechstens 4
  const used = new Set([f.n, prev && prev.n, next && next.n]);
  const more = [];
  const groups = [byName, byPlace, byPersons, bySeason];
  for (const limit of [2, 4]) {
    for (const group of groups) {
      let taken = more.filter((x) => x.group === group).length;
      for (const x of group) {
        if (more.length >= 4 || taken >= limit) break;
        if (used.has(x.f.n)) continue;
        used.add(x.f.n);
        more.push({ ...x, group });
        taken += 1;
      }
    }
  }
  return { prev, next, more };
}

function folderRow(f, why, cls = "") {
  const label = folderLabel(f);
  const name = f.x ? f.n : label.name;
  const meta = [why, label.date || String(f.y), countLabel(f.c)].filter(Boolean).join(" · ");
  return el("button", {
    type: "button", class: `folder-row ${cls}`.trim(), onclick: () => navigate({ v: "folder", f: f.n }),
  }, el("div", { class: "name", text: name }), el("div", { class: "meta", text: meta }));
}

function folderMoreView(f) {
  const { prev, next, more } = folderSuggestions(f);
  const rows = [];
  if (prev) rows.push(folderRow(prev, "‹ Davor"));
  if (next) rows.push(folderRow(next, "Danach ›"));
  for (const x of more) rows.push(folderRow(x.f, x.why));
  if (!rows.length) return null;
  return el("section", { class: "more" },
    el("div", { class: "more-end", text: "Ende des Ordners" }),
    el("div", { class: "more-box" }, el("h2", { class: "more-head", text: "Weitere Ordner" }), ...rows));
}

/* ---------------------------------------------------------------- Personen (v0.7.16) */

const PEOPLE_ORDER_KEY = "fotoschatz.people-order";   // "count" (Standard) oder "name"

function personsIndex() {
  if (DATA.persons) return DATA.persons;
  const map = new Map();
  for (const p of DATA.photos) {
    for (const name of p.p || []) {
      const key = normText(name);
      if (!key) continue;
      let e = map.get(key);
      if (!e) map.set(key, (e = { name, key, list: [] }));
      e.list.push(p);
    }
  }
  DATA.persons = map;
  return map;
}

function peopleView() {
  const byName = readPref(PEOPLE_ORDER_KEY) === "name";
  const now = `${localDay()}T12:00:00`;
  const people = [...personsIndex().values()].sort((a, b) => (byName ? 0 : b.list.length - a.list.length)
    || a.name.localeCompare(b.name, "de"));
  return el("div", { class: "folders people" }, ...people.map((e) => {
    const age = ageAt(birthOf(e.name), now);
    return el("button", {
      type: "button", class: "folder-row", onclick: () => navigate({ v: "person", n: e.key }),
    }, el("div", { class: "name", text: e.name }),
    el("div", { class: "meta", text: [countLabel(e.list.length), age && ageText(age)].filter(Boolean).join(" · ") }));
  }));
}

function birthLabel(birth) {
  if (!birth) return "";
  if (birth.length === 4) return `geb. ${birth}`;
  return `geb. ${fmtDay.format(parseLocal(birth))}`;
}

/* ---------------------------------------------------------------- Erinnerungen (v0.7.16) */

// Fuer alle, die die App nutzen, aus den eigenen Bildern; wechselt einmal am Tag.
const MEM_PLACE_KEY = "fotoschatz.mem-place";   // { day, key, recent: [...] } – zuletzt vorgeschlagene Orte
// Was auf diesem Geraet schon gezeigt wurde (v0.7.18, damit sich Erinnerungen nicht wiederholen):
// seen = Bild-id -> Tag (60 Tage gemerkt), stars = Bild-id -> Tag (Runde durch alle ★★/★-Bilder),
// folders = Ordnername -> Tag. Eintraege von heute zaehlen nicht, so bleibt die Auswahl am selben Tag gleich.
const MEM_SEEN_KEY = "fotoschatz.mem-seen";
const MEM_SEEN_DAYS = 60;
let MEM = null;

function daysBetween(a, b) {
  return Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10))
    - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 86400000);
}

function loadSeen(day) {
  let st = {};
  try { st = JSON.parse(readPref(MEM_SEEN_KEY) || "{}") || {}; } catch (e) { st = {}; }
  const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
  const seen = obj(st.seen);
  for (const [id, d] of Object.entries(seen)) {
    if (typeof d !== "string" || daysBetween(d, day) > MEM_SEEN_DAYS) delete seen[id];
  }
  const today = st.today && st.today.day === day ? st.today : { day, picks: {}, folders: null };
  return { seen, stars: obj(st.stars), folders: obj(st.folders), today };
}

function saveSeen(st) {
  writePref(MEM_SEEN_KEY, JSON.stringify(st));
}

function memories() {
  const day = localDay();
  if (MEM && MEM.day === day) return MEM;
  const year = +day.slice(0, 4);
  const md = day.slice(5);
  const now = `${day}T12:00:00`;
  const cards = [];
  const soon = [];
  const persons = personsIndex();
  const memo = loadSeen(day);
  const shown = (p) => memo.seen[p.id] && memo.seen[p.id] !== day;   // an einem frueheren Tag gezeigt

  // Geburtstag heute (je Person eine Karte) und in den naechsten 7 Tagen
  for (const e of persons.values()) {
    const birth = birthOf(e.name);
    if (birth.length !== 10) continue;
    const bmd = birth.slice(5);
    const age = year - +birth.slice(0, 4);
    if (bmd === md && age > 0) {
      const perYear = new Map();
      for (const p of e.list) {
        const y = p.t.slice(0, 4);
        if (!perYear.has(y)) perYear.set(y, []);
        perYear.get(y).push(p);
      }
      const strip = [...perYear.values()].map((list) => bestPhotos(list, 1, `${day}bd`)[0]);
      cards.push({
        key: `bd:${e.key}`, kind: "birthday", birth,
        title: DATA.me.has(e.key) ? `🎂 Alles Gute, ${e.name}!` : `🎂 ${e.name} wird heute ${age}`,
        sub: `${DATA.me.has(e.key) ? `${age} Jahre · ` : ""}${perYear.size === 1 ? "1 Jahr" : `${perYear.size} Jahre`} in Bildern · je Jahr ein Bild`,
        strip, open: { v: "person", n: e.key },
      });
      continue;
    }
    for (let ahead = 1; ahead <= 7; ahead++) {
      const d = new Date();
      d.setDate(d.getDate() + ahead);
      const dd = localDay(d);
      if (dd.slice(5) !== bmd) continue;
      soon.push({ e, ahead, age: +dd.slice(0, 4) - +birth.slice(0, 4), date: d });
    }
  }
  soon.sort((a, b) => a.ahead - b.ahead);

  // Heute vor X Jahren (sonst ±1, erst dann ±3 Tage)
  const past = DATA.photos.filter((p) => +p.t.slice(0, 4) < year);
  let today = past.filter((p) => p.t.slice(5, 10) === md);
  let exact = true;
  for (const width of [1, 3]) {
    if (today.length) break;
    today = past.filter((p) => dayDistance(p.t.slice(5, 10), md) <= width);
    exact = false;
  }
  if (today.length) {
    const years = [...new Set(today.map((p) => +p.t.slice(0, 4)))];
    const per = new Map();
    for (const p of today) per.set(p.t.slice(0, 4), (per.get(p.t.slice(0, 4)) || 0) + 1);
    const ago = (y) => (year - y === 1 ? "vor 1 Jahr" : `vor ${year - y} Jahren`);
    cards.push({
      key: "today", kind: "today",
      title: !exact ? "Um diesen Tag in früheren Jahren" : years.length === 1 ? `Heute ${ago(years[0])}`
        : years.length <= 3 ? `Heute vor ${years.map((y) => year - y).sort((x, y) => x - y).join(", ").replace(/, (\d+)$/, " und $1")} Jahren`
          : "Heute in früheren Jahren",
      sub: `${yearRanges(years)} · ${countLabel(today.length)}`,
      all: today, strip: bestPhotos(today, 12, `${day}today`, shown),
      sectionOf: (p) => `${p.t.slice(0, 4)} · ${ago(+p.t.slice(0, 4))} · ${countLabel(per.get(p.t.slice(0, 4)))}`,
    });
  }

  // Persoenlicher Link (v0.7.20): Bilder mit der Person aus dieser Woche (±3 Tage) in frueheren Jahren,
  // ohne die, die schon in „Heute vor X Jahren“ stehen
  if (DATA.me.size) {
    const inToday = new Set((cards.find((c) => c.key === "today") || { strip: [] }).strip.map((p) => p.id));
    const mine = past.filter((p) => isMine(p) && !inToday.has(p.id) && dayDistance(p.t.slice(5, 10), md) <= 3);
    if (mine.length) {
      const years = [...new Set(mine.map((p) => +p.t.slice(0, 4)))];
      const per = new Map();
      for (const p of mine) per.set(p.t.slice(0, 4), (per.get(p.t.slice(0, 4)) || 0) + 1);
      const ago = (y) => (year - y === 1 ? "vor 1 Jahr" : `vor ${year - y} Jahren`);
      cards.push({
        key: "me", kind: "me", title: DATA.me.size > 1 ? "Mit euch – diese Woche in früheren Jahren" : "Mit dir – diese Woche in früheren Jahren",
        sub: `${yearRanges(years)} · ${countLabel(mine.length)}`,
        all: mine, strip: bestPhotos(mine, 12, `${day}me`, shown),
        sectionOf: (p) => `${p.t.slice(0, 4)} · ${ago(+p.t.slice(0, 4))} · ${countLabel(per.get(p.t.slice(0, 4)))}`,
      });
    }
  }

  // Vor X Jahren: Ordner von genau heute; ein Ordner von vor 1–3 Tagen nur, wenn er an seinem Tag
  // nicht gezeigt wurde (App nicht geoeffnet) – so steht jeder Ordner hoechstens an 1–2 Tagen da (v0.7.18)
  const folderSeen = (f) => {
    const d = memo.folders[f.n];
    return d && d !== day && daysBetween(d, day) <= 7;
  };
  const folders = DATA.index.folders.filter((f) => !f.x && f.d && +f.d.slice(0, 4) < year)
    .map((f) => ({ f, off: dayOffset(f.d.slice(5), md), stars: (DATA.byFolder.get(f.n) || []).filter((p) => p.r).length,
      mine: (DATA.byFolder.get(f.n) || []).some(isMine) ? 1 : 0 }))
    .filter((x) => x.off === 0 || (x.off < 0 && x.off >= -3 && !folderSeen(x.f)))
    .sort((a, b) => b.off - a.off || b.mine - a.mine || b.stars - a.stars || seeded(day + a.f.n) - seeded(day + b.f.n))
    .slice(0, 3).map((x) => x.f);

  // Wiederentdecken: 12 Bilder des Tages – der Reihe nach alle ★★, dann alle ★, dann von vorn (v0.7.18)
  const starPool = DATA.photos.filter((p) => (p.r || 0) >= 1);
  if (starPool.length >= 4) {
    const used = (p) => memo.stars[p.id] && memo.stars[p.id] !== day;
    const shuffle = (list) => list.map((p) => [seeded(`${day}stars${p.id}`), p]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    const take = () => {
      const out = [];
      const tiers = DATA.me.size ? [[2, true, 8], [1, true, 8], [2, false, 12], [1, false, 12]] : [[2, null, 12], [1, null, 12]];
      for (const [tier, mine, upto] of tiers) {
        const rest = shuffle(starPool.filter((p) => ((p.r || 0) >= 2 ? 2 : 1) === tier && !used(p)
          && !out.includes(p) && (mine === null || isMine(p) === mine)));
        out.push(...rest.slice(0, Math.max(0, upto - out.length)));
        if (out.length >= 12) break;
      }
      return out;
    };
    let pick = take();
    if (pick.length < Math.min(12, starPool.length)) {   // Runde fertig: von vorn, nur heutige bleiben gemerkt
      for (const [id, d] of Object.entries(memo.stars)) if (d !== day) delete memo.stars[id];
      pick = take();
    }
    pick = mineFirst(pick);
    const two = pick.filter((p) => (p.r || 0) >= 2).length;
    cards.push({
      key: "stars", kind: "stars", title: "Wiederentdecken",
      sub: `${pick.length} Bilder mit ${two === pick.length ? "★★" : two ? "★★ und ★" : "★"} – jeden Tag andere`,
      all: pick, strip: pick,
    });
    for (const p of pick) memo.stars[p.id] = day;
  }

  // Ort wiederentdecken: eine Stadt mit mindestens 10 Bildern, nicht der Wohnort, laenger nicht vorgeschlagen
  const cities = new Map();
  for (const p of DATA.photos) {
    if (!p.ci) continue;
    const key = `${normText(p.co || "")}|${normText(p.ci)}`;
    let c = cities.get(key);
    if (!c) cities.set(key, (c = { key, name: p.ci, country: p.co || "", list: [], stars: 0 }));
    c.list.push(p);
    if (p.r) c.stars += 1;
    if (isMine(p)) c.mine = (c.mine || 0) + 1;
  }
  const ranked = [...cities.values()].sort((a, b) => b.list.length - a.list.length);
  const home = ranked[0];
  const candidates = ranked.filter((c) => c !== home && c.list.length >= 10);
  let place = null;
  if (candidates.length) {
    let saved = {};
    try { saved = JSON.parse(readPref(MEM_PLACE_KEY) || "{}") || {}; } catch (e) { saved = {}; }
    place = saved.day === day ? candidates.find((c) => c.key === saved.key) : null;
    if (!place) {
      const recent = new Set(Array.isArray(saved.recent) ? saved.recent : []);
      const fresh = candidates.filter((c) => !recent.has(c.key));
      const from = fresh.length ? fresh : candidates;
      // gewichtet: mehr Bilder und mehr Sterne = oefter an der Reihe
      const weight = (c) => Math.sqrt(c.list.length) * (1 + c.stars / c.list.length) * (1 + 2 * (c.mine || 0) / c.list.length);
      const total = from.reduce((sum, c) => sum + weight(c), 0);
      let r = seeded(`${day}place`) * total;
      place = from.find((c) => (r -= weight(c)) <= 0) || from[from.length - 1];
      const keep = [place.key, ...(Array.isArray(saved.recent) ? saved.recent : []).filter((k) => k !== place.key)]
        .slice(0, Math.max(1, Math.min(30, Math.floor(candidates.length / 2))));
      writePref(MEM_PLACE_KEY, JSON.stringify({ day, key: place.key, recent: keep }));
    }
  }
  if (place) {
    const years = [...new Set(place.list.map((p) => +p.t.slice(0, 4)))];
    cards.push({
      key: "place", kind: "place", title: `Ort wiederentdecken: ${place.name}`,
      sub: [place.country !== place.name ? place.country : "", yearRanges(years), countLabel(place.list.length)].filter(Boolean).join(" · "),
      all: place.list, strip: bestPhotos(place.list, 12, `${day}place`, shown),
    });
  }

  // Am selben Tag (App neu geoeffnet) genau dieselbe Auswahl wie beim ersten Oeffnen
  const byId = new Map(DATA.photos.map((p) => [p.id, p]));
  const again = (ids) => (Array.isArray(ids) && ids.length && ids.every((id) => byId.has(id)) ? ids.map((id) => byId.get(id)) : null);
  for (const card of cards) {
    const kept = again(memo.today.picks[card.key]);
    if (kept) {
      card.strip = kept;
      if (card.kind === "stars") card.all = kept;
    }
    memo.today.picks[card.key] = card.strip.map((p) => p.id);
  }
  const folderByName = DATA.folderByName;
  if (Array.isArray(memo.today.folders) && memo.today.folders.every((n) => folderByName.has(n))) {
    folders.splice(0, folders.length, ...memo.today.folders.map((n) => folderByName.get(n)));
  }
  memo.today.folders = folders.map((f) => f.n);

  // Gezeigtes merken (Streifen und Ordner), damit es die naechsten Tage nicht wiederkommt
  for (const card of cards) {
    if (card.kind === "birthday") continue;
    for (const p of card.strip) memo.seen[p.id] = day;
  }
  for (const f of folders) memo.folders[f.n] = day;
  for (const [n, d] of Object.entries(memo.folders)) if (daysBetween(d, day) > 30) delete memo.folders[n];
  saveSeen(memo);

  // Reihenfolge: Geburtstage, heute, (Ordner), Wiederentdecken, Ort
  MEM = { day, cards, soon, folders, now };
  return MEM;
}

function memStrip(card) {
  return el("div", { class: "mem-strip" }, ...card.strip.map((p, i) => el("button", {
    type: "button", class: "mem-thumb", "aria-label": fmtFull.format(parseLocal(p.t)),
    onclick: () => navigate({ v: "memories", c: card.key, viewer: { i } }),
  }, el("img", { src: thumbUrl(p), alt: "", loading: "lazy", decoding: "async", style: focusStyle(p) }))));
}

function memCard(card) {
  const open = card.open || { v: "memory", k: card.key };
  return el("section", { class: `mem-card mem-${card.kind}` },
    el("button", { type: "button", class: "mem-head", onclick: () => navigate(open) },
      el("span", { class: "mem-titles" }, el("span", { class: "mem-title", text: card.title }), el("span", { class: "mem-sub", text: card.sub })),
      svgNode(ICON_CHEVRON)),
    memStrip(card));
}

function memoriesView() {
  const M = memories();
  const wrap = el("div", { class: "memories" });
  const year = +M.day.slice(0, 4);
  for (const card of M.cards.filter((c) => c.kind === "birthday")) wrap.append(memCard(card));
  if (M.soon.length) {
    const fmtSoon = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "numeric", month: "long" });
    wrap.append(el("section", { class: "mem-card mem-soon" },
      el("div", { class: "mem-label", text: "🎂 Demnächst" }),
      ...M.soon.map((x) => el("button", {
        type: "button", class: "folder-row", onclick: () => navigate({ v: "person", n: x.e.key }),
      }, el("div", { class: "name", text: `${x.e.name} wird ${x.age}` }),
      el("div", { class: "meta", text: `${x.ahead === 1 ? "morgen" : `in ${x.ahead} Tagen`} · ${fmtSoon.format(x.date)}` })))));
  }
  for (const card of M.cards.filter((c) => c.kind === "today" || c.kind === "me")) wrap.append(memCard(card));
  if (M.folders.length) {
    wrap.append(el("section", { class: "mem-card mem-folders" },
      el("div", { class: "mem-label", text: "Diese Woche vor einigen Jahren" }),
      ...M.folders.map((f) => {
        const ago = year - +f.d.slice(0, 4);
        const label = folderLabel(f);
        const thumbs = bestPhotos(DATA.byFolder.get(f.n) || [], 4, `${M.day}${f.n}`);
        return el("button", { type: "button", class: "mem-folder", onclick: () => navigate({ v: "folder", f: f.n }) },
          el("span", { class: "mem-titles" },
            el("span", { class: "mem-title", text: `Vor ${ago === 1 ? "1 Jahr" : `${ago} Jahren`}: ${label.name}` }),
            el("span", { class: "mem-sub", text: `${label.date || f.y} · ${countLabel(f.c)}` })),
          el("span", { class: "mem-mini" }, ...thumbs.map((p) => el("img", {
            src: thumbUrl(p), alt: "", loading: "lazy", decoding: "async", style: focusStyle(p),
          }))));
      })));
  }
  for (const card of M.cards.filter((c) => c.kind === "stars" || c.kind === "place")) wrap.append(memCard(card));
  if (!wrap.childNodes.length) wrap.append(el("p", { class: "center muted", text: "Heute gibt es keine Erinnerungen." }));
  return wrap;
}

const memoryCard = (key) => memories().cards.find((c) => c.key === key) || null;

/* ---------------------------------------------------------------- Bild teilen (v0.7.16) */

// Teilt das Bild selbst (z. B. an WhatsApp), nicht einen Link. Vorher wird es neu gespeichert,
// damit GPS und Personennamen nicht mitgehen. Ohne Teilen-Funktion (z. B. PC, Firefox) wird es heruntergeladen.
let sharedFile = null;     // { key, file } – zuletzt vorbereitetes Bild

async function cleanImageFile(p) {
  const res = await fetch(imageUrl(p), { mode: "cors" });
  if (!res.ok) throw new Error(String(res.status));
  const url = URL.createObjectURL(await res.blob());
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.getContext("2d").drawImage(img, 0, 0);
    const blob = await new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Bild"))), "image/jpeg", 0.92));
    const name = `Fotoschatz ${p.t.slice(0, 10)} ${p.t.slice(11, 19).replace(/:/g, "-")}.jpg`;
    return new File([blob], name, { type: "image/jpeg", lastModified: parseLocal(p.t).getTime() });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function downloadFile(file, msg = "Bild gespeichert (Downloads)") {
  const url = URL.createObjectURL(file);
  const a = el("a", { href: url, download: file.name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  toast(msg);
}

async function shareImage(p) {
  if (!p) return;
  const key = `${p.id}.${p.h}`;
  let file = sharedFile && sharedFile.key === key ? sharedFile.file : null;
  try {
    if (!file) {
      toast("Bild wird vorbereitet …");
      file = await cleanImageFile(p);
      sharedFile = { key, file };
    }
  } catch (e) {
    toast("Bild konnte nicht geladen werden – Verbindung prüfen.");
    return;
  }
  if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
    } catch (e) {
      // Dauerte das Vorbereiten zu lange, verlangt der Browser ein neues Antippen
      if (e && e.name === "NotAllowedError") toast("Bild ist bereit – bitte noch einmal auf Teilen tippen");
    }
    return;
  }
  downloadFile(file);
}

/* ---------------------------------------------------------------- Videos (v0.8.0) */

// Videos liegen im selben Bucket: <Praefix>/videos/<ID>/{video.mp4, preview.mp4, poster.webp}. Das Verzeichnis
// <Praefix>/videos/index-<Schluessel>.json erzeugt ein separates Projekt (Videoschatz) je Link-Schluessel – wer keine
// Datei hat (Ordner-Freigaben, Gaeste vor der Freigabe), sieht den Tab nicht. Die App filtert nichts selbst.
let VIDEOS = null;      // { list (aelteste zuerst), byId, years }

const videoUrl = (v, name) => `${BASE}/videos/${v.id}/${name}`;

function fmtDuration(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}

const videoCount = (n) => (n === 1 ? "1 Video" : `${n.toLocaleString("de-DE")} Videos`);

function cleanVideos(data) {
  const raw = data && Array.isArray(data.videos) ? data.videos : [];
  const list = [];
  for (const v of raw) {
    if (!v || typeof v.id !== "string" || !/^[A-Za-z0-9]{8,64}$/.test(v.id)) continue;
    const datum = /^\d{4}-\d{2}-\d{2}$/.test(v.datum || "") ? v.datum : "1900-01-01";
    const zeit = /^\d{2}:\d{2}$/.test(v.zeit || "") ? v.zeit : "00:00";
    const kw = Array.isArray(v.stichwoerter) ? v.stichwoerter.map(String) : [];
    const persons = Array.isArray(v.personen) ? v.personen.map(String).filter(Boolean) : [];
    const ort = v.ort ? String(v.ort) : "";
    const ereignis = v.ereignis ? String(v.ereignis) : "";
    list.push({
      id: v.id,
      titel: String(v.titel || "Ohne Titel"),
      t: `${datum}T${zeit}`,
      dauer: Number(v.dauer) || 0,
      breite: Number(v.breite) || 0,
      hoehe: Number(v.hoehe) || 0,
      ort,
      ereignis,
      personen: persons,
      sterne: Number(v.sterne) === 2 ? 2 : Number(v.sterne) === 1 ? 1 : 0,     // nur in deinem Verzeichnis (v0.8.5)
      // Die Beschreibung wird nicht angezeigt, zaehlt aber fuer die Suche (v0.8.1)
      _s: normText([v.titel, v.beschreibung, kw.join(" "), persons.join(" "), ort, ereignis, datum].filter(Boolean).join(" ")),
      _p: new Set(persons.map(normText)),
    });
  }
  list.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  return { list, byId: new Map(list.map((v) => [v.id, v])) };
}

// Nach dem Start im Hintergrund: eigener Link zuerst, sonst der erste Link mit Videoverzeichnis
async function loadVideos(loaded, own) {
  for (const r of own ? [own] : loaded) {
    const key = r.link.split("-")[1];
    if (!key) continue;
    try {
      const res = await fetch(`${BASE}/videos/index-${key}.json`, { cache: "no-cache" });
      if (!res.ok) continue;
      const found = cleanVideos(await res.json());
      if (found.list.length) {
        VIDEOS = found;
        break;
      }
    } catch (e) { /* kein Verzeichnis: kein Tab */ }
  }
  if (OWNER) { VEdit.load(); VEdit.prune(); }
  const btn = $('#nav button[data-view="videos"]');
  if (btn) btn.hidden = !(VIDEOS || OWNER);
}

const VFILTER = { q: "", y: "", p: "", e: "", s: "", open: false };

/* ---- Eigene Aenderungen (v0.8.5, nur mit deinem Link): Sterne und Loeschwuensche liegen auf dem Handy; die App darf im
   Bucket nichts aendern. „Aenderungen“ erzeugt eine Datei, die der PC (Videoschatz, aenderungen.bat) verarbeitet. ---- */
const VEDIT_KEY = "fotoschatz.video-edits";
const VEdit = {
  stars: {},          // id -> 0|1|2, nur Abweichungen vom Verzeichnis
  del: {},            // id -> Titel (zum Loeschen vorgemerkt)
  load() {
    try {
      const d = JSON.parse(readPref(VEDIT_KEY) || "{}");
      this.stars = d && d.stars && typeof d.stars === "object" ? d.stars : {};
      this.del = d && d.del && typeof d.del === "object" ? d.del : {};
    } catch (e) { this.stars = {}; this.del = {}; }
    // Browser bitten, die Daten dauerhaft zu behalten (sonst koennten sie bei Platzmangel verloren gehen)
    try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {}); } catch (e) { /* egal */ }
  },
  save() { writePref(VEDIT_KEY, JSON.stringify({ stars: this.stars, del: this.del })); },
  level(v) { return Object.prototype.hasOwnProperty.call(this.stars, v.id) ? this.stars[v.id] : v.sterne; },
  setStar(v, n) {
    if (n === v.sterne) delete this.stars[v.id]; else this.stars[v.id] = n;
    this.save();
  },
  markDelete(v) { this.del[v.id] = v.titel; this.save(); },
  undoDelete(id) { delete this.del[id]; this.save(); },
  // Was der PC schon uebernommen hat, faellt weg: Sterne gleich dem Verzeichnis, geloeschte Videos nicht mehr im Verzeichnis
  prune() {
    if (!VIDEOS) return;
    for (const id of Object.keys(this.del)) if (!VIDEOS.byId.has(id)) delete this.del[id];
    for (const id of Object.keys(this.stars)) {
      const v = VIDEOS.byId.get(id);
      if (!v || this.stars[id] === v.sterne) delete this.stars[id];
    }
    this.save();
  },
  starChanges() {
    if (!VIDEOS) return [];
    return Object.entries(this.stars).filter(([id]) => VIDEOS.byId.has(id) && !this.del[id]);
  },
  count() { return Object.keys(this.del).filter((id) => VIDEOS && VIDEOS.byId.has(id)).length + this.starChanges().length; },
};

const VView = { refresh: null };       // zeichnet die Videoliste neu (gesetzt von videosView)

function closeSheet() {
  const n = $("#vsheet");
  if (!n) return;
  n.remove();
  if (mounted && mounted.grid && mounted.grid.autoplay) mounted.grid.render();       // Vorschau oben geht weiter
}

function openSheet(build) {
  closeSheet();
  stopPreview();
  VAuto.sync([]);
  const sheet = el("div", { class: "vsheet" });
  const back = el("div", { id: "vsheet", class: "vsheet-back" }, sheet);
  back.addEventListener("click", (e) => { if (e.target === back) closeSheet(); });
  back.addEventListener("contextmenu", (e) => e.preventDefault());
  build(sheet, closeSheet);
  document.body.append(back);
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

// Langes Druecken auf ein Video (nur du): Sterne vergeben oder zum Loeschen vormerken
function videoMenu(v) {
  openSheet((sheet, close) => {
    const lvl = VEdit.level(v);
    const done = (msg) => { close(); if (msg) toast(msg); if (VView.refresh) VView.refresh(); };
    const star = (n, label) => el("button", {
      type: "button", class: `vs-btn${lvl === n ? " on" : ""}`, text: label,
      onclick: () => { VEdit.setStar(v, lvl === n ? 0 : n); done(); },
    });
    sheet.append(el("div", { class: "vs-title", text: v.titel }), star(1, "★ gut"), star(2, "★★ sehr gut"));
    if (lvl) sheet.append(el("button", { type: "button", class: "vs-btn", text: "Stern entfernen",
      onclick: () => { VEdit.setStar(v, 0); done(); } }));
    sheet.append(
      el("button", { type: "button", class: "vs-btn danger", text: "Video löschen",
        onclick: () => { VEdit.markDelete(v); done("Zum Löschen vorgemerkt – unter „Änderungen“ zurücknehmen"); } }),
      el("button", { type: "button", class: "vs-btn", text: "Abbrechen", onclick: close }));
  });
}

function editsFile() {
  const ok = (id) => /^[0-9a-f]{16}$/.test(id);
  const loeschen = Object.entries(VEdit.del)
    .filter(([id]) => ok(id) && VIDEOS.byId.has(id)).map(([id, titel]) => ({ id, titel: String(titel) }));
  const sterne = {};
  for (const [id, n] of VEdit.starChanges()) if (ok(id)) sterne[id] = n;
  const d = new Date();
  const p2 = (n) => String(n).padStart(2, "0");
  const name = `videoschatz-aenderungen-${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}-${p2(d.getHours())}${p2(d.getMinutes())}.json`;
  const doc = { version: 1, erstellt: d.toISOString().replace(/\.\d{3}Z$/, "Z"), loeschen, sterne };
  return { name, text: JSON.stringify(doc, null, 2) };
}

async function shareEdits() {
  const { name, text } = editsFile();
  // Android erlaubt nicht jede Dateiart im Teilen-Menue: erst JSON, sonst als Text mit demselben Namen, sonst Download
  for (const type of ["application/json", "text/plain"]) {
    const file = new File([text], name, { type });
    if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file] });
      } catch (e) { /* abgebrochen */ }
      return;
    }
  }
  downloadFile(new File([text], name, { type: "application/json" }), "Datei gespeichert (Downloads)");
}

function editsSheet() {
  openSheet((sheet, close) => {
    const dels = Object.entries(VEdit.del).filter(([id]) => VIDEOS.byId.has(id));
    const stars = VEdit.starChanges();
    sheet.append(
      el("div", { class: "vs-title", text: "Änderungen für den PC" }),
      el("p", { class: "vs-note", text: `${dels.length} zum Löschen vorgemerkt · ${stars.length} Sterne geändert` }));
    for (const [id, titel] of dels) {
      sheet.append(el("div", { class: "vs-row" },
        el("span", { class: "vs-name", text: titel }),
        el("button", { type: "button", class: "vs-small", text: "zurücknehmen",
          onclick: () => { VEdit.undoDelete(id); close(); if (VView.refresh) VView.refresh(); } })));
    }
    sheet.append(
      el("button", { type: "button", class: "vs-btn on", text: "Datei erzeugen und teilen", onclick: shareEdits }),
      el("p", { class: "vs-note", text: "Am PC: aenderungen.bat in D:\\Coding\\videoschatz. Vorgemerktes bleibt hier, bis der PC es verarbeitet hat und die App neu geladen wurde." }),
      el("button", { type: "button", class: "vs-btn", text: "Schließen", onclick: close }));
  });
}

// Vorschau in der obersten sichtbaren Zeile laeuft von selbst (lautlos, Schleife)
const VAuto = {
  nodes: new Map(),        // Vorschaubild-Element -> <video>
  sync(thumbs) {
    for (const [thumb, node] of this.nodes) {
      if (thumbs.includes(thumb) && thumb.isConnected) continue;
      node.pause();
      node.removeAttribute("src");
      node.load();
      node.remove();
      this.nodes.delete(thumb);
    }
    for (const thumb of thumbs) {
      if (this.nodes.has(thumb) || !thumb._v) continue;
      stopPreview();
      const node = el("video", { loop: true, playsinline: true, class: "vprev" });
      node.muted = true;
      node.src = videoUrl(thumb._v, "preview.mp4");
      thumb.append(node);
      this.nodes.set(thumb, node);
      const p = node.play();
      if (p && p.catch) p.catch(() => {});
    }
  },
};

document.addEventListener("visibilitychange", () => {
  if (mounted && mounted.grid && mounted.grid.autoplay) mounted.grid.autoplay();
});

// Vorschau in der Kachel: lange druecken (Handy) bzw. kurz darueber verweilen (PC), lautlos, immer nur eine
const VPrev = { node: null, timer: 0, suppress: false };

function stopPreview() {
  clearTimeout(VPrev.timer);
  const node = VPrev.node;
  VPrev.node = null;
  if (!node) return;
  node.pause();
  node.removeAttribute("src");
  node.load();
  node.remove();
}

function startPreview(thumb, v) {
  stopPreview();
  if (VAuto.nodes.has(thumb)) return;
  const node = el("video", { loop: true, playsinline: true, class: "vprev" });
  node.muted = true;
  node.src = videoUrl(v, "preview.mp4");
  thumb.append(node);
  VPrev.node = node;
  const p = node.play();
  if (p && p.catch) p.catch(() => {});
}

class VideoGrid extends Grid {
  layout() {
    this.width = this.root.clientWidth || window.innerWidth;
    this.cols = this.width < 600 ? 2 : Math.max(3, Math.round(this.width / 260));
    const gap = 8;
    this.tile = (this.width - 16 - gap * (this.cols - 1)) / this.cols;     // Kachelbreite
    const rowH = Math.round(this.tile * 9 / 16) + 62 + gap;
    this.rows = [];
    let y = 0;
    let section = null;
    let current = [];
    const flush = () => {
      if (!current.length) return;
      this.rows.push({ type: "r", items: current, top: y, h: rowH, section });
      y += rowH;
      current = [];
    };
    this.list.forEach((v, i) => {
      const s = this.sectionOf ? this.sectionOf(v) : null;
      if (this.sectionOf && s !== section) {
        flush();
        section = s;
        this.rows.push({ type: "h", label: s, top: y, h: HEADER_H, section: s });
        y += HEADER_H;
      }
      current.push(i);
      if (current.length === this.cols) flush();
    });
    flush();
    this.root.style.height = `${y}px`;
    for (const node of this.mounted.values()) node.remove();
    this.mounted.clear();
    this.render();
  }

  render() {
    super.render();
    if (VPrev.node && !VPrev.node.isConnected) stopPreview();     // Kachel ist weggescrollt
    clearTimeout(this.autoTimer);
    this.autoTimer = setTimeout(() => this.autoplay(), 250);      // erst wenn das Scrollen kurz ruht
  }

  // v0.8.5: die Kacheln der obersten sichtbaren Zeile spielen ihre Vorschau von selbst
  autoplay() {
    if (!this.rows || !this.root.isConnected || document.hidden || $("#vsheet") || document.body.classList.contains("vp-open")) {
      VAuto.sync([]);
      return;
    }
    const bar = $(".search-bar");
    const edge = window.scrollY - this.originY() + $("#top").offsetHeight + (bar ? bar.offsetHeight : 0) + 30;
    let r = 0;
    while (r < this.rows.length && (this.rows[r].type !== "r" || this.rows[r].top + this.rows[r].h <= edge)) r++;
    const node = this.mounted.get(r);
    VAuto.sync(node ? [...node.querySelectorAll(".vthumb")] : []);
  }

  destroy() {
    clearTimeout(this.autoTimer);
    stopPreview();
    VAuto.sync([]);
    super.destroy();
  }

  renderRow(row) {
    if (row.type === "h") {
      return el("div", { class: "grid-head", style: `top:${row.top}px;height:${row.h}px` }, row.label);
    }
    const node = el("div", {
      class: "grid-row vid-row",
      style: `top:${row.top}px;height:${row.h}px;grid-template-columns:repeat(${this.cols},1fr)`,
    });
    for (const i of row.items) node.append(this.tileFor(this.list[i]));
    return node;
  }

  tileFor(v) {
    const day = fmtDay.format(parseLocal(v.t));
    const thumb = el("span", { class: "vthumb" },
      el("img", { src: videoUrl(v, "poster.webp"), alt: "", loading: "lazy", decoding: "async", draggable: "false" }),
      el("span", { class: "vdur", text: fmtDuration(v.dauer) }));
    thumb._v = v;
    if (OWNER) {
      const lvl = VEdit.level(v);
      if (lvl) thumb.append(el("span", { class: "vstar", text: lvl === 2 ? "★★" : "★" }));
    }
    const tile = el("button", { type: "button", class: "vtile", "aria-label": `${v.titel}, ${fmtDuration(v.dauer)}` },
      thumb,
      el("span", { class: "vtitle", text: v.titel }),
      el("span", { class: "vmeta", text: v.ort ? `${day} · ${v.ort}` : day }));
    let start = null;
    tile.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      start = { x: e.clientX, y: e.clientY };
      VPrev.suppress = false;
      clearTimeout(VPrev.timer);
      VPrev.timer = setTimeout(() => {
        VPrev.suppress = true;           // der Klick nach dem Loslassen soll das Video nicht oeffnen
        if (OWNER && e.pointerType !== "mouse") videoMenu(v);      // bei dir: Menue statt Vorschau
        else startPreview(thumb, v);
      }, 450);
    });
    tile.addEventListener("pointermove", (e) => {
      if (start && !VPrev.node && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) clearTimeout(VPrev.timer);
    });
    const end = () => { start = null; clearTimeout(VPrev.timer); stopPreview(); };
    tile.addEventListener("pointerup", end);
    tile.addEventListener("pointercancel", end);
    tile.addEventListener("pointerenter", (e) => {          // PC: kurz darueber verweilen
      if (e.pointerType !== "mouse") return;
      clearTimeout(VPrev.timer);
      VPrev.timer = setTimeout(() => startPreview(thumb, v), 450);
    });
    tile.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") end(); });
    tile.addEventListener("contextmenu", (e) => {          // kein Android-Menue beim langen Druecken
      e.preventDefault();
      if (!OWNER) return;
      clearTimeout(VPrev.timer);
      if (start) VPrev.suppress = true;
      if (!$("#vsheet")) videoMenu(v);                     // PC: Rechtsklick
    });
    tile.addEventListener("click", (e) => {
      if (VPrev.suppress) {
        VPrev.suppress = false;
        e.preventDefault();
        return;
      }
      stopPreview();
      navigate({ v: "videos", vid: v.id });          // kurz tippen: ganzes Video sofort
    });
    return tile;
  }
}

function videosView(main, m) {
  const asc = readPref(VORDER_KEY) === "asc";
  setHeader("Videos", "");
  showOrderButton(m, asc, () => writePref(VORDER_KEY, asc ? "desc" : "asc"));
  if (!VIDEOS || !VIDEOS.list.length) {
    main.append(el("p", { class: "center muted", text: "Noch keine Videos online. Sobald welche hochgeladen sind, erscheinen sie hier." }));
    return;
  }
  const count = (get) => {
    const map = new Map();
    for (const v of VIDEOS.list) for (const k of get(v)) map.set(k, (map.get(k) || 0) + 1);
    return map;
  };
  const people = count((v) => v.personen);
  const events = count((v) => (v.ereignis ? [v.ereignis] : []));
  const years = count((v) => [v.t.slice(0, 4)]);
  const byCount = (map) => [...map.keys()].sort((a, b) => map.get(b) - map.get(a) || a.localeCompare(b, "de"));
  const mkSelect = (label, map, keys, key) => {
    const sel = el("select", { class: "vid-sel", "aria-label": label },
      el("option", { value: "", text: label }),
      ...keys.map((k) => el("option", { value: k, text: `${k} (${map.get(k)})` })));
    sel.value = map.has(VFILTER[key]) ? VFILTER[key] : "";
    VFILTER[key] = sel.value;
    sel.addEventListener("change", () => { VFILTER[key] = sel.value; changed(); });
    return sel;
  };
  const input = el("input", { type: "search", placeholder: "Person, Ort, Ereignis, Jahr …",
    value: VFILTER.q, autocomplete: "off", enterkeyhint: "search", "aria-label": "Videos durchsuchen" });
  const filterBtn = el("button", { type: "button", class: "vid-filter-btn", "aria-expanded": "false" });
  const panel = el("div", { class: "vid-panel", hidden: !VFILTER.open },
    mkSelect("Alle Personen", people, byCount(people), "p"),
    mkSelect("Alle Ereignisse", events, byCount(events), "e"),
    mkSelect("Alle Jahre", years, [...years.keys()].sort().reverse(), "y"));
  if (OWNER) {
    const sel = el("select", { class: "vid-sel", "aria-label": "Sterne" },
      el("option", { value: "", text: "Alle Sterne" }),
      el("option", { value: "1", text: "★ und ★★" }),
      el("option", { value: "2", text: "Nur ★★" }));
    sel.value = VFILTER.s;
    sel.addEventListener("change", () => { VFILTER.s = sel.value; changed(); });
    panel.append(sel);
  }
  const editBtn = el("button", { type: "button", class: "vid-filter-btn on vid-edit-btn", hidden: true, onclick: editsSheet });
  const bar = el("div", { class: "search-bar vid-bar" },
    el("div", { class: "vid-bar-row" }, el("div", { class: "search-field" }, input), filterBtn), panel,
    OWNER ? el("div", { class: "vid-edit-row" }, editBtn) : "");
  const host = el("div", { class: "vid-host" });
  main.append(bar, host);

  const updateFilterBtn = () => {
    const n = ["p", "e", "y", ...(OWNER ? ["s"] : [])].filter((k) => VFILTER[k]).length;
    const pend = OWNER ? VEdit.count() : 0;
    editBtn.hidden = !pend;
    editBtn.textContent = `Änderungen (${pend})`;
    filterBtn.textContent = n ? `Filter (${n})` : "Filter";
    filterBtn.classList.toggle("on", n > 0);
    filterBtn.setAttribute("aria-expanded", String(VFILTER.open));
    panel.hidden = !VFILTER.open;
  };
  filterBtn.addEventListener("click", () => { VFILTER.open = !VFILTER.open; updateFilterBtn(); });

  const apply = () => {
    if (m.grid) { m.grid.destroy(); m.grid = null; }
    host.replaceChildren();
    const ws = normText(VFILTER.q).split(" ").filter(Boolean);
    const pn = VFILTER.p ? normText(VFILTER.p) : "";
    const sv = OWNER && VFILTER.s ? Number(VFILTER.s) : 0;
    const all = OWNER ? VIDEOS.list.filter((v) => !VEdit.del[v.id]) : VIDEOS.list;      // zum Loeschen vorgemerkte sind weg
    let list = all.filter((v) => (!VFILTER.y || v.t.startsWith(VFILTER.y))
      && (!VFILTER.e || v.ereignis === VFILTER.e) && (!pn || v._p.has(pn)) && (!sv || VEdit.level(v) >= sv)
      && ws.every((w) => v._s.includes(w)));
    if (!asc) list = list.slice().reverse();
    const sub = list.length === all.length ? videoCount(list.length)
      : `${videoCount(list.length)} · von ${all.length.toLocaleString("de-DE")}`;
    $("#subtitle").textContent = sub;
    if (!list.length) {
      host.append(el("p", { class: "center muted", text: "Keine Videos gefunden." }));
      return;
    }
    const perYear = new Map();
    for (const v of list) perYear.set(v.t.slice(0, 4), (perYear.get(v.t.slice(0, 4)) || 0) + 1);
    m.grid = new VideoGrid(host, list, (v) => `${v.t.slice(0, 4)} · ${videoCount(perYear.get(v.t.slice(0, 4)))}`,
      (section) => { $("#subtitle").textContent = section || sub; });
  };
  const changed = () => { updateFilterBtn(); window.scrollTo(0, 0); apply(); };
  let timer = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { VFILTER.q = input.value; window.scrollTo(0, 0); apply(); }, 150);
  });
  VView.refresh = () => { if (host.isConnected) { updateFilterBtn(); apply(); } };
  updateFilterBtn();
  apply();
}

const isPhone = () => window.matchMedia("(hover: none) and (pointer: coarse)").matches;

// Player (v0.8.3, wie YouTube): kurz getippt startet das ganze Video sofort. Es folgt der Lage des Handys (Kippen):
// hochkant = Video oben, darunter Titel/Datum/Ort/Personen; quer = nur das Video, Vollbild ohne Text (per CSS).
// Schliessen per Zurueck-Geste/Esc. Kein Fullscreen-Befehl (Chrome-Hinweis), keine Drehsperre, kein Cache fuer Videos.
const VPlayer = {
  node: null,
  video: null,
  cur: null,

  init() {
    if (this.node) return;
    this.video = el("video", { class: "vp-video", controls: true, playsinline: true, preload: "auto" });
    // Handy: kein eigenes Vollbild des Players (v0.8.4) – sonst geht Chrome beim Kippen von selbst ins Vollbild, zeigt
    // „Ziehe zum Beenden …“ und die App verliert ihren Vollbild-Modus (weisser Balken). Im Querformat fuellt das Video ohnehin alles.
    if (isPhone()) this.video.setAttribute("controlslist", "nofullscreen");
    this.title = el("div", { class: "vp-title" });
    this.meta = el("div", { class: "vp-meta" });
    this.note = el("p", { class: "vp-note" });
    this.node = el("div", { id: "vplayer", hidden: true },
      el("div", { class: "vp-top" },
        el("button", { type: "button", class: "icon-btn", "aria-label": "Schließen", onclick: () => history.back() },
          svgNode(ICON_X)),
        this.title),
      this.video,
      el("div", { class: "vp-info" }, this.meta, this.note));
    document.body.append(this.node);
    this.video.addEventListener("error", () => {
      this.note.textContent = "Dieses Video lässt sich auf diesem Gerät nicht abspielen (die Videos sind im Format AV1).";
    });
    this.video.addEventListener("loadedmetadata", () => {         // echte Abmessungen, falls das Manifest sie nicht kennt
      if (this.video.videoWidth && !this.video.style.aspectRatio) {
        this.video.style.aspectRatio = `${this.video.videoWidth} / ${this.video.videoHeight}`;
      }
    });
    document.addEventListener("keydown", (e) => {
      if (this.cur && e.key === "Escape") history.back();
    });
  },

  sync(state) {
    const v = state.v === "videos" && state.vid && VIDEOS ? VIDEOS.byId.get(state.vid) : null;
    if (v) this.show(v);
    else this.hide();
  },

  show(v) {
    this.init();
    if (this.cur === v) return;
    this.cur = v;
    this.note.textContent = "";
    this.title.textContent = v.titel;
    this.meta.textContent = [fmtFull.format(parseLocal(v.t)), fmtDuration(v.dauer), v.ort, v.personen.join(", ")]
      .filter(Boolean).join(" · ");
    this.video.style.aspectRatio = v.breite && v.hoehe ? `${v.breite} / ${v.hoehe}` : "";
    this.video.poster = videoUrl(v, "poster.webp");
    VAuto.sync([]);
    this.node.hidden = false;
    document.body.classList.add("vp-open");
    this.video.src = videoUrl(v, "video.mp4");
    const p = this.video.play();
    if (p && p.catch) p.catch(() => {});          // ohne Antippen (z. B. Vorwaerts im Verlauf) startet der Browser evtl. nicht
  },

  hide() {
    if (!this.node || !this.cur) return;
    this.cur = null;
    this.video.pause();
    this.video.removeAttribute("src");
    this.video.removeAttribute("poster");
    this.video.load();          // Verbindung freigeben
    this.node.hidden = true;
    document.body.classList.remove("vp-open");
    if (mounted && mounted.grid && mounted.grid.autoplay) mounted.grid.render();      // Vorschau oben geht weiter
  },
};

/* ---------------------------------------------------------------- Ansichten & Verlauf */

let mounted = null;
const scrollMemory = new Map();

// Je Reihenfolge eigene Ansicht und Scroll-Position (sonst passt sie nach dem Umschalten nicht)
function viewKey(s) {
  const dir = (asc) => (asc ? "asc" : "desc");
  const star = starsOnly() ? `:stars${starLevel()}` : "";
  if (s.v === "folder") return `folder:${dir(oldestFirst())}${star}:${s.f}`;
  if (s.v === "all") return `all:${dir(oldestFirst())}${star}`;
  if (s.v === "search") return "search";
  if (s.v === "map") return "map";
  if (s.v === "world") return "world";
  if (s.v === "countries") return "countries";
  if (s.v === "mapgrid") return `mapgrid:${dir(oldestFirst())}`;
  if (s.v === "videos") return `videos:${readPref(VORDER_KEY) === "asc" ? "asc" : "desc"}`;
  if (s.v === "memories") return `memories:${localDay()}`;
  if (s.v === "memory") return `memory:${dir(oldestFirst())}:${localDay()}:${s.k}`;
  if (s.v === "people") return `people:${readPref(PEOPLE_ORDER_KEY) === "name" ? "name" : "count"}`;
  if (s.v === "person") return `person:${dir(oldestFirst())}${star}:${s.n}`;
  return `folders:${dir(foldersOldestFirst())}`;
}

function mountView(state) {
  const key = viewKey(state);
  if (mounted) {
    scrollMemory.set(mounted.key, window.scrollY);
    if (mounted.grid) mounted.grid.destroy();
  }
  const main = $("#main");
  main.replaceChildren();
  document.body.classList.toggle("map-mode", state.v === "map" || state.v === "world");
  const m = { key, grid: null, list: null };
  mounted = m;

  if (state.v === "folder") {
    const f = DATA.folderByName.get(state.f);
    if (!f) {
      mounted = null;
      navigate({ v: "folders" }, true);
      return;
    }
    const label = folderLabel(f);
    // am Handy Datum kurz (14.11.2016), damit der Untertitel neben den Knoepfen ganz passt (v0.7.16)
    const narrow = window.matchMedia("(max-width: 599px)").matches;
    const date = narrow && /^\d{4}-\d{2}-\d{2}$/.test(f.d || "") && label.date && !/–/.test(label.date)
      ? `${f.d.slice(8, 10)}.${f.d.slice(5, 7)}.${f.d.slice(0, 4)}` : label.date;
    setHeader(label.name, date ? `${date} · ${countLabel(f.c)}` : `${f.y} · ${countLabel(f.c)}`, true);
    // im Ordner: Standard aelteste zuerst, umschaltbar (gemeinsam mit Suche und Alle Bilder)
    showOrderButton(m, oldestFirst(), toggleOrder);
    showStarButton();
    m.toggleStars = toggleStars;
    if (OWNER) {          // nur mit deinem Link (v0.7.15)
      $("#share").hidden = false;
      m.share = () => shareFolder(f);
    }
    m.list = withStars(DATA.byFolder.get(f.n) || []);
    if (!oldestFirst()) m.list = m.list.slice().reverse();
    if (starsOnly()) $("#subtitle").textContent = `${countLabel(m.list.length)} ${starText()} · von ${f.c}`;
    if (m.list.length) m.grid = new Grid(main, m.list);
    else main.append(el("p", { class: "center muted", text: `Keine Bilder ${starText()} in diesem Ordner.` }));
    const more = folderMoreView(f);      // deutlich abgesetzt unter dem Raster (v0.7.16)
    if (more) main.append(more);
  } else if (state.v === "all") {
    m.list = withStars(oldestFirst() ? DATA.photos : DATA.allDesc);
    const total = starsOnly() ? `${countLabel(m.list.length)} ${starText()}` : countLabel(m.list.length);
    setHeader("Alle Bilder", total);
    showOrderButton(m, oldestFirst(), toggleOrder);
    showStarButton();
    m.toggleStars = toggleStars;
    // nach Jahren gruppiert (v0.6.35); das Jahr oben im Bild steht im Untertitel
    const perYear = starsOnly() ? new Map() : DATA.perYear;
    if (starsOnly()) for (const p of m.list) perYear.set(p.t.slice(0, 4), (perYear.get(p.t.slice(0, 4)) || 0) + 1);
    const yearOf = (p) => `${p.t.slice(0, 4)} · ${countLabel(perYear.get(p.t.slice(0, 4)))}`;
    if (m.list.length) {
      m.grid = new Grid(main, m.list, yearOf, (year) => {
        $("#subtitle").textContent = year || total;
      });
    } else {
      main.append(el("p", { class: "center muted", text: `Noch keine Bilder ${starText()} – in Lightroom Sterne setzen, Publish, sync.bat.` }));
    }
  } else if (state.v === "videos") {
    videosView(main, m);
  } else if (state.v === "map") {
    const M = mapView();
    const without = DATA.photos.length - M.points.length;
    setHeader("Karte", `${countLabel(M.points.length)} mit Ort${without ? ` · ${without.toLocaleString("de-DE")} ohne` : ""}`);
    showHeaderAction(m, "🌍 Länder", () => navigate({ v: "world" }));
    main.append(M.wrap);
    m.list = M.result;
    m.apply = (st) => { if (st.at) focusMapAt(st.at); };
    loadLeaflet().then(() => {
      if (mounted !== m) return;
      if (!M.map) initMap();
      else M.map.invalidateSize();
      if (state.at) focusMapAt(state.at);
      updateBar();
    }).catch(() => {
      M.bar.textContent = "Karte konnte nicht geladen werden – Verbindung prüfen.";
    });
    return;
  } else if (state.v === "world") {
    const W = worldView();
    const years = W.countries.length ? `${Math.min(...W.countries.map((c) => c.first))}–${Math.max(...W.countries.map((c) => c.last))}` : "";
    setHeader("Wo war ich wann?", W.countries.length ? `${W.countries.length} ${W.countries.length === 1 ? "Land" : "Länder"} · ${years}` : "", true);
    main.append(W.wrap);
    const ready = () => {
      if (W.focus) focusCountry(W.focus);
      W.focus = null;
    };
    m.apply = ready;
    loadLeaflet().then(() => (W.map ? W.map.invalidateSize() : initWorld())).then(() => {
      if (mounted === m) ready();
    }).catch(() => {
      W.bar.textContent = "Weltkarte konnte nicht geladen werden – Verbindung prüfen.";
    });
    return;
  } else if (state.v === "countries") {
    const W = worldView();
    setHeader("Länder", `${W.countries.length} · nach erstem Besuch · ab 6.4.1978`, true);
    main.append(countryListView());
  } else if (state.v === "mapgrid") {
    if (!MAP || !MAP.shown) {
      mounted = null;
      navigate({ v: "map" }, true);
      return;
    }
    setHeader("Karte", MAP.shown.sub, true);
    showOrderButton(m, oldestFirst(), toggleOrder);
    m.list = oldestFirst() ? MAP.shown.list : MAP.shown.list.slice().reverse();
    const perYear = new Map();
    for (const p of m.list) perYear.set(p.t.slice(0, 4), (perYear.get(p.t.slice(0, 4)) || 0) + 1);
    const yearOf = (p) => `${p.t.slice(0, 4)} · ${countLabel(perYear.get(p.t.slice(0, 4)))}`;
    m.grid = new Grid(main, m.list, yearOf, (year) => {
      $("#subtitle").textContent = year ? `${year} · ${MAP.shown.sub}` : MAP.shown.sub;
    });
  } else if (state.v === "memories") {
    const M = memories();
    setHeader("Erinnerungen", new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" }).format(new Date()));
    main.append(memoriesView());
    // Bild in einem Streifen angetippt: Betrachter mit den Bildern dieser Karte
    m.listFor = (st) => {
      const card = st.c && M.cards.find((c) => c.key === st.c);
      return card ? card.strip : null;
    };
  } else if (state.v === "memory") {
    const card = memoryCard(state.k);
    if (!card || !card.all) {
      mounted = null;
      navigate({ v: "memories" }, true);
      return;
    }
    setHeader(card.title, card.sub, true);
    showOrderButton(m, oldestFirst(), toggleOrder);
    m.list = card.all.slice().sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
    if (!oldestFirst()) m.list.reverse();
    m.grid = new Grid(main, m.list, card.sectionOf || yearSectionOf(m.list), (section) => {
      $("#subtitle").textContent = section || card.sub;
    });
  } else if (state.v === "people") {
    const byName = readPref(PEOPLE_ORDER_KEY) === "name";
    setHeader("Personen", `${personsIndex().size.toLocaleString("de-DE")} Personen`, true);
    showHeaderAction(m, byName ? "⇅ A–Z" : "⇅ häufigste", () => {
      writePref(PEOPLE_ORDER_KEY, byName ? "count" : "name");
      render(history.state || { v: "people" });
    });
    main.append(peopleView());
  } else if (state.v === "person") {
    const e = personsIndex().get(state.n);
    if (!e) {
      mounted = null;
      navigate({ v: "people" }, true);
      return;
    }
    const birth = birthOf(e.name);
    m.list = withStars(e.list);
    if (!oldestFirst()) m.list = m.list.slice().reverse();
    const sub = [starsOnly() ? `${countLabel(m.list.length)} ${starText()} · von ${e.list.length}` : countLabel(e.list.length),
      birthLabel(birth)].filter(Boolean).join(" · ");
    setHeader(e.name, sub, true);
    showOrderButton(m, oldestFirst(), toggleOrder);
    showStarButton();
    m.toggleStars = toggleStars;
    // je Jahr eine Ueberschrift mit dem Alter in diesem Jahr
    if (m.list.length) {
      m.grid = new Grid(main, m.list, yearSectionOf(m.list, birth), (section) => {
        $("#subtitle").textContent = section || sub;
      });
    } else {
      main.append(el("p", { class: "center muted", text: `Keine Bilder ${starText()} mit ${e.name}.` }));
    }
  } else if (state.v === "search") {
    setHeader("Suche");
    showStarButton();
    mountSearch(main, state, m);
    return;
  } else {
    setHeader("Fotoschatz");
    showOrderButton(m, foldersOldestFirst(), toggleFolderOrder);
    main.append(folderListView());
    renderInstallBanner();
  }

  window.scrollTo(0, scrollMemory.get(key) || 0);
  if (m.grid) m.grid.render();
}

function render(state) {
  if (!mounted || mounted.key !== viewKey(state)) mountView(state);
  else if (mounted.search) mounted.search.apply(state);
  else if (mounted.apply) mounted.apply(state);
  if (!mounted) return;
  updateNav(state.v);
  const list = mounted.listFor ? mounted.listFor(state) : mounted.list;
  if (state.viewer && list && list.length) Viewer.show(list, state.viewer.i);
  else Viewer.hide();
  VPlayer.sync(state);
}

function navigate(state, replace = false) {
  if (replace) history.replaceState(state, "");
  else history.pushState(state, "");
  render(state);
}

function switchTab(view) {
  const current = history.state || { v: "folders" };
  if (current.v === view) {
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  navigate({ v: view }, view === "folders" || current.v !== "folders");
}

/* ---------------------------------------------------------------- Teilen (v0.7.15, nur mit deinem Link) */

const linkFor = (key) => `${location.origin}${location.pathname}#${LINK_PREFIX}-${key}`;

function toast(text) {
  const old = $(".toast");
  if (old) old.remove();
  const node = el("div", { class: "toast", role: "status", text });
  document.body.append(node);
  setTimeout(() => node.remove(), 2500);
}

// Handy: Android-Teilen-Menue (WhatsApp usw.); PC: Link in die Zwischenablage
function shareLink(title, text, url) {
  const touch = window.matchMedia("(hover: none) and (pointer: coarse)").matches;
  if (touch && navigator.share) {
    navigator.share({ title, text, url }).catch(() => { /* abgebrochen */ });
    return;
  }
  const fallback = () => window.prompt("Link kopieren:", url);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(() => toast("Link kopiert – zum Teilen einfügen"), fallback);
  } else {
    fallback();
  }
}

function shareFolder(f) {
  const name = folderLabel(f).name;
  if (!f.s) {
    window.alert(`„${name}“ ist für Gäste ganz ausgeblendet (ausblenden.txt) – Teilen ist nicht möglich.`);
    return;
  }
  if (f.a && f.g < f.a) {
    const ok = window.confirm(`Wer den Link bekommt, sieht ${f.g} von ${f.a} Bildern ` +
      `(${f.a - f.g} sind ausgeblendet, ausblenden.txt). Teilen?`);
    if (!ok) return;
  }
  shareLink(name, `Fotos: ${name}`, linkFor(f.s));
}

/* ---------------------------------------------------------------- App installieren & Updates */

let installPrompt = null;

// Einmaliger Hinweis (v0.7.15): Chrome bietet „Installieren“ selbst an, Firefox nur ueber sein Menue.
// Nach „Installieren“, „Nein danke“ bzw. „OK“ kommt er auf diesem Geraet nie wieder; in der installierten App nie.
const IS_FIREFOX_ANDROID = /Android/.test(navigator.userAgent) && /Firefox\//.test(navigator.userAgent);

function renderInstallBanner() {
  const old = $(".install-bar");
  if (old) old.remove();
  const list = $(".folders");
  if (!list || readPref(INSTALL_KEY) === "1" || displayMode() !== "Browser") return;
  const done = () => { writePref(INSTALL_KEY, "1"); renderInstallBanner(); };
  if (installPrompt) {
    list.prepend(el("div", { class: "install-bar" },
      el("div", { class: "install-text" },
        el("b", { text: "Fotoschatz als App installieren" }),
        el("span", { text: "Dann liegt Fotoschatz als Symbol auf dem Startbildschirm." })),
      el("div", { class: "install-actions" },
        el("button", {
          type: "button", class: "search-action",
          onclick: async () => {
            const prompt = installPrompt;
            installPrompt = null;
            done();
            prompt.prompt();
            try { await prompt.userChoice; } catch (e) { /* egal */ }
          },
        }, "Installieren"),
        el("button", { type: "button", class: "install-no", onclick: done }, "Nein danke"))));
  } else if (IS_FIREFOX_ANDROID) {
    list.prepend(el("div", { class: "install-bar" },
      el("div", { class: "install-text" },
        el("b", { text: "Fotoschatz als App aufs Handy holen?" }),
        el("span", { text: "Tippe auf ⋮ (Menü) und dann auf „Installieren“ bzw. „Zum Startbildschirm hinzufügen“." })),
      el("div", { class: "install-actions" },
        el("button", { type: "button", class: "search-action", onclick: done }, "OK"))));
  }
}

function showUpdateBar(worker) {
  if ($(".update-bar")) return;
  document.body.append(el("div", { class: "update-bar", role: "status" },
    el("span", { text: "Neue Version verfügbar" }),
    el("button", {
      type: "button", class: "search-action",
      onclick: () => {
        updating = true;
        worker.postMessage("SKIP_WAITING");
      },
    }, "Neu laden")));
}

let updating = false;
let waitingWorker = null;
let reloadWhenHidden = false;

// Neue Version: du siehst „Neue Version verfügbar“; alle anderen bekommen sie still (v0.7.15) – neu geladen
// wird erst, wenn die App im Hintergrund ist, beim naechsten Oeffnen ist sie dann aktuell.
function applyUpdate() {
  const worker = waitingWorker;
  if (!worker || !DATA) return;
  if (OWNER) {
    showUpdateBar(worker);
  } else {
    waitingWorker = null;
    worker.postMessage("SKIP_WAITING");
  }
}

function registerServiceWorker() {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    renderInstallBanner();
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    writePref(INSTALL_KEY, "1");
    renderInstallBanner();
  });
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (updating) location.reload();
    else if (!OWNER) reloadWhenHidden = true;
  });
  document.addEventListener("visibilitychange", () => {
    if (reloadWhenHidden && document.visibilityState === "hidden") location.reload();
  });
  navigator.serviceWorker.register("sw.js").then((reg) => {
    const offer = (worker) => {
      if (worker && navigator.serviceWorker.controller) {
        waitingWorker = worker;
        applyUpdate();
      }
    };
    offer(reg.waiting);
    reg.addEventListener("updatefound", () => {
      const worker = reg.installing;
      if (!worker) return;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed") offer(worker);
      });
    });
    // Die App bleibt am Handy lange offen: beim Zurueckkehren und stuendlich nach Updates schauen
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") reg.update().catch(() => {});
    });
    setInterval(() => reg.update().catch(() => {}), 60 * 60 * 1000);
  }).catch(() => { /* ohne Service Worker geht die App trotzdem */ });
}

/* ---------------------------------------------------------------- Start */

function showNeutral(text) {
  $("#nav").hidden = true;
  setHeader("Fotoschatz");
  $("#main").replaceChildren(el("p", { class: "center muted", text }));
}

async function start() {
  // Neuer Link, waehrend die App schon offen ist (nur der Teil nach # aendert sich): merken und neu starten
  window.addEventListener("hashchange", () => {
    const link = decodeURIComponent(location.hash.slice(1)).trim();
    if (!SECRET_RE.test(link)) return;
    saveLinks([link, ...storedLinks().filter((x) => x !== link)]);
    history.replaceState(null, "", location.pathname + location.search);
    location.reload();
  });
  registerServiceWorker();
  Viewer.init();
  Cast.init();
  $("#back").addEventListener("click", () => history.back());
  // Umschalter in der Kopfzeile (Ordnerliste, Ordner, Alle Bilder): Reihenfolge umdrehen, oben neu beginnen
  $("#order").addEventListener("click", () => {
    if (mounted && mounted.headerAction) {
      mounted.headerAction();
      return;
    }
    if (!mounted || !mounted.toggleOrder) return;
    mounted.toggleOrder();
    const state = history.state || { v: "folders" };
    scrollMemory.delete(viewKey(state));
    render(state);
  });
  $("#share").addEventListener("click", () => { if (mounted && mounted.share) mounted.share(); });
  // Sternefilter in der Kopfzeile (Ordner, Alle Bilder, Suche); Suche zaehlt selbst neu, sonst neu aufbauen
  $("#stars").addEventListener("click", () => {
    if (!mounted || !mounted.toggleStars) return;
    const state = history.state || { v: "folders" };
    mounted.toggleStars();
    if (state.v === "search") return;
    scrollMemory.delete(viewKey(state));
    render(state);
  });
  for (const btn of document.querySelectorAll("#nav button")) {
    btn.addEventListener("click", () => switchTab(btn.dataset.view));
  }

  const deep = takeDeepLink();
  const links = takeLinks();
  if (!links.length) {
    showNeutral("Bitte den Link verwenden, den du bekommen hast.");
    return;
  }
  LINK_PREFIX = links[0].split("-")[0];
  BASE = `${R2_PUBLIC_URL}/${LINK_PREFIX}`;

  // Alle gemerkten Links laden (gleicher geheimer Teil); ungueltige still vergessen
  const results = await Promise.all(links.filter((l) => l.split("-")[0] === LINK_PREFIX).map(async (link) => {
    const key = link.split("-")[1];
    try {
      const res = await fetch(`${BASE}/${key ? `index-${key}` : "index"}.json`, { cache: "no-cache" });
      if (res.status === 403 || res.status === 404) return { link, gone: true };
      if (!res.ok) return { link, error: true };
      return { link, index: await res.json() };
    } catch (err) {
      return { link, error: true };
    }
  }));
  for (const r of results) if (r.gone) dropLink(r.link);
  const loaded = results.filter((r) => r.index);
  if (!loaded.length) {
    if (!results.some((r) => r.error)) {
      showNeutral("Bitte den Link verwenden, den du bekommen hast.");
      return;
    }
    showNeutral("Keine Verbindung – bitte später noch einmal versuchen.");
    $("#main").append(el("p", { class: "center" },
      el("button", { type: "button", class: "folder-row", text: "Neu laden", onclick: () => location.reload() })));
    return;
  }
  // Dein Verzeichnis enthaelt alles (und die Teilen-Schluessel) - dann nur dieses
  const own = loaded.find((r) => r.index.gk);
  OWNER = Boolean(own);
  const index = own ? own.index : mergeIndexes(loaded.map((r) => r.index));

  DATA = prepare(index);
  applyUpdate();
  $("#nav").hidden = false;
  window.addEventListener("popstate", (e) => render(e.state || { v: "folders" }));
  history.replaceState({ v: "folders" }, "");
  render({ v: "folders" });
  if (deep) openDeepLink(deep);
  loadVideos(loaded, own);        // Videos-Tab erst zeigen, wenn es ein Verzeichnis gibt (v0.8.0)
}

start();
