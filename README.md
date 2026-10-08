# vcmi-llm-opponent
LLM strategic opponent for Heroes III on VCMI, targeting macOS Apple Silicon and Windows 11 x64.

Development now uses our own VCMI build. Upstream acceptance is optional. The engine is pinned in
`engine/version.json`; the generic built-in `ExternalAI` adapter delegates decisions to a separate local program.
When upgrading VCMI, update the pin, reapply the small integration patch, rebuild, and repeat acceptance checks
before releasing our matching build. Installed VCMI and existing saves must remain separate.

The working implementation calls Codex CLI through a ChatGPT subscription using `gpt-5.6-terra`
with reasoning effort `low` for Nullkiller3 background preparation and `none` for other gameplay requests. The adapter offers construction, troop recruitment, town-tavern hero hiring, hero destinations,
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

## Game modes and settings

Use `scripts/playtest.py` for configurable Nullkiller3/Nullkiller2 matches. Put
match settings in a JSON config, then prepare and run a new isolated session:

```sh
.venv/bin/python scripts/playtest.py prepare --config /absolute/match.json --out /absolute/new-run
.venv/bin/python scripts/playtest.py run --run /absolute/new-run
```

The output directory must be new. Settings are copied into `manifest.json`;
editing the original JSON after preparation does not change that run. Environment
switches below are supplied when running, separately from the manifest. Use a
private profile and our compiled engine; do not launch against the installed
VCMI profile. See [playtest setup](docs/testing/llm-opponent-playtest.md) for the
required engine, profile, controller and source paths.

### AI and map visibility

| Setting | Default / values | Effect |
| --- | --- | --- |
| `players` | Required color-to-AI mapping | For example, `{"red":"Nullkiller3","blue":"Nullkiller2"}`. Also supports `EmptyAI` for diagnostic scenarios. |
| `nk3_mode` | `model`; `native` | `model`: LLM chooses strategy, native AI executes. `native`: Nullkiller3 runs native planning without model requests. Nullkiller2 is always native. |
| `VCMI_AI_OPEN_MAP` (environment) | Unset: open map; `0`: normal fog; `1`: open map | Applies to **both Nullkiller2 and Nullkiller3**, at all difficulties. Nullkiller3's model receives the revealed map too. |
| `difficulty` | Required; `easy`, `normal`, `hard`, `expert`, `impossible` | Game difficulty; map visibility stays open at every level unless disabled. |
| `seed` | Optional nonnegative integer / `null` | Sets the server seed for comparable initial conditions. |
| `headless` | `false` / `true` | `false`: spectator window; `true`: no game window. Both modes run AI players. |
| `map_resource` | Required map resource | For example, `Maps/MyMap.h3m` or `.vmap` inside the private profile. |
| `save_resource` | Optional save resource | Loads a compatible save instead of starting the map from zero. |
| `max_seconds` | Required positive number | Maximum session duration; review pauses are excluded. |
| `review_interval_days` | `0` (off); integer `1..365` | Pauses at review checkpoints every N game days; continue with `continue --run RUN --completed-day DAY`. |
| `decision_timeout_seconds` | `70`; positive, at most `70` | Recorder deadline for each controller response. Native exchange and the controller also enforce their own limits. |

**Open map is the default.** The shipped `openMap` setting is `true` at all five
AI difficulty levels. Each AI reveals its team's map at the beginning of its
turn, including after loading an older save. The existing game-wide
`cheatsAllowed=false` prohibition also prevents revelation. Team visibility is
shared, so a human allied with an AI also receives that team's revealed map.
Enemy troop counts still use ordinary visible quantity categories; open map
does not grant exact private army information.

To enable normal fog/exploration for both AIs:

```sh
VCMI_AI_OPEN_MAP=0 .venv/bin/python scripts/playtest.py run --run /absolute/new-run
```

To explicitly enable full visibility:

```sh
VCMI_AI_OPEN_MAP=1 .venv/bin/python scripts/playtest.py run --run /absolute/new-run
```

Start a new game when comparing fog against open map: disabling revelation does
not hide tiles already revealed in a saved game. The override is read at AI
initialization; changing a terminal variable does not alter a running process.

### Knowledge, learning and model settings

| JSON setting | Default / values | Effect |
| --- | --- | --- |
| `experience_mode` | `learn`; `read_only`, `off` | `learn`: records experience and runs the separate analyst; `read_only`: consumes a frozen existing library without learning; `off`: disables experience use and the analyst. |
| `experience_database` | Existing default library; absolute path override | Chooses the experience database. `read_only` requires an existing library. |
| `strategy_guide` | `{"mode":"on"}`; `{"mode":"off"}` | Enables/disables the strategy reference tool. Optional `path` selects a reference bundle. |
| `game_rules` | `{"mode":"on"}`; `{"mode":"off"}` | Enables/disables the game-rules reference tool. Optional `path` selects a reference bundle. |
| `references` | `{}`; optional `prompt` and `knowledge` file paths | Frozen custom prompt/knowledge references. |
| `analysis_model` | `gpt-6.1-sol` | Model for the **separate experience analyst**. |
| `analysis_reasoning_effort` | `low` | Reasoning effort for the separate analyst. |
| `analysis_max_calls` | `12`; `1..100` | Analyst model-call limit per run. |
| `analysis_max_tokens` | `200000`; `1..1000000` | Analyst token budget per run. |
| `analysis_timeout_seconds` | `60`; positive, at most `120` | Deadline for an analyst call. |
| `analysis_interval_seconds` | `5`; positive, at most `60` | Analyst polling interval. |
| `analysis_idle_turns` | `2`; `1..30` | Idle-turn threshold for analysis. |
| `analysis_mine_turns` | `2`; `1..30` | Mine-related analysis threshold. |
| `analysis_scouting_turns` | `3`; `1..30` | Scouting-related analysis threshold. |

The gameplay controller currently uses `gpt-5.6-terra`, defined in
`controller/codex.py`. Only protocol-2 `prepare_next_turn` requests use reasoning
effort `low`; other gameplay requests use `none`. Each model call has a 60-second
limit. The match JSON's `model` and `reasoning_effort` fields do
**not** override those gameplay constants. Native-only mode avoids gameplay
model requests; also set `experience_mode: "off"` to avoid analyst model calls.
The full configuration is read by [the runner](playtesting/runs.py).

For direct engine/controller launches, `VCMI_NK3_MODE=model|native` selects
Nullkiller3 strategy mode (unset defaults to model). The other environment settings are
`VCMI_EXPERIENCE_MODE=learn|read_only|off`, `VCMI_EXPERIENCE_DB=/absolute/library`,
`VCMI_STRATEGY_GUIDE_MODE=on|off`, `VCMI_STRATEGY_GUIDE=/absolute/bundle`,
`VCMI_GAME_RULES_MODE=on|off`, `VCMI_GAME_RULES=/absolute/bundle`, and
`VCMI_CODEX_EXECUTABLE=/absolute/codex`. The playtest recorder sets knowledge
and experience modes from its manifest; configure those in JSON when using it.
`VCMI_KNOWLEDGE_FILE` can select a generated knowledge file for direct launches.

### Logging and diagnostics

Recording is enabled by the playtest runner. There is no runner switch that
turns off all evidence recording. Each run contains:

| Location | Contents |
| --- | --- |
| `engine-logs/VCMI_Client_log.txt` and server log in `engine-logs/` | Native actions, AI assignments, turns, battles and visibility. |
| `runtime.log` | Game process output. |
| `decisions/` | Controller requests, responses, timing, validation and model diagnostics. |
| `learning/` | Native own-turn journal (including with experience off); analyst calls and output when `experience_mode` is `learn`. |
| `turn-review/` | Checkpoints/review state when review intervals are enabled. |
| `report.json`, `launch.json`, `cleanup.json` | Summarized execution, launch and owned-process cleanup evidence. |

`AI_MAP_VISIBILITY player=0 visible=864 total=864` means the red AI sees all
864 tiles. Initialization may log partial visibility before its first turn;
check the entry from `AIGateway::makingTurn` after revelation.

For native log verbosity, edit **the private profile's** `config/settings.json`
before preparing a run. Merge these keys into existing `logging` settings:

```json
{
  "logging": {
    "console": {"threshold": "info"},
    "loggers": [
      {"domain": "global", "level": "info"},
      {"domain": "ai", "level": "debug"}
    ]
  }
}
```

Levels are `trace`, `debug`, `info`, `warn`, `error`. `trace` is most detailed;
`warn` or `error` reduce routine output. `logging.console.threshold` controls
console output; logger levels control which records are emitted, including to
files. There is no supported `off` level in this pinned engine. Keep `ai` at
`info` or more detailed when collecting strategy/visibility evidence.

| Environment switch | Default / effect |
| --- | --- |
| `VCMI_NK3_ROUTE_DIAGNOSTICS=1` | Unset: off. Enables diagnostics for missing native routes. To disable, **unset** it; presence, even `0`, enables it. |
| `VCMI_NK3_LEARNING_JOURNAL=/absolute/file.jsonl` | Optional native own-turn journal; managed automatically by the runner's learning supervisor. |
| `VCMI_NK3_SEED_CAMPAIGN=/absolute/campaign.json` | Diagnostic initial campaign input for fresh fixtures; unset in ordinary games. |
| `VCMI_PROFILE_DIR=/absolute/private-profile` | Direct engine profile isolation; runner sets this automatically. |
| `VCMI_EXTERNAL_AI_EXECUTABLE` / `VCMI_EXTERNAL_AI_SCRIPT` | Direct engine controller command; runner supplies its recording controller automatically. |

The older `scripts/play.py run --mode human|spectator` launcher still selects
**ExternalAI**, not Nullkiller3, and forces model/learning defaults. Use the
playtest runner for the configurable NK3/NK2 modes described above. See
[human-launch instructions](docs/playing.md) for its separate profile workflow.
