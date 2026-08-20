# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-remediation-2`
Baseline SHA: `74e92d89d889726d0d6955e5faeae6b4367898d5`

## Objective
# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 2

## Exact baseline

This fresh implementation line starts from the target worktree product tip
`74e92d89d889726d0d6955e5faeae6b4367898d5`. Prior formal lines, their
Context Packs, events, retrospectives, handoffs, and commits are historical
evidence only and must not be edited.

## Required remediation

Close the independently reviewed P1 in the package-local Data Consumer
interchange boundary:

- `_pyreadstat_module()` must admit an adapter only after a bounded real
  write/read probe over a minimal in-memory-safe frame and a safe temporary
  file; callable attributes alone are insufficient.
- A missing, import-broken, or runtime-broken pyreadstat adapter must be
  represented as typed `unavailable` with a stable `optional_dependency`
  reason at capability, manifest/admission, writer, reader, and round-trip
  surfaces; no bare adapter exception may escape.
- Preserve the existing pyarrow and other Data Consumer behavior, including
  the existing typed unavailable behavior and normal round-trip contracts.

## TDD and evidence requirements

Write RED tests first for a callable pyreadstat adapter whose write/read
operations raise `RuntimeError`, covering capability, manifest/admission,
writer, reader, and round-trip surfaces. Add a bounded real-adapter probe test
using only a minimal frame and a safe temporary file; it must not read user
data. Record the RED failure through the formal event stream, then implement
the smallest fail-closed fix and retain the GREEN evidence.

## Scope and boundaries

Only package-local Data Consumer implementation, its focused tests, this
objective, the final handoff, and formal development-line files are in scope.
Do not modify root, other worktrees, central Agent/Notebook/Report/cutover
code, providers, frontend product code, dependencies, or prior formal lines.
Do not install dependencies, sign/broadcast anything, or claim browser,
provider, central, host, full-gate, merge, tag, or release acceptance.

## Verification and known gates

Run the backend focused and impacted Data Consumer tests, impacted frontend
tests and typecheck, backend `compileall`, and `git diff --check`. Run direct
adversarial probes for absent, available, and broken pyreadstat states. Run
formal verify and CLI-generated retrospective before closeout. Browser,
provider, central, host, full, merge, tag, and release remain `NOT VERIFIED`
unless separately evidenced.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-remediation-2-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-remediation-2-handoff.md`, `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-remediation-2-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-remediation-2-handoff.md`, `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`
- Protected paths: `.agent/devlines/v1-8-9-p1-data-consumer`, `.agent/devlines/v1-8-9-p1-data-consumer-remediation-1`, `.agent/devlines/v1-8-9-p1-data-consumer-formal-closeout`, `backend/workbench/agent`, `backend/workbench/providers`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `scripts/gate.sh`
- Dependencies: `pandas`, `pyreadstat`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_data_interchange.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_consumer_projection.py tests/test_v189_data_consumer_editor.py tests/test_data_operation_routes.py tests/test_v189_data_operation_manifest.py`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`, `git diff --check`, `PYTHONPATH=backend python3 scripts/devline_control.py verify --line v1-8-9-p1-data-consumer-remediation-2`, `PYTHONPATH=backend python3 scripts/devline_control.py retrospective --line v1-8-9-p1-data-consumer-remediation-2`
- Known gates: `browser NOT VERIFIED`, `provider NOT VERIFIED`, `central NOT VERIFIED`, `host NOT VERIFIED`, `full NOT VERIFIED`, `release NOT VERIFIED`, `merge NOT VERIFIED`, `tag NOT VERIFIED`

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

### v1-8-3-cf4-admission-control (2026-07-26T15:04:30.000Z)

Completed formal devline v1-8-3-cf4-admission-control; final_state=COMPLETED; failure_lesson_keys=evidence-admission-separation, fail-closed-admission
