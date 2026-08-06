# Frozen Context Pack

Line: `v1-8-7-p0-unified-result-contract`
Baseline SHA: `9d5e94717f9f06dbc92955aa8cf3ca26dda37f71`

## Objective
# v1.8.7 P0 统一结果契约 Objective

转向后的第一条线。survey 其余族（有序 / 多项 / Cox / 分位数 / IV / 面板 / DID）
与权重调整顺延，见设计文档 §7 的重排。

## 审计发现（2026-08-06 实测，非转述）

**① 结果契约每族一份，共有核心已存在但没被抽出来。**

`backend/workbench/contracts/model/` 下 10 个文件。三个回归型结果契约
（`OrdinalResultContract` / `MultinomialResultContract` / `QuantileRegressionResultContract`）
各 14 个字段，其中 **8 个逐字相同**：

```
contract  schema_version  model_id  model_type  engine  nobs  coefficients  validation
```

`_require_common()` 已经存在，但**只校验其中 2 个**（`contract`、`model_type`），
其余 6 个各族自行重复声明。

`ETSResultContract`（16 字段）与 `SurvivalEvidenceContract`（13 字段）是**真正不同的形状**
——ETS 没有 `coefficients`，survival 是证据包而非系数包。它们不该被硬塞进同一个信封。

**② 边际效应只覆盖两个族。** 实测只有 `ordinal_logit` 与 `multinomial_logit` 产出
`marginal_effects`。**`logit` / `probit` / `poisson` 完全没有。**

这三个是最常用的二元/计数族，而它们的系数是对数几率/对数率——**没有人直接解释对数几率**。
SPSS 的 PLUM/GENLIN 与 Stata 的 `margins` 都把边际效应当默认输出。
不给边际效应，等于把最后一步翻译留给用户手算。

**③ Agent 证据投影按族分支 5 处**（`agent/context_tools.py:3214–3269`）：
`ordinal_logit` / `multinomial_logit` / `survival_cox` / `quantile_regression` / `time_series.ets`
各一个 `if`。每加一族就要在这里加一个分支——枚举矩阵在消费者侧的形态。

（`report_view_model.py` 的按族分支为 **0 处**，报告侧已经是统一的，本线不动它。）

## 必须完成

1. **抽出统一结果信封**：把 8 个共有字段抽成一个**声明的 result shape**
   （复用块 2 建立的 `register_result_shape` 注册表 + 最小 payload 闸门），
   族特有字段作为扩展而非重复声明。`_require_common` 从校验 2 个字段扩到校验全部共有字段。
2. **边际效应补到 GLM 族**：`logit` / `probit` / `poisson` 产出 `marginal_effects`，
   与既有 ordinal/multinomial 的字段形状一致，对 R `margins` 或 Stata 语义验证。
3. **消费者投影去分支**：`context_tools.py` 的 5 处按族 `if` 收敛为由契约驱动的统一投影；
   新增一族不得要求在此处加分支。
4. **系数与置信区间的统一读取入口**：消费者从一个地方读，而不是各自知道每族把系数放哪。

## 明确不做

- 不动 `ETSResultContract` 与 `SurvivalEvidenceContract` 的**形状**——它们是真正不同的
  产出，强行统一是把「统一」做成「削足适履」。它们只需注册为各自的 result shape。
- 不动 `time_series_diagnostics.py`（1014 行）与 `arma_garch.py`（558 行）的领域契约。
- 不动 `report_view_model.py`（已无按族分支）。
- 不做 ANOVA / ANCOVA（P1，本线之后）。
- 不做 survey 其余族接入（顺延）。
- 不动前端。
- 不 push / 不建 PR / 不 merge / 不 tag。

## 可证伪验收

每条写成「跑一次真实 run / 一个可执行断言，能看到什么」。

- **共有核心真被共享**：一个测试断言三个回归型结果契约的共有字段
  **来自同一个声明**，而不是三处各自写一遍；改动共有定义会同时影响三者。
- **`_require_common` 覆盖全部共有字段**：构造缺失任一共有字段的 packet，逐个被拒。
- **边际效应用户可达**：一次真实 `logit` run 的结果 artifact 中出现 `marginal_effects`，
  且在报告与 Agent 证据中可见；`probit` / `poisson` 同。
- **边际效应数值正确**：对 R 逐位对照，容差显式声明，`.R` 生成脚本提交进仓库
  （照 `tests/fixtures/survey/generate_oracle.R` 范式）。
- **消费者无按族分支**：一个测试断言 `context_tools.py` 中不再存在
  `model_type == "<族名>"` 形式的证据投影分支。
- **新增一族不需要改消费者**：用一个**合成族**（注册一个 result shape + 一条契约声明）
  断言它的证据能被投影，且未修改任何消费者代码。
- **golden 23 逐位 0-drift**。边际效应是新增字段，不得改变任何既有数值；
  若漂移，先当作设计被违反排查。
- 后端全量 ≥ 4662 passed，`git diff --check` 干净。

## 边界提示

统一信封会碰到全部 18 个族的契约装载路径。**共有字段的定义只能有一处**；
出现第二处「为某族特殊处理共有字段」的代码，即为本线失败。

## Boundary
- Affected paths: `backend/workbench/contracts/model/v186_model_families.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/result_shapes.py`, `backend/workbench/engine/packs/v186_model_families/runtime.py`
- Allowed paths: `backend/workbench/__init__.py`, `backend/workbench/api.py`, `backend/workbench/api_errors.py`, `backend/workbench/app.py`, `backend/workbench/artifacts.py`, `backend/workbench/canonical.py`, `backend/workbench/cleaning.py`, `backend/workbench/cli.py`, `backend/workbench/code_execution.py`, `backend/workbench/config.py`, `backend/workbench/control_plane.py`, `backend/workbench/data_operations.py`, `backend/workbench/diagnostic_summary.py`, `backend/workbench/domain.py`, `backend/workbench/evaluator_harness_manifest.py`, `backend/workbench/events.py`, `backend/workbench/exploration_log.py`, `backend/workbench/exports.py`, `backend/workbench/figure_context.py`, `backend/workbench/flags.py`, `backend/workbench/frozen_containment.py`, `backend/workbench/goodman_bacon_ref.py`, `backend/workbench/graph_decision_factory.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_store.py`, `backend/workbench/imputation.py`, `backend/workbench/ingestion.py`, `backend/workbench/merge.py`, `backend/workbench/metadata.py`, `backend/workbench/model_options.py`, `backend/workbench/model_terms.py`, `backend/workbench/prediction.py`, `backend/workbench/profiling.py`, `backend/workbench/projects.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_export.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/router.py`, `backend/workbench/sandbox.py`, `backend/workbench/statistical_exploration.py`, `backend/workbench/statistical_tests.py`, `backend/workbench/term_parser.py`, `backend/workbench/validation.py`, `backend/workbench/variable_roles.py`, `backend/workbench/visualization.py`, `backend/workbench/contracts`, `backend/workbench/agent`, `backend/workbench/engine`, `backend/workbench/econometrics`, `tests`, `docs/superpowers/plans`
- Protected paths: `frontend`, `scripts/gate.sh`, `tests/golden`, `tests/test_honest_did_adversarial.py`, `tests/test_honest_did_sd_adversarial.py`, `backend/workbench/survey`, `backend/workbench/report_view_model.py`, `backend/workbench/contracts/model/time_series_diagnostics.py`, `backend/workbench/contracts/model/arma_garch.py`
- Dependencies: `v1-8-7-block2-design-variance-engine`
- Tests: `LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests -q`, `git diff --check`
- Known gates: `the shared core must have exactly one definition; a second per-family special case fails this line`, `golden 23 must stay 0-drift; marginal effects are additive and must move no existing number`, `ETS and survival evidence keep their own shapes; unifying them would be forcing a fit`, `gate.sh runs in the host terminal; nested Seatbelt fakes ~20 containment failures`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
