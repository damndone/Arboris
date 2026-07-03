# v1.6.8 Graph-native Genesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新用户从 Launcher → 空画布 → 抽屉创世向导 → 第一个 run 出结果,全程不经过旧 Submit 表单;数据模型倒转(节点先于 run 存在)。

**Architecture:** 创世 = 一份含 source/table/model 三节点的无父 draft 文档(泛化 v1.6.7 `pipeline_draft.v1`),execute 收敛进 `_submit_run(rerun_reason="initial")`;新增项目级 forest 端点解除画布的 runId 依赖;前端路由倒转(`/`=Launcher,`/p/:slug/graph`=项目的家,slug=base64url)。

**Tech Stack:** FastAPI + 既有 lineage 模块(upload_store/pipeline_drafts/headset);React + react-router + SheetJS(全部现有依赖,零新增)。

**Spec:** `docs/superpowers/specs/2026-07-03-v168-graph-native-genesis-design.md`(含 §10 自审 F1–F10)

**执行环境(每个 subagent 提示词必须包含):**
- 工作目录 = worktree `.worktrees/workbench-v1.6.8`(绝不在主目录跑)
- BE 测试:`LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/<file> -x -q`(仓库根 `tests/`,非 backend/ 下)
- FE 测试:`cd frontend && npx vitest run <file>`;类型:`cd frontend && npx tsc -p tsconfig.json --noEmit`
- **禁止 `git push`**(v1.5.7.1 事故教训)
- subagent model 用 **opus**

---

## Task 0: Worktree 依赖就位(一次性)

**Files:** 无代码改动。

- [ ] **Step 1: 链接共享依赖**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.6.8
bash /Users/jiayuanren/项目规划/scripts/link-shared-deps.sh 2>/dev/null \
  || { ln -sfn /Users/jiayuanren/项目规划/frontend/node_modules frontend/node_modules; \
       ln -sfn /Users/jiayuanren/项目规划/.venv .venv; }
```

- [ ] **Step 2: 冒烟验证两侧测试可跑**

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_api.py -x -q
cd frontend && npx vitest run src/workbench/WorkbenchRouteContainer.test.tsx
```
Expected: 两者 PASS(基线绿)。失败则先修环境,不进 Task 1。

---

## Task 1: BE — `POST /uploads` 独立上传端点

**Files:**
- Modify: `backend/workbench/api.py`(新端点,放在 `create_project_endpoint` 之后)
- Test: `tests/test_uploads_api.py`(新)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_uploads_api.py
from pathlib import Path
from fastapi.testclient import TestClient
from workbench.api import app
from workbench.lineage.upload_store import resolve_upload

client = TestClient(app)

def _mkproject(tmp_path: Path) -> str:
    r = client.post("/projects", json={"parent": str(tmp_path), "name": "p1"})
    assert r.status_code == 200
    return r.json()["project_root"]

def test_upload_roundtrip(tmp_path):
    root = _mkproject(tmp_path)
    csv = b"y,x\n1,2\n3,4\n"
    r = client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": ("data.csv", csv, "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "data.csv"
    assert resolve_upload(Path(root), body["sha256"]).read_bytes() == csv

def test_upload_rejects_oversize(tmp_path, monkeypatch):
    root = _mkproject(tmp_path)
    # 把上限压到 1 字节触发 413(复用 config.max_single_file_gb 检查路径)
    import workbench.api as api_mod
    monkeypatch.setattr(api_mod, "BYTES_PER_GB", 1)
    r = client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": ("big.csv", b"yy,xx\n1,2\n", "text/csv")},
    )
    assert r.status_code == 413
```

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_uploads_api.py -x -q`
Expected: FAIL(404,端点不存在)

- [ ] **Step 3: 实现端点(镜像 `run_endpoint` 的读取/限额路径)**

```python
# backend/workbench/api.py — 放在 create_project_endpoint 之后
@app.post("/uploads")
async def upload_dataset_endpoint(
    project_root: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    """v1.6.8 genesis: standalone content-addressable upload.

    Files persist server-side from wizard step 1 so genesis draft chains
    fully rehydrate after reload (same store POST /runs uses internally).
    """
    root = Path(project_root)
    config = load_config(root / "config.yml")  # PROJECT_NOT_FOUND propagates as today
    max_upload_bytes = int(config.max_single_file_gb * BYTES_PER_GB)
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
    finally:
        await file.close()
    filename = Path(file.filename or "upload.csv").name
    sha = store_upload_bytes(root, data, filename=filename)
    return {"sha256": sha, "filename": filename}
```

注意:`store_upload_bytes` 已在文件头部 import(v1.6.0);`_read_upload_bytes` 超限抛 413(既有行为,读 `_read_upload_bytes` 确认异常类型后对齐断言)。

- [ ] **Step 4: 跑测试确认通过**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_uploads_api.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_uploads_api.py backend/workbench/api.py
git commit -m "feat(api): standalone POST /uploads (content-addressable, genesis step 1)"
```

---

## Task 2: BE — 创世 draft 文档:`POST /pipeline-drafts/genesis`

**Files:**
- Modify: `backend/workbench/api.py`(新端点 + `PipelineDraftGenesisRequest` model)
- Modify: `backend/workbench/lineage/pipeline_drafts.py`(`_validate_graph_shape` 认识创世形状)
- Test: `tests/test_pipeline_drafts_genesis.py`(新)

**创世 draft 文档形状(泛化 `pipeline_draft.v1`,与 from-node 同 store 同生命周期):**

```json
{
  "draft_id": "…", "schema_version": "pipeline_draft.v1",
  "status": "draft",
  "created_from": {"source_type": "genesis", "source_input_fingerprint": "<sha256>"},
  "graph": {
    "nodes": [
      {"node_id": "source_1", "node_type": "input.upload",
       "upload": {"sha256": "…", "filename": "data.xlsx"},
       "sheet_names": ["Sheet1", "wages"], "status": "bound"},
      {"node_id": "table_1", "node_type": "table",
       "params": {"sheet_name": null, "transpose": false},
       "columns": [], "status": "pending"},
      {"node_id": "model_1", "node_type": "model", "model_family": "regression",
       "model_type": null, "params": {}, "status": "pending"}
    ],
    "edges": [{"from": "source_1", "to": "table_1"}, {"from": "table_1", "to": "model_1"}]
  },
  "default_execution_mode": "genesis"
}
```

设计要点(vs spec §4.3 的 refinement,写进代码注释):创世 model 节点 **params-only,无 editable_schema**——前端模型步直接复用 capabilities 驱动的 RunForm 控件(它们今天就不依赖 editable_schema),BE 只做结构校验;列级校验归 execute 的 `_column_checks`(spec F3)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline_drafts_genesis.py
from pathlib import Path
from fastapi.testclient import TestClient
from workbench.api import app

client = TestClient(app)

def _mkproject(tmp_path):
    return client.post("/projects", json={"parent": str(tmp_path), "name": "p1"}).json()["project_root"]

def _upload(root, name="d.csv", data=b"y,x\n1,2\n3,4\n"):
    return client.post("/uploads", data={"project_root": root},
                       files={"file": (name, data, "text/csv")}).json()

def test_genesis_draft_created_and_persisted(tmp_path):
    root = _mkproject(tmp_path)
    up = _upload(root)
    r = client.post(f"/pipeline-drafts/genesis?project_root={root}", json={
        "upload_sha256": up["sha256"], "filename": up["filename"],
        "sheet_names": [], "columns": ["y", "x"],
    })
    assert r.status_code == 200
    draft = r.json()["draft"]
    assert draft["created_from"]["source_type"] == "genesis"
    types = [n["node_type"] for n in draft["graph"]["nodes"]]
    assert types == ["input.upload", "table", "model"]
    # 持久化:list 能看到(项目级 data/pipeline_drafts/,v1.6.7 同一 store)
    listed = client.get(f"/pipeline-drafts?project_root={root}").json()["drafts"]
    assert any(d["draft_id"] == draft["draft_id"] for d in listed)

def test_genesis_rejects_unknown_upload(tmp_path):
    root = _mkproject(tmp_path)
    r = client.post(f"/pipeline-drafts/genesis?project_root={root}", json={
        "upload_sha256": "0" * 64, "filename": "x.csv", "sheet_names": [], "columns": [],
    })
    assert r.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q`
Expected: FAIL(404)

- [ ] **Step 3: 实现端点**

```python
# backend/workbench/api.py — 放在 create_pipeline_draft_from_node 之后
class PipelineDraftGenesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upload_sha256: str
    filename: str
    sheet_names: list[str] = []
    columns: list[str] = []  # 客户端 SheetJS 解析的列名(选表后回填 table_1.columns)


@app.post("/pipeline-drafts/genesis")
def create_pipeline_draft_genesis(
    project_root: str,
    body: PipelineDraftGenesisRequest,
) -> dict[str, Any]:
    """v1.6.8: parentless genesis draft chain (source -> table -> model).

    Same store + lifecycle as from-node drafts; created_from.source_type
    distinguishes the branch everywhere downstream (validate / execute).
    """
    root = Path(project_root)
    try:
        verify_upload(root, body.upload_sha256)
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=f"UPLOAD_NOT_FOUND: {exc}") from exc

    now = utc_now()
    draft = {
        "draft_id": new_draft_id(),
        "schema_version": "pipeline_draft.v1",
        "created_at": now, "updated_at": now, "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": body.upload_sha256,
        },
        "graph": {
            "nodes": [
                {"node_id": "source_1", "node_type": "input.upload",
                 "upload": {"sha256": body.upload_sha256, "filename": body.filename},
                 "sheet_names": body.sheet_names, "status": "bound"},
                {"node_id": "table_1", "node_type": "table",
                 "params": {"sheet_name": None, "transpose": False},
                 "columns": body.columns, "status": "pending"},
                # Genesis model node is params-only (no editable_schema): the
                # wizard reuses capabilities-driven RunForm controls; validate
                # stays structural, column checks belong to execute (spec F3/F4).
                {"node_id": "model_1", "node_type": "model",
                 "model_family": "regression", "model_type": None,
                 "params": {}, "status": "pending"},
            ],
            "edges": [{"from": "source_1", "to": "table_1"},
                      {"from": "table_1", "to": "model_1"}],
        },
        "default_execution_mode": "genesis",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}
```

- [ ] **Step 4: 让 `_validate_graph_shape` 认识创世形状**

`backend/workbench/lineage/pipeline_drafts.py` 的 `_validate_graph_shape`(:356)当前假设 input.dataset+model 两节点。改法:函数开头按 `draft.get("created_from", {}).get("source_type")` 分派——`"genesis"` 走新 `_validate_genesis_shape(draft)`:

```python
_GENESIS_CHAIN = ["input.upload", "table", "model"]

def _validate_genesis_shape(draft: dict[str, Any]) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    nodes = draft.get("graph", {}).get("nodes", [])
    types = [n.get("node_type") for n in nodes]
    if types != _GENESIS_CHAIN:
        problems.append({"code": "GENESIS_CHAIN_SHAPE",
                         "message": f"genesis chain must be {_GENESIS_CHAIN}, got {types}"})
        return problems
    edges = draft.get("graph", {}).get("edges", [])
    want = [{"from": "source_1", "to": "table_1"}, {"from": "table_1", "to": "model_1"}]
    if edges != want:
        problems.append({"code": "GENESIS_CHAIN_EDGES", "message": "edges must chain source->table->model"})
    return problems
```

- [ ] **Step 5: 跑测试确认通过,回归既有 draft 测试**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py tests/test_pipeline_drafts_api.py -x -q`
Expected: 全 PASS(from-node 路径零回归)

- [ ] **Step 6: Commit**

```bash
git add tests/test_pipeline_drafts_genesis.py backend/workbench/api.py backend/workbench/lineage/pipeline_drafts.py
git commit -m "feat(drafts): parentless genesis draft chain (source/table/model) + shape validation"
```

---

## Task 3: BE — 向导步进:`PATCH /pipeline-drafts/{id}/nodes/{node_id}`

**Files:**
- Modify: `backend/workbench/api.py`(新端点)
- Modify: `backend/workbench/lineage/pipeline_drafts.py`(store 新方法 `update_node_params`,镜像既有 `update_params` 的锁/原子写/updated_at/hash 语义,:259 起可对照)
- Test: `tests/test_pipeline_drafts_genesis.py`(追加)

- [ ] **Step 1: 写失败测试(追加)**

```python
def _genesis(root, **kw):
    up = _upload(root, **({"name": kw.pop("name")} if "name" in kw else {}))
    return client.post(f"/pipeline-drafts/genesis?project_root={root}", json={
        "upload_sha256": up["sha256"], "filename": up["filename"],
        "sheet_names": [], "columns": ["y", "x"],
    }).json()

def test_wizard_step_updates_table_then_model(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    r = client.patch(f"/pipeline-drafts/{did}/nodes/table_1?project_root={root}",
                     json={"params": {"sheet_name": "Sheet1", "transpose": False},
                           "columns": ["y", "x"]})
    assert r.status_code == 200
    assert r.json()["draft_hash"] != d["draft_hash"]  # hash 前进,幂等钥匙随内容走
    r2 = client.patch(f"/pipeline-drafts/{did}/nodes/model_1?project_root={root}",
                      json={"params": {"model_type": "ols", "y": "y", "x": ["x"]}})
    assert r2.status_code == 200
    model = next(n for n in r2.json()["draft"]["graph"]["nodes"] if n["node_id"] == "model_1")
    assert model["params"]["y"] == "y" and model["status"] == "configured"

def test_node_patch_rejects_nongenesis_source_node(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    r = client.patch(f"/pipeline-drafts/{d['draft']['draft_id']}/nodes/source_1?project_root={root}",
                     json={"params": {"anything": 1}})
    assert r.status_code == 409  # source 节点 bound 后不可改(换文件 = discard 重来)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q`
Expected: 新增用例 FAIL(405/404)

- [ ] **Step 3: 实现 store 方法 + 端点**

store(对照 `update_params` :259 的锁与原子写照抄结构):

```python
# pipeline_drafts.py — PipelineDraftStore 内
_PATCHABLE = {"table": "pending", "model": "pending"}  # node_type -> 允许起始态

def update_node_params(self, draft_id: str, node_id: str,
                       params: dict[str, Any],
                       columns: list[str] | None = None) -> StoredDraft:
    validate_draft_id(draft_id)
    with self._lock_for(draft_id):
        stored = self.get(draft_id)
        draft = stored.draft
        if draft.get("created_from", {}).get("source_type") != "genesis":
            raise DraftConflict("NODE_PATCH_GENESIS_ONLY")
        node = next((n for n in draft["graph"]["nodes"] if n["node_id"] == node_id), None)
        if node is None:
            raise DraftNotFound(f"node {node_id}")
        if node.get("node_type") not in self._PATCHABLE:
            raise DraftConflict("NODE_NOT_PATCHABLE")
        node["params"] = {**node.get("params", {}), **params}
        if columns is not None and node["node_type"] == "table":
            node["columns"] = columns
        node["status"] = "configured"
        draft["updated_at"] = utc_now()
        draft["status"] = "draft"  # 任何改动都退回 draft 态,须重新 validate
        self._write_atomic(self._path(draft_id), draft)
        return self.get(draft_id)
```

(`DraftConflict`/`DraftNotFound`:用本文件既有的异常类型——先 `grep -n "class Draft" pipeline_drafts.py` 对齐真实名字,`_draft_http_error` 已做映射。)

端点:

```python
# api.py
class DraftNodePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    params: dict[str, Any]
    columns: list[str] | None = None


@app.patch("/pipeline-drafts/{draft_id}/nodes/{node_id}")
def patch_pipeline_draft_node(
    draft_id: str, node_id: str, project_root: str, body: DraftNodePatchRequest,
) -> dict[str, Any]:
    store = _pipeline_draft_store(project_root)
    try:
        stored = store.update_node_params(draft_id, node_id, body.params, columns=body.columns)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/api.py backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_genesis.py
git commit -m "feat(drafts): PATCH node params for genesis wizard steps (table/model, source immutable)"
```

---

## Task 4: BE — 创世链 validate(结构 + 引用,列校验归 execute)

**Files:**
- Modify: `backend/workbench/lineage/pipeline_drafts.py`(`validate_draft_for_execution` :580 分派创世分支)
- Test: `tests/test_pipeline_drafts_genesis.py`(追加)

- [ ] **Step 1: 写失败测试(追加)**

```python
def _configure_chain(root, did, model_params=None):
    client.patch(f"/pipeline-drafts/{did}/nodes/table_1?project_root={root}",
                 json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]})
    client.patch(f"/pipeline-drafts/{did}/nodes/model_1?project_root={root}",
                 json={"params": model_params or {"model_type": "ols", "y": "y", "x": ["x"]}})

def test_validate_genesis_ok(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    r = client.post(f"/pipeline-drafts/{did}/validate?project_root={root}",
                    json={"execution_mode": "genesis"})
    assert r.status_code == 200
    assert r.json()["executable"] is True

def test_validate_genesis_missing_xy_blocks(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    _configure_chain(root, did, model_params={"model_type": "ols"})  # 无 y/x
    r = client.post(f"/pipeline-drafts/{did}/validate?project_root={root}",
                    json={"execution_mode": "genesis"})
    body = r.json()
    assert body["executable"] is False
    assert any(p["code"] == "GENESIS_MODEL_INCOMPLETE" for p in body["problems"])
```

(validate 端点的请求/响应外形以 `tests/test_pipeline_drafts_api.py` 既有用例为准——先读它对齐字段名,`execution_mode` 传递方式照抄 from-node 用例。)

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q`
Expected: FAIL(现 validate 走 created_from=run 的引用校验,创世必炸)

- [ ] **Step 3: 实现创世 validate 分支**

`validate_draft_for_execution` 开头分派:

```python
def validate_draft_for_execution(draft, *, execution_mode):
    if draft.get("created_from", {}).get("source_type") == "genesis":
        return _validate_genesis_for_execution(draft, execution_mode=execution_mode)
    ...  # 既有 from-node 路径原样


def _validate_genesis_for_execution(draft, *, execution_mode):
    problems = _validate_genesis_shape(draft)
    if execution_mode != "genesis":
        problems.append({"code": "GENESIS_MODE_REQUIRED",
                         "message": "genesis chains execute with execution_mode='genesis'"})
    nodes = {n["node_id"]: n for n in draft["graph"]["nodes"]}
    src, tbl, mdl = nodes.get("source_1", {}), nodes.get("table_1", {}), nodes.get("model_1", {})
    if not (src.get("upload") or {}).get("sha256"):
        problems.append({"code": "GENESIS_SOURCE_UNBOUND", "message": "source_1 missing upload"})
    # 多 sheet 文件必须显式选 sheet;单 sheet/CSV 允许空串走后端默认
    if len(src.get("sheet_names") or []) > 1 and not (tbl.get("params") or {}).get("sheet_name"):
        problems.append({"code": "GENESIS_SHEET_REQUIRED", "message": "multi-sheet upload needs sheet_name"})
    mp = mdl.get("params") or {}
    if not (mp.get("y") and mp.get("x")):
        problems.append({"code": "GENESIS_MODEL_INCOMPLETE", "message": "model_1 needs y and x"})
    executable = not problems
    # 结构校验通过即 executable;列级校验(y/x 是否真在表里)交给 execute 的
    # _submit_run -> orchestrator _column_checks(spec F3,不重复造轮子)。
    return {
        "executable": executable,
        "problems": problems,
        "validated_execution_mode": "genesis" if executable else None,
        "resolved_execution": {"genesis": True},
    }
```

返回 dict 的完整字段集合以既有 from-node 返回体为准(先读 :580 起的实现,保持同形——execute :1297 会读 `executable`/`validated_execution_mode`/`resolved_execution` 三键)。

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py tests/test_pipeline_drafts_api.py -x -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_genesis.py
git commit -m "feat(drafts): genesis validate branch (structural + refs; column checks stay in execute)"
```

---

## Task 5: BE — execute 创世分支(收敛 `_submit_run`,rerun_reason="initial")

**Files:**
- Modify: `backend/workbench/api.py`(`execute_pipeline_draft` :1252 分派)
- Test: `tests/test_pipeline_drafts_genesis.py`(追加,端到端产 run)

- [ ] **Step 1: 写失败测试(追加)**

```python
def test_execute_genesis_produces_first_run(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = client.post(f"/pipeline-drafts/{did}/validate?project_root={root}",
                    json={"execution_mode": "genesis"}).json()
    r = client.post(f"/pipeline-drafts/{did}/execute?project_root={root}", json={
        "execution_mode": "genesis", "validated_draft_hash": v["draft_hash"],
    })
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    # run 真实存在且 rerun_reason=initial(创世不是 rerun)
    detail = client.get(f"/runs/{run_id}?project_root={root}").json()
    assert detail["run_id"] == run_id
    import json as _json
    inputs = _json.loads((Path(root) / "runs" / run_id / "run_inputs.json").read_text())
    assert inputs.get("rerun_of") in (None, "")
    assert inputs["form"]["y"] == "y" and inputs["form"]["x"] == "x"

def test_execute_genesis_idempotent(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = client.post(f"/pipeline-drafts/{did}/validate?project_root={root}",
                    json={"execution_mode": "genesis"}).json()
    body = {"execution_mode": "genesis", "validated_draft_hash": v["draft_hash"],
            "idempotency_key": "k1"}
    r1 = client.post(f"/pipeline-drafts/{did}/execute?project_root={root}", json=body).json()
    r2 = client.post(f"/pipeline-drafts/{did}/execute?project_root={root}", json=body).json()
    assert r2["deduped"] is True and r2["run_id"] == r1["run_id"]
```

(validate 响应里的 `draft_hash` 字段名同样以既有用例为准;若 validate 不回 hash,则用 PATCH 响应里的 `draft_hash`。`run_inputs.json` 的 `rerun_of` 键名先 `grep -n "rerun_of" backend/workbench/lineage/run_inputs.py` 对齐。)

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q`
Expected: FAIL(execution_mode="genesis" 撞现有 `new_run` 409 或 created_from["source_run_id"] KeyError)

- [ ] **Step 3: 实现创世分支**

`execute_pipeline_draft` 顶部现有 `if body.execution_mode == "new_run": raise 409` **保留**;紧随其后分派:

```python
    store = _pipeline_draft_store(project_root)
    first = store.get(draft_id)          # (提到 mode 分派前)
    is_genesis = first.draft.get("created_from", {}).get("source_type") == "genesis"
    if is_genesis and body.execution_mode != "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_MODE_REQUIRED")
    if not is_genesis and body.execution_mode == "genesis":
        raise HTTPException(status_code=409, detail="GENESIS_ONLY_FOR_GENESIS_DRAFTS")
```

创世执行体(hash 检查/dedupe/execution_lock/slot 结构与既有分支**完全同构**,可抽 `_run_draft_execution` 共享或平行实现,倾向平行实现避免动稳定路径;差异仅在"取 upload + 合成 form + _submit_run 参数"):

```python
        # --- genesis branch: synthesize the full form (no parent run to merge) ---
        draft = current.draft
        nodes = {n["node_id"]: n for n in draft["graph"]["nodes"]}
        sha = nodes["source_1"]["upload"]["sha256"]
        filename = nodes["source_1"]["upload"].get("filename") or "upload.csv"
        try:
            upload_bytes = verify_upload(root, sha).read_bytes()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"GENESIS_UPLOAD_UNUSABLE: {exc}") from exc

        tp = nodes["table_1"].get("params") or {}
        mp = dict(nodes["model_1"].get("params") or {})
        x_val = mp.pop("x", "")
        focal = mp.pop("focal_x", "")
        merged_form = {
            "mode": "auto",
            "model_type": str(mp.pop("model_type", "") or "auto"),
            "y": str(mp.pop("y", "")),
            "x": ",".join(x_val) if isinstance(x_val, list) else str(x_val),
            "sheet_name": str(tp.get("sheet_name") or ""),
            "transpose": "true" if tp.get("transpose") else "false",
            "focal_x": ",".join(focal) if isinstance(focal, list) else str(focal),
            # 其余模型参数(imputation/entity_col/did_* 等)与 POST /runs 的 Form
            # 字段一一同名——wizard 存的就是 form 字段名,直接透传:
            **{k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
               for k, v in mp.items()},
        }
        executed_hash = compute_executable_draft_hash(draft)
        # _record_snapshot_before_dispatch 同既有分支(executed_pipeline_draft.json + dedupe)
        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                root, form=merged_form, upload_bytes=upload_bytes,
                upload_filename=filename,
                started_at=datetime.now(timezone.utc).isoformat(),
                rerun_reason="initial",          # 创世不是 rerun:无 rerun_of/from_node/rerun_from
                before_dispatch=_record_snapshot_before_dispatch,
            )
        except Exception:
            events.release_slot(None)
            raise
        return {
            "ok": True, "run_id": result["run_id"], "draft_id": draft_id,
            "executed_draft_hash": executed_hash, "execution_mode": "genesis",
            "produced_lineage": {"genesis": True},
            "focus": {"status": "pending_index", "run_id": result["run_id"],
                      "poll": {"genesis": True}},
        }
```

(`_submit_run` 的关键字默认值先读 :186 起签名确认——`rerun_of`/`from_node`/`op_overrides`/`rerun_from` 均需有可省略默认;若无默认则显式传 None/{}/None。)

- [ ] **Step 4: 跑测试确认通过 + golden 回归**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_pipeline_drafts_genesis.py -x -q && LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/golden -q`
Expected: 全 PASS,golden 23 0-drift(创世走 `_submit_run` 同路的硬证据)

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/api.py tests/test_pipeline_drafts_genesis.py
git commit -m "feat(drafts): execute genesis branch — synthesize form, _submit_run(initial), dedupe+slot preserved"
```

---

## Task 6: BE — 项目级 forest 端点 `GET /graph`(F1 后端半)

**Files:**
- Create: `backend/workbench/lineage/project_forest.py`
- Modify: `backend/workbench/api.py`(新端点)
- Test: `tests/test_project_forest_api.py`(新)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_project_forest_api.py
from fastapi.testclient import TestClient
from workbench.api import app

client = TestClient(app)

def _mkproject(tmp_path, name="p1"):
    return client.post("/projects", json={"parent": str(tmp_path), "name": name}).json()["project_root"]

def test_zero_run_project_returns_empty_forest(tmp_path):
    root = _mkproject(tmp_path)
    r = client.get(f"/graph?project_root={root}")
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == [] and body["edges"] == [] and body["heads"] == []

def test_project_forest_unions_families(tmp_path):
    root = _mkproject(tmp_path)
    csv = b"y,x\n1,2\n3,4\n5,6\n"
    r = client.post("/runs", data={"project_root": root, "y": "y", "x": "x"},
                    files={"file": ("d.csv", csv, "text/csv")})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    body = client.get(f"/graph?project_root={root}").json()
    assert body["nodes"], "run nodes must appear in project forest"
    # 与 run-keyed headset 同形:同 run 的 headset 是项目森林的子集
    per_run = client.get(f"/runs/{run_id}/graph?project_root={root}&view=headset").json()
    project_keys = {n["node_key"] for n in body["nodes"]}
    assert {n["node_key"] for n in per_run["nodes"]} <= project_keys

def test_project_forest_unicode_root(tmp_path):
    root = _mkproject(tmp_path, name="中文项目")
    r = client.get(f"/graph?project_root={root}")
    assert r.status_code == 200
```

(`node_key` 字段名以 `build_headset` 实际输出为准——写实现前先 `python -c` 打一个 headset 输出对齐;若是 `key`/`id` 就改断言。)

- [ ] **Step 2: 跑测试确认失败**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_project_forest_api.py -x -q`
Expected: FAIL(404)

- [ ] **Step 3: 实现 project_forest 构建器 + 端点**

```python
# backend/workbench/lineage/project_forest.py
"""v1.6.8 F1 — project-level forest: union of all family head-sets.

The canvas home is /p/:slug/graph; a zero-run project must render an empty
forest (genesis starts there). Reuses scan_family + build_headset per family;
runs already unioned by an earlier family are skipped.
"""
from pathlib import Path
from typing import Any, Callable, Optional

from .family import scan_family
from .headset import build_headset


def build_project_forest(
    runs_dir: Path, *, annotate: Optional[Callable[..., None]] = None,
) -> dict[str, Any]:
    empty = {"nodes": [], "edges": [], "heads": [], "families": []}
    if not runs_dir.is_dir():
        return empty
    run_ids = sorted(p.name for p in runs_dir.iterdir()
                     if p.is_dir() and (p / "manifest.json").is_file())
    seen: set[str] = set()
    nodes: dict[str, dict] = {}     # node_key -> node(去重:跨 family key 不撞,同 family 由 build_headset 保证)
    edges: list[dict] = []
    edge_seen: set[tuple[str, str]] = set()
    heads: list[dict] = []
    families: list[dict] = []
    for run_id in run_ids:
        if run_id in seen:
            continue
        family = scan_family(runs_dir, run_id)
        members = {family.self_id, *family.ancestors, *family.descendants, *family.siblings}
        seen |= members
        body = build_headset(runs_dir, family, annotate=annotate)
        for node in body.get("nodes", []):
            nodes.setdefault(node["node_key"], node)
        for edge in body.get("edges", []):
            k = (edge["from"], edge["to"])
            if k not in edge_seen:
                edge_seen.add(k)
                edges.append(edge)
        heads.extend(body.get("heads", []))
        families.append({"family_root": family.self_id, "members": sorted(members)})
    return {"nodes": list(nodes.values()), "edges": edges, "heads": heads, "families": families}
```

(`build_headset` 输出的 nodes/edges 容器类型与键名以真实输出为准——先打样;`family` 属性名已在 headset.py:76 验证过。legacy run(无 node_index)被 build_headset 内部跳过,保持既有语义。)

```python
# api.py
from .lineage.project_forest import build_project_forest

@app.get("/graph")
def get_project_graph(project_root: str) -> dict[str, Any]:
    """v1.6.8 F1 — project-keyed forest; empty forest for zero-run projects."""
    runs_root = _resolve_project_runs_dir(project_root)  # PROJECT_NOT_FOUND as today
    return build_project_forest(runs_root, annotate=_annotate_editable_node)
```

- [ ] **Step 4: 跑测试确认通过 + headset 回归**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/test_project_forest_api.py tests/test_graph_headset.py -x -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/project_forest.py backend/workbench/api.py tests/test_project_forest_api.py
git commit -m "feat(graph): project-level forest endpoint GET /graph (empty forest for zero-run projects)"
```

---

## Task 7: BE — discard 创世链回收无引用 upload(F6)

**Files:**
- Modify: `backend/workbench/api.py`(`delete_pipeline_draft` :1231 扩展)
- Modify: `backend/workbench/lineage/upload_store.py`(新 `delete_upload_if_unreferenced`)
- Test: `tests/test_pipeline_drafts_genesis.py`(追加)

- [ ] **Step 1: 写失败测试(追加)**

```python
def test_discard_genesis_reclaims_unreferenced_upload(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    sha = next(n for n in d["draft"]["graph"]["nodes"]
               if n["node_id"] == "source_1")["upload"]["sha256"]
    from workbench.lineage.upload_store import resolve_upload
    assert resolve_upload(Path(root), sha).is_file()
    client.delete(f"/pipeline-drafts/{did}?project_root={root}")
    assert not resolve_upload(Path(root), sha).exists()

def test_discard_keeps_upload_referenced_by_run(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root); did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = client.post(f"/pipeline-drafts/{did}/validate?project_root={root}",
                    json={"execution_mode": "genesis"}).json()
    client.post(f"/pipeline-drafts/{did}/execute?project_root={root}",
                json={"execution_mode": "genesis", "validated_draft_hash": v["draft_hash"]})
    sha = next(n for n in d["draft"]["graph"]["nodes"]
               if n["node_id"] == "source_1")["upload"]["sha256"]
    client.delete(f"/pipeline-drafts/{did}?project_root={root}")
    from workbench.lineage.upload_store import resolve_upload
    assert resolve_upload(Path(root), sha).is_file()  # run_inputs 引用着,不回收
```

- [ ] **Step 2: 跑测试确认失败** → Run 同上,Expected: 第一个用例 FAIL(blob 残留)

- [ ] **Step 3: 实现**

```python
# upload_store.py
def delete_upload_if_unreferenced(project_root: Path, sha: str) -> bool:
    """Delete blob unless any run_inputs.json or other draft references it."""
    runs_dir = project_root / "runs"
    if runs_dir.is_dir():
        for run_dir in runs_dir.iterdir():
            ri = run_dir / "run_inputs.json"
            if ri.is_file() and sha in ri.read_text(encoding="utf-8"):
                return False
    drafts_dir = project_root / "data" / "pipeline_drafts"
    if drafts_dir.is_dir():
        for p in drafts_dir.glob("*.json"):
            if sha in p.read_text(encoding="utf-8"):
                return False
    path = resolve_upload(project_root, sha)
    if path.exists():
        path.unlink()
        return True
    return False
```

`delete_pipeline_draft` 端点:删 draft **前**先取出 genesis 的 sha,删 draft **后**调 `delete_upload_if_unreferenced`(顺序保证 draft 自身不算引用)。字符串包含判引用是保守正确(sha256 十六进制无歧义碰撞面)。

- [ ] **Step 4: 跑测试确认通过** → Run 同上,Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/upload_store.py backend/workbench/api.py tests/test_pipeline_drafts_genesis.py
git commit -m "feat(uploads): reclaim unreferenced upload on genesis draft discard (F6)"
```

---

## Task 8: FE — api.ts 客户端 + slug 工具

**Files:**
- Modify: `frontend/src/api.ts`(新函数)
- Create: `frontend/src/workbench/projectSlug.ts` + `frontend/src/workbench/projectSlug.test.ts`
- Test: `frontend/src/api.test.ts`(追加)

- [ ] **Step 1: 写失败测试(slug 必须过中文往返,F5/F10)**

```typescript
// frontend/src/workbench/projectSlug.test.ts
import { describe, expect, it } from "vitest";
import { rootToSlug, slugToRoot } from "./projectSlug";

describe("projectSlug", () => {
  it.each([
    "/Users/me/work/demo",
    "/Users/jiayuanren/项目规划/示例项目",
    "/tmp/with space/and-dash_underscore",
  ])("roundtrips %s", (root) => {
    expect(slugToRoot(rootToSlug(root))).toBe(root);
  });
  it("produces URL-path-safe slugs (no / + = %)", () => {
    const slug = rootToSlug("/Users/jiayuanren/项目规划/p1");
    expect(slug).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/workbench/projectSlug.test.ts`
Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现 slug(base64url,Unicode 安全)+ api 函数**

```typescript
// frontend/src/workbench/projectSlug.ts
// v1.6.8 F5 — path segments must not contain %2F (vite/react-router normalize
// it inconsistently). base64url over UTF-8 bytes: only [A-Za-z0-9_-].
export function rootToSlug(projectRoot: string): string {
  const bytes = new TextEncoder().encode(projectRoot);
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function slugToRoot(slug: string): string {
  const b64 = slug.replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(pad);
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}
```

```typescript
// frontend/src/api.ts — 追加(URL 组装/错误处理照抄相邻函数模式,如 listPipelineDrafts)
export type UploadResult = { sha256: string; filename: string };

export async function uploadDataset(projectRoot: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.set("project_root", projectRoot);
  form.set("file", file);
  const response = await fetch(apiUrl("/uploads"), { method: "POST", body: form });
  return handleJson(response);  // ← 用本文件既有的响应处理 helper 真名
}

export async function createGenesisDraft(
  projectRoot: string,
  body: { upload_sha256: string; filename: string; sheet_names: string[]; columns: string[] },
): Promise<{ draft: PipelineDraft; draft_hash: string }> {
  const response = await fetch(
    draftUrl(projectRoot, "/pipeline-drafts/genesis"),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  return handleJson(response);
}

export async function patchDraftNode(
  projectRoot: string, draftId: string, nodeId: string,
  body: { params: Record<string, unknown>; columns?: string[] },
): Promise<{ draft: PipelineDraft; draft_hash: string }> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${draftId}/nodes/${nodeId}`),
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  return handleJson(response);
}

export async function fetchProjectForest(projectRoot: string): Promise<HeadSetGraph> {
  const url = `${apiUrl("/graph")}?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return handleJson(response);
}
```

(`handleJson`/`draftUrl`/`apiUrl`/`PipelineDraft`/`HeadSetGraph` 均为 api.ts 既有符号——实现前 grep 对齐真名与真实错误处理惯例(`ApiError` 抛法),照抄相邻函数,不发明新模式。api.test.ts 各加一条 fetch-mock 用例,照抄相邻函数的测试模式。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/workbench/projectSlug.test.ts src/api.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workbench/projectSlug.ts frontend/src/workbench/projectSlug.test.ts frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(fe): api clients for genesis (uploads/draft/patch/project-forest) + unicode-safe base64url slug"
```

---

## Task 9: FE — 路由倒转(App.tsx)

**Files:**
- Modify: `frontend/src/App.tsx`(:403 Routes 重排;SubmitRoute 移挂 `/submit`)
- Create: `frontend/src/launcher/LauncherRoute.tsx`(本任务先放占位骨架,Task 10 填肉——占位也必须可渲染可测)
- Test: `frontend/src/App.test.tsx`(追加)

- [ ] **Step 1: 写失败测试(追加到 App.test.tsx,照抄文件内既有 render/router 测试模式)**

```typescript
it("/ renders the launcher, not the submit form", async () => {
  renderApp("/");   // ← 用 App.test.tsx 既有 helper 真名
  expect(await screen.findByText(/新建项目|Open a project/i)).toBeInTheDocument();
  expect(screen.queryByLabelText("parent folder")).not.toBeInTheDocument();
});

it("/submit still mounts the legacy form (hidden route, ⌘K fallback)", async () => {
  renderApp("/submit");
  expect(await screen.findByLabelText("parent folder")).toBeInTheDocument();
});

it("/runs/:id redirects into the project workbench when project_root present", async () => {
  renderApp("/runs/run_abc?project_root=/tmp/p1");
  await waitFor(() =>
    expect(window.location.pathname).toMatch(/^\/p\/[A-Za-z0-9_-]+\/graph$/));
  expect(window.location.search).toContain("focus=run_abc");
});

it("/runs/:id without project_root falls back to launcher", async () => {
  renderApp("/runs/run_abc");
  await waitFor(() => expect(window.location.pathname).toBe("/"));
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: 新增用例 FAIL

- [ ] **Step 3: 实现路由重排**

```tsx
// App.tsx — Routes 替换(v1.6.8 路由倒转:图是家,表单是兜底)
import { LauncherRoute } from "./launcher/LauncherRoute";
import { rootToSlug, slugToRoot } from "./workbench/projectSlug";

function LegacyRunRedirect() {
  const { runId } = useParams();
  const [searchParams] = useSearchParams();
  const root = searchParams.get("project_root");
  if (!root) return <Navigate to="/" replace />;
  return (
    <Navigate
      replace
      to={`/p/${rootToSlug(root)}/graph?focus=${encodeURIComponent(runId ?? "")}`}
    />
  );
}

function LegacyRunsListRedirect() {
  const [searchParams] = useSearchParams();
  const root = searchParams.get("project_root");
  return <Navigate replace to={root ? `/p/${rootToSlug(root)}/graph` : "/"} />;
}

function ProjectGraphRoute() {
  const { slug } = useParams();
  let projectRoot = "";
  try { projectRoot = slugToRoot(slug ?? ""); } catch { /* fall through */ }
  if (!projectRoot) return <Navigate to="/" replace />;
  return <WorkbenchHome projectRoot={projectRoot} />;  // Task 11 实现;本任务先渲染既有 RunDetail 壳可过测
}

// Routes:
<Route element={<AppShell />}>
  <Route index element={<LauncherRoute />} />
  <Route path="submit" element={<SubmitRoute />} />          {/* F7 隐藏路由 */}
  <Route path="p/:slug/graph" element={<ProjectGraphRoute />} />
  <Route path="runs" element={<LegacyRunsListRedirect />} /> {/* F8 */}
  <Route path="runs/:runId" element={<LegacyRunRedirect />} />
  <Route path="pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
</Route>
```

`useParams`/`Navigate` 加进 react-router-dom import。AppShell 的 Submit/History 两个 tab 按钮:Submit tab 删除,History tab 改为「Workbench」导航到 `/p/:slug/graph`(有 projectRoot 时)。`LauncherRoute` 本任务给最小可渲染骨架(标题 + 「新建项目」按钮占位)。

- [ ] **Step 4: 跑测试确认通过 + 全 FE 回归**

Run: `cd frontend && npx vitest run src/App.test.tsx && npx vitest run`
Expected: 新用例 PASS;既有套件中断言旧路由的用例按新语义更新(改断言,不删覆盖)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/launcher/
git commit -m "feat(fe): route inversion — / launcher, /p/:slug/graph home, /runs redirects, /submit hidden (F5/F7/F8)"
```

---

## Task 10: FE — Launcher(最近项目 + 新建 modal)

**Files:**
- Modify: `frontend/src/launcher/LauncherRoute.tsx`(填肉)
- Create: `frontend/src/launcher/recents.ts` + `frontend/src/launcher/recents.test.ts`
- Test: `frontend/src/launcher/LauncherRoute.test.tsx`(新)

- [ ] **Step 1: 写失败测试**

```typescript
// recents.test.ts
import { describe, expect, it, beforeEach } from "vitest";
import { listRecents, touchRecent, removeRecent } from "./recents";

describe("recents", () => {
  beforeEach(() => localStorage.clear());
  it("touch puts most-recent first and dedupes", () => {
    touchRecent("/a"); touchRecent("/b"); touchRecent("/a");
    expect(listRecents().map((r) => r.root)).toEqual(["/a", "/b"]);
  });
  it("stores unicode roots verbatim", () => {
    touchRecent("/Users/me/项目规划/示例");
    expect(listRecents()[0].root).toBe("/Users/me/项目规划/示例");
  });
  it("removeRecent drops stale entries", () => {
    touchRecent("/a"); removeRecent("/a");
    expect(listRecents()).toEqual([]);
  });
});
```

```typescript
// LauncherRoute.test.tsx — 关键行为
it("create modal posts to /projects and navigates into the workbench", async () => {
  vi.spyOn(api, "createProject").mockResolvedValue({ project_root: "/tmp/ws/p1" });
  renderLauncher();
  fireEvent.click(screen.getByRole("button", { name: /新建项目/ }));
  fireEvent.change(screen.getByLabelText("parent folder"), { target: { value: "/tmp/ws" } });
  fireEvent.change(screen.getByLabelText("project name"), { target: { value: "p1" } });
  fireEvent.click(screen.getByRole("button", { name: /创建/ }));
  await waitFor(() =>
    expect(window.location.pathname).toBe(`/p/${rootToSlug("/tmp/ws/p1")}/graph`));
});

it("stale recent shows invalid state instead of red banner", async () => {
  touchRecent("/gone");
  vi.spyOn(api, "fetchRuns").mockRejectedValue(
    new ApiError(404, "not found", "PROJECT_NOT_FOUND"));
  renderLauncher();
  fireEvent.click(await screen.findByText("/gone"));
  expect(await screen.findByText(/失效|not found/i)).toBeInTheDocument();
});
```

(`ApiError` 构造参数顺序照 api.ts 真实签名;renderLauncher = MemoryRouter 包装 helper,照 App.test.tsx 模式写在测试文件内。)

- [ ] **Step 2: 跑测试确认失败** → Run: `cd frontend && npx vitest run src/launcher/` Expected: FAIL

- [ ] **Step 3: 实现 recents + LauncherRoute**

```typescript
// recents.ts
const KEY = "workbench.recentProjects.v1";
export type RecentProject = { root: string; lastOpened: string };

export function listRecents(): RecentProject[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "[]"); } catch { return []; }
}
export function touchRecent(root: string): void {
  const rest = listRecents().filter((r) => r.root !== root);
  const next = [{ root, lastOpened: new Date().toISOString() }, ...rest].slice(0, 12);
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* ignore */ }
}
export function removeRecent(root: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(listRecents().filter((r) => r.root !== root)));
  } catch { /* ignore */ }
}
```

LauncherRoute:卡片网格(项目名 = root 最后一段;点击 `touchRecent` + navigate 到 `/p/${rootToSlug(root)}/graph`)+「新建项目」modal(parent/name 两字段 + Browse 目录选择器——**校验逻辑与 folder-picker 从 SubmitRoute :81-118 原样搬移**,`createProject` 成功后 touchRecent + navigate)。stale 检测:点击卡片先 `fetchRuns(root)` 探活,`PROJECT_NOT_FOUND` 时标失效 + 提供「移除」(复用 v1.6.5 的错误码判别模式,App.tsx:232 同款)。样式复用既有 `.panel`/`.control-grid` class,不新增 CSS 体系。

- [ ] **Step 4: 跑测试确认通过** → Run: `cd frontend && npx vitest run src/launcher/` Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/launcher/
git commit -m "feat(fe): launcher — recent projects (localStorage) + create-project modal with stale detection"
```

---

## Task 11: FE — 工作台解除 runId 依赖 + 空画布(F1 前端半)+ 顶栏切换器

**Files:**
- Modify: `frontend/src/lineage/hooks/useForestData.ts`(project-keyed)
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`(`runId` 可选化 → `WorkbenchHome`)
- Modify: `frontend/src/workbench/WorkbenchTopbar.tsx`(项目切换器)
- Test: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`(追加)+ `frontend/src/lineage/hooks/useForestData.test.ts`(若无则新建)

- [ ] **Step 1: 写失败测试**

```typescript
// WorkbenchRouteContainer.test.tsx 追加
it("renders empty-canvas state with '＋ 新链路' CTA for a zero-run project", async () => {
  vi.spyOn(api, "fetchProjectForest").mockResolvedValue(
    { nodes: [], edges: [], heads: [], families: [] } as never);
  vi.spyOn(api, "listPipelineDrafts").mockResolvedValue([]);
  renderWorkbenchHome({ projectRoot: "/tmp/p1" });   // 无 runId
  expect(await screen.findByRole("button", { name: /新链路/ })).toBeInTheDocument();
});

it("still focuses a run when ?focus= is present", async () => {
  // fetchProjectForest 返回含 run 节点的森林 fixture(照文件内既有 forest fixture 改造)
  // 断言 activeRunId === focus 值(既有 activeRun 断言模式)
});
```

- [ ] **Step 2: 跑测试确认失败** → Run: `cd frontend && npx vitest run src/workbench/WorkbenchRouteContainer.test.tsx` Expected: FAIL

- [ ] **Step 3: 实现**

`useForestData(projectRoot: string, runId?: string)`:改为调 `fetchProjectForest(projectRoot)`(不再 `/runs/{id}/graph?view=headset`);`runId` 仅作为初始 focus 透传,不再参与取数。适配层(`adaptHeadSet`)入参形状不变——项目端点返回同形 body(Task 6 保证),0 run 时 `adaptHeadSet` 收到空数组产出空 ForestViewModel(如 adaptHeadSet 对空输入有假设,先加空态短路)。

`WorkbenchRouteContainer`:props 改 `{ projectRoot: string; focusRunId?: string }`,导出别名 `WorkbenchHome`(Task 9 的 ProjectGraphRoute 消费,`focus` 从 searchParams 读)。`forestToGraphViewModel(forest, runId)` 的 runId 改传 `focusRunId ?? forest.heads[0]?.run_id ?? null`——**该函数对 null 的行为要先读 forestModel.ts 确认,不容 null 就给空森林分支单独短路渲染空画布**。空森林渲染:画布区域中央空态卡(「这个项目还没有数据 → ＋ 新链路」按钮,点击打开 Task 12 的向导;本任务先 dispatch 一个 `data-testid="genesis-cta"` 按钮存根)。

`WorkbenchTopbar`:左侧插 `项目名 ▾` 按钮(项目名 = projectRoot 最后一段),下拉 = `listRecents()` + 「＋ 新建项目…」(复用 Task 10 modal 组件,提取成 `launcher/CreateProjectModal.tsx` 共享);选中项 navigate `/p/${rootToSlug(root)}/graph`。

- [ ] **Step 4: 跑测试确认通过 + tsc**

Run: `cd frontend && npx vitest run src/workbench/ src/lineage/ && npx tsc -p tsconfig.json --noEmit`
Expected: PASS / 0 errors(runId 可选化会翻出一串类型错——顺着修,全部显式处理 undefined,禁 `!` 断言)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/hooks/useForestData.ts frontend/src/workbench/ frontend/src/launcher/
git commit -m "feat(fe): project-keyed workbench — empty canvas + genesis CTA + topbar project switcher (F1)"
```

---

## Task 12: FE — 创世向导(抽屉三步 + 画布实时生长)

**Files:**
- Create: `frontend/src/lineage/drafts/GenesisWizard.tsx` + `GenesisWizard.test.tsx`
- Modify: `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`(认识创世 draft 三节点链)
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`(CTA 接线 + drafts 轮询已有)
- Test: `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`(追加)

- [ ] **Step 1: 写失败测试(merge 层先行——它是画布生长的根)**

```typescript
// mergeDraftsIntoModel.test.ts 追加
it("merges a genesis draft as a parentless 3-node dashed chain", () => {
  const genesisDraft = {
    draft_id: "d1", status: "draft",
    created_from: { source_type: "genesis", source_input_fingerprint: "abc" },
    graph: { nodes: [
      { node_id: "source_1", node_type: "input.upload",
        upload: { sha256: "abc", filename: "d.xlsx" }, sheet_names: ["S1"], status: "bound" },
      { node_id: "table_1", node_type: "table",
        params: { sheet_name: "S1", transpose: false }, columns: ["y","x"], status: "configured" },
      { node_id: "model_1", node_type: "model", model_type: "ols",
        params: { y: "y", x: ["x"] }, status: "configured" },
    ], edges: [ { from: "source_1", to: "table_1" }, { from: "table_1", to: "model_1" } ] },
  };
  const model = mergeDraftsIntoModel(EMPTY_FOREST_VM, [genesisDraft] as never);
  const ids = model.nodes.map((n) => n.id);
  expect(ids).toEqual(expect.arrayContaining(
    ["draft:d1:source_1", "draft:d1:table_1", "draft:d1:model_1"]));
  expect(model.nodes.find((n) => n.id === "draft:d1:model_1")?.data.draftLifecycle)
    .toBe("configured");
});
```

(`EMPTY_FOREST_VM`/节点 id 命名/`data.draftLifecycle` 字段名以 mergeDraftsIntoModel.ts 现实现为准——from-node draft 的 merge 已存在,创世是加一个分支,**照抄它已有的 id 方案与 lifecycle 字段**,断言按真名调整。)

- [ ] **Step 2: 跑测试确认失败** → Run: `cd frontend && npx vitest run src/lineage/drafts/` Expected: FAIL

- [ ] **Step 3: 实现 merge 分支 + GenesisWizard**

merge:`created_from.source_type === "genesis"` 时,三节点全部产出为 draft 节点(样式沿用既有 draft 虚线 token),edges 按 draft.graph.edges 映射,不挂任何既有 forest 节点(parentless 岛)。

GenesisWizard(抽屉宿主复用 v1.6.7 drawer 容器组件——先读 `lineage/detail` 里 draft 抽屉的组织方式,同构挂载):

```
步1 选文件:<input type="file"> → previewFile(file)(api.ts 既有 SheetJS)拿 sheetNames/columns
          → uploadDataset() → createGenesisDraft() → onDraftChange()(触发画布重渲染)
步2 选表:  sheet 下拉(=RunForm :498 的 sheet selector 逻辑)+ transpose checkbox
          → 重新 previewFile(file, sheet, transpose) 取该表 columns
          → patchDraftNode(draftId, "table_1", {params, columns})
步3 模型:  复用 RunForm 子组件(ModelTypeSelect / FocalSelect / 各 *Controls,
          props 喂 columns + capabilities——这些组件今天就吃这两样)
          → 每次变更 patchDraftNode(draftId, "model_1", {params})
步4 Run:   validate(execution_mode="genesis") → 问题内联展示在对应步
          → execute → 成功后 onExecuted(runId):关抽屉 + focus 新 run + refetch forest
```

断点续传:向导打开时若 `listPipelineDrafts` 里有 status="draft" 的 genesis draft,询问「继续上次的链路?」——续传时步进位置 = 第一个 status!=configured/bound 的节点;**文件本体不需要重传**(已在服务端),但步 2 换表需要重解析时提示重新选择本地文件(File 对象不可持久化,columns 已存 draft 可显示)。

GenesisWizard.test.tsx:mock api 三函数,走完三步断言 patch/execute 调用序列与参数;execute 失败(mockRejected)断言错误落在步 4 内联且抽屉不关(v1.6.7 error 硬化语义)。

- [ ] **Step 4: 跑测试确认通过 + tsc** → Run: `cd frontend && npx vitest run src/lineage/drafts/ && npx tsc -p tsconfig.json --noEmit` Expected: PASS/0

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/drafts/ frontend/src/workbench/WorkbenchRouteContainer.tsx
git commit -m "feat(fe): genesis wizard — 3-step drawer, draft chain grows on canvas live, resume after reload"
```

---

## Task 13: FE — ⌘K「快速 run」+ Submit 摘导航收尾

**Files:**
- Modify: `frontend/src/workbench/CommandPalette.tsx`(新命令)
- Modify: `frontend/src/App.tsx`(AppShell tab 清理的余项)
- Test: `frontend/src/workbench/CommandPalette.test.tsx`(追加)

- [ ] **Step 1: 写失败测试**:CommandPalette 打开后含「快速 run(旧表单)」项,选中 navigate `/submit?project_root=…`(照文件内既有命令项测试模式)。
- [ ] **Step 2: 确认失败** → `cd frontend && npx vitest run src/workbench/CommandPalette.test.tsx`
- [ ] **Step 3: 实现**:命令注册处加一项(id `quick-run-legacy`,label 「快速 run(旧表单)」,action = navigate)。AppShell 顶部 tabs 清理:确保无残余 Submit 入口(Task 9 已做主体,此处查漏:检查 header/nav 及所有 `navigate("/")` 语义仍指 Launcher)。
- [ ] **Step 4: 确认通过** → 同 Step 2 + `npx vitest run`
- [ ] **Step 5: Commit** → `git commit -m "feat(fe): cmd-k quick-run fallback to /submit; submit fully off primary nav (F7)"`

---

## Task 14: 全量 gate + 真机 CDP smoke

**Files:** 无新代码(只修 gate 翻出的问题)。

- [ ] **Step 1: BE 全量 + golden**

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 python -m pytest tests/ -q
```
Expected: 全 PASS(≥1302 + 新增),golden 23 0-drift

- [ ] **Step 2: FE 全量 + tsc**

```bash
cd frontend && npx vitest run && npx tsc -p tsconfig.json --noEmit
```
Expected: 全 PASS(≥837 + 新增)/ 0 errors

- [ ] **Step 3: 真机 smoke(CDP,验收硬标准)**

后端 `python -m workbench.cli serve`(或项目既有启动命令,先查 README)+ 前端 `npm run dev`,浏览器走:
1. 打开 `/` → 见 Launcher(无 Submit 表单)
2. 新建项目(**父目录用含中文路径**)→ 落 `/p/:slug/graph` 空画布 + 「＋ 新链路」
3. 向导三步(真实 xlsx 多 sheet 文件)→ 画布逐步长出 3 个虚线节点
4. Run → run 完成 → 虚线变实线 + 结果可在 Table/detail 看到
5. 刷新页面 → 森林还在;中途弃链再刷新 → 向导可续传
6. 旧深链 `/runs/<run_id>?project_root=…` → 重定向落图并 focus
Expected: 全部通过 = 验收达成(「全程不见旧 Submit 表单」)

- [ ] **Step 4: Commit(若有修复)+ 汇报**

```bash
git add -A && git commit -m "test: v1.6.8 gate pass + live smoke fixes"
```

---

## Task 15: 收尾 — roadmap 改签 + 文档

**Files:**
- Modify: `docs/superpowers/roadmap/2026-07-01-unified-graph-workbench-roadmap.md`(若在本 worktree 存在;v1.6.8=Genesis,原内容→v1.6.9)
- Create: `docs/superpowers/followups/v1.6.8-followups.md`(范围外清单落账:画布拖放/Submit 删码/batch 图内化/全量 GC)

- [ ] **Step 1: 写 followups + 改 roadmap**(内容 = spec §9 逐条搬运,每条注明来源)
- [ ] **Step 2: Commit** → `git commit -m "docs: v1.6.8 followups + roadmap reassignment (compare/AI/report -> v1.6.9)"`

---

## 自审记录(计划 vs spec)

- **Spec 覆盖**:§4.1→Task 6;§4.2→Task 1;§4.3→Task 2/3/4;§4.4→Task 5;§4.5→Task 7;§5 路由→Task 9;Launcher→Task 10;工作台解耦+切换器→Task 11;向导+schema 来源(F4 refinement:params-only + RunForm 控件复用,比 spec 的静态 editable_schema 模板更薄,已在 Task 2 注明)→Task 12;⌘K/F7→Task 13;§8 测试→各任务 TDD + Task 14;§9→Task 15。无遗漏。
- **占位符**:无 TBD/TODO;所有"以真实现为准"处均给出对齐动作(grep/打样)与对齐对象,属于防幻觉指令而非留白。
- **类型一致性**:`rootToSlug/slugToRoot`(8/9/10/11)、`fetchProjectForest`(8/11)、`patchDraftNode`(8/12)、`WorkbenchHome{projectRoot,focusRunId}`(9/11)、`execution_mode="genesis"`(4/5/12)已交叉核对一致。
