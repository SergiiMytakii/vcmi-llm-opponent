# vcmi-llm-opponent
LLM strategic opponent for Heroes III on VCMI, targeting macOS Apple Silicon and Windows 11 x64.

Development now uses our own VCMI build. Upstream acceptance is optional. The engine is pinned in
`engine/version.json`; the generic built-in `ExternalAI` adapter delegates decisions to a separate local program.
When upgrading VCMI, update the pin, reapply the small integration patch, rebuild, and repeat acceptance checks
before releasing our matching build. Installed VCMI and existing saves must remain separate.

The working implementation calls Codex CLI through a ChatGPT subscription using `gpt-5.6-terra`
with low reasoning. The adapter offers construction, troop recruitment, town-tavern hero hiring, hero destinations,
exploration, attacks and end-turn; VCMI executes routes and battles. Real Codex construction and
recruitment, scripted movement, and mixed ExternalAI/Nullkiller2 assignment have local runtime proof.
The [two-player land scenario](docs/land-duel.md) supplies the initial calibration map.
One headful match on that map ended in a Codex victory over Nullkiller2 on day 11,
with difficulty configured to 200%; it included five deadline fallback turns.
A later memory-enabled build won another match on day 4 (seven model decisions,
one deadline fallback). Two subsequent games with LLM as blue ended in losses on days 5 and 3;
an experimental defense prompt did not establish an improvement. A later game using
player-local object labels won on day 4 (seven model decisions, one timeout).
The subsequent battle-repaired build lost on day 10, with six model replies and
nine deadline fallbacks. Latency remains a substantial gameplay limitation.
These are training results across
different builds/prompts, not a win-rate estimate.
See [runtime evidence and limits](docs/verification-land-duel-2026-10-04.md).

**Full MVP acceptance is still in progress.** Native regressions cover continuation
after a battle, save/load during a model request, and hidden-state invariance
before and after movement. An installed Mac runtime also passed a real battle
and launcher preflight from a separate package directory. Human play and Windows
runtime still need proof. Source support or a bounded smoke run does not establish
these outcomes.

- [Build and verification](docs/development.md)
- [Create a private profile and play](docs/playing.md)
- [Current external process protocol](docs/external-ai-protocol.md)
- [Research and decisions](docs/research/2026-10-02-vcmi-llm-research.md)
