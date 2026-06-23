# Workbench v1.6.1 — 真·谱系图操作层 Slice 2：跨 run 血缘森林 + stage-output Merkle 增量底座

> 设计文档 / Spec
> 日期：2026-06-23
> Base：origin/main `61d45ef`（= tag `v1.6.0`）
> Worktree/branch：`.worktrees/workbench-v1.6.1` / `workbench-v1.6.1`
> 状态：草案 v2（已并入 PM 第一轮复审，待 writing-plans）

---

## 0. 一页纸结论

把执行模型从 **“run 级全量、每跑一条孤立新链”** 升级为 **“stage-output 级内容寻址 Merkle 增量”**，让血缘图第一次成为**真正持久、可 fork / 可回滚 / 可跨 run 回溯**的操作面。

- **第一性原理**：可缓存计算单元是内容寻址的原子单元，身份 = `H(全部输入身份 ⊕ 自己算子规格 ⊕ PIPELINE_VERSION)`（Merkle）。改一个单元的算子，只有它和后代哈希变；上游不变 = 命中缓存 = **原样复用，绝不重算/复制**。
- **本版实现粒度（重要边界）**：v1.6.1 实现 **stage-output 级 Merkle CAS**，并以 `node_hash` 作为**图层身份语言**；**真正的 graph-node 级细化（任意图节点独立缓存/重跑）放 Slice 3**。验收据此理解：本版交付的是“切 model 时 a→b→c 整段 stage-output 复用”，不是“任意图节点都能独立缓存”。
- **本版交付（Slice 2 = 2A+2B+2C）**：节点结果 CAS + stage-output Merkle + 增量重跑（复用上游、只重算分歧前沿）+ head-set 图契约 + FE 森林渲染 + 编辑 model 节点（control_factory）原地 fork 出分支 + 任意节点跨 run 回溯 + 激活祖先 head 回滚。
- **本版不实现、但契约必须留口**：任意 DAG 拓扑（模型输出再入）、per-stage/code 可编辑节点、时间序列/波动率方法包、节点 AskAI / 报告撰写器、并发解除、CAS 的 GC。通过 **S1–S13 预留功能槽** 在契约层留好，绝不挖坑。

本版被四份真实 Stata 作业（单位根 / ARIMA-ARCH / 随机游走-EMH / LPM-Probit-Logit）反复验证，且其“手动状态管理惨状”反向证明 node-result CAS 方向正确。

---

## 1. 背景与动机

### 1.1 现状（v1.6.0 已发）

- origin/main = tag `v1.6.0` = `61d45ef`，门禁全绿：BE 1170 / golden 23 0-drift / FE 637 / tsc 0。
- v1.6.0 = **“可编辑算子的纯后端契约”（操作层 Slice 1，窄竖切）**：仅 model 节点可编辑；`POST /runs/{id}/rerun` 按 manifest 校验覆盖参数 → 生成**全新不可变 run**（`rerun_of` 指针记血缘）；`GET /graph` 响应时注入 `editable_schema`；内容寻址 upload（sha256）；`dag_hash`/`override_hash`/`PIPELINE_VERSION` 哈希**桩（只定义、未实现缓存）**。
- 前端编辑面（`OperationSection`）仍只读、`rerunFromNode` disabled；图是每 run 一张的只读快照。

### 1.2 为什么不能简单接线（立项根因）

最初计划“前端接线片”：编辑 model → 重跑 → 跳转新 run。**被否决**：每次重跑甩出孤立新链，**不能 fork、不能回滚、任意节点无法追溯跨重跑血缘**，与现有表单操作无本质区别。

判定性需求（用户原话比方）：

> 数据集 a 清洗得 b、变换得 c，c 上选 model1 出结果。**切换 model2/model3 时，c 及之前的节点还是原来那套，压根不需要重开一条链路再复制跑一遍 a→b→c。**

= **stage-output 级增量复用**：切模型时上游整段原样复用、绝不重算/复制，只在分歧点往下重算。

### 1.3 北极星（来自 `handoff/prototype.html` Vision 2）

血缘图 = 核心操作面：每个节点可看、可改算子/代码、可“从该处向下游重跑”；决策显式记录；AI 用户主动触发；报告 AI 起草并保留 cite 引用。本版是 Slice 2（Slice 1 = v1.6.0）。

---

## 2. 第一性原理

> **可缓存计算单元是内容寻址（content-addressable）的原子单元。**
> `node_hash = H(canonicalize([sorted(parent_node_hashes), op_spec, PIPELINE_VERSION]))`
> 改一个单元的 `op_spec`，仅它与其全部后代的 `node_hash` 变；上游不变 ⇒ 命中节点结果缓存 ⇒ **直接复用既有产物，不重算、不复制**。

这是一棵 **Merkle DAG**。用户的 a→b→c 例子不是 UX 技巧，**它就是 Merkle-diff 增量执行**。两个 run 共享 a→b→c，是因为它们字面指向**同一批 `node_hash` 单元（同一份存储）**，而非模糊匹配。跨 run 血缘森林由此成为这张内容寻址 DAG 的**天然形状**。

**本版粒度边界**：v1.6.1 的“可缓存计算单元”= **stage-output**（粗，足以交付 a→b→c 段复用）。`node_hash` 同时作为 **图层身份语言**——图节点（`stage:cleaned`/`var:*`/`model:{id}`/…）通过 node↔stage 映射映回其所属 stage-output 的 `node_hash`，使 FE 能按 hash 去重/回溯。**graph-node 级独立缓存（如单独缓存某个 `var:*`）= Slice 3**，本版不做。

v1.6.0 已把内容寻址用于 upload（sha256）+ 定义了 `canonicalize` / `dag_hash`(run 级) / `PIPELINE_VERSION`。本版把内容寻址**从 upload 下沉到 stage-output**。

---

## 3. 架构（三层，`node_hash` 是贯穿三层的通用语）

### 3.1 存储层 — 节点结果 CAS（新建）

- 内容：`node_hash → NodeResult{ artifacts(parquet/json/html), summary, decision, stats, status }`。
- 持久性：**跨 run 持久**。**跨 pipeline-version 物理共存（因 `PIPELINE_VERSION` 进 hash 不会撞），但默认不复用**——仅当哈希输入完全一致且版本兼容策略明确允许时才命中。（不是“任意跨 pipeline 复用”。）
- 位置：`<project_root>/data/node_results/<node_hash>/...`，镜像 v1.6.0 `data/uploads/<sha256>`，生命周期与 run 解耦。
- **head 引用计数**：每个 head（run）记录其根 stage-output hash；GC 按 live head 引用计数实现（**本版只建引用账本、留 GC 口，不实现 GC**）。
- **产物路径双轨兼容（保 golden 0-drift，关键）**：**本版不替换现有 `payload_ref` 语义**。
  * 旧 `payload_ref` 保持 **run-relative**（`processed/cleaned_dataset.parquet`、`model_results/{id}.json`、`reports/report.html` 原样写、原样读）。
  * 新增 `cas_ref: { node_hash, artifact }` 字段并存。
  * 首次实现 **dual-write**：run 内 artifact 继续照常写，CAS 也写一份（按 node_hash）。
  * “run artifact 改为指向 CAS 的纯引用”留到**后续版本**再做，本版不动。

### 3.2 引擎层 — 增量缓存（改造现有 stage 管线）

现状（已核实）：`_run_workflow` 是 `for stage in PIPELINE: ctx = stage.run(ctx, env)`，16 段串行、`ctx` 原地流转；图节点由末尾 `RecordingStage` 一次性记录。

改造：**不是一刀切包所有 stage**（`RecordingStage`/`ReportStage`/diagnostics/report 产物生成都有副作用）。明确 **day-1 cacheable boundary**：

| 缓存单元 | 是否缓存 | 说明 |
|---|---|---|
| source / import | ✅ | 输入 stage-output（upload 已 sha256，叠加 op_spec） |
| clean / profile / validation / routing | ✅ | 各自 stage-output |
| imputation | ✅ | stage-output |
| estimation / model | ✅ | 分歧点典型落点 |
| diagnostics | ✅ | 有 artifact 副作用 → 命中时须 dual-write 物化 run-relative 产物 |
| report | ✅ | 有 artifact 副作用 → 同上 |
| **RecordingStage** | ❌ **特判** | **不作为普通可缓存计算 stage**；它**根据已知 CAS / node↔stage mapping 生成图视图（head-set）**，不参与命中/跳过逻辑 |

缓存 wrapper 语义：拓扑序为每个 cacheable 单元算 `node_hash`（输入 hash + 该单元 op_spec + PIPELINE_VERSION）→ 命中 CAS：跳过执行，以缓存产物重建 `DataHandle`/artifact 引用，**且对有副作用的 stage（diagnostics/report）dual-write 物化 run-relative 产物**（保证下游与历史路径不变）→ 未命中：执行 + 写 CAS + dual-write run 产物。

编辑 model 的 `op_spec` → 其 hash 变 → model 及下游（diagnostics/report）未命中 → **只重算分歧前沿**；source/clean/.../imputation 命中复用。

### 3.3 契约 / 前端层 — head-set 图 + 森林画布（改造）

**图契约**升级为 head-set 形态：

```
GET /runs/{id}/graph  →  {
  nodes: { <node_hash>: NodeView },        // 按 hash 严格去重，跨 run 共享前缀只出现一次
  edges: [...],
  heads: [ { run_id, head_node_hash, from_node, rerun_of, rerun_reason, status, created_at } ],
  schema_version: <bumped>,
  legacy: <bool>                            // 旧 run 退化标记
}
```

- 服务端按 run 的 rerun 家族（见下）聚合该家族全部 head + 可达 stage-output 节点的并集 DAG。
- 仍遵 v1.6.0“serve-layer decorate-only”：CAS / 家族聚合在**响应时**计算，**绝不写回 graph.json**。

**family 聚合索引（day-1 决定）**：`rerun_of` 只有父指针。要拿“祖先 + 后代 + 兄弟 heads”，**day-1 用 serve-layer 扫描所有 run manifest**（数据量小、风险低、与 decorate-only 一致）；`run_family_index.json` 索引化留后续版本。

**FE 森林画布**：渲染 head-set 并集 DAG——**共享前缀严格按 hash 去重、只画一次**（不允许重复展示共享前缀），分歧处分叉、按 head 着色；选中节点 → 跨 run 回溯（沿 parent hash 游走）；激活祖先 head = 回滚；编辑 model 节点提交 → 在森林里原地长出子分支（不跳转）。

### 3.4 `from_node` 语义（钉死，防误实现）

编辑旧 model 节点时，**新分支不是接在旧 model 输出之后，而是接在旧 model 的父输入前沿之后**——即旧 model 这个**操作节点被替换**：

```
old:  C → M1 → D1 → R1
edit M1 → M2:
new:  C → M2 → D2 → R2          （C 共享复用；M1→M2 替换；D1→D2、R1→R2 重算）
```

所以 `from_node = h_m1` 表示**“被替换的操作节点”**；执行的复用边界 = `parents(h_m1)` 的 stage-output（命中复用）+ 该节点的 **new `op_spec`** 重算。**绝不是**在 `h_m1` 的输出后面再接一段。森林里 M1 与 M2 是同一父 C 下的**两个兄弟分支**，不是 M1→M2 串联。

---

## 4. Route 选择理由（Route 2 演进，非 Route 1 重建）

| | Route 1 重建 | **Route 2 演进（采纳）** |
|---|---|---|
| 做法 | 照 prototype `schema.sql` 引入持久 `Pipeline` 一等实体，重写数据模型 | 复用 v1.6.0 不可变 run + `rerun_of` + 内容寻址地基，**把内容寻址从 upload 下沉到 stage-output** |
| 工量/风险 | 最大；重写数据模型，golden 风险最高 | 中；不重写数据模型，复用现有 stage 管线 + DataHandle |
| 扩展性 | 忠实原型 | 同样到达原型 UX；CAS 立住后 per-stage 编辑 / AI / 并发都只是往这张 DAG 上挂 |

**结论**：Route 2 用更低风险到达同一目标，复用已验证地基（`rerun_of`/`from_node`/`PIPELINE_VERSION`/`canonicalize`），符合“为扩展性打地基且不破坏 golden”的纪律。

---

## 5. Architect ⨯ BE ⨯ FE 对抗性交叉论证

| # | 提出方 | 风险 / 反对 | 处置 |
|---|---|---|---|
| R1 | BE | **缓存中毒**：节点执行非纯函数（bootstrap/MICE/RF/MLE 的 RNG、库版本）→ 复用错结果 | seed 进 `op_spec`；`PIPELINE_VERSION` 含库版本升级即全失效；**golden 0-drift 已证全管线确定性**=现成保证 |
| R2 | Architect | **缓存粒度**：执行单元是 stage、图节点事后记录，两者不对齐 | 本版按 **stage-output 粒度**缓存；`RecordingStage` 建 node↔stage-output 映射；graph-node 级留 Slice 3 |
| R3 | FE | **共享前缀如何“同一份”**：子 run 现重新物化 a/b/c 成新 node id | 用 `node_hash` 做身份、严格 hash 去重、**不做模糊匹配**；要求 BE 把 run 级 `dag_hash` 升级为 per-stage-output Merkle |
| R4 | BE | **CAS 无限膨胀** | 按 live head 引用计数；GC 本版只留口不实现 |
| R5 | FE | **legacy run 无 node_hash** 致森林画布崩 | 退化：旧 run = 不透明 head，走旧 graph.json 单独渲染；不破坏现有 run detail |
| R6 | Architect | **单 run-slot（429）** 撞多分支并跑 | 增量更快、撞得更少；多分支并行=并发片（后）；本版单节点 fork 串行即可 |
| R7 | BE | **确定性边界**：路径/时间戳/绝对路径混入产物破坏 hash 幂等 | 产物按 node_hash 命名、剥离运行期元数据（`started_at` 不进 hash）；复用 `canonicalize` |
| R8 | BE（MLE）| ARIMA/ARCH/GARCH 等**迭代优化** + `capture` 容错 | 优化器配置 + 收敛状态进 `op_spec`/hash；fan-out per-candidate 失败被跳过、reducer 容忍（扩展 `MODEL_FIT_FAILED`）|
| R9 | BE | **副作用 stage 命中缓存后 run-relative 产物缺失** | diagnostics/report 命中时 **dual-write 物化** run-relative artifact（见 §3.2）|

---

## 6. 本版范围（Slice 2 = 2A / 2B / 2C，同版本内分段验收）

PM 决定：第一刀**不跨版本拆**，但在 v1.6.1 内拆 **2A/2B/2C 三段，各自独立验收**。

### 2A — BE 节点结果 CAS + stage-output Merkle + 增量执行（dual-write）
- `node_hash`（per-stage-output Merkle）、`lineage/node_store.py`（CAS + 引用账本）、缓存 wrapper（按 §3.2 cacheable boundary，RecordingStage 特判）、dual-write。
- **验收**：a→b→c 段复用（改 model 仅 model+下游重算）；**golden 0-drift**（首次/无编辑路径字节级不变）；**增量正确性**（命中产物与强制全算逐字节一致）；**缓存命中后 child run 目录完整**（仍含旧消费者期待的 run-relative 文件，见 G2）。

### 2B — head-set 图契约 + family serve-聚合 + from_node 语义 + 值回填
- `GET /runs/{id}/graph` 升级为家族 head-set 并集 DAG；serve-layer 扫描聚合 family；`from_node` 语义（§3.4）；`editable_schema.value` 回填 `run_inputs` 实际值。
- **验收**：契约返回家族 head-set、按 hash 严格去重；`from_node` 替换语义正确（C 复用、M1/M2 兄弟）；编辑面显示真实当前值。

### 2C — FE control_factory + 可编辑 OperationSection + 森林画布 + fork/trace/rollback
- `controlFactory`（§8 硬约束）、`OperationSection` 只读→可编辑接 `/rerun`、点亮 `rerunFromNode`、森林画布渲染并集 DAG（hash 去重、分叉、选中回溯、激活祖先 head 回滚）。
- **验收**：编辑 model → 森林原地长子分支；任意节点跨 run 回溯；激活祖先 head 回滚；tsc 0 / vitest 绿。**在现有 `GraphCanvas` 上消费 head-set adapter，不绑定 layout 重构（见 G3）。**

### 实施硬护栏（PM 第二轮，plan 必须遵守）

- **G1 — 2A 先只证明 model fork 的增量复用**：不追求第一步让所有 stage 完美缓存。先打通 `source → clean → … → model → report` **最小链路**的增量复用，并带 **“强制全算 vs 增量”对照**；其余 stage 的缓存覆盖在 2A 内逐步补，但**验收门槛是 model fork 这一条链跑通**，不是全 stage 完美。
- **G2 — CAS 命中必须仍能生成完整 run 目录**：本版保留 run-relative artifacts，**命中缓存后的 child run 目录仍须含旧消费者期待的全部文件**（`processed/*.parquet`、`model_results/*.json`、`reports/report.html` 等）。测试**必须断言**命中路径下 run 目录文件完整（dual-write 物化，见 R9）。
- **G3 — FE forest 不与 layout 重构绑定**：先在**现有 `GraphCanvas`** 上消费 head-set adapter，完成 **hash 去重 / 分叉 / active head / trace / rollback** 的**功能闭环**；**视觉 / 布局精修另算**，不在本版 2C 关键路径。

**不做（明确延后，见 §12）**：任意 DAG 拓扑/模型输出再入、per-stage/code 可编辑节点、时序/波动率/边际效应方法、节点 AskAI/报告撰写器、并发解除、CAS 的 GC、graph-node 级缓存、family 索引化。

---

## 7. 具体重构细则（代码锚定）

### 7.1 后端
- `lineage/hashing.py`：保留 `dag_hash`(run 级)兼容；新增 `node_hash(parent_hashes, op_spec, PIPELINE_VERSION)`（per-stage-output Merkle）。
- `lineage/node_store.py`（新）：CAS（写/读/存在/引用账本），镜像 `upload_store.py`（`data/node_results/<hash>/`）。
- `orchestrator/__init__.py` `_run_workflow`：按 §3.2 cacheable boundary 包缓存 wrapper（命中跳过 + 副作用 stage dual-write；RecordingStage 特判不缓存）；stage 实现行为冻结。
- `engine/stages/recording.py`：建“图节点 ↔ stage-output / node_hash”映射；**不参与缓存命中逻辑，按映射生成图视图**；`payload_ref` 保持 run-relative，**新增 `cas_ref`** 并存（dual-write）。
- `engine/context.py` `DataHandle`：增加从缓存产物重建 handle 的能力（命中时还原 frame/artifact 引用）。
- `api.py`：`_annotate_editable_nodes` 增 `run_inputs` 实际值回填到 `editable_schema.value`；`get_run_graph` 升级为 family serve-扫描聚合 + head-set；`from_node` 语义按 §3.4。
- `graph_store.py`：graph.json 单 run 持久化不变；家族聚合在 serve 层（decorate-only）。

### 7.2 前端
- `lineage/api/graphViewTypes.ts`：`EditableControl` 与后端对齐（补 `role`/`required`/`columns` kind，纠正 v1.5.0 过期形）；新增 head-set / NodeView(by hash) / heads 类型。
- `lineage/api/graphAdapter.ts`：从“per-run graph → GraphViewModel”升级为“head-set → 并集 DAG（按 node_hash 严格去重）”；映射 `editable_schema`。
- `lineage/controls/controlFactory.tsx`（新）：`editable_schema → control_factory → 控件`（§8，**绝不按 kind 直写 JSX switch**）。
- `lineage/detail/sections/OperationSection.tsx`：只读 → 可编辑（走 control_factory），接 `/rerun`。
- `workbench/registry/actionRegistry.ts`：点亮 `rerunFromNode`。
- 森林画布：扩展 `lineage/graph/GraphCanvas` 渲染 head-set 并集 DAG（hash 去重、分叉、选中回溯、激活祖先 head 回滚）。
- `api.ts`：新增 `rerunFromNode` client + family 拉取。

---

## 8. control_factory 硬约束（已锁定）

1. 节点编辑面渲染**必须走 control_factory 间接层**：`editable_schema → control_factory → UI 控件`，**绝不**按 kind 直写 JSX switch——未来 AI 生成控件/条件控件/动态可见性都能接住。
2. 沿用 **manifest 驱动**、**零 per-estimator 硬编码**。
3. day-1 只 model 节点可编辑；并发仍单 slot。
4. 控件描述含**条件可见性谓词槽**（`visible_when`/`available_when`，见 S4）。
5. control_factory 本体须**结构上接所有 kind**（radio/select/multiselect/slider/text/textarea/toggle/columns），day-1 仅启用数据源在手的控件，不影响工厂完整性。

---

## 9. 经验与教训：四份金标准验收用例

四份真实 Stata 作业从消费方压测架构。统一结论：**架构（v1.6.1）被反复验证；真正缺的是方法库纵深与节点模型泛化；node-result CAS 被“手动状态管理惨状”反向证明方向正确。**

- **A — HW9 单位根（UK 利差）**：`tsset`、`L. D.`、ACF/PACF、AR(1)、手搓 Dickey-Fuller。暴露：时序纵深为零；节点 taxonomy 需泛化；code-node 逃生舱。
- **B — Rupee ARIMA-ARCH/GARCH**：ARIMA 网格→残差→ARCH 网格→条件方差→预测区间→回测。暴露（最深）：① **模型输出反复再入管线当下游输入** → 图契约绝不能写死线性拓扑；② fan-out 扫描 + reducer 选择；③ **三次 `clear all` 重载 RESI1** = CAS 铁证；④ MLE 确定性=缓存前提（R8）。
- **C — Russell 随机游走/EMH**：朴素预测 MSE 比较、`test b=1`/`test _cons=0`、收益自相关。暴露：① schema 条件/自省操作（印证硬约束 #4）；② **同一数据多重时间排序**；③ 列聚合广播；④ 结构化后估计检验槽；⑤ 断言节点 `isid`；⑥ `preserve/restore` = CAS 第三铁证。
- **D — NYC Schools LPM/Probit/Logit + margins**：暴露：① **model-type fork 最干净验证**，证明 model 是正确的第一个可编辑节点；② **域内方法缺口：`margins`/边际效应确认缺失**；③ 异质模型比较 → reducer 须对齐 AME 不比原始系数；④ 设计矩阵/公式规格（`i.`/交互/`C()`/`I()`）；⑤ 会话转录 artifact。

---

## 10. 缺失算子清单（方法库，与本版架构正交）

> 非本版实现；路线锚点 + 验证 S1–S13 留口是否充分。

**线 1：时间序列/金融计量纵深（异域，大、分层，像 DID v1.5.5→1.5.9）**
IO（`tsset` 日/季频、字符串日期、`.dta`/Excel、图/数据集/smcl→PDF 导出）；算子（`L. D. F.`、任意公式派生、列聚合广播、收益率）；诊断（ACF/PACF/Ljung-Box、平方残差 ACF）；检验（DF/ADF/KPSS/PP、sktest/swilk、单样本 ttest）；模型（ARIMA、ARCH/GARCH）；后处理（predict 残差/拟合/条件方差/一步预测、时变方差预测区间、条件分位、标准化残差）；选择/评估（AIC/AICc 网格扫描、朴素预测 MSE 比较、区间回测覆盖率）；可视化（tsline、scatter+lfit、hist+normal、boxplot、qnorm/pnorm）。

**线 2：已覆盖域解释/诊断层补全（域内，小而高频，PM 建议优先）**
**边际效应 `margins, dydx`（AME/MEM）← 头号**；设计矩阵/公式规格（`i.`/交互/`C()`/`I()`）；LPM 诊断（`predict, xb` + 数 ŷ∉[0,1]）；结构化后估计 Wald（`test 系数=值`）；用户断言节点（`isid`/非空/单调）。

---

## 11. 需预留的功能槽（S1–S13，本版“设计时绝不挖坑”硬要求）

> 非本版实现；是 v1.6.1 重做图契约/节点模型/editable_schema 时**必须留好的口**，缺一个未来返工。

| # | 功能槽 | 来源 | 落点 |
|---|---|---|---|
| S1 | 图契约/节点承载**任意 DAG**（模型输出再入），不写死线性拓扑 | B | head-set 图契约 |
| S2 | 节点 taxonomy **开放可注册**：派生/检验/图/评估/断言/聚合节点 | 全部 | 节点 kind 非枚举死 |
| S3 | **fan-out 扫描 + reducer 选择**节点（容忍 per-candidate 失败） | B/C/D | 一次 run 可长兄弟节点 |
| S4 | **条件控件 `visible_when`** + 数据自省驱动可见性 | C | editable_schema 谓词槽（=硬约束 #4）|
| S5 | **多实例时间排序节点**，算子 op_spec 显式引用所用排序 | C | tsset 不假设全局唯一 |
| S6 | **结构化后估计检验槽**（`test 系数=值`），config 驱动 | C | 后估计节点 |
| S7 | **用户断言/校验节点**（isid/非空/单调），失败即结构化 block | C | 校验节点 |
| S8 | **MLE 确定性**：优化器配置 + 收敛状态进 hash | B | 缓存正确性前提（R1/R8）|
| S9 | **code-node 逃生舱**（手搓标量计算） | A/B/C | Slice 4/5 |
| S10 | **多输入适配器（Excel/.dta/…）+ 列领域角色 + 产物/转录导出** | C/D | 接 editable_schema role |
| S11 | **设计矩阵/公式规格层**（因子 `i.`、交互、in-formula `C()`/`I()`）| D/原型 | 参数化节点槽 |
| S12 | **后估计效应节点**（margins/AME）作为“语义可比量” | D | 节点种类（高价值）|
| S13 | **reducer 跨异质模型对齐可比量**（比 AME 不比原始系数）| D | 比较节点语义 |

**本版动作**：图契约/节点 schema/editable_schema 字段与类型必须为 S1–S13 留扩展位（开放 kind、谓词槽、op_spec 可承载优化器/排序/公式规格、节点种类可注册），但**不实现**方法本身。

---

## 12. 切片路线图

- **Slice 1（已发 v1.6.0）**：可编辑算子后端契约（model 节点）。
- **Slice 2 = 本版 v1.6.1**：跨 run 血缘森林 + stage-output Merkle 增量 + model 节点 fork/rollback/trace。
- **Slice 3**：graph-node 级缓存细化 + family 索引化（`run_family_index.json`）+ run-artifact 改 CAS 引用。
- **Slice 4**：任意 DAG 拓扑（模型输出再入）+ clean/transform/code 节点可编辑（per-stage 算子参数 + 代码沙箱）。
- **Slice 5**：节点 AskAI + 报告撰写器 + cite-chip（Agent Harness，原型 M3）。
- **Slice 6**：并发解除单 slot + 多人协作/审计（原型 M4）。

**方法库程序（并行、独立排期）**：线 2（域内解释层，**边际效应优先**）、线 1（时序/波动率纵深，分层如 DID）。Agent Harness 原 v1.7，顺延至谱系图可编辑之后（原型 M3 排序）。

---

## 13. 验收门禁与流程约束

- 独立 worktree `.worktrees/workbench-v1.6.1` off `61d45ef`（已建）。
- 门禁统一 `./scripts/gate.sh`（后端全量 + golden 0-drift + 前端 vitest + tsc），**绝不裸 pytest**。
- **golden 0-drift 硬门禁**：CAS/增量层在“首次/无编辑”路径必须与现行为**字节级一致**（缓存只跳过、不改结果；dual-write 不改 run-relative 产物内容）。
- **增量正确性专项门禁**：命中产物须与“强制全算”逐字节一致（防 R1/R7/R8/R9 缓存中毒）；提供“强制全算 vs 增量”对照测试。
- **run 目录完整性门禁（G2）**：缓存命中后的 child run 目录必须含旧消费者期待的全部 run-relative 文件，断言式检查（非仅 CAS 写入）。
- 三级审查：Implementer → Test & QA → Reviewer 再 commit；2A/2B/2C 各自过门禁。
- 执行：subagent-driven（accuracy-first：机械/接线/前端内联，subagent 仅核心逻辑 + 两角色对抗审查，撞限额内联兜底）；subagent 不传 model 参数。
- 每个 implementer prompt **禁止 `git push`**；推 main / 移动已发布 tag 需单独授权。

---

## 14. 开放问题（PM 第一轮已定）

1. **版本号**：✅ 接受 `v1.6.1`；**release note 写清这是“架构型 patch”**（量级近 minor）。
2. **缓存粒度**：✅ 坚持 **stage-output**，本版不上 graph-node 粒度（→ Slice 3）。
3. **第一刀范围**：✅ 同版本内拆 **2A/2B/2C**，分别验收 BE CAS / graph contract / FE forest（见 §6）。
4. **森林视觉**：✅ **严格 hash 去重，不允许重复展示共享前缀**。
5. **方法库优先级**：✅ **线 2 `margins`/AME 优先于线 1 时序大包**（收益高、风险小）。

---

## 15. Changelog

- **v1（2026-06-23）**：初稿（第一性原理 + 三层架构 + 三方对抗 + 四份用例 + S1–S13）。
- **v2（2026-06-23，并入 PM 第一轮复审）**：
  1. 标题 + 全文“节点级”→ **stage-output Merkle 底座**，`node_hash` 作图层身份语言，graph-node 级 → Slice 3。
  2. CAS **不替换 `payload_ref`**，改**双轨 + dual-write**（保 golden）。
  3. 新增 §3.4 **`from_node` 语义钉死**（被替换节点，复用边界 = `parents(h_m1)`，M1/M2 兄弟）。
  4. §3.2 列出 **day-1 cacheable boundary** + `RecordingStage` 特判（非可缓存计算 stage，按 mapping 生成图视图）+ 副作用 stage dual-write（R9）。
  5. family 聚合 day-1 **serve-layer 扫描**，索引化 → Slice 3。
  6. **“跨 pipeline”收紧**：物理共存、默认不复用。
  - §6 拆 **2A/2B/2C** 分段验收；§14 开放问题按 PM 结论定。
- **v3（2026-06-23，并入 PM 第二轮）**：§6 新增**实施硬护栏 G1/G2/G3**（2A 先证 model fork 最小链路增量复用；CAS 命中须生成完整 run 目录；FE forest 不绑 layout 重构）；2A 验收 + §13 门禁补 run 目录完整性断言。

---

## 附：本文件状态

草案 v2，写入 v1.6.1 worktree。下一步：（PM 如无新意见）→ `writing-plans` 出实施计划 + 2A/2B/2C 分工。**尚未写代码、未实现任何算子。**
