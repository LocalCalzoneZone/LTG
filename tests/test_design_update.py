"""Design Update 01 mechanics: attack modes + row reachability (R-1), attack
profiles (R-3), deterministic ordering (R-6), and the temp_mod HP model (R-7).
Driven through the engine's two-function contract."""

from __future__ import annotations

from ltg_combat.engine import apply_action, legal_actions, settle
from ltg_combat.scenario import party_entry_from_loadout, state_from_dict


def _enemy(eid, name, hp, row="front", mode="melee", amount=2):
    return {"id": eid, "name": name, "hp": hp, "level": 1, "row": row,
            "intent": {"name": "Hit", "amount": amount, "action_type": "ability",
                       "intent_type": "attack", "targeting": "lowest_hp_party", "mode": mode}}


def _hero(mode="melee", row="front", hp=20, keywords=None, name="Hero", level=1, hand=None):
    return {"id": name.lower(), "name": name, "archetype": "Fighter", "hp": hp, "power": 3,
            "hand_size": len(hand or []), "identity": ["W", "U", "B", "R", "G"],
            "attack_mode": mode, "row": row, "level": level, "library": hand or [],
            "keywords": keywords or {}}


def _state(party, enemies):
    st = state_from_dict({"party": party, "enemies": enemies})
    # Grant any keywords declared on the party entries (state_from_dict doesn't read them).
    for entry, c in zip(party, st.party):
        for kw in entry.get("keywords", {}):
            c.keywords[kw] = "encounter"
    return st


def _attack_targets(st):
    return {a.target_id for a in legal_actions(st) if a.kind == "attack"}


# --------------------------------------------------------------------------- #
# R-1 — attack modes & row reachability
# --------------------------------------------------------------------------- #
def test_melee_only_reaches_the_front_most_occupied_row():
    st = _state([_hero(mode="melee")],
                [_enemy("front", "Front", 5, row="front"),
                 _enemy("rear", "Rear", 5, row="rear")])
    assert _attack_targets(st) == {"front"}  # melee can't reach past the front row


def test_ranged_reaches_any_row():
    st = _state([_hero(mode="ranged")],
                [_enemy("front", "Front", 5, row="front"),
                 _enemy("rear", "Rear", 5, row="rear")])
    assert _attack_targets(st) == {"front", "rear"}


def test_empty_front_row_exposes_the_row_behind():
    st = _state([_hero(mode="melee")], [_enemy("rear", "Rear", 5, row="rear")])
    assert _attack_targets(st) == {"rear"}  # rear is now the front-most occupied row


def test_melee_cannot_hit_a_flyer_without_reach_but_ranged_and_reach_can():
    flyer = _enemy("f", "Bat", 5, row="front")
    flyer["keywords"] = ["flying"]  # marker the helper reads below

    def with_flyer(hero):
        st = state_from_dict({"party": [hero], "enemies": [flyer]})
        st.enemies[0].keywords["flying"] = "encounter"
        for kw in hero.get("keywords", {}):
            st.party[0].keywords[kw] = "encounter"
        return st

    assert _attack_targets(with_flyer(_hero(mode="melee"))) == set()           # grounded melee: can't
    assert _attack_targets(with_flyer(_hero(mode="ranged"))) == {"f"}          # ranged: can
    assert _attack_targets(with_flyer(_hero(mode="melee", keywords={"reach": 1}))) == {"f"}  # reach: can


def test_enemy_melee_targets_only_a_reachable_party_member():
    # A grounded melee enemy in the enemy front row hits the front-most party row;
    # the back-row ally is shielded by the front-row ally.
    st = _state([_hero(row="front", hp=10, name="Guard"),
                 _hero(row="rear", hp=5, name="Mage")],
                [_enemy("orc", "Orc", 8, row="front", mode="melee", amount=3)])
    # Even though Mage has the lower HP, the melee Orc can only reach the front Guard.
    view = settle(st)  # the prelude declares intents
    intents = [e.intent.target_id for e in view.enemies if e.intent]
    assert intents == ["guard"]


# --------------------------------------------------------------------------- #
# R-6 — deterministic ordering (row > level > name)
# --------------------------------------------------------------------------- #
def test_action_order_is_row_then_level_then_name():
    st = _state([_hero(name="Zed", row="front", level=1),
                 _hero(name="Ann", row="front", level=1),
                 _hero(name="Bob", row="mid", level=1)],
                [_enemy("orc", "Orc", 5)])
    # Front row first, then alphabetical: Ann acts before Zed; Bob (mid) last.
    assert legal_actions(st)[0].actor_id == "ann"


# --------------------------------------------------------------------------- #
# R-3 — attack profile (mode, power) from the loadout
# --------------------------------------------------------------------------- #
def _loadout(archetype, mode, colors, mana):
    return {"ltg_version": "0.1", "cards": [],
            "character": {"name": "X", "archetype": archetype, "level": 1, "colors": colors,
                          "starting_mana": mana, "attack_mode": mode, "row": "front"}}


def test_attack_profile_resolves_power_from_archetype_and_mode():
    assert party_entry_from_loadout(_loadout("Fighter", "melee", ["W"], ["W", "W"]))["power"] == 3
    assert party_entry_from_loadout(_loadout("Tactician", "ranged", ["U", "B"], ["U", "B"]))["power"] == 1
    assert party_entry_from_loadout(_loadout("Tactician", "melee", ["U", "B"], ["U", "B"]))["power"] == 2
    assert party_entry_from_loadout(_loadout("Caster", "ranged", ["U"], ["U", "U", "B"]))["power"] == 2


# --------------------------------------------------------------------------- #
# R-7 — positive temp HP is a shield that absorbs the blow before base HP
# --------------------------------------------------------------------------- #
def _bolt(amount, cid="bolt", colors=None):
    return {"id": cid, "name": cid.title(), "source_name": cid, "rarity": "common", "level": 1,
            "type": "Sorcery", "timing": "sorcery", "cost": {"colors": colors or {"R": 1}},
            "effects": [{"kind": "deal_damage", "amount": amount,
                         "target": {"mode": "chosen", "side": "enemy", "targeted": True}}],
            "validated": True}


def test_temp_hp_shield_absorbs_then_spills_over():
    # Positive temp HP soaks the blow first (GDD §4.9). An enemy at hp 3 / temp_mod +3
    # (eff 6) takes 5 → the buffer absorbs 3, the remaining 2 hits hp → hp 1, temp 0,
    # eff 1: still alive.
    st = state_from_dict({
        "party": [{"id": "h", "name": "H", "archetype": "Tactician", "hp": 20, "power": 5,
                   "attack_mode": "ranged", "hand_size": 1, "identity": ["U", "B", "R", "G"],
                   "library": [_bolt(5)]}],
        "enemies": [_enemy("orc", "Orc", 3, amount=0)]})
    st.enemy("orc").temp_mod += 3  # a +0/+3 buffer on the enemy (eff 6)
    st, _ = apply_action(st, next(a for a in legal_actions(st) if a.kind == "cast"))
    while st.result is None and st.stack:
        st, _ = apply_action(st, next(a for a in legal_actions(st) if a.kind == "pass"))
    orc = st.enemy("orc")
    assert orc is not None and orc.hp == 1 and orc.temp_mod == 0
    assert orc.effective_hp == 1 and orc.alive


def test_defend_temp_hp_absorbs_incoming_damage():
    # A Fighter Defends (+3 temp HP), then an enemy hits it for 3 — the buffer soaks
    # the whole blow, so base HP is preserved. (Before the shield fix this ended at
    # hp 22; the +3 temp HP had no effect against a non-lethal hit.)
    st = _state([_hero(hp=25)], [_enemy("brute", "Brute", 8, amount=3)])
    st, _ = apply_action(st, next(a for a in legal_actions(st) if a.kind == "defend"))
    assert st.character("hero").temp_mod == 3
    st, _ = apply_action(st, next(a for a in legal_actions(st) if a.kind == "end_turn"))
    while st.stack:
        p = next((a for a in legal_actions(st) if a.kind == "pass"), None)
        if p is None:
            break
        st, _ = apply_action(st, p)
    assert st.character("hero").hp == 25
