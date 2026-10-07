# Отдельный поток обучения NK3

Стратегический вызов получает текущие наблюдения, принятую стратегию и собственную
память партии. Сырые эпизоды, их оценки и автоматически выбранные уроки в него
не добавляются. Ответ стратегии не содержит `learning`. Это обучение через
сохранённую память, без изменения параметров модели.

## Владельцы и цикл

- `controller/main.py` сохраняет решение и наблюдаемые последствия, но не оценивает их.
- Native NK3 при `VCMI_NK3_LEARNING_JOURNAL` пишет собственные начало/конец хода,
  принятие или отклонение стратегии, каждый execution receipt и terminal result.
  Конец хода публикуется после подтверждения сервера. Это работает и в native-only
  режиме, когда стратегических вызовов нет. Сведения берутся из существующего
  PlayerView и собственных receipts; spectator snapshot анализатор не читает.
- `controller/evaluation.py` собирает журнал в SQLite и открывает кандидаты разбора.
  Два полных собственных хода простоя главной армии или игнорирования доступной
  шахты, либо три хода без полезной разведки при информационном препятствии —
  повод для разбора, а не готовая оценка. Прогресс, пропуски, прерванные ходы и
  смена поколения загрузки разрывают непрерывное окно.
- `controller/analyze.py` делает отдельные вызовы модели, до двух pending-эпизодов
  за вызов. Игра не ждёт результатов. `analysis_instructions.txt` задаёт критерии;
  `validate_analysis` проверяет ссылки и минимальные основания отрицательной оценки.
- `controller/experience.py` транзакционно сохраняет разбор и изменения уроков.
  `controller/knowledge.py` атомарно публикует соседний `*.knowledge.json`.
  Публикация повторяется из уже committed SQLite после сбоя без повторной оценки
  и увеличения счётчиков.

## Что означает оценка

Анализатор отдельно записывает исход (`benefit`, `harm`, `missed_opportunity`,
`no_material_change`, `unknown`), качество выбора (`supported`, `avoidable_mistake`,
`uncertain`) и ответственность (`strategy`, `native_execution`, `infrastructure`,
`external`, `mixed`, `unknown`). Вредный исход сам по себе не доказывает ошибку.

`avoidable_mistake` требует полного окна и конкретной альтернативы, записанной
до выбора, с `available=true`, `constraints_checked=true`. Анализатор проверяет
маршрут, время прибытия, риск, резервы, зависимости и конкурирующую оборону.
Прогноз не гарантирует захвата или победы. Оправданное ожидание может получить
`supported`; неполные основания требуют `uncertain`. Технические сбои не создают
стратегические советы.

Каждому эпизоду соответствует одна оценка и один разбор урока. `support` создаёт
или подтверждает условное правило, `contradict` учитывает возражение, `uncertain`
не усиливает правило, `revise` сохраняет уточнение и выводит предшественника из
использования. Повтор одного эпизода не увеличивает счётчики. У правила есть
условия, исключения и механизм пользы. Переносимые тексты не должны содержать
локальные номера объектов, координаты или расположение противника.

Первый урок — гипотеза. `supported` требует подтверждений в трёх различных
партиях при совпадающих engine/mod/executor identities и без возражений.
Это повторяемость, а не доказательство причинности. Старые уроки сохраняются;
отсутствующая версия правил понижает применимость до гипотезы. При откате
сохранения future pending-эпизоды удаляются, уже разобранный обобщённый опыт
сохраняется. Ответ анализатора, устаревший относительно отката, не принимается.

## Доступ стратегии по запросу

Codex CLI 0.160.0 получает ровно два read-only MCP-инструмента:
`search_knowledge(query, category)` и `read_lesson(id)`. Они читают фиксированный
снимок опубликованных уроков на начало вызова. Доступа к произвольным файлам,
сырым эпизодам и оценкам нет. Общий бюджет: четыре обращения, 4096 байт результата,
не более 2048 байт за обращение и трёх результатов поиска. Ответы содержат revision,
условия, исключения и происхождение подтверждений. Недоступность знаний или
отсутствие совпадения не мешает выбрать стратегию из текущих фактов.

Необязательный `references.knowledge` тоже доступен только через эти инструменты
как исходный справочник без подтверждённого learning evidence. Статические
эвристики в основных инструкциях — часть инструкции, а не уроки SQLite.

## Запуск и режимы

`playtesting/learning.py` запускает отдельный анализатор в `learn`. На SQLite
допускается один анализатор (OS lock). Для каждого запуска используются свои
журнал, файлы вызовов и лог в `learning/`. При STOP/прерывании очищаются его
дочерние процессы; при естественном завершении даётся один ограниченный batch.
После отмены моделей оставшийся журнал переносится в SQLite без нового GPT-вызова.
Ошибки старта или анализа не заменяют игровое решение.

Параметры manifest: `analysis_max_calls` (12), `analysis_max_tokens` (200000),
`analysis_timeout_seconds` (60), `analysis_interval_seconds` (5),
`analysis_idle_turns` (2), `analysis_mine_turns` (2), `analysis_scouting_turns` (3),
`analysis_model` (`gpt-6.1-sol`), `analysis_reasoning_effort` (`low`). Неизвестный
расход при ошибке консервативно исчерпывает остаток token budget. После лимита
продолжаются сбор наблюдений и восстановление публикации, без новых вызовов.

`VCMI_EXPERIENCE_DB` выбирает библиотеку, по умолчанию постоянную базу вне сборок:
- macOS: `~/Library/Application Support/VCMI-Nullkiller3/learning/experience.sqlite3`;
- Windows: `%APPDATA%/VCMI-Nullkiller3/learning/experience.sqlite3`;
- Linux: `${XDG_DATA_HOME:-~/.local/share}/VCMI-Nullkiller3/learning/experience.sqlite3`.

Обычные запуски из разных сборок дополняют одну библиотеку. Публикуемый
`experience.knowledge.json` хранится рядом. Игровые тестовые запуски используют ту же библиотеку; явный `experience_database` или
`VCMI_EXPERIENCE_DB` сохраняет выбранное пользователем расположение.
Очистка временных сборок не должна удалять постоянную библиотеку.
`VCMI_EXPERIENCE_MODE`: `learn`, `read_only`, `off`. Последние два не запускают
анализ и не меняют библиотеку. Offline replay использует замороженные SQLite и
knowledge snapshot с проверяемыми хешами. Live training/evaluation/integration используют
общую библиотеку. Для отдельного запуска анализатора:

```sh
python3 controller/analyze.py --database /path/to/experience.sqlite3 --once
python3 controller/analyze.py --database /path/to/experience.sqlite3 --publish-only
```

SQLite: `decisions`, `episodes`, `observed_signals`, `assessments`, `lessons`,
`retirements` сохраняют прежние данные; `evaluations`, `turn_events`,
`analysis_usage` и поля `lessons.exceptions/mechanism` добавляются совместимо.
Стратегическая metadata `experience.collection_only=true` сообщает нулевые
`episodes_assessed`, `lessons_updated`, `lessons_supplied`; расход аналитика
записывается отдельно в `analysis_usage` и `learning/calls/`.

## Проверки

```sh
python3 -m unittest discover -s tests -p test_learning_flow.py -v
python3 -m unittest discover -s tests -p test_evaluation.py -v
python3 -m unittest discover -s tests -p test_experience.py -v
python3 -m unittest discover -s tests -p test_learning_runtime.py -v
```

Процессные тесты используют реальную SQLite и CLI seam с fake-codex-driver.
Opt-in `test_native_experience.py` (`VCMI_NATIVE_EXPERIENCE_CONFIG`) и
`test_nullkiller3_experience.py` (`VCMI_NK3_STRATEGY_CONFIG`) используют отдельный
native bundle и private profile: полные ходы без GPT-стратегии, terminal receipts,
финальные собственные бои и разделение двух NK3 игроков. Рост игрового мастерства
требует отдельного сравнения сопоставимых партий; эти проверки доказывают механизм.
