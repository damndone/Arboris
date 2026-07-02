# Workbench v1.6.7 — Draft 融入主图（Draft-in-Graph）设计

> 起草 2026-07-02（v1.6.6 收尾后）· 经浏览器可视化 brainstorm 逐点拍板
> 北极星：**一张 lineage graph 里完成所有操作**。本版是愿景第一实质步 ——
> 消灭「跳出去到独立 Draft Graph」，把 draft → validate → execute 的完整生命周期
> 就地做在主 forest 图上。
> 对齐 roadmap `docs/superpowers/roadmap/2026-07-01-unified-graph-workbench-roadmap.md` §3 v1.6.7 + §3.5 M。

---

## 0. 一句话

选中一个 executed model 节点 → 就地 fork 出一个 **draft 子节点** → 在右抽屉编辑参数 →
validate（节点上显示预检态）→ execute → 节点从 `draft` 就地变成 `executed` child，
**全程不离开主 forest 图，不打开新路由**。支持多个草稿并行并**跨重载持久**（草稿是图上一等公民）。

## 0.1 范围边界（避免把北极星塞进一版）

北极星「**能在谱系图上进行全部操作**」= 看 / 编辑 / rerun / 对比 / 问 AI / 出报告，
是 **v1.6.7 + v1.6.8 + v1.7 合起来**的目标，**不是 v1.6.7 一版**。拆开看后端账：

| 操作 | 后端状态 | 落哪版 |
|---|---|---|
| 看 / 编辑 / rerun / **draft** | 契约已在 v1.6.0–v1.6.4 建好（from-node/patch/validate/execute/hash-gate/snapshot） | **v1.6.7**（复用） |
| **草稿持久化**（列表 + 弃置清理） | 缺 `GET /pipeline-drafts` + `DELETE` | **v1.6.7 新增**（见 §4.1/§5） |
| 任意两节点**对比** | 缺 diff 后端 | v1.6.8 |
| 节点**问 AI** | 缺 `/llm/chat` | v1.6.8 |
| 引用**报告** | 缺生成后端 | v1.6.8 |

所以：**「全部操作」当然要改后端 —— 但绝大多数后端活儿落在 v1.6.8/v1.7。**
v1.6.7 只把「draft/编辑/rerun」这一个操作搬上图；其编辑/执行契约是 v1.6.4 已建好的资本，
**本版后端仅新增 2 个薄端点让草稿真正持久**（列表 + 删除），不碰任何估计器 / 图谱 / artifact 逻辑。
「合并 Pipeline」部分是**真免费**：`PipelineView` 是纯占位 stub（`workbench/views/PipelineView.tsx`，
"coming in V2.0"，零功能），无 Pipeline 后端可合并，退役其入口丢零能力。

## 1. 背景与现状（对着代码）

主 forest 工作台今天有**两条**改参数-重跑路径：

| 路径 | 入口 | 契约 | 特征 |
|---|---|---|---|
| **A · 图内 rerun**（v1.6.1+） | 抽屉 OperationSection 直接提交 | `POST /runs/{id}/rerun` | child 就地长出、无导航；**无 validate 预检**、**无可见草稿态**；pending 仅是聚焦动画（`pendingFocusTarget` 轮询等索引） |
| **B · Draft Graph**（v1.6.4） | Actions 菜单「Open as Draft Graph」→ 跳 `/pipeline-drafts/:id` | `POST /pipeline-drafts/from-node` + `PATCH` + `/validate` + `/execute` | 持久草稿实体、**validate 预检门**、hash-gate、可多次改再跑；**但跳出了主图** |

v1.6.7 = 把 **B 的价值**（validate 预检 + 持久可视草稿）搬进 **A 的主图**，消灭跳转。

**编辑/执行契约原样复用**；本版后端仅新增 2 个薄端点（列表 + 删除，见 §5）让草稿跨重载持久。
已存在的端点（`backend/workbench/api.py`）：
- `POST /pipeline-drafts/from-node` — 从节点建草稿（返回 draft + draft_hash）
- `GET /pipeline-drafts/{id}`、`PATCH /pipeline-drafts/{id}` — 读 / 改参数
- `POST /pipeline-drafts/{id}/validate` — 预检（返回 status + checks + validated_draft_hash）
- `POST /pipeline-drafts/{id}/execute` — 执行（hash-gate + dedupe + focus.status=`pending_index` 轮询信息）

本版**新增**（薄，不碰估计器 / 图谱 / artifact）：
- `GET /pipeline-drafts?project_root=` — 列出项目下的草稿（供重载 hydrate）
- `DELETE /pipeline-drafts/{id}?project_root=` — 删草稿 json（+ 关联 dedupe 文件），供弃置 / 执行成功后清理

草稿实体（`backend/workbench/lineage/pipeline_drafts.py` `PipelineDraftV1`）：`draft_id`、`status`、
`created_from`（source_run_id / source_model_node_id / source_op_node_id / source_node_hash / source_context_fingerprint / source_input_fingerprint；**注意无 forest_node_key**，见 §4.2 锚点解析）、
`graph`（input.dataset 节点 + model 节点）。

## 2. 决策记录（brainstorm 拍板）

| # | 决策 | 选定 | 理由 |
|---|---|---|---|
| D1 | 融合深度 | **草稿节点完整生命周期** | 最贴北极星；draft 成图上一等公民 |
| D2 | 编辑面 | **复用右侧详情抽屉**（草稿节点挂 ModelNodeInspector 式 draft 编辑器，见 §4.3） | 复用 controlFactory + draft 契约；draft 编辑走 patch/validate/execute，非 OperationSection 的 rerun |
| D3 | 草稿落点 | **源 model 节点的 pending 兄弟子节点** | 契合现有 fork 语义 |
| D4 | 数量 | **多草稿并行** | 支持并排 what-if；单一注册表管理 |
| D5 | 持久化 | **跨重载持久（本版实现）** | 新增 `GET`/`DELETE` 薄端点；重载 hydrate 未执行草稿，草稿成图上一等公民 |
| D6 | 入口 | **Actions 菜单「Fork draft here」（去导航）** | 复用现有菜单项，语义离散，不与角落徽章抢空间 |
| D7 | 抽屉头部 | **动作独立成常驻工具栏行 + id 截断** | 修「Actions 够不到」+ 安置草稿控件 |
| D8 | 旧入口去向 | **`DraftGraphRoute` 留深链接 fallback；Pipeline 标签页入口退役** | 保留历史（用户偏好），不删 |
| D9 | 弃置 / 执行后清理 | **DELETE 真删 json** | 有了 DELETE 端点；弃置与执行成功都清理，不留孤儿 |

## 3. 状态机 & 视觉语言

草稿子节点生命周期（`lifecycleState`）：

```
draft ──edit──► draft
  │
  └─validate─► validating ──► valid ✓ ──execute──► pending ──indexed──► executed
                    │              ▲                   │
                    └► invalid ────┘                   └─fail─► failed
                       (可回 draft 改)                        (可回 draft 改)
```

视觉语言（森林节点渲染）：

| 态 | 边框 | 底色 | 语义 |
|---|---|---|---|
| `draft` | 虚线 灰 | 半透明 | 计划中、可编辑 |
| `validating` | 虚线 琥珀 + 转圈 | 琥珀弱 | 预检中 |
| `valid` | 实线 蓝 + ✓ | 蓝弱 | 通过、可 Execute |
| `invalid` | 实线 红 | 红弱 | 预检未过 |
| `pending` | 实线 金 + 脉冲光晕 | 金弱 | 执行中，等索引 |
| `executed` | 实线 绿 | 绿弱 | 证据（= 现有 run 节点常态） |
| `failed` | 实线 红 | 红弱 | 执行失败 |

## 4. 前端架构（后端仅 +2 薄端点，主体在前端）

### 4.1 DraftRegistry（新，单一真相源）
Session 级状态，多草稿并行的中枢：

```ts
type DraftEntry = {
  draftId: string;
  draft: PipelineDraftV1;
  draftHash: string;
  validation: DraftValidationResult | null;
  lifecycleState: LifecycleState;   // draft|validating|valid|invalid|pending|executed|failed
  // 锚点不存 forest key（会过期/不唯一）；合并时按 created_from 的 node_hash→nodeHash 解析（§4.2）
};
type DraftRegistry = Map<string /*draftId*/, DraftEntry>;
```

- **hydrate（重载/进场）**：`GET /pipeline-drafts?project_root=` 列出未执行草稿 → 填充注册表（态由 `status` 推：`draft`；若曾 execute 未索引则 `pending` 并恢复轮询）。这让草稿跨重载持久。
- 建：`createPipelineDraftFromNode` 成功 → put 一条 `draft` 态。
- 改：`patchPipelineDraftParams` → 更新 draft/draftHash、validation 清空、回 `draft` 态。
- validate：更新 validation + `validating`→`valid|invalid`。
- execute：`pending` → 现有 `pendingFocusTarget` 轮询命中 → `executed` → `DELETE` 草稿 json + 从注册表移除（真节点已进森林）。
- 弃置：`DELETE` 草稿 json + 从注册表移除，不留孤儿。
- **单一真相源 & 一等公民（D5）**：注册表以 `draftId`（= 服务端持久 key）索引；session 内新建与重载 hydrate 灌进同一注册表，二者同构。多草稿并行天然支持。

### 4.2 合并层 `mergeDraftsIntoModel`（新）
在 `forestToGraphViewModel(forest, runId)` 产出 `GraphViewModel` **之后**、且**作为 `ForestWorkbench` 里 `model` 的最终产物**注入 DraftRegistry 的草稿：
- 每条 DraftEntry → 一个草稿 `GraphViewNode`（`nodeKey` 由 `draftId` 派生 = `draft:{draftId}`，稳定唯一）+ 一条从**源节点**指向它的边。
- **锚点解析（验证发现⑤，修正）**：`CreatedFrom` 模型**不存** `source_forest_node_key`（后端仅用于创建时校验，不落库）。故锚点由 `draft.created_from` 在**当前 forest 模型**里解析：**优先 `source_node_hash` 匹配 `HeadSetNode.nodeHash`（唯一去重键），退回 `source_op_node_id` 匹配 `opNodeId`（注意 `opNodeId` 跨 run 去重后可不唯一）**。session 新建与 hydrate 走同一解析，天然一致；匹配不到 = 源节点在当前 head-set 不可见 → 跳过注入（degrade）。
- 节点携带 `lifecycleState` 供 GraphNode 渲染视觉态。
- 注入后交给**现有 forest 布局**（GraphCanvas 内 dagre，前端算，非后端坐标）定位 —— 与 `forestToGraphViewModel` 已有的合成边（variable→parent）同构，同源多草稿自然扇开，GraphCanvas/布局引擎零改动。
- **顺序约束（验证发现④）**：`validNodeKeys = new Set(model.nodes.map(n => n.nodeKey))` 从合并**后**的 `model` 派生，否则草稿节点会被 `WorkbenchStateProvider` 判非法而无法选中。故合并必须并进 `model` 的 `useMemo`，位于 validNodeKeys 之前。

### 4.3 复用 vs 新建（验证发现①：编辑面不是 OperationSection）
- **复用**：后端 draft store / validate / execute / hash-gate / snapshot 契约；`controlFactory`（`renderControl`，编辑控件）；pending 轮询（`ForestWorkbench` 的 `pendingFocusTarget`）。
- **⚠️ 不复用 `OperationSection`**：它提交走 `rerun.submitRerun`（`POST /runs/{id}/rerun`，路径 A 一次性 rerun），**不是** draft patch/validate/execute。草稿编辑必须走 draft 契约。
- **draft 编辑器**：抽屉在选中**草稿节点**时挂一个 **ModelNodeInspector 式** 编辑器（现 `pipelineDrafts/ModelNodeInspector.tsx` 已用 `renderControl` + `onSave→patchPipelineDraftParams`）—— 抽取/复用其编辑逻辑成抽屉内 section，与 OperationSection **只共享 controlFactory**。选中 **executed 节点**时抽屉仍是现有 section（含 OperationSection 的 rerun 路径，不动）。
- **pending seed（验证发现③）**：in-graph execute 不导航，故**直接从 `executePipelineDraft` 响应的 `focus.poll` seed `pendingFocusTarget`**（照抄 `handleRerun` 从 rerun 响应 seed 的写法），不经 URL 参数；`DraftGraphRoute` 的 URL-param 路径仅深链接 fallback 保留。

### 4.4 抽屉头部重构（D7，修 Actions 位置）
现根因：`DetailHeader` 的 `.dp-kind` 是**不换行 flex 行**，长 `ownerRunId · nodeKey`/warnings 把
`margin-left:auto` 的「Actions + ×」簇顶出抽屉右边缘 → 需横拖才够得到。

重构：
- 抽屉头部拆出一条**常驻动作工具栏行**：`[状态 chip] … [Fork draft] [Validate] [Execute] [⋯] [×]`。
- 元数据 id 行 `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`（截断，不再挤动作）。
- 按钮**上下文出现**：executed 节点 → `Fork draft`；选中草稿节点 → 状态 chip + `Validate`/`Execute`。
- 次要项（View Raw JSON / Copy node id / Copy as JSON / lineage path）收进 `⋯` 菜单（现 NodeActionMenu 内容）。

## 5. 组件清单

**新增**
- `frontend/src/lineage/drafts/draftRegistry.ts` — DraftRegistry 状态 + reducer/迁移 + hydrate。
- `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts` — 合并层。
- 抽屉 **draft 编辑器 section**（抽取 `ModelNodeInspector` 编辑逻辑，patch/validate/execute，仅草稿节点挂载）。
- 抽屉草稿工具栏（`DetailHeader` 内新子组件或 `sections/` 下）。

**改动**
- `frontend/src/lineage/header/DetailHeader.tsx` — 工具栏行重构 + id 截断 + 上下文按钮。
- `frontend/src/lineage/graph/NodeActionMenu.tsx` — 「Open as Draft Graph」→「Fork draft here」，去 `navigate`，改为写 DraftRegistry。
- `frontend/src/workbench/WorkbenchRouteContainer.tsx`（`ForestWorkbench`）— 挂 DraftRegistry provider + 合并层接入 `model`。
- `frontend/src/lineage/graph/GraphNode.tsx` — 按 `lifecycleState` 渲染草稿视觉态。
- `frontend/src/lineage/api/graphViewTypes.ts` — 节点加 `lifecycleState?` / `isDraft?` 字段。
- App 路由 / Pipeline 标签页入口 — 退役 Pipeline 标签页入口；`DraftGraphRoute` 保留为深链接 fallback。

**后端新增（薄，2 端点 + 2 store 方法）**
- `backend/workbench/api.py` — `GET /pipeline-drafts`（list）+ `DELETE /pipeline-drafts/{id}`。
- `backend/workbench/lineage/pipeline_drafts.py` — `PipelineDraftStore.list()`（扫 `drafts_dir/*.json`，返回 id/status/created_from/model_type 摘要 + hash）+ `PipelineDraftStore.delete()`（删 json + 关联 `*.execution.json` dedupe 文件；带 draft_id 校验，复用现有锁）。

**不动**
- 后端估计器 / 图谱 / artifact / 引擎全部。GraphCanvas 布局引擎。OperationSection / controlFactory 内部。

## 6. 数据流（fork→execute 一趟）

```
[executed model 节点] --Fork draft here--> createPipelineDraftFromNode
      │                                            │
      ▼                                            ▼
DraftRegistry.put(draft态) ──► mergeDraftsIntoModel ──► 森林上出现虚线草稿子节点(自动选中)
      │
[右抽屉编辑] --patchParams--> Registry 更新, validation 清空, 回 draft 态
      │
[Validate] --validatePipelineDraft--> validating → valid/invalid (节点变色 + 抽屉列 checks)
      │
[Execute] --executePipelineDraft(hash-gate)--> pending(金脉冲)
      │                                            │
      ▼                                            ▼
现有 pending 轮询(pendingFocusTarget) ──indexed──► refetch 森林 ──► 真 child 出现
      │
DELETE 草稿 json + Registry.delete(draftId) ──► 移除叠加层(真节点已在森林中)

[重载/进场] GET /pipeline-drafts ──► hydrate 未执行草稿回注册表 ──► 合并层重新注入图上
```

## 7. 边界 / 错误处理

- **多草稿同源扇出**：合并层给每草稿稳定 `nodeKey`（`draft:{draftId}`），布局自然分开。
- **validate 失败**：节点 `invalid` 红态，抽屉列 `checks`（复用现 DraftValidationResult 渲染），可继续改。
- **execute hash 冲突（409）**：复用现有「refetch latest draft、validation 置空、提示重验」逻辑。
- **弃置草稿**：`DELETE` 真删 json（+ dedupe 文件）+ Registry delete，不留孤儿。
- **hydrate 时源节点已 execute / 已删**：list 只返回未执行草稿；若草稿指向的源节点已不在当前 head-set，按「源节点不可见」跳过注入。
- **DELETE 幂等**：删不存在的 draft 返回 204/404 不报错，前端容忍（并发弃置安全）。
- **草稿落点源节点在当前 head-set 不可见**（跨 head 折叠）：合并层跳过注入该草稿并在抽屉提示（degrade-not-crash）。
- **并发 execute 多草稿**：各 draft 独立 pending 轮询 key（现 `pendingQueryKey` 已含 op_node_id，天然区分）。
- **只能从 executed 节点 fork**：后端 create 校验 `indexed_hash == source_node_hash`（`api.py`），故草稿节点上**不出现** Fork draft（不能草稿套草稿）；抽屉工具栏据 `lifecycleState` 隐藏 Fork。

## 8. 测试计划

**后端单测（新增端点）**
- `PipelineDraftStore.list()`：空目录、多草稿、损坏 json 跳过、返回摘要字段正确。
- `PipelineDraftStore.delete()`：删 json + dedupe 文件、幂等（删不存在不报错）、draft_id 校验。
- `GET /pipeline-drafts` / `DELETE`：HTTP 层 happy path + 404/校验错误映射。

**前端单测**
- `draftRegistry`：put/patch/validate/execute/delete 各态迁移；hydrate 灌入；多草稿并存。
- `mergeDraftsIntoModel`：注入单/多草稿、稳定 nodeKey、源节点不可见时跳过、执行后移除。
- `DetailHeader`：工具栏常驻可见（不被长 id 挤出）、id 截断、上下文按钮（executed→Fork / draft→Validate+Execute）。
- `NodeActionMenu`：「Fork draft here」不导航、写 Registry。
- `GraphNode`：各 `lifecycleState` 渲染分支。

**集成 / E2E**
- fork → edit → validate → execute → 真 child 就地出现（无路由跳转）+ 草稿 json 被 DELETE。
- 多草稿并行：两条 what-if 共存、各自独立 validate/execute。
- **重载持久**：建草稿 → 重载 → GET 列表 hydrate → 草稿仍在图上。
- 409 冲突路径。

**Gate（发版把关）**
- 后端仅新增 list/delete（不产 artifact/图谱）；**golden 应 0-drift**，须 `git diff` 核验无夹带。
- `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`（在 worktree 内跑；FE 用 `frontend/node_modules/.bin/vitest`）。

## 9. 明确 defer（backlog 登记）

- **内联编辑器**（brainstorm 编辑面 B 方案）：草稿节点旁浮层编辑，v1.6.7.x 打磨。
- **多草稿并排 diff**：→ v1.6.8（compareWithSource 升级通用双节点 diff）。
- **Pipeline 标签页彻底删除**：本版仅退役入口，视图代码保留。
- **草稿 GC / 陈旧回收**：长期未执行草稿的自动过期清理（本版有 DELETE 手动清理即够）。

## 10. 交付判据

- 不打开新路由，在一个 model 节点上完成「Fork draft → 改参数 → Validate → Execute → 看到新 child 节点就地长出」。
- 多个草稿可并行共存于同一张森林图，状态各异、互不干扰。
- **草稿跨重载持久**：重载后未执行草稿仍在图上；弃置 / 执行成功后 json 被真删，不留孤儿。
- 抽屉 Actions/草稿控件无需横拖面板即可触达。
- 后端 golden 0-drift（仅新增 list/delete，不产 artifact）；gate 全绿。
- `DraftGraphRoute` 深链接仍可用；Pipeline 标签页入口已退役。
