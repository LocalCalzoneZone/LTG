"""Generation freshness: the prompt pins the fantasy register, offers a breadth
of theme examples (not one attractor to mimic), and names the player's existing
encounter/adventure titles so the model designs away from them — the fix for
every generated adventure converging on 'a drowned cathedral' variants."""

from __future__ import annotations

from ltg_game_server import llm

_PARTY = {"size": 2, "avg_level": 1.0,
          "members": [{"name": "Soren", "level": 1, "colors": ["W", "G"]},
                      {"name": "Lasarre", "level": 1, "colors": ["U", "B"]}]}


def test_instructions_enforce_the_fantasy_setting():
    D = llm.DEFAULT_INSTRUCTIONS
    for needle in ("Setting & theme", "Magic: The Gathering", "Forgotten Realms",
                   "no science fiction", "no firearms"):
        assert needle in D, needle


def test_instructions_offer_a_breadth_of_theme_examples():
    """Several compass-point themes, so the model has a range to draw from
    instead of one example it mimics."""
    D = llm.DEFAULT_INSTRUCTIONS
    examples = ("goblin sapper", "lich-queen", "tomb guardians", "fey revel",
                "efreet", "plague-cultists", "hag coven", "frost-giant",
                "armory constructs", "serpent-folk")
    assert sum(e in D for e in examples) >= 8
    # And the anti-attractor guidance is explicit.
    assert "vary the biome" in D


def _fake_library(monkeypatch, encounters, adventures):
    # encounters/adventures may be bare names (str) or full metas (dict).
    def meta(n, extra):
        return n if isinstance(n, dict) else {"name": n, **extra}
    monkeypatch.setattr(llm.content, "list_encounters",
                        lambda: [meta(n, {"enemy_names": []}) for n in encounters])
    monkeypatch.setattr(llm.content, "list_adventures",
                        lambda: [meta(n, {"flavor": ""}) for n in adventures])


def test_request_blocks_name_the_existing_titles(monkeypatch):
    _fake_library(monkeypatch,
                  ["The Drowned Choir", "The Fungal Hollow"],
                  ["The Drowned Cathedral of Vael"])
    for block in (llm._request_block(_PARTY, "standard", ""),
                  llm._adventure_request_block(_PARTY, "standard", "")):
        assert "The Drowned Choir" in block
        assert "The Fungal Hollow" in block
        assert "The Drowned Cathedral of Vael" in block
        assert "owns" in block
        assert "something NEW" in block


def test_request_blocks_pass_enemies_and_call_out_recurring_motifs(monkeypatch):
    """The library block ships each owner's ENEMY roster (so motifs are visible,
    not just abstract titles) and names words that recur across it — the fix for
    the model landing on 'glass'/'drowned' over and over."""
    _fake_library(monkeypatch,
                  [{"name": "The Drowned Watch",
                    "enemy_names": ["Drowned Keeper", "Tide-Caller"]},
                   {"name": "The Glassblower's Menagerie",
                    "enemy_names": ["Glass Wisp", "Drowned Reaver"]}],
                  [])
    block = llm._request_block(_PARTY, "standard", "")
    assert "Drowned Keeper" in block and "Glass Wisp" in block   # enemies shipped
    assert "drowned" in block                                    # recurs (2 texts)
    # A one-off word is NOT flagged as recurring.
    assert "keeper" not in block.split("recur", 1)[-1]


def test_request_blocks_stay_clean_with_an_empty_library(monkeypatch):
    _fake_library(monkeypatch, [], [])
    for block in (llm._request_block(_PARTY, "standard", ""),
                  llm._adventure_request_block(_PARTY, "standard", "")):
        assert "already owns" not in block
        assert "something NEW" not in block


# --------------------------------------------------------------------------- #
# Mechanical variety (rolled signatures + anti-rut guidance)
# --------------------------------------------------------------------------- #
def test_instructions_teach_mechanical_variety_and_boss_silhouettes():
    D = llm.DEFAULT_INSTRUCTIONS
    assert "MECHANICAL VARIETY" in D
    assert "PALETTE, not a checklist" in D
    assert "SIGNATURE mechanic" in D
    # Several distinct boss shapes, so Example C's isn't the only mold.
    for shape in ("SUMMONER-TYRANT", "RITUALIST", "DUELLIST",
                  "NECROMANCER-KING", "GATHERER TITAN", "WARLORD"):
        assert shape in D, shape


def test_encounter_request_rolls_two_signatures(monkeypatch):
    _fake_library(monkeypatch, [], [])
    monkeypatch.setattr(llm.random, "sample", lambda pool, k: list(pool)[:k])
    block = llm._request_block(_PARTY, "standard", "")
    assert "SIGNATURE MECHANICS" in block
    assert llm.SIGNATURE_POOL[0] in block and llm.SIGNATURE_POOL[1] in block


def test_adventure_request_rolls_one_signature_per_act(monkeypatch):
    _fake_library(monkeypatch, [], [])
    monkeypatch.setattr(llm.random, "sample", lambda pool, k: list(pool)[:k])
    block = llm._adventure_request_block(_PARTY, "standard", "")
    assert "SIGNATURE MECHANICS" in block
    for i in range(1, 4):
        assert f"Act {i}: {llm.SIGNATURE_POOL[i - 1]}" in block


def test_signature_rolls_are_distinct():
    rolls = llm._signature_rolls(3)
    assert len(rolls) == len(set(rolls)) == 3
    assert all(r in llm.SIGNATURE_POOL for r in rolls)
