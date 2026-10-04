# Land duel and spectator verification — 2026-10-04

These are local development results, not full MVP acceptance. Private artifacts
are under `.build/playtests/` and are not committed. Engine source is pinned by
`engine/version.json`; each tester manifest records the actual executable hashes.

## Reproduced spectator failure

`land-duel-load-01` and `land-duel-load-02` loaded the same initial map, with
ExternalAI (scripted movement fixture) against Nullkiller2. Both crashed with
SIGSEGV after the first neutral battle, on day 2. The macOS reports were
`vcmiclient-2026-10-04-012358.ips` and `vcmiclient-2026-10-04-012453.ips`.

Both crashing stacks were:

1. `BattleStacksController::getHoveredStacksUnitIds()`
2. `StackQueue::StackBox::showAll()`
3. `WindowHandler::processPendingRedraws()`

The battle-result skip closes the window and immediately destroys BattleInterface.
WindowHandler retains the closed window until the next rendered frame. A repaint
queued before closing can therefore reach a StackBox whose battle controller is
gone. Destruction-only cancellation is too late for that retained window.

The integration patch now calls `cancelRedraw(this)` when CIntObject deactivates,
before recursively deactivating children. This cancels queued paints when a window
closes or is covered. Activation requests a complete redraw through WindowHandler.

## Same-map repair proof

Built `vcmiclient` with `cmake --build .build/mac --target vcmiclient -j4`, copied
and ad-hoc signed that executable in the private developer bundle. No adapter or
map changes were included in this replay.

`land-duel-battle-repair-01` passed the formerly crashing battle, reached day 4,
and recorded Nullkiller's `gameOver` message **You captured both towns.** after
visiting the opponent town. The client remained alive until the tester's bounded
stop. The tester confirmed both player assignments, completed process cleanup,
and unchanged installed-game profile hashes. A screenshot after battle completion
showed the map and the spectator's elimination dialog. No input interaction was
performed on that final dialog.

This proves the observed crash repair and the capture-town victory trigger for
that map. It does not prove a Codex win: the controller in these runs was the
deterministic movement fixture. The first generated map also logged nonnumeric
instance-name suffixes; the generator was subsequently corrected to use VCMI's
`type_number` convention, and the faction allowlist was changed to the required
LIC object shape. Subsequent runs must use the corrected generated map.

## Initial observation and fallback checks

`tests/fixtures/fog_maps.py` creates four diagnostic variants of the duel. The
visible red neutral is moved inside initial sight. The hidden variant changes
the distant blue hero from 40 to 40,000 pikemen, multiplies distant monster and
resource quantities by 100 and changes a distant terrain tile. Object identities
and the player's initial visible state stay fixed. Two further variants change
the visible neutral from 15 to 19 or 21 pikemen.

The `fog-base-01`, corrected `fog-hidden-02`, `fog-same_category-01` and
`fog-different_category-01` runs used the same repaired native executable, an
invalid-reply fixture and EmptyAI for blue. These internal visibility checks ran
without a window; headful gameplay acceptance is separate. The initial JSON
requests were identical for hidden changes and the 15-to-19 change. The 21-unit
variant changed `quantity_category` from 3 to 4, providing a positive control.
No exact enemy count appeared in the exported neutral army. All runs completed
cleanup and preserved the installed profile. Native fallback ended turns after
rejecting the malformed replies; no model calls were made.

`fog-comparison-02.json` records the comparison. The earlier `fog-hidden-01` is
invalid as an invariance fixture: its Python builder shared the two hero army
lists and accidentally also changed the red army. The generator now creates
independent army records, and the hidden fixture was regenerated and rerun.
The failed fixture and first comparison are preserved rather than overwritten.

Scope: these checks cover initial observation, offered paths/actions and the
end-turn fallback for the listed mutations. They do not establish invariance
after movement, battles, discoveries or save/load, nor cover every hidden-state
field. They predate the in-progress persistent-memory integration and must be
repeated against its final native build.

## First full Codex match

`codex-duel-baseline-01` used the corrected map, red ExternalAI and blue
Nullkiller2, seed 42, and configured difficulty `impossible` (200%). It was
headful. The controller snapshot is `.build/controllers/duel-baseline-01`; the
manifest hashes its actual files, model instructions and referenced materials.
The native build predates the persistent-memory work.

Codex captured the blue town on day 11. The engine log records Catherine visiting
that town, ownership changing from blue to red, `You captured both towns.`, and
Nullkiller's explicit `I heard that player 0 (red) won` / `player 1 (blue) lost`.
Decision `0:11:0` selected `move-5` with `provider: codex`, model `gpt-6.1-sol`,
reasoning `medium`, and 12.476 seconds. The test runner's reviewed outcome is
`llm_win`, backed by an extract from that log and decision metadata.

The match used 22 decisions: 17 actual Codex replies and five deadline fallbacks
that ended the turn. It finished before the 600-second test deadline. After the
engine's final game result, the runner was stopped through its own stop command;
cleanup completed and installed-profile hashes stayed unchanged. No gameplay
input was sent by a human or by UI automation. Inspection captured only images.
Successful replies' consumed reference hashes matched the manifest snapshots.

This is one win on one small training map, including fallback turns, not a win-rate
estimate or complete feature acceptance. An experimental shorter instruction was
replayed against the timed-out day-3 observation in `compact-replay-01`; it also
hit the 17-second deadline. Its valid end-turn response was fallback, so that
experiment does **not** demonstrate a latency improvement and was not adopted.

## Garrison reinforcement and the memory build

`transfer-red-01` established the missing action at the public controller seam:
the fixture had a visiting hero and town troops, but no transfer candidate. Its
controller failed with `Town has troops and a visiting hero, but no transfer is offered`.

The adapter now offers each transferable town stack separately and rechecks both
owners, the visiting hero, the source stack and destination space before sending
an ordinary ArrangeStacks request. It merges identical troops or moves a stack
into a free hero slot. It confirms the decrease in the town army, increase in
the hero army and unchanged resources after the server response.

After rebuilding client/server/library, `transfer-green-01` replayed the same
map and fixture. The hero changed from 40 pikemen/20 archers to 45 pikemen/20
archers, then gained seven griffins; the town became empty. Both transfers
logged `observed=1`, and the next requests contained `completed` memory records.
The run preserved the installed profile and completed process cleanup.

That build includes persistent-memory code. All four `fog-*-memory-01` runs
repeated the corrected visibility experiment. Initial observations, actions and
memory (13 remembered entries) remained identical for the hidden and within-range
mutations; the cross-category positive control changed the request. The summary
is `fog-memory-comparison-01.json`. These are still initial-state checks.

`memory-model-replay-01` sent the first transfer observation to the real Codex
controller. It reached the deadline and returned fallback. Therefore it does
not prove a model-authored plan in a running game.

The full Python run initially passed 19 checks and failed four of the 15 tester
checks, whose default fixture still launched the now-live Codex controller with
a two-second timeout. Pointing those record/replay tests at the existing fixed
subprocess fixture made all 15 tester checks pass (5.932 seconds). The real
controller and transport checks were already green. The rebuilt native
strategy-memory CTest passed 1/1; `git diff --check` passed. No checks here replace
the outstanding full-game save/load, Windows or final independent review gates.

## Saving during a controller request and loading a new process

`save-probe-01` built a mage guild and entered the second controller request.
Sending the ordinary console `save` command produced no file. VCMI's console
uses `std::cin.rdbuf()->in_avail()`; a standalone Apple libc++ check with 17 bytes
available on stdin returned zero. The macOS integration patch now also polls
the stdin descriptor, retaining the existing timed shutdown wait.

With that repair, `save-probe-02` sent `save Saves/ExternalAIProbe` during
request `0:1:1`. The server confirmed the save before that controller returned.
The saved state had one completed mage-guild purchase, 8,000 gold, the fixture's
eight-field plan, and two model attempts consumed.

The first reload, `load-probe-01`, exposed a separate upstream debug-launch bug:
`debugStartTest` unconditionally clicked the local human color even when an
AI-only save had no human. This created an invalid player slot, and the server
refused to start (`Human player invalid has no heroes and no towns!`). The patch
now sends that lobby action only for a valid player color.

`load-probe-02` loaded the same save after this repair. Its first request was
`0:1:2` with one call remaining. The plan, completed-purchase history, buildings,
hero and resources matched the saved observation. The first purchase was not
replayed. Both save/reload runners cleaned their process groups and preserved
installed-profile hashes. `save-load-comparison-01.json` records these checks.

The tester now accepts an optional private `save_resource` and hashes it; its
17 checks pass, including missing/escaping save rejection and snapshot integrity.
`tests/test_native_save_load.py` makes the native scenario repeatable with an
explicit private configuration. This is deterministic integration evidence;
it does not use Codex or establish behavior for a save made during a battle or
an unacknowledged purchase.

The complete opt-in native regression passed in 34.032 seconds. Evidence is in
`.build/playtests/save-load-ffodgjzr`; its reload reached day 2 with three calls
available again. The source overlay's integration patch reverse-applies cleanly,
and `git diff --check` passes.

## Native profile isolation

`tests/test_native_profile.py` first failed against the old executable: despite
an explicit profile request, `--version` printed the installed macOS data path.
The engine now supports `VCMI_PROFILE_DIR` on macOS and Windows. Its native
directory implementation keeps all writable paths below that absolute directory
and delegates only executable and shipped-data paths to the platform. It does not
change HOME or run migrations against the installed profile.

The macOS test passed with a Unicode path containing spaces (4.523 seconds).
All six reported writable paths matched, required directories were created and
installed data/log hashes stayed unchanged. The Windows branch reads the wide
environment value; it has not yet been compiled or run on Windows.

The tester now checks the profile capability through `--help`, then verifies all
six paths from `--version` before launching. The old `profile_shim.cpp` has been
removed. A pre-change regression failed because preflight did not provide native
path evidence. After integration, the full save/load regression passed again in
33.906 seconds, under `.build/playtests/save-load-lv9hcw5v`, with no injected profile
library. The 17 tester checks passed in 6.093 seconds. The sandbox and installed
profile hash checks remain in place.

## Full match with memory

`codex-duel-memory-01` is a second full headful match, with the native memory and
troop-transfer implementation. The map, seed 42, red ExternalAI / blue Nullkiller2
assignment and configured 200% difficulty match the earlier scenario. Codex
captured the blue town on day 4. There were eight decisions: seven from Codex and
one deadline fallback. The final `0:4:0` decision chose the offered attack on town
17 at `(30,11,0)` in 13.947 seconds; the engine explicitly reported red's victory
and blue's defeat. The reviewed result and extracted evidence are in that run.
The initial model-authored plan appeared in later requests, alongside confirmed
recruitment and movement outcomes. The runner was stopped after the game result;
cleanup completed and installed-profile hashes were unchanged. No gameplay input
was supplied externally. The Mac was locked, so this run has no fresh visual proof.

This is a successful full-match integration of memory, not a causal measurement
of its benefit. The two wins used different native versions and model decisions;
they do not establish a win rate or prove that memory caused the shorter game.

## Swapped sides and unsuccessful defense calibration

`codex-duel-memory-swapped-01` ran red Nullkiller2 against blue ExternalAI,
seed 43 and 200% difficulty, using native profile isolation. Blue lost on day 5.
Eight decisions contained four Codex replies and four deadline fallbacks; the first
three turns ended on timeout. On day 4 the observation included an enemy hero near
the home town. On day 5, after that hero left sight, the model moved its only army
farther away despite an offered return route. The engine explicitly recorded red
capturing both towns and blue losing. This is evidence of a poor decision in that
state, not evidence of where the unseen enemy was during each request.

An experimental knowledge paragraph asked the model to retain a recent nearby
threat until resolved and avoid leaving an undefended home town. A replay of the
problem observation still timed out. An offline diagnostic with a 35-second limit
returned a valid choice toward home after 19.379 seconds; game deadlines stayed
unchanged. That single diagnostic does not explain all latency failures.

A further experimental instruction limited strategy prose and allowed `strategy:
null` when the saved plan remained viable. Three fixed-observation replays produced
one Codex return-home choice in 16.571 seconds and two 17-second fallbacks. The full
headful `codex-duel-defense-01` game with these experimental references then lost
as blue on day 3 (eight Codex replies, one fallback). The final request offered an
attack on the visible enemy town but timed out; the evidence does not establish
that this attack would have won the battle. The experimental prompt is not adopted
as a proven improvement.

Both runs have reviewed `llm_loss` outcomes and extracted engine evidence. Cleanup
completed and installed-profile hashes were unchanged. There are no fresh screen
captures because macOS was locked. Across the four training games there are two
wins and two losses with differing builds, sides and prompts; this is not a
controlled evaluation or a win-rate estimate.

## Developer launcher and portability work

`scripts/play.py` creates a new private profile, generates the scenario and checks
the native profile capability and all writable paths before launching. It checks
Codex CLI 0.160.0 and subscription login, and prevents two launchers from sharing a
profile. On macOS, the private `player Зов` profile passed preflight and reached the
main menu; a second launcher was refused, and Ctrl-C completed owned-group cleanup.
This does not prove human gameplay or provide fresh visual evidence.

Windows source now selects the native npm `codex.exe`, uses wide arguments in the
transport test driver and a native executable for scripted Codex tests. Selection
tests first reproduced passing a batch wrapper unchanged; after the repair they
passed with spaces and Cyrillic in the installation path. The native fixture uses
`execv` on macOS and a suspended child assigned to a kill-on-close Job on Windows.
The Windows branch has not been compiled or run here. `scripts/build_windows.py`
and [the playing guide](playing.md) define the pending machine checks.

The Mac portability run built both drivers and passed 42 of 44 Python tests in
27.277 seconds, with two opt-in native game/profile tests skipped. Subsequent
Windows Job ownership tests are Windows-only and remain skipped here. The launcher
now creates the Windows client suspended, assigns it to a kill-on-close Job, and
then resumes it; this replaces PID-tree cleanup that could miss children after a
client crash. The implementation follows Microsoft's
[Job lifecycle](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
contracts, but source inspection and Mac tests are not Windows runtime evidence.

The native profile regression was rerun after making it portable: it passed on
macOS in 4.799 seconds, including protected installed-profile hashes. Launcher
preflight with `player Зов` again confirmed isolation, CLI version and ChatGPT
login without opening the game.

The private `.build/windows-handoff-2026-10-04/vcmi-llm-windows-source.zip`
contains 66 source/documentation files plus a SHA-256 manifest, with no game data
or credentials. Its SHA-256 is
`40b3fbb095038d695e803db4ca8368845a6ebc7416e97bc5f788220c7bfd9d33`.
All member hashes were checked after extraction. Running the extracted source
against the already-built Mac test drivers passed 42 of 46 tests in 27.508 seconds;
the two native opt-in checks and two Windows Job tests were skipped. This is an
unreviewed developer handoff, not a Windows binary or a release.

## Hidden object insertion/removal and movement

The new `tests/test_native_visibility.py` runs paired real-engine fixtures through
the tester, comparing complete requests `0:1:0`, `0:1:1`, and `0:1:2`. The script
moves the hero twice; the test checks that its position actually changed. These
diagnostic runs are headless and make no model calls.

Before the repair, `.build/playtests/visibility-79upp9zq` failed for insertion and
removal of a distant resource. The visible town's exported ID was 16 in the base
map, 17 with the unseen insertion, and 15 with the unseen removal. The changed
labels also appeared in actions and memory. Hidden army/resource/terrain changes
that retained object numbering still passed, explaining the earlier narrower
green checks.

The adapter now assigns a player-local label when it observes an object and
persists the private engine-ID correspondence separately from exported memory.
Candidate execution retains internal engine IDs. The same real-game regression
passed in 32.479 seconds under `visibility-dnq29rq8`: base, hidden mutations,
hidden insertion and hidden removal produced identical full requests before and
after movement. All four runs completed cleanup and preserved installed-profile
hashes. This covers those exact mutations and movements, not every possible map
feature or hidden-state change.

The native memory driver initially passed its alias stability/load and legacy-label checks
alongside the existing memory tests. The native save/load regression then passed
in 34.214 seconds under `save-load-p9ptwtnv`, retaining the model plan, attempt
budget, completed purchase and public object references. The previously prepared
Windows source kit predates this repair and must be refreshed before final acceptance.

## Battle continuation and developer-memory repair

Independent review found that the engine sends the start of an upcoming battle,
but completes it through `battleEnded()` rather than a matching unblock packet.
The adapter did not implement that callback, so subsequent decisions remained
blocked after a surviving hero finished combat. Its movement deadline could also
expire while a human was still fighting or reading the battle result.

The native regression now attacks a neutral stack and checks for request `0:1:1`
after the actual engine `BattleEnded` event. The first attempted reproduction had
an incorrect log matcher and is not regression evidence. The corrected run
`battle-resume-who86j9h` failed for the intended missing next decision in 17.733
seconds. After adding the callback and excluding active battle time from request
acknowledgement deadlines, `battle-resume-082u8doc` passed in 9.804 seconds. It
verified a surviving hero, the recorded attack result, cleanup and unchanged
installed-profile hashes. This scripted, headless test does not establish human
UI behavior or the duration of a manually played battle exceeding 180 seconds.
Shutdown still wakes the battle wait; model deadlines are unchanged.

Review also rejected optional migration of global IDs from pre-alias developer
saves. That migration is removed: only incompatible AI memory and pending intent
are cleared, retaining game state and the consumed attempt budget. Current saves
with a private alias map keep their memory. The native memory driver passed this
behavior check, and current-build save/load passed again in 33.680 seconds under
`save-load-_iiljwap`, preserving the plan, budget and completed purchase.
The full before/after-movement hidden-state comparison also passed again in
32.433 seconds under `visibility-cm8g462v` on this repaired build.

The headful `codex-duel-alias-01` match (red LLM, blue Nullkiller2, seed 44, 200%)
ended in an engine-confirmed LLM victory on day 4: seven model replies and one
timeout. Cleanup and protected hashes passed. The winning battle ended the game,
so this match did not cover continuation after combat; it used the build before
the battle repair. Across the five training games there are three wins and two
losses with different builds, sides and prompts, not a controlled win-rate study.

## Remaining acceptance

Human play with fresh visual evidence and Windows compilation/gameplay remain
outstanding. Both independent
targeted reviews approved the battle/memory repair. The exact final scripted
battle fixture passed again in 9.890 seconds under `battle-resume-ud9delb2`.
Final-build Codex gameplay is recorded below. Current-build
save/load during a model request and the defined movement-level hidden-state
comparisons have native proof. Saves during battles or unacknowledged actions
remain untested cases, not implied by that proof. A scripted victory alone is
not evidence of model strategy or either human interface.

## Installed macOS runtime

The earlier smoke bundle copied raw build binaries whose `LC_RPATH` still pointed
into `.build/mac/bin` and the local Conan cache. It was a local fixture, not a
portable runtime. The upstream `cmake --install` path now produced the separate
`.build/mac-installed-2026-10-04/VCMI.app` (47 MiB), collecting dependencies and
setting bundle-relative library paths. The install log is
`.build/mac-install-2026-10-04.log`.

The client `--version` succeeded inside a sandbox denying reads from the Conan
cache and raw build binaries; all six writable paths resolved inside a fresh
private profile. A static audit of 38 native files found no non-system absolute
dependency or runtime search path (`.build/mac-installed-link-audit.json`).
`DYLD_PRINT_LIBRARIES` produced no image list for these signed binaries, so it is
not used as evidence of loaded-image paths. A real battle through the tester
passed on the installed runtime in 10.824 seconds under `battle-resume-tfprcaoc`,
including continuation, cleanup and installed-profile protection. This establishes
local runtime packaging, not another Mac's OS compatibility or notarization.

The local developer archive
`.build/mac-handoff-2026-10-04/VCMI-LLM-macOS-arm64.tar.gz` contains 823 hashed
files plus its manifest, including the runtime and repository-relative controller
and launcher sources. It contains no Heroes III LOD files. Every archived member
was checked against the manifest. SHA-256:
`2b2efb1d16640133a7f6a65ea3ced80233cafc2f5d658b85a1240a3452a9e013`.
From its separate package directory, `scripts/play.py ... --check` confirmed
profile isolation and subscription login. The packaged engine then passed the
native battle regression in 10.606 seconds (`battle-resume-5jcs9pic`). These are
local checks; manual UI acceptance is still unavailable because the Mac is locked.

## Repaired-build Codex match

`codex-duel-battle-repair-01` used the reviewed battle/memory code, ordinary
production controller instructions, red LLM versus blue Nullkiller2, seed 44 and
200% difficulty. Red lost on day 10. The client logged the red elimination dialog
from `CPlayerInterface::gameOver`'s loss branch after blue visited the red town;
that evidence was attached as a reviewed `llm_loss`. The final visible dialog
remained open until tester cleanup; it was not dismissed through a locked UI.

There were 15 requests: six Codex replies and nine 17-second timeout fallbacks.
The model recruited troops and moved its hero. After the hero lost a battle on
day 7, further requests continued on days 8–10, so battle completion no longer
stranded adventure processing. The timing limitation is recorded as a tester
episode with per-request metadata in `latency-evidence.json`. This trial does not
establish why provider latency varied or attribute the loss to one cause.

Tester cleanup completed and protected installed-profile hashes were unchanged.
Across all six training games there are three wins and three losses with differing
builds, sides and prompts. This is not a controlled win-rate estimate. No model,
deadline or prompt changes were made to turn this trial into a success.

## User-approved 35-second decision budget

After reviewing those timeouts, the user approved 35 seconds for Codex. The
controller now allows 35 seconds, the tester defaults to and caps at 37 seconds,
and the native exchange allows 40 seconds. The model, medium reasoning, three-call
turn limit, cancellation and fallback behavior are unchanged. Old captured runs
and artifacts retain their original budgets; use the new packages for this setting.

A real subprocess regression first failed on the old controller in 17.088 seconds:
a valid reply delayed by 25 seconds was replaced with end-turn. After the change,
all four controller tests passed in 61.947 seconds, including acceptance of that
reply and cancellation of a 45-second model stub near the new 35-second deadline.
All 17 tester tests passed in 6.261 seconds. The native client/server were rebuilt
and installed into `.build/mac-runtime-35s`; both native battle tests passed in
44.566 seconds. The new case passes a 25-second delayed response through both
the recorder and actual engine before combat and verifies the next decision.
Both game runs completed cleanup and preserved installed-profile hashes.

Decision-only replays of the first three failed requests from
`codex-duel-battle-repair-01` are recorded under `.build/playtests/timeout35-replay`.
All three received validated real Codex replies without fallback; controller
durations were 22.445, 19.926 and 19.717 seconds. Each selected `recruit-1`.
These replays do not execute game actions, replay a full match, or establish an
improved win rate; they demonstrate that useful replies can arrive after 17 seconds.

The initial 35-second local packages were under `.build/handoff-35s` (superseded
by the corrected starter-config packages below):

- `VCMI-LLM-macOS-arm64-35s.tar.gz`, SHA-256
  `51f7588736cb571821d94c39a87142345298d2ef89538c13442cbf476e500588`.
- `vcmi-llm-windows-source-35s.zip`, SHA-256
  `77fede6016eff13aa42a2971ba850be6e763a065ca7e2806b0f632fed06abe93`.

Archive member hashes were verified. Windows remains a source handoff awaiting
compilation and game acceptance on Windows 11 x64. These packages supersede the
previous 17-second developer packages; previously running games must be restarted
through the isolated launcher to use the new native deadline.

Independent review found that the documented `playtesting/examples/match.json`
still explicitly selected an 18-second recorder limit. That override is removed,
so new runs prepared from the example inherit the 37-second default. Historical
captured runs are not modified. A fresh test config derived from that example,
with local test inputs and no timeout override, accepted a delayed building choice in 25.069 seconds
(`.build/timeout35-example-proof/run`); its prepared manifest contains 37 seconds.

Use the corrected packages in `.build/handoff-35s-final`:

- `VCMI-LLM-macOS-arm64-35s.tar.gz`, SHA-256
  `f4beaf84a651ebaa5c543b736fad735cb7ee547ccbfbab6434e84d8d244b6671`.
- `vcmi-llm-windows-source-35s.zip`, SHA-256
  `be4f45388a5e66daefea9db9f8d9bb0ea0bf91c89813790ca511f7bff7c8239c`.

Both archives contain the corrected example and unchanged tested 35/37/40-second
runtime sources. The Mac archive's regular-file set and hashes match its manifest;
generated Python bytecode was excluded. The native binaries are unchanged from
the tested 35-second installation.
