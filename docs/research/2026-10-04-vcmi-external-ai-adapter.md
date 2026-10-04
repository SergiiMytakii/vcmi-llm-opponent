# Внешний стратегический AI для VCMI develop

## Decision To Unblock

4 октября 2026 пользователь выбрал направление: универсальный адаптер в официальной VCMI и отдельно установленная программа AI. Цель — обновлять официальную игру без постоянной собственной сборки. Подготовка предложения разрешена; отправка разработчикам отдельно согласуется. Временная сборка допустима для доказательства идеи, но не принята как постоянный способ поставки.

Проверен develop `6a1ca68e00f540087f35579c62ffaf037f5be269` по официальному GitHub tarball и API. Это исходный ориентир, не гарантия совместимости произвольной development-сборки. Данные предыдущих исследований по 1.7.5 остаются историческими; их DLL/toolchain-контракты не являются контрактами develop.

## Short Answer

Правдоподобный путь — новый встроенный adventure-AI адаптер через AIFactory/CAdventureAI. Он подключает внешнюю программу, выдаёт только сведения своего игрока и разрешённые кандидаты действий, проверяет ответ и исполняет обычные команды VCMI. Во внешней программе остаются стратегия и Codex CLI через подписку. В VCMI не добавляется зависимость от модели или провайдера.

Такого готового внешнего контракта в проверенных механизмах нет. Предложение требует нового кода и согласия сопровождающих VCMI. Небольшой размер реализации и принятие upstream пока не доказаны. Официальную игру можно будет использовать без нашей сборки только после выпуска официальной версии с адаптером.

## Findings

Ссылки на код закреплены на указанном commit. Уверенность высокая для прочитанного кода; runtime этого адаптера отсутствует.

| Claim | Primary Source | Version / Date | Confidence |
| --- | --- | --- | --- |
| Загрузку отдельных AI-библиотек намеренно удалили; фабрика создаёт встроенные Nullkiller2/EmptyAI | [PR7453](https://github.com/vcmi/vcmi/pull/7453), [AIFactory](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/AIFactory.cpp#L29-L85) | PR merged 2026-06-13; pinned develop | Высокая |
| AI получает callback конкретного игрока; интерфейс зрителя устанавливается отдельно. При отсутствии локального human в headful включается spectate | [Client](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/client/Client.cpp#L186-L326) | pinned develop | Высокая; работа UI требует прогона |
| CAdventureAI создаёт штатный BattleAI при начале боя и завершает его после боя | [CAdventureAI](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CAdventureAI.cpp#L21-L118) | pinned develop | Высокая |
| Интерфейс AI обслуживает ходы, обязательные диалоги/выборы и finish | [CGameInterface](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CGameInterface.h#L25-L53) | pinned develop | Высокая |
| Есть callback-команды движения, найма, окончания хода и строительства | [Commands](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CCallback.cpp#L29-L95), [Build](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CCallback.cpp#L222-L232) | pinned develop | Высокая |
| getObj/getTile фильтруют видимость, но возвращают богатые объекты; descriptors town/hero регулируют подробность. Нужна отдельная разрешённая проекция данных | [Objects](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CGameInfoCallback.cpp#L113-L126), [Descriptors](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CGameInfoCallback.cpp#L226-L300), [Tiles](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CGameInfoCallback.cpp#L502-L517) | pinned develop | Высокая; полная fog-инвариантность не доказана |
| PathfinderCache использует SingleHeroPathfinderConfig; есть запрет неизвестных клеток | [Cache](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/pathfinder/PathfinderCache.cpp#L19-L33), [Fog gate](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/pathfinder/PathfinderUtil.h#L23-L27) | pinned develop | Высокая для механизма, не для всех скрытых зависимостей |
| Load создаёт interfaces заново; finishGameplay вызывает finish. Local JSON отправляется серверу, заменяет playerLocalSettings и сериализуется | [Client lifecycle](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/client/Client.cpp#L115-L171), [Save request](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/callback/CCallback.cpp#L313-L319), [Apply](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/server/NetPacksServer.cpp#L433-L437), [Serialization](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/CPlayerState.h#L118-L127) | pinned develop | Высокая; восстановление адаптера надо реализовать |
| PackageApplied(true) всё ещё отправляется после false результата обработчика; нужен контроль фактического результата | [CGameHandler](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/server/CGameHandler.cpp#L509-L555) | pinned develop | Высокая |
| Проверенный scripting dispatcher знает spellEffect/combatEvent/damageCalculator, но не adventure-controller | [ScriptHandler](https://github.com/vcmi/vcmi/blob/6a1ca68e00f540087f35579c62ffaf037f5be269/lib/scripting/ScriptHandler.cpp#L24-L33) | pinned develop | Высокая для этого механизма, не абсолютное доказательство отсутствия любых обходов |
| Есть открытые предложения LLM-интеграции и read-only coach; они не предоставляют принятое API внешнего контроллера | [LLM integration](https://github.com/vcmi/vcmi/issues/5586), [Coach](https://github.com/vcmi/vcmi/issues/7108) | Live API read 2026-10-04 | Высокая для статуса/текста; поиск обсуждений не исчерпывающий |

## Repository Implications

Ниже инженерное предложение для обсуждения, не существующее API и не утверждённая спецификация реализации.

- Встроенный адаптер владеет callback своего игрока, разрешённым snapshot, кандидатами и перепроверкой действий. Данные интерфейса зрителя не становятся знаниями AI. Ни raw game state, ни engine pointers, ни произвольные пакеты наружу не выдаются.
- Внешняя программа выбирает стратегию: строительство, конкретный найм, цель движения/разведки/нападения, конец хода. Ответ — версия наблюдения и идентификатор выданного кандидата. Разрешённая память и обращения к Codex остаются в программе; сохранение нужного состояния согласуется через адаптер с save/load игры, без второго авторитетного журнала мира.
- Адаптер рассчитывает путь штатным механизмом и исполняет обычные команды последовательно; обслуживает обязательные queries и BattleAI. После изменений мира перепроверяет продолжение. Не переносить Nullkiller makeTurn и автоматические покупки ради удобства.
- Для первого desktop-доказательства предлагается запускаемый локальный дочерний процесс и JSON через stdin/stdout, диагностика отдельно. Это исключает необходимость порта, discovery и общего сервера управления. Требуются версия протокола, корреляция запросов, ограничение размера сообщений, отказ на несовместимой версии, timeout/cancellation и завершение только собственного дерева процессов. Конкретный transport подлежит обсуждению с upstream.
- При ожидании модели игра не удерживает game-state lock. Адаптер отклоняет устаревшие ответы; контролирует результат команды отдельно от PackageApplied. На load старые запросы не воспроизводятся, состояние сверяется с загруженной игрой. Сбой программы не должен оставлять unresolved query или бесконечно удерживать ход.
- Модель, подписка, prompts и правила бюджета относятся к нашей программе. Ранее подтверждённые gpt-6.1-sol/medium, 20 секунд на запрос, 3 попытки и 60 секунд за ход сохраняются для нашего продукта; не превращаются в глобальные ограничения универсального адаптера.
- Первое доказательство: детерминированная внешняя программа на ограниченной сухопутной карте с одним героем/городом на сторону, обоими headful-режимами, штатными боями, fog-проверкой, timeout/crash и save/load. Затем подключение Codex. Это предложенная последовательность доказательства; production delivery ещё не разрешён.
- Mac arm64 и Windows 11 x64 остаются обязательными. Внешняя программа не зависит от C++ ABI плагина, но схема сообщений и runtime совместимость требуют проверки при изменениях. Отдельная программа не гарантирует вечную совместимость со всеми версиями VCMI.

## Conflicts And Unknowns

Нет согласия upstream, срока релиза, реализации или runtime-проверки нового адаптера. Не доказаны полный набор queries выбранной карты, fog-инвариантность путей/кандидатов, порядок восстановления и надёжность process handling на обеих ОС. Не проведена повторная проверка Windows toolchain develop. Отдельный [прогон официального Mac-бинарника](2026-10-04-vcmi-develop-spectator.md) подтвердил запуск зрителя и отображение боя; полный матч, Windows и найденные battle diagnostics остаются за пределами этого доказательства.

Нельзя обещать, что официальный релиз примет адаптер. Если предложение отклонят или отложат, пользователь отдельно выбирает ожидание, временную сборку либо другой маршрут; постоянный fork автоматически не разрешён. Не восстанавливать DLL loader и не подменять библиотеки установленной игры как скрытый запасной путь.
