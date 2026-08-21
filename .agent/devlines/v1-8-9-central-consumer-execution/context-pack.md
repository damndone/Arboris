# Frozen Context Pack

Line: `v1-8-9-central-consumer-execution`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 Central Consumer Execution Objective

## Objective

Close the next P0/P1 integration gap after runtime bootstrap: make the
server-owned shared Agent/Notebook runtime consume typed host data and
classification inputs and return bounded, evidence-bindable results. The
existing package-local data operations and classification engines remain the
statistical owners; this line adds only the typed host ports and their
declaration-derived runtime joins.

## Required behavior

1. A data-consumer host port may be issued only by the server and may resolve
   opaque snapshot/operation identities to existing typed data-operation
   execution. It must never receive caller filesystem paths or return rows,
   raw frames, or caller-authored evidence.
2. A classification host port may be issued only by the server and may resolve
   an opaque snapshot identity to typed feature/target inputs, execute an
   existing Logistic Regression or Random Forest adapter/protocol, and return
   a bounded result packet containing model/evaluation identities and evidence
   digests. It must fail closed on missing, stale, mismatched, or forged input.
3. Runtime composition must join the exact server-issued ports to the exact
   server-loaded catalog. A missing port keeps that contribution unavailable;
   a forged port, catalog clone, mismatched digest, or extra field is rejected.
4. Agent and Notebook continue to use the same compiler, confirmation store,
   execution admission, and evidence commit path. This line must not create a
   second capability table or a direct HTTP/provider fallback.
5. Tests prove real injected-host execution through compile -> persisted
   proposal -> server confirmation -> execute -> typed evidence receipt, plus
   fail-closed authority, scope, snapshot, stale, and raw-egress boundaries.

## Non-goals

- No new statistical model family, estimator formula, or alternate split/CV
  protocol.
- No frontend, Report renderer, browser acceptance, external provider,
  cross-process, full-gate, merge, push, tag, release, or deployment change.
- No native file-format dependency installation; `.sav/.zsav/.dta` remains an
  explicit optional-dependency boundary.

## Acceptance boundary

Focused package and shared-runtime tests may prove the typed host-port and
same-compiler path. Browser, provider, cross-process, full-repository, and
release evidence remain separate and must be reported as NOT VERIFIED until
run on an exact candidate SHA.

## Boundary
- Affected paths: `backend/workbench/data_operation_manifest.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/app.py`, `tests/test_v189_central_consumer_execution.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_classification_host_port.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_classification_production.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-central-consumer-execution-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-central-consumer-execution.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-central-consumer-execution-handoff.md`
- Allowed paths: `backend/workbench/data_operation_manifest.py`, `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/app.py`, `tests/test_v189_central_consumer_execution.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_classification_host_port.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_classification_production.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-central-consumer-execution-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-central-consumer-execution.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-central-consumer-execution-handoff.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/report_view_model.py`, `frontend/src`, `backend/workbench/engine`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-agent-notebook-runtime-bootstrap`, `v1-8-9-p1-data-consumer-core`, `v1-8-9-p1-classification-ml-core`, `v1-8-9-consumer-projection-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_central_consumer_execution.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_runtime_bootstrap.py tests/test_v189_data_operation_manifest.py tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `focused tests do not prove browser, provider, cross-process, full gate, or release readiness`

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

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

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
