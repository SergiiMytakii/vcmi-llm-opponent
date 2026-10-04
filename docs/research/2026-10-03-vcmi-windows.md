# Windows 11 x64: сборка и приёмка

## Decision To Unblock

Пользователь подтвердил Windows 11 x64 в первой версии и наличие Windows-компьютера у другого разработчика. Тот должен выполнить подготовленную проверку на этапе реализации. Агент Windows-прогон не выполнял и не связывался с разработчиком.

## Short Answer

Пользователь впоследствии отклонил общую поставку engine+AI и выбрал **только плагин к установленной игре**. Ниже сохранённые сведения о toolchain нужны для сборки совместимого DLL, но совместимость с конкретным официальным Windows-бинарником пока не доказана. Поддержка должна привязываться к проверенному бинарнику; собственная сборка движка не является разрешённым запасным вариантом.

Запускать нативный codex.exe 0.160.0 через ChatGPT login. Общий контракт наблюдений/ответов одинаков на обеих ОС, различаются сборка, пути и управление процессами. WSL не является Windows-приёмкой продукта.

## Findings

| Claim | Primary Source | Version / Date | Confidence |
| --- | --- | --- | --- |
| Windows x64 CI использует MSVC toolset14.29, Ninja, Conan и RelWithDebInfo; не vcpkg | [Workflow](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/.github/workflows/github.yml#L60-L72) | VCMI1.7.5 | Высокая |
| Conan msvc-x64 наследует msvc-intel, который задаёт compiler.version192; runtime dynamic. Базовое194 переопределяется | [x64 profile](https://github.com/vcmi/vcmi-dependencies/blob/2e1924490c80547a8f85ed88aca29223057e832b/conan_profiles/msvc-x64), [Intel](https://github.com/vcmi/vcmi-dependencies/blob/2e1924490c80547a8f85ed88aca29223057e832b/conan_profiles/base/msvc-intel), [Base](https://github.com/vcmi/vcmi-dependencies/blob/2e1924490c80547a8f85ed88aca29223057e832b/conan_profiles/base/msvc) | Pinned dependency submodule | Высокая |
| VS2022 preset существует, но CI выбирает Ninja; имя установленной VS не доказывает toolset/ABI | [Presets](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/CMakePresets.json#L200-L275) | 1.7.5 | Высокая |
| Dependencies cache берётся из release2026-07-07 | [CI install](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/CI/install_conan_dependencies.sh) | 1.7.5 | Высокая; доступность архива при будущей сборке перепроверить |
| DLL loader использует LoadLibraryExW и C++ shared_ptr через фабрику; путь ./AI/name.dll | [Loader](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/callback/CDynLibHandler.cpp), [Directories](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/VCMIDirs.cpp) | 1.7.5 | Высокая |
| Windows VCMI читает config/dirs.json около executable и позволяет разнести userData/config/logs/saves | [Directories](https://github.com/vcmi/vcmi/blob/6901839ae9760dfcd1d5ff2c4aa4ef6968fee752/lib/VCMIDirs.cpp#L113-L198) | 1.7.5 | Высокая |
| Нативный Codex поддержан; Windows11 рекомендована. Встроенный sandbox команд не равен доказательству изоляции всего CLI от игровых данных | [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) | Прочитано2026-10-03 | Высокая для docs, не runtime0.160 |
| ChatGPT и API authentication различны; forced_login_method позволяет закрепить метод, credentials остаются локально | [Authentication](https://learn.chatgpt.com/docs/auth), [Config](https://learn.chatgpt.com/docs/config-file/config-reference) | Прочитано2026-10-03 | Высокая |
| Job Object управляет группой процессов, включая обычных потомков; TerminateJobObject и kill-on-close завершают группу, breakaway влияет на охват | [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) | Updated2025-07-14 | Высокая |
| CreateProcessW допускает явный executable и Unicode paths/environment; для Unicode environment нужен соответствующий flag | [Microsoft CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) | Updated2023-02-09 | Высокая |

## Repository Implications

Предлагаемый минимальный контракт:

- Отдельный DLL под конкретный установленный VCMI 1.7.5 x64: установить происхождение и SHA бинарника, согласовать commit/toolchain/CRT/конфигурацию и доказать загрузку и реальные callbacks. Не обещать совместимость произвольного DLL со скачанным установщиком. Зафиксировать точные версии Conan и зависимостей после воспроизводимой сборки. Изолированные тестовые копии и dirs.json применимы к проверке; это не согласие на поставку своего движка.
- Нативный codex.exe по абсолютному пути, без cmd/PowerShell/wsl посредника. Prompt передавать UTF-8 через stdin и закрывать pipe; stdout JSONL и stderr читать раздельно и параллельно с ограничением размера. Путь со знаком пробела или кириллицей не должен менять аргументы. Не принимать оставшийся от прошлого запроса output-файл за новый ответ.
- Полный профиль CLI из отдельного transport-исследования: точная версия, gpt-6.1-sol/medium, forced ChatGPT auth, без API fallback и исполняемых инструментов/постороннего контекста. Credentials не входят в комплект или журналы. Вход выполняет локальный владелец аккаунта. Непроверенная версия или инструменты означают отказ preflight и fallback.
- Для отмены своего дерева — Job Object без breakaway с kill-on-close; назначить созданный suspended процесс в Job до resume. По wall-clock deadline20s инвалидировать ответ и завершить Job. Проверить возможные вложенные jobs Codex. Это инженерное применение Windows API, пока не реализация.
- Mac game-deny.sb не переносится на Windows. Инвариант одинаков: модель не получает чтение карт/save и посторонних инструментов. Точный Windows OS boundary либо доказанное отсутствие доступных модели tool paths требует проверки до приёмки; внутренний read-only sandbox команд сам по себе не доказательство.

## Conflicts And Unknowns

Реальная Windows сборка, DLL load, CLI вызов, изоляция и отмена не проверены. Source support не считается runtime-proof. Другой разработчик предоставляет evidence для следующего минимального набора; сейчас нет подготовленной production-сборки для его запуска.

| Приёмка | Необходимое свидетельство |
| --- | --- |
| Сборка и загрузка | SHA дерева, cl /Bv, effective Conan settings, CMake cache, dumpbin headers/exports/dependents; лог реальной загрузки custom DLL |
| Оба режима | Видимые человек–LLM и LLM–Nullkiller, правильный AI каждого цвета, завершённые ходы и партия |
| Подписка/модель | CLI0.160.0, ChatGPT login, gpt-6.1-sol medium, schema-valid action, latency/usage |
| Пути и изоляция | Каталог с пробелом/кириллицей, UTF-8 и EOF; отсутствие game/save reads и tool calls |
| Тайм-аут | Задержанный fixture с дочерним процессом: собственное дерево прекращается, чужой процесс остаётся, игра переходит на fallback |
| Восстановление | offline/quota/missing CLI/invalid output, save/load/cancel и поздний ответ без устаревшего исполнения |

Этот список — обязательства будущей реализации. Он не заявляет, что Windows уже работает.
