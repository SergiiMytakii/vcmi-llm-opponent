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

The build outputs are in `.build/mac/bin`. This is a developer build, not yet a packaged installer.
Launching it directly uses VCMI's ordinary macOS profile: do not do so against the user's installed-game profile.
The initial runtime smoke uses a separate private fixture and a process-local profile shim with write protection
on the original profile. A distributable isolated launcher remains required before user installation.

## Windows 11 x64 — verification pending

Prepare a short writable checkout such as `C:\vcmi-ai`. Install Visual Studio C++ build tools with v142
(compiler 19.29), Windows SDK, Git, and Python. Use an x64 Developer PowerShell with that compiler selected.
This matches the pinned upstream dependency profile (`msvc/192`); Windows 11 is our support boundary.

Create the venv/install build requirements/prepare source as above. Download `dependencies-windows-x64.txz`
from the same dependency release into `.build/`. Windows dependency checksum/lock and runtime acceptance
must be recorded on the developer machine before declaring this platform supported.

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:CONAN_HOME = "$PWD\.build\conan"
conan profile detect
conan cache restore .build\dependencies-windows-x64.txz
Push-Location .build\vcmi
conan install . --output-folder=../conan-generated --build=never --profile=dependencies/conan_profiles/msvc-x64 --conf=tools.cmake.cmaketoolchain:generator=Ninja
Pop-Location
cmake -S .build/vcmi -B .build/windows -G Ninja "-DCMAKE_TOOLCHAIN_FILE=$PWD/.build/conan-generated/conan_toolchain.cmake" -DCMAKE_BUILD_TYPE=Release -DENABLE_LAUNCHER=OFF -DENABLE_EDITOR=OFF -DENABLE_TEST=OFF -DENABLE_MMAI=OFF -DENABLE_DISCORD=OFF -DENABLE_INNOEXTRACT=OFF -DENABLE_CCACHE=OFF
cmake --build .build/windows --target vcmiclient vcmiserver -j 4
```

Before a game run, use the engine's `config/dirs.json` next to the generated executable to point
`userDataPath`, `userConfigPath`, `userCachePath`, `userLogsPath`, and `userSavePath` to a separate absolute
fixture directory tree. Copy only the developer's own licensed data into that fixture. Inspect startup log paths
before starting a game. Do not run against the installed profile.

## Controller and transport checks

From the repository root, after Conan generated the toolchain:

```sh
cmake -S tests -B .build/transport -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/.build/conan-generated/conan_toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build .build/transport
EXCHANGE_DRIVER=.build/transport/exchange-driver python3 -m unittest discover -s tests -v
```

On Windows use the same CMake commands with PowerShell quoting and set
`$env:EXCHANGE_DRIVER="$PWD\.build\transport\exchange-driver.exe"` before `python -m unittest discover -s tests -v`.
Tests execute real subprocesses: stdin EOF, output collection, nonzero exit, timeout, cancellation,
descendant cleanup, output limit, and a Unicode script path containing spaces.

## Initial game acceptance

In an isolated profile set both `ai.adventureEnemyAI` and `ai.adventureAlliedAI` to `ExternalAI`.
Set `VCMI_EXTERNAL_AI_EXECUTABLE` to the absolute Python executable and `VCMI_EXTERNAL_AI_SCRIPT` to this
repository's `controller/main.py`. Run a bounded visible test game with a buildable owned town.
Required evidence: `ExternalAI ... selected build-...`, `ExternalAI build result ... observed=1`, then the next
player/turn. Repeat with an invalid or hanging controller and confirm fallback ends the turn.
Stop only the processes created by the test and verify original saves/config hashes remain unchanged.

This does not prove full-match strategy or the two final game modes. Those require the remaining MVP work,
including Codex, heroes/recruitment, the restricted map and separate LLM/Nullkiller assignment.
