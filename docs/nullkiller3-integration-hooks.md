# Nullkiller3 integration hooks

Scope: `engine/integration.patch` against `engine/version.json` revision
`6a1ca68e00f540087f35579c62ffaf037f5be269`. Paths below are relative to
`AI/Nullkiller2` unless stated otherwise. Hooks remain separate: generation,
ranking, command admission and acknowledged effects have different contexts.
No hook is merged or removed by the observation projection extraction.

`NativeCampaign::observe` still drains battle facts, expires own-return markers,
builds resources, drains visit/site/passage receipts, filters goal-specific
receipts, publishes rules, projects own heroes/towns and sorted visible objects,
records frontiers/memory, drains battle/force facts, recovers pending execution
and reviews the campaign in that order. Its stateless projection functions
receive resolved aliases and const facts; they never write `persisted`.
`PlayerView`, `observedArmyStrength`, `observedArmyInterval` and
`observedBoatPlacement` remain the existing visibility owners.

| Duty | Patch call site | Moment and preserved check |
| --- | --- | --- |
| Mode/restore | `lib/callback/AIFactory.cpp`: `createAdventureAI`, `isAvailableAdventureAI`; `AIGateway` and `Engine/Nullkiller` constructors, `Nullkiller::init` | Only Nullkiller3 creates the strategic campaign and PlayerView; restore uses player-local namespaces. NK2 keeps its ordinary mode. |
| Visibility | `Nullkiller::gameInfo`, `observedObject`, `visibleGuards`, `visibleGuardPosition`, `observedStrength`, `getPathsInfo`, `init` | Path calculation uses PlayerView, object lookup is player-visible, non-owned armies use UI estimates, open-map mode and unsupported movement are disabled before paths. |
| Observation ordering | `Nullkiller::updateState` | Check active turn; refresh PlayerView; observe; update learned passages/invalidate paths; native analyzers; then forecast update. |
| Visibility/memory | `AIGateway::makeTurn`, `memorizeRevisitableObjs`, `getFlaggedObjects`; `Engine/AIMemory::visitableIdsToObjsVector/Set` | Memorization and remembered-object dereference use player-visible callbacks in strategic mode. |
| Visibility/admission | `AIUtility::shouldVisit` | Reject invisible objects before ordinary independent visit generation; restrict supported object types and enemy targets. |
| Visibility/threat | `Analyzers/DangerHitMapAnalyzer::updateHitMap`, `updateObservedHitMap`, `calculateTileOwners` | Use observed enemies/strength and visible adjacent legal movement; unknown arrival remains unknown before defense generation. |
| Visibility/roles | `Analyzers/HeroManager::getHeroRoleOrDefault`, `getFightingStrengthCached` | Own campaign roles override native defaults; enemy private hero multipliers are not read. |
| Visibility | `Analyzers/ObjectClusterizer::getBlocker`, `clusterize`; `Behaviors/CaptureObjectsBehavior::decompose`, `ClusterBehavior::decomposeCluster`, `ExplorationBehavior::decompose` | Use visible guard/object access before clustering/decomposition; land-frontier exploration remains. |
| Visibility | `Behaviors/StartupBehavior.cpp`: `needToRecruitHero` | Use estimated visible strength; skip private reward configuration in strategic mode. |
| Visibility/valuation | `Engine/FuzzyHelper::evaluateDanger` overloads; `Engine/PriorityEvaluator` RewardEvaluator army reward/growth, gold cost/reward, enemy hero strategic value, strategic/conquest/skill value; defense evaluation | Public estimates/constants replace private enemy data during evaluation; enemy speed is not used for strategic counterattack timing. |
| Visibility/routes | `Pathfinding/AIPathfinder::updatePaths`; `AIPathfinderConfig` construction/ruleset | Own towns and visible dwellings feed chains; every initial, repeated and final path calculation uses `gameInfo`; movement options are restricted. |
| Visibility/routes | `Pathfinding/ObjectGraph::connectHeroes`; `ObjectGraphCalculator::setGraphObjects`, `addMinimalDistanceJunctions`, `calculateConnections` | Visible objects/guards only, before graph edges (strategic open graph is disabled in init). |
| Movement admission | `Helpers/ExplorationHelper::canUseDimensionDoor`; `Pathfinding/AINodeStorage::calculateTownPortalTeleportations`; `Pathfinding/Rules/AILayerTransitionRule::process`, `setup`, virtual boat collection | Reject unsupported layers/spells; quote only observed boat placement; do not synthesize summon-boat routes. |
| Visibility/routes | `Pathfinding/Rules/AIMovementAfterDestinationRule` destination/source guards; `AIMovementToDestinationRule` constructor/process | Both sides of guarded movement use PlayerView; destination rule holds const game-info interface. |
| Resource admission | `Pathfinding/Actions/BoatActions` build-boat action feasibility | Visible placement and campaign planned boat funds before offering a route. |
| Delivery admission | `Behaviors/GatherArmyBehavior::decompose`, `deliverArmyToHero` | Named source/receiver constrain native paths; use direct delivery value; explicit useful deliveries retain reserve checks rather than autonomous size threshold. |
| Discovery admission | `Goals/ExploreNeighbourTile`: `getNeighbourExplorationTarget`, `evaluateNeighbourExplorationCandidate` | Strategic neighbors require actual discovery as well as same-day, accessible and safe movement. |
| Fresh task bindings | `Goals/AbstractGoal`, `RecruitHero::getHero/getCandidate` | Strategic IDs/ranks/emergency fields live on fresh tasks only; a tavern candidate is not an owned executor. |
| Ranking | `Nullkiller::choseBestTask`, `setNativeTaskRank`, `buildPlanAndFilter`; `TaskPlan::mergeAndFilter`; final `makeTurn` sort | Evaluate NK2 alternatives before campaign priority/conflict filtering; stable comparison preserves urgent tier, goal priority/order and native rank. |
| Generation/reserves | `Nullkiller::makeTurn`, `updateStateAndExecutePriorityPass`, `getFreeResources` | Native decomposer executes campaign/defense candidates; bounded urgent purchases and safe survivor moves precede strategy wait; locked/campaign resources remain reserved. |
| Execution/effects | `Nullkiller::executeTask` | Turn check and beginExecution precede task accept; endExecution classifies acknowledgment/failure/interruption; subsequent observe/persist confirm effects. |
| Replan | `Nullkiller::executeTask`, `makeTurn`; `AIGateway::moveHeroToTile` afterMovementCheck | Acknowledged combat loss interrupts old composition; invalidate/reobserve/persist before more work; skip old trade and run idle correction before turn end. |
| Turn lifecycle | `AIGateway::yourTurn`, `makeTurn`, `checkStrategicTurn`, `playerEndsTurn`, `finish`, `gameOver`; `executeActionAsync`; `AIStatus::waitTillFree` | Serialize strategic workers; validate expected day/current player; cancel exchange and interrupt on turn end/exit; callbacks unwind without waiting for model deadline. |
| Learning effects | `AIGateway::makeTurn`, `playerEndsTurn`, `gameOver` | Record begin/end observations; publish completed turn only after playerEndsTurn; terminal result after confirmed victory/loss. |
| Visit effects | `AIGateway::heroVisit` | Queue only own visitor's acknowledged start/end for resources, sites, borders and passages. |
| Force/resource effects | `AIGateway::garrisonsChanged`, `receivedResource` | Queue own force minima and current funds after engine callbacks, before later observation/review. |
| Battle effects | `AIGateway::battleStart`, `battleEnd` | Bind opponent; capture own army/casualties/outcome; save own-return update before queueing immutable result. No spectator army data is sent. |
| Delivery effects/admission | `AIGateway::heroExchangeStarted`, `moveCreaturesToHero` | Observe current campaign; select receiver and bracket authorized delivery; capture before values; record receipt only after transfer; preserve query acknowledgment ordering. |
| Force/command admission | `AIGateway::pickBestCreatures` | Recheck source/destination reserve after acknowledged commands; transfer only surplus; preserve last stack. Every merge/split remains turn-gated. |
| Command boundary | `AIGateway::makePossibleUpgrades`, `recruitCreatures`, `pickBestArtifacts`, `moveHeroToTile`, `buildStructure`, `tryRealize(DigAtTile/Trade)`, `endTurn` | `checkStrategicTurn` remains immediately before each upgrade, recruit/merge, artifact swap, movement/teleport step, build, dig, trade and endTurn command. Recruit/trade use free funds. |
| Command boundary | `Goals/AdventureSpellCast::accept`, `BuildBoat::accept`, `BuildThis::accept`, `BuyArmy::accept`, `Composition::accept`, `ExchangeSwapTownHeroes::accept`, `ExecuteHeroChain::accept`, `RecruitHero::accept` | Turn checks remain at each command/elementary task/chain step. Recheck boat visibility/funds, build funds, dismissal reserve, owned chain participants, garrison retention and funded legal hiring; hired effect recorded after callback acknowledgment. |
| Exit/cancellation | `client/ClientCommandManager::handleQuitCommand`; `lib/CConsoleHandler::run` | Console quit dispatches to the main thread to tear down interfaces/pending waits; macOS stdin polling preserves shutdown responsiveness. |
| Persistence | `server/NetPacksServer.cpp`: `visitSaveLocalState` | Apply namespace merge after wrong-player gate; do not replace unrelated state. |
| Save/checkpoint | `server/CGameHandler::save/tick`; `server/processors/TurnOrderProcessor` configure/start/end/day/resume/tick hooks | Successful save is explicit; optional tester review pauses at completed-day boundary, event-loop permit resumes; controls are not serialized into ordinary saves. |

The remaining patch hunks are integration infrastructure: AI/libFacade CMake
links and source inclusion; client assignment/save-console plumbing; macOS profile paths and window redraw cancellation. They add no NK3
planner or visibility hook. Existing `checkStrategicTurn` calls are intentionally
repeated at individual command boundaries: state may change between commands,
so identical spelling does not establish duplicate context.
