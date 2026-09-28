"use strict";

const APP_VERSION = "0.4.0";
const R2_PUBLIC_URL = "https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev";
const SECRET_KEY = "fotoschatz.secret";
const SECRET_RE = /^[A-Za-z0-9]{32,}$/;
const INFO_KEY = "fotoschatz.info";
const HEADER_H = 44;
const GAP = 2;

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
const fmtMonth = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" });

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

function prepare(index) {
  const photos = index.photos.slice().sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  const byFolder = new Map();
  for (const p of photos) {
    if (!byFolder.has(p.f)) byFolder.set(p.f, []);
    byFolder.get(p.f).push(p);
  }
  return {
    index,
    photos,
    byFolder,
    folderByName: new Map(index.folders.map((f) => [f.n, f])),
    allDesc: photos.slice().reverse(),
  };
}

/* ---------------------------------------------------------------- Kopfzeile & Leiste */

function setHeader(title, subtitle = "", back = false) {
  $("#title").textContent = title;
  $("#subtitle").textContent = subtitle;
  $("#back").hidden = !back;
}

function updateNav(view) {
  const active = view === "folder" ? "folders" : view;
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
  for (const year of [...years.keys()].sort((a, b) => b - a)) {
    const folders = years.get(year).sort((a, b) => {
      if ((a.x || 0) !== (b.x || 0)) return (a.x || 0) - (b.x || 0);
      return a.d < b.d ? 1 : a.d > b.d ? -1 : a.n.localeCompare(b.n, "de");
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
    text: `${countLabel(DATA.photos.length)} · Stand ${generated} · Version ${APP_VERSION}`,
  }));
  return wrap;
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
    const topLimit = window.scrollY + $("#top").offsetHeight;
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

const Viewer = {
  list: [],
  i: 0,
  open: false,
  drag: null,

  init() {
    this.root = $("#viewer");
    this.img = $(".v-photo", this.root);
    this.info = $(".v-info", this.root);
    this.counter = $(".v-counter", this.root);
    this.infoBtn = $(".v-info-btn", this.root);
    this.fsBtn = $(".v-fs-btn", this.root);
    this.autoFullscreen = window.matchMedia("(hover: none) and (pointer: coarse)").matches;
    this.setInfo(readPref(INFO_KEY) === "1");
    if (!document.documentElement.requestFullscreen) this.fsBtn.hidden = true;

    $(".v-close", this.root).addEventListener("click", () => history.back());
    $(".v-prev", this.root).addEventListener("click", () => this.go(-1));
    $(".v-next", this.root).addEventListener("click", () => this.go(1));
    this.infoBtn.addEventListener("click", () => this.setInfo(!this.infoOn, true));
    this.fsBtn.addEventListener("click", () => this.toggleFullscreen());
    const stage = $(".v-stage", this.root);
    stage.addEventListener("pointerdown", (e) => this.down(e));
    stage.addEventListener("pointermove", (e) => this.move(e));
    stage.addEventListener("pointerup", (e) => this.up(e));
    stage.addEventListener("pointercancel", () => this.reset());
    document.addEventListener("keydown", (e) => {
      if (!this.open) return;
      if (e.key === "ArrowLeft") this.go(-1);
      else if (e.key === "ArrowRight") this.go(1);
      else if (e.key === "Escape") history.back();
      else if (e.key === "i") this.setInfo(!this.infoOn, true);
      else if (e.key === "f") this.toggleFullscreen();
    });
    document.addEventListener("fullscreenchange", () => {
      // Handy: Zurueck-Taste beendet zuerst nur das Vollbild - dann auch das Bild schliessen.
      if (document.fullscreenElement || !this.open || !this.autoFullscreen) return;
      setTimeout(() => { if (this.open) history.back(); }, 300);
    });
  },

  setInfo(on, remember = false) {
    this.infoOn = on;
    this.root.classList.toggle("info-on", on);
    this.infoBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (remember) writePref(INFO_KEY, on ? "1" : "0");
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
      if (this.autoFullscreen) this.enterFullscreen();
    }
    this.display(i);
  },

  hide() {
    if (!this.open) return;
    this.open = false;
    this.root.hidden = true;
    this.img.removeAttribute("src");
    document.body.classList.remove("noscroll");
    this.exitFullscreen();
    if (mounted && mounted.grid) mounted.grid.scrollToPhoto(this.i);
  },

  display(i) {
    this.i = Math.max(0, Math.min(i, this.list.length - 1));
    const p = this.list[this.i];
    if (!p) return;
    this.img.style.transform = "";
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

  renderInfo(p) {
    const folder = DATA.folderByName.get(p.f);
    const label = folder ? folderLabel(folder) : { name: p.f, date: "" };
    const place = [...new Set([p.sl, p.ci, p.st, p.co].filter(Boolean))].join(", ");
    const lines = [el("div", { class: "when", text: fmtFull.format(parseLocal(p.t)) })];
    lines.push(el("div", { class: "line", text: label.date ? `${label.name} · ${label.date}` : label.name }));
    if (p.p && p.p.length) lines.push(el("div", { class: "line" }, el("span", { class: "label", text: "Personen: " }), p.p.join(", ")));
    if (place) lines.push(el("div", { class: "line" }, el("span", { class: "label", text: "Ort: " }), place));
    if (p.de && p.de !== label.name && p.de !== p.f) lines.push(el("div", { class: "line", text: p.de }));
    if (p.r) lines.push(el("div", { class: "line", text: "★".repeat(p.r) + "☆".repeat(Math.max(0, 5 - p.r)) }));
    this.info.replaceChildren(...lines);
  },

  go(delta) {
    const next = this.i + delta;
    if (next < 0 || next >= this.list.length) {
      this.img.style.transform = "";
      return;
    }
    history.replaceState({ ...history.state, viewer: { i: next } }, "");
    this.display(next);
  },

  down(e) {
    this.drag = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, dy: 0 };
    e.currentTarget.setPointerCapture(e.pointerId);
    this.root.classList.add("dragging");
  },

  move(e) {
    if (!this.drag || e.pointerId !== this.drag.id) return;
    this.drag.dx = e.clientX - this.drag.x;
    this.drag.dy = e.clientY - this.drag.y;
    const horizontal = Math.abs(this.drag.dx) > Math.abs(this.drag.dy);
    this.img.style.transform = horizontal
      ? `translateX(${this.drag.dx}px)`
      : `translateY(${Math.max(0, this.drag.dy)}px)`;
  },

  up(e) {
    if (!this.drag || e.pointerId !== this.drag.id) return;
    const { dx, dy } = this.drag;
    this.reset();
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8) {
      const x = e.clientX / window.innerWidth;
      if (x < 0.3) this.go(-1);
      else if (x > 0.7) this.go(1);
      else this.root.classList.toggle("ui-hidden");
    } else if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 60) {
      this.go(dx < 0 ? 1 : -1);
    } else if (dy > 120 && Math.abs(dy) > Math.abs(dx)) {
      history.back();
    }
  },

  reset() {
    this.drag = null;
    this.root.classList.remove("dragging");
    this.img.style.transform = "";
  },
};

function openViewer(i) {
  navigate({ ...history.state, viewer: { i } });
}

/* ---------------------------------------------------------------- Ansichten & Verlauf */

let mounted = null;
const scrollMemory = new Map();

const viewKey = (s) => (s.v === "folder" ? `folder:${s.f}` : s.v);

function mountView(state) {
  const key = viewKey(state);
  if (mounted) {
    scrollMemory.set(mounted.key, window.scrollY);
    if (mounted.grid) mounted.grid.destroy();
  }
  const main = $("#main");
  main.replaceChildren();
  let grid = null;
  let list = null;

  if (state.v === "folder") {
    const f = DATA.folderByName.get(state.f);
    if (!f) {
      navigate({ v: "folders" }, true);
      return;
    }
    const label = folderLabel(f);
    setHeader(label.name, label.date ? `${label.date} · ${countLabel(f.c)}` : `${f.y} · ${countLabel(f.c)}`, true);
    list = DATA.byFolder.get(f.n) || [];
    grid = new Grid(main, list);
  } else if (state.v === "all") {
    setHeader("Alle Bilder", countLabel(DATA.photos.length));
    list = DATA.allDesc;
    const monthOf = (p) => fmtMonth.format(parseLocal(p.t));
    grid = new Grid(main, list, monthOf, (month) => {
      $("#subtitle").textContent = month || countLabel(DATA.photos.length);
    });
  } else if (state.v === "search") {
    setHeader("Suche");
    main.append(el("p", { class: "center muted", text: "Die Suche kommt mit der nächsten Version." }));
  } else {
    setHeader("Fotoschatz");
    main.append(folderListView());
  }

  mounted = { key, grid, list };
  window.scrollTo(0, scrollMemory.get(key) || 0);
  if (grid) grid.render();
}

function render(state) {
  if (!mounted || mounted.key !== viewKey(state)) mountView(state);
  if (!mounted) return;
  updateNav(state.v);
  if (state.viewer && mounted.list) Viewer.show(mounted.list, state.viewer.i);
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

/* ---------------------------------------------------------------- Start */

function showNeutral(text) {
  $("#nav").hidden = true;
  setHeader("Fotoschatz");
  $("#main").replaceChildren(el("p", { class: "center muted", text }));
}

async function start() {
  Viewer.init();
  $("#back").addEventListener("click", () => history.back());
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
