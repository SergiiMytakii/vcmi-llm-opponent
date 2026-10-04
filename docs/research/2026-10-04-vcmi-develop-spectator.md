# Видимый зритель в официальном develop

4 октября 2026 проверена официальная macOS arm64 сборка `1.8.0.6a1ca68e00f540087f35579c62ffaf037f5be269` из [каталога VCMI](https://download.vcmi.eu/branch/develop/macos-arm/). SHA256 DMG: `907566586a2db4ded94f87552f4a7050681f8aa4e77ae1cc1055ccd8c75f93cf`.

В изолированной копии с `--spectate --onlyAI --testmap Maps/ProbeSmoke.h3m` прежнего падения при инициализации зрителя не было. Штатный Nullkiller2 назначен всем трём игрокам. В финальном прогоне красный и синий закончили первые ходы, коричневый начал ход; Computer Use подтвердил отображение карты и боя. Это подтверждает узкую работоспособность зрителя, а не готовность нашего AI.

Первичные данные: `/Users/serhiimytakii/.codex/artifacts/prototypes/2026-10-04-vcmi-develop-spectator`. В нём официальная DMG, копия приложения, fixture-ресурсы, исходник profile shim, команды, runtime/engine logs, `observed.json`, `result.json`, `spectator-map.png`, `spectator-progress.png`, manifest и SHA256SUMS. Воспроизведение из свежей копии bundle: `python3 replay.py`; проверяет хеши до запуска. Ресурсы игры приватные, bundle не публиковать.

Только тестовая копия приложения переподписана для profile shim; в её Info.plist изменены CFBundleExecutable на vcmiclient и CFBundleName на VCMI Develop Probe для распознавания окна Computer Use. Оригинал plist сохранён в bundle и `~/.codex/macos-app-state-backups/vcmi-develop-spectator/`. Исходные HOME/CODEX_HOME не переопределялись. Установленная игра не изменена; 75 исходных config/save файлов сохранили хеши. Тестовые процессы остановлены собственным runner, DMG размонтирована.

Ограничения:

- Прогон завершён намеренно во время боя: итоговый -9 — cleanup после SIGTERM grace, не наблюдавшийся самостоятельный crash. Завершение боя/партии не доказано.
- В логе 4015 сообщений `Cannot find player red in battle!`, diagnostics battleGetFightingHero, encoding и отсутствующей музыки. Их безвредность не доказана; полный зритель всё ещё требует приёмки.
- Первая попытка прервалась из-за отсутствующей fixture-карты; сохранена отдельно. После копирования карты startup прошёл.
- Нет LLM или внешнего адаптера; разные AI по сторонам, human-vs-adapter, save/load, честность информации и Windows не проверялись.

Вывод для планирования: develop устраняет воспроизведённое ранее препятствие запуска и показывает бой; обход с пассивным третьим игроком не нужен для дальнейшего исследования. Приёмка обоих режимов будущего продукта остаётся открытой.
