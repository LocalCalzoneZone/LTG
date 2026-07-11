/* The cockpit front end — a thin client over the engine.
 *
 * It renders the state the backend reports and the menu it built from the
 * engine's legal_actions, collects a click, and posts the chosen action's index
 * back. It computes NO legality, targets, costs, damage, or turn order — every
 * such value comes from the engine. Rewriting this file changes no outcome. */

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const COLOR_NAME = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colorless" };

let STATE = null;          // last /api/state payload
let SETUP_OPEN = true;     // setup panel visible until a fight starts
let _bootstrapped = false; // first load: jump straight to a live fight if one exists

async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
  return data;
}

async function refresh() {
  STATE = await api("/api/state");
  if (!_bootstrapped) { _bootstrapped = true; if (STATE.loaded) SETUP_OPEN = false; }
  render();
}

/* ----------------------------------------------------------------- setup -- */
function renderSetup() {
  const slots = $("#slots");
  slots.innerHTML = "";
  const summaries = (STATE && STATE.slots) || [null, null, null, null];
  summaries.forEach((s, i) => {
    const box = el("div", "slot" + (s ? " filled" : ""));
    const row = el("div");
    const label = el("span", null, `Slot ${i + 1}: `);
    const input = el("input"); input.type = "file"; input.accept = ".json";
    input.onchange = () => loadCharacter(i, input.files[0]);
    row.append(label, input);
    box.append(row);
    if (s) {
      const sum = el("div", "slot-summary");
      sum.innerHTML = `<b>${s.name}</b> — ${s.archetype} · HP ${s.hp} · Power ${s.power}
        · hand ${s.hand_size} · mana [${s.identity.join(", ")}] · ${s.card_count} cards`;
      const clear = el("button", "ghost", "remove");
      clear.onclick = () => api("/api/clear/character", { slot: i, loadout: {} }).then(refresh);
      sum.append(" ", clear);
      box.append(sum);
    }
    slots.append(box);
  });

  const sn = STATE && STATE.scenario_name;
  $("#scenario-status").textContent = sn ? `Scenario: ${sn}` : "No scenario loaded.";
  $("#determinism").textContent = (STATE && STATE.determinism) || "";
  renderQuickSetup();
}

async function loadCharacter(slot, file) {
  if (!file) return;
  try {
    const loadout = JSON.parse(await file.text());
    await api("/api/load/character", { slot, loadout });
    await refresh();
  } catch (e) { setupError(`Slot ${slot + 1}: ${e.message}`); }
}

async function loadScenarioFile(file) {
  if (!file) return;
  try {
    const scenario = JSON.parse(await file.text());
    await api("/api/load/scenario", { scenario });
    await refresh();
  } catch (e) { setupError(`Scenario: ${e.message}`); }
}

function setupError(msg) { $("#setup-error").textContent = msg; }

function renderQuickSetup() {
  const box = $("#quick-setup");
  box.innerHTML = "";
  if (!STATE || !STATE.loaded) { box.textContent = "Start a fight, then tweak values here."; return; }
  const ov = STATE.overrides || {};
  const note = el("p", "muted", "Tweak starting values, then Apply (rebuilds the fight from turn 1).");
  box.append(note);

  STATE.party.forEach((c) => {
    const pov = (ov.party && ov.party[c.id]) || {};
    const row = el("div", "qs-row");
    row.append(el("label", null, c.name));
    const hp = numInput(`qs-${c.id}-hp`, pov.hp ?? c.max_hp);
    const pw = numInput(`qs-${c.id}-power`, pov.power ?? c.base_power);
    const mana = el("input"); mana.id = `qs-${c.id}-mana`; mana.style.width = "120px";
    mana.value = (pov.mana || c.mana.flatMap((m) => Array(m.capacity).fill(m.color))).join(",");
    row.append(span("HP"), hp, span("Power"), pw, span("mana"), mana);
    box.append(row);
  });
  STATE.enemies.forEach((e) => {
    const eov = (ov.enemies && ov.enemies[e.id]) || {};
    const row = el("div", "qs-row");
    row.append(el("label", null, e.name));
    const hp = numInput(`qs-${e.id}-hp`, eov.hp ?? e.max_hp);
    const amt = numInput(`qs-${e.id}-amt`, eov.intent_amount ?? (e.intent && e.intent.amount) ?? "");
    row.append(span("HP"), hp, span("intent dmg"), amt);
    box.append(row);
  });

  const apply = el("button", "primary", "Apply & restart");
  apply.onclick = applyOverrides;
  box.append(apply);
}
function span(t) { return el("span", "muted", t); }
function numInput(id, val) { const i = el("input"); i.type = "number"; i.id = id; i.value = val; return i; }

async function applyOverrides() {
  const overrides = { party: {}, enemies: {} };
  STATE.party.forEach((c) => {
    overrides.party[c.id] = {
      hp: numVal(`qs-${c.id}-hp`),
      power: numVal(`qs-${c.id}-power`),
      mana: $(`#qs-${c.id}-mana`).value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
    };
  });
  STATE.enemies.forEach((e) => {
    overrides.enemies[e.id] = { hp: numVal(`qs-${e.id}-hp`), intent_amount: numVal(`qs-${e.id}-amt`) };
  });
  try { STATE = await api("/api/overrides", { overrides }); SETUP_OPEN = false; render(); }
  catch (err) { setupError(err.message); }
}
function numVal(id) { const v = $(`#${id}`).value; return v === "" ? null : Number(v); }

/* --------------------------------------------------------------- the board */
function render() {
  if (!STATE) return;
  $("#setup").classList.toggle("hidden", !(SETUP_OPEN || !STATE.loaded));
  const showBoard = STATE.loaded && !SETUP_OPEN;
  $("#board").classList.toggle("hidden", !showBoard);
  $("#logpanel").classList.toggle("hidden", !showBoard);
  renderSetup();
  if (!showBoard) { $("#turnline").textContent = ""; $("#history-meta").textContent = "—"; return; }

  $("#turnline").textContent = `Turn ${STATE.turn} · ${STATE.phase_label}`
    + (STATE.acting_id ? ` · deciding: ${nameOf(STATE.acting_id)}` : "");
  const h = STATE.history;
  $("#history-meta").textContent = `state ${h.index + 1}/${h.length}`;
  $("#btn-back").disabled = !h.can_back;
  $("#btn-forward").disabled = !h.can_forward;

  renderEnemies();
  renderParty();
  renderActive();
  renderStack();
  renderLog();
  renderBanner();
}

function nameOf(id) {
  const all = [...STATE.party, ...STATE.enemies, ...STATE.tokens];
  const m = all.find((x) => x.id === id);
  return m ? m.name : id;
}

function hpbar(cur, max, isEnemy) {
  const bar = el("div", "hpbar");
  const fill = el("span"); fill.style.width = Math.max(0, Math.min(100, (cur / max) * 100)) + "%";
  bar.append(fill);
  const lbl = el("div", "hp-label", `HP ${cur}/${max}`);
  const wrap = el("div"); wrap.append(bar, lbl);
  return wrap;
}

function renderEnemies() {
  const lane = $("#enemies"); lane.innerHTML = "";
  if (!STATE.enemies.length) { lane.append(el("div", "muted", "(no enemies remaining)")); return; }
  STATE.enemies.forEach((e) => {
    const box = el("div", "card-unit enemy" + (e.alive ? "" : " dead") + (e.in_hand ? " bounced" : ""));
    box.onclick = () => inspect(`Enemy — ${e.name}`, e.raw);
    const head = el("div", "unit-head");
    const sub = e.in_hand ? "in hand" : `Lv${e.level} · ${e.row}`;
    head.append(el("span", "unit-name", e.name), el("span", "unit-sub", sub));
    box.append(head, hpbar(e.hp, e.max_hp, true));

    const intent = el("div", "intent" + (e.intent ? "" : " none"));
    if (e.in_hand) {
      intent.textContent = "bounced — redeploys next turn";
    } else if (e.intent) {
      const dmg = e.intent.amount != null ? ` (${e.intent.amount})` : "";
      intent.textContent = `▶ ${e.intent.name}${dmg} → ${e.intent.target_name || "—"}`;
    } else {
      intent.textContent = "no intent declared";
    }
    box.append(intent);
    if (e.intent2) {  // boss fury (§D9-4): the second declared intent
      const dmg2 = e.intent2.amount != null ? ` (${e.intent2.amount})` : "";
      box.append(el("div", "intent",
        `▶▶ ${e.intent2.name}${dmg2} → ${e.intent2.target_name || "—"}`));
    }

    const tags = el("div", "tags");
    if (e.in_hand) tags.append(el("span", "tag disabled", "bounced"));
    tags.append(el("span", "tag", e.attack_mode));
    if (e.stunned) tags.append(el("span", "tag disabled", `stunned ×${e.stunned}`));
    if (e.temp_mod) tags.append(el("span", "tag", `${e.temp_mod > 0 ? "+" : ""}${e.temp_mod} temp HP`));
    if (e.power_bonus) tags.append(el("span", "tag", `${e.power_bonus > 0 ? "+" : ""}${e.power_bonus} Power`));
    if (e.prevent_pool) tags.append(el("span", "tag", `reduce ${e.prevent_pool}`));
    if (e.protection) tags.append(el("span", "tag", `protection ×${e.protection}`));
    (e.keywords || []).forEach((k) => tags.append(el("span", "tag", `⚜ ${k}`)));
    if (e.rises) tags.append(el("span", "tag", `rises ×${e.rises}`));
    if (tags.children.length) box.append(tags);
    lane.append(box);
  });

  // Corpses (§D9-1): the dead stay on the battlefield — dim markers, raw on click.
  (STATE.corpses || []).forEach((c) => {
    const box = el("div", "card-unit enemy dead");
    box.onclick = () => inspect(`Corpse — ${c.name}`, c);
    const head = el("div", "unit-head");
    const sub = c.stirring > 0 ? `stirring ×${c.stirring} · ${c.row}` : `corpse · ${c.row}`;
    head.append(el("span", "unit-name", `✝ ${c.name}`), el("span", "unit-sub", sub));
    box.append(head);
    if (c.stirring > 0) {
      box.append(el("div", "intent", `▶ rises in ${c.stirring} Upkeep(s) — exile or raise it`));
    }
    lane.append(box);
  });
}

// Position readout (Update 02 §M-B): current row, plus the committed row (⊕) when it
// differs and a queued voluntary move (→) when one is pending.
function posLabel(c) {
  const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
  let s = cap(c.row);
  if (c.committed && c.committed !== c.row) s += ` ⊕${cap(c.committed)}`;
  if (c.pending_voluntary) s += ` →${cap(c.pending_voluntary)}`;
  return s;
}

function renderParty() {
  const lane = $("#party"); lane.innerHTML = "";
  STATE.party.forEach((c) => {
    const box = el("div", "card-unit" + (c.id === STATE.acting_id ? " acting" : "") + (c.alive ? "" : " dead"));
    box.onclick = (ev) => { if (ev.target.dataset.stop) return; openKit(c); };

    const head = el("div", "unit-head");
    const left = el("span", "unit-name", (c.id === STATE.acting_id ? "▶ " : "") + c.name);
    const sub = el("span", "unit-sub", `${c.archetype} · ${posLabel(c)}`);
    sub.title = "Position — current row (what intents/the wall hit). ⊕ = committed row "
              + "(reach/Mitigate adjacency). → = a queued move that resolves at End step.";
    head.append(left, sub);
    box.append(head, hpbar(c.hp, c.max_hp, false));

    box.append(manaRow(c));

    const tags = el("div", "tags");
    c.status_tags.forEach((t) => tags.append(el("span", "tag", t)));
    c.channels.forEach((ch) => {
      const tag = el("span", "tag channel", `⛓ ${ch.card_name} ${ch.reserved_pips}`);
      tag.dataset.stop = "1";
      tag.title = (ch.target_name ? `on ${ch.target_name} — ` : "") + (ch.text || "");
      tag.onclick = (e) => { e.stopPropagation(); inspect(`Channel — ${ch.card_name}`, ch); };
      tags.append(tag);
    });
    if (tags.children.length) box.append(tags);

    const inspectBtn = el("button", "ghost", "raw"); inspectBtn.dataset.stop = "1";
    inspectBtn.style.marginTop = "6px";
    inspectBtn.onclick = (e) => { e.stopPropagation(); inspect(`Character — ${c.name}`, c.raw); };
    box.append(inspectBtn);
    lane.append(box);
  });

  STATE.tokens.forEach((t) => {
    const box = el("div", "card-unit");
    box.onclick = () => inspect(`Token — ${t.name}`, t.raw);
    const head = el("div", "unit-head");
    head.append(el("span", "unit-name", `⊹ ${t.name}`), el("span", "unit-sub", `Power ${t.power} · ${t.row}`));
    box.append(head, hpbar(t.hp, t.max_hp, false));
    if (t.control_kind) {  // a controlled combatant (§D9-1.4)
      const left = t.control_left != null ? ` ×${t.control_left}` : "";
      const tags = el("div", "tags");
      tags.append(el("span", "tag channel", `${t.control_kind}${left}`));
      box.append(tags);
    }
    lane.append(box);
  });
}

function manaRow(c) {
  const row = el("div", "mana");
  if (!c.mana.length) { row.append(el("span", "muted", "(no mana)")); return row; }
  c.mana.forEach((m) => {
    const m_ = el("span", "m");
    const sw = el("span", "swatch"); sw.style.background = `var(--${m.color})`;
    m_.append(sw, document.createTextNode(`${m.color} ${m.available}/${m.capacity}`));
    if (m.reserved) m_.append(el("span", "reserved-note", ` (${m.reserved} reserved)`));
    row.append(m_);
  });
  return row;
}

function renderActive() {
  const who = STATE.acting_id ? STATE.party.find((c) => c.id === STATE.acting_id) : null;
  $("#active-who").textContent = who ? `— ${who.name}${STATE.in_window ? " (reaction window)" : ""}` : "— (no decision)";
  const hand = $("#active-hand"); hand.innerHTML = "";
  if (who) who.hand.forEach((card) => hand.append(handCard(card)));
  if (who && !who.hand.length) hand.append(el("div", "muted", "(empty hand)"));

  const menu = $("#menu"); menu.innerHTML = "";
  if (STATE.result) { menu.append(el("div", "muted", "Game over.")); return; }
  if (!STATE.menu || !STATE.menu.length) { menu.append(el("div", "muted", "(no legal actions — auto-advancing)")); return; }
  STATE.menu.forEach((entry) => menu.append(menuEntry(entry)));
}

function handCard(card) {
  const c = el("div", "handcard");
  const head = el("div", "hc-head");
  head.append(el("span", "hc-name", card.name), el("span", "hc-cost", card.cost));
  c.append(head);
  if (card.text) c.append(el("div", "hc-text", card.text));
  c.append(el("div", "hc-meta", `${card.timing} · ${card.rarity} · L${card.level}`));
  return c;
}

// One target node: a leaf (carries `index` → posts the action) or an inner node
// (carries its own `targets` → expands to the next target's choices). Recursion
// gives the stepwise picker for independent multi-target cards (pick target 1,
// then target 2, …). All nodes come from the engine — the UI never guesses them.
function targetNode(node) {
  if (node.targets) {
    const wrap = el("div", "menu-entry");
    const b = el("button", null, node.label);
    const kids = el("div", "targets hidden");
    node.targets.forEach((c) => kids.append(targetNode(c)));
    b.onclick = () => kids.classList.toggle("hidden");
    wrap.append(b, kids);
    return wrap;
  }
  const tb = el("button", null, node.label);
  tb.onclick = () => act(node.index);
  return tb;
}

function menuEntry(entry) {
  const wrap = el("div", "menu-entry");
  if (entry.kind === "prompt" || (entry.index == null && !entry.targets)) {
    // A non-clickable header — e.g. "Choose a card to move (N more)".
    wrap.append(el("div", "menu-prompt muted", entry.label));
    return wrap;
  }
  if (entry.index != null && !entry.targets) {
    const b = el("button", "act", entry.label);
    b.onclick = () => act(entry.index);
    wrap.append(b);
    return wrap;
  }
  // Submenu: click reveals legal targets (two-click flow, nested for multi-target).
  const b = el("button", "act", entry.label);
  const targets = el("div", "targets hidden");
  entry.targets.forEach((t) => targets.append(targetNode(t)));
  b.onclick = () => targets.classList.toggle("hidden");
  wrap.append(b, targets);
  return wrap;
}

async function act(index) {
  try { STATE = await api("/api/action", { index }); render(); }
  catch (e) { setupError(e.message); }
}

function renderStack() {
  const stack = $("#stack"); stack.innerHTML = "";
  STATE.stack.forEach((item) => {
    const box = el("div", "stack-item" + (item.top ? " top" : ""));
    box.onclick = () => inspect(`Stack — ${item.label}`, item.raw);
    box.append(el("div", null, (item.top ? "● " : "") + item.label));
    const sub = `by ${item.source_name || "?"}${item.target_name ? " → " + item.target_name : ""} · ${item.kind}`;
    box.append(el("div", "si-sub", sub));
    stack.append(box);
  });
}

function renderLog() {
  const log = $("#log"); log.innerHTML = "";
  const filter = $("#log-filter").value.toLowerCase();
  STATE.log.forEach((e) => {
    if (filter && !(`${e.type} ${e.msg}`.toLowerCase().includes(filter))) return;
    const ev = el("div", "ev");
    ev.append(el("span", "ty", e.type));
    ev.append(document.createTextNode(e.msg));
    log.append(ev);
  });
  log.scrollTop = log.scrollHeight;
}

function renderBanner() {
  const b = $("#banner");
  if (!STATE.result) { b.classList.add("hidden"); return; }
  b.classList.remove("hidden");
  b.classList.toggle("defeat", STATE.result === "defeat");
  b.textContent = STATE.result === "victory" ? "★ VICTORY — the party wins" : "✖ DEFEAT — the party falls";
}

/* ----------------------------------------------------------- inspector/kit */
function inspect(title, obj) {
  $("#inspector-title").textContent = title;
  $("#inspector-body").textContent = JSON.stringify(obj, null, 2);
  $("#inspector").classList.remove("hidden");
}

function openKit(c) {
  $("#kit-title").textContent = `${c.name} — ${c.archetype} · kit`;
  const body = $("#kit-body"); body.innerHTML = "";

  const ev = el("div", "kit-section");
  ev.append(el("h3", null, "Evergreen abilities"));
  const grid = el("div", "evergreen");
  [["Offensive", c.evergreen.offensive], ["Defensive — action", c.evergreen.defensive_action],
   ["Defensive — reaction", c.evergreen.defensive_reaction]].forEach(([role, ab]) => {
    const card = el("div", "handcard");
    card.append(el("div", "hc-head", null));
    card.firstChild.append(el("span", "hc-name", ab.name));
    card.append(el("div", "hc-meta", role));
    card.append(el("div", "hc-text", ab.text));
    grid.append(card);
  });
  ev.append(grid);
  body.append(ev);

  const all = [...c.hand, ...c.library];
  const sec = el("div", "kit-section");
  sec.append(el("h3", null, `Card list (${all.length}) — hand + library`));
  const cards = el("div", "kit-cards");
  all.forEach((card) => cards.append(handCard(card)));
  sec.append(cards);
  body.append(sec);

  $("#kit").classList.remove("hidden");
}

/* ----------------------------------------------------------------- wiring */
$("#scenario-file").onchange = (e) => loadScenarioFile(e.target.files[0]);
document.querySelectorAll("[data-builtin]").forEach((b) => {
  b.onclick = () => api(`/api/scenario/builtin/${b.dataset.builtin}`, {}).then(refresh);
});
$("#btn-start").onclick = async () => {
  try { STATE = await api("/api/start", { overrides: {} }); SETUP_OPEN = false; render(); }
  catch (e) { setupError(e.message); }
};
$("#btn-setup").onclick = () => { SETUP_OPEN = !SETUP_OPEN; render(); };
$("#btn-back").onclick = () => api("/api/step", { delta: -1 }).then((d) => { STATE = d; render(); });
$("#btn-forward").onclick = () => api("/api/step", { delta: 1 }).then((d) => { STATE = d; render(); });
$("#inspector-close").onclick = () => $("#inspector").classList.add("hidden");
$("#kit-close").onclick = () => $("#kit").classList.add("hidden");
$("#kit").onclick = (e) => { if (e.target.id === "kit") $("#kit").classList.add("hidden"); };
$("#log-filter").oninput = () => renderLog();

refresh();
