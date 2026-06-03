# V1.5.4.1 — UI ↔ V1.5.3.2 Backend Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the UI gap to V1.5.3.2 backend capabilities (explicit model_type, MICE imputation, structured failure) using a capability-manifest driven approach — so future new models / imputation methods need backend registration only, zero frontend changes.

**Architecture:** Backend exposes `GET /capabilities` derived from V1.5.4's `MODEL_REGISTRY` + new `IMPUTATION_REGISTRY`; frontend renders the run-form controls (model_type, MICE toggle) and the post-run failure card dynamically from this manifest. `failure_evidence` carries a structured `recommended_actions: list[dict]` array (1.5.4 spec §2.5's first real producer); frontend renders action buttons from this array with `form_overrides` enabling one-click recovery. Delivered in **4 slices** (Contract First → Backend // Frontend parallel → Integration), **12 atomic PRs**.

**Tech Stack:** Python 3.11 + FastAPI + pytest + jsonschema (new); TypeScript + React + vitest. Backend at `backend/workbench/`, tests at `tests/`. Frontend at `frontend/src/`, tests via `cd frontend && npx vitest run`.

**Spec:** `docs/superpowers/specs/2026-06-03-workbench-v1.5.4.1-frontend-backend-gap-design.md`

---

## File Structure

**Slice 1 — Contracts (new docs + sample fixtures + schema tests):**
- `docs/api-contracts/capabilities.md` — endpoint description + JSON Schema
- `docs/api-contracts/recommended-actions.md` — schema for `failure_evidence.recommended_actions[]`
- `docs/api-contracts/imputation-summary.md` — schema for `imputation_summary.json`
- `docs/api-contracts/runs-post.md` — `/runs` POST form fields table
- `tests/contracts/capabilities.sample.json`, `recommended_actions.model_fit_failure.sample.json`, `imputation_summary.mice.sample.json`
- `tests/contracts/test_schema_capabilities.py`, `test_schema_recommended_actions.py`, `test_schema_imputation_summary.py`

**Slice 2 — Backend (new modules + edits):**
- New: `backend/workbench/engine/imputation_registry.py` — `ImputationMethod` dataclass + `IMPUTATION_REGISTRY` + `register_imputation_method`
- New: `backend/workbench/engine/capabilities.py` — `build_capabilities() -> dict` pure function
- New: `backend/workbench/engine/recommended_actions.py` — factory functions `actions_for_model_fit_failure(...)`, `actions_for_unsupported_model_type(...)`, `actions_for_panel_fields_missing(...)`
- Modify: `backend/workbench/api.py` — add `GET /capabilities` route; add `imputation: str = Form("")` form field to `/runs`; thread through `_bg_run`
- Modify: `backend/workbench/orchestrator.py` — `run_workflow` add `imputation: dict | None = None` keyword arg; thread to `_run_workflow` → ctx
- Modify: `backend/workbench/engine/stages/imputation.py` — register MICE method; read `ctx.artifacts["_imputation_request"]` ahead of `config.imputation_method`; **write `imputation_summary.json` to disk + `register_artifact`**
- Modify: `backend/workbench/engine/stages/estimation.py` — inject `recommended_actions` into `failure_evidence` at both failure branches (explicit + auto-fallback)
- Modify: `backend/workbench/cli.py` — add `--imputation TEXT` option (parses `mice` or JSON)

**Slice 3 — Frontend (new components + edits):**
- New: `frontend/src/capabilities/types.ts`, `api.ts`, `useCapabilities.ts` — fetch `/capabilities`, cache, TS types
- New: `frontend/src/runForm/ModelTypeSelect.tsx` — `<optgroup>` dropdown from capabilities
- New: `frontend/src/runForm/ImputationControls.tsx` — checkbox or select based on `imputation_methods.length`
- New: `frontend/src/runResult/FailureCard.tsx` — story card + action buttons from `recommended_actions`
- New: `frontend/src/runResult/ImputationSummary.tsx` — blue panel from `imputation_summary.json`
- Modify: `frontend/src/api.ts` — `runWorkflow` add `imputation?: string` param; types augmented
- Modify: `frontend/src/App.tsx` — replace hard-coded model_type `<select>` with `<ModelTypeSelect>`; add `<ImputationControls>`; pass `imputation` to `runWorkflow`
- Modify: `frontend/src/runResult.tsx` — insert `<FailureCard>` when status=failed and MODEL_FIT_FAILED present; insert `<ImputationSummary>` when `imputation_summary` artifact exists

**Slice 4 — Integration:**
- Modify: `frontend/src/capabilities/useCapabilities.ts` — switch mock-to-real `/capabilities` fetch (already real, just verified end-to-end)
- New: e2e test for failure recovery flow (Playwright or vitest+jsdom)
- Modify: `docs/extensions.md` — add "How to ship a new model_type / imputation_method that auto-appears in the UI" section + C-plan upgrade memo

---

## Phase 0 — Worktree + venv bootstrap

### Task 0: Create isolated worktree, branch, venv

- [ ] **Step 1: Create the worktree off V1.5.4 tip**

Run (from main repo root `/Users/jiayuanren/项目规划`):
```bash
git worktree add .worktrees/workbench-v1.5.4.1 -b workbench-v1.5.4.1 workbench-v1.5.4
```
Expected: `Preparing worktree (new branch 'workbench-v1.5.4.1')`, checked out at `abe7fda`.

- [ ] **Step 2: Build venv + install jsonschema**

Run:
```bash
cd .worktrees/workbench-v1.5.4.1
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
.venv/bin/pip install jsonschema
```
Expected: install completes. Verify: `.venv/bin/python -c "import jsonschema; print(jsonschema.__version__)"` prints a version number.

- [ ] **Step 3: Install frontend deps**

Run:
```bash
cd frontend && npm ci
```
Expected: completes without errors.

- [ ] **Step 4: Establish baselines (record numbers)**

Run from worktree root:
```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
cd frontend && npx vitest run && cd ..
```
Expected: **BE 705 passed**, **FE 549 passed** (matches V1.5.4 baseline). If counts differ, STOP and reconcile.

- [ ] **Step 5: Add jsonschema to pyproject dev extras (so future venvs install it)**

Find `pyproject.toml`, locate `[project.optional-dependencies]` `dev = [...]` list, append `"jsonschema>=4.0",`. Run:
```bash
.venv/bin/pip install -e ".[dev]"
```
to confirm it installs.

```bash
git add pyproject.toml
git commit -m "build: add jsonschema to dev extras for contract tests"
```

---

## Slice 1 — Contract First (1 PR, sequential)

### Task 1: Capabilities contract + sample fixture + schema test

**Files:**
- Create: `docs/api-contracts/capabilities.md`
- Create: `tests/contracts/__init__.py` (empty)
- Create: `tests/contracts/capabilities.sample.json`
- Create: `tests/contracts/test_schema_capabilities.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_schema_capabilities.py
"""Contract test: capabilities.sample.json validates against the published schema.

This test is the canonical guard that the schema documented in
docs/api-contracts/capabilities.md stays in lock-step with the sample
fixture used by both backend implementation (slice 2) and frontend
mocks (slice 3).
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "model_types", "imputation_methods"],
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "model_types": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label", "group"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "group": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "requires": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "imputation_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def test_capabilities_sample_matches_schema():
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    jsonschema.validate(sample, SCHEMA)


def test_capabilities_sample_has_all_v1532_model_types():
    """The sample must include every V1.5.3.2 backend-supported model type."""
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    keys = {m["key"] for m in sample["model_types"]}
    expected = {
        "auto", "ols", "logit", "probit", "poisson", "negative_binomial",
        "panel_ols", "glm:binomial", "glm:poisson", "glm:negative_binomial",
    }
    assert expected.issubset(keys), f"missing: {expected - keys}"


def test_capabilities_sample_has_mice():
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    keys = {m["key"] for m in sample["imputation_methods"]}
    assert "mice" in keys


def test_capabilities_groups_are_a_known_set():
    """Group is a UI rendering hint — must be from a small fixed vocabulary."""
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    allowed = {"auto", "Linear", "Binary", "Count", "Panel", "GLM"}
    groups = {m["group"] for m in sample["model_types"]}
    assert groups.issubset(allowed), f"unknown groups: {groups - allowed}"
```

- [ ] **Step 2: Write the sample fixture**

```json
// tests/contracts/capabilities.sample.json
{
  "schema_version": 1,
  "model_types": [
    {"key": "auto",              "label": "Auto (infer from y)",         "group": "auto",   "description": "Pick the best model automatically based on y type."},
    {"key": "ols",               "label": "OLS (linear)",                 "group": "Linear", "description": "Ordinary Least Squares with HC1 robust SE."},
    {"key": "logit",             "label": "Logit",                        "group": "Binary", "description": "Logistic regression for binary outcomes."},
    {"key": "probit",            "label": "Probit",                       "group": "Binary", "description": "Probit regression for binary outcomes."},
    {"key": "poisson",           "label": "Poisson",                      "group": "Count",  "description": "Poisson regression for count outcomes."},
    {"key": "negative_binomial", "label": "Negative Binomial",            "group": "Count",  "description": "For overdispersed count outcomes."},
    {"key": "panel_ols",         "label": "Panel OLS",                    "group": "Panel",  "description": "Fixed/random effects panel OLS.", "requires": ["entity_or_time"]},
    {"key": "glm:binomial",      "label": "GLM · binomial",         "group": "GLM",    "description": "Generalized linear model with binomial family."},
    {"key": "glm:poisson",       "label": "GLM · poisson",          "group": "GLM",    "description": "Generalized linear model with Poisson family."},
    {"key": "glm:negative_binomial", "label": "GLM · negative binomial", "group": "GLM", "description": "Generalized linear model with negative binomial family."}
  ],
  "imputation_methods": [
    {"key": "mice", "label": "MICE (Multiple Imputation)", "description": "Multiple Imputation by Chained Equations. Recommended when more than 5–10% of rows would otherwise be dropped due to missing values."}
  ]
}
```

- [ ] **Step 3: Run test to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/contracts/test_schema_capabilities.py -v`
Expected: 4 PASS.

- [ ] **Step 4: Write the human-readable contract doc**

Create `docs/api-contracts/capabilities.md` with:
- Section "Endpoint": `GET /capabilities` returns the JSON Schema above. Cacheable on the client for the lifetime of a session.
- Section "JSON Schema": paste the Python `SCHEMA` dict expressed as `application/schema+json` (Draft 2020-12). Use the same content as `SCHEMA` in `test_schema_capabilities.py`.
- Section "Sample": link to `tests/contracts/capabilities.sample.json` with a short note explaining it doubles as the frontend mock fixture in slice 3.
- Section "Forward compatibility": new `model_types[].group` values must be added to the frontend `Group` union before being published; new top-level keys are additive only (clients must ignore unknown).
- Section "Producer": `backend/workbench/engine/capabilities.py::build_capabilities()` derives this from `MODEL_REGISTRY` + `IMPUTATION_REGISTRY`. Never maintain a parallel list.

- [ ] **Step 5: Commit**

```bash
git add docs/api-contracts/capabilities.md tests/contracts/__init__.py \
        tests/contracts/capabilities.sample.json \
        tests/contracts/test_schema_capabilities.py
git commit -m "contract(capabilities): schema + sample fixture + jsonschema tests"
```

### Task 2: Recommended-actions contract + sample + tests

**Files:**
- Create: `docs/api-contracts/recommended-actions.md`
- Create: `tests/contracts/recommended_actions.model_fit_failure.sample.json`
- Create: `tests/contracts/test_schema_recommended_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_schema_recommended_actions.py
"""Contract test: recommended_actions[] inside a failure_evidence dict."""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

ACTION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["key", "label", "severity"],
    "properties": {
        "key": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "severity": {"type": "string", "enum": ["primary", "secondary"]},
        "form_overrides": {"type": "object"},
        "hint": {"type": "string"},
    },
    "additionalProperties": False,
}


def test_action_sample_matches_schema():
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    for action in sample:
        jsonschema.validate(action, ACTION_SCHEMA)


def test_sample_has_a_primary_action():
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    assert any(a["severity"] == "primary" for a in sample), \
        "every recovery story needs at least one primary action"


def test_sample_first_action_provides_form_override():
    """The primary action for MODEL_FIT_FAILED should be a one-click recovery
    (Re-run with auto), so it must carry form_overrides."""
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    primary = next(a for a in sample if a["severity"] == "primary")
    assert "form_overrides" in primary
    assert primary["form_overrides"].get("model_type") == "auto"
```

- [ ] **Step 2: Write the sample**

```json
// tests/contracts/recommended_actions.model_fit_failure.sample.json
[
  {
    "key": "rerun_auto",
    "label": "Re-run with auto",
    "severity": "primary",
    "form_overrides": {"model_type": "auto"}
  },
  {
    "key": "change_model",
    "label": "Change model type",
    "severity": "secondary"
  },
  {
    "key": "check_y_column",
    "label": "Check y column",
    "severity": "secondary",
    "hint": "Your y appears continuous; logit needs a binary 0/1 column."
  }
]
```

- [ ] **Step 3: Run test to verify it passes**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/contracts/test_schema_recommended_actions.py -v`
Expected: 3 PASS.

- [ ] **Step 4: Write the contract doc**

Create `docs/api-contracts/recommended-actions.md` with:
- Intent: `failure_evidence.recommended_actions` is the first concrete producer of V1.5.4 spec §2.5's declared `AnalysisPack.recommended_actions` slot. Same schema. Future producers (agent failures, pack diagnostics) MUST conform.
- Schema (the `ACTION_SCHEMA` dict above as application/schema+json).
- Severity rules: `primary` = red filled button, one per array max in failure context; `secondary` = outlined button.
- `form_overrides`: when present, clicking the button merges these key/values into the run form state. Frontend submits the merged form. Example: `{"model_type": "auto"}` triggers a one-click re-run with auto.
- `hint`: optional tooltip.
- Sample at `tests/contracts/recommended_actions.model_fit_failure.sample.json`.
- Producer: `backend/workbench/engine/recommended_actions.py` factories.

- [ ] **Step 5: Commit**

```bash
git add docs/api-contracts/recommended-actions.md \
        tests/contracts/recommended_actions.model_fit_failure.sample.json \
        tests/contracts/test_schema_recommended_actions.py
git commit -m "contract(recommended-actions): schema + sample fixture + tests"
```

### Task 3: Imputation-summary contract + sample + tests

**Files:**
- Create: `docs/api-contracts/imputation-summary.md`
- Create: `tests/contracts/imputation_summary.mice.sample.json`
- Create: `tests/contracts/test_schema_imputation_summary.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_schema_imputation_summary.py
"""Contract test: imputation_summary.json schema.

Note: the existing run_mice_imputation() in backend/workbench/imputation.py
already returns most of this shape (schema_version=1, method='mice',
status, imputed_columns, etc.). V1.5.4.1 adds three method-agnostic fields:
rows_imputed, input_artifact, output_artifact. We do NOT rename existing
fields — the contract is the union of what's already there + the 3 new ones.
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version", "method", "status",
        "imputed_columns", "input_artifact", "output_artifact",
    ],
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "method": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["completed", "skipped", "failed"]},
        # Method-agnostic core (rows_imputed is new in V1.5.4.1)
        "rows_imputed": {"type": "integer", "minimum": 0},
        "imputed_columns": {"type": "array", "items": {"type": "string"}},
        "input_artifact": {"type": "string", "minLength": 1},
        "output_artifact": {"type": "string"},
        # Method-specific (MICE) — already present in existing summary
        "selected_columns": {"type": "array", "items": {"type": "string"}},
        "skipped_columns": {"type": "array", "items": {"type": "string"}},
        "m": {"type": "integer"},
        "persisted_datasets": {"type": "integer"},
        "pooled_estimates": {"type": "boolean"},
        "max_iter": {"type": "integer"},
        "random_seed": {"type": "integer"},
        "max_missing_rate": {"type": "number"},
        "row_count": {"type": "integer"},
        "warnings": {"type": "array"},
    },
    # Allow future method-specific fields (e.g. knn's `k`, mean_fill's `strategy`).
    "additionalProperties": True,
}


def test_summary_sample_matches_schema():
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    jsonschema.validate(sample, SCHEMA)


def test_sample_has_completed_mice():
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    assert sample["method"] == "mice"
    assert sample["status"] == "completed"


def test_sample_carries_new_v1_5_4_1_fields():
    """The whole point of the V1.5.4.1 contract is to add these three fields."""
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    assert "rows_imputed" in sample
    assert "input_artifact" in sample
    assert "output_artifact" in sample
```

- [ ] **Step 2: Write the sample**

```json
// tests/contracts/imputation_summary.mice.sample.json
{
  "schema_version": 1,
  "method": "mice",
  "status": "completed",
  "rows_imputed": 17,
  "imputed_columns": ["education", "experience"],
  "selected_columns": ["education", "experience"],
  "skipped_columns": [],
  "m": 5,
  "persisted_datasets": 5,
  "pooled_estimates": false,
  "max_iter": 10,
  "random_seed": 20260429,
  "max_missing_rate": 0.4,
  "row_count": 200,
  "warnings": [],
  "input_artifact": "cleaned_dataset",
  "output_artifact": "imputed_dataset"
}
```

- [ ] **Step 3: Run test**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/contracts/test_schema_imputation_summary.py -v`
Expected: 3 PASS.

- [ ] **Step 4: Write the contract doc**

Create `docs/api-contracts/imputation-summary.md` with:
- Location: `run_root / "model_results" / "imputation_summary.json"`. Registered as artifact id `imputation_summary` with `inputs=[input_artifact]`.
- Method-agnostic required fields: `schema_version, method, status, imputed_columns, input_artifact, output_artifact`. `rows_imputed` is method-agnostic but optional for `status="skipped"`.
- MICE-specific optional fields: `m, persisted_datasets, max_iter, random_seed, max_missing_rate, selected_columns, skipped_columns, row_count, warnings, pooled_estimates`.
- Forward compatibility: future methods may add their own optional fields (KNN: `k`, mean_fill: `strategy`). Frontend renders core fields universally and uses a `method`-keyed switch for method-specific rows.
- Producer: `backend/workbench/imputation.run_mice_imputation()` returns most fields; `ImputationStage` writes the file + registers the artifact + adds the three V1.5.4.1 fields.

- [ ] **Step 5: Commit**

```bash
git add docs/api-contracts/imputation-summary.md \
        tests/contracts/imputation_summary.mice.sample.json \
        tests/contracts/test_schema_imputation_summary.py
git commit -m "contract(imputation-summary): schema + sample fixture + tests"
```

### Task 4: `/runs` POST form contract doc (no test — documentation only)

**Files:**
- Create: `docs/api-contracts/runs-post.md`

- [ ] **Step 1: Write the doc**

Create `docs/api-contracts/runs-post.md`. Content:
- Endpoint: `POST /runs` (multipart/form-data).
- Existing fields table (from `api.py`'s current `run_endpoint`):
  | field | type | default | required | meaning |
  | --- | --- | --- | --- | --- |
  | `project_root` | string | — | yes | absolute path to project root |
  | `mode` | string | `auto` | no | run mode |
  | `model_type` | string | `auto` | no | requested model type (key from `/capabilities`) |
  | `y` | string | — | yes | y column name |
  | `x` | string | — | yes | comma-separated x column names |
  | `file` | file | — | yes | uploaded data file (CSV/XLSX) |
  | `sheet_name` | string | `""` | no | excel sheet selector |
  | `transpose` | string | `false` | no | `"true"` to swap rows/columns |
- **New in V1.5.4.1:**
  | `imputation` | string (JSON) | `""` | no | When non-empty: JSON object like `{"method":"mice"}`. When empty: falls back to `config.imputation_method`. |
- Response shape unchanged: `{"run_id": "...", "status": "running"}`.
- Forward compatibility: never repurpose existing field names. New fields are additive only.

- [ ] **Step 2: Commit**

```bash
git add docs/api-contracts/runs-post.md
git commit -m "contract(runs-post): form fields table with new imputation field"
```

### Task 5: Slice 1 gate — full suite still green + contract tests pass

- [ ] **Step 1: Run full suite to confirm no regression**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: **705 + 10 contract tests = 715 passed**, 0 failures.

- [ ] **Step 2: Run frontend baseline (untouched, should be 549)**

```bash
cd frontend && npx vitest run && cd ..
```
Expected: **549 passed**.

- [ ] **Step 3: Push slice 1 (mark gate passed)**

```bash
git push -u origin workbench-v1.5.4.1
```

---

## Slice 2 — Backend Implementation (5 PRs, parallel to Slice 3)

### Task 6 (PR 2a): `/capabilities` endpoint + `IMPUTATION_REGISTRY`

**Files:**
- Create: `backend/workbench/engine/imputation_registry.py`
- Create: `backend/workbench/engine/capabilities.py`
- Modify: `backend/workbench/api.py` (add route)
- Modify: `backend/workbench/engine/stages/imputation.py` (register MICE)
- Test: `tests/test_engine_capabilities.py`, `tests/test_api_capabilities.py`

- [ ] **Step 1: Write the failing test for `build_capabilities()`**

```python
# tests/test_engine_capabilities.py
"""build_capabilities() derives the manifest from MODEL_REGISTRY +
IMPUTATION_REGISTRY. Importing workbench.engine.stages.estimation triggers
CORE_PACK registration so the model handlers are populated."""
import json
from pathlib import Path

import jsonschema

# Importing estimation registers CORE_PACK and MICE imputation method.
import workbench.engine.stages.estimation  # noqa: F401
import workbench.engine.stages.imputation  # noqa: F401
from workbench.engine.capabilities import build_capabilities

CONTRACT_DIR = Path(__file__).parent / "contracts"


def test_build_capabilities_matches_contract_schema():
    """The endpoint payload must satisfy the published JSON Schema."""
    # Reuse the schema from the slice-1 contract test for source of truth.
    from tests.contracts.test_schema_capabilities import SCHEMA
    payload = build_capabilities()
    jsonschema.validate(payload, SCHEMA)


def test_build_capabilities_includes_all_v1_5_3_2_models():
    payload = build_capabilities()
    keys = {m["key"] for m in payload["model_types"]}
    expected = {
        "auto", "ols", "logit", "probit", "poisson", "negative_binomial",
        "panel_ols", "glm:binomial", "glm:poisson", "glm:negative_binomial",
    }
    assert expected.issubset(keys), f"missing model_types: {expected - keys}"


def test_build_capabilities_includes_mice_imputation():
    payload = build_capabilities()
    keys = {m["key"] for m in payload["imputation_methods"]}
    assert "mice" in keys


def test_panel_ols_declares_entity_or_time_requirement():
    payload = build_capabilities()
    panel = next(m for m in payload["model_types"] if m["key"] == "panel_ols")
    assert "entity_or_time" in panel.get("requires", [])


def test_groups_match_known_vocabulary():
    payload = build_capabilities()
    groups = {m["group"] for m in payload["model_types"]}
    assert groups.issubset({"auto", "Linear", "Binary", "Count", "Panel", "GLM"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: workbench.engine.capabilities`.

- [ ] **Step 3: Create the imputation registry**

```python
# backend/workbench/engine/imputation_registry.py
"""Registry of imputation methods, mirror of MODEL_REGISTRY shape.

V1.5.4.1: introduces the registry but keeps the actual fit logic in
backend/workbench/imputation.py (run_mice_imputation). The registry
exists so `/capabilities` can derive the UI list dynamically and so
future methods (KNN, mean_fill) can register without touching
ImputationStage's inner loop.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImputationMethod:
    key: str            # registry key, e.g. "mice"
    label: str          # UI label
    description: str    # UI tooltip / help text


IMPUTATION_REGISTRY: dict[str, ImputationMethod] = {}


def register_imputation_method(method: ImputationMethod) -> None:
    IMPUTATION_REGISTRY[method.key] = method
```

- [ ] **Step 4: Create `build_capabilities()`**

```python
# backend/workbench/engine/capabilities.py
"""Capability manifest derivation.

build_capabilities() is a pure function that reads MODEL_REGISTRY and
IMPUTATION_REGISTRY and emits the /capabilities payload. No IO.

The function returns a dict matching the published schema in
docs/api-contracts/capabilities.md.
"""
from __future__ import annotations

from typing import Any

from .imputation_registry import IMPUTATION_REGISTRY
from .registry import MODEL_REGISTRY


# UI metadata for the built-in model_type keys. This is the SINGLE place
# we map a registry key to its display label / group / description.
_MODEL_METADATA: dict[str, dict[str, Any]] = {
    "auto":               {"label": "Auto (infer from y)",        "group": "auto",   "description": "Pick the best model automatically based on y type."},
    "ols":                {"label": "OLS (linear)",                "group": "Linear", "description": "Ordinary Least Squares with HC1 robust SE."},
    "logit":              {"label": "Logit",                       "group": "Binary", "description": "Logistic regression for binary outcomes."},
    "probit":             {"label": "Probit",                      "group": "Binary", "description": "Probit regression for binary outcomes."},
    "poisson":            {"label": "Poisson",                     "group": "Count",  "description": "Poisson regression for count outcomes."},
    "poisson_rate":       {"label": "Poisson",                     "group": "Count",  "description": "Poisson regression for count outcomes."},  # alias, not exposed
    "negative_binomial":  {"label": "Negative Binomial",           "group": "Count",  "description": "For overdispersed count outcomes."},
    "panel_ols":          {"label": "Panel OLS",                   "group": "Panel",  "description": "Fixed/random effects panel OLS.", "requires": ["entity_or_time"]},
    "glm":                {"label": "GLM",                          "group": "GLM",    "description": "Generalized linear model. Choose a family."},
}

# poisson_rate is an internal alias for `poisson`; do not expose to UI.
_HIDDEN_KEYS: set[str] = {"poisson_rate"}

# GLM is multiplexed via glm:<family>. Map families to UI entries.
_GLM_FAMILY_LABELS: dict[str, str] = {
    "binomial":           "GLM · binomial",
    "poisson":            "GLM · poisson",
    "negative_binomial":  "GLM · negative binomial",
}


def _model_entry(key: str, meta: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": key,
        "label": meta["label"],
        "group": meta["group"],
    }
    if "description" in meta:
        entry["description"] = meta["description"]
    if "requires" in meta:
        entry["requires"] = list(meta["requires"])
    return entry


def build_capabilities() -> dict[str, Any]:
    """Derive the /capabilities payload from MODEL_REGISTRY + IMPUTATION_REGISTRY."""
    # Start with the `auto` pseudo-entry (not in MODEL_REGISTRY, always present).
    model_types: list[dict[str, Any]] = [
        _model_entry("auto", _MODEL_METADATA["auto"]),
    ]

    # Real handlers from the registry.
    for key in MODEL_REGISTRY.keys():
        if key in _HIDDEN_KEYS:
            continue
        if key == "glm":
            # Expand to one entry per supported family.
            for family, label in _GLM_FAMILY_LABELS.items():
                model_types.append({
                    "key": f"glm:{family}",
                    "label": label,
                    "group": "GLM",
                    "description": f"Generalized linear model with {family.replace('_', ' ')} family.",
                })
        elif key in _MODEL_METADATA:
            model_types.append(_model_entry(key, _MODEL_METADATA[key]))

    imputation_methods = [
        {"key": m.key, "label": m.label, "description": m.description}
        for m in IMPUTATION_REGISTRY.values()
    ]

    return {
        "schema_version": 1,
        "model_types": model_types,
        "imputation_methods": imputation_methods,
    }
```

- [ ] **Step 5: Register MICE at import time**

Open `backend/workbench/engine/stages/imputation.py`. At the top of the file (after existing imports), add:

```python
from ..imputation_registry import ImputationMethod, register_imputation_method

# Dogfood: register MICE so /capabilities sees it.
register_imputation_method(ImputationMethod(
    key="mice",
    label="MICE (Multiple Imputation)",
    description=(
        "Multiple Imputation by Chained Equations. Recommended when more "
        "than 5–10% of rows would otherwise be dropped due to missing values."
    ),
))
```

- [ ] **Step 6: Run capabilities tests**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_capabilities.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Write the API route test**

```python
# tests/test_api_capabilities.py
"""GET /capabilities returns a payload conforming to the published schema."""
from fastapi.testclient import TestClient

from workbench.api import app
from tests.contracts.test_schema_capabilities import SCHEMA
import jsonschema


def test_get_capabilities_returns_valid_payload():
    client = TestClient(app)
    res = client.get("/capabilities")
    assert res.status_code == 200
    payload = res.json()
    jsonschema.validate(payload, SCHEMA)


def test_get_capabilities_includes_logit():
    client = TestClient(app)
    payload = client.get("/capabilities").json()
    assert any(m["key"] == "logit" for m in payload["model_types"])
```

- [ ] **Step 8: Add the route**

Open `backend/workbench/api.py`. Add near the top with other imports:

```python
from .engine.capabilities import build_capabilities
```

Add the route (place it next to other GET endpoints, e.g. before `@app.get("/runs")`):

```python
@app.get("/capabilities")
def capabilities_endpoint() -> dict:
    return build_capabilities()
```

- [ ] **Step 9: Run all tests**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api_capabilities.py tests/test_engine_capabilities.py -v`
Expected: 7 PASS (2 + 5).

- [ ] **Step 10: Full suite regression**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: 715 + 7 new = **722 passed**, 0 failures.

- [ ] **Step 11: Commit**

```bash
git add backend/workbench/engine/imputation_registry.py \
        backend/workbench/engine/capabilities.py \
        backend/workbench/engine/stages/imputation.py \
        backend/workbench/api.py \
        tests/test_engine_capabilities.py \
        tests/test_api_capabilities.py
git commit -m "feat(api): GET /capabilities derived from MODEL_REGISTRY + IMPUTATION_REGISTRY"
```

### Task 7 (PR 2b): `run_workflow` adds `imputation` kwarg + ImputationStage reads ctx first

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `backend/workbench/engine/stages/imputation.py`
- Test: `tests/test_imputation_kwarg.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_imputation_kwarg.py
"""run_workflow's new `imputation` kwarg overrides config.imputation_method.

Backwards compatibility: passing imputation=None (default) must leave
existing config-driven behavior unchanged.
"""
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _make_project(tmp_path: Path) -> Path:
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]  # missing every 7th
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    src = tmp_path / "d.csv"
    frame.to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    return project.root, src


def test_imputation_kwarg_mice_triggers_imputation(tmp_path: Path):
    """Passing imputation={'method': 'mice'} triggers MICE even when
    config.imputation_method is empty (the default)."""
    project_root, src = _make_project(tmp_path)
    res = run_workflow(
        project_root, [src], mode="auto", y="y", x=["x"],
        imputation={"method": "mice"},
    )
    assert res["status"] == "completed"
    run_root = project_root / "runs" / res["run_id"]
    idx = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "imputed_dataset" in ids, "imputation kwarg did not trigger MICE"


def test_imputation_none_leaves_config_path_untouched(tmp_path: Path):
    """When imputation kwarg is omitted (None), the existing config-driven
    behavior is byte-identical: no MICE because default config doesn't enable it."""
    project_root, src = _make_project(tmp_path)
    res = run_workflow(project_root, [src], mode="auto", y="y", x=["x"])
    assert res["status"] == "completed"
    run_root = project_root / "runs" / res["run_id"]
    idx = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "imputed_dataset" not in ids
```

- [ ] **Step 2: Run to verify FAIL**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_kwarg.py -v`
Expected: FAIL on the first test — `imputed_dataset` absent (kwarg doesn't exist).

- [ ] **Step 3: Add the kwarg to `run_workflow` public signature**

Open `backend/workbench/orchestrator.py`. Locate `def run_workflow(`. Add `imputation` parameter after `model_type`:

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
) -> dict[str, str]:
```

In the `try:` block, change the call to `_run_workflow(...)` to thread the new param. Find the existing call (it currently lists positional/kwarg args up through `model_type=model_type`). Add at the end:

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
        )
```

- [ ] **Step 4: Thread through `_run_workflow`**

Locate `def _run_workflow(` (around line 394). Add the parameter to its signature (after `transpose`):

```python
    transpose: bool = False,
    imputation: dict | None = None,
) -> dict[str, str]:
```

In the body, after the existing `ctx.artifacts["_started_at"] = started_at` stash line, add:

```python
    ctx.artifacts["_imputation_request"] = imputation  # may be None
```

- [ ] **Step 5: Make `ImputationStage` honor the request**

Open `backend/workbench/engine/stages/imputation.py`. Locate the `run()` method's MICE-firing check. The current logic is `if config.imputation_method == "mice":`. Change to:

```python
        # ctx.artifacts["_imputation_request"] is the V1.5.4.1 kwarg-driven
        # override; falls back to config.imputation_method when None.
        request = ctx.artifacts.get("_imputation_request")
        if request is not None:
            method = request.get("method")
        else:
            config = ctx.artifacts["_config"]
            method = config.imputation_method

        if method == "mice":
            # ... existing MICE invocation ...
```

(Keep the existing MICE invocation block unchanged after this guard. Look at the current file and substitute the new guard for the old `if config.imputation_method == "mice":` line.)

- [ ] **Step 6: Run new tests**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_kwarg.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Full suite + golden regression**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: 722 + 2 = **724 passed**. The `test_golden_imputation` golden must still pass (it uses `imputation_method: mice` in config.yml, the config path, untouched).

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/orchestrator.py \
        backend/workbench/engine/stages/imputation.py \
        tests/test_imputation_kwarg.py
git commit -m "feat(api): run_workflow accepts imputation kwarg override (back-compat via config fallback)"
```

### Task 8 (PR 2c): `/runs` POST `imputation` form field + CLI `--imputation`

**Files:**
- Modify: `backend/workbench/api.py` (`/runs` route + `_bg_run` signature)
- Modify: `backend/workbench/cli.py`
- Test: `tests/test_api_runs_imputation.py`, `tests/test_cli_imputation.py`

- [ ] **Step 1: Write failing API test**

```python
# tests/test_api_runs_imputation.py
"""POST /runs accepts an optional `imputation` form field (JSON string)
and threads it through to the background worker."""
import io
import json
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json
from workbench.projects import create_project


def _csv_bytes(tmp_path: Path) -> bytes:
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    return frame.to_csv(index=False).encode()


def _wait_terminal(project_root: Path, run_id: str, deadline_s: float = 30.0) -> str:
    """Poll the manifest until status is terminal."""
    manifest_path = project_root / "runs" / run_id / "run_manifest.json"
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline_s:
        if manifest_path.exists():
            status = read_json(manifest_path).get("status")
            if status in {"completed", "failed", "blocked"}:
                return status
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {deadline_s}s")


def test_post_runs_with_imputation_triggers_mice(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    client = TestClient(app)
    payload = _csv_bytes(tmp_path)
    res = client.post(
        "/runs",
        data={
            "project_root": str(project.root),
            "mode": "auto",
            "model_type": "auto",
            "y": "y",
            "x": "x",
            "imputation": json.dumps({"method": "mice"}),
        },
        files={"file": ("d.csv", io.BytesIO(payload), "text/csv")},
    )
    assert res.status_code == 200
    run_id = res.json()["run_id"]
    status = _wait_terminal(project.root, run_id)
    assert status == "completed", status
    idx = read_json(project.root / "runs" / run_id / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "imputed_dataset" in ids
```

- [ ] **Step 2: Run to verify FAIL**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api_runs_imputation.py -v`
Expected: FAIL (`imputation` field accepted but not threaded).

- [ ] **Step 3: Add `imputation` form field to `/runs`**

Open `backend/workbench/api.py`. Find `async def run_endpoint(`. Add `imputation: str = Form("")` after `transpose`:

```python
async def run_endpoint(
    project_root: str = Form(...),
    mode: str = Form("auto"),
    model_type: str = Form("auto"),
    y: str = Form(...),
    x: str = Form(...),
    file: UploadFile = File(...),
    sheet_name: str = Form(""),
    transpose: str = Form("false"),
    imputation: str = Form(""),
) -> dict[str, str]:
```

Inside the function body, before submitting to the executor, parse the JSON (and bail loud on malformed input — return 400 rather than silently swallowing):

```python
    imputation_kwarg: dict | None = None
    if imputation:
        try:
            imputation_kwarg = json.loads(imputation)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"imputation must be JSON: {exc}",
            )
        if not isinstance(imputation_kwarg, dict):
            raise HTTPException(
                status_code=400,
                detail="imputation must be a JSON object",
            )
```

(Add `import json` at top of file if not already present — check first.)

Pass to `_bg_run`:

```python
        events.executor.submit(
            _bg_run, run.root, run.run_id, saved_path,
            mode, y, x_columns, started_at, model_type,
            sheet_name or None, transpose == "true",
            imputation_kwarg,
        )
```

- [ ] **Step 4: Thread through `_bg_run`**

Find `def _bg_run(` in the same file. Add the parameter at the end:

```python
def _bg_run(
    run_root: Path,
    run_id: str,
    saved_path: Path,
    mode: str,
    y: str,
    x_columns: list[str],
    started_at: str,
    model_type: str = "auto",
    sheet_name: str | None = None,
    transpose: bool = False,
    imputation: dict | None = None,
) -> None:
```

Inside `_bg_run`, find the call to `_run_workflow(...)`. Pass through:

```python
    _run_workflow(
        run_root, run_id, [saved_path],
        mode, y, x_columns, config, started_at,
        on_step=on_step,
        model_type=model_type,
        sheet_name=sheet_name,
        transpose=transpose,
        imputation=imputation,
    )
```

(Check the existing call — only adjust if the call is `kwargs`-style. If positional, keep order matching `_run_workflow`'s signature. Read the existing call before editing.)

- [ ] **Step 5: Run API test**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api_runs_imputation.py -v`
Expected: PASS.

- [ ] **Step 6: Write failing CLI test**

```python
# tests/test_cli_imputation.py
"""CLI accepts --imputation <method> or --imputation '{"method":"..."}'."""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.projects import create_project


def _setup_project(tmp_path: Path) -> tuple[Path, Path]:
    project = create_project(tmp_path, "demo")
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    src = tmp_path / "d.csv"
    pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))}).to_csv(src, index=False)
    return project.root, src


def test_cli_imputation_simple_form_triggers_mice(tmp_path: Path):
    project_root, src = _setup_project(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": "backend"}
    repo_root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "workbench.cli",
         "run", str(project_root), str(src), "y",
         "--x", "x", "--imputation", "mice"],
        cwd=repo_root,
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    run_id = result.stdout.strip().split("\n")[-1]
    idx = read_json(project_root / "runs" / run_id / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "imputed_dataset" in ids
```

- [ ] **Step 7: Add `--imputation` to CLI**

Open `backend/workbench/cli.py`. Locate the `run` command (typer command). Add option:

```python
imputation: str = typer.Option(
    "", "--imputation",
    help="Imputation method ('mice') or JSON like '{\"method\":\"mice\"}'. Empty = use config.",
),
```

In the function body, parse the option and pass to `run_workflow`:

```python
    imputation_kwarg: dict | None = None
    if imputation:
        s = imputation.strip()
        if s.startswith("{"):
            imputation_kwarg = json.loads(s)
        else:
            imputation_kwarg = {"method": s}

    from .orchestrator import run_workflow
    result = run_workflow(
        project_root,
        [data_file],
        mode=mode,
        y=y,
        x=x,
        model_type=model_type,
        imputation=imputation_kwarg,
    )
```

(Add `import json` at top if missing.)

- [ ] **Step 8: Run CLI test**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_cli_imputation.py -v`
Expected: PASS.

- [ ] **Step 9: Full suite**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: 724 + 2 = **726 passed**.

- [ ] **Step 10: Commit**

```bash
git add backend/workbench/api.py backend/workbench/cli.py \
        tests/test_api_runs_imputation.py tests/test_cli_imputation.py
git commit -m "feat(api,cli): imputation kwarg threaded via /runs form + --imputation CLI"
```

### Task 9 (PR 2d): `recommended_actions` factory + inject into `failure_evidence`

**Files:**
- Create: `backend/workbench/engine/recommended_actions.py`
- Modify: `backend/workbench/engine/stages/estimation.py` (two failure branches)
- Modify: `backend/workbench/orchestrator.py` (`_validate_requested_model_type` paths — optional, see step 8)
- Test: `tests/test_recommended_actions.py`, extend `tests/test_lineage_invariants.py`

- [ ] **Step 1: Write failing unit test for the factory**

```python
# tests/test_recommended_actions.py
"""Factory functions produce schema-compliant action arrays."""
import json
from pathlib import Path

import jsonschema

from workbench.engine.recommended_actions import (
    actions_for_model_fit_failure,
    actions_for_panel_fields_missing,
)
from tests.contracts.test_schema_recommended_actions import ACTION_SCHEMA


def _validate_all(actions: list[dict]) -> None:
    for action in actions:
        jsonschema.validate(action, ACTION_SCHEMA)


def test_explicit_logit_on_continuous_y_offers_rerun_auto():
    actions = actions_for_model_fit_failure(
        requested_model_type="logit", y_type="continuous",
    )
    _validate_all(actions)
    keys = [a["key"] for a in actions]
    assert "rerun_auto" in keys
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["form_overrides"] == {"model_type": "auto"}


def test_auto_failure_does_not_offer_rerun_auto():
    """When the run was already auto and both primary + OLS fallback failed,
    re-running with auto is pointless. The primary action should be
    'check_data' or similar — never `rerun_auto`."""
    actions = actions_for_model_fit_failure(
        requested_model_type="auto", y_type="binary",
    )
    _validate_all(actions)
    keys = [a["key"] for a in actions]
    assert "rerun_auto" not in keys


def test_panel_fields_missing_offers_rerun_auto():
    actions = actions_for_panel_fields_missing()
    _validate_all(actions)
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["form_overrides"].get("model_type") == "auto"


def test_at_most_one_primary_action_per_recovery():
    """The story has one starring button. Other actions are secondary."""
    for actions in [
        actions_for_model_fit_failure(requested_model_type="logit", y_type="continuous"),
        actions_for_model_fit_failure(requested_model_type="auto", y_type="binary"),
        actions_for_panel_fields_missing(),
    ]:
        primaries = [a for a in actions if a["severity"] == "primary"]
        assert len(primaries) <= 1
```

- [ ] **Step 2: Run to verify FAIL**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_recommended_actions.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the factory**

```python
# backend/workbench/engine/recommended_actions.py
"""Factory functions that produce recommended_actions arrays for known
failure modes. These are injected into failure_evidence so the frontend
FailureCard can render one-click recovery buttons.

Contract: docs/api-contracts/recommended-actions.md
Schema:   tests/contracts/test_schema_recommended_actions.py::ACTION_SCHEMA
"""
from __future__ import annotations


_RERUN_AUTO: dict = {
    "key": "rerun_auto",
    "label": "Re-run with auto",
    "severity": "primary",
    "form_overrides": {"model_type": "auto"},
}

_CHANGE_MODEL: dict = {
    "key": "change_model",
    "label": "Change model type",
    "severity": "secondary",
}

_CHECK_Y: dict = {
    "key": "check_y_column",
    "label": "Check y column",
    "severity": "secondary",
}

_CHECK_DATA: dict = {
    "key": "check_data",
    "label": "Inspect data profile",
    "severity": "primary",
    # No form_overrides — user needs to investigate, not re-run blindly.
}


def actions_for_model_fit_failure(
    *, requested_model_type: str, y_type: str | None,
) -> list[dict]:
    """Build the actions array for a MODEL_FIT_FAILED issue.

    - Explicit failures (requested_model_type != "auto"): primary action
      = re-run with auto (one-click recovery). Secondary = pick a
      different model, check y column.
    - Auto failures (requested_model_type == "auto"): re-run with auto
      would just repeat the failure. Primary = inspect data profile.
    """
    if requested_model_type != "auto":
        actions: list[dict] = [dict(_RERUN_AUTO), dict(_CHANGE_MODEL)]
        check_y = dict(_CHECK_Y)
        if y_type == "continuous" and requested_model_type in {"logit", "probit"}:
            check_y["hint"] = (
                f"Your y appears continuous; {requested_model_type} needs a binary 0/1 column."
            )
        elif y_type == "binary" and requested_model_type in {"ols", "panel_ols"}:
            check_y["hint"] = (
                f"Your y is binary; {requested_model_type} is built for continuous y."
            )
        actions.append(check_y)
        return actions
    return [dict(_CHECK_DATA), dict(_CHANGE_MODEL)]


def actions_for_panel_fields_missing() -> list[dict]:
    """PANEL_FIELDS_MISSING — user requested panel_ols but data has no
    entity/time. One-click recovery: re-run with auto."""
    return [
        dict(_RERUN_AUTO),
        {
            "key": "verify_panel_columns",
            "label": "Verify entity/time columns",
            "severity": "secondary",
            "hint": "Panel models need at least one of: entity id column, time column.",
        },
    ]
```

- [ ] **Step 4: Run factory tests**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_recommended_actions.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Inject into EstimationStage explicit failure branch**

Open `backend/workbench/engine/stages/estimation.py`. Find the `failure_evidence` dict construction (around line 230 — `failure_evidence = _model_failure_details(...)`).

Immediately AFTER the existing lines that populate `failure_evidence["y_type"]` and `failure_evidence["requested_model_type"]`, add:

```python
            from ..recommended_actions import actions_for_model_fit_failure
            failure_evidence["recommended_actions"] = actions_for_model_fit_failure(
                requested_model_type=model_type,  # local var: the requested type
                y_type=ctx.y_type,
            )
```

Find the AUTO OLS-fallback-also-failed branch (further down in the same `except ValueError` block — where the BLOCKER MODEL_FIT_FAILED issue is appended after `ols_exc`). The `_model_failure_details(...)` call there constructs a separate failure_evidence dict for the fallback. Inject actions there too — but with `requested_model_type="auto"` so the factory picks the "no rerun_auto" branch:

```python
                # in the OLS-fallback-failed handler, after building the dict:
                from ..recommended_actions import actions_for_model_fit_failure
                fallback_evidence["recommended_actions"] = actions_for_model_fit_failure(
                    requested_model_type="auto", y_type=ctx.y_type,
                )
```

(The exact variable name for the OLS-fallback failure_evidence dict will be visible when you read estimation.py; substitute appropriately.)

- [ ] **Step 6: Extend invariant 5 to assert recommended_actions present**

Open `tests/test_lineage_invariants.py`. Find `test_invariant_explicit_model_type_failure_returns_failed_no_silent_fallback`. After the existing asserts, add:

```python
    # V1.5.4.1: failure_evidence must carry recommended_actions for the
    # frontend to render the FailureCard.
    errors = read_json(run_root / "errors.json")
    fit_failures = [
        i for i in errors["issues"]
        if i.get("code") == "MODEL_FIT_FAILED" and i.get("severity") == "BLOCKER"
    ]
    assert fit_failures, "expected a BLOCKER MODEL_FIT_FAILED issue"
    evidence = fit_failures[0]["details"]
    actions = evidence.get("recommended_actions", [])
    assert any(a["key"] == "rerun_auto" for a in actions)
```

(Adjust the path to the evidence dict based on how `GuardrailIssue.to_dict()` shapes it — read once to confirm. If it lives under `details` vs `evidence`, use the real key.)

- [ ] **Step 7: Run extended invariant + full suite**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_lineage_invariants.py -v
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: invariants pass; full suite 726 + 4 (factory) = **730 passed**.

- [ ] **Step 8: (Optional sub-step) Inject into `_validate_requested_model_type` failure paths**

This is for the `UNSUPPORTED_MODEL_TYPE` and `UNSUPPORTED_GLM_FAMILY` paths in `orchestrator._validate_requested_model_type`. Each raises `WorkflowValidationError(error_code, msg, evidence_dict)`. Locate the `evidence_dict` argument and add `"recommended_actions"` key by calling `actions_for_unsupported_model_type(...)` (you may keep it simple — same as `actions_for_panel_fields_missing()` since "re-run with auto" recovers in both cases). Add the factory function `actions_for_unsupported_model_type()` to `recommended_actions.py` if it didn't exist.

If you skip this sub-step, leave a note in the PR description: "UNSUPPORTED_MODEL_TYPE doesn't yet inject recommended_actions; tracked as a small follow-up." The frontend FailureCard will gracefully omit the action row if absent.

- [ ] **Step 9: Commit**

```bash
git add backend/workbench/engine/recommended_actions.py \
        backend/workbench/engine/stages/estimation.py \
        tests/test_recommended_actions.py \
        tests/test_lineage_invariants.py
git commit -m "feat(engine): inject recommended_actions into MODEL_FIT_FAILED failure_evidence"
```

### Task 10 (PR 2e): `imputation_summary.json` writes to disk + register_artifact + new fields

**Files:**
- Modify: `backend/workbench/engine/stages/imputation.py`
- Test: `tests/test_imputation_summary_artifact.py`; regen `tests/golden/imputation.json`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_imputation_summary_artifact.py
"""V1.5.4.1: ImputationStage writes imputation_summary.json to disk and
registers it as artifact `imputation_summary` with inputs=[input_artifact].
Also asserts the three new fields are populated."""
import json
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_imputation_summary_is_persisted_and_registered(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    src = tmp_path / "d.csv"
    pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))}).to_csv(src, index=False)

    res = run_workflow(
        project.root, [src], mode="auto", y="y", x=["x"],
        imputation={"method": "mice"},
    )
    assert res["status"] == "completed"

    run_root = project.root / "runs" / res["run_id"]
    summary_path = run_root / "model_results" / "imputation_summary.json"
    assert summary_path.exists(), "imputation_summary.json missing"

    summary = json.loads(summary_path.read_text())
    # Required schema fields
    assert summary["schema_version"] == 1
    assert summary["method"] == "mice"
    assert summary["status"] == "completed"
    # V1.5.4.1 new fields
    assert "rows_imputed" in summary
    assert summary["input_artifact"] == "cleaned_dataset"
    assert summary["output_artifact"] == "imputed_dataset"

    # Registered as artifact
    idx = read_json(run_root / "artifacts_index.json")
    ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "imputation_summary" in ids
    rec = next(a for a in idx["artifacts"] if a["artifact_id"] == "imputation_summary")
    assert rec.get("inputs") == ["cleaned_dataset"]


def test_imputation_summary_validates_against_contract_schema(tmp_path: Path):
    """The on-disk summary conforms to the published schema."""
    import jsonschema
    from tests.contracts.test_schema_imputation_summary import SCHEMA

    project = create_project(tmp_path, "demo")
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) if i % 7 else None for i in range(40)]
    src = tmp_path / "d.csv"
    pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))}).to_csv(src, index=False)
    res = run_workflow(
        project.root, [src], mode="auto", y="y", x=["x"],
        imputation={"method": "mice"},
    )
    summary_path = project.root / "runs" / res["run_id"] / "model_results" / "imputation_summary.json"
    summary = json.loads(summary_path.read_text())
    jsonschema.validate(summary, SCHEMA)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_summary_artifact.py -v`
Expected: FAIL (`imputation_summary.json` not on disk).

- [ ] **Step 3: Update `ImputationStage` to persist + augment summary**

Open `backend/workbench/engine/stages/imputation.py`. After the existing line that stashes the summary into ctx (`ctx.artifacts["_imputation_summary"] = imputation_summary`), and ONLY when `imputation_summary` exists and `status == "completed"`, write to disk and register:

```python
        if imputation_summary is not None and imputation_summary.get("status") == "completed":
            # V1.5.4.1: augment with method-agnostic fields the contract requires.
            input_artifact_id = ctx.data.artifact_id  # at this point: "cleaned_dataset"
            imputation_summary.setdefault("input_artifact", input_artifact_id)
            imputation_summary.setdefault("output_artifact", "imputed_dataset")
            imputation_summary.setdefault(
                "rows_imputed",
                # rows-imputed = number of rows that had at least one missing cell
                # in any imputed column, before imputation. We approximate from
                # the summary's `imputed_columns` against the pre-imputation frame.
                _count_rows_with_any_missing(
                    ctx.data.frame, imputation_summary.get("imputed_columns", []),
                ),
            )

            summary_path = env.run_root / "model_results" / "imputation_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps(imputation_summary, indent=2))

            from ...artifacts import register_artifact
            register_artifact(
                env.run_root,
                "imputation_summary",
                summary_path,
                "metadata",
                "imputation",
                [input_artifact_id],
            )
```

Add the helper at module bottom (or top, alongside other helpers):

```python
def _count_rows_with_any_missing(frame, columns: list[str]) -> int:
    """Count rows where at least one of `columns` is missing.

    Used as a stable, method-agnostic approximation of `rows_imputed` for
    summaries that don't track this directly (run_mice_imputation doesn't).
    """
    if not columns:
        return 0
    present = [c for c in columns if c in frame.columns]
    if not present:
        return 0
    return int(frame[present].isna().any(axis=1).sum())
```

Add `import json` if missing.

- [ ] **Step 4: Run new test**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_summary_artifact.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Regenerate the imputation golden**

The `test_golden_imputation` test now sees a new artifact (`imputation_summary`) — its `artifacts` map changes. Delete the stale golden and let the test re-write:

```bash
rm tests/golden/imputation.json
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py::test_golden_imputation -v
# First run: SKIPS, writes new golden.
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py::test_golden_imputation -v
# Second run: PASSES against the new golden.
```

Inspect the new `tests/golden/imputation.json` to confirm it includes `"imputation_summary": ["cleaned_dataset"]` in the artifacts map AND the existing entries (cleaned_dataset, imputed_dataset, ols_1, diagnostics_ols_1, statistical_tests_*) are unchanged. **The point of regenerating: ONLY a new artifact appears; no existing entry mutates. If existing entries changed, you broke behavior — revert.**

- [ ] **Step 6: Full suite + 7 goldens individually**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -v
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: all 7 goldens pass; full suite 730 + 2 = **732 passed**.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/stages/imputation.py \
        tests/test_imputation_summary_artifact.py \
        tests/golden/imputation.json
git commit -m "feat(engine): persist imputation_summary.json + register artifact + new schema fields"
```

### Task 11 (slice 2 gate): full backend gate

- [ ] **Step 1: Run full backend suite**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: **732 passed**, 0 failures.

- [ ] **Step 2: All 7 goldens individually**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py -v
```
Expected: 7 PASS.

- [ ] **Step 3: All 6 invariants + behavior snapshot**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -v
```
Expected: 7 PASS.

- [ ] **Step 4: Push**

```bash
git push origin workbench-v1.5.4.1
```

---

## Slice 3 — Frontend Implementation (4 PRs, parallel to Slice 2)

> All slice-3 tests use `vi.stubGlobal("fetch", vi.fn())` (mirroring `frontend/src/api.test.ts`). Mock responses use the sample fixtures from slice 1. **No real backend needed.**

### Task 12 (PR 3a): `useCapabilities` hook + TS types

**Files:**
- Create: `frontend/src/capabilities/types.ts`
- Create: `frontend/src/capabilities/api.ts`
- Create: `frontend/src/capabilities/useCapabilities.ts`
- Test: `frontend/src/capabilities/useCapabilities.test.tsx`

- [ ] **Step 1: Write the TS types matching the schema**

```typescript
// frontend/src/capabilities/types.ts
// Mirrors docs/api-contracts/capabilities.md schema.
export type ModelGroup = "auto" | "Linear" | "Binary" | "Count" | "Panel" | "GLM";

export interface ModelTypeEntry {
  key: string;
  label: string;
  group: ModelGroup;
  description?: string;
  requires?: string[];
}

export interface ImputationMethodEntry {
  key: string;
  label: string;
  description?: string;
}

export interface Capabilities {
  schema_version: number;
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
}
```

- [ ] **Step 2: Write the API fetch helper**

```typescript
// frontend/src/capabilities/api.ts
import { apiUrl, readResponse } from "../api";
import type { Capabilities } from "./types";

export async function fetchCapabilities(): Promise<Capabilities> {
  const response = await fetch(apiUrl("/capabilities"));
  return readResponse<Capabilities>(response);
}
```

(Check that `apiUrl` and `readResponse` are exported from `frontend/src/api.ts`. If `readResponse` is not exported, export it now — it's already used internally; the export is a minimal change.)

- [ ] **Step 3: Write the failing hook test**

```typescript
// frontend/src/capabilities/useCapabilities.test.tsx
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCapabilities } from "./useCapabilities";
import sample from "../../../tests/contracts/capabilities.sample.json";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true, status: 200,
    json: () => Promise.resolve(body),
  } as Response;
}

test("useCapabilities fetches /capabilities and returns the payload", async () => {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(sample));
  const { result } = renderHook(() => useCapabilities());
  await waitFor(() => expect(result.current.data).toBeDefined());
  expect(result.current.data?.model_types.find((m) => m.key === "probit")).toBeDefined();
  expect(result.current.error).toBeUndefined();
});

test("useCapabilities surfaces errors", async () => {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
  const { result } = renderHook(() => useCapabilities());
  await waitFor(() => expect(result.current.error).toBeDefined());
  expect(result.current.data).toBeUndefined();
});
```

(`@testing-library/react`'s `renderHook` may live in `@testing-library/react/dist/index.js` depending on version. If your version is < 13.1, `renderHook` is in `@testing-library/react-hooks` — check `frontend/package.json` first; if the older package isn't installed, the included `@testing-library/react@15` is fine.)

- [ ] **Step 4: Run to verify FAIL**

Run from `frontend/`:
```bash
npx vitest run src/capabilities/useCapabilities.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 5: Implement the hook**

```typescript
// frontend/src/capabilities/useCapabilities.ts
import { useEffect, useState } from "react";
import { fetchCapabilities } from "./api";
import type { Capabilities } from "./types";

interface UseCapabilities {
  data?: Capabilities;
  error?: Error;
  loading: boolean;
}

export function useCapabilities(): UseCapabilities {
  const [data, setData] = useState<Capabilities | undefined>();
  const [error, setError] = useState<Error | undefined>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchCapabilities()
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { data, error, loading };
}
```

- [ ] **Step 6: Run test**

Run: `npx vitest run src/capabilities/useCapabilities.test.tsx`
Expected: 2 PASS.

- [ ] **Step 7: Full frontend suite (must stay 549 + 2 = 551)**

Run: `npx vitest run`
Expected: **551 passed**.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/capabilities/ frontend/src/api.ts
git commit -m "feat(frontend): useCapabilities hook + TS types matching contract"
```

### Task 13 (PR 3b): `ModelTypeSelect` component + App.tsx wiring

**Files:**
- Create: `frontend/src/runForm/ModelTypeSelect.tsx`
- Create: `frontend/src/runForm/ModelTypeSelect.test.tsx`
- Modify: `frontend/src/App.tsx` (remove hard-coded `<select>`, wire in new component)

- [ ] **Step 1: Write the failing component test**

```typescript
// frontend/src/runForm/ModelTypeSelect.test.tsx
import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ModelTypeSelect } from "./ModelTypeSelect";
import sample from "../../../tests/contracts/capabilities.sample.json";
import type { Capabilities } from "../capabilities/types";

const caps = sample as Capabilities;

test("renders one option per model_type plus optgroups by group", () => {
  render(<ModelTypeSelect capabilities={caps} value="auto" onChange={() => {}} />);
  // Every model_type key in the fixture must appear as an <option>.
  for (const m of caps.model_types) {
    expect(screen.getByRole("option", { name: m.label })).toBeInTheDocument();
  }
  // <optgroup> rendered for every non-auto group present in the fixture.
  const groups = new Set(caps.model_types.map((m) => m.group).filter((g) => g !== "auto"));
  for (const group of groups) {
    expect(document.querySelector(`optgroup[label="${group}"]`)).not.toBeNull();
  }
});

test("calls onChange with the selected key", () => {
  const onChange = vi.fn();
  render(<ModelTypeSelect capabilities={caps} value="auto" onChange={onChange} />);
  const select = screen.getByRole("combobox", { name: /model type/i });
  fireEvent.change(select, { target: { value: "probit" } });
  expect(onChange).toHaveBeenCalledWith("probit");
});

test("renders a placeholder when capabilities is undefined", () => {
  render(<ModelTypeSelect capabilities={undefined} value="auto" onChange={() => {}} />);
  // Falls back to a single auto option so the form is still submittable.
  expect(screen.getByRole("option", { name: /auto/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify FAIL**

Run: `npx vitest run src/runForm/ModelTypeSelect.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/runForm/ModelTypeSelect.tsx
import type { Capabilities, ModelGroup, ModelTypeEntry } from "../capabilities/types";


// Group rendering order. Groups absent from the data are simply omitted.
const GROUP_ORDER: ModelGroup[] = ["Linear", "Binary", "Count", "Panel", "GLM"];


function groupedByGroup(entries: ModelTypeEntry[]): Record<ModelGroup, ModelTypeEntry[]> {
  const out: Record<string, ModelTypeEntry[]> = {};
  for (const e of entries) {
    (out[e.group] = out[e.group] || []).push(e);
  }
  return out as Record<ModelGroup, ModelTypeEntry[]>;
}


export function ModelTypeSelect(props: {
  capabilities: Capabilities | undefined;
  value: string;
  onChange: (key: string) => void;
}) {
  const { capabilities, value, onChange } = props;

  // Fallback: pre-capabilities render — show only Auto so the form stays usable.
  if (!capabilities) {
    return (
      <select
        aria-label="model type"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="auto">Auto (infer from y)</option>
      </select>
    );
  }

  const grouped = groupedByGroup(capabilities.model_types);
  const autoEntry = capabilities.model_types.find((m) => m.key === "auto");

  return (
    <select
      aria-label="model type"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {autoEntry && <option value="auto">{autoEntry.label}</option>}
      {GROUP_ORDER.map((group) =>
        grouped[group]?.length ? (
          <optgroup key={group} label={group}>
            {grouped[group].map((m) => (
              <option key={m.key} value={m.key} title={m.description}>
                {m.label}
              </option>
            ))}
          </optgroup>
        ) : null
      )}
    </select>
  );
}
```

- [ ] **Step 4: Run component tests**

Run: `npx vitest run src/runForm/ModelTypeSelect.test.tsx`
Expected: 3 PASS.

- [ ] **Step 5: Wire into `App.tsx`**

Open `frontend/src/App.tsx`. At the top, add imports:

```tsx
import { useCapabilities } from "./capabilities/useCapabilities";
import { ModelTypeSelect } from "./runForm/ModelTypeSelect";
```

In the component body (near `const [modelType, setModelType] = useState("auto");`), add:

```tsx
const { data: capabilities } = useCapabilities();
```

Find the existing hard-coded `<select>` for model type (around line 380, the `<label>Model type ...</label>` block with 4 hard-coded `<option>` elements). Replace the entire `<select aria-label="model type" ...>...</select>` with:

```tsx
<ModelTypeSelect
  capabilities={capabilities}
  value={modelType}
  onChange={setModelType}
/>
```

Keep the surrounding `<label>Model type ...</label>` wrapper.

- [ ] **Step 6: Run full FE suite**

Run: `npx vitest run`
Expected: **551 + 3 = 554 passed**, 0 failures. Any existing test that depended on the hard-coded `<option>` text via `getByRole("option", { name: "OLS (linear regression)" })` may need a label-text update — when a test fails, fix the assertion to match the new capabilities-derived label (`"OLS (linear)"`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runForm/ModelTypeSelect.tsx \
        frontend/src/runForm/ModelTypeSelect.test.tsx \
        frontend/src/App.tsx
git commit -m "feat(frontend): ModelTypeSelect from capabilities; replace hard-coded dropdown"
```

### Task 14 (PR 3c): `FailureCard` component + runResult.tsx wiring

**Files:**
- Create: `frontend/src/runResult/FailureCard.tsx`
- Create: `frontend/src/runResult/FailureCard.test.tsx`
- Modify: `frontend/src/runResult.tsx`

- [ ] **Step 1: Write the failing component test**

```typescript
// frontend/src/runResult/FailureCard.test.tsx
import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { FailureCard } from "./FailureCard";
import sampleActions from "../../../tests/contracts/recommended_actions.model_fit_failure.sample.json";

const sampleEvidence = {
  error_code: "MODEL_FIT_FAILED",
  requested_model_type: "logit",
  root_cause: "ValueError: y must be binary (got 40 unique continuous values)",
  y_type: "continuous",
  recommended_actions: sampleActions,
};

test("renders the requested model name + root cause", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  expect(screen.getByText(/logit/)).toBeInTheDocument();
  expect(screen.getByText(/y must be binary/)).toBeInTheDocument();
});

test("renders one button per recommended_action", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  for (const action of sampleActions) {
    expect(screen.getByRole("button", { name: action.label })).toBeInTheDocument();
  }
});

test("clicking an action calls onAction with the action object", () => {
  const onAction = vi.fn();
  render(<FailureCard evidence={sampleEvidence} onAction={onAction} />);
  fireEvent.click(screen.getByRole("button", { name: "Re-run with auto" }));
  expect(onAction).toHaveBeenCalledTimes(1);
  expect(onAction.mock.calls[0][0].key).toBe("rerun_auto");
  expect(onAction.mock.calls[0][0].form_overrides).toEqual({ model_type: "auto" });
});

test("primary action has different visual styling than secondary", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  const primary = screen.getByRole("button", { name: "Re-run with auto" });
  const secondary = screen.getByRole("button", { name: "Change model type" });
  expect(primary.className).not.toEqual(secondary.className);
});

test("renders nothing when no recommended_actions present", () => {
  const { container } = render(
    <FailureCard evidence={{ error_code: "X", root_cause: "y" }} onAction={() => {}} />,
  );
  // Component should still render the story (root_cause) but no button row.
  expect(screen.getByText(/y/)).toBeInTheDocument();
  expect(container.querySelectorAll("button").length).toBe(0);
});
```

- [ ] **Step 2: Run to verify FAIL**

Run: `npx vitest run src/runResult/FailureCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/runResult/FailureCard.tsx
export interface RecommendedAction {
  key: string;
  label: string;
  severity: "primary" | "secondary";
  form_overrides?: Record<string, unknown>;
  hint?: string;
}

export interface FailureEvidence {
  error_code?: string;
  requested_model_type?: string;
  root_cause?: string;
  y_type?: string;
  recommended_actions?: RecommendedAction[];
}

export function FailureCard(props: {
  evidence: FailureEvidence;
  onAction: (action: RecommendedAction) => void;
}) {
  const { evidence, onAction } = props;
  const actions = evidence.recommended_actions ?? [];
  const requested = evidence.requested_model_type;

  return (
    <div className="failure-card" role="alert" aria-label="Model fit failed">
      <div className="failure-card-title">
        {requested && requested !== "auto"
          ? `The model you requested (${requested}) could not be fit on this data`
          : "Model fit failed"}
      </div>
      {evidence.root_cause && (
        <pre className="failure-card-cause">{evidence.root_cause}</pre>
      )}
      {actions.length > 0 && (
        <div className="failure-card-actions">
          {actions.map((a) => (
            <button
              key={a.key}
              type="button"
              className={`failure-action failure-action-${a.severity}`}
              title={a.hint}
              onClick={() => onAction(a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

Add minimal CSS for the new classes — open `frontend/src/index.css` (or whichever stylesheet `runResult.tsx` already uses; check imports) and append:

```css
.failure-card { border: 1px solid #fca5a5; background: #fef2f2; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }
.failure-card-title { font-weight: 600; color: #991b1b; font-size: 14px; margin-bottom: 4px; }
.failure-card-cause { font-family: monospace; font-size: 12px; color: #7f1d1d; background: #fee2e2; padding: 6px 8px; border-radius: 4px; margin: 4px 0 10px; white-space: pre-wrap; }
.failure-card-actions { display: flex; gap: 8px; margin-top: 8px; }
.failure-action { padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.failure-action-primary { background: #dc2626; color: white; border: 0; font-weight: 500; }
.failure-action-secondary { background: white; color: #374151; border: 1px solid #d1d5db; }
```

- [ ] **Step 4: Run component tests**

Run: `npx vitest run src/runResult/FailureCard.test.tsx`
Expected: 5 PASS.

- [ ] **Step 5: Wire into `runResult.tsx`**

Open `frontend/src/runResult.tsx`. Add import:

```tsx
import { FailureCard, type RecommendedAction } from "./runResult/FailureCard";
```

Find the section where `problemIssues` is computed (around line 269). Right after, derive the failure evidence:

```tsx
  const fitFailure = problemIssues.find((i) => i.code === "MODEL_FIT_FAILED");
  // GuardrailIssue.to_dict() puts evidence under `details`; verify on real data.
  const failureEvidence = (fitFailure?.details ?? {}) as Record<string, unknown>;
  const hasFailureCard =
    detail.status === "failed" && fitFailure !== undefined;
```

(If the actual key is `evidence` or another, adjust based on inspecting a real `errors.json` from a failed run. The slice-2d invariant test already locks this name; reuse the same key.)

The component needs an action handler. The caller of `runResult` (App.tsx) owns the form state, so accept a prop from the parent — but `runResult.tsx` is invoked by `runHistory.tsx` and others. The minimum-friction path: have `runResult.tsx` accept an optional `onFailureAction?: (action: RecommendedAction, evidence) => void` prop, default no-op. App.tsx passes a handler that updates form state and re-submits.

Add the prop to the `runResult.tsx` props type, then in the JSX (right after the existing status badge and before the issues list), insert:

```tsx
      {hasFailureCard && (
        <FailureCard
          evidence={failureEvidence as never}
          onAction={(action) => props.onFailureAction?.(action, failureEvidence)}
        />
      )}
```

In `App.tsx`, supply the handler when it renders `runResult`:

```tsx
<RunResult
  detail={detail}
  /* ...existing props... */
  onFailureAction={(action) => {
    if (action.form_overrides) {
      const overrides = action.form_overrides;
      if (typeof overrides.model_type === "string") setModelType(overrides.model_type);
      // future: overrides.imputation, etc.
      // Trigger a re-submit. Reuse the existing "Run analysis" handler.
      // For V1.5.4.1 keep the change form-only — user can click "Run" again.
      // (E2E test in slice 4 will validate the recovery flow.)
    }
  }}
/>
```

The minimum V1.5.4.1 behavior: clicking "Re-run with auto" sets the form's `modelType` back to `"auto"`; the user clicks the existing Run button to submit. Slice 4 may automate the submit if simple, but it's NOT required for this PR.

- [ ] **Step 6: Run full FE suite**

Run: `npx vitest run`
Expected: **554 + 5 = 559 passed**, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runResult/FailureCard.tsx \
        frontend/src/runResult/FailureCard.test.tsx \
        frontend/src/runResult.tsx \
        frontend/src/App.tsx \
        frontend/src/index.css
git commit -m "feat(frontend): FailureCard renders failure_evidence + recommended_actions"
```

### Task 15 (PR 3d): `ImputationControls` + `ImputationSummary` + form wiring

**Files:**
- Create: `frontend/src/runForm/ImputationControls.tsx` + test
- Create: `frontend/src/runResult/ImputationSummary.tsx` + test
- Modify: `frontend/src/api.ts` (runWorkflow signature) + `App.tsx` + `runResult.tsx`

- [ ] **Step 1: Write failing test for ImputationControls**

```typescript
// frontend/src/runForm/ImputationControls.test.tsx
import { afterEach, expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ImputationControls } from "./ImputationControls";
import type { Capabilities } from "../capabilities/types";

const caps_one: Capabilities = {
  schema_version: 1,
  model_types: [],
  imputation_methods: [
    { key: "mice", label: "MICE (Multiple Imputation)" },
  ],
};

const caps_two: Capabilities = {
  schema_version: 1,
  model_types: [],
  imputation_methods: [
    { key: "mice", label: "MICE" },
    { key: "knn", label: "KNN" },
  ],
};

test("with exactly one imputation method renders a checkbox", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  expect(screen.getByRole("checkbox", { name: /mice/i })).toBeInTheDocument();
});

test("with two+ methods renders a select", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_two} value={null} onChange={onChange} />);
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});

test("checkbox emits the method key on change", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={null} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith("mice");
});

test("checkbox emits null when unchecked", () => {
  const onChange = vi.fn();
  render(<ImputationControls capabilities={caps_one} value={"mice"} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /mice/i }));
  expect(onChange).toHaveBeenCalledWith(null);
});

test("renders nothing when capabilities undefined or imputation_methods empty", () => {
  const { container, rerender } = render(
    <ImputationControls capabilities={undefined} value={null} onChange={() => {}} />,
  );
  expect(container.firstChild).toBeNull();

  rerender(
    <ImputationControls
      capabilities={{ schema_version: 1, model_types: [], imputation_methods: [] }}
      value={null}
      onChange={() => {}}
    />,
  );
  expect(container.firstChild).toBeNull();
});
```

- [ ] **Step 2: Run to verify FAIL**

Run: `npx vitest run src/runForm/ImputationControls.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `ImputationControls`**

```tsx
// frontend/src/runForm/ImputationControls.tsx
import type { Capabilities } from "../capabilities/types";


export function ImputationControls(props: {
  capabilities: Capabilities | undefined;
  value: string | null;     // method key or null (not requested)
  onChange: (key: string | null) => void;
}) {
  const methods = props.capabilities?.imputation_methods ?? [];
  if (methods.length === 0) return null;

  if (methods.length === 1) {
    const only = methods[0];
    return (
      <div className="imputation-controls">
        <label>
          <input
            type="checkbox"
            checked={props.value === only.key}
            onChange={(e) => props.onChange(e.target.checked ? only.key : null)}
          />{" "}
          Impute missing values ({only.label})
        </label>
        {only.description && (
          <div className="imputation-controls-hint">{only.description}</div>
        )}
      </div>
    );
  }

  // 2+ methods: select
  return (
    <div className="imputation-controls">
      <label>
        Imputation
        <select
          value={props.value ?? ""}
          onChange={(e) => props.onChange(e.target.value || null)}
        >
          <option value="">(none)</option>
          {methods.map((m) => (
            <option key={m.key} value={m.key} title={m.description}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
```

Add minimal CSS to `index.css`:
```css
.imputation-controls { background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 6px; padding: 10px 12px; margin: 10px 0; }
.imputation-controls-hint { font-size: 12px; color: #0c4a6e; margin-top: 6px; padding-left: 22px; }
```

- [ ] **Step 4: Run ImputationControls tests**

Run: `npx vitest run src/runForm/ImputationControls.test.tsx`
Expected: 5 PASS.

- [ ] **Step 5: Write failing test for `ImputationSummary`**

```typescript
// frontend/src/runResult/ImputationSummary.test.tsx
import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import { ImputationSummary } from "./ImputationSummary";
import sample from "../../../tests/contracts/imputation_summary.mice.sample.json";

test("renders core fields from a MICE summary", () => {
  render(<ImputationSummary summary={sample as never} />);
  expect(screen.getByText(/MICE/i)).toBeInTheDocument();
  expect(screen.getByText(/17/)).toBeInTheDocument();  // rows_imputed
  expect(screen.getByText(/education/)).toBeInTheDocument();
  expect(screen.getByText(/imputed_dataset/)).toBeInTheDocument();
});

test("renders nothing if summary is undefined", () => {
  const { container } = render(<ImputationSummary summary={undefined} />);
  expect(container.firstChild).toBeNull();
});
```

- [ ] **Step 6: Run to verify FAIL**

Run: `npx vitest run src/runResult/ImputationSummary.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 7: Implement `ImputationSummary`**

```tsx
// frontend/src/runResult/ImputationSummary.tsx
export interface ImputationSummaryData {
  schema_version: number;
  method: string;
  status: string;
  rows_imputed?: number;
  imputed_columns?: string[];
  input_artifact: string;
  output_artifact: string;
  // method-specific (mice)
  m?: number;
  max_iter?: number;
  [key: string]: unknown;
}


export function ImputationSummary(props: { summary: ImputationSummaryData | undefined }) {
  const s = props.summary;
  if (!s) return null;
  const label = s.method.toUpperCase();
  const cols = s.imputed_columns ?? [];
  return (
    <section className="imputation-summary" aria-label="Imputation summary">
      <div className="imputation-summary-title">
        💧 Imputation applied ({label})
      </div>
      <ul className="imputation-summary-list">
        <li>
          Imputed <strong>{s.rows_imputed ?? 0} rows</strong>
          {cols.length > 0 ? (
            <> across <strong>{cols.length} columns</strong> ({cols.map((c) => <code key={c}>{c}</code>).reduce<React.ReactNode[]>((acc, x, i) => (i === 0 ? [x] : [...acc, ", ", x]), [])})</>
          ) : null}
        </li>
        {s.method === "mice" && s.m !== undefined && (
          <li>
            <code>iterative</code> · <strong>{s.m}</strong> imputations
            {s.max_iter !== undefined && <> · max <strong>{s.max_iter}</strong> iters</>}
          </li>
        )}
        <li>
          Model lineage: <strong>{s.output_artifact}</strong>
          {" "}<span className="hint">(stats ran on {s.input_artifact})</span>
        </li>
      </ul>
    </section>
  );
}
```

Add CSS:
```css
.imputation-summary { border: 1px solid #bae6fd; background: #f0f9ff; border-radius: 6px; padding: 10px 12px; margin-bottom: 14px; }
.imputation-summary-title { font-weight: 600; font-size: 13px; color: #0c4a6e; margin-bottom: 4px; }
.imputation-summary-list { margin: 0; padding-left: 24px; font-size: 12px; color: #0c4a6e; line-height: 1.6; }
.imputation-summary code { background: #e0f2fe; padding: 1px 4px; border-radius: 3px; }
.imputation-summary .hint { color: #94a3b8; }
```

- [ ] **Step 8: Run ImputationSummary tests**

Run: `npx vitest run src/runResult/ImputationSummary.test.tsx`
Expected: 2 PASS.

- [ ] **Step 9: Extend `runWorkflow` in `api.ts` to accept `imputation`**

Open `frontend/src/api.ts`. Locate `export async function runWorkflow(`. Add `imputation?: string` after `transpose?`:

```typescript
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
  form.append("file", file);
  const response = await fetch(apiUrl("/runs"), { method: "POST", body: form });
  return readResponse<RunResponse>(response);
}
```

- [ ] **Step 10: Wire `ImputationControls` into App.tsx**

Open `frontend/src/App.tsx`. Add state and component:

```tsx
const [imputationMethod, setImputationMethod] = useState<string | null>(null);
```

Below the `ModelTypeSelect`, add:

```tsx
<ImputationControls
  capabilities={capabilities}
  value={imputationMethod}
  onChange={setImputationMethod}
/>
```

In the submit handler (where `runWorkflow(...)` is called), pass:

```tsx
const imputationPayload =
  imputationMethod ? JSON.stringify({ method: imputationMethod }) : undefined;
const result = await runWorkflow(
  projectRoot.trim(),
  mode,
  y.trim(),
  x.trim(),
  file,
  modelType,
  sheetName,
  transpose,
  imputationPayload,
);
```

(Adjust to existing argument order.)

Import:
```tsx
import { ImputationControls } from "./runForm/ImputationControls";
```

- [ ] **Step 11: Wire `ImputationSummary` into `runResult.tsx`**

When the run completes, the imputation summary lives at `runs/<id>/model_results/imputation_summary.json` and is registered as artifact `imputation_summary`. The frontend already has artifact-fetching plumbing (see `api.ts::fetchRunArtifacts` etc.). The simplest wiring: fetch the artifact JSON when its id is present in `detail.artifacts`.

Add a helper hook or `useEffect` in `runResult.tsx`:

```tsx
import { ImputationSummary, type ImputationSummaryData } from "./runResult/ImputationSummary";
import { fetchArtifactJson } from "./api";  // existing or add a thin wrapper if absent

const [imputationData, setImputationData] = useState<ImputationSummaryData | undefined>();
useEffect(() => {
  // detail.artifacts may be a list of artifact ids (or {artifact_id, ...} objects — inspect).
  const hasSummary = (detail.artifacts ?? []).some(
    (a: any) => (typeof a === "string" ? a : a.artifact_id) === "imputation_summary"
  );
  if (!hasSummary) { setImputationData(undefined); return; }
  fetchArtifactJson(detail.run_id, "imputation_summary")
    .then(setImputationData)
    .catch(() => setImputationData(undefined));
}, [detail.run_id]);
```

(If `fetchArtifactJson` doesn't exist, add a small wrapper in `api.ts` next to `fetchRunArtifacts`:
```typescript
export async function fetchArtifactJson(runId: string, artifactId: string): Promise<any> {
  const response = await fetch(apiUrl(`/runs/${runId}/artifacts/${artifactId}`));
  return readResponse<any>(response);
}
```
Check that `/runs/{run_id}/artifacts/{artifact_id}` is the real path — it appears in `api.py:561`.)

Render in JSX before the issues list:

```tsx
<ImputationSummary summary={imputationData} />
```

- [ ] **Step 12: Run full FE suite**

Run: `npx vitest run`
Expected: **559 + 5 + 2 = 566 passed**.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/runForm/ImputationControls.tsx \
        frontend/src/runForm/ImputationControls.test.tsx \
        frontend/src/runResult/ImputationSummary.tsx \
        frontend/src/runResult/ImputationSummary.test.tsx \
        frontend/src/api.ts \
        frontend/src/App.tsx \
        frontend/src/runResult.tsx \
        frontend/src/index.css
git commit -m "feat(frontend): ImputationControls + ImputationSummary; form transmits imputation kwarg"
```

### Task 16 (slice 3 gate): full FE gate + cumulative push

- [ ] **Step 1: Run full FE suite**

Run: `npx vitest run`
Expected: **566 passed**, 0 failures.

- [ ] **Step 2: Run full BE suite again to be safe (slice 3 didn't change backend, but confirm)**

Run: `env PYTHONPATH=backend .venv/bin/python -m pytest -q`
Expected: **732 passed**.

- [ ] **Step 3: Push**

```bash
git push origin workbench-v1.5.4.1
```

---

## Slice 4 — Integration (1 PR, after slice 2 + 3 both merged)

### Task 17 (PR 4a): End-to-end failure recovery flow test

**Files:**
- Create: `frontend/src/e2e/failure-recovery.test.tsx` (using vitest + jsdom + a real backend via TestClient subprocess) **OR** if a Playwright config doesn't already exist, write the e2e as a Python test that starts the backend then drives requests directly through the API — see Step 2 for which path to pick.

- [ ] **Step 1: Choose e2e harness based on existing setup**

Run:
```bash
ls frontend/playwright.config.* frontend/e2e/ 2>/dev/null
```
- If files exist → write a Playwright spec.
- If nothing exists → use a **Python integration test** instead (cheaper to set up, single language). Choose the Python path unless Playwright is already present.

- [ ] **Step 2 (Python path — recommended): write the integration test**

```python
# tests/test_e2e_failure_recovery.py
"""End-to-end: explicit failure -> recommended_actions injected ->
FailureCard would render -> primary action carries form_overrides for
one-click recovery.

This is an API-level e2e (not a browser test) because the frontend
form_overrides handling is a pure React state update covered by the
slice 3 component test. The integration assertion is: backend ships the
exact `recommended_actions` payload the frontend expects to receive."""
import io
import json
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json
from workbench.projects import create_project


def _wait_terminal(project_root: Path, run_id: str, deadline_s: float = 30.0) -> str:
    manifest_path = project_root / "runs" / run_id / "run_manifest.json"
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline_s:
        if manifest_path.exists():
            status = read_json(manifest_path).get("status")
            if status in {"completed", "failed", "blocked"}:
                return status
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish")


def test_explicit_logit_failure_offers_one_click_rerun_auto(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    client = TestClient(app)

    # 1. Confirm /capabilities lists logit (frontend would render it).
    caps = client.get("/capabilities").json()
    assert any(m["key"] == "logit" for m in caps["model_types"])

    # 2. Submit a run with explicit logit on continuous y -> must fail.
    ys = [1.5 * i for i in range(40)]
    xs = list(range(40))
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    payload = frame.to_csv(index=False).encode()
    res = client.post(
        "/runs",
        data={
            "project_root": str(project.root),
            "mode": "auto",
            "model_type": "logit",
            "y": "y",
            "x": "x",
        },
        files={"file": ("d.csv", io.BytesIO(payload), "text/csv")},
    )
    assert res.status_code == 200
    run_id = res.json()["run_id"]
    status = _wait_terminal(project.root, run_id)
    assert status == "failed", f"expected failed, got {status}"

    # 3. errors.json carries the recommended_actions payload.
    errors = read_json(project.root / "runs" / run_id / "errors.json")
    blockers = [i for i in errors["issues"]
                if i.get("code") == "MODEL_FIT_FAILED" and i.get("severity") == "BLOCKER"]
    assert blockers, "expected a BLOCKER MODEL_FIT_FAILED"
    actions = blockers[0]["details"].get("recommended_actions", [])
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["key"] == "rerun_auto"
    assert primary["form_overrides"] == {"model_type": "auto"}

    # 4. Apply the recovery (re-run with auto) and assert success.
    res2 = client.post(
        "/runs",
        data={
            "project_root": str(project.root),
            "mode": "auto",
            "model_type": primary["form_overrides"]["model_type"],
            "y": "y",
            "x": "x",
        },
        files={"file": ("d.csv", io.BytesIO(payload), "text/csv")},
    )
    assert res2.status_code == 200
    status2 = _wait_terminal(project.root, res2.json()["run_id"])
    assert status2 == "completed"
```

(GuardrailIssue serializes evidence under `details`. If a fresh `errors.json` shows it under `evidence` instead, switch the key in the assertion.)

- [ ] **Step 3: Run e2e + full suite**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_e2e_failure_recovery.py -v
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: e2e passes; full suite **732 + 1 = 733 passed**.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_failure_recovery.py
git commit -m "test(e2e): explicit failure -> recommended_actions -> one-click rerun_auto -> success"
```

### Task 18 (PR 4b): `docs/extensions.md` extension — capability-manifest section

**Files:**
- Modify: `docs/extensions.md`

- [ ] **Step 1: Append the new section**

At the end of `docs/extensions.md`, append a new top-level section:

```markdown
## How a new model_type / imputation_method auto-appears in the UI (V1.5.4.1 capability manifest)

The frontend run form and the FailureCard are **derived dynamically** from the backend `/capabilities` endpoint. To ship a new model_type or imputation method end-to-end:

### 1. Register the model handler (or imputation method)

```python
# in your_pack/__init__.py
from workbench.engine.registry import ModelHandler
from workbench.engine.pack import AnalysisPack, register_pack

def _fit_ridge(ctx, env):
    # ...
    return "ridge_1", primary_result_dict, fitted_model_or_None

register_pack(AnalysisPack(
    pack_id="ridge_pack",
    model_handlers=[ModelHandler(
        model_type="ridge", model_id="ridge_1",
        serves_y_types=("continuous",), fit=_fit_ridge,
    )],
))
```

### 2. Add UI metadata to `engine/capabilities.py::_MODEL_METADATA`

```python
_MODEL_METADATA["ridge"] = {
    "label": "Ridge",
    "group": "Linear",   # must be one of: Linear / Binary / Count / Panel / GLM / auto
    "description": "Ridge regression with L2 penalty.",
}
```

### 3. (Optional) Document the contract impact

If your model carries a new data-shape requirement (like `panel_ols` does with `entity_or_time`), add it to the `requires:` list in step 2. The frontend currently treats `requires` as advisory (rendered as a tooltip). The "C plan" — fully data-aware disabling — is tracked as a future enhancement, see Future C-plan memo below.

### 4. The UI updates itself

- `GET /capabilities` now lists your new entry.
- `ModelTypeSelect` renders it under its group automatically.
- `FailureCard`'s `recommended_actions` already supports `change_model` for any model_type; users can pick yours from the dropdown after a failure.

### Imputation methods

Same pattern but smaller:

```python
from workbench.engine.imputation_registry import ImputationMethod, register_imputation_method

register_imputation_method(ImputationMethod(
    key="knn", label="KNN Imputation",
    description="K-nearest-neighbors imputation for missing values.",
))
```

The frontend `ImputationControls` will automatically upgrade from a single-method checkbox to a multi-option select when `imputation_methods.length >= 2` — no frontend code change required.

### Future C-plan memo (data-aware disabling)

The slice-1 schema reserved a `requires: ["entity_or_time"]` field on `panel_ols`. The current frontend (B plan) shows this as a tooltip only. A future version will:
1. Wait for the file profile to load.
2. Inspect `id_candidates` and `time_candidates` on the profile.
3. Disable model_types whose `requires` are unmet, with a hover-explanation.

This needs a small async dependency: `ModelTypeSelect` must accept an optional `profile?: FileProfile` prop and use it for disable logic. The `requires` field is already in the schema, so this is purely a frontend enhancement when ready.
```

- [ ] **Step 2: Commit**

```bash
git add docs/extensions.md
git commit -m "docs(extensions): how new model_type / imputation_method appears in UI via capability manifest"
```

### Task 19 (slice 4 gate / final V1.5.4.1 gate)

- [ ] **Step 1: Final backend gate**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest -q
```
Expected: **733 passed**, 0 failures.

- [ ] **Step 2: Final frontend gate**

```bash
cd frontend && npx vitest run && cd ..
```
Expected: **566 passed** (unchanged from end of slice 3 — slice 4 added no FE code).

- [ ] **Step 3: 7 goldens individually + 7 invariants/snapshot**

```bash
env PYTHONPATH=backend .venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -v
```
Expected: 14 PASS.

- [ ] **Step 4: Spec success-criteria proof checklist**

Confirm each:
1. **User can pick from 10 model_type options** — open `frontend/src/runForm/ModelTypeSelect.tsx` rendering proven by `ModelTypeSelect.test.tsx`; capabilities sample has all 10 (`tests/contracts/capabilities.sample.json`).
2. **Explicit logit + non-binary y → failure card with 3 actions** — `tests/test_e2e_failure_recovery.py` (backend side) + `FailureCard.test.tsx` (frontend side).
3. **MICE checkbox → MICE runs → ImputationSummary panel** — `tests/test_api_runs_imputation.py` (run path) + `tests/test_imputation_summary_artifact.py` (artifact) + `ImputationSummary.test.tsx` (UI).
4. **New model_type → backend register + auto in UI = zero FE change** — covered conceptually by `_MODEL_METADATA` table + `test_register_model_extends_registry_without_touching_orchestrator` (V1.5.4 test, still green).
5. **New imputation method = single-line frontend update (checkbox → select)** — covered by `ImputationControls.test.tsx` rendering for `caps_two` (already passes).
6. **All V1.5.4 tests still green** — `pytest -q` shows 733.
7. **1.5.3.2 explicit-failure contract preserved** — `test_invariant_explicit_model_type_failure_returns_failed_no_silent_fallback` extended with `recommended_actions` assertion (slice 2d), still green.

- [ ] **Step 5: Final push**

```bash
git push origin workbench-v1.5.4.1
```

- [ ] **Step 6: (Optional) Open PR to base**

```bash
gh pr create --base workbench-v1.5.4 --head workbench-v1.5.4.1 \
  --title "V1.5.4.1: UI ↔ V1.5.3.2 backend capability gap closure" \
  --body "Spec: docs/superpowers/specs/2026-06-03-workbench-v1.5.4.1-frontend-backend-gap-design.md
Plan: docs/superpowers/plans/2026-06-03-workbench-v1.5.4.1-frontend-backend-gap.md

Capability-manifest driven: backend exposes /capabilities derived from MODEL_REGISTRY + IMPUTATION_REGISTRY; frontend renders dynamically. Future new models / imputation methods = backend registration only, zero frontend changes.

Closes the 'engine built, no steering wheel' gap from V1.5.3.2:
- 10 model_type options now in UI dropdown (was 4)
- MICE imputation toggle + result panel
- Explicit failure shown as story card + one-click 'Re-run with auto'

Gates: BE 733 / FE 566 / 7 goldens 0 drift / 7 invariants & snapshot / 1 e2e."
```

---

## Self-Review Notes (coverage map vs spec)

- **§0 background** → covered in plan intro + Task 18 docs extension.
- **§1 scope — 11 things to do** → mapped to Tasks 1-15:
  1. /capabilities endpoint → Task 6
  2. run_workflow imputation kwarg → Task 7
  3. /runs POST imputation form → Task 8
  4. recommended_actions injection → Task 9
  5. imputation_summary.json persistence → Task 10
  6. useCapabilities hook → Task 12
  7. ModelTypeSelect component → Task 13
  8. FailureCard component → Task 14
  9. ImputationControls component → Task 15
  10. ImputationSummary component → Task 15
  11. contract docs + fixtures → Tasks 1-4
- **§1 things NOT to do** → none accidentally introduced; prediction passthrough left untouched (V1.5.4 status quo); panel_ols `requires` is in schema but UI disable logic deferred (Task 18 documents).
- **§2.1 Capability Manifest** → Task 6 (`build_capabilities()` is the single source).
- **§2.2 run_workflow signature** → Task 7 (`imputation: dict | None`, additive keyword arg).
- **§2.3 recommended_actions** → Task 9 (`recommended_actions.py` factory + injection).
- **§2.4 imputation_summary schema** → Task 10 (`schema_version=1`, three new fields, MICE method-specific fields preserved).
- **§2.5 frontend component layout** → Tasks 12-15 (file structure matches spec exactly).
- **§3 slice plan** → Tasks 0-19 follow slice 0/1/2/3/4 boundaries.
- **§4 tests** → contract tests (Tasks 1-3), backend tests (each backend task), component tests (each frontend task), e2e (Task 17). Existing 705 BE + 549 FE remain green throughout.
- **§5 success standards (7)** → Task 19 Step 4 explicit proof checklist.
- **§6 collaboration posture** → reflected in slice gates (Tasks 5, 11, 16): contracts pushed first; back/front parallel after.

**Placeholder scan:** no "TBD"/"TODO"/"fill in details" placeholders. Every step has executable code or explicit commands. Two judgment calls flagged ("if Playwright config exists pick that path otherwise Python e2e" at Task 17, "verify `details` vs `evidence` key by inspecting real errors.json" at Tasks 9 and 14) — these are documented inline rather than left implicit.

**Type-name consistency check:** `Capabilities` / `ModelTypeEntry` / `ImputationMethodEntry` (frontend) used consistently in Tasks 12-15. `failure_evidence.recommended_actions` array element shape consistent between Task 9 (factory output) and Task 14 (frontend consumer). `imputation: dict | None` kwarg signature matches across Tasks 7, 8, 10.

---

## Final test counts (for verification)

| Stage | BE | FE | Goldens / Invariants |
|---|---|---|---|
| Phase 0 baseline | 705 | 549 | 7 / 7 |
| After Task 1 | 709 (+4) | 549 | 7 / 7 |
| After Task 2 | 712 (+3) | 549 | 7 / 7 |
| After Task 3 | 715 (+3) | 549 | 7 / 7 |
| After Task 6 | 722 (+7) | 549 | 7 / 7 |
| After Task 7 | 724 (+2) | 549 | 7 / 7 |
| After Task 8 | 726 (+2) | 549 | 7 / 7 |
| After Task 9 | 730 (+4) | 549 | 7 / 7 (invariant 5 extended) |
| After Task 10 | 732 (+2) | 549 | 7 / 7 (imputation golden regenerated, additive) |
| After Task 12 | 732 | 551 (+2) | 7 / 7 |
| After Task 13 | 732 | 554 (+3) | 7 / 7 |
| After Task 14 | 732 | 559 (+5) | 7 / 7 |
| After Task 15 | 732 | 566 (+7) | 7 / 7 |
| After Task 17 | 733 (+1 e2e) | 566 | 7 / 7 |

Final: **BE 733 / FE 566 / 7 goldens 0 drift / 7 invariants & snapshot.**
