# Frozen Context Pack

Line: `v1-8-6-consumer-entries`
Baseline SHA: `b2c8018f3cad5229b8cb3306969e1afe95b90425`

## Objective
# v1.8.6 Consumer Entries Objective

在已验证的 v1.8.6 模型族提交 `b2c8018` 上，补齐统计消费链路的两个用户入口边界：

1. 普通 `Run` UI 能配置四个 v1.8.6 模型族的 `model_options`，并将其送入现有 API；
2. 用户可通过 POST `/runs` 的声明字段提供变量/值标签，标签持久化并贯通 Table 1、报告、
   XLSX 与图形轴；未声明时继续使用列名 fallback，并显式记录 fallback 来源。

不改变既有估计器数值、统计检验算法、FeatureRecipe 语义或发布状态。

## 可证伪验收

- 普通 Run UI 选择 ordinal/multinomial/survival/quantile 时显示对应配置，提交的
  `FormData` 含 `model_options`；生存模型缺 event 列在服务端结构化拒绝。
- `/runs` 接收严格 JSON `labels`，错误结构拒绝；成功运行的 `run_inputs`、Table 1、
  HTML/XLSX 报告和至少一张图形的轴/标题读取同一声明标签。
- 未声明标签的报告仍可生成，且 `label_source=column_name_fallback`。
- 既有前端 API/Run/报告/回归测试、编译和 `git diff --check` 通过；Formal FMS verify 通过。

## 边界

- 不解析 Stata/R 外部标签文件；本线只交付显式 JSON 声明。
- 不把标签用于模型列名、Graph identity 或数值计算。
- 不 push、PR、merge、tag 或发布。

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/engine/stages/source.py`, `backend/workbench/engine/stages/cleaning.py`, `backend/workbench/visualization.py`, `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/templates/report.html.j2`, `frontend/src/api.ts`, `frontend/src/runForm/RunForm.tsx`, `frontend/src/runForm/V186ModelControls.tsx`, `frontend/src/runForm/RunForm.test.tsx`, `frontend/src/capabilities/types.ts`, `tests/test_api_run_params.py`, `tests/test_orchestrator_e2e.py`, `tests/test_reporting_exports.py`, `tests/test_labels_v186.py`, `docs/superpowers/plans/2026-08-03-v1.8.6-consumer-entries-objective.md`, `docs/releases/v1.8.6-release-notes.md`, `backend/workbench/agent/notebook/vocabulary.py`, `tests/test_lmm_extension_seams.py`, `tests/test_notebook_routes.py`, `tests/test_recording_node_hash.py`, `tests/golden/binary_logit.json`, `tests/golden/count_poisson.json`, `tests/golden/panel.json`, `tests/golden/explicit_logit.json`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/engine/stages/source.py`, `backend/workbench/engine/stages/cleaning.py`, `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/templates/report.html.j2`, `frontend/src/api.ts`, `frontend/src/runForm/RunForm.tsx`, `frontend/src/runForm/V186ModelControls.tsx`, `frontend/src/runForm/RunForm.test.tsx`, `frontend/src/capabilities/types.ts`, `tests/test_api_run_params.py`, `tests/test_orchestrator_e2e.py`, `tests/test_reporting_exports.py`, `tests/test_labels_v186.py`, `docs/superpowers/plans/2026-08-03-v1.8.6-consumer-entries-objective.md`, `docs/releases/v1.8.6-release-notes.md`, `backend/workbench/agent/notebook/vocabulary.py`, `tests/test_lmm_extension_seams.py`, `tests/test_notebook_routes.py`, `tests/test_recording_node_hash.py`, `tests/golden/binary_logit.json`, `tests/golden/count_poisson.json`, `tests/golden/panel.json`, `tests/golden/explicit_logit.json`
- Protected paths: none
- Dependencies: none
- Tests: none
- Known gates: none

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
