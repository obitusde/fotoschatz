# Fotoschatz – Projektgrundlage für Claude Code

**Dokumentversion:** v1.4 · 28.09.2026 (Sync-Tool am PC bestätigt, PWA 2a)
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
- **Ehrliche Unsicherheit:** Wenn etwas unklar oder ungetestet ist, das sagen statt raten. Punkte mit „⚠ verifizieren" in diesem Dokument sind Annahmen, die noch geprüft werden müssen.
- **Keine Diffs:** Ich lese keine Diffs. Änderungen immer in einfachen Worten zusammenfassen.
- **PowerShell-Befehle für mich:** Nie Platzhalter zum Selbst-Ersetzen. Geheime Werte liegen in `C:\Users\chris\fotoschatz-secrets.ps1` (außerhalb des Repos) und werden von Befehlen/Skripten automatisch geladen: `$env:FOTOSCHATZ_R2_PUBLIC_URL`, `$env:FOTOSCHATZ_R2_PREFIX`. Vorher `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force`.

## 0a. Deploy & Versionen (Cloud-Workflow)

- Gearbeitet wird in Claude-Code-Cloud-Sitzungen (Handy und PC). `git push` geht dort nur auf den eigenen Arbeits-Branch. Änderungen gehen trotzdem **ohne mein Zutun live** (kein Merge, kein Review durch mich).
- **Workflow `release`** (läuft, geprüft): Bei Push auf einen Branch `claude/**` (Muster der Cloud-Sitzungen: `claude/<name>`) wird dieser automatisch nach `main` übernommen (fast-forward, sonst Merge-Commit; bei Konflikt Abbruch mit Fehler). Danach stößt er `deploy` per `workflow_dispatch` auf `main` an und wartet auf dessen Ergebnis. Grund: Pushes mit `GITHUB_TOKEN` starten keine weiteren Workflows, und die Pages-Umgebung `github-pages` erlaubt Deployments nur von `main`.
- **Workflow `deploy`:** bei Push auf `main` und per `workflow_dispatch`.
  - GitHub Pages: Ordner `docs/` veröffentlichen (Pages-Source = „GitHub Actions").
  - Prüft, dass die Version aus `VERSION` in `docs/index.html` steht.
  - Dieses Projekt hat **kein** Apps Script → kein clasp-Schritt.
  - Git-Tag `v<VERSION>` setzen.
  - `concurrency`: immer nur ein Deploy gleichzeitig.
- **Datei `VERSION`** im Repo-Root (x.y.z). **Jede** Änderung erhöht die Version. `APP_VERSION` in `docs/app.js` und der Service-Worker-Cache-Name folgen dieser Version; sie ist in der App sichtbar. Das Sync-Tool hat eine eigene `__version__`; auch Änderungen daran erhöhen `VERSION`.
- **Nach jedem Push:** Status der Workflows prüfen und melden: „live in Version x.y.z" oder den Fehler in einfachen Worten.
- **Zurückgehen:** alten Stand (Tag) als **neue** Version wiederherstellen. Niemals Historie umschreiben, kein force-push auf `main`.
- **Niemals Geheimnisse ins Repo** (es ist öffentlich): kein R2-Präfix, keine R2-Zugangsdaten, keine `config.local.json`. Die öffentliche R2-Adresse (`pub-….r2.dev`) ist **kein** Geheimnis – ohne Präfix ist dort nichts abrufbar, und die App muss sie ohnehin kennen.
- **Repo-Aufbau:** `docs/` = PWA (GitHub Pages) · `sync/` = lokales Sync-Tool (läuft nur auf meinem PC) · `.github/workflows/` = release + deploy · `VERSION` · `CLAUDE.md`.
- Das Sync-Tool kann in der Cloud geschrieben werden, ausgeführt und mit echten Exporten getestet wird es aber auf meinem Windows-PC. Dafür klar sagen, was ich am PC ausführen soll. Dateien für den PC per Datei-Übergabe liefern; sie liegen dort in `D:\Fotoschatz\_sync\`.

---

## 1. Ziel & Rahmen

- Meine ca. 10.000 Lightroom-Bilder online ansehen und **durchsuchen** – auch unterwegs auf dem Handy.
- Die Familie kann die Bilder ohne Konto per Link ansehen.
- Die in Lightroom gepflegten Personen, Orte und Beschreibungen sollen nutzbar sein.
- Alte Bilder neu entdecken (Rückblick „Heute vor X Jahren") – **zunächst nur in der App**, keine Push-Benachrichtigungen.
- Vorgehen: **zuerst MVP**, danach schrittweise weitere Funktionen.
- **Zielplattform:** Android + Chrome, als installierbare PWA; angesehen wird auch am PC. Kein iPhone nötig.
- Kosten bei Cloudflare sind kein Problem (voraussichtlich ohnehin im Gratis-Bereich).

---

## 2. Ausgangslage

### Lightroom Classic
- Katalog mit ca. 10.000 Bildern, alle von Digitalkameras/Handys (keine Scans). Gepflegt: Personen (Gesichtsmarkierung), Orte, GPS, Beschreibung, teils Bewertung.
- **Inhaltliche Stichwörter gibt es praktisch nicht** – in den Stichwörtern stehen fast nur Personennamen und Verwaltungs-Stichwörter (z. B. `google-fotos-uploaded`). Keine Stichwort-Hierarchie. Die Sammlung ist über 20 Jahre gewachsen, einzelne Ausreißer sind möglich.
- Originaldateien heißen bereits nach dem Aufnahmezeitpunkt (z. B. `2006-06-08_20-11-00.JPG`).
- Oberfläche von Lightroom ist **deutsch**.

### Ordnerstruktur der Originale (Festplatte)
```
2006/
  _Import/                          ← unsortiert, wird NICHT exportiert / NICHT online
  2006-05-26 Paris mit Familie/
  2006-06-15 Baltikum/
  2006-2007 Danone/                 ← Ordnernamen weichen teils vom Muster ab
  <lose Bilder direkt im Jahr>      ← keinem Ereignis zugeordnet
2007/
  ...
```
- Ebene 1: Jahr. Ebene 2: Ereignisordner, meist `YYYY-MM-DD Name`, aber nicht immer (z. B. `2006-2007 Danone`). Der Ordnername beginnt immer mit einer Jahreszahl.
- **Lose Bilder direkt im Jahresordner** (keinem Ereignis zugeordnet) erscheinen online im Ordner **„JJJJ Weitere Bilder"** – für jedes Jahr.
- **Keine weiteren Unterordner** in den Ereignisordnern.

### Export
- Alle JPGs landen in **einem flachen Export-Ordner**: `D:\Fotoschatz`.
- Der Lightroom-Ordnername und der Aufnahmezeitpunkt stehen im Dateinamen (siehe Abschnitt 5).
- Workflow: Ein Ereignisordner ist fertig bearbeitet → exportieren → Sync starten.
- Neu bearbeitete oder korrigierte Bilder werden neu exportiert und **überschreiben** die alte Datei → der Sync ersetzt sie online.

### Rechner
- Windows-PC. Das Sync-Tool läuft lokal. Installiert: Python, exiftool (`winget install OliverBetz.ExifTool`), rclone (`winget`).
- Skripte liegen in `D:\Fotoschatz\_sync\` (beginnt mit `_` → wird nie als Fotoordner behandelt).

---

## 3. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Hosting Bilder | Cloudflare R2, öffentlich lesbar, alles unter einem geheimen Pfad-Präfix |
| Hosting App | GitHub Pages, Repo `obitusde/fotoschatz`, Ordner `docs/`, statische PWA, kein Backend |
| Bildgröße | **2048 px** lange Kante, JPEG-Qualität **70** (≈ 0,5–1,2 MB je Bild; Handy + PC) |
| Vorschaubilder | vom Sync-Tool erzeugt (WebP, ca. 400 px) |
| Upload | rclone, gesteuert durch Python-Skript, Start per `sync.bat` |
| Prüfung vor Upload | Sync-Tool prüft jedes Bild; schwere Fehler → Bild wird nicht hochgeladen; Hinweise → Upload trotzdem; Korrektur-Tabelle (CSV) zum Nachbessern in Lightroom |
| Zugriffsschutz | öffentlich, aber mit langem geheimem Link (Geheimnis im URL-Hash) |
| GPS | bleibt in den Bildern (für Karte/Umkreissuche) |
| `_Import` | wird nicht exportiert und nicht online gestellt |
| Online-Struktur | wie auf der Platte: Jahr → Ereignisordner (+ „JJJJ Weitere Bilder"), plus „Alle Bilder" |
| Benachrichtigungen | keine Push-Nachrichten, keine E-Mails – Rückblick nur in der App |
| Plattform | Android/Chrome, installierbare PWA |

---

## 4. Architektur

```
PC (Windows)                              Cloud
────────────────────────────              ───────────────────────────────────
Lightroom Classic                         Cloudflare R2 (Bucket, public read)
  │ Export-Preset (2048px, Q70)             /<SECRET>/
  ▼                                           ├─ img/    <id>.<hash>.jpg
Export-Ordner D:\Fotoschatz (flach)           ├─ thumb/  <id>.<hash>.webp
  │                                           └─ index.json
  ▼                                                ▲
sync-Tool (Python, D:\Fotoschatz\_sync)            │
  1. Export-Ordner scannen                         │
  2. Dateinamen parsen + prüfen                    │
  3. Neue/geänderte Dateien erkennen               │
  4. Metadaten lesen (exiftool)                    │
  5. Staging-Ordner befüllen (img + thumb)         │
  6. index.json bauen                              │
  7. rclone → R2  ─────────────────────────────────┘
                                                   │ lädt (fetch)
                                     GitHub Pages: Foto-PWA
                                     https://obitusde.github.io/fotoschatz/#<SECRET>
```

**Grundprinzip:** Kein Server, keine Datenbank online. Die App lädt `index.json` und macht Suche, Filter, Ordner, Karte und Rückblick komplett im Browser.

---

## 5. Lightroom-Export-Preset (eingerichtet und geprüft, 28.09.2026)

| Bereich | Einstellung |
|---|---|
| Exportieren auf | Festplatte |
| Speicherort | `D:\Fotoschatz` (ohne Unterordner) |
| Vorhandene Dateien | **ohne Warnung überschreiben** (nötig fürs Ersetzen) |
| Dateibenennung | benutzerdefinierte Vorlage: `{Ordnername}_{Aufnahmezeitpunkt}` → z. B. `2024-10-24 Wanderung ab Les Cases_2024-10-24_10-11-21.jpg`; bei losen Bildern im Jahresordner `2006_2006-06-08_20-11-00.jpg` |
| Dateiformat | JPEG, Qualität 70, Farbraum sRGB |
| Bildgröße | lange Kante 2048 px, nicht vergrößern |
| Metadaten | alle, Personen- und Standortinfo **nicht** entfernen |
| Wasserzeichen | nein |

**Hinweise:**
- Zwei Bilder in derselben Sekunde (Serienbild): Lightroom hängt `-2`, `-3` … an (`…_08-40-40-2.jpg`). ⚠ Wird später nur eines davon neu exportiert, kann es das andere überschreiben. Einzelfälle, im Blick behalten.
- Virtuelle Kopien: es wird immer nur das oberste Bild eines Stapels exportiert.
- Stichwörter mit der Option „nicht beim Export einbeziehen" landen nicht im JPG.

---

## 6. Cloudflare R2 – Einrichtung (erledigt, 28.09.2026)

1. Cloudflare-Konto, R2 aktiviert.
2. Bucket `fotoschatz`, Storage Class Standard, **Jurisdiction EU** (nicht änderbar).
3. **Öffentlicher Zugriff** über `r2.dev`-Adresse: `https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev`. ⚠ Laut Cloudflare für Entwicklung gedacht und in der Rate begrenzt → offene Entscheidung, ob später eigene Domain.
4. **CORS** am Bucket: `GET`, `HEAD` für Origin `https://obitusde.github.io`. ✅ Geprüft mit `docs/test-r2.html` (Aufruf mit `#<Präfix>`).
5. **Account-API-Token**: nur Bucket `fotoschatz`, Rechte „Object Read & Write". Zugangsdaten liegen nur lokal in der rclone-Konfiguration, **nie im Repo**.
6. rclone-Remote `r2` (`%APPDATA%\rclone\rclone.conf`):
   ```
   [r2]
   type = s3
   provider = Cloudflare
   access_key_id = …
   secret_access_key = …
   endpoint = https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com   ← EU-Endpoint wegen Jurisdiction EU
   region = auto
   acl = private
   no_check_bucket = true                                        ← Token darf Bucket nicht prüfen
   ```
7. **Geheimes Präfix**: 40 Zeichen `[A-Za-z0-9]`, liegt lokal in `fotoschatz-secrets.ps1` (später auch in `config.local.json`). Das Sync-Tool muss das Präfix trimmen und prüfen (Leerzeichen haben beim Test schon einen falschen Pfad erzeugt).
8. ✅ Geprüft: Weder die Bucket-Wurzel noch `<pub-url>/<Präfix>/` zeigen eine Dateiliste. Eine Testdatei ist über `<pub-url>/<Präfix>/test/genfer-see.jpg` abrufbar.
9. Aufräumen: Im Bucket liegt noch ein fehlerhaftes Testobjekt (Präfix mit Leerzeichen dahinter) – über das Dashboard löschen.

**Kosten/Mengen (grob):** Bilder mit 2048 px/Q70 ≈ 0,5–1,2 MB (Naturaufnahmen am oberen Ende) → ca. 6–9 GB. Vorschaubilder ≈ 20 KB → ca. 0,2 GB. Gratis-Bereich: 10 GB Speicher, Downloads kostenlos. Bei der Erstbefüllung Gesamtgröße messen; falls zu knapp, Qualität oder Kantenlänge anpassen.

---

## 7. Sync-Tool (Python, lokal)

### Voraussetzungen
- Python 3.x mit Pillow (inkl. WebP-Unterstützung)
- `exiftool.exe` im PATH
- `rclone.exe` im PATH, Remote `r2` konfiguriert
- Start per Doppelklick: `sync.bat` (ruft das Python-Skript auf, lässt das Fenster am Ende offen)

### Dateien (Repo `sync/` → am PC `D:\Fotoschatz\_sync\`)
- `sync.py` – Hauptablauf · `regeln.py` – gemeinsame Regeln (Dateinamen, Ordner, Prüfungen, Metadaten) · `diagnose.py` – Prüfen ohne Upload
- `sync.bat` – Sync per Doppelklick · `probelauf.bat` – dasselbe mit `--dry-run`
- `config.example.json` – Vorlage für die optionale `config.local.json` (per `.gitignore` ausgeschlossen)
- Ausgaben neben dem Skript: `korrekturen.csv`, `stichwoerter.txt` (alle Stichwörter mit Anzahl und Markierung), `letzter_lauf.txt` (Protokoll, enthält nie das Präfix)

### Konfiguration (optional) `config.local.json`
Ohne Datei gelten diese Standardwerte:
```json
{
  "export_dir": "D:\\Fotoschatz",
  "work_dir": "D:\\Fotoschatz\\_sync\\work",
  "secrets_file": "C:\\Users\\chris\\fotoschatz-secrets.ps1",
  "rclone_remote": "r2:fotoschatz",
  "thumb_long_edge": 400,
  "thumb_quality": 70,
  "max_delete": 100,
  "transfers": 8,
  "ignore_keywords": ["google-fotos-uploaded", "Person", "Persons", "location-ok"]
}
```
- `export_dir` = Ordner oberhalb von `_sync`, `work_dir` = `_sync\work`.
- **Präfix steht nur in `fotoschatz-secrets.ps1`** (`$env:FOTOSCHATZ_R2_PREFIX = "..."`) – das Sync-Tool liest es dort, getrimmt und geprüft.
- `work_dir` enthält: `staging/` (img als Hardlinks auf die Exporte – kein doppelter Speicherplatz, thumb, index.json) und `state.json` (Zustand je Datei, `upload_pending`, bekannte Stichwörter).

### Dateinamen (verbindlich)
- Muster, **von hinten gelesen**: `^(?P<ordner>.+)_(?P<datum>\d{4}-\d{2}-\d{2})_(?P<zeit>\d{2}-\d{2}-\d{2})(?:-(?P<nr>\d+))?\.jpe?g$` (Groß-/Kleinschreibung egal). Der Ordnername darf beliebig aussehen, auch Unterstriche enthalten.
- **Aufnahmezeit** = Datum + Zeit aus dem Dateinamen (nicht aus EXIF – `DateTimeOriginal` ist in den Exporten leer).
- **Online-Ordner:**
  - Ordnername = nur Jahreszahl (`2006`) → „2006 Weitere Bilder", steht im Jahr hinter den Ereignisordnern.
  - `YYYY-MM-DD Name` → unverändert; Jahr und Ordnerdatum daraus.
  - `YYYY-YYYY Name` → unverändert; Jahr = erstes Jahr, erlaubter Zeitraum = beide Jahre.
  - Sonst beginnt er mit `YYYY` → unverändert; Jahr daraus; Ordnerdatum = früheste Aufnahme im Ordner.
- **Ordnerjahr** bestimmt die Einordnung in der Ordneransicht, **Aufnahmezeit** die Zeitleiste.

### Prüfung vor dem Upload (verbindlich)
- **SCHWER** → Bild wird **nicht** hochgeladen: Dateiname passt nicht zum Muster; Aufnahmezeit ist kein gültiges Datum; Ordner beginnt mit `_`; Ordnername beginnt nicht mit einer Jahreszahl.
- **Hinweis** → Bild wird trotzdem hochgeladen: Aufnahmezeit unplausibel (vor 1995 oder in der Zukunft – Kamerauhr?); Aufnahmejahr passt nicht zum Ordner (erlaubt: Ordnerjahr und Folgejahr bzw. der Jahresbereich); keine GPS-Daten; Ordnerdatum ungültig; Stichwort erstmals gesehen.
- Ausgabe: `korrekturen.csv` (bzw. `diagnose_korrekturen.csv`; Excel, `;`, UTF-8 mit BOM) mit Spalten Schwere · Lightroom-Ordner · Originaldatei · Aufnahmezeit · Exportdatei · Problem, sortiert nach Ordner und Zeit → Bild in Lightroom über Ordner + Originaldatei finden, korrigieren, neu exportieren (überschreibt).
- Der ganze Lauf wird nur bei Fehlern abgebrochen, die alles durcheinanderbringen würden (siehe Sicherheitsprüfungen).
- `sync/diagnose.py` enthält dieselben Regeln und dient zum Prüfen ohne Upload.

### Ablauf pro Lauf
1. **Scannen:** alle `*.jpg` im Export-Ordner (nicht rekursiv).
2. **Dateinamen parsen und prüfen** (siehe oben).
3. **Änderungen erkennen:** über `state.json` (Größe, Änderungszeit, SHA-1 des Inhalts).
   - neu → verarbeiten
   - Inhalt geändert → neu verarbeiten (**ersetzt** online)
   - unverändert → nichts tun
   - lokal verschwunden → aus Staging entfernen (wird online gelöscht)
   - Stichwort taucht erstmals auf → Hinweis in der Korrektur-Tabelle (nicht beim allerersten Lauf)
4. **IDs & Dateinamen online:**
   - `id` = die ersten 12 Hex-Zeichen von SHA-1(Export-Dateiname). URL-sicher, auch bei Leerzeichen und Umlauten.
   - `hash` = die ersten 8 Hex-Zeichen von SHA-1(Inhalt).
   - Online-Dateien: `img/<id>.<hash>.jpg`, `thumb/<id>.<hash>.webp`.
   - Vorteil: Ein ersetztes Bild bekommt einen neuen Dateinamen → keine veralteten Caches; alle Bilddateien sind unveränderlich (`immutable`).
5. **Metadaten lesen:** exiftool im Batch nur für neue/geänderte Dateien (`-json -n -G1 -charset filename=utf8`). Ergebnisse in `state.json` zwischenspeichern.
6. **Vorschaubild erzeugen:** Pillow, Orientierung beachten, lange Kante 400 px, WebP Q70, ohne Metadaten.
7. **Großes Bild:** unverändert ins Staging kopieren (behält EXIF inkl. GPS).
8. **`index.json` komplett neu bauen** aus `state.json` (schnell, da gecacht).
9. **Sicherheitsprüfungen vor dem Upload:**
   - Export-Ordner leer oder nicht gefunden → **Abbruch**.
   - Mehr als `max_delete` Löschungen → **Abbruch** mit Hinweis (Schutz vor versehentlichem Leeren des Buckets).
   - Präfix fehlt, enthält andere Zeichen als `[A-Za-z0-9]` (Leerzeichen am Rand werden entfernt), oder ist kürzer als 32 Zeichen → **Abbruch**.
   - Defektes Bild (Vorschaubild lässt sich nicht erzeugen) → SCHWER, nur dieses Bild wird ausgelassen.
   - Option `--dry-run`: zeigt nur an, was passieren würde.
10. **Upload per rclone** nach `<remote>/<Präfix>/` in dieser Reihenfolge (die App sieht nie fehlende Bilder):
    1. `rclone copy` neue `img/` und `thumb/` (Header `Cache-Control: public, max-age=31536000, immutable`, `--size-only`, 8 parallel)
    2. `rclone copyto` `index.json` (Header `Cache-Control: no-cache`)
    3. `rclone sync` `img/` und `thumb/` → löscht Veraltetes (`--max-delete` als zweite Sicherung)
    - Nur wenn sich etwas geändert hat oder ein früherer Upload fehlschlug (`upload_pending`). Bei rclone-Fehler Abbruch; der nächste Lauf wiederholt den Upload.
    - Andere Pfade unter dem Präfix (z. B. `test/`) werden nicht angefasst.
11. **Zusammenfassung ausgeben:** neu / ersetzt / gelöscht / unverändert / schwere Fehler / Hinweise / Laufzeit / Tool-Version; Pfad zur Korrektur-Tabelle.

### Metadaten-Zuordnung (verbindlich, geprüft an 114 echten Exporten)

| Zweck | Quelle (exiftool `-G1`) | Belegung im Test |
|---|---|---|
| Aufnahmezeit | Dateiname | 114/114 |
| Ordner / Jahr | Dateiname | 114/114 |
| Personen | `XMP-iptcExt:PersonInImage` (sonst `XMP-mwg-rs:RegionName`) **plus** Stichwörter, die einem bekannten Personennamen entsprechen | 59/114 |
| Stichwörter | `XMP-dc:Subject` (sonst `IPTC:Keywords`) ohne Personennamen und ohne `ignore_keywords` | praktisch leer |
| Ort | `IPTC:Sub-location` / `XMP-iptcCore:Location` | 49/114 |
| Stadt | `XMP-photoshop:City` | 97/114 |
| Bundesland | `XMP-photoshop:State` | 110/114 |
| Land | `XMP-photoshop:Country` | 110/114 |
| Beschreibung | `XMP-dc:Description` (sonst `IPTC:Caption-Abstract`) | 67/114 |
| Bewertung | `XMP-xmp:Rating` | 20/114 |
| GPS | `Composite:GPSLatitude`, `Composite:GPSLongitude` | 110/114 |
| Maße | `File:ImageWidth`, `File:ImageHeight` | 114/114 |
| Originaldatei (nur Korrektur-Tabelle) | `XMP-crs:RawFileName` | 114/114 |
| **Nicht genutzt** | `XMP-dc:Title` (leer), `XMP-lr:HierarchicalSubject` (leer), `DateTimeOriginal` (leer) | |

- „Bekannte Personennamen" = alle Namen, die in irgendeinem Bild als Person markiert sind (Groß-/Kleinschreibung egal).

### `index.json` – Schema (kurze Schlüssel wegen Größe)
```json
{
  "v": 1,
  "generated": "2026-09-27T20:15:00Z",
  "count": 10000,
  "folders": [
    { "n": "2006-05-26 Paris mit Familie", "y": 2006, "d": "2006-05-26", "c": 27, "cover": "<id>" },
    { "n": "2006 Weitere Bilder", "y": 2006, "d": "2006-01-23", "c": 65, "cover": "<id>", "x": 1 }
  ],
  "photos": [
    {
      "id": "a1b2c3d4e5f6",
      "h": "9f8e7d6c",
      "f": "2006-05-26 Paris mit Familie",
      "t": "2006-05-27T10:07:11",
      "w": 2048, "ht": 1536,
      "p": ["Christof", "Petra"],
      "kw": [],
      "de": "Paris mit Familie",
      "sl": "Tour Eiffel", "ci": "Paris", "st": "Île-de-France", "co": "France",
      "la": 48.8584, "lo": 2.2945,
      "r": 4
    }
  ]
}
```
- `folders.x = 1` markiert „Weitere Bilder" (in der Ordneransicht am Ende des Jahres).
- `folders.cover` wird vom Sync-Tool noch geschrieben, von der App aber nicht genutzt (keine Titelbilder).
- URLs werden in der App aus `SECRET`, `id` und `h` zusammengesetzt, nicht im Index gespeichert.
- Leere Felder weglassen.
- Größe beim ersten vollen Lauf messen (Erwartung: wenige MB). Falls zu groß: gzip vorkomprimieren + `Content-Encoding`-Header, oder den Index nach Jahren aufteilen.

---

## 8. PWA (GitHub Pages)

### Technik
- Statisch, **kein Build-Schritt**: `index.html`, `app.js`, `styles.css`, `sw.js`, `manifest.webmanifest`, `icons/`.
- Vanilla JavaScript. Externe Bibliotheken (z. B. Leaflet für die Karte) nur mit **fest angegebener Version** über cdnjs, niemals „latest".
- `<meta name="robots" content="noindex, nofollow">`, kein Tracking/Analytics.
- Hell/Dunkel folgt der Einstellung des Handys/PCs (`prefers-color-scheme`).

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
- **Leiste unten:** Ordner · Alle Bilder · Suche. Kopfzeile oben mit Titel, Untertitel und ggf. Zurück-Pfeil.
1. **Ordner** (Startansicht):
   - **Reine Textliste, keine Titelbilder** (bewusst so entschieden – nichts zu pflegen, nichts zufällig).
   - Jahre absteigend (Überschrift mit Anzahl bleibt beim Scrollen oben), darunter die Ordner neueste zuerst: Name ohne Datumspräfix, darunter Datum · Anzahl; „Weitere Bilder" am Ende des Jahres.
   - Fußzeile: Anzahl Bilder · Stand des Index · App-Version.
2. **Alle Bilder:** Zeitleiste, neueste zuerst, gruppiert nach Monat; der aktuelle Monat steht im Untertitel der Kopfzeile.
3. **Ordnerinhalt:** Raster nach Aufnahmezeit sortiert.
4. **Suche:**
   - Eingabefeld mit Vorschlägen aus Personen, Orten (Ort, Stadt, Bundesland, Land), Stichwörtern und Ordnernamen.
   - Gewählte Begriffe werden zu Chips und mit **UND** verknüpft (z. B. Person + Land + Jahr).
   - Zusätzlich Freitext über Beschreibung, Orte und Ordnername.
   - Groß-/Kleinschreibung und Akzente ignorieren (Unicode-Normalisierung, diakritische Zeichen entfernen).
   - Ergebnis als Raster.
5. **Vollbild-Betrachter:**
   - Wischen links/rechts, Nachbarbilder vorladen.
   - Tippen: linkes Drittel = zurück, rechtes Drittel = weiter, Mitte = Bedienelemente aus/ein. Wischen links/rechts blättert.
   - Infos (Datum, Ordner, Personen, Ort, Beschreibung – ausgeblendet, wenn gleich dem Ordnernamen –, Bewertung) über den Knopf (i) bzw. Taste I; **anfangs ausgeblendet**, Einstellung wird gemerkt (`fotoschatz.info`).
   - Echtes Vollbild (Browser-Leisten weg): am Handy automatisch beim Öffnen, am PC per Knopf oder Taste F. ⚠ Am Handy prüfen: Zurück-Taste im Vollbild schließt das Bild genau einmal.
   - Zurück-Taste, ✕, Wischen nach unten und Esc schließen den Betrachter (History-API); am PC Pfeiltasten und Pfeil-Schaltflächen.
   - Erst das Vorschaubild, dann das große Bild; Nachbarbilder werden vorgeladen.
   - Zoomen mit zwei Fingern: nice-to-have.

### Raster & Performance (Anforderung: flüssiges Scrollen bei 10.000 Bildern)
- **Virtuelles Scrollen:** Nur die sichtbaren Zeilen (plus Puffer) existieren im DOM.
- Quadratisches Raster (Bild mittig zugeschnitten), 4 Spalten auf dem Handy, am PC ca. 170 px je Kachel, feste Zeilenhöhe → einfache, sprungfreie Virtualisierung.
- Vorschaubilder mit `loading="lazy"` / `decoding="async"`, Platzhalterfarbe, bis das Bild geladen ist.
- Index einmal laden, Suchstrukturen einmal aufbauen (Begriff → Bild-IDs).

### Service Worker – Caching
- **App-Dateien:** vorab cachen, Cache-Name enthält `APP_VERSION`.
- **Vorschaubilder:** cache-first (unveränderlich dank Hash im Namen) → beim zweiten Besuch sofort da, auch ohne Netz.
- **Große Bilder:** cache-first mit Obergrenze (z. B. die letzten ~300 Bilder, älteste werden entfernt).
- **`index.json`:** network-first, bei fehlendem Netz aus dem Cache.

---

## 9. Datenschutz & Sicherheit

- Alle Bilder sind technisch öffentlich. Schutz nur durch das nicht erratbare Präfix („Security by Obscurity") – bewusst so entschieden. Auflisten ist nicht möglich (geprüft).
- Die großen JPGs enthalten GPS und Personennamen – bewusst so, nur Familie hat den Link.
- Daten liegen in der EU (R2 Jurisdiction EU).
- **Nie ins Repo:** Geheimnis, R2-Zugangsdaten, `config.local.json`, `rclone.conf`, `fotoschatz-secrets.ps1`.
- **Link ist in falsche Hände geraten:**
  1. Neues Präfix erzeugen.
  2. Inhalte serverseitig verschieben (`rclone move` innerhalb des Buckets) oder neu hochladen.
  3. `fotoschatz-secrets.ps1` anpassen.
  4. Neuen Link an die Familie schicken. Der alte Link zeigt danach nichts mehr.
- R2 ist **kein Backup**. Die Originale und der Lightroom-Katalog brauchen weiterhin eine eigene Datensicherung.

---

## 10. Phasenplan

### Phase 0 – Diagnose (kein Produktivcode) – ✅ abgeschlossen 28.09.2026
- ✅ 0.1 Export-Preset angelegt (Abschnitt 5).
- ✅ 0.2 Testbilder exportiert (114 Bilder: Ereignisordner, Jahresordner, Personen, GPS, Bewertung).
- ✅ 0.3 Diagnose-Skript `sync/diagnose.py` (Bericht + Korrektur-Tabelle).
- ✅ 0.4 Verbindliche Feldzuordnung in Abschnitt 7 eingetragen.
- ✅ 0.5 R2: Bucket, Token, rclone, CORS, öffentliche URL, Testdatei, kein Auflisten, Abruf per `fetch` von `obitusde.github.io` (200 KB in 414 ms).

### Phase 1 – Sync-Tool – ✅ am PC bestätigt 28.09.2026
- Umsetzung nach Abschnitt 7 inkl. `--dry-run`, Prüfungen, Korrektur-Tabelle, Sicherheitsprüfungen, Zusammenfassung.
- v0.2.0 in der Cloud durchgespielt (alle vier Testfälle + Lösch-Schutz ok) und am PC gegen echtes R2 gelaufen: 114 Bilder (74 MB) in 24 s, zweiter Lauf „keine Änderungen". Ersetzen/Löschen am echten System nebenbei noch einmal prüfen.
- Messwerte: `index.json` ≈ 0,22 KB je Bild (10.000 Bilder ≈ 2,2 MB), Vorschaubild ≈ 16 KB.
- Test mit den Testbildern: neu → hochgeladen; ein Bild neu exportiert → ersetzt; eine Datei gelöscht → online entfernt; nochmaliger Lauf → „0 Änderungen".
- **Fertig, wenn:** Alle vier Testfälle korrekt laufen und `index.json` dem Schema entspricht.

### Phase 2 – PWA-MVP – in Arbeit
- Geheimnis-Handling, Ordner, Alle Bilder, Suche, Betrachter, Service Worker, Manifest, Installierbarkeit.
- **2a** (v0.3.0): Link/Präfix, Index laden, Ordnerliste, Ordner-Raster, Alle Bilder, Vollbild. In der Cloud mit 414 Testbildern im Browser (Handy- und PC-Größe, hell/dunkel) geprüft. ⚠ Am echten Handy mit echtem R2 testen.
- **2b:** Suche (Vorschläge aus Personen, Orten, Ordnern, Jahren; Chips mit UND; Freitext).
- **2c:** Manifest, Icons, Service Worker (Offline-Cache), „Neue Version verfügbar".
- **Fertig, wenn:** Auf dem Android-Handy installierbar; Start über das App-Symbol ohne erneuten Link funktioniert; Scrollen flüssig; Suche kombiniert Chips korrekt.

### Phase 3 – Erstbefüllung
- Alle Ordner (außer `_Import`) exportieren, voller Sync.
- Index-Größe, Speicherbedarf in R2, Upload-Dauer und Scroll-Performance mit ~10.000 Bildern prüfen.
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

## 12. Offene Punkte

- `r2.dev` oder eigene Domain? (spätestens vor Phase 3 entscheiden)
- Soll `sync.bat` zusätzlich zeitgesteuert laufen (Windows-Aufgabenplanung) oder nur per Doppelklick?
- ⚠ Serienbilder mit `-2`: Verhalten bei Neu-Export nur eines der Bilder beobachten.

Geklärt (28.09.2026): Personen stehen in eigenem Feld (Gesichtsmarkierung) und zusätzlich als Stichwort · virtuelle Kopien: nur oberstes Stapelbild · Aufnahmezeit aus Dateinamen · lose Bilder → „JJJJ Weitere Bilder".

---

## 13. Wartung & Betrieb

- **Laufend:** nach dem Export `sync.bat` starten, bei Einträgen in der Korrektur-Tabelle in Lightroom nachbessern und neu exportieren – sonst nichts.
- **Kein Server** zu aktualisieren. R2 und GitHub Pages werden von den Anbietern betrieben.
- **Neuer PC:** Python, Pillow, exiftool, rclone installieren; `fotoschatz-secrets.ps1`, die rclone-Konfiguration, ggf. `config.local.json` und `_sync\work\state.json` übernehmen (vorher sicher aufbewahren!). Ohne `state.json` rechnet der erste Lauf alles neu, lädt aber nichts doppelt hoch (gleiche Namen).
- **Mögliche Störungen (selten):** Cloudflare ändert Tarife oder `r2.dev`-Limits; eine externe Bibliothek ändert sich (Gegenmittel: feste Versionen).
- **App-Updates:** neue `APP_VERSION` → neuer Service-Worker-Cache. Die App zeigt „Neue Version verfügbar – neu laden".
