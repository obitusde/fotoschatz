@echo off
rem Fotoschatz - Garmin-Test (Doppelklick). Lightroom vorher schliessen!
rem Liest den API-Schluessel aus garmin_api_key.txt, fragt bei Garmin die Liste der Aktivitaeten ab
rem und zaehlt, wie viele Fotos ohne GPS in eine Aktivitaet fallen. Speichert keine Garmin-Daten.
rem Ergebnis: garmin_test.txt (nur Anzahlen) - an Claude schicken.
cd /d "%~dp0"
python garmin_test.py
pause
