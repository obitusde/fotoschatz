@echo off
rem Fotoschatz - Lightroom pruefen (Doppelklick). Lightroom vorher schliessen!
rem Liest eine Kopie des Katalogs und D:\Bilder - Raw nur als Dateiliste - korrigiert nichts.
rem Oeffnet lightroom_pruefen.html im Browser und schliesst sich dann (bleibt nur bei Fehlern offen).
cd /d "%~dp0"
python lightroom_pruefen.py
if errorlevel 1 pause
