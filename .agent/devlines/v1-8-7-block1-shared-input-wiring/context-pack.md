# Frozen Context Pack

Line: `v1-8-7-block1-shared-input-wiring`
Baseline SHA: `9d5e94717f9f06dbc92955aa8cf3ca26dda37f71`

## Objective
# v1.8.7 块 1 共享入参薄接线 Objective

v1.8.7 块 1。**零行为薄接线**，Integration 性质的机械改动。

A1（设计方差引擎）与 A2（测量级别）都要往 Run API 与 orchestrator 加入参，
因此这两条流不是不相交的工作流。本块先由一次共享提交完成**纯字段透传**，
之后 A1 / A2 才可并行。

**本块不实现任何语义。** 新字段一路透传到 `ctx.artifacts`，
到此为止；没有任何 stage 消费它们，没有任何校验，没有任何行为变化。
消费与校验分别属于块 2 及之后。

## 必须完成

1. 在 `POST /runs` 及其对称入口新增以下 Form 字段，默认空串/空值，全部可选：

   ```
   survey_strata_col        分层变量
   survey_psu_col           初级抽样单元
   survey_fpc_col           有限总体校正
   survey_replicate_weights 数据自带的重复权重列组（JSON 数组）
   survey_replicate_type    brr | jackknife | bootstrap | provided
   survey_lonely_psu        fail | remove | adjust | average | certainty
   survey_weight_frame      cross_sectional | longitudinal
   survey_subpop            子总体表达式
   ```

2. 上述字段沿既有 `sampling_weight` 的同一条路径透传：
   HTTP → `run_service` → `orchestrator` → `ctx.artifacts`，
   使用既有 `_` 前缀约定（如 `_survey_strata_col`）。

3. `measurement_level` 沿既有 `labels` 通道承载（不新增顶层 Form 字段）：
   `labels` JSON 增加可选 `measurement_level` 映射，随既有 labels 一同透传到
   `frame.attrs`。**本块只透传，不校验取值、不影响路由。**

4. 保持 `POST /runs` 与 `/runs/batch` 的**校验对称**（既有约定，v1.6.9 已清过一次债）。

5. CLI（`backend/workbench/cli.py`）同步补齐上述参数，避免重蹈 D3「CLI 缺参数」旧债。

## 明确不做

- **不实现任何语义**：不建设计对象、不算方差、不做 lonely-PSU 处理、
  不推导 degf、不产出 DEFF、不解析子总体表达式。
- **不校验新字段取值**（枚举校验属块 2）。
- 不触碰 `backend/workbench/engine/**`（块 2 的 owned scope）。
- 不触碰前端（A1 的 RunForm 工作在其自己的线内）。
- 不改 `ModelFamilyContract`（块 2/3）。
- 不改既有 `sampling_weight` 的 fail-closed 行为——它在块 2 才解除。
- 不 push / 不建 PR / 不 merge / 不 tag。

## 可证伪验收

- **透传可见**：一次真实 run 传入全部新字段后，`ctx.artifacts` 中出现对应
  `_survey_*` 键且值与传入一致；用测试断言，不靠阅读代码。
- **零行为**：传入新字段的 run 与不传新字段的同一 run，
  产出的 artifact 集合、`models` 块与全部统计数值**逐位一致**。
  这条是本块的核心约束——若两者有任何差异，说明混进了语义。
- **`sampling_weight` 行为不变**：声明 `sampling_weight` 仍然 fail-closed，
  错误码与消息与 baseline `9d5e947` 逐字节一致（解除属块 2）。
- **对称性**：`/runs` 与 `/runs/batch` 对新字段的接受与校验行为一致。
- **CLI 可达**：CLI 能传入全部新参数并到达同一透传路径。
- **`measurement_level` 透传**：`labels` 中携带 `measurement_level` 时进入
  `frame.attrs`，且**不影响 y_type 判定与模型路由**（断言路由结果不变）。
- golden 23 逐位 0-drift（本块不应产生任何漂移；若漂移，先当作设计被违反排查）。
- 后端全量 ≥ 4631 passed，`git diff --check` 干净。

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/services/run_service.py`, `backend/workbench/cli.py`
- Allowed paths: `backend/workbench/__init__.py`, `backend/workbench/api.py`, `backend/workbench/api_errors.py`, `backend/workbench/app.py`, `backend/workbench/artifacts.py`, `backend/workbench/canonical.py`, `backend/workbench/cleaning.py`, `backend/workbench/cli.py`, `backend/workbench/code_execution.py`, `backend/workbench/config.py`, `backend/workbench/control_plane.py`, `backend/workbench/data_operations.py`, `backend/workbench/diagnostic_summary.py`, `backend/workbench/domain.py`, `backend/workbench/evaluator_harness_manifest.py`, `backend/workbench/events.py`, `backend/workbench/exploration_log.py`, `backend/workbench/exports.py`, `backend/workbench/figure_context.py`, `backend/workbench/flags.py`, `backend/workbench/frozen_containment.py`, `backend/workbench/goodman_bacon_ref.py`, `backend/workbench/graph_decision_factory.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_store.py`, `backend/workbench/imputation.py`, `backend/workbench/ingestion.py`, `backend/workbench/merge.py`, `backend/workbench/metadata.py`, `backend/workbench/model_options.py`, `backend/workbench/model_terms.py`, `backend/workbench/prediction.py`, `backend/workbench/profiling.py`, `backend/workbench/projects.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_export.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/router.py`, `backend/workbench/sandbox.py`, `backend/workbench/statistical_exploration.py`, `backend/workbench/statistical_tests.py`, `backend/workbench/term_parser.py`, `backend/workbench/validation.py`, `backend/workbench/variable_roles.py`, `backend/workbench/visualization.py`, `backend/workbench/http`, `backend/workbench/orchestrator`, `backend/workbench/services`, `tests`, `docs/superpowers/plans`
- Protected paths: `backend/workbench/engine`, `backend/workbench/agent`, `frontend`, `scripts/gate.sh`, `tests/golden`, `tests/test_honest_did_adversarial.py`, `tests/test_honest_did_sd_adversarial.py`
- Dependencies: `v1-8-7-a0-release-doc-truth`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests -q`, `git diff --check`
- Known gates: `zero-behavior line: runs with and without the new fields must be bit-identical`, `golden 23 must stay 0-drift; drift means semantics leaked in`, `sampling_weight stays fail-closed in this block`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
