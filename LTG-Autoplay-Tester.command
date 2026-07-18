#!/bin/bash
# Double-click this in Finder (or run it in a terminal) to launch the LTG
# Autoplay Tester — the playtest lab (Design Update 13): probes, gauntlets,
# and balance verdicts over the ltg-autoplay harness. Independent of the game
# (LTG-Game.command) and the Deckbuilder; run the Deckbuilder alongside if you
# want the "Edit in Deckbuilder" handoff to land somewhere.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment and installing dependencies…"
  python3 -m venv .venv || exit 1
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt || exit 1
fi

# The `ltg-autoplay-tester` command serves the app and opens the browser itself.
exec ./.venv/bin/ltg-autoplay-tester "$@"
