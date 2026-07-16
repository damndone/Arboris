# Workbench v1.6.0 — Lineage Op-Layer Slice 1 (editable-op backend contract) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend "editable-op contract": every editable graph node resolves to an OperationContract, and a node can produce a new immutable run via validated overrides while preserving lineage — execution stays a full re-run; UI, AI, and incremental execution are deferred.

**Architecture:** Manifest-driven, zero per-estimator branches in the op layer. Capabilities manifest gains a per-op `params` schema + `schema_id` + `editable_stages`. Each run persists `run_inputs.json` (generic form bag + content-addressable upload by sha256 + lineage fields). A new `POST /runs/{id}/rerun` validates overrides structurally against the manifest, then re-runs the whole pipeline as a new immutable run linked by `rerun_of`. `GET /runs/{id}/graph` decorates editable nodes at response time only.

**Tech Stack:** Python 3.11, FastAPI, pytest; React + Vite + TypeScript (type-sync only this slice); `./scripts/gate.sh` gate.

**Spec:** `docs/superpowers/specs/2026-06-22-workbench-v1.6.0-lineage-op-contract-design.md`

**Grounding adjustments vs spec (confirmed against code at `1f1bc8f`):**
- `editable_stages = ["model"]` only — imputation has no graph node (graph nodes are
  `stage:raw`, `stage:cleaned`, `var:*`, `model:{id}`, `report:html`). Imputation joins
  when it gets a node (future slice).
- The capabilities manifest field stays named `schema_version` (bump 2→3), NOT renamed to
  `capabilities_schema_version` — renaming breaks the established contract test
  (`additionalProperties:False`, required `schema_version`) and FE `Capabilities.schema_version`.
  The three independent version axes are still honored: `schema_version` (capabilities),
  `run_input_schema_version` (run_inputs.json), `schema_id` (per-op `"{op_type}@v{n}"`).

**Standing rules for every task:**
- Work only inside `.worktrees/workbench-v1.6.0` (branch `workbench-v1.6.0`).
- **NEVER `git push`.** Commit locally only.
- Run backend tests with `.venv/bin/python -m pytest` (never bare `pytest`).
- **golden 0-drift is a hard gate.** After any task that could touch engine output, run
  the golden subset (see Task 0). The engine is NOT modified in this slice; if golden
  drifts, you broke an invariant — stop and fix.
- Manifest changes need **4-way sync (G0-5):** backend key / contract schema + sample / FE
  type / drift-guard test.

---

## File structure (created / modified)

**Created (backend):**
- `backend/workbench/lineage/__init__.py` — package for the op-layer modules.
- `backend/workbench/lineage/upload_store.py` — content-addressable upload store.
- `backend/workbench/lineage/run_inputs.py` — `run_inputs.json` read/write + redaction.
- `backend/workbench/lineage/hashing.py` — `canonicalize`, `override_hash`, `dag_hash`, `PIPELINE_VERSION`.
- `backend/workbench/lineage/op_contract.py` — node→OperationContract resolver + structural validation.

**Modified (backend):**
- `backend/workbench/engine/capabilities.py` — `params`, `schema_id`, `editable_stages`, `schema_version` 3.
- `backend/workbench/api.py` — CAS upload on create; write `run_inputs.json`; `_submit_run` helper; `POST /runs/{id}/rerun`; serve-layer graph annotation.
- `backend/workbench/orchestrator/_manifest.py` — `rerun_of` in manifest payload.

**Modified (frontend, type-sync only):**
- `frontend/src/capabilities/types.ts` — add `params`, `schema_id` to `ModelTypeEntry`, `editable_stages` to `Capabilities`.

**Modified (contracts/tests):**
- `tests/contracts/test_schema_capabilities.py` + `tests/contracts/capabilities.sample.json` — schema_version 3 + params/schema_id/editable_stages.
- New backend test files (one per task, named below).

**Modified (docs):**
- `docs/v1.6.0-IMPL-NOTES.md` (Task 10).

---

## Task 0: Environment + baseline gate

**Files:** none (setup only).

- [ ] **Step 1: Build the venv and install backend extras**

Run:
```bash
cd .worktrees/workbench-v1.6.0
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```
Expected: install completes, no errors.

- [ ] **Step 2: Install frontend deps**

Run:
```bash
cd frontend && npm install && cd ..
```
Expected: `node_modules/` present.

- [ ] **Step 3: Capture the baseline gate (must be green BEFORE any change)**

Run:
```bash
./scripts/gate.sh
```
Expected: `>>> GATE PASSED`. Record the backend test count from the output (call it
`BASELINE_BE`). If the gate is not green at baseline, STOP — the worktree is broken.

- [ ] **Step 4: Record the golden subset command (used after every risky task)**

Run:
```bash
.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q
```
Expected: all pass, 0 drift. This is the **golden 0-drift gate** referenced later.

- [ ] **Step 5: No commit** (setup only).

---

## Task 1: Content-addressable upload store

**Files:**
- Create: `backend/workbench/lineage/__init__.py`
- Create: `backend/workbench/lineage/upload_store.py`
- Test: `tests/test_lineage_upload_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_upload_store.py
from pathlib import Path

import pytest

from workbench.lineage.upload_store import (
    UploadBlobMissing,
    UploadHashMismatch,
    resolve_upload,
    store_upload_bytes,
    verify_upload,
)


def test_store_returns_sha256_and_writes_blob(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"col\n1\n2\n", filename="d.csv")
    blob = tmp_path / "data" / "uploads" / sha
    assert blob.is_file()
    assert blob.read_bytes() == b"col\n1\n2\n"
    assert len(sha) == 64  # hex sha256


def test_store_is_content_addressed_idempotent(tmp_path: Path):
    a = store_upload_bytes(tmp_path, b"same", filename="a.csv")
    b = store_upload_bytes(tmp_path, b"same", filename="b.csv")
    assert a == b  # same content -> same key, stored once


def test_resolve_returns_path(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"x", filename="x.csv")
    assert resolve_upload(tmp_path, sha).read_bytes() == b"x"


def test_resolve_missing_blob_raises(tmp_path: Path):
    with pytest.raises(UploadBlobMissing):
        resolve_upload(tmp_path, "0" * 64)


def test_verify_detects_corruption(tmp_path: Path):
    sha = store_upload_bytes(tmp_path, b"original", filename="x.csv")
    (tmp_path / "data" / "uploads" / sha).write_bytes(b"tampered")
    with pytest.raises(UploadHashMismatch):
        verify_upload(tmp_path, sha)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lineage_upload_store.py -q`
Expected: FAIL — `ModuleNotFoundError: workbench.lineage.upload_store`.

- [ ] **Step 3: Create the package + module**

```python
# backend/workbench/lineage/__init__.py
"""v1.6.0 lineage operation-layer: editable-op contract, run-input persistence,
content-addressable uploads. Estimator-agnostic; reads the capabilities manifest."""
```

```python
# backend/workbench/lineage/upload_store.py
"""Content-addressable upload store. Uploads are keyed by sha256 so their lifecycle
is decoupled from any single run: a rerun references a parent's upload by hash, never
by path. Blobs live at <project_root>/data/uploads/<sha256>."""
from __future__ import annotations

import hashlib
from pathlib import Path


class UploadBlobMissing(FileNotFoundError):
    """The content-addressed blob for a given sha256 does not exist."""


class UploadHashMismatch(ValueError):
    """A stored blob's content no longer hashes to its key (corruption/tamper)."""


def _uploads_dir(project_root: Path) -> Path:
    return project_root / "data" / "uploads"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_upload_bytes(project_root: Path, data: bytes, *, filename: str) -> str:
    """Write `data` content-addressably; return its sha256. Idempotent: identical
    content stores once. `filename` is accepted for API symmetry but not used as the
    key (kept by callers in run_inputs for display only)."""
    sha = sha256_bytes(data)
    target = _uploads_dir(project_root) / sha
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    return sha


def resolve_upload(project_root: Path, sha256: str) -> Path:
    path = _uploads_dir(project_root) / sha256
    if not path.is_file():
        raise UploadBlobMissing(f"No upload blob for sha256={sha256}")
    return path


def verify_upload(project_root: Path, sha256: str) -> Path:
    """Resolve and re-verify the blob hashes to its key; raise on mismatch."""
    path = resolve_upload(project_root, sha256)
    actual = sha256_bytes(path.read_bytes())
    if actual != sha256:
        raise UploadHashMismatch(
            f"Upload blob {sha256} content hashes to {actual}"
        )
    return path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lineage_upload_store.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/__init__.py backend/workbench/lineage/upload_store.py tests/test_lineage_upload_store.py
git commit -m "feat(v1.6.0): content-addressable upload store"
```

---

## Task 2: Hashing helpers (canonicalize, override_hash, dag_hash, PIPELINE_VERSION)

**Files:**
- Create: `backend/workbench/lineage/hashing.py`
- Test: `tests/test_lineage_hashing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_hashing.py
from workbench.lineage.hashing import (
    PIPELINE_VERSION,
    canonicalize,
    dag_hash,
    override_hash,
)


def test_canonicalize_is_order_independent():
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})


def test_override_hash_deterministic_under_reordering():
    assert override_hash({"x": "1", "y": "2"}) == override_hash({"y": "2", "x": "1"})


def test_override_hash_changes_with_value():
    assert override_hash({"x": "1"}) != override_hash({"x": "2"})


def test_dag_hash_combines_inputs():
    h1 = dag_hash("sha_a", {"y": "z"})
    h2 = dag_hash("sha_b", {"y": "z"})
    assert h1 != h2 and len(h1) == 64


def test_pipeline_version_is_a_nonempty_str():
    assert isinstance(PIPELINE_VERSION, str) and PIPELINE_VERSION
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lineage_hashing.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# backend/workbench/lineage/hashing.py
"""Deterministic hashes for the lineage op-layer.

PIPELINE_VERSION is a declared constant bumped whenever the PIPELINE stage
structure changes; it participates in dag_hash so a pipeline change invalidates
any future hash-skip cache. Slice 1 reserves and populates these hashes but does
NOT implement caching."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when orchestrator.PIPELINE stage structure changes.
PIPELINE_VERSION = "v1.6.0-pipeline-1"


def canonicalize(obj: Any) -> str:
    """Stable JSON string: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def override_hash(op_overrides: dict) -> str:
    return _sha(canonicalize(op_overrides))


def dag_hash(upload_sha256: str, form_bag: dict) -> str:
    return _sha(canonicalize([upload_sha256, form_bag, PIPELINE_VERSION]))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lineage_hashing.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/hashing.py tests/test_lineage_hashing.py
git commit -m "feat(v1.6.0): canonicalize + override_hash + dag_hash + PIPELINE_VERSION"
```

---

## Task 3: run_inputs.json read/write + secret redaction

**Files:**
- Create: `backend/workbench/lineage/run_inputs.py`
- Test: `tests/test_lineage_run_inputs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_run_inputs.py
from pathlib import Path

from workbench.lineage.run_inputs import (
    RUN_INPUT_SCHEMA_VERSION,
    read_run_inputs,
    redact_form,
    write_run_inputs,
)


def test_roundtrip(tmp_path: Path):
    write_run_inputs(
        tmp_path,
        form={"model_type": "ols", "y": "wage", "x": "edu"},
        upload={"sha256": "a" * 64, "filename": "d.csv"},
        rerun_of=None, from_node=None, rerun_reason="initial",
        override_hash=None, dag_hash="d" * 64,
    )
    got = read_run_inputs(tmp_path)
    assert got["run_input_schema_version"] == RUN_INPUT_SCHEMA_VERSION
    assert got["form"]["model_type"] == "ols"
    assert got["upload"]["sha256"] == "a" * 64
    assert got["rerun_reason"] == "initial"
    assert got["dag_hash"] == "d" * 64


def test_redaction_masks_secret_like_keys():
    out = redact_form({"y": "wage", "api_key": "sk-123", "db_password": "p"})
    assert out["y"] == "wage"
    assert out["api_key"] == "***"
    assert out["db_password"] == "***"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lineage_run_inputs.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# backend/workbench/lineage/run_inputs.py
"""run_inputs.json — the minimal immutable contract for reproducing/rerunning a run.

Written OUTSIDE the engine (api layer), so golden (which runs the engine) never drifts.
The form bag is a generic dict (form-param name -> value): a new estimator's params land
here automatically. Secrets are redacted on the way in."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import read_json, write_json

RUN_INPUT_SCHEMA_VERSION = 1
RUN_INPUTS_FILENAME = "run_inputs.json"

# Substrings that mark a form key as secret-bearing. Today the form bag has none;
# this guards future inputs (external connections, API keys).
_SECRET_MARKERS = ("password", "secret", "token", "api_key", "apikey", "credential")


def redact_form(form: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in form.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            out[key] = "***"
        else:
            out[key] = value
    return out


def write_run_inputs(
    run_root: Path,
    *,
    form: dict[str, Any],
    upload: dict[str, Any],
    rerun_of: str | None,
    from_node: str | None,
    rerun_reason: str,
    override_hash: str | None,
    dag_hash: str,
) -> None:
    payload = {
        "run_input_schema_version": RUN_INPUT_SCHEMA_VERSION,
        "form": redact_form(form),
        "upload": {"sha256": upload["sha256"], "filename": upload.get("filename")},
        "rerun_of": rerun_of,
        "from_node": from_node,
        "rerun_reason": rerun_reason,
        "override_hash": override_hash,
        "dag_hash": dag_hash,
    }
    write_json(run_root / RUN_INPUTS_FILENAME, payload)


def read_run_inputs(run_root: Path) -> dict[str, Any]:
    return read_json(run_root / RUN_INPUTS_FILENAME)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lineage_run_inputs.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/run_inputs.py tests/test_lineage_run_inputs.py
git commit -m "feat(v1.6.0): run_inputs.json persistence + secret redaction"
```

---

## Task 4: Capabilities manifest — params + schema_id + editable_stages (4-way sync)

**Files:**
- Modify: `backend/workbench/engine/capabilities.py`
- Modify: `tests/contracts/capabilities.sample.json`
- Modify: `tests/contracts/test_schema_capabilities.py`
- Modify: `frontend/src/capabilities/types.ts`
- Test: `tests/test_capabilities_op_schema.py`

- [ ] **Step 1: Write the failing backend test**

```python
# tests/test_capabilities_op_schema.py
from workbench.engine.capabilities import build_capabilities


def test_schema_version_bumped_to_3():
    assert build_capabilities()["schema_version"] == 3


def test_editable_stages_is_model_only():
    assert build_capabilities()["editable_stages"] == ["model"]


def test_each_model_type_has_schema_id_and_params():
    caps = build_capabilities()
    for entry in caps["model_types"]:
        if entry["key"] == "auto":
            continue
        assert entry["schema_id"] == f"{entry['key']}@v1"
        assert isinstance(entry["params"], list)


def test_iv_params_declare_roles_structurally():
    caps = build_capabilities()
    iv = next(e for e in caps["model_types"] if e["key"] == "iv_2sls")
    keys = {p["key"] for p in iv["params"]}
    assert {"model_type", "iv_endog", "iv_instruments", "covariance"} <= keys
    endog = next(p for p in iv["params"] if p["key"] == "iv_endog")
    assert endog["required"] is True and endog["role"] == "endog"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_capabilities_op_schema.py -q`
Expected: FAIL — `KeyError: 'editable_stages'` / no `schema_id`.

- [ ] **Step 3: Add a params helper + per-model params + top-level fields in `capabilities.py`**

Add near the top (after `COVARIANCE_UI`):

```python
# v1.6.0 — per-op editable schemas (mirror the FE EditableControl). Structural only:
# key (POST /runs form-param name), kind, options, required, role, value. NO business
# rules (those stay in the pipeline). Only fields the backend genuinely consumes.
_COMMON_MODEL_PARAMS = [
    {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
    {"key": "covariance", "kind": "select", "label": "Covariance", "required": False,
     "options": [o["key"] for o in COVARIANCE_UI], "value": "robust"},
]

_MODEL_PARAMS: dict[str, list[dict]] = {
    "ols": _COMMON_MODEL_PARAMS,
    "logit": _COMMON_MODEL_PARAMS,
    "probit": _COMMON_MODEL_PARAMS,
    "poisson": _COMMON_MODEL_PARAMS,
    "negative_binomial": _COMMON_MODEL_PARAMS,
    "panel_ols": _COMMON_MODEL_PARAMS + [
        {"key": "entity_col", "kind": "columns", "label": "Entity", "required": False, "role": "entity"},
        {"key": "time_col", "kind": "columns", "label": "Time", "required": False, "role": "time"},
    ],
    "iv_2sls": _COMMON_MODEL_PARAMS + [
        {"key": "iv_endog", "kind": "columns", "label": "Endogenous", "required": True, "role": "endog"},
        {"key": "iv_instruments", "kind": "columns", "label": "Instruments", "required": True, "role": "instruments"},
    ],
    "did": _COMMON_MODEL_PARAMS,
    "cs_did": _COMMON_MODEL_PARAMS,
    "sa_did": _COMMON_MODEL_PARAMS,
    "dcdh": _COMMON_MODEL_PARAMS,
    "glm:binomial": _COMMON_MODEL_PARAMS,
    "glm:poisson": _COMMON_MODEL_PARAMS,
    "glm:negative_binomial": _COMMON_MODEL_PARAMS,
}
```

In `build_capabilities()`, when building each non-auto model entry, attach `schema_id`
and `params`:

```python
    for key in MODEL_UI_ORDER:
        if key not in exposed_keys:
            continue
        entry = {"key": key, **MODEL_UI_META[key]}
        entry["schema_id"] = f"{key}@v1"
        entry["params"] = _MODEL_PARAMS.get(key, list(_COMMON_MODEL_PARAMS))
        model_types.append(entry)
```

And bump the returned dict:

```python
    return {
        "schema_version": 3,
        "editable_stages": ["model"],
        "model_types": model_types,
        "imputation_methods": imputation_methods,
        "prediction_models": list(PREDICTION_UI),
        "sampling_methods": list(SAMPLING_UI),
        "covariance_options": list(COVARIANCE_UI),
    }
```

- [ ] **Step 4: Run the backend test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_capabilities_op_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Update the contract schema + sample (4-way sync)**

In `tests/contracts/test_schema_capabilities.py`: add `editable_stages` to top-level
`properties` and extend `model_types` item `properties` (it uses
`additionalProperties: False`, so the new keys MUST be declared):

```python
        # top-level properties: add
        "editable_stages": {"type": "array", "items": {"type": "string"}},
```
```python
        # inside model_types items "properties": add
                    "schema_id": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["key", "kind"],
                            "properties": {
                                "key": {"type": "string"},
                                "kind": {"type": "string"},
                                "label": {"type": "string"},
                                "role": {"type": "string"},
                                "required": {"type": "boolean"},
                                "value": {},
                                "options": {"type": "array"},
                            },
                            "additionalProperties": False,
                        },
                    },
```

In `tests/contracts/capabilities.sample.json`: set `"schema_version": 3`, add
`"editable_stages": ["model"]`, and add `schema_id` + `params` to each non-auto
`model_types` entry to match `build_capabilities()` output.

- [ ] **Step 6: Update the FE type (4-way sync)**

In `frontend/src/capabilities/types.ts`:

```typescript
export interface EditableControlSpec {
  key: string;
  kind: "radio" | "select" | "multiselect" | "slider" | "text" | "textarea" | "toggle" | "columns";
  label?: string;
  role?: string;
  required?: boolean;
  value?: unknown;
  options?: Array<string | { value: unknown; label: string }>;
}

export interface ModelTypeEntry {
  key: string;
  label: string;
  group: ModelGroup;
  description?: string;
  requires?: string[];
  schema_id?: string;
  params?: EditableControlSpec[];
}

export interface Capabilities {
  schema_version: number;
  editable_stages?: string[];
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
  prediction_models?: PredictionModelEntry[];
  sampling_methods?: SamplingMethodEntry[];
  covariance_options?: CovarianceOption[];
}
```

- [ ] **Step 7: Run the contract test + existing capabilities tests + FE typecheck**

Run:
```bash
.venv/bin/python -m pytest tests/contracts/test_schema_capabilities.py tests/test_api_capabilities.py tests/test_engine_capabilities.py tests/test_capabilities_v1542.py -q
( cd frontend && npx tsc --noEmit )
```
Expected: all PASS; tsc 0 errors. (If `test_api_capabilities`/`test_capabilities_v1542`
assert `schema_version == 2`, update those assertions to `3` — that is the intended bump.)

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/engine/capabilities.py tests/test_capabilities_op_schema.py tests/contracts/test_schema_capabilities.py tests/contracts/capabilities.sample.json frontend/src/capabilities/types.ts
git add -u tests/
git commit -m "feat(v1.6.0): capabilities op-schema (params/schema_id/editable_stages, schema_version 3)"
```

---

## Task 5: Node → OperationContract resolver + structural validation

**Files:**
- Create: `backend/workbench/lineage/op_contract.py`
- Test: `tests/test_lineage_op_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_op_contract.py
import pytest

from workbench.lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    validate_overrides,
)


def test_resolve_model_node_by_effective_model_type():
    manifest = {"model_routing": {"effective_model_type": "iv_2sls"}}
    contract = resolve_operation_contract(stage="model", manifest=manifest)
    assert contract is not None
    assert contract.op_type == "iv_2sls"
    assert contract.schema_id == "iv_2sls@v1"
    assert {p["key"] for p in contract.editable_schema} >= {"iv_endog", "covariance"}


def test_non_editable_stage_returns_none():
    assert resolve_operation_contract(stage="clean", manifest={}) is None


def test_unresolvable_model_type_returns_none():
    assert resolve_operation_contract(
        stage="model", manifest={"model_routing": {"effective_model_type": "???"}}
    ) is None


def test_validate_rejects_unknown_key():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    with pytest.raises(OpOverrideError):
        validate_overrides(c, {"not_a_field": "x"})


def test_validate_rejects_bad_enum():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    with pytest.raises(OpOverrideError):
        validate_overrides(c, {"covariance": "not_an_option"})


def test_validate_accepts_good_override():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    validate_overrides(c, {"covariance": "robust"})  # no raise


def test_model_type_switch_uses_new_schema():
    # Parent is ols; override switches to iv_2sls. The contract must be re-resolved
    # against iv_2sls so its required endog/instruments fields are recognized.
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    switched = resolve_overrides_target(c, {"model_type": "iv_2sls"})
    assert switched.op_type == "iv_2sls"
    # iv_endog is a known key only under the new schema
    validate_overrides(switched, {"model_type": "iv_2sls", "iv_endog": "[\"educ\"]",
                                  "iv_instruments": "[\"nearc\"]"})


from workbench.lineage.op_contract import resolve_overrides_target  # noqa: E402
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lineage_op_contract.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# backend/workbench/lineage/op_contract.py
"""Node -> OperationContract resolution + layer-1 structural validation.

Manifest-driven, ZERO per-estimator branches. Addressing is by stage/op_type only,
never by label. Semantic validation (column existence, estimability, role conflicts)
is NOT done here — it stays in the pipeline's per-estimator validators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..engine.capabilities import build_capabilities

EDITABLE_STAGE_MODEL = "model"


class OpOverrideError(ValueError):
    """A structural validation failure on op_overrides (unknown key / bad enum / type)."""


@dataclass(frozen=True)
class OperationContract:
    op_type: str
    schema_id: str
    editable_schema: list[dict[str, Any]]


def _model_entry(op_type: str) -> dict | None:
    caps = build_capabilities()
    if op_type not in caps.get("editable_stages", []) and EDITABLE_STAGE_MODEL not in caps.get("editable_stages", []):
        return None
    for entry in caps["model_types"]:
        if entry["key"] == op_type:
            return entry
    return None


def _contract_for_model_type(op_type: str) -> OperationContract | None:
    entry = _model_entry(op_type)
    if entry is None or "params" not in entry:
        return None
    return OperationContract(
        op_type=op_type,
        schema_id=entry["schema_id"],
        editable_schema=list(entry["params"]),
    )


def resolve_operation_contract(*, stage: str, manifest: dict) -> OperationContract | None:
    """Resolve a graph node's OperationContract from its stage + the run manifest.
    Returns None for non-editable / unresolvable nodes (defensive)."""
    caps = build_capabilities()
    if stage not in caps.get("editable_stages", []):
        return None
    if stage == EDITABLE_STAGE_MODEL:
        op_type = (manifest.get("model_routing") or {}).get("effective_model_type")
        if not op_type:
            return None
        return _contract_for_model_type(op_type)
    return None


def resolve_overrides_target(
    contract: OperationContract, op_overrides: dict
) -> OperationContract:
    """Guardrail #4 (schema-switching order): if op_overrides switches model_type,
    re-resolve the contract against the NEW model's schema. Otherwise return as-is."""
    new_model = op_overrides.get("model_type")
    if new_model and new_model != contract.op_type:
        switched = _contract_for_model_type(new_model)
        if switched is None:
            raise OpOverrideError(f"Unknown model_type override: {new_model!r}")
        return switched
    return contract


def validate_overrides(contract: OperationContract, op_overrides: dict) -> None:
    """Layer-1 structural validation against the (already target-resolved) contract:
    keys must be known; enum (options) values must be allowed. Type/required checks
    are minimal here; deep semantics stay in the pipeline."""
    by_key = {p["key"]: p for p in contract.editable_schema}
    for key, value in op_overrides.items():
        if key not in by_key:
            raise OpOverrideError(
                f"Unknown field {key!r} for op {contract.op_type!r} ({contract.schema_id})"
            )
        spec = by_key[key]
        options = spec.get("options")
        if options and value not in [
            o if not isinstance(o, dict) else o.get("value") for o in options
        ]:
            raise OpOverrideError(
                f"Value {value!r} not allowed for {key!r}; options={options}"
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lineage_op_contract.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/op_contract.py tests/test_lineage_op_contract.py
git commit -m "feat(v1.6.0): node->OperationContract resolver + structural validation (schema-switch order)"
```

---

## Task 6: Wire `POST /runs` to CAS upload + run_inputs.json (+ `_submit_run` helper)

**Files:**
- Modify: `backend/workbench/api.py` (the `run_endpoint` create path + new `_submit_run`)
- Modify: `backend/workbench/orchestrator/_manifest.py` (add `rerun_of` to payload)
- Test: `tests/test_run_inputs_persisted.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_inputs_persisted.py
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    return b"y,x\n1,2\n3,4\n5,6\n"


def test_create_persists_run_inputs_and_cas_upload(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    resp = client.post(
        "/runs",
        data={"project_root": str(project.root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    run_root = project.root / "runs" / run_id

    inputs = json.loads((run_root / "run_inputs.json").read_text())
    assert inputs["run_input_schema_version"] == 1
    assert inputs["form"]["model_type"] == "ols"
    assert inputs["rerun_of"] is None
    assert inputs["rerun_reason"] == "initial"
    sha = inputs["upload"]["sha256"]
    assert "path" not in inputs["upload"]  # addressed by sha256 only
    assert (project.root / "data" / "uploads" / sha).is_file()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_run_inputs_persisted.py -q`
Expected: FAIL — `run_inputs.json` not written.

- [ ] **Step 3: Add `rerun_of` to the manifest payload**

In `backend/workbench/orchestrator/_manifest.py`, extend `_write_manifest` signature with
`rerun_of: str | None = None` and add to `payload` when not None:

```python
    if rerun_of is not None:
        payload["rerun_of"] = rerun_of
```

- [ ] **Step 4: Add `_submit_run` + wire the create path in `api.py`**

Add imports at the top of `api.py`:

```python
from .lineage.hashing import dag_hash, override_hash
from .lineage.run_inputs import write_run_inputs
from .lineage.upload_store import resolve_upload, store_upload_bytes, verify_upload
```

Add a shared dispatch helper (place above `run_endpoint`):

```python
def _submit_run(
    root: Path,
    *,
    form: dict[str, str],
    upload_bytes: bytes,
    upload_filename: str,
    started_at: str,
    rerun_of: str | None = None,
    from_node: str | None = None,
    rerun_reason: str = "initial",
    op_overrides: dict | None = None,
) -> dict[str, str]:
    """Single dispatch path shared by POST /runs and POST /runs/{id}/rerun.
    Stores the upload content-addressably, writes run_inputs.json, dispatches the
    full pipeline via _bg_run. Caller must hold the run slot."""
    sha = store_upload_bytes(root, upload_bytes, filename=upload_filename)
    run = create_run(root, mode=form.get("mode", "auto"))

    x_columns = [p.strip() for p in form.get("x", "").split(",") if p.strip()]
    imputation_request = parse_imputation_request(form.get("imputation", ""))
    iv_endog_list = _parse_json_str_array(form.get("iv_endog", ""), "iv_endog")
    iv_instruments_list = _parse_json_str_array(form.get("iv_instruments", ""), "iv_instruments")

    write_run_inputs(
        run.root,
        form=form,
        upload={"sha256": sha, "filename": upload_filename},
        rerun_of=rerun_of, from_node=from_node, rerun_reason=rerun_reason,
        override_hash=override_hash(op_overrides) if op_overrides else None,
        dag_hash=dag_hash(sha, form),
    )

    # Materialise the upload into the run for the engine to read (engine reads a path).
    uploads_dir = run.root / "_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved_path = uploads_dir / Path(upload_filename or "upload.csv").name
    saved_path.write_bytes(resolve_upload(root, sha).read_bytes())

    _write_manifest(
        run.root, run.run_id, form.get("mode", "auto"), "running",
        _lineage([saved_path]), started_at=started_at,
        y=form.get("y", ""), x=x_columns,
        requested_model_type=form.get("model_type", "auto"),
        rerun_of=rerun_of,
    )

    events = get_event_manager()
    events.register_run(run.run_id)
    events.mark_active(run.run_id)
    events.executor.submit(
        _bg_run, run.root, run.run_id, saved_path,
        form.get("mode", "auto"), form.get("y", ""), x_columns, started_at,
        form.get("model_type", "auto"),
        (form.get("sheet_name") or None), form.get("transpose") == "true",
        imputation_request,
        form.get("entity_col", ""), form.get("time_col", ""), form.get("covariance", ""),
        form.get("prediction_model_type", ""), _safe_int(form.get("prediction_cv_folds", "0")),
        form.get("prediction_sampling_method", ""),
        iv_endog_list, iv_instruments_list,
        form.get("did_mode", ""), form.get("did_cohort_col", ""), form.get("did_treat_col", ""),
        form.get("did_post_col", ""), form.get("did_status_col", ""), form.get("did_treatment_path", ""),
        form.get("cs_control_group", ""), form.get("cs_est_method", ""), form.get("cs_base_period", ""),
        form.get("cs_cluster_var", ""), _safe_int(str(form.get("cs_anticipation", "0"))),
        str(form.get("honest_did", "false")).lower() == "true",
    )
    return {"run_id": run.run_id, "status": "running"}
```

Then refactor `run_endpoint` to read the upload bytes and delegate. Keep its existing
`Form(...)` parameters; build the `form` dict from them, acquire the slot as today, and
replace the body with:

```python
    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    run_id_for_cleanup: str | None = None
    try:
        data = await _read_upload_bytes(file, max_upload_bytes)
        form = {
            "mode": mode, "model_type": model_type, "y": y, "x": x,
            "sheet_name": sheet_name, "transpose": transpose, "imputation": imputation,
            "entity_col": entity_col, "time_col": time_col, "covariance": covariance,
            "prediction_model_type": prediction_model_type,
            "prediction_cv_folds": prediction_cv_folds,
            "prediction_sampling_method": prediction_sampling_method,
            "iv_endog": iv_endog, "iv_instruments": iv_instruments,
            "did_mode": did_mode, "did_cohort_col": did_cohort_col,
            "did_treat_col": did_treat_col, "did_post_col": did_post_col,
            "did_status_col": did_status_col, "did_treatment_path": did_treatment_path,
            "cs_control_group": cs_control_group, "cs_est_method": cs_est_method,
            "cs_base_period": cs_base_period, "cs_cluster_var": cs_cluster_var,
            "cs_anticipation": str(cs_anticipation), "honest_did": str(honest_did).lower(),
        }
        started_at = datetime.now(timezone.utc).isoformat()
        result = _submit_run(
            root, form=form, upload_bytes=data,
            upload_filename=Path(file.filename or "upload.csv").name,
            started_at=started_at, rerun_reason="initial",
        )
        run_id_for_cleanup = result["run_id"]
        return result
    except Exception:
        events.release_slot(run_id_for_cleanup)
        raise
    finally:
        await file.close()
```

Add the upload-reader helper (validates size, returns bytes):

```python
async def _read_upload_bytes(file: UploadFile, max_bytes: int) -> bytes:
    buf = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds project size limit.")
    return bytes(buf)
```

> NOTE: keep `imputation` parse error handling — wrap `parse_imputation_request` in
> `_submit_run` so a bad value raises `HTTPException(422)` (mirror the existing behavior;
> if `parse_imputation_request` raises `ValueError`, convert to 422 in the create path).

- [ ] **Step 5: Run the new test + the existing run/api tests**

Run:
```bash
.venv/bin/python -m pytest tests/test_run_inputs_persisted.py tests/test_api.py tests/test_api_run_params.py tests/test_api_runs_imputation.py tests/test_project_run_artifacts.py -q
```
Expected: all PASS. Fix any drift in existing tests caused by the upload now living in CAS
(the engine still reads `run.root/_uploads/...`, so lineage paths are unchanged).

- [ ] **Step 6: Golden 0-drift gate**

Run:
```bash
.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q
```
Expected: PASS, 0 drift (engine untouched).

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/api.py backend/workbench/orchestrator/_manifest.py tests/test_run_inputs_persisted.py
git commit -m "feat(v1.6.0): CAS upload + run_inputs.json on create via shared _submit_run"
```

---

## Task 7: `POST /runs/{run_id}/rerun` endpoint

**Files:**
- Modify: `backend/workbench/api.py`
- Test: `tests/test_rerun_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rerun_endpoint.py
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    return b"y,x\n1,2\n3,4\n5,6\n7,8\n"


def _create_terminal_run(project_root: Path) -> str:
    resp = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    run_id = resp.json()["run_id"]
    # TestClient runs the executor synchronously enough that the run finishes; poll status.
    client.get(f"/runs/{run_id}", params={"project_root": str(project_root)})
    return run_id


def test_rerun_unknown_from_node_422(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": "does:not:exist", "op_overrides": {"covariance": "HC3"}},
    )
    assert resp.status_code == 422


def test_rerun_unknown_override_key_422(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    # find the model node id from the parent graph
    graph = client.get(f"/runs/{parent}/graph", params={"project_root": str(project.root)}).json()
    model_node = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": model_node["id"], "op_overrides": {"bogus": "x"}},
    )
    assert resp.status_code == 422


def test_rerun_creates_child_with_rerun_of(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    graph = client.get(f"/runs/{parent}/graph", params={"project_root": str(project.root)}).json()
    model_node = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": model_node["id"], "op_overrides": {"covariance": "unadjusted"}},
    )
    assert resp.status_code == 200
    child = resp.json()["run_id"]
    assert child != parent
    inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert inputs["rerun_of"] == parent
    assert inputs["from_node"] == model_node["id"]
    assert inputs["form"]["covariance"] == "unadjusted"
    assert inputs["override_hash"] is not None
    # child reuses the SAME upload blob (content-addressed), not a new one
    assert inputs["upload"]["sha256"] == json.loads(
        (project.root / "runs" / parent / "run_inputs.json").read_text())["upload"]["sha256"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rerun_endpoint.py -q`
Expected: FAIL — 404 (no rerun route).

- [ ] **Step 3: Implement the endpoint**

Add to `api.py` (imports for resolver + statuses):

```python
from .lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    resolve_overrides_target,
    validate_overrides,
)
from .lineage.run_inputs import read_run_inputs

_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "interrupted", "partial"}


class RerunRequest(BaseModel):
    from_node: str
    op_overrides: dict = {}
    rerun_reason: str = "manual_override"


@app.post("/runs/{run_id}/rerun")
def rerun_endpoint(run_id: str, project_root: str, body: RerunRequest) -> dict[str, str]:
    root = Path(project_root)
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)

    # Guardrail #8: parent must be terminal (else 409). Distinct from slot-busy 429.
    status = manifest.get("status")
    if status not in _TERMINAL_RUN_STATUSES:
        raise HTTPException(status_code=409, detail=f"Parent run not terminal (status={status}).")

    # Guardrail #6: from_node must exist in the parent graph.
    runs_root = _resolve_project_runs_dir(project_root)
    graph = GraphStore(runs_root=runs_root).read(run_id)
    node = graph.nodes.get(body.from_node)
    if node is None:
        raise HTTPException(status_code=422, detail=f"from_node not in run graph: {body.from_node}")

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise HTTPException(status_code=422, detail=f"Node {body.from_node} is not editable.")

    # Guardrails #3 + #4: structural validation against the (switch-resolved) schema.
    try:
        target = resolve_overrides_target(contract, body.op_overrides)
        validate_overrides(target, body.op_overrides)
    except OpOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    inputs = read_run_inputs(run_root)
    parent_sha = inputs["upload"]["sha256"]
    # Guardrails #2 + #5: reuse parent upload by sha256 only; re-verify content hash.
    try:
        upload_bytes = verify_upload(root, parent_sha).read_bytes()
    except Exception as exc:  # UploadBlobMissing / UploadHashMismatch
        raise HTTPException(status_code=422, detail=f"Parent upload unusable: {exc}") from exc

    merged_form = {**inputs["form"], **{k: str(v) for k, v in body.op_overrides.items()}}

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    child_id: str | None = None
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        result = _submit_run(
            root, form=merged_form, upload_bytes=upload_bytes,
            upload_filename=inputs["upload"].get("filename") or "upload.csv",
            started_at=started_at, rerun_of=run_id, from_node=body.from_node,
            rerun_reason=body.rerun_reason, op_overrides=body.op_overrides,
        )
        child_id = result["run_id"]
        return result
    except Exception:
        events.release_slot(child_id)
        raise
```

> NOTE: `op_overrides` values are coerced to `str` when merged into the form bag because
> `POST /runs` form params are strings (e.g. `iv_endog` is a JSON-array string). Keep the
> raw `op_overrides` (un-stringified) for `override_hash` so the fingerprint is stable.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_rerun_endpoint.py -q`
Expected: PASS (3 passed). If a run does not reach a terminal status under TestClient,
add a short poll loop in `_create_terminal_run` (call `GET /runs/{id}` until status in the
terminal set, max ~50 tries) — the executor is a thread pool.

- [ ] **Step 5: Add the 409 + schema-switch tests**

Append to `tests/test_rerun_endpoint.py`:

```python
def test_rerun_on_running_parent_409(tmp_path: Path, monkeypatch):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    # Force the manifest to look non-terminal.
    mpath = project.root / "runs" / parent / "run_manifest.json"
    m = json.loads(mpath.read_text()); m["status"] = "running"; mpath.write_text(json.dumps(m))
    graph = client.get(f"/runs/{parent}/graph", params={"project_root": str(project.root)}).json()
    model_node = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    resp = client.post(
        f"/runs/{parent}/rerun", params={"project_root": str(project.root)},
        json={"from_node": model_node["id"], "op_overrides": {"covariance": "robust"}},
    )
    assert resp.status_code == 409
```

Run: `.venv/bin/python -m pytest tests/test_rerun_endpoint.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_rerun_endpoint.py
git commit -m "feat(v1.6.0): POST /runs/{id}/rerun — manifest-validated immutable child run"
```

---

## Task 8: Serve-layer `editable_schema` annotation on `GET /graph`

**Files:**
- Modify: `backend/workbench/api.py` (`get_run_graph`)
- Test: `tests/test_graph_editable_annotation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_editable_annotation.py
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _run(project_root: Path) -> str:
    resp = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(b"y,x\n1,2\n3,4\n5,6\n"), "text/csv")},
    )
    run_id = resp.json()["run_id"]
    client.get(f"/runs/{run_id}", params={"project_root": str(project_root)})
    return run_id


def test_model_node_is_annotated_editable(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)}).json()
    model = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    assert model["editable"] is True
    assert model["op_type"] == "ols"
    assert model["schema_id"] == "ols@v1"
    assert isinstance(model["editable_schema"], list)
    assert model["editable_schema_source"] == "capabilities"


def test_non_model_node_not_editable(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)}).json()
    non = next(n for n in graph["nodes"].values() if n.get("stage") != "model")
    assert non.get("editable", False) is False


def test_annotation_not_written_back_to_graph_json(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)})
    raw = json.loads((project.root / "runs" / run_id / "graph.json").read_text())
    for node in raw["nodes"].values():
        assert "editable_schema" not in node  # Guardrail #7: decorate-only
        assert "editable" not in node
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_graph_editable_annotation.py -q`
Expected: FAIL — nodes have no `editable` field.

- [ ] **Step 3: Decorate at response time in `get_run_graph`**

In `api.py`, after `body = graph_to_json(graph)` and before computing `stats`, add:

```python
    manifest = _read_manifest(_resolve_run_root(project_root, run_id))
    _annotate_editable_nodes(body, manifest)
```

Add the helper:

```python
def _annotate_editable_nodes(body: dict, manifest: dict) -> None:
    """Guardrail #7: response-time decoration only — never persisted to graph.json.
    For each node whose stage is editable and resolves to an OperationContract, attach
    editable/op_type/schema_id/editable_schema/editable_schema_source."""
    form = {}
    # current values are best-effort from run_inputs if present (filled later by FE).
    for node in body.get("nodes", {}).values():
        stage = node.get("stage")
        contract = resolve_operation_contract(stage=stage, manifest=manifest)
        if contract is None:
            continue
        node["editable"] = True
        node["op_type"] = contract.op_type
        node["schema_id"] = contract.schema_id
        node["editable_schema"] = contract.editable_schema
        node["editable_schema_source"] = "capabilities"
```

> NOTE: `_read_manifest` and `resolve_operation_contract` are already imported (Tasks 6–7).
> If `_read_manifest` raises for a legacy run with no manifest, guard with a try/except
> returning the undecorated body (defensive — legacy runs stay non-editable).

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_graph_editable_annotation.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing graph API tests (no regression)**

Run: `.venv/bin/python -m pytest tests/test_graph_api.py tests/test_graph_orchestrator_integration.py -q`
Expected: PASS. If a test asserts an exact node dict shape, update it to allow the additive
`editable*` keys (they appear only on editable nodes).

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_graph_editable_annotation.py
git commit -m "feat(v1.6.0): serve-layer editable_schema annotation on GET /graph (decorate-only)"
```

---

## Task 9: Lineage DAG invariant tests

**Files:**
- Test: `tests/test_lineage_dag_invariants.py`

- [ ] **Step 1: Write the test (asserts §4 invariants end-to-end)**

```python
# tests/test_lineage_dag_invariants.py
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    return b"y,x\n1,2\n3,4\n5,6\n7,8\n"


def _terminal(project_root: Path) -> str:
    rid = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto", "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    ).json()["run_id"]
    client.get(f"/runs/{rid}", params={"project_root": str(project_root)})
    return rid


def test_rerun_does_not_mutate_parent_and_child_has_one_parent(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _terminal(project.root)
    parent_graph_before = (project.root / "runs" / parent / "graph.json").read_text()

    graph = client.get(f"/runs/{parent}/graph", params={"project_root": str(project.root)}).json()
    model_node = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    child = client.post(
        f"/runs/{parent}/rerun", params={"project_root": str(project.root)},
        json={"from_node": model_node["id"], "op_overrides": {"covariance": "unadjusted"}},
    ).json()["run_id"]
    client.get(f"/runs/{child}", params={"project_root": str(project.root)})

    # Invariant 1: parent graph.json unchanged by the rerun.
    assert (project.root / "runs" / parent / "graph.json").read_text() == parent_graph_before

    child_inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    # Invariants 2-3: exactly one parent, recorded as rerun_of.
    assert child_inputs["rerun_of"] == parent

    # Invariant 5: child did NOT copy the parent's derived artifacts; it recomputed.
    # graph.json content differs because run_id differs inside it.
    assert (project.root / "runs" / child / "graph.json").read_text() != parent_graph_before
```

- [ ] **Step 2: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lineage_dag_invariants.py -q`
Expected: PASS (1 passed). (If the child reuses the parent run_id anywhere, that's an
invariant bug — fix `_submit_run`.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_lineage_dag_invariants.py
git commit -m "test(v1.6.0): lineage DAG invariants (append-only, one parent, no artifact inheritance)"
```

---

## Task 10: Full gate, spec reconciliation, docs

**Files:**
- Modify: `docs/superpowers/specs/2026-06-22-workbench-v1.6.0-lineage-op-contract-design.md` (reconcile the two grounding adjustments)
- Create: `docs/v1.6.0-IMPL-NOTES.md`

- [ ] **Step 1: Reconcile the spec with the two grounded adjustments**

Edit the spec: change `editable_stages` examples to `["model"]` and add a note that
imputation defers until it has a graph node; change "rename `schema_version` →
`capabilities_schema_version`" to "keep `schema_version` (bump 2→3); the run-input and
per-op `schema_id` axes provide the independence." Keep §3.0's three-axis table but note
the capabilities axis retains its existing field name.

- [ ] **Step 2: Write impl notes**

Create `docs/v1.6.0-IMPL-NOTES.md` capturing: the CAS upload layout
(`<project>/data/uploads/<sha256>`), why `editable_stages=["model"]` (no imputation node),
the `_submit_run` shared-dispatch refactor, the 409-vs-429 distinction, and the deferred
roadmap (node-edit UI + control_factory; per-stage op params; hash-skip via dag_hash;
AI proxy; sandbox; report composer).

- [ ] **Step 3: Run the full gate**

Run:
```bash
./scripts/gate.sh
```
Expected: `>>> GATE PASSED`. Backend count = `BASELINE_BE` + the new tests; golden 0-drift;
vitest green; tsc 0.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-22-workbench-v1.6.0-lineage-op-contract-design.md docs/v1.6.0-IMPL-NOTES.md
git commit -m "docs(v1.6.0): reconcile spec grounding adjustments + impl notes"
```

- [ ] **Step 5: Whole-feature adversarial review (two roles)**

Per the standing review workflow, run a Reviewer + Test&QA pass over the whole branch
(probe: from_node spoofing, non-terminal parent, corrupted upload blob, model_type switch
to a model with unmet required roles → must surface as pipeline `MODEL_FIT_FAILED` not a
crash, secret redaction, graph.json non-mutation). Fix any blockers, re-run the gate.
**Do NOT push.** Merge/tag/push happens only after explicit user authorization.

---

## Self-review notes (author)

- **Spec coverage:** A (Task 4), B (Tasks 1/3/6), C (Task 7), serve-layer (Task 8),
  guardrails #1 (Task 3), #2/#5 (Tasks 1/7), #3/#4 (Tasks 5/7), #6/#8 (Task 7), #7 (Task 8),
  schema_id policy (Task 4 test), dag_hash/override_hash (Task 2), DAG invariants (Task 9).
- **Type consistency:** `resolve_operation_contract`/`resolve_overrides_target`/
  `validate_overrides`/`OperationContract`/`OpOverrideError` used identically across Tasks
  5/7/8; `store_upload_bytes`/`resolve_upload`/`verify_upload` across Tasks 1/6/7;
  `write_run_inputs`/`read_run_inputs` across Tasks 3/6/7; `_submit_run` signature stable
  across Tasks 6/7.
- **Deferred (NOT in this slice):** node-edit UI, per-stage op params, hash-skip caching,
  AI proxy, code sandbox, report composer, concurrency lift, imputation node.
