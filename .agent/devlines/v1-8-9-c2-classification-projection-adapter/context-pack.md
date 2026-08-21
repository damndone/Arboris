# Frozen Context Pack

Line: `v1-8-9-c2-classification-projection-adapter`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 C2 Classification Projection Adapter Objective

## Objective

把 classification provider catalog 中声明的 Agent、Notebook、Report
`projection_ref`、policy 和 renderer 与实际消费适配器做精确的
server-owned join，并让 Report 优先读取中央 classification projection，
不再把原始 artifact 作为 Report 的结果来源。此线只做消费层、catalog
绑定和渲染注册，不重新拟合模型、不重新计算指标、不改变已有的
artifact/receipt/C0 校验。

## Required behavior

- projection adapter 必须按 `(provider_id, exposure_path, consumer_id)` 精确
  解析 catalog 声明；不能按 consumer 名称、renderer 名称或任意 caller
  supplied projection ref 猜测。
- classification 的 projection、policy、renderer、evidence contract 和
  exposure path 必须来自同一份 server-owned catalog，并验证 ref identity、
  digest、预算、敏感度和 coverage 状态。
- Agent、Notebook、Report 的中央 classification projection 必须携带已绑定
  的 projection identity；缺失、错配、篡改或未声明时 fail closed，并保留
  `validated`、`degraded`、`unavailable` 与阻断原因。
- Report renderer 只能从闭合的 renderer registry 解析声明，不允许把未知
  renderer ref 当作 React 组件，也不能回退到 raw JSON。
- Report 使用 server-owned classification projection 展示已验证的任务、
  split、metrics、calibration、comparison、explanations、stability、shift
  和 holdout 边界；旧 artifact 下载路径只能作为诊断/兼容路径，不得成为
  Report 结果 authority。
- 通用 numeric evidence projection 的现有消费行为必须保持兼容；新的
  provider-scoped registry 必须支持未来模型族以同样方式接入，不能写成
  classification 专用的死流程。

## Explicit non-goals

- 不修改分类 estimator、split/CV/holdout/calibration/threshold/SHAP 语义。
- 不新增模型族，不扩展复杂抽样、SEM、survival 或其他 P2 模型。
- 不实现浏览器、真实 provider、跨进程 authority、发布、merge、push、tag。
- 不把 central projection 伪装成 generic numeric envelope，也不把未验证
  的 artifact 重新提升为可引用证据。

## Acceptance evidence

- TDD RED probes first cover exact provider/path/consumer joins, wrong ref,
  wrong renderer, missing declaration, forged catalog and unavailable states.
- Backend tests prove central classification Agent/Notebook/Report projections
  carry the catalog-bound identity and coverage reports no longer confuse a
  provider-specific projection with the generic consumer projection.
- Frontend tests prove Report consumes the server projection through the closed
  renderer registry, rejects unknown/mismatched identities, and never renders
  raw classification JSON.
- Existing classification central/production/consumer suites, compileall,
  frontend tests and diff check pass. Browser/provider/full/release remain
  separate claims until independently verified.

## Boundary
- Affected paths: `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_classification_central_consumer.py`
- Allowed paths: `backend/workbench/predictive_research/persistence.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_classification_central_consumer.py`
- Protected paths: `backend/workbench/predictive_research/classification_adapters.py`, `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/plan_compiler.py`, `backend/workbench/providers/builtin`, `backend/workbench/contracts/common/provider.py`, `frontend/src/notebook`, `frontend/src/agent`
- Dependencies: `v1-8-9-p1-classification-central-consumer`, `v1-8-9-consumer-catalog-contract`, `v1-8-9-provider-projection-identity`, `v1-8-9-central-evidence-consumer-mount`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_projection_adapter.py tests/test_v189_consumer_coverage.py tests/test_v189_provider_projection_identity.py -q`, `cd frontend && npm test -- --runInBand frontend/src/report/ReportClassificationProjection.v189.test.tsx`
- Known gates: `browser_visible_acceptance`, `real_provider_acceptance`, `cross_process_authority`, `full_repository_gate`, `release_readiness`

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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
