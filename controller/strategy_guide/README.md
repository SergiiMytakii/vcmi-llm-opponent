# Strategy guide

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
The model decides whether to consult 1–3 enabled cards, at most once per decision.
Without consultation only the catalog is sent. With consultation a second call
receives selected cards and the unchanged game request. Its token allowance is
the remaining original allowance; both calls share the original deadline.
Unknown first-call usage or insufficient budget prevents the second call.
Advice cannot override the always-present game contract or visibility rules.

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
reason, returned file sizes/hashes, read duration, and each call's timing/usage.
Actual inputs, instructions, schemas, outputs and events are preserved separately
in `model-call-1/` and `model-call-2/`. Known usage is summed even when a later call
fails; `usage_complete=false` indicates missing cost information. The guide adds
no gameplay reply fields. Two calls cost more than one; catalog size alone does
not demonstrate a token saving or better play. Offline tests prove delivery and
contract validity, not victories or successful native garrison/interception.

The experience library and its existing tools are independent of this guide.
