"""AI art generation — OpenRouter image model, prompted from the encounter JSON.

Like ``llm.py`` (encounter text) this is pure content sourcing: it turns the
encounter's ``scene`` / per-enemy ``description`` prose into images and hands the
updated encounter back through ``content.save_encounter`` — the same validate +
persist path every edit takes. It computes no rules.

Images are PNG/JPEG files under ``loadouts/art/<encounter_id>/`` (gitignored with
the rest of ``loadouts/``), referenced from the encounter JSON by server-relative
URL (``/art/<encounter_id>/<file>``) — so a saved encounter replays with its art
and the JSON stays small. Enemy art is keyed by the POOL enemy id; layout clones
("wolf", "wolf_2") share the base design's image.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from . import content, llm
from ltg_combat.scenario import _slug

# The OpenRouter image model lives with the settings machinery (llm.ART_MODEL);
# this alias keeps art-side callers/tests reading naturally.
ART_MODEL = llm.ART_MODEL

# ComfyUI backend: how long one image may take (a local workstation can be slow
# on first load — model weights stream from disk), and how often we poll.
COMFY_TIMEOUT = 300.0
COMFY_POLL_INTERVAL = 1.0
# Pixel sizes injected for the %width%/%height% placeholders, per aspect.
COMFY_SIZES = {"16:9": (1792, 1024), "1:1": (1024, 1024), "3:4": (896, 1152),
               "3:2": (1216, 832)}

# Generated images write into the tracked content dir, beside the encounter /
# adventure JSON they belong to, so a commit ships the art to every install.
ART_DIR = content.CONTENT_DIR / "art"
# Pre-split installs kept art in the gitignored loadouts dir; served as a
# read-only fallback under the same /art URLs (see app.py) so legacy image
# references keep resolving until the piece is regenerated.
LEGACY_ART_DIR = content.LOADOUTS_DIR / "art"
ART_URL_PREFIX = "/art"

_DATA_URL_RE = re.compile(r"^data:image/(\w+);base64,(.+)$", re.DOTALL)
_EXT = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp"}

# The editable aesthetic wrapper lives in llm.py with the rest of the settings
# machinery (llm.DEFAULT_ART_STYLE). Every image prompt is style + task framing
# + the encounter's own prose.
_SCENE_TASK = (
    "Paint a battlefield BACKDROP for a tactical fantasy combat encounter. "
    "Create ONLY the ENVIRONMENT.  That means NO creatures, NO people, NO "
    "monsters, NO characters, NO subjects. Wide landscape composition, painted "
    "edge to edge, with an uncluttered middle ground. Use scale, lighting, and "
    "atmospheric details to create a sense of place.\n\nThe setting:\n"
)

_ENEMY_TASK = (
    "Paint a single portrait for an enemy card in a tactical card-combat game. "
    "ONE subject only, full body or three-quarter view, centred, facing centre or "
    "left in an action pose, taking up the full frame.  Background is atmospheric "
    "falling off into a dark vignette to emphasize the subject.\n\n"
    "Your subject is captured at an instant of intensity - from pose, expression, "
    "movement or stillness - the frame is caught at the peak of its energy. "
    "Aggressive foreshortening, low sweeping camera angle, bold diagonals, powerful "
    "posing.\n\n"
)


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #
def _style() -> str:
    return (llm.load_settings().get("art_style") or llm.DEFAULT_ART_STYLE).strip()


def _enemy_pool_id(enemy: Dict[str, Any]) -> str:
    return str(enemy.get("id") or _slug(str(enemy.get("name", ""))))


def _find_enemy(enc: Dict[str, Any], enemy_id: Optional[str]) -> Dict[str, Any]:
    """The pool enemy — or token definition — behind an art slot id. Spawned
    tokens (a Swarm's Husklings) are creatures too; their defs live in the
    encounter's ``tokens`` dict and carry art exactly like a pool enemy."""
    if not enemy_id:
        raise ValueError("enemy_id is required for enemy art")
    for e in enc.get("enemies", []):
        if isinstance(e, dict) and _enemy_pool_id(e) == enemy_id:
            return e
    tok = (enc.get("tokens") or {}).get(enemy_id)
    if isinstance(tok, dict):
        return tok
    raise ValueError(f"unknown enemy: {enemy_id}")


def scene_prompt(enc: Dict[str, Any], override_text: str = "") -> str:
    """The full image prompt for the encounter's battle backdrop."""
    desc = (override_text or enc.get("scene") or "").strip()
    if not desc:
        raise ValueError(
            "this encounter has no scene description — add one in the editor first")
    return f"{_style()}\n\n{_SCENE_TASK}{desc}"


def enemy_prompt(enc: Dict[str, Any], enemy: Dict[str, Any],
                 override_text: str = "") -> str:
    """The full image prompt for one enemy's portrait. Falls back to the name when
    no physical description exists, and hints the scene for palette coherence."""
    name = str(enemy.get("name", "enemy"))
    desc = (override_text or enemy.get("description") or "").strip()
    if not desc:
        desc = f'A dark fantasy creature called "{name}".'
    # §D21: the type line anchors the concept — the painter is told what the
    # creature IS and what it DOES, so a "necromancer" never drifts into a
    # generic monster and an "undead archer" keeps its bow.
    tags = [str(t) for t in (enemy.get("types") or [])] \
        + [str(t) for t in (enemy.get("classes") or enemy.get("supertypes") or [])]
    tag_line = f" It is: {', '.join(tags)}." if tags else ""
    parts = [f"{_style()}\n\n{_ENEMY_TASK}The subject — {name}:\n{desc}{tag_line}"]
    scene = str(enc.get("scene") or "").strip()
    if scene:
        parts.append(f"\n\nIt is encountered here (match the mood and palette; "
                     f"do NOT paint this setting in detail): {scene}")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# OpenRouter image call
# --------------------------------------------------------------------------- #
def _request_image(api_key: str, prompt: str, aspect: str) -> Tuple[bytes, str]:
    """One image generation; returns (raw bytes, file extension).

    ``image_config.aspect_ratio`` steers Gemini image models on OpenRouter; some
    providers reject the parameter, so a 400 retries once without it (the task
    framing in the prompt still asks for the right orientation)."""
    payload: Dict[str, Any] = {
        "model": ART_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ltg.local",
        "X-Title": "LTG Art Generator",
    }
    for attempt in (0, 1):
        try:
            resp = httpx.post(llm.OPENROUTER_URL, headers=headers, json=payload,
                              timeout=180.0)
        except httpx.HTTPError as exc:
            raise ValueError(f"could not reach OpenRouter: {exc}") from exc
        if resp.status_code == 400 and attempt == 0 and "image_config" in payload:
            payload.pop("image_config")
            continue
        break
    if resp.status_code == 401:
        raise ValueError("OpenRouter rejected the API key (401). Check Options → LLM.")
    if resp.status_code >= 400:
        raise ValueError(f"OpenRouter error {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"unexpected OpenRouter response: {exc}") from exc
    images = message.get("images") or []
    if not images:
        text = str(message.get("content") or "")[:200]
        raise ValueError("the model returned no image"
                         + (f" (it said: {text})" if text.strip() else ""))
    url = str(images[0].get("image_url", {}).get("url", ""))
    m = _DATA_URL_RE.match(url)
    if not m:
        raise ValueError("the model returned an image in an unexpected format")
    ext = _EXT.get(m.group(1).lower(), "png")
    try:
        return base64.b64decode(m.group(2)), ext
    except Exception as exc:
        raise ValueError(f"could not decode the returned image: {exc}") from exc


# --------------------------------------------------------------------------- #
# ComfyUI call (a user-supplied API-format workflow on a local server)
# --------------------------------------------------------------------------- #
def _inject_workflow(workflow_text: str, prompt: str, aspect: str) -> Dict[str, Any]:
    """Fill the user's workflow with this image's prompt, size, and seed.

    The contract (documented in Options → LLM): the workflow is ComfyUI's
    API-format export, with ``%prompt%`` somewhere in a text input (substring —
    surrounding quality tags survive), and optionally the literal strings
    ``"%width%"`` / ``"%height%"`` in size inputs (replaced with integers per
    the image's aspect) and ``"%seed%"`` in a seed input (a fresh random
    integer per generation, so Repaint actually varies — a browserless API
    queue never randomizes seeds for you). Raises ValueError with a
    setup-guiding message."""
    try:
        wf = json.loads(workflow_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "the ComfyUI workflow is not valid JSON — paste the API-format "
            f"export (Workflow → Export (API)): {exc}") from exc
    if not isinstance(wf, dict):
        raise ValueError("the ComfyUI workflow must be a JSON object of nodes")
    w, h = COMFY_SIZES.get(aspect, COMFY_SIZES["1:1"])
    seed = secrets.randbelow(2**31)
    found = {"prompt": False}

    def fill(value: Any) -> Any:
        if isinstance(value, str):
            if value == "%width%":
                return w
            if value == "%height%":
                return h
            if value == "%seed%":
                return seed
            if "%prompt%" in value:
                found["prompt"] = True
                return value.replace("%prompt%", prompt)
            return value
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    wf = fill(wf)
    if not found["prompt"]:
        raise ValueError(
            'the ComfyUI workflow has no "%prompt%" placeholder — put %prompt% '
            "inside your positive-prompt text field so the generated description "
            "reaches the model")
    return wf


def _request_comfyui(base_url: str, workflow_text: str, prompt: str,
                     aspect: str) -> Tuple[bytes, str]:
    """Queue the workflow on ComfyUI and fetch the first output image.

    Protocol: POST /prompt (returns a prompt_id) → poll GET /history/<id> until
    the entry appears (execution finished or failed) → GET /view for the bytes.
    """
    base = base_url.rstrip("/")
    wf = _inject_workflow(workflow_text, prompt, aspect)
    try:
        resp = httpx.post(f"{base}/prompt", json={"prompt": wf}, timeout=30.0)
    except httpx.HTTPError as exc:
        raise ValueError(
            f"could not reach ComfyUI at {base}: {exc} — is it running with "
            "--listen so other machines can connect?") from exc
    if resp.status_code >= 400:
        raise ValueError(
            f"ComfyUI rejected the workflow ({resp.status_code}): "
            f"{resp.text[:300]}")
    try:
        prompt_id = resp.json()["prompt_id"]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unexpected ComfyUI response: {exc}") from exc

    deadline = time.monotonic() + COMFY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            hist = httpx.get(f"{base}/history/{prompt_id}", timeout=30.0).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ValueError(f"lost ComfyUI while waiting for the image: {exc}") from exc
        entry = hist.get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                # Surface the failing node's message if the history carries one.
                detail = json.dumps(status.get("messages", ""))[:300]
                raise ValueError(f"ComfyUI reported an execution error: {detail}")
            for node_output in (entry.get("outputs") or {}).values():
                for img in node_output.get("images", []):
                    fname = img.get("filename", "")
                    if not fname:
                        continue
                    try:
                        view = httpx.get(f"{base}/view", params={
                            "filename": fname,
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                        }, timeout=60.0)
                    except httpx.HTTPError as exc:
                        raise ValueError(f"could not download the image from "
                                         f"ComfyUI: {exc}") from exc
                    if view.status_code >= 400:
                        raise ValueError(f"ComfyUI /view error {view.status_code}")
                    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "png"
                    return view.content, _EXT.get(ext, "png")
            raise ValueError(
                "the ComfyUI workflow finished but produced no image output — "
                "make sure it ends in a SaveImage node")
        time.sleep(COMFY_POLL_INTERVAL)
    raise ValueError(f"ComfyUI did not finish within {int(COMFY_TIMEOUT)}s")


# --------------------------------------------------------------------------- #
# File persistence
# --------------------------------------------------------------------------- #
def _clear_slot_files(encounter_id: str, slot: str, root: Optional[Path] = None) -> None:
    d = (root or ART_DIR) / encounter_id
    if d.is_dir():
        for p in d.glob(f"{slot}-*.*"):
            p.unlink(missing_ok=True)


def _write_image(encounter_id: str, slot: str, raw: bytes, ext: str,
                 root: Optional[Path] = None) -> str:
    """Persist the image, replacing the slot's previous file. Returns the URL.

    The filename carries a random token so a regenerated image gets a NEW URL —
    browsers cache aggressively and would otherwise keep showing the old art.
    ``root`` writes outside the tracked content dir — RUN-scoped art (a forged
    drop's picture) belongs in the gitignored loadouts space, served under the
    same /art URLs."""
    d = (root or ART_DIR) / encounter_id
    d.mkdir(parents=True, exist_ok=True)
    _clear_slot_files(encounter_id, slot, root)
    fname = f"{slot}-{secrets.token_hex(4)}.{ext}"
    (d / fname).write_bytes(raw)
    return f"{ART_URL_PREFIX}/{encounter_id}/{fname}"


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def _load(encounter_id: str) -> Dict[str, Any]:
    enc = content.encounter_detail(encounter_id)
    if enc is None:
        raise ValueError(f"unknown encounter: {encounter_id}")
    return enc


def generate(encounter_id: str, kind: str, enemy_id: Optional[str] = None,
             text: str = "") -> Dict[str, Any]:
    """Generate art for an encounter's scene or one enemy; persist both the image
    file and the updated encounter JSON. Returns ``{"url": ...}``.

    ``text`` optionally overrides the saved description as the prompt's subject —
    the editor passes its live (possibly unsaved) textarea so what you see is what
    gets painted. The override is prompt-only; it is never written back.
    """
    enc = _load(encounter_id)
    settings = llm.load_settings()
    if kind == "scene":
        prompt, aspect, slot = scene_prompt(enc, text), "16:9", "scene"
    elif kind == "enemy":
        # enemy_id is the canonical slot key: a pool enemy's id or a token def's
        # key (a token def carries no "id" of its own).
        enemy = _find_enemy(enc, enemy_id)
        prompt, aspect, slot = enemy_prompt(enc, enemy, text), "1:1", str(enemy_id)
    else:
        raise ValueError(f"unknown art kind: {kind} (use 'scene' or 'enemy')")

    if settings.get("art_backend") == "comfyui":
        if not settings["comfyui_url"]:
            raise ValueError("No ComfyUI server address set. Add one in "
                             "Options → LLM → Art Generation.")
        if not settings["comfyui_workflow"]:
            raise ValueError("No ComfyUI workflow set. Paste your API-format "
                             "workflow export in Options → LLM → Art Generation.")
        raw, ext = _request_comfyui(settings["comfyui_url"],
                                    settings["comfyui_workflow"], prompt, aspect)
    else:
        if not settings["api_key"]:
            raise ValueError("No OpenRouter API key set. Add one in Options → LLM.")
        raw, ext = _request_image(settings["api_key"], prompt, aspect)
    url = _write_image(encounter_id, slot, raw, ext)
    if kind == "scene":
        enc["scene_image"] = url
    else:
        _find_enemy(enc, enemy_id)["image"] = url
    content.save_encounter(enc, encounter_id)  # same validate + persist path as edits
    return {"url": url}


def paint(prompt: str, aspect: str, folder: str, slot: str,
          root: Optional[Path] = None) -> str:
    """Generate ONE image from a finished prompt with the configured backend
    and persist it under ``content/art/<folder>/<slot>-<token>.<ext>``;
    returns the URL. The generic path behind town / location / NPC / item art
    (Update 17) — encounter art keeps its own prompt assembly above."""
    settings = llm.load_settings()
    if settings.get("art_backend") == "comfyui":
        if not settings["comfyui_url"]:
            raise ValueError("No ComfyUI server address set. Add one in "
                             "Options → LLM → Art Generation.")
        if not settings["comfyui_workflow"]:
            raise ValueError("No ComfyUI workflow set. Paste your API-format "
                             "workflow export in Options → LLM → Art Generation.")
        raw, ext = _request_comfyui(settings["comfyui_url"],
                                    settings["comfyui_workflow"], prompt, aspect)
    else:
        if not settings["api_key"]:
            raise ValueError("No OpenRouter API key set. Add one in Options → LLM.")
        raw, ext = _request_image(settings["api_key"], prompt, aspect)
    return _write_image(folder, slot, raw, ext, root)


_TOWN_TASK = (
    "Paint a wide establishing view of a fantasy town for a painterly tactical "
    "card game — the TOWN MAP backdrop, classic high fantasy. Environment and "
    "architecture only: NO people, NO creatures. Painted edge to edge.\n\n"
    "The town:\n"
)
_EXTERIOR_TASK = (
    "Paint the EXTERIOR of ONE building in a fantasy town — as seen from the "
    "outside — as the card art for a location on a town map, in a painterly "
    "tactical card game (classic high fantasy), matching the interior backdrops: "
    "the building fills the frame across its width, with the surrounding area "
    "falling away to either side; NO people, NO creatures. Warm light.\n\n"
    "The building:\n"
)
_INTERIOR_TASK = (
    "Paint the INTERIOR of ONE location in a fantasy town from the eye level of "
    "someone standing inside it — the room around them — as a wide backdrop for "
    "a painterly tactical card game (classic high fantasy). Environment only: "
    "NO people, NO creatures. Wide composition, an uncluttered middle ground "
    "where figures will stand, warm atmospheric light.\n\nWhat they see:\n"
)
_NPC_TASK = (
    "Paint a single character portrait for a townsperson card in a painterly "
    "tactical fantasy card game. ONE subject, three-quarter view, centred, calm "
    "or characterful pose (this is a townsperson, not a monster), background "
    "falling off into a dark vignette.\n\nThe person:\n"
)


def generate_town_art(town_id: str, kind: str, target_id: Optional[str] = None,
                      text: str = "") -> Dict[str, Any]:
    """Town art (Update 17 §D17-5.1): ``kind`` town (the map scene) /
    location_exterior (the map card) / location_interior (the backdrop; alias
    "location") / npc. Writes under ``content/art/towns/<town_id>/`` and updates
    the town JSON. Returns ``{"url"}``."""
    from . import scenario_content as sc
    town = sc.town_detail(town_id)
    if town is None:
        raise ValueError(f"unknown town: {town_id}")
    style = _style()
    # Exteriors belong to this town — hint its own scene so a treetop village's
    # buildings don't drift into generic-town material/architecture (same trick
    # as enemy_prompt anchoring an enemy portrait to its encounter's scene).
    # Interiors skip this: the town scene bled through into the room itself.
    town_scene = str(town.get("scene") or "").strip()
    town_context = (f"\n\nThis stands in this town (match its architecture, "
                    f"materials, and mood; do NOT paint the wider town in "
                    f"detail): {town_scene}") if town_scene else ""
    if kind == "town":
        prompt = f"{style}\n\n{_TOWN_TASK}{text or town.get('scene', '')}"
        aspect, slot = "16:9", "town"
    elif kind in ("location", "location_interior"):
        loc = sc.find_location(town, str(target_id))
        if loc is None:
            raise ValueError(f"unknown location: {target_id}")
        prompt = (f"{style}\n\n{_INTERIOR_TASK}"
                  f"{text or loc.get('interior_scene') or loc.get('scene', '')}")
        aspect, slot = "16:9", f"loc-{loc['id']}"
    elif kind == "location_exterior":
        loc = sc.find_location(town, str(target_id))
        if loc is None:
            raise ValueError(f"unknown location: {target_id}")
        if not (text or loc.get("exterior_scene")):
            raise ValueError(f"{loc['name']} has no exterior scene to paint from")
        prompt = (f"{style}\n\n{_EXTERIOR_TASK}{loc['name']}. "
                  f"{text or loc.get('exterior_scene', '')}{town_context}")
        # The map card is the same 16:9 as the interior it opens into.
        aspect, slot = "16:9", f"ext-{loc['id']}"
    elif kind == "npc":
        found = sc.find_npc(town, str(target_id))
        if found is None:
            raise ValueError(f"unknown npc: {target_id}")
        npc = found[1]
        prompt = (f"{style}\n\n{_NPC_TASK}{npc.get('name', '')}, {npc.get('role', '')}. "
                  f"{text or npc.get('portrait_desc', '')}")
        aspect, slot = "1:1", f"npc-{npc['id']}"
    else:
        raise ValueError(f"unknown town art kind: {kind}")
    url = paint(prompt, aspect, f"towns/{town_id}", slot)
    if kind == "town":
        town["art_url"] = url
    elif kind in ("location", "location_interior"):
        loc = sc.find_location(town, str(target_id))
        loc["interior_art_url"] = url
        loc["art_url"] = url
    elif kind == "location_exterior":
        sc.find_location(town, str(target_id))["exterior_art_url"] = url
    else:
        sc.find_npc(town, str(target_id))[1]["art_url"] = url
    town.pop("id", None)
    sc.save_town(town, town_id)
    return {"url": url}


def town_art_items(town_id: str) -> List[Dict[str, Any]]:
    """Every still-missing town image as generic queue items: the map first,
    then each location backdrop, then each NPC portrait."""
    from . import scenario_content as sc
    town = sc.town_detail(town_id)
    if town is None:
        return []
    items: List[Dict[str, Any]] = []
    name = town.get("name", town_id)

    def item(label: str, kind: str, target: Optional[str]) -> Dict[str, Any]:
        def _paint(kind=kind, target=target) -> None:
            fresh = sc.town_detail(town_id) or {}
            if kind == "town" and fresh.get("art_url"):
                return
            if kind == "location_interior" and (sc.find_location(fresh, target) or {}).get("interior_art_url"):
                return
            if kind == "location_exterior" and (sc.find_location(fresh, target) or {}).get("exterior_art_url"):
                return
            if kind == "npc":
                found = sc.find_npc(fresh, target)
                if found and found[1].get("art_url"):
                    return
            generate_town_art(town_id, kind, target)
        return {"label": label, "paint": _paint, "refresh_key": f"town:{town_id}"}

    if not town.get("art_url"):
        items.append(item(f"{name} — town map", "town", None))
    for loc in town.get("locations") or []:
        if loc.get("exterior_scene") and not loc.get("exterior_art_url"):
            items.append(item(f"{name} — {loc['name']} (exterior)", "location_exterior", loc["id"]))
        if not loc.get("interior_art_url"):
            items.append(item(f"{name} — {loc['name']} (interior)", "location_interior", loc["id"]))
    for loc in town.get("locations") or []:
        for npc in loc.get("npcs") or []:
            if not npc.get("art_url"):
                items.append(item(f"{name} — {npc['name']}", "npc", npc["id"]))
    return items


_ITEM_TASK = (
    "Paint a single ITEM for a card in a painterly tactical fantasy card game: "
    "the object alone, centred, on a dark atmospheric ground falling off into a "
    "vignette — no people, no hands, no creatures. Rich material detail: metal, "
    "leather, glass, wax, cloth.\n\nThe item:\n"
)


def generate_item_art(item_id: str, text: str = "") -> Dict[str, Any]:
    """Item art (Update 17 §D17-4.3): ``content/art/items/<item_id>/``; the
    item's JSON gets its art_url. Returns ``{"url"}``."""
    from . import items as _items
    item = _items.get_item(item_id)
    if item is None:
        raise ValueError(f"unknown item: {item_id}")
    prompt = f"{_style()}\n\n{_ITEM_TASK}{item.name}. {text or item.art_desc or item.flavor}"
    # 3:2 — the art frame on a card face (§D17-4.4: a consumable is played AS a
    # card, so its art is painted for that slot; the square inventory tiles crop
    # it with object-cover).
    url = paint(prompt, "3:2", f"items/{item_id}", "item")
    _items.set_item_art(item_id, url)
    return {"url": url}


# --------------------------------------------------------------------------- #
# Spoils art (§D17-4.5): the act's forged drops
# --------------------------------------------------------------------------- #
# A forged drop exists only inside a run, so its picture is RUN data: it lands
# in the gitignored loadouts art space (served under the same /art URLs), never
# in the tracked catalogue. The act freezes its spoils on arrival in town, so
# this queue paints them while the party shops and rides out — by the time the
# boss falls, the Rewards modal has pictures instead of sigils.
SPOILS_ROOT = LEGACY_ART_DIR
SPOILS_FOLDER = "spoils"


# --------------------------------------------------------------------------- #
# Scenario cast & places (§D20-2): the arc's own people and ground, painted
# content-addressed so every run of the scenario shares one set of pictures —
# the first run to arrive paints them, every later one adopts from disk.
# --------------------------------------------------------------------------- #
CAST_FOLDER = "cast"
PLACES_FOLDER = "places"


def _cast_key(entry: Dict[str, Any], *texts: str) -> str:
    """A stable id from the entry's id + its describing prose, so two scenarios'
    unrelated "the_stranger"s never share a face, while the same scenario's
    stranger keeps theirs across runs."""
    blob = "|".join([str(entry.get("id") or "")] + [str(t or "") for t in texts])
    return f"{_slug(str(entry.get('id') or 'cast'))[:32]}_{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:10]}"


def _keyed_art_url(folder: str, key: str) -> str:
    d = SPOILS_ROOT / folder / key
    if d.is_dir():
        for p in sorted(d.glob("*.*")):
            return f"{ART_URL_PREFIX}/{folder}/{key}/{p.name}"
    return ""


def generate_cast_art(npc: Dict[str, Any]) -> Dict[str, Any]:
    """Paint one cast member's portrait from their portrait_desc."""
    key = _cast_key(npc, npc.get("portrait_desc"))
    existing = _keyed_art_url(CAST_FOLDER, key)
    if existing:
        return {"url": existing}
    prompt = (f"{_style()}\n\n{_NPC_TASK}{npc.get('name', '')}, {npc.get('role', '')}. "
              f"{npc.get('portrait_desc', '')}")
    url = paint(prompt, "1:1", f"{CAST_FOLDER}/{key}", "npc", root=SPOILS_ROOT)
    return {"url": url}


def generate_place_art(place: Dict[str, Any], which: str,
                       town_scene: str = "") -> Dict[str, Any]:
    """Paint one arc place's ``interior`` backdrop or ``exterior`` map card."""
    scene = str(place.get(f"{which}_scene") or "").strip()
    if not scene:
        raise ValueError(f"{place.get('name')} has no {which} scene to paint from")
    key = _cast_key(place, scene)
    slot = "int" if which == "interior" else "ext"
    existing = _keyed_art_url(PLACES_FOLDER, f"{key}/{slot}")
    if existing:
        return {"url": existing}
    if which == "interior":
        prompt = f"{_style()}\n\n{_INTERIOR_TASK}{scene}"
    else:
        ctx = (f"\n\nThis stands in this town (match its architecture, materials, "
               f"and mood; do NOT paint the wider town in detail): {town_scene}"
               if town_scene else "")
        prompt = f"{_style()}\n\n{_EXTERIOR_TASK}{place.get('name', '')}. {scene}{ctx}"
    url = paint(prompt, "16:9", f"{PLACES_FOLDER}/{key}/{slot}", slot, root=SPOILS_ROOT)
    return {"url": url}


def scenario_cast_art_items(arc: Dict[str, Any], town_scene: str,
                            on_painted: Callable[[str, str, str], None]
                            ) -> List[Dict[str, Any]]:
    """Queue items for every arc cast portrait and place backdrop still without
    a picture. ``on_painted(kind, entry_id, url)`` — kind is ``cast`` /
    ``place_interior`` / ``place_exterior`` — writes the URL back onto the
    run's arc (and, via recomposition, the merged town)."""
    out: List[Dict[str, Any]] = []
    for npc in arc.get("cast") or []:
        if npc.get("art_url"):
            continue
        known = _keyed_art_url(CAST_FOLDER, _cast_key(npc, npc.get("portrait_desc")))
        if known:
            on_painted("cast", npc["id"], known)
            continue

        def _paint_npc(npc=npc) -> None:
            on_painted("cast", npc["id"], generate_cast_art(npc)["url"])
        out.append({"label": f'cast — {npc.get("name", npc["id"])}',
                    "paint": _paint_npc, "refresh_key": "cast"})
    for pl in arc.get("places") or []:
        for which, url_key in (("interior", "interior_art_url"),
                               ("exterior", "exterior_art_url")):
            if pl.get(url_key) or not str(pl.get(f"{which}_scene") or "").strip():
                continue
            slot = "int" if which == "interior" else "ext"
            known = _keyed_art_url(PLACES_FOLDER,
                                   f"{_cast_key(pl, pl.get(f'{which}_scene'))}/{slot}")
            if known:
                on_painted(f"place_{which}", pl["id"], known)
                continue

            def _paint_pl(pl=pl, which=which) -> None:
                on_painted(f"place_{which}", pl["id"],
                           generate_place_art(pl, which, town_scene)["url"])
            out.append({"label": f'place — {pl.get("name", pl["id"])} ({which})',
                        "paint": _paint_pl, "refresh_key": "cast"})
    return out


def spoil_art_url(item_id: str) -> str:
    """The already-painted picture for this forged drop, or "" — so a requeue
    (a reload, a second act) never repaints what is on disk."""
    d = SPOILS_ROOT / SPOILS_FOLDER / item_id
    if d.is_dir():
        for p in sorted(d.glob("item-*.*")):
            return f"{ART_URL_PREFIX}/{SPOILS_FOLDER}/{item_id}/{p.name}"
    return ""


def generate_spoil_art(item: Dict[str, Any]) -> Dict[str, Any]:
    """Paint one forged drop from the words it was forged with. Takes the item
    DICT (it is not in the catalogue registry); returns ``{"url"}``."""
    iid = str(item.get("id") or "")
    if not iid:
        raise ValueError("a spoil needs an id")
    existing = spoil_art_url(iid)
    if existing:
        return {"url": existing}
    subject = f'{item.get("name", "")}. {item.get("art_desc") or item.get("flavor") or ""}'
    url = paint(f"{_style()}\n\n{_ITEM_TASK}{subject}", "3:2",
                f"{SPOILS_FOLDER}/{iid}", "item", root=SPOILS_ROOT)
    return {"url": url}


def spoil_art_items(spoils: List[Dict[str, Any]],
                    on_painted: Callable[[str, str], None]) -> List[Dict[str, Any]]:
    """Queue items for every drop still without a picture. ``on_painted(item_id,
    url)`` writes the URL back onto the run's copy of the drop."""
    out: List[Dict[str, Any]] = []
    for raw in spoils:
        iid = str(raw.get("id") or "")
        if not iid or raw.get("art_url"):
            continue
        known = spoil_art_url(iid)
        if known:
            on_painted(iid, known)     # painted by an earlier act / before a reload
            continue

        def _paint(raw=raw, iid=iid) -> None:
            on_painted(iid, generate_spoil_art(raw)["url"])
        out.append({"label": f'spoils — {raw.get("name", iid)}', "paint": _paint,
                    "refresh_key": "spoils"})
    return out


def item_art_items() -> List[Dict[str, Any]]:
    """Every catalogue / user item without art, as generic queue items."""
    from . import items as _items
    out: List[Dict[str, Any]] = []
    for meta in _items.list_items():
        if meta.get("art_url"):
            continue
        iid = meta["id"]

        def _paint(iid=iid) -> None:
            fresh = _items.get_item(iid)
            if fresh is None or fresh.art_url:
                return
            generate_item_art(iid)
        out.append({"label": f"item — {meta['name']}", "paint": _paint, "refresh_key": "items"})
    return out


# --------------------------------------------------------------------------- #
# The art queue — "Generate all art" (Design Update 10 §D10-6.4)
# --------------------------------------------------------------------------- #
class ArtQueue:
    """Sequential generate-all jobs, one per content id (an encounter, or an
    adventure covering its phases in order). One generation in flight per job;
    each completion — success or failure — fires the next: a failure is logged
    and skipped, never blocking the queue. Enqueueing is idempotent (only what
    is still missing joins), and every landed image broadcasts to connected
    clients through the same refresh path a single generation takes."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _item_key(item: Dict[str, Any]) -> "tuple":
        if item.get("paint") is not None:
            return ("generic", item.get("label"))
        return (item["encounter_id"], item["kind"], item["enemy_id"])

    def start_items(self, key: str, items: List[Dict[str, Any]],
                    refresh: Callable[[str], Awaitable[None]]) -> Dict[str, Any]:
        """Queue prebuilt GENERIC items (each ``{"label", "paint": callable,
        "refresh_key"?}``) under ``key`` — the town / scenario art queues
        (Update 17). Same idempotence and skip-on-failure as `start`."""
        job = self._jobs.get(key)
        if job and job["running"]:
            queued = {self._item_key(i) for i in job["pending"]}
            if job["current"] is not None:
                queued.add(self._item_key(job["current"]))
            fresh = [i for i in items if self._item_key(i) not in queued]
            job["pending"].extend(fresh)
            job["total"] += len(fresh)
            return self.status(key)
        job = {"pending": list(items), "total": len(items), "done": 0,
               "failed": 0, "running": bool(items), "current": None,
               "errors": []}
        self._jobs[key] = job
        if items:
            asyncio.get_running_loop().create_task(self._run(key, refresh))
        return self.status(key)

    @staticmethod
    def _missing(encounter_ids: List[str]) -> List[Dict[str, Any]]:
        """Every absent image across the given encounters, in order: the
        backdrop first, then each undrawn enemy / token portrait."""
        items: List[Dict[str, Any]] = []
        for eid in encounter_ids:
            enc = content.encounter_detail(eid)
            if enc is None:
                continue
            name = str(enc.get("name") or eid)
            # A backdrop needs a scene description to paint from; a hand-
            # authored encounter without one is skipped, not failed.
            if not enc.get("scene_image") and str(enc.get("scene") or "").strip():
                items.append({"encounter_id": eid, "kind": "scene",
                              "enemy_id": None, "label": f"{name} — backdrop"})
            for e in enc.get("enemies", []):
                if isinstance(e, dict) and not e.get("image"):
                    pid = _enemy_pool_id(e)
                    items.append({"encounter_id": eid, "kind": "enemy",
                                  "enemy_id": pid,
                                  "label": f"{name} — {e.get('name', pid)}"})
            for tid, tok in (enc.get("tokens") or {}).items():
                if isinstance(tok, dict) and not tok.get("image"):
                    items.append({"encounter_id": eid, "kind": "enemy",
                                  "enemy_id": str(tid),
                                  "label": f"{name} — {tok.get('name', tid)}"})
        return items

    def start(self, key: str, encounter_ids: List[str],
              refresh: Callable[[str], Awaitable[None]]) -> Dict[str, Any]:
        """Queue every still-missing image for the given encounters (an
        adventure passes its phases in order) and start the runner if idle.
        Pressing again while running only adds what is newly missing."""
        missing = self._missing(encounter_ids)
        job = self._jobs.get(key)
        if job and job["running"]:
            queued = {self._item_key(i) for i in job["pending"]}
            if job["current"] is not None:
                queued.add(self._item_key(job["current"]))
            fresh = [i for i in missing if self._item_key(i) not in queued]
            job["pending"].extend(fresh)
            job["total"] += len(fresh)
            return self.status(key)
        job = {"pending": missing, "total": len(missing), "done": 0,
               "failed": 0, "running": bool(missing), "current": None,
               "errors": []}
        self._jobs[key] = job
        if missing:
            asyncio.get_running_loop().create_task(self._run(key, refresh))
        return self.status(key)

    async def _run(self, key: str,
                   refresh: Callable[[str], Awaitable[None]]) -> None:
        job = self._jobs[key]
        try:
            while job["pending"]:
                item = job["pending"].pop(0)
                job["current"] = item
                try:
                    if item.get("paint") is not None:
                        # A generic item (town / location / NPC / item art —
                        # Update 17): its own painter decides freshness.
                        await asyncio.to_thread(item["paint"])
                        await refresh(item.get("refresh_key") or key)
                        job["done"] += 1
                        continue
                    # Re-check on execution: an image may have landed since the
                    # enqueue (a manual Paint, or an overlapping press).
                    current = content.encounter_art(item["encounter_id"])
                    have = (current["scene"] if item["kind"] == "scene"
                            else current["enemies"].get(item["enemy_id"] or "", ""))
                    if not have:
                        await asyncio.to_thread(
                            generate, item["encounter_id"], item["kind"],
                            item["enemy_id"], "")
                        await refresh(item["encounter_id"])
                    job["done"] += 1
                except Exception as exc:  # skip-on-failure — the queue never stalls
                    job["failed"] += 1
                    job["errors"].append(f"{item['label']}: {exc}")
        finally:
            job["current"] = None
            job["running"] = False

    def status(self, key: str) -> Dict[str, Any]:
        job = self._jobs.get(key)
        if job is None:
            return {"total": 0, "done": 0, "failed": 0, "running": False,
                    "current": None, "errors": []}
        return {"total": job["total"], "done": job["done"],
                "failed": job["failed"], "running": job["running"],
                "current": (job["current"] or {}).get("label"),
                "errors": list(job["errors"][-3:])}


QUEUE = ArtQueue()


def remove(encounter_id: str, kind: str, enemy_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete the scene's / one enemy's art: the file and the JSON reference."""
    enc = _load(encounter_id)
    if kind == "scene":
        slot = "scene"
        enc["scene_image"] = ""
    elif kind == "enemy":
        enemy = _find_enemy(enc, enemy_id)
        slot = str(enemy_id)
        enemy.pop("image", None)
    else:
        raise ValueError(f"unknown art kind: {kind} (use 'scene' or 'enemy')")
    _clear_slot_files(encounter_id, slot)
    content.save_encounter(enc, encounter_id)
    return {"ok": True}
