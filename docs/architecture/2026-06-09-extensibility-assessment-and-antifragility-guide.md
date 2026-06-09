# Workbench 可扩展性评估 & 反脆弱开发指南

- **日期：** 2026-06-09
- **基线：** `main` @ `eaaedd8`（含已发布 `v1.5.4.2`）；BE 751 / FE 582 / golden 0-drift
- **目的：** 在"为后期扩展打好基础"的前提下，盘点现状、标定脆弱面、给出后续开发的反脆弱护栏与验收门槛。本文是**方向性 spec/plan**，不是某个 feature 的实现计划——它约束后续每个 feature 的 spec 怎么写。

---

## 0. 当前架构快照

```
请求面 (API/CLI)
  POST /runs (api.py, Form 字段)  ──┐
  CLI run (cli.py)                 ──┤→ run_workflow() ──→ _run_workflow()  [53 行 thin driver]
                                     │                         │
GET /capabilities → build_capabilities() (engine/capabilities.py, schema v2)
                                                               ▼
                          16-stage PIPELINE (engine/stages/__init__.py)
  Source→Cleaning→Profile→Validation→Routing→YType→PreEstimationChecks→
  RoleInference→ExposureDetection→StatisticalTests→Imputation→Estimation→
  Recording→Diagnostics→Reliability→Report
                                                               │
   状态载体: ModelingContext(ctx) + DataHandle(不可变数据+lineage id) + RunEnv
   扩展点: MODEL_REGISTRY (model_type→handler) / IMPUTATION_REGISTRY / AnalysisPack
                                                               ▼
              artifacts (model_results/*, prediction_results/*, staged/*, errors.json)
                                                               ▼
前端: api.ts (类型+fetch) → capabilities/* (manifest 类型+hook) →
      App.tsx (run 表单, 939行) / runResult.tsx (结果页, 710行) / runForm/* / runResult/*
```

**设计基石（V1.5.4 奠定，必须守住）：** 模型"在数据 A 上拟合、却用数据 B 记录诊断/lineage"的 bug 类，已被 `DataHandle` 原子替换 + `ModelingContext` 单一状态载体**结构性消除**。后续任何改动**不得**重新引入"松散的 modeling_frame / model_input_ids / y_type 平行局部变量"。

---

## 1. 已实现 / 失败 / 遇到的困难

### 1.1 已实现（截至 v1.5.4.2）
- **引擎契约层（V1.5.4）：** god-function 解构为 16-stage pipeline + DataHandle/ModelingContext/RunEnv + model_type 键控 registry（`resolve()` 显式优先、未知即 KeyError 不静默回退）。行为冻结，golden 0-drift。
- **能力对齐（V1.5.4.1 + V1.5.4.2）：** 显式 model_type、MICE 插补、结构化失败、Panel entity/time、Panel covariance、Prediction/ML（算法/cv_folds/不平衡采样）+ 结果展示——全部从后端打通到 GUI，由 `GET /capabilities` manifest（schema v2）动态驱动。
- **iOS 设计语言：** 新控件的 `--ios-*` token 体系。

### 1.2 失败 / 放弃
- **无硬失败、无回滚。** IV/2SLS 是**主动延后**（V1.5.4.3），不是失败——因为它是唯一需要往引擎 `CORE_PACK` 注册新估计 handler 的能力，风险最高，被刻意隔离。

### 1.3 遇到的困难（真实，已留疤）
1. **`.venv/bin/pytest` 陷阱：** 裸 entry point 不把 repo 根放进 `sys.path` → `tests.contracts` 导入失败 → 3 个 collection error 伪装成"基线红"。**必须用 `.venv/bin/python -m pytest`。**
2. **跨任务回归只有全量套件能抓：** Task2 加 covariance 透传，悄悄打破了 `test_advanced_econometrics.py` 里一个不接受 `covariance` kwarg 的 `fake_panel_ols` mock；按任务子集跑不出来，全量套件才暴露。
3. **空转测试 / 位置交换测不出：** 多个任务的初版测试"删掉被测接线仍然 green"（covariance 完成态断言、API flat-membership 断言）。靠两阶段 review 的 quality 关卡才发现。
4. **subagent 会撞会话限流：** Task5 drift-guard 子代理中途 429，由主代理补完那段小测试。

> **教训沉淀（已写入护栏 §6）：** 每个后端任务的验收**必须跑全量套件**，不是只跑碰过的文件；每个"接线类"测试必须验证"删掉接线会变红"。

---

## 2. 后期维护需重点关注的关键组件

按"改它会波及全局"排序：

| 组件 | 文件 | 为什么关键 |
|---|---|---|
| **PIPELINE 顺序** | `engine/stages/__init__.py` | 16 stage 的顺序就是契约。插入/重排会改变 `ctx.artifacts` 的可用性时序，且**没有自动 splice**（见 §3.1）。 |
| **ModelingContext / DataHandle** | `engine/context.py` | 全局状态载体 + lineage 原子性的唯一保证。任何新 stage 必须经 `ctx.with_data(DataHandle.of(...))` 换数据，禁止旁路。 |
| **MODEL_REGISTRY + resolve()** | `engine/registry.py`, `engine/stages/estimation.py` | model_type 路由的单一真相。`resolve()` 的"显式优先、未知 KeyError"语义是 1.5.3.2 契约，不能退回静默回退。`_PREDICTION_PASSTHROUGH` 碰撞集是已知 carve-out。 |
| **build_capabilities() manifest** | `engine/capabilities.py` | 前后端的契约面。schema_version 是 break-glass 信号。新增能力组**必须**同时：①后端键 ②drift-guard 测试 ③前端 `Capabilities` 类型 ④契约 schema+sample。 |
| **请求参数链** | `api.py` → `orchestrator.run_workflow/_run_workflow` → `ctx.artifacts["_*"]` | 6 个 V1.5.4.2 参数走这条链，IV 还要再加。链路任一环节 key 写错就静默失效。 |
| **artifact 命名约定** | `prediction.py` (`{model_type}_1`) ↔ `runResult.tsx` 正则 `/^prediction_.*_1$/` | 前端靠命名约定发现产物。改名 = 前端静默不渲染。 |

---

## 3. 当前最脆弱的部分（按风险降序）

### 3.1 🔴 AnalysisPack 的"声明但不接线"扩展点（最危险的扩展陷阱）
`engine/pack.py`：`AnalysisPack` 声明了 `stages / diagnostics / report_blocks / recommended_actions / interpretation_restrictions / rerun_actions`，但 `register_pack()` **只消费 `model_handlers` + `defaults_by_y_type`**，其余字段**被静默忽略**。
- **后果：** 未来维护者写 `AnalysisPack(diagnostics=[MyRule()])` 注册，期待生效——**毫无效果，也无报错**。这是教科书级的"扩展性脆弱面"：API 暗示了能力，实现没兑现。
- 同理 `stages` 字段：注释说"由 importing 模块自己 splice 到 PIPELINE"，即**没有自动插入机制**，靠人手在 estimation.py 里 `register_pack(CORE_PACK)`。

### 3.2 🔴 前端零类型检查（capability 契约无强制）
`frontend/` **没有 `tsconfig.json`**，`package.json` 只有 `dev` + `test`。vitest 经 esbuild 转译**跳过类型检查**。
- **后果：** `api.ts` ↔ `capabilities/types.ts` ↔ 组件之间的类型漂移**只在恰好被测试触达的代码路径**才可能暴露；未覆盖路径的类型错误**静默上线**。整个 manifest 驱动 UI 的正确性赌在"类型手动同步"上，却无 CI 关卡。

### 3.3 🟠 orchestrator.py 仍是 1344 行的杂物抽屉
pipeline driver 虽瘦到 53 行，但模块仍堆着：legacy `run_X` 派发、`_MODEL_TYPE_MAP`、`_PREDICTION_PASSTHROUGH`、manifest 写入、`_validate_requested_model_type`、各种 helper。
- **后果：** 新增模型/路由时容易改错地方；`_PREDICTION_PASSTHROUGH` 这类 carve-out 散落，未来 prediction 类型必须记得加入集合或注册真 handler，否则路由错乱。

### 3.4 🟠 前端大文件
`App.tsx` 939 / `runResult.tsx` 710 / `api.ts` 874。`App.tsx` 一个组件既管项目、又管 run 表单全部 state（现在又加了 7 个 panel/prediction state）、又管提交与校验。
- **后果：** 继续往 run 表单加能力（IV 会再加 instrument 多列输入）会让它更臃肿，state 之间耦合、测试变脆。

### 3.5 🟡 manifest 部分硬编码、无后端真相源
`covariance_options` 直接硬编码（statsmodels cov_type 无集中常量可对齐），`prediction_models/sampling_methods` 已有 drift-guard。covariance 若后端新增/改名，前端不会自动跟随、也无测试拦截。

### 3.6 🟡 校验语义偏保守的占位
`validatePanelPrediction` 用 `isPanelData: false` 硬编码（无可靠的前端 pre-run 面板探测），所以选 Panel OLS 必须手填列。功能正确但 UX 偏紧，且这是个"等更好信号再放松"的占位。

### 3.7 🟡 并发与设计债
- 单 run-slot 守卫（429 "a run in progress"）——多用户/批量场景会卡。
- iOS token 为硬编码 light，与 theme-aware 的 `--bg-canvas` 体系并存（暗色模式下新控件不跟随）。这是已知的双轨设计债。

---

## 4. 可在现有基础上未来升级的方向

| 方向 | 现有基座 | 升级形态 |
|---|---|---|
| **IV / 2SLS（已排期 V1.5.4.3）** | `runner.run_iv_2sls` 已存在但未注册 | 注册进 `CORE_PACK`，manifest 加 instrument 组，前端加 endog/instrument 多列输入 |
| **Feature Packs（Panel FE/RE、DID、RDD、TimeSeries、ML）** | `AnalysisPack` + `register_pack` 已是插件骨架 | 先**把 §3.1 的扩展点真正接线**，再以 pack 形式增量加模型族——这是整个产品的扩展主线 |
| **Agent Harness（BYO API key）** | 引擎已有干净 operation surface（capabilities + 结构化产物 + 结构化失败） | agent 读 manifest → 组 run 请求 → 读 artifact/failure_evidence 自驱。**前提：operation surface 完整**，所以才要先补 GUI gap |
| **可编辑 / 局部 rerun** | `recommended_actions` 一键 rerun 已有雏形；`rerun_actions` 字段已声明（未接线） | 接线 `rerun_actions`，支持改一个参数重跑而非全量 |
| **结果页信息架构 + 暗色统一** | iOS token 已落地（light） | token 改为 theme-aware；结果/历史页信息重排 |
| **批量 / 并发** | 单 slot 守卫 | 队列 + 多 slot |

---

## 5. 需要补充的信息 / 开放问题

1. **Pack 扩展点要不要现在接线？** §3.1 是扩展主线的前置。建议**在 IV(V1.5.4.3) 之前或之中**，把 `stages` 的显式插入语义文档化、把 `diagnostics/rerun_actions` 至少接线一个最小可用版本，否则 feature pack 路线一直踩空。
2. **前端类型门 要不要补？** §3.2。加 `tsconfig.json` + `tsc --noEmit` 的 `typecheck` 脚本 + 纳入门禁，成本低、收益大。**需要你拍板是否纳入每版门禁。**
3. **Agent 的目标 LLM 与边界？** 你定过"只走 API、不打包本地模型"。还需明确：默认 provider、密钥存储位置、agent 可调用的 operation 白名单。
4. **多用户/并发是否在近期路线内？** 决定要不要现在动 run-slot。
5. **IV 的 UI 形态：** instrument/endog 是多列输入，App.tsx 已偏臃肿——IV 是否顺带把 run 表单拆组件（§3.4）？

---

## 6. 反脆弱开发指南：困难点 + 验收门槛

> 原则：**让系统在每次改动中变得更难被同类 bug 击穿**。每个未来工作项都附"困难点"与"硬验收门槛"。门槛不过，不算完成。

### 6.0 通用门禁（每个版本、每个任务都适用）
- **G0-1 全量套件：** `.venv/bin/python -m pytest`（**不是**子集，更不是裸 `pytest`）+ `cd frontend && npx vitest run`，全绿。
- **G0-2 golden 0-drift：** 任何后端改动，`test_engine_golden.py` + `test_lineage_invariants.py` + `test_behavior_snapshot.py` 全过、零漂移；新参数默认值必须**行为惰性**（不传 = 旧行为字节一致）。
- **G0-3 接线测试反验证：** 任何"把 X 接到 Y"的测试，必须验证"删掉接线 → 测试变红"（monkeypatch 捕获实参 / 断言具体值，禁止只断言"完成"）。
- **G0-4 版本隔离：** 新版本独立 worktree + 分支；spec/plan 进 origin/main；发布走 tag + 向前合并拓扑。
- **G0-5 契约同源：** 改 manifest 必须同步 ①后端键 ②drift-guard ③前端类型 ④契约 schema+sample；schema_version 仅在破坏性变更时 bump。

### 6.1 工作项：接线 AnalysisPack 扩展点（建议优先，扩展主线前置）
- **困难点：** `register_pack` 现仅消费 2 个字段；`stages` 无自动 splice（顺序敏感）；`diagnostics/rerun_actions` 等下游消费点要新接。改 PIPELINE 顺序极易破 golden。
- **验收门槛：**
  - 至少 `diagnostics` 与 `rerun_actions` 之一**端到端接线** + 一个最小 pack 的特征测试证明其生效。
  - `stages` 提供**显式插入 API**（如 `stage_position` hint）或**清晰文档 + 校验**：注册带 stages 的 pack 时，若未被 splice 进 PIPELINE 则**显式报错**，而非静默忽略。
  - 反验证：注册一个声明了未接线字段的 pack，断言要么生效、要么**显式失败**——绝不静默吞掉。
  - golden 0-drift（不注册任何新 pack 时行为不变）。

### 6.2 工作项：前端类型门
- **困难点：** 历史代码可能本就有隐藏类型错；首次开 `tsc` 可能爆一批。
- **验收门槛：**
  - 新增 `frontend/tsconfig.json`（`strict` 视存量噪音可分阶段）+ `"typecheck": "tsc --noEmit"` 脚本。
  - `npx tsc --noEmit` 零 error；纳入 G0-1 门禁。
  - 存量 error 若多，允许分期，但**新增/改动文件必须零 error**。

### 6.3 工作项：IV / 2SLS（V1.5.4.3）
- **困难点：** 唯一要往 `CORE_PACK` 注册**新估计 handler** 的能力 → 直接进 golden 敏感区；instrument/endog 是多列输入，App.tsx 已臃肿；`run_iv_2sls` 已存在但未走引擎路径，需确认与 `resolve()`/passthrough 的交互。
- **验收门槛：**
  - handler 注册后，**所有现有 golden 0-drift**（IV 不在默认路径，不得影响既有快照）；新增 IV 专属 golden。
  - 端到端：API 收 instrument/endog → `ctx.artifacts` → 引擎拟合 → 产物可 GET（仿 Task6 e2e）。
  - manifest 加 IV 组 + drift-guard（若有后端真相源）；前端类型 + 契约 schema 同步。
  - 非法规格（缺 instrument / endog 与 instrument 数不匹配）返回**结构化 failed**，不崩。
  - 反验证：IV 接线测试删接线即红。

### 6.4 工作项：run 表单组件化（配合 IV，缓解 §3.4）
- **困难点：** App.tsx 现有 7+ 新 state 与提交/校验耦合；拆分不能破坏现有 38 个 App 测试。
- **验收门槛：** 抽出独立子组件后，现有 App 测试**不放松断言**即通过；新组件各有单测；提交链路 e2e 不变。

### 6.5 工作项：orchestrator.py 减负（机会性，非阻塞）
- **困难点：** 1344 行混杂；`_PREDICTION_PASSTHROUGH` 等 carve-out 散落，挪动易错。
- **验收门槛：** 仅做**行为冻结**式拆分（golden 0-drift）；把 legacy 派发/carve-out 集中到命名清晰的模块；不引入新行为。**任何涉及 `_PREDICTION_PASSTHROUGH` 的改动**附测试证明 prediction 类型路由不变。

### 6.6 工作项：Agent Harness（远期）
- **困难点：** operation surface 必须先完整（这正是先补 GUI gap 的原因）；密钥安全；agent 误操作边界。
- **验收门槛（前置 gate）：** 进入前先确认——所有计量能力都能经 manifest 发现、经结构化产物读取、经结构化失败恢复；否则 agent 会驱动一个它够不到的面。Operation 白名单 + 密钥不落盘日志 + 干跑模式。

---

## 7. 一句话总线
**先把"声明了却没接线"的扩展点（AnalysisPack §3.1）和"契约却无门"的类型面（前端 §3.2）补成真护栏，再沿 pack 路线增量加能力（IV→feature packs→agent）。** 每一步用 §6 的反验证门槛，确保系统每次改动后更难被同类 bug 击穿，而不是更脆。
