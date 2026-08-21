# Frozen Context Pack

Line: `v1-8-9-p1-survey-authority-remediation`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 Survey authority remediation

## Objective

Close the independent review findings in the Survey central-source boundary.
The consumer-facing API must not be able to mint a Survey run capability or a
receipt/source snapshot from caller-shaped paths, metadata, digests, or raw
packets. Issuance must require the server-owned internal issuer and a real,
persisted, hash-checked run artifact manifest. Unsupported Survey families must
remain typed unavailable while preserving the persisted evidence status,
reason, and safe design metadata for diagnosis.

## Success criteria

1. Direct calls to the internal capability/receipt factories without the
   server issuer fail closed.
2. A directory with a `runs/<id>` shape but no verified server artifact
   manifest cannot mint a run capability.
3. A forged receipt metadata object cannot produce a validated Agent/Notebook
   projection.
4. Supported OLS/Logit Agent and Notebook projections remain green through the
   existing central service.
5. Unsupported model families return typed unavailable while retaining the
   persisted status/reason and bounded Survey design metadata.
6. No estimator, variance-engine, Report, HTTP, frontend, provider, or release
   behavior is changed.

## Required verification

Run the existing Survey central-source suite plus the new authority probes,
catalog/coverage regression, selected compileall, `git diff --check`, formal
verification, and retrospective. Browser/provider/full/release remain separate
gates.

## Boundary
- Affected paths: `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/services/survey_consumer_service.py`, `tests/test_v189_survey_central_consumer.py`, `tests/test_v189_survey_authority_remediation.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-authority-remediation-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-survey-authority-remediation.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-authority-remediation-handoff.md`
- Allowed paths: `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/services/survey_consumer_service.py`, `tests/test_v189_survey_central_consumer.py`, `tests/test_v189_survey_authority_remediation.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-authority-remediation-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-survey-authority-remediation.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-authority-remediation-handoff.md`
- Protected paths: `backend/workbench/predictive_research`, `backend/workbench/survey`, `backend/workbench/providers`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `frontend/src`, `.agent/devlines/v1-8-9-p1-survey-central-source`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/pytest -p no:cacheprovider tests/test_v189_survey_central_consumer.py tests/test_v189_survey_authority_remediation.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/pytest -p no:cacheprovider tests/test_v189_consumer_catalog_contract.py tests/test_v189_consumer_coverage.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/evidence/survey_projection_adapter.py backend/workbench/services/survey_consumer_service.py tests/test_v189_survey_central_consumer.py tests/test_v189_survey_authority_remediation.py`, `git diff --check`
- Known gates: `Report/HTTP/frontend/browser/provider/cross-process/full-gate/merge/tag/release remain NOT VERIFIED`

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

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary
