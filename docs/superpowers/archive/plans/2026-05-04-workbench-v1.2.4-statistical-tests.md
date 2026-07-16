# Workbench V1.2.4 Statistical Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add t-test, ANOVA, chi-square, and Pearson correlation p-value outputs to the workflow as JSON artifacts and report sections.

**Architecture:** Add a focused `backend/workbench/statistical_tests.py` module that computes tests over the selected analysis variables (`y + x`) and writes four stable JSON artifact files. Integrate it into `orchestrator.py` after model column validation and before estimation, then pass summarized results into HTML/PDF reports. Update the existing progress UI with one new `statistical_tests` step; do not add a dedicated frontend results table in V1.2.4.

**Tech Stack:** Python 3.11+, pandas, scipy.stats, FastAPI workflow artifacts, Jinja2 report templates, reportlab PDF export, pytest, React 18, Vitest.

---

## File Structure

**Backend:**
- Create: `backend/workbench/statistical_tests.py` — statistical test engine, artifact writer, report summarizer
- Modify: `backend/workbench/orchestrator.py` — invoke the new test step and add results to report
- Modify: `backend/workbench/templates/report.html.j2` — render "Statistical tests" section
- Modify: `backend/workbench/exports.py` — include "Statistical tests" in PDF export

**Frontend:**
- Modify: `frontend/src/runResult.tsx` — add the `statistical_tests` progress step label
- Modify: `frontend/src/App.test.tsx` — cover the visible progress step for running runs

**Tests:**
- Create: `tests/test_statistical_tests.py` — unit tests for all four test families
- Modify: `tests/test_orchestrator_e2e.py` — assert JSON files and artifacts are emitted
- Modify: `tests/test_reporting_exports.py` — assert report section and source ids render

---

### Task 1: Statistical Test Engine

**Files:**
- Create: `backend/workbench/statistical_tests.py`
- Create: `tests/test_statistical_tests.py`

- [ ] **Step 1: Write failing unit tests for all four statistical families**

Create `tests/test_statistical_tests.py`:

```python
import math

import pandas as pd

from workbench.statistical_tests import run_statistical_tests


def test_correlation_reports_pearson_p_value():
    frame = pd.DataFrame({
        "y": [1, 2, 3, 4, 5, 6],
        "x": [2, 4, 6, 8, 10, 12],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "x"])

    row = results["correlations"]["results"][0]
    assert row["test_type"] == "pearson_correlation"
    assert row["variables"] == ["y", "x"]
    assert row["nobs"] == 6
    assert row["statistic"] > 0.99
    assert row["p_value"] < 0.001
    assert row["source_id"] == "statistical_tests.correlations.y.x"


def test_t_test_reports_group_means_and_p_value():
    frame = pd.DataFrame({
        "y": [1.0, 1.2, 1.1, 5.0, 5.2, 5.1],
        "treatment": ["control", "control", "control", "treated", "treated", "treated"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "treatment"])

    row = results["t_tests"]["results"][0]
    assert row["test_type"] == "welch_t_test"
    assert row["outcome"] == "y"
    assert row["group"] == "treatment"
    assert row["groups"] == ["control", "treated"]
    assert row["effect"]["mean_control"] == 1.1
    assert row["effect"]["mean_treated"] == 5.1
    assert row["effect"]["difference"] == 4.0
    assert row["p_value"] < 0.01


def test_anova_reports_group_means_and_p_value():
    frame = pd.DataFrame({
        "y": [1, 2, 1, 5, 6, 5, 9, 10, 9],
        "region": ["north", "north", "north", "south", "south", "south", "west", "west", "west"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "region"])

    row = results["anova"]["results"][0]
    assert row["test_type"] == "one_way_anova"
    assert row["outcome"] == "y"
    assert row["group"] == "region"
    assert row["groups"] == ["north", "south", "west"]
    assert row["effect"]["group_means"]["north"] == 4 / 3
    assert row["p_value"] < 0.01


def test_chi_square_reports_contingency_table_and_p_value():
    frame = pd.DataFrame({
        "treatment": ["control"] * 10 + ["treated"] * 10,
        "region": ["north"] * 8 + ["south"] * 2 + ["north"] * 2 + ["south"] * 8,
    })

    results = run_statistical_tests(frame, analysis_columns=["treatment", "region"])

    row = results["chi_square"]["results"][0]
    assert row["test_type"] == "chi_square"
    assert row["variables"] == ["treatment", "region"]
    assert row["degrees_of_freedom"] == 1
    assert row["effect"]["contingency_table"]["control"]["north"] == 8
    assert row["effect"]["contingency_table"]["treated"]["south"] == 8
    assert row["p_value"] < 0.05


def test_invalid_pairs_are_skipped_without_nan_output():
    frame = pd.DataFrame({
        "y": [1.0, None],
        "x": [2.0, None],
        "group": ["a", "a"],
    })

    results = run_statistical_tests(frame, analysis_columns=["y", "x", "group"])

    for family in results.values():
        assert family["schema_version"] == 1
        assert isinstance(family["results"], list)
        for row in family["results"]:
            assert not any(
                isinstance(value, float) and math.isnan(value)
                for value in row.values()
            )
```

- [ ] **Step 2: Run tests and verify they fail because the module does not exist**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_statistical_tests.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench.statistical_tests'`.

- [ ] **Step 3: Implement `backend/workbench/statistical_tests.py`**

Create `backend/workbench/statistical_tests.py`:

```python
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd
from scipy import stats

from .artifacts import register_artifact, write_json

CATEGORY_MAX_UNIQUE = 20

TEST_FAMILIES = {
    "correlations": "correlations.json",
    "t_tests": "t_tests.json",
    "anova": "anova.json",
    "chi_square": "chi_square.json",
}


def run_statistical_tests(
    frame: pd.DataFrame,
    *,
    analysis_columns: list[str],
) -> dict[str, dict[str, Any]]:
    columns = [column for column in analysis_columns if column in frame.columns]
    results: dict[str, dict[str, Any]] = {
        name: {"schema_version": 1, "test_type": name, "results": []}
        for name in TEST_FAMILIES
    }
    numeric = [column for column in columns if _is_numeric(frame[column])]
    categorical = [column for column in columns if _is_categorical(frame[column])]
    binary = [column for column in categorical if _non_null_unique(frame[column]) == 2]
    multi = [
        column for column in categorical
        if 3 <= _non_null_unique(frame[column]) <= CATEGORY_MAX_UNIQUE
    ]

    for left, right in combinations(numeric, 2):
        row = _pearson(frame, left, right)
        if row is not None:
            results["correlations"]["results"].append(row)

    for outcome in numeric:
        for group in binary:
            row = _welch_t_test(frame, outcome, group)
            if row is not None:
                results["t_tests"]["results"].append(row)

    for outcome in numeric:
        for group in multi:
            row = _anova(frame, outcome, group)
            if row is not None:
                results["anova"]["results"].append(row)

    for left, right in combinations(categorical, 2):
        row = _chi_square(frame, left, right)
        if row is not None:
            results["chi_square"]["results"].append(row)

    return results


def write_statistical_test_artifacts(
    run_root: Path,
    results: dict[str, dict[str, Any]],
) -> None:
    tests_dir = run_root / "statistical_tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    for family, filename in TEST_FAMILIES.items():
        path = tests_dir / filename
        write_json(path, results[family])
        register_artifact(
            run_root,
            f"statistical_tests_{family}",
            path,
            "statistical_test",
            "statistical_tests",
            ["cleaned_dataset"],
        )


def summarize_statistical_tests(
    results: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for family in ("correlations", "t_tests", "anova", "chi_square"):
        for row in results.get(family, {}).get("results", []):
            summaries.append(_summary_row(row))
    return summaries
```

Add helper functions in the same file:

```python
def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series)


def _non_null_unique(series: pd.Series) -> int:
    return int(series.dropna().nunique())


def _is_categorical(series: pd.Series) -> bool:
    if _is_numeric(series):
        unique = _non_null_unique(series)
        return 2 <= unique <= CATEGORY_MAX_UNIQUE and unique < len(series.dropna())
    return 2 <= _non_null_unique(series) <= CATEGORY_MAX_UNIQUE


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _pairwise(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame[columns].dropna()
```

Add test implementations:

```python
def _pearson(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 3:
        return None
    statistic, p_value = stats.pearsonr(pair[left], pair[right])
    return {
        "test_id": f"correlation:{left}:{right}",
        "test_type": "pearson_correlation",
        "variables": [left, right],
        "nobs": int(len(pair)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"r": _safe_float(statistic)},
        "source_id": f"statistical_tests.correlations.{left}.{right}",
    }


def _welch_t_test(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_values = sorted(pair[group].dropna().unique().tolist(), key=str)
    if len(group_values) != 2:
        return None
    left = pd.to_numeric(pair.loc[pair[group] == group_values[0], outcome], errors="coerce").dropna()
    right = pd.to_numeric(pair.loc[pair[group] == group_values[1], outcome], errors="coerce").dropna()
    if len(left) < 2 or len(right) < 2:
        return None
    statistic, p_value = stats.ttest_ind(left, right, equal_var=False)
    mean_left = float(left.mean())
    mean_right = float(right.mean())
    return {
        "test_id": f"t_test:{outcome}:{group}",
        "test_type": "welch_t_test",
        "outcome": outcome,
        "group": group,
        "groups": [str(group_values[0]), str(group_values[1])],
        "nobs": int(len(left) + len(right)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {
            f"mean_{group_values[0]}": mean_left,
            f"mean_{group_values[1]}": mean_right,
            "difference": mean_right - mean_left,
        },
        "source_id": f"statistical_tests.t_tests.{outcome}.{group}",
    }
```

Add ANOVA, chi-square, and summary helpers:

```python
def _anova(frame: pd.DataFrame, outcome: str, group: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [outcome, group])
    group_values = sorted(pair[group].dropna().unique().tolist(), key=str)
    samples = [
        pd.to_numeric(pair.loc[pair[group] == value, outcome], errors="coerce").dropna()
        for value in group_values
    ]
    samples = [sample for sample in samples if len(sample) >= 2]
    if len(samples) < 2:
        return None
    statistic, p_value = stats.f_oneway(*samples)
    group_means = {
        str(value): float(pd.to_numeric(pair.loc[pair[group] == value, outcome], errors="coerce").mean())
        for value in group_values
    }
    return {
        "test_id": f"anova:{outcome}:{group}",
        "test_type": "one_way_anova",
        "outcome": outcome,
        "group": group,
        "groups": [str(value) for value in group_values],
        "nobs": int(sum(len(sample) for sample in samples)),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "effect": {"group_means": group_means},
        "source_id": f"statistical_tests.anova.{outcome}.{group}",
    }


def _chi_square(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any] | None:
    pair = _pairwise(frame, [left, right])
    if len(pair) < 2:
        return None
    table = pd.crosstab(pair[left], pair[right])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    statistic, p_value, dof, _expected = stats.chi2_contingency(table)
    return {
        "test_id": f"chi_square:{left}:{right}",
        "test_type": "chi_square",
        "variables": [left, right],
        "nobs": int(table.to_numpy().sum()),
        "statistic": _safe_float(statistic),
        "p_value": _safe_float(p_value),
        "degrees_of_freedom": int(dof),
        "effect": {
            "contingency_table": {
                str(index): {str(column): int(value) for column, value in row.items()}
                for index, row in table.to_dict(orient="index").items()
            }
        },
        "source_id": f"statistical_tests.chi_square.{left}.{right}",
    }


def _p_value_text(p_value: float | None) -> str:
    if p_value is None:
        return "p-value unavailable"
    if p_value < 0.001:
        return "p < 0.001"
    return f"p = {p_value:.3f}"


def _summary_row(row: dict[str, Any]) -> dict[str, Any]:
    p_value = row.get("p_value")
    statistic = row.get("statistic")
    test_type = row.get("test_type")
    if test_type == "pearson_correlation":
        label = f"Pearson correlation: {row['variables'][0]} vs {row['variables'][1]}"
    elif test_type == "welch_t_test":
        label = f"Welch t-test: {row['outcome']} by {row['group']}"
    elif test_type == "one_way_anova":
        label = f"ANOVA: {row['outcome']} by {row['group']}"
    else:
        label = f"Chi-square: {row['variables'][0]} vs {row['variables'][1]}"
    return {
        "label": label,
        "statistic": statistic,
        "p_value": p_value,
        "interpretation": f"Statistic {statistic:.4f}; {_p_value_text(p_value)}."
        if statistic is not None
        else _p_value_text(p_value),
        "source_id": row["source_id"],
    }
```

- [ ] **Step 4: Run unit tests and verify they pass**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_statistical_tests.py -q
```

Expected: PASS, 5 tests.

---

### Task 2: Orchestrator Artifacts

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `frontend/src/runResult.tsx`
- Modify: `tests/test_orchestrator_e2e.py`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add failing e2e test for statistical test artifacts**

Append to `tests/test_orchestrator_e2e.py`:

```python
def test_run_workflow_writes_statistical_test_artifacts(tmp_path: Path):
    rows = []
    for i in range(60):
        rows.append(
            {
                "y": float(i) + (5 if i % 2 else 0),
                "x_num": float(i),
                "treatment": "treated" if i % 2 else "control",
                "region": ["north", "south", "west"][i % 3],
            }
        )
    source = tmp_path / "mixed.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x_num", "treatment", "region"],
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    expected_files = {
        "correlations": run_root / "statistical_tests" / "correlations.json",
        "t_tests": run_root / "statistical_tests" / "t_tests.json",
        "anova": run_root / "statistical_tests" / "anova.json",
        "chi_square": run_root / "statistical_tests" / "chi_square.json",
    }
    for family, path in expected_files.items():
        assert path.exists()
        payload = read_json(path)
        assert payload["schema_version"] == 1
        assert payload["test_type"] == family
        assert payload["results"]

    artifact_ids = {
        artifact["artifact_id"]
        for artifact in read_json(run_root / "artifacts_index.json")["artifacts"]
    }
    assert {
        "statistical_tests_correlations",
        "statistical_tests_t_tests",
        "statistical_tests_anova",
        "statistical_tests_chi_square",
    }.issubset(artifact_ids)
```

- [ ] **Step 2: Add failing frontend progress test**

Append to `frontend/src/App.test.tsx` or update the existing running-result fixture:

```typescript
test("running run progress includes statistical tests step", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      run_id: "running-1",
      status: "running",
      mode: "auto",
      started_at: "2026-05-04T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: {},
      errors: { issues: [] },
      model_results: [],
    }),
  } as Response);
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ groups: [] }),
  } as Response);

  renderAt("/runs/running-1?project_root=/tmp/demo");

  await waitFor(() => {
    expect(screen.getByLabelText("run progress")).toBeInTheDocument();
  });
  expect(screen.getByText("Statistical tests")).toBeInTheDocument();
});
```

This test may require stubbing `EventSource` in the file if the existing test setup does not already do it:

```typescript
class MockEventSource {
  close = vi.fn();
  addEventListener = vi.fn();
}
vi.stubGlobal("EventSource", MockEventSource);
```

- [ ] **Step 3: Run targeted tests and verify they fail**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_orchestrator_e2e.py::test_run_workflow_writes_statistical_test_artifacts -q
cd frontend && npm test -- src/App.test.tsx
```

Expected:
- Backend test fails because no `statistical_tests` files are written.
- Frontend test fails because the progress list has no "Statistical tests" label.

- [ ] **Step 4: Wire statistical tests into `orchestrator.py`**

Modify imports:

```python
from .statistical_tests import (
    run_statistical_tests,
    summarize_statistical_tests,
    write_statistical_test_artifacts,
)
```

After model column validation succeeds and before estimation starts, add:

```python
    if _s:
        _s("statistical_tests", "start", "Running statistical tests...")
    statistical_tests = run_statistical_tests(
        cleaned,
        analysis_columns=[normalized_y, *normalized_x],
    )
    write_statistical_test_artifacts(run_root, statistical_tests)
    statistical_test_summaries = summarize_statistical_tests(statistical_tests)
    if _s:
        _s("statistical_tests", "complete", "Statistical tests completed")
```

Then add the summaries to the report dict:

```python
        "statistical_tests": statistical_test_summaries,
```

- [ ] **Step 5: Add progress step to `frontend/src/runResult.tsx`**

Insert this item between `model_check` and `estimation`:

```typescript
{ step: "statistical_tests", label: "Statistical tests", status: "pending" },
```

- [ ] **Step 6: Run targeted tests and verify they pass**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_orchestrator_e2e.py::test_run_workflow_writes_statistical_test_artifacts -q
cd frontend && npm test -- src/App.test.tsx
```

Expected:
- Backend targeted test passes.
- Frontend App tests pass.

---

### Task 3: Report Integration

**Files:**
- Modify: `backend/workbench/templates/report.html.j2`
- Modify: `backend/workbench/exports.py`
- Modify: `tests/test_reporting_exports.py`

- [ ] **Step 1: Add failing report rendering test**

Append to `tests/test_reporting_exports.py`:

```python
def test_report_renders_statistical_tests_section(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": [],
        "claims": [],
        "statistical_tests": [
            {
                "label": "Pearson correlation: y vs x",
                "statistic": 0.98,
                "p_value": 0.001,
                "interpretation": "Statistic 0.9800; p = 0.001.",
                "source_id": "statistical_tests.correlations.y.x",
            }
        ],
        "warnings": [],
    }

    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)

    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Statistical tests</h2>" in html
    assert "Pearson correlation: y vs x" in html
    assert 'data-source-id="statistical_tests.correlations.y.x"' in html
    assert b"Statistical tests" in pdf_path.read_bytes()
```

- [ ] **Step 2: Run report test and verify it fails**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_reporting_exports.py::test_report_renders_statistical_tests_section -q
```

Expected: FAIL because the HTML/PDF templates do not render statistical tests yet.

- [ ] **Step 3: Update HTML report template**

In `backend/workbench/templates/report.html.j2`, insert after the Interpretation section and before Warnings:

```html
    {% if report.statistical_tests %}
    <section>
      <h2>Statistical tests</h2>
      <ul>
        {% for test in report.statistical_tests %}
        <li>
          {{ test.label }}: {{ test.interpretation }}
          <span data-source-id="{{ test.source_id }}">Source: {{ test.source_id }}</span>
        </li>
        {% endfor %}
      </ul>
    </section>
    {% endif %}
```

- [ ] **Step 4: Update PDF export**

In `backend/workbench/exports.py`, add a call after the existing Interpretation section:

```python
y = _draw_section(pdf, "Statistical tests", report.get("statistical_tests", []), y)
```

If `_draw_section` only looks for `claim` or `message`, update its text extraction to:

```python
text = str(
    item.get("claim")
    or item.get("interpretation")
    or item.get("message")
    or item.get("label")
    or ""
)
if item.get("label") and item.get("interpretation"):
    text = f"{item['label']}: {item['interpretation']}"
```

- [ ] **Step 5: Run report test and verify it passes**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_reporting_exports.py::test_report_renders_statistical_tests_section -q
```

Expected: PASS.

---

### Task 4: Full Verification and Documentation Check

**Files:**
- Verify only

- [ ] **Step 1: Run statistical tests unit suite**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_statistical_tests.py -q
```

Expected: PASS.

- [ ] **Step 2: Run backend targeted suites**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests/test_orchestrator_e2e.py tests/test_reporting_exports.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```bash
cd frontend && npm test
```

Expected: PASS.

- [ ] **Step 4: Run full backend tests**

Run:

```bash
../workbench-v1.2.1-browsing/.venv/bin/python -m pytest tests -q
```

Expected: PASS, except if `test_acceptance_templates.py` still fails due to the pre-existing relative-path issue. If it fails, capture the exact failing test and confirm it is the known path issue before proceeding.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd frontend && npx vite build
```

Expected: build succeeds. The existing large chunk warning from `xlsx` is acceptable.

- [ ] **Step 6: Review changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected changed files are scoped to:

```text
backend/workbench/statistical_tests.py
backend/workbench/orchestrator.py
backend/workbench/templates/report.html.j2
backend/workbench/exports.py
frontend/src/runResult.tsx
frontend/src/App.test.tsx
tests/test_statistical_tests.py
tests/test_orchestrator_e2e.py
tests/test_reporting_exports.py
docs/superpowers/specs/2026-05-04-workbench-v1.2.4-statistical-tests-design.md
docs/superpowers/plans/2026-05-04-workbench-v1.2.4-statistical-tests.md
```

No unrelated refactors or frontend table features should be included in V1.2.4.
