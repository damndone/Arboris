# Workbench v1.6.1 — 真·谱系图 Slice 2 实施计划（Loop Engineering）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐 loop 实现。步骤用 `- [ ]` 复选框跟踪。**本计划按 Loop 组织，不按文件——loop 是工程控制单元，文件只是实现位置。**

**Goal:** 把执行模型从“run 级全量”升级为“stage-output 级内容寻址 Merkle 增量”，让血缘图成为可 fork / 回滚 / 跨 run 回溯的持久操作面（model 节点 day-1）。

**Architecture:** Route 2 演进——复用 v1.6.0 不可变 run + `rerun_of` + 内容寻址地基；新增节点结果 CAS + per-stage-output Merkle `node_hash`；缓存 wrapper 包住可缓存 stage（命中跳过 + dual-write）；`GET /graph` flag 化升级为 head-set 家族并集；FE 在现有 `GraphCanvas` 上消费 head-set。

**Tech Stack:** Python 3.11 / pandas / FastAPI（后端）；React 18 + Vite + TypeScript + vitest（前端）；pytest + golden 快照门禁。

**Spec:** `docs/superpowers/specs/2026-06-23-workbench-v1.6.1-lineage-forest-merkle-incremental-design.md`（v3）。

---

## 全局约束（每个 loop 都适用）

- **门禁**：`./scripts/gate.sh`（后端全量 `python -m pytest` + golden 三件套 `tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py` + 前端 `vitest` + `tsc --noEmit`）。**绝不裸 pytest**。
- **golden 0-drift 硬门禁**：任何 loop 结束 golden 三件套必须 0 漂移。CAS/增量层在“首次/无编辑”路径产物字节级不变（写 CAS 是副作用、不改结果）。
- **feature flags**（默认全 OFF，保证 ship-dark）：`WORKBENCH_INCREMENTAL_CACHE`（0=旧全量执行）、`WORKBENCH_FORCE_FULL_RECOMPUTE`（1=即使有缓存也全算，调试二分用）、`WORKBENCH_GRAPH_HEADSET`（0=`GET /graph` 旧形状）。读取入口统一 `backend/workbench/flags.py`。
- **结构化证据**：增量执行每 run 产出 `incremental_trace.json`（数组：`{stage, node_hash, op_spec_hash, status: miss|hit|skip, parents:[...]}`）。
- **护栏**：R1–R9（缓存中毒/粒度/去重/膨胀/legacy/并发/确定性边界/MLE/副作用物化）、G1–G3（2A 先证 model fork 最小链路 / CAS 命中须生成完整 run 目录 / FE 不绑 layout 重构）见 spec §5/§6。
- **subagent 只吃单闭环**（不派“实现 2A”）；**每个 implementer prompt 禁止 `git push`**；subagent 不传 model 参数。
- **每个 loop 结束写一条 Progress note**（见各 loop 末尾固定格式），追加到 `docs/superpowers/plans/v1.6.1-progress.md`。
- **环境**：worktree `.worktrees/workbench-v1.6.1`，venv `.venv`（`~/.local/bin/python3.11 -m venv .venv` + `pip install -e ".[dev,panel,ml,imbalanced,imputation]" jsonschema`）；前端 `cd frontend && npm ci`。

---

## 文件结构图（实现位置，决策在 loop）

**后端（新增）**
- `backend/workbench/flags.py` — feature flag 读取（env → bool）。
- `backend/workbench/lineage/node_store.py` — 节点结果 CAS + 引用账本（镜像 `upload_store.py`）。
- `backend/workbench/lineage/op_spec.py` — 每个 cacheable stage 的稳定 `op_spec` 提取（含 RNG seed）。
- `backend/workbench/lineage/incremental.py` — 缓存 wrapper（dry-run / 命中 rehydrate / dual-write）+ `incremental_trace` 写出。
- `backend/workbench/lineage/family.py` — serve-layer family 扫描（含混合 legacy/new）。
- `backend/workbench/lineage/headset.py` — head-set 图响应构建（flag 化）。

**后端（改造）**
- `backend/workbench/lineage/hashing.py` — 新增 `node_hash(...)`（保留旧 `dag_hash`）。
- `backend/workbench/orchestrator/__init__.py` `_run_workflow` — 包缓存 wrapper（按 cacheable boundary；RecordingStage 特判）。
- `backend/workbench/engine/stages/recording.py` — 图节点盖 `node_hash`/`cas_ref`/`producing_stage`（payload_ref 保留 run-relative）。
- `backend/workbench/engine/context.py` `DataHandle` — 增加从缓存产物重建的构造。
- `backend/workbench/api.py` — `editable_schema.value` 回填；`get_run_graph` flag 化 head-set；`/rerun` 接增量执行 + from_node 元数据。

**前端（新增/改造）**
- `frontend/src/lineage/api/graphViewTypes.ts` — `EditableControl` 对齐后端 + head-set/NodeView/heads 类型。
- `frontend/src/lineage/api/graphAdapter.ts` — head-set → 并集 DAG（hash 去重）。
- `frontend/src/lineage/controls/controlFactory.tsx`（新）— `editable_schema → 控件`。
- `frontend/src/lineage/detail/sections/OperationSection.tsx` — 只读 → 可编辑接 `/rerun`。
- `frontend/src/workbench/registry/actionRegistry.ts` — 点亮 `rerunFromNode`。
- `frontend/src/lineage/graph/GraphCanvas.*` — 渲染 head-set 并集（hash 去重/分叉/active head/trace/rollback）。
- `frontend/src/api.ts` — `rerunFromNode` client + family 拉取。

**共享 fixture**
- `tests/fixtures/forest_min.csv` — 小 CSV（≥35 行，达到 model 阶段），用于 `C → M1/M2` fork。所有 BE/FE loop 共用。

---

## Loop 0：基线锁定

```
Loop 0: 基线锁定
Input:  origin/main 61d45ef、worktree .worktrees/workbench-v1.6.1（已建）
Change: 不写业务代码，只确认环境可信
Verify: git status / git rev-parse HEAD / ./scripts/gate.sh
Exit:   记录 baseline 测试数、golden 数、失败=0
Fallback: baseline 不绿 → 停止实现，先修环境或确认 base 错误
```

- [ ] **Step 1：确认 worktree 与 base**
  Run: `git -C .worktrees/workbench-v1.6.1 rev-parse HEAD`
  Expected: `61d45ef...`（或其上仅 spec/plan 文档提交）。
- [ ] **Step 2：建/激活 venv + 前端依赖**（见全局约束环境）。
- [ ] **Step 3：跑全门禁**
  Run: `cd .worktrees/workbench-v1.6.1 && ./scripts/gate.sh`
  Expected: `>>> GATE PASSED`；记录 BE 测试数（基线 1170）、golden 23、FE 637、tsc 0。
- [ ] **Step 4：写基线进 progress**
  追加 `docs/superpowers/plans/v1.6.1-progress.md`：基线数 + “失败=0”。
- [ ] **Step 5：建共享 fixture `tests/fixtures/forest_min.csv`**（≥35 行，含一个连续 y + 两个 x，能跑到 model 阶段；用于 a→b→c fork）。提交。

> **Progress note** — Loop: 0 / Changed: env+fixture / Verified: gate PASSED, baseline recorded / Known risk: none / Next: 2A.1

---

## 2A — BE 节点结果 CAS / Merkle / 增量执行

### Loop 2A.1：Hash Contract

```
Loop 2A.1: node_hash 算法钉死（含 seed）
Input:  lineage/hashing.py（已有 canonicalize / dag_hash / PIPELINE_VERSION）
Change: 新增 node_hash(parent_hashes, op_spec, PIPELINE_VERSION)
Verify: parent 顺序无关；op_spec/seed/pipeline 变则变；run_id/time 不进
Exit:   纯单测通过
Fallback: 只回滚 hashing 文件 + 测试
```

**Files:** Modify `backend/workbench/lineage/hashing.py` · Test `tests/test_node_hash.py`

- [ ] **Step 1：写失败测试** `tests/test_node_hash.py`

```python
from workbench.lineage.hashing import node_hash, PIPELINE_VERSION

def test_parent_order_irrelevant():
    a = node_hash(["h1", "h2"], {"k": 1}, PIPELINE_VERSION)
    b = node_hash(["h2", "h1"], {"k": 1}, PIPELINE_VERSION)
    assert a == b

def test_op_spec_change_changes_hash():
    a = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"model_type": "iv_2sls"}, PIPELINE_VERSION)
    assert a != b

def test_seed_change_changes_hash():
    a = node_hash(["h1"], {"random_seed": 1}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"random_seed": 2}, PIPELINE_VERSION)
    assert a != b

def test_pipeline_version_change_changes_hash():
    a = node_hash(["h1"], {"k": 1}, "v1.6.0-pipeline-1")
    b = node_hash(["h1"], {"k": 1}, "v9.9.9-pipeline-9")
    assert a != b

def test_runid_time_not_in_op_spec_path():
    # op_spec excludes volatile fields by contract; same logical op → same hash
    a = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    b = node_hash(["h1"], {"model_type": "ols"}, PIPELINE_VERSION)
    assert a == b
```

- [ ] **Step 2：跑测试确认失败** — Run: `.venv/bin/python -m pytest tests/test_node_hash.py -v` → FAIL（`node_hash` 未定义）。
- [ ] **Step 3：实现** — 在 `hashing.py` 追加：

```python
def node_hash(parent_hashes: list[str], op_spec: dict, pipeline_version: str = PIPELINE_VERSION) -> str:
    """Merkle hash of a cacheable unit. Parent order-independent (sorted);
    op_spec is the unit's structural spec (volatile fields like run_id/started_at
    MUST be excluded by the caller in op_spec extraction, not here)."""
    return _sha(canonicalize([sorted(parent_hashes), op_spec, pipeline_version]))
```

- [ ] **Step 4：跑测试确认通过** — Run 同 Step 2 → PASS（5 passed）。
- [ ] **Step 5：跑 golden 确认 0-drift** — Run: `.venv/bin/python -m pytest tests/test_engine_golden.py -q` → PASS（纯新增，无触碰）。
- [ ] **Step 6：Commit** — `git add backend/workbench/lineage/hashing.py tests/test_node_hash.py && git commit -m "feat(2A.1): node_hash Merkle contract (seed-aware)"`

> **Progress note** — Loop: 2A.1 / Changed: hashing.py +node_hash / Verified: 5 unit + golden 0-drift / Known risk: op_spec volatile-field exclusion enforced in 2A.3 / Next: 2A.2

---

### Loop 2A.2：NodeResult CAS + 引用账本

```
Loop 2A.2: CAS 最小读写 + ref ledger
Input:  upload_store.py 模式
Change: 新增 lineage/node_store.py
Verify: 同 hash 幂等写；metadata 可读回；ref ledger add/read；live head→hash 可查
Exit:   不接 orchestrator，CAS 单测绿
Fallback: CAS 模块单独回滚
```

**Files:** Create `backend/workbench/lineage/node_store.py` · Test `tests/test_node_store.py`

- [ ] **Step 1：写失败测试** `tests/test_node_store.py`

```python
from workbench.lineage.node_store import (
    write_node_result, read_node_result, node_result_exists,
    add_head_ref, heads_for_node,
)

def test_idempotent_write(tmp_path):
    h = "abc123"
    meta = {"status": "ok", "stats": {"r2": 0.4}, "summary": "x"}
    write_node_result(tmp_path, h, meta=meta, artifacts={"model.json": b"{}"})
    write_node_result(tmp_path, h, meta=meta, artifacts={"model.json": b"{}"})  # again
    assert node_result_exists(tmp_path, h)
    got = read_node_result(tmp_path, h)
    assert got["meta"]["stats"]["r2"] == 0.4
    assert got["artifacts"]["model.json"] == b"{}"

def test_ref_ledger(tmp_path):
    add_head_ref(tmp_path, head_run_id="run_002", node_hash="abc123")
    assert "run_002" in heads_for_node(tmp_path, "abc123")
```

- [ ] **Step 2：跑确认失败** — `.venv/bin/python -m pytest tests/test_node_store.py -v` → FAIL.
- [ ] **Step 3：实现** `node_store.py`（镜像 `upload_store.py`，blobs 在 `<project_root>/data/node_results/<node_hash>/`：`meta.json` + `artifacts/<name>`；ref ledger = `data/node_results/_refs.json`，`{node_hash: [run_id,...]}`，add 幂等去重）。函数签名严格按测试：`write_node_result(project_root, node_hash, *, meta, artifacts)`、`read_node_result(project_root, node_hash) -> {"meta":..., "artifacts": {name: bytes}}`、`node_result_exists`、`add_head_ref(project_root, *, head_run_id, node_hash)`、`heads_for_node(project_root, node_hash) -> list[str]`。
- [ ] **Step 4：跑确认通过** → PASS（2 passed）。
- [ ] **Step 5：Commit** — `git commit -m "feat(2A.2): node-result CAS + reference ledger"`

> **Progress note** — Loop: 2A.2 / Changed: node_store.py / Verified: idempotent write + ref ledger / Known risk: GC 仅留口 / Next: 2A.3

---

### Loop 2A.3：Stage op_spec 提取（含 RNG seed）

```
Loop 2A.3: 每个 cacheable stage 的稳定 op_spec
Input:  config.random_seed=20260429；cs/sa seed=20260615；dcdh=20260622；B/alpha
Change: 新增 lineage/op_spec.py，为 cacheable stage 生成 op_spec
Verify: 同输入 op_spec 一致；改 model 参数只改 estimation+下游 op_spec；run_id/path/time 不进；seed 进
Exit:   op_spec snapshot 测试通过
Fallback: 不接缓存，只修 op_spec
```

**Files:** Create `backend/workbench/lineage/op_spec.py` · Test `tests/test_op_spec.py`

- [ ] **Step 1：写失败测试** `tests/test_op_spec.py`

```python
from workbench.lineage.op_spec import op_spec_for_stage

def test_op_spec_stable_same_inputs():
    s1 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    s2 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    assert s1 == s2

def test_op_spec_excludes_volatile():
    s = op_spec_for_stage("estimation", form={"model_type": "ols", "run_id": "x", "started_at": "t"}, config={"random_seed": 20260429})
    assert "run_id" not in s and "started_at" not in s

def test_op_spec_includes_seed():
    s = op_spec_for_stage("imputation", form={}, config={"random_seed": 20260429})
    assert s.get("random_seed") == 20260429

def test_model_change_isolated_to_estimation():
    src1 = op_spec_for_stage("source", form={"model_type": "ols"}, config={"random_seed": 20260429})
    src2 = op_spec_for_stage("source", form={"model_type": "iv_2sls"}, config={"random_seed": 20260429})
    assert src1 == src2   # upstream unaffected by model_type
    est1 = op_spec_for_stage("estimation", form={"model_type": "ols"}, config={"random_seed": 20260429})
    est2 = op_spec_for_stage("estimation", form={"model_type": "iv_2sls"}, config={"random_seed": 20260429})
    assert est1 != est2
```

- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现** `op_spec.py`：`op_spec_for_stage(stage_name, *, form, config) -> dict`。每 stage 声明它消费的 form/config 键白名单（source 只看 upload-affecting；estimation 看 model_type/covariance/iv_*/entity_*/time_*；imputation 看 imputation method + random_seed；diagnostics/prediction 看 random_seed + prediction params；cs/sa/dcdh 估计看 seed/B/alpha/cluster）。**显式剔除 volatile**（run_id/started_at/path）。**所有可能消费 RNG 的 stage 必须显式带 seed**（R1/R8）。
- [ ] **Step 4：跑确认通过** → PASS（4 passed）。
- [ ] **Step 5：Commit** — `git commit -m "feat(2A.3): per-stage op_spec extraction incl RNG seed"`

> **Progress note** — Loop: 2A.3 / Changed: op_spec.py / Verified: stability + seed + volatile-exclusion + model isolation / Known risk: 白名单需覆盖未来 stage / Next: 2A.4

---

### Loop 2A.4：Cache Wrapper Dry-Run

```
Loop 2A.4: wrapper 只算 hash + 写 trace，不跳过 stage
Input:  node_hash / op_spec 就绪
Change: incremental.py wrapper 包 _run_workflow；仅计算+写 incremental_trace.json；不改执行
Verify: 正常 run 产物 0-drift；每个 cacheable stage 有 hash trace；RecordingStage 不在缓存列表
Exit:   golden 不漂移
Fallback: 关闭 WORKBENCH_INCREMENTAL_CACHE flag
```

**Files:** Create `backend/workbench/lineage/incremental.py`, `backend/workbench/flags.py` · Modify `backend/workbench/orchestrator/__init__.py:452-453`（`for stage in PIPELINE: ctx = stage.run(ctx, env)`）· Test `tests/test_incremental_dryrun.py`

- [ ] **Step 1：写失败测试**（用 forest_min.csv 跑一次 run，断言 `incremental_trace.json` 含 source/clean/.../estimation/diagnostics/report 的条目、不含 `RecordingStage`，且每条有 `node_hash`+`op_spec_hash`+`parents`；且对照 golden 产物字节不变）。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现** `flags.py`（`incremental_cache()`/`force_full()`/`graph_headset()` 读 env，默认 False）；`incremental.py` 的 `wrap_pipeline(pipeline)` —— 遍历时为每个 **cacheable stage**（source/clean/profile/validation/routing/imputation/estimation/diagnostics/report；**排除 RecordingStage/reliability 等非缓存**）算 `node_hash`（父 = 上游缓存单元 hash），`status="miss"` 写 trace，**仍调用原 `stage.run`**（dry-run 不跳过）。在 `_run_workflow` 用 flag 包：`flags.incremental_cache()` 时走 wrapper，否则原样。
- [ ] **Step 4：跑确认通过 + golden 0-drift** — Run: `.venv/bin/python -m pytest tests/test_incremental_dryrun.py tests/test_engine_golden.py -q` → PASS。
- [ ] **Step 5：Commit** — `git commit -m "feat(2A.4): cache wrapper dry-run + incremental_trace (no skip)"`

> **Progress note** — Loop: 2A.4 / Changed: incremental.py, flags.py, orchestrator wrap / Verified: trace complete, RecordingStage excluded, golden 0-drift / Known risk: parent-hash 串联在 2A.5 验真 / Next: 2A.5

---

### Loop 2A.5：Materialized imputation cache + identity trace

> **PM 决策 v2（2026-06-23，实测后务实重定义）**：实测证明“estimation 前完整 ctx 可干净序列化”不成立（ctx 含 DatasetSchema/DecisionPoint/WorkbenchConfig 等自定义对象）。继续做 upstream bundle 会把本版拖成 ctx-序列化重构，风险/收益不匹配。**复用拆两层**：(1) **Identity reuse** — 上游 stage-output `node_hash` 相同，森林严格去重、trace/rollback 证明上游没变；(2) **Compute skip** — 本版只对**干净、收益明确的 MICE imputation** 做真跳过；其余上游 stage 可重算，但 `node_hash` 必须一致、图上表现为同一共享前缀。**完整 per-stage ctx rehydrate / 任意 stage skip → Slice 3。**

```
Loop 2A.5: Materialized imputation cache + identity trace
Input:  2A.1–2A.4 已有 node_hash、op_spec、dry-run trace
Change: 不实现 upstream ctx bundle。只缓存 MICE imputation 的 materialized outputs：
        processed/imputed_dataset.parquet + imputation_summary.json + DataHandle identity metadata。
        其他 stage 记录 node_hash / status trace，但不跳过执行。
Verify: no-MICE run: 上游 stage 重算，但 node_hash 与 parent run 相同；
        MICE run: imputation 命中后不重跑 MICE，直接物化 run-relative artifacts；
        child run 目录仍完整（G2）；force-full vs imputation-hit run 产物逐字节一致。
Exit:   MICE 是本版唯一真实上游 compute-skip；其余上游以 node_hash identity 证明共享。
Fallback: 关闭 imputation cache，保留 node_hash identity trace。
```

**trace 状态 taxonomy（替换 hit/miss，避免误导）**
```
miss_executed         # 首次执行或 hash 未命中
hit_reused            # 真实跳过执行，复用 CAS 产物（day-1 主要是 MICE）
recomputed_same_hash  # 重新执行，但 hash 与既有/parent 节点一致 → 图层身份复用
recomputed_changed    # op_spec/input 改变，hash 改变
```

**Files:** 新增 `backend/workbench/lineage/imputation_cache.py`（materialize/restore MICE 产物）· Modify `backend/workbench/lineage/incremental.py`（状态 taxonomy + imputation 命中）· Test `tests/test_imputation_cache.py` · Fixture `tests/fixtures/forest_min_missing.csv`（含缺失，触发 MICE）

- [ ] **Step 1：建缺失 fixture** `forest_min_missing.csv`（在 forest_min 基础上对若干 wage/x 置空，使 imputation 真跑 MICE）。
- [ ] **Step 2：写失败测试**：① `WORKBENCH_INCREMENTAL_CACHE=1` + imputation 请求，同 project 跑两次：第一次 imputation `miss_executed`、第二次 `hit_reused`（MICE 不重跑）；断言第二次 run 目录仍含 `processed/imputed_dataset.parquet`、`model_results/*.json`、`reports/report.html`（**G2**）。② `WORKBENCH_FORCE_FULL_RECOMPUTE=1` 跑同输入，断言 imputation-hit 产物与 force-full 产物**逐字节一致**。③ no-MICE forest_min：上游 stage trace 标 `recomputed_same_hash`（node_hash 跨两次 run 相同）。
- [ ] **Step 3：跑确认失败** → FAIL.
- [ ] **Step 4：实现** `imputation_cache.py`（按 imputation node_hash materialize 帧+summary 到 CAS；命中则 restore + 物化 run-relative）；`incremental.py` 在 ImputationStage 处：命中且非 force-full → 跳过 MICE、注入缓存帧/summary、status `hit_reused`；否则跑、写 CAS、status `miss_executed`。其余 cacheable stage 照跑，status 按 taxonomy（对 parent trace 比对 same/changed）。`add_head_ref` 记账。
- [ ] **Step 5：跑确认通过**（MICE hit + G2 + 逐字节 + no-MICE identity）→ PASS.
- [ ] **Step 6：跑全 golden（flag off）** → 0-drift。
- [ ] **Step 7：Commit** — `git commit -m "feat(2A.5): materialized MICE imputation cache + identity trace taxonomy"`

> **Progress note** — Loop: 2A.5 / Changed: imputation_cache.py, incremental.py (taxonomy + MICE hit), forest_min_missing fixture / Verified: MICE hit_reused + G2 + byte-identical + no-MICE recomputed_same_hash + golden 0-drift / Known risk: full ctx rehydrate deferred to Slice 3 / Next: 2A.6

---

### Loop 2A.6：Model override identity incrementality（不走 HTTP）

> **主证据 = node_hash 身份复用**（上游同 hash → 森林共享前缀去重）；compute-skip 证据只要求覆盖 MICE。

```
Loop 2A.6: Model override identity incrementality
Input:  CAS / op_spec / wrapper / imputation-cache 完成
Change: 引擎内部入口传 model op_spec override（不走 POST /rerun，不依赖 head-set）
Verify: 上游 stage-output node_hash 与 parent 相同；森林前缀可按 node_hash 去重；
        estimation/model node_hash 改变；diagnostics/report node_hash 改变；
        若存在 MICE，imputation 是 hit_reused；force-full vs selective-cache 产物逐字节一致
Exit:   增量证明主证据 = node_hash 身份复用；compute-skip 覆盖 MICE
Fallback: engine override 关闭，保留 full rerun
```

**Files:** Modify `backend/workbench/orchestrator/__init__.py`（增量入口可接 `op_overrides`）· Test `tests/test_engine_increment_fork.py`

- [ ] **Step 1：写失败测试**：用 forest_min_missing.csv（带 MICE）跑 run A（model=ols）→ 记录各 stage `node_hash`。引擎内部入口以 `op_overrides={"model_type": "iv_2sls"}`（或合法同形 override，如 covariance）跑 run B → 断言：source/clean/profile/routing/imputation 的 `node_hash` 与 A **完全相同**（identity 复用）；imputation 在 B 标 `hit_reused`；estimation 的 `node_hash` **不同**；diagnostics/report `node_hash` **不同**；run B 产物与 run B force-full 产物逐字节一致。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：在 `_run_workflow`（或新薄入口 `run_workflow_incremental(..., op_overrides)`）把 override 合并进 estimation 的 form → 只改 estimation 及下游 op_spec → 上游 node_hash 不变（identity 复用）+ MICE 命中跳过。**from_node 复用边界 = parents(被替换 stage)**：override 落在哪个 stage，就从该 stage 起 hash 改变，其父 stage-output node_hash 不变（spec §3.4）。
- [ ] **Step 4：跑确认通过** → PASS。
- [ ] **Step 5：Commit** — `git commit -m "feat(2A.6): model override identity incrementality (no HTTP)"`

> **Progress note** — Loop: 2A.6 / Changed: incremental engine entry / Verified: upstream node_hash identity reuse, MICE hit_reused, model+downstream hash changed, byte-identical / Known risk: HTTP wiring deferred to 2B.3 / Next: 2A.7

---

### Loop 2A.7：RecordingStage 盖 node_hash（桥）

```
Loop 2A.7: RecordingStage graph-node hash bridge
Input:  2A.6 已产出每个 stage-output 的 node_hash + incremental_trace
Change: RecordingStage 不进缓存；读 stage-output→node_hash mapping；每个 graph node 加 node_hash/cas_ref/producing_stage；payload_ref 保持 run-relative
Verify: stage:cleaned 带 clean hash；var:* 带其 stage hash；model:* 带 estimation hash；report:html 带 report hash；RecordingStage 不在 hit/miss trace；旧 graph 字段仍存在
Exit:   2B 可用 node_hash 聚合/去重 graph nodes
Fallback: 关闭 node_hash decoration，回到旧 graph.json；缓存执行仍保留
```

**Files:** Modify `backend/workbench/engine/stages/recording.py` · Test `tests/test_recording_node_hash.py`

- [ ] **Step 1：写失败测试**：跑 forest_min run，读 graph.json，断言每个图节点新增字段 `node_hash`/`cas_ref`/`producing_stage`（`stage:cleaned`→clean stage hash、`model:{id}`→estimation hash、`report:html`→report hash）；旧字段（`id`/`display_label`/`payload_ref` run-relative）原样存在；`incremental_trace.json` 不含 RecordingStage。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：`RecordingStage` 从 ctx/incremental wrapper 取 stage-output→node_hash mapping，写入每个 `add_node(...)` 的新字段；`cas_ref={node_hash, artifact}` 与 run-relative `payload_ref` **并存（dual）**。
- [ ] **Step 4：跑确认通过 + golden 0-drift**（注意：graph.json 新增字段会动 `tests/test_lineage_invariants.py`/snapshot → 这些是**加法字段**，需同步更新 golden 快照为**新增字段、非改字段**；若 golden 比较严格则在该 loop 显式 re-bless 快照并人工核“仅加字段”）。
- [ ] **Step 5：Commit** — `git commit -m "feat(2A.7): RecordingStage stamps graph nodes with node_hash/cas_ref"`

> **Progress note** — Loop: 2A.7 / Changed: recording.py / Verified: every graph node carries hash, RecordingStage uncached, additive-only graph fields / Known risk: golden re-bless 必须人工确认仅加字段 / Next: 2B.1。**至此 2A 验收（含 G1/G2）完成。**

---

## 2B — Graph Contract

### Loop 2B.1：Family Scanner（含混合 legacy/new）

```
Loop 2B.1: 通过 rerun_of 扫祖先/后代/兄弟 heads
Input:  run_inputs.json 的 rerun_of
Change: serve-layer family.py 扫 run manifests（不改 graph.json）
Verify: 构造 run_001 → run_002/run_003 家族返回完整 family；混合 legacy(无 cas_ref)/new(有 cas_ref) 不崩，old head 标 opaque/legacy
Exit:   不改 graph.json
Fallback: 只返回当前 run
```

**Files:** Create `backend/workbench/lineage/family.py` · Test `tests/test_family_scanner.py`

- [ ] **Step 1：写失败测试**：构造 3 个 run 目录（run_001 无 rerun_of；run_002/run_003 `rerun_of=run_001`），`scan_family("run_002") -> {ancestors:[run_001], descendants:[], siblings:[run_003], self:run_002}`；再构造 legacy run（无 `cas_ref`/旧 graph）混入，断言其 head `legacy=True` 且不抛异常。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现** `scan_family(project_root, run_id) -> Family`：扫 runs 目录读各 `run_inputs.json`/manifest 的 `rerun_of`，build 父子图，分类 ancestors/descendants/siblings；legacy 检测 = graph 节点无 `node_hash`。
- [ ] **Step 4：跑确认通过** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2B.1): serve-layer family scanner (mixed legacy/new)"`

> **Progress note** — Loop: 2B.1 / Changed: family.py / Verified: ancestors/descendants/siblings + mixed-family degrade / Known risk: O(n) 扫描，索引化→Slice 3 / Next: 2B.2

---

### Loop 2B.2：Head-Set 响应（flag 化 / 非破坏）

```
Loop 2B.2: GET /graph 返回 {nodes, edges, heads}，flag 默认关
Input:  family scanner + node_hash 化的 graph
Change: headset.py 构建并集 DAG（hash 去重）；GET /graph 按 WORKBENCH_GRAPH_HEADSET / ?view=headset 分流
Verify: flag=0 旧形状现有 FE 不破；flag=1 返回 head-set；同 hash 节点只一次；legacy run 走旧 graph
Exit:   API contract test 通过
Fallback: 保留旧 graph endpoint 行为（flag 关）
```

**Files:** Create `backend/workbench/lineage/headset.py` · Modify `backend/workbench/api.py`（`get_run_graph`）· Test `tests/test_graph_headset.py`

- [ ] **Step 1：写失败测试**：① `GET /runs/{id}/graph`（无 flag）→ 旧形状（`nodes` 仍是 dict-of-id、无 `heads` 键）= 现有 contract 不破（复用现有 `tests/test_api.py` 的 graph 断言不变）；② `?view=headset` 或 `WORKBENCH_GRAPH_HEADSET=1` → `{nodes: by node_hash, edges, heads:[...], schema_version, legacy}`；③ 家族里共享前缀同 hash 节点只出现一次；④ legacy run → `legacy:true` 走旧 graph。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现** `headset.py` `build_headset(project_root, family) -> dict`（按 node_hash 严格去重并集 + heads 列表）；`api.get_run_graph` 按 `flags.graph_headset()` 或 query `view=headset` 分流，默认旧形状。
- [ ] **Step 4：跑确认通过 + 现有 test_api graph 断言不变** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2B.2): head-set graph response behind WORKBENCH_GRAPH_HEADSET flag"`

> **Progress note** — Loop: 2B.2 / Changed: headset.py, api.get_run_graph / Verified: flag-off non-breaking, flag-on head-set, hash-dedup, legacy / Known risk: 默认是否切换→release 前定 / Next: 2B.3

---

### Loop 2B.3：HTTP rerun 接线 + from_node 替换语义

```
Loop 2B.3: POST /rerun 接增量 + 记录 from_node 为“被替换节点”
Input:  2A.6 引擎增量 + from_node 复用边界
Change: api /rerun 走增量执行；记录 from_node 替换元数据
Verify: payload 含 from_node=h_m1；后端记 from_node 是“被替换节点”；新 run/head 不把 M2 接 M1 后
Exit:   contract test 通过
Fallback: /rerun 回退 full rerun，CAS 保留不启用
```

**Files:** Modify `backend/workbench/api.py`（`rerun_endpoint` → 增量执行入口）· Test `tests/test_rerun_increment.py`

- [ ] **Step 1：写失败测试**：`POST /runs/{A}/rerun` body `{from_node, op_overrides:{model_type:...}, rerun_reason}` → child run B；断言 B 的 `run_inputs.json` 记 `from_node`；B 的 graph 中新 model 节点的 parent 是 A 共享的 cleaned/vars stage-output（同 node_hash），**不是** A 的旧 model 节点；B 上游 stage `hit`。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：`rerun_endpoint` 在 `flags.incremental_cache()` 时调 2A.6 增量入口（`_submit_run` 路径接 `op_overrides`），复用边界 = `parents(from_node)`。flag 关时回退现 full rerun。
- [ ] **Step 4：跑确认通过 + golden 0-drift** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2B.3): POST /rerun incremental wiring + from_node replacement"`

> **Progress note** — Loop: 2B.3 / Changed: api.rerun_endpoint / Verified: from_node replacement (C parent, not M1) / Known risk: none / Next: 2B.4

---

### Loop 2B.4：Graph 兄弟语义 + editable_schema.value 回填

```
Loop 2B.4: 兄弟分叉语义 + 编辑面真实当前值
Input:  head-set + run_inputs
Change: head-set 中 M1/M2 同父兄弟；_annotate_editable_nodes 回填 run_inputs 实际值到 editable_schema.value
Verify: M1/M2 parent=C 同 hash、互为兄弟；model node schema value 与 run_inputs.json 一致；旧 schema 兼容
Exit:   contract test 通过
Fallback: 回填关闭，schema 用 capabilities 默认值
```

**Files:** Modify `backend/workbench/lineage/headset.py`, `backend/workbench/api.py`（`_annotate_editable_nodes`）· Test `tests/test_sibling_and_value_backfill.py`

- [ ] **Step 1：写失败测试**：fork A→B 后取 family head-set，断言 model 节点 M1(A)/M2(B) 的 parent 是同一个 `node_hash`（C）、在 `heads` 里互为兄弟；`?view=headset` 的 model 节点 `editable_schema` 中 `covariance.value` == `run_inputs.json.form.covariance`（而非 capabilities 默认 `"robust"`）。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：headset 兄弟关系由共享 parent hash 自然得到（验证渲染元数据）；`_annotate_editable_nodes` 读 `read_run_inputs` 把 `form` 实际值覆盖到对应 `editable_schema[i].value`（按 key 匹配；缺失保留默认）。
- [ ] **Step 4：跑确认通过 + golden 0-drift** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2B.4): sibling semantics + editable_schema.value backfill"`

> **Progress note** — Loop: 2B.4 / Changed: headset.py, _annotate_editable_nodes / Verified: M1/M2 siblings + real current values / Known risk: none / Next: 2C.1。**至此 2B 验收完成。**

---

## 2C — FE Forest（在现有 GraphCanvas 上，不绑 layout 重构 / G3）

### Loop 2C.1：Types + Adapter

```
Loop 2C.1: head-set → 前端 ViewModel
Input:  2B head-set 契约
Change: graphViewTypes.ts（EditableControl 对齐 + head-set 类型）；graphAdapter.ts（hash 去重并集）
Verify: fixture 里共享 C 只生成一个 node
Exit:   vitest 通过
Fallback: adapter 回退旧 per-run 适配
```

**Files:** Modify `frontend/src/lineage/api/graphViewTypes.ts`, `frontend/src/lineage/api/graphAdapter.ts` · Test `frontend/src/lineage/api/graphAdapter.headset.test.ts`

- [ ] **Step 1：写失败测试**（vitest）：喂一个 head-set fixture（两个 head 共享 C 的 node_hash），`adaptHeadSet(fixture)` → 节点数组里 C 只出现一次；M1/M2 两个 model 节点；`heads` 映射保留。
- [ ] **Step 2：跑确认失败** — `cd frontend && npx vitest run src/lineage/api/graphAdapter.headset.test.ts` → FAIL.
- [ ] **Step 3：实现**：`EditableControl` 补 `role?`/`required?`/`columns` kind（对齐后端、纠正 v1.5.0 过期形）；新增 `HeadSetResponse`/`NodeView`/`Head` 类型；`adaptHeadSet` 按 `node_hash` 去重成并集 DAG。
- [ ] **Step 4：跑确认通过 + tsc** — `npx vitest run ... && npx tsc --noEmit` → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2C.1): head-set types + dedup adapter"`

> **Progress note** — Loop: 2C.1 / Changed: graphViewTypes, graphAdapter / Verified: shared C single node, tsc 0 / Known risk: none / Next: 2C.2

---

### Loop 2C.2：control_factory

```
Loop 2C.2: 控件渲染集中走工厂
Input:  editable_schema 形状
Change: 新增 controlFactory.tsx
Verify: select/radio/text/toggle/columns 结构可接；visible_when 字段保留不一定启用；OperationSection 不直接 switch kind
Exit:   组件测试通过
Fallback: controlFactory 单独回滚
```

**Files:** Create `frontend/src/lineage/controls/controlFactory.tsx` · Test `frontend/src/lineage/controls/controlFactory.test.tsx`

- [ ] **Step 1：写失败测试**：`renderControl({kind:"select", key:"covariance", options:[...], value:"robust"}, onChange)` 渲染 `<select>`；同理 radio/text/toggle/columns 各渲染对应控件；含 `visible_when` 的 control 字段被透传保留（即便 day-1 不启用）；断言**没有**按 kind 的 JSX switch 散落在 OperationSection（工厂是唯一入口）。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现** `controlFactory.tsx`：`CONTROL_REGISTRY: Record<kind, Component>`，`renderControl(control, onChange)` 查表渲染（**绝不 switch**）；day-1 启用 select/columns（数据源在手），radio/text/toggle/slider/multiselect/textarea 注册占位组件（结构可接、未必启用）。
- [ ] **Step 4：跑确认通过 + tsc** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2C.2): control_factory indirection (no kind switch)"`

> **Progress note** — Loop: 2C.2 / Changed: controlFactory / Verified: registry render + visible_when preserved + no switch / Known risk: 仅 select/columns 启用（按 spec）/ Next: 2C.3

---

### Loop 2C.3：OperationSection 可编辑

```
Loop 2C.3: model 节点可编辑并调用 /rerun
Input:  controlFactory + /rerun client
Change: OperationSection 只读→可编辑；api.ts 加 rerunFromNode
Verify: 初始值来自 editable_schema.value；提交 payload 含 from_node；成功后不跳转、刷新 family graph
Exit:   交互测试通过
Fallback: OperationSection 回退只读
```

**Files:** Modify `frontend/src/lineage/detail/sections/OperationSection.tsx`, `frontend/src/api.ts`, `frontend/src/workbench/registry/actionRegistry.ts` · Test `frontend/src/lineage/detail/sections/OperationSection.test.tsx`

- [ ] **Step 1：写失败测试**：渲染含 `editable_schema`（covariance.value="clustered"）的 model 节点 → 控件初值 "clustered"（非默认 "robust"）；改值并提交 → 调 `rerunFromNode` 且 payload 含 `from_node=<node id>`、`op_overrides`；成功回调**不**触发路由跳转、触发 family graph refetch；`rerunFromNode` action 不再 disabled。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：`OperationSection` 用 `controlFactory` 渲染可编辑控件 + 提交按钮；`api.ts` `rerunFromNode(projectRoot, runId, {from_node, op_overrides, rerun_reason})` POST `/runs/{id}/rerun`；`actionRegistry.rerunFromNode` 去 disabled、invoke 打开编辑面/触发提交。
- [ ] **Step 4：跑确认通过 + tsc** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2C.3): editable OperationSection + /rerun client"`

> **Progress note** — Loop: 2C.3 / Changed: OperationSection, api.ts, actionRegistry / Verified: initial value + from_node payload + no-jump refetch / Known risk: none / Next: 2C.4

---

### Loop 2C.4：Forest Canvas

```
Loop 2C.4: 共享前缀去重、分叉、head 标注（在现有 GraphCanvas）
Input:  adapter 并集 DAG
Change: GraphCanvas 消费 head-set 并集；active head 切换；trace 路径
Verify: C 只画一次；M1/M2 分叉；active head 可切换；trace 显示当前节点→source 路径
Exit:   vitest + 手动 smoke
Fallback: 渲染回退单 run 图
```

**Files:** Modify `frontend/src/lineage/graph/GraphCanvas.*` · Test `frontend/src/lineage/graph/GraphCanvas.headset.test.tsx`

- [ ] **Step 1：写失败测试**：喂并集 ViewModel（共享 C + M1/M2 分叉 + 两 head）→ 渲染中 C 节点只一个 DOM；M1/M2 各一；切 active head 改高亮集合；选中 M2 → trace 返回 `[C..., M2]` 路径。**不引入 layout 重构**（复用现 GraphCanvas 布局，G3）。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：GraphCanvas 接受 head-set ViewModel，按 node_hash 渲染唯一节点、分叉边、按 active head 着色；`tracePath(nodeHash)` 沿 parent hash 上溯。
- [ ] **Step 4：跑确认通过 + tsc + 手动 smoke**（`preview_*` 起前端，编辑 model→看分支长出）。
- [ ] **Step 5：Commit** — `git commit -m "feat(2C.4): forest canvas on existing GraphCanvas (dedup/branch/active-head/trace)"`

> **Progress note** — Loop: 2C.4 / Changed: GraphCanvas / Verified: single C, M1/M2 branch, active head, trace / Known risk: 视觉精修另算（G3）/ Next: 2C.5

---

### Loop 2C.5：Rollback

```
Loop 2C.5: 激活祖先 head，不修改历史 run
Input:  active head 机制（2C.4）
Change: rollback = 切 active head（视图状态/选择），非 mutation
Verify: active head 切换；URL/state 更新；graph 数据不变（无写后端）
Exit:   rollback 是视图状态，不是 mutation
Fallback: 移除 rollback 入口
```

**Files:** Modify `frontend/src/lineage/graph/GraphCanvas.*` / workbench state · Test `frontend/src/lineage/graph/rollback.test.tsx`

- [ ] **Step 1：写失败测试**：切 active head 到祖先 → 视图 active 集合变、URL/state 更新；断言**无** POST/mutation 调用、family graph 数据不变（不可变 run 保持）。
- [ ] **Step 2：跑确认失败** → FAIL.
- [ ] **Step 3：实现**：rollback = 纯前端 active-head 选择（可选写 URL query），不调后端写。
- [ ] **Step 4：跑确认通过 + tsc** → PASS.
- [ ] **Step 5：Commit** — `git commit -m "feat(2C.5): rollback as non-mutating active-head selection"`

> **Progress note** — Loop: 2C.5 / Changed: GraphCanvas/state / Verified: active head switch, no mutation, immutable runs intact / Known risk: none / Next: QA loops。**至此 2C 验收（含 G3）完成。**

---

## 审查 Loops（每 2A/2B/2C 收尾各跑一轮，subagent 只读）

### QA Loop（Test & QA）
- [ ] 强制全算 vs 增量产物逐字节对照（全 cacheable stage）。
- [ ] legacy run 仍能打开（旧 graph 形状）。
- [ ] child run artifacts 完整（G2 断言：`processed/*.parquet`、`model_results/*.json`、`reports/report.html`）。
- [ ] golden 三件套 0-drift。
- [ ] 产出可验证命令清单 + `incremental_trace.json` 抽样。

### Reviewer Loop（对抗审查，重点查）
- [ ] hash 是否混入 run_id/path/time（grep op_spec 提取 + node_hash 调用）。
- [ ] `payload_ref` 是否仍 run-relative（未被 CAS 替换）。
- [ ] `RecordingStage` 是否被错误缓存（必须不在 cacheable 列表）。
- [ ] FE 是否严格 hash 去重（无重复共享前缀）。
- [ ] 是否偷偷实现了本版不该做的方法库功能（时序/margins/任意 DAG/per-stage 编辑）。
- [ ] feature flags 默认 OFF，关闭即等价 v1.6.0 行为。

---

## Full Gate（收官）
- [ ] `WORKBENCH_INCREMENTAL_CACHE=0`（默认）跑 `./scripts/gate.sh` → 等价 v1.6.0，PASS。
- [ ] `WORKBENCH_INCREMENTAL_CACHE=1` 跑全门禁 + 增量正确性专项 → PASS。
- [ ] 三级审查（Implementer→Test&QA→Reviewer）逐 loop 已过。
- [ ] 发布动作（merge/tag/push main）**需用户单独授权**；release note 标注“架构型 patch”。

---

## Self-Review（plan 对 spec 覆盖核对）

- **spec §3.1 CAS+双轨 payload_ref** → 2A.2 + 2A.5/2A.7（dual-write、payload_ref 保留）✓
- **spec §3.2 cacheable boundary + RecordingStage 特判** → 2A.4（排除）+ 2A.7（桥）✓
- **spec §3.3 head-set + family serve 扫描 + flag** → 2B.1/2B.2 ✓
- **spec §3.4 from_node 替换语义** → 2A.6（引擎边界）+ 2B.3（HTTP/元数据）✓
- **spec §6 2A/2B/2C 分段验收** → 三段 loop 各自 Exit + 审查 ✓
- **spec §8 control_factory 5 硬约束** → 2C.2（无 switch、visible_when 保留、全 kind 可接）✓
- **spec §11 S1–S13 留口** → editable_schema 保留 `visible_when`(S4)、op_spec 承载 seed(S8)、节点字段加法可扩展(S1/S2)；其余为后续切片，不实现 ✓
- **spec §13 门禁** → 全局约束 + Full Gate（flag-off 等价 + 增量逐字节 + G2 目录断言）✓
- **R1–R9 / G1–G3** → 分布在 2A.1(seed/R1)、2A.5(R9 dual-write/G2)、2A.6(R7 byte-identical)、2A.7(R5 legacy 加法)、2B.2(R5/D flag)、2C.4(G3) ✓

无占位、类型一致（`node_hash`/`op_spec_for_stage`/`write_node_result`/`scan_family`/`build_headset`/`adaptHeadSet`/`rerunFromNode` 全程同名）。
