# Repository guidance

For planning, issues, or Wayfinder, read docs/agents/issue-tracker.md.
Research context: docs/research/2026-10-02-vcmi-llm-research.md.
Research recommendations are proposals until explicitly accepted.
Preserve the user's installed game, saves, configuration, and running sessions.
Planning and decision prototypes do not authorize production implementation.

## Model instruction routing

- **Native Instructions** (`controller/native_instructions.txt`): minimal, always-loaded
  model/executor contract — role, observations, tools, supported goals, output format,
  evidence and execution limits, plus short routing to the separate references.
- **Game Rules** (`controller/game_rules/`): how game mechanics work, including
  prerequisites and scenario/mod exceptions.
- **Strategy Guide** (`controller/strategy_guide/`): which actions to choose and why —
  priorities, alternatives, risks and reconsideration.

Put new gameplay guidance in the relevant Rules or Guide card. Change Native
Instructions only for base contract changes or clarifications; do not accumulate
strategy fixes there after each bad game decision. Split mixed guidance by
responsibility rather than duplicating it across the base prompt and cards.

Verify guidance against current controller/schema and native execution code.
Current observations, scenario/mod rules and native quotes govern game facts;
the executor contract governs supported operations. Text cannot create missing
capabilities, observations or execution behavior.
Follow each bundle's README for edits, catalog updates and validation. Prepare a
new run to use changed guidance; preserve existing prepared snapshots and sessions.
