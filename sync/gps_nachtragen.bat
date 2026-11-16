@echo off
rem Fotoschatz - GPS nachtragen (Doppelklick). Lightroom vorher schliessen!
rem Sucht alle Fotos ohne GPS, laedt passende Garmin-Aktivitaeten (_sync\garmin\), nimmt Handyfotos und
rem Google-Zeitachse dazu und schreibt EINE GPS-Spur: gpx\ohne_gps.gpx (fuer Lightroom Map > Tracklog).
rem Ergebnis: gps_nachtragen.txt (keine Koordinaten). Aendert nichts an Fotos, Katalog oder Originalen.
cd /d "%~dp0"
python gps_nachtragen.py
pause
