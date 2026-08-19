import { useState } from "react";
import { useGame } from "../lib/store";
import type { GearView, ItemView, PartySheetRow, RewardsView, ShopView } from "../lib/types";
import { ManaIcon } from "./Pips";
import { IconSigil, IconX } from "./Icons";

const SMALL_BTN =
  "caps-label border border-line px-2 py-0.5 text-[8px] tracking-[0.14em] text-mist transition " +
  "hover:border-line2 hover:text-parch disabled:cursor-not-allowed disabled:opacity-40";
const BRASS_BTN =
  "chamfer-x caps-label bg-gradient-to-b from-brass-hi to-brass px-6 py-2 text-[10px] tracking-[0.3em] text-ink-0 transition " +
  "hover:from-brass-hi hover:to-brass-hi disabled:cursor-not-allowed disabled:from-white/[0.06] disabled:to-white/[0.06] disabled:text-dimmed";

const RARITY_TINT: Record<string, string> = {
  common: "border-line text-parch",
  uncommon: "border-tide/60 text-tide",
  rare: "border-brass/70 text-brass",
  mythic: "border-aether/70 text-aether",
};

/** One item as a card (§D17-4.5): art (or a sigil), name, rarity hairline,
 * the one-line mechanics summary, the one-line flavour. */
export function ItemCard({ item, small, footer, onClick, selected }: {
  item: ItemView; small?: boolean; footer?: React.ReactNode; onClick?: () => void; selected?: boolean;
}) {
  const tint = RARITY_TINT[item.rarity] ?? RARITY_TINT.common;
  const W = small ? "w-[104px]" : "w-[150px]";
  return (
    <div
      onClick={onClick}
      className={`flex ${W} flex-col overflow-hidden border bg-ink-0/80 text-left shadow ${tint} ${
        onClick ? "cursor-pointer transition hover:shadow-[0_0_12px_rgba(233,204,130,0.15)]" : ""
      } ${selected ? "ring-1 ring-brass" : ""}`}
      title={`${item.name}${item.flavor ? ` — “${item.flavor}”` : ""}`}
    >
      <div className={`${small ? "aspect-square" : "aspect-[4/3]"} w-full bg-ink-0`}>
        {item.art_url ? (
          <img src={item.art_url} alt={item.name} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-dimmed"><IconSigil size={small ? 16 : 24} /></div>
        )}
      </div>
      <div className="flex flex-col gap-0.5 p-1.5">
        <span className={`caps-label truncate text-[${small ? 9 : 10}px] tracking-[0.1em]`}>{item.name}</span>
        <span className="text-[9px] font-light text-mist">{item.rarity} · {item.slot}{item.points_price ? ` · ${item.points_price} pts` : ""}</span>
        {!small && item.summary && <span className="text-[10px] font-light text-parch">{item.summary}</span>}
        {!small && item.flavor && <span className="truncate text-[9px] font-light italic text-dimmed">“{item.flavor}”</span>}
        {footer}
      </div>
    </div>
  );
}

function EmptySlot({ label, small }: { label: string; small?: boolean }) {
  return (
    <div className={`flex ${small ? "h-[104px] w-[104px]" : "h-[150px] w-[150px]"} flex-col items-center justify-end border border-dashed border-line/70 pb-1`}>
      <span className="caps-label text-[8px] tracking-[0.14px] text-dimmed">{label}</span>
    </div>
  );
}

/** The gear half of the character sheet (§D17-4.1): three gear slots, the
 * belt, the inventory — with equip / swap / discard / sell / give when
 * `editable` (town, or the between-phase screen); read-only in combat. */
export function GearSheet({ row, editable, inTown, party }: {
  row: PartySheetRow; editable: boolean; inTown: boolean; party: PartySheetRow[];
}) {
  const sendTown = useGame((s) => s.sendTown);
  const [sel, setSel] = useState<{ item: ItemView; where: string } | null>(null);
  const [give, setGive] = useState<string>("");
  const g: GearView = row.gear;
  const cid = row.id;
  const act = (verb: string, payload: Record<string, unknown>) => {
    sendTown(verb, { character_id: cid, ...payload });
    setSel(null);
  };
  const pick = (item: ItemView | null, where: string) => item && setSel(sel?.item.id === item.id ? null : { item, where });

  const slot = (label: string, key: "primary" | "secondary" | "accessory") => {
    const it = g[key];
    return it ? (
      <ItemCard key={key} item={it} small selected={sel?.item.id === it.id} onClick={() => pick(it, key)}
                footer={<span className="caps-label text-[8px] tracking-[0.12em] text-brass">{label}</span>} />
    ) : <EmptySlot key={key} label={label} small />;
  };

  return (
    <div className="mt-4">
      <div className="caps-label text-[10px] tracking-[0.2em] text-mist">
        Gear{row.worn_points ? ` · ${row.worn_points} worn points · effective level ${row.effective_level}` : ""}
      </div>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        {slot("Primary", "primary")}{slot("Secondary", "secondary")}{slot("Accessory", "accessory")}
        <span className="w-2" />
        {[0, 1, 2].map((i) => {
          const it = g.belt[i];
          return it ? (
            <ItemCard key={`b${i}`} item={it} small selected={sel?.item.id === it.id} onClick={() => pick(it, "belt")}
                      footer={<span className="caps-label text-[8px] tracking-[0.12em] text-vigor">Belt</span>} />
          ) : <EmptySlot key={`b${i}`} label={`Belt ${i + 1}`} small />;
        })}
      </div>
      <div className="caps-label mt-3 text-[10px] tracking-[0.2em] text-mist">Inventory</div>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        {[0, 1, 2].map((i) => {
          const it = g.inventory.gear[i];
          return it ? (
            <ItemCard key={`g${i}`} item={it} small selected={sel?.item.id === it.id} onClick={() => pick(it, "inventory")} />
          ) : <EmptySlot key={`g${i}`} label="Gear" small />;
        })}
        <span className="w-2" />
        {[0, 1, 2].map((i) => {
          const it = g.inventory.consumables[i];
          return it ? (
            <ItemCard key={`c${i}`} item={it} small selected={sel?.item.id === it.id} onClick={() => pick(it, "inventory")} />
          ) : <EmptySlot key={`c${i}`} label="Consumable" small />;
        })}
      </div>
      {sel && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border border-line bg-black/25 p-2">
          <span className="caps-label text-[10px] tracking-[0.14em] text-parch">{sel.item.name}</span>
          <span className="text-[10px] font-light text-mist">{sel.item.summary}</span>
          {sel.item.flavor && <span className="text-[10px] font-light italic text-dimmed">“{sel.item.flavor}”</span>}
          <span className="h-px flex-1 bg-line" />
          {editable ? (
            <>
              {sel.item.slot === "weapon" && sel.where !== "primary" && (
                <button className={SMALL_BTN} onClick={() => act("equip", { item_id: sel.item.id, slot: "primary" })}>Equip primary</button>
              )}
              {sel.item.slot === "weapon" && sel.where !== "secondary" && (
                <button className={SMALL_BTN} onClick={() => act("equip", { item_id: sel.item.id, slot: "secondary" })}>Equip secondary</button>
              )}
              {sel.item.slot === "accessory" && sel.where !== "accessory" && (
                <button className={SMALL_BTN} onClick={() => act("equip", { item_id: sel.item.id, slot: "accessory" })}>Wear</button>
              )}
              {["primary", "secondary", "accessory"].includes(sel.where) && (
                <button className={SMALL_BTN} onClick={() => act("unequip", { slot: sel.where })}>Unequip</button>
              )}
              {sel.item.slot === "consumable" && sel.where !== "belt" && (
                <button className={SMALL_BTN} onClick={() => act("to_belt", { item_id: sel.item.id })}>To belt</button>
              )}
              {sel.item.slot === "consumable" && sel.where === "belt" && (
                <button className={SMALL_BTN} onClick={() => act("from_belt", { item_id: sel.item.id })}>Off belt</button>
              )}
              {inTown && (
                <>
                  <button className={SMALL_BTN} onClick={() => act("sell", { item_id: sel.item.id })} title="Sell at half its points price">
                    Sell · {sel.item.sell_price ?? 0}g
                  </button>
                  {party.length > 1 && (
                    <>
                      <select value={give} onChange={(e) => setGive(e.target.value)}
                              className="border border-line bg-ink-0 px-1 py-0.5 text-[10px] font-light">
                        <option value="">Give to…</option>
                        {party.filter((p) => p.id !== cid).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                      <button className={SMALL_BTN} disabled={!give} onClick={() => { act("give", { to: give, item_id: sel.item.id }); setGive(""); }}>Give</button>
                    </>
                  )}
                </>
              )}
              <button className={`${SMALL_BTN} border-blood/60 text-blood`} onClick={() => act("discard", { item_id: sel.item.id })}>Discard</button>
            </>
          ) : (
            <span className="caps-label text-[9px] tracking-[0.14em] text-dimmed">Read-only in combat</span>
          )}
        </div>
      )}
    </div>
  );
}

/** The shop modal (§D17-5.5) — per-player, asynchronous: the location's stock
 * for this act (fixed for the act), buy for a chosen character (×1.25 the
 * points price); selling happens from the character sheet (×0.5). */
export function ShopModal({ shop, party, onClose }: { shop: ShopView; party: PartySheetRow[]; onClose: () => void }) {
  const sendTown = useGame((s) => s.sendTown);
  const [buyer, setBuyer] = useState(party[0]?.id ?? "");
  const wallet = party.find((p) => p.id === buyer)?.gold ?? 0;
  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/70 backdrop-blur-[2px]" onClick={onClose}>
      <div className="panel-ticks flex max-h-[85vh] w-[min(94vw,900px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">{shop.name} — wares</h2>
          <span className="text-[10px] font-light text-mist">stock is fixed for the act · buy ×{shop.buy_mult} · sell ×{shop.sell_mult}</span>
          <span className="h-px flex-1 bg-line" />
          <label className="flex items-center gap-2 text-[10px] font-light text-mist">
            Buyer
            <select value={buyer} onChange={(e) => setBuyer(e.target.value)} className="border border-line bg-ink-0 px-1 py-0.5 text-[10px]">
              {party.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.gold}g</option>)}
            </select>
          </label>
          <button onClick={onClose} className="text-mist hover:text-parch"><IconX size={14} /></button>
        </div>
        <div className="scroll-thin flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto pr-1">
          {shop.stock.length === 0 && <div className="text-xs font-light text-dimmed">Sold out for this act.</div>}
          {shop.stock.map((it) => (
            <ItemCard key={it.id} item={it} footer={
              <button
                className={`${SMALL_BTN} mt-1 self-start ${wallet < (it.buy_price ?? 0) ? "" : "border-brass/60 text-brass"}`}
                disabled={!buyer || wallet < (it.buy_price ?? 0)}
                onClick={() => sendTown("buy", { location_id: shop.location_id, item_id: it.id, character_id: buyer })}
              >
                Buy · {it.buy_price}g
              </button>
            } />
          ))}
        </div>
      </div>
    </div>
  );
}

/** The Rewards modal (§D17-4.5): the drops as cards, a dropdown per item —
 * a character (disabled when they'd overflow) or Discard — and Accept once
 * everything is placed (the all-players confirmation follows). */
export function RewardsModal({ rewards }: { rewards: RewardsView }) {
  const sendTown = useGame((s) => s.sendTown);
  return (
    <div className="fixed inset-x-0 bottom-0 top-[42px] z-30 flex items-center justify-center bg-black/80 backdrop-blur-[2px]">
      <div className="panel-ticks flex max-h-[88vh] w-[min(94vw,980px)] flex-col border border-line2 bg-ink-2 p-5 shadow-2xl">
        <div className="mb-3 flex items-center gap-3">
          <h2 className="caps-label text-[13px] tracking-[0.25em] text-brass">The Spoils</h2>
          <span className="text-[10px] font-light text-mist">the boss falls — assign each find to a character, or discard it</span>
          <span className="h-px flex-1 bg-line" />
        </div>
        <div className="scroll-thin flex min-h-0 flex-1 flex-wrap content-start gap-3 overflow-y-auto pr-1">
          {rewards.items.map((it, i) => {
            const room = rewards.room[String(i)] ?? {};
            const value = rewards.assign[String(i)] ?? "";
            return (
              <ItemCard key={it.id} item={it} footer={
                <select
                  value={value}
                  onChange={(e) => sendTown("reward_assign", { index: i, target: e.target.value || null })}
                  className={`mt-1 border bg-ink-0 px-1 py-0.5 text-[10px] font-light ${value ? "border-brass/60 text-parch" : "border-line text-mist"}`}
                >
                  <option value="">Assign to…</option>
                  {rewards.characters.map((c) => (
                    <option key={c.id} value={c.id} disabled={!room[c.id]}>
                      {c.name}{room[c.id] ? "" : " (full)"}
                    </option>
                  ))}
                  <option value="discard">Discard</option>
                </select>
              } />
            );
          })}
        </div>
        <div className="mt-4 flex items-center justify-end gap-3">
          <span className="text-[10px] font-light text-mist">
            {Object.keys(rewards.assign).length} / {rewards.items.length} placed
          </span>
          <button className={BRASS_BTN} disabled={!rewards.all_assigned} onClick={() => sendTown("reward_accept", {})}>
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}

export function GoldPips({ gold }: { gold: number }) {
  return <span className="inline-flex items-center gap-1 text-brass"><ManaIcon color="W" size={10} />{gold}</span>;
}
