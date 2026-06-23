# Workbench v1.6.1 — 真·谱系图操作层 Slice 2：跨 run 血缘森林 + 节点级 Merkle 增量

> 设计文档 / Spec
> 日期：2026-06-23
> Base：origin/main `61d45ef`（= tag `v1.6.0`）
> Worktree/branch：`.worktrees/workbench-v1.6.1` / `workbench-v1.6.1`
> 状态：草案（待 PM 复审 → writing-plans）

---

## 0. 一页纸结论

把执行模型从 **“run 级全量、每跑一条孤立新链”** 升级为 **“节点级 Merkle 内容寻址增量”**，让血缘图第一次成为**真正持久、可 fork / 可回滚 / 可跨 run 回溯**的操作面。

- **第一性原理**：节点是内容寻址的原子单元，身份 = `H(全部输入身份 ⊕ 自己算子规格 ⊕ PIPELINE_VERSION)`（Merkle）。改一个节点的算子，只有它和后代哈希变；上游不变 = 命中缓存 = **原样复用，绝不重算/复制**。
- **本版交付（Slice 2）**：节点结果 CAS + per-node Merkle + 增量重跑（复用上游、只重算分歧前沿）+ head-set 图契约 + FE 森林渲染 + 编辑 model 节点（control_factory）原地 fork 出分支 + 任意节点跨 run 回溯 + 激活祖先 head 回滚。
- **本版不实现、但契约必须留口**：任意 DAG 拓扑（模型输出再入）、per-stage/code 可编辑节点、时间序列/波动率方法包、节点 AskAI / 报告撰写器、并发解除、CAS 的 GC。这些通过 **S1–S13 预留功能槽** 在契约层留好，绝不挖坑。

本版被四份真实 Stata 作业（单位根 / ARIMA-ARCH / 随机游走-EMH / LPM-Probit-Logit）反复验证，且这四份代码的“手动状态管理惨状”反向证明 node-result CAS 方向正确。

---

## 1. 背景与动机

### 1.1 现状（v1.6.0 已发）

- origin/main = tag `v1.6.0` = `61d45ef`，门禁全绿：BE 1170 / golden 23 0-drift / FE 637 / tsc 0。
- v1.6.0 是 **“可编辑算子的纯后端契约”（操作层 Slice 1，窄竖切）**：仅 model 节点可 end-to-end 编辑；`POST /runs/{id}/rerun` 按 manifest 校验覆盖参数 → 生成**全新不可变 run**（`rerun_of` 指针记血缘）；`GET /graph` 响应时注入 `editable_schema`；内容寻址 upload（sha256）；`dag_hash`/`override_hash`/`PIPELINE_VERSION` 哈希**桩（只定义、未实现缓存）**。
- 前端编辑面（`OperationSection`）仍只读、动作 `rerunFromNode` disabled；图是每 run 一张的只读快照。

### 1.2 为什么不能简单接线（本版立项的根因）

最初计划“前端接线片”：编辑 model 节点 → 重跑 → 跳转到新 run。**被否决**，理由：每次重跑甩出孤立新链，**不能 fork、不能回滚、任意节点无法追溯跨重跑的完整血缘**，与现有表单操作无本质区别。

判定性需求（用户原话比方）：

> 数据集 a 清洗得 b、变换得 c，c 上选 model1 出结果。**切换 model2/model3 时，c 及之前的节点还是原来那套，压根不需要重开一条链路再复制跑一遍 a→b→c。**

要求：**第一性原理、追求极致性能、为后期扩展性打地基、不要畏手畏脚。** 这等于要求**节点级增量复用**——切模型时上游原样复用、绝不重算/复制，只在分歧点往下重算。

### 1.3 北极星（来自 `handoff/prototype.html` Vision 2）

血缘图 = 核心操作面：图上每个节点可看、可改算子/代码、可“从该处向下游重跑”；决策显式记录；AI 用户主动触发；报告由 AI 起草并保留对节点的 cite 引用。本版是迈向该北极星的 Slice 2（Slice 1 = v1.6.0）。

---

## 2. 第一性原理

> **节点是内容寻址（content-addressable）的原子单元。**
> `node_hash = H(canonicalize([sorted(parent_node_hashes), op_spec, PIPELINE_VERSION]))`
> 改一个节点的 `op_spec`，仅它与其全部后代的 `node_hash` 变化；上游 `node_hash` 不变 ⇒ 命中节点结果缓存 ⇒ **直接复用既有产物，不重算、不复制**。

这是一棵 **Merkle DAG**。用户的 a→b→c 例子不是 UX 技巧，**它就是 Merkle-diff 增量执行**。两个 run 共享 a→b→c，是因为它们字面指向**同一批 `node_hash` 节点（同一份存储）**，而非模糊匹配。跨 run 血缘森林由此成为这张内容寻址 DAG 的**天然形状**，不是前端缝合的 hack。

v1.6.0 已把内容寻址用于 upload（sha256）+ 定义了 `canonicalize` / `dag_hash`(run 级) / `PIPELINE_VERSION`。本版把内容寻址**从 upload 一层下沉到每个节点**。

---

## 3. 架构（三层，`node_hash` 是贯穿三层的通用语）

### 3.1 存储层 — 节点结果 CAS（新建）

- 内容：`node_hash → NodeResult{ artifacts(parquet/json/html), summary, decision, stats, status }`。
- 跨 run、跨 pipeline；**幂等写**（同 hash = 同内容）。
- 位置：`<project_root>/data/node_results/<node_hash>/...`（与 v1.6.0 `data/uploads/<sha256>` 同构，生命周期与 run 解耦）。
- **head 引用计数**：每个 head（run）记录其根节点 hash；GC 按 live head 引用计数实现（**本版只建引用账本、留 GC 口，不实现 GC**）。
- 与现有 run 目录的关系：现 run 目录（`processed/cleaned_dataset.parquet`、`model_results/{id}.json`、`reports/report.html`）改为**指向 CAS 的引用**（payload_ref 由“run 内相对路径”升级为“node_hash + 产物名”），而非各自复制一份。Legacy run 保留旧布局（见 §8 兼容）。

### 3.2 引擎层 — 增量缓存（改造现有 stage 管线）

现状（已核实）：`_run_workflow` 是 `for stage in PIPELINE: ctx = stage.run(ctx, env)`，16 段串行、`ctx` 原地流转；图节点由末尾 `RecordingStage` 一次性记录（`stage:raw / stage:cleaned / var:* / model:{id} / report:html`）。**无任何 per-stage 缓存边界。**

改造：在 stage 执行外包一层 **hash → 查缓存 → 命中跳过 / 未命中执行入库**：

1. 拓扑序遍历，为每个**缓存单元**算 `node_hash`（输入 hash + 该单元 op_spec + PIPELINE_VERSION）。
2. 命中 CAS → 跳过执行，直接以缓存产物充当该单元输出（重建 `DataHandle`/artifact 引用）。
3. 未命中 → 执行，将产物**写入 CAS**（按 node_hash），并记账。
4. 编辑 model 的 `op_spec` → 其 hash 变 → model 及下游未命中 → **只重算分歧前沿**；a/b/c 命中复用。

**缓存粒度（本版决定）**：按 **stage-output 粒度**（粗，足以交付 a→b→c 复用），不做 node 级细化（留后续 Slice）。`RecordingStage` 增加“图节点 ↔ 产生它的缓存单元”映射，使图节点能映回 node_hash。

### 3.3 契约 / 前端层 — head-set 图 + 森林画布（改造）

**图契约**从“每 run 一张 graph.json”升级为 head-set 形态：

```
GET /runs/{id}/graph  →  {
  nodes: { <node_hash>: NodeView },        // 按 hash 去重，跨 run 共享前缀只出现一次
  edges: [...],
  heads: [ { run_id, head_node_hash, from_node, rerun_of, rerun_reason, status, created_at } ],
  schema_version: <bumped>,
  legacy: <bool>                            // 旧 run 退化标记
}
```

- 服务端按 run 的 rerun 家族（见 §6 API）聚合出该家族全部 head + 其可达节点的并集 DAG。
- 仍遵 v1.6.0“serve-layer decorate-only”：CAS / 家族聚合在**响应时**计算，**绝不写回 graph.json**。

**FE 森林画布**：渲染 head-set 并集 DAG——共享前缀只画一次、分歧处分叉；按 head 着色 / 标注；选中节点 → 跨 run 回溯（沿 parent hash 游走）；激活祖先 head = 回滚；编辑 model 节点提交 → 在森林里原地长出子分支（不跳转走人）。

---

## 4. Route 选择理由（Route 2 演进，非 Route 1 重建）

| | Route 1 重建 | **Route 2 演进（采纳）** |
|---|---|---|
| 做法 | 照 prototype `schema.sql` 引入持久 `Pipeline` 一等实体，节点 PATCH、run 从属 pipeline，重写数据模型 | 复用 v1.6.0 不可变 run + `rerun_of` + 内容寻址地基，**把内容寻址从 upload 下沉到每个节点** |
| 工量/风险 | 最大；重写数据模型，golden 风险最高，周期最长 | 中；不重写数据模型，复用现有 stage 管线 + DataHandle 交接 |
| 扩展性 | 忠实原型 | 同样到达原型 UX；CAS 立住后 per-stage 编辑 / AI / 并发都只是往这张 DAG 上挂 |

**结论**：Route 2 用更低风险到达同一目标，每一步复用已验证地基（`rerun_of`/`from_node`/`PIPELINE_VERSION`/`canonicalize` 全现成），符合“为扩展性打地基且不破坏 golden”的一贯纪律。

---

## 5. Architect ⨯ BE ⨯ FE 对抗性交叉论证

| # | 提出方 | 风险 / 反对 | 处置（钉进架构） |
|---|---|---|---|
| R1 | BE | **缓存中毒**：节点执行非纯函数（bootstrap/MICE/RF/MLE 的 RNG、库版本）→ 复用错结果 | seed 进 `op_spec`；`PIPELINE_VERSION` 含库版本，升级即全失效；**golden 0-drift 已证全管线确定性**=缓存正确性现成保证 |
| R2 | Architect | **缓存粒度**：执行单元是 stage、图节点事后记录，两者不对齐 | 本版按 stage-output 粒度缓存；`RecordingStage` 建 node↔缓存单元映射；node 级细化留后 |
| R3 | FE | **共享前缀如何“同一份”**：子 run 现重新物化 a/b/c 成新 node id | 用 `node_hash` 做身份，同 hash=同节点，FE 按 hash 去重、**不做模糊匹配**；要求 BE 把 run 级 `dag_hash` 升级为 per-node Merkle |
| R4 | BE | **CAS 无限膨胀** | 按 live head 引用计数；GC 本版只留口不实现（v1.6.0 upload 生命周期解耦先例） |
| R5 | FE | **legacy run 无 node_hash** 致森林画布崩 | 退化：旧 run = 一个不透明 head，仍走旧 graph.json 单独渲染；不破坏现有 run detail |
| R6 | Architect | **单 run-slot（429）** 撞多分支并跑 | 增量更快、撞得更少；多分支并行=并发片（后）；本版单节点 fork 串行即可 |
| R7 | BE | **确定性边界**：文件路径/时间戳/绝对路径混入产物破坏 hash 幂等 | 产物按 node_hash 命名、剥离运行期元数据（`started_at` 等不进 hash）；复用 `canonicalize`（sorted+compact）|
| R8 | BE（MLE 专项）| ARIMA/ARCH/GARCH 等**迭代优化**模型 + `capture` 容错 | 优化器配置（起始值/容差/最大迭代）+ 收敛状态进 `op_spec`/hash；fan-out 里 per-candidate 失败被跳过、reducer 容忍（扩展现有 `MODEL_FIT_FAILED`）|

三方一致结论：**Route 2 演进可行且正确**，是“为扩展性打地基”的正解。

---

## 6. 本版范围（Slice 2，诚实边界）

含**增量复用脊柱**的最小自洽端到端，少任一条即退回玩具：

**做（v1.6.1）**
1. 节点结果 CAS + per-node Merkle 哈希（覆盖现有 stage-output 粒度）。
2. 增量重跑：复用上游、只重算分歧前沿（= a→b→c 要求）。
3. head-set 图契约 + 家族聚合接口。
4. FE 森林画布渲染（共享前缀去重、分歧分叉、按 head 着色）。
5. 编辑 model 节点（**control_factory 间接层**）→ 提交 → 原地 fork 出子分支（不跳转）。
6. 任意节点跨 run 回溯（parent-hash 游走）+ 激活祖先 head 回滚。
7. 后端把 `run_inputs` 实际值回填进 `editable_schema.value`（v1.6.0 IMPL-NOTES 延后项）。

**API（新增/改造）**
- `GET /runs/{id}/graph` → 返回家族 head-set 并集 DAG（按 node_hash）。
- `GET /runs/{id}/family`（或并入上）→ run + 全部 `rerun_of` 后代/祖先家族。
- `POST /runs/{id}/rerun` → 复用 v1.6.0 契约，但执行走增量缓存；返回 child head，FE 原地长分支。

**不做（明确延后，见 §10 路线图）**
- 任意 DAG 拓扑 / 模型输出再入（per-stage/code 可编辑节点）。
- 时间序列 / 波动率 / 边际效应等方法（独立方法包程序）。
- 节点 AskAI / 报告撰写器（Agent Harness，原型 M3）。
- 并发解除单 slot / 多人协作 / 审计（原型 M4）。
- CAS 的 GC（只留引用计数口）。

---

## 7. 具体重构细则（代码锚定）

### 7.1 后端

- `lineage/hashing.py`：`dag_hash`(run 级) → 新增 `node_hash(parent_hashes, op_spec, PIPELINE_VERSION)`（per-node Merkle）；保留旧函数兼容。
- `lineage/node_store.py`（新）：节点结果 CAS（写/读/存在性/引用计数账本），镜像 `lineage/upload_store.py` 结构（`data/node_results/<hash>/`）。
- `orchestrator/__init__.py` 的 `_run_workflow`：在 `for stage in PIPELINE` 外包缓存层（hash→命中跳过/未命中执行入库）；保持 stage 实现不变（行为冻结，golden 0-drift）。
- `engine/stages/recording.py`：建“图节点 ↔ 缓存单元/node_hash”映射，`payload_ref` 升级为指向 CAS。
- `engine/context.py` `DataHandle`：增加从缓存产物重建 handle 的能力（命中时不重算但要还原 frame/artifact 引用）。
- `api.py`：`_annotate_editable_nodes` 增加 `run_inputs` 实际值回填到 `editable_schema.value`；`get_run_graph` 升级为家族聚合 + head-set；新增 family 解析。
- `graph_store.py`：保持 graph.json 单 run 持久化不变；家族聚合在 serve 层做（decorate-only）。

### 7.2 前端

- `lineage/api/graphViewTypes.ts`：`EditableControl` 与后端对齐（补 `role` / `required` / `columns` kind 等，纠正 v1.5.0 过期形）；新增 head-set / NodeView(by hash) / heads 类型。
- `lineage/api/graphAdapter.ts`：从“per-run graph → GraphViewModel”升级为“head-set → 并集 DAG（按 node_hash 去重）”；映射 `editable_schema`。
- `lineage/controls/controlFactory.tsx`（新）：`editable_schema → control_factory → 控件`（见 §8 硬约束，**绝不按 kind 直写 JSX switch**）。
- `lineage/detail/sections/OperationSection.tsx`：只读 → 可编辑（走 control_factory），接 `/rerun`。
- `workbench/registry/actionRegistry.ts`：点亮 `rerunFromNode`。
- 森林画布：扩展现有 `lineage/graph/GraphCanvas` 渲染 head-set 并集 DAG（按 head 着色、分叉、选中回溯、激活祖先 head 回滚）。
- `api.ts`：新增 `rerunFromNode` client + family 拉取。

---

## 8. control_factory 硬约束（已锁定，必须守住）

1. 节点编辑面渲染**必须走 control_factory 间接层**：`editable_schema → control_factory → UI 控件`，**绝不**按 kind 直写 JSX switch——这样未来 AI 生成控件 / 条件控件 / 动态可见性都能被接住。
2. 沿用 **manifest 驱动**，**零 per-estimator 硬编码**（后端已是，前端照此）。
3. day-1 只 model 节点可编辑；并发仍单 slot（多节点 rerun 撞 429，留并发片）。
4. 控件描述需含**条件可见性谓词槽**（`visible_when` / `available_when`，见 S4）——为 schema 条件操作留口。
5. control_factory 本体须能**结构上接所有 kind**（radio/select/multiselect/slider/text/textarea/toggle/columns），即便 day-1 仅启用部分；启用与否取决于数据源是否在手，不影响工厂完整性。

---

## 9. 经验与教训：四份金标准验收用例

四份真实 Stata 作业被用来从消费方压测架构。它们的统一结论：**架构（v1.6.1）被反复验证；真正缺的是方法库纵深与节点模型泛化；node-result CAS 被“手动状态管理惨状”反向证明方向正确。**

### 9.1 用例 A — HW9 单位根（UK 利差）
TWFE 之外的时序入门：`tsset`、滞后/差分（`L. D.`）、ACF/PACF（`corrgram`）、AR(1)（`regress x L.x`）、手搓 Dickey-Fuller。
**暴露**：整个时间序列纵深为零；节点 taxonomy 需泛化到非回归节点；code-node 逃生舱（手搓 ρ=1 检验）。

### 9.2 用例 B — Rupee ARIMA-ARCH/GARCH 波动率
ARIMA 网格选 AICc → 残差 → ARCH 网格 → 条件方差 → 预测区间 → 回测。
**暴露（最深）**：① **模型输出（残差/条件方差）反复再入管线当下游输入** → 固定 16 段 `model→report` 线性管线表达不了，图契约**绝不能写死线性拓扑**；② fan-out 扫描 + reducer 选择节点；③ 用户**三次 `clear all` 重载 RESI1** = CAS 价值铁证；④ MLE 确定性=缓存前提（R8）。

### 9.3 用例 C — Russell 随机游走 / 弱式 EMH
Today vs Yesterday 朴素预测 MSE 比较、回归检验随机游走（`test b=1` / `test _cons=0`）、收益率 + 自相关。
**暴露**：① schema 条件 / 数据自省驱动操作（`capture confirm string/variable`、列优先回退）→ 印证硬约束 #4 条件控件；② **同一数据多重时间排序**（交易日 vs 日历 `tsset` 切换）→ 时间排序是可多实例的参数化节点；③ 列聚合→广播（去均值）；④ 结构化后估计检验槽（`test`）；⑤ 断言节点（`isid`）；⑥ `preserve/restore` = CAS 价值第三铁证。

### 9.4 用例 D — NYC Schools LPM / Probit / Logit + 边际效应
同 y/X 切 LPM→Probit→Logit 比较 + `margins, dydx`。
**暴露**：① **这是 model-type fork 最干净的验证**，且证明 **model 节点是正确的第一个可编辑节点**（切模型类型是高频真操作，非玩具）；② **域内方法缺口：边际效应 `margins` 确认缺失**（已发 logit/probit 半成品，statsmodels 现成、补起来不贵但高频）；③ 异质模型比较 → **reducer 须对齐语义可比量（AME），不比原始系数**；④ 设计矩阵/公式规格层（`i.` 因子 / 交互 / in-formula `C()`/`I()`）；⑤ 会话转录 artifact（smcl→PDF）区别于分析报告。

---

## 10. 缺失算子清单（方法库，与本版架构正交）

> 这些**不是本版实现的方法**，是未来分两条线排期的方法库内容；列此为路线锚点 + 验证 S1–S13 留口是否充分。

**线 1：时间序列 / 金融计量纵深（异域，大、分层，像 DID v1.5.5→1.5.9）**
- 数据/IO：`tsset`（日/季频）、字符串日期解析、`.dta`/Excel 输入、图/数据集导出、smcl→PDF 转录。
- 算子：滞后/差分/超前（`L. D. F.`）、任意公式派生变量、列聚合→广播（去均值）、算术收益率。
- 诊断：ACF/PACF/Ljung-Box、平方残差 ACF（ARCH 效应）、`corrgram`。
- 检验：Dickey-Fuller/ADF/KPSS/PP 单位根、正态性（sktest/swilk）、单样本 `ttest`。
- 模型：ARIMA(p,d,q)、ARCH(q)/GARCH(p,q)。
- 后处理：`predict` 残差/拟合/条件方差/一步预测、时变方差预测区间、条件分位、标准化残差。
- 选择/评估：AIC/AICc + 网格扫描 harness、朴素预测 MSE 比较、区间回测覆盖失败率。
- 可视化：tsline、scatter+lfit、histogram+normal、boxplot、qnorm/pnorm。

**线 2：已覆盖域的解释/诊断层补全（域内，小而高频，可能更急）**
- **边际效应 `margins, dydx`（AME/MEM）** ← 头号。
- 设计矩阵/公式规格（因子 `i.`、交互、in-formula `C()`/`I()`）。
- LPM 诊断（`predict, xb` + 数 ŷ∉[0,1]）。
- 结构化后估计假设检验（`test 系数=值` Wald）。
- 用户断言节点（`isid`/非空/单调）。

---

## 11. 需预留的功能槽（S1–S13，本版“设计时绝不挖坑”的硬要求）

> 这些**不是本版实现**，是 v1.6.1 重做图契约 / 节点模型 / editable_schema 时**必须留好的口**，缺一个未来就要返工。

| # | 功能槽 | 来源 | 落点 |
|---|---|---|---|
| S1 | 图契约/节点承载**任意 DAG**（模型输出再入），不写死线性拓扑 | B | head-set 图契约 |
| S2 | 节点 taxonomy **开放可注册**：派生/检验/图/评估/断言/聚合节点 | 全部 | 节点 kind 非枚举死 |
| S3 | **fan-out 扫描 + reducer 选择**节点（容忍 per-candidate 失败） | B/C/D | 一次 run 可长兄弟节点 |
| S4 | **条件控件 `visible_when`** + 数据自省驱动可见性 | C | editable_schema 谓词槽（=硬约束 #4）|
| S5 | **多实例时间排序节点**，算子 op_spec 显式引用所用排序 | C | tsset 不假设全局唯一 |
| S6 | **结构化后估计检验槽**（`test 系数=值`），config 驱动非 code-node | C | 后估计节点 |
| S7 | **用户断言/校验节点**（isid/非空/单调），失败即结构化 block | C | 校验节点 |
| S8 | **MLE 确定性**：优化器配置 + 收敛状态进 hash | B | 缓存正确性前提（R1/R8）|
| S9 | **code-node 逃生舱**（手搓标量计算） | A/B/C | Slice 4/5 坐实 |
| S10 | **多输入适配器（Excel/.dta/…）+ 列领域角色 + 产物/转录导出** | C/D | 接 editable_schema 的 role |
| S11 | **设计矩阵/公式规格层**（因子 `i.`、交互、in-formula `C()`/`I()`）| D/原型 | 参数化节点槽 |
| S12 | **后估计效应节点**（margins/AME）作为“语义可比量” | D | 节点种类（高价值）|
| S13 | **reducer 跨异质模型对齐可比量**（比 AME 不比原始系数）| D | 比较节点语义 |

**本版动作**：图契约 / 节点 schema / editable_schema 的字段与类型设计，必须为 S1–S13 留出扩展位（开放 kind、谓词槽、op_spec 可承载优化器/排序/公式规格、节点种类可注册），但**不实现**这些方法本身。

---

## 12. 切片路线图（北极星全貌）

- **Slice 1（已发 v1.6.0）**：可编辑算子后端契约（model 节点）。
- **Slice 2 = 本版 v1.6.1**：跨 run 血缘森林 + 节点级 Merkle 增量 + model 节点 fork/rollback/trace。
- **Slice 3**：增量细化（stage 粒度 → node 粒度）+ 真正“从节点向下游”局部重算优化。
- **Slice 4**：任意 DAG 拓扑落地（模型输出再入）+ clean/transform/code 节点可编辑（per-stage 算子参数 + 代码沙箱）。
- **Slice 5**：节点 AskAI + 报告撰写器 + cite-chip（Agent Harness 落点，原型 M3）。
- **Slice 6**：并发解除单 slot + 多人协作 / 审计（原型 M4）。

**方法库程序（与切片并行、独立排期）**：线 1 时间序列/波动率纵深（TS Layer 1 = tsset+算子+ACF/PACF+单位根；Layer 2 = ARIMA/ARCH/GARCH；…）；线 2 已覆盖域解释层补全（边际效应优先）。

（Agent Harness 原计划 v1.7，现顺延到谱系图可编辑之后——AI 本就该建在可操作的图之上，与原型 M3 排序一致。）

---

## 13. 验收门禁与流程约束

- 独立 worktree `.worktrees/workbench-v1.6.1` off origin/main `61d45ef`（已建）。
- 门禁统一 `./scripts/gate.sh`（后端全量 + golden 0-drift + 前端 vitest + tsc），**绝不裸 pytest**。
- **golden 0-drift 硬门禁**：CAS/增量层在“无编辑、首次跑”路径必须与现行为字节级一致（缓存只跳过、不改结果）；新增哈希/缓存对既有产物零漂移。
- **增量正确性专项门禁**：缓存命中产物必须与重算产物逐字节一致（防 R1/R7/R8 缓存中毒）；提供“强制全算” vs “增量”对照测试。
- 三级审查：Implementer → Test & QA → Reviewer 再 commit。
- 执行：subagent-driven（accuracy-first：机械/接线/前端内联，subagent 仅核心逻辑 + 两角色对抗审查，撞限额内联兜底）；subagent 不传 model 参数。
- 每个 implementer prompt **禁止 `git push`**；推 main / 移动已发布 tag 需单独授权。

---

## 14. 开放问题（待 PM 这轮商讨）

1. **版本号**：用户定仍叫 `v1.6.1`，但量级（动执行引擎 + 存储 + 图契约 + 前端画布）接近一个 minor。接受命名 vs 改 `v1.7.0`。
2. **缓存粒度**：本版定 stage-output 粒度；是否要更进一步直接上 node 粒度（工量更大）。
3. **第一刀是否过大**：Slice 2 把“增量执行引擎 + 森林画布 + 编辑接线”塞进一版，是否要拆成“BE 增量引擎一版 / FE 森林一版”。
4. **森林视觉保真度**：共享前缀严格按 hash 去重（最干净）vs 允许部分上游重复展示（更省前端工）。
5. **方法库优先级**：线 2（边际效应等域内解释层，小而高频）是否应早于线 1（时序异域纵深）排期。

---

## 附：本文件状态

本 spec 为草案，写入 v1.6.1 worktree。下一步：PM 复审 → `writing-plans` 出实施计划 + 分工（Architect/BE/FE 任务拆解、subagent-driven）。**尚未写代码、尚未实现任何算子。**
