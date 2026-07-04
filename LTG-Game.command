#!/bin/bash
# Double-click this in Finder (or run it in a terminal) to launch LTG-Game —
# the playable game UI. It sets up the Python venv on first run, builds the
# React client if needed, then serves the client + API/WS on one port and opens
# your browser. Independent of the cockpit (LTG-Combat-Cockpit.command).
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

# The `ltg-game` command builds the client (first run) and serves everything.
exec ./.venv/bin/ltg-game "$@"
