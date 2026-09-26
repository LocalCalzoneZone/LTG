"""Shared test setup: the data sandbox, and generation fixtures.

The sandbox: before any app module is imported, the suite points the game's
data roots (`LTG_CONTENT_DIR`, `LTG_LOADOUTS_DIR`, `LTG_SAVES_DIR`; see
`ltg_game_server.content.data_dir`) at a fresh temp dir. `content/` is copied in
without `art/` (about 1 GB, and no test reads it); `loadouts/` and `saves/`
start empty, as on a clean clone. So the suite never touches the real data
dirs: it can run beside a live game or Deckbuilder server, and two suites can
run at once.

`gate_clean_pool` builds an encounter that clears EVERY generation gate — the
§D14 kit floor, the anti-sameness checks, and the party-size layout rules
(2×size bodies AND 2×size distinct designs, ≤3 clones of any id). Generation
tests that need a "valid reply" (the repaired half of a repair-loop test) build
it here instead of hand-rolling a pool that silently rots as the gates grow."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_sandbox() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ltg-tests-"))
    real_content = REPO_ROOT / "content"

    def skip_art(folder: str, names: List[str]) -> List[str]:
        return ["art"] if Path(folder) == real_content else []

    shutil.copytree(real_content, root / "content", ignore=skip_art)
    for sub in ("content/art", "content/scenarios", "loadouts", "saves"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


# Module level, not a fixture: this must run before the test modules import
# ltg_game_server / ltg_deckbuilder, which read the variables at import time.
SANDBOX = _make_sandbox()
os.environ["LTG_CONTENT_DIR"] = str(SANDBOX / "content")
os.environ["LTG_LOADOUTS_DIR"] = str(SANDBOX / "loadouts")
os.environ["LTG_SAVES_DIR"] = str(SANDBOX / "saves")


def pytest_unconfigure(config):
    shutil.rmtree(SANDBOX, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _sandboxed_data_dirs():
    """Fail loudly if an app module read its data roots before the sandbox was
    set: the suite would then be writing into the real content/ and loadouts/."""
    from ltg_deckbuilder import app as db_app
    from ltg_game_server import content, runs
    sandbox = SANDBOX.resolve()
    for path in (content.CONTENT_DIR, content.LOADOUTS_DIR, runs.SAVES_DIR,
                 db_app.LOADOUT_DIR):
        assert sandbox in Path(path).resolve().parents, (
            f"{path} is outside the test sandbox {sandbox}")
    yield


def _v_hit(n: int) -> Dict[str, Any]:
    return {"kind": "deal_damage", "amount": n,
            "target": {"mode": "chosen", "side": "ally", "targeted": True}}


def _v_heal(n: int) -> Dict[str, Any]:
    return {"kind": "heal", "amount": n,
            "target": {"mode": "chosen", "side": "ally", "targeted": True}}


# Eight distinct roles: varied archetypes, triggers, target_rules, rows, reaches.
# The first two are ANCHORS (§D25-6): both are lockdown pieces, the second also
# channels, and their kits collide with nothing a test brings — so they always
# sit right after a test's own designs, and every pool the factory builds meets
# the lockdown floor and the channeler rule at standard.
_FILLERS: List[Dict[str, Any]] = [
    {"id": "gc_brute", "row": "front", "attack_mode": "melee", "comps": [
        {"id": "smash", "archetype": "Debilitate", "timing": "proactive", "priority": 30,
         "cooldown": 2, "target_rule": "valuation",
         "telegraph": "Smash — deal 4 and taunt",
         "verbs": [_v_hit(4), {"kind": "taunt",
                               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]},
        {"id": "spite", "archetype": "Punish", "timing": "reactive", "trigger": "on_hit",
         "cooldown": 2, "priority": 25, "target_rule": "trigger_source",
         "telegraph": "Spite — deal 2", "verbs": [_v_hit(2)]}]},
    {"id": "gc_chanter", "row": "rear", "attack_mode": "ranged", "comps": [
        {"id": "anthem", "archetype": "Fortify", "timing": "proactive", "priority": 35,
         "cooldown": 3, "target_rule": "self", "channel": True,
         "telegraph": "War-Anthem — the warband +1/+0 while held",
         "verbs": [{"kind": "pump", "power": 1, "toughness": 0,
                    "duration": "while_channeled",
                    "target": {"mode": "all", "side": "enemy"}}]},
        {"id": "hush", "archetype": "Debilitate", "timing": "proactive", "priority": 28,
         "cooldown": 3, "target_rule": "valuation",
         "telegraph": "Hush — deal 2 and taunt",
         "verbs": [_v_hit(2), {"kind": "taunt",
                               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}]},
    {"id": "gc_hexer", "row": "mid", "attack_mode": "ranged", "comps": [
        {"id": "hush", "archetype": "Debilitate", "timing": "proactive", "priority": 28,
         "cooldown": 3, "target_rule": "highest_threat",
         "telegraph": "Hush — stun a hero",
         "verbs": [{"kind": "stun",
                    "target": {"mode": "chosen", "side": "ally", "targeted": True}}]},
        {"id": "jeer", "archetype": "Burst", "timing": "proactive", "priority": 45,
         "cooldown": 2, "target_rule": "valuation", "telegraph": "Jeer — deal 2",
         "verbs": [_v_hit(2)]}]},
    {"id": "gc_growth", "row": "mid", "attack_mode": "melee", "comps": [
        {"id": "coil", "archetype": "Escalate", "timing": "proactive", "priority": 40,
         "cooldown": 2, "target_rule": "self",
         "telegraph": "Coil — +1/+1, permanently",
         "verbs": [{"kind": "counters", "power": 1, "toughness": 1,
                    "target": {"mode": "self"}}]},
        {"id": "lash", "archetype": "Debilitate", "timing": "proactive", "priority": 30,
         "cooldown": 3, "target_rule": "highest_threat",
         "telegraph": "Lash — deal 3 and stun",
         "verbs": [_v_hit(3), {"kind": "stun",
                               "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}]},
    {"id": "gc_medic", "row": "rear", "attack_mode": "ranged", "comps": [
        {"id": "mend", "archetype": "Fortify", "timing": "proactive", "priority": 20,
         "cooldown": 2, "target_rule": "lowest_hp_ally",
         "telegraph": "Mend — heal an ally 4", "verbs": [_v_heal(4)]},
        {"id": "sting", "archetype": "Burst", "timing": "proactive", "priority": 40,
         "cooldown": 2, "target_rule": "channeling_player",
         "telegraph": "Sting — deal 2", "verbs": [_v_hit(2)]}]},
    {"id": "gc_leech", "row": "rear", "attack_mode": "ranged", "comps": [
        {"id": "drain", "archetype": "Drain", "timing": "proactive", "priority": 30,
         "cooldown": 2, "target_rule": "valuation",
         "telegraph": "Drain — deal 3, heal 3",
         "verbs": [_v_hit(3), {"kind": "heal", "amount": 3, "target": {"mode": "self"}}]},
        {"id": "hiss", "archetype": "Punish", "timing": "reactive", "trigger": "on_targeted",
         "cooldown": 2, "priority": 25, "target_rule": "trigger_source",
         "telegraph": "Hiss — wound -1/-1",
         "verbs": [{"kind": "wound", "power": 1, "toughness": 1,
                    "target": {"mode": "chosen", "side": "ally", "targeted": True}}]}]},
    {"id": "gc_avenger", "row": "front", "attack_mode": "melee", "comps": [
        {"id": "avenge", "archetype": "Escalate", "timing": "reactive",
         "trigger": "on_ally_death", "cooldown": 2, "priority": 18, "target_rule": "self",
         "telegraph": "Avenge — +2/+1, permanently",
         "verbs": [{"kind": "counters", "power": 2, "toughness": 1,
                    "target": {"mode": "self"}}]},
        {"id": "swing", "archetype": "Burst", "timing": "proactive", "priority": 35,
         "cooldown": 2, "target_rule": "valuation", "telegraph": "Swing — deal 3",
         "verbs": [_v_hit(3)]}]},
    {"id": "gc_warden", "row": "front", "attack_mode": "melee", "comps": [
        {"id": "shield", "archetype": "Fortify", "timing": "proactive", "priority": 25,
         "cooldown": 3, "target_rule": "wounded_ally",
         "telegraph": "Shield — heal the most wounded 3", "verbs": [_v_heal(3)]},
        {"id": "rebuke", "archetype": "Punish", "timing": "reactive",
         "trigger": "on_ally_hit", "cooldown": 2, "priority": 25,
         "target_rule": "trigger_source", "telegraph": "Rebuke — deal 3",
         "verbs": [_v_hit(3)]}]},
    {"id": "gc_wisp", "row": "mid", "attack_mode": "ranged", "comps": [
        {"id": "bolt", "archetype": "Burst", "timing": "proactive", "priority": 30,
         "cooldown": 2, "target_rule": "primed_hero", "action_type": "spell",
         "telegraph": "Bolt — deal 3 to the primed", "verbs": [_v_hit(3)]},
        {"id": "wail", "archetype": "Punish", "timing": "reactive",
         "trigger": "on_hero_healed", "cooldown": 2, "priority": 22,
         "target_rule": "trigger_source", "telegraph": "Wail — deal 2",
         "verbs": [_v_hit(2)]}]},
]


def _filler_enemy(spec: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": spec["id"], "name": spec["id"].replace("_", " ").title(),
            "types": ["beast"], "classes": ["warrior"],
            "hp": 6, "power": 2, "level": 2, "row": spec["row"],
            "attack_mode": spec["attack_mode"], "flavor": "a varied body",
            "description": "A shape with its own silhouette and its own threat.",
            "components": [dict(c) for c in spec["comps"]]}


def gate_clean_pool(extra_enemies: Optional[List[Dict[str, Any]]] = None,
                    name: str = "Gate Clean Zzz") -> Dict[str, Any]:
    """A full encounter passing every generation gate. `extra_enemies` are
    placed FIRST in the pool (and first in every layout) so a test can watch its
    own designs ride through generation; fillers round the pool out to 8+."""
    from ltg_game_server.llm import _kit_signature

    def kit(e):
        return frozenset(_kit_signature(c) for c in e.get("components", []))

    extras = [dict(e) for e in (extra_enemies or [])]
    have_ids = {e["id"] for e in extras}
    have_kits = {kit(e) for e in extras}
    # Skip any filler whose kit collides with a test's own design — the factory
    # guarantees a gate-clean pool by construction, whatever the test brings.
    fillers = [_filler_enemy(f) for f in _FILLERS if f["id"] not in have_ids]
    fillers = [e for e in fillers if kit(e) not in have_kits]
    pool = (extras + fillers)[:10]
    assert len(pool) >= 8, "extras collided with too many fillers"
    assert len(extras) <= 4, "the anchors must stay inside the size-3 layout"
    ids = [e["id"] for e in pool]
    anchors = ["gc_brute", "gc_chanter"]
    return {"name": name,
            "scene": "A proving ground of packed sand under storm-lantern light.",
            "enemies": pool,
            "layouts": {"1": ids[:2], "2": ids[:4], "3": ids[:6],
                        # 10 bodies, 8 distinct, ≤2 clones — the clones are the
                        # anchors, so size 4 carries 4 lockdown pieces
                        "4": ids[:8] + anchors},
            "tokens": {}}


@pytest.fixture
def clean_pool():
    return gate_clean_pool
