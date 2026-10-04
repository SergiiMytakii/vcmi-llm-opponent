# Codex CLI через подписку: структурированный выбор действия

## Вопрос и результат

Проверен Codex CLI 0.160.0, существующий вход ChatGPT, модель `gpt-6.1-sol`, reasoning `medium`. Два запроса с искусственным игровым наблюдением завершились в пределах согласованных 20 секунд. Это доказательство узкого transport-контракта на Mac, не подключённый игровой AI и не оценка качества стратегии.

| Прогон | Время процесса | Ответ | Usage |
| --- | --- | --- | --- |
| CLI с отключёнными tools/context | 5.866 s | fixture-v1 / a-capture | 3489 input, 26 output, 0 cached, 0 reasoning output |
| То же + OS запрет чтения игровых путей | 8.331 s | fixture-v1 / a-capture | 3489 input, 26 output, 0 cached, 0 reasoning output |

Оба процесса завершились с кодом 0 и событием turn.completed. Оба ответа соответствовали схеме с enum action_id и additionalProperties=false. Tool-call событий нет. Малое искусственное наблюдение явно описывало победный захват пустого видимого города; это не тест сложного стратегического решения и не p95.

## Первичные данные

Приватный bundle: `/Users/serhiimytakii/.codex/artifacts/prototypes/2026-10-03-codex-action-choice`.

- `run.py`, `observation.json`, `schema.json`, `instructions.txt`, `models-no-tools.json`, исходный catalog entry и точные CLI binaries.
- `live-*`, `sandbox-live-*`: команды, события, stderr, ответы и результаты двух прогонов.
- `game-deny.sb`, `sandbox-denial.json`: OS запрет чтения/записи VCMI.app, пользовательского VCMI-профиля, логов и native-load bundle; чтение отдельного synthetic hidden-game canary завершилось отказом.
- `offline_check.py`, `offline-result.json`: recorded response принят; malformed/stale/unknown/late response даёт fallback; отдельный локальный задержанный процесс отменён за 0.207 s. Это локальный timeout fixture, не искусственно затянутый облачный запрос.
- `manifest.json`, `SHA256SUMS`: версии, host revision, digests. Credentials не копировались. Offline replay самодостаточен; live replay требует своего входа ChatGPT и сети.

## Устройство проверенного профиля

`codex exec --ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check --json --output-schema ... -s read-only -m gpt-6.1-sol`. Отдельные overrides закрепляют model provider openai, forced_login_method=chatgpt и medium. Переменные OPENAI_API_KEY/CODEX_API_KEY удалены только из окружения дочернего процесса. HOME/CODEX_HOME не переопределялись; используется существующая авторизация. Пользовательский config не редактировался.

Shell, view-image, web, apps/MCP через plugins, hooks, memories, skills discovery, multi-agent, goals, browser/computer/image-generation и прочие исполняемые tools отключены. Project instructions и внешний skills context не загружаются. Из локальной копии catalog entry выбранной модели удалены apply_patch, shell и experimental tools; модель/провайдер не меняются. Одного read-only sandbox недостаточно, чтобы исключить чтение скрытой карты.

Важное ограничение: это составной профиль конкретной версии, а не стабильный универсальный флаг «no tools». В pinned исходниках shell feature отключает shell отдельно, а apply_patch регистрируется по model metadata. При обновлении CLI необходимо повторить проверку и не запускать модель с непроверенным набором инструментов или унаследованными managed MCP settings. В эксперименте нет независимого перехвата outbound tool catalog.

В журнале есть error-typed предупреждение об экспериментальном skip_host_skill_discovery. Оно не является отказом turn: за ним следуют корректный ответ и turn.completed. Отдельное stderr warning сообщает о lookup метаданных фоновой модели; оно не доказывает фактический запрос к другой модели. Команда явно задаёт gpt-6.1-sol; автоматическая подмена не разрешена.

## Источники

- [Structured output в Codex exec](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema), прочитано 3 октября 2026.
- [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference): forced_login_method, project_doc_max_bytes, features, model_catalog_json; прочитано 3 октября 2026.
- [GPT-6.1 Sol в Codex CLI](https://learn.chatgpt.com/docs/models#gpt-61-sol); доступ конкретного аккаунта дополнительно проверен успешными вызовами.
- [Регистрация tools, rust-v0.160.0](https://github.com/openai/codex/blob/79b1b666f2e8551f8abbbca34957227f67f3f553/codex-rs/core/src/tools/spec_plan.rs#L1079-L1295): shell, apply_patch, MCP resources и прочие tools имеют разные условия.
- [Config schema этой версии](https://github.com/openai/codex/blob/79b1b666f2e8551f8abbbca34957227f67f3f553/codex-rs/core/config.schema.json).

## Последствие для плана

Инженерный выбор — локальный ограниченный bridge, вызывающий закреплённый Codex CLI, с stdin-наблюдением и отдельным валидатором ответа. Не передавать пути карты, сохранения, credentials или raw game state. Сохранять измеряемые latency/usage, модель/effort/версию и причину fallback. Не считать usage денежной стоимостью API: вызовы выполнены через подписку, её лимиты могут исчерпаться.

20 секунд включают запуск процесса и получение ответа. Тайм-аут закрывает право ответа выбрать действие до cleanup процесса; максимум 3 попытки и 60 секунд ожидания за ход. Windows process-tree cancellation, отсутствие инструментов на Windows, rate limit/offline и игровая интеграция требуют отдельных proof. Production-код эксперимента не переиспользовать автоматически.
