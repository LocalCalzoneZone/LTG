#!/bin/bash
# Double-click this in Finder (or run it in a terminal) to play LTG Combat.
# It sets up the venv on first run, then launches the text UI for the §A fight.
# Optional: pass a scenario JSON path to play a different encounter, e.g.
#   ./LTG-Combat.command examples/scenario_a.json
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  # Editable install of the whole monorepo (core + both apps).
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

# `ltg-combat repl [scenario.json]` is the text UI; defaults to the §A fight.
exec ./.venv/bin/ltg-combat repl "$@"
