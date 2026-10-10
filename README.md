# Fotoschatz

Private Online-Fotogalerie für die Lightroom-Bilder (ca. 23.000), auch fürs Handy. Die Familie sieht sie ohne Konto über einen geheimen Link.

```
Lightroom ──Publish──> D:\Fotoschatz\Published Smart Folder ──sync.bat──> Cloudflare R2 (Bilder + index.json)
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
| 4 | **Am Ende jeder Sitzung:** links unter *Publish Services* „Published Smart Folder“ anklicken › **Publish** (Lightroom exportiert nur, was neu oder geändert ist) | Lightroom |
| 5 | Lightroom schließen › gleich `sync.bat` (wartet selbst, bis Lightroom ganz beendet ist) | PC |
| 6 | Ein Jahr ist fertig: Doppelklick auf „Published Smart Folder“ › Datum bei *Capture Date is before* ein Jahr weiter › Save › Publish | Lightroom |
| 7 | Ab und zu `uebersicht.bat`: Was ist exportiert und online, was fehlt? Und **Lightroom geschlossen** `zeitachse_pruefen.bat`: Stimmen Kamera-Uhren und GPS? | PC |

**Lightroom Publish (seit 10.10.2026):** Publish Service *Hard Drive: Fotoschatz* (Einstellungen wie das alte Export-Preset: `D:\Fotoschatz`, ohne Put in Subfolder, Dateiname `Ordner_Datum_Uhrzeit`, 2048 px, Q70, alle Metadaten) mit **einem Published Smart Folder** und den Regeln *Folder doesn't contain _Import* + *Capture Date is before 2013-01-01*. Lightroom nimmt damit jedes passende Bild **automatisch** auf (auch ein später in einen alten Ordner gelegtes) und merkt sich, was geändert wurde. Es legt die Dateien in `D:\Fotoschatz\Published Smart Folder\` ab. Stapel kennt der Smart Folder nicht – darum exportiert Lightroom auch die unteren Stapelbilder; `sync.bat` lässt sie (und Rejected) weg. Nie mehr mit dem alten Export-Preset nach `D:\Fotoschatz` exportieren.

**Grundregel:** Korrigiert wird **nur in Lightroom**, danach neu exportieren. Nie Dateien im Explorer umbenennen, verschieben oder ändern, sonst passt der Katalog nicht mehr.

---

## Die Skripte (Doppelklick auf die `.bat`)

| Skript | Was es macht | Was es **nicht** macht / Achtung |
|---|---|---|
| `aktualisieren.bat` | Holt die neuesten Skripte aus diesem Repo. Ersetzt erst, wenn alles geladen ist. | Fasst `config.local.json`, `work\`, `google\`, `gpx\` nicht an. Ersetzt sich selbst nicht; wenn sie sich ändert, einmal von Hand holen. |
| `lightroom_pruefen.bat` | Liest eine **Kopie** des Lightroom-Katalogs und sagt, was in Lightroom zu korrigieren ist. Zum Beispiel: Ordnernamen, falsche Zeiten, nicht gestapelte Fassungen, fehlende oder nicht importierte Dateien, doppelte Stichwörter. Dazu Infos zu Gesichtern und „GPS nachtragen“ je Ordner. | Ändert nichts. **Lightroom muss geschlossen sein.** Das Ergebnis stimmt nur so gut wie der Katalog. |
| `gps_test.bat` | Fragt nach einem Ordnernamen und sucht für Fotos ohne GPS den Ort: aus Handyfotos und der Google-Zeitachse (`_sync\google\*.json`). Füllt Lücken, wenn man am selben Ort blieb. Prüft, ob die Kamera-Uhr falsch ging. Schreibt `_sync\gpx\<Ordner>.gpx` für Lightroom. | Setzt **kein** GPS, das machst du in Lightroom (*Map › Tracklog › Load Tracklog… › All Tracks › Auto-Tag*). Vor April 2017 gibt es keine Zeitachse. Ging die Kamera-Uhr falsch, zuerst in Lightroom *Edit Capture Time* korrigieren. Bei Stapeln vorher *Expand All Stacks*. Erst 5–10 Fotos testen, auf der Karte prüfen. |
| `probelauf.bat` | Wie `sync.bat`, zeigt aber nur an, was passieren würde. | Lädt nichts hoch. |
| `sync.bat` | Macht online genau das, was in `D:\Fotoschatz` und seinen Unterordnern liegt (außer `_`-Ordnern), in 7 Schritten (jeder wird beim Ausführen kurz erklärt, mit Fortschritt und Restzeit): 1 Lightroom-Katalog (Kopie) lesen: welche Bilder gehören in die Galerie · 2 Exporte mit dem letzten Lauf vergleichen · 3 Infos aus neuen Bildern lesen, Bilder **unten im Stapel, Rejected oder aus `_`-Ordnern** aussortieren (bleiben offline) · 4 Vorschaubilder machen · 5 Prüfliste `korrekturen.csv` (und `geburtstage.txt` anlegen bzw. neue Personen anhängen) · 6 Inhaltsverzeichnis `index.json` für die App · 7 hochladen (neue Bilder, dann `index.json`, dann Altes löschen). | **Lightroom muss beendet sein** (sync wartet bis 5 Minuten darauf). Bilder mit falschem Dateinamen oder ungültiger Zeit werden **nicht** hochgeladen. Findet sync ein Bild nicht im Katalog, lädt es das Bild trotzdem hoch (Hinweis in `korrekturen.csv`). Würden mehr als 100 Bilder online gelöscht, **fragt** es nach (j/n) und zeigt Beispiele – nur „j“ löscht. Kennt `ort-egal` noch nicht und meldet dort „keine GPS-Daten“ (nur ein Hinweis). |
| `aufraeumen.bat` | **Seit Lightroom Publish nicht mehr nötig** – Lightroom räumt seinen Ordner selbst auf. Bricht ab, sobald Exporte in Unterordnern liegen. Früher: überflüssige Exporte nach `_sync\geloescht\` verschieben. | Bild soll offline: in Lightroom Rejected setzen oder aus dem Smart Folder nehmen, dann Publish und `sync.bat`. |
| `uebersicht.bat` | Vergleicht Originale, Exporte und Online-Stand. Ergebnis als Seite im Browser. | Sieht Lightroom-Stapel nicht. Bilder in Stapeln können als „nicht exportiert“ erscheinen. |
| `zeitachse_pruefen.bat` | Liste aller Fotos mit GPS (ab 04/2017), die mehr als 1 km neben dem Ort laut Google-Zeitachse liegen, **größte Abstände zuerst**: Abstand, Ort jetzt in Lightroom, Ort laut Google, Kartenlinks, Knöpfe zum Kopieren (Dateiname für die Suche, Koordinaten fürs GPS-Feld), Häkchen „erledigt“. Darunter zugeklappt die Kamera-Uhr-Prüfung für alle Ordner. | Ändert nichts, du korrigierst in Lightroom. **Lightroom muss geschlossen sein.** Die Seite enthält Koordinaten: bleibt auf dem PC, an Claude nur `zeitachse_pruefen.txt`. „Weit weg“ kann richtig sein (Foto von jemand anderem, Flug, Funkloch). Alte Scans und Fotos ohne Kamera-Angabe prüft es nicht. Fotos, die schon mit falscher Uhr eine GPS-Spur bekommen haben, liegen „passend“ zur Zeitachse; die findet nur die Uhr-Prüfung. |
| `personen_pruefen.bat` | Zeigt je Ordner die Bilder **ohne benannte Person** und warum: Name nur vorgeschlagen · Gesicht ohne Namen · kein Gesicht erkannt · nicht durchsucht · Gesicht benannt, aber Stichwort fehlt (Lightroom-Fehler). Ordner mit vielen Personenbildern zuerst, Filter nach Sternen, Knöpfe zum Kopieren der Dateinamen. Oben eine Diagnose, woher die Personen kommen (Gesicht/Stichwort). | Ändert nichts, du benennst in Lightroom. **Lightroom muss geschlossen sein.** Ob auf einem Bild „ohne Gesicht“ wirklich jemand ist, siehst nur du. Seite enthält Namen: bleibt auf dem PC, an Claude nur `personen_pruefen.txt`. |
| `geburtstage.txt` (keine .bat) | **Geburtsdaten für das Alter in der App** („Uli (45)“, Babys „14 Monate“). `sync.bat` legt die Datei beim ersten Lauf mit allen Personen an (häufigste zuerst) und hängt neue Personen unten an. Du trägst hinter dem `;` das Datum ein (`12.03.1975` oder nur `1975` → „ca. 45“), mit dem Windows-Editor, dann `sync.bat`. | Unbekannt = leer lassen. Ein Datum, das sync nicht versteht, wird im Protokoll mit Zeilennummer gemeldet und ignoriert. Bleibt auf dem PC, `aktualisieren.bat` fasst sie nicht an. |
| `katalog_diagnose.bat` | Technischer Test, ob der Katalog lesbar ist. Ergebnis an Claude schicken. | Nur bei Problemen nötig. |

Die `.py`-Dateien gehören zu den `.bat`-Dateien (`regeln.py` und `katalog.py` sind gemeinsame Bausteine).

---

## Wo du aufpassen musst

- **`D:\Bilder - Raw` (Originale):** Kein Skript schreibt dort etwas, sie lesen nur Dateinamen. Auch du änderst dort nichts außerhalb von Lightroom.
- **Lightroom-Katalog:** wird nur kopiert und die Kopie gelesen, nie geändert. Vor `lightroom_pruefen` und `gps_test` muss Lightroom geschlossen sein. Läuft Lightroom nach dem Schließen noch im Hintergrund, warten die Skripte selbst (höchstens 5 Minuten) – du kannst sie also direkt nach dem Schließen starten.
- **`D:\Fotoschatz`** gehört Lightroom (Publish). Dort nichts von Hand löschen, umbenennen oder hineinkopieren. Was dort fehlt, löscht `sync.bat` auch online.
- **Stapel:** Nur das oberste Bild eines Stapels kommt in die Galerie – `sync.bat` prüft das selbst im Katalog. Vor *Edit Capture Time* oder GPS-Zuordnung *Expand All Stacks*, sonst bleiben versteckte Fotos falsch.
- **Aufnahmezeit oder Ordnername ändern = neuer Dateiname.** ⚠ Wie Lightroom Publish dann die alte Datei behandelt, ist noch nicht geprüft – beim ersten Mal in `D:\Fotoschatz\Published Smart Folder` nachsehen, ob die alte Datei weg ist.
- **Sterne:** ★ = wichtig, ★★ = Lieblingsbild, sonst keine. Wichtige und Lieblingsbilder prüfst du gezielt (`personen_pruefen`, Filter „★ wichtig und ★★“).
- **Merker-Stichwörter:** `ort-egal` = bewusst ohne GPS, `personen-egal` = bewusst ohne Personen. Die Prüf-Tools melden diese Bilder dann nicht mehr. (Altes `location-ok` gilt übergangsweise weiter.)
- **Ordnernamen** beginnen mit einer Jahreszahl und müssen eindeutig sein. Ordner mit `_` am Anfang (z. B. `_Import`) kommen nie online.
- **Geheimnisse nie ins Repo** (es ist öffentlich): das Präfix, die R2-Zugangsdaten, `config.local.json`, `rclone.conf`, `fotoschatz-secrets.ps1`. Auch die Google-Zeitachse, `gpx\`, `geburtstage.txt` und die HTML-Berichte bleiben auf dem PC.
- **R2 ist kein Backup.** Originale und Katalog weiter selbst sichern.

---

## Was im Projekt noch zu tun ist

- [ ] Lightroom aufräumen mit `lightroom_pruefen`: Zeiten, Stapel, offene Namensvorschläge bestätigen.
- [ ] GPS nachtragen, wo es geht: mit `gps_test`, von Hand auf die Karte ziehen, oder `ort-egal` vergeben.
- [ ] **Erstbefüllung:** Published Smart Folder bis 2012 veröffentlichen (läuft), dann `sync.bat` (fragt einmal wegen der Löschungen online → „j“). Danach Größe und Tempo am Handy prüfen.
- [ ] Warnung „x Bilder warten noch auf Publish“ in `sync.bat` – dafür `katalog_diagnose.txt` nach dem großen Publish an Claude (Abschnitt 12).
- [ ] Link an die Familie schicken.
- [ ] Später in der App: Chromecast, „Heute vor X Jahren“, Personen-Seite, Diashow, Teilen (Liste in `CLAUDE.md`, Abschnitt 10).
