# Completion Report — Lane B (Model Pack)：`time_series.ets`

work_package: v181-model-ets · lane: model · branch `feat/v181-model-ets`
branch_start_commit: `e76f3898941d888467a8630cd11b881d357f46f1`
contract_lock: `backend/workbench/contracts/model/ets.py`（ETSResultContract@1.0，未改动）

## 1. 实现了什么、没有实现什么

**实现：**

- `backend/workbench/engine/packs/ets/` 完整 pack：
  - `errors.py` — `ETSDiagnostic` / `ETSInputError` / `ETSEstimationError`（JSON-safe，冻结 evidence）。
  - `input.py` — `ETSModelOptions`（严格 options 校验，未知/缺失字段一律拒绝）+ `prepare_ets_input`
    （complete-case 只允许在样本两端并计数；内部缺失值、时间轴内部空洞、重复时间戳、
    不可解析时间、乘法分量遇非正值、常数序列、样本量不足全部 blocking）。
  - `estimation.py` — `statsmodels.tsa.exponential_smoothing.ets.ETSModel` MLE；
    `fit_method="statsmodels.ets.mle"`；`result_identity` = sha256(规格 + 样本指纹 + 拟合方法 + 参数名)。
  - `diagnostics.py` — optimizer 状态映射到合同的 `converged / max_iterations / failed`；
    非收敛 = blocking diagnostic（不返回任何数字），并给出
    `RecommendedActionCandidate`（drop_damping / drop_seasonal / drop_trend，均 `required_confirmation: True`）。
  - `compare.py` — compare adapter：非 ETS 对手 → `comparability=restricted` +
    `ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE`，且**不产生任何 AIC/BIC 差**；不同样本 →
    `restricted` + `ETS_SAMPLE_DIFFERS`；同族同样本 → `full` + 可选
    `ETS_SPECIFICATION_DIFFERS` + delta。
  - `runner.py` — `fit_ets(frame, options)` 纯核心 + `fit_from_context(ctx, env)` 引擎适配器。
  - `declaration.py` — `declare_pack()`：注册**一个** handler（`time_series.ets` / `ets_1`）与一条
    capability（Integration 只需加一行 `PackDeclaration`）。
- `tests/models/ets/`（6 个文件，53 tests）与 `tests/fixtures/models/ets/known_truth.py`
  （手写 ETS innovations 递归生成器，不调用生产代码，也不调用 statsmodels）。

**没有实现（work order non_goals / 越界）：**

- 未改 `engine/registry.py`、`engine/capabilities.py`、`packs/builtin_declarations.py`——
  **`time_series.ets` 目前尚未进入 builtin 声明**，这是 Integration 的薄注册提交。
- 无 Agent 编排 / 确认 UI / 自然语言 / 可执行 operation；无 forecast/figure/report 交付物；
  未改 ARMA-GARCH pack 任何行为；未新增依赖。
- 未做 pinned-run 落盘（LMM 的 admission/seal 机制属 `services/`，非本 lane 所有）。
  `fit_from_context` 只写 `ctx.artifacts`，不写 artifact 文件。见 §5 限制。

## 2. 精确修改的文件

全部为新增文件（无任何既有文件被修改，`git status` 仅三个新目录）：

```
backend/workbench/engine/packs/ets/{__init__,errors,input,estimation,diagnostics,compare,runner,declaration}.py
tests/models/ets/{test_ets_known_truth,test_ets_input_policy,test_ets_diagnostics,test_ets_compare,test_ets_pack_runtime,test_ets_contract_conformance}.py
tests/fixtures/models/ets/known_truth.py
docs/superpowers/release-trains/v1.8.1/evidence/completion-report-lane-b.md
```

commit: 见分支 `feat/v181-model-ets` 上的 `feat(ets): ...` 提交。

## 3. 是否修改合同

**否。** `backend/workbench/contracts/model/ets.py` 一字未改，按 lock 消费
`ETSResultContract` / `ETSSpecification` / `CONVERGENCE_CODES` / `COMPARE_REASON_CODES`。
`contracts/common/envelope.py`、`packs/loader.py` 只读使用。无 Contract Change Request。

## 4. 执行过的命令与精确结果

TDD 顺序（先失败）：

```
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/models/ets/test_ets_known_truth.py -q
→ ERROR: ModuleNotFoundError: No module named 'workbench.engine.packs.ets.runner'（pack 不存在，1 error）
```

实现后：

```
pytest tests/models/ets -q                                   → 53 passed（1.48s）
pytest tests/models tests/test_api_capabilities.py tests/engine -q -p no:randomly
                                                             → 312 passed, 86 warnings（9.81s）
git status --porcelain                                       → 仅 3 个未跟踪的新目录
git diff --check                                             → 无输出
```

未运行 `scripts/gate.sh`（work order 明令禁止，其它 lane 并行）。

### KNOWN-TRUTH 数值证据（tolerance 与实测）

数据由 `tests/fixtures/models/ets/known_truth.py` 手写递归生成，n = 4000，固定 seed。
容差策略：取 n=4000 时该参数的渐近标准误的约 3 倍并向上取整；σ² 的渐近 SE =
σ²·√(2/n) = 0.0224，故容差 0.07（≈3σ）。容差是先按 SE 推的，不是为了让测试通过而放宽的。

| fixture (seed) | 参数 | 真值 | 估计值 | 容差 (≈3 SE) | 实测偏差 |
| --- | --- | --- | --- | --- | --- |
| ETS(A,A,N) (1810101) | smoothing_level α | 0.40 | 0.4074 | 0.04 (SE≈0.013) | 0.0074 |
| | smoothing_trend β | 0.10 | 0.1033 | 0.015 (SE≈0.0045) | 0.0033 |
| | sigma² | 1.00 | 1.0024 | 0.07 | 0.0024 |
| ETS(A,Ad,N) (1810102) | α | 0.40 | 0.4034 | 0.04 | 0.0034 |
| | β | 0.10 | 0.0958 | 0.015 | 0.0042 |
| | damping φ | 0.90 | 0.9044 | 0.04 (SE≈0.013) | 0.0044 |
| | sigma² | 1.00 | 0.9587 | 0.07 | 0.0413 |
| ETS(A,A,A), m=4 (1810103) | α | 0.40 | 0.3940 | 0.04 | 0.0060 |
| | β | 0.05 | 0.0527 | 0.015 | 0.0027 |
| | smoothing_seasonal γ | 0.10 | 0.1089 | 0.03 (SE≈0.008) | 0.0089 |
| | sigma² | 1.00 | 0.9765 | 0.07 | 0.0235 |

其它具体数字断言：

- `ETS(A,A,N)` 与 `ETS(A,Ad,N)` 在**同一序列**上 `result_identity` 不同，且长度 = 64；同规格重拟合
  identity 与 aic 完全一致（确定性）。
- 真实带阻尼序列上 `aic(A,Ad,N) < aic(A,A,N)`，compare 的 `preferred_by_aic == "ETS(A,Ad,N)"`。
- 边缘缺失：120 行序列去掉 2 头 1 尾 → `n_obs=117, n_excluded=3,
  exclusion_reasons={leading_missing_value:2, trailing_missing_value:1}`。
- 内部缺失 1 个 → `ETS_INTERIOR_MISSING_VALUE`, severity=blocking, interior_missing_count=1。
- 删掉 2 个中间日期 → `ETS_INTERIOR_TIME_GAP`, modal_step_seconds=86400.0, distinct_step_count=2。
- 非收敛（注入 warnflag=1 / 空 retvals）→ `ETS_OPTIMIZER_DID_NOT_CONVERGE`, blocking，
  evidence 仅 {convergence_code, specification, n_obs}，**不含 aic/参数**。
- compare 三态：`restricted/ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE`（criteria=None）、
  `restricted/ETS_SAMPLE_DIFFERS`（criteria=None）、`full`（有 delta）。
- 合同层：`params` 中塞 `conditional_variance` → `ETSContractError("conditional-mean model")`；
  顶层塞 `value_at_risk_95` → `unknown ets_result field`。估计层同样先行拒绝
  （`ETS_FORBIDDEN_PARAMETER`）。

## 5. 已知限制、失败路径、性能

- **时间轴必须等距**。任何非等距（含交易日/工作日序列）都会被 `ETS_INTERIOR_TIME_GAP` 或
  `ETS_IRREGULAR_TIME_INDEX` 阻塞。这是合同点 4 的直接后果，但意味着 ARMA-GARCH 已支持的
  `business_or_trading_observations` 语义在 ETS 侧**不可用**；如产品需要，应作为下一轮
  contract 变更（新增显式 `time_index_semantics`），本 lane 不擅自放宽。
- **未做 pinned-run 落盘 / artifact manifest**：`fit_from_context` 返回 packet 并写
  `ctx.artifacts["_ets_result"]`，但不写 `artifacts/…json`、不参与 LMM 那套 admission seal。
  真正接入 run 生命周期需要 `services/pinned_run_directory.py`（非本 lane 所有）。
- **未做 forecast / figure / deliverable**：合同未锁定这些字段，本 lane 不发明。
- **σ² = statsmodels `mse`（残差均方）**，不是自由度校正后的方差；已在容差内与真值一致。
- 参数集合随规格变化（damping/seasonal 出现与否），`params` 是 name→float 的开放映射，
  合同也如此定义；下游不应假定固定 key 集合。
- 性能：n=4000 单次拟合 0.085s(A,A,A) ~ 0.30s(A,A,N)；`tests/models/ets` 全量 53 tests 1.48s。

## 6. 集成风险、建议合并顺序、回滚

- **风险低**：纯新增文件，无既有文件改动，未注册进 builtin 声明，因此合并后默认对现有行为
  零影响（`build_capabilities()` 不会多出 ETS，直到 Integration 加声明）。
- **Integration 的薄注册**（本 lane 不可做）：在
  `backend/workbench/engine/packs/builtin_declarations.py` 追加
  `PackDeclaration(module="workbench.engine.packs.ets.declaration", model_type="time_series.ets")`。
  注册后 `build_capabilities()["model_types"]` 会新增一条 key=`time_series.ets`，
  任何断言 capability 条数的既有测试需相应更新——这是唯一可预见的冲突点。
- 建议顺序：本分支可**先于**其它 lane 合并（无共享文件），薄注册放在最后一步。
- 回滚：删除 `backend/workbench/engine/packs/ets/`、`tests/models/ets/`、
  `tests/fixtures/models/ets/`（以及薄注册那一行）即可，无迁移、无数据、无 schema 变更。

## 7. 是否触碰 forbidden/protected files

**否。** `git status --porcelain` 只显示三个新目录 + 本报告；
`engine/registry.py`、`engine/capabilities.py`、`packs/builtin_declarations.py`、
`packs/arma_garch/**`、`agent/**`、`graph_store.py`、`frontend/**`、`scripts/gate.sh`、
两个 honest-DID 测试文件均未改动。未调用任何真实 LLM；未 push / PR / merge / tag；
未运行 `scripts/gate.sh`。
