# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-projection-readers`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 P1 Data Consumer Projection Readers Objective

## Objective

Close the remaining central data-consumer read boundary. Agent, Notebook, and
Report must consume one server-owned, scope-bound projection of committed data
operation evidence. The readers must not accept a caller-owned project path,
dataframe, raw packet, or alternate registry, and they must return an explicit
unavailable projection for missing, stale, malformed, foreign, or ambiguous
durable state.

## Success criteria

1. A server-only opaque run capability can be minted only from a resolved
   project/run scope and carries no serializable path or raw data.
2. One central reader resolves committed data `OperationRecord` output ports
   and produces a bounded, deterministic projection with record, operation,
   artifact identity, evidence digest, catalog identity, and lineage facts.
3. Agent and Notebook wrappers accept only the server capability and delegate
   to the same central reader; path/raw/forged capability inputs fail closed.
4. The Report run response includes the same server-owned data projection and
   receipt when the request identity is admitted; it never falls back to raw
   model/data files.
5. Tests prove Agent/Notebook/Report projections share the same digest and
   reject foreign scope, stale catalog, incomplete output, ambiguity, raw
   payloads, and forged capabilities.

## Non-goals

- Do not execute a new data operation in this line; execution remains behind
  the existing preview/confirmation/OperationRecord lifecycle.
- Do not expose dataframe rows, filesystem paths, arbitrary options, or raw
  evidence payloads through a consumer projection.
- Do not weaken legacy compatibility tests by treating path-derived input as
  authoritative.
- Do not claim browser, external-provider, cross-process, full-host, or
  release acceptance from focused tests alone.

## Boundary
- Affected paths: `backend/workbench/services/data_consumer_projection_service.py`, `backend/workbench/services/data_consumer_host_resolver.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/http/data_operation_routes.py`, `tests/test_v189_data_consumer_projection.py`, `tests/test_v189_central_evidence_consumer_mount.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-projection-readers-handoff.md`
- Allowed paths: `backend/workbench/services/data_consumer_projection_service.py`, `backend/workbench/services/data_consumer_host_resolver.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/http/data_operation_routes.py`, `tests/test_v189_data_consumer_projection.py`, `tests/test_v189_central_evidence_consumer_mount.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-projection-readers-handoff.md`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider tests/test_v189_data_consumer_projection.py tests/test_v189_data_host_resolver.py tests/test_v189_data_host_port.py tests/test_v189_consumer_catalog_contract.py tests/test_v189_consumer_coverage.py tests/test_v189_agent_notebook_runtime_bootstrap.py -q --disable-warnings`
- Known gates: `browser acceptance not verified`, `external provider acceptance not verified`, `cross-process authority not verified`, `full host and release acceptance not verified`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth
