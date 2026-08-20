# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-remediation-8`
Baseline SHA: `cf41b0ab0a89e85a1e05d337b0ef6b065080a1e0`

## Objective
# v1.8.9 P0 Evidence/Report Hardening — remediation-8 objective

## Objective

At exact clean baseline `cf41b0ab0a89e85a1e05d337b0ef6b065080a1e0`, close the
remaining P0 ARMA-GARCH report-path defect.  The legal owner-admitted
`_run_workflow` path must execute the real ARMA-GARCH deliverable build and
then construct an owner-issued `ReportDocumentWriterV1` before the real
Jinja template and durable writer run.  A missing or invalid admission must
return typed unavailable/blocked state before any raw ARMA builder/read and
must prove zero builder calls.

## Required outcomes

1. Preserve the existing fail-closed admission gate.  Missing, forged, stale,
   or wrong-root owner/projection input produces typed unavailable/blocked
   state before `build_arma_garch_deliverables` or any ARMA artifact read; the
   builder call count remains zero.
2. Repair the legal ARMA path so `_run_workflow` reaches the real
   `build_arma_garch_deliverables` implementation, converts its result through
   the server-owned projection/document boundary, and invokes the real
   `ReportDocumentWriterV1` plus real template rendering and durable artifact
   registration.  No renderer mock may stand in for this proof.
3. Preserve exact owner, request identity, receipt, canonical project/run
   root, artifact identity, content hash, and rendered file hash bindings.
   Do not reintroduce `ReportStage` raw-dict fallback, ownerless legacy
   rendering, or a second report engine.
4. Add a real renderer probe using only a temporary canonical run root and
   safe fixture data.  Keep the existing missing-admission probe and extend
   the valid probe so it asserts the real writer/template path and the
   resulting indexed artifact/hash bindings.
5. Audit ARMA deliverable callers.  Keep typed contract or explicit typed
   unavailable behavior for all callers; record exactly these three known
   legacy ownerless/raw caller GAPs without weakening the contract:
   `legacy_arma_raw_renderer_boundary`,
   `ownerless_normal_report_e2e_boundary_one`, and
   `ownerless_normal_report_e2e_boundary_two`.
6. Run evidence/report focused and impacted suites, compileall, diff-check,
   formal verification, final GATE, retrospective generation, and handoff.
   Commit only scoped changes in this worktree.  Do not push, merge, tag,
   deploy, or modify another worktree/root checkout.

## Scope

- `backend/workbench/engine/packs/arma_garch/deliverables.py`
- `backend/workbench/engine/stages/report.py`
- `backend/workbench/orchestrator/__init__.py` (only if the real workflow
  wiring requires it)
- `tests/test_v189_evidence_report_boundary.py`
- `tests/models/arma_garch/test_deliverables.py` (only for typed contract
  caller alignment if required)
- this objective, its implementation plan, and the remediation-8 handoff

## Protected boundaries

Do not modify Agent, Notebook, provider, estimator, frontend, dependency,
deployment, live-host, release, or unrelated report/export surfaces.  Do not
hand-edit `.agent/devlines` files.  Do not reset, checkout, delete, overwrite,
push, merge, or tag.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-plan.md`, `backend/workbench/engine/packs/arma_garch/deliverables.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_v189_evidence_report_boundary.py`, `tests/models/arma_garch/test_deliverables.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-plan.md`, `backend/workbench/engine/packs/arma_garch/deliverables.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_v189_evidence_report_boundary.py`, `tests/models/arma_garch/test_deliverables.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-8-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/notebook`, `backend/workbench/providers`, `backend/workbench/estimator`, `frontend`, `backend/workbench/live_host`, `dependencies`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py -k 'arma_garch_report_admission or arma_garch_real_renderer'`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/models/arma_garch/test_deliverables.py tests/test_orchestrator_e2e.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python -m compileall -q backend/workbench/engine/packs/arma_garch/deliverables.py backend/workbench/engine/stages/report.py backend/workbench/orchestrator/__init__.py`, `git diff --check`
- Known gates: `browser-visible acceptance`, `provider-live-host-execution`, `central-agent-notebook-integration`, `full-repository-gate`, `release-acceptance`, `three-legacy-ownerless-raw-caller-gaps-remain`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
