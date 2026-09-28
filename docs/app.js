"use strict";

const APP_VERSION = "0.5.0";
const R2_PUBLIC_URL = "https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev";
const SECRET_KEY = "fotoschatz.secret";
const SECRET_RE = /^[A-Za-z0-9]{32,}$/;
const INFO_KEY = "fotoschatz.info";
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
    this.autoFullscreen = window.matchMedia("(hover: none) and (pointer: coarse)").matches;
    this.setInfo(readPref(INFO_KEY) === "1");
    if (!document.documentElement.requestFullscreen) this.fsBtn.hidden = true;

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
    clearTimeout(this.tapTimer);
    this.reset();
    document.body.classList.remove("noscroll");
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

// Begriffe: p = Person, o = Ort (Ort, Stadt, Bundesland, Land), f = Ordner, y = Jahr, k = Stichwort
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

// Einmal aufbauen: Begriff -> Positionen in DATA.allDesc (neueste zuerst) und je Bild ein Suchtext.
function buildSearch() {
  const list = DATA.allDesc;
  const terms = new Map();
  const add = (type, value, i, label = value, sub = "") => {
    const norm = normText(value);
    if (!norm) return;
    const key = `${type}:${type === "f" ? value : norm}`;
    let t = terms.get(key);
    if (!t) {
      t = { key, type, label, sub, norm, ids: [] };
      terms.set(key, t);
    }
    if (t.ids[t.ids.length - 1] !== i) t.ids.push(i);
  };
  const folderInfo = new Map();
  for (const f of DATA.index.folders) {
    const label = folderLabel(f);
    folderInfo.set(f.n, f.x ? { name: f.n, sub: String(f.y) } : { name: label.name, sub: label.date || String(f.y) });
  }
  const text = new Array(list.length);
  list.forEach((p, i) => {
    for (const name of p.p || []) add("p", name, i);
    for (const place of [p.sl, p.ci, p.st, p.co]) if (place) add("o", place, i);
    const fi = folderInfo.get(p.f) || { name: p.f, sub: "" };
    add("f", p.f, i, fi.name, fi.sub);
    add("y", p.t.slice(0, 4), i);
    for (const k of p.kw || []) add("k", k, i);
    const parts = [p.de, p.sl, p.ci, p.st, p.co, p.f, ...(p.p || []), ...(p.kw || [])];
    text[i] = ` ${normText(parts.filter(Boolean).join(" "))} `;
  });
  for (const t of terms.values()) if (t.type === "f") t.norm = normText(`${t.key.slice(2)} ${t.label}`);
  return { terms, text };
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
  const w = words(freeText);
  if (w.length) {
    const base = pos || DATA.allDesc.map((_, i) => i);
    pos = base.filter((i) => w.every((x) => SEARCH.text[i].includes(x)));
  }
  return pos;
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

function svgNode(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup;
  return t.content.firstChild;
}

function mountSearch(main, state, m) {
  if (!SEARCH) SEARCH = buildSearch();
  const s = {
    keys: (state.q || lastSearch.q).filter((k) => SEARCH.terms.has(k)),
    text: state.t !== undefined ? state.t : lastSearch.t,
    panel: false,
    shown: null,
  };

  const chips = el("div", { class: "chips" });
  const input = el("input", {
    type: "search", placeholder: "Person, Ort, Ordner, Jahr …", enterkeyhint: "search",
    autocomplete: "off", autocapitalize: "off", spellcheck: "false", "aria-label": "Suchbegriff",
  });
  input.value = s.text;
  const clear = el("button", { type: "button", class: "icon-btn search-clear", "aria-label": "Eingabe löschen" }, svgNode(ICON_X));
  const bar = el("div", { class: "search-bar" },
    chips, el("div", { class: "search-field" }, svgNode(ICON_SEARCH), input, clear));
  const body = el("div", { class: "search-body" });
  const results = el("div", { class: "search-results" });
  main.append(bar, body, results);

  const addKey = (key) => {
    s.keys.push(key);
    s.text = "";
    input.value = "";
    s.panel = false;
    input.blur();
    update();
  };

  const pick = (t, count) => el("button", { type: "button", class: "pick", onclick: () => addKey(t.key) },
    t.label, el("small", { text: String(count ?? t.ids.length) }));

  function renderChips() {
    chips.replaceChildren(...s.keys.map((key) => {
      const t = SEARCH.terms.get(key);
      return el("button", {
        type: "button", class: "chip", title: `${TERM_GROUP[t.type]} – entfernen`,
        onclick: () => { s.keys = s.keys.filter((k) => k !== key); update(); },
      }, el("span", { text: t.label }), svgNode(ICON_X));
    }));
    clear.hidden = !s.text;
  }

  function renderPanel() {
    const nodes = [];
    const free = searchPositions(s.keys, s.text);
    nodes.push(el("button", {
      type: "button", class: "sg-row sg-free", onclick: () => { s.panel = false; input.blur(); update(); },
    }, el("span", { class: "name", text: `Freitext „${s.text.trim()}“` }),
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

  function renderPicks() {
    const top = (type) => [...SEARCH.terms.values()].filter((t) => t.type === type)
      .sort((a, b) => b.ids.length - a.ids.length || a.label.localeCompare(b.label, "de")).slice(0, PICK_LIMIT);
    const years = [...SEARCH.terms.values()].filter((t) => t.type === "y").sort((a, b) => (a.label < b.label ? 1 : -1));
    const nodes = [];
    for (const [title, list] of [["Personen", top("p")], ["Orte", top("o")], ["Jahre", years]]) {
      if (!list.length) continue;
      nodes.push(el("div", { class: "sg-head", text: title }), el("div", { class: "picks" }, ...list.map((t) => pick(t))));
    }
    if (!nodes.length) nodes.push(el("p", { class: "center muted", text: "Suchbegriff eingeben." }));
    body.replaceChildren(...nodes);
  }

  function showResults() {
    const signature = JSON.stringify([s.keys, words(s.text)]);
    if (signature === s.shown) {
      if (m.grid) m.grid.render();
      return;
    }
    s.shown = signature;
    if (m.grid) m.grid.destroy();
    m.grid = null;
    results.replaceChildren();
    const pos = searchPositions(s.keys, s.text) || [];
    m.list = pos.map((i) => DATA.allDesc[i]);
    $("#subtitle").textContent = pos.length ? countLabel(pos.length) : "";
    window.scrollTo(0, 0);
    if (m.list.length) m.grid = new Grid(results, m.list);
    else results.append(el("p", { class: "center muted", text: "Keine Bilder gefunden." }));
  }

  function update() {
    lastSearch = { q: s.keys.slice(), t: s.text };
    history.replaceState({ ...(history.state || {}), v: "search", q: lastSearch.q, t: s.text }, "");
    renderChips();
    const searching = s.keys.length > 0 || words(s.text).length > 0;
    if (s.panel && s.text.trim()) {
      results.hidden = true;
      renderPanel();
    } else if (!searching) {
      results.hidden = true;
      s.shown = null;
      if (m.grid) m.grid.destroy();
      m.grid = null;
      m.list = [];
      results.replaceChildren();
      $("#subtitle").textContent = "";
      renderPicks();
    } else {
      body.replaceChildren();
      results.hidden = false;
      showResults();
    }
  }

  input.addEventListener("input", () => {
    s.text = input.value;
    s.panel = true;
    update();
  });
  input.addEventListener("focus", () => {
    if (s.text.trim() && !s.panel) {
      s.panel = true;
      update();
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    s.panel = false;
    input.blur();
    update();
  });
  clear.addEventListener("click", () => {
    s.text = "";
    input.value = "";
    s.panel = false;
    update();
  });

  update();
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
    m.list = DATA.byFolder.get(f.n) || [];
    m.grid = new Grid(main, m.list);
  } else if (state.v === "all") {
    setHeader("Alle Bilder", countLabel(DATA.photos.length));
    m.list = DATA.allDesc;
    const monthOf = (p) => fmtMonth.format(parseLocal(p.t));
    m.grid = new Grid(main, m.list, monthOf, (month) => {
      $("#subtitle").textContent = month || countLabel(DATA.photos.length);
    });
  } else if (state.v === "search") {
    setHeader("Suche");
    mountSearch(main, state, m);
    return;
  } else {
    setHeader("Fotoschatz");
    main.append(folderListView());
  }

  window.scrollTo(0, scrollMemory.get(key) || 0);
  if (m.grid) m.grid.render();
}

function render(state) {
  if (!mounted || mounted.key !== viewKey(state)) mountView(state);
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
