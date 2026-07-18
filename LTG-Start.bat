@echo off
rem Double-click this in Explorer to start LTG — BOTH the game and the
rem deckbuilder in one window. The game opens in your browser; the deckbuilder
rem runs quietly at http://localhost:8000 (the game's Edit buttons reach it).
rem The in-app Quit button (or closing this window) stops both.
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto :run

echo First run: creating virtual environment and installing dependencies...
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% -m venv .venv
if not exist .venv\Scripts\python.exe goto :fail
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:run
rem Keep this window open while you play; closing it stops both apps.
.venv\Scripts\ltg-start.exe %*
if errorlevel 1 pause
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3 is installed from python.org
echo (tick "Add python.exe to PATH" in its installer), then run this again.
echo If it still fails, delete the .venv folder and retry.
pause
exit /b 1
