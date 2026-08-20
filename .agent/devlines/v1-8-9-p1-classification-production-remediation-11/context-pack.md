# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-11`
Baseline SHA: `bab159d3ed8e19a67c17a3fdce21853437c0b451`

## Objective
# Workbench v1.8.9 P1 Classification Production Remediation 11 Objective

Close the independent-spec-review blocker from exact baseline
`bab159d3ed8e19a67c17a3fdce21853437c0b451` without changing the completed
remediation-10 line, central Agent/Notebook/router/provider behavior, or the
report producer.

The repository artifacts-index reader must derive its accepted artifact types
from the canonical producer/registry vocabulary, including the real
`formal_output` workflow artifact type. A valid canonical `formal_output`
index must pass through the repository, `GET /runs/{run_id}/artifacts`, and
ReportWorkspace. Unknown or forged artifact types, missing or null fields,
duplicate artifact IDs, path escapes, invalid digests, and malformed JSON must
fail closed with exactly `ARTIFACTS_INDEX_INVALID`; the HTTP route must return
HTTP 500 without returning groups or leaking raw parser exceptions.

An absent or unreadable artifacts index is a resource-unavailable condition:
the repository and HTTP route must return exactly
`ARTIFACTS_INDEX_UNAVAILABLE` and HTTP 503. The tests must state this status
matrix explicitly and parameterize valid `formal_output`, invalid mutations,
and missing/unreadable cases.

Existing classification production bindings remain server-owned and must not
be guessed or recomputed from raw JSON: active project/run/namespace,
artifact/digest, split/fold/OOF/holdout, weights, calibration/threshold,
receipt, and evidence. Agent, Notebook, and Report consume only typed
persisted evidence.

The remediation is limited to:

- `backend/workbench/repository/run_repository.py`
- `backend/workbench/http/runs_routes.py`
- `frontend/src/report/ReportWorkspaceContext.tsx`
- `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`
- `tests/test_v189_classification_production.py`
- `tests/test_api.py` only if focused canonical-index fixtures require direct
  contract alignment
- this objective and its new handoff

Required evidence is TDD RED before production changes, then GREEN for the
repository/HTTP/ReportWorkspace valid and invalid artifact-index probes, the
classification consumer/protocol/leakage suites, frontend focused suite and
typecheck, compileall, diff check, the required `tests/test_api.py -k
artifacts` known gate, formal verify, and formal retrospective. The two
existing asynchronous report-fixture failures remain a known gate; do not
modify the report producer. Browser acceptance, external provider benchmark,
central integration/cutover, host full gate, merge, tag, and release remain
`NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/http/runs_routes.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `tests/test_v189_classification_production.py`, `tests/test_api.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-classification-production-remediation-11-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-remediation-11-handoff.md`
- Allowed paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/http/runs_routes.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `tests/test_v189_classification_production.py`, `tests/test_api.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-classification-production-remediation-11-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-remediation-11-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/notebook`, `backend/workbench/predictive_research`, `backend/workbench/engine/stages/report.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `scripts/gate.sh`
- Dependencies: `v1-8-9-p1-classification-production-remediation-10`, `canonical artifact producer and registry vocabulary`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api.py -q -k artifacts`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `frontend npm run typecheck`, `git diff --check`, `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-p1-classification-production-remediation-11`, `PYTHONPATH=backend .venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-p1-classification-production-remediation-11`
- Known gates: `tests/test_api.py -k artifacts has two existing async report fixture failures`, `browser acceptance NOT VERIFIED`, `external provider benchmark NOT VERIFIED`, `central Agent/Notebook/Report integration NOT VERIFIED`, `host full gate NOT VERIFIED`, `release/merge/tag/root-main synchronization NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix
