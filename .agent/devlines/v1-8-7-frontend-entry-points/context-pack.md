# Frozen Context Pack

Line: `v1-8-7-frontend-entry-points`
Baseline SHA: `9d5e94717f9f06dbc92955aa8cf3ca26dda37f71`

## Objective
# v1.8.7 前端入口 Objective

后端已交付的两块能力目前**界面上点不到**：复杂抽样设计的八个声明字段，
以及 ANOVA/ANCOVA 的选项。两者的后端与 `/capabilities` 都已贯通，
但 RunForm 没有对应控件，只能经 API/CLI 使用。

按 §4.2，「内核写好、用户碰不到」正是本版要消灭的形态。本线补入口。

## 审计发现（2026-08-06 实测）

- `frontend/src/runForm/RunForm.tsx` 1023 行，按族硬编码分支：
  `modelType === "iv_2sls"` / `"did"` / `"cs_did"` / `"sa_did"` / `"dcdh"` /
  `"panel_ols"` / `"linear_mixed_effects"` / `"time_series.arma_garch"`，
  以及 `V186ModelControls.tsx` 里硬编码的 `V186_MODEL_TYPES` 数组
  与 `defaultV186ModelOptions` 的 switch。
- `frontend/src/api.ts:582` 已有 `samplingWeight` 通道；survey 设计八字段缺失。

**这是枚举矩阵在前端的形态**，与块 2/3、P0 在后端拆掉的是同一个病。
但把前端改成 capability 驱动远超「补入口」，本线不做，记为 GAP。

## 必须完成

1. `SurveyDesignControls` —— 八个设计字段的控件：
   `survey_strata_col` / `survey_psu_col` / `survey_fpc_col` /
   `survey_replicate_weights` / `survey_replicate_type` /
   `survey_lonely_psu` / `survey_weight_frame` / `survey_subpop`。
   取值范围从 `/capabilities` 的 `survey_design` 读取，**不在前端硬编码**
   （后端已发布 `replicate_types` 与 `lonely_psu_policies`）。
2. `AnovaControls` —— ANOVA/ANCOVA 选项：平方和类型、因子、交互项、事后检验。
   **平方和类型必须是用户显式选择，不得预设默认值**——这是后端 fail-closed 的前端对应面，
   界面上悄悄选一个会让后端的强制声明失去意义。
3. 两者接入 `RunForm` 与 `api.ts`，字段随 run 提交。
4. 前端测试覆盖：控件渲染、取值来自 capabilities、提交负载正确。

## 明确不做

- 不把 RunForm 改成 capability 驱动（记 GAP，单独立项）。
- 不动既有族的控件。
- 不做真机验收（本线之后单独做）。
- 不 push / 不建 PR / 不 merge / 不 tag。

## 可证伪验收

- 选中一个接受抽样权重的模型族时，survey 设计控件出现；其余族不出现。
- `replicate_type` 与 `lonely_psu` 的可选值**来自 `/capabilities`**：
  一个测试用 mock 的 capabilities 改变可选集，断言控件跟着变
  （硬编码则该测试红）。
- ANOVA 的平方和类型**初始为空**，未选择时提交按钮不可用或提交被拒；
  一个测试断言不存在预设默认值。
- 一次提交的 FormData 中出现全部已填的 survey 字段与 ANOVA `model_options`。
- 既有 RunForm 测试全绿，前端全量 ≥ 1634 tests，`tsc --noEmit` 通过。

## Boundary
- Affected paths: `frontend/src/runForm/RunForm.tsx`, `frontend/src/api.ts`
- Allowed paths: `backend/workbench/__init__.py`, `backend/workbench/api.py`, `backend/workbench/api_errors.py`, `backend/workbench/app.py`, `backend/workbench/artifacts.py`, `backend/workbench/canonical.py`, `backend/workbench/cleaning.py`, `backend/workbench/cli.py`, `backend/workbench/code_execution.py`, `backend/workbench/config.py`, `backend/workbench/control_plane.py`, `backend/workbench/data_operations.py`, `backend/workbench/diagnostic_summary.py`, `backend/workbench/domain.py`, `backend/workbench/evaluator_harness_manifest.py`, `backend/workbench/events.py`, `backend/workbench/exploration_log.py`, `backend/workbench/exports.py`, `backend/workbench/figure_context.py`, `backend/workbench/flags.py`, `backend/workbench/frozen_containment.py`, `backend/workbench/goodman_bacon_ref.py`, `backend/workbench/graph_decision_factory.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_store.py`, `backend/workbench/imputation.py`, `backend/workbench/ingestion.py`, `backend/workbench/merge.py`, `backend/workbench/metadata.py`, `backend/workbench/model_options.py`, `backend/workbench/model_terms.py`, `backend/workbench/prediction.py`, `backend/workbench/profiling.py`, `backend/workbench/projects.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_export.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/router.py`, `backend/workbench/sandbox.py`, `backend/workbench/statistical_exploration.py`, `backend/workbench/statistical_tests.py`, `backend/workbench/term_parser.py`, `backend/workbench/validation.py`, `backend/workbench/variable_roles.py`, `backend/workbench/visualization.py`, `frontend/src`, `tests`, `docs/superpowers/plans`
- Protected paths: `scripts/gate.sh`, `tests/golden`, `tests/test_honest_did_adversarial.py`, `tests/test_honest_did_sd_adversarial.py`, `backend/workbench/survey`, `backend/workbench/contracts`
- Dependencies: `v1-8-7-p0-unified-result-contract`
- Tests: `cd frontend && npm run test -- --run`, `cd frontend && npx tsc --noEmit`
- Known gates: `option sets must come from /capabilities, never hard-coded in the form`, `the sums-of-squares type must have no preset default; a silent UI choice defeats the backend refusal`, `RunForm stays per-family branching in this line; capability-driven rendering is a separate scope`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
