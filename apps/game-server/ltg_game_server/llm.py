"""LLM encounter generation — OpenRouter client, prompt, and generate/validate loop.

Text generation lives here; image generation lives in art.py (which reuses this
module's key/settings storage and OpenRouter endpoint). It is *content
sourcing* (like content.py): it produces an encounter dict the engine can build,
then hands it to ``content.save_encounter`` for the exact same validation + persist
path an authored encounter takes. It computes no rules.

Settings (API key, model, editable instructions) persist to a single gitignored
JSON file in the loadouts dir (``loadouts/`` is already gitignored — see .gitignore),
so the key never enters version control and survives restarts.
"""

from __future__ import annotations

import json
import random
import re
from math import ceil
from typing import Any, Dict, List, Optional

import httpx

from . import content
from ltg_combat.scenario import _slug

# --------------------------------------------------------------------------- #
# Settings storage
# --------------------------------------------------------------------------- #
SETTINGS_PATH = content.LOADOUTS_DIR / "llm_settings.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Selectable models. `id` is the exact OpenRouter slug sent in the request; edit
# these if a slug 404s (OpenRouter slugs drift). `label` is the dropdown display.
MODELS: List[Dict[str, str]] = [
    {"id": "z-ai/glm-5.2", "label": "GLM 5.2 (z-ai)"},
    {"id": "google/gemini-3.5-flash", "label": "Gemini 3.5 Flash (Google)"},
    {"id": "anthropic/claude-opus-4.8", "label": "Claude Opus 4.8 (Anthropic)"},
]

# Image generation backends (Options → LLM → Art Generation). "openrouter" calls
# the cloud image model below with the stored API key; "comfyui" queues the
# user's own workflow on a local ComfyUI server (see art.py for the protocol and
# the %prompt% / %width% / %height% placeholder contract).
ART_BACKENDS: List[Dict[str, str]] = [
    {"id": "openrouter", "label": "OpenRouter (cloud)"},
    {"id": "comfyui", "label": "ComfyUI (local workstation)"},
]
# The OpenRouter image model. One fixed slug (edit here if it drifts); the
# text-generation model stays independently selectable above.
ART_MODEL = "google/gemini-3.1-flash-lite-image"

# The editable aesthetic wrapper for image generation (Options → LLM → Art
# Generation). It lives here with the rest of the settings machinery so the
# "" == follow-the-default persistence trick (see save_settings) covers it too;
# art.py composes it with per-image task framing + the encounter's own prose.
DEFAULT_ART_STYLE = """A monumental dynamic illustration fusing heroic realism with
high-end manhwa splash art. Hyper-realistic anatomy and meticulously rendered
material textures meet a polished, porcelain-like finish. Powerful, iconic poses
are rendered with dramatic foreshortening. Heroic directional lighting with strong
rim light and volumetric bloom carves glowing, ethereal silhouettes against dark,
atmospheric backdrops. Detailed, layered background; deep moody shadows against
vibrant saturated accents; epic scale, high-fidelity radiant finish. No text, no
lettering, no watermarks, no borders, no UI elements."""

# Encounter Level budget = 2 × party_size × avg_level × multiplier (Update 04 §F-6,
# magnitudes bumped from playtest — the base fight ran too easy even at the old ×1.5
# "hard"). This is the sum of all enemies' levels, i.e. how strong the group is.
DIFFICULTY: Dict[str, float] = {"easy": 1.0, "standard": 1.5, "hard": 2.5}

# Independent of budget, an encounter must field at least this many enemies so the
# party is always outnumbered — 2× the party size (playtest: too few bodies = trivial).
def _min_enemies(size: int) -> int:
    return 2 * max(1, size)

# Every generated enemy's HP is multiplied by this (per difficulty) AFTER the model
# produces it — the chassis baselines (Husk 2, Bruiser 4, Caster-frame 2) are low
# enough that one removal + a chip effect clears them. Scaling HP in code (not via
# the prompt) guarantees the floor regardless of what the model returns or how the
# user has edited the instructions. Kept deliberately shallow: difficulty should
# come from the encounter Level budget (DIFFICULTY) and from being outnumbered
# (_min_enemies), not from HP bloat, which only makes a fight longer.
ENEMY_HP_MULT: Dict[str, float] = {"easy": 1.0, "standard": 1.2, "hard": 1.5}


def _scale_hp(encounter: Dict[str, Any], difficulty: str) -> None:
    """Multiply enemy (and spawned-token) HP in place by the difficulty's factor."""
    mult = ENEMY_HP_MULT.get(difficulty, 1.2)

    def bump(v: Any) -> Any:
        try:
            return max(1, ceil(int(v) * mult))
        except (TypeError, ValueError):
            return v

    for e in encounter.get("enemies", []):
        if isinstance(e, dict) and "hp" in e:
            e["hp"] = bump(e["hp"])
        # Tokens a Swarm spawns are bodies too — beef them so they aren't free kills.
        for c in (e.get("components") or []) if isinstance(e, dict) else []:
            for verb in (c.get("verbs") or []) if isinstance(c, dict) else []:
                if isinstance(verb, dict) and verb.get("kind") == "create_token" and "hp" in verb:
                    verb["hp"] = bump(verb["hp"])
    toks = encounter.get("tokens")
    if isinstance(toks, dict):
        for t in toks.values():
            if isinstance(t, dict) and "hp" in t:
                t["hp"] = bump(t["hp"])

# The editable, reviewable system prompt shown in Options → LLM. It teaches the
# Update 04 enemy framework and pins the exact JSON contract, anchored on two
# verbatim encounters that provably build in the engine.
DEFAULT_INSTRUCTIONS = r"""You are the encounter designer for Langelier Tactical Game (LTG), a tactical
card-combat game. You design a *single thematic enemy group* (an "encounter") that
a party of player-heroes will fight. Your output is consumed by a deterministic
engine, so it MUST be valid JSON matching the schema below — no prose, no markdown.

# Setting & theme (read before designing anything)

LTG is CLASSIC HIGH FANTASY — the register of Magic: The Gathering or Dungeons &
Dragons (Forgotten Realms). Swords, sorcery, monsters, ancient ruins, wild
places. Stay in genre: no science fiction, no modern technology, no firearms.

Pick ONE fresh, specific theme per request and commit to it — a faction, a
place, a reason they stand together. Draw from the genre's full breadth. For
the KIND of range expected (not a menu to pick from):
- a goblin sapper crew undermining the walls of a mountain pass
- the frozen court of a lich-queen and her hollow knights
- sun-bleached tomb guardians waking beneath a desert necropolis
- a fey revel turned feral in a moonlit glade
- an efreet's brass-palace honor guard
- plague-cultists and their rat-swarms in the sewers of a free city
- a hag coven trading in stolen voices at a swamp crossroads
- a frost-giant hunting party with chained wyverns
- animated armory constructs defending a dead wizard's tower
- serpent-folk reavers boiling out of a jungle temple

Combine, twist, or invent well beyond these. Do NOT fall back on the same mood
every time (no perpetual drowned/sunken gothic ruins) — vary the biome, the
faction, the palette, and the emotional register between requests. The request
parameters may list titles the player already owns: treat those as OFF-LIMITS
creative territory — no reused names, locations, or central conceits, and no
re-skins of them.

# The enemy framework (Design Update 04)

An enemy is a **chassis** (its body: HP, Power, attack profile, home row) plus any
number of **components** (its mind: telegraphed abilities and reactions), plus
optional **keywords** (static properties). You compose thematic enemies from these
finite parts; the engine resolves them.

## Chassis (physical baseline — pick one, then optionally buy upgrades)
| chassis | HP | Power | attack | home row | cost |
|---|---|---|---|---|---|
| Husk        | 2 | 1 | melee            | front | 5  |
| Bruiser     | 4 | 2 | melee            | front | 10 |
| Skirmisher  | 2 | 2 | melee + ranged   | mid   | 10 |
| Artillery   | 2 | 2 | ranged           | rear  | 10 |
| Caster-frame| 2 | 1 | ranged           | rear  | 7  |
Upgrade prices: +1 HP = 1 pt · +1 Power = 3 pts · adding a ranged attack = 2 pts.

## Components (abilities — each has a cost; more/complex = higher level)
archetype (typical effect) — base cost:
- Punish (telegraphed retaliation, deal_damage on a trigger) — 3
- Fortify (heal / pump / REGEN self or ally) — 3
- Ward (prevent/protection shield on self or an ally — a bodyguard's shield) — 3
- Evasive (repositioning; pairs with flying/hexproof) — 2
- Burst (extra damage above the basic attack) — 4
- Debilitate (wound / stun / taunt / prevent / POISON) — 4
- Escalate (recurring self-pump / +1/+1 counters / CHARGE gathering) — 4
- Drain (deal_damage + heal self, coupled) — 5
- Counter (REACTIVE ONLY: cancel the hero action on the stack — a counterspell
  on trigger on_spell_cast, or a parry on trigger on_attack) — 3
- Swarm (create_token) — 6
- Necromancy (raise a fallen fellow enemy: `control` on an own-side CORPSE —
  see the corpses section) — 5
Cost modifiers (multiply, round up): cooldown 1 = ×1.5 · cooldown 2–3 = ×1.0 ·
once_per_encounter = ×0.5 · reactive timing = +2 flat after multipliers.

## The two-component minimum & the punching-bag rule (HARD REQUIREMENTS)
- EVERY enemy carries AT LEAST TWO components — two abilities, two spells, or
  ability + spell; proactive + reactive is the classic pairing. A bare statline
  reads as filler at the table and a one-trick body telegraphs its whole game
  on turn one. Cheap fodder affords its second component easily: a reactive
  sting or a once_per_encounter moment costs ×0.5 — the budget-friendly pick.
- The PUNCHING-BAG rule: the engine picks an enemy's top READY proactive
  component every turn and only falls through to the basic attack when none is
  ready — so a proactive self-pump with cooldown 1 fires forever and the enemy
  NEVER attacks: it stacks counters it will never spend, a punching bag the
  party ignores at no cost. Therefore any proactive component whose verbs only
  develop the enemy itself (counters / pump / regen / heal / shield on SELF)
  MUST carry cooldown ≥ 2, so the off-turn swings spend what the pump builds.
  Pumping OTHERS (an anthem, a warband buff, a heal on an ally) is a real turn
  and exempt, as is gathering CHARGE — but a charge gather always needs its
  on_charge_full detonation on the same enemy, or the windup pays off nothing.

## Typed counters: poison, regen, and charge (Design Update 08)
- POISON `{"kind": "poison", "amount": 1, "target": {chosen hero}}` — the victim
  gains 1 counter per amount NOW and again at each Upkeep (each counter is a
  permanent −0/−1) until ANY healing on them cures it. Magnitude: amount 1 per
  tick at any level (an optional `"turns": N` bounds it). Poison is NOT damage —
  it ignores shields and never breaks a channel. It is the anti-turtle,
  anti-channeler pressure: one poisoner per encounter reads as a clock the
  enemy healer forces the party's healer to answer.
- REGEN `{"kind": "regen", "amount": 1, "target": {self or ally}}` (Fortify) —
  the mirror: +0/+1 per tick until the creature is dealt damage that CONNECTS.
  A regen'd elite must be *hit* to be whittled, making chip damage a real
  assignment. Regen ticks count as healing (they cure poison).
- CHARGE — the WINDUP pattern (see its own section below).

## Verb magnitudes scale with the enemy's Level L
deal_damage (Burst/Punish) = L+1 · Drain (damage & heal each) = ceil(L/2)+1 ·
heal (Fortify) = L+2 · pump/wound = ±ceil(L/3) · Escalate counters = +1/+1 ·
lose_life (unpreventable) = ceil(L/2) · stun / taunt = no magnitude (binary) ·
create_token = a Husk at level ceil(L/2), max 2 alive per creator.

## Targeting, conditions, triggers (the full vocabulary — use all of it)
target_rule: "valuation" (the smart default — snipes the killable/casting hero;
a stun/taunt rule automatically spreads: it skips heroes already locked down) ·
"self" · "trigger_source" (reactive: whoever caused the trigger) ·
"lowest_hp_ally" (support: heal/buff the most wounded FELLOW ENEMY; a pure heal
skips allies at full HP, so the healer never wastes a turn) ·
"wounded_ally" (strict support: ONLY fires when an ally is actually hurt) ·
"highest_threat" (assassin's read: the hardest-hitting hero — cut the sword arm) ·
"channeling_player" (sniper: the hero holding a channeled spell — break it) ·
"primed_hero" (the hero primed to spike: holding a live amplify/double_next
combo tag, or with a nearly-full ultimate gauge; falls back to valuation when
nobody is primed, so a rule using it never wastes its turn).

condition (optional gate on any component):
{"kind": "self_hp_pct", "op": "<", "value": 50}   — bloodied behaviour
{"kind": "turn", "op": ">=", "value": 3}          — an escalation timer
{"kind": "ally_count", "op": "<", "value": 2}     — desperation when nearly alone
{"kind": "hero_count", "op": ">=", "value": 3}    — anti-party cleave unlocks vs big parties
{"kind": "hero_channeling", "op": ">=", "value": 1} — arm the ritual-breaker only
  when a hero is actually channeling
{"kind": "self_channeling", "op": ">=", "value": 1} — defend-the-ritual behaviour
  while this enemy holds its own channel
{"kind": "hero_gauge_pct", "op": ">=", "value": 80} — a hero's ultimate gauge is
  nearly full (arm the gauge-punisher only when it matters)
{"kind": "hero_primed", "op": ">=", "value": 1} — a hero holds a live
  amplify/double_next combo tag (a spike is being set up)

trigger (reactive components): "on_hit" (this enemy took damage) · "on_ally_hit" ·
"on_ally_death" · "on_targeted" · "on_spell_cast" (punish or COUNTER casting) ·
"on_attack" (a hero's attack is on the stack — parry/shield/riposte before it lands) ·
"on_incoming_lethal" (an emergency save — heal/prevent to survive the killing blow) ·
"on_ally_below_50" (an ally just fell under 50% — any percent works, e.g. _30) ·
"on_self_below_40" (THIS enemy just fell under 40% — a minion-grade enrage moment;
any percent; give it once_per_encounter so it stays a moment) ·
"on_hero_downed" (a hero was just incapacitated — the pack surges) ·
"on_hero_healed" (a hero regained HP — punish the medic; target_rule
"trigger_source" hits whoever cast the heal) ·
"on_charge_full" (with "charge_threshold": Y — fires the moment this enemy's
charge reaches Y; see the windup section) ·
"on_ultimate_cast" (a hero's ULTIMATE is on the stack — the dread window.
PUNISH freely: damage, wound, stun the caster via target_rule "trigger_source" —
the tyrant makes you pay for your moment, priced as a normal reactive. A
`counter` verb on this trigger is BOSS-ONLY and MUST be once_per_encounter —
cancelling a once-per-fight, gauge-priced ultimate is the most feel-bad answer
in the game, so it is reserved for one dramatic "Tyrant's Contempt" per boss,
ever; the engine rejects anything else).

`"once_per_encounter": true` on a component = a single dramatic use (×0.5 cost).

## Corpses & the undead shelf (Design Update 09 §D9-1)
When a non-token enemy dies it leaves a CORPSE on its row (tokens never do).
Corpses are objects, not creatures — only `control` (raise) and `exile` (burn)
touch them. This unlocks a whole faction archetype, the BODY ECONOMY:
- NECROMANCY (archetype above, base 5): proactive, `"target_rule": "corpse"`
  (the engine finds the nearest own-side corpse; no corpse → the rule skips and
  the priority list falls through, so a Necromancer never wastes a turn), verb
  `{"kind": "control", "target": {"mode": "chosen", "side": "enemy",
  "targeted": true, "state": "corpse"}}` — copy this shape verbatim. The fallen
  minion rises as an enemy-side undead token at HALF its max HP. Classify it
  `"action_type": "spell"` (counterable — Negate-bait). AT MOST ONE Necromancer
  per encounter: necromancy that outpaces the party's removal is a treadmill,
  not a fight.
- RISES (enemy trait, min level 2, cost 3): add `"rises": 2` on the enemy —
  when it dies its corpse visibly STIRS and it revives after 2 Upkeeps at half
  max HP, once per encounter. The enemy is NOT defeated while stirring; the
  party answers by exiling or raising the corpse first. The shambling tide.
- CORPSE-BURST (Burst variant): consume an own-side corpse for a blast — pair
  `"target_rule": "corpse"` with an exile of the corpse plus row damage, e.g.
  `[{"kind": "exile", "target": {"mode": "chosen", "side": "enemy",
  "targeted": true, "state": "corpse"}}, {"kind": "deal_damage", "amount": <X>,
  "target": {"mode": "all", "side": "ally", "rows": ["front"]}}]` — the faction
  that eats its own dead.
Faction guidance: cheap corpse-leaving Husks up front, ONE Necromancer feeding
on the fallen (kill-priority incarnate), a riser or two. Exile and control are
the party's trump cards against it — that tension is the design.

## Forced movement & row blasts (Design Update 09 §D9-3)
The `move` verb shoves a creature between rows, IMMEDIATELY: `{"kind": "move",
"direction": "forward" | "back" | "to_front" | "to_mid" | "to_rear", "target":
{"mode": "chosen", "side": "ally", "targeted": true}}`. Movement re-checks
pending melee intents (Update 15 §L-3): a shove can re-shape the wall and
redirect a swing, but it never cancels an intent outright — it is positional
play, not a soft stun. Blessed patterns:
- The HOOKER (Debilitate variant): `move` a hero `"to_front"`, cooldown 2 —
  drags the caster into the wall's reach; pairs with a front-row biter.
- The LINE-BREAKER: a shove `"back"` on the party's wall, opening your own
  melee lanes to the squishy rows behind it.
At most ONE forced-mover per encounter at standard difficulty; two only at hard.
Row-scoped damage shapes (use them for area attacks):
- a whole row: `{"mode": "all", "side": "ally", "rows": ["front"]}`;
- splash around the picked hero: add `"scope": "row"` (their whole row) or
  `"scope": "blast"` (their row plus adjacent rows; front↔mid, mid↔rear) to a
  chosen target. Only the pick is targeted; the splash is incidental.
Magnitude schedule by scope (T-55): single target = L+1 · a whole row = L per
creature · blast / party-wide = ceil(L/2)+1 — wider is always shallower.

## Positional intents — attacks aimed at a ROW (Design Update 15 §L-5)
Put `"target_row": "front" | "mid" | "rear"` on a proactive component and its
intent aims at GROUND, not a name: no target pick, taunt is ignored, and it
declares even into an empty row. The telegraph names the row ("…prepares an
assault on the front of your party") and occupancy is read when the strike
RESOLVES — so the party dodges it by not standing there, at the price of their
proactive actions. This is the raid-boss pattern: the glowing floor circle.
- Verbs are auto-scoped onto the row: whatever ally-side target you write
  (chosen or all) is normalised to the row footprint `{"mode": "all", "side":
  "ally", "rows": [<the row>]}` — writing the footprint yourself is equally
  fine. Self-riders stay put (a self `counters` stays on the enemy).
- `"action_type": "attack"` makes the swipe answerable by Mitigate and attack
  counters — use it for physical cleaves; "spell" for arcane barrages
  (counterable by Negate-style answers).
- Price per the T-55 row schedule (a whole row = L per creature); a positional
  swipe that whiffs on an empty row still taxed the party's turn economy —
  that is the design, not a bug.
- Give it `cooldown 2` (or make it the windup detonation): every-turn row
  nukes force a scatter-every-turn treadmill instead of a decision. Tune the
  number so a tank CAN choose to stand in it behind Defend/Mitigate.
- The chassis basic attack can be positional too: a legacy `intent` template
  with `"target_row"` aims the basic swing at that row every turn (rare —
  prefer a component with a cooldown).

## The windup (charge — Design Update 08 §D8-2.4)
The most dramatic pattern you have besides a channel: a GATHERER visibly fills a
charge gauge over several turns, and a HIDDEN ability detonates when it fills.
The party watches the pips rise without knowing what they feed — eat it, counter
it on the stack, or stop it from ever filling (kill, stun, strip the gather).
Build it as TWO components on one enemy:
- The gather: proactive, priced as Escalate (4), verbs
  `[{"kind": "charge", "amount": 1}]`, target_rule "self" (charge is enemy-only
  and always self). Its intent reads as "gathering" to the players.
- The detonation: `"timing": "reactive"`, `"trigger": "on_charge_full"`,
  `"charge_threshold": <Y>` — it fires onto the stack the moment charge reaches
  Y and the charge resets. Priced at its archetype base + the reactive +2, no
  further modifier — but its verb magnitudes may spend up to 2× the level
  schedule (the multi-turn delay, the visible gauge, and the disruptability are
  the price). The threshold MUST require at least two gather resolutions
  (Y ≥ 2 × the gather's amount) — a one-turn "windup" is just a Burst; price it
  as one.
Use at most ONE gatherer per encounter, and pair it naturally with a Ward
bodyguard — the party must choose between the wall and the fuse.

## Channelled components (ongoing effects the party must break)
`"channel": true` on a proactive component makes it a CHANNEL: resolving it
starts a held, ongoing effect instead of a one-shot. Its verbs then mean:
- `"duration": "while_channeled"` on a verb = a CONTINUOUS effect that holds
  (an aura): e.g. wound all heroes -1/-1, or pump all fellow enemies +1/+1.
- `"trigger": "upkeep"` on a verb = fires EVERY turn while held (a ritual tick):
  e.g. deal 2 damage to a hero each turn, or spawn a token each turn.
The party breaks a channel by hitting the channeler for ≥25% of its max HP in
ONE hit, or by removing the channeler (kill / bounce / suspend) — and the
channel enters play through the stack, so it can be countered before it exists.
Channels are the strongest decision-generators you have: a visible, growing
threat with a clear answer. Give one to a ritualist/warlock-type enemy (or a
boss phase) and give the channeler real HP so breaking it costs the party a
real hit. A channel can be a "spell" (action_type) — counterable by Negate.
Price a channelled component at its archetype ×1.5 (ongoing value).
At standard difficulty and above, include at least ONE channeler in the
encounter — an aura (party-wide wound / warband anthem) or a ritual tick
(recurring damage / token spawn). Pair it with a guard whose condition
{"kind":"self_channeling"...} lives on the CHANNELER (it protects itself) or
whose Ward targets it — the party must choose between the ritual and the wall.

## Spell vs ability (thematic classification — set it on every component)
Enemies have no cards, but their actions still classify on the action taxonomy,
and players' counters care: `"action_type": "spell"` marks a component as MAGIC —
a spell counter (Negate/Dispel) can cancel it; the default ("ability") is
physical/innate and only broader counters answer it. Classify by fiction:
Fireball / Meteor / Psionic Lance / a curse = "spell" · Life Leech / Sparkbomb /
Spore Fog / venom / a war-cry = "ability" (omit the field). Casters and mystics
should carry spell-classed components — it makes counterspell decks matter.

## Keywords (min level / cost)
reach (1/1) · trample (2/2) · flying (2/4) · lifelink (3/3) · infect (3/3) ·
deathtouch (3/4) · protection (4/3) · hexproof (4/4) · indestructible (6/6).
Infect: any damage the creature deals that CONNECTS also poisons the victim
(one unbounded poison effect per connecting hit, first counter at the next
Upkeep). An infected biter turns every landed hit into a healer assignment —
pair it with pressure that punishes healing (on_hero_healed) for a genuinely
nasty knot, and use AT MOST ONE infect creature per encounter.
Hexproof wards off targeted SPELLS and ABILITIES only — basic attacks still land
on a hexproof creature (both directions), so a hexproof enemy is spell-slippery,
not unhittable.
NEVER put first strike, vigilance, or haste on an enemy (those are player-only).

## Budget → Level (this is how you scope difficulty)
Per-enemy budget by level: B(L) = 5·L + 5  → L1=10, L2=15, L3=20, L4=25, L5=30,
L8=45, L10=55. An enemy's **level is the smallest L whose budget covers its total
cost** (chassis + upgrades + keywords + components after modifiers). Underspending
is fine; overspending is impossible. Complexity self-prices into level.

# Design guidance (make it fun, challenging, thematic)
- All enemies share ONE faction/theme — cohesive palette (no frost giants in a
  vampire coven). Give the encounter an evocative name and each enemy a flavor line.
- Build a *tactical puzzle*, not a stat wall: mix rows (a front bruiser to block, a
  rear caster to answer, a mid harasser), and give at least one enemy a component
  that forces a decision. Reactions (on_hit, on_spell_cast) punish careless play.
- Challenge comes from DECISIONS, not stats. The proven patterns — use 2–3 per
  encounter:
  * A SUPPORT enemy (Fortify + target_rule lowest_hp_ally): creates kill-priority.
  * An ESCALATE clock (counters +1/+1, self, cooldown 2 — NEVER 1, see the
    punching-bag rule): ignore it and lose — the pump lands every other turn
    and the swings between grow. Pair the clock with a reaction or a second
    ability so the stacked counters are always being spent on someone.
  * An EMERGENCY SAVE (reactive on_incoming_lethal, heal/prevent self): breaks
    exact-lethal maths; the party must overkill or double-tap.
  * An AVENGER (reactive on_ally_death, permanent counters on self): punishes
    naive kill order — pairs beautifully with expendable Swarm tokens.
  * A CONTROL piece (Debilitate: stun a hero, or taunt to drag their attacks):
    attacks the party's action economy — the sharpest knife in the drawer. The
    engine spreads control automatically (a stun rule skips already-stunned
    heroes), so two control pieces don't waste each other.
  * A COUNTERSPELL SENTINEL (reactive Counter, trigger on_spell_cast, verb
    {"kind":"counter","filter":"spell"}, cooldown 2–3): the enemy side's answer to
    the stack. Suddenly the party must bait it or play around it. A duellist
    variant counters ATTACKS instead (trigger on_attack, filter "attack"). Use at
    most ONE counter-piece per encounter, always with a cooldown — it frustrates
    when spammed, thrills when scarce.
  * A WARD BODYGUARD (Ward: prevent/protection onto the channeler or the boss,
    target_rule a fixed ally id or "self"): layers the kill-priority puzzle.
  * A RITUALIST (a channel component): the centerpiece decision — see channels.
  * A BLOODIED TURN (reactive on_self_below_40, once_per_encounter: counters,
    a heal, or a desperate AoE): every elite minion deserves one dramatic moment.
  * An EXECUTIONER (reactive on_hero_downed: the pack surges — counters on self or
    a free hit): downing a hero must feel dangerous for the OTHERS too.
  * A MEDIC-PUNISHER (reactive on_hero_healed, target_rule trigger_source): makes
    the party's sustain a decision instead of a free loop.
  * A TIMER (condition turn >= N unlocking a bigger ability): punishes turtling.
  * A POISONER (Debilitate with a poison verb): the anti-turtle clock — the
    party must spend healing to cure it or race it. At most one per encounter.
  * A GATHERER (the charge windup — see its section): a visible fuse under a
    veiled kit; the drama is the gauge filling while the party guesses.
  * A GAUGE-PUNISHER (reactive Debilitate/Punish, condition
    {"kind":"hero_gauge_pct","op":">=","value":80} or trigger
    "on_ultimate_cast", target_rule "primed_hero" / "trigger_source"): makes
    charging an ultimate a DECISION, not a free ride — the hero nearing the
    dread window becomes the fight's centre of gravity. AT MOST ONE per
    encounter; it exists to tax the moment, never to lock it out.
- MECHANICAL VARIETY (anti-rut rules — as binding as the budgets):
  * The pattern list above is a PALETTE, not a checklist. Each encounter leans
    on a DIFFERENT 2–3 patterns; across many generations every pattern should
    see play, including the ones you'd otherwise skip (body economy, forced
    movement, charge windups, poison clocks, counter-sentinels, taunt/stun
    control, infect, regen elites, avengers, medic-punishers).
  * The well-worn rut is: a lowest_hp_ally healer + an Escalate clock + a
    damage-tick channel + a −1/−1 hexer. Do NOT build that quartet again unless
    the player's note asks for it.
  * Give the encounter ONE SIGNATURE mechanic — the thing this fight is ABOUT,
    which the layouts, the guard pieces, and the boss (if any) all serve — and
    let it pose a tactical question beyond "kill order?": Can we afford to
    heal? Burn the corpses or race the necromancer? Eat the detonation or break
    the fuse? How do we keep the backline off the hook?
  * Vary the damage SHAPES across the pool (single-target snipe, row sweep,
    blast splash, upkeep tick, unpreventable lose_life, poison) and the
    target_rules (not everything "valuation" — use highest_threat,
    channeling_player, wounded_ally, trigger_source where the fiction fits).
  * The request parameters below may ROLL suggested signature mechanics for
    this generation — treat a roll as the encounter's default identity unless
    the player's note pulls elsewhere.
- Respect the per-party-size Level budgets you are given below: for each layout,
  the sum of its enemies' levels (a boss counts double) should land near that
  size's target. The party must be OUTNUMBERED at every size — each layout must
  field at least the required minimum count (never fewer). Make the extra bodies
  count: vary them across rows and roles rather than cloning one statline.

# Party-size layouts (REQUIRED — the encounter must scale 1–4 heroes)
Design ONE thematic enemy pool in `"enemies"`, then assign a roster per party
size in a top-level `"layouts"` object: keys "1"–"4", each a list of enemy ids
drawn from the pool. The engine fields the layout matching the party that starts
the game. Rules:
- An id may REPEAT in a layout — the engine clones it ("wolf", "wolf 2"), so big
  parties face more bodies of the same design. Duplicates count toward the
  minimum and the budget (a repeated level-2 wolf costs 2 each time).
- The boss (if any) appears in EVERY layout — it is the encounter's centerpiece.
  Solo layouts around a boss should thin the minions, never drop the boss.
- Scale by both COUNT and ROLE: a solo hero faces the core puzzle in miniature
  (2–3 bodies, one decision-generator); a full party of 4 faces the whole war
  band (8+ bodies, support + control + clock all live).
- Every enemy in the pool should appear in at least one layout.

# Bosses (only when the parameters below ask for one)
One enemy may carry `"is_boss": true` — never more than one. A boss:
- spends up to 2.5 × B(L) at its level (a level-6 boss spends up to 87) and counts
  as DOUBLE its level toward the encounter total. Surround it with real minions.
- cannot be destroyed / exiled / bounced above 25% HP (the engine enforces this
  "execute window") — so give it real HP; the party must whittle it down.
- ENRAGES at 25% HP: give it one component with `"archetype": "Enrage"` — it costs
  no budget and auto-fires ONCE, going on the stack when the boss first drops below
  25%. Enraging is a HARD TURN: the engine also shakes off any stun/taunt on the
  boss and resets its ability cooldowns, so the post-enrage kit opens at full
  aggression. Write the Enrage itself as a MULTI-VERB eruption — stack 2–3 verbs:
  permanent +X/+X counters AND an AoE hit AND/OR a token wave / a big self-heal /
  a granted keyword (e.g. trample). One small pump is a wasted climax.
- may phase-gate other components with `"phase": "pre_enrage"` or `"post_enrage"`
  so the fight transforms when it turns: e.g. a single-target breath before, a
  party-wide firestorm after. Give the post-enrage kit a clearly scarier shape —
  the fight's final act should FEEL different, not just bigger numbers.
- VARY THE BOSS SILHOUETTE — the worked example's "big breath pre / AoE post /
  pump-and-burn Enrage" is ONE shape, not the mold. Fit the silhouette to the
  faction, e.g.: the SUMMONER-TYRANT (token waves + a warband anthem; Enrage =
  a fresh wave + permanent pump) · the RITUALIST (a channelled aura or tick the
  party must break while the execute window looms; Enrage restarts the rite
  harder) · the DUELLIST (a parry-Counter, a Punish riposte, taunts; Enrage
  grants trample + a permanent pump) · the NECROMANCER-KING (raises its fallen
  court; Enrage = raise a corpse AND a token wave) · the GATHERER TITAN (charge
  windups set the fight's rhythm; post-enrage, a second detonation on a shorter
  fuse) · the WARLORD (row blasts and forced movement; Enrage = shove the wall
  back + blast the exposed rows).
- declares TWO intents per round once enraged (engine-enforced — Design Update
  09 §D9-4). Design the post-enrage kit knowing every component fires twice as
  often: cooldowns matter double, and the guaranteed basic attack backstops the
  second slot every round.
- Elite minions can carry their own mini-enrage: a reactive component on
  `"trigger": "on_self_below_50"` (any percent) with once_per_encounter — the
  fight stays dynamic even away from the boss.
- Every proactive component needs a `telegraph` and a `priority` (lower =
  considered first; 10–19 emergencies, 20–49 tactical, basic attack is
  implicitly 90). Give ability components a `cooldown` (2 is typical).
  NOTE (Design Update 08 §D8-1): the telegraph is NO LONGER shown while the
  intent is declared — players see only a generic category ("threatens…",
  "begins casting a spell…", "gathers its power…"). The telegraph is the
  action's ON-STACK NAME when it executes, and the reveal text when a hero
  strips the intent. Write it well anyway: it is what the players learn.

# Scene & visual descriptions (REQUIRED — they feed art + narration)
- Top-level `"scene"`: 2–3 sentences describing the SETTING where this fight
  happens, on theme. Concrete and visual — location, light, weather, one or two
  striking details an artist could paint as the battle backdrop.
- Every enemy gets a `"description"`: 1–2 sentences of PHYSICAL appearance —
  size/silhouette, anatomy, colors, materials, gear, how it moves. Write what a
  character artist needs; no mechanics, no backstory. The boss deserves the most
  vivid one. (`flavor` stays the short mechanical hint; `description` is the look.)

# Output JSON contract (return EXACTLY this shape, nothing else)
{
  "name": "Encounter name",
  "scene": "2–3 sentence setting description (the battle backdrop)",
  "enemies": [
    {
      "id": "snake_case_id",           // unique; derived from the name
      "name": "Enemy Name",
      "flavor": "one-line mechanical hint",
      "description": "1–2 sentence physical appearance (for art/narration)",
      "hp": <int>,                      // chassis HP after upgrades
      "power": <int>,                   // basic-attack damage (chassis Power)
      "level": <int>,                   // derived from total cost via B(L)
      "row": "front" | "mid" | "rear",
      "home_row": "front" | "mid" | "rear",   // optional; where it redeploys to
      "attack_mode": "melee" | "ranged",
      "is_boss": true,                  // AT MOST ONE enemy, only when asked for
      "rises": 2,                       // optional undead trait (min level 2, cost 3): revives after 2 Upkeeps, once
      "keywords": ["flying", ...],      // may be []
      "components": [                   // REQUIRED: at least TWO per enemy (the two-component rule)
        {
          "id": "snake_case",
          "archetype": "Drain" | "Fortify" | "Punish" | "Debilitate" | "Evasive" |
                       "Burst" | "Escalate" | "Swarm" | "Enrage",
          "timing": "proactive" | "reactive",
          "trigger": "<from the trigger vocabulary above>",  // reactive only
          "charge_threshold": <int>,    // on_charge_full only: fires at this charge
          "condition": {"kind": "self_hp_pct", "op": "<", "value": 50},   // optional gate
          "cooldown": <int>,            // turns between uses, e.g. 2
          "once_per_encounter": true,   // optional; a single dramatic use
          "priority": <int>,            // lower = evaluated first
          "target_rule": "valuation" | "self" | "trigger_source" | "lowest_hp_ally" | "channeling_player" | "primed_hero",
          "action_type": "spell",       // MAGIC components only (counterable by spell counters); omit for physical
          "channel": true,              // ongoing held effect (see channel rules); omit for one-shots
          "phase": "pre_enrage" | "post_enrage",   // boss components only; optional
          "move_home": true,            // Evasive only: reposition toward home_row
          "telegraph": "Intent text shown to players",   // proactive
          "verbs": [                    // the effects; omit for pure Evasive
            {"kind": "deal_damage", "amount": <int>, "target": {"mode": "chosen", "side": "ally", "targeted": true}},
            {"kind": "deal_damage", "amount": <int>, "target": {"mode": "all", "side": "ally"}},   // AoE: every hero
            {"kind": "deal_damage", "amount": <int>, "target": {"mode": "all", "side": "ally", "rows": ["front"]}},  // ROW assault (T-55: L per creature)
            {"kind": "deal_damage", "amount": <int>, "target": {"mode": "chosen", "side": "ally", "targeted": true, "scope": "blast"}},  // BLAST: the pick + its row + adjacent rows
            {"kind": "move", "direction": "to_front", "target": {"mode": "chosen", "side": "ally", "targeted": true}},  // the Hooker's drag; "back" for a Line-breaker
            {"kind": "control", "target": {"mode": "chosen", "side": "enemy", "targeted": true, "state": "corpse"}},    // NECROMANCY ONLY: raise an own-side corpse (target_rule "corpse")
            {"kind": "lose_life",   "amount": <int>, "target": {"mode": "chosen", "side": "ally", "targeted": true}},  // unpreventable
            {"kind": "heal",        "amount": <int>, "target": {"mode": "self"}},          // or chosen ally (see target_rule)
            {"kind": "wound", "power": <int>, "toughness": <int>, "target": {"mode": "chosen", "side": "ally", "targeted": true}},
            {"kind": "pump",  "power": <int>, "toughness": <int>, "target": {"mode": "self"}},     // this-turn buff
            {"kind": "counters", "power": <int>, "toughness": <int>, "target": {"mode": "self"}},  // PERMANENT (Escalate)
            {"kind": "stun",  "target": {"mode": "chosen", "side": "ally", "targeted": true}},     // hero loses a turn
            {"kind": "taunt", "target": {"mode": "chosen", "side": "ally", "targeted": true}},     // hero must attack me
            {"kind": "prevent", "parameter": "combat_damage", "uses": "next", "target": {"mode": "self"}},  // a shield; parameter ∈ combat_damage (attacks + activated abilities) | spell_damage (spells + triggered) | all_damage
            {"kind": "amplify", "event": "combat_damage", "multiplier": 2, "bonus": 0, "target": {"mode": "self"}},  // COMBO primer: its next matching damage ×2 (+bonus); event ∈ combat_damage|spell_damage|any_damage|heal; also targets an ally enemy
            {"kind": "double_next", "filter": "spell", "target": {"mode": "self"}},   // its next spell/ability to resolve, resolves twice; filter ∈ spell|ability|action
            {"kind": "copy_spell"},                               // REACTIVE only (on_spell_cast): copies the triggering spell — the copy MIRRORS back at its caster; NO target field
            {"kind": "heal", "amount": {"ref": "caster_last_damage"}, "target": {"mode": "self"}},  // retro combo: heal the last damage this enemy took
            {"kind": "protection", "target": {"mode": "self"}},   // negates the next spell/attack entirely (Ward)
            {"kind": "counter", "filter": "spell"},               // REACTIVE Counter only: cancels the triggering action; "attack" filter for a parry; NO target field
            {"kind": "poison", "amount": 1, "target": {"mode": "chosen", "side": "ally", "targeted": true}},  // Debilitate: −0/−1 per Upkeep until healed
            {"kind": "regen",  "amount": 1, "target": {"mode": "self"}},   // Fortify: +0/+1 per Upkeep until damaged
            {"kind": "charge", "amount": 1},                      // gather (windup); enemy-only, always self, NO target field
            {"kind": "grant_keyword", "keywords": ["flying"], "duration": "encounter", "target": {"mode": "chosen", "side": "ally", "targeted": true}},
            {"kind": "create_token", "token_id": "<id in tokens>", "count": <int>, "hp": <int>, "power": <int>},
            {"kind": "wound", "power": 1, "toughness": 1, "duration": "while_channeled", "target": {"mode": "all", "side": "ally"}},   // CHANNEL aura: holds until broken
            {"kind": "pump", "power": 1, "toughness": 1, "duration": "while_channeled", "target": {"mode": "all", "side": "enemy"}},   // CHANNEL anthem: pumps the warband while held
            {"kind": "deal_damage", "amount": 2, "trigger": "upkeep", "target": {"mode": "chosen", "side": "ally", "targeted": true}}  // CHANNEL tick: fires every turn
          ]
        }
      ]
    }
  ],
  "layouts": {                          // REQUIRED: the roster per party size (ids from "enemies"; repeats clone)
    "1": ["enemy_a", "enemy_b"],
    "2": ["enemy_a", "enemy_a", "enemy_b", "enemy_c"],
    "3": ["enemy_a", "enemy_a", "enemy_b", "enemy_b", "enemy_c", "enemy_d"],
    "4": ["enemy_a", "enemy_a", "enemy_a", "enemy_b", "enemy_b", "enemy_c", "enemy_c", "enemy_d"]
  },
  "tokens": {                           // token definitions ONLY if a Swarm spawns them
    "huskling": {"name": "Huskling", "hp": 2, "power": 1, "row": "front", "attack_mode": "melee"}
  }
}

IMPORTANT verb-target convention: `{"mode": "chosen", "side": "ally", "targeted": true}`
means "the combatant this component's target_rule picked" — a hero for damage/stun/
taunt (valuation / trigger_source / channeling_player), a fellow enemy for a support
heal/buff (lowest_hp_ally). A self-effect uses `{"mode": "self"}`; an AoE on the party
uses `{"mode": "all", "side": "ally"}`. Copy these shapes verbatim — do not invent new
target shapes. The `counter` and `copy_spell` verbs are REACTIVE-ONLY (components
answering on_spell_cast / on_attack) and take no target field — the engine aims
them at the action that tripped the trigger (a `copy_spell` copy mirrors back at
the spell's caster, so give it ONLY to a spell-mirror sentinel and expect hostile
spells to rebound). `amplify` and `double_next` are combo primers: use them as a
windup the party can see coming (prime, then swing) — priming is one-shot and
holds until spent. NEVER use these verbs (player-only; they do nothing
or break the fight): destroy, bounce, strip_intent, fight, revive, draw, scry,
move_card, ramp, add_mana, stance. `control` is enemy-legal ONLY on corpses (the
Necromancy shape above — never on a living hero), and `exile` is enemy-legal ONLY
on an own-side corpse (the Corpse-burst shape). Never grant enemies first_strike /
vigilance / haste.

# Three worked examples that build correctly (study these, then design your own)

EXAMPLE A — a B/R vampire coven (pool of 3 designs, scaled 1–4 by layouts):
{"name":"Crimson Coven — Drain & Reactions","scene":"A desecrated hillside chapel at midnight: pews toppled, red votive candles guttering in pools of wax, and a shattered rose window casting broken moonlight across a blood-slick altar.","enemies":[
 {"id":"grave_thrall","name":"Grave Thrall","flavor":"A wall that shambles forward and drags heroes into its reach.","description":"A bloated corpse in rusted chainmail, grey-green skin split at the seams, dragging a bell-heavy mace behind it.","hp":6,"power":1,"level":3,"row":"front","attack_mode":"melee",
  "components":[
   {"id":"corpse_grip","archetype":"Debilitate","timing":"proactive","priority":30,"cooldown":3,"target_rule":"valuation","telegraph":"Corpse-Grip — taunt a hero into the wall","verbs":[
     {"kind":"taunt","target":{"mode":"chosen","side":"ally","targeted":true}}]},
   {"id":"grave_chill","archetype":"Debilitate","timing":"reactive","trigger":"on_hit","cooldown":2,"priority":25,"target_rule":"trigger_source","telegraph":"Grave-Chill — wound the attacker -1/-1","verbs":[
     {"kind":"wound","power":1,"toughness":1,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},
 {"id":"bloodbat","name":"Bloodbat","flavor":"A dodging flyer only ranged/reach answers — it shrieks when hunted.","description":"A dog-sized bat with wet crimson fur, tattered wing membranes, and a cluster of pearl-white eyes.","hp":2,"power":2,"level":3,"row":"mid","home_row":"rear","attack_mode":"melee","keywords":["flying"],
  "components":[
   {"id":"evasive","archetype":"Evasive","timing":"proactive","priority":20,"move_home":true,"target_rule":"self","telegraph":"Flit to the shadows"},
   {"id":"shriek","archetype":"Debilitate","timing":"reactive","trigger":"on_targeted","cooldown":2,"priority":25,"target_rule":"trigger_source","telegraph":"Piercing Shriek — wound the hunter -1/-1","verbs":[
     {"kind":"wound","power":1,"toughness":1,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},
 {"id":"vampire_adept","name":"Vampire Adept","flavor":"Drains from safety, punishes your casting.","description":"A gaunt aristocrat in a high-collared black robe, chalk-white skin stretched over sharp bones, fingertips stained to the knuckle with old blood.","hp":6,"power":1,"level":4,"row":"rear","attack_mode":"ranged","keywords":["lifelink"],
  "components":[
   {"id":"drain","archetype":"Drain","timing":"proactive","priority":30,"cooldown":2,"target_rule":"valuation","telegraph":"Life Drain — deal 3, heal 3","verbs":[
     {"kind":"deal_damage","amount":3,"target":{"mode":"chosen","side":"ally","targeted":true}},
     {"kind":"heal","amount":3,"target":{"mode":"self"}}]},
   {"id":"curse","archetype":"Debilitate","timing":"reactive","trigger":"on_spell_cast","cooldown":2,"priority":20,"target_rule":"trigger_source","action_type":"spell","telegraph":"Withering Curse — wound the caster -1/-1","verbs":[
     {"kind":"wound","power":1,"toughness":1,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]}
],"layouts":{
 "1":["grave_thrall","bloodbat"],
 "2":["grave_thrall","grave_thrall","bloodbat","bloodbat"],
 "3":["grave_thrall","grave_thrall","grave_thrall","bloodbat","bloodbat","vampire_adept"],
 "4":["grave_thrall","grave_thrall","grave_thrall","grave_thrall","bloodbat","bloodbat","vampire_adept","vampire_adept"]
},"tokens":{}}

EXAMPLE B — a ritual CHANNEL, a counterspell sentinel, a bloodied moment, smart healing, and a token swarm:
{"name":"Ironhide's Warband — Rite of the Boar","scene":"A palisaded war-camp gouged into a muddy hillside: banner poles of lashed bone, cookfires burned low, and churned earth littered with cracked shields.","enemies":[
 {"id":"ironhide","name":"Ironhide Warleader","flavor":"Swings while healthy; erupts when bloodied; punishes melee.","description":"A boar-headed brute two heads taller than a man, plated in riveted scrap-iron, bronze-capped tusks, hefting a chained maul.","hp":10,"power":3,"level":5,"row":"front","attack_mode":"melee","keywords":["trample"],
  "components":[
   {"id":"bloodied_roar","archetype":"Escalate","timing":"reactive","trigger":"on_self_below_50","once_per_encounter":true,"priority":12,"target_rule":"self","telegraph":"BLOODIED ROAR — +2/+1, permanently","verbs":[
     {"kind":"counters","power":2,"toughness":1,"target":{"mode":"self"}}]},
   {"id":"punish","archetype":"Punish","timing":"reactive","trigger":"on_hit","cooldown":2,"priority":25,"target_rule":"trigger_source","telegraph":"Retaliate — deal 2 to the attacker","verbs":[
     {"kind":"deal_damage","amount":2,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},
 {"id":"bonechanter","name":"Bonechanter of the Sty","flavor":"Holds a rite that bleeds the party every turn — break it or drown.","description":"A hunched shaman draped in boar hides and knotted fetishes, rattling a staff of fused vertebrae that weeps a red haze.","hp":8,"power":1,"level":5,"row":"rear","attack_mode":"ranged",
  "components":[
   {"id":"blood_rite","archetype":"Drain","timing":"proactive","channel":true,"action_type":"spell","cooldown":3,"priority":20,"target_rule":"valuation","telegraph":"Blood Rite — a held ritual: 2 damage every turn and the party fights at -1/-0","verbs":[
     {"kind":"deal_damage","amount":2,"trigger":"upkeep","target":{"mode":"chosen","side":"ally","targeted":true}},
     {"kind":"wound","power":1,"toughness":0,"duration":"while_channeled","target":{"mode":"all","side":"ally"}}]},
   {"id":"mend","archetype":"Fortify","timing":"proactive","priority":30,"cooldown":2,"target_rule":"wounded_ally","telegraph":"Knit Hide — heal the most wounded ally 5","verbs":[
     {"kind":"heal","amount":5,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},
 {"id":"broodmother","name":"Hive Broodmother","flavor":"Spawns Husklings, at most two alive.","description":"A swollen, chitin-backed matriarch the size of an ox-cart, egg-sacs glistening along her flanks, dozens of larval eyes blinking in the dark.","hp":4,"power":2,"level":3,"row":"rear","attack_mode":"melee",
  "components":[
   {"id":"swarm","archetype":"Swarm","timing":"proactive","priority":20,"cooldown":2,"target_rule":"self","telegraph":"Spawn Husklings (x2)","verbs":[
     {"kind":"create_token","token_id":"huskling","count":2,"hp":2,"power":1}]},
   {"id":"brood_fury","archetype":"Escalate","timing":"reactive","trigger":"on_ally_death","once_per_encounter":true,"priority":15,"target_rule":"self","telegraph":"Brood-Fury — +1/+1, permanently","verbs":[
     {"kind":"counters","power":1,"toughness":1,"target":{"mode":"self"}}]}]},
 {"id":"mistveil_hexer","name":"Mistveil Hexer","flavor":"Silences one spell a fight and chips your board; hard to pin.","description":"A wiry figure wrapped in grey rags that bleed mist, face hidden behind a cracked porcelain mask, fingers ending in needle-long silver rings.","hp":5,"power":2,"level":4,"row":"mid","home_row":"rear","attack_mode":"melee","keywords":["hexproof"],
  "components":[
   {"id":"hush","archetype":"Counter","timing":"reactive","trigger":"on_spell_cast","cooldown":3,"priority":15,"action_type":"spell","target_rule":"trigger_source","telegraph":"Hushing Mist — counter the spell","verbs":[
     {"kind":"counter","filter":"spell"}]},
   {"id":"hex","archetype":"Debilitate","timing":"proactive","priority":30,"cooldown":1,"target_rule":"valuation","telegraph":"Withering Hex — wound -1/-1","verbs":[
     {"kind":"wound","power":1,"toughness":1,"target":{"mode":"chosen","side":"ally","targeted":true}}]},
   {"id":"evasive","archetype":"Evasive","timing":"proactive","priority":20,"move_home":true,"target_rule":"self","telegraph":"Miststep"}]}
],"layouts":{
 "1":["ironhide","broodmother"],
 "2":["ironhide","bonechanter","broodmother","mistveil_hexer"],
 "3":["ironhide","bonechanter","broodmother","broodmother","mistveil_hexer","mistveil_hexer"],
 "4":["ironhide","ironhide","bonechanter","bonechanter","broodmother","broodmother","mistveil_hexer","mistveil_hexer"]
},"tokens":{"huskling":{"name":"Huskling","hp":2,"power":1,"row":"front","attack_mode":"melee"}}}

EXAMPLE C — a BOSS encounter: phase gates, enrage, a healer, an escalate clock, and
action-economy control (total weight: boss 6×2=12 + 3 + 3 + 3 = 21). Note the
Emberling's escalate clock: the pump is cooldown 2, so every off-turn it SWINGS
with everything it has stacked — never a cooldown-1 self-pump (punching-bag rule):
{"name":"Court of the Ashen Tyrant","scene":"A throne hall carved into a dead volcano: obsidian pillars veined with cooling magma, ash drifting like snow past braziers of dragonfire, and a basalt throne atop a stair of fused shields.","enemies":[{"id":"ashen_tyrant","name":"Ashen Tyrant","flavor":"A dragon-blooded warlord. Unkillable until bloodied; furious after.","description":"A towering dragon-blooded warlord, scales of cracked basalt glowing ember-orange at the seams, cloaked in scorched war-banners, dragging a greatsword still white-hot from the forge.","hp":24,"power":3,"level":6,"row":"front","attack_mode":"melee","is_boss":true,"keywords":["trample"],"components":[{"id":"cinder_breath","archetype":"Burst","timing":"proactive","phase":"pre_enrage","priority":30,"cooldown":2,"target_rule":"valuation","telegraph":"Cinder Breath — deal 7","verbs":[{"kind":"deal_damage","amount":7,"target":{"mode":"chosen","side":"ally","targeted":true}}]},{"id":"firestorm","archetype":"Burst","timing":"proactive","phase":"post_enrage","priority":20,"cooldown":2,"target_rule":"self","action_type":"spell","telegraph":"Firestorm — 4 to ALL heroes","verbs":[{"kind":"deal_damage","amount":4,"target":{"mode":"all","side":"ally"}}]},{"id":"tyrants_fury","archetype":"Enrage","priority":5,"target_rule":"self","telegraph":"TYRANT'S FURY — +2/+2 permanently, and the hall burns for 3","verbs":[{"kind":"counters","power":2,"toughness":2,"target":{"mode":"self"}},{"kind":"deal_damage","amount":3,"target":{"mode":"all","side":"ally"}}]}]},{"id":"cinderpriest","name":"Cinderpriest","flavor":"Keeps the court standing. Kill the healer or drown in mended wounds.","description":"A stooped acolyte in layered ash-grey vestments, face veiled in smoke-stained gauze, cradling a censer that leaks glowing cinders.","hp":6,"power":1,"level":3,"row":"rear","attack_mode":"ranged","components":[{"id":"mend","archetype":"Fortify","timing":"proactive","priority":20,"cooldown":2,"target_rule":"lowest_hp_ally","telegraph":"Searing Mend — heal an ally 5","verbs":[{"kind":"heal","amount":5,"target":{"mode":"chosen","side":"ally","targeted":true}}]},{"id":"rescue","archetype":"Fortify","timing":"reactive","trigger":"on_ally_below_50","priority":15,"cooldown":2,"target_rule":"lowest_hp_ally","telegraph":"Emergency Rite — heal 5","verbs":[{"kind":"heal","amount":5,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},{"id":"emberling","name":"Emberling","flavor":"Grows hotter every turn it is ignored — and spends that heat on you.","description":"A knee-high sprite of living flame, its coal-black core wrapped in dancing orange fire that flares taller each time it feeds.","hp":4,"power":1,"level":3,"row":"mid","attack_mode":"ranged","components":[{"id":"stoke","archetype":"Escalate","timing":"proactive","priority":40,"cooldown":2,"target_rule":"self","telegraph":"Stoke the Flames — +1/+1, permanently","verbs":[{"kind":"counters","power":1,"toughness":1,"target":{"mode":"self"}}]},{"id":"flare_snap","archetype":"Punish","timing":"reactive","trigger":"on_hit","cooldown":2,"priority":25,"target_rule":"trigger_source","telegraph":"Flare-Snap — deal 4 to the attacker","verbs":[{"kind":"deal_damage","amount":4,"target":{"mode":"chosen","side":"ally","targeted":true}}]}]},{"id":"ashfang_zealot","name":"Ashfang Zealot","flavor":"Bullies the sword arm: dazes casters, drags attention to itself.","description":"A scarred fanatic in blackened half-plate, jaw tattooed with flame sigils, twin hooked blades smoking at their edges.","hp":8,"power":2,"level":3,"row":"front","attack_mode":"melee","components":[{"id":"skull_ring","archetype":"Debilitate","timing":"proactive","priority":30,"cooldown":3,"target_rule":"valuation","telegraph":"Skull-Ringer — stun a hero (loses a turn)","verbs":[{"kind":"stun","target":{"mode":"chosen","side":"ally","targeted":true}}]},{"id":"challenge","archetype":"Debilitate","timing":"reactive","trigger":"on_ally_hit","priority":25,"cooldown":2,"target_rule":"trigger_source","telegraph":"Blood Challenge — taunt the attacker","verbs":[{"kind":"taunt","target":{"mode":"chosen","side":"ally","targeted":true}}]}]}],"layouts":{
 "1":["ashen_tyrant","cinderpriest"],
 "2":["ashen_tyrant","cinderpriest","emberling","ashfang_zealot"],
 "3":["ashen_tyrant","cinderpriest","emberling","emberling","ashfang_zealot","ashfang_zealot"],
 "4":["ashen_tyrant","cinderpriest","cinderpriest","emberling","emberling","ashfang_zealot","ashfang_zealot","ashfang_zealot"]
},"tokens":{}}

Design a brand-new encounter (do not copy the examples' theme). Return ONLY the JSON."""


def _default_settings() -> Dict[str, Any]:
    return {"api_key": "", "model": MODELS[0]["id"],
            "instructions": DEFAULT_INSTRUCTIONS, "art_style": DEFAULT_ART_STYLE,
            "art_backend": "openrouter", "comfyui_url": "", "comfyui_workflow": ""}


def load_settings() -> Dict[str, Any]:
    """The full settings dict (including the raw api_key), defaults merged in."""
    out = _default_settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        if isinstance(data, dict):
            for k in ("api_key", "model", "instructions", "art_style",
                      "art_backend", "comfyui_url", "comfyui_workflow"):
                if isinstance(data.get(k), str) and data[k] != "":
                    out[k] = data[k]
    except (OSError, json.JSONDecodeError):
        pass
    return out


def public_settings() -> Dict[str, Any]:
    """Settings for the UI — never leaks the raw key, just whether one is set."""
    s = load_settings()
    return {
        "model": s["model"],
        "instructions": s["instructions"],
        "art_style": s["art_style"],
        "art_backend": s["art_backend"],
        "art_backends": ART_BACKENDS,
        "art_model": ART_MODEL,
        "comfyui_url": s["comfyui_url"],
        "comfyui_workflow": s["comfyui_workflow"],
        "models": MODELS,
        "has_key": bool(s["api_key"]),
        "difficulties": list(DIFFICULTY.keys()),
    }


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a partial update and persist. An absent/empty ``api_key`` leaves the
    stored key untouched (so editing the model/instructions never wipes the key);
    pass ``api_key: null`` explicitly to clear it. ``instructions: null`` resets to
    the built-in default. Returns ``public_settings``.

    Instructions matching the default are stored as "" (i.e. *not stored*), so
    upgrades to DEFAULT_INSTRUCTIONS reach every user who hasn't customised —
    an earlier build froze the default text into the file; writing "" here heals
    those files on the next save."""
    cur = load_settings()
    if "model" in patch and isinstance(patch["model"], str) and patch["model"]:
        if patch["model"] not in {m["id"] for m in MODELS}:
            raise ValueError(f"unknown model: {patch['model']}")
        cur["model"] = patch["model"]
    if "instructions" in patch:
        ins = patch["instructions"]
        if ins is None:
            cur["instructions"] = DEFAULT_INSTRUCTIONS   # explicit reset
        elif isinstance(ins, str) and ins.strip():
            cur["instructions"] = ins
    if "art_style" in patch:
        style = patch["art_style"]
        if style is None:
            cur["art_style"] = DEFAULT_ART_STYLE         # explicit reset
        elif isinstance(style, str) and style.strip():
            cur["art_style"] = style
    if "art_backend" in patch and isinstance(patch["art_backend"], str) and patch["art_backend"]:
        if patch["art_backend"] not in {b["id"] for b in ART_BACKENDS}:
            raise ValueError(f"unknown art backend: {patch['art_backend']}")
        cur["art_backend"] = patch["art_backend"]
    # ComfyUI address + workflow: a present string (even "") sets it verbatim so
    # the UI can clear either field; None clears too.
    for k in ("comfyui_url", "comfyui_workflow"):
        if k in patch:
            v = patch[k]
            cur[k] = v.strip() if isinstance(v, str) else ""
    if "api_key" in patch:
        key = patch["api_key"]
        if key is None:
            cur["api_key"] = ""            # explicit clear
        elif isinstance(key, str) and key.strip():
            cur["api_key"] = key.strip()   # replace; empty string = leave as-is
    content.LOADOUTS_DIR.mkdir(parents=True, exist_ok=True)
    on_disk = dict(cur)
    if on_disk["instructions"] == DEFAULT_INSTRUCTIONS:
        on_disk["instructions"] = ""       # "" == follow the (upgradeable) default
    if on_disk["art_style"] == DEFAULT_ART_STYLE:
        on_disk["art_style"] = ""
    SETTINGS_PATH.write_text(json.dumps(on_disk, indent=2))
    return public_settings()


# --------------------------------------------------------------------------- #
# Party scoping + prompt assembly
# --------------------------------------------------------------------------- #
def _party_summary(character_ids: List[str]) -> Dict[str, Any]:
    """Size, average level, and a per-hero line, read from the picked loadouts."""
    members: List[Dict[str, Any]] = []
    for cid in character_ids:
        lo = content.loadout_for(cid)
        if lo is None:
            raise ValueError(f"unknown character: {cid}")
        char = lo.get("character", {})
        members.append({
            "name": char.get("name", cid),
            "level": int(char.get("level", 1) or 1),
            "colors": char.get("colors", []),
        })
    if not members:
        raise ValueError("choose at least one character")
    avg = sum(m["level"] for m in members) / len(members)
    return {"size": len(members), "avg_level": avg, "members": members}


def _budget(size: int, avg_level: float, difficulty: str) -> int:
    mult = DIFFICULTY.get(difficulty, 1.0)
    return max(1, round(2 * size * avg_level * mult))


# Signature mechanics rolled per request (encounters) / per act (adventures).
# The instructions teach every one of these; sampling here — in code, not in the
# model — is what actually spreads generations across the design space: an LLM
# left to its own devices reaches for the same healer/clock/tick-channel kit
# every time. Each entry is a self-contained nudge the model can build around.
SIGNATURE_POOL: List[str] = [
    "the BODY ECONOMY — corpse-leaving husks, ONE necromancer raising them (or "
    "rises / a corpse-burst); the party must spend exile or control",
    "FORCED MOVEMENT — a Hooker dragging the backline to the front, or a "
    "Line-breaker shoving the wall back, paired with a row-scoped biter",
    "a CHARGE WINDUP — a visible gatherer with a hidden detonation, a Ward "
    "bodyguard on the fuse",
    "POISON PRESSURE — a poisoner clock, plus a medic-punisher (on_hero_healed) "
    "so curing it costs",
    "ACTION-ECONOMY CONTROL — stun and taunt pieces that attack the party's "
    "turns rather than their HP",
    "a COUNTERSPELL SENTINEL — one scarce Counter (spell filter, or an "
    "attack-parry duellist) the party must bait out",
    "EVASION — flying / hexproof skirmishers that slip the party's answers and "
    "redeploy home; reach and chip damage decide it",
    "the ANTHEM WARBAND — a channelled while_channeled pump on all fellow "
    "enemies; break the singer or fight their whole army uphill",
    "AURA OPPRESSION — a channelled party-wide wound aura, its channeler kept "
    "alive by a guard (self_channeling condition or a Ward)",
    "SWARM AND AVENGER — expendable token waves feeding an on_ally_death "
    "escalator; naive kill order loses",
    "REGEN ELITES — regen counters that only connecting hits break, plus a "
    "support healer creating kill-priority",
    "the ASSASSIN'S READ — highest_threat and channeling_player snipers that "
    "punish the party's carry and their rituals",
    "INFECT DREAD — ONE infect biter that turns every landed hit into a healer "
    "assignment",
    "DESPERATION PHASES — bloodied conditions (self_hp_pct, ally_count) that "
    "transform minions mid-fight into something worse",
    "a TIMER — a turn >= N condition unlocking a far bigger ability; turtling "
    "loses the race",
]


def _signature_rolls(k: int) -> List[str]:
    """`k` distinct signature mechanics, freshly rolled for one request."""
    return random.sample(SIGNATURE_POOL, k=min(k, len(SIGNATURE_POOL)))


def _library_lines() -> List[str]:
    """Prompt lines naming every encounter/adventure the player already owns.

    Both generators append these so the model designs AWAY from the existing
    library — without them, models converge on the same few moods and the
    player collects five variations of one idea."""
    encounters = [str(e.get("name") or "") for e in content.list_encounters()]
    adventures = [str(a.get("name") or "") for a in content.list_adventures()]
    lines: List[str] = []
    if any(encounters):
        lines.append("- The player already owns these encounters: "
                     + "; ".join(n for n in encounters if n) + ".")
    if any(adventures):
        lines.append("- The player already owns these adventures: "
                     + "; ".join(n for n in adventures if n) + ".")
    if lines:
        lines.append(
            "- They are generating because they want something NEW. Choose a "
            "theme, location, and faction clearly distinct from every title "
            "above — no sequels, no re-skins; and if several titles share a "
            "mood, steer far away from that mood entirely.")
    return lines


def _request_block(party: Dict[str, Any], difficulty: str, note: str) -> str:
    """The per-request parameters appended after the editable instructions: the
    concrete party, difficulty, and the per-party-size budgets the layouts must
    scope to (the encounter is generated once, playable by any party of 1–4)."""
    roster = "; ".join(
        f'{m["name"]} (level {m["level"]}'
        + (f', {"/".join(m["colors"])})' if m["colors"] else ")")
        for m in party["members"]
    )
    size_lines = []
    for size in range(1, 5):
        budget = _budget(size, party["avg_level"], difficulty)
        size_lines.append(
            f'  * layouts["{size}"]: at least {_min_enemies(size)} enemies (2× the '
            f"party, duplicates count), total enemy Levels about {budget} "
            "(a boss counts double).")
    lines = [
        "# THIS ENCOUNTER'S PARAMETERS",
        f'- Designing party (they picked this fight): {party["size"]} hero(es) — {roster}.',
        f'- Average party level: {party["avg_level"]:.1f}.',
        f"- Difficulty: {difficulty}.",
        "- REQUIRED: a `layouts` object with keys \"1\", \"2\", \"3\" and \"4\". The party "
        "must be outnumbered at EVERY size — per-size minimums and Level targets "
        "(sum of the layout's enemies' levels; aim close, never far under):",
        *size_lines,
        ("- This is a HARD fight: include a boss (is_boss: true, with a dramatic "
         "multi-verb Enrage component and phase-gated abilities), surrounded by real "
         "minions — and the boss appears in every layout."
         if difficulty == "hard" else
         "- No boss at this difficulty unless the player's request below asks for one."),
        ("- Include at least one CHANNELER (a channel component) somewhere in the "
         "pool." if difficulty != "easy" else
         "- Keep the designs lean at this difficulty — one decision-generator is "
         "plenty; skip counterspells."),
    ]
    rolls = _signature_rolls(2)
    lines.append(
        "- Rolled SIGNATURE MECHANICS for this generation — build the "
        "encounter's identity around at least one (adapt it to the theme; the "
        "player's note below overrides): (1) " + rolls[0] + "; (2) " + rolls[1] + ".")
    lines.extend(_library_lines())
    note = (note or "").strip()
    if note:
        lines.append(f"- Player's one-line request (honor the theme/flavor): {note}")
    lines.append("\nReturn ONLY the encounter JSON.")
    return "\n".join(lines)


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse the model's reply into a dict, tolerating code fences / surrounding prose."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Fall back to the outermost { … } span.
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("model did not return JSON")
        obj = json.loads(s[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model returned JSON that is not an object")
    return obj


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in ids the engine would otherwise default, so validation errors are about
    real design problems, not missing keys. Returns {name, enemies, tokens}."""
    enemies = raw.get("enemies")
    if not isinstance(enemies, list):
        raise ValueError("encounter is missing an 'enemies' list")
    for i, e in enumerate(enemies):
        if isinstance(e, dict):
            if not str(e.get("id", "")).strip():
                e["id"] = _slug(str(e.get("name", ""))) or f"enemy_{i + 1}"
            for c in e.get("components", []) or []:
                if isinstance(c, dict) and not str(c.get("id", "")).strip():
                    c["id"] = _slug(str(c.get("archetype", "comp"))) or f"comp_{i}"
    out = {
        "name": str(raw.get("name") or "Generated Encounter"),
        # The battle backdrop + per-enemy physical descriptions ride the encounter
        # JSON for the upcoming image-generation and narration systems.
        "scene": str(raw.get("scene") or "").strip(),
        "enemies": enemies,
        "layouts": raw.get("layouts") if isinstance(raw.get("layouts"), dict) else {},
        "tokens": raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {},
    }
    # The optional encounter objective (§D12-1) rides through to content
    # validation (adventure acts only — see the adventure prompt extension).
    if isinstance(raw.get("objective"), dict):
        out["objective"] = raw["objective"]
    return out


def _check_layouts(encounter: Dict[str, Any]) -> None:
    """Party-size scaling gate: layouts for sizes 1–4 must exist and outnumber the
    party at every size (2× — duplicates count). Id validity and boss coverage are
    checked by content.save_encounter's deeper validation; this catches the shape
    problems early with a repair-friendly message."""
    layouts = encounter.get("layouts") or {}
    missing = [str(s) for s in range(1, 5) if str(s) not in layouts]
    if missing:
        raise ValueError(
            'missing "layouts" for party size(s): ' + ", ".join(missing)
            + ' — add a top-level "layouts" object with keys "1"–"4", each a list '
            "of enemy ids from your enemies pool (repeats allowed).")
    for size in range(1, 5):
        roster = layouts.get(str(size))
        if not isinstance(roster, list):
            raise ValueError(f'layouts["{size}"] must be a list of enemy ids')
        need = _min_enemies(size)
        if len(roster) < need:
            raise ValueError(
                f'layouts["{size}"] fields only {len(roster)} enemies — a party of '
                f"{size} must be outnumbered with at least {need} (repeat ids to "
                "clone more bodies).")


# Verb kinds that only develop the acting enemy itself when aimed at "self" —
# the punching-bag test: a proactive component made solely of these, ready
# every turn, locks out the basic attack forever (engine picks the top ready
# proactive component each turn), so the enemy pumps and never acts.
_SELF_DEV_KINDS = {"counters", "pump", "regen", "heal",
                   "prevent", "protection", "amplify", "double_next"}


def _is_self_development(verb: Dict[str, Any]) -> bool:
    if str(verb.get("kind") or "") not in _SELF_DEV_KINDS:
        return False
    target = verb.get("target") if isinstance(verb.get("target"), dict) else {}
    return str(target.get("mode") or "self") == "self"


def _design_problems(encounter: Dict[str, Any]) -> List[str]:
    """The playtest-driven design gate on generated enemies (Design Update 14):
    every enemy needs at least two components, no enemy may be a 'punching bag'
    whose every turn goes into pumping itself, and a charge gather must have its
    detonation. Returns repair-friendly problem strings (empty = clean)."""
    problems: List[str] = []
    for e in encounter.get("enemies", []):
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or e.get("id") or "?")
        comps = [c for c in (e.get("components") or []) if isinstance(c, dict)]
        if len(comps) < 2:
            problems.append(
                f"{name} has {len(comps)} component(s) — every enemy needs at "
                "least 2 (ability + ability, ability + spell, or spell + spell; "
                "a reactive or once_per_encounter component is a cheap second)")
        gathers = detonates = False
        for c in comps:
            verbs = [v for v in (c.get("verbs") or []) if isinstance(v, dict)]
            kinds = {str(v.get("kind") or "") for v in verbs}
            gathers = gathers or "charge" in kinds
            detonates = detonates or str(c.get("trigger") or "") == "on_charge_full"
            # Enrage auto-fires once (the engine parses it as reactive) and a
            # verbless component (pure Evasive) only repositions — neither can
            # monopolise the enemy's turns.
            if (str(c.get("timing") or "proactive") != "proactive"
                    or str(c.get("archetype") or "").lower() == "enrage"
                    or c.get("once_per_encounter")
                    or int(c.get("cooldown") or 0) >= 2
                    or not verbs or "charge" in kinds):
                continue
            if all(_is_self_development(v) for v in verbs):
                problems.append(
                    f"{name}: component '{c.get('id') or c.get('archetype')}' only "
                    "buffs the enemy itself and can fire EVERY turn (cooldown <= 1) "
                    "— it would pump forever and never attack: a punching bag. Give "
                    "it cooldown >= 2 so the basic attack spends the counters, make "
                    "it reactive/once_per_encounter, or aim it at allies instead")
        if gathers and not detonates:
            problems.append(
                f"{name} gathers charge but has no on_charge_full detonation "
                "component — the windup needs its payoff on the same enemy")
    return problems


def _chat(api_key: str, model: str, messages: List[Dict[str, str]],
          max_tokens: Optional[int] = None,
          timeout: float = 120.0) -> str:
    """One OpenRouter chat completion; returns the assistant message text.

    ``max_tokens`` is set explicitly for adventure generation (T-63): three full
    encounters plus prose overflow many models' default completion budget, and a
    truncated JSON reply would otherwise burn a repair attempt."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ltg.local",
                "X-Title": "LTG Encounter Generator",
            },
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ValueError(f"could not reach OpenRouter: {exc}") from exc
    if resp.status_code == 401:
        raise ValueError("OpenRouter rejected the API key (401). Check Options → LLM.")
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise ValueError(f"OpenRouter error {resp.status_code}: {detail}")
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"unexpected OpenRouter response: {exc}") from exc


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate_encounter(character_ids: List[str], difficulty: str = "standard",
                       note: str = "", attempts: int = 2,
                       persist: bool = True) -> Dict[str, Any]:
    """Generate, validate, persist an encounter and return its meta (id + name …).

    Scopes to the picked party + difficulty, calls the configured model, then feeds
    the result through ``content.save_encounter`` (the same gate an authored encounter
    passes). On a validation failure it re-prompts with the engine's error, up to
    ``attempts`` total. Raises ValueError with a human message on any hard failure.

    ``persist=False`` (the Autoplay Tester's quarantine path, §D13-2.3) runs the
    exact same validation gate but returns the CLEANED ENCOUNTER DICT instead of
    saving — nothing enters the game's picker.
    """
    settings = load_settings()
    if not settings["api_key"]:
        raise ValueError("No OpenRouter API key set. Add one in Options → LLM.")
    if difficulty not in DIFFICULTY:
        difficulty = "standard"

    party = _party_summary(character_ids)
    system = settings["instructions"]
    user = _request_block(party, difficulty, note)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_err = ""
    for attempt in range(max(1, attempts)):
        reply = _chat(settings["api_key"], settings["model"], messages)
        try:
            encounter = _normalize(_extract_json(reply))
            _scale_hp(encounter, difficulty)  # floor enemy HP so they aren't one-shot
            _check_layouts(encounter)         # scaling layouts for parties of 1–4
            # Art/narration data is required: the scene and every enemy's look.
            problems = []
            if not encounter["scene"]:
                problems.append('missing the top-level "scene" (2–3 sentence setting)')
            undescribed = [str(e.get("name", "?")) for e in encounter["enemies"]
                           if isinstance(e, dict)
                           and not str(e.get("description") or "").strip()]
            if undescribed:
                problems.append('enemies missing a "description" (physical '
                                'appearance): ' + ", ".join(undescribed))
            problems.extend(_design_problems(encounter))  # §D14: kit floor
            if problems:
                raise ValueError("; ".join(problems))
            if not persist:
                # The full authored-content gate, without the save.
                return content._validate_encounter(encounter)
            return content.save_encounter(encounter)  # validates + persists
        except ValueError as exc:
            last_err = str(exc)
            # Feed the failure back so the model can repair its own output.
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": (
                f"That output was rejected: {last_err}\n"
                "Fix it and return ONLY the corrected encounter JSON.")})
    raise ValueError(f"generation failed after {attempts} attempts: {last_err}")


# --------------------------------------------------------------------------- #
# Adventure generation — one call, one arc (Design Update 10 §D10-5)
# --------------------------------------------------------------------------- #
# T-63: an explicit, very high completion budget — three full encounters plus
# narration overflow the default `max_tokens` most models assume, and truncated
# JSON would otherwise waste repair attempts. Kept below common per-model output
# ceilings so the request never 400s.
ADVENTURE_MAX_TOKENS = 32000
ADVENTURE_TIMEOUT = 600.0  # one reply carries three encounters; allow the time

# Appended to the (editable) encounter instructions for an adventure request:
# everything the model already knows about designing ONE encounter holds per
# act; this block adds the arc, the boss ladder, and the output wrapper.
ADVENTURE_EXTENSION = r"""
# ADVENTURE MODE — three acts, one arc (this request generates a whole adventure)

You are designing an ADVENTURE: three thematically linked encounters (the ACTS)
fought in sequence by one party — progress through a single place. Guards at the
gate, knights in the courtyard, the tyrant in his throne room: one faction, one
location traversed, escalating stakes. Everything in the instructions above
applies to EACH act individually (chassis, components, budgets, layouts, scenes,
descriptions). This block adds the arc-level rules:

- SCENES PROGRESS: the three acts' `scene` texts must read as three stations of
  ONE location — outside it, inside it, at its heart — not three unrelated
  arenas. Same palette, same weather-world, deepening dread.
- DIFFICULTY ESCALATES BY DESIGN: each act's Level budgets are given below,
  computed for a party one level stronger per act. Respect each act's own
  per-party-size layout minimums and targets.
- ACTS DIFFER MECHANICALLY: each act leans on a DIFFERENT signature mechanic
  (the parameters roll one per act) so the run escalates in KIND, not just in
  numbers — e.g. a skirmish of evasive raiders, then the ritual they were
  screening, then the boss spending the corpses both fights left behind.
- ACT III ENDS IN THE BOSS: exactly one enemy with `is_boss: true` in Act III —
  the adventure's HIGHEST-LEVEL enemy, with the full boss kit (multi-verb
  Enrage, phase gates, real HP). No enemy anywhere may exceed its level.
- ACTS I AND II MAY each field ONE MINI-BOSS — never an obligation, use it for
  variety. A mini-boss is mechanically a full boss (`is_boss: true`, Enrage,
  2.5× budget, counts double), thematically distinct (the gate-captain, not the
  king), and STRICTLY lower level than Act III's boss.
- NARRATION: each act carries a `narration` — one short paragraph, SECOND
  PERSON, PRESENT TENSE, describing the party arriving into that act's scene
  ("You push through the splintered gate. Beyond, the courtyard…"). Act I's
  narration is the adventure's opening. No mechanics, no numbers — atmosphere
  and forward motion.
- `flavor` is the adventure's one-line pitch, shown in the New Game list.

# Encounter OBJECTIVES (Design Update 12 §D12-1 — adventure flavour)

One act MAY carry an optional `"objective"` — an alternate win condition that
turns the act into a set piece. The standing rules are HARD validation:
- AT MOST ONE objective in the whole adventure, and only on Act I or Act II.
  Act III is ALWAYS the standard boss kill — the climax stays a fight.
- Objectives are fully public (the party sees the goal and its countdown from
  turn 1). Defeat by party wipe is unchanged.
Use one in roughly two adventures out of three, when the fiction asks for it;
let the act's `narration` reference the objective. The three kinds:

1. SURVIVE — hold out N rounds; the party wins the act when round N's End Step
   completes (survivors withdraw). Timer 4–6 rounds. Survival must not be
   passive: schedule reinforcements and pick a defensible theme (a gate, a
   bridge, a shrinking camp).
   {"kind": "survive", "turns": 5, "reinforcements": [
     {"turn": 3, "layouts": {"1": ["raider"], "2": ["raider","raider"],
                             "3": ["raider","raider","howler"],
                             "4": ["raider","raider","howler","howler"]}}]}
   Reinforcement ids reference the act's enemy pool; repeats clone. Each entry
   deploys at the start of round `turn`'s Enemy Intents step.

2. WAVES — clear successive waves; the act's top-level `layouts` ARE wave 1,
   and `"waves"` lists the later waves (same per-size map shape). Later waves
   wait off-board and deploy when the current wave falls. A war-band theme with
   DISTINCT wave compositions — vary rows and roles, don't clone one statline
   thrice. Every wave fields at least 1× the party size (per size), at least 2×
   in total, and the summed Level budget across waves may run to 1.5× the act's
   standard budget (staggered arrival pays for the excess). A mini-boss, if the
   act has one, appears in the FINAL wave only (never in `layouts`).
   {"kind": "waves", "waves": [
     {"1": ["cutthroat"], "2": ["cutthroat","cutthroat"],
      "3": ["cutthroat","cutthroat","archer"],
      "4": ["cutthroat","cutthroat","archer","archer"]},
     {"1": ["pit_captain"], "2": ["pit_captain","cutthroat"],
      "3": ["pit_captain","cutthroat","archer"],
      "4": ["pit_captain","cutthroat","cutthroat","archer"]}]}

3. RACE — the doom clock: one marked enemy (the ritualist, the summoner) must
   be DEFEATED within N rounds (3–5), or the failure fires. Give the marked
   target real HP, a Ward bodyguard, and field it in EVERY layout. Prefer
   `"fail": "escalate"` — the escalation is an enrage-shaped, budget-free
   eruption of 2–3 verbs (permanent counters on the enemy side, an AoE, a token
   wave, a granted keyword) that transforms the fight but leaves it winnable;
   `"fail": "defeat"` ends the run on the spot and is for hand-authored set
   pieces only.
   {"kind": "race", "target": "bonechanter", "turns": 4, "fail": "escalate",
    "escalation": {"telegraph": "The Rite Completes",
      "verbs": [{"kind": "counters", "power": 2, "toughness": 2,
                 "target": {"mode": "all", "side": "enemy"}},
                {"kind": "deal_damage", "amount": 3,
                 "target": {"mode": "all", "side": "ally"}}]}}

# Adventure output contract (return EXACTLY this shape, nothing else)
{
  "name": "Adventure name",
  "flavor": "one-line pitch",
  "acts": [
    { "narration": "…", <a complete encounter object: name, scene, enemies, layouts, tokens> },
    { "narration": "…", <act II encounter> },
    { "narration": "…", <act III encounter — contains the one boss> }
  ]
}
Each act is a COMPLETE encounter exactly per the contract above (name, scene,
enemies with descriptions, layouts for party sizes 1–4, tokens if needed)."""


def _adventure_request_block(party: Dict[str, Any], difficulty: str,
                             note: str) -> str:
    """Per-request parameters: the party, the single difficulty, and each act's
    per-party-size budget lines computed at party level 1 / 2 / 3 (T-62)."""
    roster = "; ".join(
        f'{m["name"]} (level {m["level"]}'
        + (f', {"/".join(m["colors"])})' if m["colors"] else ")")
        for m in party["members"]
    )
    lines = [
        "# THIS ADVENTURE'S PARAMETERS",
        f'- Designing party (they picked this run): {party["size"]} hero(es) — {roster}.',
        f"- Difficulty: {difficulty} (applies to all three acts).",
        "- Between acts every character levels up, so act N is budgeted for a "
        "party of level N:",
    ]
    for act in range(1, content.ACT_COUNT + 1):
        lines.append(f'- ACT {act} (party level {act}) — required layouts "1"–"4":')
        for size in range(1, 5):
            budget = _budget(size, float(act), difficulty)
            lines.append(
                f'  * layouts["{size}"]: at least {_min_enemies(size)} enemies '
                f"(2× the party, duplicates count), total enemy Levels about "
                f"{budget} (a boss counts double).")
    lines.append(
        "- Act III must contain exactly ONE boss (is_boss: true) — the "
        "adventure's highest-level enemy. Acts I and II may each field at most "
        "one mini-boss, strictly lower level than Act III's boss.")
    if difficulty != "easy":
        lines.append("- Include at least one CHANNELER (a channel component) "
                     "somewhere in each act's pool.")
    rolls = _signature_rolls(content.ACT_COUNT)
    lines.append(
        "- Rolled SIGNATURE MECHANICS, one per act — build each act's identity "
        "around its roll (adapt to the theme; the player's note overrides), so "
        "the threats escalate in KIND across the run, not just in budget: "
        + " ".join(f"Act {i}: {r}." for i, r in enumerate(rolls, start=1)))
    lines.extend(_library_lines())
    note = (note or "").strip()
    if note:
        lines.append(f"- Player's one-line request (honor the theme/flavor): {note}")
    lines.append("\nReturn ONLY the adventure JSON.")
    return "\n".join(lines)


def generate_adventure(character_ids: List[str], difficulty: str = "standard",
                       note: str = "", attempts: int = 3) -> Dict[str, Any]:
    """Generate, validate, persist an adventure and return its meta.

    One request generates the whole arc (coherence by construction); the reply
    then runs the same repair loop an encounter takes — per-act HP scaling,
    per-act layout checks, then ``content.save_adventure`` (per-act engine gate
    + the §D10-4.1 adventure checks). Any failure re-prompts the model with the
    engine's own error, up to ``attempts`` total."""
    settings = load_settings()
    if not settings["api_key"]:
        raise ValueError("No OpenRouter API key set. Add one in Options → LLM.")
    if difficulty not in DIFFICULTY:
        difficulty = "standard"

    party = _party_summary(character_ids)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": settings["instructions"] + ADVENTURE_EXTENSION},
        {"role": "user", "content": _adventure_request_block(party, difficulty, note)},
    ]

    last_err = ""
    for _attempt in range(max(1, attempts)):
        reply = _chat(settings["api_key"], settings["model"], messages,
                      max_tokens=ADVENTURE_MAX_TOKENS, timeout=ADVENTURE_TIMEOUT)
        try:
            raw = _extract_json(reply)
            acts = raw.get("acts")
            if not isinstance(acts, list) or len(acts) != content.ACT_COUNT:
                raise ValueError(
                    f'the adventure needs an "acts" list of exactly '
                    f"{content.ACT_COUNT} acts")
            cleaned_acts = []
            for i, act in enumerate(acts, start=1):
                if not isinstance(act, dict):
                    raise ValueError(f"act {i} must be an object")
                try:
                    enc = _normalize(act)
                    _scale_hp(enc, difficulty)
                    _check_layouts(enc)
                    problems = []
                    if not enc["scene"]:
                        problems.append('missing the top-level "scene"')
                    undescribed = [str(e.get("name", "?")) for e in enc["enemies"]
                                   if isinstance(e, dict)
                                   and not str(e.get("description") or "").strip()]
                    if undescribed:
                        problems.append('enemies missing a "description": '
                                        + ", ".join(undescribed))
                    problems.extend(_design_problems(enc))  # §D14: kit floor
                    if not str(act.get("narration") or "").strip():
                        problems.append('missing its "narration" (one short '
                                        "second-person paragraph)")
                    if problems:
                        raise ValueError("; ".join(problems))
                except ValueError as exc:
                    raise ValueError(f"act {i}: {exc}") from exc
                enc["narration"] = str(act.get("narration") or "").strip()
                cleaned_acts.append(enc)
            adventure = {
                "name": str(raw.get("name") or "Generated Adventure"),
                "flavor": str(raw.get("flavor") or "").strip(),
                "acts": cleaned_acts,
            }
            # Same gate authored content takes: per-act engine validation plus
            # the adventure-level checks, then persist (wrapper + act files).
            return content.save_adventure(adventure)
        except ValueError as exc:
            last_err = str(exc)
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": (
                f"That output was rejected: {last_err}\n"
                "Fix it and return ONLY the corrected adventure JSON.")})
    raise ValueError(f"adventure generation failed after {attempts} attempts: "
                     f"{last_err}")
