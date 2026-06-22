#!/bin/bash
# Double-click this in Finder to start the LTG Deck Builder.
# It sets up the venv on first run, then serves the app and opens your browser.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  # Editable install of the whole monorepo (core + both apps).
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

# Open the browser a moment after the server starts listening.
( sleep 2 && open "http://localhost:8000" ) &

echo "Starting LTG Deck Builder at http://localhost:8000  (Ctrl-C to stop)"
exec ./.venv/bin/uvicorn ltg_deckbuilder.app:app --host 0.0.0.0 --port 8000
