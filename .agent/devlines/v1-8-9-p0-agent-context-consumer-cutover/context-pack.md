# Frozen Context Pack

Line: `v1-8-9-p0-agent-context-consumer-cutover`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P0 Agent context consumer cutover objective

## Objective

Bring the legacy Agent read-only context consumer suite onto the v1.8.9
server-owned result-artifact contract. Tests that intend to expose verified
model facts must create a real artifact index entry, digest, input identity,
and self-digesting `result_binding` before calling the Agent context tools.
Tests that intentionally exercise malformed, running, missing, or otherwise
unavailable state must assert the typed unavailable/lifecycle projection
instead of expecting a raw `model_results` fallback.

The cutover must preserve the production fail-closed boundary: no caller-owned
JSON, path, project identity, or inferred model result may become citable
evidence. It must not weaken `_verified_model_results`, C0 evidence admission,
or Report/Notebook projections. The goal is to make the existing consumer
suite truthful under the v1.8.9 contract, not to delete coverage or blanket
skip failures.

## Required outcomes

- The previously failing `tests/test_agent_context_tools.py` cases either use
  a server-shaped persisted artifact fixture or explicitly assert the typed
  unavailable/lifecycle state they are designed to cover.
- Verified-result tests prove the indexed path, digest, model identity,
  source-artifact identity, and payload digest are all present; changing any
  one invalidates the projection.
- Existing raw-row redaction and malformed/tampered fail-closed assertions
  remain active.
- No production authority or raw-result fallback is added.

## Scope

Allowed paths:

- `tests/test_agent_context_tools.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-context-consumer-cutover.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-handoff.md`

Protected paths include all production backend/frontend code, existing
formal devline records, root checkout, other worktrees, and unrelated tests.
If a production defect is demonstrated rather than a stale fixture, stop and
request an explicit rescope through `devline_control.py` before editing it.

## Baseline and verification

- Exact baseline: `91ee6a05eab2a1892844c8a3057e1e607359a29e`.
- Focused gate:
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_agent_context_tools.py -q --disable-warnings`.
- Adjacent typed boundary gate:
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_evidence_report_boundary.py -q --disable-warnings`.
- Also run selected-file compile checks and `git diff --check`.
- Browser, external provider, host-authority/full gate, cross-process,
  merge, tag, release, and deployment remain separate `NOT VERIFIED` gates.

## Boundary
- Affected paths: `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-handoff.md`
- Allowed paths: `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-agent-context-consumer-cutover-handoff.md`
- Protected paths: `backend/workbench`, `frontend`, `.agent/devlines`
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_agent_context_tools.py -q --disable-warnings`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_v189_central_evidence_consumer_mount.py tests/test_v189_evidence_report_boundary.py -q --disable-warnings`
- Known gates: `Browser, external provider, host authority/full gate, cross-process, merge, tag, release and deployment remain NOT VERIFIED`

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

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
