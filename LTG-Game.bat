@echo off
rem Double-click this in Explorer to launch LTG-Game — the playable game UI.
rem It sets up the venv on first run, builds the React client if needed, then
rem serves the client + API/WS on one port and opens your browser.
rem Windows equivalent of LTG-Game.command.
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
rem The `ltg-game` command builds the client (first run) and serves everything.
rem Keep this window open while you play; closing it stops the game server.
.venv\Scripts\ltg-game.exe %*
if errorlevel 1 pause
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3 is installed from python.org
echo (tick "Add python.exe to PATH" in its installer), then run this again.
echo If it still fails, delete the .venv folder and retry.
pause
exit /b 1
