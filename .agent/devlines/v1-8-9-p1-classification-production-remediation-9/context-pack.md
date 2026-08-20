# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-9`
Baseline SHA: `988f44a358d65d42b3179afcf6b50e328cf3546d`

## Objective
# Workbench v1.8.9 P1 Classification Production Remediation 9 Objective

Close the returned independent-spec-review gaps from exact baseline
`988f44a358d65d42b3179afcf6b50e328cf3546d` without changing the completed
remediation line, central Agent/Notebook/router/provider behavior, or the
report producer.

The real artifacts-list seam must fail closed from the repository reader
through `GET /runs/{run_id}/artifacts` to `ReportWorkspace`. The index must
contain an explicit `artifacts` list; every record must satisfy the existing
canonical `ArtifactRecord.to_dict()` contract and the list-reader identity
invariants: exact required fields and types, known artifact kind, normalized
run-relative path containment, lowercase SHA-256/digest shape, and unique
nonempty artifact identity. Unknown `record_type`/artifact kind, missing or
null fields, duplicate IDs, path escapes, invalid digests, and tampered
structure must all produce the exact typed
`ARTIFACTS_INDEX_INVALID` outcome. The list route must never fall back to
`groups=[]` or leak parser exceptions.

The classification production regression near line 685 must assert exactly
`CLASSIFICATION_SERVER_IDENTITY_MISMATCH`, with a RED probe showing that an
alternative error code is not acceptable. Existing active project/run/
namespace, artifact/digest, split/fold/OOF/holdout, weights,
calibration/threshold, receipt, and evidence bindings must remain server-owned
and must not be guessed or recomputed from raw JSON.

The remediation is limited to:

- `backend/workbench/repository/run_repository.py`
- `backend/workbench/http/runs_routes.py`
- `frontend/src/report/ReportWorkspaceContext.tsx`
- `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`
- `tests/test_v189_classification_production.py`
- `tests/test_api.py` only if focused canonical-index fixtures require contract
  alignment
- this objective and its new handoff

Required evidence is TDD RED before production changes, then GREEN for the
repository/HTTP/ReportWorkspace probes, the classification focused suite,
frontend focused suite, `tests/test_api.py -k artifacts`, compileall, diff
check, formal verify, and formal retrospective. The two known asynchronous
`tests/test_api.py -k artifacts` fixture failures remain a known gate unless
directly caused by this validator. Browser acceptance, external provider
benchmark, central integration/cutover, host full gate, merge, tag, and
release remain `NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/http/runs_routes.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `tests/test_v189_classification_production.py`, `tests/test_api.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-classification-production-remediation-9-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-remediation-9-handoff.md`
- Allowed paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/http/runs_routes.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `tests/test_v189_classification_production.py`, `tests/test_api.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-classification-production-remediation-9-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-remediation-9-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/notebook`, `backend/workbench/predictive_research`, `backend/workbench/engine/stages/report.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `scripts/gate.sh`
- Dependencies: `v1-8-9-p1-classification-production-remediation-8`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api.py -q -k artifacts`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `browser/provider/central integration/host full gate/release remain NOT VERIFIED`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
