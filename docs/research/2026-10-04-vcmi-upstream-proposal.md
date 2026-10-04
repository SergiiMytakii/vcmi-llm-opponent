# Предложение VCMI: отдельная программа стратегического AI

Статус: пользователь явно согласовал отправку 4 октября 2026. [Комментарий опубликован](https://github.com/vcmi/vcmi/issues/5586#issuecomment-5973539236) от SergiiMytakii; автор и полный текст проверены повторным чтением GitHub API. Это запрос обратной связи по архитектуре, без обещания сроков или готового патча. Английский текст ниже — точное отправленное сообщение.

Основание: [проверка адаптера](2026-10-04-vcmi-external-ai-adapter.md) и [отдельный прогон зрителя](2026-10-04-vcmi-develop-spectator.md). Приватные игровые ресурсы, логи и локальные пути не отправляются.

---

Would a narrowly scoped external adventure-AI adapter be a direction you would consider for VCMI?

I am planning a separately installed strategy program, with an LLM as one possible decision backend. The intended experience is human vs external AI and visible external AI vs Nullkiller2, using normal VCMI movement and battle resolution on macOS and Windows.

I checked develop at `6a1ca68e00f540087f35579c62ffaf037f5be269`. Following the removal of dynamic AI loading in #7453, a possible integration point seems to be a built-in adapter registered in `AIFactory`, using `CAdventureAI` and `CCallback`.

The proposed responsibility split is:

- **VCMI adapter:** expose a deliberately limited, player-visible observation; offer legal action candidates; validate the returned choice; execute ordinary engine commands. Keep pathfinding, battle AI, required game queries and save/load reconciliation within VCMI.
- **External program:** select strategic actions and maintain permitted strategy memory. Model providers, prompts, credentials and subscription/API access stay outside VCMI.

For a first proof, I would limit the scenario to one hero and one town per side on a land map: build, recruit a specified army quantity, move/visit/explore/attack a known target, and end the turn. This is a bounded demonstration, not a claim of general map support.

A local child process with versioned JSON over stdin/stdout looks sufficient for that proof. VCMI would need bounded waits, stale-response rejection and defined behavior when the program fails. Only player-visible data would leave the adapter; the spectator's view would not be used as the AI's observation. Hidden-state invariance, command outcomes and save/load would need tests, rather than relying on callback visibility checks alone.

The adapter is not implemented yet. I would start with a deterministic external program before adding an LLM, so the engine integration can be tested independently. The project would not require restoring native AI-library loading or adding a general network command server.

Before building a larger prototype, would you consider this boundary suitable for upstream? In particular, is an explicitly configured local executable acceptable, and would you prefer a different existing integration point or a smaller initial action set?
