@echo off
rem Fotoschatz - Aufraeumen: ueberfluessige Exporte aus D:\Fotoschatz nach _sync\geloescht verschieben (Doppelklick)
rem Fragt je Gruppe nach. Der Originalordner wird nie veraendert.
cd /d "%~dp0"
python aufraeumen.py
echo.
pause
