@echo off
rem Fotoschatz - Bildbeschreibungen mit Ollama testen (Doppelklick). Lightroom darf offen sein.
rem Nimmt nur die Lightroom-Exporte eines Ordners, misst die Zeit je Bild.
rem Ergebnis: beschreibungen\<Ordner>.html (oeffnet sich im Browser) und beschreiben.txt (nur Zeiten).
cd /d "%~dp0"
set "SUCHE="
set /p "SUCHE=Ordnername enthaelt (Enter = automatisch einen Ordner mit 30-50 Bildern): "
python beschreiben.py %SUCHE%
pause
