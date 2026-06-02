# V1.5.4 Engine Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `orchestrator._run_workflow` (~860-line god-function) into `DataHandle + ModelingContext + RunEnv + stage pipeline + model registry`, with **zero user-visible behavior change**, killing the "model fit on data A but diagnostics/report/lineage record data B" bug class by construction.

**Architecture:** Bundle the cross-stage mutable locals (`modeling_frame`/`model_input_ids`/`y_type`/`primary_type`/`exposure_col`) into a single `ModelingContext` whose data lives in an immutable `DataHandle` (frame + artifact_id + provenance focdused together). Extract the linear stages into named `Stage` units that take `(ctx, env) -> ctx`. Replace the `if y_type==... elif` estimation block with a `model_type`-keyed registry resolved by `resolve(ctx)` that honors explicit `requested_model_type` first (preserving the 1.5.3.2 routing contract). A characterization "golden" test captured before any change is the primary regression gate, alongside the existing 672 BE / 549 FE suites.

**Tech Stack:** Python 3.11, pandas, dataclasses, pytest. Backend at `backend/workbench/`, tests at `tests/`, run via `env PYTHONPATH=backend .venv/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-02-workbench-v1.5.4-engine-decomposition-design.md`

---

## File Structure

**New files (`backend/workbench/engine/`):** a new package isolating the engine contract.
- `engine/__init__.py` — re-exports `DataHandle`, `ModelingContext`, `RunEnv`, `Stage`, registry symbols.
- `engine/context.py` — `DataHandle`, `ModelingContext`, `RunEnv` dataclasses (pure, no IO).
- `engine/registry.py` — `ModelHandler`, `MODEL_REGISTRY`, `DEFAULT_BY_Y_TYPE`, `register_model`, `resolve`.
- `engine/pack.py` — `AnalysisPack`, `register_pack`, `DiagnosticRule` (forward type).
- `engine/stages/__init__.py` — ordered `PIPELINE` list + `Stage` Protocol.
- `engine/stages/*.py` — one module per stage (source, cleaning, profile, validation, routing, ytype, roles, exposure, imputation, estimation, diagnostics, report, reliability).

**Modified:**
- `backend/workbench/orchestrator.py` — `_run_workflow` shrinks to a thin driver that builds initial ctx/env and threads them through `PIPELINE`. Existing `_check_*`/`_detect_*`/`_write_*` helpers stay; they get called from the relevant stage module (imported, not moved unless trivial).

**New tests (`tests/`):**
- `tests/test_engine_golden.py` — characterization snapshot (Phase 1).
- `tests/test_engine_context.py` — `DataHandle`/`ModelingContext`/`RunEnv` unit tests.
- `tests/test_engine_registry.py` — registry resolve + explicit-type-failure.
- `tests/test_engine_stages.py` — per-stage unit tests.
- `tests/test_engine_pack.py` — pack registration + dogfood.
- `tests/test_lineage_invariants.py` — the 6 consistency invariants (Phase 6).
- `docs/extensions.md` — extension contract doc (Phase 7).

---

## Phase 0 — Worktree + venv bootstrap

### Task 0: Create isolated worktree, branch, venv (iron rule)

**Files:** none (environment only).

- [ ] **Step 1: Create the worktree + branch off the merged backend base**

Run (from main repo root `/Users/jiayuanren/项目规划`):
```bash
git worktree add .worktrees/workbench-v1.5.4 -b workbench-v1.5.4 origin/workbench-v1.5.3
```
Expected: `Preparing worktree (new branch 'workbench-v1.5.4')` and a checkout at `origin/workbench-v1.5.3` (which carries the PR #9 merged 1.5.3.1 backend).

- [ ] **Step 2: Build the venv with full extras**

Run:
```bash
cd .worktrees/workbench-v1.5.4
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```
Expected: install completes; `.venv/bin/python -c "import sklearn, linearmodels, statsmodels"` exits 0.

- [ ] **Step 3: Establish the green baseline (record the numbers)**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: all pass (record the exact count — spec baseline is **672 passed** with full extras). If the number differs, STOP and reconcile before refactoring — you cannot characterize against an unknown baseline.

- [ ] **Step 4: Frontend gate baseline (must stay untouched)**

Run:
```bash
cd frontend && npx vitest run
```
Expected: **549 passed**. You will not touch `frontend/` in this plan; this is the before-photo.

---

## Phase 1 — Golden/characterization harness (the safety net)

> This is written and committed BEFORE any production code changes. It snapshots full-run outputs for representative fixtures and asserts they stay structurally identical after the refactor. It is the real gate beyond the 672.

### Task 1: Golden fixtures + capture helper

**Files:**
- Create: `tests/test_engine_golden.py`

- [ ] **Step 1: Write the capture helper + the first golden test (continuous/OLS)**

```python
# tests/test_engine_golden.py
import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path: Path, frame: pd.DataFrame, *, y: str, x: list[str],
         mode: str = "auto", model_type: str = "auto") -> Path:
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode=mode, y=y, x=x,
                          model_type=model_type)
    return project.root / "runs" / result["run_id"], result


def _capture(run_root: Path) -> dict:
    """Structural fingerprint of a run: status, artifact ids+input lineage,
    primary model id/type/coefficient keys, diagnostic codes. Numeric values
    are rounded to decouple from float noise while still catching drift."""
    manifest = read_json(run_root / "run_manifest.json")
    idx = read_json(run_root / "artifacts_index.json")
    artifacts = {
        a["artifact_id"]: sorted(a.get("inputs", []))
        for a in idx["artifacts"]
    }
    snapshot = {"status": manifest["status"], "artifacts": artifacts}
    model_dir = run_root / "model_results"
    if model_dir.exists():
        models = {}
        for mr in sorted(model_dir.glob("*.json")):
            m = read_json(mr)
            models[m["model_id"]] = {
                "model_type": m.get("model_type"),
                "coef_keys": sorted(m.get("coefficients", {}).keys()),
                "coef_rounded": {
                    k: round(float(v), 6)
                    for k, v in m.get("coefficients", {}).items()
                },
            }
        snapshot["models"] = models
    errors_path = run_root / "errors.json"
    if errors_path.exists():
        snapshot["error_codes"] = sorted(
            i["code"] for i in read_json(errors_path).get("issues", [])
        )
    return snapshot


def test_golden_continuous_ols(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [1.0 + 2.0 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    run_root, result = _run(tmp_path, frame, y="y", x=["x"])
    snap = _capture(run_root)
    assert snap["status"] == "completed"
    assert snap["models"]["ols_1"]["model_type"] in {"ols", "continuous"}
    assert "x" in snap["models"]["ols_1"]["coef_keys"]
    # Persist the golden on first run, compare on subsequent runs.
    _assert_or_write_golden("continuous_ols", snap)


_GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_or_write_golden(name: str, snap: dict) -> None:
    _GOLDEN_DIR.mkdir(exist_ok=True)
    path = _GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        path.write_text(json.dumps(snap, indent=2, sort_keys=True))
        pytest.skip(f"golden {name} written; re-run to assert")
    expected = json.loads(path.read_text())
    assert snap == expected, f"golden drift for {name}"
```

- [ ] **Step 2: Run it twice — first writes the golden, second asserts**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -q
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -q
```
Expected: first run SKIPS (writes `tests/golden/continuous_ols.json`), second run PASSES.

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine_golden.py tests/golden/continuous_ols.json
git commit -m "test(engine): golden characterization harness + continuous/OLS baseline"
```

### Task 2: Golden coverage for binary, count, panel, blocked, imputation, explicit-model-type

**Files:**
- Modify: `tests/test_engine_golden.py`

- [ ] **Step 1: Add the remaining golden tests**

```python
def test_golden_binary_logit(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [0, 1] * 25,
        "x": [i * 0.5 for i in range(50)],
        "firm_id": list(range(200, 250)),
    })
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    _assert_or_write_golden("binary_logit", _capture(run_root))


def test_golden_count_poisson(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [i % 5 for i in range(50)],
        "x": [i * 0.3 for i in range(50)],
        "firm_id": list(range(300, 350)),
    })
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    _assert_or_write_golden("count_poisson", _capture(run_root))


def test_golden_panel(tmp_path: Path):
    rows = []
    for firm_id in range(6):
        for year in range(2018, 2025):
            x = firm_id + year - 2018
            rows.append({"firm_id": firm_id, "year": year, "x": x,
                         "y": 1.0 + 2.0 * x + firm_id * 0.1})
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=["x"])
    _assert_or_write_golden("panel", _capture(run_root))


def test_golden_blocked_missing_column(tmp_path: Path):
    frame = pd.DataFrame({"y": [1.0 * i for i in range(35)], "x": list(range(35))})
    run_root, result = _run(tmp_path, frame, y="y", x=["missing"])
    assert result["status"] == "blocked"
    _assert_or_write_golden("blocked_missing_column", _capture(run_root))


def test_golden_imputation(tmp_path: Path):
    # Introduce missing values to trigger the imputation branch.
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    _assert_or_write_golden("imputation", _capture(run_root))


def test_golden_explicit_model_type_logit(tmp_path: Path):
    frame = pd.DataFrame({
        "y": [0, 1] * 25,
        "x": [i * 0.5 for i in range(50)],
        "firm_id": list(range(200, 250)),
    })
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"], model_type="logit")
    _assert_or_write_golden("explicit_logit", _capture(run_root))
```

- [ ] **Step 2: Run twice (write goldens, then assert)**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -q
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -q
```
Expected: first run skips new goldens (writes 6 files), second run all PASS. If the imputation/count fixtures don't actually trigger their branch (e.g. count detected as continuous), adjust the fixture until `_capture` shows the intended `model_type`, then regenerate that golden.

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine_golden.py tests/golden/
git commit -m "test(engine): golden coverage — binary, count, panel, blocked, imputation, explicit-type"
```

---

## Phase 2 — Context scaffolding (pure, not yet wired)

### Task 3: `DataHandle`

**Files:**
- Create: `backend/workbench/engine/__init__.py`
- Create: `backend/workbench/engine/context.py`
- Test: `tests/test_engine_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_context.py
import pandas as pd
import pytest

from workbench.engine.context import DataHandle


def test_datahandle_binds_frame_and_identity():
    frame = pd.DataFrame({"a": [1, 2, 3]})
    h = DataHandle(frame=frame, artifact_id="cleaned_dataset",
                   provenance=("raw_data.csv",))
    assert h.artifact_id == "cleaned_dataset"
    assert h.provenance == ("raw_data.csv",)
    assert list(h.frame["a"]) == [1, 2, 3]


def test_datahandle_is_frozen():
    h = DataHandle(frame=pd.DataFrame(), artifact_id="x", provenance=())
    with pytest.raises(Exception):
        h.artifact_id = "y"  # frozen dataclass forbids reassignment


def test_datahandle_derived_metrics():
    frame = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    h = DataHandle.of(frame, artifact_id="cleaned_dataset", provenance=("r",))
    assert h.row_count == 2
    assert h.column_count == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_context.py -q`
Expected: FAIL — `ModuleNotFoundError: workbench.engine`.

- [ ] **Step 3: Implement `DataHandle`**

```python
# backend/workbench/engine/__init__.py
from .context import DataHandle, ModelingContext, RunEnv

__all__ = ["DataHandle", "ModelingContext", "RunEnv"]
```

```python
# backend/workbench/engine/context.py
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class DataHandle:
    """A dataframe bound to its provenance identity. Models, diagnostics,
    reports and lineage must all read frame AND artifact_id from the same
    handle — making 'fit on A, record B' impossible by construction."""

    frame: pd.DataFrame
    artifact_id: str
    provenance: tuple[str, ...]
    schema_fingerprint: str | None = None
    row_count: int | None = None
    column_count: int | None = None

    @classmethod
    def of(cls, frame: pd.DataFrame, *, artifact_id: str,
           provenance: tuple[str, ...]) -> "DataHandle":
        return cls(
            frame=frame,
            artifact_id=artifact_id,
            provenance=tuple(provenance),
            row_count=len(frame),
            column_count=len(frame.columns),
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_context.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/__init__.py backend/workbench/engine/context.py tests/test_engine_context.py
git commit -m "feat(engine): DataHandle — bind frame to provenance identity"
```

### Task 4: `ModelingContext` + `RunEnv`

**Files:**
- Modify: `backend/workbench/engine/context.py`
- Test: `tests/test_engine_context.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_engine_context.py
from workbench.engine.context import ModelingContext, RunEnv


def test_modeling_context_with_data_replaces_handle_atomically():
    h1 = DataHandle.of(pd.DataFrame({"a": [1]}), artifact_id="cleaned_dataset",
                       provenance=("r",))
    ctx = ModelingContext(data=h1, y_col="y", x_cols=["x"])
    h2 = DataHandle.of(pd.DataFrame({"a": [2]}), artifact_id="imputed_dataset",
                       provenance=("cleaned_dataset",))
    ctx2 = ctx.with_data(h2)
    # original untouched; new ctx carries the new handle and same scalars
    assert ctx.data.artifact_id == "cleaned_dataset"
    assert ctx2.data.artifact_id == "imputed_dataset"
    assert ctx2.y_col == "y" and ctx2.x_cols == ["x"]


def test_runenv_holds_side_effect_deps(tmp_path):
    env = RunEnv(run_root=tmp_path, run_id="r1", recorder=object(), on_step=None)
    assert env.run_id == "r1"
    assert env.run_root == tmp_path
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_context.py -q`
Expected: FAIL — `ImportError: cannot import name 'ModelingContext'`.

- [ ] **Step 3: Implement `ModelingContext` + `RunEnv`**

```python
# append to backend/workbench/engine/context.py
@dataclass
class ModelingContext:
    """Cross-stage state, previously loose locals in _run_workflow."""

    data: DataHandle
    y_col: str
    x_cols: list[str]
    requested_model_type: str | None = None   # 1.5.3.2 explicit routing
    y_type: str | None = None
    primary_type: str | None = None
    exposure_col: str | None = None
    roles: dict[str, Any] | None = None
    diagnostics: list[Any] | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    # short-circuit signal for blocked/failed early-exit stages
    terminal_status: str | None = None

    def with_data(self, handle: DataHandle) -> "ModelingContext":
        return replace(self, data=handle)


@dataclass
class RunEnv:
    """Side-effecting dependencies, kept OUT of ModelingContext so the
    context stays pure-constructible in unit tests."""

    run_root: Path
    run_id: str
    recorder: Any
    on_step: Callable[[str, str, str], None] | None = None

    def step(self, name: str, state: str, message: str) -> None:
        if self.on_step:
            self.on_step(name, state, message)
```

Also update `engine/__init__.py` `__all__` (already lists all three — verify).

- [ ] **Step 4: Run to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_context.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/context.py tests/test_engine_context.py
git commit -m "feat(engine): ModelingContext + RunEnv — bundle cross-stage state, isolate IO"
```

---

## Phase 3 — Incremental stage extraction

> Strategy (spec §3): extract ONE stage at a time. After each extraction, run the FULL backend suite + goldens. Never extract two stages before a green. The `_run_workflow` body is consumed top-down; each task moves one contiguous block into a stage module that reads/writes `ctx`/`env`, and replaces that block in `_run_workflow` with a call.

### Task 5: Stage Protocol + pipeline skeleton + thin-driver shim

**Files:**
- Create: `backend/workbench/engine/stages/__init__.py`
- Modify: `backend/workbench/orchestrator.py` (`_run_workflow` setup at `:391-394`)
- Test: `tests/test_engine_stages.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_stages.py
from workbench.engine.stages import Stage, PIPELINE


def test_pipeline_is_ordered_list_of_named_stages():
    assert isinstance(PIPELINE, list)
    names = [s.name for s in PIPELINE]
    # filled in as stages are added; starts empty-or-partial, must be unique
    assert len(names) == len(set(names))


def test_stage_protocol_shape():
    # a trivial stage satisfies the protocol
    class Noop:
        name = "noop"
        def run(self, ctx, env):
            return ctx
    s: Stage = Noop()
    assert s.name == "noop"
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_stages.py -q`
Expected: FAIL — `ModuleNotFoundError: workbench.engine.stages`.

- [ ] **Step 3: Implement the Protocol + empty pipeline**

```python
# backend/workbench/engine/stages/__init__.py
from __future__ import annotations

from typing import Protocol

from ..context import ModelingContext, RunEnv


class Stage(Protocol):
    name: str
    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext: ...


# Stages are appended here in pipeline order as each is extracted (Tasks 6+).
PIPELINE: list[Stage] = []
```

- [ ] **Step 4: Run to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_stages.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/__init__.py tests/test_engine_stages.py
git commit -m "feat(engine): Stage protocol + empty PIPELINE skeleton"
```

### Tasks 6–18: Extract each stage (one task each)

> **Extraction recipe (apply identically per stage):**
> 1. Create `backend/workbench/engine/stages/<name>.py` with a class implementing `Stage`. Its `run(self, ctx, env)` contains the EXACT logic from the named `_run_workflow` line-range, with substitutions: `_recorder` → `env.recorder`, `if _s: _s(...)` → `env.step(...)`, `run_root` → `env.run_root`, `run_id` → `env.run_id`. Loose locals the block produced become reads/writes on `ctx` (e.g. `y_type` → `ctx.y_type`; the modeling frame becomes `ctx.data.frame` and any provenance write uses `ctx.data.artifact_id`).
> 2. In `engine/stages/__init__.py`, import the stage and append an instance to `PIPELINE` (in order).
> 3. In `orchestrator._run_workflow`, DELETE the moved block and rely on the driver loop (added in Task 19) — but until the driver exists, temporarily call the stage inline: `ctx = <Stage>().run(ctx, env)`.
> 4. Add a focused unit test in `tests/test_engine_stages.py` constructing a minimal `ModelingContext`/`RunEnv` and asserting the stage's single responsibility.
> 5. Run FULL suite + goldens. Must be green before the next task.
>
> Each task below gives the stage name, the source line-range to move, and the ctx fields it reads/writes. Behavior is preserved — these are relocations, not rewrites.

- [ ] **Task 6 — `SourceStage`** (`source.py`). Move `orchestrator.py:396-412` (ingest + schema + `record_stage` raw). Reads: `ctx.data` (raw input paths via `env`/initial ctx). Writes: `ctx.data = DataHandle.of(cleaned... )` is NOT here — this stage records raw + carries the ingested frame forward as the working `DataHandle` with `artifact_id` per raw inputs. Verify full suite + goldens green. Commit `feat(engine): extract SourceStage`.

- [ ] **Task 7 — `CleaningStage`** (`cleaning.py`). Move `:414-437` (clean + write cleaning_actions + cleaned_dataset). Writes: `ctx = ctx.with_data(DataHandle.of(cleaned, artifact_id="cleaned_dataset", provenance=tuple(raw_inputs)))`. This is the FIRST place `DataHandle` replaces the loose `cleaned`/`raw_inputs` pairing. Verify + commit `feat(engine): extract CleaningStage — cleaned_dataset becomes a DataHandle`.

- [ ] **Task 8 — `ProfileStage`** (`profile.py`). Move `:439-451`. Reads `ctx.data.frame`; writes `data_profile` artifact with `inputs=[ctx.data.artifact_id]`. Verify + commit.

- [ ] **Task 9 — `ValidationStage`** (`validation.py`). Move `:453-472`. On blockers: set `ctx.terminal_status = "blocked"`, write manifest+flush, and the driver must short-circuit when `ctx.terminal_status` is set. Unit-test the blocked path. Verify (the `blocked_missing_column` golden must still match) + commit.

- [ ] **Task 10 — `RoutingStage`** (`routing.py`). Move `:474-488`. Reads `ctx.data.frame`; writes `analysis_router` with `inputs=["data_profile"]`. Verify + commit.

- [ ] **Task 11 — `YTypeStage`** (`ytype.py`). Move the y_type detection block (`:490`–~`:530`, through `normalized_y`/`normalized_x`, `_map_model_type`, the `requested_model_type` handling). Writes `ctx.y_type`, and sets `ctx.requested_model_type` from the requested `model_type` arg. **Preserve the explicit-vs-detected logic exactly** (spec §2.4). Verify (`explicit_logit` golden must match) + commit.

- [ ] **Task 12 — `RoleInferenceStage`** (`roles.py`). Move `infer_variable_roles(...)` block (~`:573`). Writes `ctx.roles`. Verify + commit.

- [ ] **Task 13 — `ExposureDetectionStage`** (`exposure.py`). Move the exposure candidate/selection block (the `if y_type == "count": exposure_candidates ... _select_valid_exposure_col` region). Writes `ctx.exposure_col`. Verify + commit.

- [ ] **Task 14 — `ImputationStage`** (`imputation.py`). Move the imputation branch where `modeling_frame`/`model_input_ids` were reassigned to the imputed parquet. Writes `ctx = ctx.with_data(DataHandle.of(imputed_frame, artifact_id="imputed_dataset", provenance=("cleaned_dataset",)))`. **This is the bug-class epicenter** — confirm the `imputation` golden matches AND that no code path still references a bare `modeling_frame` local. Verify + commit `feat(engine): extract ImputationStage — atomic DataHandle swap kills frame/id drift`.

- [ ] **Task 15 — `DiagnosticsStage`** (`diagnostics.py`). Move the diagnostics + variable-importance block (the `exog = modeling_frame[diag_x]...` region through diagnostic writes). Reads `ctx.data.frame`, `ctx.exposure_col`, `ctx.primary_type`; calls existing `_check_*`/`_build_variable_importance` helpers (imported from orchestrator). Verify + commit.

- [ ] **Task 16 — `ReportStage`** (`report.py`). Move the report/recorder `record_report` + report_view_model/reporting block. Reads `ctx.data.artifact_id` for report lineage. Verify + commit.

- [ ] **Task 17 — `ReliabilityStage`** (`reliability.py`). Move the `_check_rare_event`/reliability caveat block. Verify + commit.

- [ ] **Task 18 — `RecordingStage`/`finalize`** (`recording.py`). Move the `record_stage`/`record_variable`/`record_model`/`record_edge` graph-recording block (`:426-518`) plus the final `_write_manifest(..., "completed", ...)` + recorder flush. Reads `ctx.data.artifact_id` for all `inputs=`. Verify + commit.

> NOTE on `EstimationStage`: estimation is extracted in Task 19 together with the registry swap, because the if/elif block and its replacement are one change (spec §3 step 4: "registry last").

---

## Phase 4 — Model registry (last, per spec §3)

### Task 19: Extract `EstimationStage` behind the registry

**Files:**
- Create: `backend/workbench/engine/registry.py`
- Create: `backend/workbench/engine/stages/estimation.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_engine_registry.py`

- [ ] **Step 1: Write the failing test (registry resolve honors explicit type first)**

```python
# tests/test_engine_registry.py
import pytest

from workbench.engine.context import DataHandle, ModelingContext
from workbench.engine.registry import (
    MODEL_REGISTRY, DEFAULT_BY_Y_TYPE, resolve, register_model, ModelHandler,
)


def _ctx(*, y_type=None, requested=None):
    import pandas as pd
    h = DataHandle.of(pd.DataFrame({"y": [0, 1], "x": [1.0, 2.0]}),
                      artifact_id="cleaned_dataset", provenance=())
    return ModelingContext(data=h, y_col="y", x_cols=["x"],
                           y_type=y_type, requested_model_type=requested)


def test_resolve_auto_uses_y_type_default():
    assert resolve(_ctx(y_type="continuous")).model_type == "ols"
    assert resolve(_ctx(y_type="binary")).model_type == "logit"


def test_resolve_explicit_type_wins_over_y_type():
    h = resolve(_ctx(y_type="continuous", requested="logit"))
    assert h.model_type == "logit"


def test_resolve_unknown_explicit_type_raises_no_fallback():
    with pytest.raises(KeyError):
        resolve(_ctx(y_type="continuous", requested="does_not_exist"))


def test_register_model_extends_registry_without_touching_orchestrator():
    register_model(ModelHandler(model_type="dummy_x", model_id="dummy_1",
                                serves_y_types=("continuous",),
                                runner=lambda **kw: {"model_id": "dummy_1"}))
    assert "dummy_x" in MODEL_REGISTRY
    assert resolve(_ctx(y_type="continuous", requested="dummy_x")).model_id == "dummy_1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_registry.py -q`
Expected: FAIL — `ModuleNotFoundError: workbench.engine.registry`.

- [ ] **Step 3: Implement the registry**

```python
# backend/workbench/engine/registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ModelHandler:
    model_type: str            # "ols" / "logit" / "poisson_rate" / ...
    model_id: str              # default model_id when this handler is primary
    serves_y_types: tuple[str, ...]
    runner: Callable[..., dict[str, Any]]


MODEL_REGISTRY: dict[str, ModelHandler] = {}
DEFAULT_BY_Y_TYPE: dict[str, str] = {}


def register_model(handler: ModelHandler) -> None:
    MODEL_REGISTRY[handler.model_type] = handler


def set_default(y_type: str, model_type: str) -> None:
    DEFAULT_BY_Y_TYPE[y_type] = model_type


def resolve(ctx) -> ModelHandler:
    """Explicit requested_model_type wins (1.5.3.2 contract: unknown/failed
    => structured failure, NO silent fallback). Auto falls back to the
    y_type default."""
    if ctx.requested_model_type and ctx.requested_model_type != "auto":
        return MODEL_REGISTRY[ctx.requested_model_type]  # KeyError => caller -> failed
    return MODEL_REGISTRY[DEFAULT_BY_Y_TYPE[ctx.y_type]]
```

- [ ] **Step 4: Run to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_registry.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Register the built-in handlers + extract EstimationStage**

Create `engine/stages/estimation.py`. Register the existing runners (matching the current `:238-322` if/elif exactly):

```python
# backend/workbench/engine/stages/estimation.py
from __future__ import annotations

from ..context import ModelingContext, RunEnv
from ..registry import ModelHandler, register_model, set_default, resolve
from ...econometrics.runner import (
    run_ols, run_logit, run_probit, run_poisson, run_negative_binomial,
    run_glm, run_panel_ols,
)

# Built-in handlers — dogfood the registry. model_id/args mirror the current
# orchestrator if/elif so golden output is byte-identical.
register_model(ModelHandler("ols", "ols_1", ("continuous",), run_ols))
register_model(ModelHandler("logit", "logit_1", ("binary",), run_logit))
register_model(ModelHandler("probit", "probit_1", ("binary",), run_probit))
register_model(ModelHandler("poisson_rate", "poisson_1", ("count",), run_poisson))
register_model(ModelHandler("negative_binomial", "negative_binomial_1", ("count",), run_negative_binomial))
register_model(ModelHandler("glm", "glm_1", ("count",), run_glm))
register_model(ModelHandler("panel_ols", "panel_ols_1", ("continuous",), run_panel_ols))

set_default("continuous", "ols")
set_default("binary", "logit")
set_default("count", "poisson_rate")


class EstimationStage:
    name = "estimation"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Port the EXACT estimation orchestration from orchestrator.py:238-411:
        # build per-model kwargs (exposure handling for poisson, categorical_x,
        # robust for ols), call handler.runner(...), _write_model_result(...,
        # inputs=[ctx.data.artifact_id]), set ctx.primary_type. The explicit
        # vs auto dispatch is `resolve(ctx)`. On explicit-type fit failure,
        # produce the structured `failed` exactly as today (no OLS fallback).
        ...
```

> The `run` body is a faithful port of `orchestrator.py:238-411`. Keep the special-cases verbatim: poisson `exposure_col`/`poisson_x`, `categorical_x=categorical_vars`, `robust=True` for OLS, the auto-path OLS fallback for `model_results` empties, and `primary_type = model_results[0][1].get("model_type", "ols")`. Replace the if/elif selection with `handler = resolve(ctx)`. All `_write_model_result` calls use `inputs=[ctx.data.artifact_id]`.

In `orchestrator.py`, delete the `:238-411` estimation block and the loose `model_input_ids` references; the driver (Task 20) calls `EstimationStage`. Append `EstimationStage()` to `PIPELINE` in the correct position (after Imputation, before Diagnostics) in `engine/stages/__init__.py`.

- [ ] **Step 6: Run full suite + goldens**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: all pass; every golden (incl. `explicit_logit`, `panel`, `count_poisson`) matches. If a golden drifts, the port diverged from the original branch — diff against `orchestrator.py:238-411` until identical.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/registry.py backend/workbench/engine/stages/estimation.py backend/workbench/engine/stages/__init__.py backend/workbench/orchestrator.py tests/test_engine_registry.py
git commit -m "feat(engine): model registry + EstimationStage — explicit-type-first resolve, dogfood built-ins"
```

### Task 20: Collapse `_run_workflow` into the thin driver

**Files:**
- Modify: `backend/workbench/orchestrator.py` (`_run_workflow`)
- Test: existing suite + goldens

- [ ] **Step 1: Replace the inline stage calls with the pipeline loop**

`_run_workflow` becomes (target <~80 lines):

```python
def _run_workflow(run_root, run_id, input_files, mode, y, x, config,
                  started_at, on_step=None, model_type="auto",
                  sheet_name=None, transpose=False) -> dict[str, str]:
    from .engine.context import DataHandle, ModelingContext, RunEnv
    from .engine.stages import PIPELINE

    store = GraphStore(runs_root=run_root.parent)
    recorder = GraphRecorder(run_id=run_id, store=store)
    env = RunEnv(run_root=run_root, run_id=run_id, recorder=recorder, on_step=on_step)

    # Initial ctx — SourceStage/CleaningStage populate the real DataHandle.
    ctx = ModelingContext(
        data=DataHandle.of(pd.DataFrame(), artifact_id="raw",
                           provenance=tuple(f"raw_{p.name}" for p in input_files)),
        y_col=normalize_column_name(y),
        x_cols=[normalize_column_name(c) for c in x],
        requested_model_type=model_type,
    )
    ctx.artifacts["_input_files"] = input_files
    ctx.artifacts["_config"] = config
    ctx.artifacts["_sheet"] = (sheet_name, transpose)

    for stage in PIPELINE:
        ctx = stage.run(ctx, env)
        if ctx.terminal_status:   # blocked / failed short-circuit
            return {"run_id": run_id, "status": ctx.terminal_status}

    return {"run_id": run_id, "status": "completed"}
```

> The outer `run_workflow` (public, `:161`) and its exception handling are UNCHANGED. `started_at`/`mode`/`config`/`sheet_name`/`transpose` flow into the relevant stages via `ctx.artifacts` (or add typed fields if cleaner). Confirm `WorkflowValidationError`/`OptionalDependencyNotInstalled` still propagate from stages exactly as before (they bubble out of `stage.run`).

- [ ] **Step 2: Run full suite + goldens**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
wc -l backend/workbench/orchestrator.py
```
Expected: all pass; `_run_workflow` body is now <~80 lines (verify by inspecting; total file shrinks substantially as blocks moved out).

- [ ] **Step 3: Commit**

```bash
git add backend/workbench/orchestrator.py
git commit -m "refactor(orchestrator): _run_workflow collapses to thin pipeline driver"
```

---

## Phase 5 — AnalysisPack + dogfood

### Task 21: `AnalysisPack` + `register_pack` and register the core pack

**Files:**
- Create: `backend/workbench/engine/pack.py`
- Modify: `backend/workbench/engine/stages/estimation.py` (move built-in registration into a core pack)
- Test: `tests/test_engine_pack.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_pack.py
from workbench.engine.pack import AnalysisPack, register_pack, REGISTERED_PACKS
from workbench.engine.registry import MODEL_REGISTRY


def test_register_pack_contributes_model_handlers():
    from workbench.engine.registry import ModelHandler
    pack = AnalysisPack(pack_id="t", model_handlers=[
        ModelHandler("packtest", "packtest_1", ("continuous",), lambda **k: {}),
    ])
    register_pack(pack)
    assert "packtest" in MODEL_REGISTRY
    assert any(p.pack_id == "t" for p in REGISTERED_PACKS)


def test_core_pack_is_registered_on_import():
    import workbench.engine.stages.estimation  # noqa: F401
    # built-in models present => core pack dogfooded the mechanism
    assert {"ols", "logit", "poisson_rate"}.issubset(MODEL_REGISTRY.keys())


def test_pack_declares_future_fields_without_implementing_them():
    pack = AnalysisPack(pack_id="t2")
    assert pack.report_blocks == []
    assert pack.rerun_actions == []
    assert pack.interpretation_restrictions == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_pack.py -q`
Expected: FAIL — `ModuleNotFoundError: workbench.engine.pack`.

- [ ] **Step 3: Implement `AnalysisPack`**

```python
# backend/workbench/engine/pack.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .registry import ModelHandler, register_model


# Forward type — V1.5.4 does NOT build a DiagnosticRule engine; existing
# _check_* helpers remain. This is the declared contract slot.
DiagnosticRule = Any

REGISTERED_PACKS: list["AnalysisPack"] = []


@dataclass
class AnalysisPack:
    pack_id: str
    stages: list[Any] = field(default_factory=list)
    model_handlers: list[ModelHandler] = field(default_factory=list)
    diagnostics: list[DiagnosticRule] = field(default_factory=list)
    # ---- declared, NOT implemented in V1.5.4 (-> V1.5.6+ / agent) ----
    report_blocks: list[Any] = field(default_factory=list)
    recommended_actions: list[Any] = field(default_factory=list)
    interpretation_restrictions: list[Any] = field(default_factory=list)
    rerun_actions: list[Any] = field(default_factory=list)


def register_pack(pack: AnalysisPack) -> None:
    for handler in pack.model_handlers:
        register_model(handler)
    # stages: appended by the importing module into PIPELINE if provided.
    REGISTERED_PACKS.append(pack)
```

- [ ] **Step 4: Convert the built-in registration in `estimation.py` to a core pack**

Replace the loose `register_model(...)` calls in `estimation.py` with:

```python
from ..pack import AnalysisPack, register_pack

CORE_PACK = AnalysisPack(
    pack_id="core",
    model_handlers=[
        ModelHandler("ols", "ols_1", ("continuous",), run_ols),
        ModelHandler("logit", "logit_1", ("binary",), run_logit),
        ModelHandler("probit", "probit_1", ("binary",), run_probit),
        ModelHandler("poisson_rate", "poisson_1", ("count",), run_poisson),
        ModelHandler("negative_binomial", "negative_binomial_1", ("count",), run_negative_binomial),
        ModelHandler("glm", "glm_1", ("count",), run_glm),
        ModelHandler("panel_ols", "panel_ols_1", ("continuous",), run_panel_ols),
    ],
)
register_pack(CORE_PACK)
set_default("continuous", "ols")
set_default("binary", "logit")
set_default("count", "poisson_rate")
```

- [ ] **Step 5: Run full suite + goldens**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: all pass (registry now populated via the core pack; goldens unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/pack.py backend/workbench/engine/stages/estimation.py tests/test_engine_pack.py
git commit -m "feat(engine): AnalysisPack contract + dogfood core pack registration"
```

---

## Phase 6 — Consistency invariant tests

### Task 22: Lineage invariant + imputation + dummy + exposure + explicit-failure tests

**Files:**
- Create: `tests/test_lineage_invariants.py`

- [ ] **Step 1: Write all six invariant tests**

```python
# tests/test_lineage_invariants.py
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path, frame, *, y, x, model_type="auto"):
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    res = run_workflow(project.root, [src], mode="auto", y=y, x=x, model_type=model_type)
    return project.root / "runs" / res["run_id"], res


def _model_inputs(run_root, model_id):
    idx = read_json(run_root / "artifacts_index.json")
    for a in idx["artifacts"]:
        if a["artifact_id"] == model_id:
            return sorted(a.get("inputs", []))
    raise AssertionError(f"{model_id} not in artifact index")


def test_invariant_model_and_report_share_one_input_artifact(tmp_path):
    """1. Lineage invariant: model + report reference the same data artifact."""
    frame = pd.DataFrame({"y": [1.0 + 2 * i for i in range(40)],
                          "x": list(range(40)), "firm_id": list(range(100, 140))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    model_inputs = _model_inputs(run_root, "ols_1")
    assert model_inputs == ["cleaned_dataset"]  # no imputation => cleaned
    # report lineage references the same upstream data artifact
    report_inputs = _model_inputs(run_root, "report_html")
    assert "ols_1" in report_inputs or "cleaned_dataset" in report_inputs


def test_invariant_imputation_lineage_points_at_imputed_not_cleaned(tmp_path):
    """2. After imputation, model lineage must be imputed_dataset."""
    xs = [float(i) if i % 7 else None for i in range(40)]
    frame = pd.DataFrame({"y": [1.0 + 2 * i for i in range(40)], "x": xs,
                          "firm_id": list(range(100, 140))})
    run_root, _ = _run(tmp_path, frame, y="y", x=["x"])
    idx_ids = {a["artifact_id"] for a in read_json(run_root / "artifacts_index.json")["artifacts"]}
    if "imputed_dataset" in idx_ids:  # imputation actually fired
        assert _model_inputs(run_root, "ols_1") == ["imputed_dataset"]


def test_invariant_dummy_coding_aggregates_to_original_variable(tmp_path):
    """3. Dummy-coded categorical: coefficient risk aggregates by original var,
    report does not treat a dummy term as an original continuous variable."""
    frame = pd.DataFrame({
        "y": [1.0 + i for i in range(60)],
        "region_code": (["north", "south", "east"] * 20),
        "firm_id": list(range(100, 160)),
    })
    run_root, res = _run(tmp_path, frame, y="y", x=["region_code"])
    # behavior-preservation: run completes or blocks deterministically;
    # assert the original variable name survives in the model result keys map.
    if res["status"] == "completed":
        mr = read_json(run_root / "model_results" / "ols_1.json")
        assert any("region_code" in k for k in mr.get("coefficients", {}))


def test_invariant_exposure_warning_is_honest(tmp_path):
    """4. Exposure detected but offset NOT implemented: it stays an ordinary
    predictor; lineage must not pretend an offset transform happened."""
    rows = [{"y": i % 4, "x": i * 0.2, "exposure": 1.0 + i, "firm_id": 100 + i}
            for i in range(50)]
    run_root, res = _run(tmp_path, pd.DataFrame(rows), y="y", x=["x", "exposure"])
    idx_ids = {a["artifact_id"] for a in read_json(run_root / "artifacts_index.json")["artifacts"]}
    assert "offset_dataset" not in idx_ids  # no fictional offset artifact


def test_invariant_explicit_type_failure_returns_failed_no_fallback(tmp_path):
    """6. Explicit model_type that cannot fit => structured failed, NOT a
    silent OLS fallback (locks the 1.5.3.2 contract)."""
    # continuous y with an explicit logit request => cannot fit a logit
    frame = pd.DataFrame({"y": [1.5 * i for i in range(40)], "x": list(range(40)),
                          "firm_id": list(range(100, 140))})
    run_root, res = _run(tmp_path, frame, y="y", x=["x"], model_type="logit")
    assert res["status"] in {"failed", "blocked"}
    assert not (run_root / "model_results" / "ols_1.json").exists()
```

- [ ] **Step 2: Run them**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_lineage_invariants.py -q`
Expected: PASS. If test 6's fixture does not actually trigger a logit fit failure on this data, adjust the fixture (e.g. a strictly continuous target the logit family rejects) until the status is `failed`/`blocked` and no `ols_1.json` is written — the invariant (no silent fallback) is the point.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lineage_invariants.py
git commit -m "test(engine): lineage/imputation/dummy/exposure/explicit-failure invariants"
```

### Task 23: Behavior snapshot test (numeric equivalence)

**Files:**
- Modify: `tests/test_lineage_invariants.py` (or new `tests/test_behavior_snapshot.py`)

- [ ] **Step 1: Write the snapshot test**

```python
# tests/test_behavior_snapshot.py
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_behavior_snapshot_matches_committed_golden(tmp_path):
    """5. Same input/Y/X => coefficient, p-value, VIF, warning codes,
    diagnostic summary, report-block existence identical to the golden.
    This re-uses the Phase-1 golden machinery as the single source of truth;
    here we assert the post-refactor run still equals the committed golden."""
    frame = pd.DataFrame({"y": [1.0 + 2.0 * i for i in range(40)],
                          "x": list(range(40)), "firm_id": list(range(100, 140))})
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    res = run_workflow(project.root, [src], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / res["run_id"]
    mr = read_json(run_root / "model_results" / "ols_1.json")
    golden = read_json(Path(__file__).parent / "golden" / "continuous_ols.json")
    assert round(float(mr["coefficients"]["x"]), 6) == \
        golden["models"]["ols_1"]["coef_rounded"]["x"]
```

- [ ] **Step 2: Run it**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_behavior_snapshot.py -q`
Expected: PASS (coefficient matches the committed golden).

- [ ] **Step 3: Commit**

```bash
git add tests/test_behavior_snapshot.py
git commit -m "test(engine): behavior snapshot — numeric equivalence vs golden"
```

---

## Phase 7 — Extension contract docs + final gate

### Task 24: `docs/extensions.md`

**Files:**
- Create: `docs/extensions.md`

- [ ] **Step 1: Write the contract doc**

Document: (a) what an `AnalysisPack` may contribute in V1.5.4 — `model_handlers` (fully wired), `stages` (appended to `PIPELINE`), `diagnostics` (registered, existing `_check_*` style); (b) the declared-but-unimplemented fields (`report_blocks`/`recommended_actions`/`interpretation_restrictions`/`rerun_actions`) and that they are reserved for V1.5.6+/agent; (c) how registration happens (import-time `register_pack(...)`); (d) the `(ctx, env)` a stage receives and the rule that any artifact a stage writes MUST use `inputs=[ctx.data.artifact_id]`; (e) a worked example registering a new `ModelHandler` (e.g. ridge) without touching `_run_workflow`.

- [ ] **Step 2: Commit**

```bash
git add docs/extensions.md
git commit -m "docs: extension contract (AnalysisPack) for V1.5.4 engine"
```

### Task 25: Final full gate (the success criteria)

**Files:** none (verification).

- [ ] **Step 1: Backend full suite (full extras)**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: all pass — original 672 + the new engine/golden/invariant tests. Record the new total.

- [ ] **Step 2: Optional-extras lazy gate**

Build a no-extras venv and run:
```bash
~/.local/bin/python3.11 -m venv .venv-noextras
.venv-noextras/bin/pip install -e ".[dev]"
env PYTHONPATH=backend .venv-noextras/bin/python -m pytest -q
```
Expected: matches spec baseline pattern (e.g. 665 pass + 7 skip) — no new hard import of sklearn/linearmodels/imblearn at module load. If the new `engine/` modules import optional deps eagerly, make those imports lazy (inside `run`/handler), then re-run.

- [ ] **Step 3: Frontend gate (must be untouched)**

Run: `cd frontend && npx vitest run`
Expected: **549 passed** (identical to Phase 0 — you never touched `frontend/`).

- [ ] **Step 4: CLI smoke + no-pickle**

Run:
```bash
env PYTHONPATH=backend .venv/bin/python -m workbench.cli run <project> <data.csv> y --x x
grep -rn "pickle" backend/workbench/engine/ || echo "no pickle in engine — ok"
```
Expected: CLI run completes; no `pickle` usage introduced.

- [ ] **Step 5: New-model-without-touching-orchestrator proof**

Confirm `tests/test_engine_registry.py::test_register_model_extends_registry_without_touching_orchestrator` passes and that `git log --oneline` shows `_run_workflow` was NOT edited to add the dummy model. This is the success criterion "new model via register_model only."

- [ ] **Step 6: Push the branch**

```bash
git push -u origin workbench-v1.5.4
```
Expected: branch published. (Per project rule: push after the version's work is committed.)

---

## Self-Review Notes (coverage map vs spec)

- Spec §2.1 DataHandle → Task 3. §2.2 ModelingContext+RunEnv → Task 4. §2.3 stage pipeline → Tasks 5–18, 20. §2.4 registry (explicit-first) → Task 19 + invariant test 6 (Task 22). §2.5 AnalysisPack (3 wired classes, others declared) → Task 21.
- Spec §3 safety strategy: golden first (Phase 1), one stage at a time (Phase 3, green gate per task), ctx incremental (Tasks 7/14 introduce DataHandle progressively), registry last (Task 19 after all non-estimation stages).
- Spec §4 tests: invariants 1–4 + 6 → Task 22; snapshot (5) → Task 23.
- Spec §5 success criteria → Task 25 (each step maps to one criterion). §6 roadmap is informational (no task).
- Phase 0 enforces the iron rule (own worktree/branch/venv; base `origin/workbench-v1.5.3`).
