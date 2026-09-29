@echo off
rem Fotoschatz - Katalog-Diagnose (Doppelklick). Lightroom vorher schliessen!
rem Kopiert den Lightroom-Katalog nach _sync\katalog und liest nur die Kopie. Ergebnis: katalog_diagnose.txt
cd /d "%~dp0"
python katalog_diagnose.py
pause
