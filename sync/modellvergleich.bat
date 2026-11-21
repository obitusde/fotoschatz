@echo off
rem Fotoschatz - Modellvergleich fuer Bildbeschreibungen (Doppelklick). Lightroom darf offen sein, Ollama muss laufen.
rem Vier Testordner, je Ordner gleichmaessig verteilte Exporte, beschrieben mit 4b und 9b (und ein Groessentest).
rem Ergebnis: beschreibungen\vergleich.html (oeffnet sich im Browser) und modellvergleich.txt (nur Zahlen).
cd /d "%~dp0"
set "ANZAHL="
set /p "ANZAHL=Bilder je Ordner (Enter = 30): "
set "ARGS="
if not "%ANZAHL%"=="" set "ARGS=--bilder %ANZAHL%"
if exist "beschreibungen\vergleich.json" (
  set "NEU="
  set /p "NEU=Es gibt schon einen Zwischenstand. Enter = weitermachen, j = alles neu: "
  if /i "%NEU%"=="j" set "ARGS=%ARGS% --neu"
)
python modellvergleich.py %ARGS%
pause
