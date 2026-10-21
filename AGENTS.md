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

# Default-path performance and storage (2026-10-20)

- New default-path code must keep elapsed time, peak RSS, and run-directory
  bytes within 1.05 times v1.9.0 on the same workload. A regression blocks
  further feature work until accepted.
- Do not serialize observation rows into JSON, convert large arrays to Python
  lists for processing, or re-read/copy a whole source merely for validation.
  Use registered import digests, versioned array-byte fingerprints and compact
  summaries; explicit observation inspection may use ranges or binary arrays.
- Performance acceptance uses an otherwise test-idle host, fixed shared input
  files with SHA256, fresh workers without data generation, baseline-only noise
  calibration (at least five), then at least five alternating A/B pairs with raw
  measurements and median comparisons; sampling noise must be below 5%.
  Retain failed measurements. Numerical coefficients, standard errors and test
  statistics must remain bit-identical; do not widen reference tolerances.
- Check free disk space before every measurement; below 10 GB, report and do
  not start. Keep one fixed CSV per family under `local/perf-inputs/`, with
  its registered SHA256; the reproducer must not make per-run input copies.
  Product snapshots/uploads remain normal product outputs. Do not patch product
  functions, replace file writes, change configuration or alter the worker
  environment for measurement. Timing/memory observation stays outside product
  functions; traced timings do not certify uninstrumented time limits.
- Only one active benchmark run directory may exist. Before removing it,
  durably journal commit, case, elapsed time, ru_maxrss, optional same-run
  tracemalloc peak, directory bytes, every file's path/size/SHA256 and principal
  numerical results; verify the journal and file count. Keep one verified
  tar.gz representative per family/release, logs and scripts. This cleanup
  authorization applies to benchmark products only, never other data/worktrees.
