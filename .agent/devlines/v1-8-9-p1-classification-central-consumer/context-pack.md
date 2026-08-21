# Frozen Context Pack

Line: `v1-8-9-p1-classification-central-consumer`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 Classification Central Consumer Objective

## Objective

接通已经持久化并通过分类生产契约校验的 classification evidence，使中央
Agent、Notebook、Report 都从同一个 server-owned classification projection
入口读取结果。此线只负责消费层和 catalog/admission 接线，不重新拟合模型、
不重新计算指标、不降低已有的 artifact/receipt/C0 校验强度。

## Required behavior

- 中央服务必须先解析 server-bound project/run identity，再从 indexed
  classification artifact、receipt 和 server identity 读取结果。
- Agent、Notebook、Report 使用同一个 provider-owned projection adapter；
  只在 consumer presentation 上有差异。
- classification projection 必须保留 `validated`、`degraded`、
  `unavailable` 和阻断原因；缺失、过期、篡改、foreign run、错误 artifact
  identity 必须 fail closed。
- Report 的 classification evidence authority 必须明确为 server-owned，
  不能继续把已经校验过的 classification wrapper 标成 non-authoritative。
- Agent/Notebook 的中央读取入口不得接受 caller-supplied packet、registry、
  provider、model 或 filesystem path；只能接受 server-issued run capability
  或由中央服务解析出的 run identity。
- 本条线只建立共享 central reader；精确 projection-ref 的 catalog coverage
  adapter join 作为后续 C2 单独实现，不能在本条线用 generic consumer
  projection 冒充完成。
- 不能修改分类 estimator、split/CV/holdout/calibration/threshold/SHAP
  语义；不能通过 raw JSON fallback 让未验证结果显示为有效结果。

## Explicit non-goals

- 不新增分类模型族。
- 不实现浏览器、真实 provider、跨进程 authority 或发布流程。
- 不修改 central compiler、workflow runtime 或 Notebook planner。
- 不修改 provider catalog declaration 或前端 renderer registry；这些属于
  后续 C2 接线。

## Acceptance evidence

- TDD RED probes first cover central route authority, shared adapter identity,
  stale/tampered/foreign artifact rejection and no in-memory bypass.
- Central backend tests prove one reader/adapter is used for Agent/Notebook/Report
  and unavailable states remain typed. Catalog coverage remains an explicit
  follow-up gate rather than being counted as complete here.
- Existing package classification production/consumer suites remain green.
- `compileall`, `git diff --check` and formal devline verification/retrospective
  pass. Browser/provider/full/release remain separate claims.

## Boundary
- Affected paths: `backend/workbench/services/classification_consumer_service.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_central_consumer.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-central-consumer-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-central-consumer.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-central-consumer-handoff.md`
- Allowed paths: `backend/workbench/services/classification_consumer_service.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_central_consumer.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-central-consumer-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-central-consumer.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-central-consumer-handoff.md`
- Protected paths: `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/agent/notebook/planning_agent.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`
- Dependencies: `v1-8-9-agent-notebook-runtime-bootstrap`, `v1-8-9-central-evidence-consumer-mount`, `v1-8-9-p1-classification-production`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_central_consumer.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`
- Known gates: `central catalog coverage and frontend renderer registry are a separate C2 line`, `browser/provider/cross-process/full-gate/release remain NOT VERIFIED`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

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

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required
