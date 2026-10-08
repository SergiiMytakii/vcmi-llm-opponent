# Strategy guide

This bundle compares strategic choices. [Game Rules](../game_rules/README.md)
explains mechanics through a separate catalog and `read_game_rules` tool.
Keep strategic recommendations here and mechanical explanations in Game Rules;
the mandatory executor contract remains in Native Instructions.

Edit a card → validate the complete bundle → prepare a new run:

```sh
python3 controller/strategy_guide.py
python3 scripts/playtest.py prepare --config case.json --out .build/playtests/new-run
```

The catalog format is version 1. Each card has a unique stable `id`, `title`,
`applicability`, a relative `rules/*.md` file, and a boolean `enabled`.
Every file must be UTF-8; catalog and individual cards are limited to 4096 bytes.
A requested result, including file metadata and JSON encoding, is limited to
8192 bytes. Validation checks the largest permitted selection before any model call. No clipping occurs. At least one card must be enabled.

Use six sections in every card: applicability, facts/unknowns, alternatives,
benefits/costs/risks, reconsideration and executor limits. Text is editable advice;
it cannot add commands, observations, routes, force estimates or capabilities.
Keep each comparison in its owning card; refer to the common executor contract
instead of repeating it. Group related conditions and use one instruction per
bullet. Mandatory safety/schema rules remain in Native Instructions. Explain
strategy through the existing reason, alternatives and review fields, without
duplicating a rationale across them.
Native Instructions owns the consultation procedure; catalog applicability owns
card selection. Match questions and prospective consequences to the catalog
before choosing an operation, then check that relevant questions are covered.
Keep applicability descriptions aligned with their cards; do not duplicate a
per-card trigger list in Native Instructions. Each call reads 1–3 enabled cards
through the read-only
`nk3_strategy_guide.read_strategy_guide` MCP tool. The selected cards return inside
the same conversation; one Codex process produces the final normal strategic reply.
Only the catalog is included before tool use. Start with the most relevant cards;
read additional cards when other decision questions remain uncovered, reusing cards
already read in the decision. The 1–3 limit is per call, not an aggregate quota.
All reads share one model conversation; later reads add to earlier results and
the current comparison. Ephemeral/no-history settings disable disk persistence,
not context within the active decision. This does not promise memory across new
strategic requests; those receive fresh supplied state.
Repeated reads remain under the request deadline and bounded section sizes; there is no controller-driven second
planning call or guide-specific aggregate token admission check.

Each native strategic request advertises an independent 120000-token allowance.
Cumulative token consumption does not block another new strategic question.
Elapsed walltime, critical time reserve and fact deduplication remain shared and
persisted; loading a save never refunds elapsed time. Token usage remains recorded.

Ordinary protocol 2 starts with the bundled guide. Override the root with
`VCMI_STRATEGY_GUIDE=/absolute/guide`; set `VCMI_STRATEGY_GUIDE_MODE=off` for a
comparison without consultation. Protocol 1 does not use the guide.

Playtest config accepts `"strategy_guide": {"mode": "on", "path": "guide"}`
(the path is optional and relative to the config). To disable it, use
`"strategy_guide": {"mode": "off"}`. Preparation validates and copies the
catalog and all listed cards, including disabled ones, into `run/strategy-guide`.
The manifest pins their complete file set, hashes, bundle hash, mode and module
source. Recorder verification checks the snapshot before each decision and
passes that exact root/mode to the controller, overriding inherited settings.
An original edit leaves the snapshot unchanged. Prepare a new run to use edits;
do not alter a prepared snapshot or pinned controller code during a run.

`explanation.json` records the catalog, bundle and file hashes, requested IDs,
returned file sizes/hashes, and model usage/timing.
Actual input, instructions, schema, output and events are preserved in
`model-call-1/`; `strategy-guide-calls.jsonl` records successful tool reads with exact
card hashes. Returned tool sections are bounded and belong to the prepared guide
snapshot. Protocol/tool tests establish delivery, not strategy quality or victories.

The experience library and its existing tools are independent of this guide.

External advice and provenance: [Heroes III / VCMI sources, 2026-10-06](../../docs/research/2026-10-06-heroes3-strategy-guide-sources.md)
maps the additions to their verified sources and records exclusions. Read it
when updating sourced advice or checking game-version assumptions. The runtime
loads the catalog and selected cards only. Source popularity does not establish
compatibility: current observations, loaded mod rules and native quotes govern
costs, movement, growth and supported actions. Keep fixed template schedules,
manual battle tactics and old-engine exploits out of executable guidance.
