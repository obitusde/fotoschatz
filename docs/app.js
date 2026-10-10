"use strict";

const APP_VERSION = "0.7.8";
const R2_PUBLIC_URL = "https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev";
const SECRET_KEY = "fotoschatz.secret";
const SECRET_RE = /^[A-Za-z0-9]{32,}$/;
const INFO_KEY = "fotoschatz.info";
const INSTALL_KEY = "fotoschatz.install-hidden";
const ORDER_KEY = "fotoschatz.order";   // Bilder (Suche, Alle Bilder, im Ordner): "asc" = aelteste zuerst (Standard), "desc" = neueste zuerst
const STARS_KEY = "fotoschatz.stars";   // "1" = nur Bilder mit Sternen (Ordner, Alle Bilder, Suche; v0.6.38)
const FOLDER_ORDER_KEY = "fotoschatz.folder-order";   // Ordnerliste: "desc" = neueste zuerst (Standard), "asc" = aelteste zuerst
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

function takeSecret() {
  const fromHash = decodeURIComponent(location.hash.slice(1)).trim();
  if (fromHash) {
    history.replaceState(null, "", location.pathname + location.search);
    if (SECRET_RE.test(fromHash)) {
      try { localStorage.setItem(SECRET_KEY, fromHash); } catch (e) { /* privat */ }
      return fromHash;
    }
  }
  try {
    const stored = localStorage.getItem(SECRET_KEY);
    if (stored && SECRET_RE.test(stored)) return stored;
  } catch (e) { /* privat */ }
  return null;
}

function readPref(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* privat */ }
}

function forgetSecret() {
  try { localStorage.removeItem(SECRET_KEY); } catch (e) { /* privat */ }
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

/* ---------------------------------------------------------------- Kopfzeile & Leiste */

const oldestFirst = () => readPref(ORDER_KEY) !== "desc";
const foldersOldestFirst = () => readPref(FOLDER_ORDER_KEY) === "asc";
const orderLabel = (asc = oldestFirst()) => (asc ? "⇅ älteste zuerst" : "⇅ neueste zuerst");

function toggleOrder() {
  writePref(ORDER_KEY, oldestFirst() ? "desc" : "asc");
}

// Sternefilter (v0.6.38): nur Bilder mit ★ oder ★★ (Feld r aus Lightroom)
const starsOnly = () => readPref(STARS_KEY) === "1";
const withStars = (list) => (starsOnly() ? list.filter((p) => p.r) : list);

function toggleStars() {
  writePref(STARS_KEY, starsOnly() ? "0" : "1");
}

function showStarButton() {
  const btn = $("#stars");
  const on = starsOnly();
  btn.textContent = on ? "★" : "☆";
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.title = on ? "Nur Bilder mit Sternen – antippen für alle" : "Alle Bilder – antippen für nur Bilder mit Sternen";
  btn.hidden = false;
}

function toggleFolderOrder() {
  writePref(FOLDER_ORDER_KEY, foldersOldestFirst() ? "desc" : "asc");
}

// Knopf rechts in der Kopfzeile fuer eine eigene Aktion (z. B. Karte -> Laender)
function showHeaderAction(m, label, action) {
  const btn = $("#order");
  btn.textContent = label;
  btn.hidden = false;
  m.headerAction = action;
}

// Kleiner Umschalter rechts in der Kopfzeile (Ordnerliste, Ordner, Alle Bilder) – je Ansicht eigene Aktion
function showOrderButton(m, asc, toggle) {
  const order = $("#order");
  order.textContent = orderLabel(asc);
  order.hidden = false;
  m.toggleOrder = toggle;
}

function setHeader(title, subtitle = "", back = false) {
  const order = $("#order");
  if (order) order.hidden = true;
  const stars = $("#stars");
  if (stars) stars.hidden = true;
  $("#title").textContent = title;
  $("#subtitle").textContent = subtitle;
  $("#back").hidden = !back;
}

function updateNav(view) {
  const active = view === "folder" ? "folders" : ["mapgrid", "world", "countries"].includes(view) ? "map" : view;
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
    if (p.r) rows.push(["Bewertung", p.r === 1 ? "★ wichtig" : p.r === 2 ? "★★ Lieblingsbild" : "★".repeat(p.r)]);
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
  if (starsOnly()) pos = pos ? pos.filter((i) => DATA.allDesc[i].r) : SEARCH.starred;
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
  const s = { keys: [], text: "", mode: "select", panel: false, shown: null, open: new Set(), allPersons: false, pending: null };

  const chips = el("div", { class: "chips" });
  const input = el("input", {
    type: "search", placeholder: "Person, Ort, Ordner, Jahr …", enterkeyhint: "search",
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
    }, el("span", { class: "name", text: `Freitext „${s.text.trim()}“ übernehmen` }),
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

  // Orte als Baum: Antippen klappt auf, erste Zeile "Ganz …" waehlt den ganzen Zweig
  function placeRows(counts) {
    const rows = [];
    const chosen = s.keys.filter((k) => k.startsWith("o:"));
    const walk = (parent, depth) => {
      const kids = (SEARCH.children.get(parent) || []).filter((k) => counts.get(k))
        .sort((a, b) => counts.get(b) - counts.get(a) || SEARCH.terms.get(a).label.localeCompare(SEARCH.terms.get(b).label, "de"));
      for (const key of kids) {
        const t = SEARCH.terms.get(key);
        const n = counts.get(key);
        const path = key.slice(2);
        const hasKids = (SEARCH.children.get(path) || []).some((k) => counts.get(k));
        const isChosen = chosen.includes(key);
        const open = hasKids && (isChosen || s.open.has(key) || chosen.some((c) => c.startsWith(`${key}|`)));
        const row = el("button", {
          type: "button",
          class: "tree-row" + (open ? " open" : "") + (isChosen ? " chosen" : ""),
          style: `padding-left:${16 + depth * 20}px`,
          "aria-expanded": hasKids ? String(open) : null,
          onclick: () => {
            if (isChosen) return;
            if (!hasKids) { addKey(key); return; }
            if (s.open.has(key)) s.open.delete(key);
            else s.open.add(key);
            renderFacets();
          },
        }, el("span", { class: "name", text: t.label }), el("span", { class: "meta", text: n.toLocaleString("de-DE") }),
        hasKids ? svgNode(ICON_CHEVRON) : el("span", { class: "chev-space" }));
        rows.push(row);
        if (open) {
          if (!isChosen) {
            rows.push(el("button", {
              type: "button", class: "tree-row tree-all", style: `padding-left:${16 + (depth + 1) * 20}px`,
              onclick: () => addKey(key),
            }, el("span", { class: "name", text: `Ganz ${t.label}` }), el("span", { class: "meta", text: n.toLocaleString("de-DE") }),
            el("span", { class: "chev-space" })));
          }
          walk(path, depth + 1);
        }
      }
    };
    walk("", 0);
    return rows;
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
      nodes.push(el("div", { class: "sg-head", text: "Personen" }), box);
    }
    const places = placeRows(counts);
    if (places.length) nodes.push(el("div", { class: "sg-head", text: "Orte" }), el("div", { class: "tree" }, ...places));
    const years = yearNodes(counts);
    if (years.length) nodes.push(el("div", { class: "sg-head", text: "Jahre" }), ...years);
    const keywords = ofType("k").sort(byCount).slice(0, 30);
    if (keywords.length) nodes.push(el("div", { class: "sg-head", text: "Stichwörter" }), el("div", { class: "picks" }, ...keywords.map((t) => pick(t, counts.get(t.key)))));
    if (!nodes.length) nodes.push(el("p", { class: "center muted", text: "Nichts weiter einzugrenzen." }));
    body.replaceChildren(...nodes);
  }

  function renderResults() {
    const signature = JSON.stringify([s.keys, words(s.text), oldestFirst(), starsOnly()]);
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
    const perYear = new Map();
    for (const p of m.list) perYear.set(p.t.slice(0, 4), (perYear.get(p.t.slice(0, 4)) || 0) + 1);
    const yearOf = (p) => `${p.t.slice(0, 4)} · ${countLabel(perYear.get(p.t.slice(0, 4)))}`;
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

/* ---------------------------------------------------------------- Ansichten & Verlauf */

let mounted = null;
const scrollMemory = new Map();

// Je Reihenfolge eigene Ansicht und Scroll-Position (sonst passt sie nach dem Umschalten nicht)
function viewKey(s) {
  const dir = (asc) => (asc ? "asc" : "desc");
  const star = starsOnly() ? ":stars" : "";
  if (s.v === "folder") return `folder:${dir(oldestFirst())}${star}:${s.f}`;
  if (s.v === "all") return `all:${dir(oldestFirst())}${star}`;
  if (s.v === "search") return "search";
  if (s.v === "map") return "map";
  if (s.v === "world") return "world";
  if (s.v === "countries") return "countries";
  if (s.v === "mapgrid") return `mapgrid:${dir(oldestFirst())}`;
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
    setHeader(label.name, label.date ? `${label.date} · ${countLabel(f.c)}` : `${f.y} · ${countLabel(f.c)}`, true);
    // im Ordner: Standard aelteste zuerst, umschaltbar (gemeinsam mit Suche und Alle Bilder)
    showOrderButton(m, oldestFirst(), toggleOrder);
    showStarButton();
    m.toggleStars = toggleStars;
    m.list = withStars(DATA.byFolder.get(f.n) || []);
    if (!oldestFirst()) m.list = m.list.slice().reverse();
    if (starsOnly()) $("#subtitle").textContent = `${countLabel(m.list.length)} mit Sternen · von ${f.c}`;
    if (m.list.length) m.grid = new Grid(main, m.list);
    else main.append(el("p", { class: "center muted", text: "Keine Bilder mit Sternen in diesem Ordner." }));
  } else if (state.v === "all") {
    m.list = withStars(oldestFirst() ? DATA.photos : DATA.allDesc);
    const total = starsOnly() ? `${countLabel(m.list.length)} mit Sternen` : countLabel(m.list.length);
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
      main.append(el("p", { class: "center muted", text: "Noch keine Bilder mit Sternen – in Lightroom ★ oder ★★ setzen, neu exportieren, sync.bat." }));
    }
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
  if (state.viewer && mounted.list && mounted.list.length) Viewer.show(mounted.list, state.viewer.i);
  else Viewer.hide();
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

/* ---------------------------------------------------------------- App installieren & Updates */

let installPrompt = null;

function renderInstallBanner() {
  const old = $(".install-bar");
  if (old) old.remove();
  const list = $(".folders");
  if (!installPrompt || !list || readPref(INSTALL_KEY) === "1") return;
  list.prepend(el("div", { class: "install-bar" },
    el("span", { text: "Fotoschatz als App auf dem Startbildschirm?" }),
    el("button", {
      type: "button", class: "search-action",
      onclick: async () => {
        const prompt = installPrompt;
        installPrompt = null;
        renderInstallBanner();
        prompt.prompt();
        try { await prompt.userChoice; } catch (e) { /* egal */ }
      },
    }, "Installieren"),
    el("button", {
      type: "button", class: "icon-btn", "aria-label": "Nicht mehr anzeigen",
      onclick: () => { writePref(INSTALL_KEY, "1"); renderInstallBanner(); },
    }, svgNode(ICON_X))));
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

function registerServiceWorker() {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    renderInstallBanner();
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    renderInstallBanner();
  });
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (updating) location.reload();
  });
  navigator.serviceWorker.register("sw.js").then((reg) => {
    const offer = (worker) => {
      if (worker && navigator.serviceWorker.controller) showUpdateBar(worker);
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
  registerServiceWorker();
  Viewer.init();
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

  const secret = takeSecret();
  if (!secret) {
    showNeutral("Bitte den Link verwenden, den du bekommen hast.");
    return;
  }
  BASE = `${R2_PUBLIC_URL}/${secret}`;

  let index;
  try {
    const res = await fetch(`${BASE}/index.json`, { cache: "no-cache" });
    if (res.status === 403 || res.status === 404) {
      forgetSecret();
      showNeutral("Bitte den Link verwenden, den du bekommen hast.");
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    index = await res.json();
  } catch (err) {
    showNeutral("Keine Verbindung – bitte später noch einmal versuchen.");
    $("#main").append(el("p", { class: "center" },
      el("button", { type: "button", class: "folder-row", text: "Neu laden", onclick: () => location.reload() })));
    return;
  }

  DATA = prepare(index);
  $("#nav").hidden = false;
  window.addEventListener("popstate", (e) => render(e.state || { v: "folders" }));
  history.replaceState({ v: "folders" }, "");
  render({ v: "folders" });
}

start();
