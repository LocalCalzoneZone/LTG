"""Party-size scaling: per-size layouts on an encounter, resolved at build time
(scale_encounter), validated on save (content._validate_layouts) and at
generation (llm._check_layouts)."""

from __future__ import annotations

import pytest

from ltg_combat.scenario import scale_encounter, state_from_dict
from ltg_game_server import llm
from ltg_game_server.content import _validate_encounter


def _pool():
    return [
        {"id": "wolf", "name": "Wolf", "hp": 4, "level": 1, "power": 2,
         "attack_mode": "melee"},
        {"id": "shaman", "name": "Shaman", "hp": 6, "level": 3, "power": 1,
         "row": "rear", "attack_mode": "ranged"},
        {"id": "alpha", "name": "Alpha", "hp": 12, "level": 4, "power": 3,
         "attack_mode": "melee"},
    ]


def _enc(layouts):
    return {"name": "Wolfpack", "enemies": _pool(), "tokens": {},
            "layouts": layouts}


_LAYOUTS = {
    "1": ["wolf", "shaman"],
    "2": ["wolf", "wolf", "shaman", "alpha"],
    "4": ["wolf", "wolf", "wolf", "wolf", "shaman", "shaman", "alpha", "alpha"],
}


def test_scale_picks_the_matching_layout():
    out = scale_encounter(_enc(_LAYOUTS), 2)
    assert [e["id"] for e in out["enemies"]] == ["wolf", "wolf_2", "shaman", "alpha"]
    assert out["enemies"][1]["name"] == "Wolf 2"


def test_scale_clamps_to_the_nearest_defined_size():
    # No "3" layout: a party of 3 falls back to the largest defined size <= 3.
    out = scale_encounter(_enc(_LAYOUTS), 3)
    assert len(out["enemies"]) == 4          # the "2" layout
    # A party of 6 clamps down to "4"; a size below every key clamps up to the
    # smallest defined layout.
    assert len(scale_encounter(_enc(_LAYOUTS), 6)["enemies"]) == 8
    assert len(scale_encounter(_enc({"2": ["wolf", "shaman"]}), 1)["enemies"]) == 2


def test_scale_without_layouts_is_the_identity():
    enc = {"name": "Fixed", "enemies": _pool(), "tokens": {}}
    assert scale_encounter(enc, 3) is enc


def test_scaled_clones_build_into_a_valid_state():
    out = scale_encounter(_enc(_LAYOUTS), 4)
    st = state_from_dict({**out, "party": [{
        "id": "p", "name": "p", "hp": 10, "power": 2, "hand_size": 0,
        "identity": ["U"], "library": []}]})
    ids = [e.id for e in st.enemies]
    assert len(ids) == len(set(ids)) == 8    # unique clone ids


# --- save-time validation ------------------------------------------------------ #
def test_validate_encounter_keeps_clean_layouts():
    cleaned = _validate_encounter(_enc(_LAYOUTS))
    assert cleaned["layouts"] == _LAYOUTS


def test_validate_encounter_rejects_unknown_layout_ids():
    bad = _enc({"1": ["wolf", "ghost"]})
    with pytest.raises(ValueError, match="unknown enemy id"):
        _validate_encounter(bad)


def test_validate_encounter_requires_the_boss_in_every_layout():
    enc = _enc({"1": ["wolf", "shaman"], "2": ["wolf", "wolf", "alpha", "shaman"]})
    enc["enemies"][2]["is_boss"] = True      # alpha is the boss
    with pytest.raises(ValueError, match="boss"):
        _validate_encounter(enc)


# --- generation-time validation ------------------------------------------------ #
def test_check_layouts_requires_all_four_sizes():
    with pytest.raises(ValueError, match="party size"):
        llm._check_layouts({"layouts": _LAYOUTS})     # missing "3"


def test_check_layouts_enforces_outnumbering_per_size():
    layouts = {str(s): ["wolf"] * (2 * s) for s in range(1, 5)}
    llm._check_layouts({"layouts": layouts})          # exactly 2x everywhere: ok
    layouts["3"] = ["wolf", "wolf"]                   # a party of 3 vs 2 bodies
    with pytest.raises(ValueError, match='layouts\\["3"\\]'):
        llm._check_layouts({"layouts": layouts})


# --- the prompt's gold examples must themselves pass the full gate -------------- #
def _prompt_examples():
    """Parse every worked example JSON embedded in DEFAULT_INSTRUCTIONS."""
    import json
    text = llm.DEFAULT_INSTRUCTIONS
    decoder = json.JSONDecoder()
    out = []
    idx = 0
    while True:
        idx = text.find('\n{"name":"', idx)
        if idx == -1:
            return out
        obj, _ = decoder.raw_decode(text[idx + 1:])
        out.append(obj)
        idx += 10


def test_prompt_gold_examples_validate_and_scale():
    examples = _prompt_examples()
    assert len(examples) == 3                          # A, B, C
    for enc in examples:
        cleaned = _validate_encounter(enc)             # engine + layout gate
        assert set(cleaned["layouts"].keys()) == {"1", "2", "3", "4"}
        llm._check_layouts(cleaned)                    # outnumbered at every size
        for size in (1, 2, 3, 4):
            assert len(scale_encounter(cleaned, size)["enemies"]) >= 2 * size
