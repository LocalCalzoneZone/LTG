#!/bin/bash
# Double-click this in Finder (or run it in a terminal) to launch the
# LTG Combat Playtest Cockpit — the web GUI for playtesting & debugging combat.
# It sets up the venv on first run, then serves the app and opens your browser.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  # Editable install of the whole monorepo (core + both apps).
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

# The `ltg-combat-cockpit` command serves the app and opens the browser itself.
exec ./.venv/bin/ltg-combat-cockpit "$@"
