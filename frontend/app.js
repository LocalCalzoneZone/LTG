// LTG Deck Builder — minimal vanilla SPA. The backend Pydantic schema is the
// single source of truth; this file only round-trips what the backend validates.

const COLORS = ["W", "U", "B", "R", "G"];

const blankLoadout = () => ({
  ltg_version: "0.1",
  character: { name: "New Character", description: "", colors: ["U"], starting_mana: ["U", "B"] },
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
function renderCharacter() {
  $("#char-name").value = state.character.name;
  $("#char-desc").value = state.character.description || "";

  const colorPick = $("#color-pick");
  colorPick.innerHTML = "";
  COLORS.forEach((c) => {
    const pip = document.createElement("div");
    pip.className = "pip" + (state.character.colors.includes(c) ? " on" : "");
    pip.dataset.c = c;
    pip.textContent = c;
    pip.onclick = () => toggleColor(c);
    colorPick.appendChild(pip);
  });

  const manaPick = $("#mana-pick");
  manaPick.innerHTML = "";
  COLORS.forEach((c) => {
    const pip = document.createElement("div");
    pip.className = "pip" + (state.character.starting_mana.includes(c) ? " on" : "");
    pip.dataset.c = c;
    pip.textContent = c;
    pip.onclick = () => toggleMana(c);
    manaPick.appendChild(pip);
  });
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
  renderCharacter();
  scheduleValidate();
}

function toggleMana(c) {
  const list = state.character.starting_mana;
  const i = list.indexOf(c);
  if (i >= 0) {
    list.splice(i, 1);
  } else if (list.length < 2) {
    list.push(c);
  } else {
    list.shift(); // keep the two most recent
    list.push(c);
  }
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
      li.innerHTML = `<span>${m.name}</span><span class="meta">${m.type_line} · ${m.rarity}</span>`;
      li.onclick = () => addCard(m.name);
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
    toast(`Added ${card.source_name}${card.needs_translation ? " (needs translation)" : ""}`);
  } catch (e) {
    toast(`Add failed: ${e.message}`);
  }
}

// --------------------------------------------------------------------------
// Deck table
// --------------------------------------------------------------------------
function costString(cost) {
  const parts = [];
  if (cost.generic) parts.push(String(cost.generic));
  for (const c of COLORS) {
    const n = (cost.colors && cost.colors[c]) || 0;
    for (let i = 0; i < n; i++) parts.push(c);
  }
  return parts.join("") || "—";
}

function renderDeck() {
  $("#deck-count").textContent = state.cards.length;
  const body = $("#deck-body");
  body.innerHTML = "";
  state.cards.forEach((card, idx) => {
    const tr = document.createElement("tr");
    const nameInput = `<input type="text" value="${escapeAttr(card.name)}" data-idx="${idx}" class="name-edit" />`;
    tr.innerHTML = `
      <td>${nameInput}${card.needs_translation ? " <span class='flag'>⚑ needs translation</span>" : ""}</td>
      <td>${card.source_name}</td>
      <td>${costString(card.cost)}</td>
      <td>${card.type}</td>
      <td>${card.rarity}</td>
      <td><button class="remove-btn" data-idx="${idx}">✕</button></td>`;
    tr.querySelector(".name-edit").onclick = (e) => e.stopPropagation();
    tr.querySelector(".name-edit").oninput = (e) => { state.cards[idx].name = e.target.value; scheduleValidate(); };
    tr.querySelector(".remove-btn").onclick = (e) => { e.stopPropagation(); state.cards.splice(idx, 1); renderDeck(); scheduleValidate(); };
    tr.onclick = () => openDetail(idx);
    body.appendChild(tr);
  });
}

// --------------------------------------------------------------------------
// Card detail
// --------------------------------------------------------------------------
function openDetail(idx) {
  const card = state.cards[idx];
  const el = $("#detail-card");
  const effectsHtml = card.effects.length
    ? card.effects.map((e) => `<div>${escapeHtml(JSON.stringify(e))}</div>`).join("")
    : "<div class='meta'>(no structured effects)</div>";
  el.innerHTML = `
    <h3>${escapeHtml(card.name)}</h3>
    <div class="sub">${card.source_name} · ${card.type} · ${card.rarity} · Level ${card.level}
      ${card.needs_translation ? "· <span class='flag'>⚑ needs translation</span>" : ""}</div>

    <div class="block">
      <div class="label">Original MTG text (read-only)</div>
      <div class="readonly-text">${escapeHtml(card.original_text) || "—"}</div>
    </div>

    <div class="block">
      <div class="label">Translated (LTG) text — editable</div>
      <textarea id="detail-translated" rows="3">${escapeHtml(card.translated_text)}</textarea>
    </div>

    <div class="block">
      <div class="label">Flavour name — editable</div>
      <input id="detail-name" type="text" value="${escapeAttr(card.name)}" />
    </div>

    <div class="block">
      <div class="label">Structured effects (read-only)</div>
      <div class="effects">${effectsHtml}</div>
    </div>

    <label><input type="checkbox" id="detail-reactive" ${card.reactive ? "checked" : ""} /> reactive</label>

    <div class="detail-actions">
      <button class="danger" id="detail-remove">Remove from deck</button>
      <button class="primary" id="detail-close">Done</button>
    </div>`;

  $("#detail-translated").oninput = (e) => { card.translated_text = e.target.value; };
  $("#detail-name").oninput = (e) => { card.name = e.target.value; };
  $("#detail-reactive").onchange = (e) => { card.reactive = e.target.checked; };
  $("#detail-remove").onclick = () => { state.cards.splice(idx, 1); closeDetail(); renderDeck(); scheduleValidate(); };
  $("#detail-close").onclick = () => { closeDetail(); renderDeck(); scheduleValidate(); };
  $("#detail-overlay").classList.remove("hidden");
}

function closeDetail() { $("#detail-overlay").classList.add("hidden"); }

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
// Top bar: new / load / save / export / import
// --------------------------------------------------------------------------
function syncCharacterFromInputs() {
  state.character.name = $("#char-name").value;
  state.character.description = $("#char-desc").value;
}

async function saveLoadout() {
  syncCharacterFromInputs();
  try {
    const { saved } = await api("POST", "/api/loadout/save", { loadout: state });
    toast(`Saved as "${saved}"`);
  } catch (e) {
    toast(`Save failed: ${e.message}`);
  }
}

async function loadDialog() {
  let names = [];
  try { names = (await api("GET", "/api/loadouts")).loadouts; } catch (e) { /* ignore */ }
  const choice = prompt(
    `Load a saved loadout by name, or click Cancel then "Load" again to import a file.\n\nSaved: ${
      names.length ? names.join(", ") : "(none)"}`,
    names[0] || ""
  );
  if (choice === null) { $("#file-import").click(); return; }
  if (!choice.trim()) return;
  try {
    state = await api("GET", `/api/loadout/${encodeURIComponent(choice.trim())}`);
    renderAll();
    toast(`Loaded "${choice.trim()}"`);
  } catch (e) {
    toast(`Load failed: ${e.message}`);
  }
}

function exportJson() {
  syncCharacterFromInputs();
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(state.character.name || "loadout").replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function importFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      state = JSON.parse(reader.result);
      renderAll();
      toast("Imported from file");
    } catch (e) {
      toast("Import failed: invalid JSON");
    }
  };
  reader.readAsText(file);
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
  $("#btn-new").onclick = () => { if (confirm("Discard current loadout and start new?")) { state = blankLoadout(); renderAll(); } };
  $("#btn-load").onclick = loadDialog;
  $("#btn-save").onclick = saveLoadout;
  $("#btn-export").onclick = exportJson;
  $("#btn-search").onclick = doSearch;
  $("#search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("#char-name").oninput = () => { state.character.name = $("#char-name").value; scheduleValidate(); };
  $("#char-desc").oninput = () => { state.character.description = $("#char-desc").value; };
  $("#file-import").onchange = (e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = ""; };
  $("#detail-overlay").onclick = (e) => { if (e.target.id === "detail-overlay") { closeDetail(); renderDeck(); } };
  renderAll();
}

init();
