# Game Rules

This reference explains game mechanics. The separate Strategy Guide compares
strategic choices. Experience lessons remain a third independent source.
Native Instructions owns the mandatory executor contract and critical guards.

The model sees only this catalog and reads 1–3 cards per call when mechanics are unclear
through `nk3_game_rules.read_game_rules`. Full cards return in the same model
conversation; reading does not start another planning process or execute actions.
Additional unresolved mechanics may need another call within the request deadline;
reuse cards already read. Native Instructions owns the shared authority and
consultation procedure.

| Card | Mechanics |
| --- | --- |
| `day_and_week` | Calendar, movement renewal, income, construction limits and stock growth |
| `town_economy` | Buildings, prerequisites, production, recruitment and upgrades |
| `hero_army` | Seven stacks, compatibility, physical army pools and delivery |
| `combat_strength` | Estimates, hero effects, uncertainty and cumulative losses |
| `mana_magic` | Capacity, regeneration, guild recovery and spell support |
| `ownership_victory` | Capture, elimination, townless defeat and victory conditions |

Cards use four sections: mechanics, applicability/exceptions, facts to check,
and executor boundary. Explain mechanisms rather than prescribing a strategy.
Use focused bullets; keep executor-specific caveats and refer to the common
contract instead of repeating general authority, route or delivery guards.
Current scenario/mod facts and quotes govern amounts and availability. Unknown
values remain unknown. This is a basic reference, not a full rules encyclopedia.

Edit a card, validate the bundle, then prepare a new run:

```sh
python3 controller/game_rules.py
python3 scripts/playtest.py prepare --config case.json --out .build/playtests/new-run
```

Catalog format and bounded reader are shared with Strategy Guide. Each card and
catalog is limited to 4096 UTF-8 bytes; an encoded selection to 8192 bytes. The
reader validates the whole bundle, rejects unknown/duplicate IDs and escaping or
symlink paths, and verifies selected file hashes before returning text.

Protocol 2 uses this bundle by default. Configure `VCMI_GAME_RULES` with an
absolute custom root, or `VCMI_GAME_RULES_MODE=off` to disable it independently
of Strategy Guide. Protocol 1 has no Game Rules integration.

Playtest config accepts `"game_rules": {"mode": "on", "path": "rules"}`;
path is optional and relative to the config. `{"mode": "off"}` disables it.
Preparation copies all catalogued cards into `run/game-rules`, pins the complete
file set and hashes, and records the mode in the manifest. Recorder verification
checks the snapshot before a decision and passes its exact path and mode to the
controller. Old manifests without `game_rules` keep this reference off.

Original card edits do not change a prepared snapshot. Do not edit an existing
run's snapshot. Source changes require preparing a new run under the existing
controller pinning policy; no running game is restarted by editing these files.

`explanation.json` includes a separate `game_rules` record with catalog, bundle
hash, file hashes and actual requested IDs. `model-call-1/game-rules-calls.jsonl`
records successful reads, exact returned hashes and sizes. Strategy advice has
its own tool and audit. Both stay under the existing model deadline and usage.

The rules were checked against the pinned engine and current observation and
executor code: [source notes](../../docs/research/2026-10-06-game-rules-sources.md).
Protocol tests establish delivery and separation, not improved play or wins.

## Common provenance

Each card keeps its manual page range and short engine revision in the runtime
text. Shared sources are the [NWC/3DO 1999 manual](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/297000/manuals/BONUS_Heroes_of_Might_and_Magic_III_HDEdition_OldManual1999_EN.pdf)
and pinned VCMI revision `6a1ca68e00f540087f35579c62ffaf037f5be269`. Full validation
notes and code pointers stay in the source notes linked above. Runtime tools return
the catalog and requested cards, not this README; compact provenance is not a new
lookup requirement for the model.
