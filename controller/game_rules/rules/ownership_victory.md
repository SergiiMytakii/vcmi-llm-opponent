# Ownership, defeat and victory

## Mechanics
- A town capture changes ownership of a base; a hero defeat resolves that battle. Player elimination is a separate event. In standard conquest all hostile teams must be defeated; surviving towns/heroes can keep a side in play. Maps can define additional or different victory/loss objectives.
- Under classic retreat a hero abandons the previous army but keeps artifacts and can return through a tavern. Paid surrender to an opposing hero normally preserves surviving troops and artifacts. Rehire has its own cost and availability; VCMI may give a retreated hero a minimal starting stack. Restrictions can prevent either outcome. A won hero battle therefore does not prove that hero or player is permanently gone.
- A public townless-defeat condition can eliminate a player after its stated period without towns. In the pinned VCMI counter, each townless player's turn end advances the count; owning a town resets it. Losing a town is not automatically immediate defeat while a hero survives.

## Applicability and exceptions
- Use actual victory.kind, supported status, public description and participants. An unsupported special objective stays unsupported. The public rule does not disclose unseen towns or enemy elapsed turns; the last observed town is not necessarily the last existing one.

## Facts to check
- With no own towns and a known public counter, the last capture day is current day + turns - own_elapsed_turns - 1. Six elapsed turns out of seven requires capture today, before turn end. Use the actual map period; an unknown counter does not establish a deadline. Owning a town resets the constraint.
- Read participant statuses, townless_defeat status/turns/basis, own_elapsed_turns, confirmed ownership changes and terminal results. A disappeared sighting proves no kill. Never invent a countdown or infer victory from an accepted goal.

## Executor boundary
- Apply the native outcome/terminal-result contract. Read Strategy Guide endgame for elimination choices; retreat/surrender commands remain unsupported.

Source: NWC/3DO 1999 manual, pp. 10, 17, 45-46; VCMI `6a1ca68e`.
