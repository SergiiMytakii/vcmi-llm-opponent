# ExternalAI development protocol

The engine launches `VCMI_EXTERNAL_AI_EXECUTABLE` with one argument,
`VCMI_EXTERNAL_AI_SCRIPT`, once per decision. Configure both as absolute paths;
there is no shell command interpolation. The current Python entrypoint is
`controller/main.py`, which calls Codex CLI through the user's ChatGPT login.
The engine adapter is independent of that provider.

The engine writes one UTF-8 JSON object to stdin and closes stdin. Input is
limited to 256 KiB; stdout must contain one JSON reply, at most 8 KiB, followed
by successful process exit. Diagnostics belong on stderr. The native adapter
discards stderr; the playtesting recorder preserves it separately. The native
process deadline is 40 seconds including launch; polling and cleanup can add
approximately 220 ms. Shutdown cancels an in-flight request. Windows launches
suspended, assigns the process to its owned Job Object, then resumes it; Windows
runtime verification remains outstanding.

## Requests and candidates

Each request contains `protocol: 1`, `request_id`, `observation`, `memory` and
`actions`. A request ID includes player, game day and decision index. The engine
persists the consumed decision count before calling the controller and permits
at most three calls per turn. A loaded game may reuse a request ID, so the tester
also assigns a unique recording ID. A controller reply is accepted only in the
current synchronous exchange; neither request IDs nor action IDs are durable
object references.

Observations contain the player's resources and explicit `resource_order`, own
heroes with exact armies/positions/movement, own towns/buildings/armies, and
player-visible objects. Enemy army descriptions expose only the permitted level
of detail: `count` for detailed information, otherwise `quantity_category`.
Missing information is unknown. `previous_unconfirmed_action`, when present,
is evidence of an uncertain result and must not be treated as a command to retry.

Visible resource piles and routes expose `resource_type`. Their `resource_amount`
is null with `resource_amount_visibility: "revealed_on_collection"`: map visibility
does not reveal hidden pile size. Visible mines/routes expose `resource_type`
and `production_per_day`, with `production_basis: "base_before_bonuses_and_handicap"`.
These describe public base production, not net income. Neutral abandoned mines keep
type/production null with `resource_visibility: "hidden_until_captured"`.
Resource facts remain in observed-object memory with its ordinary age/staleness.

`memory.resource_notifications` retains up to 16 player-addressed resource
information components: `resource_type`, signed `amount`, `source: "player_info_dialog"`
and `observed_day` (day incorporated into memory). This reveals exact quantities
actually shown to this player, including pickups, without reading uncollected map
amounts. Notifications do not identify a source object or independently prove
collection by a particular movement. They persist with ordinary AI local state;
callbacks buffer them under the request mutex for the turn worker.

The engine exports currently offered actions:

| Kind | Effect and relevant fields |
| --- | --- |
| `build` | Construct one normal building: `town`, `building`, `cost`. Automatic, Grail and special buildings are excluded. |
| `recruit` | Buy the stated creature/count from an owned town: `town`, `destination`, `creature`, `amount`, `cost`. The destination is the visiting owned hero when present, otherwise the town. |
| `hire_hero` | Hire an offered candidate from an owned town tavern: `town`, `hero_type`, `level`, `army`, `secondary_skills`, `cost`, `spawn_position`. Requires a free visiting slot, enough gold and both configured hero limits. No troop transfer or movement is included. |
| `upgrade` | Upgrade one existing owned stack through VCMI: `destination`, `slot`, `from_creature`, `creature`, unchanged `amount`, full `cost`. Availability is rechecked immediately before dispatch. |
| `transfer` | Move one complete town stack into its visiting owned hero, merging matching troops or using a free slot: `town`, `destination`, `creature`, `amount`, zero `cost`. The town loses those troops. |
| `visit` / `attack` | Move an owned `hero` toward an observed `target`; `travel_turns`, object type/ownership and permitted army information describe the candidate. Routes and battles belong to the engine. |
| `explore` | Move toward an offered visible frontier adjacent to unrevealed terrain. This does not disclose what is beyond it. |
| `end_turn` | Stop decisions and finish the turn. Always offered. |

Action IDs are opaque and valid only for the current request. Object IDs in
observations and action fields (`town`, `hero`, `destination`, `object_id`) are
player-local labels assigned when the object is first observed. They persist
across save/load; the private mapping to engine IDs is never sent to the model.
`target_ref` connects a
candidate to bounded party memory; it is not a remotely executable command.
Candidates may be legal but strategically unsafe. Movement can stop after an
interaction, battle or exhausted movement; a progress result is not proof of
reaching or capturing the target. Recruitment into a distant town does not
reinforce the hero until a separate transfer occurs at that town.

`observation.hero_limits` reports own `on_map_count`, `total_count` and their
configured `on_map_cap` / `total_cap`. Hero offers come from the player's tavern
pool and have no owned object ID before hiring. The adapter rechecks availability,
ownership, slot, gold and limits before dispatch. Confirmation requires the new
owned visiting hero of the chosen type, an increased own hero count and exact
resource deduction. Adventure taverns and inviting the next candidate are excluded.

Illustrative reply:

```json
{"protocol":1,"request_id":"0:1:0","action_id":"build-0","strategy":null}
```

The three identity/choice fields are required. The optional `strategy` field is
an intention-only update validated against the memory contract; the Codex output
schema requires it when memory is supplied. `null` retains the previous plan.
Deterministic fixtures and fallback may omit it. See [party memory](strategy-memory.md)
for its fields, limits and distinction between intentions and engine observations.

## Execution and failure

The adapter rejects stale IDs, unoffered actions, malformed JSON, excess fields,
oversized output, nonzero exit and timeout. Failure ends the turn. Before dispatch
it rechecks the active player, object ownership, costs/availability or transfer
slots, and movement visibility. It uses ordinary engine callbacks and server
validation. After each successful action it builds a fresh observation.

Construction success is checked in town state. Recruitment checks army counts,
remaining stock and resources. Transfer checks both armies and unchanged resources.
Movement checks the hero's observed position/movement. Routes are recalculated
after confirmed steps, with boats, teleports, flying and adventure movement spells
disabled. Adventure work remains blocked until the engine's
`battleEnded` callback; time spent in an active battle does not consume the
request-acknowledgement deadline, and shutdown cancels that wait. The model
deadline remains separate and unchanged.
BattleAI handles combat. Package acknowledgement alone does not establish these
postconditions. Uncertain actions are recorded, not replayed automatically.

Attempts, pending intent and bounded memory are written into the player's
`playerLocalSettings._namespaces.ExternalAI`. The patched server preserves that
namespace when replacing ordinary UI settings. The callback API and binary
`SaveLocalState` layout are unchanged from the pinned upstream engine: AI updates
use `{"_namespaces":{"ExternalAI":state}}` inside the existing JSON field.
Namespace-only updates leave UI fields untouched; ordinary UI snapshots replace
UI fields while retaining server-held namespaces. The AI host and server need
our integration. A human peer does not need Codex or ExternalAI, but still needs
a compatible VCMI version and matching game mods. Full stock Windows peer
acceptance is pending; wire compatibility alone does not prove a network match.
See [standard-client checks](testing/standard-client-compatibility.md).
A native save made during a controller request has been loaded
in a new process: the plan, completed purchase and remaining attempt budget were
restored, and the next day reset the budget. Saves during battles and unacknowledged
actions still require separate acceptance; see the runtime verification report.

Codex uses pinned CLI 0.160.0, `gpt-6.1-sol`, medium reasoning, ChatGPT login and a
restricted model profile with tools disabled. Its internal deadline is 35 seconds,
with a 37-second recorder limit and 40-second native deadline. There is no API-key fallback.
Missing authentication, unsupported CLI, timeout or invalid output produces an
offered end-turn response with separate `provider: fallback` diagnostics. The
current no-tools wire proof and native runtime limits are documented in the local
verification evidence; Windows still needs independent verification.

Own `heroes` is always a complete array, including `[]`. `memory.own_force_changes` records `no_longer_owned` from consecutive complete lists; missing legacy fields remain unknown. It does not assert a cause of loss. `capabilities` describes adapter operations, not guaranteed future candidates.

Movement candidates include `arrival_turn_offset`, `turn_stop`, `route_encounters`, and `stop_threats`. The stop is conditional on an unchanged route; the first interaction has an unknown outcome and may stop before/at its tile or lose the hero. Threats use visible enemies and aged sightings only; tile distance is proximity, while interception and unseen threats remain unknown.

Build `effects` distinguish unchanged existing stacks, dwelling creature/stock, and separately offered recruitment or upgrade. Construction is not reinforcement. Confirmed upgrades require unchanged stack count, the new type, and exact resource deduction.

Army metadata uses VCMI creature AI values: own stacks include unit value, base health/speed and ranged role; own heroes include total creature value, primary skills, mana and the native fighting multiplier. Visible enemies expose an estimate and a category-derived range only; an unbounded legion or unknown count has no invented upper bound. Hero bonuses, spells, tactics and siege are not simulated. Known town `fort_level` remains separate. Movement `combat` supplies a creature-value comparison, explicitly leaving losses unknown.

Own towns expose actual current daily income, stock/current growth and next weekly growth time. Builds expose production and its delta against a built predecessor, gold-only payback before handicap, and the stated projection limits for bonuses. Recruitment, transfer and upgrade expose creature-value gain and whether it joins a hero now or requires separate visit/transfer. A reinforcement return includes known garrison value and explicitly unknown onward travel/conditional purchases. Compare these with travel, route threats and remaining decision budget; future operations are not guaranteed.

Memory schema 2 adds executor and typed readiness/completion conditions to the strategy JSON schema. Python and native validation agree; the adapter independently records progress and required reconsideration. See strategy-memory.md for migration, result cursors and statuses.

Movement candidates also expose `route_steps`: edges remaining in the currently known player-scoped path, independent of daily movement replenishment. Goal progress keeps the shortest observed route and strongest observed executor army; reaching either previous best again does not reset stagnation. Missing paths stay unknown. Fresh changes in target information, new target-town army high-water marks, newly built target-town buildings and new resource high-water marks for non-hero goals can also justify progress.

Each own town has `defense`: its creature army value, fort level, separate stationed hero values, current/aged enemy-hero sightings measured from the town, offered hero return routes and recruitment action IDs. Enemy arrival remains null; distance is last observed tile proximity, not enemy routing. Sightings are removed from positional threats once their old tile is visible and empty. Absent return candidates mean unknown/not currently offered. Town and garrison-hero values may overlap and must not be summed as a battle forecast.

Own heroes include `level` and known `secondary_skills`. Level-up callbacks choose only an offered skill, without additional model calls. The deterministic heuristic favors ranged/melee army fit and travel skills for travel objectives; the active executor's typed target determines its role, otherwise the strongest own army supplies the combat role. Unsupported or tied options preserve their offered order. This is a bounded heuristic, not a claim of optimal development for every faction or mod.

Blocking visits stop before their interaction tile. Equal-cost replanning may choose another visible reachable neighbouring tile; `turn_stop.possible_positions` gives that conditional envelope, and `interaction_position` remains separate. Threat proximity uses the minimum over possible stops. Native proof compares actual stopping with the envelope, rather than claiming one exact approach.
Build effects also include the player-visible building description and fortification component; these are game data, not instructions.
