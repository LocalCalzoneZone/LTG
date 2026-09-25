# LTG documentation

| Read this | When you need |
|---|---|
| [game_design.md](game_design.md) | **The rules**, current canon (GDD v2). Combat, enemies, encounters and adventures, characters, progression and economy, scenario mode and campaigns. |
| [generation.md](generation.md) | How content is generated: every LLM writer, when it runs, what it reads, the gates it must pass, models, taste rules, art and animation |
| [balance_register.md](balance_register.md) | Every tunable number (`T-NN`) with its current value and the code symbol that holds it, plus the retune watch-list |
| [architecture.md](architecture.md) | The codebase map: packages, module and region maps, the wire protocol, data directories, ops, how-to checklists |
| [roadmap.md](roadmap.md) | What is not built or not tested yet, as objectives grouped into milestones |
| [design/](design/README.md) | **History**: the v1 GDD and Design Updates 01–24, what each one did, and how to resolve the `§` citations in code comments |
| [reviews/](reviews/2026-09/README.md) | Dated review records: the [2026-09-02 whole-game review](reviews/2026-09/README.md) briefs, and the [2026-09-24 consolidation](reviews/2026-09-24/README.md) sweeps and findings. Their open items live in the roadmap. |
| [panel_animation_prompt_guide.md](panel_animation_prompt_guide.md), [panel_animation_prompts.md](panel_animation_prompts.md) | Working docs for the image-to-video panel animations |

Elsewhere in the repo:

- [../CLAUDE.md](../CLAUDE.md): orientation for coding agents, covering commands, invariants, settled decisions, and gotchas.
- [../ltg_player_guide.html](../ltg_player_guide.html): the player-facing guide.
- [../apps/game-ui/DESIGN_SYSTEM.md](../apps/game-ui/DESIGN_SYSTEM.md): the "Brasswork & Ink" UI design system.
- [../apps/deckbuilder/CUSTOM_CARD_SCHEMA.md](../apps/deckbuilder/CUSTOM_CARD_SCHEMA.md): the custom-card import format.
- [../WINDOWS_INSTALL.md](../WINDOWS_INSTALL.md): installing on a plain Windows machine.

## Keeping the docs true

- **Rules live in one place.** When a rule changes, update `game_design.md` in the same change, citing the design `§` or the code symbol. Magnitudes go in `balance_register.md`.
- **New design work** starts as a numbered update in `design/`. Once built, fold it into the canon and tick its objectives in `roadmap.md`.
- **If code and canon disagree, the code is what players get.** Fix whichever one is wrong, and don't leave the ruling only in a code comment.
