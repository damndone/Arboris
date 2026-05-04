# V1.2.4: Statistical Tests Package

## Start Point

Worktree: `.worktrees/workbench-v1.2.4-statistical-tests`  
Branch: `codex/workbench-v1.2.4-statistical-tests`  
Base commit: `1bab7e5` (`feat: V1.2.3 interactive submit — file preview, model routing, inline results`)

## Goal

Add a focused statistical tests package to the existing workflow:

- t-test
- ANOVA
- chi-square test
- Pearson correlation with p-value
- `statistical_tests/*.json` artifacts
- a "Statistical tests" section in the HTML/PDF report

This version does **not** add new model families, frontend controls, natural-language QA, or new visualization panels. Existing artifact download and report iframe surfaces are enough for V1.2.4.

---

## Scope

V1.2.4 **does**:

| # | Capability | Output |
|---|---|---|
| 1 | Pearson correlation for numeric variable pairs | `statistical_tests/correlations.json` |
| 2 | Welch two-sample t-test for numeric outcome vs binary categorical group | `statistical_tests/t_tests.json` |
| 3 | One-way ANOVA for numeric outcome vs multi-category group | `statistical_tests/anova.json` |
| 4 | Chi-square test for categorical variable pairs | `statistical_tests/chi_square.json` |
| 5 | Artifact registration for all four JSON files | artifact type `statistical_test` |
| 6 | Report section summarizing non-skipped test results | HTML/PDF report |

V1.2.4 **does not**:

- Add Logit, Poisson, ARIMA, VAR, or new model routing
- Add VIF, Cook's distance, leverage, BP/DW/JB tests
- Add a frontend statistical tests table
- Add per-model diagnostic figures
- Add a backend `/preview` API
- Add natural-language question answering

---

## Design Approach

Use a small backend module:

`backend/workbench/statistical_tests.py`

The module runs tests against the cleaned dataframe after model column validation. It uses the selected analysis variables, not every column in the dataset:

```python
analysis_columns = [normalized_y, *normalized_x]
```

This keeps results relevant to the user's chosen analysis and avoids generating noisy reports for unrelated columns.

The orchestrator writes four JSON files on every completed workflow. Each file may contain an empty `results` list if no valid variable combination exists. Empty files are still useful because they make the artifact contract stable and show that the test type was considered.

---

## Statistical Test Rules

### Type Classification

The engine uses dataframe dtypes and cardinality:

| Classification | Rule |
|---|---|
| numeric | `pandas.api.types.is_numeric_dtype(series)` |
| categorical | non-numeric, or numeric with `nunique <= 20` and not all values unique |
| binary categorical | categorical with exactly 2 non-null values |
| multi categorical | categorical with 3 to 20 non-null values |

The `20` category threshold is a local constant, not user-configurable in V1.2.4.

### Correlations

Run Pearson correlation for every numeric pair in `analysis_columns`.

Minimum valid rows: 3 pairwise non-null observations.

Output row:

```json
{
  "test_id": "correlation:y:x",
  "test_type": "pearson_correlation",
  "variables": ["y", "x"],
  "nobs": 35,
  "statistic": 0.98,
  "p_value": 0.0001,
  "effect": {"r": 0.98},
  "source_id": "statistical_tests.correlations.y.x"
}
```

### T-tests

Run Welch two-sample t-test for each numeric variable against each binary categorical variable in `analysis_columns`.

This covers common cases such as `y` by treatment group. It is not restricted to `y` only, because the selected `x` variables may also include numeric covariates worth comparing by a binary group.

Minimum valid rows: at least 2 observations per group.

Output row:

```json
{
  "test_id": "t_test:y:treatment",
  "test_type": "welch_t_test",
  "outcome": "y",
  "group": "treatment",
  "groups": ["control", "treated"],
  "nobs": 40,
  "statistic": -2.41,
  "p_value": 0.021,
  "effect": {
    "mean_control": 10.2,
    "mean_treated": 12.8,
    "difference": 2.6
  },
  "source_id": "statistical_tests.t_tests.y.treatment"
}
```

### ANOVA

Run one-way ANOVA for each numeric variable against each multi-category variable in `analysis_columns`.

Minimum valid rows: at least 2 observations in at least 2 groups.

Output row:

```json
{
  "test_id": "anova:y:region",
  "test_type": "one_way_anova",
  "outcome": "y",
  "group": "region",
  "groups": ["north", "south", "west"],
  "nobs": 60,
  "statistic": 5.14,
  "p_value": 0.009,
  "effect": {
    "group_means": {"north": 10.1, "south": 12.4, "west": 15.0}
  },
  "source_id": "statistical_tests.anova.y.region"
}
```

### Chi-square

Run chi-square tests for every categorical pair in `analysis_columns`.

Minimum valid rows: at least 2 rows after pairwise non-null filtering, and a contingency table with at least 2 rows and 2 columns.

Output row:

```json
{
  "test_id": "chi_square:treatment:region",
  "test_type": "chi_square",
  "variables": ["treatment", "region"],
  "nobs": 60,
  "statistic": 7.21,
  "p_value": 0.027,
  "degrees_of_freedom": 2,
  "effect": {
    "contingency_table": {
      "control": {"north": 10, "south": 8, "west": 12},
      "treated": {"north": 4, "south": 14, "west": 12}
    }
  },
  "source_id": "statistical_tests.chi_square.treatment.region"
}
```

---

## JSON Artifact Contract

Each file uses the same top-level shape:

```json
{
  "schema_version": 1,
  "test_type": "correlations",
  "results": []
}
```

Files:

| File | Artifact ID | Artifact Type | Step |
|---|---|---|---|
| `statistical_tests/correlations.json` | `statistical_tests_correlations` | `statistical_test` | `statistical_tests` |
| `statistical_tests/t_tests.json` | `statistical_tests_t_tests` | `statistical_test` | `statistical_tests` |
| `statistical_tests/anova.json` | `statistical_tests_anova` | `statistical_test` | `statistical_tests` |
| `statistical_tests/chi_square.json` | `statistical_tests_chi_square` | `statistical_test` | `statistical_tests` |

The source ids are stable strings under `statistical_tests.<family>...`; report entries refer to these source ids.

---

## Orchestrator Integration

Add a new workflow step between `model_check` and `estimation`.

Current sequence:

```text
model_check -> estimation -> visualization -> narrative -> reporting
```

V1.2.4 sequence:

```text
model_check -> statistical_tests -> estimation -> visualization -> narrative -> reporting
```

The SSE step list in `frontend/src/runResult.tsx` must add `statistical_tests` between "Model check" and "Estimation" so live progress does not silently skip a backend phase.

Pseudocode:

```python
if _s: _s("statistical_tests", "start", "Running statistical tests...")
statistical_tests = run_statistical_tests(
    cleaned,
    analysis_columns=[normalized_y, *normalized_x],
)
write_statistical_test_artifacts(run_root, statistical_tests)
if _s: _s("statistical_tests", "complete", "Statistical tests completed")
```

The statistical test step is non-blocking. If an individual variable pair is not valid for a test, the engine skips that pair. Unexpected engine exceptions should fail the workflow, because malformed statistical output would make the report misleading.

---

## Report Integration

The report object gains:

```python
"statistical_tests": summarize_statistical_tests(statistical_tests)
```

Each summary row:

```python
{
    "label": "Pearson correlation: y vs x",
    "statistic": 0.98,
    "p_value": 0.0001,
    "interpretation": "Strong positive association; p < 0.001.",
    "source_id": "statistical_tests.correlations.y.x",
}
```

Template change:

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

PDF export currently renders report sections through `exports.py`. V1.2.4 should add a "Statistical tests" section there too, using the same `report["statistical_tests"]` list.

---

## File Changes

| # | File | Type | Responsibility |
|---|---|---|---|
| 1 | `backend/workbench/statistical_tests.py` | Create | Test engine, JSON artifact writer, report summarizer |
| 2 | `backend/workbench/orchestrator.py` | Modify | Run statistical test step and pass summaries into report |
| 3 | `backend/workbench/templates/report.html.j2` | Modify | Add "Statistical tests" report section |
| 4 | `backend/workbench/exports.py` | Modify | Add "Statistical tests" PDF section |
| 5 | `frontend/src/runResult.tsx` | Modify | Add `statistical_tests` progress step label |
| 6 | `tests/test_statistical_tests.py` | Create | Unit tests for all four statistical test families |
| 7 | `tests/test_orchestrator_e2e.py` | Modify | Assert statistical test artifacts are written in workflow |
| 8 | `tests/test_reporting_exports.py` | Modify | Assert HTML/PDF report includes statistical test section and source ids |
| 9 | `frontend/src/App.test.tsx` | Modify | Assert live progress list includes "Statistical tests" for running runs |
| 10 | `docs/superpowers/specs/2026-05-04-workbench-v1.2.4-statistical-tests-design.md` | Create | This spec |

---

## Testing Strategy

### Unit Tests

`tests/test_statistical_tests.py`:

- Pearson correlation returns r and p-value for two numeric variables
- Welch t-test returns group means and p-value for numeric outcome by binary group
- One-way ANOVA returns group means and p-value for numeric outcome by 3 groups
- Chi-square returns contingency table, dof, statistic, and p-value for two categorical variables
- Insufficient data skips invalid pairs without raising

### E2E Tests

`tests/test_orchestrator_e2e.py`:

- A mixed dataset writes all four `statistical_tests/*.json` files
- Artifact index contains all four `statistical_test` artifacts
- At least one result exists in each JSON family for the mixed fixture
- Workflow status remains `completed`

### Reporting Tests

`tests/test_reporting_exports.py`:

- HTML report renders `<h2>Statistical tests</h2>`
- HTML includes `data-source-id` for statistical test rows
- PDF contains the "Statistical tests" section title

### Frontend Tests

`frontend/src/App.test.tsx`:

- Running run progress panel includes "Statistical tests" between "Model check" and "Estimation"

No dedicated frontend statistical result table is required for V1.2.4.

---

## Known Tradeoffs

- Statistical tests are selected from the current analysis variables (`y + x`), not all dataset columns.
- The report summarizes only non-empty results. Empty artifact files still exist.
- No multiple-testing correction in V1.2.4. The report should not overstate p-values as causal evidence.
- Categorical detection uses cardinality heuristics. A backend `/preview` or schema API can replace this later.
- Statistical tests run before model estimation, but after model column validation, so blocked model-column runs do not write statistical test artifacts.

---

## Success Criteria

- `tests/test_statistical_tests.py` covers t-test, ANOVA, chi-square, and correlation p-values.
- `tests/test_orchestrator_e2e.py` proves all four JSON files are emitted and registered as artifacts.
- `tests/test_reporting_exports.py` proves the report has a "Statistical tests" section with source ids.
- `frontend/src/App.test.tsx` proves the new workflow step is visible in progress UI.
- Full backend suite passes except the already-known independent `test_acceptance_templates.py` path issue if it is still present.
- Full frontend suite passes.
