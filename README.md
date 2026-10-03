# Fotoschatz

Private Online-Fotogalerie für die Lightroom-Bilder (ca. 23.000), auch fürs Handy. Die Familie sieht sie ohne Konto über einen geheimen Link.

```
Lightroom ──Export──> D:\Fotoschatz ──sync.bat──> Cloudflare R2 (Bilder + index.json)
                                                        │
                        App (GitHub Pages, ordner docs/) ┘  https://obitusde.github.io/fotoschatz/#<geheim>
```

- **`docs/`** = die App (läuft im Browser, installierbar auf Android). Geht nach jedem Push automatisch live.
- **`sync/`** = die Werkzeuge für den PC. Sie liegen dort in `D:\Fotoschatz\_sync\`.
- Alle Einzelheiten und Entscheidungen stehen in [`CLAUDE.md`](CLAUDE.md).

---

## So arbeitest du (normaler Ablauf)

| # | Schritt | Wo |
|---|---|---|
| 0 | **Skripte aktuell halten:** `aktualisieren.bat` | PC |
| 1 | Ordner in Lightroom fertig machen: Personen, Orte, Zeiten, Stapel | Lightroom |
| 2 | **Lightroom schließen** › `lightroom_pruefen.bat` › die Liste in Lightroom abarbeiten | PC + Lightroom |
| 3 | Fehlt GPS: `gps_test.bat` › GPX-Datei in Lightroom laden und Fotos zuordnen | PC + Lightroom |
| 4 | Exportieren: *Collapse All Stacks* › Strg+A › Export mit deiner Vorlage (2048 px, nach `D:\Fotoschatz`) | Lightroom |
| 5 | `probelauf.bat` (zeigt nur an), dann `sync.bat` (lädt hoch) | PC |
| 6 | `aufraeumen.bat` (überflüssige alte Exporte weg) und nochmal `sync.bat` | PC |
| 7 | Ab und zu `uebersicht.bat`: Was ist exportiert und online, was fehlt? Und **Lightroom geschlossen** `zeitachse_pruefen.bat`: Stimmen Kamera-Uhren und GPS? | PC |

**Grundregel:** Korrigiert wird **nur in Lightroom**, danach neu exportieren. Nie Dateien im Explorer umbenennen, verschieben oder ändern, sonst passt der Katalog nicht mehr.

---

## Die Skripte (Doppelklick auf die `.bat`)

| Skript | Was es macht | Was es **nicht** macht / Achtung |
|---|---|---|
| `aktualisieren.bat` | Holt die neuesten Skripte aus diesem Repo. Ersetzt erst, wenn alles geladen ist. | Fasst `config.local.json`, `work\`, `google\`, `gpx\` nicht an. Ersetzt sich selbst nicht; wenn sie sich ändert, einmal von Hand holen. |
| `lightroom_pruefen.bat` | Liest eine **Kopie** des Lightroom-Katalogs und sagt, was in Lightroom zu korrigieren ist. Zum Beispiel: Ordnernamen, falsche Zeiten, nicht gestapelte Fassungen, fehlende oder nicht importierte Dateien, doppelte Stichwörter. Dazu Infos zu Gesichtern und „GPS nachtragen“ je Ordner. | Ändert nichts. **Lightroom muss geschlossen sein.** Das Ergebnis stimmt nur so gut wie der Katalog. |
| `gps_test.bat` | Fragt nach einem Ordnernamen und sucht für Fotos ohne GPS den Ort: aus Handyfotos und der Google-Zeitachse (`_sync\google\*.json`). Füllt Lücken, wenn man am selben Ort blieb. Prüft, ob die Kamera-Uhr falsch ging. Schreibt `_sync\gpx\<Ordner>.gpx` für Lightroom. | Setzt **kein** GPS, das machst du in Lightroom (*Map › Tracklog › Load Tracklog… › All Tracks › Auto-Tag*). Vor April 2017 gibt es keine Zeitachse. Ging die Kamera-Uhr falsch, zuerst in Lightroom *Edit Capture Time* korrigieren. Bei Stapeln vorher *Expand All Stacks*. Erst 5–10 Fotos testen, auf der Karte prüfen. |
| `probelauf.bat` | Wie `sync.bat`, zeigt aber nur an, was passieren würde. | Lädt nichts hoch. |
| `sync.bat` | Prüft alle Exporte in `D:\Fotoschatz`, macht Vorschaubilder und `index.json` und lädt Neues hoch. Geänderte Bilder werden ersetzt, verschwundene Exporte online gelöscht. Probleme stehen in `korrekturen.csv`. | Bilder mit falschem Dateinamen oder ungültiger Zeit werden **nicht** hochgeladen. Bricht ab, wenn mehr als 100 Bilder gelöscht würden (Schutz). Kennt `location-ok` noch nicht und meldet dort „keine GPS-Daten“. |
| `aufraeumen.bat` | Findet überflüssige Exporte (ohne Original, doppelt, RAW+JPG) und **verschiebt** sie nach `_sync\geloescht\` (fragt vorher). | Löscht nicht endgültig. Rückgängig: zurückschieben. Danach `sync.bat`, sonst bleiben sie online. |
| `uebersicht.bat` | Vergleicht Originale, Exporte und Online-Stand. Ergebnis als Seite im Browser. | Sieht Lightroom-Stapel nicht. Bilder in Stapeln können als „nicht exportiert“ erscheinen. |
| `zeitachse_pruefen.bat` | Liste aller Fotos mit GPS (ab 04/2017), die mehr als 1 km neben dem Ort laut Google-Zeitachse liegen, **größte Abstände zuerst**: Abstand, Ort jetzt in Lightroom, Ort laut Google, Kartenlinks, Knöpfe zum Kopieren (Dateiname für die Suche, Koordinaten fürs GPS-Feld), Häkchen „erledigt“. Darunter zugeklappt die Kamera-Uhr-Prüfung für alle Ordner. | Ändert nichts, du korrigierst in Lightroom. **Lightroom muss geschlossen sein.** Die Seite enthält Koordinaten: bleibt auf dem PC, an Claude nur `zeitachse_pruefen.txt`. „Weit weg“ kann richtig sein (Foto von jemand anderem, Flug, Funkloch). Alte Scans und Fotos ohne Kamera-Angabe prüft es nicht. Fotos, die schon mit falscher Uhr eine GPS-Spur bekommen haben, liegen „passend“ zur Zeitachse; die findet nur die Uhr-Prüfung. |
| `personen_pruefen.bat` | Zeigt je Ordner die Bilder **ohne benannte Person** und warum: Name nur vorgeschlagen · Gesicht ohne Namen · kein Gesicht erkannt · nicht durchsucht · Gesicht benannt, aber Stichwort fehlt (Lightroom-Fehler). Ordner mit vielen Personenbildern zuerst, Filter nach Sternen, Knöpfe zum Kopieren der Dateinamen. Oben eine Diagnose, woher die Personen kommen (Gesicht/Stichwort). | Ändert nichts, du benennst in Lightroom. **Lightroom muss geschlossen sein.** Ob auf einem Bild „ohne Gesicht“ wirklich jemand ist, siehst nur du. Seite enthält Namen: bleibt auf dem PC, an Claude nur `personen_pruefen.txt`. |
| `katalog_diagnose.bat` | Technischer Test, ob der Katalog lesbar ist. Ergebnis an Claude schicken. | Nur bei Problemen nötig. |

Die `.py`-Dateien gehören zu den `.bat`-Dateien (`regeln.py` und `katalog.py` sind gemeinsame Bausteine).

---

## Wo du aufpassen musst

- **`D:\Bilder - Raw` (Originale):** Kein Skript schreibt dort etwas, sie lesen nur Dateinamen. Auch du änderst dort nichts außerhalb von Lightroom.
- **Lightroom-Katalog:** wird nur kopiert und die Kopie gelesen, nie geändert. Vor `lightroom_pruefen` und `gps_test` muss Lightroom geschlossen sein.
- **`D:\Fotoschatz`** ist nur der Export. Er darf gelöscht und neu exportiert werden.
- **Stapel:** Nur das oberste Bild eines Stapels kommt in die Galerie. Vor dem Export *Collapse All Stacks*. Vor *Edit Capture Time* oder GPS-Zuordnung dagegen *Expand All Stacks*, sonst bleiben versteckte Fotos falsch.
- **Aufnahmezeit ändern = neuer Exportname.** Danach exportieren, `sync.bat`, `aufraeumen.bat`.
- **Sterne:** ★ = wichtig, ★★ = Lieblingsbild, sonst keine. Wichtige und Lieblingsbilder prüfst du gezielt (`personen_pruefen`, Filter „★ wichtig und ★★“).
- **Merker-Stichwörter:** `ort-egal` = bewusst ohne GPS, `personen-egal` = bewusst ohne Personen. Die Prüf-Tools melden diese Bilder dann nicht mehr. (Altes `location-ok` gilt übergangsweise weiter.)
- **Ordnernamen** beginnen mit einer Jahreszahl und müssen eindeutig sein. Ordner mit `_` am Anfang (z. B. `_Import`) kommen nie online.
- **Geheimnisse nie ins Repo** (es ist öffentlich): das Präfix, die R2-Zugangsdaten, `config.local.json`, `rclone.conf`, `fotoschatz-secrets.ps1`. Auch die Google-Zeitachse, `gpx\` und die HTML-Berichte bleiben auf dem PC.
- **R2 ist kein Backup.** Originale und Katalog weiter selbst sichern.

---

## Was im Projekt noch zu tun ist

- [ ] Lightroom aufräumen mit `lightroom_pruefen`: Zeiten, Stapel, offene Namensvorschläge bestätigen.
- [ ] GPS nachtragen, wo es geht: mit `gps_test`, von Hand auf die Karte ziehen, oder `location-ok` vergeben.
- [ ] **Erstbefüllung:** alle Ordner exportieren und mit `sync.bat` hochladen. Danach Größe und Tempo am Handy prüfen.
- [ ] Link an die Familie schicken.
- [ ] Später in der App: Chromecast, „Heute vor X Jahren“, Karte, Personen-Seite, Diashow, Teilen (Liste in `CLAUDE.md`, Abschnitt 10).
