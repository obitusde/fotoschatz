@echo off
rem Fotoschatz - Personen pruefen (Doppelklick). Lightroom vorher schliessen!
rem Zeigt je Ordner die Bilder ohne benannte Person - korrigiert nichts.
rem Oeffnet personen_pruefen.html im Browser und schliesst sich dann (bleibt nur bei Fehlern offen).
cd /d "%~dp0"
python personen_pruefen.py
if errorlevel 1 pause
