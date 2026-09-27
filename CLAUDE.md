# Fotoschatz – Projektgrundlage für Claude Code

**Dokumentversion:** v1.1 · 27.09.2026
**Repo:** `obitusde/fotoschatz` · **Pages:** `https://obitusde.github.io/fotoschatz/`
**Projekt:** Fotoschatz – private Online-Fotogalerie für ca. 10.000 Lightroom-Bilder – Eigenbau mit Cloudflare R2 + installierbarer PWA (GitHub Pages)

---

## 0. Arbeitsweise (bitte strikt einhalten)

- **Sprache:** Kommunikation auf Deutsch.
- **Erst Architektur, dann Code:** Vor jeder Umsetzung Ansatz kurz vorstellen und besprechen. Code wird erst geschrieben/geändert, wenn ich nach der Besprechung ausdrücklich freigebe.
- **High-Level zuerst:** Antworten erst knapp auf hoher Ebene, Details nur auf Nachfrage.
- **Diagnose zuerst:** Vor Produktivcode kleine Test-/Diagnosefunktionen, die Annahmen an echten Daten prüfen (z. B. welche Metadaten wirklich im JPG stehen).
- **Vollständige Dateien:** Bei Änderungen immer die komplette Datei liefern, keine Patches/Diffs.
- **Versionsnummern:** Jede Änderung bekommt eine neue Versionsnummer (App: `APP_VERSION` in `app.js`, sichtbar in der UI und im Service-Worker-Cache-Namen; Sync-Tool: `__version__`, wird beim Start ausgegeben).
- **Ehrliche Unsicherheit:** Wenn etwas unklar oder ungetestet ist, das sagen statt raten. Punkte mit „⚠ verifizieren" in diesem Dokument sind Annahmen, die in Phase 0 geprüft werden müssen.
- **Keine Diffs:** Ich lese keine Diffs. Änderungen immer in einfachen Worten zusammenfassen.

## 0a. Deploy & Versionen (Cloud-Workflow)

- Gearbeitet wird in Claude-Code-Cloud-Sitzungen (Handy und PC). `git push` geht dort nur auf den eigenen Arbeits-Branch. Änderungen sollen trotzdem **ohne mein Zutun live gehen** (kein Merge, kein Review durch mich).
- **Workflow `release`:** Bei Push auf einen Claude-Arbeits-Branch diesen automatisch nach `main` übernehmen (fast-forward, sonst Merge-Commit; bei Konflikt abbrechen und fehlschlagen). Danach den Deploy auslösen. Achtung: Pushes mit `GITHUB_TOKEN` starten keine weiteren Workflows → Deploy per `workflow_dispatch` anstoßen oder im selben Lauf ausführen. ⚠ Das Branch-Namensmuster der Cloud-Sitzungen beim ersten Lauf prüfen.
- **Workflow `deploy`:** bei Push auf `main` und per `workflow_dispatch`.
  - GitHub Pages: Ordner `docs/` veröffentlichen (Pages-Source = „GitHub Actions").
  - Dieses Projekt hat **kein** Apps Script → kein clasp-Schritt.
  - Git-Tag `v<VERSION>` setzen.
  - `concurrency`: immer nur ein Deploy gleichzeitig.
- **Datei `VERSION`** im Repo-Root (x.y.z). **Jede** Änderung erhöht die Version. `APP_VERSION` in `docs/app.js` und der Service-Worker-Cache-Name folgen dieser Version; sie ist in der App sichtbar. Das Sync-Tool hat eine eigene `__version__`; auch Änderungen daran erhöhen `VERSION`.
- **Nach jedem Push:** Status der Workflows prüfen und melden: „live in Version x.y.z" oder den Fehler in einfachen Worten.
- **Zurückgehen:** alten Stand (Tag) als **neue** Version wiederherstellen. Niemals Historie umschreiben, kein force-push auf `main`.
- **Niemals Geheimnisse ins Repo** (es ist öffentlich): kein R2-Präfix, keine R2-Zugangsdaten, keine `config.local.json`.
- **Repo-Aufbau:** `docs/` = PWA (GitHub Pages) · `sync/` = lokales Sync-Tool (läuft nur auf meinem PC) · `.github/workflows/` = release + deploy · `VERSION` · `CLAUDE.md`.
- Das Sync-Tool kann in der Cloud geschrieben werden, ausgeführt und mit echten Exporten getestet wird es aber auf meinem Windows-PC. Dafür klar sagen, was ich am PC ausführen soll.

---

## 1. Ziel & Rahmen

- Meine ca. 10.000 Lightroom-Bilder online ansehen und **durchsuchen** – auch unterwegs auf dem Handy.
- Die Familie kann die Bilder ohne Konto per Link ansehen.
- Die in Lightroom gepflegten Stichwörter (inkl. Personen und Orte) sollen nutzbar sein.
- Alte Bilder neu entdecken (Rückblick „Heute vor X Jahren") – **zunächst nur in der App**, keine Push-Benachrichtigungen.
- Vorgehen: **zuerst MVP**, danach schrittweise weitere Funktionen.
- **Zielplattform:** Android + Chrome, als installierbare PWA. Kein iPhone nötig.
- Kosten bei Cloudflare sind kein Problem (voraussichtlich ohnehin im Gratis-Bereich).

---

## 2. Ausgangslage

### Lightroom Classic
- Katalog mit ca. 10.000 Bildern, gut gepflegt: Stichwörter, Personen, Orte, GPS.
- Oberfläche von Lightroom ist **deutsch**.

### Ordnerstruktur der Originale (Festplatte)
```
2026/
  _Import/                          ← unsortiert, wird NICHT exportiert / NICHT online
  2026-02-20 Paris Wochenende allein/
  2026-04-03 Comer See/
  2026-04-11 Savona/
  2026-07-22 Japan mit Familie/
2025/
  ...
```
- Ebene 1: Jahr. Ebene 2: Ereignisordner `YYYY-MM-DD Name`.
- **Keine weiteren Unterordner** in den Ereignisordnern.

### Export
- Alle JPGs landen in **einem flachen Export-Ordner** auf dem PC.
- Der Ereignisordner wird über die Dateinamenvorlage in den Dateinamen geschrieben (siehe Abschnitt 5).
- Workflow: Ein Ereignisordner ist fertig bearbeitet → exportieren → Sync starten.
- Neu bearbeitete alte Bilder werden neu exportiert und **überschreiben** die alte Datei → der Sync ersetzt sie online.

### Rechner
- Windows-Laptop. Das Sync-Tool läuft lokal (nicht in Apps Script, da Apps Script nicht auf lokale Dateien zugreifen kann).

---

## 3. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Hosting Bilder | Cloudflare R2, öffentlich lesbar, alles unter einem geheimen Pfad-Präfix |
| Hosting App | GitHub Pages, Repo `obitusde/fotoschatz`, Ordner `docs/`, statische PWA, kein Backend |
| Bildgröße | 1600 px lange Kante, JPEG-Qualität 70 |
| Vorschaubilder | vom Sync-Tool erzeugt (WebP, ca. 400 px) |
| Upload | rclone (sync), gesteuert durch Python-Skript, Start per `sync.bat` |
| Zugriffsschutz | öffentlich, aber mit langem geheimem Link (Geheimnis im URL-Hash) |
| GPS | bleibt in den Bildern (für Karte/Umkreissuche) |
| `_Import` | wird nicht exportiert und nicht online gestellt |
| Online-Struktur | wie auf der Platte: Jahr → Ereignisordner, plus „Alle Bilder" |
| Benachrichtigungen | keine Push-Nachrichten, keine E-Mails – Rückblick nur in der App |
| Plattform | Android/Chrome, installierbare PWA |

---

## 4. Architektur

```
PC (Windows)                              Cloud
────────────────────────────              ───────────────────────────────────
Lightroom Classic                         Cloudflare R2 (Bucket, public read)
  │ Export-Preset (1600px, Q70)             /<SECRET>/
  ▼                                           ├─ img/    <id>.<hash>.jpg
Export-Ordner (flach)                         ├─ thumb/  <id>.<hash>.webp
  │                                           └─ index.json
  ▼                                                ▲
sync-Tool (Python)                                 │
  1. Export-Ordner scannen                         │
  2. Neue/geänderte Dateien erkennen               │
  3. Metadaten lesen (exiftool)                    │
  4. Staging-Ordner befüllen (img + thumb)         │
  5. index.json bauen                              │
  6. rclone sync Staging → R2  ────────────────────┘
                                                   │ lädt (fetch)
                                     GitHub Pages: Foto-PWA
                                     https://obitusde.github.io/fotoschatz/#<SECRET>
```

**Grundprinzip:** Kein Server, keine Datenbank online. Die App lädt `index.json` und macht Suche, Filter, Ordner, Karte und Rückblick komplett im Browser.

---

## 5. Lightroom-Export-Preset

⚠ Die Bezeichnungen sind sinngemäß – in Phase 0 am echten deutschen Export-Dialog verifizieren und hier korrigieren.

| Bereich | Einstellung |
|---|---|
| Exportieren auf | Festplatte |
| Speicherort | fester Ordner, z. B. `D:\Fotos_Online_Export` (ohne Unterordner) |
| Vorhandene Dateien | **ohne Warnung überschreiben** (nötig fürs Ersetzen) |
| Dateibenennung | benutzerdefinierte Vorlage: `{Ordnername}_{Dateiname}` → z. B. `2026-07-22 Japan mit Familie_DSC1234.jpg` |
| Dateiformat | JPEG, Qualität 70, Farbraum sRGB |
| Bildgröße | lange Kante 1600 px, nicht vergrößern |
| Metadaten | alle (bzw. alle außer Kamera-Raw-Infos) |
| Personeninfo entfernen | **nein** (sonst fehlen die Personennamen) |
| Standortinfo entfernen | **nein** (GPS bleibt drin) |
| Stichwörter als Lightroom-Hierarchie schreiben | ja (prüfen, was es in Phase 0 bringt) |
| Wasserzeichen | nein |

**Hinweise:**
- Stichwörter mit der Option „nicht beim Export einbeziehen" landen nicht im JPG.
- Virtuelle Kopien haben denselben Original-Dateinamen → Namenskonflikt. Entweder nicht exportieren oder einen zusätzlichen Token (Kopiename) in die Vorlage aufnehmen. In Phase 0 klären.
- Konvention: Ereignisordner-Namen enthalten **keinen Unterstrich** `_` (Trennzeichen zum Original-Dateinamen). Das Sync-Tool warnt bei Verstößen.

---

## 6. Cloudflare R2 – Einrichtung

1. Cloudflare-Konto, R2 aktivieren (⚠ Zahlungsmethode ist vermutlich auch im Gratis-Tarif nötig).
2. Bucket anlegen, z. B. `fotoschatz`.
3. **Öffentlichen Zugriff** aktivieren:
   - Option A: `r2.dev`-Subdomain (schnell zum Start). ⚠ Laut Cloudflare für Entwicklung gedacht und in der Rate begrenzt – verifizieren.
   - Option B: eigene Domain über Cloudflare (für Dauerbetrieb empfohlen). → Offene Entscheidung.
4. **CORS** am Bucket: `GET`, `HEAD` für Origin `https://obitusde.github.io` erlauben.
5. **API-Token** für R2: nur dieser Bucket, Rechte „Object Read & Write". Zugangsdaten liegen nur lokal in der rclone-Konfiguration, **nie im Repo**.
6. rclone-Remote konfigurieren: Provider Cloudflare, Endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
7. **Geheimes Präfix** erzeugen: zufällige Zeichenkette, mind. 32 Zeichen, nur `[A-Za-z0-9]`.
8. ⚠ Verifizieren: Der öffentliche Bucket erlaubt **kein Auflisten** der Inhalte (sonst wäre das Präfix wertlos).

**Kosten/Mengen (grob):** Bilder mit 1600 px/Q70 ≈ 300–500 KB → 3–5 GB. Vorschaubilder ≈ 20 KB → ca. 0,2 GB. Das liegt voraussichtlich im Gratis-Bereich (10 GB Speicher, Downloads kostenlos).

---

## 7. Sync-Tool (Python, lokal)

### Voraussetzungen
- Python 3.x mit Pillow (inkl. WebP-Unterstützung)
- `exiftool.exe` im PATH
- `rclone.exe` im PATH, Remote konfiguriert
- Start per Doppelklick: `sync.bat` (ruft das Python-Skript auf, lässt das Fenster am Ende offen)

### Konfiguration `sync/config.local.json` (per `.gitignore` ausgeschlossen)
```json
{
  "export_dir": "D:\\Fotos_Online_Export",
  "work_dir": "D:\\Fotos_Online_Sync",
  "rclone_remote": "r2:fotoschatz",
  "secret_prefix": "<SECRET>",
  "thumb_long_edge": 400,
  "thumb_quality": 70,
  "max_delete": 100
}
```
- `work_dir` enthält: `staging/` (img, thumb, index.json) und `state.json` (Zustand je Datei).

### Ablauf pro Lauf
1. **Scannen:** alle `*.jpg` im Export-Ordner.
2. **Dateinamen parsen:** Regex `^(\d{4}-\d{2}-\d{2}) (.+?)_(.+)\.jpg$` → Ordnerdatum, Ordnername, Original-Dateiname.
   - Das Jahr wird aus dem Ordnerdatum abgeleitet.
   - Passt der Name nicht zum Muster → Warnung, Datei wird übersprungen.
   - Dateien aus Ordnern, die mit `_` beginnen (z. B. `_Import`), werden als Schutz übersprungen.
3. **Änderungen erkennen:** über `state.json` (Größe, Änderungszeit, SHA-1 des Inhalts).
   - neu → verarbeiten
   - Inhalt geändert → neu verarbeiten (**ersetzt** online)
   - unverändert → nichts tun
   - lokal verschwunden → aus Staging entfernen (wird online gelöscht)
4. **IDs & Dateinamen online:**
   - `id` = stabil aus dem Export-Dateinamen abgeleitet (z. B. die ersten 12 Hex-Zeichen von SHA-1(Dateiname)). Das ist URL-sicher, auch bei Leerzeichen und Umlauten.
   - `hash` = die ersten 8 Hex-Zeichen von SHA-1(Inhalt).
   - Online-Dateien: `img/<id>.<hash>.jpg`, `thumb/<id>.<hash>.webp`.
   - Vorteil: Ein ersetztes Bild bekommt einen neuen Dateinamen. Dadurch gibt es keine veralteten Caches, und alle Bilddateien sind unveränderlich (`immutable`) und dürfen lange gecacht werden.
5. **Metadaten lesen:** exiftool im Batch nur für neue/geänderte Dateien (`-json -n` für numerische GPS-Werte). Ergebnisse in `state.json` zwischenspeichern.
6. **Vorschaubild erzeugen:** Pillow, Orientierung beachten, lange Kante 400 px, WebP Q70, ohne Metadaten.
7. **Großes Bild:** unverändert ins Staging kopieren (behält EXIF inkl. GPS).
8. **`index.json` komplett neu bauen** aus `state.json` (schnell, da gecacht).
9. **Sicherheitsprüfungen vor dem Upload:**
   - Export-Ordner leer oder nicht gefunden → **Abbruch**.
   - Mehr als `max_delete` Löschungen → **Abbruch** mit Hinweis (Schutz vor versehentlichem Leeren des Buckets).
   - Option `--dry-run`: zeigt nur an, was passieren würde.
10. **Upload per rclone:** `rclone sync <staging> <remote>/<secret_prefix>/ ...`
    - `img/` und `thumb/`: Header `Cache-Control: public, max-age=31536000, immutable`
    - `index.json`: Header `Cache-Control: no-cache`
    - Mehrere parallele Übertragungen für die Erstbefüllung.
11. **Zusammenfassung ausgeben:** neu / ersetzt / gelöscht / unverändert / Warnungen (Namensmuster, fehlendes Datum, fehlendes GPS) / Laufzeit / Tool-Version.

### Zu lesende Metadatenfelder (⚠ Zuordnung in Phase 0 an echten Exporten festlegen)

| Zweck | Kandidaten (exiftool) |
|---|---|
| Stichwörter | `XMP:Subject`, `IPTC:Keywords` |
| Hierarchie | `XMP-lr:HierarchicalSubject` |
| Personen | `XMP-iptcExt:PersonInImage`, Gesichtsregionen `XMP-mwg-rs:RegionName`, oder Hierarchie-Wurzel wie `Personen|…` |
| Aufnahmedatum | `DateTimeOriginal` (Ersatz: Ordnerdatum) |
| GPS | `GPSLatitude`, `GPSLongitude` |
| Bewertung | `XMP:Rating` |
| Titel / Beschreibung | `XMP:Title`, `XMP:Description` / `IPTC:Caption-Abstract` |
| Ort | `XMP:City`, `XMP:Country`, Sublocation |
| Maße | `ImageWidth`, `ImageHeight` |

### `index.json` – Schema (Entwurf, kurze Schlüssel wegen Größe)
```json
{
  "v": 1,
  "generated": "2026-09-27T20:15:00Z",
  "count": 10000,
  "folders": [
    { "n": "2026-07-22 Japan mit Familie", "d": "2026-07-22", "c": 1396, "cover": "<id>" }
  ],
  "photos": [
    {
      "id": "a1b2c3d4e5f6",
      "h": "9f8e7d6c",
      "f": "2026-07-22 Japan mit Familie",
      "t": "2026-07-23T10:42:11",
      "w": 1600, "ht": 1067,
      "kw": ["Tokyo", "Tempel"],
      "p": ["Person A", "Person B"],
      "hk": ["Orte|Japan|Tokyo"],
      "ti": "", "de": "",
      "ci": "Tokyo", "co": "Japan",
      "la": 35.7148, "lo": 139.7967,
      "r": 4
    }
  ]
}
```
- URLs werden in der App aus `SECRET`, `id` und `h` zusammengesetzt, nicht im Index gespeichert.
- Leere Felder weglassen.
- Größe beim ersten vollen Lauf messen (Erwartung: wenige MB). Falls zu groß: gzip vorkomprimieren + `Content-Encoding`-Header, oder den Index nach Jahren aufteilen.

---

## 8. PWA (GitHub Pages)

### Technik
- Statisch, **kein Build-Schritt**: `index.html`, `app.js`, `styles.css`, `sw.js`, `manifest.webmanifest`, `icons/`.
- Vanilla JavaScript. Externe Bibliotheken (z. B. Leaflet für die Karte) nur mit **fest angegebener Version** über cdnjs, niemals „latest".
- `<meta name="robots" content="noindex, nofollow">`, kein Tracking/Analytics.
- Hell/Dunkel-Modus. Da es eine Foto-App ist, eher dunkles Standard-Design.

### Geheimnis-Handling
- Link-Format: `https://obitusde.github.io/fotoschatz/#<SECRET>` (der Teil nach `#` wird nie an einen Server gesendet und steht nicht im Repo).
- Beim ersten Öffnen: Geheimnis aus dem Hash lesen, in `localStorage` unter einem eindeutigen Schlüssel speichern (z. B. `fotoschatz.secret`, da `obitusde.github.io` auch andere PWAs hostet), dann den Hash aus der URL entfernen.
- Beim späteren Start (z. B. über das installierte App-Symbol): Geheimnis aus `localStorage` lesen.
- Kein Geheimnis vorhanden → neutrale Seite „Bitte den Link verwenden, den du bekommen hast". Keine Hinweise auf den Bucket.
- ⚠ Verifizieren: Die installierte PWA (Chrome Android) teilt `localStorage` mit dem Browser-Tab, in dem der Link geöffnet wurde.
- Deep-Links (Phase 3): `#<SECRET>/f/<ordner>` öffnet direkt einen Ordner.

### Installierbarkeit (Android/Chrome)
- `manifest.webmanifest`: `name`, `short_name`, `start_url: "./"`, `scope: "./"`, `display: "standalone"`, Theme-/Hintergrundfarbe, Icons 192 und 512 (+ maskable).
- Service Worker registriert → Chrome bietet „App installieren" an.

### MVP-Ansichten
1. **Ordner** (Startansicht):
   - Jahre absteigend, darunter die Ereignisordner mit Titelbild, Name (ohne Datumspräfix, Datum separat) und Anzahl.
   - Titelbild = bestbewertetes Bild des Ordners, sonst das erste.
2. **Alle Bilder:** Zeitleiste, neueste zuerst, gruppiert nach Monat mit mitlaufender Überschrift.
3. **Ordnerinhalt:** Raster nach Aufnahmezeit sortiert.
4. **Suche:**
   - Eingabefeld mit Vorschlägen aus Stichwörtern, Personen, Orten und Ordnernamen.
   - Gewählte Begriffe werden zu Chips und mit **UND** verknüpft (z. B. Person + Land + Jahr).
   - Zusätzlich Freitext über Titel, Beschreibung, Stadt und Ordnername.
   - Groß-/Kleinschreibung und Akzente ignorieren (Unicode-Normalisierung, diakritische Zeichen entfernen).
   - Ergebnis als Raster.
5. **Vollbild-Betrachter:**
   - Wischen links/rechts, Nachbarbilder vorladen.
   - Info-Leiste: Datum, Ordner, Personen, Stichwörter, Ort.
   - Zurück-Taste schließt den Betrachter (History-API).
   - Zoomen mit zwei Fingern: nice-to-have.

### Raster & Performance (Anforderung: flüssiges Scrollen bei 10.000 Bildern)
- **Virtuelles Scrollen:** Nur die sichtbaren Zeilen (plus Puffer) existieren im DOM.
- Quadratisches Raster (Bild mittig zugeschnitten), 3–4 Spalten auf dem Handy, feste Zeilenhöhe → einfache, sprungfreie Virtualisierung.
- Vorschaubilder mit `loading="lazy"` / `decoding="async"`, Platzhalterfarbe, bis das Bild geladen ist.
- Index einmal laden, Suchstrukturen einmal aufbauen (Stichwort → Bild-IDs).

### Service Worker – Caching
- **App-Dateien:** vorab cachen, Cache-Name enthält `APP_VERSION`.
- **Vorschaubilder:** cache-first (unveränderlich dank Hash im Namen) → beim zweiten Besuch sofort da, auch ohne Netz.
- **Große Bilder:** cache-first mit Obergrenze (z. B. die letzten ~300 Bilder, älteste werden entfernt).
- **`index.json`:** network-first, bei fehlendem Netz aus dem Cache.

---

## 9. Datenschutz & Sicherheit

- Alle Bilder sind technisch öffentlich. Schutz nur durch das nicht erratbare Präfix („Security by Obscurity") – bewusst so entschieden.
- Die großen JPGs enthalten GPS, Stichwörter und Personennamen – bewusst so, nur Familie hat den Link.
- **Nie ins Repo:** Geheimnis, R2-Zugangsdaten, `config.local.json`, `rclone.conf`.
- **Link ist in falsche Hände geraten:**
  1. Neues Präfix erzeugen.
  2. Inhalte serverseitig verschieben (`rclone move` innerhalb des Buckets) oder neu hochladen.
  3. `config.local.json` anpassen.
  4. Neuen Link an die Familie schicken. Der alte Link zeigt danach nichts mehr.
- R2 ist **kein Backup**. Die Originale und der Lightroom-Katalog brauchen weiterhin eine eigene Datensicherung.

---

## 10. Phasenplan

### Phase 0 – Diagnose (kein Produktivcode)
- 0.1 Export-Preset anlegen (Abschnitt 5), Bezeichnungen im deutschen Dialog verifizieren.
- 0.2 Ca. 20 Testbilder exportieren: mit Personen, hierarchischen Stichwörtern, GPS, Bewertung, Titel; auch Dateinamen mit Umlauten und Leerzeichen.
- 0.3 Diagnose-Skript: exiftool-Ausgabe aller Testbilder als lesbarer Bericht. Welche Felder sind gefüllt? Sind Personen getrennt von normalen Stichwörtern erkennbar? Kommt die Hierarchie mit?
- 0.4 Ergebnis: **verbindliche Feldzuordnung** in Abschnitt 7 eintragen.
- 0.5 R2: Bucket, Token, rclone, CORS, öffentliche URL einrichten; 1 Testdatei hochladen und von `obitusde.github.io` per `fetch` abrufen; prüfen, dass Auflisten nicht möglich ist.
- **Fertig, wenn:** Feldzuordnung steht und eine Testdatei aus der Test-PWA ladbar ist.

### Phase 1 – Sync-Tool
- Umsetzung nach Abschnitt 7 inkl. `--dry-run`, Sicherheitsprüfungen, Zusammenfassung.
- Test mit den 20 Testbildern: neu → hochgeladen; ein Bild neu exportiert → ersetzt; eine Datei gelöscht → online entfernt; nochmaliger Lauf → „0 Änderungen".
- **Fertig, wenn:** Alle vier Testfälle korrekt laufen und `index.json` dem Schema entspricht.

### Phase 2 – PWA-MVP
- Geheimnis-Handling, Ordner, Alle Bilder, Suche, Betrachter, Service Worker, Manifest, Installierbarkeit.
- **Fertig, wenn:** Auf dem Android-Handy installierbar; Start über das App-Symbol ohne erneuten Link funktioniert; Scrollen flüssig; Suche kombiniert Chips korrekt.

### Phase 3 – Erstbefüllung
- Alle Ordner (außer `_Import`) exportieren, voller Sync.
- Index-Größe, Upload-Dauer und Scroll-Performance mit ~10.000 Bildern prüfen.
- Danach Link an die Familie verteilen.

### Phase 4 – Erweiterungen (Reihenfolge nach Absprache)
1. **Rückblick „Heute vor X Jahren"** auf dem Startbildschirm der App:
   - Bilder mit gleichem Tag/Monat aus früheren Jahren, gruppiert nach Jahr.
   - Gibt es am Tag nichts, ±3 Tage.
   - Bevorzugt Bilder mit hoher Bewertung.
2. **„Überrasch mich":** zufällige Auswahl (bevorzugt gut bewertet) oder zufälliger Ordner.
3. **Karte:**
   - Leaflet + OpenStreetMap (Namensnennung und Nutzungsregeln der Kacheln beachten), Cluster mit Anzahl.
   - Antippen → Bilder an diesem Ort.
4. **Umkreissuche:** Punkt auf der Karte wählen + Radius (1 / 5 / 20 / 50 km) → Entfernungsberechnung im Browser → Raster. Zusätzlich „In meiner Nähe" über den Standort des Handys.
5. **Personen-Seite:** alle Personen mit Anzahl; pro Person chronologisch („durch die Jahre").
6. **Best-of-Filter** nach Bewertung (z. B. ≥ 4 Sterne), kombinierbar mit Suche/Ordner.
7. **Diashow:** Vollbild mit automatischem Weiterblättern, einstellbares Intervall, optional zufällig.
8. **Teilen:** Einzelbild über das Android-Teilen-Menü (Web Share API mit Datei), z. B. an WhatsApp.
9. **Deep-Links** auf Ordner (und ggf. einzelne Bilder).
10. **Statistik:** Bilder pro Jahr, häufigste Orte/Personen.

---

## 11. Bewusst nicht im Scope (vorerst)

- Push-Benachrichtigungen, E-Mail-Rückblicke
- Likes/Kommentare der Familie (bräuchte ein Backend)
- Videos, RAW-Dateien, Originalauflösung
- iPhone/Safari-Optimierung
- Upload oder Bearbeitung aus der App heraus
- Automatische Gesichtserkennung (Personen kommen ausschließlich aus Lightroom)

---

## 12. Offene Punkte (in Phase 0 bzw. vor Phase 2 klären)

- `r2.dev` oder eigene Domain?
- Wie sind Personen im exportierten JPG erkennbar (eigenes Feld, Hierarchie oder nur normales Stichwort)?
- Umgang mit virtuellen Kopien beim Export.
- Soll `sync.bat` zusätzlich zeitgesteuert laufen (Windows-Aufgabenplanung) oder nur per Doppelklick?

---

## 13. Wartung & Betrieb

- **Laufend:** nach dem Export `sync.bat` starten – sonst nichts.
- **Kein Server** zu aktualisieren. R2 und GitHub Pages werden von den Anbietern betrieben.
- **Neuer PC:** Python, Pillow, exiftool, rclone installieren; `config.local.json` und die rclone-Konfiguration übernehmen (vorher sicher aufbewahren!).
- **Mögliche Störungen (selten):** Cloudflare ändert Tarife oder `r2.dev`-Limits; eine externe Bibliothek ändert sich (Gegenmittel: feste Versionen).
- **App-Updates:** neue `APP_VERSION` → neuer Service-Worker-Cache. Die App zeigt „Neue Version verfügbar – neu laden".
