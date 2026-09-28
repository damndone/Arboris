# Formal development-line control

Open exactly one formal development line per release version (for example
`v1-8-9`), using only `scripts/devline_control.py start`. Do not open separate
lines for phases, slices, remediations, or reviews inside a version; those are
events on the version's line. The objective file, exact baseline SHA,
boundaries, tests, and known gates must be supplied before implementation
begins. Read the resulting `.agent/devlines/<line_id>/CONTEXT_PACK.md` (the
formal on-disk `context-pack.md`), `.agent/development/global_rules.md`, and
relevant prior retrospectives before implementation; the Context Pack
identifies the exact historical evidence to read.

Do not hand-create or edit `.agent/devlines` files. Use the formal CLI for
append, verification, retrospective generation, and explicit Context Pack
refresh. Correct a frozen affected-path scope only through explicit
`scripts/devline_control.py rescope-context --line <line_id> --affected-path <repo-relative-path>`;
an allowlist expansion/replacement additionally requires explicit repeatable `--allow-path` values.
Never edit a Context Pack or manifest in place. Existing `scripts/devline_memory.py` and legacy `.agent/devlines/*`
records are migration evidence only: do not extend, rewrite, or treat them as
formal FMS evidence.

Use the CLI to append material FAILURE, ERROR, GAP, WASTE, REVIEW, GATE, or
STATE_CHANGE events to the version line's `events.jsonl`. Record decisions and
outcomes that a later version would need, not every intermediate test run.
Before closing the version, verify the event stream and regenerate
`RETROSPECTIVE.md` through the same control.

Formal FMS verification is a process-control gate only; it does not replace
model, containment, browser, performance, or release acceptance evidence.
