@echo off
rem Fotoschatz - Uebersicht: was ist auf der Platte, exportiert, online? (Doppelklick)
rem Liest den Originalordner nur - dort wird nichts geschrieben.
cd /d "%~dp0"
python uebersicht.py
echo.
pause
