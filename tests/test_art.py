"""Art generation tests: prompt assembly from encounter JSON, image persistence,
encounter references, and the settings plumbing. The OpenRouter call is mocked —
these never touch the network."""

from __future__ import annotations

import base64
import json

import pytest

from ltg_game_server import art, content, llm


# --------------------------------------------------------------------------- #
# Isolation: everything (encounters, settings, art files) under tmp_path
# --------------------------------------------------------------------------- #
@pytest.fixture
def loadouts(tmp_path, monkeypatch):
    d = tmp_path / "loadouts"
    monkeypatch.setattr(content, "LOADOUTS_DIR", d)
    monkeypatch.setattr(content, "_SCAN_DIRS", [d])
    monkeypatch.setattr(content, "HIDDEN_FILE", d / "hidden.json")
    monkeypatch.setattr(content, "ENCOUNTER_HIDDEN_FILE", d / "encounters_hidden.json")
    monkeypatch.setattr(llm, "SETTINGS_PATH", d / "llm_settings.json")
    monkeypatch.setattr(art, "ART_DIR", d / "art")
    return d


ENC = {
    "name": "Test Fight",
    "scene": "A ruined chapel at midnight, moonlight through a shattered window.",
    "enemies": [
        {"id": "ghoul", "name": "Ghoul", "hp": 4, "level": 1, "power": 1,
         "description": "A grey, hunched corpse-eater with too many teeth."},
        {"id": "warden", "name": "Warden", "hp": 6, "level": 2, "power": 2},
    ],
    # A token definition (what a Swarm spawns) — creatures too, art-wise.
    "tokens": {"husk": {"name": "Husk", "hp": 2, "power": 1, "row": "front",
                        "attack_mode": "melee"}},
}


@pytest.fixture
def encounter(loadouts):
    meta = content.save_encounter(dict(ENC))
    return meta["id"]  # "test_fight"


def _fake_image_response(raw=b"fake-png-bytes", mime="png", status=200):
    b64 = base64.b64encode(raw).decode()

    class Resp:
        status_code = status
        text = "err"

        @staticmethod
        def json():
            return {"choices": [{"message": {
                "content": "",
                "images": [{"type": "image_url",
                            "image_url": {"url": f"data:image/{mime};base64,{b64}"}}],
            }}]}

    return Resp()


@pytest.fixture
def mock_openrouter(monkeypatch):
    """Patch art's httpx.post; records every request payload."""
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _fake_image_response()

    monkeypatch.setattr(art.httpx, "post", post)
    return calls


def _set_key():
    llm.save_settings({"api_key": "sk-test"})


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #
def test_scene_prompt_carries_style_and_scene_text(loadouts, encounter):
    enc = content.encounter_detail(encounter)
    p = art.scene_prompt(enc)
    assert "ruined chapel" in p                       # the encounter's own prose
    assert "heroic realism" in p                      # the default style wrapper
    assert "no creatures" in p.lower()                # backdrop framing

def test_enemy_prompt_uses_description_and_hints_scene(loadouts, encounter):
    enc = content.encounter_detail(encounter)
    p = art.enemy_prompt(enc, enc["enemies"][0])
    assert "corpse-eater" in p and "Ghoul" in p
    assert "ruined chapel" in p                       # palette-coherence hint

def test_enemy_prompt_falls_back_to_name(loadouts, encounter):
    enc = content.encounter_detail(encounter)
    p = art.enemy_prompt(enc, enc["enemies"][1])      # Warden has no description
    assert '"Warden"' in p

def test_custom_art_style_reaches_the_prompt(loadouts, encounter):
    llm.save_settings({"art_style": "Pale watercolor, misty and soft."})
    enc = content.encounter_detail(encounter)
    assert "Pale watercolor" in art.scene_prompt(enc)

def test_scene_prompt_requires_a_description(loadouts):
    eid = content.save_encounter({"name": "Bare", "enemies": [
        {"id": "e1", "name": "E1", "hp": 1, "level": 1, "power": 1}]})["id"]
    with pytest.raises(ValueError, match="scene description"):
        art.scene_prompt(content.encounter_detail(eid))

def test_editor_text_override_wins(loadouts, encounter):
    enc = content.encounter_detail(encounter)
    p = art.scene_prompt(enc, "A frozen lake under green aurora.")
    assert "frozen lake" in p and "ruined chapel" not in p


# --------------------------------------------------------------------------- #
# Generate / remove
# --------------------------------------------------------------------------- #
def test_generate_scene_persists_file_and_reference(loadouts, encounter, mock_openrouter):
    _set_key()
    out = art.generate(encounter, "scene")
    url = out["url"]
    assert url.startswith(f"/art/{encounter}/scene-") and url.endswith(".png")
    # The file exists and holds the model's bytes.
    fname = url.split("/")[-1]
    assert (art.ART_DIR / encounter / fname).read_bytes() == b"fake-png-bytes"
    # The reference rides the encounter (so replays include it).
    assert content.encounter_detail(encounter)["scene_image"] == url
    assert content.encounter_for(encounter)["scene_image"] == url
    # The request asked for a wide backdrop with both modalities.
    req = mock_openrouter[-1]
    assert req["model"] == art.ART_MODEL
    assert req["modalities"] == ["image", "text"]
    assert req["image_config"] == {"aspect_ratio": "16:9"}

def test_regenerate_replaces_the_old_file(loadouts, encounter, mock_openrouter):
    _set_key()
    url1 = art.generate(encounter, "scene")["url"]
    url2 = art.generate(encounter, "scene")["url"]
    assert url1 != url2                               # cache-busting filename
    files = list((art.ART_DIR / encounter).glob("scene-*.*"))
    assert [f"/art/{encounter}/{p.name}" for p in files] == [url2]

def test_generate_enemy_sets_the_pool_reference(loadouts, encounter, mock_openrouter):
    _set_key()
    url = art.generate(encounter, "enemy", "ghoul")["url"]
    assert url.startswith(f"/art/{encounter}/ghoul-")
    enemies = {e["id"]: e for e in content.encounter_detail(encounter)["enemies"]}
    assert enemies["ghoul"]["image"] == url
    assert "image" not in enemies["warden"]
    assert mock_openrouter[-1]["image_config"] == {"aspect_ratio": "1:1"}

def test_remove_clears_file_and_reference(loadouts, encounter, mock_openrouter):
    _set_key()
    art.generate(encounter, "scene")
    art.generate(encounter, "enemy", "ghoul")
    art.remove(encounter, "scene")
    art.remove(encounter, "enemy", "ghoul")
    detail = content.encounter_detail(encounter)
    assert detail["scene_image"] == ""
    assert all("image" not in e for e in detail["enemies"])
    assert list((art.ART_DIR / encounter).glob("*.*")) == []

def test_generate_requires_api_key(loadouts, encounter):
    with pytest.raises(ValueError, match="API key"):
        art.generate(encounter, "scene")

def test_generate_unknown_enemy_or_kind(loadouts, encounter, mock_openrouter):
    _set_key()
    with pytest.raises(ValueError, match="unknown enemy"):
        art.generate(encounter, "enemy", "dragon")
    with pytest.raises(ValueError, match="unknown art kind"):
        art.generate(encounter, "banner")

def test_400_retries_once_without_image_config(loadouts, encounter, monkeypatch):
    _set_key()
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if "image_config" in json:
            resp = _fake_image_response(status=400)
            return resp
        return _fake_image_response()

    monkeypatch.setattr(art.httpx, "post", post)
    out = art.generate(encounter, "scene")
    assert out["url"].endswith(".png")
    assert len(calls) == 2 and "image_config" not in calls[1]


def test_generate_token_art_sets_the_definition_reference(loadouts, encounter, mock_openrouter):
    """A token definition (a Swarm's spawn) takes art exactly like a pool enemy,
    keyed by the tokens-dict key — every live spawn shares it."""
    _set_key()
    url = art.generate(encounter, "enemy", "husk")["url"]
    assert url.startswith(f"/art/{encounter}/husk-")
    detail = content.encounter_detail(encounter)
    assert detail["tokens"]["husk"]["image"] == url
    assert content.encounter_art(encounter)["enemies"]["husk"] == url
    # And a token def with no description prompts from its name.
    assert '"Husk"' in mock_openrouter[-1]["messages"][0]["content"]

def test_remove_token_art(loadouts, encounter, mock_openrouter):
    _set_key()
    art.generate(encounter, "enemy", "husk")
    art.remove(encounter, "enemy", "husk")
    detail = content.encounter_detail(encounter)
    assert "image" not in detail["tokens"]["husk"]
    assert list((art.ART_DIR / encounter).glob("husk-*.*")) == []


# --------------------------------------------------------------------------- #
# ComfyUI backend (a user-supplied workflow on a local server)
# --------------------------------------------------------------------------- #
COMFY_WORKFLOW = json.dumps({
    "3": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["4", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "model.safetensors"}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": "%width%", "height": "%height%", "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "masterpiece, %prompt%, sharp focus", "clip": ["4", 1]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
})


def _use_comfy(url="http://gpu-box:8188", workflow=COMFY_WORKFLOW):
    llm.save_settings({"art_backend": "comfyui", "comfyui_url": url,
                       "comfyui_workflow": workflow})


@pytest.fixture
def mock_comfy(monkeypatch):
    """A fake ComfyUI server: records the queued workflow, serves one image."""
    calls = {"post": [], "get": []}

    class Resp:
        def __init__(self, payload=None, content=b"", status=200):
            self._payload, self.content, self.status_code = payload, content, status
            self.text = "err"

        def json(self):
            return self._payload

    def post(url, headers=None, json=None, timeout=None):
        calls["post"].append((url, json))
        return Resp({"prompt_id": "pid-1"})

    def get(url, params=None, timeout=None):
        calls["get"].append((url, params))
        if "/history/" in url:
            return Resp({"pid-1": {
                "status": {"status_str": "success"},
                "outputs": {"9": {"images": [
                    {"filename": "LTG_0001_.png", "subfolder": "", "type": "output"}]}},
            }})
        return Resp(content=b"comfy-png-bytes")  # /view

    monkeypatch.setattr(art.httpx, "post", post)
    monkeypatch.setattr(art.httpx, "get", get)
    return calls


def test_comfyui_backend_queues_injected_workflow(loadouts, encounter, mock_comfy):
    _use_comfy()
    out = art.generate(encounter, "scene")
    assert out["url"].startswith(f"/art/{encounter}/scene-")
    fname = out["url"].split("/")[-1]
    assert (art.ART_DIR / encounter / fname).read_bytes() == b"comfy-png-bytes"
    # The queued workflow got the prompt injected in place (tags survive) and
    # the 16:9 scene sizes as integers.
    url, payload = mock_comfy["post"][0]
    assert url == "http://gpu-box:8188/prompt"
    wf = payload["prompt"]
    text = wf["6"]["inputs"]["text"]
    assert text.startswith("masterpiece, ") and text.endswith(", sharp focus")
    assert "ruined chapel" in text and "%prompt%" not in text
    assert (wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]) == (1344, 768)
    # And the image was fetched through /view with the history's coordinates.
    view = [c for c in mock_comfy["get"] if c[0].endswith("/view")][0]
    assert view[1]["filename"] == "LTG_0001_.png"


def test_comfyui_seed_placeholder_rolls_per_generation(loadouts, encounter, mock_comfy, monkeypatch):
    wf = json.loads(COMFY_WORKFLOW)
    wf["3"]["inputs"]["seed"] = "%seed%"
    _use_comfy(workflow=json.dumps(wf))
    art.generate(encounter, "scene")
    art.generate(encounter, "scene")
    seeds = [c[1]["prompt"]["3"]["inputs"]["seed"] for c in mock_comfy["post"]]
    assert all(isinstance(s, int) for s in seeds)
    # Two rolls colliding is a ~1-in-2^31 fluke; a repeat here means %seed% broke.
    assert seeds[0] != seeds[1]


def test_comfyui_enemy_art_is_square(loadouts, encounter, mock_comfy):
    _use_comfy()
    art.generate(encounter, "enemy", "ghoul")
    wf = mock_comfy["post"][0][1]["prompt"]
    assert (wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]) == (1024, 1024)


def test_comfyui_requires_url_and_workflow(loadouts, encounter):
    llm.save_settings({"art_backend": "comfyui"})
    with pytest.raises(ValueError, match="server address"):
        art.generate(encounter, "scene")
    llm.save_settings({"comfyui_url": "http://gpu-box:8188"})
    with pytest.raises(ValueError, match="workflow"):
        art.generate(encounter, "scene")


def test_comfyui_workflow_must_carry_the_prompt_placeholder(loadouts, encounter, mock_comfy):
    _use_comfy(workflow=json.dumps({"6": {"class_type": "CLIPTextEncode",
                                          "inputs": {"text": "no placeholder"}}}))
    with pytest.raises(ValueError, match="%prompt%"):
        art.generate(encounter, "scene")


def test_comfyui_invalid_workflow_json(loadouts, encounter):
    _use_comfy(workflow="{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        art.generate(encounter, "scene")


def test_comfyui_execution_error_surfaces(loadouts, encounter, monkeypatch):
    _use_comfy()

    class Resp:
        status_code = 200
        text = ""
        def __init__(self, payload):
            self._p = payload
        def json(self):
            return self._p

    monkeypatch.setattr(art.httpx, "post",
                        lambda *a, **k: Resp({"prompt_id": "pid-1"}))
    monkeypatch.setattr(art.httpx, "get", lambda *a, **k: Resp(
        {"pid-1": {"status": {"status_str": "error",
                              "messages": ["CUDA out of memory"]},
                   "outputs": {}}}))
    with pytest.raises(ValueError, match="execution error"):
        art.generate(encounter, "scene")


def test_openrouter_stays_the_default_backend(loadouts, encounter, mock_openrouter):
    _set_key()
    art.generate(encounter, "scene")  # would raise if routed to ComfyUI
    assert mock_openrouter[-1]["model"] == art.ART_MODEL


def test_comfy_settings_roundtrip_through_the_endpoint(loadouts):
    from fastapi.testclient import TestClient
    from ltg_game_server.app import app
    client = TestClient(app)
    r = client.put("/api/llm/settings", json={
        "art_backend": "comfyui", "comfyui_url": "http://gpu-box:8188",
        "comfyui_workflow": COMFY_WORKFLOW})
    assert r.status_code == 200
    got = r.json()
    assert got["art_backend"] == "comfyui"
    assert got["comfyui_url"] == "http://gpu-box:8188"
    assert got["comfyui_workflow"] == COMFY_WORKFLOW
    # An unknown backend is refused; clearing the url with "" sticks.
    assert client.put("/api/llm/settings", json={"art_backend": "dalle"}).status_code == 422
    r = client.put("/api/llm/settings", json={"comfyui_url": ""})
    assert r.json()["comfyui_url"] == ""


# --------------------------------------------------------------------------- #
# Session plumbing: clones share art; snapshots carry it
# --------------------------------------------------------------------------- #
def test_art_base_id_resolves_setup_enemies_and_midgame_spawns():
    """Setup enemies (clones included) resolve through base_of; a mid-game token
    spawn ("husk_3", never in base_of) resolves by stripping the spawn suffix."""
    from ltg_game_server.snapshot import _art_base_id
    art_map = {"base_of": {"wolf": "wolf", "wolf_2": "wolf"}}
    assert _art_base_id("wolf_2", art_map) == "wolf"     # layout clone: mapped
    assert _art_base_id("husk_3", art_map) == "husk"     # spawn: suffix-strip
    assert _art_base_id("husk", art_map) == "husk"       # already a def key

def test_base_of_maps_layout_clones_to_pool_ids():
    pool = {"wolf", "shaman"}
    scaled = [{"id": "wolf"}, {"id": "wolf_2"}, {"id": "wolf_3"}, {"id": "shaman"}]
    assert content._base_of(scaled, pool) == {
        "wolf": "wolf", "wolf_2": "wolf", "wolf_3": "wolf", "shaman": "shaman"}

def test_encounter_art_is_keyed_by_pool_id(loadouts, encounter, mock_openrouter):
    _set_key()
    url = art.generate(encounter, "enemy", "ghoul")["url"]
    scene_url = art.generate(encounter, "scene")["url"]
    assert content.encounter_art(encounter) == {
        "scene": scene_url, "enemies": {"ghoul": url},
        # Art-direction prose rides along for the inspect view ("" when unset).
        "descriptions": {
            "ghoul": "A grey, hunched corpse-eater with too many teeth.",
            "warden": "",
        }}


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def test_put_llm_settings_persists_art_style_through_the_endpoint(loadouts):
    """Regression: the PUT body model must carry art_style — a field missing from
    LlmSettingsBody is silently stripped before llm.save_settings sees it."""
    from fastapi.testclient import TestClient
    from ltg_game_server.app import app
    client = TestClient(app)
    r = client.put("/api/llm/settings", json={"art_style": "Ink sketch."})
    assert r.status_code == 200
    assert r.json()["art_style"] == "Ink sketch."
    assert llm.load_settings()["art_style"] == "Ink sketch."


def test_art_style_settings_roundtrip(loadouts):
    pub = llm.public_settings()
    assert pub["art_style"] == llm.DEFAULT_ART_STYLE
    llm.save_settings({"art_style": "Ink sketch."})
    assert llm.public_settings()["art_style"] == "Ink sketch."
    # None resets to the (upgradeable) default, stored as "".
    llm.save_settings({"art_style": None})
    assert llm.public_settings()["art_style"] == llm.DEFAULT_ART_STYLE
    on_disk = json.loads(llm.SETTINGS_PATH.read_text())
    assert on_disk["art_style"] == ""
