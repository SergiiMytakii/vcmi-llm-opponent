# Безопасные наблюдения и действия VCMI 1.7.5

## Decision To Unblock

Определить узкий адаптер для одного героя и города: LLM выбирает строительство, найм, цели, разведку и нападение; VCMI исполняет пути и бои. Проверены исходники `6901839ae9760dfcd1d5ff2c4aa4ef6968fee752`, 3 октября 2026. Runtime-инварианты нового адаптера ещё не проверены.

## Short Answer

Инженерный выбор: отдельный adventure AI на прямых `CCallback`, штатном `PathfinderCache` с `SingleHeroPathfinderConfig` и `CAdventureAI`/BattleAI. Из AIGateway использовать проверенные образцы обработки событий, а не весь стратегический цикл Nullkiller2. Не вызывать его `makeTurn`, BuyArmy, автоматическую торговлю/улучшения или стратегические danger-анализаторы. Это уточняет исходную рекомендацию о небольшом форке Nullkiller2: готовые макроисполнители имеют незаявленные расходы.

## Findings

Все ссылки ниже закреплены на VCMI 1.7.5. Уверенность высокая для кода; новый адаптер не реализован.

| Claim | Primary Source | Version / Date | Confidence |
| --- | --- | --- | --- |
| getObj проверяет видимость, но возвращает rich object pointer; нужен ручной DTO | [CGameInfoCallback.cpp:114](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CGameInfoCallback.cpp#L114-L129) | 1.7.5 | Высокая |
| Town/hero info ограничивает подробности по доступу и учитывает Visions/Disguise | [Town](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CGameInfoCallback.cpp#L222-L242), [Hero](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CGameInfoCallback.cpp#L267-L385) | 1.7.5 | Высокая |
| Own lists доступны отдельно; getGrailPos и unchecked tile не входят в allowlist | [Own lists](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CPlayerSpecificInfoCallback.cpp#L34-L82), [Tiles](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CGameInfoCallback.cpp#L498-L514) | 1.7.5 | Высокая |
| Single-hero pathfinder есть; unrevealed cells блокируются, транспортные механики имеют options | [Cache](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/pathfinder/PathfinderCache.cpp#L21-L35), [Fog gate](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/pathfinder/PathfinderUtil.h#L25-L29), [Options](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/pathfinder/PathfinderOptions.h#L23-L38) | 1.7.5 | Высокая; полная fog-безопасность не доказана |
| AIGateway town interaction сам улучшает войска и покупает spellbook; recruitment dialog сам нанимает | [Town interaction](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/AIGateway.cpp#L810-L835), [Recruitment](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/AIGateway.cpp#L295-L303) | 1.7.5 | Высокая |
| BuyArmy улучшает и может удалять стеки; Nullkiller makeTurn торгует ресурсами | [BuyArmy](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/Goals/BuyArmy.cpp#L32-L92), [Trade](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/Engine/Nullkiller.cpp#L525) | 1.7.5 | Высокая |
| Удаления скрытых объектов приходят AI; нельзя превращать их в стратегическое знание | [AIGateway](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/AIGateway.cpp#L324-L349) | 1.7.5 | Высокая |
| Direct commands отправляют запросы; успешный bool build не подтверждает результат сервера | [Build](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CCallback.cpp#L220-L230), [Recruit](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CCallback.cpp#L62-L69), [Server](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/NetPacksServer.cpp#L141-L170) | 1.7.5 | Высокая |

## Repository Implications

Следующие пункты — предлагаемый контракт нового адаптера, а не существующее API:

- Snapshot: opaque version, player/day, свои ресурсы, герой (позиция/движение/своя армия), город (здания/гарнизон/доступный найм). Только собственные данные — точные.
- Видимая карта: выбранные поля открытых клеток, видимые объекты и их посещаемые позиции. Не сериализовать указатели, game state, TerrainTile целиком или object-specific hidden fields.
- Чужие hero/town — только отредактированные callback descriptors. Нейтральная видимая армия — coarse `InfoAboutArmy(..., false)`. Сохранять признак detailed/category; оценки строить только из этой проекции. Не экспортировать скрытые exact counts, награды, истинную силу или риск, рассчитанный по полному объекту.
- Память — копии ранее разрешённых DTO с last_seen и stale. Скрытое удаление очищает опасный внутренний указатель, но не обновляет знания модели о мире.
- Ответ модели: только observation_version и action_id из предложенной таблицы; числовые параметры хранит адаптер.
- BUILD — одно здание с полной ценой; RECRUIT — конкретные существо, число, источник и назначение с полной ценой. Town-only. Передача гарнизона своему visiting hero — явный бесплатный эффект кандидата с проверкой допустимых стеков. Не включать скрытые upgrade/trade/spellbook/dismiss.
- MOVE/VISIT/ATTACK — собственный герой и известный объект либо открытая frontier-клетка рядом с неизвестной областью. Путь выбирает штатный single-hero pathfinder с выключенными морем, телепортами, полётом и water walking. Исполнять по шагам через обычные команды. После боя, query, новой информации или изменения владения пересобрать наблюдение и перепроверить продолжение.
- END_TURN всегда доступен. Неизвестный платный query отклонять; обработчики бесплатных обязательных запросов должны быть явными. Резервный алгоритм использует те же DTO/кандидаты и проверки.

Проверка fog: парные состояния с одинаковыми доступными знаниями и историей, но разным скрытым миром должны дать одинаковые DTO, кандидаты/порядок/IDs/цены и команды при фиксированном выборе. Отдельно менять exact counts внутри одной видимой quantity category. Проверять pathfinder и fallback, а не только prompt. Нельзя считать сам факт наличия fog gate доказательством инвариантности.

Проверка расходов: перехватить исходящие economy-команды; выбранное действие производит только заявленные расходы и transfers. Вынужденные игровые последствия движения/боя описываются отдельно от инициативных покупок AI.

## Conflicts And Unknowns

- Прямой адаптер ещё нужно реализовать: callbacks, query handling, состояние хода и движение не получаются автоматически из библиотеки pathfinder.
- Если pathfinder не проходит инвариантность, сузить или исправить конкретный путь до LLM-подключения. Не ослаблять требование тумана войны ради переиспользования.
- Честность всех внутренних оценок vanilla Nullkiller не доказана. В сравнении обязательно одинаковые сценарные ограничения и отключённые cheat/reveal-настройки; нельзя заявлять полную информационную эквивалентность только из одинаковой карты.
- Конкретная fixture-карта, параметры кандидатов и обязательные queries будут проверяться до полноценной партии. Эти вопросы не разрешают расширение на произвольные карты.
