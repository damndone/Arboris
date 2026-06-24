# v1.6.1 续作对接（HANDOFF）

新会话从这里接上。**当前：2A + 2B + 2C 功能闭环全部完成。NEXT = (A) 决定是否把 ForestCanvas 接进 live app 路由（已知集成缺口），然后 (B) 2C QA/Reviewer 收尾 + 用户授权后 push/merge/tag。**

## 0. 一句话状态
worktree `.worktrees/workbench-v1.6.1`，branch `workbench-v1.6.1` @ `15c2b8f`+（off origin/main `61d45ef` = tag v1.6.0），**未 push / 未 merge / 未 tag**。venv 已建（worktree 根 `.venv`，全 extras）+ 前端 `npm ci` 已装。**GATE PASSED：BE 1202 / golden 23 0-drift / FE 661 / tsc 0。**

## 0.4 2C 已完成（5 loop，功能闭环；GATE PASSED FE 661 +24）
- **2C.1** `graphViewTypes.ts`（EditableControl 对齐 + HeadSet*/ForestViewModel + `opNodeId`）+ `graphAdapter.ts::adaptHeadSet`。森林节点身份 = dedup key（node_hash 或 bare node_id），**非 node_id**（M1/M2 共享 id）；`opNodeId` 留原始 id 作 from_node。
- **2C.2** `controls/controlFactory.tsx`：`CONTROL_REGISTRY` 查表（**无 switch**），8 kind 全注册，day-1 仅 select+columns 启用，其余占位；`visible_when` 透传不强制。
- **2C.3** `detail/RerunContext.tsx`（Provider）+ `api.ts::rerunFromNode/getRunGraphHeadSet` + `OperationSection.tsx`（有 Provider→可编辑、无→只读降级）+ actionRegistry `rerunFromNode` 点亮（invoke=openDetail）。提交 = 仅改动键 op_overrides + from_node=opNodeId；成功不跳转（onRerun=refetch）。
- **2C.4** `graph/forestGraph.ts`（parentMap/tracePath/headActiveSet 纯函数）+ `graph/ForestCanvas.tsx`。**决策：另建 ForestCanvas 而非改 648 行 GraphCanvas**（G3：功能闭环，视觉/layout 精修另算；GraphNode 绑 ReactFlow Handle）。
- **2C.5** rollback = ForestCanvas 纯 useState 切 active head（零 fetch、零 mutation、forest 对象不变）。

## 0.45 ⚠️ 已知集成缺口（NEXT 决策点）
`ForestCanvas` 功能完整但**尚未挂进 live app 路由**——run-detail 视图仍渲染旧 `GraphCanvas`（per-run），没有 head-set 拉取（`getRunGraphHeadSet` 已就绪未被调用）+ forest 开关。要让用户真正用上跨 run 森林编辑，需一个集成 loop：在 run 详情处 flag-gated 挂 `ForestCanvas`（`WORKBENCH_GRAPH_HEADSET` 或前端 toggle）。**这是 plan 之外的整合工，2C 各 loop 文件清单未含**（plan 假设原地改 GraphCanvas）。建议作为 2C.6 / 集成 loop，需与用户确认范围。

## 0.5 2B 已完成（4 loop，GATE PASSED：BE 1202 / golden 23 0-drift / FE 637 / tsc 0）
- **2B.1** `lineage/family.py::scan_family(runs_dir, run_id) -> Family{self_id, ancestors, descendants, siblings, members:{run_id->FamilyMember{run_id,rerun_of,legacy}}}`。legacy = 无 `node_index.json`。
- **2B.2** `lineage/headset.py::build_headset(runs_dir, family, *, annotate) -> {nodes(by node_hash), edges:[{source,target}], heads:[{run_id,head_node_hash,from_node,rerun_of,rerun_reason,status,created_at}], schema_version=4, legacy}`。`api.get_run_graph` 加 `view` query：`?view=headset` 或 `WORKBENCH_GRAPH_HEADSET=1` → head-set；否则旧形状。target legacy(无 node_index) + headset 请求 → 旧形状 + `legacy:true`。dedup key = node_hash（cacheable）或 bare node_id（raw 等，家族内确定性共享）。
- **2B.3** rerun 无新生产代码：已走 2A 增量路径。from_node = 被替换 op 节点；M1/M2 是 cleaning 下兄弟（无 estimation→estimation 链）。`recomputed_changed` 仍 reserved（model-node-only 编辑下上游 hash 不变，不可达）。
- **2B.4** `api._annotate_editable_node(node, manifest, form=None)` + `_backfill_schema_values`（COPY 不改共享 capabilities）。head-set 传 `run_inputs.form` → `editable_schema[i].value` 回填真实当前值，`editable_schema_source="run_inputs"`；空/缺 key 保留 capabilities 默认；旧 per-run 路径不变（`"capabilities"`）。

## 0.6 2C 要消费的 BE 契约（head-set）
`GET /runs/{id}/graph?view=headset` → 上面的 head-set 形状。FE 在现有 `GraphCanvas` 上：按 node_hash 去重并集 DAG、分叉、active head、trace、rollback（G3：不绑 layout 重构）。control_factory 消费 `editable_schema`（带回填 value）。`POST /runs/{id}/rerun` body `{from_node, op_overrides, rerun_reason}`。

## 1. 先读这四份（按序）
1. `docs/superpowers/HANDOFF-v1.6.1.md`（本文）
2. `docs/superpowers/plans/v1.6.1-progress.md` — 每个 loop 的 progress note（已做到 2A.7）
3. `docs/superpowers/specs/2026-06-23-...-design.md`（**看 §15 changelog，尤其 v5 务实重定义**）
4. `docs/superpowers/plans/2026-06-23-...-incremental.md` — 按 loop 的实施计划（2B/2C 全文在此）

## 2. 接上后先验基线
```bash
cd .worktrees/workbench-v1.6.1
./scripts/gate.sh        # 期望 GATE PASSED：BE 1189 / golden 23 0-drift / FE 637 / tsc 0
```
不绿先查环境，别往下做。

## 3. 关键决策（别推翻，已是定论）
- **复用拆两层（spec v5）**：identity reuse（上游 stage-output `node_hash` 相同 → 森林去重 + trace/rollback 证上游未变）+ compute skip（day-1 仅 MICE 真跳过）。完整 ctx rehydrate / 任意 stage skip → **Slice 3**（estimation 前 ctx 是自定义对象一坨，不可干净序列化——实测结论）。
- **2A.7 = node_index.json**（node_id→node_hash/cas_ref/producing_stage），decorate-only，graph.json 字节不变。
- trace 状态：`miss_executed / hit_reused / recomputed_same_hash / recomputed_changed`。

## 4. NEXT = 2B（Graph Contract），按 plan 的 loop
- **2B.1** family scanner（`lineage/family.py`，serve-layer 扫 run manifests 的 `rerun_of`，含混合 legacy/new 家族；不改 graph.json）
- **2B.2** head-set 响应（`lineage/headset.py`，`GET /graph` 按 `WORKBENCH_GRAPH_HEADSET` flag 默认关/非破坏；按 `node_hash` 严格去重——**消费 2A.7 的 `node_index.json`**）
- **2B.3** `/rerun` HTTP 接线 + from_node 替换语义（spec §3.4：被替换节点，复用边界 = `parents`；`recomputed_changed` 状态在这里靠 parent trace 实现）
- **2B.4** 兄弟语义 + `editable_schema.value` 回填（`api.py::_annotate_editable_nodes` 读 run_inputs 实际值）

然后 **2C**（FE 森林，在现有 `GraphCanvas` 上、**不绑 layout 重构 G3**）：2C.1 types+adapter → 2C.2 control_factory（**绝不按 kind 直写 switch**）→ 2C.3 可编辑 OperationSection 接 `/rerun` → 2C.4 forest canvas → 2C.5 rollback（非 mutation）。

## 5. 执行铁律
- 每 loop 一闭环；subagent 只吃单 loop（机械/接线/前端**内联**做，subagent 仅核心逻辑 + 两角色对抗审查，撞限额内联兜底）；**subagent 不传 model 参数**。
- **每个 implementer/subagent prompt 一律禁止 `git push`**。
- 门禁 `./scripts/gate.sh` **绝不裸 pytest**；**golden 0-drift 硬门禁**；feature flags 默认 OFF。
- 推进节奏 = **section 检查点**（2B 全部 loop 跑完再向用户汇报，2C 同理）。
- **推 main / merge / 移动 tag 需用户单独授权。**
- 护栏 R1–R9 / G1–G3 / A–D patch 见 spec §5/§6 + plan。

## 6. 2A 产出的可消费接口（2B/2C 要用）
- `lineage/hashing.py::node_hash(parent_hashes, op_spec, pipeline_version)`
- `lineage/node_store.py`：`write_node_result/read_node_result/node_result_exists/add_head_ref/heads_for_node`（CAS 在 `<project_root>/data/node_results/`）
- `lineage/op_spec.py::op_spec_for_stage(stage, *, form, config)`
- `lineage/incremental.py::run_pipeline_traced(...)` + `incremental_trace.json`（每 run，flag 开时）
- `lineage/imputation_cache.py`（MICE materialize/restore）
- `lineage/node_index.py::write_node_index` → 每 run 的 `node_index.json`（**2B.2 去重靠它**）
- `flags.py`：`incremental_cache() / force_full_recompute() / graph_headset()`
