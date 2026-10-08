# Combat strength and losses

## Mechanics
- Stack damage depends on creature count, its damage range, attack versus defense and applicable modifiers. A hero's Attack and Defense contribute to troop combat statistics; spells, skills, artifacts, speed, shooting and abilities also matter. Morale can give another action or prevent acting; luck can trigger bonus damage. These are conditional effects, not guaranteed actions or damage.
- Siege walls, towers and moat can change attacks and losses. Winning a fight can still leave too few troops for another fight or defense. Survivor wounds normally heal when combat ends; dead creatures are not restored merely by waiting. Special recovery/resurrection mechanics need actual effects and confirmed surviving counts.
- Creature AI value and hero-adjusted strength are estimates, not win probabilities. Different creature counts are not comparable strength. Route encounters and target combat can both consume the same army; favorable values do not guarantee a lossless operation.

## Applicability and exceptions
- VCMI uses configurable damage factors and morale/luck chances; do not copy fixed probabilities or old-manual damage caps. Creature immunities and morale exceptions may change with mods. Apply effects only when supplied; enemy skills, spells and unbounded counts remain unknown.

## Facts to check
- Distinguish army_ai_value, hero_multiplier, hero_combat_value, fighting_strength_estimate, army_interval, fortifications and path/target loss_estimate. Compare forecasts with own_battle_result. Starting minima and retained post-loss floors differ; permission to risk losses is not a casualty prediction.

## Executor boundary
- BattleAI chooses tactical movement, spells and stack actions; the strategic model uses the common goal-risk and battle-receipt contract.

Source: NWC/3DO 1999 manual, pp. 33, 43-46; VCMI `6a1ca68e`.
