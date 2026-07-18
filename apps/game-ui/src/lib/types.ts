// Mirrors the server snapshot contract (apps/game-server/.../snapshot.py). The
// client is a pure view over this; it never computes rules.

export type Color = "W" | "U" | "B" | "R" | "G" | "C";
export type Row = "front" | "mid" | "rear";
export type PriorityKind =
  | "main_action"
  | "reaction"
  | "mana_choice"
  | "card_choice"
  | null;

export interface StatBlock {
  current: number;
  base: number;
  modifier: number;
}

export interface CardView {
  id: string;
  name: string;
  cost: string; // pip string like "{2}{U}"
  timing: string; // instant | sorcery | channeled
  rarity: string;
  level: number;
  type: string;
  text: string;
}

export interface ManaColor {
  color: Color;
  pool: number;
  capacity: number;
  channel_occupied: number;
}

export interface ManaBlock {
  identity_colors: Color[];
  by_color: ManaColor[];
  pending_capacity_choice: boolean;
}

// A keyword static, pre-labelled by the server (registry display name + rules
// gloss) so the client renders icon + tooltip without knowing any rules.
export interface KeywordInfo {
  id: string; // registry id, e.g. "first_strike"
  name: string; // display name, e.g. "First Strike"
  gloss: string; // one-line rules explanation for the tooltip
}

export interface ChannelSummary {
  card_id: string;
  card_name: string;
  reserved_pips: string;
  target_id: string | null;
  target_name: string | null;
  text: string;
  // What ending this channel fires (the channel_break trigger), "" when none.
  break_text: string;
}

// A Skill/Ultimate as the client sees it (D8-3). For a seat you don't control
// only `used` arrives; the card fields are present for your own characters.
export interface HeroicView extends Partial<CardView> {
  used: boolean;
}

export interface EvergreenEntry {
  name: string; // flavour name when authored, else the default
  text: string; // the mechanical line
  flavor: string; // the authored one-line flavour text ("" when none)
}

export interface EvergreenBlock {
  offensive: EvergreenEntry;
  defensive_action: EvergreenEntry;
  defensive_reaction: EvergreenEntry;
}

export interface CharacterView {
  id: string;
  name: string;
  archetype: string;
  portrait: string; // loadout art (data URL / image URL), "" if none
  description: string; // the loadout's character blurb, "" if none
  row: Row;
  power: StatBlock;
  hp: StatBlock;
  incapacitated: boolean;
  is_channeling: boolean;
  channels_summary: ChannelSummary[];
  status_tags: string[];
  keywords: KeywordInfo[];
  // +1/+1 counters received; their stat change is already inside power/hp.
  counters: number;
  // Typed counters (D8-2) — public information.
  poison_counters: number;
  regen_counters: number;
  poisoned: boolean;
  regenerating: boolean;
  // Heroic actions (D8-3): the public 0–100 gauge; the full card faces ship only
  // to the controlling client (others see just the used flag).
  ultimate_gauge: number;
  skill: HeroicView | null;
  ultimate: HeroicView | null;
  // The evergreen abilities wearing their authored flavour names (D8-3.4).
  evergreen: EvergreenBlock;
  // The active stance (§D9-2), or null: per main-ability slot, "unchanged" |
  // "removed" | {name} for a replacement.
  stance: {
    card_id: string;
    card_name: string;
    slots: Record<string, "unchanged" | "removed" | { name: string }>;
  } | null;
  mitigate_value: number;
  acted_mode: string | null;
  turn_ended: boolean;
  mana: ManaBlock;
  is_active_focusable: boolean;
  controlled: boolean;
  is_priority_holder: boolean;
  hand: CardView[] | null;
  hand_count: number;
  library_count: number;
  graveyard: CardView[] | null;
  graveyard_count: number;
  library: CardView[] | null;
}

// A VEILED intent (Design Update 08 §D8-1): the pre-stack contract is a generic
// category plus the locked target — never names, verbs, or magnitudes. The real
// action appears in full on the stack when it executes.
export type IntentCategory =
  | "threat"
  | "spellcraft"
  | "row assault"
  | "party assault"
  | "gathering"
  | "support"
  | "summon"
  | "manoeuvre"
  | "none";

export interface IntentView {
  enemy_id: string;
  creature_id: string; // same as enemy_id (legacy key)
  creature_name: string;
  category: IntentCategory;
  target_id: string | null;
  target_name: string | null;
  line: string; // the template line ("The Spore Husk threatens Soren.")
  status: "declared" | "stripped" | "stunned" | "executed" | "fizzled" | "none";
  reveal: string; // what a stripped intent turned out to be ("" otherwise)
  // 1, or 2 for an enraged boss's second declared intent (§D9-4 boss fury).
  slot: number;
}

// The encounter objective (§D12-1.5): fully public — the mission, not an
// intent. `line` is the banner text pinned atop the intents window; the
// kind-specific counters back any richer rendering.
export interface ObjectiveView {
  kind: "survive" | "waves" | "race";
  status: "active" | "complete" | "failed";
  line: string;
  rounds_remaining: number | null;
  wave: number | null;
  waves_total: number | null;
  target_id: string | null;
}

// A corpse marker (§D9-1): the dead stay on the battlefield — an object, not a
// creature. `stirring` > 0 means it revives in that many Upkeeps (rises) unless
// exiled or raised first; such an enemy is NOT yet defeated.
export interface CorpseView {
  id: string;
  name: string;
  row: Row;
  level: number;
  power: number;
  max_hp: number;
  stirring: number;
  is_boss: boolean;
}

export interface CreatureView {
  id: string;
  name: string;
  // The POOL enemy id behind this creature (a layout clone "wolf_2" -> "wolf");
  // art generate/remove calls are keyed by it, and clones share the base's art.
  base_id: string;
  // Generated portrait URL, "" until one exists (the card shows its sigil).
  image: string;
  // The enemy's art-direction prose (physical appearance), "" if none.
  description: string;
  row: Row;
  level: number;
  power: StatBlock;
  hp: StatBlock;
  attack_mode: string;
  keywords: KeywordInfo[];
  // +1/+1 counters received; their stat change is already inside power/hp.
  counters: number;
  // Typed counters (D8-2) — public on both sides; stat changes already folded in.
  poison_counters: number;
  regen_counters: number;
  poisoned: boolean; // an active (ticking) poison effect
  regenerating: boolean;
  // The charge gauge (D8-2.4): the count/threshold are public; what the charge
  // FEEDS is hidden until it fires. threshold null = no windup on this enemy.
  charge: number;
  charge_threshold: number | null;
  intent: IntentView | null;
  // Every declared line this round — two for an enraged boss (§D9-4).
  intents: IntentView[];
  // The doom-clock badge (§D12-1.5): rounds left on a live race clock, for the
  // marked enemy only — null everywhere else.
  doom_clock: number | null;
  // The rises trait (§D9-1.5) — public: it will stir and revive when killed.
  rises: number | null;
  is_boss: boolean;
  is_channeling: boolean;
  // Held enemy channels (§8): named so the player knows what breaking does.
  channels: { name: string }[];
  // One hit of at least this much breaks the enemy's channel(s).
  break_threshold: number;
  in_execute_window: boolean;
}

export interface TokenView {
  id: string;
  name: string;
  // The token DEFINITION key behind this spawn ("huskling_3" -> "huskling");
  // art calls are keyed by it, and all spawns of one definition share the art.
  base_id: string;
  // Generated portrait URL, "" until one exists.
  image: string;
  // The token definition's art-direction prose, "" if none.
  description: string;
  row: Row;
  power: StatBlock;
  hp: StatBlock;
  keywords: KeywordInfo[];
  counters: number;
  poison_counters: number;
  regen_counters: number;
  is_channeling: boolean;
  // Control chip (§D9-1.4): set when this party-side combatant is a controlled
  // enemy — "dominated" (a living enemy that snaps back) or "undead" (raised,
  // crumbles). `control_left` counts End Steps remaining; null == the encounter.
  controlled_by: string | null;
  control_left: number | null;
  control_kind: "dominated" | "undead" | null;
}

export interface StackRow {
  label: string;
  kind: string;
  // Engine vocabulary (serialize.py action_mode): "melee attack" | "ranged attack"
  // | "spell" | "ability" — the damage lane, so what answers it is unambiguous.
  mode: string | null;
  source_id: string;
  source_name: string | null;
  source_side: string;
  target_id: string | null;
  target_name: string | null;
  reserved_pips: string;
  // The full card behind the action (cast / card-carried trigger), for the
  // hover tooltip; null for basic attacks and enemy components.
  card: CardView | null;
  top: boolean;
  uid: number;
}

export interface LogEntry {
  // Absolute position in the engine log — lets the client tell NEW entries
  // from history (the combat-FX layer fires one-shot effects off exactly that).
  seq?: number;
  type: string;
  msg: string;
  data: Record<string, unknown>;
  // The full card this line references (cast / draw / channel events), for the
  // hover tooltip; null when the line names no known card.
  card?: CardView | null;
}

export interface LegalAction {
  index: number;
  kind: string; // attack|cast|defend|move|mitigate|pass|end_turn|choose_mana|choose_card|choose_scry|drop_channels
  actor_id: string;
  card_id: string | null;
  target_id: string | null;
  // Per-site targets for an independent multi-target cast (e.g. Agony Warp),
  // ordered by site; targets[0] mirrors target_id. Empty for single-target actions.
  // A stack-targeting counter uses target_id "#<uid>" (referencing StackRow.uid).
  targets: (string | null)[];
  // Per-site effect label (aligned with `targets`, or a single entry for a
  // single-target cast): what each pick is for, e.g. "weaken −0/−3". Null = no
  // label; the UI falls back to a generic "select a target".
  target_labels?: (string | null)[];
  color: Color | null;
  mode: number | null;
  // X chosen for an {X}-cost cast (one legal action per affordable X); null
  // for non-X actions.
  x?: number | null;
  // Candidate handle for a choose_card / choose_scry pick — indexes into
  // GameSnapshot.pending_choice.candidates.
  choice?: number | null;
  label: string;
}

export interface Priority {
  holder_character_id: string | null;
  kind: PriorityKind;
}

// ---- Adventures (Design Update 10) ----------------------------------------- //
// The points-buy price table (server-sent; the client renders costs, never rules).
export interface BuildPrices {
  hp_step: number; // per +2 HP
  mana: number; // per +1 capacity slot
  card: number; // per +1 starting card
  power: number; // per +1 bought Power
  power_cap_per_level: number; // bought Power ≤ this × level (T-60)
}

// A character's points-buy build as the level-up screen edits it.
export interface BuildView {
  hp: number;
  starting_mana: Color[];
  starting_cards: number;
  power_bought: number;
  keyword: string | null;
  attack_mode: "melee" | "ranged";
  colors: Color[];
  level: number;
  portrait: string;
}

// One character's row in the level-up gate. `build`/points ship only for the
// seats this client controls; everyone else is a confirmed/waiting light.
export interface LevelUpRow {
  id: string;
  name: string;
  confirmed: boolean;
  build?: BuildView;
  locked?: number; // the entering build's spend
  banked?: number; // carried remainder
  available?: number; // banked + the 30 grant (0 extra once confirmed)
}

export interface LevelUpBlock {
  next_level: number;
  points_per_level: number;
  prices: BuildPrices;
  characters: LevelUpRow[];
}

// The adventure block riding the snapshot (absent for plain encounters).
export interface AdventureBlock {
  id: string;
  name: string;
  flavor: string;
  act: number; // 1-based
  acts_total: number;
  act_name: string;
  narration: string;
  character_ids: string[]; // roster ids — Restart from Act I re-picks these
  complete: boolean;
  level_up: LevelUpBlock | null;
}

export interface GameSnapshot {
  turn: number;
  phase: string;
  phase_label: string;
  // Generated battle backdrop URL ("" until one exists) and the encounter this
  // game was built from — in-game art generate/remove calls aim at it.
  scene_image: string;
  encounter_id: string;
  priority: Priority;
  characters: CharacterView[];
  creatures: CreatureView[];
  tokens: TokenView[];
  // Corpse markers (§D9-1.7): the dead on their rows; a stirring one pulses.
  corpses: CorpseView[];
  stack: StackRow[];
  // The objective banner (§D12-1.5): fully public, pinned as the first line of
  // the intents window. Null for a standard encounter.
  objective: ObjectiveView | null;
  // The veiled intents window (D8-1.5): one line per living enemy this round.
  intents: IntentView[];
  // A pending card pick's candidates as full cards (only sent to the chooser's
  // client — hidden information, gated like hands). Null when no pick is open.
  pending_choice: { kind: string; chooser_id: string; candidates: CardView[] } | null;
  log: LogEntry[];
  legal_actions: LegalAction[];
  result: string | null;
  game_over: { result: string; objective_line?: string | null } | null;
  // Present only when this session runs an adventure (Update 10): act sequence,
  // narration, and the between-acts level-up gate. A non-final act victory
  // arrives with result/game_over suppressed and `level_up` set instead.
  adventure?: AdventureBlock;
}

export interface SeatsMsg {
  seats: Record<string, string | null>;
  you: string[];
}

// Setup-options (New Game modal).
export interface CharacterOption {
  id: string;
  name: string;
  archetype: string;
  colors: Color[];
  identity: Color[];
  description: string;
  portrait: string; // data URL / image URL, "" if none
  card_count: number;
  deletable: boolean; // true for imported loadouts; false for bundled examples
}
export interface EncounterOption {
  id: string;
  name: string;
  enemy_names: string[];
  enemy_count: number;
  // Party sizes with a dedicated layout (e.g. [1,2,3,4]); [] == fixed roster.
  scales: number[];
  deletable: boolean;
  editable: boolean;
}

// Authored enemy + encounter shape (Options → encounter editor). Mirrors the
// scenario dict the engine consumes; the editor is a pure form over it.
export interface EnemyIntentSpec {
  name: string;
  amount: number;
  mode?: "melee" | "ranged";
  targeting?: string; // lowest_hp | front_lowest_hp | lowest_hp_party | <char id>
  action_type?: string;
  intent_type?: string;
}
// One enemy component (Design Update 04 §F-3) as authored JSON. The editor edits
// the common scalars directly; `verbs`/`condition` are edited as JSON blobs and
// validated server-side (the engine gate rejects anything malformed on save).
export interface ComponentSpec {
  id?: string;
  archetype?: string;
  timing?: "proactive" | "reactive";
  trigger?: string;
  condition?: unknown;
  cooldown?: number;
  once_per_encounter?: boolean;
  priority?: number;
  target_rule?: string;
  action_type?: string; // "spell" for magic (counterable by spell counters)
  channel?: boolean;    // held ongoing effect (broken by a ≥25% hit / removal)
  phase?: string;       // boss: "pre_enrage" | "post_enrage"
  move_home?: boolean;
  telegraph?: string;
  verbs?: unknown[];
}
export interface EnemySpec {
  id?: string;
  name: string;
  hp: number;
  level: number;
  power?: number;
  row?: Row;
  home_row?: Row;
  attack_mode?: "melee" | "ranged";
  is_boss?: boolean;
  keywords?: string[];
  flavor?: string;
  description?: string; // physical appearance (art/narration)
  image?: string; // generated portrait URL (art.py), rides the encounter JSON
  // Legacy enemies carry a flat `intent`; framework enemies carry `components`
  // (their basic attack is synthesized from `power` by the engine).
  intent?: EnemyIntentSpec;
  ranged_intent?: EnemyIntentSpec | null;
  components?: ComponentSpec[];
}
export interface EncounterDetail {
  id: string;
  name: string;
  // LLM-generated battle backdrop ("" for hand-authored). Rides the encounter
  // for the image-generation / narration systems; the editor round-trips it.
  // (Per-enemy physical `description`s travel inside the enemy dicts.)
  scene?: string;
  // Generated battle-backdrop URL (art.py); per-enemy images ride the enemy dicts.
  scene_image?: string;
  enemies: EnemySpec[];
  tokens: Record<string, unknown>;
  // Per-party-size rosters: {"1": [enemy ids...], ..., "4": [...]} (repeats clone).
  // The editor round-trips them, pruning ids that no longer exist.
  layouts?: Record<string, string[]>;
}
// An adventure in the New Game / Options lists (Update 10).
export interface AdventureOption {
  id: string;
  name: string;
  flavor: string;
  act_names: string[];
  deletable: boolean;
  editable: boolean;
}
// The full adventure: wrapper fields + each act's embedded encounter detail.
export interface AdventureActDetail extends EncounterDetail {
  narration: string;
  encounter_id: string;
}
export interface AdventureDetail {
  id: string;
  name: string;
  flavor: string;
  acts: AdventureActDetail[];
}
// "Generate all art" queue progress (polled).
export interface ArtQueueStatus {
  total: number;
  done: number;
  failed: number;
  running: boolean;
  current: string | null;
  errors: string[];
}

export interface SetupOptions {
  characters: CharacterOption[];
  encounters: EncounterOption[];
  adventures: AdventureOption[];
}

// LLM / encounter generation (Options → LLM).
export interface LlmModel {
  id: string; // exact OpenRouter slug
  label: string;
}
export interface LlmSettings {
  model: string;
  instructions: string;
  art_style: string; // the aesthetic wrapper for image generation
  art_backend: string; // "openrouter" | "comfyui"
  art_backends: LlmModel[]; // {id,label} options for the backend picker
  art_model: string; // the fixed OpenRouter image-model slug (display only)
  comfyui_url: string; // e.g. http://192.168.1.50:8188
  comfyui_workflow: string; // API-format workflow JSON with %prompt% placeholder
  models: LlmModel[];
  has_key: boolean; // the raw key is never sent to the client
  difficulties: string[]; // e.g. ["easy","standard","hard"]
}
// Partial update; omit `api_key` (or send "") to leave the stored key untouched.
// `instructions: null` / `art_style: null` reset that prompt to the server's
// built-in default.
export interface LlmSettingsPatch {
  api_key?: string;
  model?: string;
  instructions?: string | null;
  art_style?: string | null;
  art_backend?: string;
  comfyui_url?: string;
  comfyui_workflow?: string;
}
