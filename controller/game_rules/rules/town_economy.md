# Town economy and recruitment

## Mechanics
All owned towns spend one shared resource treasury. Town income buildings and mines produce recurring resources; a purchase consumes resources now. Classic construction allows one building per town each day. Prerequisite buildings need their own costs and construction days; a hall upgrade replaces its lower income tier rather than stacking both incomes.

A dwelling creates production and available recruitment stock. Buying creatures spends that stock and its quoted per-unit price. Availability is not an army. New troops belong to the actual receiving hero/garrison and help a distant hero only after delivery.

Building an upgraded dwelling, recruiting upgraded creatures and upgrading existing troops are different operations. Classic troop upgrade cost is the recruitment-price difference times the affected quantity; it does not create extra creatures. Upgraded and base creatures are distinct stack types.

## Applicability and exceptions
VCMI makes construction caps, faction prerequisites, prices and growth configurable. Citadel/Castle and other bonuses can change growth. Special weeks, map events and initial dwelling stock can change availability. VCMI restricts building another Capitol while one is owned; on capturing a second Capitol its Capitol building is removed. Confirm resulting buildings rather than promising retained income.

## Facts to check
Read buildings, building_options/availability, income_delta, recruitment_options, available, unit_cost, weekly_growth and resource_calendar. Each quantity quote from one stock is an alternative, not another pool. Costs, prerequisites and recipients come from current data.

## Executor boundary
Use supported building and reinforcement operations. Construction or funds alone establish neither purchase nor delivery. An upgrade requires current native support; after any change use confirmed results and fresh quotes.

Source: [NWC/3DO manual, printed pp. 50-54](https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/297000/manuals/BONUS_Heroes_of_Might_and_Magic_III_HDEdition_OldManual1999_EN.pdf). VCMI exceptions checked against engine revision `6a1ca68e00f540087f35579c62ffaf037f5be269`.
