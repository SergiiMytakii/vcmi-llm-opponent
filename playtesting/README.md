# Playtesting

Independent test runner for the one-shot ExternalAI controller. Uses Python 3.10+ standard library;
macOS game launch additionally uses the existing Apple Clang toolchain and sandbox-exec.

Run `python3 scripts/playtest.py --help` from the repository root.
[Playtest procedure and logging contract](../docs/testing/llm-opponent-playtest.md) owns the testing workflow.

- `runs.py`: private fixtures, reference snapshots, source hashes, immutable run identities.
- `controller.py`: real stdin/stdout/stderr exchange, limits, timing, decision-only replay.
- `launcher.py`: bounded isolated macOS launch, assignment checks, owned-process cleanup.
- `reports.py`: engine-confirmed execution, episodes, manual outcomes, comparisons.

The module neither chooses the game strategy nor invokes Codex independently of the configured controller.
It never loads a spectator log into a model prompt. Automatic Windows game launch remains unverified and
is refused; controller recording, replay, and reports use portable Python.
