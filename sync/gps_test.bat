@echo off
rem Fotoschatz - GPS-Test (Doppelklick). Lightroom vorher schliessen!
rem Liest eine Kopie des Katalogs und _sync\google\*.json. Alles bleibt auf dem PC.
rem Ergebnis: gps_test.txt (nur Anzahlen) und gpx\<Ordner>.gpx (GPS-Spur zum Ausprobieren in Lightroom)
cd /d "%~dp0"
set "SUCHE=Japan"
set /p "SUCHE=Ordnername enthaelt (Enter = Japan): "
python gps_test.py "%SUCHE%"
pause
