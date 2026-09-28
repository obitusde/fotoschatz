@echo off
rem Fotoschatz - Probelauf: zeigt nur, was passieren wuerde (Doppelklick)
cd /d "%~dp0"
python sync.py --dry-run
echo.
pause
