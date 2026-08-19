# Frozen Context Pack

Line: `v1-8-9-p1-classification-production`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 P1 Classification Production Objective

Close the production classification path on top of the frozen v1.8.9
classification contracts. The path must consume the declared task/split/
availability/weight specifications instead of silently forcing IID raw-frame
execution; use fold-local preprocessing; keep model selection, calibration,
thresholding, and the final holdout separated; and emit one evidence shape
that the server-indexed Report consumer can safely read.

The completion adapters are Logistic Regression and Random Forest. This line
does not add model families, change the central Agent/Notebook router, or call
an external provider. Unsupported categorical/missing/weight/split cases must
return typed blocked or unavailable outcomes rather than silently degrading.

Required outcomes:

- task-declared IID/group/temporal/panel profiles are either executed with
  their declared row/entity/time invariants or rejected explicitly;
- preprocessing is fit only on the relevant training rows and its receipt is
  bound to the split and artifact identity;
- weights are either honored end-to-end or typed blocked before fitting;
- calibration and threshold policy are represented honestly, with no claim of
  calibrated evidence when only descriptive bins exist;
- holdout release remains sealed and one-time;
- classification evidence is internally consistent (`validated` only when the
  packet is complete, otherwise `degraded`/`unavailable`) and matches the
  typed frontend consumer shape.

The central cutover, browser acceptance, external provider benchmark, host
full gate, merge, tag, and release remain separate gates.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/prediction.py`, `tests/test_v189_classification_production.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `frontend/src/report/ReportView.v189.test.tsx`
- Allowed paths: `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/split_kernel.py`, `backend/workbench/prediction.py`, `tests/test_v189_classification_production.py`, `tests/predictive_research/test_classification_consumers_v189.py`, `frontend/src/report/ClassificationEvidence.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ClassificationEvidence.test.tsx`, `frontend/src/report/ReportView.v189.test.tsx`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/http`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `scripts/gate.sh`
- Dependencies: `v1-8-9-foundation-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py tests/predictive_research/test_classification_contracts_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/predictive_research/test_classification_leakage_v189.py tests/predictive_research/test_classification_consumers_v189.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `central Agent/Notebook/Report mount is separate`, `external provider/browser/full gate/release remain NOT VERIFIED`

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
