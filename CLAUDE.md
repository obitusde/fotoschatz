# Fotoschatz – Projektgrundlage für Claude Code

**Dokumentversion:** v3.15 · 03.10.2026 (Sterne ★ wichtig / ★★ Lieblingsbild, Merker `ort-egal`/`personen-egal`, v0.6.29; davor v0.6.28 `personen_pruefen`)
**Repo:** `obitusde/fotoschatz` · **Pages:** `https://obitusde.github.io/fotoschatz/`
**Projekt:** Fotoschatz – private Online-Fotogalerie für ca. 23.000 Lightroom-Bilder – Eigenbau mit Cloudflare R2 + installierbarer PWA (GitHub Pages)

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
  - Prüft, dass die Version aus `VERSION` in `docs/index.html` steht und `APP_VERSION` in `docs/app.js` sowie `VERSION` in `docs/sw.js` gleich sind (sonst bekommt die installierte App kein Update).
  - Dieses Projekt hat **kein** Apps Script → kein clasp-Schritt.
  - Git-Tag `v<VERSION>` setzen.
  - `concurrency`: immer nur ein Deploy gleichzeitig.
- **Datei `VERSION`** im Repo-Root (x.y.z). **Jede** Änderung erhöht die Version. `APP_VERSION` in `docs/app.js` und der Service-Worker-Cache-Name folgen dieser Version; sie ist in der App sichtbar. Das Sync-Tool hat eine eigene `__version__`; auch Änderungen daran erhöhen `VERSION`.
- **Nach jedem Push:** Status der Workflows prüfen und melden: „live in Version x.y.z" oder den Fehler in einfachen Worten.
- **Zurückgehen:** alten Stand (Tag) als **neue** Version wiederherstellen. Niemals Historie umschreiben, kein force-push auf `main`.
- **Niemals Geheimnisse ins Repo** (es ist öffentlich): kein R2-Präfix, keine R2-Zugangsdaten, keine `config.local.json`. Die öffentliche R2-Adresse (`pub-….r2.dev`) ist **kein** Geheimnis – ohne Präfix ist dort nichts abrufbar, und die App muss sie ohnehin kennen.
- **Repo-Aufbau:** `docs/` = PWA (GitHub Pages) · `sync/` = lokales Sync-Tool (läuft nur auf meinem PC) · `.github/workflows/` = release + deploy · `VERSION` · `CLAUDE.md` · `README.md` (Kurzfassung für mich: Ablauf, was jedes Skript macht und nicht macht, Achtung-Punkte, offene Aufgaben – bei neuen Skripten oder geändertem Ablauf mitpflegen).
- Das Sync-Tool kann in der Cloud geschrieben werden, ausgeführt und mit echten Exporten getestet wird es aber auf meinem Windows-PC. Dafür klar sagen, was ich am PC ausführen soll. Dateien liegen dort in `D:\Fotoschatz\_sync\`; **neue Fassungen holt `aktualisieren.bat`** (Doppelklick, seit v0.6.23) – sonst per Datei-Übergabe.

---

## 1. Ziel & Rahmen

- Meine ca. 23.000 Lightroom-Bilder (Stand 28.09.2026: 23.168) online ansehen und **durchsuchen** – auch unterwegs auf dem Handy.
- Die Familie kann die Bilder ohne Konto per Link ansehen.
- Die in Lightroom gepflegten Personen, Orte und Beschreibungen sollen nutzbar sein.
- Alte Bilder neu entdecken (Rückblick „Heute vor X Jahren") – **zunächst nur in der App**, keine Push-Benachrichtigungen.
- Vorgehen: **zuerst MVP**, danach schrittweise weitere Funktionen.
- **Zielplattform:** Android + Chrome, als installierbare PWA; angesehen wird auch am PC. Kein iPhone nötig.
- Kosten bei Cloudflare sind kein Problem (voraussichtlich ohnehin im Gratis-Bereich).

---

## 2. Ausgangslage

### Lightroom Classic
- Katalog mit ca. 23.000 Bildern, überwiegend von Digitalkameras/Handys, dazu alte Familienfotos (Scans, ab 1912). Gepflegt: Personen (Gesichtsmarkierung), Orte, GPS, Beschreibung, teils Bewertung.
- **Inhaltliche Stichwörter gibt es praktisch nicht** – in den Stichwörtern stehen fast nur Personennamen und Verwaltungs-Stichwörter (z. B. `google-fotos-uploaded`). Keine Stichwort-Hierarchie. Die Sammlung ist über 20 Jahre gewachsen, einzelne Ausreißer sind möglich.
- Originaldateien heißen meist nach dem Aufnahmezeitpunkt (z. B. `2006-06-08_20-11-00.JPG`), aber nicht immer (z. B. DNGs nicht umbenannt).
- Oberfläche von Lightroom ist **englisch** (Anleitungen mit englischen Menü-/Bausteinnamen).

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
- Ebene 1: Jahr – oder ein **Sammelordner** mit Jahreszahl, z. B. `1912-1985 Göbel und Schäfer\1936-1985 Familie Göbel\` (auch tiefer verschachtelt). Ebene 2: Ereignisordner, meist `YYYY-MM-DD Name`, aber nicht immer (z. B. `2006-2007 Danone`). Der Ordnername beginnt immer mit einer Jahreszahl.
- **Lose Bilder direkt im Jahresordner** (keinem Ereignis zugeordnet) erscheinen online im Ordner **„JJJJ Weitere Bilder"** – für jedes Jahr.
- Online zählt immer nur der **eigene** Ordnername (nicht der Pfad) → Ordnernamen müssen eindeutig sein (Übersicht prüft das).

### Export
- Alle JPGs landen in **einem flachen Export-Ordner**: `D:\Fotoschatz`.
- Der Lightroom-Ordnername und der Aufnahmezeitpunkt stehen im Dateinamen (siehe Abschnitt 5).
- Workflow: Ein Ereignisordner ist fertig bearbeitet → exportieren → Sync starten.
- Neu bearbeitete oder korrigierte Bilder werden neu exportiert und **überschreiben** die alte Datei → der Sync ersetzt sie online.

### Originale
- Liegen auf `D:\Bilder - Raw` (ändert sich nicht), darunter `JJJJ\<Ereignisordner>\` wie oben.
- **In diesen Ordner wird niemals geschrieben** – kein Skript legt dort Dateien an, ändert oder löscht etwas. Tools dürfen dort nur Verzeichnisse auflisten (Namen, Größen).
- Enthält auch alte Familienfotos (Scans, z. B. `1912-1935 Familie Hedwig Kilp`) und Bearbeitungen aus „Bearbeiten in …“ (`…-Edit.tif`).
- **`D:\Fotoschatz` dagegen darf gelöscht und überschrieben werden** – es ist nur der Export aus Lightroom.

### Rechner
- Windows-PC. Das Sync-Tool läuft lokal. Installiert: Python, exiftool (`winget install OliverBetz.ExifTool`), rclone (`winget`).
- Skripte liegen in `D:\Fotoschatz\_sync\` (beginnt mit `_` → wird nie als Fotoordner behandelt).

---

## 3. Getroffene Entscheidungen

| Thema | Entscheidung |
|---|---|
| Sterne (03.10.2026) | **★ = wichtig, ★★ = Lieblingsbild**, 0 = normal (die meisten). Werden in Lightroom neu gesetzt (alte 3–5★ ersetze ich). Wichtige und Lieblingsbilder prüfe ich gezielt (Personen u. a.); die App nutzt ★★/★ später für Rückblick und Best-of |
| Merker-Stichwörter (03.10.2026) | `ort-egal` (früher `location-ok`) = bewusst ohne GPS · `personen-egal` = bewusst ohne Personen. Die Tools melden solche Bilder nicht mehr; alte Namen (`location-ok`, `personen-ok`) gelten übergangsweise weiter (`katalog.ORT_EGAL`/`PERSONEN_EGAL`). In Lightroom *Include on Export* aus, in `ignore_keywords` ausgeblendet |
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

## 5. Lightroom-Export-Preset (eingerichtet 28.09.2026, Dateiname umgestellt 29.09.2026)

| Bereich | Einstellung |
|---|---|
| Exportieren auf | Festplatte |
| Speicherort | `D:\Fotoschatz` (ohne Unterordner) |
| Vorhandene Dateien | **ohne Warnung überschreiben** (nötig fürs Ersetzen) |
| Dateibenennung | File Naming › Custom: `{Folder Name»}_{Date (YYYY)»}-{Date (MM)»}-{Date (DD)»}_{Hour»}-{Minute»}-{Second»}` (Aufnahmedatum, Stunde 24-h – am PC bestätigt), Extensions: Lowercase → z. B. `2024-10-24 Wanderung ab Les Cases_2024-10-24_10-11-21.jpg`; bei losen Bildern im Jahresordner `2006_2006-06-08_20-11-00.jpg`. Bis 29.09.2026 war es `{Folder Name»}_{Filename»}` – umgestellt, weil nicht alle Originale (z. B. DNGs) nach Datum benannt sind. |
| Dateiformat | JPEG, Qualität 70, Farbraum sRGB, HDR Output aus, Content Credentials nicht einbeziehen |
| Nachschärfen | Screen, High (Geschmackssache; „Standard“ wäre üblicher) |
| Bildgröße | lange Kante 2048 px, nicht vergrößern |
| Metadaten | alle, Personen- und Standortinfo **nicht** entfernen |
| Wasserzeichen | nein |

**Hinweise:**
- Zwei Bilder in derselben Sekunde (Serienbild, oder Original + `-Edit`-Fassung): Lightroom hängt `-2`, `-3` … an (`…_08-40-40-2.jpg`). ⚠ Wird später nur eines davon neu exportiert, kann es das andere überschreiben. Einzelfälle, im Blick behalten.
- ⚠ Scans ohne Aufnahmedatum in Lightroom bekommen ein Ersatzdatum (welches, ungeprüft) → Übersicht zeigt „Jahr passt nicht“/„Datum unplausibel“.
- **Stapel:** Nur das oberste Bild eines Stapels soll in die Galerie. Vor dem Export `Photo › Stacking › Collapse All Stacks`, dann Strg+A – im Filmstreifen (F6) steht z. B. „146 of 163 photos / 146 selected“ = nur die obersten sind markiert (am PC bestätigt 29.09.2026).
- Virtuelle Kopien, die **nicht** mit ihrem Original gestapelt sind, erscheinen als eigene Kachel und werden mit exportiert → Übersicht meldet sie als Aufgabe „2 Fassungen“ (stapeln, gewünschte Fassung nach oben).
- Stichwörter mit der Option „nicht beim Export einbeziehen" landen nicht im JPG.

---

## 6. Cloudflare R2 – Einrichtung (erledigt, 28.09.2026)

1. Cloudflare-Konto, R2 aktiviert.
2. Bucket `fotoschatz`, Storage Class Standard, **Jurisdiction EU** (nicht änderbar).
3. **Öffentlicher Zugriff** über `r2.dev`-Adresse: `https://pub-6f47b0d5f2154b4fbdd0ac01fe7b6f8e.r2.dev`. ⚠ Laut Cloudflare für Entwicklung gedacht und in der Rate begrenzt. **Entscheidung 29.09.2026: bei `r2.dev` bleiben** (keine eigene Domain; für eine Familien-Galerie reicht es). Falls es später hakt (Drosselung, Fehler), eigene Domain nachrüsten.
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

**Kosten/Mengen (gemessen an 114 Bildern, hochgerechnet auf 23.168):** ⌀ 0,65 MB je Bild → ca. 15 GB, Vorschaubilder ⌀ 16 KB → ca. 0,4 GB, `index.json` ca. 5 MB. Gesamt ca. 15–16 GB (Spanne 12–18 GB). Gratis-Bereich 10 GB, darüber ⚠ ca. 0,015 $/GB/Monat → **ca. 1 € pro Jahr**; Zugriffe liegen im Freikontingent, Downloads kostenlos. Entscheidung: bei 2048 px bleiben.

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
- `uebersicht.py` + `uebersicht.bat` – Übersicht „was ist auf der Platte / exportiert / online / zu prüfen?“ (siehe unten)
- `aufraeumen.py` + `aufraeumen.bat` – überflüssige Exporte aus `D:\Fotoschatz` entfernen (siehe unten)
- `katalog.py` – Zugriff auf den Lightroom-Katalog, nur über eine Kopie · `katalog_diagnose.py` + `katalog_diagnose.bat` – prüft, ob der Katalog lesbar ist (siehe „Lightroom-Katalog“)
- `lightroom_pruefen.py` + `lightroom_pruefen.bat` – **Tool 1 „Lightroom prüfen“**: was in Lightroom zu korrigieren ist, dazu „GPS nachtragen“ je Ordner (siehe unten)
- `gps_test.py` + `gps_test.bat` – GPS-Test: können Fotos ohne GPS ihren Ort aus Handyfotos und Google-Zeitachse bekommen? (siehe „GPS nachtragen“)
- `personen_pruefen.py` + `personen_pruefen.bat` – Bilder ohne benannte Person je Ordner, mit Grund (siehe „Personen prüfen“)
- `zeitachse_pruefen.py` + `zeitachse_pruefen.bat` – Kamera-Uhr und GPS gegen Google-Zeitachse für den ganzen Katalog (siehe „Zeitachse prüfen“)
- `aktualisieren.bat` + `aktualisieren.ps1` (v0.6.23) – **neue Skripte holen per Doppelklick**: lädt alle `.py`/`.bat`/`.ps1` und `config.example.json` aus `sync/` im Repo (Stand `main`, fest auf einen Commit, damit alles zusammenpasst und kein alter Zwischenspeicher stört) erst in einen Temp-Ordner und ersetzt nur, wenn alles geladen ist; zeigt neu / aktualisiert / unverändert und die Version. Eigene Dateien (`config.local.json`, `work\`, `google\`, `gpx\`, `katalog\` …) bleiben unberührt. `aktualisieren.bat` ersetzt sich nicht selbst (Windows liest eine laufende .bat zeilenweise) – ändert sie sich, einmal von Hand holen. In der Cloud mit PowerShell 7 getestet (⚠ am PC läuft Windows PowerShell 5.1); Fehlerfall: nichts ersetzt.
- `config.example.json` – Vorlage für die optionale `config.local.json` (per `.gitignore` ausgeschlossen)
- Ausgaben neben dem Skript: `korrekturen.csv`, `stichwoerter.txt` (alle Stichwörter mit Anzahl und Markierung), `orte.txt` (alle Ortsnamen als Baum Land > Bundesland > Stadt > Ort mit Anzahl, so wie Lightroom sie schreibt – ab und zu an Claude schicken, damit englische Namen in `docs/orte.js` übersetzt werden), `letzter_lauf.txt` (Protokoll, enthält nie das Präfix)

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
- `META_VERSION` in `sync.py`: wird erhöht, wenn neue Metadatenfelder dazukommen → der nächste Lauf liest die Metadaten aller Bilder neu (`mv` je Datei in `state.json`) und lädt nur die neue `index.json` hoch.
- `work_dir` enthält: `staging/` (img als Hardlinks auf die Exporte – kein doppelter Speicherplatz, thumb, index.json) und `state.json` (Zustand je Datei, `upload_pending`, bekannte Stichwörter).

### Dateinamen (verbindlich)
- Muster, **von hinten gelesen**: `<Ordner>_JJJJ-MM-TT_hh-mm-ss[-Zusätze].jpg` (Groß-/Kleinschreibung egal). Der Ordnername darf beliebig aussehen, auch Unterstriche enthalten.
- **Erlaubte Zusätze** (v0.6.6, beliebig kombiniert): Nummer `-2`, `-Edit`/`-Bearbeitet` (Bearbeiten in Photoshop), `-HDR`, `-Pano`, `-Enhanced-NR`/`-Verbessert-RR` (Rauschen entfernen), `-SR`, `-AI`. Anlass: echte Exporte `…_1915-02-12_20-10-34-Edit.jpg` wurden als SCHWER abgelehnt.
- Die Zusätze stammen aus der früheren Vorlage `{Folder Name»}_{Filename»}`; mit der Datums-Vorlage (seit 29.09.2026) kommt nur noch `-2` usw. vor. Das Sync-Tool versteht beide.
- **Aufnahmezeit** = Datum + Zeit aus dem Dateinamen (nicht aus EXIF – `DateTimeOriginal` ist in den Exporten leer).
- **Online-Ordner:**
  - Ordnername = nur Jahreszahl (`2006`) → „2006 Weitere Bilder", steht im Jahr hinter den Ereignisordnern.
  - `YYYY-MM-DD Name` → unverändert; Jahr und Ordnerdatum daraus.
  - `YYYY-YYYY Name` → unverändert; Jahr = erstes Jahr, erlaubter Zeitraum = beide Jahre.
  - Sonst beginnt er mit `YYYY` → unverändert; Jahr daraus; Ordnerdatum = früheste Aufnahme im Ordner.
- **Ordnerjahr** bestimmt die Einordnung in der Ordneransicht, **Aufnahmezeit** die Zeitleiste.

### Prüfung vor dem Upload (verbindlich)
- **SCHWER** → Bild wird **nicht** hochgeladen: Dateiname passt nicht zum Muster; Aufnahmezeit ist kein gültiges Datum; Ordner beginnt mit `_`; Ordnername beginnt nicht mit einer Jahreszahl.
- **Hinweis** → Bild wird trotzdem hochgeladen: Aufnahmezeit unplausibel (in der Zukunft, oder vor 1995 und nicht passend zum Ordner – Kamerauhr?); Aufnahmejahr passt nicht zum Ordner (erlaubt: Ordnerjahr und Folgejahr bzw. der Jahresbereich; bei alten Ordnern vor 1995 wie `1912-1935 …` heißt der Hinweis so statt „Kamerauhr“); keine GPS-Daten; Ordnerdatum ungültig; Stichwort erstmals gesehen.
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

### Übersichts-Tool `uebersicht.py` (v0.6.4, erweitert v0.6.6–v0.6.10; v0.6.11: Ordner-Vorschläge wieder entfernt – „nicht gut“, Entscheidung 29.09.2026)
- Vergleicht **Originale** (`originals_dir`, Standard `D:\Bilder - Raw`, nur Verzeichnislisten), **Exporte** (`export_dir`) und **online** (`work\state.json`: Datei unverändert seit dem letzten Sync und kein `upload_pending`).
- Bild = Ordnername + Dateiname ohne Endung; RAW und JPG mit gleichem Namen im selben Ordner zählen als **ein** Bild. Ein Original gilt auch als exportiert, wenn seine Bearbeitung (`…-Edit` usw.) exportiert ist. Ordner mit `_` (z. B. `_Import`) werden separat gezählt („bewusst nicht online“), Videos ebenso, Dateien direkt im Wurzelordner ignoriert.
- Zuordnung Export → Original: Lightroom-Ordner aus dem Export-Dateinamen + Originaldatei (`XMP-crs:RawFileName`, aus `state.json` oder für noch nicht synchronisierte Exporte per exiftool); ersatzweise der Name aus dem Export (Aufnahmezeit + Zusätze).
- Ergebnis `uebersicht.html` neben dem Skript, öffnet sich im **Standard-Browser** (Windows-Zuordnung für Internet-Links, weil `.html` am PC mit dem Editor verknüpft ist – am PC bestätigt). `uebersicht.bat` schließt sich danach selbst (bleibt nur bei Fehlern offen). Nicht im Repo, nicht hochgeladen.
- **Aufbau der Seite:** Kacheln (gesamt / online / Sync fehlt / nicht exportiert / überflüssige Exporte / 📍 % ohne GPS und 👤 % ohne Personen mit „x von y Ordnern ganz ohne“) + Balken, dann:
  1. ~~**Zu erledigen in Lightroom**~~ – **seit v0.6.13 in `lightroom_pruefen.py`** (dort aus dem Katalog statt aus den Exporten; die Übersicht zeigt nur noch einen Hinweis darauf und die Info-Tabelle „Ohne GPS / ohne Personen je Ordner“). Frühere Fassung (v0.6.9, aus den Exporten): oben „So gehst du vor“ (Ordner im Folders-Panel öffnen, Bild über *Library Filter › Text › Filename › contains* finden, ändern, neu exportieren mit zugeklappten Stapeln, sync.bat, aufraeumen.bat). Darunter **je Lightroom-Ordner** (Pfad unter `D:\Bilder - Raw`) aufklappbar eine Tabelle: **Datei in Lightroom** (Originaldateiname bzw. „(ganzer Ordner)“) · **Aufnahmezeit** · **Problem** · **Was tun in Lightroom** (englische Menüwege). Aufgabenarten:
     - Ordner: oberster Ordner ohne Jahreszahl; Ereignisordner im falschen Jahresordner; Ordnername ohne Jahreszahl; Leerzeichen am Anfang/Ende/doppelt → `Folders-Panel: Rechtsklick › Rename…` bzw. verschieben. Unterordner sind erlaubt.
     - Ordnername doppelt → einen umbenennen.
     - Jahr passt nicht / Datum unplausibel / Ordnerdatum ungültig → `Metadata › Edit Capture Time…` bzw. Ordner umbenennen.
     - **2 Fassungen**: Original + virtuelle Kopie beide sichtbar (nicht gestapelt), beide würden exportiert → `Photo › Stacking › Group into Stack` (Strg+G), gewünschte Fassung `Move to Top of Stack` (Umschalt+S), oder Kopie löschen. Erkannt an: mehrere Exporte vom selben Original im selben Durchgang (≤ 10 min).
     - **RAW + JPG** vom selben Foto im Ordner → falls zwei Kacheln: JPG entfernen oder `Edit › Preferences › General › Treat JPEG files next to raw files as separate photos` aus.
     - **gleiche Zeit**: mehrere verschiedene Fotos mit exakt gleicher Aufnahmezeit (Scans mit Ersatzdatum) → `Edit Capture Time…` je Foto; bei Serienbildern nichts tun.
     - **Ohne GPS / ohne Personen je Ordner – nur Info** (zugeklappt, zählt nicht als Aufgabe): Tabelle Ordner · exportiert · ohne GPS · ohne Personen (Anzahl und %).
  2. **Aufräumen in D:\Fotoschatz:** Exporte ohne passendes Original; doppelt exportiert (**älterer Export aus einem früheren Durchgang**, > 10 min älter als der neueste; neuester bleibt); **RAW und JPG beide exportiert** (Export aus der JPG-Datei ist überflüssig, der aus der RAW-Datei bleibt; v0.6.8); nicht verwendbare Exporte (SCHWER).
     - Mehrere Exporte vom selben Original aus **demselben Durchgang** (≤ 10 min) räumt das Tool nicht weg (es weiß nicht, welche Fassung oben im Stapel liegt) – sie stehen als Aufgabe „2 Fassungen“ in der Lightroom-Liste. Am PC waren das 3 Fälle bei Göbel (nicht gestapelte virtuelle Kopien).
  3. **Ordner wie in Lightroom** (v0.6.7): oberste Ebene mit den echten Ordnernamen unter `D:\Bilder - Raw` (neueste zuerst, Namen ohne Jahreszahl zuletzt), darin die Unterordner mit Pfad ab dort (z. B. `1936-1985 Familie Göbel\Briefe`), „lose Bilder → JJJJ Weitere Bilder“ bzw. „Bilder direkt in diesem Ordner“ am Ende. Ampel je Ordner, Hinweise nach Art (`⚠ 3 Jahr passt nicht · 1 Datum unplausibel`) und grau `📍 40 % ohne GPS · 👤 70 % ohne Personen` (Anteil der exportierten Bilder, v0.6.10; ohne Export „📍 – · 👤 –“; Personen = markierte Personen plus Stichwörter mit bekanntem Personennamen, wie im Sync-Tool); aufgeklappt Hinweise und fehlende Originaldateien. Filter „Nur offene“ (fehlendes GPS allein gilt als erledigt) und „Viele ohne Personen“ (≥ 50 % der exportierten Bilder ohne Personen – dort lohnt sich das Benennen in Lightroom, Taste O).
  - **Stand der Gesichtserkennung in Lightroom** sieht die Übersicht nicht (nur benannte Personen in den Exporten). In Lightroom: *Activity Center* (oben links) › *Face Detection*; Ordner öffnen, Taste **O** (*People*): *Named People* / *Unnamed People*.
  4. **Weitere Angaben:** leere Ordner, `_`-Ordner, Videos, Dateiarten.
- Zählfehler behoben (v0.6.8): „Ordner: ● n“ je Gruppe zählte Bilder statt Ordner.
- Lightroom zählt je Ordner mehr als die Übersicht (z. B. 163 statt 147 bei Göbel/Schäfer): virtuelle Kopien und evtl. RAW+JPG als zwei Bilder. Maßgeblich: die Übersicht meldet keine fehlenden Originale.
- Sicherheit: Abbruch, wenn Skript im Originalordner liegt oder Export- und Originalordner sich überschneiden. In der Cloud geprüft: Originalordner vor/nach dem Lauf identisch (Namen, Größen, Zeiten, Prüfsummen).
- Bekannte Unschärfe: Bilder in Lightroom-**Stapeln** (nur das oberste wird exportiert) erscheinen als „nicht exportiert“. Genau geht es über die Katalog-Kopie (siehe „Lightroom-Katalog“).

### Lightroom-Katalog (v0.6.11, Diagnose)
- Katalog: `C:\Daten\Lightroom Catalog` (Ordner mit der `.lrcat`-Datei; Einstellung `catalog` in `config.local.json`, erlaubt Ordner, Datei oder Name ohne Endung). Im Ordner liegen mehrere Kataloge (`Lightroom Catalog-v13-3.lrcat`, `…-v13.lrcat`, alte nach Lightroom-Updates, werden von mir gelöscht) → **benutzt wird immer der zuletzt geänderte** (Entscheidung 29.09.2026, v0.6.12); die Diagnose zeigt, welcher benutzt wurde und welche übergangen. Die `.lrcat` ist eine SQLite-Datenbank, Aufbau von Adobe nicht dokumentiert (Quellen: `hfiguiere/lrcat-extractor` `doc/lrcat_format.md`, `camerahacks/lightroom-database`).
- **Original-Katalog wird nur gelesen** (Freigabe 29.09.2026: „Kopie OK, Original nicht zum Schreiben anfassen“): `katalog.py` kopiert ihn nach `_sync\katalog\` und öffnet nur die Kopie (Sperre im Code: nur Pfade unter `_sync\katalog`). Das Original wird nie mit SQLite geöffnet (SQLite legt sonst Hilfsdateien daneben an). Ein vorhandenes `-wal` (nach Absturz) wird mitkopiert.
- Abbruch, wenn Lightroom offen ist (`<Katalog>.lrcat.lock` vorhanden oder `Lightroom.exe` läuft) oder sich der Katalog beim Kopieren ändert.
- `katalog_diagnose.py`: gibt Tabellen, Spalten und Anzahlen aus, dazu gezielte Prüfungen (Version, Wurzelordner, Bilder/virtuelle Kopien/Stapel, Katalog ↔ Platte nur über Dateinamen, Stichwörter inkl. „nicht beim Export“ und fast gleiche Namen, Gesichter benannt/Vorschlag/ohne Namen je Ordner, GPS/Stadt/Beschreibung, Sammlungen) → `katalog_diagnose.txt` an Claude schicken. In der Cloud mit einem nachgebauten Katalog getestet; ⚠ am echten Katalog prüfen, welche Tabellen/Spalten es gibt.

### Zwei getrennte Tools (Entscheidung 29.09.2026)
- **Tool 1 „Lightroom prüfen“** (`lightroom_pruefen.py`, v0.6.13): sagt nur, was **in Lightroom** zu korrigieren ist. Es korrigiert nichts, und auch ich korrigiere nichts außerhalb von Lightroom (sonst Sync-Probleme).
- **Tool 2 „Web-Upload“:** `sync.bat`/`probelauf.bat` (hochladen), `uebersicht.bat` (was ist exportiert/online), `aufraeumen.bat` (überflüssige Exporte).
- ⚠ Noch offen: Die Übersicht könnte mit der Katalog-Kopie genau sagen, welche Bilder noch nicht exportiert sind (Stapel berücksichtigt). Bisher nicht gebaut, weil die Übersicht dann Lightroom geschlossen bräuchte.

### Lightroom prüfen `lightroom_pruefen.py` (v0.6.13, v0.6.21: location-ok + GPS nachtragen)
- Lightroom schließen, `lightroom_pruefen.bat` doppelklicken → Katalog-Kopie (`katalog.py`) + Dateiliste von `D:\Bilder - Raw` → `lightroom_pruefen.html` im Standard-Browser (Fenster schließt sich, bleibt nur bei Fehlern offen). Dauer am echten Katalog ⚠ noch nicht gemessen (Diagnose: 8 s).
- **Geprüft werden nur Bilder unter `D:\Bilder - Raw`**. Andere Wurzelordner im Katalog (`F:\PORTFOLIO-RAW` – gibt es nicht mehr, soll ignoriert werden; `C:\Users\chris\Pictures`, 3 Bilder) stehen nur unter „Weitere Angaben“ mit Anleitung *Folders-Panel › Rechtsklick › Remove…* (vorher Katalog-Sicherung).
- **„Für die Galerie“** = nicht in einem `_`-Ordner und im Stapel oben (bzw. nicht gestapelt) – genau das, was mit *Collapse All Stacks* + Strg+A exportiert wird.
- **Aufgaben je Lightroom-Ordner** (Tabelle Datei · Aufnahmezeit · Problem · Was tun, englische Menüwege):
  - Ordner: wie bisher (`check_folder` aus der Übersicht), Ordnername doppelt.
  - Aufnahmezeit: dieselben Regeln wie das Sync-Tool – aus Ordnername + `captureTime` wird der künftige Export-Dateiname gebildet und mit `regeln.analyze_name` geprüft (Jahr passt nicht, Datum unplausibel); keine Aufnahmezeit.
  - **2 Fassungen**: Original und Bearbeitung (`…-Edit` usw.) bzw. virtuelle Kopie nicht gestapelt → beide in der Galerie. **2 Kacheln**: gleicher Dateiname, andere Endung (z. B. RAW und JPG getrennt). **Stapel: Original oben**: im Stapel liegt die unbearbeitete Fassung oben (gewollt → nichts tun).
  - **gleiche Zeit** (≥ 2 Fotos, gleiche Sekunde, z. B. Scans mit Ersatzdatum); **abgelehnt** (Markierung X, sichtbar); **gelöschtes Handybild** (`.trashed-…`).
  - **Katalog ↔ Platte** (auch in `_`-Ordnern): **Datei verschoben** (fehlt in Lightroom, liegt gleichnamig nicht importiert in einem anderen Ordner → Fragezeichen › *Locate…*), **Datei fehlt**, **nicht importiert** (→ *Synchronize Folder…*; in `_`-Ordnern nur gezählt).
- **Stichwörter:** Tabelle aller Stichwörter (Art Person/Stichwort, Oberbegriff, Anzahl Bilder, Empfehlung: doppelt → zusammenführen, 0 Bilder → *Metadata › Purge Unused Keywords*, `ignore_keywords` → Verwaltung, bleibt). Am echten Katalog: 8 Namen doppelt (Jonas, Inge, Eugen, Hedwig, Magdalene, Walter, Uli, Lutz – Personen-Stichwort + normales Stichwort unter „Person“); für die Galerie egal, nur Ordnung.
- **Personen und Orte je Ordner – nur Info** (Entscheidung 29.09.2026: Gesichter nur als Info, keine Aufgaben): Bilder · Namensvorschläge offen (`AgLibraryKeywordFace.userPick = 0`) · Gesichter ohne Namen · bestätigt (`userPick = 1`) · ohne Gesichtserkennung (`Adobe_libraryImageFaceProcessHistory.lastFaceDetector` leer) · ohne GPS (ohne `location-ok`, seit v0.6.21) · GPS ohne Stadt; Spalten per Klick sortierbar, sortiert nach offenen Vorschlägen. Dazu Ortsnamen in mehreren Schreibweisen (gleich bis auf Groß/klein, Akzente, Satzzeichen, z. B. Zurich/Zürich).
- Am echten Katalog (Diagnose 29.09.2026): 25.808 Gesichter, 13.448 bestätigt, 9.462 Vorschläge offen, 2.898 ohne Namen; 1.777 Bilder nicht gescannt (vermutlich `F:`); 0 virtuelle Kopien, 272 Stapel; 5 Comer-See-Dateien im Explorer aus `2026\_Import` verschoben; 1.444 Bilder GPS ohne Stadt.
- **GPS nachtragen** (v0.6.21, Wunsch 01.10.2026): eigener Abschnitt mit Kachel. Je Ordner mit Bildern ohne GPS (nur „für die Galerie“, ohne `location-ok`): ohne GPS · **mit Spur ≤ 1 h** (Punkt der Google-Zeitachse aus `_sync\google\*.json` oder ein Foto mit GPS aus dem ganzen Katalog höchstens 1 h daneben) · davon Zeitachse · davon Foto mit GPS · + über Lücke (v0.6.22, siehe „Lücken füllen“) · location-ok · Vorschlag („gps_test.bat mit „<Ordner>““ ab halber Abdeckung, sonst teilweise bzw. „von Hand auf die Karte ziehen oder location-ok“). Sortiert nach „mit Spur“. v0.6.24: Spaltenköpfe umbrechen, Ordner- und Vorschlag-Spalte mit Mindestbreite (vorher am PC abgeschnitten). Zeitachse wird mit `gps_test.timeline_points` gelesen; in die Seite kommen nur Anzahlen und Zeitraum, keine Koordinaten. Falsche Kamera-Uhr verfälscht die Zahl (gps_test prüft die Uhr). In der Cloud mit nachgebautem Katalog + Mini-Zeitachse getestet (Spur über Foto, über Zeitachse, keine Spur, location-ok – alle richtig; Katalog und Originale unverändert).
- ⚠ Unbestätigte Namensvorschläge landen vermutlich nicht im Export (nicht geprüft).
- In der Cloud mit einem nachgebauten Katalog getestet (alle Aufgabenarten; Katalog und Originale danach unverändert).

### GPS nachtragen (v0.6.14, Test)
- Ziel: Fotos ohne GPS (meist Kamera) bekommen ihren Ort **in Lightroom** über eine GPS-Spur: *Map › Tracklog › Load Tracklog…* › Fotos markieren › *Auto-Tag Selected Photos*. Das Tool schreibt nur die Spur-Datei, nie in Fotos, Katalog oder Originale.
- Quellen: (1) Fotos **mit** GPS im selben Zeitraum (±1 Tag, ganzer Katalog, meist Handyfotos) aus der Katalog-Kopie; (2) **Google-Zeitachse**, vom Handy exportiert (*Einstellungen › Standort › Standortdienste › Zeitachse › Zeitachsendaten exportieren*, seit 2024/25 nur noch am Handy, nicht mehr Takeout), abgelegt als `_sync\google\*.json`. Gelesen werden Android-Export (`semanticSegments`: Weg/Aufenthalt/Bewegung, `rawSignals`), iPhone-Export (Liste) und alter Takeout (`locations`).
- **Datenschutz (Entscheidung 01.10.2026: Daten bleiben auf dem PC):** `_sync\google\`, `_sync\gpx\` und `gps_test.txt` sind per `.gitignore` ausgeschlossen. `gps_test.txt` enthält nur Anzahlen, keine Koordinaten – nur diese Datei geht an Claude.
- `gps_test.bat` fragt nach einem Teil des Ordnernamens (Standard „Japan“) und gibt aus: Fotos je Kamera mit/ohne GPS/`location-ok`; Zeitachse (Format, Jahre, Punkte im Zeitraum, Zeitzonen); Genauigkeit der Zeitachse gegen Fotos mit GPS (Median/90 %); **Kamera-Uhr**: für jede Kamera die Verschiebung (−12…+12 h), bei der die meisten Fotos ohne GPS ein Handyfoto ≤ 10 min daneben haben (erkennt Heimatzeit statt Ortszeit); Abdeckung (Abstand zum nächsten Punkt ≤ 5 min / 15 min / 60 min / 3 h); schreibt `_sync\gpx\<Ordner>.gpx` (Abschnitte bei Lücken > 2 h).
- Zeiten: Lightroom-Aufnahmezeit = Ortszeit ohne Zeitzone; Zeitachse mit Zeitzone → Ortszeit; reine UTC-Punkte (Rohsignale) bekommen die Zeitzone der Abschnitte daneben. In die GPX-Datei kommt die Ortszeit, umgerechnet über die PC-Zeitzone. ⚠ Annahme: Lightroom liest Kamerazeiten ohne Zeitzone genauso (PC-Zeitzone) – am PC prüfen. Ging die Kamera-Uhr falsch, zuerst in Lightroom *Metadata › Edit Capture Time… › Shift by set number of hours* (richtet auch die Reihenfolge in der Galerie).
- `location-ok` = mein Merker „bewusst ohne GPS, schon entschieden“ – der GPS-Test und „Lightroom prüfen“ (v0.6.21) lassen diese Bilder aus. ⚠ Noch offen: das Sync-Tool meldet bei ihnen weiter den Hinweis „keine GPS-Daten“.
- In der Cloud mit nachgebautem Katalog + Zeitachse getestet (Kamera-Uhr 7 h daneben erkannt, Zeitachse auf ~56 m an den Handyfotos).
- **Am PC, Japan (01.10.2026, v0.6.14):** Zeitachse 137 MB, 338.579 Punkte, 04/2017–10/2026 (alles Android-Format). Japan-Ordner: 452 Bilder, RICOH GR III 234 ohne GPS, Pixel 8 216 mit GPS; Ricoh-Uhr stimmte (beste Verschiebung 0 h). **Fehler gefunden:** alle Zeitachsen-Punkte im Japan-Zeitraum hatten „+2 h“ – der Android-Export schreibt die Zeiten in der Zeitzone des Handys **beim Export**, nicht der Ortszeit → Zeitachse 7 h daneben (Median 7 km Abstand zu Handyfotos).
- **v0.6.15:** Ortszeit aus `startTimeTimezoneUtcOffsetMinutes`/`endTimeTimezoneUtcOffsetMinutes` der Abschnitte (⚠ Feldname aus dem Android-Format, am echten Export bestätigen); zusätzlich **Selbstkontrolle**: Verschiebung −14…+14 h, bei der die Zeitachse am besten zu den Fotos mit GPS passt (Median-Abstand), wird angewendet, wenn sie den Abstand mindestens halbiert. In der Cloud beide Fälle getestet (mit Feld: direkt richtig; ohne Feld: +7 h erkannt).
- **Am PC, Japan (v0.6.15):** Zeitzonen-Feld bestätigt (34.253 Abschnitte mit, 18.695 ohne). Ergebnis: 140 von 236 Ricoh-Fotos mit Punkt ≤ 5 min, 64 ≤ 15 min, 29 ≤ 60 min; Median 73 m. Fehler: die globale +7-h-Korrektur verschob auch die schon richtigen Punkte (90 % unter 8,8 km).
- **v0.6.16:** Abschnitte **ohne** Zeitzonen-Feld gelten als unzuverlässig (Export-Zeitzone) und bekommen die Zeitzone der Abschnitte mit Feld daneben (≤ 36 h), wie die Rohsignale. Kamera-Uhr-Warnung erst ab 10 Fotos je Kamera. In der Cloud mit gemischtem Export getestet (alle Punkte +9 h, keine Verschiebung nötig).
- **Am PC bestätigt (01.10.2026, v0.6.16):** Japan: Median 52 m, 90 % unter 516 m; 233 von 236 Ricoh-Fotos mit Punkt ≤ 60 min. **Lightroom-Auto-Tag mit der GPX-Datei hat gepasst** („sieht gut aus“) → Annahme „Lightroom liest Kamerazeiten in der PC-Zeitzone“ bestätigt, *Set Time Zone Offset* bleibt auf 0.
- Ablauf in Lightroom: Library › Ordner › Library Filter › Metadata › Camera (Kamera ohne GPS) → Map › *Map › Tracklog › Load Tracklog…* (`_sync\gpx\<Ordner>.gpx`) → erst 5–10 Fotos markieren › *Map › Tracklog › Auto-Tag Selected Photos* › auf der Karte prüfen (sonst Strg+Z) → dann Strg+A › Auto-Tag → neu exportieren, sync.bat.
- Weitere Ordner mit vielen Fotos ohne GPS (Stand 30.09.2026, gesamt ≈ 1.100 in der Galerie): Lausanne Street Photography 296, Werner 70. Geburtstag 42, Paris Wochenende allein 36, Erasmus Lyon 2002 35, Weihnachten Neuenrade 28, Göbel-Scans, Lüdenscheid-Scans. Ab 04/2017 deckt die Zeitachse ab; davor nur Fotos mit GPS bzw. von Hand (Fotos auf die Karte ziehen) oder `location-ok`.
- **Paris (v0.6.16):** Ricoh 36 ohne GPS, Spur gut (alle ≤ 60 min, ~200 m), aber Kamera-Uhr-Warnung „−3 h“ war Zufall (je 7 Treffer bei −3/−4/−6 h, kaum Handyfotos zum Vergleich).
- **Kamera-Uhr-Prüfung v0.6.18 (Regeln von mir, 01.10.2026):** Handyfotos haben immer die richtige Zeit; Ricoh u. a. Kameras und andere Zeitzonen sind die Ausnahme; die meisten Fotos entstehen 8–20 Uhr.
  - Vergleich Kamera ↔ Handyfoto: Treffer = Handyfoto ≤ 2 min daneben (gleiche Szene); „zufällig“ = Median der Treffer über −12…+12 h.
  - In Frage kommen nur typische Fehler: Heimatzeit statt Ortszeit (Unterschied aus der Zeitachse: Ortszeit − PC-Zeitzone am Reisebeginn), ±1 h (Sommer-/Winterzeit), Heimatzeit ±1 h; bei Gleichstand gewinnt Heimatzeit. Untypische Verschiebungen nur bei sehr klarer Übereinstimmung (≥ 10 Treffer, ≥ 3× zufällig, ≥ halbe Fotos).
  - Regeln: typische Verschiebung, wenn Treffer ≥ 2× zufällig + 3 und ≥ 1,5× Treffer ohne Verschiebung + 3; sonst Tageszeit: ohne Verschiebung < 60 % zwischen 8 und 20 Uhr, mit typischer Verschiebung ≥ 85 % (und +30 Punkte).
  - Ausgabe je Kamera (ab 5 Fotos): „Uhr stimmt“ / „Uhr stimmt vermutlich“ / „⚠ Uhr vermutlich um +X h daneben (Grund)“ mit Lightroom-Weg *Edit Capture Time… › Shift by set number of hours* / „unklar“ mit Prüfanleitung.
  - In der Cloud mit 10 nachgebauten Fällen getestet (Heimatzeit, richtig, ±1 h, Heimatzeit+1 h, wenig/viele/keine Handyfotos) – alle richtig.
- **Werner 70. Geburtstag (v0.6.18, am PC):** Fehler gefunden – (1) die Zeitzonen-Selbstkontrolle hat die Zeitachse um −4 h verschoben, obwohl ohne Verschiebung < 10 Vergleiche möglich waren (nur 10 Handyfotos vom Vortag); (2) ein Aufenthalt (Feier) hat in der Zeitachse nur Anfangs- und Endpunkt → 34 von 42 Fotos > 60 min vom nächsten Punkt. Diese GPX-Datei nicht verwenden.
- **v0.6.19:** Selbstkontrolle verschiebt nur noch, wenn es ohne Verschiebung mindestens 10 Vergleiche gibt und die Verschiebung den Abstand halbiert und unter 1 km bringt; bei Gleichstand gilt 0 h. Aufenthalte (≤ 24 h) bekommen alle 10 min einen Punkt am selben Ort. In der Cloud getestet (Feier 9–18 Uhr, Handyfotos nur am Vortag: alle 42 Fotos ≤ 5 min, keine Verschiebung; frühere Testfälle unverändert richtig).
- **Am PC (v0.6.19):** Werner 70: alle 42 ≤ 5 min, keine Verschiebung ✔. Weihnachten Neuenrade: alle 28 ≤ 5 min, Median 4 m ✔. Comer See: alle 73 Fotos (Pixel) haben schon GPS. Lausanne: 300 Ricoh, nur 12 Handyfotos; Spur gut (254 ≤ 5 min, Median 39 m), aber Uhr-Warnung „+1 h“ beruhte auf nur 3 Treffern → Fehlalarm-Gefahr.
- **Lausanne am PC (v0.6.20):** Auto-Tag legte die Fotos auf die Bahnstrecke Morges → Lausanne → Ricoh-Uhr ging doch 1 h nach (der „schwache Hinweis +1 h“ beruhte auf nur einem Handyfoto, war aber richtig). Mit *Edit Capture Time +1 h* korrigiert, danach „Uhr stimmt vermutlich“. Gelernt: Lightroom zählt Fotos in zugeklappten Stapeln beim Ordner mit (301), zeigt im Raster nur die obersten (298) → vor *Edit Capture Time* und Auto-Tag *Expand All Stacks*. Im Track-Menü „All Tracks“ wählen (Ordner mit 2 Tagen).
- **Lücken füllen (v0.6.22, Idee 2 vom 01.10.2026):** Liegen zwei aufeinanderfolgende Punkte (Zeitachse + Fotos mit GPS) mehr als 30 min und höchstens 3 h auseinander und höchstens 1 km voneinander entfernt (z. B. Abend im Restaurant), kommt alle 10 min ein Punkt dazwischen (gleichmäßig zwischen beiden) – in die GPX-Datei und in die Abdeckung (`gps_test.fill_gaps`, Zeile „dazu Lücken gefüllt“ + Anzahl Lücken). Größere Entfernung = man war unterwegs → nicht gefüllt. „Lightroom prüfen“ zählt das als Spalte „+ über Lücke“. In der Cloud getestet (Restaurant 18:00–20:50: 6 Fotos von > 60 min auf ≤ 5 min; Ortswechsel 5 km: nicht gefüllt; frühere Testfälle unverändert).
- **v0.6.20:** Uhr-Befund braucht mindestens 5 Paare (Kamera ↔ Handyfoto ≤ 2 min); Zufallsmaß = beste **untypische** Verschiebung ±2…±6 h, ein Befund muss ≥ 1,5× davon + 3 sein. Wenige Treffer → „unklar – schwacher Hinweis auf …“ mit den Paaren (Dateinamen + Uhrzeiten) zum Nachprüfen in Lightroom; bei einem Befund werden bis zu 5 Belege genannt. Keine Fotos ohne GPS → „nichts zu tun“. In der Cloud mit 56 Zufalls-Läufen getestet: 55 richtig, 1 vorsichtig „unklar“, 0 falsch.

### Zeitachse prüfen `zeitachse_pruefen.py` (v0.6.26, **v0.6.27 neu gebaut**, Wunsch 03.10.2026)
- **v0.6.27 (mein Wunsch: „ich will sehen, wo das Bild laut Google hin soll und wie weit es weg ist, absteigend die größten Ausreißer; Copy/Paste einfach“):** Eine Liste **aller** Fotos mit GPS, die ≥ 1 km neben der Zeitachse liegen, **sortiert nach Abstand, größte zuerst** (max. 3.000 Zeilen). Je Zeile: Abstand · Datei mit Knopf *Kopieren* (kopiert den Dateinamen **ohne** Endung – mit Endung fand die Lightroom-Suche `R0004574.DNG` nicht) · Kamera · Aufnahmezeit · Ordner · **Jetzt in Lightroom** (Stadt, Land, Koordinaten, Kartenlink) · **Laut Google** (Koordinaten `lat, lng` mit *Kopieren* zum Einfügen ins GPS-Feld im Metadata-Panel – ⚠ Format am PC prüfen; Kartenlink; „Zeitachse ±x min“) · Link „beide“ (Route in Google Maps) · Häkchen *erledigt* (im Browser gemerkt, `fotoschatz.zeitachse.done`). Filter „Zeigen ab 1/5/20/100 km“, „Erledigte ausblenden“. Anleitung oben (All Photographs › Filename › Contains › Strg+V; Lightroom stimmt → erledigt; Google stimmt → Koordinaten einfügen; ganze Serie → Kamera-Uhr). Kamera-Uhr-Prüfung zugeklappt darunter.
- **Datenschutz:** `zeitachse_pruefen.html` enthält jetzt Koordinaten → bleibt auf dem PC (nicht an Claude). Für Claude: `zeitachse_pruefen.txt` (Anzahlen je Abstandsstufe, Ordner mit den meisten Ausreißern, die 30 größten mit Datei/Zeit/Kamera/Ordner, Uhr-Hinweise – **keine Koordinaten**). Beide per `.gitignore` ausgeschlossen. `read_catalog` liefert dafür Stadt und Land (`place`).
- In der Cloud getestet (Ausreißer 223/50/11/2 km richtig sortiert, Kopieren-Knöpfe im Browser geprüft, Filter und „erledigt“ nach Neuladen erhalten; Katalog unverändert; Syntax auch für Python 3.8 geprüft).
- Bisherige Fassung v0.6.26:
- Lightroom schließen, `zeitachse_pruefen.bat` → Katalog-Kopie (über `lightroom_pruefen.read_catalog`, jetzt mit Kameramodell) + `_sync\google\*.json` → `zeitachse_pruefen.html` im Browser (per `.gitignore` ausgeschlossen; enthält Dateinamen und Abstände, keine Koordinaten). Ändert nichts.
- Geprüft werden nur Bilder „für die Galerie“.
- **1. Kamera-Uhr** je Ordner und Kamera mit denselben Regeln wie `gps_test` (dafür `gps_test.clock_check` als Funktion herausgelöst; Ausgabe von `gps_test` an 34 Testfällen unverändert). Anders als in `gps_test` zählen **alle** Fotos der Kamera (auch mit GPS – findet Fälle wie Lausanne, die schon mit falscher Uhr getaggt wurden). Bezug = Fotos mit GPS von **Handy-Kameras** (≥ 20 Fotos, ≥ 80 % mit GPS, ganzer Katalog, ±1 Tag). Ausgelassen: Handys, Kamera „(unbekannt)“, Aufnahmen vor 2000 (Scans), Gruppen < 5 Fotos. Heimatzeit-Unterschied aus der Zeitachse im Zeitraum. Gemeldet nur „Uhr daneben“ (mit Shift-Wert, Belegen, Hinweis „x haben schon GPS – neu zuordnen“) und „unklar – schwacher Hinweis“ mit Paaren.
- **2. GPS gegen Zeitachse** (Fotos mit GPS ab Beginn der Zeitachse): Ort laut Zeitachse zur Aufnahmezeit = zwischen den Punkten davor/danach (je ≤ 15 min) gleichmäßig, sonst nächster Punkt ≤ 5 min; Abstand > 3 km → Liste je Ordner (Datei, Zeit, Kamera, Abstand; max. 40 je Ordner) mit Median aller. Gründe laut Seite: von Hand falsch platziert, Uhr falsch, Foto von jemand anderem (dann richtig), Zeitachse ungenau.
- In der Cloud mit nachgebautem Katalog getestet (Ricoh-Uhr −1 h mit 10 schon getaggten Fotos → „+1 h daneben“ mit 5 Belegen; Ricoh und Canon richtig → nicht gemeldet; ein Handyfoto 50 km daneben → gemeldet, die anderen 14 nicht; Scans übergangen; Katalog und Originale unverändert). ⚠ Am echten Katalog: Dauer, Zahl der Fehlalarme.

### Personen prüfen `personen_pruefen.py` (v0.6.28, Wunsch 03.10.2026: „alle wichtigen Bilder sollen erkannte Personen haben“)
- **Gelernt (Recherche + Katalog):** Gesicht benennen **und bestätigen** → Lightroom setzt ein Personen-Stichwort (`keywordType = 'person'`) aufs Bild. Nur vorgeschlagen („Uli?“, `userPick = 0`) → kein Stichwort. Stichwort von Hand → kein Gesichtsrahmen. Bekannte Lightroom-Fehler: benanntes Gesicht ohne Stichwort (Abhilfe: Name am Rahmen anklicken, Enter); Keyword-Spalte im Metadaten-Filter aktualisiert sich nach dem Bestätigen nicht (Lightroom neu starten oder Spalte umstellen) → „Keyword › None“ im Filter ist **unzuverlässig** (am PC gesehen: Bild mit Uli unter „None“). Lightroom kann nicht nach „kein Gesicht erkannt“ filtern. Am echten Katalog 8 Namen doppelt (Personen-Stichwort + von Hand unter „Person“) = früher von Hand vergeben.
- Lightroom schließen, `personen_pruefen.bat` → Katalog-Kopie → `personen_pruefen.html` (Datei- und Personennamen, bleibt auf dem PC) + `personen_pruefen.txt` (nur Anzahlen und Ordnernamen, für Claude). Beide per `.gitignore` ausgeschlossen. Ändert nichts. Nur Bilder „für die Galerie“.
- **Person** = bestätigtes Gesicht **oder** Stichwort mit bekanntem Personennamen (wie im Sync-Tool). Bekannte Namen = Personen-Stichwörter, Stichwörter unter „Person/Persons/Personen/People“, Namen bestätigter Gesichter.
- **Diagnose (Kacheln):** Person über Gesicht und Stichwort · nur Gesicht · nur Stichwort (von Hand) · ohne Person · Gesicht bestätigt, aber Stichwort fehlt · Sterne-Verteilung (`Adobe_images.rating`, jetzt in `read_catalog`).
- **v0.6.29:** oben eigene Liste „★★ Lieblingsbilder und ★ wichtige Bilder ohne Person“ über alle Ordner (Lieblingsbilder zuerst, mit Ordner-Spalte und „alle Dateinamen kopieren“); Filter „alle / ★ wichtig und ★★ / nur ★★“; Bilder mit `personen-egal` werden nicht gemeldet (Kachel mit Anzahl). In der Cloud getestet (Lieblings- vor wichtigen Bildern, `personen-egal` ausgelassen; `gps_test` an 34 Testfällen bis auf die Beschriftung „ort-egal“ gleich).
- **Gründe ohne Person** (schnellste Abhilfe zuerst): Name vorgeschlagen · Gesicht ohne Namen · kein Gesicht erkannt (selbst ansehen, *Draw Face Region*) · nicht nach Gesichtern durchsucht. Dazu „Stichwort fehlt“ (hat Person, Lightroom-Fehler) mit in der Liste.
- **Ordner:** „Ordner mit Personen“ (≥ 20 % der Bilder mit Person – dort fehlen Namen am ehesten), sortiert nach Anzahl ohne Person; „Ordner mit wenig Personen“ (Landschaft/Street) zugeklappt. Je Ordner Tabelle Datei (Kopieren ohne Endung) · Aufnahme · Sterne · Grund · Erkannt; Knopf „alle Dateinamen kopieren“ (mit Leerzeichen, für *Filename › Contains* – ⚠ am PC prüfen, ob Lightroom dann alle zeigt). Filter „ab ★…★★★★“ (Bewertungen sind laut mir bisher kaum gepflegt – Pflege ist noch offen).
- In der Cloud mit nachgebautem Katalog getestet (alle Fälle richtig zugeordnet, Kopieren und Sterne-Filter im Browser geprüft, Katalog unverändert, Syntax für Python 3.8).

### Aufräumen `aufraeumen.py` (v0.6.6, v0.6.8: Gruppe „RAW und JPG beide exportiert“, virtuelle Kopien ausgenommen)
- Nutzt dieselbe Auswertung wie die Übersicht. Zeigt je Gruppe (ohne Original / doppelt / nicht verwendbar) die Dateien und fragt „j/n“; bei „doppelt“ Warnung wegen gewollter virtueller Kopien.
- **Verschiebt** nach `_sync\geloescht\<Datum-Uhrzeit>\` (nicht endgültig löschen; rückgängig = zurückschieben), Protokoll in `_sync\aufraeumen_protokoll.txt`. Beim nächsten Sync verschwinden die Bilder online; warnt, wenn das mehr als `max_delete` wären.
- Sicherheit: bewegt nur `.jpg` direkt in `D:\Fotoschatz`; Abbruch bei allem unter `D:\Bilder - Raw`, bei Unterordnern oder Nicht-JPGs (in der Cloud geprüft, Originalordner unverändert).

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
      "r": 4,
      "fp": [0.488, 0.166]
    }
  ]
}
```
- `folders.x = 1` markiert „Weitere Bilder" (in der Ordneransicht am Ende des Jahres).
- `fp` = Fokuspunkt (x, y relativ 0..1): Mitte des Rahmens um alle Lightroom-Gesichtsbereiche (`XMP-mwg-rs:RegionArea*`, Typ Face); fehlt ohne Gesichter.
- `folders.cover` wird vom Sync-Tool noch geschrieben, von der App aber nicht genutzt (keine Titelbilder).
- URLs werden in der App aus `SECRET`, `id` und `h` zusammengesetzt, nicht im Index gespeichert.
- Leere Felder weglassen.
- Größe: ≈ 0,22 KB je Bild → bei 23.000 Bildern ca. 5 MB. **Entscheidung 29.09.2026: `index.json` bleibt unkomprimiert** (einfach, ≈ 5 MB; der Service Worker hält die letzte Fassung, geladen wird sie nur bei Änderungen neu). Falls der Start am Handy zu langsam wird: gzip (`Content-Encoding: gzip`) oder nach Jahren aufteilen.

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

### Installierbarkeit (Android/Chrome) – v0.6.0
- `manifest.webmanifest`: `name`/`short_name` „Fotoschatz“, `id`/`start_url`/`scope` `./`, **`display: "fullscreen"`** (seit v0.6.2, siehe unten), Icons 192 und 512 (+ maskable), Symbol: weißer Bilderrahmen mit Berg und Sonne auf Blau (`docs/icons/`).
- Service Worker `docs/sw.js` registriert → Chrome bietet „App installieren“ an. Zusätzlich zeigt die Ordneransicht oben „Fotoschatz als App auf dem Startbildschirm? [Installieren] [✕]“ (✕ wird gemerkt: `fotoschatz.install-hidden`).
- In der Cloud geprüft: Chrome meldet keine Installierbarkeits-Fehler (außer „Inkognito“ im Testbrowser).
- ✅ Am Handy installiert (28.09.2026). Die Chrome-Meldung „zum Beenden des Vollbildmodus …“ kommt bei **jedem** Vollbild per Fullscreen-API, auch in der installierten App → nicht abschaltbar.
- Lösung v0.6.2: Die installierte App läuft **ganz im Vollbild** (`display: "fullscreen"`, keine Statusleiste, Handy nutzt Gestensteuerung). Kopfzeile hält Abstand zur Kamera-Aussparung (`env(safe-area-inset-top)`). ⚠ Am Handy prüfen, dass dabei keine Chrome-Meldung erscheint. Geänderte Manifest-Einstellungen übernimmt Chrome bei installierten Apps nur verzögert → zum Testen App deinstallieren und neu installieren.
- Einfärben der Statusleiste per `theme-color` (v0.6.1) hat in der installierten App nicht gewirkt (Handy, 28.09.2026) – Code bleibt, schadet nicht.
- v0.6.2 am Handy: keine Chrome-Meldung mehr, aber Statusleiste noch sichtbar. Vermutete Ursache: Der Service Worker lieferte das Manifest aus dem alten App-Cache (noch `standalone`), Android friert die Anzeige beim Installieren ein. Seit v0.6.3 kommt das Manifest immer frisch aus dem Netz; die Fußzeile der Ordnerliste zeigt den tatsächlichen Modus („Anzeige: Vollbild / Fenster / Browser“).
- ✅ v0.6.3 am Handy bestätigt: nach Deinstallieren/Neuinstallieren läuft die App im Vollbild, keine Statusleiste, keine Chrome-Meldung.

### MVP-Ansichten
- **Leiste unten:** Ordner · Alle Bilder · Suche. Kopfzeile oben mit Titel, Untertitel und ggf. Zurück-Pfeil.
1. **Ordner** (Startansicht):
   - **Reine Textliste, keine Titelbilder** (bewusst so entschieden – nichts zu pflegen, nichts zufällig).
   - Jahre absteigend (Überschrift mit Anzahl bleibt beim Scrollen oben), darunter die Ordner neueste zuerst: Name ohne Datumspräfix, darunter Datum · Anzahl; „Weitere Bilder" am Ende des Jahres.
   - Fußzeile: Anzahl Bilder · Stand des Index · App-Version.
2. **Alle Bilder:** Zeitleiste, neueste zuerst, gruppiert nach Monat; der aktuelle Monat steht im Untertitel der Kopfzeile.
3. **Ordnerinhalt:** Raster nach Aufnahmezeit sortiert.
4. **Suche** (v0.5.0, umgebaut v0.6.0):
   - **Zwei Modi:** *Auswahl* (Begriffe wählen, keine Bilder) und *Raster*. Unter dem Suchfeld steht immer die Zahl der passenden Bilder („40 Bilder passen“) und der Knopf **Anzeigen** (bzw. Enter). Anzeigen legt einen Verlaufseintrag an: Zurück-Taste / „Ändern“ führt vom Raster zur Auswahl. Suchfeld oder Chip im Raster antippen → zurück zur Auswahl (Chip wird dabei entfernt). Aus dem Betrachter zurück → Raster.
   - **Auswahl ohne Tippen** – alles gezählt innerhalb der schon gewählten Begriffe, Begriffe ohne Treffer fallen weg:
     - Personen: die 12 häufigsten, „alle … zeigen“ klappt die ganze Liste auf.
     - **Orte als Baum** Land › Bundesland › Stadt › Ort (leere und doppelte Stufen wie Wien/Wien entfallen). Antippen klappt auf, erste Zeile „Ganz <Name>“ wählt den ganzen Zweig; Blätter werden direkt gewählt. Gewählte Orte sind aufgeklappt und blau.
     - Jahre (Aufnahmejahr), Stichwörter (falls vorhanden).
   - **Beim Tippen:** Vorschläge gruppiert nach Personen, Orten (mit Lage, z. B. „Nürnberg – Bayern, Deutschland“), Ordnern (mit Datum), Jahren, Stichwörtern, jeweils mit Anzahl; Gruppe mit exaktem Treffer oben. Erste Zeile „Freitext … übernehmen“: alle Wörter müssen vorkommen in Beschreibung, Orten (deutsch **und** englisch), Ordnername, Personen, Stichwörtern.
   - Gewählte Begriffe werden zu Chips und mit **UND** verknüpft (z. B. Person + Land + Jahr).
   - Groß-/Kleinschreibung, Akzente und Satzzeichen ignorieren (é→e, ä→a, ß→ss, „ile de france“ findet „Île-de-France“).
   - Ergebnis als Raster, neueste zuerst. Chips und Text bleiben beim Tab-Wechsel erhalten.
   - Gemessen mit 23.100 künstlichen Bildern: Aufbau einmalig ≈ 0,13 s, Vorschläge je Tastendruck ≈ 2 ms (Cloud-Rechner; Handy langsamer, aber unkritisch).
   - **Orte auf Deutsch** (in der App, nicht im Sync-Tool – Übersetzungen gehen ohne PC-Schritt live):
     - Länder automatisch über den Browser (`Intl.DisplayNames`, englisch → deutsch, plus einige Schreibvarianten wie „USA“, „Czech Republic“); nur auf das Feld Land angewendet.
     - Bundesländer, Städte, Orte über die Tabelle `docs/orte.js` (`PLACE_DE`), gepflegt von Claude. **Nur allgemein bekannte Namen** (Bavaria → Bayern, Munich → München …) – das Repo ist öffentlich, kleine/private Orte bleiben englisch.
     - Nicht übersetzte Namen erscheinen so, wie Lightroom sie schreibt. Neue Orte kommen automatisch mit dem nächsten Sync in die App.
5. **Vollbild-Betrachter:**
   - Wischen links/rechts, Nachbarbilder vorladen.
   - Tippen: linkes Drittel = zurück, rechtes Drittel = weiter (sofort), Mitte = Bedienelemente aus/ein (mit ≈ 0,3 s Verzögerung wegen Doppeltippen). Wischen links/rechts blättert.
   - **Zoom** (v0.5.0): zwei Finger auf-/zuziehen (bis 4-fach); Doppeltippen in der Mitte bzw. Doppelklick = 2,5-fach an dieser Stelle, nochmal = zurück; am PC Mausrad. Vergrößert: ein Finger/Maus verschiebt den Ausschnitt (nicht über den Bildrand hinaus), Tippen = Bedienelemente, Blättern per Wischen ist aus. Blättern (Taste, Knopf) oder Drehen setzt den Zoom zurück.
   - **Präsentations-Klicker / Tastatur:** weiter = Bild ab, Pfeil rechts, Leertaste; zurück = Bild auf, Pfeil links.
   - Infos (Datum, Ordner, Personen, Ort, Beschreibung – ausgeblendet, wenn gleich dem Ordnernamen –, Bewertung) über den Knopf (i) bzw. Taste I; **anfangs ausgeblendet**, Einstellung wird gemerkt (`fotoschatz.info`).
   - **Kein Vollbild per Fullscreen-API am Handy** (v0.6.1/0.6.2): Chrome blendet dabei jedes Mal „zum Beenden des Vollbildmodus …“ ein. Die installierte App läuft stattdessen komplett im Vollbild (Manifest). Knopf ⛶ bzw. Taste F nur noch am PC. Zurück-Taste schließt das Bild mit einem Druck (am Handy bestätigt).
   - Zurück-Taste, ✕, Wischen nach unten und Esc schließen den Betrachter (History-API); am PC Pfeiltasten und Pfeil-Schaltflächen.
   - Erst das Vorschaubild, dann das große Bild; Nachbarbilder werden vorgeladen.

### Raster & Performance (Anforderung: flüssiges Scrollen bei 10.000 Bildern)
- **Virtuelles Scrollen:** Nur die sichtbaren Zeilen (plus Puffer) existieren im DOM.
- Quadratisches Raster (Bild mittig zugeschnitten), 4 Spalten auf dem Handy, am PC ca. 170 px je Kachel, feste Zeilenhöhe → einfache, sprungfreie Virtualisierung.
- Vorschaubilder mit `loading="lazy"` / `decoding="async"`, Platzhalterfarbe, bis das Bild geladen ist.
- Ausschnitt der Kacheln (Stufe 1, v0.3.2): `object-position: 50% 20%` → Hochformat oben betont (Köpfe). Stufe 2 (v0.4.0): Bilder mit Gesichtern werden um den Fokuspunkt `fp` zugeschnitten (`object-position` aus `fp` und Seitenverhältnis). An echten Exporten geprüft: Gesichtsbereiche stimmen, auch bei zugeschnittenen Bildern (`diagnose.py` → `_sync\gesichter_test\`, rot Gesicht, gelb Ausschnitt).
- Index einmal laden, Suchstrukturen einmal aufbauen (Begriff → Bild-IDs).

### Service Worker – Caching (v0.6.0)
- Alle Cache-Namen beginnen mit `fotoschatz-` (auf `obitusde.github.io` liegen weitere Apps; beim Aufräumen werden nur eigene alte App-Caches gelöscht).
- **App-Dateien:** vorab cachen, Cache-Name `fotoschatz-app-<VERSION>`; Startseite und `?v=`-Dateien aus dem Cache. **Manifest nie aus dem Cache** (immer Netz, v0.6.3).
- **Vorschaubilder** (`fotoschatz-thumb`): cache-first, bis ≈ 10.000 Stück (≈ 160 MB), älteste fliegen raus.
- **Große Bilder** (`fotoschatz-img`): cache-first, die letzten ≈ 300.
- Bilder werden vom Service Worker mit CORS geladen (kein „undurchsichtiger“ Cache); klappt das nicht, normal laden ohne Speichern.
- **`index.json`** (`fotoschatz-data`): network-first, ohne Netz die zuletzt geladene Fassung → App läuft offline mit allen schon gesehenen Bildern (in der Cloud geprüft).
- **Updates:** neue Version → Leiste „Neue Version verfügbar [Neu laden]“ (Prüfung beim Zurückkehren in die App und stündlich). In der Cloud geprüft.

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
- **2b** (v0.5.0): Suche wie oben, dazu Zoom im Betrachter und Präsentations-Klicker. In der Cloud im Browser geprüft (Handy/PC, hell/dunkel, Zwei-Finger-Zoom simuliert). ⚠ Zoom-Gefühl und Klicker am echten Handy prüfen.
- **2c** (v0.6.0): Manifest, Icons, Service Worker (Offline-Cache), „Neue Version verfügbar“, Installieren-Hinweis. Dazu: Suche mit Auswahl-Modus und Trefferzahl, Orte als Baum und auf Deutsch, `orte.txt` im Sync-Tool (sync.py v0.6.0). ⚠ Am Handy: installieren, Start über Symbol, Vollbild-Meldung.
- **2d – Chromecast** (Version 0.7.0, Entscheidung 28.09.2026: Cast-Knopf in der App, nicht Bildschirm spiegeln):
  - Cast Web Sender SDK (von Google geladen) – laut Google unterstützt in Chrome auf Android und am PC, nur über https.
  - Zuerst mit dem fertigen **Default Media Receiver** (keine Registrierung): Betrachter bekommt einen Cast-Knopf, das aktuelle Bild (`img/…jpg` direkt aus R2) wird auf den Fernseher geschickt, Blättern am Handy (auch per Klicker) wechselt das Bild am Fernseher.
  - Laut Google zeigt dieser Empfänger Bilder höchstens in 1280 × 720. Wenn das am Fernseher zu weich ist: eigene Empfänger-App (einmalige Google-Cast-Registrierung, ca. 5 $), Empfängerseite auf GitHub Pages, volle Auflösung.
  - ⚠ Prüfen: 720p-Grenze bei neueren Geräten; ob der Cast-Knopf auch in der installierten App (nicht nur im Browser-Tab) erscheint.
- **Fertig, wenn:** Auf dem Android-Handy installierbar; Start über das App-Symbol ohne erneuten Link funktioniert; Scrollen flüssig; Suche kombiniert Chips korrekt.

### Phase 3 – Erstbefüllung
- Alle Ordner (außer `_Import`) exportieren, voller Sync.
- Index-Größe, Speicherbedarf in R2, Upload-Dauer und Scroll-Performance mit ~10.000 Bildern prüfen.
- Danach Link an die Familie verteilen.

### Phase 4 – Erweiterungen (Reihenfolge nach Absprache)
1. **Rückblick „Heute vor X Jahren"** auf dem Startbildschirm der App:
   - Bilder mit gleichem Tag/Monat aus früheren Jahren, gruppiert nach Jahr.
   - Gibt es am Tag nichts, ±3 Tage.
   - Bevorzugt ★★ Lieblingsbilder, dann ★ wichtige.
2. **„Überrasch mich":** zufällige Auswahl (bevorzugt gut bewertet) oder zufälliger Ordner.
3. **Karte:**
   - Leaflet + OpenStreetMap (Namensnennung und Nutzungsregeln der Kacheln beachten), Cluster mit Anzahl.
   - Antippen → Bilder an diesem Ort.
4. **Umkreissuche:** Punkt auf der Karte wählen + Radius (1 / 5 / 20 / 50 km) → Entfernungsberechnung im Browser → Raster. Zusätzlich „In meiner Nähe" über den Standort des Handys.
5. **Personen-Seite:** alle Personen mit Anzahl; pro Person chronologisch („durch die Jahre").
6. **Best-of-Filter** nach Bewertung (★★ Lieblingsbilder, ★ wichtig – Entscheidung 03.10.2026), kombinierbar mit Suche/Ordner.
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
