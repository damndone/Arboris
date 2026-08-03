# Frozen Context Pack

Line: `v1-8-6-weights-crosscut`
Baseline SHA: `bacce13e884fe8fe309044ee395d40fd428d733f`

## Objective
# v1.8.6 S3 Weights Cross-cut Objective

在 S0 contract 基础上，把 sampling/analysis/frequency 三种权重语义贯通 API、service、
workflow contract、OLS/预测协议和可选 UI 字段；不支持的模型族必须拒绝。

## 必须完成

1. API 请求、service、stage、typed packet 均保留三种权重字段，不互相替代。
2. `frequency_weight` 与 `analysis_weight` 接入 OLS；`sampling_weight` 在分层/PSU 语义未
   完整实现前 fail-closed。
3. strata/PSU 复用既有 cluster 通道；模型族通过 `allows_weights` 声明准入。
4. 预测路径继续保留正 frequency weight 的 sample_weight 语义，并从真实 API 可达。

## 可证伪验收

- HTTP/API 真实 Run 传入 frequency weight 后，prediction/OLS packet 记录列名和 executed 状态，
  且结果与不加权结果不同。
- 全 1 frequency weight 与不传权重逐位一致。
- 未声明权重的模型族返回稳定错误码且不写结果 artifact。
- sampling_weight 的拒绝路径和下一步说明可见；UI 不伪装为已支持。

## Boundary
- Affected paths: `docs/superpowers/plans/2026-08-03-v1.8.6-weights-crosscut-objective.md`, `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `backend/workbench/prediction.py`, `backend/workbench/predictive_research/prediction_protocol.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/econometrics/runner.py`, `frontend/src/api.ts`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `tests/test_api_run_params.py`, `tests/test_workflow_contracts_v186.py`, `tests/predictive_research/test_prediction_entrypoint_v186.py`, `tests/predictive_research/test_prediction_protocol_v186.py`, `tests/test_ols_weights_v186.py`
- Allowed paths: `docs/superpowers/plans/2026-08-03-v1.8.6-weights-crosscut-objective.md`, `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `backend/workbench/predictive_research/prediction_protocol.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/econometrics/runner.py`, `frontend/src/api.ts`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `tests/test_api_run_params.py`, `tests/test_workflow_contracts_v186.py`, `tests/predictive_research/test_prediction_entrypoint_v186.py`, `tests/predictive_research/test_prediction_protocol_v186.py`, `tests/test_ols_weights_v186.py`
- Protected paths: none
- Dependencies: `baseline-bacce13`, `S0-contract-admission-and-prediction-frequency-kernel-present`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api_run_params.py tests/predictive_research/test_prediction_entrypoint_v186.py tests/predictive_research/test_prediction_protocol_v186.py -q`
- Known gates: `TDD-red-before-API-weight-code`, `OLS-and-prediction-preserve-unweighted-values`, `sampling_weight-remains-fail-closed`, `no-push-PR-merge-or-tag-without-authorization`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary
