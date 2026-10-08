# Nullkiller3 background planning: local evidence

Implemented the approved 2026-10-08 background-planning plan. Background protocol-2
`prepare_next_turn` calls use `gpt-5.6-terra` with effort `low`; ordinary gameplay
calls retain `none`. Each model call has its own 60-second deadline, with recorder
and native bounds of 70/80 seconds. Saved daily time balances cannot veto a new
strategic question.

The serialized own-turn owner publishes a value snapshot before ending its turn.
Opponent callbacks only take that publication and start transport. A detached,
cancelable attempt has no planner/game pointers; its process-wide lease survives
until actual transport cleanup finishes. Own-turn admission never joins it.
Positive safety uses existing current visibility, native neutral screens and
bounded stationary defense. An empty observed threat list under fog is insufficient.
An open approach's conditional movement scenario is not a safety bound and cannot
qualify a route for background planning.

## Real model and native execution

- `.build/background-proof/real-positive-safety-low/run`: complete native visibility
  established the empty-front basis. The real model answered during the opposing
  turn with effort `low`. Native admission installed the next-day plan and the
  `guild_2` build receipt reports `effects_observed`. There was no ordinary player-0
  request on day 2. Opening setup and the slow opponent were controlled fixtures.
- `.build/background-proof/real-threat-supported/run`: the original supported
  offensive goal moved the army on day 1. After the snapshot, the opponent
  reinforced its hero. A real background `low` reply was available, but the new
  critical day-2 question canceled it. The real foreground model used `none` and
  native admission accepted its current defense plan. The `defend_base` movement
  receipt followed that acceptance; no old offensive command executed on day 2.

Both runs completed cleanup and reported `protected_files_unchanged: true`. They
prove these execution sequences, not stronger strategic quality or a win rate.

## Controlled actual callers

The tests use separate maps/profiles and normal native callbacks, observation,
admission, arbiter, subprocess transport and receipt paths.

- `.build/background-barriers-final.log`: three cases passed. Allocation run
  `native-background-allocation-6jzdhml7` captured `checkpoint:allocation`, then
  admitted a routine building/reserve that removed the recalculated choice. The
  original question reached foreground transport with the installed commitments
  before any prepared expense. Partial run `native-background-partial-u1qnz3r8`
  retained the independent hero and town groups, rejected the second hero after
  the enemy removed its native neutral screen, and supplied that hero's residual
  routine question and accepted reserves to foreground transport. Stabilization
  run `native-background-stabilization-2tiywypj` retained the critical question
  after an acknowledged urgent recruit made the current defense sufficient.
- `.build/background-coverage-callers.log`: the final rebuilt actual partial
  caller, `native-background-partial-0i41zugj`, closes the accepted hero and town
  questions independently. The rejected secondary hero's and unassigned town's
  original questions remain, along with any fresh current questions. The same
  assertion first failed on the previous binary in
  `.build/background-coverage-red.log`.
  All five caller tests passed (eight scenarios, 100.173 seconds), including fresh
  allocation `native-background-allocation-d9_tp_k4`, stabilization
  `native-background-stabilization-shr3joeg`, ready admission and the four fallback
  variants. Each run completed cleanup with protected files unchanged.
- `.build/background-barriers-repair.log`: ready, pending, crash, malformed and
  oversized transport cases passed. Ready admission executed without a second
  request; every error/pending case started an actual ordinary request.
- `tests/background_exchange_driver.cpp` and `tests/test_process_exchange.py`:
  a concurrent sleeping background child cannot retain foreground pipe handles
  or delay foreground completion/destruction. Actual shared transport also starts
  after a prior 60-second charge, exhausted saved daily time, and spawn failure;
  repeated identical facts remain deduplicated.
- `tests/test_background_native.py`: value-contract checks cover keep/revise,
  independent and dependent groups, shared treasury, completion/expiry, identity,
  semantic bindings, positive/unknown safety, movement refill and changed fronts.

## Build and limits

Client and server were rebuilt from the authoritative overlays and integration
patch in the reusable macOS tree, then installed to
`.build/background-runtime/VCMI.app`. Build/install logs are
`.build/background-repair-build.log` and `.build/background-repair-install.log`.
Existing linker warnings did not prevent either target from building.
The final isolated runtime additionally contains the per-participant coverage
repair and removal of the conditional movement-scenario safety branch; build and
install logs are `.build/background-coverage-build.log` and
`.build/background-coverage-install.log`.

The post-review non-runtime Python suite passed
(`.build/background-tests-after-review.log`: 415 tests, 171 environment-gated skips,
244 executed); standalone CTest passed 6/6. The final focused safety, controller
and transport suite passed 35/35 (`.build/background-coverage-focused.log`). The
new route-safety regression first failed on the previous implementation
(`.build/background-safety-red.log`). Actual isolated caller checks run separately.
Windows runtime and human play are outside this local proof.

The older `test_nullkiller3_checkpoint.py` fixture failed its assertion that no
request occurs before the release day: it seeds a campaign without a selected
global course and receives existing opening/defense questions. It supplied no
background admission and is not acceptance evidence. The dedicated new allocation
case above proves the required background/foreground sequence.

Pre-existing user plan and independently committed neutral-count/opponent-key
changes were preserved. No push, deployment or user-game restart was performed.
Completed invocation-owned test profile copies were removed after verification;
decision snapshots, manifests and runtime logs retain the evidence. The reusable
licensed base fixture and fresh stable runtime remain available.
