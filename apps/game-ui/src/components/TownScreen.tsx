import { useEffect, useMemo, useState } from "react";
import { useGame } from "../lib/store";
import { roman } from "../lib/format";
import type {
  ConfirmView,
  ConversationView,
  PartySheetRow,
  QuestLogView,
  TownLocationView,
  TownNpcView,
  TownSnapshot,
} from "../lib/types";
import { ManaIcon } from "./Pips";
import { IconSigil, IconX } from "./Icons";
import { GearSheet, ShopModal } from "./Items";

const SMALL_BTN =
  "caps-label border border-line px-2.5 py-1 text-[9px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch disabled:cursor-not-allowed disabled:opacity-40";
const GHOST_BTN =
  "caps-label border border-line2 px-4 py-2 text-left text-[10px] tracking-[0.16em] text-parch transition " +
  "hover:border-brass hover:text-brass-hi disabled:cursor-not-allowed disabled:opacity-40";
const BRASS_BTN =
  "chamfer-x caps-label bg-gradient-to-b from-brass-hi to-brass px-8 py-2.5 text-[11px] tracking-[0.3em] text-ink-0 transition " +
  "hover:from-brass-hi hover:to-brass-hi disabled:cursor-not-allowed disabled:from-white/[0.06] disabled:to-white/[0.06] disabled:text-dimmed";

const FUNCTION_LABEL: Record<string, string> = {
  inn: "Inn", weaponsmith: "Weaponsmith", artificer: "Artificer", apothecary: "Apothecary",
};
function fnLabel(fn: string): string {
  return FUNCTION_LABEL[fn] ?? fn.replace(/_/g, " ");
}

/** The town screen (Update 17 §D17-5.2): the battlefield shell repurposed —
 * backdrop + card slots (locations, then a location's NPCs) + inspect + a verb
 * button + splash on entry. Party-wide movement goes through the all-players
 * confirmation server-side; browsing is per-player. */
export function TownScreen() {
  const town = useGame((s) => s.town);
  const sendTown = useGame((s) => s.sendTown);
  const showQuestLog = useGame((s) => s.showQuestLog);
  const setQuestLog = useGame((s) => s.setQuestLog);
  const [inspect, setInspect] = useState<{ kind: "location"; item: TownLocationView } | { kind: "npc"; item: TownNpcView } | null>(null);
  const [splashSeen, setSplashSeen] = useState<string>("");
  const [showShop, setShowShop] = useState(false);

  // Close inspect when the screen changes underneath it.
  const screenKey = town ? `${town.location?.id ?? "map"}:${town.scenario.act_number}` : "";
  useEffect(() => { setInspect(null); setShowShop(false); }, [screenKey]);

  if (!town) return null;

  if (town.mode === "complete") return <RunEndScreen town={town} />;

  const loc = town.location;
  const backdrop = loc ? loc.art_url : town.town.art_url;
  const sceneText = loc ? loc.scene : town.town.scene;
  const splashKey = town.splash ? `${town.splash.kind}:${town.splash.title}:${town.splash.text}` : "";
  const showSplash = !!town.splash && splashSeen !== splashKey && !town.conversation;

  return (
    <div className="field-scene relative isolate flex h-full w-full flex-col overflow-hidden">
      {/* Backdrop + scrim */}
      {backdrop ? (
        <img src={backdrop} alt="" className="absolute inset-0 -z-10 h-full w-full object-cover" />
      ) : (
        <div className="absolute inset-0 -z-10 bg-gradient-to-b from-ink-0 to-ink-1" />
      )}
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-ink-0 via-ink-0/55 to-ink-0/35" />

      {/* Header */}
      <div className="flex items-start justify-between gap-4 px-6 pt-4">
        <div>
          <div className="caps-label text-[10px] tracking-[0.3em] text-mist">
            {town.town.name} · Scenario {town.scenario.scenario_number} · Act {roman(town.scenario.act_number)} of {roman(town.scenario.acts_total)}
          </div>
          <div className="caps-label mt-1 text-[16px] tracking-[0.22em] text-brass-hi">
            {loc ? loc.name : town.town.name}
          </div>
          <div className="mt-1 max-w-xl text-xs font-light italic text-mist">
            {loc ? fnLabel(loc.function) : town.scenario.act_title}
          </div>
        </div>
        {!backdrop && (
          <div className="max-w-md text-right text-[11px] font-light leading-relaxed text-dimmed">{sceneText}</div>
        )}
      </div>

      {/* Body: the party on the left (as on the battlefield), the town's
          cards tiled to the right */}
      <div className="flex min-h-0 flex-1 gap-4 px-6 py-3">
        <PartyColumn party={town.party_sheet} />
        <div className="scroll-thin flex min-h-0 flex-1 items-center overflow-y-auto">
          <div className="grid w-full grid-cols-[repeat(auto-fill,190px)] justify-center gap-4">
            {loc
              ? loc.npcs.map((n) => (
                  <SlotCard
                    key={n.id}
                    title={n.name}
                    subtitle={n.role}
                    art={n.art_url}
                    marker={n.questgiver ? "Quest" : n.has_dialogue ? "Talk" : n.merchant ? "Wares" : ""}
                    onClick={() => setInspect({ kind: "npc", item: n })}
                  />
                ))
              : town.town.locations.map((l) => (
                  <SlotCard
                    key={l.id}
                    title={l.name}
                    subtitle={fnLabel(l.function)}
                    art={l.art_url}
                    marker={l.questgiver ? "Quest" : l.has_dialogue ? "Talk" : ""}
                    onClick={() => setInspect({ kind: "location", item: l })}
                  />
                ))}
          </div>
        </div>
      </div>

      {/* Console: party strip + verbs */}
      <TownConsole town={town} />

      {/* Overlays */}
      {inspect && (
        <InspectSheet
          inspect={inspect}
          onClose={() => setInspect(null)}
          onVisit={(id) => { sendTown("visit", { location_id: id }); setInspect(null); }}
          onTalk={(id) => { sendTown("talk", { npc_id: id }); setInspect(null); }}
          onShop={town.shop ? () => { setInspect(null); setShowShop(true); } : undefined}
        />
      )}
      {showShop && town.shop && <ShopModal shop={town.shop} party={town.party_sheet} onClose={() => setShowShop(false)} />}
      {town.trade && <TradeOffer town={town} />}
      {town.conversation && <DialogueModal town={town} conv={town.conversation} />}
      {showQuestLog && <QuestLogPanel log={town.quest_log} onClose={() => setQuestLog(false)} />}
      {showSplash && (
        <TownSplash town={town} onContinue={() => setSplashSeen(splashKey)} />
      )}
      {town.materializing && !town.splash && (
        <div className="pointer-events-none absolute inset-x-0 top-24 flex justify-center">
          <span className="caps-label border border-line bg-ink-0/80 px-3 py-1.5 text-[10px] tracking-[0.2em] text-mist">
            The town stirs…
          </span>
        </div>
      )}
      <ConfirmOverlay confirm={town.confirm} />
    </div>
  );
}

/** The party, standing on the left as it does on the battlefield: portrait
 * cards with name, level, HP; click for the character sheet. */
function PartyColumn({ party }: { party: PartySheetRow[] }) {
  const setSheetFor = useGame((s) => s.setSheetFor);
  return (
    <div className="scroll-thin flex w-[150px] shrink-0 flex-col justify-center gap-2 overflow-y-auto">
      {party.map((p) => (
        <button
          key={p.id}
          onClick={() => setSheetFor(p.id)}
          title={`${p.name} — character sheet`}
          className="group relative flex w-full flex-col overflow-hidden border border-tide/40 bg-ink-0/70 text-left shadow-lg transition hover:border-tide"
        >
          <div className="aspect-[3/4] w-full bg-ink-0">
            {p.portrait ? (
              <img src={p.portrait} alt={p.name} className="h-full w-full object-cover object-top" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-dimmed"><IconSigil size={26} /></div>
            )}
          </div>
          <div className="flex items-baseline justify-between gap-1 bg-gradient-to-t from-ink-0/95 to-ink-0/60 px-2 py-1.5">
            <span className="caps-label truncate text-[10px] tracking-[0.1em] text-parch">{p.name}</span>
            <span className="shrink-0 text-[9px] font-light text-mist">L{p.level}{p.max_hp ? ` · ${p.hp ?? p.max_hp}/${p.max_hp}` : ""}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

function SlotCard({ title, subtitle, art, marker, onClick }: {
  title: string; subtitle: string; art: string; marker: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group relative flex w-[190px] flex-col overflow-hidden border border-line bg-ink-0/70 text-left shadow-lg transition hover:border-brass/70 hover:shadow-[0_0_16px_rgba(233,204,130,0.12)]"
    >
      <div className="aspect-[3/4] w-full bg-ink-0">
        {art ? (
          <img src={art} alt={title} className="h-full w-full object-cover object-top" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-dimmed">
            <IconSigil size={30} />
          </div>
        )}
      </div>
      {marker && (
        <span className="caps-label absolute right-1 top-1 border border-brass/70 bg-ink-0/85 px-1.5 py-0.5 text-[8px] tracking-[0.16em] text-brass">
          {marker}
        </span>
      )}
      <div className="flex flex-col gap-0.5 bg-gradient-to-t from-ink-0/95 to-ink-0/60 p-2.5">
        <span className="caps-label truncate text-[12px] tracking-[0.1em] text-parch">{title}</span>
        <span className="truncate text-[10px] font-light text-mist">{subtitle}</span>
      </div>
    </button>
  );
}

function TownConsole({ town }: { town: TownSnapshot }) {
  const sendTown = useGame((s) => s.sendTown);
  const setQuestLog = useGame((s) => s.setQuestLog);
  const setSheetFor = useGame((s) => s.setSheetFor);
  const retryJob = useGame((s) => s.retryJob);
  const job = town.adventure_job;
  const busy = !!town.confirm;
  let startLabel = "Start Adventure";
  let startHint = "";
  if (!town.adventure_unlocked) startHint = "Accept a quest first";
  else if (job.state === "pending") { startLabel = "Preparing the road…"; startHint = "the adventure is being written"; }
  else if (job.state === "failed") { startLabel = "Generation failed"; startHint = job.error ?? ""; }
  else if (town.adventure_ready) startHint = town.adventure_name;
  return (
    <div className="flex items-end justify-between gap-4 border-t border-line bg-ink-0/80 px-5 py-3 backdrop-blur-[2px]">
      <div className="flex items-end gap-2">
        <button className={SMALL_BTN} onClick={() => setSheetFor(town.party_sheet[0]?.id ?? null)}>Character sheets</button>
        {town.run.last_save?.label && (
          <span className="ml-3 self-center text-[10px] font-light text-dimmed" title="Last save">
            Saved · {town.run.last_save.label.split(" · ").slice(-1)[0]}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button className={SMALL_BTN} onClick={() => sendTown("save")} disabled={busy}>Save Game</button>
        <button className={SMALL_BTN} onClick={() => setQuestLog(true)}>Quest Log</button>
        <button className={SMALL_BTN} onClick={() => sendTown("leave")} disabled={!town.location || busy}>Leave Location</button>
        {job.state === "failed" ? (
          <button className={SMALL_BTN + " border-blood/60 text-blood"} onClick={retryJob} title={job.error ?? ""}>
            Generation failed — Retry
          </button>
        ) : (
          <button
            className={BRASS_BTN}
            disabled={!town.adventure_ready || busy || !!town.location}
            title={startHint || (town.location ? "Leave the location first" : "")}
            onClick={() => sendTown("start_adventure")}
          >
            {startLabel}
          </button>
        )}
      </div>
    </div>
  );
}

function InspectSheet({ inspect, onClose, onVisit, onTalk, onShop }: {
  inspect: { kind: "location"; item: TownLocationView } | { kind: "npc"; item: TownNpcView };
  onClose: () => void;
  onVisit: (id: string) => void;
  onTalk: (id: string) => void;
  onShop?: () => void;
}) {
  const item = inspect.item;
  const art = item.art_url;
  const isNpc = inspect.kind === "npc";
  const npc = isNpc ? (item as TownNpcView) : null;
  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/70 backdrop-blur-[2px]" onClick={onClose}>
      <div className="panel-ticks flex w-[min(92vw,720px)] gap-5 border border-line2 bg-ink-2 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="w-[220px] shrink-0">
          <div className="aspect-[3/4] w-full border border-line bg-ink-0">
            {art ? (
              <img src={art} alt={item.name} className="h-full w-full object-cover object-top" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-dimmed"><IconSigil size={40} /></div>
            )}
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start gap-3">
            <div>
              <div className="caps-label text-[14px] tracking-[0.22em] text-brass">{item.name}</div>
              <div className="mt-0.5 text-xs font-light italic text-mist">
                {isNpc ? npc!.role : fnLabel((item as TownLocationView).function)}
              </div>
            </div>
            <span className="h-px flex-1 self-center bg-line" />
            <button onClick={onClose} className="text-mist hover:text-parch"><IconX size={14} /></button>
          </div>
          <p className="mt-4 text-sm font-light leading-relaxed text-parch">
            {isNpc ? npc!.persona : (item as TownLocationView).description}
          </p>
          {isNpc && npc!.flavor && (
            <p className="mt-3 text-sm font-light italic text-mist">“{npc!.flavor}”</p>
          )}
          <div className="mt-auto flex flex-wrap items-center justify-end gap-2 pt-5">
            {isNpc ? (
              <>
                {npc!.merchant && (
                  <button className={SMALL_BTN} onClick={onShop} disabled={!onShop} title="Browse this act's stock">
                    See their wares
                  </button>
                )}
                <button className={BRASS_BTN} onClick={() => onTalk(item.id)}>Talk to {item.name.split(" ")[0]}</button>
              </>
            ) : (
              <button className={BRASS_BTN} onClick={() => onVisit(item.id)}>Visit {item.name}</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The dialogue modal (§D17-5.4): party portraits left (a zoomed 3:4 crop of
 * each portrait's upper portion, tiled), NPC portrait and text centre, choices
 * as ghost buttons. The initiating player chooses; everyone sees the text.
 * Clicking a party portrait attributes the line to that character. */
function DialogueModal({ town, conv }: { town: TownSnapshot; conv: ConversationView }) {
  const sendTown = useGame((s) => s.sendTown);
  const npc = town.location?.npcs.find((n) => n.id === conv.npc_id);
  const busy = !!town.confirm;
  // The featured party portrait: the attributed speaker, else the first.
  const featured = town.party_sheet.find((p) => p.id === conv.attributed) ?? town.party_sheet[0];
  return (
    <div className="absolute inset-0 z-30 flex items-stretch bg-black/85 backdrop-blur-[2px]">
      {/* Left: the party — one portrait featured near full height, the rest as tabs */}
      <div className="relative flex w-[30%] min-w-[220px] shrink-0 flex-col justify-end">
        {featured?.portrait ? (
          <img src={featured.portrait} alt={featured.name}
               className="absolute inset-0 h-full w-full object-cover object-top" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-dimmed"><IconSigil size={48} /></div>
        )}
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-transparent to-ink-0/70" />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-0 via-ink-0/70 to-transparent px-4 pb-4 pt-16">
          <div className="caps-label text-[13px] tracking-[0.22em] text-parch">{featured?.name}</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {town.party_sheet.map((p) => (
              <button
                key={p.id}
                onClick={() => sendTown("attribute", { character_id: p.id })}
                title={`Attribute the party's line to ${p.name}`}
                className={`caps-label border px-2 py-0.5 text-[8px] tracking-[0.12em] transition ${
                  conv.attributed === p.id ? "border-brass text-brass" : "border-line text-mist hover:text-parch"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Centre: the words */}
      <div className="flex min-w-0 flex-1 flex-col justify-center px-8 py-6">
        <div className="flex items-start gap-3">
          <div>
            <div className="caps-label text-[15px] tracking-[0.25em] text-brass">{npc?.name ?? conv.npc_id}</div>
            <div className="text-xs font-light italic text-mist">{npc?.role}{town.location ? ` · ${town.location.name}` : ""}</div>
          </div>
          <span className="h-px flex-1 self-center bg-line" />
          <button onClick={() => sendTown("end_talk")} className="text-mist hover:text-parch" title="End the conversation">
            <IconX size={14} />
          </button>
        </div>
        <div className="mt-6 max-h-[40vh] overflow-y-auto">
          <p className="font-display text-xl font-light leading-relaxed text-parch">
            {conv.speaker === "party" && conv.attributed && (
              <span className="caps-label mr-2 text-[10px] tracking-[0.2em] text-mist">
                {town.party_sheet.find((p) => p.id === conv.attributed)?.name ?? "The party"} —
              </span>
            )}
            {conv.text}
          </p>
        </div>
        <div className="mt-6 flex flex-col gap-2">
          {conv.choices.map((c) => (
            <button
              key={c.index}
              className={GHOST_BTN}
              disabled={busy}
              onClick={() => sendTown("choose", { index: c.index })}
              title={c.party_wide ? "A party-wide choice — every player confirms" : ""}
            >
              {c.label}
              {c.party_wide && <span className="ml-2 text-[9px] text-dimmed">· party</span>}
            </button>
          ))}
          {conv.over && (
            <button className={GHOST_BTN} onClick={() => sendTown("end_talk")}>Farewell.</button>
          )}
        </div>
      </div>

      {/* Right: the NPC, near full height */}
      <div className="relative flex w-[30%] min-w-[220px] shrink-0 flex-col justify-end">
        {npc?.art_url ? (
          <img src={npc.art_url} alt={npc.name} className="absolute inset-0 h-full w-full object-cover object-top" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-dimmed"><IconSigil size={48} /></div>
        )}
        <div className="absolute inset-0 bg-gradient-to-l from-transparent via-transparent to-ink-0/70" />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-0 via-ink-0/70 to-transparent px-4 pb-4 pt-16 text-right">
          <div className="caps-label text-[13px] tracking-[0.22em] text-brass">{npc?.name}</div>
          <div className="text-[10px] font-light italic text-mist">{npc?.role}</div>
        </div>
      </div>
    </div>
  );
}

function QuestLogPanel({ log, onClose }: { log: QuestLogView; onClose: () => void }) {
  return (
    <div className="absolute inset-y-0 right-0 z-30 flex w-[min(92vw,460px)] flex-col border-l border-line2 bg-ink-2/95 p-5 shadow-2xl backdrop-blur-[2px]">
      <div className="mb-4 flex items-center gap-3">
        <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">Journal</h2>
        <span className="text-[10px] font-light text-mist">{log.arc_title} · Act {roman(log.act_number)}</span>
        <span className="h-px flex-1 bg-line" />
        <button onClick={onClose} className="text-mist hover:text-parch"><IconX size={14} /></button>
      </div>
      <div className="scroll-thin flex flex-col gap-3 overflow-y-auto pr-1 text-sm font-light">
        <JournalEntries log={log} full />
        {log.completed.length > 0 && (
          <div className="mt-2 border-t border-line pt-2">
            <div className="caps-label text-[10px] tracking-[0.2em] text-mist">Deeds done</div>
            {log.completed.map((c) => (
              <div key={c.act} className="mt-1 text-xs text-mist">
                Act {roman(c.act)} — {c.title}: <span className="text-parch">{c.quest}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** The journal's entries: the act's intro, then what the townsfolk said, the
 * quest once agreed to, the road taken. Nothing the party hasn't heard. */
export function JournalEntries({ log, full }: { log: QuestLogView; full?: boolean }) {
  const entries = log.journal ?? [];
  const shown = full ? entries : entries.slice(-6);
  if (!entries.length) return <div className="text-xs font-light italic text-dimmed">The page is blank so far.</div>;
  return (
    <div className="flex flex-col gap-2">
      {!full && entries.length > shown.length && (
        <div className="text-[10px] font-light italic text-dimmed">… {entries.length - shown.length} earlier entries in the Journal</div>
      )}
      {shown.map((e, i) => (
        <div key={i} className={`text-xs font-light leading-relaxed ${e.kind === "intro" ? "italic text-parch" : e.kind === "quest" ? "text-brass" : "text-mist"}`}>
          {e.kind === "heard" && (
            <span className="caps-label mr-1 text-[9px] tracking-[0.14em] text-parch">{e.speaker}{e.where ? `, ${e.where}` : ""} —</span>
          )}
          {e.kind === "heard" ? <span>“{e.text}”</span> : e.text}
        </div>
      ))}
      {log.direct_to && (
        <div className="text-xs font-light text-parch">Seek {log.direct_to.npc ?? ""}{log.direct_to.location ? ` at ${log.direct_to.location}` : ""}.</div>
      )}
    </div>
  );
}

/** The character sheet (§D17-5.2): stats and build, level and points-to-next,
 * gold, and the gear slots (cards arrive with Phase 2). Read-only in combat;
 * edit affordances are Phase 2's. */
export function CharacterSheetModal({ rows, editable = false, inTown = false }: {
  rows: PartySheetRow[]; editable?: boolean; inTown?: boolean;
}) {
  const sheetFor = useGame((s) => s.sheetFor);
  const setSheetFor = useGame((s) => s.setSheetFor);
  const row = rows.find((r) => r.id === sheetFor);
  if (!row) return null;
  const b = row.build;
  const basePower = b.attack_mode === "melee" ? 2 : 1;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/75 backdrop-blur-[2px]" onClick={() => setSheetFor(null)}>
      <div className="panel-ticks flex max-h-[92vh] w-[min(96vw,1180px)] gap-6 overflow-y-auto border border-line2 bg-ink-2 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* The portrait, featured: near full height of the sheet */}
        <div className="relative w-[340px] shrink-0 self-stretch overflow-hidden border border-line bg-ink-0" style={{ minHeight: 520 }}>
          {row.portrait ? (
            <img src={row.portrait} alt={row.name} className="absolute inset-0 h-full w-full object-cover object-top" />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-dimmed"><IconSigil size={56} /></div>
          )}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-0 via-ink-0/80 to-transparent px-4 pb-4 pt-20">
            <div className="caps-label text-[18px] tracking-[0.22em] text-brass-hi">{row.name}</div>
            <div className="mt-1 flex items-center justify-between text-xs font-light text-parch">
              <span>Level {row.level}{row.effective_level && row.effective_level !== row.level ? ` (eff. ${row.effective_level})` : ""}</span>
              <span>{row.gold} gold</span>
            </div>
            <div className="mt-1 text-[10px] font-light text-mist">
              {row.earned_points} points earned{row.points_to_next_level != null ? ` · ${row.points_to_next_level} to next level` : " · max level"}
              {row.banked ? ` · ${row.banked} banked` : ""}
            </div>
            {b.description && <p className="mt-2 text-xs font-light italic leading-relaxed text-mist">{b.description}</p>}
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start gap-3">
            <div className="caps-label text-[14px] tracking-[0.22em] text-brass">Character Sheet</div>
            <span className="flex gap-1">
              {rows.length > 1 && rows.map((r) => (
                <button key={r.id} onClick={() => setSheetFor(r.id)}
                        className={`caps-label border px-2 py-0.5 text-[8px] tracking-[0.12em] ${r.id === row.id ? "border-brass text-brass" : "border-line text-mist hover:text-parch"}`}>
                  {r.name}
                </button>
              ))}
            </span>
            <span className="h-px flex-1 self-center bg-line" />
            <button onClick={() => setSheetFor(null)} className="text-mist hover:text-parch"><IconX size={14} /></button>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-sm font-light">
            <Stat label="Hit Points" value={`${row.hp ?? b.hp} / ${b.hp}`} />
            <Stat label="Attack" value={`${b.attack_mode} ${basePower + b.power_bought}`} />
            <Stat label="Mana capacity" value={<span className="flex gap-0.5">{b.starting_mana.map((c, i) => <ManaIcon key={i} color={c} size={13} />)}</span>} />
            <Stat label="Starting cards" value={String(b.starting_cards)} />
            <Stat label="Keyword" value={b.keyword ?? "—"} />
            <Stat label="Colours" value={<span className="flex gap-0.5">{b.colors.map((c, i) => <ManaIcon key={i} color={c} size={13} />)}</span>} />
          </div>
          <GearSheet row={row} editable={editable} inTown={inTown} party={rows} />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 py-1">
      <span className="caps-label text-[9px] tracking-[0.16em] text-mist">{label}</span>
      <span className="text-parch">{value}</span>
    </div>
  );
}

function TownSplash({ town, onContinue }: { town: TownSnapshot; onContinue: () => void }) {
  const sp = town.splash!;
  const art = sp.kind === "town" ? town.town.art_url : town.location?.art_url ?? "";
  const waiting = town.materializing && !sp.text;
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-ink-0">
      {art && <img src={art} alt="" className="absolute inset-0 h-full w-full object-cover opacity-60" />}
      <div className="absolute inset-0 bg-gradient-to-t from-ink-0 via-ink-0/40 to-ink-0/70" />
      <div className="relative z-10 flex max-w-2xl flex-col items-center gap-5 px-8 text-center">
        <div className="caps-label text-[11px] tracking-[0.3em] text-mist">{sp.subtitle}</div>
        <div className="flex items-center gap-4">
          <span className="h-px w-14 bg-gradient-to-r from-transparent to-brass" />
          <div className="caps-label whitespace-nowrap text-[15px] tracking-[0.25em] text-brass-hi">{sp.title}</div>
          <span className="h-px w-14 bg-gradient-to-l from-transparent to-brass" />
        </div>
        <p className="font-display text-lg font-light leading-relaxed text-parch">
          {waiting ? "The town stirs as you arrive…" : sp.text}
        </p>
        {town.materialize_error && (
          <p className="text-sm font-light text-blood">The chronicle faltered: {town.materialize_error}</p>
        )}
        <button onClick={onContinue} className={BRASS_BTN} disabled={waiting}>
          {waiting ? "Arriving…" : "Continue"}
        </button>
      </div>
    </div>
  );
}

/** The all-players confirmation (T-84): every player answers; 30 s → yes; the
 * initiator may cancel. Rendered in town and in combat alike. */
export function ConfirmOverlay({ confirm }: { confirm: ConfirmView | null | undefined }) {
  const answerConfirm = useGame((s) => s.answerConfirm);
  const cancelConfirm = useGame((s) => s.cancelConfirm);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!confirm) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [confirm?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const seconds = useMemo(() => {
    if (!confirm) return 0;
    return Math.max(0, confirm.seconds_left - Math.floor((now - mountedAt(confirm.id)) / 1000));
  }, [confirm, now]);
  if (!confirm) return null;
  return (
    <div className="absolute inset-x-0 bottom-20 z-40 flex justify-center">
      <div className="panel-ticks flex items-center gap-4 border border-brass/60 bg-ink-2/95 px-5 py-3 shadow-2xl">
        <div>
          <div className="caps-label text-[11px] tracking-[0.2em] text-brass">{confirm.label}</div>
          <div className="text-[10px] font-light text-mist">
            {confirm.yes_count} of {confirm.player_count} agreed · auto-yes in {seconds}s
          </div>
        </div>
        {!confirm.answered ? (
          <>
            <button className={BRASS_BTN} onClick={() => answerConfirm(confirm.id, true)}>Yes</button>
            <button className={SMALL_BTN} onClick={() => answerConfirm(confirm.id, false)}>No</button>
          </>
        ) : confirm.you_are_initiator ? (
          <button className={SMALL_BTN} onClick={() => cancelConfirm(confirm.id)}>Cancel</button>
        ) : (
          <span className="caps-label text-[9px] tracking-[0.16em] text-dimmed">Waiting…</span>
        )}
      </div>
    </div>
  );
}

function TradeOffer({ town }: { town: TownSnapshot }) {
  const sendTown = useGame((s) => s.sendTown);
  const t = town.trade!;
  const from = town.party_sheet.find((p) => p.id === t.from)?.name ?? t.from;
  const to = town.party_sheet.find((p) => p.id === t.to)?.name ?? t.to;
  return (
    <div className="absolute inset-x-0 top-24 z-40 flex justify-center">
      <div className="panel-ticks flex items-center gap-4 border border-brass/60 bg-ink-2/95 px-5 py-3 shadow-2xl">
        <div className="text-[11px] font-light text-parch">
          {from} offers {to}{t.item_id ? " an item" : ""}{t.item_id && t.gold ? " and" : ""}{t.gold ? ` ${t.gold} gold` : ""}.
        </div>
        <button className={BRASS_BTN} onClick={() => sendTown("trade_answer", { yes: true })}>Accept</button>
        <button className={SMALL_BTN} onClick={() => sendTown("trade_answer", { yes: false })}>Decline</button>
      </div>
    </div>
  );
}

/** The defeat splash inside a scenario (Normal or Hardcore): the party is
 * beaten and forced to flee; the run continues in town (or ends, in Hardcore)
 * once someone presses on. Covers ONLY the bottom action bar (rendered absolute
 * inside the bar's wrapper in App) — the battlefield and log above stay
 * readable and clickable, so the losing board can be inspected. */
export function DefeatSplash({ adventureName, hardcore }: { adventureName: string; hardcore: boolean }) {
  const sendTown = useGame((s) => s.sendTown);
  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center overflow-y-auto bg-ink-0/95 px-6 py-3">
      <div className="flex max-w-3xl flex-col items-center gap-2 text-center">
        <div className="flex items-center gap-4">
          <span className="h-px w-14 bg-gradient-to-r from-transparent to-blood" />
          <div className="caps-label whitespace-nowrap text-[15px] tracking-[0.25em] text-blood">Defeated</div>
          <span className="h-px w-14 bg-gradient-to-l from-transparent to-blood" />
        </div>
        <div className="caps-label text-[10px] tracking-[0.3em] text-mist">{adventureName}</div>
        <p className="font-display text-base font-light leading-relaxed text-parch">
          {hardcore
            ? "The line breaks and does not re-form. There is no road back from this."
            : "The line breaks. Bloodied and outnumbered, you are forced to flee — back down the road to town, the quest undone, to lick your wounds and try again."}
        </p>
        <button onClick={() => sendTown("flee")} className={`${BRASS_BTN} mt-1`}>
          {hardcore ? "It is over" : "Return to town"}
        </button>
      </div>
    </div>
  );
}

const _mounted = new Map<number, number>();
function mountedAt(id: number): number {
  let t = _mounted.get(id);
  if (t === undefined) { t = Date.now(); _mounted.set(id, t); }
  return t;
}

function RunEndScreen({ town }: { town: TownSnapshot }) {
  const disconnect = useGame((s) => s.disconnect);
  const dead = town.scenario.dead;
  return (
    <div className="field-scene relative flex h-full w-full items-center justify-center overflow-hidden">
      {town.town.art_url && <img src={town.town.art_url} alt="" className="absolute inset-0 h-full w-full object-cover opacity-40" />}
      <div className="absolute inset-0 bg-gradient-to-t from-ink-0 via-ink-0/60 to-ink-0/70" />
      <div className="relative z-10 flex max-w-xl flex-col items-center gap-5 px-8 text-center">
        <div className="caps-label text-[11px] tracking-[0.3em] text-mist">{town.town.name} · {town.scenario.title}</div>
        <div className="caps-label text-[18px] tracking-[0.25em] text-brass-hi">
          {dead ? "The Run Is Over" : "Scenario Complete"}
        </div>
        <p className="font-display text-lg font-light leading-relaxed text-parch">
          {dead
            ? "The party fell, and in Hardcore there is no coming back. The run's saves remain to be read, not continued."
            : `Three acts, one villain: ${town.scenario.villain}. The town remembers.`}
        </p>
        <button className={BRASS_BTN} onClick={() => { disconnect(); const u = new URL(location.href); u.searchParams.delete("s"); history.pushState({}, "", u); }}>
          Return to the menu
        </button>
      </div>
    </div>
  );
}
