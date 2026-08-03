# Frozen Context Pack

Line: `v1-8-6-data-management`
Baseline SHA: `7f27613432a34ec216edcce3a524f5674e8aa441`

## Objective
# v1.8.6 S5 Data Management Objective

把已有 typed FeatureRecipe 与数据操作内核接入真实 API/UI/Graph，并提供可回溯、可拒绝的
merge/append/reshape/subset 工作流。

## 必须完成

- FeatureRecipe 五个受限算子可从用户入口配置，产出 typed artifact、Graph 节点和 lineage。
- merge/append 对键冲突、多对多、异常行数膨胀 fail-closed。
- reshape 长宽转换显式记录输入、参数、行列变化和下游 identity 失效。
- subset 作为可追溯操作，不把临时 DataFrame 变成不可见状态。

## 可证伪验收

- 真实 UI/API 链路：上传两表 → merge → reshape → derive → 建模，Graph 全链可见可回溯。
- merge 膨胀 fixture 被拒绝且给出可执行下一步。
- FeatureRecipe 节点点击不显示 `missing_node_hash`，并能下载/查看 typed payload。

## Boundary
- Affected paths: `backend/workbench/data_operations.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/predictive_research/contracts.py`, `backend/workbench/predictive_research/feature_recipe.py`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/lineage/detail/sections/DataColumnCastSection.tsx`, `frontend/src/lineage/detail/sections/DataColumnCastSection.test.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `tests/test_data_operations.py`, `tests/test_data_operation_routes.py`, `tests/test_feature_recipe_v186.py`
- Allowed paths: `backend/workbench/data_operations.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/predictive_research/contracts.py`, `backend/workbench/predictive_research/feature_recipe.py`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/lineage/detail/sections/DataColumnCastSection.tsx`, `frontend/src/lineage/detail/sections/DataColumnCastSection.test.tsx`, `frontend/src/workbench/registry/sectionRegistry.ts`, `tests/test_data_operations.py`, `tests/test_data_operation_routes.py`, `tests/test_feature_recipe_v186.py`
- Protected paths: none
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_data_operations.py tests/test_data_operation_routes.py tests/test_feature_recipe_v186.py -q`
- Known gates: `npm run typecheck`, `bash scripts/gate.sh`

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

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
