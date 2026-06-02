# V1.5.4 — Engine Decomposition + Extension Contract（设计稿）

> **定位：Foundation Refactor / Engine Contract Layer。**
> 目标不是加功能，而是把现有 workflow 从一个 ~860 行事务脚本（`orchestrator._run_workflow`），重构成**可测试、可注册、可被 agent 调用**的引擎内核。
>
> **成功的样子：用户看起来什么都没变，但内部状态契约彻底变稳。**
>
> 日期：2026-06-02 ｜ Base：`workbench-v1.5.3`（已含 PR #9 merge 的 1.5.3.1 后端）｜ 铁律：独立 worktree `.worktrees/workbench-v1.5.4` + 独立分支 `workbench-v1.5.4` + 独立 venv。

---

## 0. 背景与病根

`_run_workflow`（`backend/workbench/orchestrator.py:377` → `:1236`，~860 行）是一个线性事务脚本，跨阶段状态以**游离局部变量**穿行：`modeling_frame`、`model_input_ids`、`y_type`、`primary_type`、`exposure_col`。

核心 bug 风险（结构性，不是靠多写测试能根治的）：

> **模型用了 A 数据，但 diagnostics / report / lineage 写了 B 数据。**

根因示例：
```python
modeling_frame = imputed_frame
model_input_ids = ["imputed_dataset"]   # ← 两个分离变量，任何新分支可能只改一个
```
现状 provenance 还是每次手写字符串：
```python
register_artifact(run_root, "cleaned_dataset", cleaned_path, "processed_data", "cleaning", raw_inputs)
#                            ↑ id 手敲                                                 ↑ 来源手敲
```

**根治方向 = 把漂移的状态物理绑定成单一对象**，让模型 / 诊断 / 报告 / lineage 全部从同一处读取，做到 *correct by construction*。

---

## 1. 范围边界（必须非常清楚）

### V1.5.4 **要**做
1. 引入 `DataHandle`（数据本体 + 来源身份焊死）。
2. 引入 `ModelingContext`（收拢跨阶段状态）。
3. 引入 stage pipeline（具名阶段，统一形状，可独立测）。
4. 引入 model registry（替换 `if y_type==... elif ...`）。
5. 把 `orchestrator.py` 从"核心逻辑所在地"降级为"调度壳"（`_run_workflow` 瘦成 <~80 行驱动）。
6. 建立功能包注册机制（`AnalysisPack` 形状 + 进程内注册）。
7. 新增 lineage consistency invariant 等结构性测试。

### V1.5.4 **不**做
1. 不做 AI agent（→ V1.5.5）。
2. 不做 editable / partial rerun（→ V1.5.6）。
3. 不大规模加新模型 / 新统计逻辑。
4. 不改前端用户体验（FE 549 未动，仅须仍通过）。
5. 不改变现有报告语义、不改 API surface。
6. 不重写全部统计逻辑；`_check_*` / `_detect_*` helper 保持原样，只被对应阶段调用。
7. 不追求一次把 orchestrator 变完美；不实现 pack 的 report_blocks / rerun / interpretation 运行机制（仅声明字段）。
8. 不做动态 / 第三方插件加载、entry-points 发现、沙箱（→ 后话）。

---

## 2. 核心设计

### 2.1 `DataHandle` — 数据 + 身份焊死

```python
@dataclass(frozen=True)
class DataHandle:
    frame: pd.DataFrame
    artifact_id: str                 # "cleaned_dataset" / "imputed_dataset"
    provenance: tuple[str, ...]       # 写 lineage 时只能引用这个（tuple，不可变）
    schema_fingerprint: str | None = None
    row_count: int | None = None
    column_count: int | None = None
```

**硬规则：模型层禁止裸传 `pd.DataFrame`。**
```python
fit_model(data=ctx.data)        # ✅ 唯一允许
fit_model(modeling_frame)       # ❌ 禁止
```
imputation 那两行游离赋值消失，变成一步原子替换：
```python
ctx = ctx.with_data(DataHandle(frame=imputed_frame, artifact_id="imputed_dataset", provenance=(...)))
```

### 2.2 `ModelingContext` — 收拢跨阶段状态

```python
@dataclass
class ModelingContext:
    data: DataHandle                  # ← 取代 modeling_frame + model_input_ids
    y_col: str
    x_cols: list[str]
    requested_model_type: str | None = None   # 1.5.3.2 显式路由契约（见 2.4 必修）
    y_type: str | None = None
    primary_type: str | None = None
    exposure_col: str | None = None
    roles: dict | None = None
    diagnostics: list | None = None
    artifacts: dict | None = None
```
原来散落在 `_run_workflow` 的 `modeling_frame / model_input_ids / y_type / primary_type / exposure_col` 全部收进这里。

**ctx 保持"偏数据、可纯构造"。** 副作用依赖（run_root / recorder / on_step）不进 ctx，收进单独注入的 `RunEnv`：
```python
@dataclass
class RunEnv:
    run_root: Path
    run_id: str
    recorder: GraphRecorder
    on_step: Callable[[str, str, str], None] | None = None
```
这样单测可直接 `ModelingContext(data=fake_handle, ...)`，无须起真实 run。

### 2.3 Stage pipeline — 统一形状

```python
class Stage(Protocol):
    name: str
    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext: ...
```

阶段清单（按代码已有天然边界；补回用户清单漏掉的 Cleaning / Validation）：

| Stage | 职责（对应现有代码） |
|---|---|
| `SourceStage` | ingest + schema + 记 raw（:396–412） |
| `CleaningStage` | clean + 写 cleaning_actions / cleaned_dataset（:414–437） |
| `ProfileStage` | profile（:439–451） |
| `ValidationStage` | validate；**含 `blocked` 早退**（:453–472） |
| `RoutingStage` | classify_dataset（:474–488） |
| `YTypeStage` | y_type 检测（含显式 model_type 的 y_type 映射） |
| `RoleInferenceStage` | infer_variable_roles |
| `ExposureDetectionStage` | exposure candidate 检测 / 选择 |
| `ImputationStage` | imputation → 产出新建模 `DataHandle`（条件触发） |
| `ModelEstimationStage` | **model registry 分发** → primary model |
| `DiagnosticsStage` | diagnostics + variable importance |
| `ReportStage` | report_view_model / reporting |
| `ReliabilityStage` | reliability / rare-event caveat |

每个 stage 可单独测试，无须每次跑完整 `_run_workflow`。早退（blocked / failed）通过 ctx 状态或专用信号短路后续阶段。

### 2.4 Model registry — ⚠️ 必修：显式 model_type 优先

**注册表按 `model_type` 键**，另存 `y_type → 默认 model_type` 映射。**不可纯按 y_type 键**——那会抹掉 1.5.3.2 刚 merge 的"显式 model_type 路由 + 失败结构化 `failed`、不静默回退"契约。

```python
@dataclass
class ModelHandler:
    model_type: str             # "ols" / "logit" / "poisson_rate" / ...
    model_id: str
    serves_y_types: tuple[str, ...]
    def fit(self, ctx: ModelingContext, env: RunEnv) -> ModelResult: ...

MODEL_REGISTRY: dict[str, ModelHandler] = {}
DEFAULT_BY_Y_TYPE: dict[str, str] = {"continuous": "ols", "binary": "logit", "count": "poisson_rate", ...}

def resolve(ctx) -> ModelHandler:
    if ctx.requested_model_type:                  # 显式优先（1.5.3.2 契约）
        return MODEL_REGISTRY[ctx.requested_model_type]   # 不匹配/拟合失败 → 结构化 failed，不回退
    return MODEL_REGISTRY[DEFAULT_BY_Y_TYPE[ctx.y_type]]  # auto 才走 y_type 默认
```
`ModelEstimationStage` 用 `handler = resolve(ctx); result = handler.fit(ctx, env)` 取代 if/elif。
**加模型（fixed effects / cluster SE / DID / event study / RDD / ARIMA / Lasso / RF / XGBoost…）= 注册 handler，不碰 `_run_workflow`。**

### 2.5 功能包注册机制（AnalysisPack）

定整个形状，但 **V1.5.4 完整走通的扩展点 = `model_handlers` + `stages`**（即"加模型 / 加阶段"零改主函数，并有测试证明）。`diagnostics` 仅做到"内核把现有 `_check_*` 作为 core pack 的诊断登记进来"——**不**把现有诊断逻辑重写成形式化 `DiagnosticRule` 引擎（与 §1「helper 保持原样」一致，留给后续）。其余字段（report_blocks / recommended_actions / interpretation_restrictions / rerun_actions）仅声明，留空给 V1.5.6+。

```python
@dataclass
class AnalysisPack:
    pack_id: str
    stages: list[Stage] = field(default_factory=list)
    model_handlers: list[ModelHandler] = field(default_factory=list)
    diagnostics: list[DiagnosticRule] = field(default_factory=list)
    # —— 以下声明位，V1.5.4 不实现运行机制（→ V1.5.6+ / agent）——
    report_blocks: list = field(default_factory=list)
    recommended_actions: list = field(default_factory=list)
    interpretation_restrictions: list = field(default_factory=list)
    rerun_actions: list = field(default_factory=list)

def register_pack(pack: AnalysisPack) -> None: ...   # import 时注册
```
**Dogfood：内核自身通过该机制注册**（内置模型/诊断打包成 core pack），证明契约可用、不是纸面。契约写入 `docs/extensions.md`：pack 提供什么、何时注册、收到的 (ctx, env)、必须写哪些 artifact。

---

## 3. 重构安全策略（最关键，860 行行为不变重构）

1. **先写金标（characterization）测试**：动代码前，对代表性 fixture（continuous / binary / count / panel + 一个 blocked + 一个 imputation + 一个**显式 model_type**）抓全套产物（manifest、lineage、各 model_result、errors、记录的图），断言重构后**结构/数值一致**。
2. **一次只抽一个阶段**，每抽完跑全套 BE + 金标，绿了才抽下一个。绝不连抽两步。
3. **ctx / DataHandle 增量引入**：先包一层（老局部变量做 `ctx.data.frame` 别名），全绿后再删游离变量。
4. **注册表最后切**：阶段抽完才把 if/elif 换成 `resolve`，验证 model_id / 数值结果完全一致，并锁住显式 model_type 失败路径。

---

## 4. 新增测试（拆了也放心的前提）

1. **Lineage invariant test**：模型结果 / diagnostics / report / recorder 记录的输入 = 同一个 `ctx.data.artifact_id`。
   ```python
   assert model_result.input_data_id == ctx.data.artifact_id
   assert diagnostic_summary.input_data_id == ctx.data.artifact_id
   assert report_metadata.input_data_id == ctx.data.artifact_id
   ```
2. **Imputation 后一致性**：原始有缺失 → imputation 生成新 frame → 模型用 imputed → lineage 写 `imputed_dataset` → report 不再误引 `cleaned_dataset`。（当前最怕的 bug 类）
3. **Dummy coding 后一致性**：`x_region_code` 被 dummy-coded → 模型输入列变 → coefficient risk 按**原始变量**聚合 → report 不把 dummy term 当原始连续变量解释。
4. **Exposure warning 一致性**（诚实记录现状）：检测到 exposure → 模型仍把它当普通 predictor（offset 未真正实现）→ diagnostics/report 明确 warning → lineage **不假装**它被 offset 处理。
5. **Behavior snapshot test**：同输入、同 Y/X，重构前后主要数值一致——coefficient、p-value、VIF、warning code、diagnostic summary、report block existence。
6. **显式 model_type 失败 → `failed` 不回退**（锁 1.5.3.2 契约，见 2.4）。

---

## 5. 成功标准

- BE 672 通过 **+ 新金标 / 一致性测试通过**；FE 549 通过（未动）。
- `_run_workflow` 从 ~860 行 → 瘦驱动（<~80 行）；阶段进独立聚焦模块。
- **新模型仅靠注册 handler 加入、不改 `_run_workflow`**（dummy/alias 测试证明）。
- 内核通过 `register_pack` 自注册（dogfood）；`docs/extensions.md` 写清契约。
- CLI smoke ok / 无 pickle / 无 extras 时 lazy（665 pass + 7 skip）仍成立。

---

## 6. 修订后路线图

| 版本 | 定位 | 核心目标 |
|---|---|---|
| **V1.5.4** | Foundation Refactor | 拆 orchestrator、绑定 DataHandle、stage pipeline、model registry、pack 注册机制 |
| **V1.5.5** | Agent Harness | 用户自带 OpenAI / Anthropic / Gemini API key，agent 通过稳定 operation surface 调用分析/诊断/报告 |
| **V1.5.6** | Editable / Partial Rerun | 基于 ctx + artifact graph + stage contract 做局部重跑 |
| **V1.5.7+** | Feature Packs | Panel / DID / RDD / Time Series / ML 等按 pack 接入 |
