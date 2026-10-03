@echo off
rem Fotoschatz - Zeitachse pruefen (Doppelklick). Lightroom vorher schliessen!
rem Vergleicht Aufnahmezeit und GPS mit Handyfotos und Google-Zeitachse - korrigiert nichts.
rem Oeffnet zeitachse_pruefen.html im Browser und schliesst sich dann (bleibt nur bei Fehlern offen).
cd /d "%~dp0"
python zeitachse_pruefen.py
if errorlevel 1 pause
