@echo off
rem Fotoschatz - neue Skripte von GitHub holen (Doppelklick).
rem Laedt alle Skripte aus dem Repo (Ordner sync, Stand main) in diesen Ordner. Eigene Dateien
rem (config.local.json, work, google, gpx ...) bleiben unberuehrt. Diese .bat ersetzt sich nicht selbst.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0aktualisieren.ps1"
echo.
pause
