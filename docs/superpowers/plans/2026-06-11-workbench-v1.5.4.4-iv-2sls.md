# V1.5.4.4 — IV/2SLS Done Right + Debt Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the stranded `run_iv_2sls` estimator end-to-end to the GUI — explicit-only registration, fail-loud input validation, the standard IV diagnostic trio, a role-assignment input UI, a covariance selector, and a `rerun_actions` failure recovery — plus clear the V1.5.4.3 debt, with zero user-facing behavior change for non-IV runs.

**Architecture:** `iv_2sls` registers into `CORE_PACK` as an explicit-only `ModelHandler` (in `MODEL_REGISTRY`, NOT in `DEFAULT_BY_Y_TYPE`, so it is never auto-selected). A `_fit_iv_2sls(ctx, env)` adapter validates the spec then calls `run_iv_2sls`. The fitted IV object lands in `ctx.artifacts["_fitted_models"]["iv_2sls_1"]` via the existing EstimationStage loop; `DiagnosticsStage` gains an `iv_2sls`-guarded branch that reads it and writes an `iv_diagnostics` artifact. Because no existing run requests `iv_2sls`, all changes are inert in production → golden 0-drift. The frontend reveals IV controls only when `iv_2sls` is selected.

**Tech Stack:** Python 3.11, pytest, dataclasses, linearmodels (IV2SLS); React + TypeScript + Vitest + tsc; bash.

**Spec:** `docs/superpowers/specs/2026-06-11-workbench-v1.5.4.4-iv-2sls-design.md`

---

## File Structure

**Backend (modify):**
- `backend/workbench/engine/stages/estimation.py` — `_fit_iv_2sls` adapter + `ModelHandler("iv_2sls", ...)` in `CORE_PACK.model_handlers` (NOT in `defaults_by_y_type`); IV pack `rerun_actions`.
- `backend/workbench/engine/iv_spec.py` (create) — pure `validate_iv_spec(...)` helper + `IVSpecError`.
- `backend/workbench/engine/stages/diagnostics.py` — `iv_2sls`-guarded IV diagnostics branch writing `iv_diagnostics` artifact.
- `backend/workbench/engine/iv_diagnostics.py` (create) — pure `build_iv_diagnostics(fitted, n_endog, n_instruments)` → dict with stats + verdicts.
- `backend/workbench/engine/pack.py` — `register_pack` raises on duplicate `RerunAction.key` (debt item).
- `backend/workbench/engine/capabilities.py` — add `iv_2sls` to the model-type set.
- `backend/workbench/api.py` — `iv_endog` / `iv_instruments` Form fields threaded through `_bg_run` → `_run_workflow` → `ctx.artifacts`.
- `backend/workbench/orchestrator.py` — thread `iv_endog`/`iv_instruments` into `_run_workflow` → ctx.artifacts (minimal dispatch-seam touch).

**Backend (tests):**
- `tests/test_iv_spec.py`, `tests/test_iv_diagnostics.py`, `tests/test_engine_iv.py`, `tests/test_pack_rerun_dedup.py`, plus golden additions.

**Frontend:**
- `frontend/src/runForm/IVControls.tsx` (create) + `frontend/src/runForm/IVControls.test.tsx`.
- `frontend/src/runForm/RunForm.tsx` — render `<IVControls>` when `model_type === "iv_2sls"`; thread `iv_endog`/`iv_instruments` into `runWorkflow`.
- `frontend/src/api.ts` — extend `RunExtraParams` with `iv_endog`/`iv_instruments`.
- `frontend/src/runResult/IVDiagnosticsCard.tsx` (create) + test; rendered from `runResult.tsx`.
- `frontend/src/capabilities/types.ts` — type addition if manifest shape changes.
- `frontend/tsconfig.json` — root-config coverage (debt item).

**Tooling / docs:**
- `examples/iv_<name>/` example dataset + `docs/iv-2sls-howto.md`.
- `tests/test_pack_contract.py` / `test_pack_stage_insertion.py` / `test_pack_rerun_actions.py` — `REGISTERED_PACKS` restore fixture (debt item).
- `docs/v1.5.4.4-release-notes.md`.

---

## Phase 0 — Worktree Setup

### Task 0: Create branch, worktree, environments

**Files:** none (environment only)

- [ ] **Step 1: Create branch + worktree from main head**

```bash
cd "/Users/jiayuanren/项目规划"
git fetch origin
git worktree add -b workbench-v1.5.4.4 .worktrees/workbench-v1.5.4.4 main
cd .worktrees/workbench-v1.5.4.4
```

- [ ] **Step 2: Build backend venv with full extras** (IV needs the `panel` extra → linearmodels)

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```

- [ ] **Step 3: Install frontend deps**

```bash
cd frontend && npm install && cd ..
```

- [ ] **Step 4: Baseline gate (record green starting point)**

```bash
./scripts/gate.sh
```
Expected: GATE PASSED — backend 761 passed, frontend 582 passed, golden 0-drift, tsc clean. Record the counts — the no-regression baseline.

- [ ] **Step 5: Commit (worktree marker)**

```bash
git commit --allow-empty -m "chore: start V1.5.4.4 worktree (IV/2SLS done right)"
```

---

## Phase A — IV spec validation (fail-loud, no estimation yet)

### Task 1: `validate_iv_spec` pure helper

**Files:**
- Create: `backend/workbench/engine/iv_spec.py`
- Test: `tests/test_iv_spec.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_iv_spec.py
import pytest

from workbench.engine.iv_spec import validate_iv_spec, IVSpecError


def test_valid_spec_passes():
    # 1 endog, 2 instruments (over-identified), no overlap
    validate_iv_spec(y="wage", exog=["age"], endog=["educ"],
                     instruments=["dist", "momeduc"])


def test_empty_endog_raises():
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=["age"], endog=[], instruments=["dist"])
    assert "endogenous" in str(exc.value).lower()


def test_empty_instruments_raises():
    with pytest.raises(IVSpecError):
        validate_iv_spec(y="wage", exog=["age"], endog=["educ"], instruments=[])


def test_order_condition_violation_raises():
    # 2 endog, 1 instrument => under-identified
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=[], endog=["educ", "exp"],
                         instruments=["dist"])
    assert "identif" in str(exc.value).lower()


def test_overlap_between_buckets_raises():
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=["educ"], endog=["educ"],
                         instruments=["dist"])
    assert "educ" in str(exc.value)


def test_y_in_a_bucket_raises():
    with pytest.raises(IVSpecError):
        validate_iv_spec(y="wage", exog=["wage"], endog=["educ"],
                         instruments=["dist"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_iv_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workbench.engine.iv_spec'`.

- [ ] **Step 3: Implement `iv_spec.py`**

```python
# backend/workbench/engine/iv_spec.py
from __future__ import annotations


class IVSpecError(ValueError):
    """Raised when an IV/2SLS specification is invalid. Carries an
    IV_* prefixed message so the estimation failure path surfaces it
    as a structured MODEL_FIT_FAILED with a 'Switch to OLS' recovery."""


def validate_iv_spec(
    y: str,
    exog: list[str],
    endog: list[str],
    instruments: list[str],
) -> None:
    if not endog:
        raise IVSpecError(
            "IV_SPEC_INCOMPLETE: at least one endogenous regressor is required."
        )
    if not instruments:
        raise IVSpecError(
            "IV_SPEC_INCOMPLETE: at least one instrument is required."
        )
    if len(instruments) < len(endog):
        raise IVSpecError(
            "IV_UNDER_IDENTIFIED: the order condition requires "
            f"#instruments ({len(instruments)}) >= #endogenous ({len(endog)})."
        )
    buckets = {"exog": exog, "endog": endog, "instruments": instruments}
    seen: dict[str, str] = {}
    for role, cols in buckets.items():
        for col in cols:
            if col == y:
                raise IVSpecError(
                    f"IV_INVALID_PARTITION: '{col}' is the dependent variable "
                    f"and cannot also be in {role}."
                )
            if col in seen:
                raise IVSpecError(
                    f"IV_INVALID_PARTITION: '{col}' appears in both "
                    f"{seen[col]} and {role}; each column has exactly one role."
                )
            seen[col] = role
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_iv_spec.py -v`
Expected: PASS (6).

- [ ] **Step 5: Golden no-drift (pure helper, nothing wired yet — sanity only)**

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py -q`
Expected: PASS, 0 drift.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/iv_spec.py tests/test_iv_spec.py
git commit -m "feat(iv): fail-loud validate_iv_spec (order condition + partition)"
```

---

## Phase B — IV backend wiring

### Task 2: `_fit_iv_2sls` adapter + explicit-only registration + param threading

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py`
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_engine_iv.py`

- [ ] **Step 1: Write the failing test** (drives a full IV run end-to-end through the engine, asserting the estimator receives the right kwargs)

```python
# tests/test_engine_iv.py
import pandas as pd
import numpy as np
import pytest

from workbench.engine.context import ModelingContext  # adjust import to actual harness
from workbench import orchestrator as orch


@pytest.fixture
def iv_frame():
    rng = np.random.default_rng(0)
    n = 400
    z = rng.normal(size=n)            # instrument
    u = rng.normal(size=n)
    educ = 0.8 * z + u + rng.normal(size=n) * 0.3   # endogenous
    age = rng.normal(size=n)          # exogenous control
    wage = 1.0 + 0.5 * educ + 0.2 * age + u + rng.normal(size=n) * 0.5
    return pd.DataFrame({"wage": wage, "educ": educ, "age": age, "dist": z})


def test_iv_run_calls_estimator_with_buckets(monkeypatch, iv_frame, tmp_path):
    captured = {}
    real = orch.run_iv_2sls

    def spy(frame, *, y, exog, endog, instruments, model_id, covariance):
        captured.update(dict(y=y, exog=exog, endog=endog,
                             instruments=instruments, covariance=covariance))
        return real(frame, y=y, exog=exog, endog=endog,
                    instruments=instruments, model_id=model_id, covariance=covariance)

    monkeypatch.setattr(orch, "run_iv_2sls", spy)

    # Run via the standard workflow harness (mirror the pattern other
    # engine tests use: create_project -> write csv -> run_workflow with
    # model_type="iv_2sls", iv_endog/iv_instruments, x as exog).
    # ... harness setup writes iv_frame to a csv under a temp project ...
    # result manifest status must be "completed".
    assert captured["endog"] == ["educ"]
    assert captured["instruments"] == ["dist"]
    assert "age" in captured["exog"]
    assert captured["covariance"] == "robust"
```

> Implementer note: fill the harness body to match the existing engine-test convention (see `tests/test_engine_*` for `create_project` / `run_workflow(... model_type=, x=, ...)`). The assertions on `captured` are the load-bearing part (G0-3: deleting the wiring makes them red).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine_iv.py -v`
Expected: FAIL — `iv_2sls` not a registered model type (KeyError in `resolve`).

- [ ] **Step 3: Add the adapter + handler in `estimation.py`**

Add the adapter near the other `_fit_*` adapters:

```python
def _fit_iv_2sls(ctx, env):
    from ..iv_spec import validate_iv_spec
    endog = ctx.artifacts.get("_iv_endog") or []
    instruments = ctx.artifacts.get("_iv_instruments") or []
    exog = ctx.artifacts["_normalized_x"]
    y = ctx.artifacts["_normalized_y"]
    validate_iv_spec(y=y, exog=exog, endog=endog, instruments=instruments)
    return _orch().run_iv_2sls(
        ctx.data.frame,
        y=y,
        exog=exog,
        endog=endog,
        instruments=instruments,
        model_id="iv_2sls_1",
        covariance=ctx.artifacts.get("_covariance") or "robust",
    )
```

Add to `CORE_PACK.model_handlers` (NOT to `defaults_by_y_type` — explicit-only):

```python
        ModelHandler("iv_2sls", "iv_2sls_1", ("continuous",), _fit_iv_2sls),
```

> `validate_iv_spec` raises `IVSpecError` (a `ValueError` subclass), so a bad spec rides the existing `except ValueError` in `EstimationStage.run` → structured `MODEL_FIT_FAILED` + `actions_for_model_fit_failure`. No new failure plumbing needed.

- [ ] **Step 4: Thread `_iv_endog` / `_iv_instruments` from request into ctx.artifacts**

In `backend/workbench/orchestrator.py` `_run_workflow`, accept `iv_endog: list[str] | None = None`, `iv_instruments: list[str] | None = None`, normalize them with the same `normalize_column_name` helper panel entity/time uses, and set:

```python
        ctx.artifacts["_iv_endog"] = normalized_iv_endog
        ctx.artifacts["_iv_instruments"] = normalized_iv_instruments
```

In `backend/workbench/api.py` add Form fields and thread them:

```python
    iv_endog: str = Form(""),          # JSON array of column names
    iv_instruments: str = Form(""),    # JSON array of column names
```
Parse the JSON arrays (mirror how `imputation` JSON is parsed), pass through `_bg_run` → `_run_workflow(..., iv_endog=..., iv_instruments=...)`.

- [ ] **Step 5: Run the IV test + full suite**

Run: `.venv/bin/python -m pytest tests/test_engine_iv.py -v`
Expected: PASS — captured kwargs correct, manifest `completed`.
Run: `.venv/bin/python -m pytest -q`
Expected: 761 + new tests pass.

- [ ] **Step 6: Golden no-drift (iv_2sls never auto-selected → existing runs unchanged)**

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_engine_pack.py tests/test_engine_registry.py -q`
Expected: PASS, 0 drift. Add an assertion (in `test_engine_registry.py` or `test_engine_iv.py`) that `"iv_2sls" not in DEFAULT_BY_Y_TYPE` (explicit-only invariant — goes red if someone makes it a default).

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/stages/estimation.py backend/workbench/api.py backend/workbench/orchestrator.py tests/test_engine_iv.py
git commit -m "feat(iv): register iv_2sls explicit-only + thread endog/instruments"
```

---

### Task 3: IV characterization golden

**Files:**
- Modify: `tests/test_engine_golden.py` (+ `tests/golden/iv_2sls.json`)

- [ ] **Step 1: Add an IV golden capture**

Add a fixed-seed IV run (reuse the Task 2 `iv_frame` recipe with a pinned seed) to the golden suite so IV's own output is locked. Follow the existing `_capture` convention (coefficients via `v["estimate"]`). Write the snapshot to `tests/golden/iv_2sls.json`.

- [ ] **Step 2: Run to generate + verify stable**

Run twice: `.venv/bin/python -m pytest tests/test_engine_golden.py -q`
Expected: PASS both times (deterministic).

- [ ] **Step 3: Commit**

```bash
git add tests/test_engine_golden.py tests/golden/iv_2sls.json
git commit -m "test(iv): characterization golden for iv_2sls"
```

---

## Phase C — IV diagnostic trio

### Task 4: `build_iv_diagnostics` pure helper

**Files:**
- Create: `backend/workbench/engine/iv_diagnostics.py`
- Test: `tests/test_iv_diagnostics.py`

- [ ] **Step 1: Write the failing test** (uses a real fitted IV2SLS from a strong-instrument fixture so the verdicts are deterministic-ish; assert structure + verdict direction, tolerant on exact stat values)

```python
# tests/test_iv_diagnostics.py
import numpy as np, pandas as pd
from workbench import orchestrator as orch
from workbench.engine.iv_diagnostics import build_iv_diagnostics


def _fitted(n_instruments):
    rng = np.random.default_rng(1)
    n = 800
    z1 = rng.normal(size=n); z2 = rng.normal(size=n)
    u = rng.normal(size=n)
    educ = 1.5 * z1 + (0.0 if n_instruments == 1 else 1.5 * z2) + u
    wage = 1 + 0.5 * educ + u + rng.normal(size=n) * 0.3
    df = pd.DataFrame({"wage": wage, "educ": educ, "z1": z1, "z2": z2})
    instruments = ["z1"] if n_instruments == 1 else ["z1", "z2"]
    _, fitted = orch.run_iv_2sls(df, y="wage", exog=[], endog=["educ"],
                                 instruments=instruments, model_id="iv_2sls_1")
    return fitted, 1, n_instruments


def test_overidentified_includes_sargan():
    fitted, n_endog, n_instr = _fitted(2)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "over"
    assert d["weak_instruments"]["verdict"] in {"strong", "weak"}
    assert "first_stage_f" in d["weak_instruments"]
    assert d["endogeneity"]["test"] == "wu_hausman"
    assert d["overidentification"]["applicable"] is True
    assert "statistic" in d["overidentification"]


def test_just_identified_overid_not_applicable():
    fitted, n_endog, n_instr = _fitted(1)
    d = build_iv_diagnostics(fitted, n_endog, n_instr)
    assert d["identification"] == "just"
    assert d["overidentification"]["applicable"] is False
    assert "not applicable" in d["overidentification"]["verdict"].lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_iv_diagnostics.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `iv_diagnostics.py`**

```python
# backend/workbench/engine/iv_diagnostics.py
from __future__ import annotations
from typing import Any

_WEAK_F_THRESHOLD = 10.0  # Staiger-Stock rule of thumb (NOT a guarantee)


def build_iv_diagnostics(fitted: Any, n_endog: int, n_instruments: int) -> dict:
    identification = (
        "under" if n_instruments < n_endog
        else "just" if n_instruments == n_endog
        else "over"
    )

    # Weak instruments: per-endog first-stage F (min across endog).
    fs = fitted.first_stage.diagnostics  # DataFrame indexed by endog name
    f_col = "f.stat" if "f.stat" in fs.columns else fs.columns[0]
    min_f = float(fs[f_col].min())
    weak = {
        "first_stage_f": min_f,
        "threshold": _WEAK_F_THRESHOLD,
        "verdict": "strong" if min_f > _WEAK_F_THRESHOLD else "weak",
        "message": (
            "Instruments are strong (first-stage F > 10, rule of thumb)."
            if min_f > _WEAK_F_THRESHOLD else
            "Instruments appear weak (first-stage F <= 10); interpret with caution."
        ),
    }

    wh = fitted.wu_hausman()
    p_wh = float(wh.pval)
    endogeneity = {
        "test": "wu_hausman",
        "statistic": float(wh.stat),
        "pvalue": p_wh,
        "verdict": "endogenous" if p_wh < 0.05 else "exogenous",
        "message": (
            "Endogeneity confirmed (p < 0.05); IV is warranted."
            if p_wh < 0.05 else
            "No endogeneity detected (p >= 0.05); OLS is consistent and more efficient."
        ),
    }

    if identification == "over":
        s = fitted.sargan
        p_s = float(s.pval)
        overid = {
            "applicable": True,
            "test": "sargan",
            "statistic": float(s.stat),
            "pvalue": p_s,
            "verdict": "suspect" if p_s < 0.05 else "not_rejected",
            "message": (
                "Instrument exogeneity rejected (p < 0.05); instruments suspect."
                if p_s < 0.05 else
                "Instrument exogeneity not rejected (p >= 0.05)."
            ),
        }
    else:
        overid = {
            "applicable": False,
            "verdict": "Not applicable (just-identified).",
        }

    return {
        "identification": identification,
        "weak_instruments": weak,
        "endogeneity": endogeneity,
        "overidentification": overid,
    }
```

> Implementer note: confirm the linearmodels attribute names against the installed version (`fitted.first_stage.diagnostics`, `fitted.wu_hausman()`, `fitted.sargan`). If an attribute differs, adapt the accessor but keep the returned dict shape — the tests and the frontend depend on the shape, not the linearmodels API.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_iv_diagnostics.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/iv_diagnostics.py tests/test_iv_diagnostics.py
git commit -m "feat(iv): build_iv_diagnostics trio (weak/endogeneity/overid)"
```

---

### Task 5: Wire IV diagnostics into `DiagnosticsStage`

**Files:**
- Modify: `backend/workbench/engine/stages/diagnostics.py`
- Test: `tests/test_engine_iv.py` (extend)

- [ ] **Step 1: Write the failing test** (a completed IV run must produce an `iv_diagnostics` artifact; a non-IV run must NOT)

```python
def test_iv_run_writes_iv_diagnostics_artifact(iv_frame, tmp_path):
    # run iv_2sls via harness; load run artifacts
    # assert an "iv_diagnostics" artifact exists with keys identification/
    # weak_instruments/endogeneity/overidentification
    ...

def test_non_iv_run_has_no_iv_diagnostics(tmp_path):
    # run a plain ols/auto run; assert NO iv_diagnostics artifact (0-drift)
    ...
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_engine_iv.py -k iv_diagnostics -v`
Expected: FAIL — no such artifact.

- [ ] **Step 3: Add the guarded branch in `DiagnosticsStage.run`**

After the existing reads (`fitted_models`, `model_type`, `run_root`, `register_artifact`/`write_json` import), add:

```python
        if model_type == "iv_2sls":
            from ..iv_diagnostics import build_iv_diagnostics
            fitted = fitted_models.get("iv_2sls_1")
            if fitted is not None:
                n_endog = len(ctx.artifacts.get("_iv_endog") or [])
                n_instr = len(ctx.artifacts.get("_iv_instruments") or [])
                iv_diag = build_iv_diagnostics(fitted, n_endog, n_instr)
                write_json(run_root / "iv_diagnostics.json", iv_diag)
                register_artifact(
                    recorder, "iv_diagnostics", parents=["iv_2sls_1"],
                )  # match the existing register_artifact signature in this file
```

> Match the exact `register_artifact`/`write_json` call shape already used in `DiagnosticsStage` (read the surrounding lines). The branch only fires for `iv_2sls`, so all current goldens skip it → 0-drift.

- [ ] **Step 4: Run the tests + golden**

Run: `.venv/bin/python -m pytest tests/test_engine_iv.py -q`
Expected: PASS (artifact present for IV, absent for non-IV).
Run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q`
Expected: PASS, 0 drift.

- [ ] **Step 5: Reverse-check (G0-3)**

Comment out the `write_json(run_root / "iv_diagnostics.json", ...)` line; re-run `test_iv_run_writes_iv_diagnostics_artifact` — it MUST fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/stages/diagnostics.py tests/test_engine_iv.py
git commit -m "feat(iv): write iv_diagnostics artifact (guarded on iv_2sls)"
```

---

## Phase D — Capabilities sync + frontend

### Task 6: Capabilities manifest 4-way sync for `iv_2sls`

**Files:**
- Modify: `backend/workbench/engine/capabilities.py`
- Modify: contract schema + sample (the file the V1.5.4.2 G0-5 sync touched — locate via `grep -rl prediction_models tests/contracts`)
- Modify: `frontend/src/capabilities/types.ts` (only if the manifest shape changes)
- Test: the existing capabilities drift-guard test

- [ ] **Step 1: Write/extend the failing drift-guard test**

Extend the manifest drift-guard test to assert `iv_2sls` is in `model_types` and that the manifest's model-type set equals the backend's supported set (so dropping the registration goes red).

Run: `.venv/bin/python -m pytest tests/test_engine_capabilities.py -v` (or the actual capabilities test file)
Expected: FAIL — `iv_2sls` missing from manifest.

- [ ] **Step 2: Add `iv_2sls` to `build_capabilities()`**

Add `iv_2sls` to the model-type list the manifest emits (mirror how `panel_ols`/prediction entries are emitted). If the frontend needs to know IV requires endog/instruments to drive the role UI, include a minimal flag (e.g. an entry field `requires: ["endog","instruments"]`); otherwise keep it a plain model-type entry and let the frontend special-case `iv_2sls`.

- [ ] **Step 3: Run the drift-guard + update contract schema/sample**

Run the capabilities test; update the contract schema + sample additively (mirror the V1.5.4.2 schema_version bump precedent — bump only if the shape changed). Re-run until green.

- [ ] **Step 4: Frontend type + tsc**

If the manifest shape changed, update `Capabilities` in `frontend/src/capabilities/types.ts`. Run `cd frontend && npx tsc --noEmit` — expect 0 errors.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/capabilities.py tests/ frontend/src/capabilities/types.ts
git commit -m "feat(iv): add iv_2sls to capabilities manifest (4-way sync)"
```

---

### Task 7: `IVControls` role-assignment component

**Files:**
- Create: `frontend/src/runForm/IVControls.tsx`
- Test: `frontend/src/runForm/IVControls.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/runForm/IVControls.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { IVControls } from "./IVControls";

const cols = ["age", "educ", "dist", "momeduc"];

describe("IVControls", () => {
  it("reports endog/instruments and identification status via onChange", () => {
    const onChange = vi.fn();
    render(<IVControls columns={cols} value={{ endog: [], instruments: [] }} onChange={onChange} />);
    // assign educ -> endogenous, dist -> instrument (UI-specific queries)
    // expect onChange last call to carry endog:["educ"], instruments:["dist"]
    // expect a "just-identified" badge to be visible
    expect(screen.getByText(/identified/i)).toBeInTheDocument();
  });

  it("shows under-identified when instruments < endog", () => {
    render(<IVControls columns={cols} value={{ endog: ["educ", "age"], instruments: ["dist"] }} onChange={() => {}} />);
    expect(screen.getByText(/under-identified/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/runForm/IVControls.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `IVControls.tsx`**

Component contract:
```tsx
export interface IVRoleValue { endog: string[]; instruments: string[]; }
export function IVControls(props: {
  columns: string[];                 // candidate columns (y already excluded by caller)
  value: IVRoleValue;
  onChange: (v: IVRoleValue) => void;
}): JSX.Element
```
Behavior (no `@ts-ignore`/`as any`; strict types):
- Render one row per `columns` entry with a single-select role: `exogenous control` | `endogenous` | `instrument` | `unused`. A column's presence in `value.endog` / `value.instruments` sets its role; everything else defaults to `exogenous control` (so `x`/exog stays the default, matching the "reuse x as exog" decision). Overlap is impossible because each column has exactly one select.
- On any change, recompute `endog`/`instruments` arrays and call `onChange`.
- Compute identification badge from counts: `instruments.length < endog.length` → "under-identified" (error styling); `==` → "just-identified"; `>` → "over-identified".
- Keep styling consistent with existing `runForm` controls (reuse the iOS token classes used by `PanelControls`).

Mirror existing `runForm` control patterns (`PanelControls.tsx`, `ModelTypeSelect.tsx`) for props/types/styles.

- [ ] **Step 4: Run to verify it passes + tsc**

Run: `cd frontend && npx vitest run src/runForm/IVControls.test.tsx && npx tsc --noEmit`
Expected: PASS + 0 type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/IVControls.tsx frontend/src/runForm/IVControls.test.tsx
git commit -m "feat(frontend): IVControls role-assignment + identification badge"
```

---

### Task 8: Wire `IVControls` + covariance into `RunForm`, thread params

**Files:**
- Modify: `frontend/src/runForm/RunForm.tsx`
- Modify: `frontend/src/api.ts` (`RunExtraParams`)
- Test: extend `frontend/src/runForm/RunForm` test coverage (or App.test.tsx)

- [ ] **Step 1: Write the failing test**

Add a test: selecting `model_type = iv_2sls` renders `IVControls` and the covariance selector; submitting sends `iv_endog` / `iv_instruments` in the `runWorkflow` extras. Assert via a `runWorkflow` spy that the payload carries the arrays.

Run: `cd frontend && npx vitest run` (new test) — Expected: FAIL.

- [ ] **Step 2: Extend `RunExtraParams` in `api.ts`**

```ts
export interface RunExtraParams {
  // ...existing fields...
  iv_endog?: string[];
  iv_instruments?: string[];
}
```
Ensure `runWorkflow` serializes them as JSON arrays in the form body (mirror existing extras).

- [ ] **Step 3: Render IV controls in `RunForm`**

When `modelType === "iv_2sls"`: render `<IVControls columns={candidateColumns} value={ivRole} onChange={setIvRole} />` and reuse the existing covariance `<select>` (the one PanelControls uses) so IV gets robust/clustered/unadjusted. Exclude `y` from `candidateColumns`. On submit, pass `iv_endog: ivRole.endog`, `iv_instruments: ivRole.instruments`, and the chosen covariance through `runWorkflow` extras. Leave all non-IV behavior untouched (behavior-frozen for other models).

- [ ] **Step 4: Run vitest + tsc**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS (583+), 0 type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/RunForm.tsx frontend/src/api.ts frontend/src/runForm/*.test.tsx
git commit -m "feat(frontend): wire IVControls + covariance into RunForm"
```

---

### Task 9: `IVDiagnosticsCard` result rendering

**Files:**
- Create: `frontend/src/runResult/IVDiagnosticsCard.tsx`
- Test: `frontend/src/runResult/IVDiagnosticsCard.test.tsx`
- Modify: `frontend/src/runResult.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// renders the three diagnostics + identification badge from an iv_diagnostics object
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { IVDiagnosticsCard } from "./IVDiagnosticsCard";

const diag = {
  identification: "over",
  weak_instruments: { first_stage_f: 24.3, threshold: 10, verdict: "strong", message: "Instruments are strong (first-stage F > 10, rule of thumb)." },
  endogeneity: { test: "wu_hausman", statistic: 8.1, pvalue: 0.004, verdict: "endogenous", message: "Endogeneity confirmed (p < 0.05); IV is warranted." },
  overidentification: { applicable: true, test: "sargan", statistic: 1.9, pvalue: 0.168, verdict: "not_rejected", message: "Instrument exogeneity not rejected (p >= 0.05)." },
};

describe("IVDiagnosticsCard", () => {
  it("shows all three diagnostics and the over-identified badge", () => {
    render(<IVDiagnosticsCard diagnostics={diag as any} />);
    expect(screen.getByText(/over-identified/i)).toBeInTheDocument();
    expect(screen.getByText(/first-stage F/i)).toBeInTheDocument();
    expect(screen.getByText(/IV is warranted/i)).toBeInTheDocument();
  });

  it("renders 'not applicable' for just-identified overid", () => {
    const d = { ...diag, identification: "just", overidentification: { applicable: false, verdict: "Not applicable (just-identified)." } };
    render(<IVDiagnosticsCard diagnostics={d as any} />);
    expect(screen.getByText(/not applicable/i)).toBeInTheDocument();
  });
});
```

> Replace `as any` in the real test once the `IVDiagnostics` type below exists (the type gate forbids `as any` in committed source — define and use the proper type).

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/runResult/IVDiagnosticsCard.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `IVDiagnosticsCard.tsx` + type**

Define the `IVDiagnostics` TS interface mirroring the backend dict shape (identification union; weak_instruments/endogeneity/overidentification members). Render: identification badge, then the three rows (statistic(s) + verdict badge + plain-language message), expanded by default, stats and verdicts both shown. Reuse the existing result-card styling. Fetch mirrors how `PredictionResultCard`/`ImputationSummary` fetch their artifact (`fetchArtifactJson(runId, "iv_diagnostics")`), rendered only when the artifact exists.

- [ ] **Step 4: Render from `runResult.tsx`**

Add `<IVDiagnosticsCard ... />` to the result view, shown when the `iv_diagnostics` artifact is present (mirror the artifact-presence pattern used for `PredictionResultCard`).

- [ ] **Step 5: vitest + tsc**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, 0 type errors, no `as any` in committed source.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runResult/IVDiagnosticsCard.tsx frontend/src/runResult/IVDiagnosticsCard.test.tsx frontend/src/runResult.tsx
git commit -m "feat(frontend): IVDiagnosticsCard renders the IV trio"
```

---

## Phase E — rerun_actions dogfood + dedup guard

### Task 10: IV pack `rerun_actions` ("Switch to OLS") + key-dedup guard

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py` (CORE_PACK `rerun_actions`)
- Modify: `backend/workbench/engine/pack.py` (dedup guard)
- Test: `tests/test_pack_rerun_dedup.py`, extend `tests/test_engine_iv.py`

- [ ] **Step 1: Write the failing dedup test**

```python
# tests/test_pack_rerun_dedup.py
import pytest
from workbench.engine.pack import (
    AnalysisPack, RerunAction, register_pack, RERUN_ACTION_REGISTRY, PackContractError,
)


@pytest.fixture
def restore_rerun_registry():
    snap = list(RERUN_ACTION_REGISTRY)
    yield
    RERUN_ACTION_REGISTRY[:] = snap


def test_duplicate_rerun_key_raises(restore_rerun_registry):
    register_pack(AnalysisPack(pack_id="p1", rerun_actions=[
        RerunAction(key="dup", label="A", param_overrides={})]))
    with pytest.raises(PackContractError) as exc:
        register_pack(AnalysisPack(pack_id="p2", rerun_actions=[
            RerunAction(key="dup", label="B", param_overrides={})]))
    assert "dup" in str(exc.value)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pack_rerun_dedup.py -v`
Expected: FAIL — no dedup, no raise.

- [ ] **Step 3: Add the dedup guard in `register_pack`**

In the `rerun_actions` loop:

```python
    existing_keys = {ra.key for ra in RERUN_ACTION_REGISTRY}
    for rerun in pack.rerun_actions:
        if rerun.key in existing_keys:
            raise PackContractError(
                f"Duplicate RerunAction key {rerun.key!r} "
                f"(pack {pack.pack_id!r}); rerun keys must be unique."
            )
        existing_keys.add(rerun.key)
        RERUN_ACTION_REGISTRY.append(rerun)
```

- [ ] **Step 4: Add the IV `rerun_actions` to CORE_PACK**

```python
    rerun_actions=[
        RerunAction(key="iv_switch_to_ols", label="Switch to OLS",
                    param_overrides={"model_type": "ols"}),
    ],
```

> CORE_PACK currently declares no `rerun_actions`; adding this is the first real registrant. Because the registry is now non-empty, confirm golden 0-drift still holds: `actions_for_model_fit_failure` appends rerun actions only in the explicit-failure branch — verify the existing recommended-actions goldens still pass (they assert specific action sets; if a golden pins the exact action list for an explicit non-IV failure, update it to include `iv_switch_to_ols` OR scope the rerun action so it only attaches for IV — see Step 5).

- [ ] **Step 5: Decide attach-scope + golden check**

Run: `.venv/bin/python -m pytest tests/test_recommended_actions.py tests/test_engine_golden.py -q`
- If green: the registry append is inert for existing goldens — done.
- If a recommended-actions golden now includes `iv_switch_to_ols` for a NON-IV failure, that is a behavior change. Fix by scoping: only surface registry rerun actions whose `param_overrides`/applicability match the failed `requested_model_type` (add a guard in `_rerun_action_to_dict` consumption keyed off the failure's model_type), so "Switch to OLS" attaches only to IV failures. Re-run until 0-drift.

- [ ] **Step 6: Extend IV test — failure surfaces the recovery**

Add to `tests/test_engine_iv.py`: an IV run with an empty `iv_instruments` produces a `failed` manifest whose `MODEL_FIT_FAILED` evidence `recommended_actions` includes `key == "iv_switch_to_ols"` with `form_overrides == {"model_type": "ols"}`. Reverse-check: removing the CORE_PACK `rerun_actions` entry makes this assertion red.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/pack.py backend/workbench/engine/stages/estimation.py tests/test_pack_rerun_dedup.py tests/test_engine_iv.py
git commit -m "feat(iv): Switch-to-OLS rerun action + fail-loud rerun key dedup"
```

---

## Phase F — Example + docs

### Task 11: Canonical IV example dataset + how-to

**Files:**
- Create: `examples/iv_returns_to_schooling/` (csv + a short README) — or match the existing `examples/` layout
- Create: `docs/iv-2sls-howto.md`

- [ ] **Step 1: Add a small textbook IV dataset**

Add a compact CSV with a clear endogenous regressor and a valid-by-construction instrument (e.g. simulated returns-to-schooling: `wage`, `educ` endogenous, `dist`/`momeduc` instruments, `age` control). Keep it small (≤ a few hundred rows) and documented in the README (what each column is, why the instrument is plausible).

- [ ] **Step 2: Write the how-to**

`docs/iv-2sls-howto.md`: how to run IV from the GUI (select `iv_2sls`, assign roles, read the diagnostics), what the three diagnostics mean in one line each, and the order-condition requirement. Reference the example dataset.

- [ ] **Step 3: Smoke-run the example through the engine**

Run an IV workflow on the example dataset (CLI/test harness) and confirm it completes with an `iv_diagnostics` artifact. (No assertion task — just confirm the shipped example actually works.)

- [ ] **Step 4: Commit**

```bash
git add examples/iv_returns_to_schooling docs/iv-2sls-howto.md
git commit -m "docs(iv): canonical example dataset + how-to"
```

---

## Phase G — Debt cleanup + final gate

### Task 12: V1.5.4.3 debt — REGISTERED_PACKS fixture + tsconfig root coverage

**Files:**
- Modify: `tests/test_pack_contract.py`, `tests/test_pack_stage_insertion.py`, `tests/test_pack_rerun_actions.py`
- Modify: `frontend/tsconfig.json` (+ maybe a `tsconfig` for config files)

- [ ] **Step 1: Add a `REGISTERED_PACKS` restore fixture**

In each of the three pack test files, add and use a fixture that snapshots and restores `workbench.engine.pack.REGISTERED_PACKS` (mirror the existing `restore_rerun_registry` / `restore_pipeline` fixtures), so registry-mutating tests don't leak.

```python
@pytest.fixture(autouse=True)
def restore_registered_packs():
    from workbench.engine.pack import REGISTERED_PACKS
    snap = list(REGISTERED_PACKS)
    yield
    REGISTERED_PACKS[:] = snap
```

Run: `.venv/bin/python -m pytest tests/test_pack_contract.py tests/test_pack_stage_insertion.py tests/test_pack_rerun_actions.py -q` — Expected: PASS, and order-independent.

- [ ] **Step 2: Bring root config files under the type gate (or document exclusion)**

Either add `vite.config.ts` / `vitest.setup.ts` to a tsconfig include (where `@types/node` earns its place) and fix any resulting errors, OR add a one-line comment in `frontend/tsconfig.json`'s neighborhood documenting the deliberate `include: ["src"]` scope. Run `cd frontend && npx tsc --noEmit` — Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pack_contract.py tests/test_pack_stage_insertion.py tests/test_pack_rerun_actions.py frontend/tsconfig.json
git commit -m "chore: clear V1.5.4.3 debt (REGISTERED_PACKS fixture + tsconfig scope)"
```

---

### Task 13: Final gate + release notes

**Files:**
- Create: `docs/v1.5.4.4-release-notes.md`

- [ ] **Step 1: Run the full gate**

Run: `./scripts/gate.sh`
Expected: GATE PASSED — backend (761 + IV tests), frontend (582 + IV tests), golden 0-drift (incl. new `iv_2sls.json`), tsc clean.

- [ ] **Step 2: Bare-pytest confirmation**

Run: `.venv/bin/pytest -q`
Expected: PASS, no collection errors.

- [ ] **Step 3: Write release notes**

Create `docs/v1.5.4.4-release-notes.md`: IV/2SLS now reachable from the GUI (explicit-only), role-assignment input (overlap impossible) + identification badge, the diagnostic trio with plain-language verdicts (incl. just-identified "not applicable" overid), covariance selector, fail-loud spec validation, "Switch to OLS" recovery (first real `rerun_actions` consumer), canonical example + how-to, V1.5.4.3 debt cleared. State the behavior-freeze guarantee (iv_2sls explicit-only and new → all current goldens byte-identical) and deferred items (full orchestrator split → V1.5.4.5, OLS-vs-IV / full first-stage / CLI path → later).

- [ ] **Step 4: Commit + push branch**

```bash
git add docs/v1.5.4.4-release-notes.md
git commit -m "docs: V1.5.4.4 release notes"
git push -u origin workbench-v1.5.4.4
```

---

## Self-Review Notes

- **Spec coverage:** §2.1 IV wiring→Task2; §2.2 validation→Task1(+ridden in Task2); §2.3 diagnostics→Task4+5; §2.4 frontend→Task7+8+9; §2.5 covariance→Task8; §2.6 rerun dogfood→Task10; §2.7 manifest sync→Task6; §2.8 example→Task11; §2.9 debt→Task10(dedup)+Task12(fixture/tsconfig). §3 architecture (explicit-only via MODEL_REGISTRY-not-DEFAULT, fitted via _fitted_models, diagnostics guarded branch) realized in Tasks 2/5. §5 antifragility (golden 0-drift per backend task, G0-3 reverse-checks in Tasks 5 & 10, G0-5 in Task 6, explicit-only invariant in Task 2) covered. §6 phasing A–G = Tasks 1 / 2-3 / 4-5 / 6-9 / 10 / 11 / 12-13.
- **Behavior-freeze:** every backend task has a golden 0-drift step; Task 10 Step 5 explicitly handles the one place a non-IV golden could shift (rerun action attach-scope) and resolves it to 0-drift.
- **Deferred honored:** no full orchestrator split (only the minimal `_run_workflow` param thread), no OLS-vs-IV, no full first-stage display, no CLI path, no wiring of the still-deferred pack slots.
- **Type consistency:** `validate_iv_spec`/`IVSpecError`, `build_iv_diagnostics` returned dict shape, `IVRoleValue {endog,instruments}`, `RunExtraParams.iv_endog/iv_instruments`, artifact id `iv_diagnostics`, model_id `iv_2sls_1`, rerun key `iv_switch_to_ols` are defined once and referenced consistently across backend, tests, and frontend.
- **Runtime-discovered content:** Task 4 Step 3 flags that linearmodels attribute names (`first_stage.diagnostics`/`wu_hausman()`/`sargan`) must be confirmed against the installed version while keeping the dict shape fixed; Task 6/8/9 frontend JSX details follow existing `runForm`/`runResult` patterns rather than being enumerated line-by-line, with tsc + vitest as the hard gates.
```
