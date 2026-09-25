"""The `python -m ltg_combat` CLI (roadmap M1.3: `validate` read a removed field)."""

from __future__ import annotations

from pathlib import Path

from ltg_combat.__main__ import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_validate_reports_a_good_loadout(capsys):
    assert main(["validate", str(EXAMPLES / "loadout_soren.json")]) == 0
    out = capsys.readouterr().out
    assert "loadout OK" in out and "Soren" in out


def test_validate_rejects_a_missing_file(capsys):
    assert main(["validate", str(EXAMPLES / "no_such_loadout.json")]) == 1
