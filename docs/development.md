# Development build

The source overlay in `engine/ExternalAI` and `engine/integration.patch` are authoritative. Generated checkouts,
dependencies, binaries and private game data stay under ignored `.build/`. Never copy licensed Heroes III data
into Git or a public release. Do not overwrite the installed game or reuse its live profile for development.

## Prepare the pinned source

Requires Git, Python 3.10+ and the platform C++ toolchain. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python scripts/prepare_engine.py
```

On Windows use `py -3`, `.venv\Scripts\python.exe`, and the same Python script.
The script refuses an existing destination. Pass a fresh path for a new checkout or upgrade; it never resets
local changes. During adapter development, copy changed `engine/ExternalAI` files into the generated
`AI/ExternalAI` directory before rebuilding. Do not make authoritative edits only in the generated checkout.

## macOS arm64

Install Xcode Command Line Tools first. The initial build uses Apple Clang 17 and the official prebuilt
dependencies for the pinned engine. Download `dependencies-mac-arm.txz` from
[vcmi-dependencies 2026-09-01](https://github.com/vcmi/vcmi-dependencies/releases/tag/2026-09-01), save it under
`.build/`, and compare SHA-256 with `macos_dependencies_sha256` in `engine/version.json` before restoring it.

From the repository root:

```sh
export PATH="$PWD/.venv/bin:$PATH"
export CONAN_HOME="$PWD/.build/conan"
conan profile detect
conan cache restore .build/dependencies-mac-arm.txz
cd .build/vcmi
conan install . --output-folder=../conan-generated --build=never \
  --profile=dependencies/conan_profiles/macos-arm \
  --profile=dependencies/conan_profiles/base/apple-system \
  --lockfile=../../engine/conan-macos.lock \
  --conf=tools.cmake.cmaketoolchain:generator=Ninja
cd ../..
cmake -S .build/vcmi -B .build/mac -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/.build/conan-generated/conan_toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_LAUNCHER=OFF -DENABLE_EDITOR=OFF \
  -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_DISCORD=OFF \
  -DENABLE_INNOEXTRACT=OFF -DENABLE_CCACHE=OFF
cmake --build .build/mac --target vcmiclient vcmiserver -j 4
```

The build outputs are in `.build/mac/bin`. Do not distribute copies of these raw
binaries: their library search paths still point into the build and Conan cache.
Install into a fresh private directory to collect dependencies and rewrite those paths:

```sh
cmake --install .build/mac --prefix "$PWD/.build/mac-runtime"
```

This produces `.build/mac-runtime/VCMI.app` with the client, server, libraries and
VCMI resources. It contains no licensed Heroes III data. Keep the controller,
`scripts/`, `playtesting/` and their repository-relative layout alongside it; use
`scripts/play.py` with this installed executable. Python 3.10+ and the pinned
Codex CLI remain prerequisites. This developer bundle uses local ad-hoc signing;
it is not a notarized public installer. Do not double-click the native app: that
bypasses profile setup.
Always set `VCMI_PROFILE_DIR` to an absolute private data directory containing `Data/`, `Maps/`
and `config/`. The patched engine keeps configuration, cache, logs and saves under that directory.
Without this variable VCMI still uses its ordinary platform profile. Do not launch against the installed profile.
`--help` advertises `VCMI_PROFILE_DIR`; `--version` prints every resolved writable path. The tester checks
both before starting a game and protects the installed profile with the macOS sandbox. It no longer needs
a profile-interposition dylib. The [isolated launcher](playing.md) performs these
same capability and path checks before a user game.

## Windows 11 x64 — verification pending

Prepare a short writable checkout such as `C:\vcmi-ai`. Install Visual Studio C++ build tools with v142
(compiler 19.29), Windows SDK, Git, and Python. Use an x64 Developer PowerShell with that compiler selected.
This matches the pinned upstream dependency profile (`msvc/192`); Windows 11 is our support boundary.

Create the venv and install build requirements, then run the build script below.
It creates a fresh checkout, downloads the pinned official dependency archive,
checks its SHA-256 from `engine/version.json`, and uses a private Conan cache.
It refuses an existing work directory. If a build fails, retain that directory
and use a new `--work` path for another attempt.

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe scripts/build_windows.py --work .build/windows --jobs 4
```

The script installs the client, server, dependencies and shipped resources into
`.build/windows/runtime`, builds both native test drivers and runs Python tests.
Commands and failures are recorded in `build.log`; `build-evidence.json` is written
only after success. The Windows resolved dependency graph is not yet locked or
verified. The dependency archive digest is pinned, but this is not a claim of a
reproduced Windows build.

Use [the isolated launcher](playing.md) for game checks. It sets `VCMI_PROFILE_DIR`
without changing HOME or Codex authentication. Windows compilation and runtime
verification remain pending; source support is not platform acceptance.

## Controller and transport checks

From the repository root, after Conan generated the toolchain:

```sh
cmake -S tests -B .build/transport -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/.build/conan-generated/conan_toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build .build/transport
EXCHANGE_DRIVER=.build/transport/exchange-driver FAKE_CODEX_DRIVER=.build/transport/fake-codex-driver python3 -m unittest discover -s tests -v
```

On Windows use the same CMake commands with PowerShell quoting and set
`$env:EXCHANGE_DRIVER="$PWD\.build\transport\exchange-driver.exe"` and
`$env:FAKE_CODEX_DRIVER="$PWD\.build\transport\fake-codex-driver.exe"` before running the tests.
Tests execute real subprocesses: stdin EOF, output collection, nonzero exit, timeout, cancellation,
descendant cleanup, output limit, and a Unicode script path containing spaces.

## Initial game acceptance

In an isolated profile set both `ai.adventureEnemyAI` and `ai.adventureAlliedAI` to `ExternalAI`.
Set `VCMI_EXTERNAL_AI_EXECUTABLE` to the absolute Python executable and `VCMI_EXTERNAL_AI_SCRIPT` to this
repository's `controller/main.py`. Run a bounded visible test game with a buildable owned town.
Required evidence: `ExternalAI ... selected build-...`, `ExternalAI build result ... observed=1`, then the next
player/turn. Repeat with an invalid or hanging controller and confirm fallback ends the turn.
Stop only the processes created by the test and verify original saves/config hashes remain unchanged.

These construction checks remain useful regressions. The working tree now also contains Codex,
recruitment, movement, per-player AI selection and a restricted scenario. Follow
[playtesting](testing/llm-opponent-playtest.md) for current isolated runs and
[land-duel verification](verification-land-duel-2026-10-04.md) for actual full-match evidence.
Both final modes, save/load, Windows and release packaging still require complete acceptance.

## Nullkiller3 route obstruction diagnostics

`VCMI_NK3_ROUTE_DIAGNOSTICS=1` enables `NK3_ROUTE_DIAGNOSTICS` records for missing
actor/target quotes: raw native path count, blocked-action and mixed-actor counts,
and whether the ordinary player pathfinder establishes a route. These are
diagnostic facts, not a claim that a missing route is impossible.

When `allow_route_repair` is enabled and the main army has ended without useful
work, native execution can yield an unlocked, uncommitted own helper into a safe
empty nearby land tile. Required defenders are excluded. The move must be a
current-turn single-hero native route with no losses, special action or known
lethal exposure, and must open a previously obstructed known land connection.
`NK3_ROUTE_REPAIR` records the observed move; quotes rebuild afterward. Strategic
adjacent exploration requires actual new visibility and cannot substitute an
object-direction score for discovery. Ordinary Nullkiller2 retains its existing
neighbor behavior. This repairs physical traffic; LLM still chooses operations.

Run `test_route_obstruction.py` and `test_neighbour_exploration.py` against the
prepared native build. For save-based proof, set `VCMI_NATIVE_ROUTE_YIELD_CONFIG`
to a compatible private tester config containing an obstructed save and run
`test_native_route_yield.py`. Its profile is isolated; the live game is untouched.
