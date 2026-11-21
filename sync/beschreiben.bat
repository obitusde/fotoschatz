@echo off
rem Fotoschatz - Bildbeschreibungen mit Ollama testen (Doppelklick). Lightroom darf offen sein.
rem Nimmt nur die Lightroom-Exporte eines Ordners, misst die Zeit je Bild.
rem Ergebnis: beschreibungen\<Ordner> (<Modell>).html (oeffnet sich im Browser) und beschreiben.txt (nur Zeiten).
cd /d "%~dp0"
set "SUCHE="
set /p "SUCHE=Ordnername enthaelt (Enter = automatisch einen Ordner mit 30-50 Bildern): "
set "MODELL="
set /p "MODELL=Modell (Enter = automatisch qwen3.5:4b, oder z. B. 9b): "
set "ARGS="
if not "%MODELL%"=="" set "ARGS=--modell %MODELL%"
python beschreiben.py %ARGS% %SUCHE%
pause
