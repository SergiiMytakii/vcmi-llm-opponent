# Nullkiller3 strategic review loop: verification, 2026-10-09

Scope: the explicitly authorized implementation of
`docs/plans/2026-10-09-nullkiller3-strategy-review-loop.md`, based on
`b97db768576893f2fac6495c572e57a09950cada`. Implementation verification preceded
the user's later authorization to commit all remaining changes. No push,
installed-game update or user-session takeover was performed.

## Behavior

Dispatch suppresses the same facts for the current own turn; it does not close
the question. Failed, cancelled or restored exchanges retain their question for
the next permitted turn. Version-1 arbiter saves remain readable; version 2 saves
attempts separately from accepted coverage. Accepted no-progress coverage names
the exact question/facts, unfinished milestone, installed revision and active
goals. A goal exit, disappearance or revision change reopens it. Invalid optional
coverage is dropped without discarding the native namespace. Partial background
admission closes only the covered subjects.

Controller and native weaker-main admission use existing fresh native attack and
reinforcement quotes, including packed whole stacks, retained floors, deadline,
loss authorization and unchanged source commitments. Stable protocol-2 semantic
refusals carry exact identity and bounded usage through subprocess, native
feedback persistence and the next request. Protocol 1 and transport-error trust
remain unchanged. Ended decision-basis questions close through their actual actor;
townless questions require supported recovery or regained ownership.

Guide cards compare a named attack and local risk with actual protection benefit,
delay and exit. An ordinary loss ceiling and the model's temporary hold floor are
revisable choices. Native formulas, commands, risk authority, budgets and model
settings remain unchanged. The largest permitted Guide result is 8176/8192 bytes.

## Tests and build

Compact provenance, requests, every recorded wait/refusal, readiness quotes,
milestone stall observations, losses and exact operation chains are in
`.build/strategy-loop/verification.json`; original logs and snapshots are retained.

- Original unchanged RED reproductions were run before editing. The unresolved
  review now passes; the captured day-2 weaker-main answer now receives the same
  stable rejection in Python and native. Regressions also cover supported weak
  attack/interception/delivery, stale arrival, indivisible source-floor packing,
  missing routes, excessive losses, lost actors, coverage and optional saves.
- Final contract suite: 60 passed; native value CTest: 7 passed. Seven Guide
  subprocess tests passed after the final text refinement.
- Actual native caller proves refusal feedback, next-turn reappearance, admitted
  correction and execution. An in-flight save/load test proves current-turn
  suppression and next-turn admitted attack; the interrupted answer executes no
  command. Console saving uses the existing windowed save-test route; the initial
  headless console-save probe crashed and is retained as a failed diagnostic.
- Actual preparation exit releases its hold while independent delivery completes.
  Partial/allocation background callers and covered-ready-task caller pass.
- Full discovery: 456 tests, 166 opt-in/platform skips. All remaining setup errors
  came from the absent default exchange-driver path (20 errors including subtests,
  one module); all affected transport tests passed in the configured 66-test rerun.
  An earlier missing Boost include path was resolved using the existing dependency
  cache; all 36 affected native forecast cases passed. Logs retain failed setup
  attempts as well as their successful reruns.
- Reused pinned VCMI source `6a1ca68e00f540087f35579c62ffaf037f5be269`, incremental
  macOS arm64 build and Conan cache. Authoritative overlays match generated source.
  Client/server build, isolated install and strict signature verification pass.
  Candidate runtime: `.build/strategy-loop-runtime/VCMI.app`; controller snapshot:
  `.build/strategy-loop/candidate-guide-source/controller`.

After these builds/games, the separate user-authorized chat
«Исследуй архитектуру кодовой базы» began extracting request assembly into
`StrategicRequest.cpp/.h` and changed the shared `NativeCampaignStrategy.cpp`,
integration patch and test-build files. Those edits were preserved. These game
and build claims refer to the exact tested native source retained in
`.build/strategy-loop/native-source/NativeCampaignStrategy.cpp`, matching its
original receipt hash, and the unchanged signed candidate runtime. They do not
claim verification of the other chat's in-progress refactor.

## Real-model games

Three completed comparisons use the same map/profile hashes, opponents, difficulty,
declared seed per pair, limits and `gpt-5.6-terra` with effort `none`; Guide/Rules
are on and experience is off. Baseline uses archived b97 controller **and tester**.
Candidate uses final native code and final Guide. Different case labels cause the
generic comparison helper to reject the labels: its raw result is retained.
The receipt separately verifies every material start/settings field; `case_id`
is bookkeeping and is not consumed by the launcher. Manifests were not rewritten.

| Declared seed | Baseline native victory day | Candidate native victory day | Baseline own battle loss value | Candidate own battle loss value |
| --- | ---: | ---: | ---: | ---: |
| 42 | 4 | 3 | 6451 | 2937 |
| 43 | 23 | 4 | 23296 | 9895 |
| 44 | 11 | 4 | 12838 | 9529 |

The completed mirrored baseline wins on day 29; the mirrored candidate wins on
day 2, loss value 6732. The executable
controlled attack on the blue start wins on day 3, loss value 2937; it is a
scripted feasibility control, not a model result.

Large-army acquisition is observed on day 1 in each comparison. First captured
current-army town-route quotes occur on baseline days 1/2/8 and candidate day 1
in all three; absence of an earlier detailed quote is an observation gap, not
proof of physical impossibility. All quotes remain conditional. Maximum recorded
decisive-milestone stalls are baseline 2/21/2 days and candidate 2/2/2 days; missing
intermediate model observations are not counted as confirmed daily progress.

Exact positive chains, not nearby timestamps:

- Candidate 42: day-2 commitment/victory-target request installs
  `capture_enemy_town_d3`, revision 3, actor `object:4`; acknowledged movement is
  sequence 12. Day-3 accepted revision 4 of that operation owns native battle
  result sequence 17 and the observed newly owned town; terminal confirms victory.
- Candidate 43: day-3 completed-milestone/campaign-exit review installs
  `capture_enemy_town`, revision 5, actor `object:0`; acknowledged movement 17,
  native battle result 19 and day-4 terminal. The completed hold is replaced by
  a named 19% local-risk attack.
- Candidate 44: day-3 campaign-exit/victory-target request installs
  `capture_enemy_town`, revision 4, actor `object:4`; acknowledged movement 18,
  native battle result 20 and day-4 terminal. The day-2 defense exits before attack.
- Mirror: day-1 safety review installs `capture_town`, revision 2, actor `object:4`,
  acknowledged movement 10; day-2 accepted revision 3 owns battle result 14 and
  terminal victory. Source requests/replies and native records establish identity.

Terminal visits are interrupted by game end and recorded `reconciled_unknown`;
their ownership snapshots are observed state, not confirmed command completion.
Native own battle results and prior acknowledged movement establish execution.
The receipt preserves that distinction.

Earlier candidate revisions are excluded from the final comparison, including a
26-day run that repeated empty defense extensions. Its concrete alternatives
motivated the final Guide refinement; it was not hidden or counted as success.
Diagnostic old-baseline runs recorded with the current tester are also excluded.

These artificial small-map games demonstrate the requested concrete escape from
the observed deadlock. They establish neither win rate nor deterministic RNG,
general superiority or Windows runtime behavior.

## Independent review

Initial independent Spec and Standards review identified quote-consistency and
ended-question closure defects. Both were repaired and approved by fresh targeted
Spec and Standards reviewers. A fresh targeted Standards review approved the final
Guide refinement and its byte limits. Final targeted gameplay/caller/Guide Spec
review approves the pinned tested target, with the concurrent-refactor limitation
above. No verified blocker or required-proof gap remains in this plan's scope.

Completed owned test profile copies were removed after process cleanup and proof
collection; compact logs, manifests, exact source/controller snapshots and named
in-flight save evidence remain. APFS clone removal reduced logical test storage;
it is not a claim that the same number of physical bytes was reclaimed.
