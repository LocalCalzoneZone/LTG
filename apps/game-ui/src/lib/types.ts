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

export interface IntentView {
  name: string;
  amount: number | null;
  target_id: string | null;
  target_name: string | null;
}

export interface CreatureView {
  id: string;
  name: string;
  row: Row;
  level: number;
  power: StatBlock;
  hp: StatBlock;
  attack_mode: string;
  keywords: KeywordInfo[];
  // +1/+1 counters received; their stat change is already inside power/hp.
  counters: number;
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
  row: Row;
  power: StatBlock;
  hp: StatBlock;
  keywords: KeywordInfo[];
  counters: number;
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
  top: boolean;
  uid: number;
}

export interface IntentRow {
  creature_id: string;
  creature_name: string;
  intent_text: string;
  // Same vocabulary as StackRow.mode: "melee attack" | "ranged attack" | "spell" | "ability".
  mode: string | null;
  target_id: string | null;
  target_name: string | null;
}

export interface LogEntry {
  type: string;
  msg: string;
  data: Record<string, unknown>;
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
  priority: Priority;
  characters: CharacterView[];
  creatures: CreatureView[];
  tokens: TokenView[];
  stack: StackRow[];
  intents: IntentRow[];
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
  enemies: EnemySpec[];
  tokens: Record<string, unknown>;
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
  models: LlmModel[];
  has_key: boolean; // the raw key is never sent to the client
  difficulties: string[]; // e.g. ["easy","standard","hard"]
}
// Partial update; omit `api_key` (or send "") to leave the stored key untouched.
// `instructions: null` resets the prompt to the server's built-in default.
export interface LlmSettingsPatch {
  api_key?: string;
  model?: string;
  instructions?: string | null;
}
