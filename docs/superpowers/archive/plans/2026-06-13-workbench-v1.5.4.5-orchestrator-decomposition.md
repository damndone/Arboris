# V1.5.4.5 orchestrator.py 行为冻结拆分 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `backend/workbench/orchestrator.py`（1354 行）拆成 `orchestrator/` 包（薄驱动核心 + 5 个按消费者分簇的 helper 子模块 + 再导出枢纽），`workbench.orchestrator.*` 命名空间逐字不变，行为冻结，golden 0-drift，0 新功能。

**Architecture:** 方案 A —— `orchestrator.py` → `orchestrator/__init__.py`（核心驱动 + 显式 re-export）+ `_manifest.py` / `_model_types.py` / `_column_checks.py` / `_reliability_checks.py` / `_report_build.py`。helper 整段逐字搬运（剪切+粘贴，函数体一字不改），子模块只补自身需要的 import，核心用显式 `from ._x import (...)` 把名字重绑回包命名空间。增量：每簇一个 Task，每 Task 结束跑 `./scripts/gate.sh` 全绿，红即 `git reset --hard` 退回上一个绿点。

**Tech Stack:** Python 3.11，pytest（`.venv/bin/python -m pytest`），vitest + tsc，`./scripts/gate.sh` 一键门禁。

**基线：** main `91e05f4`（= V1.5.4.4）。门禁基线 = BE 794 / golden+invariants+snapshot 15 个 0-drift / FE 593 / tsc 0。

**承重铁律（每个 Task 都要守）：**
1. `run_*` 再导出（`run_ols`/`run_logit`/`run_panel_ols`/`run_glm`/`run_poisson`/`run_probit`/`run_negative_binomial`/`run_iv_2sls`/`run_time_series_diagnostics`/`run_prediction_model`）**永远留在 `__init__.py`**，绝不进子模块 —— 这是测试 monkeypatch 的命名空间面。
2. 任何子模块**不得** `from . import ...` 或 `from .orchestrator import ...` 反向导入包 `__init__`（初始化期循环）。子模块要用同级 helper 时写 `from ._sibling import name`。
3. helper 整段逐字搬运，函数体一个字符都不改。只动 import 归属与 re-export。
4. 每 Task 末尾 `./scripts/gate.sh` 必须 `>>> GATE PASSED`，否则不提交、退回。

---

## Task 0：地基 —— worktree + venv + 基线门禁

**Files:**
- Create: worktree `.worktrees/workbench-v1.5.4.5`（分支 `workbench-v1.5.4.5`，base = `91e05f4`）

- [ ] **Step 1: 建分支 worktree（版本隔离铁律：本版所有代码只在此目录）**

```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.4.5 .worktrees/workbench-v1.5.4.5 91e05f4
cd .worktrees/workbench-v1.5.4.5
```

- [ ] **Step 2: 建 venv（全 extras，IV/panel 需 linearmodels）**

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -q -e ".[dev,panel,ml,imbalanced,imputation]"
```

- [ ] **Step 3: 前端依赖**

```bash
( cd frontend && npm install )
```

- [ ] **Step 4: 跑基线门禁，确认起点全绿**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`（BE 794 / golden 15 0-drift / FE 593 / tsc 0）。**若基线就不绿，停下排查环境，不要往下走。**

- [ ] **Step 5: 抓取命名空间基线快照（Task 7 的护栏要用）**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" > /tmp/orch_namespace_baseline.txt
wc -l /tmp/orch_namespace_baseline.txt
```
Expected: 打印出当前 `orchestrator` 模块的全部公开名（公共 API + 私有 helper + `run_*` + 被 import 进来的依赖名）。**把这份清单留底**（Task 7 写死成测试期望）。

- [ ] **Step 6: 无需提交**（worktree 即起点；本 Task 不改源码）。

---

## Task 1：纯包化（搬文件，不拆内容）

把单文件变成包，**只**修相对 import 深度，不动任何函数。隔离"import 深度漂移"这唯一机械风险。

**Files:**
- Move: `backend/workbench/orchestrator.py` → `backend/workbench/orchestrator/__init__.py`
- Test: 复用 `./scripts/gate.sh`

- [ ] **Step 1: git mv 成包**

```bash
mkdir backend/workbench/orchestrator
git mv backend/workbench/orchestrator.py backend/workbench/orchestrator/__init__.py
```

- [ ] **Step 2: 把所有 workbench 级相对 import 深度 +1（`.X` → `..X`）**

在 `backend/workbench/orchestrator/__init__.py` 顶部 import 区，把下列**单点**相对 import 全部改成双点（因为模块下沉了一级）。逐行核对（共约 40 行）：

```python
from ..artifacts import read_json, register_artifact, write_json
from ..cleaning import clean_frame, normalize_column_name
from ..config import load_config
from ..diagnostic_summary import build_diagnostic_summary
from ..domain import GuardrailIssue, Severity
from ..engine.context import DataHandle, ModelingContext, RunEnv
from ..engine.stages.cleaning import CleaningStage
from ..engine.stages.profile import ProfileStage
from ..engine.stages.routing import RoutingStage
from ..engine.stages.source import SourceStage
from ..engine.stages.validation import ValidationStage
from ..engine.stages.ytype import YTypeStage
from ..engine.stages.pre_estimation_checks import PreEstimationChecksStage
from ..engine.stages.roles import RoleInferenceStage
from ..engine.stages.exposure import ExposureDetectionStage
from ..engine.stages.statistical_tests import StatisticalTestsStage
from ..engine.stages.imputation import ImputationStage
from ..engine.stages.estimation import EstimationStage
from ..engine.stages.recording import RecordingStage
from ..engine.stages.diagnostics import DiagnosticsStage
from ..engine.stages.reliability import ReliabilityStage
from ..engine.stages.report import ReportStage
from ..graph_recorder import GraphRecorder
from ..graph_model import Stage
from ..graph_store import GraphStore
from .. import graph_decision_factory as dpf
from ..econometrics.optional_deps import OptionalDependencyNotInstalled
from ..econometrics.diagnostics import compute_diagnostics
from ..econometrics.runner import (
    run_glm, run_iv_2sls, run_logit, run_negative_binomial,
    run_ols, run_panel_ols, run_poisson, run_probit,
    run_time_series_diagnostics,
)
from ..exports import export_pdf, export_xlsx
from ..ingestion import ingest_files
from ..imputation import run_mice_imputation
from ..metadata import infer_schema
from ..narrative import build_claims
from ..profiling import profile_frame
from ..prediction import run_prediction_model
from ..projects import create_run
from ..reporting import render_html_report
from ..router import classify_dataset, detect_y_kind
from ..statistical_tests import (
    run_statistical_tests, summarize_statistical_tests, write_statistical_test_artifacts,
)
from ..validation import has_blockers, validate_profile
from ..variable_roles import infer_variable_roles
from ..visualization import create_figures
```

注意 `from . import graph_decision_factory as dpf`（原第 35 行的单点 `from .`）→ `from .. import graph_decision_factory as dpf`。函数体内对 `dpf`/各 helper 的引用都不变。

- [ ] **Step 3: 冒烟 import**

Run: `.venv/bin/python -c "import workbench.orchestrator; print('ok')"`
Expected: `ok`（无 ImportError）。若报 `attempted relative import beyond top-level package` 或 `ModuleNotFoundError`，说明漏改某一行深度，回 Step 2 核对。

- [ ] **Step 4: 命名空间未漂移自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: 无输出（diff 为空）—— 包化后对外名字集合与基线完全一致。

- [ ] **Step 5: 全量门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): packageize orchestrator.py (verbatim, depth-shift only)

orchestrator.py -> orchestrator/__init__.py; relative imports shifted
.X -> ..X. No logic change; namespace byte-identical; gate PASSED."
```

---

## Task 2：抽 `_manifest.py`（清单/血缘/刷盘基建）

**搬运成员：** `_write_manifest`、`_lineage`、`_safe_flush_recorder`、`_build_model_routing_summary`、`_primary_model_summary`。

**Files:**
- Create: `backend/workbench/orchestrator/_manifest.py`
- Modify: `backend/workbench/orchestrator/__init__.py`（删这 5 个 def，加 re-export）

- [ ] **Step 1: 列出这 5 个函数实际用到的依赖**

Run（看每个函数体引用了哪些外部名，决定 `_manifest.py` 顶部要 import 什么）：
```bash
.venv/bin/python - <<'PY'
import re,inspect
import workbench.orchestrator as o
for n in ["_write_manifest","_lineage","_safe_flush_recorder","_build_model_routing_summary","_primary_model_summary"]:
    print("====",n); print(inspect.getsource(getattr(o,n)))
PY
```
Expected: 看到源码。记下其中用到的外部符号（典型：`Path`、`datetime`/`timezone`、`write_json`/`read_json`、`GraphRecorder`、`Stage`、`dpf`、`json` 等）。

- [ ] **Step 2: 新建 `_manifest.py`，逐字粘贴这 5 个函数 + 顶部补依赖 import**

文件骨架（import 按 Step 1 实测补全；**子模块用 `..` 引 workbench 级依赖**）：
```python
"""Manifest / lineage / recorder-flush infra extracted from orchestrator.

Verbatim move from orchestrator.py (V1.5.4.5, behavior-frozen). Consumed by
validation/estimation/pre_estimation/report stages + api.py via the
workbench.orchestrator.* re-export namespace.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..artifacts import read_json, write_json
from ..graph_recorder import GraphRecorder
# ... 其余按 Step 1 实测补齐（仅补本文件 5 个函数真正引用到的名字）

# <<< 逐字粘贴 _write_manifest / _lineage / _safe_flush_recorder /
#     _build_model_routing_summary / _primary_model_summary，函数体一字不改 >>>
```

- [ ] **Step 3: 从 `__init__.py` 删掉这 5 个函数定义，改成 re-export**

在 `__init__.py` 原本定义这 5 个函数的位置删除它们的 `def`，并在 import 区加：
```python
from ._manifest import (
    _build_model_routing_summary,
    _lineage,
    _primary_model_summary,
    _safe_flush_recorder,
    _write_manifest,
)
```
（核心驱动 `run_workflow`/`run_batch_y_workflow` 仍直接调用 `_write_manifest`/`_lineage`/`_primary_model_summary`，re-export 后这些名字在包命名空间可用，调用处不变。）

- [ ] **Step 4: 冒烟 import + 命名空间自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator; print('ok')" && \
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: `ok` + diff 为空。

- [ ] **Step 5: 全量门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。**特别确认 golden 0-drift**（manifest 写入直接进 golden 快照，最敏感）。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/_manifest.py backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): extract _manifest.py (verbatim, re-exported)

_write_manifest/_lineage/_safe_flush_recorder/_build_model_routing_summary/
_primary_model_summary moved to orchestrator/_manifest.py; re-exported from
__init__. Namespace unchanged; gate PASSED; golden 0-drift."
```

---

## Task 3：抽 `_model_types.py`（模型类型映射）

**搬运成员：** 常量 `_MODEL_TYPE_MAP`、`_SUPPORTED_GLM_FAMILIES`、`_PREDICTION_MODEL_TYPES`、`_ROOT_CAUSE_MAX_LENGTH`；函数 `_map_model_type`、`_validate_requested_model_type`、`_model_id_for_type`、`_engine_for_type`、`_model_failure_details`。

**Files:**
- Create: `backend/workbench/orchestrator/_model_types.py`
- Modify: `backend/workbench/orchestrator/__init__.py`

- [ ] **Step 1: 查源码与依赖**

Run:
```bash
.venv/bin/python - <<'PY'
import inspect
import workbench.orchestrator as o
for n in ["_map_model_type","_validate_requested_model_type","_model_id_for_type","_engine_for_type","_model_failure_details"]:
    print("====",n); print(inspect.getsource(getattr(o,n)))
for c in ["_MODEL_TYPE_MAP","_SUPPORTED_GLM_FAMILIES","_PREDICTION_MODEL_TYPES","_ROOT_CAUSE_MAX_LENGTH"]:
    print("====",c,"=",getattr(o,c))
PY
```
Expected: 看到 5 函数 4 常量源码。记下依赖（典型仅 `Any`、字符串处理，几乎自包含）。

- [ ] **Step 2: 新建 `_model_types.py`，逐字粘贴 4 常量 + 5 函数 + 补 import**

```python
"""Model-type mapping extracted from orchestrator (V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by ytype/estimation/diagnostics stages + the core
driver's exception handler via the workbench.orchestrator.* namespace.

新模型类型的映射改这里：_MODEL_TYPE_MAP / _SUPPORTED_GLM_FAMILIES /
_PREDICTION_MODEL_TYPES 三张表 + 对应翻译函数都在本文件。
"""
from __future__ import annotations

from typing import Any

# <<< 逐字粘贴 _ROOT_CAUSE_MAX_LENGTH 及其余常量、5 个函数，内容一字不改 >>>
```

- [ ] **Step 3: `__init__.py` 删定义、加 re-export**

```python
from ._model_types import (
    _MODEL_TYPE_MAP,
    _PREDICTION_MODEL_TYPES,
    _ROOT_CAUSE_MAX_LENGTH,
    _SUPPORTED_GLM_FAMILIES,
    _engine_for_type,
    _map_model_type,
    _model_failure_details,
    _model_id_for_type,
    _validate_requested_model_type,
)
```
（核心 `run_workflow` 异常处理里调用 `_model_id_for_type`/`_engine_for_type` 不变。）

- [ ] **Step 4: 冒烟 + 命名空间自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator; print('ok')" && \
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: `ok` + 空 diff。

- [ ] **Step 5: 门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/_model_types.py backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): extract _model_types.py (verbatim, re-exported)

Model-type maps + _map/_validate/_model_id/_engine/_model_failure_details
moved out; re-exported. Namespace unchanged; gate PASSED; golden 0-drift."
```

---

## Task 4：抽 `_column_checks.py`（列检查）

**搬运成员：** 常量 `_CATEGORICAL_NAME_PATTERNS`、`_SUSPICIOUS_NAME_PATTERNS`；函数 `_model_column_issue`、`_coerce_x_columns_to_numeric`、`_detect_categorical_x_vars`、`_detect_suspicious_vars`、`_check_suspicious_dtypes`、`_check_categorical_candidates`、`_normalized_existing`、`_check_dropped_variables`。

> 归属判据：这些是 pre_estimation / routing / recording 三道工序消费的"列级"helper。`_normalized_existing` 被 routing 用、`_check_dropped_variables` 被 recording 用，均属列处理范畴，归本簇。

**Files:**
- Create: `backend/workbench/orchestrator/_column_checks.py`
- Modify: `backend/workbench/orchestrator/__init__.py`

- [ ] **Step 1: 查源码与依赖**

Run:
```bash
.venv/bin/python - <<'PY'
import inspect
import workbench.orchestrator as o
for n in ["_model_column_issue","_coerce_x_columns_to_numeric","_detect_categorical_x_vars","_detect_suspicious_vars","_check_suspicious_dtypes","_check_categorical_candidates","_normalized_existing","_check_dropped_variables"]:
    print("====",n); print(inspect.getsource(getattr(o,n)))
PY
```
Expected: 看到源码。记下依赖（典型：`pd`、`GuardrailIssue`/`Severity`、`normalize_column_name`、常量）。**注意若某函数内部调用了本簇另一个函数（如 `_detect_*` 被 `_check_*` 调用），它们同在本文件，直接引用即可，无需 import。**

- [ ] **Step 2: 新建 `_column_checks.py`，逐字粘贴 2 常量 + 8 函数 + 补 import**

```python
"""Column-level checks extracted from orchestrator (V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by pre_estimation_checks/routing/recording stages via
the workbench.orchestrator.* namespace.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..cleaning import normalize_column_name
from ..domain import GuardrailIssue, Severity
# ... 按 Step 1 实测补齐

# <<< 逐字粘贴 2 常量 + 8 函数，内容一字不改；簇内互调直接引用 >>>
```

- [ ] **Step 3: `__init__.py` 删定义、加 re-export**

```python
from ._column_checks import (
    _CATEGORICAL_NAME_PATTERNS,
    _SUSPICIOUS_NAME_PATTERNS,
    _check_categorical_candidates,
    _check_dropped_variables,
    _check_suspicious_dtypes,
    _coerce_x_columns_to_numeric,
    _detect_categorical_x_vars,
    _detect_suspicious_vars,
    _model_column_issue,
    _normalized_existing,
)
```

- [ ] **Step 4: 冒烟 + 命名空间自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator; print('ok')" && \
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: `ok` + 空 diff。

- [ ] **Step 5: 门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/_column_checks.py backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): extract _column_checks.py (verbatim, re-exported)

Column-level checks moved out; re-exported. Namespace unchanged; gate
PASSED; golden 0-drift."
```

---

## Task 5：抽 `_reliability_checks.py`（可靠性/相关性检查，最大簇）

**搬运成员：** 常量 `_BINARY_CORRELATION_WARN`、`_BINARY_CORRELATION_INFO`、`_TREATMENT_PROXY_CORRELATION_WARN`、`_EXPOSURE_NAME_PATTERNS`；函数 `_check_model_validity`、`_check_overdispersion_issue`、`_diagnostic_family`、`_check_rare_event`、`_detect_binary_vars`、`_check_binary_correlations`、`_check_treatment_proxy_correlations`、`_detect_exposure_candidates`、`_select_valid_exposure_col`。

> 最大、最杂的一簇（diagnostics/reliability/exposure 三道工序分用）。模式已在 Task 2–4 验证，此时再动最稳。

**Files:**
- Create: `backend/workbench/orchestrator/_reliability_checks.py`
- Modify: `backend/workbench/orchestrator/__init__.py`

- [ ] **Step 1: 查源码与依赖**

Run:
```bash
.venv/bin/python - <<'PY'
import inspect
import workbench.orchestrator as o
for n in ["_check_model_validity","_check_overdispersion_issue","_diagnostic_family","_check_rare_event","_detect_binary_vars","_check_binary_correlations","_check_treatment_proxy_correlations","_detect_exposure_candidates","_select_valid_exposure_col"]:
    print("====",n); print(inspect.getsource(getattr(o,n)))
for c in ["_BINARY_CORRELATION_WARN","_BINARY_CORRELATION_INFO","_TREATMENT_PROXY_CORRELATION_WARN","_EXPOSURE_NAME_PATTERNS"]:
    print("====",c,"=",getattr(o,c))
PY
```
Expected: 看到 9 函数 4 常量源码。记下依赖（典型：`pd`、`GuardrailIssue`/`Severity`、阈值常量；簇内 `_detect_binary_vars` 可能被 `_check_binary_correlations` 调用 → 同文件直接引用）。

- [ ] **Step 2: 新建 `_reliability_checks.py`，逐字粘贴 4 常量 + 9 函数 + 补 import**

```python
"""Reliability / correlation checks extracted from orchestrator
(V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by diagnostics/reliability/exposure stages via the
workbench.orchestrator.* namespace. 阈值常量（0.7/0.5）随其函数留在本文件。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..domain import GuardrailIssue, Severity
# ... 按 Step 1 实测补齐

# <<< 逐字粘贴 4 常量 + 9 函数，内容一字不改；簇内互调直接引用 >>>
```

- [ ] **Step 3: `__init__.py` 删定义、加 re-export**

```python
from ._reliability_checks import (
    _BINARY_CORRELATION_INFO,
    _BINARY_CORRELATION_WARN,
    _EXPOSURE_NAME_PATTERNS,
    _TREATMENT_PROXY_CORRELATION_WARN,
    _check_binary_correlations,
    _check_model_validity,
    _check_overdispersion_issue,
    _check_rare_event,
    _check_treatment_proxy_correlations,
    _detect_binary_vars,
    _detect_exposure_candidates,
    _diagnostic_family,
    _select_valid_exposure_col,
)
```

- [ ] **Step 4: 冒烟 + 命名空间自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator; print('ok')" && \
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: `ok` + 空 diff。

- [ ] **Step 5: 门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/_reliability_checks.py backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): extract _reliability_checks.py (verbatim, re-exported)

Reliability/correlation checks + thresholds moved out; re-exported.
Namespace unchanged; gate PASSED; golden 0-drift."
```

---

## Task 6：抽 `_report_build.py`（报告构建）

**搬运成员：** `_build_variable_importance`、`_importance_sort_key`、`_build_descriptive_stats`、`_coefficient_rows`、`_coefficient_rows_for_models`、`_mice_imputation_fact`、`_model_summary`、`_variable_summary`、`_write_model_result`。

> 含本版唯一簇内边：`_coefficient_rows_for_models` → `_coefficient_rows`（同文件，直接引用）。

**Files:**
- Create: `backend/workbench/orchestrator/_report_build.py`
- Modify: `backend/workbench/orchestrator/__init__.py`

- [ ] **Step 1: 查源码与依赖**

Run:
```bash
.venv/bin/python - <<'PY'
import inspect
import workbench.orchestrator as o
for n in ["_build_variable_importance","_importance_sort_key","_build_descriptive_stats","_coefficient_rows","_coefficient_rows_for_models","_mice_imputation_fact","_model_summary","_variable_summary","_write_model_result"]:
    print("====",n); print(inspect.getsource(getattr(o,n)))
PY
```
Expected: 看到 9 函数源码。记下依赖（典型：`pd`、`Any`、`write_json`/`register_artifact`、`Path`）。确认 `_coefficient_rows_for_models` 内部调用 `_coefficient_rows` → 同文件直接引用。

- [ ] **Step 2: 新建 `_report_build.py`，逐字粘贴 9 函数 + 补 import**

```python
"""Report-building helpers extracted from orchestrator
(V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by report/recording/estimation stages via the
workbench.orchestrator.* namespace.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import register_artifact, write_json
# ... 按 Step 1 实测补齐

# <<< 逐字粘贴 9 函数，内容一字不改；_coefficient_rows_for_models 调
#     _coefficient_rows 同文件直接引用 >>>
```

- [ ] **Step 3: `__init__.py` 删定义、加 re-export**

```python
from ._report_build import (
    _build_descriptive_stats,
    _build_variable_importance,
    _coefficient_rows,
    _coefficient_rows_for_models,
    _importance_sort_key,
    _mice_imputation_fact,
    _model_summary,
    _variable_summary,
    _write_model_result,
)
```

- [ ] **Step 4: 冒烟 + 命名空间自检**

Run:
```bash
.venv/bin/python -c "import workbench.orchestrator; print('ok')" && \
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: `ok` + 空 diff。

- [ ] **Step 5: 门禁**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`。此时 `__init__.py` 应已只剩：import 区 + `WorkflowValidationError` + 4 个公共函数（`run_workflow`/`_run_workflow`/`run_batch_y_workflow`/`parse_imputation_request`）+ PIPELINE + re-export 块。粗验行数：
```bash
wc -l backend/workbench/orchestrator/__init__.py
```
Expected: 显著小于 1354（目标 ~350 行级别）。

- [ ] **Step 6: 提交**

```bash
git add backend/workbench/orchestrator/_report_build.py backend/workbench/orchestrator/__init__.py
git commit -m "refactor(orch): extract _report_build.py (verbatim, re-exported)

Report-building helpers moved out; re-exported. __init__ now thin driver +
re-export hub. Namespace unchanged; gate PASSED; golden 0-drift."
```

---

## Task 7：收口 —— 命名空间完整性护栏 + 维护者指南 + 发布说明

把"防再导出漂移"做成永久测试（拓展性地基），并补维护者指南。这是本版**唯一新增的测试**（真 TDD：先写期望、跑红、再保证绿）。

**Files:**
- Create: `tests/test_orchestrator_namespace.py`
- Modify: `backend/workbench/orchestrator/__init__.py`（顶部加维护者 docstring）
- Create: `docs/v1.5.4.5-release-notes.md`

- [ ] **Step 1: 生成命名空间期望清单常量**

Run（把当前（已拆完）的命名空间快照转成 Python 集合字面量，写进测试）：
```bash
.venv/bin/python -c "import workbench.orchestrator as o; print(sorted(n for n in dir(o) if not n.startswith('__')))"
```
Expected: 打印一个排序后的名字 list。**与 `/tmp/orch_namespace_baseline.txt`（Task 0 抓的拆分前快照）必须是同一集合** —— 先手动 `diff` 确认：
```bash
.venv/bin/python -c "import workbench.orchestrator as o; print('\n'.join(sorted(n for n in dir(o) if not n.startswith('__'))))" | diff /tmp/orch_namespace_baseline.txt -
```
Expected: 空 diff。把这份 list 复制进 Step 2 的测试。

- [ ] **Step 2: 写护栏测试（先让它能跑）**

`tests/test_orchestrator_namespace.py`：
```python
"""V1.5.4.5 拓展性护栏：orchestrator 拆成包后，对外命名空间必须保持稳定。

任何 stage 用 `from ...orchestrator import X` 取用的 helper、以及测试
monkeypatch 的 run_* 名，都必须在 workbench.orchestrator 包命名空间可见。
这个测试把名字集合钉死 —— 将来漏掉一条 re-export、或误删一个 run_* 监控面，
立刻变红。新增对外 helper 时，同步更新下方 EXPECTED 即可（有意为之的改动）。
"""
import workbench.orchestrator as orch

# Step 1 抓取的拆分前/后一致的对外名集合（公共 API + 私有 helper + run_* + 依赖）
EXPECTED_NAMES = {
    # <<< 粘贴 Step 1 的 list 内容，逐项填入，例如： >>>
    "run_workflow", "_run_workflow", "run_batch_y_workflow", "parse_imputation_request",
    "WorkflowValidationError",
    "run_ols", "run_logit", "run_panel_ols", "run_glm", "run_poisson", "run_probit",
    "run_negative_binomial", "run_iv_2sls", "run_time_series_diagnostics",
    "run_prediction_model",
    "_write_manifest", "_lineage", "_safe_flush_recorder",
    "_build_model_routing_summary", "_primary_model_summary",
    "_MODEL_TYPE_MAP", "_SUPPORTED_GLM_FAMILIES", "_PREDICTION_MODEL_TYPES",
    "_ROOT_CAUSE_MAX_LENGTH", "_map_model_type", "_validate_requested_model_type",
    "_model_id_for_type", "_engine_for_type", "_model_failure_details",
    "_model_column_issue", "_coerce_x_columns_to_numeric", "_detect_categorical_x_vars",
    "_detect_suspicious_vars", "_check_suspicious_dtypes", "_check_categorical_candidates",
    "_normalized_existing", "_check_dropped_variables",
    "_CATEGORICAL_NAME_PATTERNS", "_SUSPICIOUS_NAME_PATTERNS",
    "_check_model_validity", "_check_overdispersion_issue", "_diagnostic_family",
    "_check_rare_event", "_detect_binary_vars", "_check_binary_correlations",
    "_check_treatment_proxy_correlations", "_detect_exposure_candidates",
    "_select_valid_exposure_col", "_BINARY_CORRELATION_WARN", "_BINARY_CORRELATION_INFO",
    "_TREATMENT_PROXY_CORRELATION_WARN", "_EXPOSURE_NAME_PATTERNS",
    "_build_variable_importance", "_importance_sort_key", "_build_descriptive_stats",
    "_coefficient_rows", "_coefficient_rows_for_models", "_mice_imputation_fact",
    "_model_summary", "_variable_summary", "_write_model_result",
    # <<< 以及 Step 1 列表里其余依赖名（pd、dpf、各 Stage、import 进来的工具函数等），
    #     一律照抄 —— 集合相等才是“命名空间冻结”的真断言 >>>
}


def test_orchestrator_namespace_is_frozen():
    actual = {n for n in dir(orch) if not n.startswith("__")}
    missing = EXPECTED_NAMES - actual
    extra = actual - EXPECTED_NAMES
    assert not missing, f"orchestrator 命名空间丢失（漏 re-export?）: {sorted(missing)}"
    assert not extra, f"orchestrator 命名空间多出（未登记的新名）: {sorted(extra)}"


def test_monkeypatch_surface_present():
    """测试 monkeypatch 真正盯着的 run_* 面必须可见。"""
    for name in ["run_panel_ols", "run_logit", "run_prediction_model", "run_batch_y_workflow"]:
        assert hasattr(orch, name), f"monkeypatch 面缺失: {name}"
```

- [ ] **Step 3: 跑护栏测试，确认绿（集合应已相等）**

Run: `.venv/bin/python -m pytest tests/test_orchestrator_namespace.py -v`
Expected: 两个测试 PASS。**若 `extra`/`missing` 非空**，说明 EXPECTED 没照抄全 Step 1 的清单，或拆分漏/多了 re-export —— 按报错的名字对齐（先怀疑 EXPECTED 抄漏，再怀疑 `__init__` re-export）。

- [ ] **Step 4: 验证护栏“会变红”（删接线即红，G0-3 精神）**

临时在 `__init__.py` 注释掉 `_lineage` 的 re-export，跑：
Run: `.venv/bin/python -m pytest tests/test_orchestrator_namespace.py::test_orchestrator_namespace_is_frozen -q`
Expected: FAIL，报 `丢失: ['_lineage']`。**确认会红后，撤销注释**，重跑确认恢复 PASS。

- [ ] **Step 5: 加维护者指南 docstring**

在 `__init__.py` 模块顶部（现有内容之上）加：
```python
"""Workflow orchestration package.

V1.5.4.5: orchestrator.py（1354 行）拆成包，行为冻结。本 __init__ 是薄驱动核心
（run_workflow / _run_workflow / run_batch_y_workflow / parse_imputation_request /
PIPELINE 装配）+ 对外命名空间再导出枢纽。

维护者须知：
- helper 按消费者分簇在子模块：_manifest（清单/血缘）、_model_types（模型类型映射）、
  _column_checks（列检查）、_reliability_checks（可靠性/相关性）、_report_build（报告构建）。
  新 helper 按用途放对应子模块；找不到归属再考虑新建子模块。
- 子模块**不得**反向 import 本包（`from . import ...` / `from .orchestrator import ...`）—— 初始化期循环。
  子模块要用同级 helper，写 `from ._sibling import name`。
- 凡 stage / api / 测试以 `workbench.orchestrator.X` 形式引用的名字，必须在本文件 re-export；
  tests/test_orchestrator_namespace.py 钉死这份集合，漏导出即变红。
- run_* 再导出是测试 monkeypatch 的命名空间面，永远留在本文件。
"""
```

- [ ] **Step 6: 写发布说明 `docs/v1.5.4.5-release-notes.md`**

```markdown
# V1.5.4.5 — orchestrator.py 行为冻结拆分

结构债清理第二刀（0 新功能，behavior-frozen，golden 0-drift）。

## 拆了什么
`backend/workbench/orchestrator.py`（1354 行）→ `backend/workbench/orchestrator/` 包：
- `__init__.py` — 薄驱动核心 + 对外命名空间再导出枢纽
- `_manifest.py` — 清单/血缘/刷盘基建（5 函数）
- `_model_types.py` — 模型类型映射（5 函数 + 4 表/常量）
- `_column_checks.py` — 列检查（8 函数 + 2 常量）
- `_reliability_checks.py` — 可靠性/相关性检查（9 函数 + 4 常量）
- `_report_build.py` — 报告构建（9 函数）

## 为什么安全
- helper 逐字搬运（函数体一字不改）+ 显式 re-export → `workbench.orchestrator.*` 命名空间逐字节不变。
- stage 懒加载导入、api/cli 导入、所有 monkeypatch 零改动。
- 每簇一道 `./scripts/gate.sh` 全量门禁，golden 0-drift。
- 新增 `tests/test_orchestrator_namespace.py` 钉死命名空间，防将来再导出漂移。

## 门禁
BE <N> / golden+invariants+snapshot 15 0-drift / FE 593 / tsc 0 / gate.sh PASSED。
（<N> 为收口时实测后端用例数，应 = 794 + 2 新增命名空间测试 = 796。）

## 拓展性地基
新 helper 该放哪一眼可知（按子模块用途）；命名空间护栏 + 维护者 docstring 固化契约；
每个子模块小到可被完整 hold —— 为 V1.6 Agent Harness 的"agent 驱动清晰操作面"铺路。
```

- [ ] **Step 7: 全量门禁（含新测试）**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`，后端用例数应为 **796**（794 + 2）。

- [ ] **Step 8: 提交**

```bash
git add tests/test_orchestrator_namespace.py backend/workbench/orchestrator/__init__.py docs/v1.5.4.5-release-notes.md
git commit -m "test(orch): namespace-freeze guard + maintainer guide + release notes

tests/test_orchestrator_namespace.py pins the workbench.orchestrator.*
surface (missing/extra both go red); __init__ gains maintainer docstring;
V1.5.4.5 release notes. gate PASSED (BE 796); golden 0-drift."
```

---

## Task 8：全分支 review + 发布拓扑（需用户授权推送）

**Files:** 无新代码（review + 集成）。

- [ ] **Step 1: 全分支 review**

用 superpowers:requesting-code-review 对整条 `workbench-v1.5.4.5` 分支做评审。重点核：
- 每个子模块顶部 import 是否**仅**含本文件真正用到的名字（无残留死 import）；
- 无任何子模块反向 import 包；
- `run_*` 仍在 `__init__.py`；
- `__init__.py` 除驱动 + re-export 外无残留 helper 定义；
- golden 快照文件未被改动（`git diff 91e05f4 -- tests/golden/` 应为空）。

- [ ] **Step 2: 最终门禁复跑**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED`（BE 796 / golden 15 0-drift / FE 593 / tsc 0）。

- [ ] **Step 3: 打 tag + 合并 main（沿用既定拓扑）**

```bash
# 在分支 head 打 tag
git tag v1.5.4.5
# 回主仓库 --no-ff 合并
cd /Users/jiayuanren/项目规划
git checkout main
git merge --no-ff workbench-v1.5.4.5 -m "release: merge V1.5.4.5 into main (tag v1.5.4.5)"
```
保留分支 + worktree 作版本标记（版本隔离铁律）。

- [ ] **Step 4: 推送（⚠ 需用户显式授权 —— 分类器拦直推 origin/main）**

**停下来向用户确认后**再执行：
```bash
git push origin main
git push origin v1.5.4.5
git push origin workbench-v1.5.4.5
```

- [ ] **Step 5: 更新记忆 `project_workbench.md`**

把 Current state 块更新为 V1.5.4.5 SHIPPED（commit/tag、门禁数、拆了哪些子模块、命名空间护栏、下一站 = V1.5.5 多项目并发 或 性能优化候选）。并按 [[feedback_version_cleanup]] 主动问是否清 worktree 缓存。

---

## 自检（写完计划的回看）

**Spec 覆盖：** spec §3 目标结构 5 子模块 → Task 2–6 各一；§4 实施拓扑 Phase 0–7 → Task 0–7 一一对应；§4 Phase 7 命名空间护栏 → Task 7；§7 发布拓扑 → Task 8。✅ 无遗漏。

**占位扫描：** 计划里的 `<<< 逐字粘贴 >>>` / `<<< 按 Step 1 实测补齐 >>>` 是**有意**的——本版是"搬运"而非"新写"，函数体真身在现有文件里，逐字粘贴比在计划里重抄 1354 行更不易出错，且每个搬运 Task 的 Step 1 都先 `inspect.getsource` 打印真身、Step 4 命名空间 diff 兜底、Step 5 全量门禁兜底。Task 7 的 EXPECTED 集合在 Step 1 用真实 `dir()` 生成，非臆造。✅

**类型/命名一致：** 命名空间自检命令（`dir(o)` diff `/tmp/orch_namespace_baseline.txt`）在 Task 0 建基线、Task 1–6 每步复用、Task 7 固化成测试，前后一致；re-export 名字与各 Task 搬运成员表逐一对应。✅
