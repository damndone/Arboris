# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-remediation-9`
Baseline SHA: `d454ddf3ec93e95775c6a8c730e45d00fa16e1f3`

## Objective
# Workbench v1.8.9 P0 Evidence/Report Hardening — remediation-9 objective

## Objective

At exact baseline `d454ddf3ec93e95775c6a8c730e45d00fa16e1f3`, create a
formal-only/audit remediation line for the independent review findings against
remediation-8.  Preserve remediation-8 as immutable append-only history, freeze
the current development rules in this line's Context Pack, and close only the
formal evidence and negative-probe assertion gaps.  Product implementation code
must remain unchanged.

## Required outcomes

1. Start formal line `v1-8-9-p0-evidence-report-remediation-9` only through
   `scripts/devline_control.py start`, with this objective, the exact baseline,
   explicit affected/allowed/protected paths, tests, and known gates.  The new
   Context Pack must capture the current persistence capability rule.
2. Append-only record the remediation-8 Context Pack drift
   (`CONTEXT_REFRESH_REQUIRED`, frozen rules empty, current global rules
   containing the persistence rule) and its disposition in remediation-9.  Do
   not edit or refresh remediation-8 records.
3. Extend the existing missing-admission boundary test with an explicit
   assertion that `run_root / "reports" / "report.html"` does not exist.  Add a
   committed wrong-root or forged negative probe only if the existing focused
   evidence does not already cover that boundary; do not duplicate product
   logic.
4. Produce a remediation-9 handoff with exact final `HEAD`, implementation
   commit and digest evidence, formal verify output, retrospective output,
   final GATE, and the product-code-unchanged proof.
5. Preserve the three legacy GAP identities exactly:
   `legacy_arma_raw_renderer_boundary`,
   `ownerless_normal_report_e2e_boundary_one`, and
   `ownerless_normal_report_e2e_boundary_two`.  Preserve browser/provider,
   central Agent/Notebook, host, full-repository, and release acceptance as
   `NOT VERIFIED`.
6. Run the scoped test, diff-check, formal verify, retrospective generation,
   and final worktree audit.  Create one scoped local commit only; do not push,
   merge, tag, deploy, reset, checkout, delete, or modify another worktree.

## Scope

- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-plan.md`
- `tests/test_v189_evidence_report_boundary.py`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-handoff.md`
- formal records generated under `.agent/devlines/v1-8-9-p0-evidence-report-remediation-9/`

## Protected boundaries

Do not modify remediation-8 records or handoff, any backend product
implementation, Agent, Notebook, provider, estimator, frontend, dependency,
deployment, live-host, release, or unrelated report/export surface.  Do not
hand-edit `.agent/devlines` files.  Do not modify another worktree or root
checkout.

## Boundary

- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-plan.md`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-plan.md`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p0-evidence-report-remediation-8`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-handoff.md`, `backend/workbench/engine`, `backend/workbench/orchestrator`, `backend/workbench/agent`, `backend/workbench/notebook`, `backend/workbench/providers`, `backend/workbench/estimator`, `frontend`, `dependencies`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py -k 'arma_garch_report_admission_missing_is_typed_and_does_not_build_raw_deliverable'`, `git diff --check`, `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-p0-evidence-report-remediation-9`
- Known gates: `remediation-8-context-pack-drift-recorded-and-left-unchanged`, `remediation-8-handoff-final-head-mismatch-recorded`, `three-legacy-gaps-preserved`, `browser-acceptance-NOT-VERIFIED`, `provider-live-host-execution-NOT-VERIFIED`, `central-agent-notebook-integration-NOT-VERIFIED`, `host-acceptance-NOT-VERIFIED`, `full-repository-gate-NOT-VERIFIED`, `release-acceptance-NOT-VERIFIED`, `product-code-unchanged`

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-plan.md`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-plan.md`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-9-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p0-evidence-report-remediation-8`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-handoff.md`, `backend/workbench/engine`, `backend/workbench/orchestrator`, `backend/workbench/agent`, `backend/workbench/notebook`, `backend/workbench/providers`, `backend/workbench/estimator`, `frontend`, `dependencies`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py -k arma_garch_report_admission_missing_is_typed_and_does_not_build_raw_deliverable`, `git diff --check`, `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-p0-evidence-report-remediation-9`
- Known gates: `remediation-8-context-pack-drift-recorded-and-left-unchanged`, `remediation-8-handoff-final-head-mismatch-recorded`, `three-legacy-gaps-preserved`, `browser-acceptance-NOT-VERIFIED`, `provider-live-host-execution-NOT-VERIFIED`, `central-agent-notebook-integration-NOT-VERIFIED`, `host-acceptance-NOT-VERIFIED`, `full-repository-gate-NOT-VERIFIED`, `release-acceptance-NOT-VERIFIED`, `product-code-unchanged`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
