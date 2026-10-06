# Mana and magic readiness

## Mechanics
Ordinary hero casting needs a spellbook, an available spell and enough current mana for its cost. Learning higher-level spells is limited by Wisdom and applicable effects. A mage guild supplies spells a visiting hero can learn, not an arbitrary complete spell list.

Classic mana capacity is ten points per Knowledge before bonuses. Spell Power affects spell damage or duration; more capacity alone does not make a spell stronger. Magic-school skills can alter costs and effects. The classic hero spell limit is once per combat round, subject to actual rules and restrictions.

Classic regeneration is one mana per day before bonuses. On the pinned VCMI engine, starting a new day in a town with a mage guild restores mana to at least the normal limit. Arrival alone does not establish replenishment. Outside a guild town regeneration derives from applicable bonuses; recovery preserves mana already above the normal limit.

## Applicability and exceptions
Artifacts, skills, mod spells and map objects can change casting, capacity or recovery. A town must actually have the guild. Missing spellbook, spell list, costs or regeneration remain unknown; hero level or creature value proves no spell readiness.

## Facts to check
Use mana, supplied hero profile/effects, town buildings and current arrival quotes. Recovery takes time and can expose the hero until day renewal. After recovery inspect fresh mana and route/strength estimates; a stronger future hero is not a current arrival quote.

## Executor boundary
BattleAI selects combat spells. Adventure spells need explicit support and quotes; general knowledge of Town Portal or Summon Boat creates no command. Current movement_support and supported goal kinds govern what the strategic model can execute.

Source: [NWC/3DO manual, printed pp. 33, 45, 55](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/297000/manuals/BONUS_Heroes_of_Might_and_Magic_III_HDEdition_OldManual1999_EN.pdf). VCMI exceptions checked against engine revision `6a1ca68e00f540087f35579c62ffaf037f5be269`.
