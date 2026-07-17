/* LTG Autoplay Tester — the lab UI. Four views over the /api surface:
   Roster (loadouts + verdict chips), Test Bench (compose a probe), Queue
   (live jobs), Verdicts (the report reader). Static, no build step. */

"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const api = async (method, path, body) => {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* raw */ }
    throw new Error(msg);
  }
  return res.json();
};

let TOAST_T = null;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  clearTimeout(TOAST_T);
  TOAST_T = setTimeout(() => { el.className = ""; }, 3500);
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---- state ---------------------------------------------------------------- */
const state = {
  roster: [], gauntlets: [], baseline: null, jobs: [], verdicts: [],
  bench: { kind: "card", character_id: null, card_id: null,
           gauntlet_id: null, preset: "quick", party: [] },
  openVerdict: null,
};

/* ---- navigation ------------------------------------------------------------ */
const VIEWS = ["roster", "bench", "queue", "verdicts"];
function show(view) {
  VIEWS.forEach((v) => {
    $(`#view-${v}`).classList.toggle("active", v === view);
  });
  document.querySelectorAll(".navbtn").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  location.hash = view;
  render(view);
}
$("#nav").addEventListener("click", (e) => {
  const b = e.target.closest(".navbtn");
  if (b) show(b.dataset.view);
});

/* ---- shared bits ------------------------------------------------------------ */
const pips = (colors) =>
  (colors || []).map((c) => `<span class="pip ${esc(c)}"></span>`).join("");

function flagChip(v) {
  if (!v) return `<span class="chip dim">never probed</span>`;
  const cls = { OVER: "blood", UNDER: "tide", IN_BAND: "vigor", FLAGS: "blood",
                NOT_EXERCISED: "aether" }[v.flag] || "dim";
  let out = `<span class="chip ${cls}">${esc(v.flag.replace("_", " "))}</span>`;
  if (v.combo_blind) out += `<span class="chip brass">combo-blind</span>`;
  if (v.screening_only) out += `<span class="chip dim">screening</span>`;
  if (v.stale) out += `<span class="chip blood">stale</span>`;
  return out;
}

const deltaSpan = (pp) => {
  const cls = pp > 0.05 ? "delta-pos" : pp < -0.05 ? "delta-neg" : "delta-zero";
  return `<span class="${cls}">${pp >= 0 ? "+" : ""}${Number(pp).toFixed(1)} pp</span>`;
};

/* ---- roster ----------------------------------------------------------------- */
async function loadRoster() {
  state.roster = (await api("GET", "/api/roster")).characters;
}

function renderRoster() {
  const el = $("#view-roster");
  if (!state.roster.length) {
    el.innerHTML = `<div class="panel"><div class="empty">No loadouts found —
      the Tester reads the same registry as the game (Deckbuilder loadouts +
      bundled examples).</div></div>`;
    return;
  }
  const rows = state.roster.map((c) => `
    <tr>
      <td><b>${esc(c.name)}</b><br><span class="dim">${esc(c.archetype)} · level ${c.level}</span></td>
      <td>${pips(c.colors)}</td>
      <td>${c.card_count} cards${c.has_skill ? ` · skill: ${esc(c.skill_name)}` : ""}${c.has_ultimate ? ` · ult: ${esc(c.ultimate_name)}` : ""}</td>
      <td>${flagChip(c.last_verdict)}</td>
      <td style="white-space:nowrap">
        <button class="btn small" data-act="probe-char" data-id="${esc(c.id)}">Probe character</button>
        <button class="btn small quiet" data-act="probe-card" data-id="${esc(c.id)}">Probe a card</button>
        ${c.has_skill ? `<button class="btn small quiet" data-act="probe-skill" data-id="${esc(c.id)}">Skill</button>` : ""}
        ${c.has_ultimate ? `<button class="btn small quiet" data-act="probe-ult" data-id="${esc(c.id)}">Ultimate</button>` : ""}
        <button class="btn small quiet" data-act="edit" data-id="${esc(c.id)}">Edit in Deckbuilder</button>
      </td>
    </tr>`).join("");
  el.innerHTML = `
    <div class="panel">
      <div class="panel-title">Roster — every loadout the registry sees</div>
      <table>
        <tr><th>Character</th><th>Colours</th><th>Kit</th><th>Last verdict</th><th></th></tr>
        ${rows}
      </table>
    </div>`;
  el.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const id = b.dataset.id;
    const kindMap = { "probe-char": "character", "probe-card": "card",
                      "probe-skill": "skill", "probe-ult": "ultimate" };
    if (b.dataset.act === "edit") {
      try {
        const { url } = await api("GET", `/api/deckbuilder-url/${id}`);
        window.open(url, "_blank");
        toast("Opened the Deckbuilder edit flow — the roster re-reads on your return.");
      } catch (err) { toast(err.message, true); }
      return;
    }
    state.bench.kind = kindMap[b.dataset.act];
    state.bench.character_id = id;
    state.bench.card_id = null;
    show("bench");
  };
}

/* ---- bench -------------------------------------------------------------------- */
async function loadGauntlets() {
  const d = await api("GET", "/api/gauntlets");
  state.gauntlets = d.gauntlets;
  state.baseline = d.baseline;
  if (!state.bench.gauntlet_id) state.bench.gauntlet_id = d.baseline;
}

function renderBench() {
  const el = $("#view-bench");
  const b = state.bench;
  if (!b.character_id && state.roster.length) b.character_id = state.roster[0].id;
  const chr = state.roster.find((c) => c.id === b.character_id);
  if (b.kind === "card" && chr && !b.card_id && chr.cards.length)
    b.card_id = chr.cards[0].id;

  const kindOpts = [
    ["card", "Card", "one card vs the filler, plus the lever ladder"],
    ["skill", "Skill", "with vs without the once-per-encounter Skill"],
    ["ultimate", "Ultimate", "with vs without, plus the dependence read"],
    ["character", "Character", "roster percentile, attribution, spend audit"],
    ["enemy_schema", "Enemy schema", "attribute results to the generation rules"],
  ];
  const gOpts = state.gauntlets.map((g) =>
    `<option value="${esc(g.id)}" ${g.id === b.gauntlet_id ? "selected" : ""}>
       ${esc(g.name)} — ${g.encounters} encounters${g.generated ? " (generated)" : ""}</option>`).join("");
  const charOpts = state.roster.map((c) =>
    `<option value="${esc(c.id)}" ${c.id === b.character_id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  const cardOpts = chr ? chr.cards.map((c) =>
    `<option value="${esc(c.id)}" ${c.id === b.card_id ? "selected" : ""}>
       ${esc(c.name)} (${esc(c.timing)}, ${esc(c.rarity)})</option>`).join("") : "";
  const partyChecks = state.roster.map((c) =>
    `<label style="display:inline-block;margin-right:14px;font-size:12px">
       <input type="checkbox" data-party="${esc(c.id)}"
         ${b.party.includes(c.id) ? "checked" : ""}/> ${esc(c.name)}</label>`).join("");

  el.innerHTML = `
    <div class="panel">
      <div class="panel-title">Compose a probe</div>
      <label class="field">Subject</label>
      <div class="radio-row" id="kind-row">
        ${kindOpts.map(([k, t, d]) => `
          <div class="opt ${b.kind === k ? "on" : ""}" data-kind="${k}">
            <span class="caps">${t}</span><span class="dim">${d}</span>
          </div>`).join("")}
      </div>
      <div class="row">
        ${b.kind === "enemy_schema" ? `
          <div><label class="field">Party (the measuring side)</label>${partyChecks || '<span class="dim">no loadouts</span>'}</div>
        ` : `
          <div><label class="field">Character</label>
            <select id="b-char">${charOpts}</select></div>
          ${b.kind === "card" ? `<div><label class="field">Card</label>
            <select id="b-card">${cardOpts}</select></div>` : ""}
        `}
        <div><label class="field">Gauntlet</label>
          <select id="b-gauntlet">${gOpts}</select></div>
      </div>
      <label class="field">Preset</label>
      <div class="radio-row" id="preset-row">
        <div class="opt ${b.preset === "quick" ? "on" : ""}" data-preset="quick">
          <span class="caps">Quick</span><span class="dim">the screening read — minutes, marked "screening only"</span>
        </div>
        <div class="opt ${b.preset === "thorough" ? "on" : ""}" data-preset="thorough">
          <span class="caps">Thorough</span><span class="dim">the act-on-able verdict — adds the full deck sweep</span>
        </div>
      </div>
      <div style="margin-top:16px;display:flex;align-items:center;gap:16px">
        <button class="btn" id="b-launch">Launch probe</button>
        <span class="dim" id="b-estimate">…</span>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">Mint a generated gauntlet</div>
      <div class="row">
        <div><label class="field">Name</label><input type="text" id="g-name" placeholder="e.g. fresh-set-jul" /></div>
        <div><label class="field">Encounters</label><input type="number" id="g-count" value="4" min="1" max="8" /></div>
        <div><label class="field">Difficulty</label>
          <select id="g-diff"><option>standard</option><option>easy</option><option>hard</option></select></div>
      </div>
      <label class="field">Note to the designer model (optional)</label>
      <input type="text" id="g-note" placeholder="a theme, a mechanic to stress…" />
      <div style="margin-top:12px;display:flex;gap:14px;align-items:center">
        <button class="btn" id="g-mint">Mint gauntlet</button>
        <span class="dim">Uses the game's LLM settings (Options → LLM). Generated sets stay
        quarantined from the game's picker; promote keepers from the gauntlet list.</span>
      </div>
      <div id="g-list" style="margin-top:14px"></div>
    </div>`;

  // wiring
  $("#kind-row").onclick = (e) => {
    const o = e.target.closest(".opt");
    if (o) { b.kind = o.dataset.kind; renderBench(); }
  };
  $("#preset-row").onclick = (e) => {
    const o = e.target.closest(".opt");
    if (o) { b.preset = o.dataset.preset; renderBench(); }
  };
  const sel = (id, fn) => { const n = $(id); if (n) n.onchange = fn; };
  sel("#b-char", (e) => { b.character_id = e.target.value; b.card_id = null; renderBench(); });
  sel("#b-card", (e) => { b.card_id = e.target.value; updateEstimate(); });
  sel("#b-gauntlet", (e) => { b.gauntlet_id = e.target.value; updateEstimate(); });
  el.querySelectorAll("[data-party]").forEach((n) => {
    n.onchange = () => {
      b.party = Array.from(el.querySelectorAll("[data-party]:checked"))
        .map((x) => x.dataset.party);
    };
  });
  $("#b-launch").onclick = launchProbe;
  $("#g-mint").onclick = mintGauntlet;
  renderGauntletList();
  updateEstimate();
}

function probeBody() {
  const b = state.bench;
  return {
    kind: b.kind, gauntlet_id: b.gauntlet_id, preset: b.preset,
    character_id: b.kind === "enemy_schema" ? null : b.character_id,
    card_id: b.kind === "card" ? b.card_id : null,
    character_ids: b.kind === "enemy_schema"
      ? (b.party.length ? b.party : state.roster.slice(0, 1).map((c) => c.id))
      : null,
  };
}

async function updateEstimate() {
  const est = $("#b-estimate");
  if (!est) return;
  try {
    const d = await api("POST", "/api/probes/estimate", probeBody());
    est.textContent = `≈ ${d.games.toLocaleString()} games · ~${d.est_minutes} min on the pool`;
  } catch (e) { est.textContent = ""; }
}

async function launchProbe() {
  try {
    const job = await api("POST", "/api/probes", probeBody());
    toast(`Probe queued — ${job.title}`);
    show("queue");
  } catch (e) { toast(e.message, true); }
}

async function mintGauntlet() {
  const name = $("#g-name").value.trim();
  if (!name) { toast("Name the gauntlet first.", true); return; }
  const party = state.bench.party.length
    ? state.bench.party : state.roster.slice(0, 2).map((c) => c.id);
  try {
    await api("POST", "/api/gauntlets/generate", {
      name, character_ids: party,
      count: parseInt($("#g-count").value, 10) || 4,
      difficulty: $("#g-diff").value, note: $("#g-note").value.trim(),
    });
    toast("Minting queued — watch the Queue view (LLM calls take a while).");
    show("queue");
  } catch (e) { toast(e.message, true); }
}

async function renderGauntletList() {
  const el = $("#g-list");
  if (!el) return;
  const rows = await Promise.all(state.gauntlets.map(async (g) => {
    let detail = null;
    try { detail = await api("GET", `/api/gauntlets/${g.id}`); } catch (e) { /* skip */ }
    const encs = detail ? detail.encounters.map((e) => `
      <tr><td class="dim">${esc(e.name)}${e.objective ? ` <span class="chip brass">${esc(e.objective)}</span>` : ""}</td>
      <td class="dim">${esc((e.enemies || []).join(", "))}</td>
      <td style="text-align:right">${g.generated ? `<button class="btn small quiet" data-promote="${esc(g.id)}::${esc(e.file)}">Promote to game</button>` : ""}</td></tr>`).join("") : "";
    return `
      <div style="margin-bottom:10px">
        <span class="caps" style="font-size:11px;color:var(--brass)">${esc(g.name)}</span>
        <span class="dim" style="font-size:11px"> · hash ${esc(g.hash)} · ${g.frozen ? "frozen" : "mutable"}${g.generated ? " · generated (quarantined)" : ""}</span>
        <table style="margin-top:4px">${encs}</table>
      </div>`;
  }));
  el.innerHTML = rows.join("");
  el.onclick = async (e) => {
    const b = e.target.closest("[data-promote]");
    if (!b) return;
    const [gid, file] = b.dataset.promote.split("::");
    try {
      const meta = await api("POST", `/api/gauntlets/${gid}/promote`, { encounter_file: file });
      toast(`Promoted into the game as "${meta.name}".`);
    } catch (err) { toast(err.message, true); }
  };
}

/* ---- queue ---------------------------------------------------------------------- */
async function loadJobs() {
  state.jobs = (await api("GET", "/api/probes")).jobs;
  const busy = state.jobs.filter((j) => j.status === "running" || j.status === "queued");
  $("#queue-pulse").innerHTML = busy.length
    ? `<span class="busy">${busy.length} job(s) running</span>` : "";
}

function renderQueue() {
  const el = $("#view-queue");
  if (!state.jobs.length) {
    el.innerHTML = `<div class="panel"><div class="empty">No jobs yet — compose one on the Test Bench.</div></div>`;
    return;
  }
  const rows = state.jobs.map((j) => {
    const p = j.progress || { done: 0, total: 0, label: "" };
    const pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
    const status = {
      queued: `<span class="chip dim">queued</span>`,
      running: `<span class="chip brass">running</span>`,
      done: `<span class="chip vigor">done</span>`,
      failed: `<span class="chip blood">failed</span>`,
      cancelled: `<span class="chip dim">cancelled</span>`,
      interrupted: `<span class="chip blood">interrupted</span>`,
    }[j.status] || esc(j.status);
    return `
      <tr>
        <td><b>${esc(j.title)}</b><br><span class="dim">${esc(j.id)} · ${esc(j.created)}</span>
          ${j.error ? `<br><span class="delta-pos">${esc(j.error)}</span>` : ""}</td>
        <td style="width:110px">${status}</td>
        <td style="width:260px">
          ${j.status === "running" ? `
            <span class="dim">${p.done.toLocaleString()} / ${p.total.toLocaleString()} · ${esc(p.label)}</span>
            <div class="bar"><i style="width:${pct}%"></i></div>` : ""}
        </td>
        <td style="width:180px;text-align:right">
          ${j.status === "running" || j.status === "queued"
            ? `<button class="btn small danger" data-cancel="${esc(j.id)}">Cancel</button>` : ""}
          ${j.verdict_id
            ? `<button class="btn small" data-verdict="${esc(j.verdict_id)}">Open verdict</button>` : ""}
        </td>
      </tr>`;
  }).join("");
  el.innerHTML = `
    <div class="panel">
      <div class="panel-title">Queue — probes run in the background and survive restarts</div>
      <table><tr><th>Job</th><th>Status</th><th>Progress</th><th></th></tr>${rows}</table>
    </div>`;
  el.onclick = async (e) => {
    const c = e.target.closest("[data-cancel]");
    if (c) {
      try { await api("POST", `/api/probes/${c.dataset.cancel}/cancel`); toast("Cancelling…"); }
      catch (err) { toast(err.message, true); }
      return;
    }
    const v = e.target.closest("[data-verdict]");
    if (v) { state.openVerdict = v.dataset.verdict; show("verdicts"); }
  };
}

/* ---- verdicts --------------------------------------------------------------------- */
async function loadVerdicts() {
  state.verdicts = (await api("GET", "/api/verdicts")).verdicts;
}

function renderVerdicts() {
  const el = $("#view-verdicts");
  if (state.openVerdict) { renderVerdictDetail(el, state.openVerdict); return; }
  if (!state.verdicts.length) {
    el.innerHTML = `<div class="panel"><div class="empty">No verdicts yet.</div></div>`;
    return;
  }
  const rows = state.verdicts.map((v) => `
    <tr class="clickable" data-open="${esc(v.id)}">
      <td><b>${esc(v.title)}</b><br><span class="dim">${esc(v.created)} · ${esc(v.preset)} · ${esc(v.gauntlet.name || "")}</span></td>
      <td>${flagChip(v)}</td>
      <td class="muted">${esc(v.recommendation).slice(0, 140)}${v.recommendation.length > 140 ? "…" : ""}</td>
    </tr>`).join("");
  el.innerHTML = `
    <div class="panel">
      <div class="panel-title">Verdicts — reports, never writes</div>
      <table><tr><th>Probe</th><th>Flag</th><th>Recommendation</th></tr>${rows}</table>
    </div>`;
  el.onclick = (e) => {
    const r = e.target.closest("[data-open]");
    if (r) { state.openVerdict = r.dataset.open; renderVerdicts(); }
  };
}

async function renderVerdictDetail(el, id) {
  let v;
  try { v = await api("GET", `/api/verdicts/${id}`); }
  catch (e) { state.openVerdict = null; renderVerdicts(); return; }

  const m = v.marginal || null;
  const ladder = (v.ladder || []).map((r) => `
    <tr><td>${esc(r.lever)}</td>
      <td class="num">${deltaSpan(r.delta_pp)}</td>
      <td class="num dim">± ${r.ci95_pp}</td>
      <td>${r.in_band ? `<span class="chip vigor">in band</span>` : `<span class="chip blood">still over</span>`}</td></tr>`).join("");
  const screening = (v.screening || []).slice(0, 12).map((s) => `
    <tr><td>${esc(s.name)}</td>
      <td class="num">${s.games_seen}</td><td class="num">${s.games_cast}</td>
      <td class="num">${s.win_when_cast != null ? (100 * s.win_when_cast).toFixed(0) + "%" : "—"}</td>
      <td class="num">${s.win_when_held != null ? (100 * s.win_when_held).toFixed(0) + "%" : "—"}</td>
      <td class="num">${s.cast_vs_held_pp != null ? deltaSpan(s.cast_vs_held_pp) : "—"}</td></tr>`).join("");
  const cells = (v.cells || []).map((c) => `
    <tr><td class="dim">${esc(c.content)}</td><td class="dim">${esc(c.difficulty)}</td>
      <td class="num dim">${c.size}</td><td class="num">${(100 * c.win_rate).toFixed(0)}%</td>
      <td class="num dim">${c.mean_rounds}</td></tr>`).join("");
  const roster = v.roster_rates ? Object.entries(v.roster_rates).map(([k, r]) => `
    <tr><td>${esc(k)}${k === v.subject.character_id ? ' <span class="chip brass">subject</span>' : ""}</td>
      <td class="num">${(100 * r).toFixed(0)}%</td></tr>`).join("") : "";
  const spend = v.spend_audit ? Object.entries(v.spend_audit).map(([k, r]) => `
    <tr><td>${esc(k)}</td><td class="num">${(100 * r).toFixed(0)}%</td></tr>`).join("") : "";
  const features = (v.features || []).map((f) => `
    <tr><td>${esc(f.feature)}${f.flagged ? ' <span class="chip blood">flag</span>' : ""}</td>
      <td class="num">${deltaSpan(f.delta_win_pp)}</td>
      <td class="num dim">${f.delta_rounds >= 0 ? "+" : ""}${f.delta_rounds} r</td>
      <td class="num dim">${f.encounters_with}/${f.encounters_without}</td>
      <td class="dim">${esc(f.lever)}</td></tr>`).join("");

  el.innerHTML = `
    <div class="panel">
      <button class="btn small quiet" id="v-back">← All verdicts</button>
      <div class="verdict-head" style="margin-top:12px">
        <span class="flag ${esc(v.flag)}">${esc((v.flag || "").replace("_", " "))}</span>
        <span class="caps" style="font-size:12px;color:var(--mist)">${esc(v.title)}</span>
        ${v.combo_blind ? `<span class="chip brass">combo-blind — can convict, never acquit</span>` : ""}
        ${v.screening_only ? `<span class="chip dim">screening only — rerun thorough before acting</span>` : ""}
      </div>
      ${v.stale ? `<div class="stale-band">Stale — the gauntlet changed since this verdict; rerun to compare.</div>` : ""}
      <div class="verdict-rec">${esc(v.recommendation)}</div>
      ${m ? `<div class="stamp">Marginal contribution <b>${m.delta_pp >= 0 ? "+" : ""}${m.delta_pp} pp</b>
        (± ${m.ci95_pp} at 95%, n ${m.n} paired cells; win ${(100 * m.win_a).toFixed(0)}% vs ${(100 * m.win_b).toFixed(0)}% ablated)
        ${v.z_vs_deck != null ? ` · z vs deck <b>${v.z_vs_deck}</b>` : ""}
        ${v.ultimate_dependence != null ? ` · ${(100 * v.ultimate_dependence).toFixed(0)}% of wins route through the ultimate` : ""}
        ${v.percentile != null ? ` · roster percentile <b>${v.percentile}</b>` : ""}</div>` : ""}
      <div class="stamp">Context: gauntlet <b>${esc(v.gauntlet.name)}</b> (hash ${esc(v.gauntlet.hash)}) ·
        policy <b>${esc(v.policy_version)}</b> · preset <b>${esc(v.preset)}</b> · ${esc(v.created)}</div>

      ${ladder ? `<div class="panel-title" style="margin-top:18px">The lever ladder</div>
        <table><tr><th>Lever</th><th class="num">Δ vs filler</th><th class="num">CI</th><th>Band</th></tr>${ladder}</table>` : ""}

      ${roster ? `<div class="panel-title" style="margin-top:18px">Roster (identical solo cells)</div>
        <table><tr><th>Character</th><th class="num">Win rate</th></tr>${roster}</table>` : ""}

      ${spend ? `<div class="panel-title" style="margin-top:18px">Spend-plan audit (the gauntlet run)</div>
        <table><tr><th>Plan</th><th class="num">Win rate</th></tr>${spend}</table>` : ""}

      ${features ? `<div class="panel-title" style="margin-top:18px">Generation-vocabulary attribution</div>
        <table><tr><th>Feature</th><th class="num">Δ win</th><th class="num">Δ rounds</th><th class="num">with/without</th><th>Lever</th></tr>${features}</table>` : ""}
      ${(v.proposals || []).length ? `<div class="panel-title" style="margin-top:18px">Proposed register deltas (apply by hand)</div>
        <div class="copyblock">${esc(v.proposals.join("\n\n"))}</div>` : ""}

      ${screening ? `<div class="panel-title" style="margin-top:18px">Deck screening — cast vs held (confounded; a ranking signal only)</div>
        <table><tr><th>Card</th><th class="num">Seen</th><th class="num">Cast</th>
          <th class="num">Win when cast</th><th class="num">Win when held</th><th class="num">Split</th></tr>${screening}</table>` : ""}

      ${cells ? `<div class="panel-title" style="margin-top:18px">Cells (as-is variant)</div>
        <table><tr><th>Content</th><th>Pressure</th><th class="num">Size</th><th class="num">Win</th><th class="num">Rounds</th></tr>${cells}</table>` : ""}

      <div class="footer-note">${esc(v.footer || "")}</div>
    </div>`;
  $("#v-back").onclick = () => { state.openVerdict = null; renderVerdicts(); };
}

/* ---- render dispatch / polling ----------------------------------------------------- */
async function render(view) {
  try {
    if (view === "roster") { await loadRoster(); await loadVerdicts(); renderRoster(); }
    if (view === "bench") { await loadRoster(); await loadGauntlets(); renderBench(); }
    if (view === "queue") { await loadJobs(); renderQueue(); }
    if (view === "verdicts") { await loadVerdicts(); renderVerdicts(); }
  } catch (e) { toast(e.message, true); }
}

setInterval(async () => {
  try {
    await loadJobs();
    if ($("#view-queue").classList.contains("active")) renderQueue();
  } catch (e) { /* server away */ }
}, 2500);

// The Deckbuilder handoff loop: re-read the roster when the tab regains focus.
window.addEventListener("focus", () => {
  if ($("#view-roster").classList.contains("active")) render("roster");
});

show(VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "roster");
