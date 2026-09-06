# LTG review, 2026-09-02

A whole-game audit done on branch `UI-and-immersion-updates` at commit `1fba7f4`: a hands-on playtest of the running client (a combat encounter and an Act III town save) plus thirteen subsystem code reads. The four work briefs below are self-contained: open a fresh coding session, point it at one brief, and work through the items in the suggested order. Every line number was checked against the code at review time but will drift; re-grep before editing.

| Brief | Items | File |
|---|---|---|
| 1. Gameplay mechanics | 1.1 reaction-window pass parade · 1.2 position and defence as real decisions · 1.3 fights with shape · quick rules fixes | [01-gameplay-mechanics.md](01-gameplay-mechanics.md) |
| 2. Immersion, UI, polish | 2.1 the board narrates its beats · 2.2 hand and reaction strip | [02-immersion-ui-polish.md](02-immersion-ui-polish.md) |
| 3. Stability, code | 3.1 harden the LAN session · 3.2 ship safely to the Windows player · 3.3 explicit contracts | [03-stability-code.md](03-stability-code.md) |
| 4. RPG aliveness | 4.1 world memory · 4.2 NPCs know the heroes, everyone has a voice · 4.3 gold, rest and loot have a job | [04-rpg-aliveness.md](04-rpg-aliveness.md) |

Item 2.3 from the original review (onboarding, town ambience, audio) was not selected and is not briefed.

Each brief carries its own evidence (file:line references and the playtest observations); the long-form reader dossiers behind them were session-temporary and are not kept.

Cross-brief dependencies worth knowing:
- Brief 2 item 2.1 renders the `redirectable` bit that brief 1 item 1.2 adds to veiled intents.
- Brief 3 item 3.3's typed event registry is what makes brief 2's FX fixes durable.
- Brief 4 item 4.2's narrator and barks depend on the same registry.
- Brief 1 item 1.1's standing orders live in the reaction strip that brief 2 item 2.2 redesigns.

Settled decisions all briefs respect: gauge payouts are intended; the owner wants more enemy control pressure, not less; shipped content is not the quality bar; the deckbuilder is custom-cards-only; the "Brasswork & Ink" design system is approved; the Windows player's install path (full clone, in-app update, committed `dist/`) is a constraint, not a bug.
