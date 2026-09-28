@echo off
rem Fotoschatz - Sync starten (Doppelklick)
cd /d "%~dp0"
python sync.py %*
echo.
pause
