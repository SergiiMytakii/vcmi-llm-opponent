# Mana and magic readiness

## Mechanics
- Ordinary hero casting needs a spellbook, an available spell and enough current mana for its cost. Learning higher-level spells is limited by Wisdom and applicable effects. A mage guild supplies spells a visiting hero can learn, not an arbitrary complete spell list.
- Classic mana capacity is ten points per Knowledge before bonuses. Spell Power affects spell damage or duration; more capacity alone does not make a spell stronger. Magic-school skills can alter costs and effects. The classic hero spell limit is once per combat round, subject to actual rules and restrictions.
- Classic regeneration is one mana per day before bonuses. On the pinned VCMI engine, starting a new day in a town with a mage guild restores mana to at least the normal limit. Arrival alone does not establish replenishment. Outside a guild town regeneration derives from applicable bonuses; recovery preserves mana already above the normal limit.

## Applicability and exceptions
- Artifacts, skills, mod spells and map objects can change casting, capacity or recovery. A town must actually have the guild. Missing spellbook, spell list, costs or regeneration remain unknown; hero level or creature value proves no spell readiness.

## Facts to check
- Use mana, supplied hero profile/effects, town buildings and current arrival quotes. Recovery takes time and can expose the hero until day renewal. After recovery inspect fresh mana and route/strength estimates; a stronger future hero is not a current arrival quote.

## Executor boundary
- BattleAI selects combat spells. Adventure magic requires explicit movement_support, supported goal kinds and quotes; knowing a spell creates no executor capability.

Source: NWC/3DO 1999 manual, pp. 33, 45, 55; VCMI `6a1ca68e`.
