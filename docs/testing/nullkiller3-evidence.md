# Nullkiller3 implementation evidence

Implementation in progress, 2026-10-05. This is evidence of completed checks,
not a claim that the full Nullkiller3 plan is implemented.

Worktree: `codex/nullkiller3`; project base `202bc9d`. Pinned VCMI revision:
`6a1ca68e00f540087f35579c62ffaf037f5be269`. The installed user game and its
running match have not been replaced. No commit, push or main merge occurred.

## Native boundary

- Current shared building/recruitment/delivery forecasts passed the paired
  privacy checks again in 122.149 seconds: six native worlds and twelve
  model/timeout worlds, including actual movement. Evidence:
  `.build/evidence/nk3-enemy-units-visibility-proof.log`,
  `.build/playtests/nk3-visibility-d8y7c6xg`,
  `.build/playtests/nk3-model-visibility-6sqy3log`.
  A preceding real regression exposed enemy category bounds using static
  creature AI values while own armies used the pinned combat-value table:
  100 visible pikemen had lower bound 8000 instead of 8900. Both now use the
  public combat-value table; the horde interval is 8900..22161. Evidence:
  `.build/evidence/nk3-enemy-units-native-red.log`.
  The current three public C++ contract drivers also pass:
  `.build/evidence/nk3-current-contract-proof.log`.
- `scripts/prepare_engine.py .build/nk3-prepare-proof` prepared a fresh pinned
  checkout with the integration patch and project-owned NK3 sources.
- Release client and server builds completed. Proper CMake installation produced
  private, signed macOS bundles with rewritten dependency paths.
- The unchanged baseline rejects `Nullkiller3`; the new bundle reports the
  requested red `Nullkiller3`, blue `EmptyAI` assignments.
- `VCMI_NATIVE_VISIBILITY_CONFIG=.build/baseline-integration.json python3 -m
  unittest discover -s tests -p test_native_visibility.py -v` passed the real
  ExternalAI baseline visibility test. That is separate from NK3 proof.
- `VCMI_NK3_NATIVE_CONFIG=.build/nk3-native-config.json python3 -m unittest
  discover -s tests -p test_nullkiller3_native.py -v` passed six real worlds in
  40.666 seconds. Hidden changes, inserted/removed hidden objects, and a changed
  exact count within one visible category produced equal native inputs and
  selected tasks before and after hero movement. A different visible category
  changed the evidence. Runs used no controller decisions and protected-file
  checks passed. Evidence: `.build/playtests/nk3-visibility-_d8ex7df` and
  `.build/evidence/nk3-native-visibility-final.log`.
- A stale visible-tile snapshot initially crashed after a resource was removed.
  NK3 now rebuilds command paths from fresh visible tiles. The passing fixture
  covers this transition.
- NK2 on the same map/seed in baseline and new bundles produced the same 68
  logged task/build/movement/turn actions. Evidence:
  `.build/evidence/nk2-baseline-comparison.json`. This checks that scenario, not
  every possible NK2 behavior.
- Shared process transport: 12 tests passed, including cancellation, timeout,
  output limits and descendant cleanup. Evidence:
  `.build/evidence/shared-transport-python.log`.

## Native campaign checks

- A restored unfinished task no longer proves uninterrupted preservation from
  its endpoint. The retained intention records `force_continuity_unconfirmed`,
  keeps safe survivor movement available, and releases the reservation after
  expiry without inventing an actual loss. The real save-inside-movement
  regression first falsely completed the interval. All three execution
  scenarios then passed in 47.613 seconds, including useful fresh tasks after
  load: `.build/evidence/nk3-force-continuity-current-red.log`,
  `.build/evidence/nk3-force-continuity-final-proof.log`. Three C++ contract
  drivers also passed, including serialization, deadline release and malformed
  interval rejection: `.build/evidence/nk3-force-continuity-contract-proof.log`.
  Packet minima between native persistence boundaries are transient; an unknown
  restored interval is explicitly unproved rather than fabricated as intact.
- Bounded urgent recruitment now completes before a strategic external wait.
  A slow-controller regression previously reached a request with no native
  defense consequence. All three defense scenarios passed after reordering in
  18.759 seconds, including reserve-override accounting, a model snapshot after
  acknowledged recruitment, and suppressing an unnecessary weak-front review:
  `.build/evidence/nk3-stabilize-before-wait-red.log`,
  `.build/evidence/nk3-stabilize-before-wait-green.log`.
  The three current force-history/survivor scenarios also passed in 31.527
  seconds: `.build/evidence/nk3-stabilize-before-wait-survivor-proof.log`.
- A failed preservation releases its live hero/force reservation after the
  deadline while retaining the observed minimum and failure cause. Three real
  games passed, including a survivor's safe return after a stale model reply
  and continuing through day seven: 31.564 seconds,
  `.build/evidence/nk3-force-expiry-real-proof.log`. The preceding public
  regression failed because the expired obligation still held the hero;
  all three C++ contract drivers passed after repair:
  `.build/evidence/nk3-force-expiry-red.log`,
  `.build/evidence/nk3-force-expiry-green.log`.
- The final independent-event fixture passed both real scenarios in 22.543
  seconds: three accepted critical reviews during one turn and no repeated
  request for an unchanged blocker. Evidence:
  `.build/evidence/nk3-three-events-final-proof.log`. Its controller is
  deterministic; this is not evidence of three paid provider calls.
- The latest ordinary bundle passed both building/delivery campaign scenarios
  (34.689 seconds) and the shared-result plus waiting-save/load scenarios
  (28.830 seconds). Evidence:
  `.build/evidence/nk3-force-expiry-campaign-recovery-proof.log`,
  `.build/evidence/nk3-force-expiry-execution-lifecycle-proof.log`.
  The command-interruption case requires a separate private probe and was
  skipped in these ordinary-bundle runs.
- The public C++ value contract checks typed goals, capability requirements,
  dependency cycles, parallel hero conflicts, resource reservations and factual
  completion. It rejects invalid proposals atomically.
- The contract driver passed dependency unlocking, completion-driven reserve
  release and restoring a completed building from serialized state. Evidence:
  `.build/evidence/nk3-contract-proof.log`.
- A deterministic campaign built Castle Mage Guild I on day 1 and Mage Guild II
  on day 2, independent of NK2's ordinary selection. The second building's
  `[5,4,5,4,4,4,2000]` resource reserve survived other purchases and pickups,
  then released on observed construction. No model was called.
- `VCMI_NK3_CAMPAIGN_CONFIG=.build/nk3-campaign-config.json python3 -m unittest
  discover -s tests -p test_nullkiller3_campaign.py -v` passed the real save/load
  building test in 21.192 seconds. A day-1 save loaded with the first construction
  complete, retained the second goal, and did not replay the first building.
  Evidence: `.build/playtests/nk3-campaign-kqp2g77q`.
- A real hero chain delivered from Christian to Catherine: recipient army value
  increased from 7146 to 14978; courier retained 1068 against a force floor of
  1000. Evidence: `.build/evidence/nk3-delivery-reserve-results.json`.
- Initial force-preservation behavior repeatedly revisited the occupied town.
  The corrected player holds beside the town: courier movement stayed at 737
  while the main hero continued useful actions. Evidence:
  `.build/evidence/nk3-delivery-hold-results.json`.

- The final native campaign integration suite passed both real scenarios in
  38.685 seconds: near and multi-day distant delivery, force preservation,
  return/holding without repeated visits, and building save/load. Evidence:
  `.build/evidence/nk3-native-campaign-restore-neutral.log`,
  `.build/playtests/nk3-delivery-2j4lyn0_`,
  `.build/playtests/nk3-campaign-2fzpjpvt`.
- A far-route regression exposed reversed handoffs when the recipient moved
  into the courier. The gateway now follows the accepted delivery obligation
  regardless of which participant moved. Both army conservation and the
  courier's force floor are checked through actual game results.
- Malformed saved campaign/status records are rejected before intentions are
  restored. The real load initially exposed VCMI's unflaggable owner `-2`;
  the validator now accepts that public owner value. Public contract proof:
  `.build/evidence/nk3-contract-restore-neutral-proof.log`.
- Request arbiter save/load proof passes: pending exchanges reserve their entire
  possible wait/token cost before dispatch. Restoring cannot refund an unknown
  exchange or repeat the same question. Three independent events still permit
  three revisions. `.build/evidence/nk3-arbiter-restore-proof.log`.
- Playtest manifests distinguish `nk3_mode: native|model`; ambiguous modes are
  rejected before preparation. This is provenance support, not model proof.

## Strategic exchange checks

- The existing subscription controller now accepts a protocol-2 strategy request
  without offered action IDs. The model contract creates typed goals, roles,
  alternatives, evidence references and reconsideration conditions. Controller
  tests pass valid plans and reject stale identity, unsupported capabilities,
  invalid policy and unsolicited commands. Evidence:
  `.build/evidence/nk3-controller-compact-proof.log`.
- The real-engine recorder fixture passed valid model-authored construction,
  stale response, unsupported capability and timeout in 29.089 seconds. Invalid
  plans were not installed; native construction continued; the failed opening
  question was not repeated. Independent newly observed enemy fronts remain
  distinct questions. Evidence:
  `.build/evidence/nk3-strategic-engine-probe-final.log`,
  `.build/playtests/nk3-strategy-5n4iasaz`.
- The gateway releases its shared game-state lock during the one-shot exchange,
  checks identity and relevant observed facts after reacquiring it, refreshes
  native state, and builds tasks afresh. Closing/terminal callbacks cancel the
  shared transport. Save-during-wait, graceful closing/load and actual turn-loss proof are recorded below. Pending native-command recovery still requires proof.
- First real model request timed out at the existing 60-second controller limit;
  no campaign was installed. Evidence: `.build/playtests/nk3-first-live`.
  A separate minimal request through the same subscription controller succeeded
  in 5.377 seconds with actual usage of 9147 input and 27 output tokens. Provider
  access works; the fourth real strategic run below proves acceptance and execution.

- Fourth real model run accepted revision 1 in 42.876 seconds with 12,132 actual
  input/output tokens. Its `archer_development` and `discover_east` goals were
  absent from the initial completion state, linked to actual executed native
  tasks, then completed by observed predicates. Evidence:
  `.build/playtests/nk3-fourth-live`, `.build/evidence/nk3-fourth-live-driver.log`.
  Earlier attempts exposed an invalid scout predicate, unsupported Grail
  building classification and UTF-8 text-size mismatch. Closed goal schemas,
  public building support and character/byte limits now reject these safely.
- Real lifecycle proof passed in 24.174 seconds: save during the unlocked wait,
  graceful console shutdown cancels the exchange, exits without applying a
  strategy, and loading that save does not replay its unknown opening request.
  Useful native play continues. Evidence:
  `.build/evidence/nk3-lifecycle-green.log`,
  `.build/playtests/nk3-lifecycle-9koi9bab`.
  Console shutdown now dispatches through the existing main-thread queue; the
  prior command threw on its console thread and crashed before AI teardown.
  NK3 turn workers serialize before resetting interruption, and all exchange
  exits settle the live arbiter's in-flight state.
- Separate test-only lifecycle bundles issue real EndTurn packets through the
  callback. During a slow model wait the request cancels and day 2 performs
  fresh native work (9.713 seconds). During an acknowledged hero movement the
  chain interrupts; no native task or movement occurs after server turn loss
  before day 2, whose first snapshot matches the acknowledged position
  (10.912 seconds). Evidence: `.build/evidence/nk3-turn-loss-game-proof.log`,
  `.build/playtests/nk3-turn-loss-n1buwb_f`,
  `.build/evidence/nk3-movement-loss-game-proof.log`,
  `.build/playtests/nk3-movement-loss-h6ii7s2f`.
  Probe provenance records the test-only factory and exact source restoration.
  Ordinary prepare/build does not include the fixture.
- Command gates run at mutable packets and within compositions/hero-chain
  nodes. The ordinary bundle passed delivery, construction/save-load, actual
  helper loss and strategic wait/save-load (4 tests, 69.101 seconds):
  `.build/evidence/nk3-command-gates-game-proof.log`.
- Saved NK3 aliases, namespace collections and role metadata are checked before
  restoring intentions. Malformed references discard their dependent intent
  and facts while retaining experience ownership and spent request budget;
  unknown root/budget shapes permit native continuation only. Contract proof:
  `.build/evidence/nk3-namespace-contract-final-proof.log`.
  Ordinary construction/save-load and model-wait/save-load remain valid
  (2 tests, 45.124 seconds): `.build/evidence/nk3-namespace-game-proof.log`,
  `.build/playtests/nk3-campaign-lc0uirck`,
  `.build/playtests/nk3-lifecycle-y15ffqsc`.
- A diagnostic controller exposed repeated repair questions when the model
  merely renumbered an unchanged blocked scout goal. Repair events now aggregate
  goal semantics and blocker causes, excluding revision, goal ID, deadline
  renewal and prose. Contract proof preserves independent target changes:
  `.build/evidence/nk3-repair-signature-contract-proof.log`.
  Real renumbered-plan continuation passed in 14.752 seconds:
  `.build/evidence/nk3-repair-signature-game-proof.log`,
  `.build/playtests/nk3-critical-events-k3y_x1mq`.
  The separate three-critical-front episode has not passed; current diagnostics
  are `.build/evidence/nk3-frontier-critical-events-game-proof.log` and
  `.build/playtests/nk3-critical-events-mwt6kfkl`. It produced two critical
  reviews on different days, so it is not evidence for three in one turn.

## Forecasts and current visibility proof

- Own-resource forecasts include protected funds, building prerequisites and
  one construction per town per day. Own recruitment exposes current stock,
  costs and the next weekly growth. These conditional branches exclude unknown
  pickups, trades and other spending. Contract proof:
  `.build/evidence/nk3-build-schedule-green.log`.
- Real resource goals require the engine's confirmed pickup event; existing gold
  cannot prove a pickup. Five strategy-boundary cases passed in 36.370 seconds:
  construction, resource pickup, stale reply, invalid capability and timeout.
  `.build/evidence/nk3-schedules-strategy-proof.log`,
  `.build/playtests/nk3-strategy-fuovf5ev`.
- Enemy army observations now expose UI category intervals. Native safety uses
  the visible upper bound, with an explicit conservative sentinel for unbounded
  observations. Enemy speed, bonuses and intention remain unknown. Threat
  scenarios based on distance are assumptions, not measured enemy ETAs.
- Six native visibility worlds passed in 39.974 seconds after these changes:
  `.build/evidence/nk3-schedules-visibility-proof.log`,
  `.build/playtests/nk3-visibility-_krnnwy5`.
- Twelve real model/fallback visibility runs passed in 87.441 seconds. Requests,
  native choices and movement match across equivalent permitted observations,
  including hidden insertions/removals and counts inside one visible category.
  A different visible category changes evidence. Timeout continues useful native
  play. `.build/evidence/nk3-model-visibility-proof.log`,
  `.build/playtests/nk3-model-visibility-v_t81fun`.
- A real economic episode initially reported an unfunded City Hall because of
  insufficient wood. After native resource collection, the conditional forecast
  predicted day 5; actual prerequisites and City Hall completed on day 5 while
  preserving 1000 gold. Passed in 13.066 seconds:
  `.build/evidence/nk3-economy-game-proof-final.log`,
  `.build/playtests/nk3-economy-wd3n6i_3`.

## Logistics refinements

- Source heroes and dependency-waiting participants retain their obligations.
  The force ledger protects the promised reinforcement from unrelated transfers
  and releases that pledge only to its delivery, preserving other force floors.
  Helper replacements are tied to the revision and reused while still owned.
  Public contract proof: `.build/evidence/nk3-logistics-contract-final.log`.
- Shared bounded memory retains active native campaign targets among 160 newer
  sightings. The regression failed before retention and passed afterward:
  `.build/evidence/nk3-retained-memory-red.log`,
  `.build/evidence/nk3-logistics-memory-final.log`. The default ExternalAI caller
  retains the same behavior.
- Holding the commitments exposed disconnected known routes: previously,
  unrelated fallback movement happened to reveal the way. Native route repair
  now deliberately advances a participant to a safe known frontier toward its
  destination, then recomputes the route. This geometry ranks a discovery step;
  it does not claim an unknown route is open. Both delivery/save-load scenarios
  passed in 37.624 seconds, with distant delivery on day 3:
  `.build/evidence/nk3-route-repair-campaign-proof.log`,
  `.build/playtests/nk3-delivery-3iog4n2i`.
- A separate real-battle fixture loses Christian, replaces him with Adela and
  completes the handoff to the original recipient. The isolated episode passed
  in 8.326 seconds with army conservation:
  `.build/evidence/nk3-helper-loss-game-proof-isolated.log`,
  `.build/playtests/nk3-helper-loss-93pu3dcw`.
- A named delivery now additionally requires an acknowledged handoff receipt.
  Recruitment reaching the army threshold alone fails the completion predicate;
  a completed saved delivery without its receipt is rejected. Red/green proof:
  `.build/evidence/nk3-confirmed-delivery-red.log`,
  `.build/evidence/nk3-logistics-contract-final.log`. The final receipt build
  passed all three real scenarios in 45.368 seconds, including actual recipient
  gain, donor decrease, the deadline and force floor:
  `.build/evidence/nk3-logistics-final2-game-proof.log`,
  `.build/playtests/nk3-delivery-xch18hdu`,
  `.build/playtests/nk3-campaign-16sb4zic`,
  `.build/playtests/nk3-helper-loss-6_80_ckg`.
- A distant replacement is held at a second owned town before the original
  courier dies in battle. Native repair selects that same replacement, saves
  during the unfinished route, then resumes after load without seed injection.
  The choice survives multiple days; the physical handoff completes on day 4,
  conserves total army and retains the helper's 1,000 force floor. Proof passed
  in 19.099 seconds: `.build/evidence/nk3-helper-replacement-load-proof.log`,
  `.build/playtests/nk3-helper-loss-p9rksawd`.
- A real task below a raw army minimum was incorrectly admitted using hero
  combat bonuses: 5,900 creatures' value satisfied a 6,000 commitment. Removing
  recruitment from the fixture reproduced that defect before repair:
  `.build/evidence/nk3-force-units-red-isolated.log`.
  Path commitment checks and own-arrival army values now use creature value;
  combat strength is a separately named estimate. The focused regression and
  all four logistics/save-load tests passed (5 tests, 71.534 seconds):
  `.build/evidence/nk3-force-units-green-game-proof.log`,
  `.build/playtests/nk3-force-units-xckcd72s`.
- Expired or irrecoverable ownership obligations release funds and participant
  assignments; temporary route blockers continue to protect valid commitments.
  The pre-change public contract froze expired reserves:
  `.build/evidence/nk3-expired-commitments-red.log`; repaired contract proof:
  `.build/evidence/nk3-campaign-current-contract-proof.log`.
  A real missed Capitol deadline then released its 10,000 gold reserve and
  native spending continued the next day without a model (7.861 seconds):
  `.build/evidence/nk3-expired-fallback-game-proof-final.log`,
  `.build/playtests/nk3-expired-fallback-sbxp_300`.

- Losing the courier's original safe town exposed a released preservation
  floor. The surviving helper now retains that floor and can hold at or route
  toward another owned safe town. Public red/green proof:
  `.build/evidence/nk3-preservation-displacement-red.log`,
  `.build/evidence/nk3-preservation-displacement-green.log`.
  Six real regressions passed in 79.394 seconds:
  `.build/evidence/nk3-displaced-preservation-game-proof.log`.
- A town-source delivery initially had no native task: a town cannot carry
  its army to the recipient. The recipient now visits the source town and the
  acknowledged ordinary garrison transfer records the named handoff. Five
  delivery/helper/save-load regressions passed in 71.938 seconds:
  `.build/evidence/nk3-town-donor-game-proof.log`,
  `.build/playtests/nk3-town-delivery-8y97uw_6`.
- A town and its garrison hero share one physical army. Their value-only own
  projection now names the current army holder; both aliases receive the same
  reservation and independent competing deliveries are rejected. The public
  regression reproduced the missing protection before repair:
  `.build/evidence/nk3-garrison-pool-red.log`,
  `.build/evidence/nk3-garrison-pool-green.log`.
  A separate test-only bundle puts a visiting hero into the garrison through
  an acknowledged engine swap packet. Actual town-source donation passed in
  7.178 seconds, kept the donor's 1,000 floor, conserved total troop value and
  completed its accepted delivery receipt:
  `.build/evidence/nk3-garrison-pool-game-proof-final.log`,
  `.build/playtests/nk3-town-delivery-j106fh9d`.
  Its factory restoration/probe provenance is recorded separately; ordinary
  preparation has no test-state driver. Full-stack handoff and unexpected
  garrison departures still require separate proof.

## Shared resource and army forecasts

- A real three-city fixture reproduced independent forecasts spending 15,000
  gold on day 1 from a 10,000 treasury. Accepted building commitments now share
  one income and spending calendar, priority order, prerequisite dependencies
  and each town's daily building slot. The real builds matched two City Halls
  on day 1 and the third on day 2. Red/green evidence:
  `.build/evidence/nk3-joint-economy-red-treasury.log`,
  `.build/evidence/nk3-joint-economy-game-proof.log`,
  `.build/playtests/nk3-joint-economy-6sdhrcm_`.
- Forecast snapshots are now recorded before native actions as well as after
  observed results. The building/load test saves only after the first building
  is actually complete and the second is unfinished, rather than assuming the
  first log entry is post-action. The real load passed in 20.449 seconds:
  `.build/evidence/nk3-joint-economy-save-proof.log`.
- Own hero positions provide current land-route forecasts for courier meetings.
  Delivery forecasts count physical army pools once, preserve other force
  floors and separate unknown routes, insufficient force and current-route
  lateness. The town-source ETA matched the acknowledged handoff. Five real
  delivery/economy/save-load checks passed in 56.697 seconds:
  `.build/evidence/nk3-delivery-forecast-game-proof.log`.
- A reinforcement below its threshold exposed delayed native recruitment:
  the partial handoff preceded procurement and the later hire missed the
  deadline. Town-source recruitment now belongs to the accepted goal in the
  priority pass. A checked build completed recruitment and the named handoff
  on day 1. The same episode exposed static creature values in forecasts
  (1,120 versus the actual 1,246 bought troop value); own recruitment now uses
  the same pinned combat-value unit as owned stacks. Evidence:
  `.build/evidence/nk3-recruitment-forecast-red.log`,
  `.build/evidence/nk3-recruitment-checked-game.log`,
  `.build/evidence/nk3-recruitment-forecast-current-red.log`.
  Two intervening diagnostic installations followed failed compilation and
  contained the old executable; they are not repair proof. Subsequent
  build/install commands require successful compilation before installation.
- Accepted construction and town-source hire now consume one treasury and
  existing dwelling-stock calendar. Existing weekly growth is conditional on
  retaining the observed bonuses; new dwellings and stack packing remain
  unproved. Current-stock delivery, ordinary delivery, the three-city calendar,
  protected economic development, hero logistics and building/load passed
  together (6 tests, 63.992 seconds):
  `.build/evidence/nk3-joint-stock-game-proof.log`,
  `.build/playtests/nk3-town-delivery-gmzqf95c`,
  `.build/playtests/nk3-joint-economy-yu4_9beo`,
  `.build/playtests/nk3-campaign-rp2cji1h`.
- A separate multi-day delivery needs both initial stock and the next weekly
  growth. The forecast scheduled hire on days 1 and 8; the final real handoff
  completed on day 8 (8.987 seconds):
  `.build/evidence/nk3-weekly-delivery-game-proof.log`,
  `.build/playtests/nk3-town-delivery-0qo0ocrq`.
  These branches share costs and stock; they do not prove battle wins or routes
  after a projected meeting. Further defense and logistics proof remains.
- Private profile snapshots use independent APFS copy-on-write files when
  available, with ordinary copy fallback on unsupported filesystems. Updating
  either copy leaves the other unchanged; all 29 playtesting tests passed:
  `.build/evidence/nk3-profile-clone-playtesting-proof.log`.

## Conditional defense and native consequences

- A real strong scout had a safe same-day route back to its town, but the
  garrison-only signal classified one visible pikeman as insufficient defense.
  The preceding regression failed in 6.420 seconds:
  `.build/evidence/nk3-defense-capacity-red.log`,
  `.build/playtests/nk3-defense-n2nmu1tp`.
  Current defense forecasts allocate each owned physical pool once across
  simultaneous fronts, include established own arrivals and displaced goals,
  and retain unknown enemy ETA/combat bonuses. The corrected episode passed
  in 6.441 seconds: `.build/evidence/nk3-defense-capacity-green.log`,
  `.build/playtests/nk3-defense-ea0vy51a`.
  Late reinforcements, duplicate mobile allocation and town/garrison aliases
  pass the public value contract:
  `.build/evidence/nk3-defense-allocation-contract-proof.log`.
  Recruitment and fortification bonuses are excluded from this defense capacity;
  it does not prove an actual defended town or a successful emergency override.
- All eighteen native/model/timeout paired privacy worlds passed again with
  defense allocation in 121.858 seconds:
  `.build/evidence/nk3-defense-visibility-proof.log`,
  `.build/playtests/nk3-visibility-ov3h_k6l`,
  `.build/playtests/nk3-model-visibility-bze0f8yw`.
- Public campaign regressions demonstrated two false completions: an observed
  force floor breach could be erased by later recruitment, and an overdue
  construction could complete an expired goal. Both are now rejected; the
  observed preservation failure survives save/load. Evidence:
  `.build/evidence/nk3-preservation-history-red.log`,
  `.build/evidence/nk3-preservation-history-green.log`,
  `.build/evidence/nk3-expired-completion-red.log`,
  `.build/evidence/nk3-expired-completion-green.log`.
  Real combat loss/recovery and losses inside a multi-command task still need
  separate proof; endpoint observations alone do not cover every intermediate loss.
- A seven-stack garrison exposed a dismiss-before-recruit breach: raw troop
  value fell from 426 to 385 before the acknowledged hire restored it. NK3 now
  checks the surviving raw force before the dismissal packet and refuses a
  purchase that requires breaking another goal's floor. The two final real
  garrison scenarios pass in 13.677 seconds:
  `.build/evidence/nk3-seven-slots-red.log`,
  `.build/evidence/nk3-seven-slots-final-proof.log`,
  `.build/playtests/nk3-seven-slots-6g3l2m4g`,
  `.build/playtests/nk3-town-delivery-3yp3oen9`.
  The private probe observes actual garrison packets and the acknowledged
  initial swap; ordinary preparation excludes it.
- Confirmed native construction was absent from the next shared model request.
  The real regression is `.build/evidence/nk3-execution-memory-red.log`.
  Native task dispatch now persists a value-only before snapshot, then records
  net resources and owned-state consequences after execution. Observed effects
  are distinct from complete task fulfillment; interrupted/load reconciliation
  is labeled unknown. Actual building cost reaches the next shared request:
  `.build/evidence/nk3-execution-memory-green.log`,
  `.build/playtests/nk3-execution-iq_y9m11` (6.164 seconds).
  The public persistence contracts pass malformed pending records and preserve
  spent model budget: `.build/evidence/nk3-execution-contract-proof.log`.
- Native consequences were also absent from the run report. That real report
  regression failed before the recorder change:
  `.build/evidence/nk3-execution-report-red.log`.
  The corrected game and 29 playtesting tests pass in 16.002 seconds:
  `.build/evidence/nk3-execution-report-green.log`.
  Reports preserve bounded logger JSON, resource deltas, unknown outcomes and
  incomplete-record counts. A net delta is not gross spending or proof of its
  cause after recovery. Current controller/arbiter checks pass (3 tests):
  `.build/evidence/nk3-execution-controller-proof.log`.
- A private packet driver saves after the first acknowledged step while the
  native movement task is still pending, then ends the turn. Loading that
  actual server save with the ordinary bundle reconciles one unknown task;
  the observed moved position becomes the first fresh planning snapshot and
  acknowledged native tasks continue. No controller request occurs. Evidence:
  `.build/evidence/nk3-native-command-save-final-proof.log`,
  `.build/playtests/nk3-native-command-save-k_ex6alp` (20.521 seconds).
  The live client's player-local settings are not a reliable dispatch-state
  readback because SaveLocalState is applied on the server; the proof checks
  the loaded server save. The probe factory is restored and rebuilt:
  `.build/evidence/nk3-native-command-final-normal-restore.log`.

- A visible insufficient critical defense exposed the economic priority pass
  spending first despite a fully reserved treasury. The real regression is
  `.build/evidence/nk3-defense-spending-red.log`. Fresh native urgent recruitment
  now precedes the economic build, with an exact stock-derived spending bound
  and a recorded actual reservation override. The income goal still completes:
  `.build/evidence/nk3-defense-spending-green.log`,
  `.build/playtests/nk3-defense-spending-nftfdnc9` (6.287 seconds).
  Ten affected real integration scenarios pass in 95.021 seconds, with three
  separate-probe checks skipped: `.build/evidence/nk3-defense-spending-integration-proof.log`.
  The stationary enemy fixture proves spending order and bounded funding; an
  actually attacking opponent and completed defense remain separate acceptance.
- The preceding ordinary execution-memory bundle passed 39 shared scenarios in
  227.889 seconds, with three separately proved private-probe scenarios skipped:
  `.build/evidence/nk3-current-execution-shared-proof.log`.

- A private packet driver exposed a preservation-history gap: an acknowledged
  garrison withdrawal followed by immediate recruitment before the next planner
  snapshot was reported as uninterrupted preservation. The real regression is
  `.build/evidence/nk3-force-history-red.log`,
  `.build/playtests/nk3-force-history-orkn50sw` (7.547 seconds).
  The gateway now queues only owned-hero troop minima from acknowledged army
  changes. The native owner applies them to the matching accepted revision
  before review or persistence; later recruitment cannot erase the breach.
  The corrected game also receives a critical commitment review:
  `.build/evidence/nk3-force-history-green.log`,
  `.build/playtests/nk3-force-history-25ab5ptu` (7.488 seconds).
  Three public contract drivers pass, including saved force-dip history:
  `.build/evidence/nk3-force-history-contract-proof.log`.
  This controlled withdrawal proves event handling; real combat loss remains
  separate acceptance. The ordinary factory is restored and installed:
  `.build/evidence/nk3-force-history-normal-build.log`.

- The owned-packet minimum recorder preserves native/model visibility parity
  across 18 real paired worlds, before and after movement and under timeout:
  `.build/evidence/nk3-force-history-visibility-proof.log` (123.789 seconds),
  `.build/playtests/nk3-visibility-isofoep5`,
  `.build/playtests/nk3-model-visibility-5xo0th54`.
  Current controller/arbiter/report tests pass (32 tests in 11.252 seconds):
  `.build/evidence/nk3-force-history-controller-reports-proof.log`.
- A damaged survivor with a known safe same-day town route stayed frozen when
  its strategic reply was rejected. The genuine regression is
  `.build/evidence/nk3-survivor-red2.log` (10.469 seconds).
  Native stabilization now admits only a currently visible, single-hero land
  route without estimated danger/loss, special actions or an army exchange.
  It retains the failed preservation history and troop floor for transfers.
  The two final real event-history and safe-return scenarios pass:
  `.build/evidence/nk3-survivor-final-proof.log` (17.785 seconds),
  `.build/playtests/nk3-force-history-s8dp7sg7`,
  `.build/playtests/nk3-force-history-0tok7bcm`.
  The deliberately stale reply is rejected at the controller boundary; the
  engine records fallback and returns the survivor without further force loss.
  Earlier fixture attempts that exited through blocked town tiles, and an
  assertion expecting the native layer's identity message rather than the
  controller's rejection, are not separate production regressions.
  Ordinary source restoration and installation:
  `.build/evidence/nk3-survivor-normal-build.log`.

- Three current garrison/delivery scenarios plus funded/weekly town delivery,
  the two defense scenarios and the two force-history/safe-return scenarios pass
  on the current ordinary/probe bundles (9 tests, 70.278 seconds):
  `.build/evidence/nk3-survivor-garrison-defense-proof.log`.
- Three distinct owned-garrison withdrawals now each follow acceptance of the
  preceding critical reply, using the real native logger as a private fixture
  timing signal. They produce three accepted critical commitment reviews in
  day 2, with native movement after the third review:
  `.build/evidence/nk3-three-events-finished-proof.log`,
  `.build/playtests/nk3-three-events-vr2ym46l` (8.470 seconds).
  The controller is deterministic: this proves the runtime arbiter and native
  continuation, not live provider latency or three paid ChatGPT calls. No
  production change or request-count quota was needed for this scenario.
  The former weak-front fixture is unsuitable after covered defenses stopped
  requesting critical reviews; independent real owned events replace that
  count test. An earlier fixture changing facts during model wait correctly
  rejected the stale reply and is not a quota regression. The ordinary factory
  is restored/rebuilt: `.build/evidence/nk3-three-events-finished-normal-restore.log`.

## Accepted risk and actual battle consequences

- The accepted `max_loss_ratio` now constrains independently selected native
  combat paths, including heroes outside named goals. The real paired fixture
  permits a battle at 50% and prohibits it at 0%, while useful native work
  continues in both cases. Meaningful pre-change failure:
  `.build/evidence/nk3-global-risk-current-red.log` (18.491 seconds).
  Final risk pair and separately acknowledged casualty report checks pass:
  `.build/evidence/nk3-battle-result-final-proof.log` (2 tests, 27.028 seconds),
  `.build/playtests/nk3-risk-policy-q_lbga47`,
  `.build/playtests/nk3-risk-policy-_9flw6yb`.
- Own `BattleResult` casualties and battle outcomes now enter native memory and
  reports separately from net army changes around tasks. The fixture's actual
  casualty value agrees with independently observed own-army loss and the
  pinned public creature values. Report metrics count confirmed own battle
  outcomes and casualties; an uncertain saved task or transfer does not become
  combat loss or a match victory. The missing-event regression is
  `.build/evidence/nk3-battle-result-red.log` (9.242 seconds).
  Controller/report/experience checks pass:
  `.build/evidence/nk3-battle-report-controller-final-proof.log`
  (47 tests, 19.907 seconds), plus three C++ contract drivers:
  `.build/evidence/nk3-battle-result-contract-proof.log`.
  Battle callbacks queue only own result values; queued facts remain transient
  until the existing native persistence boundary. This does not prove durable
  packet-by-packet history across arbitrary mid-callback saves.
- All 18 native/model/timeout paired hidden-world tests pass on the ordinary
  battle-result bundle:
  `.build/evidence/nk3-battle-result-visibility-proof.log` (122.931 seconds),
  `.build/playtests/nk3-visibility-k9g68ffp`,
  `.build/playtests/nk3-model-visibility-l4jqrxlz`.
- The current garrison probe passes all three force-history cases, including
  stronger checks that the survivor is already at a safe owned town and its
  return is acknowledged in memory before the day-2 shared model request:
  `.build/evidence/nk3-battle-result-force-history-proof.log`
  (31.657 seconds), `.build/playtests/nk3-force-history-6k0jteuw`,
  `.build/playtests/nk3-force-history-3pkigg6y`,
  `.build/playtests/nk3-force-history-f_xz1ena`.

- Unexpected acknowledged combat loss now requests a critical strategic review
  even without a preservation goal. In the real fixture the permitted path's
  actual casualty value exceeds the accepted 1% budget. The result appears in
  the shared request and is reviewed exactly once while subsequent native play
  continues. RED: `.build/evidence/nk3-unexpected-battle-loss-red.log`
  (9.912 seconds). Three real risk/casualty/review cases pass:
  `.build/evidence/nk3-unexpected-battle-loss-green.log` (36.978 seconds),
  `.build/playtests/nk3-risk-policy-yyjt073b`,
  `.build/playtests/nk3-risk-policy-ndt0icjw`,
  `.build/playtests/nk3-risk-policy-r2od97v4`.
  Freshly rebuilt three C++ drivers also pass, including unknown force-interval
  restoration, expiry and duplicate/independent combat-event questions:
  `.build/evidence/nk3-unexpected-battle-loss-final-build2.log` (0.04 seconds).
  The fresh build exposed and corrected three missing namespace qualifiers in
  earlier force-continuity test additions; historical ctest-only invocations did
  not rebuild those additions. This current build is the verification of them.

- Before an unaddressed unexpected own combat-loss review, native stabilization
  now uses remaining movement toward the nearest owned town on an established
  visible land path with no estimated danger, loss, exchange or special action.
  It uses the existing native hero-chain executor. Arrival can be next day;
  this fixture proves acknowledged progress before waiting, unchanged survivor
  force, and no intervening unrelated movement in the request snapshot.
  An initial assertion demanding same-day arrival was infeasible with the
  fixture's remaining movement, so it is not counted as a production regression.
  The meaningful missing-return regression is
  `.build/evidence/nk3-combat-survivor-progress-red.log` (10.081 seconds).
  Four final ordinary-bundle risk/consequence/review/return cases pass:
  `.build/evidence/nk3-combat-survivor-policy-final-proof.log`
  (42.393 seconds), `.build/playtests/nk3-risk-policy-n5il_8ef`,
  `.build/playtests/nk3-risk-policy-2uqah7vf`,
  `.build/playtests/nk3-risk-policy-n7wta9_o`,
  `.build/playtests/nk3-risk-policy-wa4tbxam`.
  Checked build/install: `.build/evidence/nk3-combat-survivor-build.log`.
  This is stabilization at the native task boundary; interrupting an existing
  multi-action composition immediately after a disqualifying battle remains
  separate acceptance.

- Loss of a policy-critical town now requests a critical review independently
  of named town goals. A real NK2 opponent captures the initial critical town;
  the separate development town survives. The loss is confirmed from the
  complete own-town list and queried exactly once through day 4. The shared
  request contains no goal targeting the lost town. RED:
  `.build/evidence/nk3-critical-policy-town-loss-red.log` (6.731 seconds).
  GREEN: `.build/evidence/nk3-critical-policy-town-loss-green.log`
  (6.535 seconds), `.build/playtests/nk3-critical-town-loss-dixrai41`.
  Missing own-list data cannot prove ownership loss; native observation now
  explicitly emits empty complete own lists. Fresh C++ build/check/install:
  `.build/evidence/nk3-critical-policy-town-loss-build.log`.
  Current controller/experience/report checks pass (50 tests, 19.756 seconds):
  `.build/evidence/nk3-critical-policy-town-loss-controller-proof.log`.

- Current native/model/timeout visibility remains equal across all 18 paired
  worlds after generic loss signals and survivor stabilization:
  `.build/evidence/nk3-critical-policy-town-loss-visibility-proof.log`
  (123.636 seconds), `.build/playtests/nk3-visibility-svgmdinj`,
  `.build/playtests/nk3-model-visibility-ric5rh0o`.
- A valid cancelled saved commitment was reactivated by the next review.
  The public save/restore/review regression fails before the change:
  `.build/evidence/nk3-cancelled-goal-red.log`.
  Cancellation now remains terminal, and a dependent operation becomes a failed
  dependency rather than retaining its actors and reserves while waiting for a
  cancelled prerequisite. All three freshly rebuilt C++ drivers pass:
  `.build/evidence/nk3-cancelled-goal-green.log` (0.03 seconds), with checked
  ordinary build/install in the same log. This is public serialized-contract
  proof, not a UI cancellation or real-game cancellation scenario.

- The current ordinary/garrison-probe combination passes 11 real scenarios:
  force minima and safe return before waiting, preservation expiry, physical
  garrison pool/slot reserves, own-town/current-stock/weekly delivery, bounded
  urgent defense spending before construction/waiting, and covered weak fronts.
  `.build/evidence/nk3-critical-policy-town-loss-garrison-defense-proof.log`
  (91.134 seconds). The private factory is restored and the ordinary build
  checked: `.build/evidence/nk3-critical-policy-town-loss-normal-restore.log`.

- A fresh `prepare_engine.py .build/nk3-fresh-events` clone checks out the
  recorded VCMI and dependency revisions and applies the source-controlled
  integration patch. Tracked patch bytes and every owned adapter/NK3 source
  digest equal the fresh prepared tree:
  `.build/evidence/nk3-fresh-events-provenance.json`.
  Fresh release client/server build and signed private installation succeed:
  `.build/evidence/nk3-fresh-events-build2.log`, exact configuration command:
  `.build/evidence/nk3-fresh-events-configure-command.json`.
  The first configure attempt omitted the venv Ninja path; retry supplies
  `CMAKE_MAKE_PROGRAM` explicitly. This is a build-tool lookup issue, not a
  source regression.
- The unchanged NK2 baseline and this freshly prepared/built integration have
  identical 51 task/build/movement/turn records through three complete own
  turns on the same map/seed/difficulty. Neither invokes a controller and both
  preserve protected files and confirm assignments:
  `.build/evidence/nk2-fresh-events-baseline-comparison.json`,
  `.build/playtests/nk2-fresh-baseline-zy61620y`.
  This proves that scenario, not every NK2 behavior.

- The fresh events bundle passes six real ExternalAI visibility variants:
  `.build/evidence/nk3-fresh-events-externalai-visibility-proof2.log`
  (40.777 seconds), `.build/playtests/visibility-llym4eo_`.
  The first attempt retained an NK3-only config field after selecting ExternalAI;
  configuration validation rejected it before launch. The corrected private
  config removes that field; the failure is not an adapter regression.
- Enabling learning crashed the first valid NK3 strategy before any episodes
  existed, because the empty assessment array schema lacked the minimum
  required by its closed-schema validator. A real runtime trace showed this
  failure. The corrected public controller reproduction is
  `.build/evidence/nk3-opening-learning-current-red.log`; its fixture includes
  a valid experience identity. The schema now explicitly permits zero items.
  Native controller and experience checks pass (17 tests, 9.328 seconds):
  `.build/evidence/nk3-opening-learning-current-green.log`.
- A real own terminal defeat after two accepted native strategic replies had no
  final learning request: `.build/evidence/nk3-terminal-experience-current-red.log`
  (8.391 seconds), `.build/playtests/experience-jct3hn6f`.
  The gateway now logs only immutable own terminal facts. In learn/model mode,
  the existing playtest recorder performs the existing end-only terminal
  reflection after engine command cleanup; its response never reaches a game
  gateway or updates an operational plan. Native-only/off runs do not acquire
  this model call. The final request discloses only own player/day/result and
  experience identity, without invented final own-object observations.
  Two real final reflection/durable lesson and active-reflection STOP cases pass:
  `.build/evidence/nk3-terminal-experience-final-proof.log` (17.376 seconds).
  The callback waits for no model. The separate reflection has its own
  controllable process group; STOP cancels it. Current controller/arbiter/
  experience/report checks pass (51 tests, 19.880 seconds):
  `.build/evidence/nk3-terminal-experience-controller-reports-proof.log`.
  Checked ordinary bundle: `.build/evidence/nk3-terminal-experience-build.log`.
  This postgame mode currently belongs to the playtest supervisor; arbitrary
  standalone game launches do not automatically run it. The terminal tail attribution is extended below; arbitrary consequences
  outside acknowledged native tasks still need separate proof.

- ExternalAI terminal learning remains compatible with the shared recorder:
  `.build/evidence/nk3-terminal-experience-externalai-proof.log` (7.626 seconds),
  `.build/playtests/experience-kp5nx2h0`.
- A real native task tail after the last strategic request was absent from final
  learning: `.build/evidence/nk3-terminal-tail-red.log` (8.644 seconds).
  Execution logger records now bind their own facts to player and experience
  identity. The recorder transfers up to eight game-bound own results within a
  12 KB history budget; skipped history and malformed record counts remain explicit.
  It rejects opponent, other-game, future-day and unattributed records. The same
  experience owner consumes and deduplicates these consequences, retaining unknown
  task acknowledgments as unknown. No final own-object observation is invented.
  Real durable-tail reflection and STOP proof passes in 16.980 seconds:
  `.build/evidence/nk3-terminal-tail-green.log`, `.build/playtests/experience-v655hze_`
  and `.build/playtests/experience-v5p3s6e2`. A real two-NK3 game keeps each player's
  terminal reflection and result history separate (10.401 seconds):
  `.build/evidence/nk3-terminal-tail-two-player-proof.log`,
  `.build/playtests/experience-b36gdhvo`.
  Rejection proof: `.build/evidence/nk3-terminal-tail-attribution-proof.log`.
  Current controller/experience/arbiter/recorder checks pass (49 tests, 19.901 seconds):
  `.build/evidence/nk3-terminal-tail-controller-reports-proof.log`.
  Checked ordinary bundle: `.build/evidence/nk3-terminal-tail-build.log`.

- A real compound native task continued exploring five more tiles after own
  casualties exceeded the accepted loss ceiling: the regression ended at
  `[12,18,0]` instead of the acknowledged guarded visit `[7,13,0]`.
  `.build/evidence/nk3-combat-composition-interruption-red.log` (7.771 seconds).
  The own battle callback now sets an atomic replan flag using the accepted
  risk policy; after mandatory battle queries complete, the worker unwinds the
  stale composition at its next movement boundary. The partial task is recorded
  as `replan_after_combat` with observed net effects, without claiming completion
  or locking the survivor. Cached remaining tasks and the pass's unrelated trade
  are skipped before fresh stabilization/decomposition and the critical review.
  No model is called inside a callback, and the flag is not a saved command.
  The regression passes (8.159 seconds):
  `.build/evidence/nk3-combat-composition-interruption-green.log`,
  `.build/playtests/nk3-risk-policy-nkco9qpm`.
  All five real risk cases and three real terminal-learning cases pass on this
  ordinary bundle (79.264 seconds):
  `.build/evidence/nk3-combat-interruption-policy-experience-proof.log`.
  Paired native and model/timeout visibility scenarios pass (124.594 seconds):
  `.build/evidence/nk3-combat-interruption-visibility-proof.log`,
  `.build/playtests/nk3-visibility-snazbw9o`,
  `.build/playtests/nk3-model-visibility-jqtjrbsz`.
  Checked ordinary bundle: `.build/evidence/nk3-combat-composition-interruption-build.log`.

### Rule and executor provenance for durable experience

Native and ExternalAI lessons retain the public engine version/revision, declared
active mod versions, and execution mechanism. Supported confidence requires three
distinct supporting games with the same known rules and executor. Reordered mod
lists preserve compatibility; different revisions, mod versions, unknown custom
versions, and a different executor retain the lesson as a hypothesis. The virtual
builtin `core` entry has no independent version; unknown custom entries remain
unknown. This is declared-rule provenance, not a checksum of licensed assets.
Terminal reflection uses the latest own decision from that game for historical
rule context, with that source explicitly recorded.

The missing Native context failed through the real controller/terminal pipeline
(`nk3-experience-provenance-red.log`). The corrected Native proof passed in 7.619
seconds (`nk3-experience-provenance-green2.log`, run `experience-uqpy16wo`). Four
Native terminal scenarios plus the ExternalAI compatibility case passed in 38.002
seconds (`nk3-experience-provenance-native-external-proof.log`). Public controller
comparisons passed in 2.122 seconds (`nk3-experience-context-comparison-proof.log`);
50 affected controller, experience, arbiter and recorder checks passed in 21.717
seconds (`nk3-experience-provenance-controller-proof.log`). All logs are under
`.build/evidence/`.

### Visiting defenders and preliminary full-model match failure

The preliminary real `gpt-6.1-sol` match against NK2 at impossible difficulty,
LandDuel-v1, red NK3, seed 42, reached day 19 before crashing. Accepted model goals
for opening reinforcement and frontier reconnaissance completed. The run is
`.build/playtests/nk3-full-live-landduel-red-42` (run ID
`ae85ae2ab8cc4de99a37a87c4940e8ff`). This is incomplete calibration, with no
confirmed final game result or checkpoint.

It exposed an actual defense-completion defect: the visiting hero stood on the
own town tile with 22,666 army value, but the separate town army was only 5,679.
The completion predicate omitted the visitor. The repaired public observation
identifies an owned visiting hero and counts it only at the exact town position
and only when distinct from the town's physical army holder. Nearby, foreign and
garrison aliases are guarded. The C++ contract failed before repair and passed
afterward (`nk3-visiting-defense-red.log`,
`nk3-visiting-defense-alias-proof.log`). A fresh real initial observation also
failed on the previous ordinary bundle and passed on the repaired one, before
any native army exchange (6.406 / 6.216 seconds;
`nk3-visiting-defense-runtime-red.log`,
`nk3-visiting-defense-runtime-green.log`, repaired run
`nk3-visiting-defense-3isvllvi`). Checked ordinary build:
`nk3-visiting-defense-green-build.log`.

The full-match crash followed the supervisor's console `save` command in
headless mode. The macOS faulting thread is `consoleHandler`; the matching client
UUID and symbol table place the fault at `handleSaveCommand +84`, which
dereferences the absent player UI interface. This was not a NativeCampaign
worker-thread fault. Console checkpoint transport remains verified only with a
spectator interface (`headless=false`). Crash evidence:
`.build/evidence/nk3-full-live-landduel-crash.ips` and
`nk3-full-live-landduel-crash-analysis.json`. Original launch cleanup reported a
surviving owned model group; a separate delayed audit found neither owned group
113 nor 1278 alive (`nk3-full-live-landduel-delayed-cleanup.json`). The original
failure records remain unchanged; protected files were unchanged.

### Executed town defense and episode preservation

All five ordinary-bundle defense scenarios passed in 32.616 seconds
(`.build/evidence/nk3-defense-runtime-proof.log`). The new attack scenario uses
an ExternalAI test controller which selects only its own publicly offered attack
on a visible enemy town. It deliberately attacks with one pikeman; this proves
execution and ownership retention, not competitive strength. NK3's stationed
hero recruited before the attack, won the actual battle with 7,146 army value and
zero casualties, retained the critical town, and completed holding it on day 3.
The earlier development assertion incorrectly expected the unrecruited 5,900
army value; runtime evidence justified accepting the additional owned recruits.

The durable episode projection now retains own town `defense_value`,
`army_holder_ref` and `visiting_hero_ref`, so the model can distinguish a separate
visiting defender from a shared garrison pool. The real controller/SQLite/model
boundary failed before this repair and passed afterward (0.352 / 0.363 seconds;
`.build/evidence/nk3-experience-town-defense-red.log`,
`nk3-experience-town-defense-green.log`). All 51 affected experience, controller,
arbiter and recorder checks passed in 23.104 seconds
(`nk3-experience-town-defense-controller-proof.log`).

### Reviewed real-model victory against NK2 at 200 percent

The repaired ordinary bundle won a complete LandDuel-v1 game on day 3, with red
NK3 against blue NK2, impossible difficulty (200 percent), requested seed 42,
`gpt-6.1-sol`, medium reasoning, and experience off. Run:
`.build/playtests/nk3-full-live-landduel-red-42-v2`, ID
`69b97103f82f4383ba05b46995d01127`. The initial accepted strategy developed archers
and scouted. A new visible critical-defense question on day 3 led the model to
choose a frontier approach and then capture the lightly defended enemy town,
rather than return too late to the home town. The native executor performed that
operation, won the siege, and the engine delivered the own win plus the opponent
loss. The final own-state effect contains both towns. Terminal cancellation
leaves the capture task `reconciled_unknown`; that is not task-completion proof,
but the independent game-over result and town ownership establish the match win.

There were three requests (two on day 1, one on day 3), two accepted responses,
and one invalid role response. The invalid reply was rejected without replay or
a same-question retry; native play continued. Recorded usage, including the
rejected response, was 52,418 input and 4,072 output tokens (56,490 total). The
engine charged 143,544 budget tokens because it conservatively reserves unknown
usage when no reply is delivered. These are distinct measures. Native wait p50
was 51.484 seconds and interpolated p95 57.849 seconds (only three samples).
Actual own casualties totalled 356 creature AI value across two won battles.

The root supervisor reviewed assignments, source hashes, profile difficulty,
seed setup, both game-over messages, cleanup and protected-file integrity before
attaching `llm_win`. No supervisor game command or checkpoint was sent; cleanup
was requested only after the terminal callback. The source seeds the PRNG with
42 before logging its first random draw, despite the log's misleading label.
The same bundle passed all 18 paired native/model/timeout visibility variants
after the match (123.358 seconds,
`.build/evidence/nk3-visiting-defense-win-visibility-proof.log`). Evidence review:
`.build/evidence/nk3-full-live-landduel-v2-reviewed-win.json`; the immutable copy is
attached in the run's `outcome.json`. This establishes one winning episode, not
comparative superiority or the complete acceptance series.

### Final battle attribution and graceful won-game shutdown

A real NK2 attack killed the stationed NK3 hero and ended the game on the
opponent's day-1 turn. The own terminal loss existed, but its acknowledged battle
was absent from final learning: there was no subsequent own turn to drain the
callback queue. The public terminal-learning regression failed in 7.069 seconds
(`.build/evidence/nk3-opponent-turn-terminal-battle-red.log`,
`.build/playtests/experience-6lg74ste`).

Terminal handling now drains only queued own battle facts before its final
record, briefly excluding the turn worker with the game-state lock. Callbacks
run after the engine's packet-application lock is released. This section assigns
existing own aliases/result sequences and performs no game command or model
exchange. The formerly missing defeat now retains all 15 pikeman casualties
(1,335 army value), the own actor reference, and `battle_lost`; these facts reach
the postgame request and durable SQLite episode. The first repaired run passed
the new battle assertions but exposed the helper's older assumption that only
native task records can form an unseen execution tail. The helper now includes
acknowledged own battle records too.

The additional real final-win case exposed a separate shutdown defect:
`persist()` sent `SaveLocalState` after terminal cancellation and then waited on
a closed network. The natural process-exit assertion failed in 35.789 seconds
(`nk3-terminal-win-shutdown-red.log`). Local journaling still finishes, but the
server update is sent only while uncancelled and the player is in game. The same
case passes in 7.144 seconds (`nk3-terminal-win-shutdown-green.log`,
`.build/playtests/experience-fqi1u9gr`); launch records a natural exit code 0 and
there are no network persistence commands after the terminal marker.

All six terminal-learning scenarios and the original save-during-wait,
cancel-and-restore lifecycle case pass on the ordinary corrected bundle in
68.605 seconds (`nk3-terminal-shutdown-experience-lifecycle-proof.log`). This
covers opponent-turn defeat, own final battle victory, two-player attribution,
public rule provenance, postgame STOP, and preserved unknown-request budgets
after load. Checked build: `nk3-terminal-shutdown-build.log`; ordinary bundle
`.build/nk3-terminal-shutdown-installed/VCMI.app`.

### Preliminary native-only result on the same duel

NK3 without a model lost to NK2 on day 13 in a fresh headless LandDuel-v1 game,
red NK3 / blue NK2, impossible, requested seed 42. Run:
`.build/playtests/nk3-native-landduel-red-42-headless`, ID
`f5f9a373886a4b8991cf265f6d5fc3be`. It made zero model requests and naturally exited
with code 0 in 12.820 seconds; assignments, own terminal loss, opponent win,
cleanup and protected files were verified. The final town pool was empty. Evidence:
`.build/evidence/nk3-native-landduel-red-42-reviewed-loss.json`. The existing report
enum uses `llm_loss` for the tested side; the evidence explicitly identifies the
native-only variant.

The preceding model win used spectator mode and the prior ordinary bundle.
The intervening source changes concern terminal journaling/shutdown, but the two
runs are preliminary calibration and do not replace a controlled final matrix.

### Building stagnation and supported continuation

A real Mage Guild 4 campaign built levels 1 and 2 but then exhausted its rare
resources. With no mines or resource pickups, it reached day 6 without any
stagnation question, before its day-7 deadline or horizon review. The regression
failed for that missing request (`nk3-building-stagnation-red.log`, 11.536
seconds, `.build/playtests/nk3-building-stagnation-ci17sevj`). Ordinary native
construction of other buildings continued; it was not progress toward the guild.

The native owner now tracks the remaining supported prerequisite sequence and
last progress day for each live, ready building objective. Routine income,
unrelated construction and a new model revision do not reset that sequence.
After two own days without prerequisite progress, an unsupported continuation
raises one canonical building question. Its durable fact signature is unchanged
until the objective's remaining prerequisites change. The existing arbiter
suppresses repetition; deadlines and failures retain their existing signals.

A second real case exposed an overly broad first implementation: after waiting
for reserved cash, it asked the model just before an affordable City Hall build
(`nk3-building-cash-wait-red.log`, 6.456 seconds). A conditional, supported build
schedule now continues natively, including the day of purchase. In the final
fixture, a 9,500 gold reserve makes the city wait beyond day 3 for income; it
then actually builds without any stagnation request. The original stalled guild
is reviewed once on day 4, with last prerequisite progress on day 2, despite
unrelated construction. Evidence runs:
`.build/playtests/nk3-building-stagnation-a_v7t50v` and
`.build/playtests/nk3-building-cash-wait-mdzz22dh`.

Both cases, the unchanged-blocker regression and the existing real economy /
protected-reserve case pass together in 42.896 seconds
(`nk3-building-progress-runtime-proof.log`). The rebuilt three C++ contract
drivers pass, including preservation of the progress clock through namespace
restoration and rejection of malformed clocks without refunding spent budgets
(`nk3-building-progress-contract-proof.log`). Checked ordinary bundle:
`.build/nk3-building-progress-installed/VCMI.app`; build logs
`nk3-building-stagnation-build.log` and `nk3-building-cash-wait-build.log`.
The same case was then saved on day 3 during a paused strategic exchange,
cancelled through the isolated game's console, and loaded into a new process.
The restored player asked the stagnation question on day 4 with the original
last-progress day 2 and remaining prerequisites `[2,3]`. The interrupted day-3
request was not replayed, and the unchanged stagnation question did not repeat.
Both runs verified cleanup and protected-file integrity. Evidence:
`.build/evidence/nk3-building-progress-save-proof.log` and
`.build/playtests/nk3-progress-save-hq1x49mv/proof.json`; the bounded driver and
paused controller are `.build/nk3-building-progress-save-proof.py` and
`.build/nk3-save-progress-probe.py`. Saving uses the spectator interface; the
restored phase uses headless mode. This slice covers building objectives;
stagnation semantics for the other goal types remain unproved.

### Existing visible boat crossings

The new water fixture has a full-height, two-tile water strip, one visible boat,
and a visible neutral mine on the opposite side. Normal NK2 actually moved on
and across the strip, establishing a legal fixture. The old NK3 accepted the
capture intention but never crossed before its deadline; the public regression
failed in 28.492 seconds (`nk3-water-route-red.log`,
`.build/playtests/nk3-water-etcoo5vq`). An earlier fixture-config attempt failed
before launch because `nk3_mode` is invalid for a normal NK2 player. An earlier
assertion looked for an unavailable embark log word; those are not movement
regressions. The control check now reads actual movement coordinates.

Supported movement options now admit LAND/SAIL transitions through visible
existing boats in both native planning and the fresh single-hero command path.
Native virtual-boat creation and movement spells remain disabled. The DTO states
these limits in `movement_support.water`, advertises water, and records owned
heroes' `in_boat` state. Own arrival forecasts and their consumers now use
`own_arrivals`, since these current permitted routes can include sailing.
Their assumptions name existing boats and do not assume future construction.

The first enabled build demonstrated native sailing but still failed the
accepted goal: the mine was visible by its footprint while its entrance lacked
an established route. The local route repair rejected an information-gathering
step that needed embark/disembark over more than one day. Repair can now take
that observed, zero-loss single-hero step across own turns; its caller still
checks the whole goal deadline and rebuilds it from fresh state. The same goal
then passed in 17.269 seconds (`nk3-water-repair-green.log`,
`.build/playtests/nk3-water-3bmcs63e`). Acknowledged execution records show day-1
embark from `[5,11,0]` to `[8,11,0]` (`in_boat` false to true), day-2 disembark to
`[10,12,0]`, and day-3 capture at `[11,11,0]`. No battle or match victory is claimed.

The boat originally appeared as generic `other` data. A further public
regression failed in 17.422 seconds (`nk3-water-observed-boat-red.log`); visible
boats now have kind `boat`, retaining the same observed-only alias namespace.
The latest two water tests pass in 45.055 seconds
(`nk3-observed-boat-water-proof.log`). They cover normal NK2 control, actual NK3
capture, equal model input before and after the crossing, equal native rankings
after actual embark, and equal observed boarded state when a hidden boat or
hidden water patch changes. Removing the visible boat prevents embark/capture
and surfaces the missing route through the existing repair question. Latest
paired evidence: `.build/playtests/nk3-water-visibility-sva_oklo`; ordinary latest
capture: `.build/playtests/nk3-water-ihkfxeo3`.

The preceding five-case water/economy/building-stagnation suite passes in 75.947
seconds (`nk3-water-and-economy-runtime-proof.log`). The actual own embark state
also survives the durable experience projection into the model context
(`nk3-water-learning-proof.log`, 0.349 seconds). Twenty affected controller,
experience and arbiter checks passed in 12.094 seconds, and the latest rebuilt
three C++ contract drivers pass (`nk3-existing-boat-controller-proof.log`,
`nk3-observed-boat-contract-proof.log`). Checked latest ordinary bundle:
`.build/nk3-observed-boat-installed/VCMI.app`, build log
`nk3-observed-boat-build.log`. The same final bundle also passes all 18 existing
paired land/native/model/timeout visibility variants in 133.022 seconds
(`nk3-observed-boat-land-visibility-proof.log`,
`.build/playtests/nk3-visibility-ycgr86qe` and
`.build/playtests/nk3-model-visibility-tmirp4di`). Boat construction, naval defense,
teleports and adventure movement spells still need their own evidence.

### Checkpoint while actually embarked

The first spectator-console attempt saved successfully but loaded an already
disembarked hero. Its explicit premise assertion failed
(`nk3-water-save-proof.log`, 17.294 seconds); this was not evidence of a broken
boat serializer. The private lifecycle probe now has an `embark_save` mode:
after the real EMBARK packet, it cancels only its own test planner and saves
through an asynchronous callback holding the normal game-state lock. This
prevents a subsequent own move racing the checkpoint. The probe is absent from
normal preparation; its factory source is restored byte-for-byte after building.
The first private build was not run because its normal timer would suppress the
embark-specific gate; the corrected fixture is `nk3-embarked-save-probe-v2`.

Ordinary NK3 loaded the probe save on day 1 at `[8,11,0]`, with `in_boat=true`
and accepted revision 1. Its first result was `reconciled_unknown`, followed by
fresh useful tasks; it disembarked and captured the mine on day 3 without
replaying embark or requesting an opening strategy. Both run phases verified
cleanup and protected-file integrity. Direct proof passed in 17.559 seconds:
`nk3-water-exact-save-proof.log`, `.build/playtests/nk3-water-save-0zznbu8m/proof.json`.
Probe isolation and matching factory hashes are recorded in
`nk3-embarked-save-probe-v2-provenance.json`.

The subsequent old movement-save regression hit a test filter that assumed
every execution record was a native command. Its real report included three
own `battle_won` records, which correctly have no command acknowledgement, and
exactly one recovered unknown command. The filter now selects acknowledged
commands without excluding the battle facts from the report. The final exact
boat save, movement save/reconciliation, unfinished preservation interval, and
shared-model building-consequence cases all pass in 68.567 seconds
(`nk3-water-save-and-movement-lifecycle-green.log`). Latest saved boat evidence:
`.build/playtests/nk3-water-save-eerwg53d`.

### Owned shipyard construction and protected resources

The initial regression replaced the provided boat with an owned visible shipyard.
Its accepted plan reserved 10 wood / 1,000 gold for the crossing and 4 wood /
8,000 gold for another hero. The initial treasury was 15 wood / 10,000 gold.
The pre-implementation bundle accepted both goals but never created a boat or
captured the mine (`nk3-shipyard-own-reserve-red.log`, 22.768 seconds,
`.build/playtests/nk3-shipyard-84wiurpw`).

The native pathfinder now admits the existing `BuildBoat` action only for an
owned visible sailing shipyard with visible possible launch tiles and a current
placement/status quote. Planning may use the selected participant goal's reserve;
other campaign reserves and native resource locks remain protected. Immediately
before the command, the executor rechecks placement and free resources for the
executing goal. The ordinary NK2 status-before-location query order is preserved.
Unproved boat spells and airships remain disabled.

The first funded/blocked runtime pair passes in 13.505 seconds
(`nk3-shipyard-reserves-green.log`). The funded command spends exactly 10 wood /
1,000 gold on `across_water`, embarks at [8,14,0] on day 1, disembarks on day 2,
and captures the mine on day 3. Another live reserve remains intact. With only
nine free wood outside another obligation, no embark occurs through day 4.

The final ordinary bundle is `.build/nk3-shipyard-visibility-installed/VCMI.app`,
configured by `.build/nk3-shipyard-visibility-config.json`; its checked build log
is `nk3-shipyard-visibility-build.log`. On this bundle, exact-cost and blocked
reserve tests pass, and neutral/enemy shipyards or all occupied launch tiles
produce no opening construction quote (`nk3-shipyard-public-green.log`; the
visibility case in that aggregate had a fixture indexing error and was rerun
separately after repair).

Four paired games change a hidden boat, coast, or shipyard while retaining equal
permitted observations before and after actual construction. They preserve
opening and later model inputs, native rankings before/after embark, and day-3
mine capture (`nk3-shipyard-public-green2.log`, 48.296 seconds). Reviewed run
links, exact cost, execution sequence, bundle hashes, cleanup and protected-file
checks are saved in `nk3-owned-shipyard-visibility-proof.json`. The paired fixture
has a second water barrier so later native scouting cannot reveal the mutations
before its model boundary. Earlier attempts used a mutation that was subsequently
revealed and then an out-of-range fixture coordinate; those failures are retained
and do not constitute product regressions. A single occupied launch tile still
allows the engine's legal alternative placement; the negative fixture therefore
occupies all three water candidates.

All three rebuilt C++ contract drivers pass (`nk3-shipyard-contract-proof.log`).
The model contract/arbiter checks pass four tests in 1.978 seconds; six explicitly
runtime-gated experience cases were skipped by that focused invocation
(`nk3-shipyard-controller-proof.log`). This stage does not claim a new competitive
win or statistical improvement.

The final bundle also passes the 18 prior paired land/native/model/timeout
variants and the four existing-boat visibility/precondition variants
(`nk3-shipyard-land-and-water-proof.log`, 148.800 seconds). That aggregate has
one loader error from a misspelled additional test name; the omitted ordinary
boat control was then run by its correct name and passed in 16.735 seconds
(`nk3-shipyard-water-control-green.log`, `.build/playtests/nk3-water-uucr8aj8`).
All actual game scenarios in these invocations pass.

On the owned-shipyard fixture, ordinary NK2 in the unchanged baseline and the
current bundle produces the same 70 task/build/movement/turn records through
three complete own turns, with no controller calls, correct assignments and
protected cleanup (`nk2-owned-shipyard-baseline-comparison.json`,
`.build/playtests/nk2-shipyard-control-ugvbcvxc`). This proves preservation in this
scenario. All copied adapter/NK3 source bytes and the tracked patch match the
prepared source tree; no private checkpoint probe is installed in its factory
(`nk3-owned-shipyard-source-proof.json`). `git diff --check` passes; no staging
or commit has occurred.

### Current candidate: first controlled native/model match pair

The owned-shipyard candidate was frozen for two fresh headless LandDuel-v1 games
with red NK3, blue NK2, impossible/200%, seed 43 and experience off. Both use the
same client/server/library, profile/map hashes, BattleAI and land-only map rules;
only `nk3_mode` differs. The private settings contain server.seed=43. Pinned
`CGameHandler::init` applies the nonzero seed before logging its first RNG output;
both games log the same 738509560 value (that log value is an RNG sample, not the
seed itself). Model sampling and other asynchronous randomness are not claimed
controlled.

| Variant | Reviewed outcome | Day | Elapsed | Requests / accepted |
| --- | --- | --- | --- | --- |
| NK3 without model | Loss | 13 | 13.702 s | 0 / 0 |
| Full NK3, real gpt-6.1-sol / medium | Win | 23 | 762.880 s | 17 / 12 |

Native run: `.build/playtests/nk3-current-landduel-native-red-43-headless`
(`81cc1dd4ccac4c25aa4cdd2da787ba07`). Full run:
`.build/playtests/nk3-current-landduel-model-red-43-headless`
(`5d514ee015fa4ebea301d6a4e6a3812d`). Root-reviewed final artifacts are
`nk3-current-landduel-native-red-43-reviewed-loss.json` and
`nk3-current-landduel-model-red-43-reviewed-win.json`; immutable copies are attached
to their runs through the tester outcome owner. Comparison:
`nk3-current-landduel-red-43-mode-comparison.json`; tester reports both the starting
conditions and strategy comparison as compatible. This is one map, one seed,
one starting side and two of the four required variants; it does not establish
statistical superiority. The prior day-3 seed-42 victory used an older bundle.

The full game has 14 valid controller replies, including two rejected natively
because delivery source and recipient were one physical army. Two requests time
out; one controller response omits a consistent actor/goal assignment. Accepted
strategies hold the home town, restore wood income, strengthen its defenses,
observe the eastern approach and then capture the opposing town. Its final own
snapshot contains both towns, a 32,519 hero army and an 8,286 home garrison, and
both terminal conquest messages corroborate the own day-23 win. The final capture
command is correctly labelled interrupted/reconciled_unknown at shutdown;
terminal and final ownership prove the match outcome without upgrading that
command's acknowledgement. Both games exit naturally with code 0, no active
owned process groups and unchanged protected files. No human game command,
checkpoint or tactical intervention was sent.

Known measured model usage is 305,888 input + 16,322 output = 322,210 tokens;
usage for the two timed-out calls is unknown. Native budget accounting charges
662,010 tokens conservatively and is not the actual usage. Request wait p50 is
43.383 s, p95 60.212 s. At most two requests occur in one own day in this pair.
The full match records 401 no-change native executions: 398 are repeated visits
for already-stationed future holding goals, at 39–40 per affected own day. Their
potential effect on other independent work needs a focused regression; the raw
count alone does not prove 401 lost useful opportunities.

An initial spectator-mode native run also lost on day 13, but its local defeat
dialog delayed the own AI terminal callback. Pinned CPlayerInterface::gameOver
waits for that dialog before the client finishes dispatching interfaces. The
already-finished private game was stopped, with cleanup and preservation
confirmed; it is retained separately and not included in the controlled pair.
The comparable pair uses headless mode and obtains complete own terminal records.

Fresh `prepare_engine.py .build/nk3-fresh-shipyard-source` succeeds at the pinned
engine/dependency revisions. All owned source bytes and tracked patch match the
already-built/tested prepared tree (`nk3-fresh-shipyard-source-proof.json`);
a second compilation of that fresh source clone was not performed.

### Passive holding avoids ineffective visits

The seed-43 full match exposed 398 repeated no-change holding visits. A separate
public strategy fixture assigns an already-stationed defender and an independent
scout. Its original test fails for 105 repeated holding visits in 8.194 seconds
(`nk3-holding-scout-red.log`, `.build/playtests/nk3-holding-2uemjvme`). The scout
actually completes in time; starvation was not established and is not claimed.
The accepted actor remains at its town while its future held_until predicate
remains pending.

`NativeCampaign::generate` now treats that stationed defender as waiting when no
legal army improvement is available from the town. Its role, army/resource floors
and deadline remain active; ordinary defense recruitment and other actors' work
continue. An owned source with a transferable surplus still permits acquisition.
The executor's whole-creature and free/matching-slot constraints apply to a
reserved source/destination; an unreserved source uses the existing native army
manager's reinforcement estimate. No command cache or saved waiting state is added.

An additional real starting garrison provides 100 pikemen. Native recruitment
legally consolidates its usable surplus into the stationed hero, leaving 5,963
source value against a 5,900 protected floor. The remaining 63 cannot supply one
89-value pikeman. A value-only initial guard still repeats the ineffective visit;
`nk3-holding-fractional-surplus-red.log` fails for that symptom in 8.609 seconds
(`.build/playtests/nk3-holding-m0h9vhbb`). An earlier assertion incorrectly required
the transfer to be attributed to the holding goal; raw records show it correctly
occurs within the ordinary recruitment owner, so the test checks acknowledged
hero gain and source reduction independently of that task label.

The final ordinary bundle is `.build/nk3-passive-holding-final-installed/VCMI.app`,
configured by `.build/nk3-passive-holding-final-config.json`. Both holding cases,
five defense scenarios, the reserved multiday delivery, and both owned-shipyard
resource cases pass: 10 real tests in 85.751 seconds
(`nk3-passive-holding-and-defense-green.log`). Three rebuilt C++ drivers pass
(`nk3-passive-holding-contract-proof.log`). All owned copied source bytes and the
tracked patch match the prepared tree (`nk3-passive-holding-source-proof.json`),
and `git diff --check` passes. The preceding reviewed competitive pair retains its
own immutable earlier bundle and provenance; this holding revision has not yet
received a new competitive full-match result. No staging, commit or final Review
has occurred.

### Known late delivery reports its deadline reason before expiry

The ordinary public delivery fixture has a visible owned source with 8,900 army
value, an initial 5,900 recipient and a 12,000 target. Its supported route arrives
on day 2 against a day-1 deadline. Before this repair, native local task admission
fails and the day-1 strategic request reports only `route_not_established`.
The durable RED (`nk3-known-deadline-red2.log`, run `nk3-deadline-kltapyre`)
fails in 7.525 seconds for the missing pre-expiry deadline explanation.

After local route/task generation has admitted no task, a forecast explicitly
marked `late_on_current_route` now produces `deadline_unreachable`, with the
supported route duration. This forecast does not veto admitted local repairs.
A changed route duration changes the semantic repair question; routine clock,
strategy revision and goal renumbering do not. Saved optional route duration is
validated; malformed executable intent is cleared while spent budget survives.

The final ordinary bundle is `.build/nk3-known-deadline-installed/VCMI.app`,
with `.build/nk3-known-deadline-config.json`. Three real tests pass in 31.187
seconds (`nk3-known-deadline-green.log`): one day-1 deadline review for the late
route, completed delivery on the same route with a day-3 deadline, and no model
retry for an unchanged renumbered blocker. Runs are respectively
`nk3-deadline-ag9hwvzr`, `nk3-deadline-v2akpc5k`, and
`nk3-critical-events-zxwiafbb`. Each private run confirms cleanup and unchanged
protected files. Three rebuilt C++ drivers pass
(`nk3-known-deadline-contract-proof.log`), including route-question and persistence
checks. Root/prepared source and patch equality is recorded in
`nk3-known-deadline-source-proof.json`. No competitive match, staging, commit or
final Review is claimed for this revision.

### Real operation stagnation, scheduled growth and a defended courier replacement

A second public fixture exposes a real admitted ineffective delivery. The source
has 8,900 value and an 8,850 defense floor, so its remaining 50 cannot supply one
89-value pikeman. Main remains at 5,900 against a 6,000 delivery target. With all
source dwellings forbidden there is no projected replacement stock. The route
and intent are admitted, but repeated visits do not transfer any troop.
`nk3-handoff-stagnation-premise2.log` is the meaningful RED: 9.975 seconds,
run `nk3-handoff-stagnation-kdy2x638`, 39 ineffective visits on day 1, 40 on day 2,
40 on day 3 and 18 before stopping on day 4; no stagnation review. The preceding
fixture attempt lacked a legal defender assignment and proves no native defect.

The native owner now preserves progress for nonholding operations by semantic
objective, relevant own participants and the actual source floor. It records
acknowledged tasks with no participant change, excluding unrelated income and
construction. Two own days without progress after repeated ineffective attempts
produce one combined semantic question. Goal numbers, revision and the routine
clock are excluded. A changed source pledge or route-repair policy permits fresh
execution. Stationed defense/preservation and construction retain their existing
separate waiting/progress rules. Unchanged stalled work becomes
`no_target_progress` and stops consuming further visit passes; it does not release
other obligations or reserves.

The first clock-only GREEN still repeats visits after a retained answer. Its
stronger RED (`nk3-operation-stagnation-repeat-red.log`, 10.055 seconds) justifies
the admission stop. The initial waiting extension also reveals a false day-8
stagnation request immediately before supported growth recruitment
(`nk3-operation-stagnation-wait-green.log`). A conditional pending purchase in the
accepted recruitment calendar now gets its native opportunity before stagnation
review, including a purchase due today.

Final ordinary bundle: `.build/nk3-operation-stagnation-final-installed/VCMI.app`,
config `.build/nk3-operation-stagnation-final-config.json`. The retained and
renumbered intents each ask once on day 3 and perform zero ineffective delivery
visits from that day onward. A revised source floor of 8,700 produces an
acknowledged day-3 transfer reaching at least 6,000 while preserving that floor.
These three cases, cash-wait control and both deadline cases pass in
`nk3-operation-stagnation-final-green.log`. Its seventh case actually completes
the weekly delivery without a stagnation request, but then fails the test helper's
old native-only zero-request assertion. That helper assertion is now conditional
on native mode. The repaired model weekly test and unchanged native weekly
control both pass in `nk3-operation-stagnation-save-and-weekly-green.log`; both
physically complete on day 8. Model requests on that boundary concern horizon or
campaign exhaustion, not routine daily income or stagnation.

A genuine console checkpoint is taken on own day 3 while the strategic exchange
waits. Stable save bytes are checked twice and copied to a recovery file before
stopping; the resumed manifest must pin the same digest. The game loads the exact
own day 3 and proceeds through day 5, including another own turn with renewed
wait allowance, without replaying the stalled delivery or asking the saved
addressed question again. `nk3-operation-stagnation-durable-save-green.log` passes
in 18.018 seconds. Run pair `nk3-handoff-stagnation-4m5ybmrn/{game,restored}` and
its `checkpoint.json` retain lineage, save SHA-256 and recovery copy. Three rebuilt
C++ drivers pass (`nk3-operation-stagnation-final-contract-proof.log`), including
valid operation-clock persistence and malformed-clock rejection without refund.

A separate defense fixture makes NK2 kill the named courier in an acknowledged
battle. Native replacement retains the recipient and delivery deadline; the main
hero receives the alternative helper's army, returns to the critical home town,
and completes `held_until` on day 6 with at least 12,000 army value. The town
remains owned throughout. `nk3-defense-courier-replacement-green.log` passes in
7.937 seconds (`nk3-helper-loss-24rbos75`). This is a controlled defense episode
against NK2, not a full competitive victory.

Ten focused successful scenarios (the checkpoint case has two game runs) on this
ordinary native revision are indexed with manifests, engine hashes, own-day ranges
and cleanup/preservation checks in `nk3-operation-stagnation-final-source-proof.json`.
All owned source bytes and the tracked patch match the prepared tree.
`git diff --check` passes. Historical failed test attempts remain retained.
No final broad suite, new competitive full match, staging, commit or independent
final Review is claimed for this revision.

## User-requested intermediate checkpoint: local courier repair

This is an implementation checkpoint, not final acceptance or comparative
superiority. The user explicitly requested an intermediate local commit before
continuing. Final independent Spec/Standards Review and the comparison series are
still pending. Older research proposals are excluded from this checkpoint.

The current ordinary bundle is
`.build/nk3-local-courier-review-final-installed/VCMI.app`, configured by
`.build/nk3-local-courier-review-final-config.json`. Native helper replacement is
performed before constructing the strategic review. The fresh task/forecast
boundary distinguishes supported future arrival from an impossible route; a
locally resolved courier-loss signature is persisted without spending a model
request or its wait/token budget.

The unchanged model-mode courier-loss reproduction originally requested reviews
on days 2 and 3 before delivery. Its retained failure is
`nk3-model-local-courier-repair-red.log`. An intermediate implementation still
failed (`nk3-model-local-courier-repair-green.log`; its filename does not imply
success). The final reproduction passes in 8.443 seconds:
`nk3-model-local-courier-repair-final-green.log`, run
`nk3-helper-loss-m3mrxb63/game`. The courier dies in battle, another helper
donates its army and the accepted delivery completes without a battle-loss,
commitment or repair-exhausted review. Campaign exhaustion remains a legitimate
separate decision.

The negative control reserves all 8,900 army value of the available replacement
for another obligation. That courier loss receives exactly one strategic
review, and the pledged army is retained. Together with the public arbiter's
budget/save/new-facts assertions, two tests pass in 8.860 seconds:
`nk3-local-courier-review-negative-and-budget.log`, run
`nk3-helper-loss-xvm9rf2e/game`. All three rebuilt C++ contract drivers pass in
`nk3-local-courier-review-final-contract-proof.log`.

The affected runtime regression series ran 13 tests in 153.932 seconds: 12 pass
and one fails. It is retained as
`nk3-local-courier-review-runtime-regression.log`. Critical-town loss, urgent
recruitment before model waiting, late/timely delivery, semantic stagnation,
stagnation save/load and native courier replacement/defense pass. Its real multiday courier
save/load case fails on this checkpoint: the helper choice survives, but the
restored force-preservation obligation becomes `force_continuity_unconfirmed`
and delivery does not complete by its deadline. Run pair
`nk3-helper-loss-ydy5gof3/{game,restored}` preserves both sides of that failure.
This is an open defect to investigate after the requested checkpoint, not a
passing restoration claim. Private runs report cleanup and protected-file
preservation. Raw build/run artifacts remain local under ignored `.build/`.

## Remaining acceptance work

Material weekly/checkpoint choices still need a complete requirement-to-behavior
check; ordinary supported growth waiting is now proved. The new stagnation clock
covers nonholding operation kinds, with actual ineffective delivery, semantic
renumbering, repaired delivery and save/load proof; movement-only loops and other
specific unmet progress paths are not claimed proved by that one fixture.
Defense-courier loss/replacement and holding the critical town are proved, while
the earlier reviewed competitive win belongs to its immutable older bundle.
Further required logistics/consequence/experience boundary checks, the frozen
four-variant comparison series with holdout cases and complete metrics, and final
current-source validation and independent Spec/Standards Review remain.

Supported movement is land, visible existing boats and currently quoted owned
shipyard construction under protected resources, with paired hidden-world proof.
Teleports and adventure movement spells remain explicitly unsupported; no claim
of those mechanics is required from the currently advertised capability set.
Full completion and comparative superiority are not claimed. The intermediate
checkpoint is explicitly requested; final delivery remains pending.
