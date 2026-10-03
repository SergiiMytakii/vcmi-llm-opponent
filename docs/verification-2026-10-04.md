# First ExternalAI increment — verification on 2026-10-04

Scope: begin the authorized custom-build approach with a working native-to-external construction/end-turn
path. This is not acceptance of the complete LLM opponent or of Windows support.

Engine pin: `6a1ca68e00f540087f35579c62ffaf037f5be269`. Host: macOS arm64, Apple Clang 17,
Python 3.14.3. Source/dependency pins and build commands are in `engine/version.json` and `docs/development.md`.

Verified:

- `scripts/prepare_engine.py .build/prepare-check` created the pinned source and applied the integration patch.
  Repeating it refused the existing directory without overwriting it.
- Conan install with `engine/conan-macos.lock` succeeded. CMake built both `vcmiclient` and `vcmiserver`.
  Dependency link warnings mention duplicate system libraries and nonexistent Conan system-library search
  directories; the build and runtime succeeded. Windows compilation has not been performed.
- `EXCHANGE_DRIVER=.build/transport/exchange-driver PYTHONPATH=tests python3 -m unittest test_controller test_process_exchange -v`:
  12 tests passed. Real process checks cover cancellation, timeout, descendants, output limits, nonzero exits,
  UTF-8 under a non-UTF-8 Python stdio setting, and script paths containing spaces/Cyrillic.
- Independent review reproduced a fatal `SIGPIPE` when the controller exited before reading a large allowed
  request. The added regression failed with process exit -13 before the fix. On macOS the adapter now sets
  `F_SETNOSIGPIPE` on its own request pipe; the same test returns an ordinary error without killing the host.
  No process-wide signal disposition is changed. Both engine targets were rebuilt after the repair.
- The first game run exposed Grail construction as a false-positive candidate from `canBuildStructure`.
  Server rejection was correctly recorded as `observed=0`. Candidates now additionally require `BUILD_NORMAL`.
- The final isolated headful run with the actual compiled adapter and `controller/main.py` recorded
  **18 newly built buildings, zero failed builds**, and progressed through 59 turns for all three fixture
  players after the pipe repair. The fixture was the existing private All for One smoke map, not the final MVP map.
- A controller returning a stale request ID produced 233 rejected replies/end-turn selections and no builds.
- A hanging controller timed out twice, followed by end-turn and the next player. The two timeout records
  were at 00:34:56.758 and 00:35:16.774 local time. No model was used in these runs.

Private evidence is under ignored `.build/smoke/`: `final-normal-proof.json`, final client/runtime logs,
`normal-build-proof/`, `invalid-reply-proof/`, `timeout-proof/`, and `before-normal-filter/`.
The runner stopped only its process group after the bounded observation; return code -9 was its explicit
cleanup, not a spontaneous game crash. This does not prove graceful engine shutdown while a request is pending.
Standalone transport cancellation is covered by tests. No test game processes remain running.

## Profile preservation incident

The controlled runs each verified unchanged hashes of 75 original config/save files. A later Computer Use
application selection unexpectedly launched a second copy through LaunchServices without the isolated
environment. That process rewrote the installed profile's `settings.json` and `modSettings.json` during startup.
It was stopped before any game was started. No save file has a modification time within that incident.

The complete pre-change mod configuration was recovered from its startup log and restored. The unexpected
version and source log are retained privately in `.build/smoke/profile-recovery/`. No exact pre-change byte copy
of `settings.json` was available; full restoration of that file cannot be claimed. It was rewritten by VCMI's
settings normalization. No speculative replacement of user preferences was made.

LaunchServices entry in the private test bundle now exits instead of starting the client; only the isolated
runner launches its real binary. The last controlled run persisted before/after hash manifests and changed
none of the 75 protected files relative to the post-incident baseline. A distributable isolated launcher and
additional shutdown/save-load acceptance remain necessary before installing this as a user-facing build.

## Not yet proved

Windows 11 x64 build, Job Object behavior and Unicode paths on Windows; Codex integration/visibility limits;
recruitment and hero decisions; save/load state and budget restoration; full dialog/battle lifecycle;
LLM-vs-Nullkiller assignment and both final modes; full-match victory; packaging and update releases.
