# Frozen Context Pack

Line: `v1-8-9-agent-notebook-cutover`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 Agent / Notebook Cutover Objective

## Objective

把 Agent 与 Notebook 的自然语言入口接入同一个服务端能力目录、编译器、
确认边界、执行准入和结果证据链。自然语言只能提出受约束的
`AnalysisIntentV1`，不能直接生成 operation、provider、contract、事实或
执行权限。两条入口必须使用同一套语义计划和安全边界，只在交互与持久化
投影上保持差异。

目标链路为：

`自然语言 -> 澄清 -> typed intent -> server compilation record -> PlanDiff/preview -> confirmation -> ExecutionAdmission -> execution -> immutable EvidenceEnvelope -> typed consumer projections`。

## Baseline and upstream authority

- Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Branch: `workbench-v1.8.9-wave-a`
- Exact baseline: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Plan lock: `f3836408cf15c3e7380823e5c1b303b4467c7aec`
- C0 catalog digest recorded by Contract Lock: `cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40`
- Evidence envelope contract digest: `a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835`
- Evidence persistence contract digest: `44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2`
- Planning/execution-admission contract digest: `8459bbfbf01400f3411245d5d1945ae36a300a55c3a096efbb74ea3705ab349a`
- Context-egress contract digest: `892d6f672a9de9fae50dfe2c029a97e00dc24fede045df6ca9cf35e3c6b10817`

The Data Consumer, Classification ML, Consumer Projection and provider-catalog
integration lines are present as package-local contributions in this dirty
integration worktree. The three historical P0 C1 implementation handoffs named
by the program are not materialized here; this line must consume only their
locked public seams and must keep any C1/runtime claim explicitly separate.

## Required outcome

1. Provider declarations, frozen contract refs, runtime contributions and UI
   renderers form one deterministic, fail-closed catalog. JSON may contain only
   opaque executor IDs; actual callables are server-composed and registered.
2. Agent and Notebook submit the same typed intent to one public compiler and
   receive either typed clarifications or a persisted `CompilationRecordV1`.
3. Execution accepts only a server-bound record ID and a server-issued,
   actor/session/project-bound confirmation. Client-shaped compiled objects,
   stale records, cross-session replay, changed data/provider/contract digests,
   unknown effects and unsafe egress are rejected before side effects.
4. Completion cannot precede immutable evidence persistence. Result consumers
   and Report/UI render only persisted typed projections; they do not calculate
   or fabricate facts.
5. Data Consumer operations and Classification ML operations are exposed by
   declaration-derived discovery. No central family/prefix/model switch is
   added for these or future providers.
6. Notebook recipes persist intent, contract/provider refs, compilation record,
   diff, confirmation, operation/artifact/evidence refs and rerun prerequisites;
   editing or changing the bound snapshot invalidates old authority.

## Safety and AI-native boundary

- LLMs/agents may normalize language, propose clarifying questions and explain
  persisted results, but server-owned schemas and registries decide capability,
  contracts, permissions, sensitivity, resource/effect and evidence.
- Missing target, structure/time/entity, availability, positive class, metric,
  decision cost, sensitivity or resource choice is a typed clarification or
  block; no hidden default is invented.
- Prompt injection, unsupported operations, conflicting constraints, raw provider
  clients, direct module imports, arbitrary code strings and prompt-requested
  egress bypasses are negative-path tests, not fallback behavior.
- Remote context is receipt-backed, sensitivity-bounded and budgeted. Unknown
  sensitivity/schema/renderer/policy is blocked.
- Read-only preview may be prepared automatically only when declared safe;
  execution always observes the declared confirmation/effect policy.

## Acceptance boundary

The line must provide focused backend/frontend tests, typecheck, compileall,
diff check, formal event verification and a generated retrospective. Shadow
planning must classify exact matches, justified changes, typed clarifications
and regressions with zero silent capability loss, authority broadening or
consumer fact divergence.

Browser-visible acceptance, external provider calls, host full gate, release,
merge, push and tag remain separate evidence and must be reported as
`NOT VERIFIED` unless independently run.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/trusted_executor_registry.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/contracts/agent/execution_admission.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage/detail/sections/sectionRegistry.test.ts`, `frontend/src/report/ReportView.tsx`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_notebook_planning_agent.py`, `tests/test_agent_operation_lifecycle.py`, `frontend/src/report/ReportView.v189.test.tsx`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-agent-notebook-cutover-handoff.md`
- Allowed paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/trusted_executor_registry.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/contracts/agent/execution_admission.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage/detail/sections/sectionRegistry.test.ts`, `frontend/src/report/ReportView.tsx`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_notebook_planning_agent.py`, `tests/test_agent_operation_lifecycle.py`, `frontend/src/report/ReportView.v189.test.tsx`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-agent-notebook-cutover.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-agent-notebook-cutover-handoff.md`
- Protected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/data_operations.py`, `backend/workbench/evidence`, `backend/workbench/predictive_research`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-workflow-truth-core`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-p1-data-consumer-core`, `v1-8-9-p1-classification-ml-core`, `v1-8-9-consumer-projection-core`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_notebook_cutover.py ../tests/test_notebook_planning_agent.py ../tests/test_agent_operation_lifecycle.py -q`, `cd frontend && npm test -- --run src/report/ReportView.v189.test.tsx src/workbench/registry/sectionRegistry.v189.test.ts && npm run typecheck`
- Known gates: `cutover component tests do not prove browser, provider, full gate or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-notebook-planning-resilience (2026-08-02T03:50:30.000Z)

Completed formal devline v1-8-5-notebook-planning-resilience; final_state=COMPLETED; failure_lesson_keys=abort-signal-races-provider-stream, complete-nonobject-tool-json-remains-retryable, partial-tool-progress-prevents-retry
