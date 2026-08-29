"""Dialogue — authored at generation, walked at runtime (Design Update 17 §D17-5.4).

A dialogue tree::

    {"root": id, "nodes": {id: {"speaker": "npc" | "party" | "narration", "text": str,
                                "choices": [{"label", "next"?, "requires"?: [flag…],
                                             "effects"?: [hook…]}]}}}

2–4 nodes deep on the main line (a hard cap of MAX_DEPTH — generous, since a
defeated_once branch stacks on top), 2–3 choices per node; a choice without
``next`` ends the conversation. **Hooks are a closed vocabulary** (like effect verbs):
``set_flag``, ``grant_quest`` (which quest option the party took), ``defer_quest``
(they will think it over — the NPC asks again next time), ``advance_quest``,
``unlock_adventure`` (write-once per act), ``give_gold``, ``give_item``,
``rest``, ``open_shop``, ``direct_to``. Nothing else validates; the prompt is
told so.

``requires`` reads flags the hooks set. Flags live in the run state and persist
across acts and scenarios; standing flags the runtime sets itself:
``defeated_once``, ``act_<n>_complete``, ``quest_accepted``.

Live LLM dialogue is not in v1: ``freeform: true`` is reserved and rejected.

Two halves here: `validate_dialogue` (the authored-content gate the act
materialization passes) and `Conversation` (the runtime walker: current node,
visible choices under the party's flags, and choose → hooks fired by the
caller — the ScenarioRun owns the run state the hooks mutate).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set

HOOKS = ("set_flag", "grant_quest", "defer_quest", "advance_quest",
         "unlock_adventure", "give_gold", "give_item", "rest", "open_shop",
         "direct_to")
# Flags the RUNTIME sets on its own — legal in `requires` without any set_flag
# hook establishing them (§D20-1). Everything else gating a choice must be
# reachable: some hook in the act (or an earlier act — the caller passes what is
# already true) has to be able to set it, or the choice is a door with no key.
STANDING_FLAGS = frozenset({"defeated_once", "quest_accepted",
                            "act_1_complete", "act_2_complete", "act_3_complete"})
STANDING_PREFIXES = ("item_",)   # give_item writes item_<id>
# Hooks whose choice is party-wide: they open the all-players confirmation
# (§D17-5.4). Flavour choices don't.
PARTY_WIDE_HOOKS = frozenset({"grant_quest", "unlock_adventure", "rest"})
MAX_DEPTH = 10
MIN_CHOICES = 1     # a leaf may carry one "Farewell"; the prompt asks 2–3
# An offer node carries every quest option the NPC has plus the "let us think
# on it" out, so the ceiling is a little above the 2–3 the prompt asks for.
MAX_CHOICES = 5


def _clean_hook(h: Any, where: str) -> Dict[str, Any]:
    if not isinstance(h, dict):
        raise ValueError(f"{where}: hook must be an object")
    kind = str(h.get("kind") or h.get("hook") or "").strip()
    if kind not in HOOKS:
        raise ValueError(f"{where}: unknown hook '{kind}' — allowed: {', '.join(HOOKS)}")
    out: Dict[str, Any] = {"kind": kind}
    if kind in ("grant_quest", "defer_quest"):
        # Which of the act's quest options this choice takes / puts off. Bare
        # (no id) is legal and means "the act's only quest".
        quest = str(h.get("quest") or h.get("quest_id") or "").strip()
        if quest:
            out["quest"] = quest
    elif kind == "set_flag":
        flag = str(h.get("flag") or "").strip()
        if not flag:
            raise ValueError(f"{where}: set_flag needs a flag name")
        out["flag"] = flag
        out["value"] = bool(h.get("value", True))
    elif kind == "give_gold":
        try:
            out["amount"] = int(h.get("amount", 0))
        except (TypeError, ValueError):
            raise ValueError(f"{where}: give_gold amount must be a number")
        if out["amount"] <= 0:
            raise ValueError(f"{where}: give_gold amount must be positive")
    elif kind == "give_item":
        item = str(h.get("item") or h.get("item_id") or "").strip()
        if not item:
            raise ValueError(f"{where}: give_item needs an item id")
        out["item"] = item
    elif kind == "direct_to":
        out["npc"] = str(h.get("npc") or "").strip() or None
        out["location"] = str(h.get("location") or "").strip() or None
        if not out["npc"] and not out["location"]:
            raise ValueError(f"{where}: direct_to needs an npc or a location")
    elif kind == "open_shop":
        out["location"] = str(h.get("location") or "").strip() or None
    return out


def validate_dialogue(raw: Dict[str, Any], flags_known: Optional[Set[str]] = None
                      ) -> Dict[str, Any]:
    """The authored-dialogue gate: shape, closed hooks, every ``next`` resolves,
    depth ≤ MAX_DEPTH, no `freeform`. Returns the cleaned tree."""
    if not isinstance(raw, dict):
        raise ValueError("dialogue must be an object")
    if raw.get("freeform"):
        raise ValueError("freeform dialogue is reserved (not implemented in v1)")
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, dict) or not nodes_raw:
        raise ValueError("dialogue needs a nodes map")
    root = str(raw.get("root") or "").strip()
    if root not in nodes_raw:
        raise ValueError(f"dialogue root '{root}' is not a node")
    nodes: Dict[str, Dict[str, Any]] = {}
    for nid, node in nodes_raw.items():
        nid = str(nid)
        if not isinstance(node, dict):
            raise ValueError(f"node '{nid}' must be an object")
        speaker = str(node.get("speaker") or "npc").strip()
        # "narration": an unvoiced beat between lines — what the NPC does, what
        # the party notices, what a name or a rumour actually MEANS. Playtest:
        # dialogue that only ever speaks is hard to follow, because everything
        # the characters already know goes unsaid. Rendered without a nameplate.
        if speaker not in ("npc", "party", "narration"):
            raise ValueError(f"node '{nid}': speaker must be npc, party, or narration")
        text = str(node.get("text") or "").strip()
        if not text:
            raise ValueError(f"node '{nid}' has no text")
        choices_raw = node.get("choices")
        if choices_raw is None:
            choices_raw = []
        if not isinstance(choices_raw, list):
            raise ValueError(f"node '{nid}': choices must be a list")
        if len(choices_raw) > MAX_CHOICES:
            raise ValueError(f"node '{nid}' has {len(choices_raw)} choices (max {MAX_CHOICES})")
        choices: List[Dict[str, Any]] = []
        for k, ch in enumerate(choices_raw, start=1):
            if not isinstance(ch, dict):
                raise ValueError(f"node '{nid}' choice {k} must be an object")
            label = str(ch.get("label") or "").strip()
            if not label:
                raise ValueError(f"node '{nid}' choice {k} needs a label")
            nxt = ch.get("next")
            nxt = str(nxt).strip() if nxt not in (None, "") else None
            if nxt is not None and nxt not in nodes_raw:
                raise ValueError(f"node '{nid}' choice '{label}' points at missing node '{nxt}'")
            req = ch.get("requires") or []
            if not isinstance(req, list):
                raise ValueError(f"node '{nid}' choice '{label}': requires must be a list of flags")
            req = [str(f).strip() for f in req if str(f).strip()]
            effects = [_clean_hook(h, f"node '{nid}' choice '{label}'")
                       for h in (ch.get("effects") or [])]
            choices.append({"label": label, "next": nxt, "requires": req,
                            "effects": effects})
        nodes[nid] = {"speaker": speaker, "text": text, "choices": choices}
    # Depth: the longest root → leaf walk (cycles are an error).
    def depth(nid: str, seen: "tuple") -> int:
        if nid in seen:
            raise ValueError(f"dialogue loops through node '{nid}'")
        best = 1
        for ch in nodes[nid]["choices"]:
            if ch["next"]:
                best = max(best, 1 + depth(ch["next"], seen + (nid,)))
        return best
    if depth(root, ()) > MAX_DEPTH:
        raise ValueError(f"dialogue runs deeper than {MAX_DEPTH} nodes — trim the longest chain")
    return {"root": root, "nodes": nodes}


def hooks_of(choice: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(choice.get("effects") or [])


def is_party_wide(choice: Dict[str, Any]) -> bool:
    return any(h.get("kind") in PARTY_WIDE_HOOKS for h in hooks_of(choice))


class Conversation:
    """The runtime walker over one validated tree. Holds the current node and
    the attributed party speaker; `visible_choices` filters on flags; `choose`
    advances and returns the hooks the caller must fire (in order). The walker
    itself never mutates run state."""

    def __init__(self, npc_id: str, tree: Dict[str, Any]) -> None:
        self.npc_id = npc_id
        self.tree = tree
        self.node_id: Optional[str] = tree["root"]
        self.attributed: Optional[str] = None   # live character id for "party" lines
        self.history: List[str] = []            # node ids walked
        # The full transcript, chat-style, for the snapshot: every node shown
        # plus each choice the party took (speaker "choice") — so every client
        # in a multiplayer town sees the whole exchange, not just the reply.
        self.lines: List[Dict[str, Any]] = []
        self._record_node()

    def _record_node(self) -> None:
        node = self.node
        if node is not None:
            self.lines.append({"speaker": node["speaker"], "text": node["text"],
                               "attributed": self.attributed
                               if node["speaker"] == "party" else None})

    @property
    def node(self) -> Optional[Dict[str, Any]]:
        if self.node_id is None:
            return None
        return self.tree["nodes"].get(self.node_id)

    def visible_choices(self, flags: Dict[str, bool]) -> List[Dict[str, Any]]:
        node = self.node
        if node is None:
            return []
        out = []
        for i, ch in enumerate(node["choices"]):
            if all(flags.get(f) for f in ch.get("requires", [])):
                out.append({"index": i, "label": ch["label"],
                            "party_wide": is_party_wide(ch),
                            "ends": ch["next"] is None})
        return out

    def choose(self, index: int, flags: Dict[str, bool]) -> List[Dict[str, Any]]:
        """Take choice ``index`` of the current node (must be visible under
        ``flags``); advance (or end); return its hooks."""
        node = self.node
        if node is None:
            raise ValueError("the conversation is over")
        if not 0 <= index < len(node["choices"]):
            raise ValueError("no such choice")
        ch = node["choices"][index]
        if not all(flags.get(f) for f in ch.get("requires", [])):
            raise ValueError("that choice is not available")
        self.history.append(str(self.node_id))
        self.lines.append({"speaker": "choice", "text": ch["label"],
                           "attributed": self.attributed})
        self.node_id = ch["next"]
        self._record_node()
        return copy.deepcopy(hooks_of(ch))

    def interject(self, text: str, farewell: str = "Farewell.") -> None:
        """Hand the NPC one more line after the tree has ended — the closing
        reply to an accept or a defer. A synthetic leaf is added to THIS
        walker's tree (ids never collide with authored nodes) and becomes the
        current node, so the conversation shows it and then ends on the
        farewell. Hook-free by construction: nothing fires twice."""
        nid = "reply"
        while nid in self.tree["nodes"]:
            nid = "_" + nid
        # The walker may be holding the act's own tree object — never write
        # into that; the leaf lives on this conversation's copy only.
        self.tree = {"root": self.tree["root"], "nodes": dict(self.tree["nodes"])}
        self.tree["nodes"][nid] = {
            "speaker": "npc", "text": str(text).strip(),
            "choices": [{"label": farewell, "next": None, "requires": [], "effects": []}],
        }
        self.node_id = nid
        self._record_node()

    @property
    def over(self) -> bool:
        return self.node_id is None

    def snapshot(self, flags: Dict[str, bool]) -> Dict[str, Any]:
        node = self.node
        return {
            "npc_id": self.npc_id,
            "node_id": self.node_id,
            "speaker": node["speaker"] if node else None,
            "text": node["text"] if node else "",
            "attributed": self.attributed,
            "choices": self.visible_choices(flags),
            "over": self.over,
            "lines": [dict(l) for l in self.lines],
        }


def flags_set_in(tree: Dict[str, Any]) -> Set[str]:
    """Every flag a set_flag hook in this tree can establish."""
    out: Set[str] = set()
    for node in tree.get("nodes", {}).values():
        for ch in node.get("choices", []):
            for h in ch.get("effects", []):
                if h.get("kind") == "set_flag" and h.get("value", True):
                    out.add(h["flag"])
    return out


def flags_required_in(tree: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for node in tree.get("nodes", {}).values():
        for ch in node.get("choices", []):
            out.update(ch.get("requires", []))
    return out


def check_flag_consistency(dialogues: Dict[str, Dict[str, Any]],
                           extra_required: Set[str] = frozenset(),
                           flags_known: Set[str] = frozenset()) -> List[str]:
    """§D20-1: every flag gating a choice (or a gated topic —
    ``extra_required``) must be REACHABLE — a standing runtime flag, already
    true in the run, or settable by some set_flag hook in this act's trees.
    A gate nothing can open is a dead choice the player never sees; when the
    unreachable flag is the ONLY way to a quest accept, it is a broken act.
    Returns repair-friendly problem strings (empty = clean)."""
    settable: Set[str] = set()
    for tree in dialogues.values():
        settable |= flags_set_in(tree)
    required: Set[str] = set(extra_required)
    for tree in dialogues.values():
        required |= flags_required_in(tree)
    problems: List[str] = []
    for flag in sorted(required):
        if flag in STANDING_FLAGS or flag in settable or flag in flags_known:
            continue
        if any(flag.startswith(pfx) for pfx in STANDING_PREFIXES):
            continue
        problems.append(
            f"the flag '{flag}' gates a choice but nothing can set it — add a "
            f'{{"kind": "set_flag", "flag": "{flag}"}} hook on the choice where '
            "the party LEARNS this (the NPC who explains it), or drop the gate")
    return problems
