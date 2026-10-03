# vcmi-llm-opponent
LLM strategic opponent for Heroes III on VCMI, targeting macOS Apple Silicon and Windows 11 x64.

Development now uses our own VCMI build. Upstream acceptance is optional. The engine is pinned in
`engine/version.json`; the generic built-in `ExternalAI` adapter delegates decisions to a separate local program.
When upgrading VCMI, update the pin, reapply the small integration patch, rebuild, and repeat acceptance checks
before releasing our matching build. Installed VCMI and existing saves must remain separate.

The first increment implements construction and end-turn through a deterministic external controller.
It is **not yet the LLM opponent**: Codex integration, recruitment, hero targets, exploration, attacks,
restricted scenario, per-player AI selection, and both complete play modes remain to be implemented.
The planned model provider is Codex CLI through a ChatGPT subscription, `gpt-6.1-sol` with medium reasoning.

- [Build and verification](docs/development.md)
- [Current external process protocol](docs/external-ai-protocol.md)
- [Research and decisions](docs/research/2026-10-02-vcmi-llm-research.md)
