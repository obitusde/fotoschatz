# Fotoschatz – Erweiterung Videos („Videoschatz")

**Version:** 0.1 · **Stand:** 18.11.2026 · **Status:** Projektdefinition, noch kein Code

Dieses Dokument beschreibt die Erweiterung von Fotoschatz um eigene Videos. Es ist die Arbeitsgrundlage für Claude Code. Vor jeder Umsetzung: Dokument und bestehenden Fotoschatz-Code lesen, Architektur mit Christof besprechen, erst danach Code schreiben.

---

## 1. Ziel

Rund 1750 eigene Videos (193 GB) verkleinert in Cloudflare R2 ablegen und in der Fotoschatz-PWA ansehen, gut sortiert, durchsuchbar und so präsentiert, dass man Lust hat, sie anzusehen. Ohne dass Christof die Videos einzeln durchsehen muss.

Pro Video gibt es am Ende:
- eine komprimierte, im Handy-Browser abspielbare Kopie
- ein Vorschaubild und eine kurze Bewegtvorschau
- Datum, Ort, Ereignis (Zuordnung zu Fotoschatz-Ordner)
- automatisch erzeugten Titel, Beschreibung, Stichwörter
- Transkript des gesprochenen Texts
- erkannte Personen (max. 10 bekannte Personen)
- Sichtbarkeit: privat (nur Christof) oder Familie

## 2. Ausgangslage

- **Videos:** 1753 Dateien, 193 GB. Überwiegend Handy-Clips von wenigen Minuten, einige von Kameras.
- **Ablage:** alle in einem Verzeichnis mit Unterordnern ohne Logik. Die Struktur wird ignoriert und bleibt, wie sie ist. Die Videos sind nicht in Lightroom und sollen dort auch nicht hinein.
- **Originale:** werden nie verändert, verschoben oder gelöscht. Es entstehen nur Kopien.
- **Fotos:** Fotoschatz existiert bereits (Cloudflare R2 + PWA, Repo `obitusde/fotoschatz`). Fotos liegen auf F: in Jahresordnern mit Ereignisordnern `YYYY-MM-DD Name`, sind in Lightroom mit Personen und Orten verschlagwortet.
- **Zielgeräte der Familie:** nur Android, Geräte 1–2 Jahre alt. Kein iPhone.

### Rechner (Verarbeitung lokal)

- Asus ROG Zephyrus M16 (2022), Windows 11
- Intel Core i7-12700H, 16 GB RAM
- NVIDIA GeForce RTX 3060 Laptop GPU, 6 GB VRAM
- ca. 400 GB frei
- Chocolatey ist bereits installiert

## 3. Grundsätze

1. **Alles lokal.** Kodieren, Transkription, Gesichtserkennung und Beschreibung laufen auf dem Laptop. Nichts außer den fertigen Kopien verlässt den PC. (Cloud-Modell nur als Vergleich im Test, siehe 9.)
2. **Originale nur lesen.**
3. **Wiederaufnehmbar.** Jeder Schritt schreibt sein Ergebnis in eine eigene Datei. Abbrechen jederzeit, beim nächsten Start geht es dort weiter.
4. **Idempotent.** Video-ID aus dem Dateiinhalt (Hash), nicht aus dem Pfad. Umbenennen/Verschieben von Originalen löst keine Neuverarbeitung aus, Duplikate werden erkannt.
5. **Nicht raten, markieren.** Unsichere Ergebnisse (Drehung, Person, Datum, Ausschuss) bekommen eine Prüf-Markierung statt einer stillen Entscheidung.
6. **Standardmäßig privat.** Nichts ist für die Familie sichtbar, bevor Christof es freigibt.
7. **Konfigurierbar.** Pfade, Schwellwerte, Modelle, Paketgröße in einer Konfigurationsdatei.
8. **Nachvollziehbar.** Log mit Versionsnummern von Skript, Tools und Modellen pro Verarbeitung.

## 4. Getroffene Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Speicher | Cloudflare R2, gleicher Speicher wie Fotoschatz | günstig, kein Abrufentgelt; Cloudflare Stream wäre pro Minute teurer |
| Video-Codec | AV1 (SVT-AV1, CPU), max. 1080p | kleinste Dateien; aktuelle Android-Geräte dekodieren AV1 per Hardware; Kodierzeit egal (läuft nachts) |
| Audio | AAC | überall abspielbar |
| Container | MP4 mit `faststart`, Keyframe ca. alle 2 s | sofortiges Abspielen, schnelles Spulen |
| Sichtbarkeit | jede Datei genau einmal in R2, Name = zufällige ID; Sichtbarkeit nur als Flag im Manifest; Worker prüft Token | Freigeben/Sperren ohne Kopieren oder Neu-Upload |
| Sortierung | nur online/im Manifest, Originale bleiben unsortiert | Christof sieht Videos nie auf dem PC an |
| Oberfläche | in Fotoschatz integriert, ein Interface | siehe 8 |
| Lightroom | Videos nicht importieren | Lightroom speichert Video-Metadaten nur im Katalog, keine Gesichtserkennung für Videos |

Geschätzt: AV1 1080p bei ca. 2 Mbit/s ergibt grob 10–20 GB statt 193 GB. Unbestätigt, der Test liefert echte Zahlen.

## 5. Pipeline pro Video

Verarbeitung in **Paketen** (Standard ca. 50 Videos). Jeder Schritt läuft für das ganze Paket, damit jedes Modell nur einmal geladen wird (16 GB RAM, 6 GB VRAM). CPU-lastige und GPU-lastige Schritte laufen nacheinander, nicht parallel.

### Schritt 0 – Inventar und Analyse (einmalig, schnell)
- Alle Dateien rekursiv finden, Hash berechnen, ID vergeben.
- Metadaten auslesen (ffprobe, ExifTool): Auflösung, Bildrate, Codec, Dauer, Drehung, HDR ja/nein, GPS, Gerät, Aufnahmezeit.
- **Datum ermitteln**, in dieser Reihenfolge: Aufnahmezeit aus Metadaten → Datum im Dateinamen (`PXL_20230714_…`, `VID_…`) → Dateidatum (nur als Notbehelf, markiert).
- **Zeitzone korrigieren:** Handy speichert meist UTC. Lokale Zeit über GPS bzw. Fotos desselben Zeitraums.
- **Duplikate** erkennen (gleicher Hash, zusätzlich inhaltsähnliche Kopien, z. B. WhatsApp-Versionen).
- **Ausschuss-Kandidaten** markieren: sehr kurz, fast schwarz, versehentliche Aufnahme.
- **Sonderfälle** markieren: Zeitlupe/Zeitraffer (Bildrate), HDR, Bewegte Fotos vom Pixel (prüfen, ob unter den Dateien).
- Ausgabe: Bericht mit Statistik und geschätzter Gesamtdauer.

### Schritt 1 – Umwandeln (CPU)
1. **Wackeln messen** (vidstab, Durchgang 1). Nur oberhalb eines Schwellwerts stabilisieren (Durchgang 2). Handys stabilisieren oft schon selbst; doppeltes Stabilisieren bringt wenig und beschneidet den Rand. Stabilisieren ist immer der erste Filter.
2. **Drehung:** Metadaten-Drehung anwenden. Inhaltliche Prüfung (siehe Schritt 3/5): automatisch drehen nur, wenn mehrere Bilder und Methoden übereinstimmen, sonst markieren.
3. **HDR → SDR** per Tone-Mapping, falls HDR.
4. Skalieren auf max. 1080p, Hochformat bleibt Hochformat.
5. **Lautstärke normalisieren.**
6. AV1 + AAC in MP4, `faststart`, Metadaten (Datum, GPS) übernehmen.
7. **Vorschaubild:** mehrere Kandidaten, schärfstes nicht schwarzes Bild wählen.
8. **Bewegtvorschau:** 2–3 s, stumm, klein.

### Schritt 2 – Ton (GPU)
- faster-whisper, Sprache automatisch (Deutsch, Französisch, Englisch möglich).
- Transkript mit Zeitmarken.

### Schritt 3 – Gesichter (GPU)
- Bilder alle ca. 3–5 s ziehen, Gesichter finden, Embeddings berechnen.
- Abgleich mit Referenzgesichtern der bis zu 10 Personen; unter Schwellwert = unbekannt (ignorieren).
- Referenzen: aus Fotoschatz-/Lightroom-Fotos mit Personen-Stichwort, pro Person mehrere, bei Kindern pro Altersphase.
- Zusätzlich: Gruppierung unbekannter Gesichter, damit Christof Gruppen einmal benennen kann.
- Ergebnis pro Video: Personen, Anteil der Bilder, Sicherheit, Zeitmarken.
- Nebenprodukt: Gesichter in gedrehten Varianten als Hinweis für falsche Drehung.

### Schritt 4 – Ereignis zuordnen
- Datum mit Fotoschatz-Ereignissen (`YYYY-MM-DD Name`) abgleichen, mehrtägige Ereignisse und GPS-Nähe berücksichtigen.
- Treffer: Ereignisname als Titel-Kontext, Stichwörter/Personen der Fotos dieses Ereignisses als Kontext.
- Kein Treffer: Einordnung „Jahr / Monat", markieren.
- Quelle der Foto-Stichwörter: Fotoschatz-Manifest bzw. exportierte JPEGs (nicht der Lightroom-Katalog).

### Schritt 5 – Beschreibung (GPU)
- Lokales Vision-Modell über Ollama. Erster Kandidat: `qwen3-vl:4b` (passt in 6 GB VRAM; in einem veröffentlichten Test genauso genau wie 8B, keine Halluzinationen). Vor dem Bau aktuellen Stand prüfen.
- 6–10 Bilder pro Clip (ca. alle 15–20 s), eine Anfrage.
- Prompt-Kontext: Datum, Ort, Ereignis, erkannte Personen, Transkript. Anweisung: nur Sichtbares beschreiben, keine Namen erfinden, kein Datum raten.
- Ausgabe: Titel, Beschreibung (2–3 Sätze, Deutsch), Stichwörter, optional Einschätzung der Drehung.
- Erwartung: Suchhilfe, nicht Wahrheit. In der App als „automatisch erzeugt" gekennzeichnet und bearbeitbar.

### Schritt 6 – Stimmen (optional, ganz am Ende des Projekts)
- Sprecher-Erkennung (z. B. SpeechBrain ECAPA) mit Referenzaufnahmen.
- Bei Handyvideos unzuverlässig (Wind, Abstand, Kinderstimmen, Durcheinandersprechen). Nutzen: erkennen, wer filmt.

### Schritt 7 – Hochladen und Manifest
- Datei, Vorschaubild, Bewegtvorschau nach R2 (rclone).
- Eintrag ins Video-Manifest, Sichtbarkeit `privat`.

## 6. Datenformat (Entwurf)

Arbeitsordner auf C: (Pfad in Konfiguration), pro Video ein Unterordner `<id>/` mit:
- `meta.json` – Inventar und Analyse
- `video.mp4`, `poster.webp`, `preview.mp4`
- `transcript.json`, `faces.json`, `describe.json`
- `status.json` – welche Schritte mit welcher Version erledigt sind, Prüf-Markierungen

Video-Manifest (`videos.json`), pro Eintrag u. a.:
`id, datum, zeitzone, dauer, breite, hoehe, ort {lat, lon, name}, ereignis, titel, beschreibung, stichwoerter, personen [{name, anteil, sicherheit}], transkript_kurz, sichtbarkeit (privat|familie), favorit, pruefen [gruende], quelle_pfad (nur lokal, nicht hochladen), version`

Feldnamen beim Bau mit bestehendem Fotoschatz-Manifest abstimmen.

## 7. Bedienung

```
videoschatz analyse              # Inventar + Bericht, nur lesen
videoschatz start                # alles verarbeiten, in Paketen, inkl. Upload
videoschatz start --anzahl 10    # Testlauf
videoschatz start --bis 07:00    # automatisch morgens stoppen
videoschatz status               # Fortschritt
videoschatz stop                 # oder Strg+C
```

- Anhalten jederzeit. Fertige Schritte bleiben, ein halb kodiertes Video wird neu begonnen.
- Standby verhindern, solange gearbeitet wird. Laptop am Netzteil.
- Fortschrittsanzeige: Paket, Video, Schritt, geschätzte Restzeit.
- Morgenbericht: fertig, Fehler, zur Prüfung markiert.
- Neue Videos: in den Quellordner legen, `videoschatz start` verarbeitet nur Neue.
- Eventuell später getrennte Befehle für Umwandeln und Hochladen (offen).

## 8. Oberfläche (grober Rahmen, Details später)

Untere Leiste: `Fotos · Videos · Personen · Karte · Suche`

- **Videos-Tab:** Raster mit Bewegtvorschau, nach Jahr/Ereignis, Dauer-Badge, Personen-Chips; oben „Zufällig" und „Heute vor X Jahren".
- **Ereignis:** oben eigene, seitlich wischbare Video-Reihe, darunter die Fotos. Videos gehen nicht im Fotoraster unter.
- **Personen:** pro Person „Videos" und „Fotos", Videos zuerst.
- **Karte:** eigenes Video-Symbol, ein-/ausblendbar.
- **Suche:** gemeinsam, Filter `Alle · Fotos · Videos`, findet auch gesprochenen Text.
- **Player:** Vollbild, Hochformat füllend, Wischen zum nächsten Video des Ereignisses; darunter Titel, Beschreibung, Personen, Ort; bearbeitbar.
- **Prüfen (nur Christof):** markierte Videos, Freigabe für Familie (einzeln und „alle übrigen freigeben"), Privat-Markierung, Favoriten.
- **Sichtbarkeit:** Familie sieht private Videos nirgends (auch nicht in Ereignis, Suche, Karte). Worker liefert Dateien nur mit passendem Token; Range-Requests müssen unterstützt werden (Spulen).
- Fotos und Videos: gleicher R2-Speicher, gleicher Worker, getrennte Manifeste, die die App zusammenführt.

## 9. Tools (vor Installation Versionen und Paketnamen prüfen)

| Zweck | Tool |
|---|---|
| Kodieren, Stabilisieren | ffmpeg-Build mit SVT-AV1 und libvidstab |
| Metadaten | ExifTool, ffprobe |
| Skripte | Python mit eigener venv |
| Transkript | faster-whisper (CUDA) |
| Gesichter | InsightFace oder Alternative (onnxruntime-gpu) |
| Beschreibung | Ollama + Vision-Modell |
| Upload | rclone (R2) |
| Worker | bestehender Fotoschatz-Stack (Node/Wrangler) |

Lizenz Gesichtsmodelle: InsightFace-Modelle (z. B. buffalo_l) haben eine unklare/eingeschränkte Lizenz; für privaten, nicht kommerziellen Gebrauch vermutlich unkritisch. Alternative: OpenCV SFace (als kommerziell nutzbar beschrieben, vermutlich etwas schwächer). Vor dem Bau klären.

NVIDIA-Treiber muss aktuell sein (CUDA für Whisper, Ollama, Gesichter).

## 10. Arbeitsweise mit Claude

- Claude Code schreibt Skripte; ausgeführt werden sie von Christof lokal in Windows (PowerShell, Installation als Administrator). Claude kann Windows-Programme nicht selbst installieren und die GPU nicht nutzen.
- Skripte schreiben Ausgaben und Logs in einen Projektordner. Christof gibt ihn in der Claude-Desktop-App frei, damit Claude Logs, Berichte und Testergebnisse direkt lesen kann.
- Diagnose zuerst, dann Code. Jede Komponente einzeln testen, bevor sie in die Pipeline kommt.
- Komplette Dateien statt Patches, Versionsnummer bei jeder Änderung.
- Architektur besprechen, bevor Code geschrieben wird. Code erst nach Abschluss der Diskussion umschreiben.

## 11. Meilensteine

1. **Diagnose-Skript** (nur lesend): Windows, winget/Chocolatey, NVIDIA-Treiber/CUDA, ffmpeg + AV1 + vidstab, Python, Ollama, onnxruntime-gpu, freier Speicher.
2. **Installations-Skript** in Etappen, jede Etappe gibt Versionen aus.
3. **Einzeltests pro Tool** an einem Video: kodieren, Whisper, Gesichter, Beschreibung.
4. **Inventar (`analyse`)** über alle 1753 Dateien + Bericht.
5. **Testlauf mit ca. 20 bekannten Videos** unterschiedlicher Herkunft und Länge:
   - Größe, Qualität, Kodierdauer → Bitrate/Preset festlegen
   - Abspielen auf ältestem Familien-Handy
   - Beschreibungen beurteilen; Vergleich lokal vs. Cloud-Modell (OpenRouter) an denselben Videos
   - Gesichtserkennung mit Referenzen beurteilen, Schwellwerte festlegen
   - Wackel- und Drehungs-Schwellwerte festlegen
6. **Pipeline komplett** (`start`, Pakete, Fortsetzen, Bericht).
7. **Worker + Manifest** in Fotoschatz einbinden, Sichtbarkeit.
8. **Oberfläche** (Details dann besprechen).
9. **Großer Lauf** über alle Videos (geschätzt mehrere Nächte, unbestätigt).
10. Optional: Stimmen.

## 12. Offene Punkte

- Quellpfad der Videos und Arbeitsordner festlegen.
- Kodierparameter (Bitrate/CRF, Preset) nach Test.
- Wahl Vision-Modell und Gesichtsmodell nach Test und Lizenzprüfung.
- Referenzfotos: welche Personen, aus welchen Fotos.
- Ein Befehl inkl. Upload oder getrennte Befehle.
- Wie Bearbeitungen in der App (Titel, Beschreibung, Personen) gespeichert werden und bei Neuverarbeitung erhalten bleiben.
- Anpassungen am bestehenden Fotoschatz-Worker und -Manifest (erst nach Lesen des Codes).

## 13. Bekannte Risiken

- Automatische Beschreibungen sind schlicht und können halluzinieren.
- Gesichtserkennung bei Kindern über die Jahre: Verwechslungen möglich (auch bei Immich berichtet).
- Kleine, seitliche, verdeckte Gesichter werden oft nicht erkannt.
- Laufzeiten sind Schätzungen; echte Werte erst nach Test auf der RTX 3060.
- R2-Kopien ersetzen kein Backup der Originale.

---

## Änderungsprotokoll

- **0.1** (18.11.2026) – erste Projektdefinition aus Chat-Diskussion
