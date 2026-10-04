# Ход, подтверждения и восстановление VCMI 1.7.5

## Decision To Unblock

Безопасное ожидание Codex и восстановление узкого adventure-AI адаптера, без переноса стратегического цикла Nullkiller. Основа: commit `6901839ae9760dfcd1d5ff2c4aa4ef6968fee752`, проверка 3 октября 2026.

## Short Answer

Один фоновый владелец стратегического хода; короткие callbacks событий/queries; ожидание модели без game-state mutex. Одна adventure-команда в полёте. Подтверждать видимый результат, а не только отправку или PackageApplied. Late responses отсекать внутренней generation. Состояние AI сохранять через playerLocalSettings, после load перестраивать кандидаты и не повторять старую команду автоматически.

## Findings

| Claim | Primary Source | Version / Date | Confidence |
| --- | --- | --- | --- |
| yourTurn вызывается непосредственно после playerStartsTurn; обработку пакетов нельзя задерживать ожиданием модели | [NetPacksClient](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/NetPacksClient.cpp#L923-L930), [Client handlePack](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L352-L365) | 1.7.5 | Высокая |
| AIGateway демонстрирует асинхронный запуск хода, но его lock/strategy код нельзя копировать целиком | [AIGateway](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/AI/Nullkiller2/AIGateway.cpp#L524-L542) | 1.7.5 | Высокая |
| QueryID(-1) допустим для yourTurn, но ответ на него запрещён | [TurnOrderProcessor](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/processors/TurnOrderProcessor.cpp#L275-L301), [QueryReply](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/NetPacksServer.cpp#L408-L416) | 1.7.5 | Высокая |
| request ID назначается клиентом; requestRealized вызывается до разблокировки waitingRequest | [sendRequest](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L373-L393), [PackageApplied](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/NetPacksClient.cpp#L904-L909) | 1.7.5 | Высокая |
| Критично: PackageApplied(true) отправляется и после visitor failure; это не доказательство успеха игровой команды | [CGameHandler](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/CGameHandler.cpp#L496-L544) | 1.7.5 | Высокая |
| EndTurn запрещён при unresolved query; окончание подтверждается PlayerEndsTurn | [TurnOrderProcessor](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/processors/TurnOrderProcessor.cpp#L305-L318), [Checks](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/processors/TurnOrderProcessor.cpp#L342-L369) | 1.7.5 | Высокая |
| CAdventureAI создаёт и вызывает отдельный BattleAI | [CAdventureAI](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CAdventureAI.cpp#L33-L41) | 1.7.5 | Высокая |
| saveLocalState отправляет JSON серверу; сервер заменяет playerLocalSettings, поле сериализуется | [Callback](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CCallback.cpp#L311-L318), [Server](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/NetPacksServer.cpp#L418-L423), [State](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/CPlayerState.h#L113-L121) | 1.7.5 | Высокая |
| Load создаёт интерфейсы заново и повторно запускает активный ход; finish ждёт корректного завершения фоновой работы | [Client](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L139-L176), [Resume turn](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/processors/TurnOrderProcessor.cpp#L389-L397) | 1.7.5 | Высокая |

## Repository Implications

Это контракт реализации, не уже работающий адаптер:

1. `yourTurn` регистрирует владение ходом и быстро возвращается. Ответить на настоящий query начала хода, но не на -1. Query callbacks обслуживаются независимо от LLM worker; BattleAI продолжает бой. Ответы на обязательные бесплатные запросы определены для fixture-сценария, неизвестный необрабатываемый запрос даёт диагностируемую остановку, а не бесконечное ожидание.
2. Под коротким GS lock скопировать разрешённое наблюдение. До вызова модели освободить все game locks и не сохранять raw pointers. После ответа перепроверить player/turn/внутреннюю generation и актуальные предусловия кандидата.
3. Внутренняя generation меняется при timeout, load, finish и конце хода. Она не передаётся модели. Публичная observation_version отражает только доступные знания, чтобы hidden-only события не меняли prompt или кандидатов.
4. На timeout сначала закрыть попытку, затем запустить fallback. Каждый старт запроса, включая retry, расходует один из трёх слотов; максимум 20 секунд на запрос и 60 суммарно за ход. Fallback использует те же кандидаты. Поздний ответ игнорируется даже после завершения subprocess.
5. Adventure-команды последовательны. requestSent связывает отправленную операцию с request ID, requestRealized только обновляет учёт и будит worker. Он не блокируется и не отправляет следующую команду. Для build проверяется появление здания, recruit — армия/доступность/ресурсы, move — позиция/движение/query/бой. Событие PlayerEndsTurn подтверждает конец хода.
6. Потерянное подтверждение — unknown outcome. Сначала согласовать текущее видимое состояние; не повторять покупку или движение вслепую. Если состояние нельзя согласовать, остановить выполнение с причиной и возможностью загрузки сохранения. Не обещать exactly-once на основании request ID.
7. Namespaced playerLocalSettings содержит schema version, player/day/turn, цель, только разрешённую память, расход попыток/ожидания и минимальный pending intent с ожидаемым видимым результатом. Сохранение расхода попытки должно быть подтверждено до обращения к LLM; intent — до отправки игровой команды. JSON не дублирует историю движка.
8. Load: прочитать JSON, создать новую generation, восстановить бюджет, сверить pending intent с сохранённым игровым состоянием, перестроить пути. Старые ответы/команды не воспроизводить. Не сохранять subprocess, future, pointers, pathfinder cache, QueryID/request ID или monotonic deadline.
9. Finish: отменить модельный запрос, завершить только свой process tree и ограниченно дождаться worker. Не переносить бесконечный retry EndTurn из AIGateway.

## Conflicts And Unknowns

- Runtime ordering и все обязательные queries fixture ещё нужно доказать. Предложенная схема не гарантирует отсутствие hangs без этих проверок.
- Откат на старый save откатывает и бюджет, сохранённый внутри него. Это обычный новый replay сохранённого состояния, а не глобальный расходный лимит подписки. Абсолютный запрет обхода бюджета старым save потребовал бы внешнего журнала и не предлагается для MVP.
- Игровые команды имеют отдельное ожидание подтверждений; лимит 20 секунд относится к модели, не к длительности боя или человеческого хода. Для отсутствия прогресса нужен отдельный диагностический watchdog.
- Обязательные проверки: timeout/fallback/late response; query и бой при ожидании; yourTurn(-1); visitor failure с PackageApplied(true); save/load около запроса и команды; finish при зависшем subprocess; hidden-only изменения; исчерпание лимита без новой попытки.
