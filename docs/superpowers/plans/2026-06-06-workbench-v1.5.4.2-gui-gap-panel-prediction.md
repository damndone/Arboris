# V1.5.4.2 — GUI Gap Closure (Panel + Prediction) + iOS Design — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface backend estimation capabilities that exist but are unreachable from the GUI — panel entity/time columns, panel covariance, prediction/ML models (algorithm + cv_folds + sampling) — render their results, and apply an iOS design language to the run form and result/history pages.

**Architecture:** All new backend params are optional and default to current behavior (golden snapshots must not drift). Panel columns are injected by **overriding** `ctx.artifacts["_id_candidates"]/["_time_candidates"]` in `RoutingStage`; prediction params follow a **request-over-config** precedence in `DiagnosticsStage`; the capability manifest is extended so the frontend renders new controls dynamically (continuing V1.5.4.1's capability-driven pattern). Frontend mirrors the existing `ImputationControls`/`ImputationSummary` patterns.

**Tech Stack:** Python 3.11, FastAPI, pandas, statsmodels/linearmodels/scikit-learn (optional extras), pytest; React + TypeScript + Vitest; CSS variables for the iOS design tokens.

**Spec:** `docs/superpowers/specs/2026-06-06-workbench-v1.5.4.2-gui-gap-panel-prediction-design.md`

---

## File Structure

**Backend (modify):**
- `backend/workbench/orchestrator.py` — add optional params to `run_workflow()` and `_run_workflow()`; stash into `ctx.artifacts`.
- `backend/workbench/engine/stages/routing.py` — override candidates when user supplies entity/time.
- `backend/workbench/engine/stages/estimation.py` — `_fit_panel_ols` passes `covariance`.
- `backend/workbench/engine/stages/diagnostics.py` — prediction params request-over-config.
- `backend/workbench/api.py` — new `POST /runs` Form fields; thread to `_bg_run`.
- `backend/workbench/engine/capabilities.py` — extend manifest.

**Backend (create tests):**
- `tests/test_panel_columns.py`, `tests/test_panel_covariance.py`, `tests/test_prediction_request.py`, `tests/test_capabilities_v1542.py`, `tests/test_e2e_panel_prediction.py`.

**Frontend (create):**
- `frontend/src/runForm/PanelControls.tsx` (+ `.test.tsx`)
- `frontend/src/runForm/PredictionControls.tsx` (+ `.test.tsx`)
- `frontend/src/runResult/PredictionResultCard.tsx` (+ `.test.tsx`)

**Frontend (modify):**
- `frontend/src/api.ts` — `runWorkflow` new params.
- `frontend/src/capabilities/types.ts` — new manifest fields.
- `frontend/src/App.tsx` — state + submission + validation + controls.
- `frontend/src/runResult.tsx` — fetch + render `PredictionResultCard`.
- `frontend/src/styles.css` — iOS design tokens + rollout.

---

## Phase 0 — Worktree Setup

### Task 0: Create branch, worktree, environments

**Files:** none (environment only)

- [ ] **Step 1: Create branch + worktree from main head**

```bash
cd "/Users/jiayuanren/项目规划"
git fetch origin
git worktree add -b workbench-v1.5.4.2 .worktrees/workbench-v1.5.4.2 main
cd .worktrees/workbench-v1.5.4.2
```

- [ ] **Step 2: Build backend venv with full extras**

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```

- [ ] **Step 3: Install frontend deps**

```bash
cd frontend && npm install && cd ..
```

- [ ] **Step 4: Baseline gate (record green starting point)**

Run:
```bash
.venv/bin/pytest -q
cd frontend && npx vitest run && cd ..
```
Expected: backend all pass (full extras), frontend all pass. Record the counts — these are the no-regression baseline.

- [ ] **Step 5: Commit (worktree marker)**

```bash
git commit --allow-empty -m "chore: start V1.5.4.2 worktree (panel + prediction GUI gap)"
```

---

## Phase 1 — Panel entity/time columns (Backend)

### Task 1: Thread entity/time params and override candidates in RoutingStage

**Files:**
- Modify: `backend/workbench/orchestrator.py` (`run_workflow`, `_run_workflow`)
- Modify: `backend/workbench/engine/stages/routing.py`
- Test: `tests/test_panel_columns.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_panel_columns.py
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("linearmodels")


def _panel_frame() -> pd.DataFrame:
    rows = []
    for firm in ("A", "B", "C"):
        for year in (2019, 2020, 2021, 2022):
            base = {"A": 10, "B": 20, "C": 30}[firm]
            rows.append({
                "firm": firm,
                "yr": year,
                "profit": base + (year - 2019) * 2.0,
                "rnd": base / 2 + (year - 2019),
            })
    return pd.DataFrame(rows)


def _run(tmp_path, frame, **kwargs):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], **kwargs)
    return project.root / "runs" / result["run_id"], result


def test_user_entity_time_drives_panel_fit(tmp_path):
    run_root, result = _run(
        tmp_path,
        _panel_frame(),
        mode="auto",
        y="profit",
        x=["rnd"],
        model_type="panel_ols",
        entity_col="firm",
        time_col="yr",
    )
    assert result["status"] == "completed"
    router = read_json(run_root / "staged" / "analysis_router.json")
    assert "firm" in router.get("id_candidates", [])
    assert "yr" in router.get("time_candidates", [])


def test_omitting_entity_time_is_backward_compatible(tmp_path):
    # No entity/time supplied: must still run via auto-detection (no crash,
    # no override). This guards the default path.
    run_root, result = _run(
        tmp_path, _panel_frame(), mode="auto", y="profit", x=["rnd"],
        model_type="auto",
    )
    assert result["status"] in ("completed", "blocked")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_panel_columns.py -v`
Expected: FAIL — `run_workflow() got an unexpected keyword argument 'entity_col'`.

- [ ] **Step 3: Add params to `run_workflow`**

In `backend/workbench/orchestrator.py`, change the `run_workflow` signature (currently ends `imputation: dict | None = None,`) to add two params, and forward them to `_run_workflow`:

```python
def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
    model_type: str = "auto",
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
) -> dict[str, str]:
```

Find the `return _run_workflow(...)` call inside `run_workflow` and add the new keyword arguments to it:

```python
        return _run_workflow(
            run.root,
            run.run_id,
            input_files,
            mode,
            y,
            x,
            config,
            started_at,
            model_type=model_type,
            imputation=imputation,
            entity_col=entity_col,
            time_col=time_col,
            covariance=covariance,
            prediction_model_type=prediction_model_type,
            prediction_cv_folds=prediction_cv_folds,
            prediction_sampling_method=prediction_sampling_method,
        )
```

> NOTE: keep all the other existing positional/keyword args in that call exactly as they are; only add the six new keyword args. Covariance/prediction params are consumed in Tasks 2–3 but are plumbed here once.

- [ ] **Step 4: Add params to `_run_workflow` and stash into ctx.artifacts**

In `_run_workflow`, extend the signature (after `imputation: dict | None = None,`):

```python
    imputation: dict | None = None,
    entity_col: str = "",
    time_col: str = "",
    covariance: str = "",
    prediction_model_type: str = "",
    prediction_cv_folds: int = 0,
    prediction_sampling_method: str = "",
) -> dict[str, str]:
```

Then, in the block where other `ctx.artifacts["_..."]` are assigned (right after `ctx.artifacts["_imputation_request"] = imputation`), add:

```python
    ctx.artifacts["_entity_col"] = entity_col
    ctx.artifacts["_time_col"] = time_col
    ctx.artifacts["_covariance"] = covariance
    ctx.artifacts["_prediction_model_type"] = prediction_model_type
    ctx.artifacts["_prediction_cv_folds"] = prediction_cv_folds
    ctx.artifacts["_prediction_sampling_method"] = prediction_sampling_method
```

- [ ] **Step 5: Override candidates in RoutingStage**

In `backend/workbench/engine/stages/routing.py`, after the existing lines that compute `time_candidates` and `id_candidates` and BEFORE `routing = classify_dataset(...)`, insert user overrides:

```python
        time_candidates = _normalized_existing(schema.time_candidates, cleaned)
        id_candidates = _normalized_existing(schema.id_candidates, cleaned)

        # V1.5.4.2: user-supplied panel columns override auto-detection.
        # Only override when the named column actually exists in the cleaned
        # frame; otherwise fall back to detection (defensive).
        entity_col = ctx.artifacts.get("_entity_col") or ""
        time_col = ctx.artifacts.get("_time_col") or ""
        if entity_col and entity_col in cleaned.columns:
            id_candidates = [entity_col]
        if time_col and time_col in cleaned.columns:
            time_candidates = [time_col]

        routing = classify_dataset(cleaned, id_candidates, time_candidates)
```

> The downstream `ctx.artifacts["_time_candidates"]`/`["_id_candidates"]` assignments already exist below this block and will now carry the overridden lists. `estimation._fit_panel_ols` reads `[0]` of these — no change needed there for entity/time.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_panel_columns.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Golden no-drift check**

Run: `.venv/bin/pytest tests/test_engine_golden.py -v`
Expected: PASS, 7 goldens unchanged (no new param passed → behavior identical).

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/orchestrator.py backend/workbench/engine/stages/routing.py tests/test_panel_columns.py
git commit -m "feat(engine): user-supplied panel entity/time override auto-detection"
```

---

## Phase 2 — Panel covariance (Backend)

### Task 2: `_fit_panel_ols` honors requested covariance

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py` (`_fit_panel_ols`)
- Test: `tests/test_panel_covariance.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_panel_covariance.py
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("linearmodels")


def _panel_frame() -> pd.DataFrame:
    rows = []
    for firm in ("A", "B", "C", "D"):
        for year in (2019, 2020, 2021, 2022):
            base = {"A": 10, "B": 20, "C": 30, "D": 40}[firm]
            rows.append({"firm": firm, "yr": year,
                         "profit": base + (year - 2019) * 2.0 + (hash((firm, year)) % 5),
                         "rnd": base / 2 + (year - 2019)})
    return pd.DataFrame(rows)


def test_clustered_covariance_runs(tmp_path):
    source = tmp_path / "data.csv"
    _panel_frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="profit", x=["rnd"],
        model_type="panel_ols", entity_col="firm", time_col="yr",
        covariance="clustered",
    )
    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    model = read_json(run_root / "model_results" / "panel_ols_1.json")
    assert model["model_type"] == "panel_ols"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_panel_covariance.py -v`
Expected: FAIL — `_fit_panel_ols` ignores covariance (TypeError is NOT expected; failure is that covariance is not forwarded). If linearmodels rejects `"clustered"` without cluster entity, adjust to `covariance="robust"` and assert it still completes; the point is the param threads through.

> Decision: `run_panel_ols(covariance=...)` already accepts the value and passes it to `.fit(cov_type=...)`. Valid linearmodels `cov_type` values include `"unadjusted"`, `"robust"`, `"clustered"`, `"kernel"`. For `"clustered"` linearmodels uses entity/time clusters from the index. Keep the test value `"clustered"`; if the installed linearmodels needs explicit cluster flags, fall back to `"robust"` in the test and document.

- [ ] **Step 3: Forward covariance in `_fit_panel_ols`**

In `backend/workbench/engine/stages/estimation.py`, modify `_fit_panel_ols`:

```python
def _fit_panel_ols(ctx, env):
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    covariance = ctx.artifacts.get("_covariance") or "robust"
    primary, fitted = _orch().run_panel_ols(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        model_id="panel_ols_1",
        covariance=covariance,
    )
    return "panel_ols_1", primary, None
```

> `"robust"` is the existing `run_panel_ols` default, so omitting covariance reproduces current behavior exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_panel_covariance.py -v`
Expected: PASS.

- [ ] **Step 5: Golden no-drift check**

Run: `.venv/bin/pytest tests/test_engine_golden.py -v`
Expected: PASS (default covariance unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/stages/estimation.py tests/test_panel_covariance.py
git commit -m "feat(engine): panel_ols honors requested covariance (default robust)"
```

---

## Phase 3 — Prediction request-over-config (Backend)

### Task 3: Prediction params come from request first, config fallback

**Files:**
- Modify: `backend/workbench/engine/stages/diagnostics.py`
- Test: `tests/test_prediction_request.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prediction_request.py
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("sklearn")


def _frame() -> pd.DataFrame:
    n = 60
    xs = [float(i) for i in range(n)]
    ys = [2.0 + 1.5 * v + (i % 7) for i, v in enumerate(xs)]
    return pd.DataFrame({"y": ys, "x": xs})


def test_prediction_via_request_writes_artifact(tmp_path):
    source = tmp_path / "data.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    # config.yml has prediction_enabled=False by default; request must drive it.
    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"],
        model_type="auto",
        prediction_model_type="prediction_ridge",
        prediction_cv_folds=3,
    )
    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    pred = read_json(run_root / "prediction_results" / "prediction_ridge_1.json")
    assert pred["model_type"] == "prediction_ridge"
    assert pred["cv_folds"] == 3
    assert "metrics" in pred


def test_no_prediction_request_writes_nothing(tmp_path):
    source = tmp_path / "data.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / result["run_id"]
    assert not (run_root / "prediction_results").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_prediction_request.py -v`
Expected: FAIL on `test_prediction_via_request_writes_artifact` — artifact not written (request params ignored; only config drives prediction today).

- [ ] **Step 3: Read request params first in DiagnosticsStage**

In `backend/workbench/engine/stages/diagnostics.py`, locate the prediction block (currently):

```python
        prediction_model_type = (
            model_type
            if model_type in _PREDICTION_MODEL_TYPES
            else config.prediction_model_type if config.prediction_enabled else ""
        )
        if prediction_model_type:
            prediction_model_id = f"{prediction_model_type}_1"
            try:
                run_prediction_model(
                    modeling_frame,
                    run_root,
                    y=normalized_y,
                    x=normalized_x,
                    model_type=prediction_model_type,
                    model_id=prediction_model_id,
                    cv_folds=config.prediction_cv_folds,
                    random_seed=config.random_seed,
                    inputs=model_input_ids,
                    sampling_method=config.prediction_sampling_method,
                )
```

Replace the selection + the three config-sourced kwargs with request-over-config resolution. First, near the top of the `run` method where other `ctx.artifacts[...]` are read (alongside `config = ctx.artifacts["_config"]`), add:

```python
        req_pred_type = ctx.artifacts.get("_prediction_model_type") or ""
        req_pred_folds = ctx.artifacts.get("_prediction_cv_folds") or 0
        req_pred_sampling = ctx.artifacts.get("_prediction_sampling_method") or ""
```

Then change the prediction block to:

```python
        prediction_model_type = (
            model_type
            if model_type in _PREDICTION_MODEL_TYPES
            else req_pred_type
            or (config.prediction_model_type if config.prediction_enabled else "")
        )
        if prediction_model_type:
            prediction_model_id = f"{prediction_model_type}_1"
            cv_folds = req_pred_folds or config.prediction_cv_folds
            sampling_method = req_pred_sampling or config.prediction_sampling_method
            try:
                run_prediction_model(
                    modeling_frame,
                    run_root,
                    y=normalized_y,
                    x=normalized_x,
                    model_type=prediction_model_type,
                    model_id=prediction_model_id,
                    cv_folds=cv_folds,
                    random_seed=config.random_seed,
                    inputs=model_input_ids,
                    sampling_method=sampling_method,
                )
```

> Leave the two `except` handlers (OptionalDependencyNotInstalled, ValueError) unchanged. When no request param and config disabled, `prediction_model_type` is `""` → block skipped → no artifact (preserves `test_no_prediction_request_writes_nothing`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_prediction_request.py -v`
Expected: PASS (both).

- [ ] **Step 5: Golden no-drift check**

Run: `.venv/bin/pytest tests/test_engine_golden.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/stages/diagnostics.py tests/test_prediction_request.py
git commit -m "feat(engine): prediction params from request first, config fallback"
```

---

## Phase 4 — API surface (Backend)

### Task 4: New `POST /runs` Form fields threaded to the worker

**Files:**
- Modify: `backend/workbench/api.py` (`run_endpoint`, `_bg_run`)
- Test: append to `tests/test_e2e_panel_prediction.py` (created in Task 7) — for now add a focused API test here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_run_params.py
import io
import pandas as pd
from unittest.mock import patch

from fastapi.testclient import TestClient

from workbench.api import app


def _csv() -> bytes:
    return pd.DataFrame({"y": [1.0, 2, 3, 4], "x": [1.0, 2, 3, 4],
                         "firm": ["a", "a", "b", "b"], "yr": [1, 2, 1, 2]}).to_csv(index=False).encode()


def test_run_endpoint_forwards_new_params(tmp_path):
    client = TestClient(app)
    proj = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    root = proj.json()["project_root"]

    captured = {}

    def _fake_bg(run_root, run_id, saved_path, mode, y, x, started_at, model_type,
                 sheet_name, transpose, imputation, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    with patch("workbench.api._bg_run", _fake_bg):
        resp = client.post("/runs", data={
            "project_root": root, "mode": "auto", "model_type": "panel_ols",
            "y": "y", "x": "x",
            "entity_col": "firm", "time_col": "yr", "covariance": "robust",
            "prediction_model_type": "prediction_ridge", "prediction_cv_folds": "3",
            "prediction_sampling_method": "",
        }, files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")})

    assert resp.status_code == 200
    # new params arrive as trailing positional/keyword args to _bg_run
    flat = list(captured.get("args", ())) + list(captured.get("kwargs", {}).values())
    assert "firm" in flat and "yr" in flat and "prediction_ridge" in flat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_api_run_params.py -v`
Expected: FAIL — `entity_col` etc. not accepted / not forwarded.

- [ ] **Step 3: Add Form fields to `run_endpoint`**

In `backend/workbench/api.py`, extend the `run_endpoint` signature (after `imputation: str = Form(""),`):

```python
    imputation: str = Form(""),
    entity_col: str = Form(""),
    time_col: str = Form(""),
    covariance: str = Form(""),
    prediction_model_type: str = Form(""),
    prediction_cv_folds: str = Form("0"),
    prediction_sampling_method: str = Form(""),
) -> dict[str, str]:
```

- [ ] **Step 4: Forward to `_bg_run` via the executor submit**

Locate the `events.executor.submit(_bg_run, ...)` call and append the new args (after `imputation_request,`):

```python
        events.executor.submit(
            _bg_run, run.root, run.run_id, saved_path,
            mode, y, x_columns, started_at, model_type,
            sheet_name or None, transpose == "true", imputation_request,
            entity_col, time_col, covariance,
            prediction_model_type, _safe_int(prediction_cv_folds),
            prediction_sampling_method,
        )
```

Add a tiny helper near the top of `api.py` (after imports):

```python
def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
```

- [ ] **Step 5: Extend `_bg_run` / `_execute_run` to accept and forward**

Find `_bg_run` (the function submitted to the executor; it wraps `_execute_run`). Extend its signature with the new trailing params and forward them into the `run_workflow`/`_run_workflow` call. The execute helper currently passes `model_type=..., imputation=...` — add:

```python
def _bg_run(run_root, run_id, saved_path, mode, y, x, started_at, model_type,
            sheet_name, transpose, imputation,
            entity_col="", time_col="", covariance="",
            prediction_model_type="", prediction_cv_folds=0,
            prediction_sampling_method=""):
    ...
    # in the _run_workflow(...) call, add:
            entity_col=entity_col,
            time_col=time_col,
            covariance=covariance,
            prediction_model_type=prediction_model_type,
            prediction_cv_folds=prediction_cv_folds,
            prediction_sampling_method=prediction_sampling_method,
```

> Read the current `_bg_run`/`_execute_run` body first (`backend/workbench/api.py` around line 219+) and thread the params through whichever helper actually calls `_run_workflow`. Keep the existing args unchanged; only append.

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_api_run_params.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/api.py tests/test_api_run_params.py
git commit -m "feat(api): POST /runs accepts panel + prediction params"
```

---

## Phase 5 — Capability manifest (Backend)

### Task 5: Extend `build_capabilities()` with prediction/sampling/covariance

**Files:**
- Modify: `backend/workbench/engine/capabilities.py`
- Test: `tests/test_capabilities_v1542.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_capabilities_v1542.py
from workbench.engine.capabilities import build_capabilities


def test_manifest_exposes_new_groups():
    caps = build_capabilities()
    assert "prediction_models" in caps
    keys = {m["key"] for m in caps["prediction_models"]}
    assert {"prediction_lasso", "prediction_ridge", "prediction_random_forest"} <= keys

    assert "sampling_methods" in caps
    skeys = {s["key"] for s in caps["sampling_methods"]}
    assert {"smote", "oversample", "undersample"} <= skeys

    assert "covariance_options" in caps
    ckeys = {c["key"] for c in caps["covariance_options"]}
    assert {"robust", "clustered"} <= ckeys


def test_manifest_backward_compatible():
    caps = build_capabilities()
    # V1.5.4.1 fields still present and unchanged in shape.
    assert caps["schema_version"] >= 1
    assert any(m["key"] == "auto" for m in caps["model_types"])
    assert "imputation_methods" in caps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_capabilities_v1542.py -v`
Expected: FAIL — `prediction_models` not in manifest.

- [ ] **Step 3: Extend `build_capabilities()`**

In `backend/workbench/engine/capabilities.py`, add module-level metadata and extend the returned dict:

```python
PREDICTION_UI = [
    {"key": "prediction_lasso", "label": "Lasso", "description": "L1-regularized linear prediction."},
    {"key": "prediction_ridge", "label": "Ridge", "description": "L2-regularized linear prediction."},
    {"key": "prediction_random_forest", "label": "Random Forest", "description": "Tree-ensemble prediction."},
]

SAMPLING_UI = [
    {"key": "smote", "label": "SMOTE"},
    {"key": "oversample", "label": "Oversample"},
    {"key": "undersample", "label": "Undersample"},
]

COVARIANCE_UI = [
    {"key": "robust", "label": "Robust (default)"},
    {"key": "clustered", "label": "Clustered"},
    {"key": "unadjusted", "label": "Unadjusted"},
]
```

Then bump `schema_version` to `2` and add the three keys to the return dict:

```python
    return {
        "schema_version": 2,
        "model_types": model_types,
        "imputation_methods": imputation_methods,
        "prediction_models": list(PREDICTION_UI),
        "sampling_methods": list(SAMPLING_UI),
        "covariance_options": list(COVARIANCE_UI),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_capabilities_v1542.py -v`
Expected: PASS.

- [ ] **Step 5: Update any manifest contract test that pins schema_version**

Run: `.venv/bin/pytest tests/ -k capabilities -v`
Expected: PASS. If a contract test in `tests/contracts/` asserts `schema_version == 1`, update it to `2` and note the additive change.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/capabilities.py tests/test_capabilities_v1542.py
git commit -m "feat(capabilities): expose prediction/sampling/covariance (schema v2)"
```

---

## Phase 6 — End-to-end (Backend)

### Task 6: e2e panel + prediction through the HTTP API

**Files:**
- Test: `tests/test_e2e_panel_prediction.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_panel_prediction.py
import io
import time
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app

pytest.importorskip("linearmodels")
pytest.importorskip("sklearn")


def _panel_csv() -> bytes:
    rows = []
    for firm in ("A", "B", "C"):
        for yr in (2019, 2020, 2021, 2022):
            base = {"A": 10, "B": 20, "C": 30}[firm]
            rows.append({"firm": firm, "yr": yr,
                         "profit": base + (yr - 2019) * 2.0, "rnd": base / 2 + (yr - 2019)})
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _wait(client, root, run_id, deadline=40.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline:
        r = client.get(f"/runs/{run_id}", params={"project_root": root})
        if r.status_code == 200 and r.json().get("status") in ("completed", "blocked", "failed"):
            return r.json()["status"]
        time.sleep(0.3)
    raise AssertionError("run did not terminate")


def test_e2e_panel_with_user_columns(tmp_path):
    client = TestClient(app)
    root = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"}).json()["project_root"]
    resp = client.post("/runs", data={
        "project_root": root, "mode": "auto", "model_type": "panel_ols",
        "y": "profit", "x": "rnd", "entity_col": "firm", "time_col": "yr",
    }, files={"file": ("d.csv", io.BytesIO(_panel_csv()), "text/csv")})
    run_id = resp.json()["run_id"]
    assert _wait(client, root, run_id) == "completed"


def test_e2e_prediction_artifact_fetchable(tmp_path):
    client = TestClient(app)
    root = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"}).json()["project_root"]
    csv = pd.DataFrame({"y": [2.0 + 1.5 * i for i in range(60)],
                        "x": [float(i) for i in range(60)]}).to_csv(index=False).encode()
    resp = client.post("/runs", data={
        "project_root": root, "mode": "auto", "model_type": "auto",
        "y": "y", "x": "x", "prediction_model_type": "prediction_ridge",
        "prediction_cv_folds": "3",
    }, files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    run_id = resp.json()["run_id"]
    assert _wait(client, root, run_id) == "completed"
    # the artifact the PredictionResultCard will fetch
    art = client.get(f"/runs/{run_id}/artifacts/prediction_ridge_1", params={"project_root": root})
    assert art.status_code == 200
    assert art.json()["model_type"] == "prediction_ridge"
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `.venv/bin/pytest tests/test_e2e_panel_prediction.py -v`
Expected: should PASS if Tasks 1–4 are correct. If the artifact GET path differs, inspect the artifact id used by `register_artifact` (`model_id` = `prediction_ridge_1`) and the `/runs/{id}/artifacts/{artifact_id}` route in `api.py`.

- [ ] **Step 3: Fix any wiring gaps revealed**

If `test_e2e_prediction_artifact_fetchable` 404s, confirm the artifact endpoint resolves by `artifact_id` (it does for `imputation_summary` in V1.5.4.1). Adjust the param name if the route requires `?project_root=`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_panel_prediction.py
git commit -m "test(e2e): panel user-columns + prediction artifact via API"
```

- [ ] **Step 5: Full backend gate**

Run: `.venv/bin/pytest -q`
Expected: all pass; goldens unchanged. Record the new count vs Task 0 baseline.

---

## Phase 7 — Frontend API + types

### Task 7: `runWorkflow` new params + manifest types

**Files:**
- Modify: `frontend/src/api.ts` (`runWorkflow`)
- Modify: `frontend/src/capabilities/types.ts`
- Test: `frontend/src/api.test.ts` (append)

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/api.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { runWorkflow } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("runWorkflow panel+prediction params", () => {
  it("appends entity/time/covariance/prediction params to FormData", async () => {
    let sent: FormData | null = null;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      sent = init.body as FormData;
      return new Response(JSON.stringify({ run_id: "r1", status: "running" }),
        { status: 200, headers: { "content-type": "application/json" } });
    }));
    const file = new File(["y,x\n1,2"], "d.csv", { type: "text/csv" });
    await runWorkflow("/proj", "auto", "y", "x", file, "panel_ols", undefined, false, undefined, {
      entityCol: "firm", timeCol: "yr", covariance: "robust",
      predictionModelType: "prediction_ridge", predictionCvFolds: 3,
      predictionSamplingMethod: "",
    });
    expect(sent!.get("entity_col")).toBe("firm");
    expect(sent!.get("time_col")).toBe("yr");
    expect(sent!.get("covariance")).toBe("robust");
    expect(sent!.get("prediction_model_type")).toBe("prediction_ridge");
    expect(sent!.get("prediction_cv_folds")).toBe("3");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: FAIL — `runWorkflow` has no 10th options arg.

- [ ] **Step 3: Add an options arg to `runWorkflow`**

In `frontend/src/api.ts`, extend `runWorkflow` with a trailing optional options object (keeps existing positional callers working):

```ts
export interface RunExtraParams {
  entityCol?: string;
  timeCol?: string;
  covariance?: string;
  predictionModelType?: string;
  predictionCvFolds?: number;
  predictionSamplingMethod?: string;
}

export async function runWorkflow(
  projectRoot: string,
  mode: string,
  y: string,
  x: string,
  file: File,
  modelType: string = "auto",
  sheetName?: string,
  transpose?: boolean,
  imputation?: string,
  extra?: RunExtraParams,
): Promise<RunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("model_type", modelType);
  form.append("y", y);
  form.append("x", x);
  if (sheetName) form.append("sheet_name", sheetName);
  if (transpose) form.append("transpose", "true");
  if (imputation) form.append("imputation", imputation);
  if (extra?.entityCol) form.append("entity_col", extra.entityCol);
  if (extra?.timeCol) form.append("time_col", extra.timeCol);
  if (extra?.covariance) form.append("covariance", extra.covariance);
  if (extra?.predictionModelType)
    form.append("prediction_model_type", extra.predictionModelType);
  if (extra?.predictionCvFolds)
    form.append("prediction_cv_folds", String(extra.predictionCvFolds));
  if (extra?.predictionSamplingMethod)
    form.append("prediction_sampling_method", extra.predictionSamplingMethod);
  form.append("file", file);
  const response = await fetch(apiUrl("/runs"), { method: "POST", body: form });
  return readResponse<RunResponse>(response);
}
```

- [ ] **Step 4: Extend manifest types**

In `frontend/src/capabilities/types.ts`:

```ts
export interface PredictionModelEntry {
  key: string;
  label: string;
  description?: string;
}

export interface SamplingMethodEntry {
  key: string;
  label: string;
}

export interface CovarianceOption {
  key: string;
  label: string;
}

export interface Capabilities {
  schema_version: number;
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
  prediction_models?: PredictionModelEntry[];
  sampling_methods?: SamplingMethodEntry[];
  covariance_options?: CovarianceOption[];
}
```

> Mark the three new fields optional so existing tests that construct `Capabilities` without them still typecheck.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/capabilities/types.ts frontend/src/api.test.ts
git commit -m "feat(frontend): runWorkflow panel+prediction params + manifest types"
```

---

## Phase 8 — PanelControls (Frontend)

### Task 8: Panel entity/time + covariance control

**Files:**
- Create: `frontend/src/runForm/PanelControls.tsx`
- Test: `frontend/src/runForm/PanelControls.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/runForm/PanelControls.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PanelControls } from "./PanelControls";
import type { Capabilities } from "../capabilities/types";

const caps: Capabilities = {
  schema_version: 2, model_types: [], imputation_methods: [],
  covariance_options: [{ key: "robust", label: "Robust (default)" },
                       { key: "clustered", label: "Clustered" }],
};

describe("PanelControls", () => {
  it("offers column choices and reports selection", () => {
    const onEntity = vi.fn();
    render(<PanelControls capabilities={caps} columns={["firm", "yr", "profit"]}
      entity="" time="" covariance="" onEntity={onEntity} onTime={vi.fn()} onCovariance={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/entity/i), { target: { value: "firm" } });
    expect(onEntity).toHaveBeenCalledWith("firm");
  });

  it("renders covariance options from the manifest", () => {
    render(<PanelControls capabilities={caps} columns={["firm"]} entity="" time="" covariance=""
      onEntity={vi.fn()} onTime={vi.fn()} onCovariance={vi.fn()} />);
    expect(screen.getByText("Clustered")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runForm/PanelControls.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `PanelControls`**

```tsx
// frontend/src/runForm/PanelControls.tsx
import type { Capabilities } from "../capabilities/types";

export function PanelControls(props: {
  capabilities: Capabilities | undefined;
  columns: string[];
  entity: string;
  time: string;
  covariance: string;
  onEntity: (v: string) => void;
  onTime: (v: string) => void;
  onCovariance: (v: string) => void;
}) {
  const cov = props.capabilities?.covariance_options ?? [];
  return (
    <div className="ios-group" aria-label="Panel settings">
      <div className="ios-group-label">面板设置 · 个体 / 时间二选一</div>
      <div className="ios-row-pair">
        <label className="ios-field">
          <span>个体列 entity</span>
          <select value={props.entity} onChange={(e) => props.onEntity(e.target.value)}>
            <option value="">(自动)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="ios-field">
          <span>时间列 time</span>
          <select value={props.time} onChange={(e) => props.onTime(e.target.value)}>
            <option value="">(自动)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {cov.length > 0 && (
        <label className="ios-field">
          <span>标准误 covariance</span>
          <select value={props.covariance} onChange={(e) => props.onCovariance(e.target.value)}>
            {cov.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </label>
      )}
      <div className="ios-hint">两者都留空 → 自动探测（向后兼容）</div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/runForm/PanelControls.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/PanelControls.tsx frontend/src/runForm/PanelControls.test.tsx
git commit -m "feat(frontend): PanelControls (entity/time/covariance)"
```

---

## Phase 9 — PredictionControls (Frontend)

### Task 9: Prediction toggle + algorithm + cv_folds + sampling

**Files:**
- Create: `frontend/src/runForm/PredictionControls.tsx`
- Test: `frontend/src/runForm/PredictionControls.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/runForm/PredictionControls.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PredictionControls } from "./PredictionControls";
import type { Capabilities } from "../capabilities/types";

const caps: Capabilities = {
  schema_version: 2, model_types: [], imputation_methods: [],
  prediction_models: [
    { key: "prediction_lasso", label: "Lasso" },
    { key: "prediction_ridge", label: "Ridge" },
  ],
  sampling_methods: [{ key: "smote", label: "SMOTE" }],
};

describe("PredictionControls", () => {
  it("hides detail when disabled and reports algorithm on select", () => {
    const onModel = vi.fn();
    render(<PredictionControls capabilities={caps} enabled={true}
      modelType="prediction_lasso" cvFolds={5} sampling=""
      onEnabled={vi.fn()} onModelType={onModel} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/algorithm|算法/i), { target: { value: "prediction_ridge" } });
    expect(onModel).toHaveBeenCalledWith("prediction_ridge");
  });

  it("renders nothing interactive beyond the toggle when disabled", () => {
    render(<PredictionControls capabilities={caps} enabled={false}
      modelType="" cvFolds={5} sampling=""
      onEnabled={vi.fn()} onModelType={vi.fn()} onCvFolds={vi.fn()} onSampling={vi.fn()} />);
    expect(screen.queryByLabelText(/algorithm|算法/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runForm/PredictionControls.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `PredictionControls`**

```tsx
// frontend/src/runForm/PredictionControls.tsx
import type { Capabilities } from "../capabilities/types";

export function PredictionControls(props: {
  capabilities: Capabilities | undefined;
  enabled: boolean;
  modelType: string;
  cvFolds: number;
  sampling: string;
  onEnabled: (v: boolean) => void;
  onModelType: (v: string) => void;
  onCvFolds: (v: number) => void;
  onSampling: (v: string) => void;
}) {
  const models = props.capabilities?.prediction_models ?? [];
  const sampling = props.capabilities?.sampling_methods ?? [];
  if (models.length === 0) return null;
  return (
    <div className="ios-group" aria-label="Prediction settings">
      <label className="ios-row">
        <span>同时跑预测模型</span>
        <input type="checkbox" className="ios-switch" checked={props.enabled}
          onChange={(e) => props.onEnabled(e.target.checked)} />
      </label>
      {props.enabled && (
        <>
          <label className="ios-field">
            <span>算法 algorithm</span>
            <select value={props.modelType} onChange={(e) => props.onModelType(e.target.value)}>
              <option value="">(选择)</option>
              {models.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="ios-field">
            <span>交叉验证折数 cv_folds</span>
            <input type="number" min={2} max={20} value={props.cvFolds}
              onChange={(e) => props.onCvFolds(Number(e.target.value) || 5)} />
          </label>
          {sampling.length > 0 && (
            <label className="ios-field">
              <span>不平衡采样 sampling</span>
              <select value={props.sampling} onChange={(e) => props.onSampling(e.target.value)}>
                <option value="">(none)</option>
                {sampling.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </label>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/runForm/PredictionControls.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/PredictionControls.tsx frontend/src/runForm/PredictionControls.test.tsx
git commit -m "feat(frontend): PredictionControls (algorithm/cv/sampling)"
```

---

## Phase 10 — PredictionResultCard (Frontend)

### Task 10: Render the prediction_result artifact

**Files:**
- Create: `frontend/src/runResult/PredictionResultCard.tsx`
- Test: `frontend/src/runResult/PredictionResultCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/runResult/PredictionResultCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PredictionResultCard, type PredictionResultData } from "./PredictionResultCard";

const data: PredictionResultData = {
  schema_version: 1, model_id: "prediction_ridge_1", model_type: "prediction_ridge",
  engine: "scikit-learn", status: "completed", nobs: 60,
  input_columns: { y: "y", x: ["x"] }, cv_folds: 3, sampling_method: null,
  metrics: { test_r2: 0.92, test_rmse: 1.1, cv_r2_mean: 0.9 },
  warnings: ["Prediction results are not causal effects and are not regression inference."],
};

describe("PredictionResultCard", () => {
  it("renders metrics and the non-causal warning", () => {
    render(<PredictionResultCard result={data} />);
    expect(screen.getByText(/Ridge|prediction_ridge/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.92/)).toBeInTheDocument();
    expect(screen.getByText(/not causal/i)).toBeInTheDocument();
  });

  it("renders nothing when result is undefined", () => {
    const { container } = render(<PredictionResultCard result={undefined} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runResult/PredictionResultCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `PredictionResultCard`**

```tsx
// frontend/src/runResult/PredictionResultCard.tsx
export interface PredictionResultData {
  schema_version: number;
  model_id: string;
  model_type: string;
  engine: string;
  status: string;
  nobs: number;
  input_columns: { y: string; x: string[] };
  cv_folds: number;
  sampling_method: string | null;
  metrics: { test_r2: number | null; test_rmse: number | null; cv_r2_mean: number | null };
  warnings: string[];
}

function fmt(v: number | null): string {
  return v === null || v === undefined ? "—" : v.toFixed(3);
}

export function PredictionResultCard(props: { result: PredictionResultData | undefined }) {
  const r = props.result;
  if (!r) return null;
  return (
    <section className="ios-card prediction-result" aria-label="Prediction result">
      <div className="ios-card-title">🔮 预测 / ML — {r.model_type}</div>
      <ul className="ios-metric-list">
        <li><span>Test R²</span><strong>{fmt(r.metrics.test_r2)}</strong></li>
        <li><span>Test RMSE</span><strong>{fmt(r.metrics.test_rmse)}</strong></li>
        <li><span>CV R² (mean, {r.cv_folds}-fold)</span><strong>{fmt(r.metrics.cv_r2_mean)}</strong></li>
        {r.sampling_method && <li><span>Sampling</span><strong>{r.sampling_method}</strong></li>}
      </ul>
      {r.warnings.map((w) => <div key={w} className="ios-warning">⚠️ {w}</div>)}
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/runResult/PredictionResultCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Wire fetch in `runResult.tsx`**

Mirror the `ImputationSummary` pattern. Near the existing imputation fetch (`runResult.tsx` ~line 197), add a sibling effect: when the loaded artifacts list contains an item whose `artifact_id` starts with `prediction_` and ends `_1`, call `fetchArtifactJson<PredictionResultData>(...)` for it and store in state, then render `<PredictionResultCard result={predictionResult} />` alongside `<ImputationSummary />`.

```tsx
// imports
import { PredictionResultCard, type PredictionResultData } from "./runResult/PredictionResultCard";

// state (near imputationSummary state)
const [predictionResult, setPredictionResult] =
  useState<PredictionResultData | undefined>(undefined);

// effect (near the imputation_summary fetch effect) — find the prediction
// artifact id from the already-loaded artifacts list, then fetch its JSON.
// Use the same artifacts source the ImputationSummary effect uses.
// const predId = <artifacts>.find(a => /^prediction_.*_1$/.test(a.artifact_id))?.artifact_id;
// if (predId) fetchArtifactJson<PredictionResultData>(projectRoot, runId, predId)
//   .then(setPredictionResult).catch(() => setPredictionResult(undefined));

// render (next to <ImputationSummary ... />)
<PredictionResultCard result={predictionResult} />
```

> Read the existing ImputationSummary effect first and copy its exact artifacts-list source, `projectRoot`/`runId` access, and error handling. The artifact id is the prediction `model_id` (e.g. `prediction_ridge_1`).

- [ ] **Step 6: Run the runResult tests**

Run: `cd frontend && npx vitest run src/runResult`
Expected: PASS (existing + new). Fix any prop/import mismatch.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runResult/PredictionResultCard.tsx frontend/src/runResult/PredictionResultCard.test.tsx frontend/src/runResult.tsx
git commit -m "feat(frontend): render prediction_result (PredictionResultCard)"
```

---

## Phase 11 — App wiring + validation (Frontend)

### Task 11: Wire controls into the run form + client-side validation

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx` (append)

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/App.test.tsx` a focused validation test:

```tsx
import { describe, it, expect } from "vitest";
import { validatePanelPrediction } from "./App";

describe("validatePanelPrediction", () => {
  it("flags entity == time", () => {
    const err = validatePanelPrediction({
      modelType: "panel_ols", entity: "firm", time: "firm",
      isPanelData: true, predictionEnabled: false, predictionModelType: "",
    });
    expect(err).toMatch(/entity.*time|相同|同一列/i);
  });

  it("flags prediction enabled without algorithm", () => {
    const err = validatePanelPrediction({
      modelType: "auto", entity: "", time: "",
      isPanelData: false, predictionEnabled: true, predictionModelType: "",
    });
    expect(err).toMatch(/algorithm|算法/i);
  });

  it("flags panel selected with no columns and non-panel data", () => {
    const err = validatePanelPrediction({
      modelType: "panel_ols", entity: "", time: "",
      isPanelData: false, predictionEnabled: false, predictionModelType: "",
    });
    expect(err).toMatch(/panel|面板/i);
  });

  it("passes a valid panel config", () => {
    const err = validatePanelPrediction({
      modelType: "panel_ols", entity: "firm", time: "yr",
      isPanelData: true, predictionEnabled: false, predictionModelType: "",
    });
    expect(err).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t validatePanelPrediction`
Expected: FAIL — `validatePanelPrediction` not exported.

- [ ] **Step 3: Add the pure validator (exported) to App.tsx**

```tsx
// frontend/src/App.tsx (module scope, exported for unit testing)
export function validatePanelPrediction(s: {
  modelType: string;
  entity: string;
  time: string;
  isPanelData: boolean;
  predictionEnabled: boolean;
  predictionModelType: string;
}): string | null {
  if (s.modelType === "panel_ols") {
    if (s.entity && s.time && s.entity === s.time) {
      return "个体列与时间列不能是同一列 (entity == time)。";
    }
    if (!s.entity && !s.time && !s.isPanelData) {
      return "选择 Panel OLS 时请指定个体或时间列；该数据未被识别为面板数据。";
    }
  }
  if (s.predictionEnabled && !s.predictionModelType) {
    return "已开启预测，请选择算法 (algorithm)。";
  }
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx -t validatePanelPrediction`
Expected: PASS.

- [ ] **Step 5: Wire state + controls + submission into the run form**

In `App.tsx`'s `SubmitRoute` (where `modelType`, `imputationMethod`, `useCapabilities()` already live):

1. Add state:

```tsx
const [entityCol, setEntityCol] = useState("");
const [timeCol, setTimeCol] = useState("");
const [covariance, setCovariance] = useState("");
const [predictionEnabled, setPredictionEnabled] = useState(false);
const [predictionModelType, setPredictionModelType] = useState("");
const [predictionCvFolds, setPredictionCvFolds] = useState(5);
const [predictionSampling, setPredictionSampling] = useState("");
const [validationError, setValidationError] = useState<string | null>(null);
```

2. Render `<PanelControls .../>` (only when `modelType === "panel_ols"`) and `<PredictionControls .../>` near the existing `<ImputationControls .../>`. Source `columns` from the loaded `preview` (`preview?.columns?.map(c => c.name) ?? []`). Source `isPanelData` from preview/router if available, else `false`.

3. In the submit handler, before calling `runWorkflow`, run the validator and abort on error:

```tsx
const err = validatePanelPrediction({
  modelType, entity: entityCol, time: timeCol,
  isPanelData: false, // or derived from preview routing if present
  predictionEnabled, predictionModelType,
});
setValidationError(err);
if (err) return;
```

4. Pass the extra params to `runWorkflow`:

```tsx
await runWorkflow(projectRoot, mode, y, x, file, modelType, sheetName, transpose,
  imputationMethod ? JSON.stringify({ method: imputationMethod }) : undefined,
  {
    entityCol, timeCol, covariance,
    predictionModelType: predictionEnabled ? predictionModelType : "",
    predictionCvFolds: predictionEnabled ? predictionCvFolds : undefined,
    predictionSamplingMethod: predictionEnabled ? predictionSampling : "",
  });
```

5. Render `{validationError && <div className="ios-warning" role="alert">{validationError}</div>}` near the submit button.

> Read the current submit handler and `runWorkflow` call site first; keep the existing imputation arg exactly, only add the trailing `extra` object.

- [ ] **Step 6: Run the App tests**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (existing + new validator).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): wire panel+prediction controls + client validation"
```

---

## Phase 12 — iOS design tokens (Frontend)

### Task 12: iOS design tokens in styles.css + rollout

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add iOS design tokens and component classes**

Append to `frontend/src/styles.css`:

```css
/* ===== V1.5.4.2 iOS design tokens ===== */
:root {
  --ios-bg: #f2f2f7;
  --ios-card: #ffffff;
  --ios-radius: 14px;
  --ios-blue: #007aff;
  --ios-green: #34c759;
  --ios-sep: rgba(60,60,67,0.12);
  --ios-secondary: #8e8e93;
  --ios-font: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
}

.ios-group {
  background: var(--ios-card);
  border-radius: var(--ios-radius);
  padding: 12px 14px;
  margin: 12px 0;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  font-family: var(--ios-font);
}
.ios-group-label { font-size: 13px; color: var(--ios-secondary); margin-bottom: 8px; }
.ios-row, .ios-field {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0; border-bottom: 0.5px solid var(--ios-sep); gap: 12px;
}
.ios-row:last-child, .ios-field:last-child { border-bottom: none; }
.ios-field { flex-direction: column; align-items: stretch; }
.ios-field > span { font-size: 13px; color: var(--ios-secondary); margin-bottom: 4px; }
.ios-row-pair { display: flex; gap: 12px; }
.ios-row-pair .ios-field { flex: 1; }
.ios-hint { font-size: 12px; color: var(--ios-secondary); margin-top: 6px; }
.ios-switch { width: 44px; height: 26px; }
.ios-card {
  background: var(--ios-card); border-radius: var(--ios-radius);
  padding: 14px; margin: 12px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  font-family: var(--ios-font);
}
.ios-card-title { font-weight: 600; margin-bottom: 8px; }
.ios-metric-list { list-style: none; padding: 0; margin: 0; }
.ios-metric-list li {
  display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 0.5px solid var(--ios-sep);
}
.ios-metric-list li:last-child { border-bottom: none; }
.ios-warning {
  font-size: 13px; color: #8a6d00; background: rgba(255,204,0,0.12);
  border-radius: 10px; padding: 8px 10px; margin-top: 8px;
}
```

- [ ] **Step 2: Apply tokens to result/history surfaces (styling only)**

Add the page background and card adoption without restructuring markup — e.g. extend the existing `body`/`.panel`/`.result-panel` rules to use the token variables:

```css
body { background: var(--ios-bg); }
.panel, .result-panel { border-radius: var(--ios-radius); }
```

> Do NOT change the DOM structure of result/history pages — tokens only (radius, background, fonts, colors). Information layout stays identical (spec §4.6).

- [ ] **Step 3: Visual smoke**

Run the app and eyeball the run form + a completed run:
```bash
cd .worktrees/workbench-v1.5.4.2
PYTHONPATH=backend .venv/bin/python -m uvicorn workbench.api:app --port 8011 &
cd frontend && npm run dev
```
Confirm: PanelControls appear when Panel OLS selected; PredictionControls toggle works; a prediction run shows the PredictionResultCard; iOS cards render. Stop both servers after.

- [ ] **Step 4: Run full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat(frontend): iOS design tokens + run-form/result rollout"
```

---

## Phase 13 — Final gate

### Task 13: Full-suite gate + release notes

**Files:**
- Create: `docs/v1.5.4.2-release-notes.md`

- [ ] **Step 1: Backend full gate (full extras)**

Run: `.venv/bin/pytest -q`
Expected: all pass. Compare count to Task 0 baseline (should be baseline + new tests).

- [ ] **Step 2: Golden 0-drift confirmation**

Run: `.venv/bin/pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -v`
Expected: PASS, 7 goldens unchanged.

- [ ] **Step 3: No-extras lazy-import check**

Run (in a clean env or with extras absent if feasible): `.venv/bin/pytest -q -k "not panel and not prediction and not e2e_panel"`
Expected: optional-dep tests skip cleanly, others pass.

- [ ] **Step 4: Frontend full gate**

Run: `cd frontend && npx vitest run`
Expected: all pass.

- [ ] **Step 5: CLI smoke**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m workbench.cli run /tmp/wb-smoke examples/wage.csv wage --x education
```
Expected: completes without error (auto model path unaffected).

- [ ] **Step 6: Write release notes**

Create `docs/v1.5.4.2-release-notes.md` summarizing the 8 items, the backward-compatibility guarantee (omitting new params reproduces goldens), schema_version bump to 2, and the deferred IV/2SLS (→ V1.5.4.3).

- [ ] **Step 7: Commit + push branch**

```bash
git add docs/v1.5.4.2-release-notes.md
git commit -m "docs: V1.5.4.2 release notes"
git push -u origin workbench-v1.5.4.2
```

---

## Self-Review Notes

- **Spec coverage:** §3 items 1–8 map to Tasks 1 (panel cols), 2 (covariance), 3 (prediction run), 4 (API), 5 (manifest), 8 (PanelControls), 9 (PredictionControls), 10 (PredictionResultCard, required display), 11 (validation + wiring), 12 (iOS tokens incl. result/history rollout). §5 testing → Tasks 1–6 (BE) + per-component FE tests + Task 13 gate.
- **Backward compatibility:** every backend task includes a golden no-drift step; all new params default to current behavior.
- **Deferred (non-goals honored):** IV/2SLS not present; no auto-detection algorithm changes; result/history pages get tokens only.
- **Type consistency:** `RunExtraParams` (api.ts) keys ↔ `runWorkflow` form fields ↔ api.py Form names ↔ `ctx.artifacts["_..."]` keys all aligned (`entity_col`/`time_col`/`covariance`/`prediction_model_type`/`prediction_cv_folds`/`prediction_sampling_method`). `PredictionResultData` matches `prediction.py` result dict exactly.
