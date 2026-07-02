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
  keywords: string[];
  intent: IntentView | null;
  is_boss: boolean;
  is_channeling: boolean;
  in_execute_window: boolean;
}

export interface TokenView {
  id: string;
  name: string;
  row: Row;
  power: StatBlock;
  hp: StatBlock;
  is_channeling: boolean;
}

export interface StackRow {
  label: string;
  kind: string;
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
export interface EnemySpec {
  id?: string;
  name: string;
  hp: number;
  level: number;
  power?: number;
  row?: Row;
  keywords?: string[];
  intent: EnemyIntentSpec;
  ranged_intent?: EnemyIntentSpec | null;
}
export interface EncounterDetail {
  id: string;
  name: string;
  enemies: EnemySpec[];
  tokens: Record<string, unknown>;
}
export interface SetupOptions {
  characters: CharacterOption[];
  encounters: EncounterOption[];
}
