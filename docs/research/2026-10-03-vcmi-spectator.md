# Видимое наблюдение в VCMI 1.7.5 без пересборки движка

## Вопрос и текущая граница

Пользователь выбрал **только плагин к установленной игре**, отклонив отдельную сборку VCMI для Mac и Windows. Рекомендация общей сборки engine+AI из Windows-исследования этим решением отменена. Совместимость отдельного DLL с конкретным установленным Windows-бинарником ещё требуется доказать.

Обычный видимый человек–AI запуск проверен минимальным модулем на Mac. Видимый AI-only запуск падает до первого хода. В существующих исходниках обнаружена несовместимость инициализации интерфейса игрока с цветом SPECTATOR; исправление клиента не входит в выбранную поставку. Способ сохранить наблюдение без такого исправления пока не подтверждён.

## Первичные источники

Все ссылки относятся к VCMI 1.7.5, commit `6901839ae9760dfcd1d5ff2c4aa4ef6968fee752`; соответствующее локальное дерево прочитано непосредственно.

| Факт | Источник | Уверенность |
| --- | --- | --- |
| При отсутствии человека видимый клиент автоматически включает spectator и устанавливает CPlayerInterface с цветом SPECTATOR | [Client.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L218-L335) | Высокая |
| Environment зрителя получает callback с nullopt, но installNewPlayerInterface создаёт другой callback с цветом SPECTATOR и передаёт именно его интерфейсу | [Client.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L328-L335) | Высокая |
| initGameInterface безусловно вызывает initializeHeroTownList; последняя запрашивает своих героев/города и разыменовывает playerLocalSettings своего игрока | [CPlayerInterface.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/CPlayerInterface.cpp#L1363-L1384) | Высокая |
| getHeroesInfo разыменовывает результат getPlayerState; недопустимый цвет игрока даёт nullptr | [Player callback](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CPlayerSpecificInfoCallback.cpp#L49-L53), [State lookup](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CGameInfoCallback.cpp#L66-L90) | Высокая |
| aiNameForPlayer предпочитает имя игрока, если соответствующая AI-библиотека существует; иначе используются глобальные настройки allied/enemy | [Client.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L300-L325) | Высокая |
| --ai объявлен парсером; чтение его значения в client/clientapp/server/lib не найдено. В эксперименте индивидуальное назначение этим флагом не доказано | [EntryPoint.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/clientapp/EntryPoint.cpp#L147-L157) | Высокая для проверки исходников, не обещание интерфейса |
| В лобби имя AI показано не редактируемым полем человека, а label | [OptionsTab.cpp](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/lobby/OptionsTab.cpp#L1035-L1038) | Высокая |
| gosolo вызывает removeGUI и заменяет человеческий интерфейс AI; removeGUI очищает окна и adventureInt | [Command manager](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/ClientCommandManager.cpp#L77-L120), [removeGUI](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L518-L525) | Высокая |
| autoSkip пропускает человеческие ходы, сохраняя GUI; это не самостоятельный spectator | [Command contract](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/ClientCommandManager.h#L35-L42), [Adventure interface](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/adventureMap/AdventureMapInterface.cpp#L461) | Высокая для механизма; обход не проверен |

## Наблюдаемый сбой

Локальный bundle: `/Users/serhiimytakii/.codex/artifacts/prototypes/2026-10-03-vcmi-native-load`. Файл `spectator-crash-excerpt.json` содержит очищенные выдержки пяти crash reports экспериментальной VCMI-Probe.app: EXC_BAD_ACCESS/SIGSEGV по адресу 0x6a8, кадры initializeHeroTownList → initGameInterface → installNewPlayerInterface → initPlayerInterfaces → newGame. Первый кадр библиотеки имеет имя `<deduplicated_symbol>` и не символизирован до конкретной строки.

Совпадение стека с заведомо недопустимым player-state доступом даёт высокую уверенность в причине этого пути инициализации. Оно не доказывает, что одного guard достаточно для всего spectator: имеются несколько обращений к данным собственного игрока, а дальнейший UI также требует проверки. Патч и повторный успешный spectator-прогон не выполнялись. Оригинальное приложение и его профиль не менялись.

## Следствия для плана

- Только бинарный AI-плагин, без изменений клиента/движка; отдельные dylib/DLL должны соответствовать проверенным установленным бинарникам. Доказательство загрузки минимального класса не равно доказательству всех интерфейсов и полной партии.
- Не обещать полноценного AI-only зрителя на 1.7.5. gosolo не сохраняет требуемый игровой интерфейс.
- Возможный обход с пассивным третьим человеческим игроком и autoSkip — **гипотеза**, меняющая устройство карты. До включения нужны решение пользователя и прототип: видимость действий, отсутствие влияния третьего игрока на экономику/победу/туман войны, разные AI и save/load. Глобальное раскрытие карты боевым игрокам не подходит.
- Если обход не подходит или не работает, остаётся отдельное решение об объёме первой версии. Пересборка движка не является разрешённым запасным вариантом.

## Первый эксперимент с пассивным игроком

### Дополнительная ручная проверка штатного spectator

По прямой просьбе пользователя повторён запуск через Computer Use: копия клиента с `--spectate --onlyAI`, затем клики «Новая игра → Сценарий → Все за одного → Начать». В изолированном профиле оба значения adventure AI заменены на штатный Nullkiller; лог подтвердил загрузку Nullkiller для всех трёх цветов без вызова ProbeAI. После «Начать» приложение завершилось с SIGSEGV (returncode -11), до первого хода. Новый macOS report `vcmiclient-2026-10-03-235007.ips` содержит ту же цепочку initializeHeroTownList → initGameInterface → installNewPlayerInterface и адрес 0x6a8. Это не завершение по таймеру runner.

Bundle: `/Users/serhiimytakii/.codex/artifacts/prototypes/2026-10-03-vcmi-manual-spectator`; воспроизведение `python3 run_manual.py`, затем указанные клики. `before-start.png`, `manual-crash-excerpt.json`, команды и журналы сохранены. Все 75 исходных config/save hashes совпали; установленное приложение не менялось. Проверка выполнена в копии с прежним изолирующим shim и fixture-ресурсами, поэтому не объявляет одинаковое поведение всех установок VCMI.

### Проверка autoSkip

Пользователь разрешил проверить этот обход. Отдельный bundle `/Users/serhiimytakii/.codex/artifacts/prototypes/2026-10-03-vcmi-passive-observer` содержит копию исходного native-load bundle и собственный `run_observer.py`. Команда `python3 run_observer.py` запускает копию клиента с `--autoSkip`; затем вручную выбирается единственная fixture-карта All for One. Два AI используют прежний no-op ProbeAI, красный человек автоматически пропускает ходы.

Наблюдались 1806 завершённых AI callbacks за 30 секунд после первого callback. Окно карты оставалось открытым, дата менялась; `autoskip-window.png` показывает в основном закрытую туманом карту обычного человека. Runner намеренно остановил собственную process group; returncode -9 — cleanup. SHA-256 всех 75 защищённых исходных файлов config/Saves совпали. `result.json`, `runtime.log`, `command.json`, screenshot, исходники и SHA256SUMS сохранены в bundle.

Это подтверждает только автоматическую передачу хода при живом GUI. Два разных стратегических AI, перемещения, победа, нейтральность наблюдателя и save/load этим прогоном не доказаны. В fixture человек остаётся обычным противником с городом и героем; считать такой сценарий готовым режимом наблюдения нельзя.

Дополнительный предел по коду: [CClient::battleStarted](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/client/Client.cpp#L392-L470) создаёт видимый бой для участвующего человека либо специального spectator; третий человеческий игрок не получает окно боя двух AI. Возможность наблюдать только стратегическую карту вынесена на отдельное решение пользователя.

Для дальнейшей проверки видимости найден [cheatMapReveal](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/server/processors/PlayerMessageProcessor.cpp#L629-L650): раскрытие адресовано команде игрока. Поэтому союз наблюдателя с боевым AI совместно с раскрытием карты нарушил бы ограничения тумана войны. Применение исключительно к отдельной команде наблюдателя — пока гипотеза будущего изолированного эксперимента, не принятое решение продукта.
