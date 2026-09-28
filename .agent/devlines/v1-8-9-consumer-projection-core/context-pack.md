# Frozen Context Pack

Line: `v1-8-9-consumer-projection-core`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 Consumer Projection Core Objective

## Objective

Implement a bounded, schema-versioned projection layer for Results, Agent,
Notebook, Report and UI. The only statistical source is a server-persisted
`EvidenceEnvelopeV1` binding. Projection code may select, redact, order and
render persisted facts, but must never recompute estimates, infer missing
values, invoke a model/statistical routine, or promote an availability or
validation state.

Every consumer projection must retain the same artifact, envelope and fact
identity. Missing, unsupported, incomplete or restricted facts remain
`UNAVAILABLE`, `DEGRADED` or `BLOCKED`. Remote/provider egress is bounded,
sensitivity-aware and receipt-backed; unknown sensitivity and unknown schema,
renderer or policy fail closed.

## Exact baseline and upstream authority

- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Branch: `workbench-v1.8.9-wave-a`
- Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Contract Lock C0 handoff: `docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md`
- C0 catalog digest: `cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40`
- Evidence envelope contract digest: `a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835`
- Evidence persistence contract digest: `44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2`
- Context egress contract digest: `892d6f672a9de9fae50dfe2c029a97e00dc24fede045df6ca9cf35e3c6b10817`

The three P0 C1 implementation handoffs named by the implementation plan are
not present in this worktree at the baseline. This line therefore consumes
only their locked public contract seam and must not recreate their private
implementation. Real C1 integration remains a separate acceptance boundary.

## In-scope paths

- `backend/workbench/evidence/consumer_adapters.py`
- `backend/workbench/evidence/coverage.py`
- `backend/workbench/services/results_service.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/report_view_model.py`
- `backend/workbench/providers/builtin/consumer_projection.json`
- `frontend/src/report/FamilyEvidence.tsx`
- `frontend/src/report/FamilyEvidence.test.tsx`
- `frontend/src/report/reportEvidence.ts`
- `frontend/src/notebook/evidenceContracts.ts`
- `tests/test_v189_consumer_projection.py`
- `tests/test_v189_consumer_coverage.py`
- this objective, Work Order and completion handoff

## Protected boundaries

Do not modify workflow runtime, planning compiler, central capability or
workflow adapter registries, Notebook planner, ReportView, sectionRegistry
mounts, the completed P1 data-consumer files, statistical implementations,
provider execution, or any release/integration artifact outside this line.
Do not add an LLM inference path, generic raw-dict fallback, client fact
admission, zero/empty fallback, or raw-row remote egress.

## Required evidence

- TDD red-first tests for persisted read admission, identity/value parity,
  fact-level status/provenance preservation, sensitivity redaction, egress
  receipts, bounded budgets, extension discovery and declaration-derived
  coverage.
- Focused backend projection and coverage suites.
- Focused `FamilyEvidence` frontend tests and frontend typecheck.
- `git diff --check`, formal event verification and CLI-generated retrospective.
- Handoff must separate implementation, focused tests, formal process evidence,
  and `NOT VERIFIED` C1 integration, browser, production mount, provider,
  full-gate and release evidence.

## Boundary
- Affected paths: `backend/workbench/evidence/consumer_adapters.py`, `backend/workbench/evidence/coverage.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/report_view_model.py`, `backend/workbench/providers/builtin/consumer_projection.json`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/reportEvidence.ts`, `frontend/src/notebook/evidenceContracts.ts`, `tests/test_v189_consumer_projection.py`, `tests/test_v189_consumer_coverage.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-consumer-projection-core-handoff.md`
- Allowed paths: `backend/workbench/evidence/consumer_adapters.py`, `backend/workbench/evidence/coverage.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/report_view_model.py`, `backend/workbench/providers/builtin/consumer_projection.json`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/reportEvidence.ts`, `frontend/src/notebook/evidenceContracts.ts`, `tests/test_v189_consumer_projection.py`, `tests/test_v189_consumer_coverage.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`, `docs/superpowers/handoff/2026-08-15-v1.8.9-consumer-projection-core-handoff.md`
- Protected paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/notebook/planning_agent.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_consumer_projection.py ../tests/test_v189_consumer_coverage.py -q`, `cd frontend && npm test -- --run src/report/FamilyEvidence.test.tsx && npm run typecheck`
- Known gates: `consumer projections do not prove production mounts, browser, provider, full gate or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
