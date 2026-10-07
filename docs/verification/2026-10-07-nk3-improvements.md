# Nullkiller3 improvements: verification, 2026-10-07

Base: `909bf56823b018712a35229c9c9204b6a544a0f1`. Scope follows the updated
`docs/plans/2026-10-07-nullkiller3-koniczyna-improvements.md` and the user's explicit implementation request.
The original historical game was not reanalysed. Initial existing overlay work and
ownership were recorded in `.build/koniczyna-resume-base.json`; the supplied plan
remains user-owned and is excluded from the implementation commit.

## Changes and boundaries

Battle start snapshots capture the actual own actor, side, execution origin,
accepted revision and selected native route. A NK3-only hook on actual ExecuteHeroChain::accept
captures the currently executing path, including chain participants; Composition ancestry
is never used as the selected forecast.
Incoming attacks have no outstanding campaign goal or selected route; interrupted
or restored battles without a proven start have unknown origin. Existing result
goal/revision use the start snapshot. Origin, position, side and forecast enter
logs and the learning journal only after recordResult; saved/model memory is unchanged.
Reports preserve unit casualties, loss value, outcome and incomplete retreat cost,
with `route_estimate_not_single_battle` for whole-route forecasts.

The instruction procedure now has explicit helper-loss review, decisive offense,
and defense/departure comparisons. Existing guide cards, answer schema, validators,
loss formulas, native commands, budgets, ordinary/local risk and save format are unchanged.

## Native proof and build

The reused pinned engine is `6a1ca68e00f540087f35579c62ffaf037f5be269`;
generated source and incremental build are under
`/Users/serhiimytakii/CodexWork/2026-10-07/vcmi-issue17/.build/{source,mac}`.
Only authoritative repository overlay/patch files define the change.

Commands/results (logs under `.build/`):

- `cmake --build <mac> --target vcmiclient vcmiserver -j 4`, then `cmake --install <mac> --prefix .build/improvements-stage`: passed, Release arm64.
- Ad-hoc `codesign --verify --deep --strict`: passed; install produces relocatable Frameworks/rpaths. Existing duplicate-library/stale-search-path linker warnings did not prevent build or private runtime.
- `git apply --reverse --check engine/integration.patch` in generated source: passed.
- `test_nullkiller3_battle_callbacks.py` with `VCMI_NK3_NATIVE_BUILD=<mac>`: passed. Public accept changes revision 1 to 2 between callbacks; queued result retains 1. Incoming attack and missing-context cases preserve empty goal and memory isolation. No production export/test hook was added.
- `test_nullkiller3_battle_attribution.py` with `VCMI_NK3_STRATEGY_CONFIG=.build/koniczyna-proof-final.json`: 2 live tests passed. `nk3-battle-attribution-48lxr4qg` proves actual attack on helper; `nk3-battle-attribution-3n7dhv_r` proves named interception/selected forecast and receipt retained after later revisions.
- `test_nullkiller3_policy.py -k stops_the_old_composition` with final-stage config: passed, `nk3-risk-policy-we5mcdy_`.
- `test_playtesting.py`: 33 tests, 31 passed, 2 opt-in transport ownership tests skipped in this invocation. Report tests cover legacy unknown fields and incomplete retreat cost.
- Full discovery: 320 tests, 150 opt-in skips; initial invocation had only 12 missing exchange-driver method errors (14 including subtests). All 12 were rerun with EXCHANGE_DRIVER pointing to the existing issue17 transport build and passed. Combined results cover all 170 executed methods; the initial full-suite log retains its setup errors.

Final build provenance is `.build/improvements-build-receipt.json`. Tests use
private profiles, sandboxed filesystem writes, guide/rules on and experience off.
All completed runtime checks preserve installed profile files and clean their processes.

## Actual model/native scenarios

All cases use gpt-6.1-sol low, existing tester/recorder/native executor, game rules
and guide on, and experience off with journal recording. Raw current requests,
responses, guide tool consumption, model metadata and native consequences live in
`.build/playtests/<case>/`; `.build/koniczyna-focused-proof.json` indexes run IDs,
actual codex decisions, replies, cards and battles. Directed setup is not model proof.

| Case | Observed decision and native result |
| --- | --- |
| model-helper-repeated-threat | Despite its early case name, this proves **unknown/historical threat**: confirmed helper loss remains supplied, model reads exploration/defense/endgame, explains unknown origin, chooses a stronger actor/new route for 37 fog tiles; native scouts and later captures. |
| model-helper-visible-repeat | Model reads defense/exploration/endgame after real helper defeat. Keeps surviving weak helper protected and the separate 989900 garrison, scouts with stronger main, then captures. Both real replies include concrete filled defense_exit; no unchanged weak repeat outing. |
| model-helper-reinforced-route | Final binary. Actual helper defeat and native reinforcement receipt coexist in supplied bounded memory. The surviving actor's force rises from 89 to 989989; model promotes it to main and chooses offered 3.15% loss enemy-town capture. Native named battle/capture succeeds, actual casualties value 9988. Cards: endgame/defense/offensive_operation. This is a justified changed-force alternative, not another weak helper scout assignment. |
| model-decisive-risk | Reads endgame, compares offered reinforcement/defense with named interception and dependent base capture. Ordinary policy .25, local .35 versus 31% heuristic. Native executes named interception, then capture; no local grant becomes ordinary risk. |
| model-last-army-refusal | Reads endgame/defense; hopeless attack exceeds the remaining army and 1246 recruits do not establish defense. Chooses valuable 57-tile scouting and explicit town trade; native moves, no compulsory assault. |
| model-useful-return | Model preserves separate garrison while scouting. Native initiative returns to own town and takes actual troops (49495 to 1040641), then model uses fresh reinforcement/18% interception quote; interception and town operation execute. Return was native initiative, not an explicit model recall command. |
| model-late-return | Reads endgame/defense; no offered timely home return, inadequate available recruitment. Model chooses replacement enemy base now and accepts exposed-town risk; native capture executes. |
| model-continued-hold | Reads defense/endgame/offensive guidance; protects last town while recovering 199226 compatible troops, then intercepts. After confirmed interception/preservation completes, reads exploration/endgame and exits hold into supported scouting/capture. |
| model-two-fronts | Three-player fixture. Names remaining hostile force and home exposure, compares late return; executes one interception and one base capture, then continues searching for remaining towns. Own battle/base capture never becomes a premature match-win claim. |

The first eight ordinary focused runs and comparison series used candidate client
SHA256 `59788d473067...`; their instruction file matches the final version.
Afterward, diagnostic-only changes classified no-execution restored attacks as
unknown, removed unproved end revision and included chain participants. Independent Standards review found that the earlier Composition traversal could
select an ancestor/future path. The repair removed that traversal and moved the
snapshot into actual chain execution, without changing commands or selection.
Final client/server were rebuilt; callback and live battle/interruption checks were
rerun, including a composition battle assertion for actual target [7,13,0] and
ordinary .01 allowance. The concrete enemy-shipyard example from review is
currently excluded by NK3 owned-shipyard visibility/placement gates; the live
composition check uses the existing guarded exploration fixture. No claim is made
of live reproduction of an enemy-shipyard prerequisite. Earlier game outcomes are attributed
to their recorded binary, not relabelled as final-binary tournament results.

Setup probes delegate only while the necessary own receipts remain supplied.
Their later deterministic setup replies after history eviction are not counted as
model decisions or match-level acceptance. Failed setup attempts are preserved
as failed evidence and excluded from the successful scenario index. The safe
changed-force run was stopped after the target battle/capture, not counted as a match win.

## New comparison series

Twins.h3m was chosen and its 1v1 roster checked before comparison. Each paired
baseline/candidate preparation has identical map/profile hashes, NK3/NK2 roster,
impossible, declared seeds, gpt-6.1-sol low, guide/rules on, experience off,
130-second decision timeout and 1200-second game cap. Frozen baseline controller
files match main 909bf56. Four games ran concurrently; model service latency and
sampling remain uncontrolled. A declared seed is not independent proof of the
engine's random stream. `.build/koniczyna-comparisons.json` records all four paired
starting-condition checks; `.build/koniczyna-comparison-metrics.json` holds run IDs,
terminal records, model metrics, per-defeat own actors/last observed roles, returns
and resource receipts. Latest observed role may be unknown and is not assumed
from army size. Costs of rehire/retreat and unrelated packet causes remain unallocated.

| Map/seed/version | Confirmed outcome | Last observed day | Defeats | Own casualty value | Fallback / timeout |
| --- | --- | --- | --- | --- | --- |
| koniczyna-42-baseline | unfinished | 30 | 8 | 19735 | 0 / 0 |
| koniczyna-42-candidate | unfinished | 28 | 3 | 31044 | 0 / 0 |
| koniczyna-43-baseline | unfinished | 23 | 5 | 22405 | 2 / 0 |
| koniczyna-43-candidate | win day 22 | 21 | 2 | 29817 | 1 / 0 |
| koniczyna-44-baseline | unfinished | 23 | 2 | 9620 | 1 / 1 |
| koniczyna-44-candidate | unfinished | 27 | 5 | 24582 | 1 / 1 |
| twins-42-baseline | unfinished | 38 | 0 | 0 | 28 / 1 |
| twins-42-candidate | unfinished | 43 | 5 | 20307 | 1 / 1 |

Only candidate Koniczyna seed 43 has reviewed terminal win evidence, day 22,
recorded via tester outcome with the log hash and actual assignments/difficulty.
All other seven matches reached the time cap; they are unfinished, not defeats.
The candidate reduced observed defeats on seeds 42/43 but increased them on 44;
unequal days/unfinished games and substantial baseline Twins fallbacks prevent a
claim of reliably fewer losses or earlier wins. Zero casualties on retreat does
not mean zero recovery cost. Per-actor repeated losses and last observed roles
are retained in the metrics artifact; reconstruction beyond own confirmed receipts
would require assumptions and is not reported as measured restoration cost.

Target scenarios establish reasoned attack/hold/return alternatives, not a numerical
quality score for every tournament delay. No guaranteed improvement is claimed.

Task-owned duplicate licensed Data was removed from 24 completed private run
profiles after process/cleanup checks. Maps, saves, config, raw model exchanges,
logs and learning journals remain; canonical private fixtures retain Data. See
`.build/koniczyna-cleanup.json`. Installed game and original historical run are untouched.

## Concurrent work

While final verification was finishing, a separate user-authorized chat changed
open-map defaults in the shared integration.patch/generated source. This task
preserves those edits. Its reviewed patch is frozen in
`.build/koniczyna-reviewed-integration.patch`; its exact owned review diff is
`.build/koniczyna-owned-review.diff`. The isolated reviewed package was built/installed before the open-map edits and
retained the plan's tested visibility settings. After the separately authorized
open-map change was committed as ccace7c, the delivered package was rebuilt and
installed from the combined current source. Its native attribution, callback and
composition/interruption checks were repeated with VCMI_AI_OPEN_MAP=0; the default
open-map setting can be disabled for these original comparison conditions.
Integrated build/install/test logs use `.build/koniczyna-integrated-*`; the final
build receipt identifies the delivered package and complete current patch. The final
changed-force model/native run `29fc0f98ab744e78b12c318a6a675e0d` uses final client
`c537c3f7faef62e4d43d63489c9a16861b1a8135e06ee82dbed9dbe90ba32376` and confirms
real local capture forecast, actual casualties and completed native battle.
Other-chat files and open-map changes are already committed independently and
are excluded from this task's commit delta. Earlier model/comparison binary IDs
remain immutable; they are not represented as integrated-default-open-map results.

Delivered client SHA256: `bb86f7364b190b02fe10a570a4e1e9ac8e6aeedeeeab8dbffa069c7fdd327b80`.
Integrated live runs: `nk3-battle-attribution-nwj2j69m` (incoming), `nk3-battle-attribution-5ic2m3wx` (interception), `nk3-risk-policy-e7c27qku` (composition/interruption); all passed, with protected files unchanged and completed cleanup.
