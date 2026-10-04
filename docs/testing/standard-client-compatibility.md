# Стандартный сетевой клиент и ExternalAI

AI работает на клиенте хоста. Хост и сервер используют нашу интеграцию;
человеческому участнику не нужны Codex, Python или авторизация ChatGPT.
Ему нужны совместимая версия VCMI и совпадающие игровые моды.

`SaveLocalState`, `CCallback::saveLocalState(JsonNode)` и
`IGameActionCallback` сохраняют формат и сигнатуры pinned upstream из
`engine/version.json`. AI передаёт обновление
`{"_namespaces":{"ExternalAI":state}}` в существующем JSON-поле. Сервер
проверяет принадлежность игрока, обновляет namespace без удаления полей UI.
Обычный снимок UI заменяет поля UI, сохраняя уже записанные namespaces.
Поле `storageNamespace` в двоичный пакет не добавляется.

## Проверки разработчика

Использовать заголовки и библиотеку одной свежей developer-сборки:

```sh
.venv/bin/cmake -S tests/local-state -B .build/local-state-tests \
  -DVCMI_SOURCE_DIR="$PWD/.build/vcmi" \
  -DVCMI_LIBRARY="$PWD/.build/mac/bin/libvcmi.dylib" \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/.build/conan-generated/conan_toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build .build/local-state-tests
.venv/bin/ctest --test-dir .build/local-state-tests --output-on-failure
```

Нативный тест читает пакет исходного формата, сравнивает двоичные байты,
читает JSON-обновление AI стандартным декодером и проверяет сохранность UI,
памяти, других namespaces, раздельность игроков и отклонение повреждённых
обновлений. Исходный формат в тесте взят из pinned upstream `SaveLocalState`.
При смене pin сверять его заново с upstream.

Проверку настоящего сохранения и загрузки проводить по
[инструкции тестера](llm-opponent-playtest.md), задав
`VCMI_NATIVE_SAVE_CONFIG` с новой сборкой и приватными игровыми данными.

## Полная сетевая проверка

Совпадение этого пакета не гарантирует совместимость любой версии VCMI.
Нужно отдельно проверить стандартный Windows-клиент с выбранной версией:
подключение к Mac-хосту, назначение людей и ExternalAI, обычные действия обоих
людей, несколько ходов AI, бой, сохранение и повторное подключение при загрузке.
Для двух людей и отдельного AI требуется подходящая карта минимум на три стороны.
Сохранять версии/хеши, логи обоих клиентов и сервера, результаты и ограничения.
До этого считать полный сценарий Mac + стандартный Windows неподтверждённым.
