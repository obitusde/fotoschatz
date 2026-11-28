"use strict";

/* Fotoschatz Videos fuer den Fernseher (nur ansehen). Liest dieselben Video-Verzeichnisse wie die App
   (<Praefix>/videos/index-<Schluessel>.json). Bedienung nur ueber Fernbedienung/Tastatur (Ziffern, Medien-, Farbtasten). */
const TV_VERSION = "0.8.15";
const R2_PUBLIC_URL = "https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev";
const SECRET_RE = /^[A-Za-z0-9]{32,}(-[A-Za-z0-9]{16,})?$/;
const LINK_KEY = "fotoschatz.tv.link";
const POS_KEY = "fotoschatz.tv.pos";
const ORDER_KEY = "fotoschatz.tv.order";
const COLS = 4;

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of kids) n.append(c);
  return n;
};
const readPref = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const writePref = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* egal */ } };

const S = {
  base: "", list: [], shown: [], year: "", person: "", desc: true,
  cur: 0, yi: 0, pi: 0, years: [], persons: [], pos: {}, player: null, help: false,
};

/* ---------------------------------------------------------------- Link (einmal als Lesezeichen, dann gemerkt) */

function takeLink() {
  let link = "";
  const fromHash = decodeURIComponent(location.hash.slice(1)).trim();
  if (fromHash) {
    history.replaceState(null, "", location.pathname + location.search);
    if (SECRET_RE.test(fromHash)) { link = fromHash; writePref(LINK_KEY, link); }
  }
  if (!link) {
    const own = readPref(LINK_KEY);
    if (own && SECRET_RE.test(own)) link = own;
  }
  if (!link) {         // am PC zum Testen: ein in der App gemerkter Link
    try {
      const list = JSON.parse(readPref("fotoschatz.links") || "[]");
      link = (Array.isArray(list) ? list : []).find((x) => typeof x === "string" && SECRET_RE.test(x) && x.includes("-")) || "";
    } catch (e) { /* egal */ }
  }
  return link;
}

/* ---------------------------------------------------------------- Daten */

const videoUrl = (v, name) => `${S.base}/videos/${v.id}/${name}`;
const fmtDuration = (sec) => {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
};
const fmtDay = (t) => `${t.slice(8, 10)}.${t.slice(5, 7)}.${t.slice(0, 4)}`;
const countLabel = (n) => (n === 1 ? "1 Video" : `${n.toLocaleString("de-DE")} Videos`);

function cleanVideos(data) {
  const raw = data && Array.isArray(data.videos) ? data.videos : [];
  const list = [];
  for (const v of raw) {
    if (!v || typeof v.id !== "string" || !/^[A-Za-z0-9]{8,64}$/.test(v.id)) continue;
    if (v.privat) continue;                                  // auf dem Wohnzimmer-Fernseher nicht zeigen
    const datum = /^\d{4}-\d{2}-\d{2}$/.test(v.datum || "") ? v.datum : "1900-01-01";
    const zeit = /^\d{2}:\d{2}$/.test(v.zeit || "") ? v.zeit : "00:00";
    list.push({
      id: v.id,
      titel: String(v.titel || "Ohne Titel"),
      t: `${datum}T${zeit}`,
      dauer: Number(v.dauer) || 0,
      ort: v.ort ? String(v.ort) : "",
      personen: Array.isArray(v.personen) ? v.personen.map(String).filter(Boolean) : [],
    });
  }
  return list;
}

/* ---------------------------------------------------------------- Weiterschauen (je Geraet) */

function loadPos() {
  try { const d = JSON.parse(readPref(POS_KEY) || "{}"); S.pos = d && typeof d === "object" ? d : {}; } catch (e) { S.pos = {}; }
}
function savePos(v, t, d) {
  if (!v) return;
  if (!d || t < 5 || t > d - 10) delete S.pos[v.id];          // am Anfang oder (fast) zu Ende: nichts merken
  else S.pos[v.id] = [Math.round(t), Math.round(d)];
  writePref(POS_KEY, JSON.stringify(S.pos));
}

/* ---------------------------------------------------------------- Filter und Raster */

function buildOptions() {
  const years = new Map(), persons = new Map();
  for (const v of S.list) {
    const y = v.t.slice(0, 4);
    years.set(y, (years.get(y) || 0) + 1);
    for (const p of new Set(v.personen)) persons.set(p, (persons.get(p) || 0) + 1);
  }
  S.years = [{ value: "", label: "Alle", count: S.list.length },
    ...[...years.keys()].sort().reverse().map((y) => ({ value: y, label: y, count: years.get(y) }))];
  S.persons = [{ value: "", label: "Alle", count: S.list.length },
    ...[...persons.keys()].sort((a, b) => persons.get(b) - persons.get(a) || a.localeCompare(b, "de"))
      .map((p) => ({ value: p, label: p, count: persons.get(p) }))];
}

function renderChips(row, opts, current, kind) {
  row.replaceChildren();
  opts.forEach((o, i) => {
    const b = el("button", { type: "button", class: `chip${o.value === current ? " on" : ""}`, "data-kind": kind, "data-i": String(i) },
      el("span", { text: o.label }), el("small", { text: String(o.count) }));
    b.addEventListener("click", () => { S.keys = false; chooseChip(kind, i); });
    row.append(b);
  });
}

function applyFilter(keepId) {
  let shown = S.list.filter((v) => (!S.year || v.t.startsWith(S.year)) && (!S.person || v.personen.includes(S.person)));
  shown.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  if (S.desc) shown.reverse();
  S.shown = shown;
  S.yi = Math.max(0, S.years.findIndex((o) => o.value === S.year));
  S.pi = Math.max(0, S.persons.findIndex((o) => o.value === S.person));
  renderChips($("#years"), S.years, S.year, "y");
  renderChips($("#persons"), S.persons, S.person, "p");
  $("#count").textContent = countLabel(shown.length) + (S.year || S.person ? ` von ${S.list.length.toLocaleString("de-DE")}` : "");
  $("#orderlabel").textContent = S.desc ? "neueste zuerst" : "älteste zuerst";
  renderGrid();
  const at = keepId ? shown.findIndex((v) => v.id === keepId) : -1;
  S.cur = at >= 0 ? at : 0;
}

function renderGrid() {
  const grid = $("#grid");
  grid.replaceChildren();
  if (!S.shown.length) {
    grid.append(el("p", { class: "note", text: "Keine Videos für diese Auswahl." }));
    return;
  }
  const frag = document.createDocumentFragment();
  S.shown.forEach((v, i) => {
    const thumb = el("span", { class: "thumb" },
      el("img", { src: videoUrl(v, "poster.webp"), alt: "", loading: "lazy", decoding: "async" }),
      el("span", { class: "dur", text: fmtDuration(v.dauer) }));
    const p = S.pos[v.id];
    if (p && p[1]) thumb.append(el("span", { class: "prog" }, el("i", { style: `width:${Math.min(100, Math.round(p[0] / p[1] * 100))}%` })));
    const day = fmtDay(v.t);
    const tile = el("button", { type: "button", class: "tile", "data-i": String(i) }, thumb,
      el("span", { class: "ttl", text: v.titel }),
      el("span", { class: "meta", text: [day, v.ort, v.personen.join(", ")].filter(Boolean).join(" · ") }));
    tile.addEventListener("click", () => { S.keys = false; S.cur = i; play(v); });
    frag.append(tile);
  });
  grid.append(frag);
}

function updateProgress(v) {         // Fortschrittsbalken einer Kachel nach dem Ansehen
  const i = S.shown.indexOf(v);
  const tile = $("#grid").children[i];
  if (!tile || !tile.classList.contains("tile")) return;
  const thumb = tile.querySelector(".thumb");
  const old = thumb.querySelector(".prog");
  if (old) old.remove();
  const p = S.pos[v.id];
  if (p && p[1]) thumb.append(el("span", { class: "prog" }, el("i", { style: `width:${Math.min(100, Math.round(p[0] / p[1] * 100))}%` })));
}

function chooseChip(kind, i) {
  const opts = kind === "y" ? S.years : S.persons;
  const o = opts[Math.max(0, Math.min(opts.length - 1, i))];
  const was = kind === "y" ? S.year : S.person;
  const next = o.value === was ? "" : o.value;               // dasselbe noch einmal = zuruecksetzen
  if (kind === "y") S.year = next; else S.person = next;
  applyFilter();
  focusChip(kind, kind === "y" ? S.yi : S.pi);
}

/* ---------------------------------------------------------------- Fokus */

function barHeight() { return $("#bar").offsetHeight; }

function focusTile(i) {
  const n = S.shown.length;
  if (!n) return;
  i = Math.max(0, Math.min(n - 1, i));
  S.cur = i;
  const tile = $("#grid").children[i];
  if (!tile) return;
  tile.focus({ preventScroll: true });
  if (i < COLS) window.scrollTo(0, 0);
  else {
    const r = tile.getBoundingClientRect();
    if (r.top < barHeight() + 8 || r.bottom > window.innerHeight - 8) tile.scrollIntoView({ block: "center" });
  }
}

function focusChip(kind, i) {
  const row = $(kind === "y" ? "#years" : "#persons");
  const chip = row.children[Math.max(0, Math.min(row.children.length - 1, i))];
  if (!chip) return;
  chip.focus({ preventScroll: true });
  chip.scrollIntoView({ inline: "center", block: "nearest" });
  window.scrollTo(0, 0);
}

const zone = () => {
  const a = document.activeElement;
  if (a && a.classList && a.classList.contains("chip")) return a.dataset.kind;
  return "g";
};

/* ---------------------------------------------------------------- Player */

const video = () => $("#video");
let osdTimer = 0, saveTimer = 0, lastSave = 0;

function osdShow(sticky) {
  const o = $("#osd");
  o.classList.remove("hide");
  clearTimeout(osdTimer);
  if (!sticky) osdTimer = setTimeout(() => { if (!video().paused) o.classList.add("hide"); }, 4000);
}

function osdUpdate() {
  const v = video(), d = v.duration || (S.player && S.player.dauer) || 0;
  $("#osdfill").style.width = d ? `${Math.min(100, (v.currentTime / d) * 100)}%` : "0";
  $("#osdtime").textContent = `${fmtDuration(v.currentTime)} / ${fmtDuration(d)}${v.paused ? "   ❚❚ Pause" : ""}`;
}

function play(v, fresh) {
  if (!v) return;
  const already = !!S.player;                   // laeuft schon ein Video (z. B. naechstes Zufallsvideo)?
  if (already) { persist(true); updateProgress(S.player); }
  S.player = v;
  const vid = video();
  $("#player").hidden = false;
  $("#vmsg").hidden = true;
  $("#osdtitle").textContent = v.titel;
  $("#osdmeta").textContent = [fmtDay(v.t), v.ort, v.personen.join(", ")].filter(Boolean).join(" · ");
  const saved = S.pos[v.id];
  vid.poster = videoUrl(v, "poster.webp");
  vid.src = videoUrl(v, "video.mp4");
  S.resume = !fresh && saved ? saved[0] : 0;
  const p = vid.play();
  if (p && p.catch) p.catch(() => { $("#vmsg").textContent = "Mit Play / 5 starten"; $("#vmsg").hidden = false; });
  if (!already) history.pushState({ p: v.id }, "");
  osdShow(false);
  clearInterval(saveTimer);
  saveTimer = setInterval(() => { osdUpdate(); persist(); }, 1000);
}

function persist(force) {
  const v = S.player;
  if (!v) return;
  const vid = video();
  if (!force && Date.now() - lastSave < 5000) return;
  lastSave = Date.now();
  savePos(v, vid.currentTime || 0, vid.duration || v.dauer);
}

function stopPlayer(fromPop) {
  const v = S.player;
  if (!v) return;
  const vid = video();
  persist(true);
  S.player = null;
  clearInterval(saveTimer);
  vid.pause();
  vid.removeAttribute("src");
  vid.removeAttribute("poster");
  vid.load();                                   // Verbindung freigeben
  $("#player").hidden = true;
  if (!fromPop && history.state && history.state.p) history.back();
  updateProgress(v);
  const i = S.shown.indexOf(v);
  if (i >= 0) S.cur = i;
  focusTile(S.cur);
}

window.addEventListener("popstate", () => { if (S.player) stopPlayer(true); });

function playerKeys(a) {
  const vid = video();
  const seek = (d) => { if (vid.duration) vid.currentTime = Math.max(0, Math.min(vid.duration - 0.5, vid.currentTime + d)); osdShow(false); osdUpdate(); };
  switch (a) {
    case "ok": case "playpause": case "play":
      if (vid.paused) { const p = vid.play(); if (p && p.catch) p.catch(() => {}); $("#vmsg").hidden = true; } else vid.pause();
      return true;                               // die Einblendung folgt den Ereignissen play/pause
    case "pause": vid.pause(); osdShow(true); osdUpdate(); return true;
    case "left": case "rew": seek(-10); return true;
    case "right": case "ff": seek(10); return true;
    case "secprev": case "pminus": seek(-60); return true;
    case "secnext": case "pplus": seek(60); return true;
    case "up": case "down": osdShow(false); osdUpdate(); return true;
    case "back": case "stop": stopPlayer(false); return true;
    case "random": randomVideo(); return true;
    case "skipnext": case "skipprev": {
      const d = a === "skipnext" ? 1 : -1;
      const at = S.shown.indexOf(S.player);
      stopPlayer(false);
      focusTile(Math.max(0, Math.min(S.shown.length - 1, (at < 0 ? S.cur : at) + d)));
      return true;
    }
  }
  return false;
}

/* ---------------------------------------------------------------- Auswahl (Raster und Filterreihen) */

function jumpYear(d) {
  const n = S.shown.length;
  if (!n) return;
  const yearOf = (i) => S.shown[i].t.slice(0, 4);
  let i = S.cur;
  const y = yearOf(i);
  if (d > 0) { while (i < n && yearOf(i) === y) i++; if (i >= n) { toast("Das ist das letzte Jahr."); return; } }
  else {
    while (i >= 0 && yearOf(i) === y) i--;
    if (i < 0) { if (S.cur === 0) { toast("Das ist das erste Jahr."); return; } i = 0; }
    else { const y2 = yearOf(i); while (i > 0 && yearOf(i - 1) === y2) i--; }
  }
  focusTile(i);
}

function pick() { return S.shown[S.cur]; }

function gridKeys(a) {
  const n = S.shown.length;
  const z = zone();
  // Farbtasten gelten in allen Zonen
  if (a === "red") { toggleOrder(); return true; }
  if (a === "green") { stepFilter("y", 1, false); return true; }          // Jahr aelter (2019 -> 2018)
  if (a === "yellow") { stepFilter("y", -1, false); return true; }        // Jahr neuer
  if (a === "blue") { stepFilter("p", 1, true); return true; }            // naechste Person, am Ende wieder „Alle“
  if (a === "random") { randomVideo(); return true; }
  if (z === "y" || z === "p") {
    const kind = z;
    const focused = Number(document.activeElement.dataset.i);
    switch (a) {
      case "left": focusChip(kind, focused - 1); return true;
      case "right": focusChip(kind, focused + 1); return true;
      case "ok": chooseChip(kind, focused); return true;
      case "down": case "ff": if (kind === "y") focusChip("p", S.pi); else focusTile(S.cur); return true;
      case "up": case "rew": if (kind === "p") focusChip("y", S.yi); return true;
      case "pplus": chooseStep(kind, kind === "y" ? -1 : 1); return true;       // Jahr: P+ = ein Jahr spaeter
      case "pminus": chooseStep(kind, kind === "y" ? 1 : -1); return true;
      case "playpause": case "play": if (pick()) play(pick()); return true;
      case "skipnext": focusTile(S.cur + 1); return true;
      case "skipprev": focusTile(S.cur - 1); return true;
      case "back": case "stop": focusTile(S.cur); return true;
    }
    return false;
  }
  switch (a) {
    case "left": focusTile(S.cur - 1); return true;
    case "right": focusTile(S.cur + 1); return true;
    case "down": case "ff": if (S.cur + COLS < n) focusTile(S.cur + COLS); else if (S.cur < n - 1 && Math.floor(S.cur / COLS) < Math.floor((n - 1) / COLS)) focusTile(n - 1); return true;
    case "up": case "rew": if (S.cur >= COLS) focusTile(S.cur - COLS); else focusChip("p", S.pi); return true;
    case "skipnext": focusTile(S.cur + 1); return true;
    case "skipprev": focusTile(S.cur - 1); return true;
    case "ok": case "playpause": case "play": if (pick()) play(pick()); return true;
    case "pplus": focusTile(S.cur + COLS * 3); return true;                        // eine Seite weiter
    case "pminus": focusTile(S.cur - COLS * 3); return true;
    case "secprev": jumpYear(S.desc ? 1 : -1); return true;
    case "secnext": jumpYear(S.desc ? -1 : 1); return true;
    case "back": focusChip("y", S.yi); return true;                                 // 0 = in die Filter
    case "stop": return false;
  }
  return false;
}

function chooseStep(kind, d) {                 // naechster/voriger Eintrag in der Reihe (ohne Zuruecksetzen)
  const opts = kind === "y" ? S.years : S.persons;
  const cur = kind === "y" ? S.yi : S.pi;
  const next = Math.max(0, Math.min(opts.length - 1, cur + d));
  if (next === cur) return;
  if (kind === "y") S.year = opts[next].value; else S.person = opts[next].value;
  applyFilter();
  focusChip(kind, kind === "y" ? S.yi : S.pi);
}

function stepFilter(kind, d, wrap) {             // Farbtasten: Filter schrittweise aendern, ohne den Fokus zu verlieren
  const opts = kind === "y" ? S.years : S.persons;
  const cur = kind === "y" ? S.yi : S.pi;
  let next = cur + d;
  if (wrap) next = (next + opts.length) % opts.length;
  else if (next < 0 || next >= opts.length) {
    toast(d > 0 ? "Das ist das älteste Jahr." : "Das ist schon „Alle“ Jahre.");
    return;
  }
  const was = zone();
  if (kind === "y") S.year = opts[next].value; else S.person = opts[next].value;
  applyFilter();
  toast(`${kind === "y" ? "Jahr" : "Person"}: ${opts[next].label}`);
  if (was === "y" || was === "p") focusChip(was, was === "y" ? S.yi : S.pi);
  else focusTile(0);
}

function toggleOrder() {
  S.desc = !S.desc;
  writePref(ORDER_KEY, S.desc ? "desc" : "asc");
  const keep = pick() && pick().id;
  applyFilter(keep);
  focusTile(S.cur);
  toast(S.desc ? "Neueste zuerst" : "Älteste zuerst");
}

function randomVideo() {                         // zufaelliges Video der aktuellen Auswahl, sofort abspielen
  const pool = S.shown.filter((v) => v !== S.player);
  if (!pool.length) { toast("Keine weiteren Videos in dieser Auswahl."); return; }
  const v = pool[Math.floor(Math.random() * pool.length)];
  S.cur = S.shown.indexOf(v);
  play(v, true);
}

/* ---------------------------------------------------------------- Hilfe, Meldungen */

function helpHtml() {
  const rows = S.player ? [
    ["5 / Play", "Pause und weiter"], ["Stop / 0", "Zurück zur Auswahl"],
    ["Skip ◀◀ ▶▶", "Zurück zur Auswahl, Fokus auf dem vorigen / nächsten Video"],
    ["◀◀ / ▶▶  (4 / 6)", "10 Sekunden zurück / vor"], ["P− / P+  (7 / 9)", "1 Minute zurück / vor"],
    ["3", "Nächstes Zufallsvideo (aus der gewählten Auswahl)"],
    ["Info / 1", "Diese Hilfe an / aus"],
  ] : [
    ["2 4 6 8", "Auswahl bewegen (auch Pfeiltasten)"], ["5 / Play", "Ausgewähltes Video abspielen"],
    ["◀◀ / ▶▶", "Eine Zeile hoch / runter"], ["Skip ◀◀ ▶▶", "Voriges / nächstes Video"],
    ["P+ / P−", "Eine Seite weiter / zurück (in der Jahr-Reihe: Jahr ändern)"],
    ["7 / 9", "Vorheriges / nächstes Jahr in der Liste"],
    ["0", "In die Filter (Jahr-Reihe) springen"],
    ["In den Filtern", "4 / 6 wählen, 5 an / aus (nochmal 5 = zurücksetzen), 8 / 2 wechseln die Reihe, 0 zurück zu den Videos"],
    ["Grün", "Jahr älter (2019 → 2018)"], ["Gelb", "Jahr neuer (2018 → 2019)"],
    ["Blau", "Nächste Person (der Reihe nach, am Ende wieder „Alle“)"],
    ["Rot", "Reihenfolge neueste / älteste zuerst"],
    ["3", "Zufallsvideo aus der gewählten Auswahl sofort abspielen – nochmal 3: das nächste"],
    ["Info / 1", "Diese Hilfe an / aus"],
  ];
  const dl = el("dl", {});
  for (const [k, t] of rows) dl.append(el("dt", { text: k }), el("dd", { text: t }));
  return [el("h2", { text: S.player ? "Hilfe – Video" : "Hilfe – Auswahl" }), dl,
    el("p", { class: "hint", text: "Fotoschatz Videos · Version " + TV_VERSION + " · Info, 1 oder 0 schließt die Hilfe" })];
}

function toggleHelp(on) {
  S.help = on === undefined ? !S.help : on;
  const h = $("#help");
  h.hidden = !S.help;
  if (S.help) h.replaceChildren(...helpHtml());
}

let toastTimer = 0;
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}

/* ---------------------------------------------------------------- Tasten */

function actionOf(e) {
  const k = e.key, c = e.keyCode;
  if (k === "Info" || k === "1" || k === "F1" || k === "ContextMenu" || c === 457 || c === 165) return "info";
  if (k === "ArrowUp" || k === "2") return "up";
  if (k === "ArrowDown" || k === "8") return "down";
  if (k === "ArrowLeft" || k === "4") return "left";
  if (k === "ArrowRight" || k === "6") return "right";
  if (k === "Enter" || k === "5") return "ok";
  if (k === "0" || k === "Escape" || k === "Backspace") return "back";
  if (k === "MediaStop" || c === 178 || c === 413) return "stop";
  if (k === "7") return "secprev";
  if (k === "9") return "secnext";
  if (k === "ChannelUp" || k === "PageDown" || c === 427) return "pplus";
  if (k === "ChannelDown" || k === "PageUp" || c === 428) return "pminus";
  if (k === "MediaTrackNext") return "skipnext";
  if (k === "MediaTrackPrevious") return "skipprev";
  if (k === "MediaPlayPause" || c === 179 || k === " ") return "playpause";
  if (k === "MediaPlay" || c === 415) return "play";
  if (k === "MediaPause" || c === 19) return "pause";
  if (k === "MediaFastForward" || c === 417) return "ff";
  if (k === "MediaRewind" || c === 412) return "rew";
  if (k === "3") return "random";
  if (k === "ColorF0Red" || c === 403) return "red";
  if (k === "ColorF1Green" || c === 404) return "green";
  if (k === "ColorF2Yellow" || c === 405) return "yellow";
  if (k === "ColorF3Blue" || c === 406) return "blue";
  return null;
}

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  $("#lastkey").textContent = `Letzte Taste: ${e.key} · ${e.keyCode}`;
  const a = actionOf(e);
  if (!a) return;
  S.keys = true;
  document.body.classList.add("keys");
  e.preventDefault();
  if (a === "info") { toggleHelp(); return; }
  if (S.help) { if (a === "back" || a === "stop") toggleHelp(false); return; }
  if (S.player) { playerKeys(a); return; }
  if (!S.list.length) return;
  if (!document.activeElement || document.activeElement === document.body) { focusTile(S.cur); if (["left", "right", "up", "down"].includes(a)) return; }
  gridKeys(a);
});
document.addEventListener("pointerdown", () => document.body.classList.remove("keys"), true);

/* ---------------------------------------------------------------- Start */

async function start() {
  $("#ver").textContent = `Version ${TV_VERSION}`;
  const link = takeLink();
  const key = link.split("-")[1];
  if (!link || !key) {
    $("#grid").replaceChildren(el("p", { class: "note", text: "Bitte den Link verwenden, den du bekommen hast." }));
    return;
  }
  S.base = `${R2_PUBLIC_URL}/${link.split("-")[0]}`;
  S.desc = readPref(ORDER_KEY) !== "asc";
  loadPos();
  let data;
  try {
    const res = await fetch(`${S.base}/videos/index-${key}.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch (err) {
    $("#grid").replaceChildren(el("p", { class: "note", text: "Die Videos konnten nicht geladen werden. Bitte später noch einmal versuchen." }));
    return;
  }
  S.list = cleanVideos(data);
  if (!S.list.length) {
    $("#grid").replaceChildren(el("p", { class: "note", text: "Noch keine Videos online." }));
    return;
  }
  buildOptions();
  applyFilter();
  document.documentElement.style.setProperty("--bar", `${barHeight() + 8}px`);
  window.addEventListener("resize", () => document.documentElement.style.setProperty("--bar", `${barHeight() + 8}px`));
  const vid = video();
  vid.addEventListener("ended", () => { savePos(S.player, 0, 0); stopPlayer(false); });
  vid.addEventListener("loadedmetadata", () => {
    if (S.resume > 0 && S.resume < (vid.duration || 1e9) - 5) vid.currentTime = S.resume;
    S.resume = 0;
  });
  vid.addEventListener("play", () => { osdShow(false); osdUpdate(); });
  vid.addEventListener("pause", () => { osdShow(true); osdUpdate(); });
  vid.addEventListener("error", () => {
    if (!S.player) return;
    $("#vmsg").textContent = "Dieses Video lässt sich nicht abspielen.";
    $("#vmsg").hidden = false;
  });
  vid.addEventListener("playing", () => { $("#vmsg").hidden = true; });
}

start();
