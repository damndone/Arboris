# Frozen Context Pack

Line: `v1-8-9-p1-survey-remediation-5`
Baseline SHA: `8571606b97c6bde5a9ad2a5264c302d4ada0b3ce`

## Objective
# Workbench v1.8.9 P1 Survey remediation-5 objective

## Objective

Perform a formal/document-only repair at the exact baseline
`8571606b97c6bde5a9ad2a5264c302d4ada0b3ce`. Do not add a statistical feature,
change product code, rerun or reinterpret the Survey engine, or alter the
already-passed remediation-4 P1 projection implementation. Create a new
append-only formal line that reconciles the independent review discrepancy in
remediation-4 and publishes an exact, evidence-backed objective/plan/handoff
for remediation-5.

## Required behavior

- Preserve remediation-4 `events.jsonl`, Context Pack, retrospective, and all
  historical remediation-4 handoff/objective/plan bytes exactly; the old line
  is immutable historical evidence.
- Record the independent review discrepancy in this new line as a `GAP` and a
  `REVIEW`: remediation-4 contains a repeated state transition
  `FOCUSED_PROJECTION_GREEN -> REGRESSION_GREEN`, while its handoff claims
  `state_chain_mismatch=0` and its plan still marks formal closeout items
  pending.
- State-chain semantics for this line are explicit: a mismatch is counted per
  non-contiguous state transition in the new line's own ordered event stream;
  historical remediation-4 inconsistencies are not rewritten or relabeled as
  zero, and the new line's own chain must verify with zero mismatches.
- Document the resolution evidence from the exact current baseline and the
  remediation-4 handoff: code/P1 projection evidence is inherited and
  unchanged; the repair here is documentation/formal reconciliation only.
- In the new plan and handoff, mark every completed formal/document-only item
  as completed. Preserve all external or unperformed boundaries as
  `NOT VERIFIED`, including central cutover, browser, provider/oracle, host,
  full gate, release readiness, merge, tag, and push.
- Close the new line only after the handoff is frozen and its digest is bound
  by the final state event; run CLI verification and retrospective generation.

## Scope

Allowed paths are limited to this new objective, plan, handoff, and the new
formal line `v1-8-9-p1-survey-remediation-5`. No product code or tests are
owned by this line.

Protected paths include the entire old formal line
`.agent/devlines/v1-8-9-p1-survey-remediation-4`, the old remediation-4
objective/plan/handoff, root and every other worktree, all product/test paths,
and all older formal records or historical handoffs.

## Baseline, dependency, and gates

- Exact baseline: `8571606b97c6bde5a9ad2a5264c302d4ada0b3ce`.
- Dependency: `v1-8-9-p1-survey-remediation-4` (read-only historical evidence).
- Product/P1 projection implementation: inherited as already passed; no code
  change or new statistical behavior is claimed here.
- Required checks: formal `verify`, formal `retrospective`, `git diff --check`,
  exact HEAD, and final clean worktree.
- `NOT VERIFIED`: central Notebook/Report cutover, browser-visible acceptance,
  external provider/oracle evidence, host acceptance, full gate, release
  readiness, merge, tag, and push.

## Final status target

`COMPLETED` for this formal/document-only repair, with the preserved external
boundaries explicitly remaining `NOT VERIFIED`.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-5-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-5.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-5-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-5-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-5.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-5-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-survey-remediation-4`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-4-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-4.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md`, `backend/workbench`, `tests`, `.worktrees`
- Dependencies: `v1-8-9-p1-survey-remediation-4`
- Tests: `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-p1-survey-remediation-5`, `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-p1-survey-remediation-5`, `git diff --check`, `git rev-parse HEAD`, `git status --short --branch`
- Known gates: `inherited Survey P1 projection evidence remains unchanged; no new statistical feature`, `central Notebook/Report cutover NOT VERIFIED`, `browser-visible acceptance NOT VERIFIED`, `external provider/oracle evidence NOT VERIFIED`, `host acceptance NOT VERIFIED`, `full gate NOT VERIFIED`, `release readiness NOT VERIFIED`, `merge/tag/push NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
