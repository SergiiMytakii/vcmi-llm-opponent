# Public sources for Game Rules

## Decision to unblock

The user requested basic Heroes III / VCMI mechanics, explicitly separated from
strategy advice, then requested stronger grounding in open sources. This note
supports the six `controller/game_rules/rules/*.md` cards. It does not authorize
new strategic commands or assert better play.

## Short answer

Use the original NWC/3DO manual for classic explanations, then resolve defaults,
exceptions and conflicting descriptions against the pinned VCMI engine.
Current observations, scenario/mod configuration and native quotes govern the
actual game. Controller limitations are repository facts, not Heroes III rules.

Checked 6 October 2026. The publisher-distributed
[Heroes III manual, 1999](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/297000/manuals/BONUS_Heroes_of_Might_and_Magic_III_HDEdition_OldManual1999_EN.pdf)
was downloaded from Steam's document CDN and read with `pdftotext -layout`.
Printed and PDF page numbers match. Relevant pages were read in full: 10,
13–17, 28–33, 43–46, 50–55. The PDF is not copied into the repository.
Engine code was verified locally and through public first-party source at
`6a1ca68e00f540087f35579c62ffaf037f5be269`, the revision in `engine/version.json`.

## Findings

| Card / claim | Primary source | Version / confidence |
| --- | --- | --- |
| Day renewal, income, weekly available stock; initial setup skips another income payment; special weeks can change stock | Manual pp. 13, 52; VCMI [NewTurnProcessor.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/server/processors/NewTurnProcessor.cpp), `generateNewTurnPack`, `generateTownGrowth` | 1999 / pinned revision; high |
| Slowest creature affects land allowance; terrain/roads/Pathfinding affect cost; entirely native army avoids native penalty; normal embark/disembark costs remaining movement | Manual pp. 15–16, 45; VCMI [CGHeroInstance.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/mapObjects/CGHeroInstance.cpp), `isNativeTerrain`, `getLowestCreatureSpeed`; [TurnInfo.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/pathfinder/TurnInfo.cpp) | Classic baseline; native quotes govern exceptions; high |
| Battle creature-speed artifacts do not necessarily improve adventure travel | VCMI `CGHeroInstance.cpp`, `getMovementSpeed` excludes artifact speed sources | Pinned revision; high |
| Construction costs/prerequisites and one building per town/day are classic; VCMI uses a configurable cap and forbids constructing another owned Capitol | Manual p. 50; VCMI [CGameInfoCallback.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CGameInfoCallback.cpp), `canBuildStructure`; [gameConfig.json](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/config/gameConfig.json), `buildingsPerTurnCap` | Classic / pinned configurable default; high |
| Higher hall income replaces lower-tier production; growth includes Citadel/Castle bonuses; a second captured Capitol is removed | VCMI [CGTownInstance.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/mapObjects/CGTownInstance.cpp), `dailyIncome`, `getGrowthInfo`, `removeCapitols` | Pinned revision; high |
| Stock must be purchased; upgrading a dwelling differs from upgrading troops; classic upgrade price is the cost difference per creature | Manual pp. 51–54; VCMI `CGameInfoCallback.cpp`, `fillUpgradeInfo` | Classic formula; native quote authoritative; high |
| Seven homogeneous stacks, matching types merge, heroes keep a last creature during transfer/dismissal | Manual pp. 14, 28–32; VCMI [CCreatureSet.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/mapObjects/army/CCreatureSet.cpp), `getSlotFor`; `lib/constants/NumericConstants.h`, `ARMY_SIZE=7` | Classic / pinned revision; high |
| Garrisoning combines hero/town armies; a garrison hero is the town upper-army pool | Manual p. 54; VCMI `CGTownInstance.cpp`, `getUpperArmy` | Classic / pinned revision; high |
| Damage depends on quantity, range, Attack/Defense and modifiers; lucky strikes add damage rather than merely selecting maximum base damage | Manual pp. 33, 43–44; VCMI [damageCalculator.lua](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/scripts/damage/damageCalculator.lua), base damage, attack-defense and luck factors | Pinned formula resolves old wording; high |
| Morale can cause an additional or missed action; army composition changes morale; chance is configurable | Manual p. 44; VCMI [CArmedInstance.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/mapObjects/army/CArmedInstance.cpp), `updateMoraleBonusFromArmy`; [GameRandomizer.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/GameRandomizer.cpp), morale/luck rolls | Classic mechanism / pinned configuration; high |
| Survivor wounds heal after battle; deaths are not recovered by ordinary waiting; temporary recovery can differ | Manual p. 43; VCMI [BattleResultProcessor.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/server/battles/BattleResultProcessor.cpp), `CasualtiesAfterBattle` | Classic baseline / surviving counts govern; high |
| Spellbook, available spell, mana and learning-level access matter; Knowledge supplies capacity, Power affects effects; ordinary hero casting is once per combat round | Manual pp. 33, 45, 55; VCMI `CGHeroInstance.cpp`, `canLearnSpell`, `manaLimit`; default bonuses in `gameConfig.json` | Classic defaults with bonuses/exceptions; high |
| Default regeneration is one/day; new-day guild restoration preserves above-limit mana | Manual p. 55; VCMI `CGHeroInstance.cpp`, `manaRegain`, `getManaNewTurn`; `gameConfig.json`, `manaRegeneration` | Classic baseline / pinned actual restoration; high |
| Capture, hero defeat and elimination differ; retreat abandons former troops, paid surrender preserves survivors; VCMI rehire may supply a minimal stack | Manual pp. 10, 45–46; VCMI `BattleResultProcessor.cpp`; [HeroPoolProcessor.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/server/processors/HeroPoolProcessor.cpp), `onHeroEscaped`, `onHeroSurrendered` | Classic / pinned implementation; high |
| Townless count advances at the player's turn end and resets with town ownership; threshold belongs to the map condition | VCMI `NewTurnProcessor.cpp`, `onPlayerTurnEnded`; [CGameState.cpp](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/gameState/CGameState.cpp), `DAYS_WITHOUT_TOWN` | Pinned revision; high; enemy state remains hidden |
| Optional VCMI mechanics and mod ports differ from original engines | Official [Game Mechanics](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/docs/players/Game_Mechanics.md) and [FAQ](https://vcmi.eu/faq/) | Pinned docs / FAQ read 2026-10-06; high for scope, not installed mod state |

## Repository implications

Our adaptation keeps basic mechanics and conditional classic defaults in Game
Rules, comparisons in Strategy Guide, and mandatory guards in Native
Instructions. Cards contain source attribution and exceptions, not copied
manual text or fixed faction recipes. Catalog applicability mentions the actual
mechanics so the model can discover the relevant card.

`army_holder_ref`, native quotes, `resource_calendar`, forecasts and available
goal kinds are supplied by the current local `NativeCampaign.cpp`/controller
contract. AI values and loss estimates are conditional repository estimates,
not a manual-provided winning probability. `ObservationRules.h` owns visibility
and supported victory serialization; the reference reveals no enemy countdown.

This is our source-informed implementation choice: reuse the bounded reader but
keep separate catalogs, tools, snapshots and audits. It is not an externally
prescribed architecture. Full creature/spell tables, tactical commands and extra
capabilities remain outside the basic reference.

## Conflicts and unknowns

- Manual p. 27 says luck produces maximum damage; p. 44 describes double damage.
  Pinned VCMI has a positive luck factor in its damage formula. The card says
  bonus damage and leaves the full formula to the engine; it does not promise
  that every final damage result is exactly doubled.
- The manual's damage caps and morale/luck percentages are not copied into
  forecasts. VCMI exposes configurable factors/chances and optional mod changes.
- Old manual town-defense prose suggests visiting/garrison armies fight in
  sequence. Current VCMI has conditional siege merging; the card explains pools
  and uses current ownership/forecasts rather than promising two separate battles.
- Classic retreat loses the previous army; VCMI's rehire preparation supplies a
  minimal creature stack. A rehire quote governs actual troops, cost and timing.
- Sources establish default mechanisms, not loaded mods, current spellbooks,
  movement exceptions, future captures or hidden enemy assets. Missing fields
  stay unknown. No game effectiveness or victory rate was measured.
