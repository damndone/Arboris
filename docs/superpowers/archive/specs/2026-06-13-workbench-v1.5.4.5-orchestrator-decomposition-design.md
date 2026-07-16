# V1.5.4.5 — orchestrator.py 行为冻结拆分（设计稿）

- 日期：2026-06-13
- 版本：V1.5.4.5（路线图既定的"orchestrator.py 减负"，结构债清理第二刀）
- 基线：origin/main `91e05f4`（= V1.5.4.4，tag `v1.5.4.4`）
- 主题：把 `backend/workbench/orchestrator.py`（1354 行）从"驱动 + 公共 helper 抽屉"拆成"薄驱动核心 + 5 个按消费者分簇的 helper 模块"，**行为逐字节冻结**，golden 0-drift，0 新功能。

## 1. 目标与非目标

### 目标
1. 把堆在 `orchestrator.py` 里的 ~20 个私有 helper，按消费者天然分成 5 簇，各搬进 `orchestrator/` 包的独立子模块。
2. **对外命名空间 `workbench.orchestrator.*` 逐字不变** —— 所有 stage 的懒加载 `from ...orchestrator import X`、`api.py`/`cli.py` 的导入、以及测试的 `monkeypatch.setattr(orchestrator, ...)` 全部零改动。
3. 为后期拓展性打地基：拆完后"新 helper 该放哪"一眼可知（新模型类型→`_model_types`，新检查→对应 checks 模块，新报告块→`_report_build`），且每个子模块小到能被一个 agent/人完整 hold 在脑中。
4. 全程增量、每簇一道门禁，绝不 big-bang。

### 非目标（明确排除）
- **不改任何运行时行为**：不动算法、不动阈值常量的值、不加缓存、不做性能优化。性能优化留作独立的后续版本（拆完后热路径才看得清，届时另起 benchmark 基线 + 单独评估 golden 冲击）。
- **不下放 helper 到各 stage**（方案 B）：那会打破 `orchestrator.*` monkeypatch 契约、要改测试、非测试层冻结、golden 风险高。本版坚决不做。
- **不动健康核心**：`run_workflow` / `_run_workflow` / `run_batch_y_workflow` / `parse_imputation_request` / PIPELINE 装配 / `run_*` runner 再导出 —— 全部留在核心，逻辑不变。
- 不动 `_PREDICTION_PASSTHROUGH`（它已在 `engine/stages/estimation.py`，不在本文件）。

## 2. 关键约束（行为冻结的承重点）

调研已确认（git-verified 2026-06-13）：

1. **唯一脆弱的 monkeypatch 命名空间面 = `run_*` 再导出**：测试真正 `monkeypatch.setattr(orchestrator, ...)` 的只有 `run_panel_ols`、`run_logit`、`run_prediction_model`、`run_batch_y_workflow`。这些从 `econometrics.runner` / `prediction` 引进的 `run_*` 名字 **必须物理留在核心 `__init__.py`**，不进任何子模块。
2. **20 个私有 helper 无一被 monkeypatch** → 它们彼此互调、或搬到子模块，都不影响任何测试的 patch 语义。
3. **依赖图单向且近乎无簇间边**（实测每个 helper 的文件内被调次数）：
   - 核心驱动 → `_manifest`（用 `_write_manifest`/`_lineage`/`_primary_model_summary`）
   - 核心驱动 → `_model_types`（用 `_model_id_for_type`/`_engine_for_type`）
   - 簇内唯一边：`_coefficient_rows_for_models` → `_coefficient_rows`（同在 `_report_build`）
   - **子模块之间零依赖** → 无循环 import 风险。
4. **包化会把相对 import 深度 +1**：`orchestrator.py`（在 `workbench/`）→ `orchestrator/__init__.py`（在 `workbench/orchestrator/`）后，`from .engine...` 要变 `from ..engine...`，`from .artifacts` → `from ..artifacts`，等等。这是纯机械但必须无遗漏的改动，单独成一个 Phase 隔离风险。
5. **stage 的懒加载导入解析到包 `__init__`**：因为是函数体内（运行时）导入，包初始化早已完成 → 安全。**铁律：任何子模块都不得 `from . import ...` 反向导入包 `__init__`**（否则初始化期循环）。子模块要用同级 helper 时，直接 `from ._other import name`。

## 3. 目标结构

`orchestrator.py`（单文件）→ `orchestrator/`（包）：

```
backend/workbench/orchestrator/
  __init__.py            驱动核心 + 命名空间再导出枢纽
  _manifest.py           清单/血缘/刷盘基建
  _model_types.py        模型类型映射
  _column_checks.py      列检查（pre-estimation 私货）
  _reliability_checks.py 可靠性/相关性检查（最大簇）
  _report_build.py       报告构建（展示层逻辑）
```

### `__init__.py`（核心，目标 ~350 行）
保留：
- `WorkflowValidationError`
- `run_workflow` / `_run_workflow` / `run_batch_y_workflow` / `parse_imputation_request`
- 全部 16 个 `from ..engine.stages.X import XStage` + PIPELINE 相关
- `run_*` runner/prediction 再导出（`run_ols`/`run_logit`/`run_panel_ols`/`run_glm`/`run_poisson`/`run_probit`/`run_negative_binomial`/`run_iv_2sls`/`run_time_series_diagnostics`/`run_prediction_model`）—— **monkeypatch 面，原地**
- 其余 module-level import（`pd`、`dpf`、`GraphRecorder` 等）凡驱动自身仍需的
- **再导出枢纽**：用显式 `from ._manifest import (...)` 等，把 5 簇的全部 helper 名字重新绑定到包命名空间。显式（非 `import *`）以保证可 grep、契约可见。

### 各子模块成员
| 模块 | 函数 / 常量 |
|---|---|
| `_manifest.py` | `_write_manifest`、`_lineage`、`_safe_flush_recorder`、`_build_model_routing_summary`、`_primary_model_summary` |
| `_model_types.py` | `_MODEL_TYPE_MAP`、`_SUPPORTED_GLM_FAMILIES`、`_PREDICTION_MODEL_TYPES`、`_map_model_type`、`_validate_requested_model_type`、`_model_id_for_type`、`_engine_for_type`、`_model_failure_details`、`_ROOT_CAUSE_MAX_LENGTH` |
| `_column_checks.py` | `_model_column_issue`、`_coerce_x_columns_to_numeric`、`_detect_categorical_x_vars`、`_detect_suspicious_vars`、`_check_suspicious_dtypes`、`_check_categorical_candidates`、`_normalized_existing`、`_check_dropped_variables`、`_CATEGORICAL_NAME_PATTERNS`、`_SUSPICIOUS_NAME_PATTERNS` |
| `_reliability_checks.py` | `_check_model_validity`、`_check_overdispersion_issue`、`_diagnostic_family`、`_check_rare_event`、`_detect_binary_vars`、`_check_binary_correlations`、`_check_treatment_proxy_correlations`、`_detect_exposure_candidates`、`_select_valid_exposure_col`、`_BINARY_CORRELATION_WARN`、`_BINARY_CORRELATION_INFO`、`_TREATMENT_PROXY_CORRELATION_WARN`、`_EXPOSURE_NAME_PATTERNS` |
| `_report_build.py` | `_build_variable_importance`、`_importance_sort_key`、`_build_descriptive_stats`、`_coefficient_rows`、`_coefficient_rows_for_models`、`_mice_imputation_fact`、`_model_summary`、`_variable_summary`、`_write_model_result` |

> 注：簇成员的最终归属以"实测调用边 + 该函数实际依赖的 import"为准；若某 helper 的内部依赖横跨两簇，Task 内按"主消费者"归簇并在子模块顶 `from ._other import x` 直连。常量随其唯一使用它的函数走。

## 4. 实施拓扑（增量，每簇一道门禁）

每个 Phase 结束都必须过 `./scripts/gate.sh`（BE 全量 794 / golden+invariants+snapshot 15 个 0-drift / vitest 593 / `tsc --noEmit` 0），红了就 `git` 退回上一个绿点，问题锁在单簇内。

- **Phase 0 — 地基**：新建 worktree `.worktrees/workbench-v1.5.4.5` + 分支 `workbench-v1.5.4.5`（base = main `91e05f4`）；建 venv（`~/.local/bin/python3.11 -m venv .venv` + `-e ".[dev,panel,ml,imbalanced,imputation]"`）+ `frontend && npm install`；跑基线 `gate.sh` 确认起点全绿。
- **Phase 1 — 纯包化（不拆内容）**：`orchestrator.py` → `orchestrator/__init__.py`，逐字搬运，只修相对 import 深度（+1 级）。门禁绿。隔离"import 深度漂移"这个唯一机械风险。
- **Phase 2 — 抽 `_manifest.py`**（最被广用、簇内边少，先验证 re-export + 跨模块直连 import 模式）。门禁绿。
- **Phase 3 — 抽 `_model_types.py`**（自包含）。门禁绿。
- **Phase 4 — 抽 `_column_checks.py`**。门禁绿。
- **Phase 5 — 抽 `_reliability_checks.py`**（最大簇，模式已验证后再动）。门禁绿。
- **Phase 6 — 抽 `_report_build.py`**（含唯一簇内边 `_coefficient_rows`）。门禁绿。
- **Phase 7 — 收口 + 拓展性地基**：
  - 新增 `tests/test_orchestrator_namespace.py`：断言 `dir(workbench.orchestrator)` 暴露的公共名 + 全部历史 helper 名 + 全部 `run_*` 名，与基线快照集合**完全一致**（一个不多一个不少）。这是拓展性护栏 —— 将来谁手滑漏掉一条 re-export、或误删一个 monkeypatch 面，立刻变红。基线集合在 Phase 0 用 `91e05f4` 的 `orchestrator` 模块抓取并写死。
  - 在 `orchestrator/__init__.py` 顶部写一段"维护者指南"docstring：新 helper 该放哪个子模块、子模块不得反向 import 包、re-export 是对外契约。
  - 全分支 review（requesting-code-review）+ 写 `docs/v1.5.4.5-release-notes.md`。

## 5. 测试策略

- **golden 0-drift 是行为冻结的硬证据**：纯搬运 + re-export 保证同一批函数对象、同一调用图，结果必逐字节相同。每 Phase 必跑。
- **全量套件（非子集）**：项目历史上只跑子集漏过连带破坏（V1.5.4.2 stale mock）。每 Phase 跑 `gate.sh` 全量。
- **本版不写"删接线即变红"(G0-3) 风格新测试**：因为本版不新增任何接线，纯搬运。冻结证据来自"golden 0-drift + 794 全绿"。唯一新增测试是 Phase 7 的命名空间完整性护栏（防再导出漂移），它本身就是"漏 re-export 即变红"。
- **拆分若漏 import**：子模块少写一个 `from ._x import y` → 运行即 `NameError` → 全量套件立刻红，自然兜住。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 包化改相对 import 深度漏改一处 | 单独 Phase 1，只做这件事，门禁兜底 |
| 漏一条 re-export → stage 懒加载 `ImportError` | 每 Phase 全量门禁 + Phase 7 命名空间完整性测试 |
| 子模块反向 import 包 → 初始化循环 | 设计铁律 §2.5；子模块只 `from ._sibling import` |
| 误碰 `run_*` 命名空间面 | 设计明令 `run_*` 留核心，命名空间测试盯死 |
| golden 漂移 | 每 Phase 必跑 golden 0-drift，红即回退单簇 |

## 7. 发布拓扑（沿用既定流程）

tag `v1.5.4.5` 打在分支 head → `--no-ff` 合并进 main → 保留分支 + worktree 作版本标记。**直推 origin/main 会被分类器拦，需用户显式授权那一步。** 版本隔离铁律：本版所有代码只在 `.worktrees/workbench-v1.5.4.5`，不写进任何旧版目录。
