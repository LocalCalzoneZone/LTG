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
}

export interface CreatureView {
  id: string;
  name: string;
  // The POOL enemy id behind this creature (a layout clone "wolf_2" -> "wolf");
  // art generate/remove calls are keyed by it, and clones share the base's art.
  base_id: string;
  // Generated portrait URL, "" until one exists (the card shows its sigil).
  image: string;
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
  row: Row;
  power: StatBlock;
  hp: StatBlock;
  keywords: KeywordInfo[];
  counters: number;
  poison_counters: number;
  regen_counters: number;
  is_channeling: boolean;
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
  stack: StackRow[];
  // The veiled intents window (D8-1.5): one line per living enemy this round.
  intents: IntentView[];
  // A pending card pick's candidates as full cards (only sent to the chooser's
  // client — hidden information, gated like hands). Null when no pick is open.
  pending_choice: { kind: string; chooser_id: string; candidates: CardView[] } | null;
  log: LogEntry[];
  legal_actions: LegalAction[];
  result: string | null;
  game_over: { result: string } | null;
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
export interface SetupOptions {
  characters: CharacterOption[];
  encounters: EncounterOption[];
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
