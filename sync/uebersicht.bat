@echo off
rem Fotoschatz - Uebersicht: was ist auf der Platte, exportiert, online, zu pruefen? (Doppelklick)
rem Liest den Originalordner nur - dort wird nichts geschrieben. Schliesst sich, sobald die Seite offen ist.
cd /d "%~dp0"
python uebersicht.py
if errorlevel 1 pause
