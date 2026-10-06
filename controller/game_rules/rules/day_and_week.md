# Day, week and movement

## Mechanics
A player's turn is part of a game day. In classic sequential play the next day begins after all players finish. Day renewal grants movement and owned-town/mine income. A seven-day week adds dwelling growth to recruitment stock on its first day; these creatures still need purchase and delivery.

Land movement allowance depends on the slowest creature in the army, plus hero bonuses. Terrain changes travel cost; roads lower it and Pathfinding reduces difficult-terrain penalties. An army entirely native to a terrain avoids its native-terrain penalty. Adventure movement and battle speed are different: a creature-speed artifact need not increase adventure travel.

A hero needs a boat for normal water travel. Classic embark/disembark consumes remaining movement. A subterranean gate connects map levels; reaching its entrance does not reveal an unknown exit in advance.

## Applicability and exceptions
VCMI calendar, movement bonuses, simultaneous turns and mods can alter defaults. Initial game setup is not another paid income day. Special weeks may modify growth or reduce existing stock. Unused movement does not accumulate into tomorrow's allowance; a boat exception needs current rules or a native quote.

## Facts to check
Use day, days_in_week, movement, movement_per_day, daily_income, resource_calendar, movement_support and own_arrival. Quotes govern actual arrival and interaction costs. Known gates need an observed connection; fog remains unknown. Changing troops can change later travel estimates.

## Executor boundary
Native code owns routes and turn progression. Model goals use supported land/boat/passage capabilities; a general game rule creates no teleport or boat spell command. A route is not proof of safe arrival or safe overnight exposure.

Source: [NWC/3DO manual, printed pp. 13, 15-16, 45](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/297000/manuals/BONUS_Heroes_of_Might_and_Magic_III_HDEdition_OldManual1999_EN.pdf). VCMI exceptions checked against engine revision `6a1ca68e00f540087f35579c62ffaf037f5be269`.
