# Nullkiller3 global strategy: source verification

Date: 2026-10-07. Plan: `docs/plans/2026-10-07-nullkiller3-global-strategy.md`.

## Implemented

- Player-visible strategic map overview, deterministic coverage/caps and conditional effective-income preview. Existing pathfinding and execution remain native owners.
- One persisted selected course, native predicate progress, exact operation/receipt bindings, atomic course/operation validation and independent course recovery from invalid saves.
- Course/progress in subsequent requests, event-driven reconsideration, milestone candidate pins and accepted/rejected decision records.
- Ordinary artifact admission and acknowledged pickup evidence tied to the exact own inventory instance.
- Always-loaded instructions contain the protocol contract. Initial comparison, planning horizon, transition cost and economic advice live in the conditional `global_strategy` Guide card.

## Proof

Focused standalone tests use the existing engine JSON library and fresh test executables; no client/server/game package was built.

- Controller, Guide, prompt-context and artifact tests: 42 tests, 39 passed, 3 skipped because private recorded fixtures are absent.
- Strategic map/candidate/income/request-cap suite: 17 passed.
- Fresh strategic-intent driver: contract, predicate progress, exact receipt matching, operation replacement and value save/restore passed.
- Fresh campaign driver: default and defense-exit checks passed.
- Fresh idle driver: blocked scouting correction and repeat suppression passed.
- Syntax-only compilation checks cover NativeCampaign, NativeCampaignStrategy, StrategicDecision and PlayerView.
- Guide test exercises actual conditional card delivery in the same model call.
- Review found the previous 8192-byte transport cap rejected valid larger courses. A standalone subprocess regression reproduced that failure. NK3 now requests a 32768-byte reply allowance plus 1024 bytes for usage/framing; other callers retain their default cap. The repaired global-course/transport suite passes all 25 tests, including an actual valid UTF-8 course over 8192 bytes, exact byte-boundary rejection, cancellation and timeout.

Commands: `python3 -m unittest` for `test_global_strategy_controller`, `test_nullkiller3_controller`, `test_strategy_guide`, `test_helper_hiring_controller`, `test_keymaster_controller`, `test_goal_risk_controller`, `test_prompt_context`, `test_artifact_visit_receipts`; separately `test_strategic_candidates` with `STRATEGIC_CANDIDATES_DRIVER` set to the fresh driver. Standalone native drivers link the existing `libvcmi.dylib`; source checks use `c++ -fsyntax-only` with the existing engine include paths.

## Limits

The user explicitly excluded a new game build. No game was launched, restarted or modified, and no live-model acceptance run was performed. Actual game-process save/load, artifact pickup hooks and long-run strategy quality remain unverified at runtime. Value-contract tests are not a substitute for those checks or a claim of victory.

Concurrent income/Guide work was committed separately during implementation. Final review is based on HEAD `af0de056de70eab9a003d64b44760bdea23000e4`. Remaining unrelated defense-card and Koniczyna-plan edits are excluded. Focused proof uses a source snapshot containing this change and committed reference cards, to isolate those edits.

## Review

Independent Spec and Standards reviews completed. The transport-limit blocker was repaired, reproduced through the real subprocess boundary, and approved by fresh targeted Spec and Standards reviewers. No blocking findings remain in the reviewed change.
