# Frozen Context Pack

Line: `v1-8-9-consumer-projection-core`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 Consumer Projection Core Objective

## Objective

Build the bounded, non-recomputing evidence-consumer layer for Agent,
Notebook, Report and UI. Every consumer must select facts from a persisted,
server-bound EvidenceEnvelope/artifact identity; it must never recalculate
statistics, accept client-supplied facts, expose unrestricted raw payloads or
turn unavailable evidence into zeros or empty success states.

## Required behavior

- Resolve a committed EvidenceEnvelope and its artifact/data snapshot identity
  before projecting any facts.
- Define a declarative, versioned consumer projection registry with consumer ID,
  accepted evidence/envelope refs, selected fact kinds, redaction policy,
  budget, ordering and renderer key.
- Agent and Notebook projections are bounded and sensitivity-aware; remote
  contexts use the existing C0 egress gateway and produce an auditable receipt.
- Report/UI projections preserve fact IDs, values, units, intervals, caveats,
  availability and validation provenance while visibly distinguishing
  `UNAVAILABLE`, `DEGRADED` and `BLOCKED`.
- Unknown schema, sensitivity, renderer, consumer or evidence identity fails
  closed. No generic raw-dict fallback is allowed.
- Coverage is derived from provider and consumer declarations, versioned at the
  raw-key level, and reports direct/composable/unreachable/exempt paths without
  aggregate-count-only claims.

## Scope

Owned files are exactly those listed in the formal Work Order
`docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`.
Central compiler, workflow runtime, central registry, Notebook planner, Report
mount and section registry are protected and must not be modified in this
line.

## Baseline and gates

- Exact baseline: `91ee6a05eab2a1892844c8a3057e1e607359a29e`.
- Dependency: the closed P0 model-branch Resume line and existing Contract
  Lock/Evidence Core/Agent Compiler contracts.
- Required: TDD RED/GREEN, persisted-envelope mutation probe, sensitivity and
  egress adversarial probes, exact identity/coverage tests, frontend renderer
  tests/typecheck, compileall, diff check, formal retrospective and verify.
- Browser, real provider, production host, full repository gate, merge, push,
  tag and release remain explicit follow-up gates.

## Boundary
- Affected paths: `tests/test_v189_evidence_report_boundary.py`
- Allowed paths: `tests/test_v189_evidence_report_boundary.py`
- Protected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/notebook/planning_agent.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `tests/test_workflow_runtime.py`, `tests/test_notebook_planning_agent.py`
- Dependencies: `v1-8-9-p0-model-branch-resume`, `v1-8-9-contract-lock`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_consumer_projection.py ../tests/test_v189_consumer_coverage.py -q`, `cd frontend && npm test -- --run src/report/FamilyEvidence.test.tsx && npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench`, `git diff --check`
- Known gates: `This lane does not prove central production mounts, browser acceptance, real provider benchmarks, host identity configuration, full repository gate, release, merge, push or tag.`

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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
