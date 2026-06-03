# V1.5.4.1 — UI ↔ V1.5.3.2 Backend Gap Closure(设计稿）

> **定位:Capability-Manifest 驱动的前后端接通。**
> 把 V1.5.3.2 后端能力(显式 model_type 扩展、MICE 插补、显式失败结构化)接到前端 UI,**用契约 + 切片 + 并行**的方式做,同时为 V1.5.5(Agent Harness)和 V1.5.6(editable rerun)提供可复用的 schema 契约位。
>
> **成功的样子:用户在 UI 上能选 probit / GLM family / 启用 MICE / 看见显式失败的"故事卡片" + 一键重跑;未来加新模型 / 新插补方法 = 后端注册 + 自动出现在 UI = 前端零改。**
>
> 日期:2026-06-03 ｜ Base:`workbench-v1.5.4`(`abe7fda`)｜ 铁律:独立 worktree `.worktrees/workbench-v1.5.4.1` + 独立分支 `workbench-v1.5.4.1` + 独立 venv。

---

## 0. 背景与缺口

V1.5.4 把后端拆解成可注册的 stage pipeline + model registry,**1.5.3.2 新增的所有后端能力在 CLI / Python API 上完全可用,且 705 测试 + 7 金标守门**。但产品视角上,UI 仍停留在 V1.5.0 时代:

| 能力 | CLI/API | 前端 UI |
|---|---|---|
| 显式 `model_type`(probit / negative_binomial / panel_ols / glm:*) | ✅ | ❌ 下拉只有 `auto`/`ols`/`logit`/`poisson` 四项 |
| MICE 插补(config-gated) | ✅ | ❌ 无开关,只 lineage 节点能识别静态标签 |
| 显式 model_type 失败 → 结构化 `failed`(1.5.3.2 契约) | ✅ 后端写 `failure_evidence` | ❌ `MODEL_FIT_FAILED` 埋在通用 issues 列表,故事不显式 |
| `imputation_summary` 结果展示 | ✅ 后端写 JSON | ❌ 前端零消费 |

**根因不是缺 UI,是缺契约。** 如果只把当前缺口"接线":扩下拉、加 checkbox、改卡片——下一次再加 KNN 插补 / Lasso 模型 / 新错误码,前后端又要联动改。这违背"为后期拓展性打基础"的原则。

**根治方向 = 把"加新能力"的成本从"前后端联动改"降到"后端注册即可"**。机制:后端暴露 `/capabilities` 能力清单(从 `MODEL_REGISTRY` + imputation registry 派生),前端动态渲染。

---

## 1. 范围边界

### V1.5.4.1 **要**做

1. 后端 `/capabilities` endpoint(从 V1.5.4 `MODEL_REGISTRY` + 新建 `IMPUTATION_REGISTRY` 派生)。
2. `run_workflow` 加 `imputation: dict | None = None` kwarg;`ImputationStage` 读 ctx 优先,fallback config。
3. `/runs` POST 加 `imputation` form 字段(JSON 字符串透传)。
4. `failure_evidence`(`engine/stages/estimation.py` 失败分支 + `ValidationStage` 的 `UNSUPPORTED_MODEL_TYPE` / `UNSUPPORTED_GLM_FAMILY` / `PANEL_FIELDS_MISSING`)注入 `recommended_actions: list[dict]`。
5. `imputation_summary.json` 按稳定 schema 写入 + `register_artifact("imputation_summary", ...)`。
6. 前端 `useCapabilities` hook(启动时拉 `/capabilities`,缓存)。
7. 前端 `ModelTypeSelect` 组件(从 capabilities 派生 `<optgroup>` 分组下拉,原 hard-coded 4 项删除)。
8. 前端 `FailureCard` 组件(渲染 `recommended_actions` 数组,severity 决按钮风格,`form_overrides` 一键透传到 form 状态重跑)。
9. 前端 `ImputationControls`(`imputation_methods.length === 1` 时 checkbox,≥ 2 时升级 select)。
10. 前端 `ImputationSummary` 回显面板(consumes `imputation_summary.json`)。
11. 前后端契约文档(`docs/api-contracts/*.md`)+ 契约 fixture + jsonschema 校验测试。

### V1.5.4.1 **不**做

1. 不做 prediction 模型(Lasso/Ridge/RandomForest)的前端入口——产品定位需先想清(→ V1.5.5 agent / V1.5.6 editable)。
2. 不做 panel_ols 的"数据感知禁用"(等 profile 异步出来再判 disable)——`requires` 字段在 capabilities schema 里**已声明**,前端组件实现留给后续(原 mockup C 方案的升级路径)。
3. 不做项目级 config.yml 编辑器(MICE 通过 form 字段透传即可)。
4. 不做 KNN / MeanFill 等其他插补方法的后端实现(但 schema 留好扩展空间)。
5. 不改变现有 `run_workflow` 公开签名的位置参数顺序(只追加 keyword-only 参数)。
6. 不改任何 V1.5.4 已验证的金标 / invariant / behavior snapshot(必须仍绿)。

---

## 2. 核心设计

### 2.1 Capability Manifest — `/capabilities` endpoint

**单一来源**:后端从 `MODEL_REGISTRY` 和新建的 `IMPUTATION_REGISTRY` 派生清单,**不维护单独的"UI 选项列表"**——这就是消除"加新东西前后端联动"的关键。

```http
GET /capabilities → 200 OK
```
```json
{
  "schema_version": 1,
  "model_types": [
    {"key": "auto", "label": "Auto (infer from y)", "group": "auto", "description": "Pick the best model automatically based on y type."},
    {"key": "ols", "label": "OLS (linear)", "group": "Linear", "description": "Ordinary Least Squares with HC1 robust SE."},
    {"key": "logit", "label": "Logit", "group": "Binary", "description": "Logistic regression for binary outcomes."},
    {"key": "probit", "label": "Probit", "group": "Binary", "description": "Probit regression for binary outcomes."},
    {"key": "poisson", "label": "Poisson", "group": "Count", "description": "Poisson regression for count outcomes."},
    {"key": "negative_binomial", "label": "Negative Binomial", "group": "Count", "description": "For overdispersed count outcomes."},
    {"key": "panel_ols", "label": "Panel OLS", "group": "Panel", "description": "Fixed/random effects panel OLS.",
     "requires": ["entity_or_time"]},
    {"key": "glm:binomial", "label": "GLM · binomial", "group": "GLM", "description": "Generalized linear model with binomial family."},
    {"key": "glm:poisson", "label": "GLM · poisson", "group": "GLM", "description": "Generalized linear model with Poisson family."},
    {"key": "glm:negative_binomial", "label": "GLM · negative binomial", "group": "GLM", "description": "Generalized linear model with negative binomial family."}
  ],
  "imputation_methods": [
    {"key": "mice", "label": "MICE (Multiple Imputation)", "description": "Multiple Imputation by Chained Equations. Recommended when >5–10% rows would otherwise be dropped due to missing values."}
  ]
}
```

**Schema 字段含义:**
- `schema_version: int` — 单调递增,前端检查 `>= 1` 即可降级处理。
- `model_types[].key` — 后端 `MODEL_REGISTRY` 的 key 或 `glm:<family>` 形式;前端透传到 `run_workflow(model_type=...)`。
- `model_types[].group` — UI 分组键(`Linear` / `Binary` / `Count` / `Panel` / `GLM` / `auto`)。前端用它生成 `<optgroup>`。
- `model_types[].requires` — 可选数组,声明该模型对数据形状的要求(本版只声明 `entity_or_time`,前端**暂不**实现 disable 逻辑;留给未来 C 方案升级)。
- `imputation_methods[].key` — 透传到 `run_workflow(imputation={"method": "..."})`。

**实现位置:** 新建 `backend/workbench/engine/capabilities.py`,导出 `build_capabilities() -> dict` 纯函数(无 IO,纯读 `MODEL_REGISTRY` + `IMPUTATION_REGISTRY`)。`api.py` 加 `@app.get("/capabilities")` 路由调用之。

**`IMPUTATION_REGISTRY`(新建)**:位于 `backend/workbench/engine/imputation_registry.py`,与 `MODEL_REGISTRY` 同形:
```python
@dataclass
class ImputationMethod:
    key: str           # "mice"
    label: str
    description: str
    apply: Callable    # adapter signature: (ctx, env) -> ImputationSummary

IMPUTATION_REGISTRY: dict[str, ImputationMethod] = {}
def register_imputation_method(m: ImputationMethod) -> None: ...
```
V1.5.4.1 只注册 MICE。`AnalysisPack` 加可选字段 `imputation_methods: list[ImputationMethod]`(类似 model_handlers,V1.5.4 已声明但此前未消费)。

### 2.2 `run_workflow` 公开 API 演化

**关键约束**:V1.5.4 的 `run_workflow` 签名已被 CLI 和测试套件依赖。**只追加 keyword-only 参数,不动既有顺序**。

```python
def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
    model_type: str = "auto",
    imputation: dict | None = None,    # NEW — keyword-only, default None
) -> dict[str, str]:
    ...
```

**为什么用 `dict` 而不是 `imputation_method: str`?**
- 当前 MICE 不需要参数。
- 但 KNN 需要 `k`,MeanFill 不需要,strategy-specific config 用 dict 自然扩展:
  ```python
  imputation={"method": "mice"}                  # 现在
  imputation={"method": "knn", "k": 5}           # 未来
  imputation={"method": "mean_fill"}             # 未来
  ```
- 一次加 dict 包装比未来再改签名安全。

**`imputation=None` 时**:落到现有 `config.imputation_method` 路径(完全向后兼容,V1.5.4 既有测试不变)。**`imputation` 非空时**:优先使用 dict 的 `method` 字段;`ImputationStage` 内 `ctx.requested_imputation = imputation`,读取顺序 `ctx.requested_imputation > config.imputation_method`。

CLI 同步:`workbench run ... --imputation mice` 或 `--imputation '{"method":"mice"}'`(本版只支持简单形式,但解析后照填 dict)。

### 2.3 `recommended_actions` schema —— 失败卡片数据驱动

**V1.5.4 `AnalysisPack.recommended_actions` 字段已声明但无生产者**,V1.5.4.1 是它**第一次有真实生产者**(orchestrator 失败路径)和**第一次有真实消费者**(前端 FailureCard)。这与 V1.5.4 spec §2.5 的"声明位"承诺直接对接。

后端 `failure_evidence` 注入数组:
```json
{
  "error_code": "MODEL_FIT_FAILED",
  "model_type": "logit",
  "requested_model_type": "logit",
  "model_id": "logit_1",
  "engine": "statsmodels",
  "y": "wage",
  "x": ["education", "experience"],
  "y_type": "continuous",
  "root_cause": "ValueError: y must be binary (got 40 unique continuous values)",
  "step": "estimation",
  "recommended_actions": [
    {
      "key": "rerun_auto",
      "label": "Re-run with auto",
      "severity": "primary",
      "form_overrides": {"model_type": "auto"}
    },
    {
      "key": "change_model",
      "label": "Change model type",
      "severity": "secondary"
    },
    {
      "key": "check_y_column",
      "label": "Check y column",
      "severity": "secondary",
      "hint": "Your y appears continuous; logit needs a binary 0/1 column."
    }
  ]
}
```

**字段含义:**
- `key: str` — 行动 ID,前端用于 React `key` + 埋点。
- `label: str` — 按钮显示文字。
- `severity: "primary" | "secondary"` — 按钮视觉风格。`primary` 用红色填充(失败上下文中的强行动),`secondary` 用边框灰色。
- `form_overrides: dict | undefined` — 可选,点击时把这些字段覆盖到 run form 状态。前端透传到 `run_workflow` 调用即可一键重跑。
- `hint: str | undefined` — 可选,鼠标 hover 显示。

**生产者位置:**
- `engine/stages/estimation.py` 显式失败分支(主要),根据 `requested_model_type` + `y_type` 生成上下文相关的 actions。
- `engine/stages/estimation.py` auto OLS 兜底也失败的分支(severity 都是 secondary,因为没有简单恢复路径)。
- `orchestrator._validate_requested_model_type`(`UNSUPPORTED_MODEL_TYPE` / `UNSUPPORTED_GLM_FAMILY`)。
- `engine/stages/estimation.py` 的 `PANEL_FIELDS_MISSING` pre-check。

**新建** `backend/workbench/engine/recommended_actions.py`,导出工厂函数 `actions_for_model_fit_failure(requested_model_type, y_type, ...) -> list[dict]`,集中所有"产 actions"的逻辑,便于单测和复用。

**与 V1.5.4 的连续性**:此举把 V1.5.4 spec §2.5 "Pack 声明位"中的 `recommended_actions` 从"声明"变为"工程实存"。AnalysisPack 注册的 actions(V1.5.6+ 才接通)与本版 orchestrator 直接产的 actions 走同一 schema。

### 2.4 `imputation_summary.json` 稳定 schema

后端写入路径 `run_root / "model_results" / "imputation_summary.json"`,并 `register_artifact("imputation_summary", ..., inputs=[input_artifact_id])`。

```json
{
  "schema_version": 1,
  "method": "mice",
  "status": "completed",
  "rows_imputed": 17,
  "columns_imputed": ["education", "experience"],
  "iterations": 12,
  "n_imputations": 5,
  "input_artifact": "cleaned_dataset",
  "output_artifact": "imputed_dataset"
}
```

**Method-agnostic 必填字段**:`schema_version`、`method`、`status`、`rows_imputed`、`columns_imputed`、`input_artifact`、`output_artifact`。
**Method-specific 字段**(本版 MICE):`iterations`、`n_imputations`。未来 KNN 加 `k`、MeanFill 加 `strategy`(`mean`/`median`/`mode`)— 都是新增可选字段,前端按 `method` 字段切分显示。

**前端 ImputationSummary 组件**消费此 JSON,渲染上述 mockup 中的蓝色"Imputation applied (MICE)"面板。**未来加 KNN 时,前端只需在 switch (method) 加一个 case,组件其他部分零改。**

### 2.5 前端组件结构

```
frontend/src/
  capabilities/
    api.ts                # GET /capabilities, 缓存
    useCapabilities.ts    # React hook
    types.ts              # 与契约 schema 一一对应的 TS 类型
  runForm/
    ModelTypeSelect.tsx   # <optgroup> 分组下拉, props: capabilities, value, onChange
    ImputationControls.tsx # checkbox 或 select, props: capabilities, value, onChange
  runResult/
    FailureCard.tsx       # props: failure_evidence; 渲染故事 + recommended_actions 按钮
    ImputationSummary.tsx # props: summary JSON; 蓝色回显面板
```

`App.tsx` 现有 hard-coded `<select>`(`App.tsx:382` 4 个 option)**完全删除**,替换为 `<ModelTypeSelect capabilities={caps} value={modelType} onChange={setModelType} />`。`runResult.tsx` 在 `detail.status === "failed"` 且 issues 中存在 `MODEL_FIT_FAILED` 时,在状态条下方插入 `<FailureCard ... />`。

---

## 3. 切片化交付计划

总工作量 ~6 天,但**实际墙钟 ~3.5 天**(切片 2/3 并行)。**12 个原子 PR / commit**,每个独立可 review、可 test、可 revert。

### 切片 1 — Contract First(0.5 天 / 1 PR,Sequential block)

**目标:** 写契约文档 + JSON Schema + fixture + 校验测试。**无任何前后端实现代码**。完成后切片 2/3 可立即并行启动。

**Deliverables:**
- `docs/api-contracts/capabilities.md` — endpoint + JSON Schema + sample fixture(`capabilities.sample.json`)
- `docs/api-contracts/recommended-actions.md` — schema + 3 个 sample(`recommended_actions.model_fit_failure.sample.json` 等)
- `docs/api-contracts/imputation-summary.md` — schema + sample(`imputation_summary.mice.sample.json`)
- `docs/api-contracts/runs-post.md` — 现有 form 字段表 + 新增 `imputation` 字段定义
- `tests/contracts/test_schema_capabilities.py` — jsonschema 校验 sample fixture
- `tests/contracts/test_schema_recommended_actions.py` — 同上
- `tests/contracts/test_schema_imputation_summary.py` — 同上

**Reviewer:** 架构 owner(契约一致性)。

**Definition of Done:** 4 个 markdown + 3 个 sample fixture + 3 个 schema test 通过(jsonschema 校验)。

### 切片 2 — Backend Implementation(2 天 / 5 PR,可并行于切片 3)

依赖**切片 1**(契约 + fixture)。后端工程师 own。

| PR | 内容 | 关键文件 | 测试 | 大致行数 |
|---|---|---|---|---|
| **2a** | `IMPUTATION_REGISTRY` + 注册 MICE + `build_capabilities()` + `/capabilities` 路由 | `engine/imputation_registry.py`(新)、`engine/capabilities.py`(新)、`api.py`(加路由) | endpoint response ↔ 切片 1 capabilities.sample.json 一致;jsonschema 校验 endpoint 实际输出 | ~120 |
| **2b** | `run_workflow` 加 `imputation: dict\|None` kwarg + `ImputationStage` 读 `ctx.requested_imputation` 优先 | `orchestrator.run_workflow`、`_run_workflow`、`engine/stages/imputation.py` | 既有 `test_engine_golden.py::test_golden_imputation` 仍绿(向后兼容);**新增** `test_imputation_kwarg_overrides_config`(传 `imputation={"method":"mice"}` 触发 MICE 即使 config 空) | ~80 |
| **2c** | `/runs` POST 加 `imputation` form 字段(JSON 字符串,可选)+ CLI `--imputation` 选项 | `api.py`、`cli.py` | `test_api_runs_imputation_form_field`(form 透传)、`test_cli_imputation_option`(CLI smoke) | ~60 |
| **2d** | `recommended_actions` 工厂 + 注入 `failure_evidence` | `engine/recommended_actions.py`(新)、`engine/stages/estimation.py`(失败分支,显式与 auto-fallback 两处)、`orchestrator._validate_requested_model_type`、estimation 的 `PANEL_FIELDS_MISSING` pre-check | 工厂函数纯单测(给定输入 → 输出确定 actions 数组);现有 invariant 5(`test_explicit_model_type_failure_returns_failed_no_fallback`)扩展为同时检查 `failure_evidence.recommended_actions` schema 符合契约 | ~150 |
| **2e** | `imputation_summary.json` 按稳定 schema 写入 + `register_artifact` | `engine/stages/imputation.py` | `test_imputation_summary_schema_matches_contract`(jsonschema 校验真实产出);imputation golden 自动更新(`artifacts` 多一个 `imputation_summary` entry — 这是预期,regen 该 golden) | ~50 |

**Reviewer:** 后端 owner。

**Definition of Done:** 全部 5 PR 合,705 BE 测试 + 新增 ~10 后端测试全绿,goldens 0 drift(除 imputation golden 因新增 artifact 而 regenerate)。

### 切片 3 — Frontend Implementation(2 天 / 4 PR,可并行于切片 2)

依赖**切片 1**(契约 fixture)。前端工程师 own。**所有测试用 sample fixture 当 mock,完全不依赖后端运行。**

| PR | 内容 | 关键文件 | 测试 | 大致行数 |
|---|---|---|---|---|
| **3a** | `useCapabilities` hook + TS 类型 | `frontend/src/capabilities/{api,types,useCapabilities}.ts` | hook 单测(MSW mock /capabilities,断言缓存与重渲染);TS 类型与切片 1 schema 字段一致(可用 `quicktype` 校验或手核) | ~80 |
| **3b** | `ModelTypeSelect` 组件(从 capabilities 派生 `<optgroup>`)+ `App.tsx` 替换原 hard-coded select | `frontend/src/runForm/ModelTypeSelect.tsx`、`App.tsx`(删 ~6 行 hard-coded option,加 `<ModelTypeSelect />`)| 组件单测 with sample fixture:assert 渲染 5 个 `<optgroup>` + 10 个 `<option>`;onChange 触发回调;A/B 快照 | ~120 |
| **3c** | `FailureCard` 组件 + `runResult.tsx` 在 failed + MODEL_FIT_FAILED 时插入 | `frontend/src/runResult/FailureCard.tsx`、`runResult.tsx`(插入逻辑 ~10 行)| 组件单测 with sample fixture:assert 标题/根因/3 个按钮渲染;`form_overrides` onClick 触发回调含正确 payload;severity primary/secondary 应用不同 CSS class | ~150 |
| **3d** | `ImputationControls`(`length===1` checkbox,`>=2` select)+ `ImputationSummary` 回显 + `App.tsx` 表单接入 + `runResult.tsx` 接入 summary | `frontend/src/runForm/ImputationControls.tsx`、`runResult/ImputationSummary.tsx`、`App.tsx`、`runResult.tsx`、`api.ts`(form.append imputation)| `ImputationControls` 单测两种 capabilities;`ImputationSummary` 单测渲染 sample summary;form 提交断言 `imputation` form 字段被附加 | ~200 |

**Reviewer:** 前端 owner。

**Definition of Done:** 全部 4 PR 合,FE 549 测试 + 新增 ~12 组件单测全绿(切片 4 才会跑端到端集成,本切片不引入)。

### 切片 4 — Integration(1 天 / 2 PR,切片 2 + 切片 3 都合后)

**Sequential gate**:必须切片 2、3 都合并后才开始。**所有人 own**(熟全局者最佳)。

| PR | 内容 | 测试 |
|---|---|---|
| **4a** | 前端 `useCapabilities` 切到真实 `/capabilities`;补 e2e 测试一只(Playwright 或 vitest happy-dom 起 server) | `tests/e2e/test_explicit_failure_recovery.spec.ts`:用户选 probit → y 非 binary → 失败卡片显示 → 点 "Re-run with auto" → 表单 model_type 切回 auto → 重跑成功 |
| **4b** | `docs/extensions.md` 扩写"如何让新模型 / 新插补方法自动出现在 UI"小节 + "未来升级到数据感知禁用(C 方案)"备忘 | 无新代码,纯文档 |

**Reviewer:** 架构 owner(全局视角)。

**Definition of Done:** 1 个 e2e 测试通过;`docs/extensions.md` 含完整扩展指南;**全栈 705 BE + 549 FE 基线仍绿**(本版没有"砍掉测试"的合法理由)。

---

## 4. 关键测试 / 验证策略

### 4.1 契约校验测试(切片 1 + 切片 2)
- 所有 sample fixture 与 schema 校验通过(`jsonschema`)。
- 后端真实产出(endpoint response / `failure_evidence` / `imputation_summary.json`)在生产路径写入时,也跑 schema 校验断言(可以是 pytest fixture 拦截或专用测试)。
- **目的:** 防止后端"实现走偏"于契约。

### 4.2 现有金标 / invariant 仍守门(切片 2)
- 7 个 V1.5.4 金标必须仍 0 drift,**唯一例外** = `imputation.json`,因为 2e 加了 `imputation_summary` artifact —— 需要 regenerate 且改动只能是新增 entry,既有 entry 数据不动。
- V1.5.4 的 6 个 invariant + 1 个 behavior snapshot 必须仍 0 失败。
- 显式失败 invariant 5 **扩展为**同时校验 `failure_evidence.recommended_actions` 符合契约 schema(切片 2d)。

### 4.3 组件单测覆盖(切片 3)
- 每个新组件用 sample fixture 喂数据,断言 DOM / 回调。
- **不引入端到端测试**——切片 3 完全 mock,保证前端工程师可独立工作。

### 4.4 唯一一只端到端集成测试(切片 4)
- "用户选 probit → 失败 → 一键 Re-run with auto → 成功"的完整链路。
- 这是**回归门槛**——证明前后端契约真的对得上。

---

## 5. 成功标准

| # | 标准 | 验证方法 |
|---|---|---|
| 1 | 用户可在 UI 下拉选 `auto`/`ols`/`logit`/`probit`/`poisson`/`negative_binomial`/`panel_ols`/`glm:binomial`/`glm:poisson`/`glm:negative_binomial` 共 10 项 | 切片 3b 组件测试 + 切片 4 e2e |
| 2 | 用户显式选 logit + 数据非 binary → 显示故事卡片(标题、根因、3 个 actions 按钮)+ 点 "Re-run with auto" 一键重跑 | 切片 3c 组件测试 + 切片 4 e2e |
| 3 | 用户在 UI 启用 MICE checkbox → MICE 真的跑 → 结果页显示 `ImputationSummary` 面板("imputed 17 rows × 2 cols ...") | 切片 3d 组件测试 + 切片 2b/2e 后端测试 + 切片 4 e2e |
| 4 | **未来加新 model_type(例如 `arima`)只需后端 `register_model` + 自动出现在 UI**,前端零改 | 切片 4 文档 + 现场演示:在测试 conftest 注册 dummy handler,/capabilities 自动多一个 entry,前端 `<optgroup>` 渲染该 entry(组件测试可覆盖) |
| 5 | **未来加新插补方法(例如 KNN)只需后端 `register_imputation_method` + `imputation_summary.json` 新增 method-specific 字段**,前端 ImputationSummary 加一个 switch case 即可 | 切片 4 文档 |
| 6 | V1.5.4 全部测试仍绿(705 BE + 549 FE + 7 金标 + 6 invariant) | 切片 2/3/4 各自跑 |
| 7 | 1.5.3.2 显式失败契约保留:显式 model_type 失败 → 写 `failed` manifest + 不静默回退 | `test_explicit_model_type_failure_returns_failed_no_silent_fallback` 仍绿 + 切片 4 e2e |

---

## 6. 协作姿势(并行开发的具体玩法)

### 单人开发
按 1 → (2 与 3 交替/并行) → 4 推进。每个切片 commit 多 PR 也保留切片化好处:回滚粒度细、review 单元小。

### 多人开发
1. 你/我做切片 1(契约 + fixture),merge 到 base 分支 `workbench-v1.5.4.1-base`。
2. **甩开两个分支:**
   - `workbench-v1.5.4.1-backend` ← 后端工程师 own,做切片 2 的 5 PR
   - `workbench-v1.5.4.1-frontend` ← 前端工程师 own,做切片 3 的 4 PR
3. 两位**不需要看对方代码**,只看 `docs/api-contracts/` 下的文档。每日同步进度即可。
4. 两支都 merge 回 base 后,**你/我做切片 4**(熟全局者收口集成测试 + 文档)。
5. base 分支 PR → `workbench-v1.5.4`(或直接 `workbench-v1.5.3` / `main`,看 release 策略)。

---

## 7. 修订后路线图位置

| 版本 | 定位 | 与本版关系 |
|---|---|---|
| V1.5.4 | Foundation Refactor(已完成) | base |
| **V1.5.4.1** | **UI ↔ V1.5.3.2 后端能力接通(本版)** | 本版 |
| V1.5.5 | Agent Harness(BYO API key)| 复用本版 `/capabilities`(agent 启动第一件事拉它)、`recommended_actions`(agent 失败时也产 actions) |
| V1.5.6 | Editable / Partial Rerun | 复用本版 `recommended_actions.form_overrides` 机制 + `imputation_summary.output_artifact` 引用 |
| V1.5.7+ | Feature Packs(Panel/DID/RDD/TS/ML) | 注册新 model_handlers / imputation_methods → **自动出现在本版的 UI** = 0 前端改动 |

V1.5.4.1 不只是"接缝",而是为后续三个版本提供可复用的契约位。
