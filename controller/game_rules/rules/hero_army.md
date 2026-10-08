# Heroes, stacks and garrisons

## Mechanics
- A classic army has seven slots, each holding a stack of one creature type. Identical types can merge; a different type needs a free slot. Base and upgraded creatures count as different types. A stack's quantity is not its combat strength. Classic field heroes must keep at least one creature when dismissing or transferring troops.
- Town recruitment stock, the stationary town army and a visiting hero's army are distinct concepts. Garrisoning a hero combines that hero's army with the town garrison; VCMI's upper army then resolves to that hero's pool. Count it once. Troops in a departing hero's army leave with that hero; emptying this pool does not leave identical defenders behind.
- Army composition also has consequences: mixing several factions or undead with living troops can reduce morale. Native terrain and the slowest creature can affect travel. Equal total army values can therefore have different properties.

## Applicability and exceptions
- Mods and bonuses can change morale or creature behavior; some creatures ignore morale. Use actual creature IDs and current packing/last-creature constraints. A visiting hero can have a separate pool, and siege handling can combine defenders. Town/hero names alone do not identify physical army ownership.

## Facts to check
- Read army_units, army_holder_ref, reinforcement_sources, meeting options and retained floors. A full seven-stack recipient accepts only compatible current types under this executor. Current troops, pledged troops and future recruits are different commitments.

## Executor boundary
- Use reinforce_hero for delivery and prepare_garrison for stationary preparation under the common admission/receipt contract.

Source: NWC/3DO 1999 manual, pp. 14, 28-32, 54; VCMI `6a1ca68e`.
