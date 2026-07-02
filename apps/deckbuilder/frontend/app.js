// LTG Deck Builder — minimal vanilla SPA. The backend Pydantic schema is the
// single source of truth; this file only round-trips what the backend validates.

const COLORS = ["W", "U", "B", "R", "G"];
// A spell's speed derives from its timing (matches backend spell_speed).
const SPEED_BY_TIMING = { instant: "reactive", sorcery: "active", channeled: "sustained" };
const derivedSpeed = (timing) => SPEED_BY_TIMING[timing] || "—";
const ARCHETYPE_ORDER = ["Fighter", "Tactician", "Caster", "Channeler"];
let ARCHETYPES = {}; // {Fighter:{starting_hp,…,attacks:{melee:3},default_mode}, …} from backend
let ROWS = ["front", "mid", "rear"];

const blankLoadout = () => ({
  ltg_version: "0.1",
  character: {
    name: "New Character", description: "", portrait: "",
    archetype: "Fighter", level: 1, colors: ["U"], starting_mana: ["U", "U"],
    attack_mode: "melee", row: "front",
  },
  cards: [],
});

let state = blankLoadout();
let validateTimer = null;

const $ = (sel) => document.querySelector(sel);
const api = async (method, path, body) => {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
  return data;
};

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 2500);
}

// --------------------------------------------------------------------------
// Character panel
// --------------------------------------------------------------------------
function manaIcon(c) {
  return `<img class="mana-icon" src="/assets/mana/${c}.svg" alt="${c}" title="${c}" />`;
}

// Render a Scryfall mana cost ("{1}{G}{G}") as small icons + generic-number pips.
function manaCostHtml(manaCost) {
  const tokens = (manaCost || "").match(/\{([^}]+)\}/g) || [];
  if (!tokens.length) return "";
  return `<span class="res-cost">${tokens.map((t) => {
    const sym = t.slice(1, -1);
    return /^[WUBRG]$/.test(sym) ? manaIcon(sym) : `<span class="mc-generic">${escapeHtml(sym)}</span>`;
  }).join("")}</span>`;
}

function makePip(color, on, onClick) {
  const pip = document.createElement("button");
  pip.type = "button";
  pip.className = "pip" + (on ? " on" : "");
  pip.dataset.c = color;
  pip.innerHTML = manaIcon(color);
  pip.onclick = onClick;
  return pip;
}

function renderPortrait() {
  const img = $("#portrait-img");
  const ph = $("#portrait-ph");
  const clear = $("#portrait-clear");
  const src = state.character.portrait || "";
  if (src) {
    img.src = src; img.hidden = false; ph.hidden = true; clear.hidden = false;
  } else {
    img.hidden = true; img.removeAttribute("src"); ph.hidden = false; clear.hidden = true;
  }
}

function manaAmount() {
  return ARCHETYPES[state.character.archetype]?.starting_mana || 2;
}

// The {mode: power} attack profiles the current archetype allows.
function attackOptions() {
  return ARCHETYPES[state.character.archetype]?.attacks || { melee: 0 };
}

// Keep attack_mode valid for the archetype (Fighter is melee-only); default if not.
function reconcileAttackMode() {
  const ch = state.character;
  const opts = attackOptions();
  if (!(ch.attack_mode in opts)) {
    ch.attack_mode = ARCHETYPES[ch.archetype]?.default_mode || Object.keys(opts)[0];
  }
}

// Power is derived from (archetype, attack_mode) — never set directly.
function currentPower() {
  return attackOptions()[state.character.attack_mode];
}

// Keep starting_mana the right length for the archetype and within `colors`.
function reconcileStartingMana() {
  const ch = state.character;
  const colors = ch.colors;
  const amount = manaAmount();
  for (let i = 0; i < ch.starting_mana.length; i++) {
    if (!colors.includes(ch.starting_mana[i])) ch.starting_mana[i] = colors[0];
  }
  while (ch.starting_mana.length < amount) ch.starting_mana.push(colors[0]);
  ch.starting_mana.length = amount;
}

function renderCharacter() {
  const ch = state.character;
  $("#char-name").value = ch.name;
  $("#char-desc").value = ch.description || "";
  $("#char-level").textContent = ch.level || 1;
  renderPortrait();

  // Archetype picker
  const archPick = $("#archetype-pick");
  archPick.innerHTML = "";
  ARCHETYPE_ORDER.forEach((a) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "archetype-btn" + (ch.archetype === a ? " on" : "");
    btn.textContent = a;
    btn.onclick = () => setArchetype(a);
    archPick.appendChild(btn);
  });

  // Derived stat block (read-only) — Power follows the chosen attack profile.
  const stats = ARCHETYPES[ch.archetype];
  $("#stat-block").innerHTML = stats
    ? `<span class="stat"><b>${stats.starting_hp}</b> HP</span>
       <span class="stat"><b>${stats.starting_hand}</b> hand</span>
       <span class="stat"><b>${stats.starting_mana}</b> mana</span>
       <span class="stat"><b>${currentPower()}</b> Power</span>`
    : "";

  // Attack type: one button per profile the archetype offers (mode + Power).
  const attackPick = $("#attack-pick");
  attackPick.innerHTML = "";
  const opts = attackOptions();
  Object.keys(opts).forEach((mode) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "archetype-btn" + (ch.attack_mode === mode ? " on" : "");
    btn.textContent = `${mode} ${opts[mode]}`;
    btn.disabled = Object.keys(opts).length === 1;  // fixed (e.g. Fighter)
    btn.onclick = () => setAttackMode(mode);
    attackPick.appendChild(btn);
  });

  // Default row.
  const rowPick = $("#row-pick");
  rowPick.innerHTML = "";
  ROWS.forEach((r) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "archetype-btn" + (ch.row === r ? " on" : "");
    btn.textContent = r;
    btn.onclick = () => setRow(r);
    rowPick.appendChild(btn);
  });

  // Colours
  const colorPick = $("#color-pick");
  colorPick.innerHTML = "";
  COLORS.forEach((c) => {
    colorPick.appendChild(makePip(c, ch.colors.includes(c), () => toggleColor(c)));
  });

  // Starting mana: amount-many slots, each constrained to the character's colours.
  $("#mana-label").textContent = `Starting mana (${manaAmount()}, from your colours)`;
  const manaPick = $("#mana-pick");
  manaPick.innerHTML = "";
  for (let slot = 0; slot < manaAmount(); slot++) {
    const row = document.createElement("div");
    row.className = "pip-row mana-slot";
    const label = document.createElement("span");
    label.className = "slot-label";
    label.textContent = `Slot ${slot + 1}`;
    row.appendChild(label);
    ch.colors.forEach((c) => {
      row.appendChild(makePip(c, ch.starting_mana[slot] === c, () => setMana(slot, c)));
    });
    manaPick.appendChild(row);
  }
}

function setArchetype(a) {
  state.character.archetype = a;
  reconcileStartingMana();
  reconcileAttackMode();  // archetypes differ in which attack profiles they allow
  renderCharacter();
  scheduleValidate();
}

function setAttackMode(mode) {
  state.character.attack_mode = mode;
  renderCharacter();
  scheduleValidate();
}

function setRow(r) {
  state.character.row = r;
  renderCharacter();
  scheduleValidate();
}

function setMana(slot, c) {
  state.character.starting_mana[slot] = c;
  renderCharacter();
  scheduleValidate();
}

function toggleColor(c) {
  const list = state.character.colors;
  const i = list.indexOf(c);
  if (i >= 0) {
    if (list.length > 1) list.splice(i, 1);
  } else if (list.length < 3) {
    list.push(c);
  } else {
    toast("Colours: pick at most 3");
  }
  reconcileStartingMana();
  renderCharacter();
  scheduleValidate();
}

// --------------------------------------------------------------------------
// Search + add
// --------------------------------------------------------------------------
async function doSearch() {
  const q = $("#search-input").value.trim();
  const ul = $("#search-results");
  ul.innerHTML = "<li class='meta'>Searching…</li>";
  if (!q) { ul.innerHTML = ""; return; }
  try {
    const { matches } = await api("GET", `/api/scryfall/search?q=${encodeURIComponent(q)}`);
    ul.innerHTML = "";
    if (!matches.length) { ul.innerHTML = "<li class='meta'>No matches.</li>"; return; }
    matches.forEach((m) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <span class="res-main">
          <span class="res-name">${escapeHtml(m.name)}</span>
          <span class="meta">${manaCostHtml(m.mana_cost)}${escapeHtml(m.type_line)} · ${m.rarity}</span>
        </span>
        <button class="quick-add" title="Quick add to deck">+</button>`;
      li.querySelector(".res-main").onclick = () => openPreview(m);
      li.querySelector(".quick-add").onclick = (e) => { e.stopPropagation(); addCard(m.name); };
      ul.appendChild(li);
    });
  } catch (e) {
    ul.innerHTML = `<li class='meta'>Error: ${e.message}</li>`;
  }
}

async function addCard(name) {
  try {
    const card = await api("POST", "/api/cards/add", { source_name: name });
    state.cards.push(card);
    renderDeck();
    scheduleValidate();
    await recheckCard(state.cards.length - 1, false); // populate lints on add
    toast(`Added ${card.source_name}${card.needs_translation ? " (needs translation)" : ""}`);
  } catch (e) {
    toast(`Add failed: ${e.message}`);
  }
}

// Preview a search result (full MTG card) before committing it to the deck.
function searchCostString(m) {
  return (m.mana_cost || "").replace(/[{}]/g, "") || "—";
}

function openPreview(m) {
  const el = $("#detail-card");
  el.innerHTML = `
    <h3>${escapeHtml(m.name)}</h3>
    <div class="sub">${escapeHtml(m.type_line)} · ${m.rarity} · ${searchCostString(m)}
      · Level ${Math.round(m.cmc || 0)}</div>

    <div class="block">
      <div class="label">MTG card text</div>
      <div class="readonly-text">${escapeHtml(m.oracle_text) || "(no rules text)"}</div>
    </div>
    <div class="block meta">This is the original MTG card. Adding it runs the LTG
      translation registry and drops it into your deck.</div>

    <div class="detail-actions">
      <button id="preview-cancel">Cancel</button>
      <button class="primary" id="preview-add">Add to deck</button>
    </div>`;
  $("#preview-add").onclick = async () => { closeDetail(); await addCard(m.name); };
  $("#preview-cancel").onclick = closeDetail;
  $("#detail-overlay").classList.remove("hidden");
}

// --------------------------------------------------------------------------
// Deck table
// --------------------------------------------------------------------------
let sortState = { key: null, dir: 1 };

const RARITY_RANK = { common: 0, uncommon: 1, rare: 2, mythic: 3 };

function cardSortValue(card, key) {
  switch (key) {
    case "cost": return card.level;
    case "rarity": return RARITY_RANK[card.rarity] ?? -1;
    case "source_name": return card.source_name.toLowerCase();
    case "type": return card.type.toLowerCase();
    default: return (card.name || "").toLowerCase();
  }
}

function applySort(key) {
  if (sortState.key === key) {
    sortState.dir *= -1;
  } else {
    sortState = { key, dir: 1 };
  }
  state.cards.sort((a, b) => {
    const va = cardSortValue(a, key), vb = cardSortValue(b, key);
    if (va < vb) return -1 * sortState.dir;
    if (va > vb) return 1 * sortState.dir;
    return 0;
  });
  renderDeck();
}

function updateSortIndicators() {
  document.querySelectorAll("#deck-table th.sortable").forEach((th) => {
    const ind = th.querySelector(".sort-ind");
    ind.textContent = th.dataset.sort === sortState.key ? (sortState.dir === 1 ? " ▲" : " ▼") : "";
  });
}

// Mana cost as icons (matches the search-result presentation).
function costIconsHtml(cost) {
  const parts = [];
  if (cost.generic) parts.push(`<span class="mc-generic">${cost.generic}</span>`);
  for (const c of COLORS) {
    const n = (cost.colors && cost.colors[c]) || 0;
    for (let i = 0; i < n; i++) parts.push(manaIcon(c));
  }
  return parts.length ? `<span class="res-cost">${parts.join("")}</span>` : "—";
}

// Card types LTG doesn't accept (mirror of backend FORBIDDEN_TYPES) — for the flag.
const FORBIDDEN_TYPES = ["Land", "Planeswalker", "Creature", "Artifact"];
function forbiddenType(typeLine) {
  const tokens = (typeLine || "").split(/[^A-Za-z]+/);
  return FORBIDDEN_TYPES.find((t) => tokens.includes(t)) || null;
}

// Per-card status for the Status column: validated / needs validating + any issues.
function cardIssues(card) {
  const issues = [];
  issues.push(card.validated
    ? { cls: "good", text: "✓ validated" }
    : { cls: "warn", text: "needs validating" });
  if (card._error) issues.push({ cls: "bad", text: "⛔ invalid" });
  const badType = forbiddenType(card.type);
  if (badType) issues.push({ cls: "bad", text: `⛔ ${badType} type` });
  const identity = new Set(state.character.colors);
  const offColors = Object.keys(card.cost.colors || {}).filter((c) => !identity.has(c));
  if (offColors.length) issues.push({ cls: "bad", text: `⛔ off-colour (${offColors.join("")})` });
  const dupes = state.cards.filter((c) => c.source_name === card.source_name).length;
  if (dupes > 1) issues.push({ cls: "warn", text: "⚠ duplicate" });
  if (card.needs_translation) issues.push({ cls: "flag", text: "⚑ needs translation" });
  if ((card._lints || []).length) issues.push({ cls: "warn", text: `⚠ ${card._lints.length} lint${card._lints.length > 1 ? "s" : ""}` });
  return issues;
}

function renderDeck() {
  $("#deck-count").textContent = state.cards.length;
  const body = $("#deck-body");
  body.innerHTML = "";
  state.cards.forEach((card, idx) => {
    const tr = document.createElement("tr");
    const issues = cardIssues(card);
    const status = issues.map((i) => `<span class="chip ${i.cls}">${i.text}</span>`).join("");
    if (issues.some((i) => i.cls === "bad")) tr.classList.add("row-illegal");
    tr.innerHTML = `
      <td class="deck-name">${escapeHtml(card.name)}</td>
      <td>${card.source_name}</td>
      <td>${costIconsHtml(card.cost)}</td>
      <td>${card.type}</td>
      <td>${card.rarity}</td>
      <td class="deck-status-cell">${status}</td>
      <td><button class="remove-btn" data-idx="${idx}">✕</button></td>`;
    tr.querySelector(".remove-btn").onclick = (e) => { e.stopPropagation(); state.cards.splice(idx, 1); renderDeck(); scheduleValidate(); };
    tr.onclick = () => openCard(idx);
    body.appendChild(tr);
  });
  updateSortIndicators();
}

// --------------------------------------------------------------------------
// Guided effect editor
// --------------------------------------------------------------------------
let EFFECT_SPECS = {};   // { kind: { params:[{name,control,...}] } }
let MODES = ["self", "chosen", "all"];
let SIDES = ["ally", "enemy", "any"];
const MODE_LABEL = { self: "You", chosen: "Choose one", all: "All" };
const SIDE_LABEL = { ally: "Ally", enemy: "Enemy", any: "Either" };

async function loadSpecs() {
  try {
    const r = await api("GET", "/api/effect-specs");
    EFFECT_SPECS = r.specs;
    MODES = r.modes;
    SIDES = r.sides;
  } catch (e) { /* editor falls back to whatever the card already holds */ }
}

async function loadArchetypes() {
  try {
    const resp = await api("GET", "/api/archetypes");
    ARCHETYPES = resp.archetypes || resp;  // tolerate either shape
    if (resp.rows) ROWS = resp.rows;
    reconcileStartingMana();
    reconcileAttackMode();
    renderCharacter();
    scheduleValidate();
  } catch (e) { /* picker falls back to defaults */ }
}

// Mirror of backend describe_target, for slot/link labels.
function describeTargetJS(d) {
  if (typeof d === "string") return d; // "$slot" ref
  if (!d || d.mode === "self") return "you";
  if (d.mode === "all") {
    const n = { ally: "all allies", enemy: "all enemies", any: "everyone" }[d.side];
    return d.exclude_self && d.side !== "enemy" ? "all other " + n.split(" ").slice(1).join(" ") : n;
  }
  const noun = { ally: "ally", enemy: "enemy", any: "target" }[d.side];
  const art = d.exclude_self ? "another" : ("aeiou".includes(noun[0]) ? "an" : "a");
  return `${art} ${noun}${d.targeted ? ", targeted" : ""}`;
}

// Normalize a descriptor so it stays schema-coherent as the user toggles mode.
function normTarget(d) {
  if (d.mode === "self") return { mode: "self" };
  const out = { mode: d.mode, side: d.side || "ally", exclude_self: !!d.exclude_self };
  if (d.mode === "chosen") out.targeted = !!d.targeted;
  return out;
}

const KINDS = () => Object.keys(EFFECT_SPECS).sort();

// A fresh editor row (flat). modal/conditional are bare markers — the rows below
// them supply the grouped effects (see flatten/rebuild). Leaves are full effects.
function newItem(kind) {
  if (kind === "modal") return { kind: "modal", label: "", choose: 1, or_more: false };
  if (kind === "conditional") return { kind: "conditional", condition: { kind: "cast_mode", mode: "reaction" } };
  return defaultEffect(kind);
}

// A fresh leaf effect of `kind`, filled from the spec defaults.
function defaultEffect(kind) {
  const eff = { kind };
  (EFFECT_SPECS[kind]?.params || []).forEach((p) => {
    // An optional number (e.g. token power/hp) defaults to null in the schema for
    // back-compat, but the editor should seed a concrete value so the author sets it.
    const nullishNum = (p.control === "int" || p.control === "float") && p.default === null;
    if ("default" in p && !nullishNum) eff[p.name] = clone(p.default);
    else if (p.control === "bool") eff[p.name] = false;
    else if (p.control === "int" || p.control === "float" || p.control === "value") eff[p.name] = 1;
    else if (p.control === "enum") eff[p.name] = (p.options || [])[0];
    else if (p.control === "target") eff[p.name] = { mode: "chosen", side: "any", targeted: false };
    else if (p.control === "action_target") eff[p.name] = { class: "action", side: "enemy" };
    else if (p.control === "keyword_list") eff[p.name] = (p.required && (p.options || []).length) ? [p.options[0]] : [];
    else eff[p.name] = "";
  });
  return eff;
}

const clone = (x) => (x && typeof x === "object" ? JSON.parse(JSON.stringify(x)) : x);

function slotLabel(name, card) { return `${name} (${describeTargetJS(card.targets[name])})`; }

function nextSlotName(card) {
  let n = 1;
  while (card.targets[`T${n}`] !== undefined) n++;
  return `T${n}`;
}

// --- HTML builders --------------------------------------------------------
// The target descriptor builder: link select + (when direct) mode/side/toggles.
function targetControlHtml(i, current, card, field = "target") {
  const isSlot = typeof current === "string";
  const slots = Object.keys(card.targets);
  const f = `data-i="${i}" data-field="${field}"`;
  const linkOpts = [`<option value="__direct__" ${isSlot ? "" : "selected"}>Build target…</option>`];
  if (slots.length) {
    linkOpts.push(`<optgroup label="Shared slot">`);
    slots.forEach((s) => linkOpts.push(`<option value="$${s}" ${current === "$" + s ? "selected" : ""}>↪ ${slotLabel(s, card)}</option>`));
    linkOpts.push(`</optgroup>`);
  }
  linkOpts.push(`<option value="__new_slot__">＋ New shared slot</option>`);
  const link = `<select class="tgt-link" ${f}>${linkOpts.join("")}</select>`;

  if (isSlot) return `<span class="tgt-builder">${link}<span class="tgt-summary">↪ ${describeTargetJS(current)}</span></span>`;

  const d = current || { mode: "chosen", side: "any" };
  const modeSel = `<select class="tgt-mode" ${f}>${MODES.map((m) => `<option value="${m}" ${d.mode === m ? "selected" : ""}>${MODE_LABEL[m] || m}</option>`).join("")}</select>`;
  const sideSel = d.mode === "self" ? "" :
    `<select class="tgt-side" ${f}>${SIDES.map((s) => `<option value="${s}" ${d.side === s ? "selected" : ""}>${SIDE_LABEL[s] || s}</option>`).join("")}</select>`;
  const exclude = d.mode === "self" ? "" :
    `<label class="inline mini"><input type="checkbox" class="tgt-exclude" ${f} ${d.exclude_self ? "checked" : ""}/> another</label>`;
  const targeted = d.mode === "chosen" ?
    `<label class="inline mini" title="Uses the targeting mechanic — hexproof/shroud apply"><input type="checkbox" class="tgt-targeted" ${f} ${d.targeted ? "checked" : ""}/> targets</label>` : "";
  return `<span class="tgt-builder">${link}${modeSel}${sideSel}${exclude}${targeted}</span>`;
}

function valueControlHtml(i, p, val) {
  let type = "number", num = 1, ref = "";
  if (val === "all") type = "all";
  else if (val && typeof val === "object" && "ref" in val) {
    if (val.ref === "mana_capacity") type = "capacity";
    else { type = "ref"; ref = val.ref; }
  } else num = val;
  return `
    <select class="val-type" data-i="${i}" data-p="${p}">
      <option value="number" ${type === "number" ? "selected" : ""}>number</option>
      <option value="all" ${type === "all" ? "selected" : ""}>all</option>
      <option value="capacity" ${type === "capacity" ? "selected" : ""}>mana capacity</option>
      <option value="ref" ${type === "ref" ? "selected" : ""}>reference</option>
    </select>
    ${type === "number" ? `<input class="val-input" type="number" data-i="${i}" data-p="${p}" value="${num}" />` : ""}
    ${type === "ref" ? `<input class="val-input" type="text" data-i="${i}" data-p="${p}" value="${escapeAttr(ref)}" placeholder="e.g. destroyed_target.level" />` : ""}`;
}

function paramHtml(i, p, val) {
  switch (p.control) {
    case "bool":
      return `<label class="inline"><input type="checkbox" class="eff-param" data-i="${i}" data-p="${p.name}" ${val ? "checked" : ""}/> ${p.name}</label>`;
    case "int":
    case "float":
      return `<label class="inline">${p.name} <input type="number" class="eff-param" data-i="${i}" data-p="${p.name}" step="${p.control === "float" ? "0.1" : "1"}" value="${val ?? 0}" /></label>`;
    case "enum": {
      const none = p.optional ? `<option value="" ${val == null ? "selected" : ""}>(none)</option>` : "";
      return `<label class="inline">${p.name} <select class="eff-param" data-i="${i}" data-p="${p.name}">${none}${(p.options || []).map((o) => `<option ${val === o ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
    }
    case "value":
      return `<label class="inline">${p.name} ${valueControlHtml(i, p.name, val)}</label>`;
    case "keyword_list": {
      const sel = new Set(val || []);
      return `<span class="kw-list"><span class="kw-label">${p.name}</span>${(p.options || []).map((o) =>
        `<label class="inline mini"><input type="checkbox" class="kw-check" data-i="${i}" data-kw="${o}" ${sel.has(o) ? "checked" : ""}/> ${escapeHtml((p.labels && p.labels[o]) || o)}</label>`).join("")}</span>`;
    }
    case "nested": {
      let summary;
      if (p.name === "modes") summary = `${(val || []).length} modes`;
      else if (p.name === "effects") summary = `${(val || []).length} effect(s)`;
      else if (p.name === "condition") summary = val
        ? (val.kind === "cast_mode" ? `cast as ${val.mode}` : `target ${val.property}`) : "—";
      else summary = "—";
      return `<span class="nested-note">${p.name}: ${escapeHtml(summary)} · edit in { } raw JSON</span>`;
    }
    default:
      return `<label class="inline">${p.name} <input type="text" class="eff-param" data-i="${i}" data-p="${p.name}" value="${escapeAttr(val ?? "")}" /></label>`;
  }
}

// --- flat editor model -----------------------------------------------------
// The editor edits a FLAT list of rows; modal/conditional are marker rows that
// scope the effects BELOW them. flatten/rebuild convert to/from the nested schema.
let editorItems = [];

function flattenEffects(effects) {
  const items = [];
  // A conditional flattens to its marker followed by its (leaf) effects; a plain
  // leaf flattens to itself. Used at top level AND inside a modal mode.
  const pushEffect = (e) => {
    if (e.kind === "conditional") {
      items.push({ kind: "conditional", condition: clone(e.condition) });
      (e.effects || []).forEach((inner) => items.push(clone(inner)));
    } else {
      items.push(clone(e));
    }
  };
  for (const e of effects || []) {
    if (e.kind === "modal") {
      // The 'choose' count belongs to the whole modal; replicate it onto every
      // mode-marker so the controls (shown on the first marker) round-trip. A mode
      // may itself hold a conditional, so flatten each mode effect recursively.
      for (const m of e.modes || []) {
        items.push({ kind: "modal", label: m.label || "",
                     choose: e.choose ?? 1, or_more: e.or_more ?? false });
        (m.effects || []).forEach(pushEffect);
      }
    } else {
      pushEffect(e);
    }
  }
  return items;
}

function rebuildEffects(items) {
  const out = [];
  let modal = null, mode = null, cond = null;
  for (const it of items) {
    if (it.kind === "modal") {
      cond = null;  // a new mode starts; close any open conditional
      mode = { label: it.label || "", effects: [] };
      if (modal) { modal.modes.push(mode); }
      else {
        // First marker of the group carries the modal's choose count.
        modal = { kind: "modal", modes: [mode],
                  choose: it.choose ?? 1, or_more: it.or_more ?? false };
        out.push(modal);
      }
    } else if (it.kind === "conditional") {
      cond = { kind: "conditional", condition: clone(it.condition), effects: [] };
      // Nest the conditional inside the open modal mode (modal > conditional >
      // effect); only a conditional with no modal above it sits at top level.
      if (mode) mode.effects.push(cond);
      else out.push(cond);
    } else {
      const dest = cond ? cond.effects : (mode ? mode.effects : out);
      dest.push(clone(it));
    }
  }
  return out;
}

function commitEffects(idx, rerender) {
  state.cards[idx].effects = rebuildEffects(editorItems);
  recheckCard(idx, rerender);
}

// The inline condition builder for a conditional marker row.
function conditionControlHtml(i, cond) {
  cond = cond || { kind: "cast_mode", mode: "reaction" };
  const kindSel = `<select class="cond-kind" data-i="${i}">
      <option value="cast_mode" ${cond.kind === "cast_mode" ? "selected" : ""}>cast mode</option>
      <option value="target_property" ${cond.kind === "target_property" ? "selected" : ""}>target property</option>
    </select>`;
  let rest = "";
  if (cond.kind === "cast_mode") {
    rest = `<select class="cond-mode" data-i="${i}">
        <option value="action" ${cond.mode === "action" ? "selected" : ""}>cast as an action</option>
        <option value="reaction" ${cond.mode === "reaction" ? "selected" : ""}>cast as a reaction</option></select>`;
  } else {
    const prop = cond.property || "has_keyword";
    rest = `<select class="cond-prop" data-i="${i}">
        <option value="has_keyword" ${prop === "has_keyword" ? "selected" : ""}>has keyword</option>
        <option value="side" ${prop === "side" ? "selected" : ""}>is on side</option>
        <option value="level" ${prop === "level" ? "selected" : ""}>is level</option></select>`;
    if (prop === "has_keyword") {
      const kwSpec = (EFFECT_SPECS.grant_keyword?.params || []).find((p) => p.name === "keywords") || {};
      const opts = kwSpec.options || [];
      rest += `<select class="cond-keyword" data-i="${i}">${opts.map((o) =>
        `<option value="${o}" ${cond.keyword === o ? "selected" : ""}>${escapeHtml((kwSpec.labels && kwSpec.labels[o]) || o)}</option>`).join("")}</select>`;
    } else if (prop === "level") {
      rest += `<input type="number" class="cond-level" data-i="${i}" min="1" value="${cond.level ?? 1}" />
        <select class="cond-compare" data-i="${i}">
          <option value="exactly" ${cond.compare === "exactly" || !cond.compare ? "selected" : ""}>exactly</option>
          <option value="or_more" ${cond.compare === "or_more" ? "selected" : ""}>or more</option>
          <option value="or_less" ${cond.compare === "or_less" ? "selected" : ""}>or less</option></select>`;
    } else {
      rest += `<select class="cond-side" data-i="${i}">${["ally", "enemy"].map((s) =>
        `<option value="${s}" ${cond.side === s ? "selected" : ""}>${SIDE_LABEL[s] || s}</option>`).join("")}</select>`;
    }
  }
  return `<span class="cond-builder">if ${kindSel} ${rest}</span>`;
}

function effectRowHtml(e, i, card, depth = 0) {
  const indent = depth >= 2 ? " scoped scoped2" : depth === 1 ? " scoped" : "";
  const kindSel = `<select class="eff-kind" data-i="${i}">${KINDS().map((k) => `<option ${k === e.kind ? "selected" : ""}>${k}</option>`).join("")}</select>`;
  const tools = `<span class="effect-tools">
      <button class="eff-up" data-i="${i}" title="Move up">↑</button>
      <button class="eff-down" data-i="${i}" title="Move down">↓</button>
      <button class="eff-remove danger" data-i="${i}" title="Remove">✕</button></span>`;

  if (e.kind === "modal") {
    // The "choose N" count applies to the whole modal — show it on the first
    // mode-marker of the group only.
    const isFirstModal = !editorItems.slice(0, i).some((x) => x.kind === "modal");
    const chooseCtl = isFirstModal ? `
          <label class="inline">choose <input type="number" min="1" class="modal-choose" data-i="${i}" value="${e.choose ?? 1}" /></label>
          <label class="inline mini"><input type="checkbox" class="modal-ormore" data-i="${i}" ${e.or_more ? "checked" : ""}/> or more</label>` : "";
    return `<div class="effect-row marker">
        <div class="effect-head">${kindSel}${tools}</div>
        <div class="effect-params">
          <span class="marker-note">choose option — effects below (until the next block) are this option</span>
          <label class="inline">label <input type="text" class="modal-label" data-i="${i}" value="${escapeAttr(e.label || "")}" placeholder="(optional)"/></label>${chooseCtl}
        </div></div>`;
  }
  if (e.kind === "conditional") {
    return `<div class="effect-row marker${indent}">
        <div class="effect-head">${kindSel}${tools}</div>
        <div class="effect-params">${conditionControlHtml(i, e.condition)}
          <span class="marker-note">applies to the effects below</span></div></div>`;
  }

  const spec = EFFECT_SPECS[e.kind];
  const params = (spec?.params || []).filter((p) =>
    // The level value is meaningless until a level comparator is chosen.
    !(e.kind === "move_card" && p.name === "filter_level" && (e.filter_level_compare ?? "any") === "any")
  ).map((p) => {
    if (p.name === "target" && p.control === "action_target")
      return `<span class="param"><label class="inline">target <span class="tgt-summary">an enemy action${e.filter && e.filter !== "action" ? " · " + e.filter : ""}</span></label></span>`;
    if (p.control === "target") {
      const label = p.name === "other" ? "vs" : p.name;  // fight's 2nd target reads "vs"
      return `<span class="param"><label class="inline">${label}</label> ${targetControlHtml(i, e[p.name], card, p.name)}</span>`;
    }
    return `<span class="param">${paramHtml(i, p, e[p.name])}</span>`;
  }).join("");
  return `
    <div class="effect-row${indent}">
      <div class="effect-head">${kindSel}${tools}</div>
      <div class="effect-params">${params}</div>
    </div>`;
}

// Render the flat editor rows, indenting by nesting depth: a modal mode is depth 1,
// a conditional nested in a mode pushes its effects to depth 2 (modal > conditional
// > effect). A top-level conditional scopes its effects to depth 1.
function renderEffectRows(card) {
  if (!editorItems.length) return "<div class='meta'>No effects yet.</div>";
  let inMode = false, inCond = false;
  return editorItems.map((e, i) => {
    if (e.kind === "modal") { inMode = true; inCond = false; return effectRowHtml(e, i, card, 0); }
    if (e.kind === "conditional") { const d = inMode ? 1 : 0; inCond = true; return effectRowHtml(e, i, card, d); }
    return effectRowHtml(e, i, card, (inMode ? 1 : 0) + (inCond ? 1 : 0));
  }).join("");
}

let currentIdx = null;

// Open a card: flatten its (nested) effects into the flat editor rows, then render.
function openCard(idx) {
  editorItems = flattenEffects(state.cards[idx].effects);
  openDetail(idx);
}

function openDetail(idx) {
  currentIdx = idx;
  const card = state.cards[idx];
  const lints = card._lints || [];
  const slots = Object.keys(card.targets);
  const el = $("#detail-card");

  el.innerHTML = `
    <h3>${escapeHtml(card.name)}</h3>
    <div class="sub">${card.source_name} · ${card.type} · ${card.rarity} · Level ${card.level}</div>

    <div class="block">
      <div class="label">Flavour name — editable</div>
      <input id="detail-name" type="text" value="${escapeAttr(card.name)}" />
      <div class="label" style="margin-top:8px">Flavour — how the effect works "in character" (optional)</div>
      <textarea id="detail-flavor" rows="3" placeholder="Optional in-character description of how this effect works…">${escapeHtml(card.flavor_text || "")}</textarea>
    </div>

    <div class="block">
      <div class="label">Original MTG text (read-only)</div>
      <div class="readonly-text">${escapeHtml(card.original_text) || "—"}</div>
    </div>

    <div class="block">
      <div class="label-row">
        <div class="label">Effects (source of truth)</div>
        <button id="raw-toggle" class="small">{ } raw JSON</button>
      </div>
      <div id="effects-editor">${renderEffectRows(card)}</div>
      <div class="add-row">
        <button id="add-effect" class="small">＋ Effect</button>
        <button id="add-modal" class="small">＋ Modal option</button>
        <button id="add-conditional" class="small">＋ Conditional</button>
      </div>
      ${slots.length ? `<div class="slots">
        <div class="label">Shared target slots (chosen-only)</div>
        ${slots.map((s) => { const d = card.targets[s]; return `<div class="slot-row">
          <span class="slot-name">$${s}</span>
          <select class="slot-side" data-slot="${s}">${SIDES.map((t) => `<option value="${t}" ${d.side === t ? "selected" : ""}>${SIDE_LABEL[t] || t}</option>`).join("")}</select>
          <label class="inline mini"><input type="checkbox" class="slot-exclude" data-slot="${s}" ${d.exclude_self ? "checked" : ""}/> another</label>
          <label class="inline mini"><input type="checkbox" class="slot-targeted" data-slot="${s}" ${d.targeted ? "checked" : ""}/> targets</label>
          <button class="slot-remove danger" data-slot="${s}" title="Remove slot">✕</button>
        </div>`; }).join("")}
      </div>` : ""}
      <div id="raw-json" class="hidden">
        <textarea id="raw-json-text" rows="7" spellcheck="false">${escapeHtml(JSON.stringify({ targets: card.targets, effects: rebuildEffects(editorItems) }, null, 2))}</textarea>
        <button id="raw-apply" class="small">Apply JSON</button>
        <span id="raw-error" class="chip bad" hidden></span>
      </div>
    </div>

    <div class="block">
      <div class="label-row">
        <div class="label">Translated text — ${card.text_override ? "manual override" : "auto-derived from effects"}</div>
        <label class="inline small"><input type="checkbox" id="text-override" ${card.text_override ? "checked" : ""}/> manual override</label>
      </div>
      <textarea id="detail-translated" rows="2" ${card.text_override ? "" : "readonly"}>${escapeHtml(card.translated_text)}</textarea>
    </div>

    ${lints.length ? `<div class="block lints">
      <div class="label">Lints</div>
      ${lints.map((l) => `<div class="lint">⚠ ${escapeHtml(l)}</div>`).join("")}
    </div>` : ""}

    <div class="timing-note">Timing <b>${card.timing}</b> → <b>${derivedSpeed(card.timing)}</b> (derived)</div>

    <div class="block validate-bar">
      <span class="chip ${card.validated ? "good" : "warn"}">${card.validated ? "✓ Validated" : "Not validated"}</span>
      <button id="detail-validate" class="${card.validated ? "" : "primary"}">${card.validated ? "Unmark" : "Mark validated"}</button>
    </div>

    <div class="detail-actions">
      <button class="danger" id="detail-remove">Remove from deck</button>
      <button id="detail-close">Done</button>
    </div>`;

  wireDetail(idx);
  $("#detail-overlay").classList.remove("hidden");
}

function wireDetail(idx) {
  const card = state.cards[idx];

  $("#detail-name").oninput = (e) => { card.name = e.target.value; renderDeck(); };
  $("#detail-flavor").oninput = (e) => { card.flavor_text = e.target.value; };
  $("#detail-validate").onclick = () => toggleValidated(idx);
  $("#detail-remove").onclick = () => { state.cards.splice(idx, 1); closeDetail(); renderDeck(); scheduleValidate(); };
  $("#detail-close").onclick = () => { closeDetail(); renderDeck(); scheduleValidate(); };

  $("#add-effect").onclick = () => { editorItems.push(newItem("deal_damage")); commitEffects(idx, true); };
  $("#add-modal").onclick = () => { editorItems.push(newItem("modal")); commitEffects(idx, true); };
  $("#add-conditional").onclick = () => { editorItems.push(newItem("conditional")); commitEffects(idx, true); };

  $("#text-override").onchange = (e) => { card.text_override = e.target.checked; recheckCard(idx, true); };
  $("#detail-translated").oninput = (e) => { if (card.text_override) card.translated_text = e.target.value; };

  // Effect kind / params / target — all operate on the flat editorItems.
  document.querySelectorAll(".eff-kind").forEach((sel) => {
    sel.onchange = () => { editorItems[+sel.dataset.i] = newItem(sel.value); commitEffects(idx, true); };
  });
  document.querySelectorAll(".eff-param").forEach((inp) => {
    inp.onchange = () => {
      const i = +inp.dataset.i, p = inp.dataset.p;
      const spec = (EFFECT_SPECS[editorItems[i].kind].params || []).find((x) => x.name === p);
      editorItems[i][p] = inp.type === "checkbox" ? inp.checked
        : spec.control === "int" ? (parseInt(inp.value) || 0)
        : spec.control === "float" ? (parseFloat(inp.value) || 0)
        : (spec.control === "enum" && spec.optional && inp.value === "") ? null
        : inp.value;
      commitEffects(idx, p === "trigger" || p === "duration" || p === "filter_level_compare");
    };
  });
  document.querySelectorAll(".kw-check").forEach((cb) => {
    cb.onchange = () => {
      const e = editorItems[+cb.dataset.i], kw = cb.dataset.kw;
      e.keywords = e.keywords || [];
      const at = e.keywords.indexOf(kw);
      if (cb.checked && at < 0) e.keywords.push(kw);
      if (!cb.checked && at >= 0) e.keywords.splice(at, 1);
      commitEffects(idx, false);
    };
  });
  document.querySelectorAll(".val-type").forEach((sel) => {
    sel.onchange = () => {
      const i = +sel.dataset.i, p = sel.dataset.p;
      editorItems[i][p] = sel.value === "all" ? "all"
        : sel.value === "capacity" ? { ref: "mana_capacity" }
        : sel.value === "ref" ? { ref: "" } : 1;
      commitEffects(idx, true);
    };
  });
  document.querySelectorAll(".val-input").forEach((inp) => {
    inp.onchange = () => {
      const i = +inp.dataset.i, p = inp.dataset.p;
      editorItems[i][p] = inp.type === "number" ? (parseInt(inp.value) || 0) : { ref: inp.value };
      commitEffects(idx, false);
    };
  });
  // Target descriptor builder
  document.querySelectorAll(".tgt-link").forEach((sel) => { sel.onchange = () => onTargetLink(idx, +sel.dataset.i, sel.value, sel.dataset.field || "target"); });
  document.querySelectorAll(".tgt-mode").forEach((sel) => { sel.onchange = () => { const e = editorItems[+sel.dataset.i], f = sel.dataset.field || "target"; e[f] = normTarget({ ...e[f], mode: sel.value }); commitEffects(idx, true); }; });
  document.querySelectorAll(".tgt-side").forEach((sel) => { sel.onchange = () => { const e = editorItems[+sel.dataset.i], f = sel.dataset.field || "target"; e[f] = normTarget({ ...e[f], side: sel.value }); commitEffects(idx, true); }; });
  document.querySelectorAll(".tgt-exclude").forEach((cb) => { cb.onchange = () => { const e = editorItems[+cb.dataset.i], f = cb.dataset.field || "target"; e[f] = normTarget({ ...e[f], exclude_self: cb.checked }); commitEffects(idx, true); }; });
  document.querySelectorAll(".tgt-targeted").forEach((cb) => { cb.onchange = () => { const e = editorItems[+cb.dataset.i], f = cb.dataset.field || "target"; e[f] = normTarget({ ...e[f], targeted: cb.checked }); commitEffects(idx, true); }; });

  // Modal label + conditional condition builder
  document.querySelectorAll(".modal-label").forEach((inp) => { inp.onchange = () => { editorItems[+inp.dataset.i].label = inp.value; commitEffects(idx, false); }; });
  document.querySelectorAll(".modal-choose").forEach((inp) => { inp.onchange = () => { editorItems[+inp.dataset.i].choose = parseInt(inp.value) || 1; commitEffects(idx, true); }; });
  document.querySelectorAll(".modal-ormore").forEach((cb) => { cb.onchange = () => { editorItems[+cb.dataset.i].or_more = cb.checked; commitEffects(idx, true); }; });
  document.querySelectorAll(".cond-kind").forEach((sel) => {
    sel.onchange = () => {
      editorItems[+sel.dataset.i].condition = sel.value === "cast_mode"
        ? { kind: "cast_mode", mode: "reaction" }
        : { kind: "target_property", property: "has_keyword", keyword: "flying" };
      commitEffects(idx, true);
    };
  });
  document.querySelectorAll(".cond-mode").forEach((sel) => { sel.onchange = () => { editorItems[+sel.dataset.i].condition.mode = sel.value; commitEffects(idx, true); }; });
  document.querySelectorAll(".cond-prop").forEach((sel) => {
    sel.onchange = () => {
      const byProp = {
        has_keyword: { kind: "target_property", property: "has_keyword", keyword: "flying" },
        side: { kind: "target_property", property: "side", side: "enemy" },
        level: { kind: "target_property", property: "level", level: 1, compare: "exactly" },
      };
      editorItems[+sel.dataset.i].condition = byProp[sel.value] || byProp.has_keyword;
      commitEffects(idx, true);
    };
  });
  document.querySelectorAll(".cond-keyword").forEach((sel) => { sel.onchange = () => { editorItems[+sel.dataset.i].condition.keyword = sel.value; commitEffects(idx, true); }; });
  document.querySelectorAll(".cond-side").forEach((sel) => { sel.onchange = () => { editorItems[+sel.dataset.i].condition.side = sel.value; commitEffects(idx, true); }; });
  document.querySelectorAll(".cond-level").forEach((inp) => { inp.onchange = () => { editorItems[+inp.dataset.i].condition.level = parseInt(inp.value) || 1; commitEffects(idx, true); }; });
  document.querySelectorAll(".cond-compare").forEach((sel) => { sel.onchange = () => { editorItems[+sel.dataset.i].condition.compare = sel.value; commitEffects(idx, true); }; });

  document.querySelectorAll(".eff-up").forEach((b) => b.onclick = () => moveItem(idx, +b.dataset.i, -1));
  document.querySelectorAll(".eff-down").forEach((b) => b.onclick = () => moveItem(idx, +b.dataset.i, 1));
  document.querySelectorAll(".eff-remove").forEach((b) => b.onclick = () => { editorItems.splice(+b.dataset.i, 1); commitEffects(idx, true); });

  // Slots (chosen-only descriptors) — card-level
  document.querySelectorAll(".slot-side").forEach((sel) => {
    sel.onchange = () => { card.targets[sel.dataset.slot] = normTarget({ ...card.targets[sel.dataset.slot], side: sel.value }); recheckCard(idx, true); };
  });
  document.querySelectorAll(".slot-exclude").forEach((cb) => {
    cb.onchange = () => { card.targets[cb.dataset.slot] = normTarget({ ...card.targets[cb.dataset.slot], exclude_self: cb.checked }); recheckCard(idx, true); };
  });
  document.querySelectorAll(".slot-targeted").forEach((cb) => {
    cb.onchange = () => { card.targets[cb.dataset.slot] = normTarget({ ...card.targets[cb.dataset.slot], targeted: cb.checked }); recheckCard(idx, true); };
  });
  document.querySelectorAll(".slot-remove").forEach((b) => {
    b.onclick = () => {
      const s = b.dataset.slot;
      // Re-materialize the descriptor into every field that linked this slot (a
      // fight links two: target + other).
      editorItems.forEach((e) => ["target", "other"].forEach((f) => {
        if (e[f] === "$" + s) e[f] = clone(card.targets[s]);
      }));
      delete card.targets[s];
      commitEffects(idx, true);
    };
  });

  // Raw JSON escape hatch
  $("#raw-toggle").onclick = () => $("#raw-json").classList.toggle("hidden");
  $("#raw-apply").onclick = () => applyRawJson(idx);
}

// The link dropdown: build inline, link to an existing slot, or make a new one.
function onTargetLink(idx, i, value, field = "target") {
  const card = state.cards[idx];
  const e = editorItems[i];
  if (value === "__direct__") {
    // unlink: materialize the current descriptor (copy the slot's, or default)
    e[field] = typeof e[field] === "string"
      ? clone(card.targets[e[field].slice(1)]) || { mode: "chosen", side: "any" }
      : e[field];
  } else if (value === "__new_slot__") {
    const name = nextSlotName(card);
    const cur = e[field];
    const seed = (cur && typeof cur === "object" && cur.mode === "chosen") ? normTarget(cur) : { mode: "chosen", side: "ally", exclude_self: false, targeted: false };
    card.targets[name] = seed;
    e[field] = "$" + name;
  } else {
    e[field] = value; // "$T1"
  }
  commitEffects(idx, true);
}

function moveItem(idx, i, dir) {
  const j = i + dir;
  if (j < 0 || j >= editorItems.length) return;
  [editorItems[i], editorItems[j]] = [editorItems[j], editorItems[i]];
  commitEffects(idx, true);
}

function applyRawJson(idx) {
  const card = state.cards[idx];
  const errEl = $("#raw-error");
  try {
    const parsed = JSON.parse($("#raw-json-text").value);
    card.effects = parsed.effects || [];
    card.targets = parsed.targets || {};
    editorItems = flattenEffects(card.effects); // re-sync the flat editor
    errEl.hidden = true;
    recheckCard(idx, true);
  } catch (e) {
    errEl.textContent = "Invalid JSON: " + e.message;
    errEl.hidden = false;
  }
}

// Re-validate a card after an edit: un-ratify, re-derive text, refresh lints.
async function recheckCard(idx, rerender) {
  const card = state.cards[idx];
  card.validated = false;
  try {
    const res = await api("POST", "/api/cards/validate", { card });
    if (res.valid) {
      // Mutate in place so wired handlers (which close over this object) stay
      // valid across non-rerender edits; replacing the object would orphan them.
      Object.keys(card).forEach((k) => { if (!k.startsWith("_")) delete card[k]; });
      Object.assign(card, res.card);
      card._lints = res.lints;
      card._error = null;
    } else {
      card._error = res.errors.join("; ");
      card._lints = card._lints || [];
      toast("Invalid: " + res.errors[0]);
    }
  } catch (e) {
    toast("Validation error: " + e.message);
  }
  renderDeck();
  scheduleValidate();
  if (rerender) openDetail(idx);
  else {
    // light update: refresh derived text only (params edited in place)
    const c = state.cards[idx];
    const ta = $("#detail-translated");
    if (ta && !c.text_override) ta.value = c.translated_text;
  }
}

// Ratify / un-ratify the card's effects.
function toggleValidated(idx) {
  const card = state.cards[idx];
  if (card.validated) {
    card.validated = false;
  } else {
    if ((card._error || "").length) { toast("Fix structural errors first."); return; }
    card.validated = true;
    card.needs_translation = false;
  }
  renderDeck();
  scheduleValidate();
  openDetail(idx);
}

function closeDetail() { currentIdx = null; $("#detail-overlay").classList.add("hidden"); }

// --------------------------------------------------------------------------
// Deck status (live, non-blocking)
// --------------------------------------------------------------------------
function scheduleValidate() {
  clearTimeout(validateTimer);
  validateTimer = setTimeout(refreshStatus, 250);
}

async function refreshStatus() {
  const body = $("#status-body");
  try {
    const { valid, errors, status } = await api("POST", "/api/loadout/validate", { loadout: state });
    if (!valid) {
      body.innerHTML = `<div class="warn">Loadout invalid:</div>` +
        errors.map((e) => `<div class="warn">• ${escapeHtml(e)}</div>`).join("");
      return;
    }
    body.innerHTML = renderStatus(status);
  } catch (e) {
    body.innerHTML = `<div class="warn">Status error: ${escapeHtml(e.message)}</div>`;
  }
}

function renderStatus(s) {
  const sizePct = Math.min(100, (s.size.count / s.size.limit) * 100);
  const sizeOver = s.size.count > s.size.limit;
  let html = "";
  html += `<div>Cards <strong>${s.size.count} / ${s.size.limit}</strong>
    <div class="bar"><span class="${sizeOver ? "over" : ""}" style="width:${sizePct}%"></span></div></div>`;
  html += `<div>Rarity: ` + ["mythic", "rare", "uncommon", "common"].map((r) => {
    const { count, limit } = s.rarity[r];
    const cls = count > limit ? "warn" : "";
    return `<span class="${cls}">${r} ${count}/${limit}</span>`;
  }).join(" · ") + `</div>`;
  html += `<div class="${s.duplicates.length ? "warn" : "ok"}">Singleton: ${
    s.duplicates.length ? "dupes — " + s.duplicates.join(", ") : "ok"}</div>`;
  html += `<div class="${s.off_color.length ? "warn" : "ok"}">Off-colour: ${
    s.off_color.length ? s.off_color.join(", ") : "none"}</div>`;
  html += `<div class="${s.untranslated ? "warn" : "ok"}">Untranslated: ${s.untranslated}</div>`;
  if (s.starting_mana_outside_identity.length) {
    html += `<div class="warn">Starting mana outside identity: ${s.starting_mana_outside_identity.join(", ")}</div>`;
  }
  return html;
}

// --------------------------------------------------------------------------
// Top bar: new / load / save / import deck list / export engine loadout
// --------------------------------------------------------------------------
let currentFileHandle = null;   // File System Access handle for the open savegame
let currentFileName = null;
const HAS_FS = typeof window.showOpenFilePicker === "function";
const JSON_TYPES = [{ description: "LTG loadout", accept: { "application/json": [".json"] } }];

function syncCharacterFromInputs() {
  state.character.name = $("#char-name").value;
  state.character.description = $("#char-desc").value;
}

function defaultFileName(suffix = "") {
  const base = (state.character.name || "loadout").replace(/[^a-z0-9]+/gi, "_").toLowerCase();
  return `${base}${suffix}.json`;
}

function applyLoadedText(text, handle, name) {
  let data;
  try { data = JSON.parse(text); } catch (e) { toast("Load failed: invalid JSON"); return; }
  state = data;
  if (!state.character.row) state.character.row = "front";  // older loadouts
  currentFileHandle = handle || null;
  currentFileName = name || null;
  reconcileStartingMana();
  reconcileAttackMode();
  renderAll();
  toast(`Loaded ${name || "loadout"}`);
}

// Load — a real file picker; remembers the handle so Save can overwrite it.
async function loadLoadout() {
  if (HAS_FS) {
    let handle;
    try { [handle] = await window.showOpenFilePicker({ types: JSON_TYPES, multiple: false }); }
    catch (e) { return; } // user cancelled
    const file = await handle.getFile();
    applyLoadedText(await file.text(), handle, file.name);
  } else {
    $("#file-load").click(); // fallback: <input type=file>
  }
}

async function writeHandle(handle, text) {
  const w = await handle.createWritable();
  await w.write(text);
  await w.close();
}

// Save — overwrite the open file, else prompt for a location (Save As).
async function saveLoadout() {
  syncCharacterFromInputs();
  const text = JSON.stringify(state, null, 2);
  if (currentFileHandle) {
    try { await writeHandle(currentFileHandle, text); toast(`Saved ${currentFileName || ""}`.trim()); }
    catch (e) { toast(`Save failed: ${e.message}`); }
    return;
  }
  if (HAS_FS) {
    let handle;
    try { handle = await window.showSaveFilePicker({ suggestedName: defaultFileName(), types: JSON_TYPES }); }
    catch (e) { return; } // user cancelled
    try {
      await writeHandle(handle, text);
      currentFileHandle = handle;
      currentFileName = handle.name;
      toast(`Saved ${handle.name}`);
    } catch (e) { toast(`Save failed: ${e.message}`); }
  } else {
    downloadText(text, defaultFileName()); // fallback: download
    toast("Saved (downloaded)");
  }
}

function downloadText(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// --- Deck-list import ------------------------------------------------------
function openImport() {
  $("#import-text").value = "";
  $("#import-status").textContent = "";
  $("#import-overlay").classList.remove("hidden");
  $("#import-text").focus();
}
function closeImport() { $("#import-overlay").classList.add("hidden"); }

// "1 Akroma's Will (CMR) 3" -> "Akroma's Will" (drop qty, set code, collector #).
function parseDeckList(text) {
  return text.split(/\r?\n/).map((line) => {
    let s = line.trim();
    if (!s || s.startsWith("//") || s.startsWith("#")) return null;
    if (/^(deck|sideboard|commander|maybeboard)\b/i.test(s)) return null; // section headers
    s = s.replace(/^\s*\d+\s*x?\s+/i, "");          // leading quantity ("1 ", "2x ")
    // Moxfield/Archidekt/Goldfish glue export metadata onto the end in varying
    // order: "(SET) 123", foil markers "*F*"/"*E*", category tags "[...]"/"<...>".
    // Strip trailing metadata tokens repeatedly until the name is clean.
    let prev;
    do {
      prev = s;
      s = s.replace(/\s*\*[^*]*\*\s*$/, "");                 // *F*, *E* foil/etch markers
      s = s.replace(/\s*\[[^\]]*\]\s*$/, "");                // [Maybeboard], [Foil] tags
      s = s.replace(/\s*<[^>]*>\s*$/, "");                   // <tag>
      s = s.replace(/\s*\([^)]*\)\s*[\w-]*\s*$/i, "");      // (SET) 123 / (PLST) MH1-48
    } while (s !== prev);
    return s.trim();
  }).filter(Boolean);
}

async function doImport() {
  const names = parseDeckList($("#import-text").value);
  if (!names.length) { $("#import-status").textContent = "No card names found."; return; }
  $("#import-status").textContent = `Importing ${names.length} card(s)…`;
  $("#import-go").disabled = true;
  try {
    const res = await api("POST", "/api/cards/import", { names });
    res.cards.forEach(({ card, lints }) => state.cards.push({ ...card, _lints: lints }));
    renderDeck();
    scheduleValidate();
    closeImport();
    const nf = res.not_found.length;
    toast(`Imported ${res.cards.length} card(s)${nf ? ` — ${nf} not found` : ""}.`);
    if (nf) console.warn("Not found on import:", res.not_found);
  } catch (e) {
    $("#import-status").textContent = `Import failed: ${e.message}`;
  } finally {
    $("#import-go").disabled = false;
  }
}

// Export an engine-ready loadout: only structurally-valid, validated cards.
async function exportEngineLoadout() {
  syncCharacterFromInputs();
  try {
    const res = await api("POST", "/api/loadout/export", { loadout: state });
    if (res.exported_count === 0) {
      const reasons = res.omitted.map((o) => `• ${o.name}: ${o.reason}`).join("\n");
      alert(`Nothing exported — no validated cards.\n\nOmitted:\n${reasons || "(deck is empty)"}`);
      return;
    }
    const blob = new Blob([JSON.stringify(res.engine_loadout, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(state.character.name || "loadout").replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.engine.json`;
    a.click();
    URL.revokeObjectURL(url);
    if (res.omitted.length) {
      toast(`Exported ${res.exported_count}; omitted ${res.omitted.length} unvalidated.`);
      console.warn("Omitted from engine export:", res.omitted);
    } else {
      toast(`Exported ${res.exported_count} validated card(s).`);
    }
  } catch (e) {
    toast(`Export failed: ${e.message}`);
  }
}

// --------------------------------------------------------------------------
// Helpers + wiring
// --------------------------------------------------------------------------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

function renderAll() {
  renderCharacter();
  renderDeck();
  refreshStatus();
}

function init() {
  $("#btn-new").onclick = () => { if (confirm("Discard current loadout and start new?")) { state = blankLoadout(); currentFileHandle = null; currentFileName = null; renderAll(); } };
  $("#btn-load").onclick = loadLoadout;
  $("#btn-import").onclick = openImport;
  $("#btn-save").onclick = saveLoadout;
  $("#btn-export-engine").onclick = exportEngineLoadout;
  $("#btn-search").onclick = doSearch;
  $("#search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("#char-name").oninput = () => { state.character.name = $("#char-name").value; scheduleValidate(); };
  $("#char-desc").oninput = () => { state.character.description = $("#char-desc").value; };
  $("#file-load").onchange = (e) => {
    const file = e.target.files[0];
    if (file) file.text().then((t) => applyLoadedText(t, null, file.name));
    e.target.value = "";
  };
  $("#import-cancel").onclick = closeImport;
  $("#import-go").onclick = doImport;
  $("#import-overlay").onclick = (e) => { if (e.target.id === "import-overlay") closeImport(); };
  $("#portrait").onclick = (e) => { if (e.target.id !== "portrait-clear") $("#portrait-file").click(); };
  $("#portrait-clear").onclick = (e) => { e.stopPropagation(); state.character.portrait = ""; renderPortrait(); };
  $("#portrait-file").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { state.character.portrait = reader.result; renderPortrait(); };
    reader.readAsDataURL(file);
    e.target.value = "";
  };
  $("#detail-overlay").onclick = (e) => { if (e.target.id === "detail-overlay") { closeDetail(); renderDeck(); } };
  document.querySelectorAll("#deck-table th.sortable").forEach((th) => {
    th.onclick = () => applySort(th.dataset.sort);
  });
  loadSpecs();
  loadArchetypes();
  renderAll();
}

init();
