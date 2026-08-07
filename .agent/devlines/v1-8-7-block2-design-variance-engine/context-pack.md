# Frozen Context Pack

Line: `v1-8-7-block2-design-variance-engine`
Baseline SHA: `9d5e94717f9f06dbc92955aa8cf3ca26dda37f71`

## Objective
# v1.8.7 块 2 设计方差引擎 + 两张枚举天花板 Objective

v1.8.7 块 2。**本版架构核心**，也是阶段门：块 2 不完全关闭（oracle 对上 + 用户可达验收通过），
不得开块 3。

块 1 已把八个设计声明透传到 `ctx.artifacts` 且证明为零行为。本块让它们**第一次被消费**。

## 核心约束：正交组合，不是枚举矩阵

三者必须是独立对象，自由组合：

```
Design      strata / PSU / weights / fpc / replicate / lonely-psu / subpop
Estimator   声明了能力集的确定性估计量
Variance    linearization | replicate
```

**组合合法性由估计量声明的能力推导，不查表：**

| 能力 | 必需？ | 解锁 |
|---|---|---|
| 确定性重估 `(data, weights) -> params` | **必需** | 重复权重方差 |
| 影响函数 | 可选 | Taylor 线性化 |
| 消费设计对象 | 可选 | degf 感知推断、调整 Wald |

**禁止**在 `estimation.py` 按族写 `if`；**禁止**手写「族 × 设计」支持矩阵。

本块只定义能力协议并实现消费它的引擎，用**合成估计量**证明其可用；
真实模型族按此协议声明属块 3。

## 必须完成

### 2A 设计方差引擎

1. Design 对象：strata / PSU / weights / fpc / lonely-psu 策略 / subpop。
2. **Taylor 线性化**通道（对提供影响函数的估计量）。
3. **重复权重**通道：`brr` / `jackknife` / `bootstrap`，以及直接消费数据自带的
   重复权重（`provided`）。这是通用引擎，不是分位数回归的专用补丁。
4. **设计自由度** `degf = #PSU − #strata`，用于 t 临界值与 CI（**不是**正态近似）。
5. **lonely PSU 五策略**：`fail`（默认）/ `remove` / `adjust` / `average` / `certainty`。
6. **DEFF / DEFT / Kish 有效样本量** `n_eff = (Σw)² / Σw²`，**默认产出，非可选开关**。
7. **子总体**：在完整设计对象上取子集，保留全部方差信息。
8. **调整 Wald 检验**，分母自由度用设计自由度。
9. **replicate 失败如实报告**：成功/失败计数与原因分类；失败比例超阈值**拒绝出结果**。
10. 解除 `sampling_weight` 的 fail-closed —— **仅当**设计已声明且本引擎可算；
    未声明设计时保持 fail-closed，并**替换掉现有那句错误建议**
    （`entity_col + covariance=clustered` 不等于分层设计方差）。

### 2B `result_shape` 扩展点

11. `ModelFamilyContract.result_shape`（`workflow_contracts.py:310`）从封闭三值枚举
    改为**可声明扩展**。
12. 接 v1.8.6 的**最小 payload 闸门**：声明新 shape 时必须同时声明其 payload 最小
    schema 与版本，消费者按既有版本协商规则处理未知版本。
    **不做**全仓 Artifact Schema Registry。

## 明确不做

- **不声明任何真实模型族**（属块 3/4/5）。本块只用合成估计量证明协议可用。
- 不做事后分层 / 校准 / raking（块 6）。
- 不做 PCA/EFA/Cronbach/聚类的实现——**只打开** `result_shape`，不填内容。
- 不做时间序列 + 抽样设计（概念不组合）。
- 不碰前端（A1 的 RunForm 属其自己的线）。
- 不改块 1 的入参接线形状。
- 不 push / 不建 PR / 不 merge / 不 tag。

## 可证伪验收

每条写成「跑一次真实 run / 一个可执行断言，能看到什么」。

**引擎正确性（外部 oracle）**

- 分层 + PSU + 权重的 OLS，系数与 SE 对 R `survey::svyglm` 逐位，容差显式声明。
- `degf` 等于 `#PSU − #strata`；用 `degf` 较小的 fixture 断言 CI 用的是 t 临界值
  而非正态近似（两者必须可区分，否则该断言什么也没证明）。
- 五种 lonely PSU 策略各自对 R 逐位；默认 `fail` 给出明确错误码 + 该层标识。
- 重复权重三型各自对 R `withReplicates` 逐位。
- 消费数据自带重复权重（模拟 NHANES 形状）产出与 R 一致的 SE。
- **子总体**：设计内取子集对 R `subset(design, …)` 逐位；且用**横切分层**的 fixture
  断言它与「先筛数据再建设计」结果**确实不同**（fixture 必须让两者可区分）。
- 调整 Wald 对 R `regTermTest` 逐位，分母自由度为设计自由度。
- `DEFF` / `n_eff` 对 R `svymean(deff=TRUE)` 与 `(Σw)²/Σw²` 逐位。

**架构（这几条钉住「不退化成枚举」）**

- **正交性证明**：临时注册一个**合成估计量**（不属任何既有族、仅满足必需能力），
  跑通完整设计方差路径，**且未修改任何设计层代码**。
- **能力分级生效**：只声明「确定性重估」的估计量走得通重复权重通道，
  被拒绝线性化通道，且拒绝理由是 **typed** 的（缺 `影响函数` 能力），非自由文本。
- **无按族分支**：断言 `estimation.py` 中不存在按族分支的 survey 逻辑，
  也不存在手写的「族 × 设计」支持矩阵。
- **`result_shape` 扩展点**：注册一个**合成产出形状**，断言它能通过契约校验、
  能注册、能投影到消费者；并断言 `workflow_contracts.py` 中不再存在封闭
  `result_shape` 枚举。
- **能力矩阵可发现**：`/capabilities` 与 agent 投影暴露「设计 × 方差方法」的
  可推导支持关系。

**用户可达 / 不回归**

- 一次真实 run 声明设计后，结果 artifact 出现 `survey_design` 条目
  （分层数、PSU 数、`degf`、方差方法、DEFF、n_eff），且在报告、表格、XLSX 导出中可见。
- replicate 失败时结果中出现成功/失败计数与原因分类；超阈值拒绝出结果。
- 未声明 `sampling_weight` 且未声明设计的既有 run **逐位不变**。
- **golden 23 逐位 0-drift**。本块不应产生任何漂移；若漂移，
  **先当作设计被违反排查**，不走重生流程。
- 后端全量 ≥ 4638 passed，`git diff --check` 干净。

## Boundary
- Affected paths: `backend/workbench/engine/stages/estimation.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/econometrics/runner.py`
- Allowed paths: `backend/workbench/__init__.py`, `backend/workbench/api.py`, `backend/workbench/api_errors.py`, `backend/workbench/app.py`, `backend/workbench/artifacts.py`, `backend/workbench/canonical.py`, `backend/workbench/cleaning.py`, `backend/workbench/cli.py`, `backend/workbench/code_execution.py`, `backend/workbench/config.py`, `backend/workbench/control_plane.py`, `backend/workbench/data_operations.py`, `backend/workbench/diagnostic_summary.py`, `backend/workbench/domain.py`, `backend/workbench/evaluator_harness_manifest.py`, `backend/workbench/events.py`, `backend/workbench/exploration_log.py`, `backend/workbench/exports.py`, `backend/workbench/figure_context.py`, `backend/workbench/flags.py`, `backend/workbench/frozen_containment.py`, `backend/workbench/goodman_bacon_ref.py`, `backend/workbench/graph_decision_factory.py`, `backend/workbench/graph_model.py`, `backend/workbench/graph_recorder.py`, `backend/workbench/graph_store.py`, `backend/workbench/imputation.py`, `backend/workbench/ingestion.py`, `backend/workbench/merge.py`, `backend/workbench/metadata.py`, `backend/workbench/model_options.py`, `backend/workbench/model_terms.py`, `backend/workbench/prediction.py`, `backend/workbench/profiling.py`, `backend/workbench/projects.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_export.py`, `backend/workbench/report_quality.py`, `backend/workbench/report_store.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/router.py`, `backend/workbench/sandbox.py`, `backend/workbench/statistical_exploration.py`, `backend/workbench/statistical_tests.py`, `backend/workbench/term_parser.py`, `backend/workbench/validation.py`, `backend/workbench/variable_roles.py`, `backend/workbench/visualization.py`, `backend/workbench/engine`, `backend/workbench/econometrics`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/survey`, `tests`, `docs/superpowers/plans`
- Protected paths: `frontend`, `scripts/gate.sh`, `tests/golden`, `tests/test_honest_did_adversarial.py`, `tests/test_honest_did_sd_adversarial.py`, `backend/workbench/http`, `backend/workbench/services`, `backend/workbench/orchestrator`
- Dependencies: `v1-8-7-block1-shared-input-wiring`
- Tests: `LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests -q`, `Rscript tests/fixtures/survey/generate_oracle.R`, `git diff --check`
- Known gates: `PHASE GATE: block 3 must not start until every oracle here matches`, `golden 23 must stay 0-drift; drift means the design was violated`, `no per-family survey branching and no family-x-design support matrix`, `gate.sh must run in the host terminal; nested Seatbelt fakes ~20 containment failures`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
