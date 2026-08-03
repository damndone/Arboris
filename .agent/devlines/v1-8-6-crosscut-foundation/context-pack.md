# Frozen Context Pack

Line: `v1-8-6-crosscut-foundation`
Baseline SHA: `4d5d75ee7f4228cd53e12f70d88958028709f1cb`

## Objective
# v1.8.6 S0 Cross-cutting Expansion Objective

基于已完成的 predictive-research foundation，先完成可追加的估计器注册面、模型族契约声明、
SampleSpec identity 接线和 legacy prediction 显式化。不得改变既有无权重模型数值。

## 必须完成

1. 把 `CORE_PACK` 的注册与 handler/model-params 构造解耦；新增模型族只追加注册项。
2. 为 `ModelFamilyContract` 增加 `allows_weights` 与 `supported_split_kinds`，未声明能力
   在拟合前 fail-closed。
3. 把 `SampleSpecV1.content_hash()` 接入 run identity、Graph identity 和缓存失效判定；
   FeatureRecipe 结果 identity 不包含 SplitPlan，Evaluation/Prediction identity 必须包含。
4. 旧 `run_prediction_model` 明确标为历史重放 helper，显式声明 shuffle/cross-validation
   语义，不再成为新 run 的隐式入口。

## 可证伪验收

- 既有 golden 23 逐位 0-drift。
- 新模型族只需追加 registry entry 的结构测试通过。
- 未声明权重/split 的模型族稳定拒绝且不产生结果 artifact。
- 同一 SampleSpec 重复 identity 相同；改变 SplitPlan 参数产生新的评估 identity；改变无关
  字段不会错误失效上游变换缓存。
- 旧 helper 的历史重放测试通过，新 run 路径没有调用它。

## Boundary
- Affected paths: `docs/superpowers/plans/2026-08-03-v1.8.6-s0-crosscut-objective.md`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/predictive_research/contracts.py`, `backend/workbench/prediction.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_model.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/lineage/op_spec.py`, `backend/workbench/lineage/incremental.py`, `backend/workbench/lineage/hashing.py`, `tests/predictive_research/test_sample_identity_v186.py`, `tests/test_estimation_registry_v186.py`, `tests/test_workflow_contracts_v186.py`, `tests/test_prediction_models.py`, `tests/test_engine_increment_fork.py`, `tests/test_incremental_dryrun.py`, `tests/test_node_hash.py`
- Allowed paths: `docs/superpowers/plans/2026-08-03-v1.8.6-s0-crosscut-objective.md`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/predictive_research/contracts.py`, `backend/workbench/prediction.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_model.py`, `backend/workbench/predictive_research/persistence.py`, `backend/workbench/lineage/op_spec.py`, `backend/workbench/lineage/incremental.py`, `backend/workbench/lineage/hashing.py`, `tests/predictive_research/test_sample_identity_v186.py`, `tests/test_estimation_registry_v186.py`, `tests/test_workflow_contracts_v186.py`, `tests/test_prediction_models.py`, `tests/test_engine_increment_fork.py`, `tests/test_incremental_dryrun.py`, `tests/test_node_hash.py`
- Protected paths: none
- Dependencies: `baseline=4d5d75e`, `existing integration line rescope manifest=45c658c8e8d7d6a77c26d614c80d07c1a4f7c1848c8f20a3b666508c78ce0d97`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/predictive_research/test_sample_identity_v186.py tests/test_estimation_registry_v186.py tests/test_workflow_contracts_v186.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_increment_fork.py tests/test_incremental_dryrun.py tests/test_node_hash.py`
- Known gates: `TDD red evidence required before production code`, `golden 23 must remain 0-drift`, `no push PR merge or tag without explicit authorization`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
