@echo off
rem Double-click this in Explorer to start the LTG Deck Builder.
rem It sets up the venv on first run, then serves the app and opens your browser.
rem Windows equivalent of LTG-Deckbuilder.command.
cd /d "%~dp0"

if exist .venv\Scripts\python.exe goto :run

echo First run: creating virtual environment and installing dependencies...
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% -m venv .venv
if not exist .venv\Scripts\python.exe goto :fail
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
rem Editable install of the whole monorepo (core + all apps).
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:run
rem The `ltg-deckbuilder` command serves the app and opens the browser itself.
rem Keep this window open while you play; closing it stops the app.
.venv\Scripts\ltg-deckbuilder.exe %*
if errorlevel 1 pause
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3 is installed from python.org
echo (tick "Add python.exe to PATH" in its installer), then run this again.
echo If it still fails, delete the .venv folder and retry.
pause
exit /b 1
