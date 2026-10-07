"use strict";

// Fotoschatz Service Worker. Version folgt VERSION / APP_VERSION.
const VERSION = "0.7.1";
const APP_CACHE = `fotoschatz-app-${VERSION}`;
const THUMB_CACHE = "fotoschatz-thumb";
const IMG_CACHE = "fotoschatz-img";
const DATA_CACHE = "fotoschatz-data";
const THUMB_LIMIT = 10000;   // ca. 160 MB
const IMG_LIMIT = 300;       // ca. 200 MB
const APP_FILES = [
  "./",
  `styles.css?v=${VERSION}`,
  `orte.js?v=${VERSION}`,
  `app.js?v=${VERSION}`,
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/favicon-32.png",
];
// Pfade in R2: /<Praefix>/thumb/…, /<Praefix>/img/…, /<Praefix>/index.json
const R2_FILE = /^\/[A-Za-z0-9]{32,}\/(thumb|img)\/[^/]+$/;
const R2_INDEX = /^\/[A-Za-z0-9]{32,}\/index\.json$/;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(APP_CACHE).then((cache) => cache.addAll(APP_FILES)));
});

self.addEventListener("activate", (event) => {
  // Nur eigene alte App-Caches loeschen (obitusde.github.io hostet auch andere Apps)
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("fotoschatz-app-") && name !== APP_CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (!url.pathname.startsWith(new URL(self.registration.scope).pathname)) return;
    // Manifest nie aus dem Cache: Chrome liest daraus beim Installieren die Anzeige (Vollbild)
    if (url.pathname.endsWith("/manifest.webmanifest")) {
      event.respondWith(fetch(request.url, { cache: "no-cache" }));
      return;
    }
    event.respondWith(appFile(request));
    return;
  }
  const file = url.pathname.match(R2_FILE);
  if (file) {
    event.respondWith(file[1] === "thumb"
      ? cacheFirst(THUMB_CACHE, request, THUMB_LIMIT, 200)
      : cacheFirst(IMG_CACHE, request, IMG_LIMIT, 20));
  } else if (R2_INDEX.test(url.pathname)) {
    event.respondWith(networkFirst(request));
  }
});

// App-Dateien: aus dem Cache der aktuellen Version, sonst Netz (z. B. test-r2.html)
async function appFile(request) {
  const cache = await caches.open(APP_CACHE);
  const scope = new URL(self.registration.scope).pathname;
  const path = new URL(request.url).pathname;
  const shell = request.mode === "navigate" && (path === scope || path === `${scope}index.html`);
  const hit = shell ? await cache.match("./") : await cache.match(request);
  return hit || fetch(request);
}

// Bilder sind unveraenderlich (Hash im Namen): einmal geladen, immer aus dem Cache.
// Geladen wird mit CORS, damit der Cache keine undurchsichtigen Antworten speichert.
const putCounter = {};
async function cacheFirst(name, request, limit, trimEvery) {
  const cache = await caches.open(name);
  const hit = await cache.match(request.url);
  if (hit) return hit;
  let response;
  try {
    response = await fetch(request.url, { mode: "cors", credentials: "omit", cache: "reload" });
  } catch (e) {
    return fetch(request);
  }
  if (response.ok) {
    const copy = response.clone();
    cache.put(request.url, copy).then(() => {
      putCounter[name] = (putCounter[name] || 0) + 1;
      if (putCounter[name] % trimEvery === 0) trim(cache, limit);
    }).catch(() => {});
  }
  return response;
}

async function trim(cache, limit) {
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(key);
}

// index.json: immer frisch aus dem Netz, ohne Netz die zuletzt geladene Fassung
async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request.url, response.clone());
    return response;
  } catch (e) {
    const hit = await cache.match(request.url);
    if (hit) return hit;
    throw e;
  }
}
