#!/bin/bash
# Double-click this in Finder (or run it in a terminal) to start LTG — BOTH the
# game and the deckbuilder in one window. The game opens in your browser; the
# deckbuilder runs quietly at http://localhost:8000 (the game's Edit buttons
# reach it). The in-app Quit button (or closing this window) stops both.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

exec ./.venv/bin/ltg-start
