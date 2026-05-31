# V1.5.3.1 Backend Analysis Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, backend-only mature package analysis capabilities while keeping default `auto` behavior stable and conservative.

**Architecture:** Extend the existing backend in place. Keep the Stata-like external surface (`model_type + y + x + options`) and R-like internal artifact outputs, without introducing a large registry framework. New methods are explicit requests, optional extras fail with structured messages, and artifacts stay lightweight.

**Tech Stack:** Python 3.11, pandas, scipy, statsmodels, optional linearmodels, optional scikit-learn, optional imbalanced-learn, pytest.

---

## Scope Lock

Do not modify:

- `frontend/src/workbench/**`
- `frontend/src/lineage/**`
- `frontend/package.json`

Do not add:

- AI endpoints
- rerun endpoints
- editable operation endpoints
- command palette behavior
- causal inference execution
- automatic execution of every new model in `auto`

The implementation only changes backend code, backend tests, `pyproject.toml`, and docs.

## File Structure

Create:

- `backend/workbench/econometrics/optional_deps.py`  
  Small helper for optional extra imports and structured missing-dependency details.

- `backend/workbench/imputation.py`  
  Explicit MICE preprocessing helper. It writes imputation artifacts and never overwrites `processed/cleaned_dataset.parquet`.

- `backend/workbench/prediction.py`  
  Explicit prediction-only helper for Lasso, Ridge, and RandomForest. It writes `prediction_results/*.json` and never feeds econometric inference automatically.

- `tests/test_optional_deps.py`  
  Unit tests for missing dependency messages.

- `tests/test_advanced_econometrics.py`  
  Tests for Probit, Negative Binomial, GLM, optional panel and IV behavior.

- `tests/test_statistical_tests_extended.py`  
  Tests for Spearman, Kendall, Mann-Whitney, Kruskal, Fisher exact, and p-value correction metadata.

- `tests/test_imputation_mice.py`  
  Tests for impute-only MICE artifact behavior and safe skip behavior.

- `tests/test_prediction_models.py`  
  Tests for explicit prediction artifacts and bounded CV behavior.

Modify:

- `pyproject.toml`  
  Add optional extras: `panel`, `ml`, `imbalanced`, `imputation`.

- `backend/workbench/artifacts.py`  
  Add optional package names to environment snapshots.

- `backend/workbench/config.py`  
  Add flat config fields for explicit advanced requests. Avoid nested config parsing in this release.

- `backend/workbench/cli.py`  
  Add `--model-type` and minimal advanced options.

- `backend/workbench/api.py`  
  Preserve existing API behavior; only pass through already accepted `model_type`.

- `backend/workbench/orchestrator.py`  
  Add explicit advanced model routing. Preserve `auto` behavior.

- `backend/workbench/econometrics/runner.py`  
  Add direct model functions.

- `backend/workbench/econometrics/normalize.py`  
  Ensure new result families produce lightweight JSON.

- `backend/workbench/statistical_tests.py`  
  Add direct scipy/statsmodels tests and correction metadata.

---

### Task 1: Add Optional Dependency Helper And Extras

**Files:**
- Create: `backend/workbench/econometrics/optional_deps.py`
- Modify: `pyproject.toml`
- Modify: `backend/workbench/artifacts.py`
- Test: `tests/test_optional_deps.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_optional_deps.py`:

```python
import pytest

from workbench.econometrics.optional_deps import (
    OptionalDependencyNotInstalled,
    optional_dependency_error,
    require_optional_dependency,
)


def test_optional_dependency_error_payload_is_actionable():
    payload = optional_dependency_error("panel", "linearmodels", "panel_ols")

    assert payload == {
        "error_code": "OPTIONAL_DEPENDENCY_MISSING",
        "step": "estimation",
        "engine": "linearmodels",
        "model_type": "panel_ols",
        "message": 'Install the panel extra to use panel_ols: pip install -e ".[panel]"',
        "details": {
            "extra": "panel",
            "package": "linearmodels",
            "install": 'pip install -e ".[panel]"',
        },
    }


def test_require_optional_dependency_raises_structured_error_for_missing_package():
    with pytest.raises(OptionalDependencyNotInstalled) as exc_info:
        require_optional_dependency(
            "definitely_missing_workbench_package",
            extra="panel",
            engine="definitely_missing_workbench_package",
            model_type="panel_ols",
        )

    payload = exc_info.value.to_issue_details()
    assert payload["error_code"] == "OPTIONAL_DEPENDENCY_MISSING"
    assert payload["model_type"] == "panel_ols"
    assert payload["details"]["extra"] == "panel"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_optional_deps.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.econometrics.optional_deps'`.

- [ ] **Step 3: Add optional extras to `pyproject.toml`**

Modify `[project.optional-dependencies]` to:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.2", "httpx>=0.27"]
panel = ["linearmodels>=6"]
ml = ["scikit-learn>=1.5"]
imbalanced = ["imbalanced-learn>=0.12"]
imputation = ["statsmodels>=0.14"]
```

- [ ] **Step 4: Implement `optional_deps.py`**

Create `backend/workbench/econometrics/optional_deps.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Any


def optional_dependency_error(
    extra: str,
    package: str,
    model_type: str,
    *,
    step: str = "estimation",
    engine: str | None = None,
) -> dict[str, Any]:
    install = f'pip install -e ".[{extra}]"'
    resolved_engine = engine or package
    return {
        "error_code": "OPTIONAL_DEPENDENCY_MISSING",
        "step": step,
        "engine": resolved_engine,
        "model_type": model_type,
        "message": f"Install the {extra} extra to use {model_type}: {install}",
        "details": {
            "extra": extra,
            "package": package,
            "install": install,
        },
    }


@dataclass
class OptionalDependencyNotInstalled(RuntimeError):
    extra: str
    package: str
    model_type: str
    step: str = "estimation"
    engine: str | None = None

    def __str__(self) -> str:
        return str(self.to_issue_details()["message"])

    def to_issue_details(self) -> dict[str, Any]:
        return optional_dependency_error(
            self.extra,
            self.package,
            self.model_type,
            step=self.step,
            engine=self.engine,
        )


def require_optional_dependency(
    module_name: str,
    *,
    extra: str,
    engine: str,
    model_type: str,
    step: str = "estimation",
) -> ModuleType:
    try:
        return import_module(module_name)
    except ImportError as exc:
        raise OptionalDependencyNotInstalled(
            extra=extra,
            package=module_name,
            model_type=model_type,
            step=step,
            engine=engine,
        ) from exc
```

- [ ] **Step 5: Add optional package names to environment snapshots**

Modify `backend/workbench/artifacts.py`:

```python
PACKAGE_VERSION_NAMES = (
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pandas",
    "openpyxl",
    "pyarrow",
    "statsmodels",
    "scipy",
    "linearmodels",
    "scikit-learn",
    "imbalanced-learn",
    "matplotlib",
    "jinja2",
    "reportlab",
    "pyyaml",
    "typer",
)
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_optional_deps.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml backend/workbench/artifacts.py backend/workbench/econometrics/optional_deps.py tests/test_optional_deps.py
git commit -m "feat: add optional analysis dependency helpers"
```

---

### Task 2: Add Explicit Statsmodels Models

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Modify: `backend/workbench/econometrics/normalize.py`
- Test: `tests/test_advanced_econometrics.py`

- [ ] **Step 1: Write failing tests for Probit, Negative Binomial, and GLM**

Create `tests/test_advanced_econometrics.py`:

```python
import numpy as np
import pandas as pd

from workbench.econometrics.runner import (
    run_glm,
    run_negative_binomial,
    run_probit,
)


def test_run_probit_binary_y_returns_normalized_result():
    rng = np.random.default_rng(42)
    n = 80
    x1 = rng.normal(size=n)
    latent = -0.2 + 0.9 * x1 + rng.normal(size=n)
    y = (latent > 0).astype(int)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_probit(frame, y="y", x=["x1"], model_id="probit_1")

    assert result["schema_version"] == 1
    assert result["model_id"] == "probit_1"
    assert result["model_type"] == "probit"
    assert result["engine"] == "statsmodels"
    assert result["nobs"] == n
    assert "x1" in result["coefficients"]
    assert len(result["fitted_values_preview"]) <= 500
    assert "fitted_values" not in result


def test_run_negative_binomial_count_y_returns_irr():
    rng = np.random.default_rng(43)
    n = 120
    x1 = rng.uniform(0, 3, n)
    mu = np.exp(0.2 + 0.4 * x1)
    y = rng.negative_binomial(n=2, p=2 / (2 + mu))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_negative_binomial(frame, y="y", x=["x1"], model_id="nb_1")

    assert result["model_type"] == "negative_binomial"
    assert result["engine"] == "statsmodels"
    assert "irr" in result
    assert "x1" in result["coefficients"]


def test_run_glm_poisson_returns_requested_family():
    rng = np.random.default_rng(44)
    n = 60
    x1 = rng.uniform(0, 2, n)
    y = rng.poisson(np.exp(0.1 + 0.3 * x1))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_glm(
        frame,
        y="y",
        x=["x1"],
        model_id="glm_1",
        family_name="poisson",
    )

    assert result["model_type"] == "glm"
    assert result["glm_family"] == "poisson"
    assert result["engine"] == "statsmodels"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_advanced_econometrics.py -v
```

Expected: FAIL with import errors for `run_glm`, `run_negative_binomial`, and `run_probit`.

- [ ] **Step 3: Make normalized results lightweight**

Modify `backend/workbench/econometrics/normalize.py` by changing the result block in `normalize_statsmodels_result` so full arrays are replaced by previews:

```python
    fitted_values = _json_safe_sequence(getattr(fitted, "fittedvalues", []))
    residuals = _json_safe_sequence(getattr(fitted, "resid", []))
    result: dict[str, Any] = {
        "schema_version": 1,
        "model_id": model_id,
        "nobs": int(fitted.nobs),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "pseudo_r2": _json_safe_float(getattr(fitted, "prsquared", None)),
        "llf": _json_safe_float(getattr(fitted, "llf", None)),
        "aic": _json_safe_float(getattr(fitted, "aic", None)),
        "bic": _json_safe_float(getattr(fitted, "bic", None)),
        "fitted_values_preview": fitted_values[:500],
        "residuals_preview": residuals[:500],
        "coefficients": coefficients,
    }
```

Existing code that reads fitted/residual arrays must be updated in Task 4 if needed. This step intentionally stops new model artifacts from storing large arrays.

- [ ] **Step 4: Implement new model functions**

Add imports and functions to `backend/workbench/econometrics/runner.py`:

```python
def _add_engine(result: dict[str, Any], *, engine: str = "statsmodels") -> dict[str, Any]:
    result["engine"] = engine
    return result


def run_probit(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.probit(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(
            f"Probit model {model_id} failed to fit. Check binary outcome values and predictors."
        ) from exc
    if not getattr(fitted, "converged", True):
        raise ValueError(f"Probit model {model_id} did not converge.")
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "probit"
    return _add_engine(result), fitted


def run_negative_binomial(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    series = frame[y].dropna()
    if (series < 0).any():
        raise ValueError(f"Negative Binomial model requires non-negative y, but '{y}' has negative values.")
    if not (series == series.astype(int)).all():
        raise ValueError(f"Negative Binomial model requires integer count y, but '{y}' has non-integer values.")
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        fitted = smf.negativebinomial(formula=formula, data=frame).fit(disp=False, maxiter=100)
    except Exception as exc:
        raise ValueError(f"Negative Binomial model {model_id} failed to fit.") from exc
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "negative_binomial"
    return _add_engine(result), fitted


def run_glm(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    family_name: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    from statsmodels.genmod import families

    family_map = {
        "binomial": families.Binomial,
        "poisson": families.Poisson,
        "negative_binomial": families.NegativeBinomial,
    }
    family_cls = family_map.get(family_name)
    if family_cls is None:
        raise ValueError(f"Unsupported GLM family: {family_name}")
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    fitted = smf.glm(formula=formula, data=frame, family=family_cls()).fit(maxiter=100)
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "glm"
    result["glm_family"] = family_name
    return _add_engine(result), fitted
```

Also update existing `run_ols`, `run_logit`, `run_poisson`, and `run_fixed_effects` to set `engine`:

```python
    result["model_type"] = "ols_robust" if robust else "ols"
    return _add_engine(result), original
```

Use the equivalent `_add_engine(result)` before returning in the other existing functions.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
pytest tests/test_advanced_econometrics.py tests/test_econometrics_engine.py -v
```

Expected: PASS. Existing tests that checked `fitted_values` and `residuals` may need to read preview keys only if they were directly asserting the old large arrays.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/econometrics/runner.py backend/workbench/econometrics/normalize.py tests/test_advanced_econometrics.py
git commit -m "feat: add explicit statsmodels advanced models"
```

---

### Task 3: Route Explicit Advanced Models Through Orchestrator And CLI

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `backend/workbench/cli.py`
- Test: `tests/test_advanced_econometrics.py`
- Test: `tests/test_p0_regression.py`

- [ ] **Step 1: Add failing orchestration tests**

Append to `tests/test_advanced_econometrics.py`:

```python
from pathlib import Path

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_workflow_explicit_probit_writes_model_result(tmp_path: Path):
    project = create_project(tmp_path, "probit-project")
    csv_path = tmp_path / "binary.csv"
    frame = pd.DataFrame({
        "y": [0, 1, 0, 1, 0, 1] * 10,
        "x": list(range(60)),
    })
    frame.to_csv(csv_path, index=False)

    result = run_workflow(
        project.root,
        [csv_path],
        mode="auto",
        y="y",
        x=["x"],
        model_type="probit",
    )

    run_root = project.root / "runs" / result["run_id"]
    model = read_json(run_root / "model_results" / "probit_1.json")
    assert model["model_type"] == "probit"
    assert model["engine"] == "statsmodels"


def test_run_workflow_auto_still_routes_binary_to_logit(tmp_path: Path):
    project = create_project(tmp_path, "auto-project")
    csv_path = tmp_path / "binary.csv"
    frame = pd.DataFrame({
        "y": [0, 1, 0, 1, 0, 1] * 10,
        "x": list(range(60)),
    })
    frame.to_csv(csv_path, index=False)

    result = run_workflow(project.root, [csv_path], mode="auto", y="y", x=["x"])

    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "model_results" / "logit_1.json").is_file()
    assert not (run_root / "model_results" / "probit_1.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_advanced_econometrics.py::test_run_workflow_explicit_probit_writes_model_result -v
```

Expected: FAIL because `run_workflow` does not accept `model_type`.

- [ ] **Step 3: Add `model_type` to `run_workflow`**

Modify `backend/workbench/orchestrator.py`:

```python
def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
    model_type: str = "auto",
) -> dict[str, str]:
```

Then pass `model_type=model_type` into `_run_workflow(...)` and into `_write_manifest(...)` calls that currently hardcode `"auto"` for `requested_model_type`.

- [ ] **Step 4: Import and route new model functions**

Modify the import block in `backend/workbench/orchestrator.py`:

```python
from .econometrics.runner import (
    run_glm,
    run_logit,
    run_negative_binomial,
    run_ols,
    run_poisson,
    run_probit,
    run_time_series_diagnostics,
)
```

Replace the estimation branch with explicit model checks before y-type auto routing:

```python
        if model_type == "probit":
            primary, primary_fitted = run_probit(
                cleaned, y=normalized_y, x=normalized_x,
                model_id="probit_1", categorical_x=categorical_vars,
            )
            _write_model_result(run_root, "probit_1", primary)
            model_results.append(("probit_1", primary))
            fitted_models["probit_1"] = primary_fitted
        elif model_type == "negative_binomial":
            primary, primary_fitted = run_negative_binomial(
                cleaned, y=normalized_y, x=normalized_x,
                model_id="negative_binomial_1", categorical_x=categorical_vars,
            )
            _write_model_result(run_root, "negative_binomial_1", primary)
            model_results.append(("negative_binomial_1", primary))
            fitted_models["negative_binomial_1"] = primary_fitted
        elif model_type.startswith("glm:"):
            family_name = model_type.split(":", 1)[1]
            primary, primary_fitted = run_glm(
                cleaned, y=normalized_y, x=normalized_x,
                model_id="glm_1", family_name=family_name,
                categorical_x=categorical_vars,
            )
            _write_model_result(run_root, "glm_1", primary)
            model_results.append(("glm_1", primary))
            fitted_models["glm_1"] = primary_fitted
        elif y_type == "binary":
            ...
```

Keep the existing binary/count/continuous branches unchanged after the explicit branches.

- [ ] **Step 5: Update model type mapping**

Modify `_MODEL_TYPE_MAP` in `backend/workbench/orchestrator.py`:

```python
_MODEL_TYPE_MAP = {
    "ols": "continuous",
    "logit": "binary",
    "probit": "binary",
    "poisson": "count",
    "negative_binomial": "count",
}
```

Do not map `glm:*` here. It should leave `y_type` data-driven while explicit GLM routing uses the requested family.

- [ ] **Step 6: Add CLI `--model-type`**

Modify `backend/workbench/cli.py`:

```python
    mode: str = typer.Option("auto", "--mode"),
    model_type: str = typer.Option("auto", "--model-type"),
) -> None:
    from .orchestrator import run_workflow

    result = run_workflow(
        project_root,
        [data_file],
        mode=mode,
        y=y,
        x=x,
        model_type=model_type,
    )
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
pytest tests/test_advanced_econometrics.py tests/test_p0_regression.py -v
```

Expected: PASS. `auto` tests still produce existing OLS/Logit/Poisson artifacts.

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/orchestrator.py backend/workbench/cli.py tests/test_advanced_econometrics.py
git commit -m "feat: route explicit advanced model types"
```

---

### Task 4: Keep Figure Generation Compatible With Lightweight Model Results

**Files:**
- Modify: `backend/workbench/visualization.py`
- Test: `tests/test_visualization.py`

- [ ] **Step 1: Write a failing compatibility test**

Append to `tests/test_visualization.py`:

```python
def test_create_figures_accepts_preview_residual_keys(tmp_path):
    import pandas as pd

    from workbench.visualization import create_figures

    frame = pd.DataFrame({"y": [1, 2, 3], "x": [1, 2, 3]})
    model_results = [
        (
            "ols_1",
            {
                "fitted_values_preview": [1.0, 2.0, 3.0],
                "residuals_preview": [0.0, 0.0, 0.0],
                "coefficients": {
                    "x": {"estimate": 1.0, "std_error": 0.1},
                },
            },
        )
    ]

    figures = create_figures(
        frame,
        tmp_path,
        numeric_columns=["y", "x"],
        time_column=None,
        model_results=model_results,
    )

    assert "residuals_fitted" in figures
    assert "coef_plot" in figures
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_visualization.py::test_create_figures_accepts_preview_residual_keys -v
```

Expected: FAIL because `create_figures` reads `residuals` and `fitted_values`.

- [ ] **Step 3: Update visualization to read preview keys**

Modify `backend/workbench/visualization.py`:

```python
        residuals = _numeric_list(
            model_result.get("residuals_preview", model_result.get("residuals"))
        )
        fitted = _numeric_list(
            model_result.get("fitted_values_preview", model_result.get("fitted_values"))
        )
```

- [ ] **Step 4: Run visualization tests**

Run:

```bash
pytest tests/test_visualization.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/visualization.py tests/test_visualization.py
git commit -m "fix: support lightweight model result previews"
```

---

### Task 5: Extend Statistical Tests Directly

**Files:**
- Modify: `backend/workbench/statistical_tests.py`
- Test: `tests/test_statistical_tests_extended.py`
- Test: `tests/test_statistical_tests.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_statistical_tests_extended.py`:

```python
import pandas as pd

from workbench.statistical_tests import run_statistical_tests


def test_rank_correlations_are_reported_for_numeric_pairs():
    frame = pd.DataFrame({"y": [1, 2, 3, 4, 5], "x": [1, 4, 9, 16, 25]})

    results = run_statistical_tests(frame, analysis_columns=["y", "x"])

    rank_rows = results["rank_correlations"]["results"]
    types = {row["test_type"] for row in rank_rows}
    assert {"spearman_correlation", "kendall_correlation"} <= types


def test_nonparametric_tests_and_fisher_are_reported():
    frame = pd.DataFrame({
        "y": [1.0, 1.1, 1.2, 3.0, 3.1, 3.2, 5.0, 5.1, 5.2],
        "group": ["a", "a", "a", "b", "b", "b", "c", "c", "c"],
        "binary": [0, 0, 1, 1, 1, 0, 0, 1, 1],
        "flag": [0, 1, 0, 1, 1, 0, 0, 1, 1],
    })

    results = run_statistical_tests(
        frame,
        analysis_columns=["y", "group", "binary", "flag"],
    )

    assert results["nonparametric"]["results"]
    assert any(row["test_type"] == "kruskal_wallis" for row in results["nonparametric"]["results"])
    assert any(row["test_type"] == "mann_whitney_u" for row in results["nonparametric"]["results"])
    assert any(row["test_type"] == "fisher_exact" for row in results["fisher_exact"]["results"])


def test_multiple_testing_correction_metadata_is_present():
    frame = pd.DataFrame({
        "y": [1, 2, 3, 4, 5, 6],
        "x1": [1, 2, 3, 4, 5, 6],
        "x2": [6, 5, 4, 3, 2, 1],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "x1", "x2"])

    row = results["correlations"]["results"][0]
    assert "p_value_corrected" in row
    assert row["correction_method"] == "fdr_bh"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_statistical_tests_extended.py -v
```

Expected: FAIL because new result families are not present.

- [ ] **Step 3: Add result families**

Modify `TEST_FAMILIES` in `backend/workbench/statistical_tests.py`:

```python
TEST_FAMILIES = {
    "correlations": "correlations.json",
    "rank_correlations": "rank_correlations.json",
    "t_tests": "t_tests.json",
    "anova": "anova.json",
    "nonparametric": "nonparametric.json",
    "chi_square": "chi_square.json",
    "fisher_exact": "fisher_exact.json",
}
```

- [ ] **Step 4: Add helper functions**

Add functions to `backend/workbench/statistical_tests.py`:

```python
def _spearman(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return None
    statistic, p_value = stats.spearmanr(pair[left], pair[right])
    return {
        "test_id": f"spearman:{left}:{right}",
        "test_type": "spearman_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"rho": _safe_float(statistic)},
        "source_id": f"statistical_tests.rank_correlations.spearman.{left}.{right}",
    }


def _kendall(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return None
    statistic, p_value = stats.kendalltau(pair[left], pair[right])
    return {
        "test_id": f"kendall:{left}:{right}",
        "test_type": "kendall_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"tau": _safe_float(statistic)},
        "source_id": f"statistical_tests.rank_correlations.kendall.{left}.{right}",
    }


def _mann_whitney(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    group_values = sorted(group_series.dropna().unique().tolist(), key=str)
    if len(group_values) != 2:
        return None
    left = pd.to_numeric(pair.loc[group_series == group_values[0], outcome], errors="coerce").dropna()
    right = pd.to_numeric(pair.loc[group_series == group_values[1], outcome], errors="coerce").dropna()
    if len(left) < 2 or len(right) < 2:
        return None
    statistic, p_value = stats.mannwhitneyu(left, right, alternative="two-sided")
    return {
        "test_id": f"mann_whitney:{outcome}:{group}",
        "test_type": "mann_whitney_u",
        "outcome": outcome,
        "group": group,
        "groups": [str(group_values[0]), str(group_values[1])],
        "nobs": int(len(left) + len(right)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"median_difference": float(right.median() - left.median())},
        "source_id": f"statistical_tests.nonparametric.mann_whitney.{outcome}.{group}",
    }


def _kruskal(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_series = _as_series(pair, group)
    if group_series is None:
        return None
    group_values = sorted(group_series.dropna().unique().tolist(), key=str)
    samples = [
        pd.to_numeric(pair.loc[group_series == value, outcome], errors="coerce").dropna()
        for value in group_values
    ]
    samples = [sample for sample in samples if len(sample) >= 2]
    if len(samples) < 2:
        return None
    statistic, p_value = stats.kruskal(*samples)
    return {
        "test_id": f"kruskal:{outcome}:{group}",
        "test_type": "kruskal_wallis",
        "outcome": outcome,
        "group": group,
        "groups": [str(value) for value in group_values],
        "nobs": int(sum(len(sample) for sample in samples)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {},
        "source_id": f"statistical_tests.nonparametric.kruskal.{outcome}.{group}",
    }


def _fisher_exact(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    table = pd.crosstab(pair[left], pair[right])
    if table.shape != (2, 2):
        return None
    statistic, p_value = stats.fisher_exact(table.to_numpy())
    return {
        "test_id": f"fisher_exact:{left}:{right}",
        "test_type": "fisher_exact",
        "variables": [left, right],
        "nobs": int(table.to_numpy().sum()),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            "odds_ratio": _safe_float(statistic),
            "contingency_table": {
                str(index): {str(column): int(value) for column, value in row.items()}
                for index, row in table.to_dict(orient="index").items()
            },
        },
        "source_id": f"statistical_tests.fisher_exact.{left}.{right}",
    }
```

- [ ] **Step 5: Call new tests and correction**

In `run_statistical_tests`, add calls beside existing loops:

```python
    for left, right in combinations(numeric, 2):
        for row in (_spearman(frame, left, right), _kendall(frame, left, right)):
            if row is not None:
                results["rank_correlations"]["results"].append(row)
```

Add nonparametric calls:

```python
    for outcome in numeric:
        for group in binary:
            if outcome != group:
                row = _mann_whitney(frame, outcome, group)
                if row is not None:
                    results["nonparametric"]["results"].append(row)

    for outcome in numeric:
        for group in multi:
            if outcome != group:
                row = _kruskal(frame, outcome, group)
                if row is not None:
                    results["nonparametric"]["results"].append(row)
```

Add Fisher calls:

```python
    for left, right in combinations(binary, 2):
        row = _fisher_exact(frame, left, right)
        if row is not None:
            results["fisher_exact"]["results"].append(row)
```

At the end of `run_statistical_tests`, before `return results`, add:

```python
    _apply_multiple_testing_correction(results)
```

Add helper:

```python
def _apply_multiple_testing_correction(results: dict[str, dict[str, Any]]) -> None:
    from statsmodels.stats.multitest import multipletests

    rows: list[dict[str, Any]] = []
    p_values: list[float] = []
    for family in results.values():
        for row in family.get("results", []):
            p_value = row.get("p_value")
            if p_value is None:
                continue
            rows.append(row)
            p_values.append(float(p_value))
    if not p_values:
        return
    _reject, corrected, _alpha_sidak, _alpha_bonf = multipletests(
        p_values,
        method="fdr_bh",
    )
    for row, corrected_value in zip(rows, corrected, strict=True):
        row["p_value_corrected"] = _safe_float(corrected_value)
        row["correction_method"] = "fdr_bh"
```

- [ ] **Step 6: Update summary loop**

Modify `summarize_statistical_tests` family list:

```python
    for family in (
        "correlations",
        "rank_correlations",
        "t_tests",
        "anova",
        "nonparametric",
        "chi_square",
        "fisher_exact",
    ):
```

Update `_summary_row` to handle new test types:

```python
    elif test_type in ("spearman_correlation", "kendall_correlation"):
        label = f"{test_type.replace('_', ' ').title()}: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type in ("mann_whitney_u", "kruskal_wallis"):
        label = f"{test_type.replace('_', ' ').title()}: {row['outcome']} by {row['group']}"
```

Keep the existing `else` for categorical pair tests.

- [ ] **Step 7: Run tests**

Run:

```bash
pytest tests/test_statistical_tests.py tests/test_statistical_tests_extended.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/statistical_tests.py tests/test_statistical_tests_extended.py
git commit -m "feat: extend statistical tests"
```

---

### Task 6: Add PanelOLS And IV2SLS Behind The Panel Extra

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_advanced_econometrics.py`

- [ ] **Step 1: Add tests for missing panel fields and import-skipped success**

Append to `tests/test_advanced_econometrics.py`:

```python
import pytest


def test_run_panel_ols_requires_entity_or_time():
    from workbench.econometrics.runner import run_panel_ols

    frame = pd.DataFrame({"y": [1, 2, 3], "x": [1, 2, 3]})

    with pytest.raises(ValueError, match="PANEL_FIELDS_MISSING"):
        run_panel_ols(
            frame,
            y="y",
            x=["x"],
            entity=None,
            time=None,
            model_id="panel_ols_1",
        )


def test_run_panel_ols_with_linearmodels_if_installed():
    pytest.importorskip("linearmodels")
    from workbench.econometrics.runner import run_panel_ols

    frame = pd.DataFrame({
        "firm_id": ["a", "a", "b", "b", "c", "c"],
        "year": [2020, 2021, 2020, 2021, 2020, 2021],
        "y": [1.0, 1.2, 2.0, 2.2, 3.0, 3.2],
        "x": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    })

    result, _ = run_panel_ols(
        frame,
        y="y",
        x=["x"],
        entity="firm_id",
        time="year",
        model_id="panel_ols_1",
    )

    assert result["model_type"] == "panel_ols"
    assert result["engine"] == "linearmodels"


def test_run_iv_2sls_requires_complete_spec():
    from workbench.econometrics.runner import run_iv_2sls

    frame = pd.DataFrame({"y": [1, 2, 3], "x": [1, 2, 3]})

    with pytest.raises(ValueError, match="IV_SPEC_INCOMPLETE"):
        run_iv_2sls(
            frame,
            y="y",
            exog=["x"],
            endog=[],
            instruments=[],
            model_id="iv_2sls_1",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_advanced_econometrics.py::test_run_panel_ols_requires_entity_or_time tests/test_advanced_econometrics.py::test_run_iv_2sls_requires_complete_spec -v
```

Expected: FAIL with missing function imports.

- [ ] **Step 3: Implement panel functions**

Add to `backend/workbench/econometrics/runner.py`:

```python
def _normalize_linearmodels_result(fitted: Any, model_id: str, model_type: str) -> dict[str, Any]:
    params = getattr(fitted, "params", {})
    std_errors = getattr(fitted, "std_errors", {})
    pvalues = getattr(fitted, "pvalues", {})
    coefficients: dict[str, dict[str, Any]] = {}
    for term, estimate in params.items():
        p_value = pvalues.get(term)
        coefficients[str(term)] = {
            "estimate": _json_safe_float(estimate),
            "std_error": _json_safe_float(std_errors.get(term)),
            "p_value": round(float(p_value), 6) if p_value is not None else None,
            "source_id": f"model_results.{model_id}.coefficients.{term}",
        }
    return {
        "schema_version": 1,
        "model_id": model_id,
        "model_type": model_type,
        "engine": "linearmodels",
        "nobs": int(getattr(fitted, "nobs", 0)),
        "r_squared": _json_safe_float(getattr(fitted, "rsquared", None)),
        "coefficients": coefficients,
        "warnings": [],
    }


def run_panel_ols(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str | None,
    time: str | None,
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    if entity is None and time is None:
        raise ValueError("PANEL_FIELDS_MISSING: panel_ols requires entity or time.")
    panel_model = require_optional_dependency(
        "linearmodels.panel",
        extra="panel",
        engine="linearmodels",
        model_type="panel_ols",
    )
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    index_cols = [col for col in (entity, time) if col is not None]
    panel = frame.set_index(index_cols)
    formula_terms = " + ".join(x)
    effects: list[str] = []
    if entity is not None:
        effects.append("EntityEffects")
    if time is not None:
        effects.append("TimeEffects")
    formula = f"{y} ~ 1 + {formula_terms}"
    if effects:
        formula = f"{formula} + {' + '.join(effects)}"
    fitted = panel_model.PanelOLS.from_formula(formula, data=panel).fit(cov_type=covariance)
    return _normalize_linearmodels_result(fitted, model_id, "panel_ols"), fitted


def run_iv_2sls(
    frame: pd.DataFrame,
    y: str,
    exog: list[str],
    endog: list[str],
    instruments: list[str],
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    if not endog or not instruments:
        raise ValueError("IV_SPEC_INCOMPLETE: iv_2sls requires endogenous variables and instruments.")
    iv_model = require_optional_dependency(
        "linearmodels.iv",
        extra="panel",
        engine="linearmodels",
        model_type="iv_2sls",
    )
    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, exog + endog + instruments)
    formula = f"{y} ~ 1"
    if exog:
        formula += " + " + " + ".join(exog)
    formula += f" [{' + '.join(endog)} ~ {' + '.join(instruments)}]"
    fitted = iv_model.IV2SLS.from_formula(formula, data=frame).fit(cov_type=covariance)
    return _normalize_linearmodels_result(fitted, model_id, "iv_2sls"), fitted
```

Add import near the top:

```python
from .optional_deps import require_optional_dependency
```

- [ ] **Step 4: Route explicit panel model only when config fields exist**

In `backend/workbench/orchestrator.py`, import `run_panel_ols` and add an explicit branch:

```python
        if model_type == "panel_ols":
            entity = id_candidates[0] if id_candidates else None
            time = time_candidates[0] if time_candidates else None
            primary, primary_fitted = run_panel_ols(
                cleaned,
                y=normalized_y,
                x=normalized_x,
                entity=entity,
                time=time,
                model_id="panel_ols_1",
            )
            _write_model_result(run_root, "panel_ols_1", primary)
            model_results.append(("panel_ols_1", primary))
            fitted_models["panel_ols_1"] = primary_fitted
        elif model_type == "probit":
            ...
```

Do not route `iv_2sls` through workflow until explicit CLI/API fields for endog and instruments are added. The runner function is still tested directly in this task.

- [ ] **Step 5: Run panel tests**

Run:

```bash
pytest tests/test_advanced_econometrics.py -v
```

Expected: PASS. The installed-linearmodels test is skipped if the `panel` extra is not installed.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/econometrics/runner.py backend/workbench/orchestrator.py tests/test_advanced_econometrics.py
git commit -m "feat: add optional panel and IV model functions"
```

---

### Task 7: Add Explicit MICE Imputation

**Files:**
- Create: `backend/workbench/imputation.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_imputation_mice.py`

- [ ] **Step 1: Write failing imputation tests**

Create `tests/test_imputation_mice.py`:

```python
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json, write_json
from workbench.imputation import run_mice_imputation


def _init_artifacts(run_root: Path) -> None:
    write_json(run_root / "artifacts_index.json", {"artifacts": []})


def test_run_mice_imputation_writes_artifacts_without_overwriting_cleaned(tmp_path: Path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    processed = run_root / "processed"
    processed.mkdir()
    cleaned_path = processed / "cleaned_dataset.parquet"
    frame = pd.DataFrame({
        "y": [1.0, None, 3.0, 4.0, 5.0],
        "x": [1.0, 2.0, None, 4.0, 5.0],
        "group": ["a", "b", "a", None, "b"],
    })
    frame.to_parquet(cleaned_path, index=False)

    result = run_mice_imputation(
        frame,
        run_root,
        columns=["y", "x", "group"],
        m=2,
        max_iter=2,
        random_seed=42,
    )

    assert result["status"] == "completed"
    assert (run_root / "processed" / "imputed_dataset.parquet").is_file()
    assert (run_root / "imputation" / "mice_summary.json").is_file()
    assert (run_root / "imputation" / "mice_decisions.json").is_file()
    assert cleaned_path.is_file()

    summary = read_json(run_root / "imputation" / "mice_summary.json")
    assert summary["method"] == "mice"
    assert summary["m"] == 2
    assert "group" in summary["skipped_columns"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_imputation_mice.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.imputation'`.

- [ ] **Step 3: Implement `run_mice_imputation`**

Create `backend/workbench/imputation.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json


def run_mice_imputation(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    columns: list[str],
    m: int = 5,
    max_iter: int = 10,
    random_seed: int = 20260429,
    max_missing_rate: float = 0.4,
) -> dict[str, Any]:
    from statsmodels.imputation.mice import MICEData

    selected = [column for column in columns if column in frame.columns]
    numeric_columns: list[str] = []
    skipped_columns: list[str] = []
    for column in selected:
        series = frame[column]
        if not pd.api.types.is_numeric_dtype(series):
            skipped_columns.append(column)
            continue
        if float(series.isna().mean()) > max_missing_rate:
            skipped_columns.append(column)
            continue
        numeric_columns.append(column)

    imputation_dir = run_root / "imputation"
    imputation_dir.mkdir(parents=True, exist_ok=True)
    if not numeric_columns:
        summary = {
            "schema_version": 1,
            "method": "mice",
            "status": "skipped",
            "m": m,
            "max_iter": max_iter,
            "random_seed": random_seed,
            "imputed_columns": [],
            "skipped_columns": skipped_columns,
            "warnings": ["No supported numeric columns were available for MICE."],
        }
        write_json(imputation_dir / "mice_summary.json", summary)
        write_json(imputation_dir / "mice_decisions.json", {"decisions": []})
        return summary

    imputed = frame.copy()
    mice_frame = frame[numeric_columns].copy()
    mice_data = MICEData(mice_frame)
    for _ in range(max_iter):
        mice_data.update_all()
    imputed_values = mice_data.data
    for column in numeric_columns:
        imputed[column] = imputed_values[column]

    imputed_path = run_root / "processed" / "imputed_dataset.parquet"
    imputed.to_parquet(imputed_path, index=False)
    register_artifact(
        run_root,
        "imputed_dataset",
        imputed_path,
        "processed_data",
        "imputation",
        ["cleaned_dataset"],
    )

    summary = {
        "schema_version": 1,
        "method": "mice",
        "status": "completed",
        "m": m,
        "max_iter": max_iter,
        "random_seed": random_seed,
        "imputed_columns": numeric_columns,
        "skipped_columns": skipped_columns,
        "warnings": [],
    }
    summary_path = imputation_dir / "mice_summary.json"
    decisions_path = imputation_dir / "mice_decisions.json"
    write_json(summary_path, summary)
    write_json(
        decisions_path,
        {
            "decisions": [
                {
                    "column": column,
                    "action": "mice_impute",
                    "missing_rate": float(frame[column].isna().mean()),
                }
                for column in numeric_columns
            ]
        },
    )
    register_artifact(run_root, "mice_summary", summary_path, "metadata", "imputation", ["cleaned_dataset"])
    register_artifact(run_root, "mice_decisions", decisions_path, "metadata", "imputation", ["cleaned_dataset"])
    return summary
```

- [ ] **Step 4: Add explicit config fields**

Modify `backend/workbench/config.py`:

```python
    imputation_method: str = ""
    imputation_m: int = 5
    imputation_max_iter: int = 10
```

This keeps config flat and compatible with the existing loader.

- [ ] **Step 5: Wire impute-only before model estimation**

In `backend/workbench/orchestrator.py`, import:

```python
from .imputation import run_mice_imputation
```

After statistical tests and before estimation, add:

```python
    modeling_frame = cleaned
    if config.imputation_method == "mice":
        imputation_summary = run_mice_imputation(
            cleaned,
            run_root,
            columns=[normalized_y, *normalized_x],
            m=config.imputation_m,
            max_iter=config.imputation_max_iter,
            random_seed=config.random_seed,
            max_missing_rate=config.max_missing_rate,
        )
        if imputation_summary.get("status") == "completed":
            modeling_frame = pd.read_parquet(run_root / "processed" / "imputed_dataset.parquet")
```

Then change estimation calls in this block from `cleaned` to `modeling_frame`. Do not change profiling, validation, statistical tests, or visualization input in this task.

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_imputation_mice.py tests/test_config_and_domain.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/imputation.py backend/workbench/config.py backend/workbench/orchestrator.py tests/test_imputation_mice.py
git commit -m "feat: add explicit MICE imputation preprocessing"
```

---

### Task 8: Add Explicit Prediction Models Behind The ML Extra

**Files:**
- Create: `backend/workbench/prediction.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_prediction_models.py`

- [ ] **Step 1: Write failing prediction tests**

Create `tests/test_prediction_models.py`:

```python
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json, write_json
from workbench.prediction import run_prediction_model


def _init_artifacts(run_root: Path) -> None:
    write_json(run_root / "artifacts_index.json", {"artifacts": []})


def test_run_prediction_model_writes_lightweight_artifact(tmp_path: Path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame({
        "y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "x1": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "x2": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    })

    result = run_prediction_model(
        frame,
        run_root,
        y="y",
        x=["x1", "x2"],
        model_type="prediction_ridge",
        model_id="prediction_ridge_1",
        cv_folds=10,
        random_seed=42,
    )

    assert result["model_type"] == "prediction_ridge"
    assert result["engine"] == "scikit-learn"
    assert result["cv_folds"] <= 5
    assert "predictions" not in result
    path = run_root / "prediction_results" / "prediction_ridge_1.json"
    assert path.is_file()
    saved = read_json(path)
    assert saved["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_prediction_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.prediction'`.

- [ ] **Step 3: Implement prediction helper**

Create `backend/workbench/prediction.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .econometrics.optional_deps import require_optional_dependency


def run_prediction_model(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    y: str,
    x: list[str],
    model_type: str,
    model_id: str,
    cv_folds: int = 5,
    random_seed: int = 20260429,
) -> dict[str, Any]:
    sklearn_model_selection = require_optional_dependency(
        "sklearn.model_selection",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_pipeline = require_optional_dependency(
        "sklearn.pipeline",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_preprocessing = require_optional_dependency(
        "sklearn.preprocessing",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_metrics = require_optional_dependency(
        "sklearn.metrics",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_linear = require_optional_dependency(
        "sklearn.linear_model",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_ensemble = require_optional_dependency(
        "sklearn.ensemble",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )

    data = frame[[y, *x]].dropna()
    X = data[x]
    target = data[y]
    folds = min(max(int(cv_folds), 2), 5, len(data))

    if model_type == "prediction_lasso":
        estimator = sklearn_linear.Lasso(alpha=1.0, random_state=random_seed, max_iter=5000)
    elif model_type == "prediction_ridge":
        estimator = sklearn_linear.Ridge(alpha=1.0)
    elif model_type == "prediction_random_forest":
        estimator = sklearn_ensemble.RandomForestRegressor(
            n_estimators=100,
            random_state=random_seed,
            n_jobs=1,
        )
    else:
        raise ValueError(f"Unsupported prediction model_type: {model_type}")

    pipeline = sklearn_pipeline.make_pipeline(
        sklearn_preprocessing.StandardScaler(),
        estimator,
    )
    X_train, X_test, y_train, y_test = sklearn_model_selection.train_test_split(
        X,
        target,
        test_size=0.25,
        random_state=random_seed,
    )
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    cv_scores = sklearn_model_selection.cross_val_score(
        pipeline,
        X,
        target,
        cv=folds,
        scoring="r2",
    )
    result = {
        "schema_version": 1,
        "model_id": model_id,
        "model_type": model_type,
        "engine": "scikit-learn",
        "status": "completed",
        "nobs": int(len(data)),
        "input_columns": {"y": y, "x": x},
        "cv_folds": int(folds),
        "metrics": {
            "test_r2": float(sklearn_metrics.r2_score(y_test, predictions)),
            "test_rmse": float(sklearn_metrics.mean_squared_error(y_test, predictions, squared=False)),
            "cv_r2_mean": float(cv_scores.mean()),
        },
        "warnings": [
            "Prediction results are not causal effects and are not regression inference."
        ],
    }
    output_dir = run_root / "prediction_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{model_id}.json"
    write_json(path, result)
    register_artifact(run_root, model_id, path, "prediction_result", "prediction", ["cleaned_dataset"])
    return result
```

- [ ] **Step 4: Add config fields**

Modify `backend/workbench/config.py`:

```python
    prediction_enabled: bool = False
    prediction_model_type: str = ""
    prediction_cv_folds: int = 5
```

- [ ] **Step 5: Wire prediction after primary model**

In `backend/workbench/orchestrator.py`, import:

```python
from .prediction import run_prediction_model
```

After diagnostics complete, add:

```python
    if config.prediction_enabled and config.prediction_model_type:
        prediction_model_id = f"{config.prediction_model_type}_1"
        run_prediction_model(
            modeling_frame if "modeling_frame" in locals() else cleaned,
            run_root,
            y=normalized_y,
            x=normalized_x,
            model_type=config.prediction_model_type,
            model_id=prediction_model_id,
            cv_folds=config.prediction_cv_folds,
            random_seed=config.random_seed,
        )
```

Do not add prediction results to narrative claims in this task.

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_prediction_models.py tests/test_config_and_domain.py -v
```

Expected: PASS if `scikit-learn` is installed. If not installed, run the missing-extra unit test path from Task 1 and install `.[ml]` before completing this task.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/prediction.py backend/workbench/config.py backend/workbench/orchestrator.py tests/test_prediction_models.py
git commit -m "feat: add explicit prediction model artifacts"
```

---

### Task 9: Add Imbalanced-Learn Prediction-Only Sampling

**Files:**
- Modify: `backend/workbench/prediction.py`
- Modify: `backend/workbench/config.py`
- Test: `tests/test_prediction_models.py`

- [ ] **Step 1: Write failing sampling test**

Append to `tests/test_prediction_models.py`:

```python
def test_prediction_sampling_requires_prediction_context(tmp_path: Path):
    from workbench.prediction import build_sampler

    sampler = build_sampler("", model_type="prediction_random_forest", random_seed=42)
    assert sampler is None

    try:
        build_sampler("smote", model_type="ols", random_seed=42)
    except ValueError as exc:
        assert "prediction-only" in str(exc)
    else:
        raise AssertionError("Expected prediction-only validation error")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_prediction_models.py::test_prediction_sampling_requires_prediction_context -v
```

Expected: FAIL because `build_sampler` is not defined.

- [ ] **Step 3: Add sampler helper**

Add to `backend/workbench/prediction.py`:

```python
def build_sampler(
    sampling_method: str,
    *,
    model_type: str,
    random_seed: int,
) -> Any | None:
    if not sampling_method:
        return None
    if not model_type.startswith("prediction_"):
        raise ValueError("Imbalanced sampling is prediction-only and cannot feed inference models.")
    imblearn_over = require_optional_dependency(
        "imblearn.over_sampling",
        extra="imbalanced",
        engine="imbalanced-learn",
        model_type=model_type,
        step="prediction",
    )
    imblearn_under = require_optional_dependency(
        "imblearn.under_sampling",
        extra="imbalanced",
        engine="imbalanced-learn",
        model_type=model_type,
        step="prediction",
    )
    if sampling_method == "smote":
        return imblearn_over.SMOTE(random_state=random_seed)
    if sampling_method == "oversample":
        return imblearn_over.RandomOverSampler(random_state=random_seed)
    if sampling_method == "undersample":
        return imblearn_under.RandomUnderSampler(random_state=random_seed)
    raise ValueError(f"Unsupported sampling method: {sampling_method}")
```

- [ ] **Step 4: Add config field**

Modify `backend/workbench/config.py`:

```python
    prediction_sampling_method: str = ""
```

- [ ] **Step 5: Thread sampling into prediction helper without using it for regression inference**

Change `run_prediction_model` signature:

```python
    sampling_method: str = "",
) -> dict[str, Any]:
```

Inside `run_prediction_model`, after train/test split:

```python
    sampler = build_sampler(
        sampling_method,
        model_type=model_type,
        random_seed=random_seed,
    )
    if sampler is not None:
        X_train, y_train = sampler.fit_resample(X_train, y_train)
```

Add to result:

```python
        "sampling_method": sampling_method or None,
```

In orchestrator, pass:

```python
            sampling_method=config.prediction_sampling_method,
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_prediction_models.py -v
```

Expected: PASS. Tests that need `imbalanced-learn` should be guarded with `pytest.importorskip("imblearn")` if a full sampling fit test is added.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/prediction.py backend/workbench/config.py backend/workbench/orchestrator.py tests/test_prediction_models.py
git commit -m "feat: add prediction-only imbalanced sampling"
```

---

### Task 10: Add Structured Model Failure Issues

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_advanced_econometrics.py`

- [ ] **Step 1: Write failing structured error test**

Append to `tests/test_advanced_econometrics.py`:

```python
def test_explicit_model_failure_records_structured_context(tmp_path: Path):
    project = create_project(tmp_path, "bad-probit-project")
    csv_path = tmp_path / "bad.csv"
    pd.DataFrame({
        "y": [0, 0, 0, 0, 0, 0] * 5,
        "x": list(range(30)),
    }).to_csv(csv_path, index=False)

    result = run_workflow(
        project.root,
        [csv_path],
        mode="auto",
        y="y",
        x=["x"],
        model_type="probit",
    )

    run_root = project.root / "runs" / result["run_id"]
    errors = read_json(run_root / "errors.json")
    issue = next(item for item in errors["issues"] if item["code"] == "MODEL_FIT_FAILED")
    assert issue["details"]["model_type"] == "probit"
    assert issue["details"]["model_id"] == "probit_1"
    assert issue["details"]["engine"] == "statsmodels"
    assert issue["details"]["step"] == "estimation"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_advanced_econometrics.py::test_explicit_model_failure_records_structured_context -v
```

Expected: FAIL because model failure details do not include structured model context.

- [ ] **Step 3: Add model context helper**

In `backend/workbench/orchestrator.py`, add:

```python
def _model_failure_details(
    *,
    model_type: str,
    model_id: str,
    engine: str,
    y: str,
    x: list[str],
) -> dict[str, Any]:
    return {
        "error_code": "MODEL_FIT_FAILED",
        "step": "estimation",
        "engine": engine,
        "model_type": model_type,
        "model_id": model_id,
        "y": y,
        "x": x,
    }
```

- [ ] **Step 4: Use helper in explicit model failures**

In the `except ValueError as exc:` block, replace details with:

```python
            {
                **_model_failure_details(
                    model_type=primary_requested_type,
                    model_id=primary_requested_model_id,
                    engine=primary_requested_engine,
                    y=normalized_y,
                    x=normalized_x,
                ),
                "message": str(exc),
                "effective_y_type": y_type,
            },
```

Before the estimation `try`, initialize:

```python
    primary_requested_type = model_type if model_type != "auto" else y_type
    primary_requested_model_id = "ols_1"
    primary_requested_engine = "statsmodels"
```

Inside each explicit branch, set the actual values before calling the model:

```python
            primary_requested_type = "probit"
            primary_requested_model_id = "probit_1"
            primary_requested_engine = "statsmodels"
```

Do the equivalent for Negative Binomial, GLM, PanelOLS, Logit, Poisson, and OLS branches.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_advanced_econometrics.py tests/test_orchestrator_e2e.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/orchestrator.py tests/test_advanced_econometrics.py
git commit -m "fix: record structured model failure context"
```

---

### Task 11: Update Documentation And Release Notes

**Files:**
- Create: `docs/v1.5.3.1-release-notes.md`
- Modify: `README.md`

- [ ] **Step 1: Add release notes**

Create `docs/v1.5.3.1-release-notes.md`:

````markdown
# V1.5.3.1 Release Notes

V1.5.3.1 is a backend-only analysis expansion release.

## Added

- Explicit `model_type` support for Probit, Negative Binomial, and selected GLM families.
- Optional `panel` extra for PanelOLS and IV2SLS model functions.
- Extended statistical tests: Spearman, Kendall, Mann-Whitney U, Kruskal-Wallis, Fisher exact, and FDR correction metadata.
- Explicit MICE imputation preprocessing with bounded iterations and separate imputation artifacts.
- Optional `ml` extra for prediction-only Lasso, Ridge, and RandomForest artifacts.
- Optional `imbalanced` extra for prediction-only sampling methods.

## Preserved

- Default `auto` still routes only to OLS, Logit, or Poisson.
- No frontend files changed.
- No causal inference execution.
- No model pickle artifacts.
- Graph lineage remains simple and backward-compatible.

## Install Extras

```bash
python3 -m pip install -e ".[panel]"
python3 -m pip install -e ".[ml]"
python3 -m pip install -e ".[imbalanced]"
```
````

- [ ] **Step 2: Update README backend usage**

Add after the existing CLI example in `README.md`:

````markdown
Run an explicit advanced backend model:

```bash
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv --y wage --x education --model-type negative_binomial
```

Default `--model-type auto` remains conservative and only selects OLS, Logit, or Poisson. Advanced models and prediction workflows must be explicitly requested or enabled in project config.
````

- [ ] **Step 3: Run docs status check**

Run:

```bash
git diff -- docs/v1.5.3.1-release-notes.md README.md
```

Expected: diff only contains V1.5.3.1 backend documentation.

- [ ] **Step 4: Commit**

```bash
git add docs/v1.5.3.1-release-notes.md README.md
git commit -m "docs: document V1.5.3.1 backend analysis expansion"
```

---

### Task 12: Final Verification

**Files:**
- No source changes expected unless verification finds a regression.

- [ ] **Step 1: Confirm no frontend files changed**

Run:

```bash
git diff --name-only HEAD~11..HEAD
```

Expected: no paths under `frontend/src/workbench/`, `frontend/src/lineage/`, or `frontend/package.json`.

- [ ] **Step 2: Run backend tests**

Run:

```bash
pytest -v
```

Expected: PASS. Optional-extra tests that require uninstalled extras should skip using `pytest.importorskip`.

- [ ] **Step 3: Run explicit smoke commands**

Create a temporary project and run existing auto:

```bash
workbench create /tmp workbench-v1531-smoke
workbench run /tmp/workbench-v1531-smoke examples/datasets/cross_section.csv --y wage --x education
```

Expected: run completes and writes the same default model family as before.

Run explicit advanced model:

```bash
workbench run /tmp/workbench-v1531-smoke examples/datasets/cross_section.csv --y wage --x education --model-type glm:poisson
```

Expected: run completes or writes a structured model-fit warning; it must not crash with an unstructured traceback.

- [ ] **Step 4: Inspect artifacts for large hidden output**

Run:

```bash
find /tmp/workbench-v1531-smoke/runs -name "*.pickle" -o -name "*.pkl"
```

Expected: no output.

Run:

```bash
find /tmp/workbench-v1531-smoke/runs -type f -size +20M
```

Expected: no large model, prediction, or imputation artifacts. Raw uploaded data may be present if the input itself is large; for the smoke fixture it should produce no output.

- [ ] **Step 5: Commit any verification fixes**

If verification required fixes, stage only the files changed by those fixes and use a focused commit message. For example, if the only fix is in orchestrator routing:

```bash
git add backend/workbench/orchestrator.py
git commit -m "fix: stabilize V1.5.3.1 backend analysis expansion"
```

If no fixes were required, do not create an empty commit.

## Self-Review Checklist

- [ ] The plan implements every spec section without adding frontend work.
- [ ] Default `auto` remains OLS/Logit/Poisson.
- [ ] Every optional extra has a missing-dependency path.
- [ ] MICE is explicit and does not overwrite the cleaned dataset.
- [ ] Prediction artifacts are isolated from inference claims.
- [ ] No step asks the worker to invent behavior without code guidance.
- [ ] Each task has a targeted test command and commit boundary.
