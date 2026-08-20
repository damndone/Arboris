# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-remediation-7`
Baseline SHA: `df25a0f5154520423ad45833daf4a1ccd3c1615b`

## Objective
# v1.8.9 P0 Evidence/Report Hardening — remediation-7 objective

## Objective

At the exact clean baseline `df25a0f5154520423ad45833daf4a1ccd3c1615b`, close
the independent P1-D finding left by remediation-6.  The production
orchestrator path must provide `ReportStage` with the exact server-owned
Report owner/projection pair through `ctx.artifacts`, and the ARMA-GARCH
report branch must fail closed with typed unavailable state before it reads or
constructs a raw deliverable when admission is absent.

## Required outcomes

1. Exercise the real orchestrator run path, not only a helper: a server-owned
   Report owner and its issued projection must be injected into
   `ctx.artifacts` before the stage pipeline runs, so `ReportStage.run` can
   receive the valid pair.  The owner/projection must remain exact server
   admissions; caller-shaped or copied values must not be accepted.
2. Make the ARMA-GARCH branch perform the same owner/projection admission
   before `build_arma_garch_deliverables` or any raw deliverable construction
   or read.  Missing admission must produce typed unavailable/blocked report
   state without invoking the raw builder.  A valid server-admitted owner and
   projection must preserve the existing ARMA report path.
3. Add real stage integration probes for orchestrator-to-`ReportStage`
   wiring, plus missing-admission and valid-admission ARMA-GARCH tests.  The
   negative tests must prove the raw builder/read path was not reached and the
   positive tests must prove the owner-issued path remains usable.
4. Run focused and impacted tests in a socket-capable host, direct admission
   and no-IO/order probes, `compileall`, `git diff --check`, and formal
   verification/retrospective generation.  Record exact RED/GREEN commands,
   results, final commit, and digests in the remediation-7 handoff.

## Boundaries

Only the target worktree may change.  Initial implementation scope is the
Evidence/Report stage and its focused boundary tests plus remediation-7
objective/plan/handoff docs.  The orchestrator module is deliberately not in
the initial allowlist; if the RED integration probe proves that the production
injection requires `backend/workbench/orchestrator/__init__.py`, expand the
formal Context Pack only with an explicit `rescope-context` call naming that
exact file and no broader directory.  Do not modify central Agent/Notebook
semantic engines, providers, estimators, frontend, dependencies, deployment
wiring, the root checkout, or another worktree.  Push, merge, tag, release,
and broad fallback behavior remain out of scope.

## Protected paths

- `backend/workbench/agent/`
- `backend/workbench/http/agent_routes.py`
- `backend/workbench/http/notebook_routes.py`
- `backend/workbench/providers/`
- `backend/workbench/estimator/`
- `backend/workbench/live_host/`

## Boundary
- Affected paths: `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7-plan.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7-handoff.md`
- Allowed paths: `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7-plan.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-7-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/providers`, `backend/workbench/estimator`, `backend/workbench/live_host`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py -k 'orchestrator_report_admission or arma_garch_report_admission'`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_evidence_report_boundary.py`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/models/arma_garch/test_deliverables.py`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_orchestrator_e2e.py`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/engine/stages/report.py backend/workbench/orchestrator/__init__.py`, `git diff --check`
- Known gates: `browser acceptance NOT VERIFIED`, `provider execution and production C0 NOT VERIFIED`, `central Agent/Notebook semantic integration NOT VERIFIED`, `live-host integration NOT VERIFIED`, `full repository/release gate NOT VERIFIED`, `merge/push/tag/deploy NOT VERIFIED`

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
