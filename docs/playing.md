# Running the developer build

This is a developer workflow. macOS has native game evidence; Windows compilation
and gameplay remain unverified. Use the matching engine built from this repository,
Python 3.10+ and Codex CLI 0.160.0, signed in with a ChatGPT subscription. Decisions
use `gpt-5.6-terra` without reasoning tokens (`none`). There is no API-key fallback.

Run commands from the repository root. Keep the repository available while playing:
the launcher uses its controller files. Never start the engine by double-clicking
it: the launcher supplies the separate profile and controller configuration.

## Create a separate profile

Point `--data` at your own licensed Heroes III `Data` directory containing the LOD
archives. `--profile` must be a new directory; the command refuses an existing one.
It copies data and creates the restricted Land Duel map and settings. It does not
import existing saves, mods or configuration. Optional music is not copied.

macOS example (replace the source path with your actual Data directory):

```sh
python3 scripts/play.py init --data "/path/to/Heroes III/Data" --profile "$PWD/.build/profiles/player"
python3 scripts/play.py run --engine "$PWD/.build/mac-runtime/VCMI.app/Contents/MacOS/vcmiclient" --profile "$PWD/.build/profiles/player" --mode human --check
```

The engine path above comes from `cmake --install` in the
[build instructions](development.md); building the binaries alone does not create
that bundle. A prepared developer archive may put it under `runtime/VCMI.app`;
use that executable path when working from the archive.

Windows PowerShell example, after `scripts/build_windows.py` succeeds:

```powershell
.venv\Scripts\python.exe scripts/play.py init --data "D:\Heroes III\Data" --profile "$PWD\.build\profiles\player"
.venv\Scripts\python.exe scripts/play.py run --engine "$PWD\.build\windows\runtime\VCMI_client.exe" --profile "$PWD\.build\profiles\player" --mode human --check
```

`--check` verifies the engine's profile isolation, CLI version and ChatGPT login.
It does not call the model or prove gameplay. If login is missing, run `codex login`
yourself. Do not share authentication files. The launcher resolves the standard
npm `codex.cmd` installation to its native Windows x64 `codex.exe`; for another
installation layout pass `--codex "C:\path\to\codex.exe"`. It never executes the
batch wrapper. A missing optional native npm package is an error, not a fallback.

## Play or watch

Repeat the checked `run` command without `--check`:

- `--mode human` opens the VCMI main menu. Start a new game, select
  **External AI - Land Duel**, use red as human and blue as computer. The computer
  uses ExternalAI. Difficulty follows normal VCMI rules; the generated profile
  starts at 200%, which gives a human different starting resources from an AI.
- `--mode spectator` starts red ExternalAI against blue Nullkiller2 automatically,
  with a visible map and automatic battles. The engine declares victory when a
  side controls both towns.

The scenario limits both sides to one hero, excludes boats and adventure movement
spells, and lets the engine execute movement and battles. The model can choose
up to 32 offered actions in one request, with a 35-second controller deadline.
The engine validates each step and asks again when the situation changes or the
batch ends. A turn covers useful work for all heroes and towns, with a 256-action
runaway guard. A failed request ends the turn.

Close the game normally; Ctrl-C in the launcher's terminal also requests cleanup.
Only one launcher may use a profile at a time. Logs are under `<profile>/logs`,
saves under `<profile>/Saves`. The installed game's profile is not selected.

## Windows acceptance to perform on the developer machine

Keep the build log and `build-evidence.json` from [the Windows build](development.md).
Then use a new profile whose path contains spaces and Cyrillic characters:

1. Run `--check`; all six engine writable paths must resolve inside the new profile.
2. Start human mode, play a turn and confirm blue's log contains a real Codex
   decision and an executed action. Save, quit, restart through the same launcher,
   load that save and continue. Record any error and the exact executable hashes.
3. Start spectator mode and observe a completed battle and a capture-town result.
   Preserve logs and screenshots, including any timeout or loss.
4. Check cleanup after normal exit and Ctrl-C: no launched `VCMI_client.exe`,
   `VCMI_server.exe`, controller Python or Codex processes should survive.
   Compare installed-game configuration and save hashes before and after.

The Windows launcher assigns the suspended client to a kill-on-close process Job
before it can create a server or controller. Normal exit, Ctrl-C and launcher death
are intended to clean up the whole tree. `logs/cleanup.json` records graceful
cleanup; abrupt launcher termination cannot write that report. This implementation
still needs the real Windows checks above.

The native subprocess tests include timeout, cancellation, descendants and Unicode
paths; the build also runs Windows Job ownership and native profile checks. These
checks do not replace game acceptance. The automated match tester
currently launches games only on macOS. Windows cleanup and these manual game
steps are still pending evidence. Do not treat a successful Python test run as a
verified Windows release.
