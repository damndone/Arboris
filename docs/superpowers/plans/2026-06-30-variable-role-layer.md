# Variable Role Layer (v1.6.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every workbench estimator's variables explicit research-design roles (Outcome / Focal / Treatment / Covariates / Instruments / Unit / Time / Exposure / Cluster / Explanatory_unspecified) that are derived per estimator family, persisted, and rendered in lineage as inputs flowing into the model — without changing any estimation math.

**Architecture:** A new pure module `variable_roles.py` turns the *resolved* estimator inputs into a list of `RoleAssignment`s (role lives on the edge, not the node). `recording.py` records one identity node per column plus role-bearing `var → model` edges. `focal_x` is the only new captured field; all other role sources already persist. The frontend renders role groups generically from the edge ops. Coefficient goldens must stay 0-drift; only graph goldens regenerate.

**Tech Stack:** Python 3 (pytest), FastAPI, React + TypeScript (vitest), existing `GraphRecorder` / lineage graph, golden snapshot harness (`scripts/gate.sh`).

**Spec:** `docs/superpowers/specs/2026-06-30-workbench-v1.6.5-variable-role-layer-design.md` (frozen).

---

## Conventions for every task

- Worktree: `.worktrees/workbench-v1.6.5`, branch `codex/workbench-v1.6.5`. Do **not** push/merge/tag.
- Run backend tests with UTF-8: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest …` from the worktree root.
- Full gate (run at phase boundaries): `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`.
- Frontend tests: `cd frontend && npx vitest run <path>`.
- Commit after every green step. Never commit `frontend/node_modules`.

---

## File Structure

**New backend files**
- `backend/workbench/lineage/variable_roles.py` — `Role` enum, `RoleAssignment`, `ResolvedRoleInputs`, `ROLE_EDGE_OP`, `canonicalize_focal_x`, `derive_roles`, `validate_role_conflicts`, `dedup_edges`. Pure, no I/O.
- `tests/lineage/test_variable_roles.py` — table-driven unit tests for the above.

**Modified backend files**
- `backend/workbench/engine/stages/recording.py` — record identity nodes + role edges from `derive_roles`.
- `backend/workbench/lineage/run_inputs.py` — persist canonical `focal_x`.
- `backend/workbench/orchestrator/_manifest.py` — persist `focal_x` in manifest.
- `backend/workbench/api.py` — parse `focal_x` from form, thread into the run.

**New / modified frontend files**
- `frontend/src/lineage/roles.ts` — role vocabulary, edge-op → role map, canonical group order (shared constants).
- `frontend/src/workbench/RunSnapshotAdapter.ts` — expose role per variable edge; group variables by role.
- `frontend/src/workbench/views/GraphView.tsx` (or the variable-rendering component it uses) — render role groups + `roles: unspecified` / `legacy_unspecified` tag + dropped-in-role.
- `frontend/src/pipelineDrafts/ModelNodeInspector.tsx` — focal_x editing control.
- `frontend/src/runForm/RunForm.tsx` — focal multi-select on submit.
- Node detail drawer component — split Formula / Identification / Offset / Panel-inference blocks.
- Forest model node badge component — `run · hash · source|rerun`.

---

## Phase A — Pure role engine (`variable_roles.py`)

### Task A1: Role vocabulary, edge-op map, and data structures

**Files:**
- Create: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lineage/test_variable_roles.py
from workbench.lineage.variable_roles import Role, RoleAssignment, ROLE_EDGE_OP

def test_every_role_has_an_edge_op():
    for role in Role:
        assert role in ROLE_EDGE_OP

def test_edge_ops_match_spec():
    assert ROLE_EDGE_OP[Role.OUTCOME] == "enters_as_outcome"
    assert ROLE_EDGE_OP[Role.FOCAL] == "enters_as_focal"
    assert ROLE_EDGE_OP[Role.TREATMENT] == "enters_as_treatment"
    assert ROLE_EDGE_OP[Role.COVARIATES] == "enters_as_covariates"
    assert ROLE_EDGE_OP[Role.EXPLANATORY_UNSPECIFIED] == "enters_as_explanatory_unspecified"
    assert ROLE_EDGE_OP[Role.EXPOSURE] == "offsets_as_exposure"
    assert ROLE_EDGE_OP[Role.INSTRUMENTS] == "identifies_as_instruments"
    assert ROLE_EDGE_OP[Role.UNIT] == "configures_unit"
    assert ROLE_EDGE_OP[Role.TIME] == "configures_time"
    assert ROLE_EDGE_OP[Role.CLUSTER] == "configures_cluster"

def test_role_assignment_edge_kind_derived_from_op():
    ra = RoleAssignment(column="x1", role=Role.FOCAL, source="focal_x",
                        estimator_family="regression", estimator_key="ols")
    assert ra.edge_op == "enters_as_focal"
    assert ra.edge_kind == "enters_as_"
    cl = RoleAssignment(column="firm", role=Role.CLUSTER, source="_cs_cluster_var",
                        estimator_family="did", estimator_key="cs_did")
    assert cl.edge_kind == "configures_"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: workbench.lineage.variable_roles`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/workbench/lineage/variable_roles.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    OUTCOME = "outcome"
    FOCAL = "focal"
    TREATMENT = "treatment"
    COVARIATES = "covariates"
    EXPLANATORY_UNSPECIFIED = "explanatory_unspecified"
    INSTRUMENTS = "instruments"
    EXPOSURE = "exposure"
    UNIT = "unit"
    TIME = "time"
    CLUSTER = "cluster"


ROLE_EDGE_OP: dict[Role, str] = {
    Role.OUTCOME: "enters_as_outcome",
    Role.FOCAL: "enters_as_focal",
    Role.TREATMENT: "enters_as_treatment",
    Role.COVARIATES: "enters_as_covariates",
    Role.EXPLANATORY_UNSPECIFIED: "enters_as_explanatory_unspecified",
    Role.EXPOSURE: "offsets_as_exposure",
    Role.INSTRUMENTS: "identifies_as_instruments",
    Role.UNIT: "configures_unit",
    Role.TIME: "configures_time",
    Role.CLUSTER: "configures_cluster",
}

# Roles that may hold at most one per column (substantive/identification/offset).
MUTUALLY_EXCLUSIVE: frozenset[Role] = frozenset({
    Role.OUTCOME, Role.FOCAL, Role.TREATMENT, Role.COVARIATES,
    Role.EXPLANATORY_UNSPECIFIED, Role.INSTRUMENTS, Role.EXPOSURE,
})
DIMENSION_ROLES: frozenset[Role] = frozenset({Role.UNIT, Role.TIME, Role.CLUSTER})


def _edge_kind(op: str) -> str:
    for prefix in ("enters_as_", "offsets_as_", "identifies_as_", "configures_"):
        if op.startswith(prefix):
            return prefix
    raise ValueError(f"unknown edge op {op!r}")


@dataclass(frozen=True)
class RoleAssignment:
    column: str
    role: Role
    source: str
    estimator_family: str
    estimator_key: str
    dropped: bool = False

    @property
    def edge_op(self) -> str:
        return ROLE_EDGE_OP[self.role]

    @property
    def edge_kind(self) -> str:
        return _edge_kind(self.edge_op)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): role vocabulary, edge-op map, RoleAssignment"
```

---

### Task A2: `canonicalize_focal_x` (order = resolved RHS, case-preserving)

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
from workbench.lineage.variable_roles import canonicalize_focal_x

def test_canonicalize_orders_by_resolved_rhs_and_dedups():
    rhs = ["age", "education", "income", "region"]
    assert canonicalize_focal_x("income, education", rhs) == ["education", "income"]

def test_canonicalize_strips_whitespace_and_dups_preserves_case():
    rhs = ["Income", "Education"]
    assert canonicalize_focal_x(" Income , Income ,Education ", rhs) == ["Income", "Education"]
    # case-sensitive: a differently-cased token that is not in rhs is dropped
    assert canonicalize_focal_x("income", ["Income"]) == []

def test_canonicalize_accepts_list_input():
    assert canonicalize_focal_x(["b", "a"], ["a", "b", "c"]) == ["a", "b"]

def test_canonicalize_empty():
    assert canonicalize_focal_x("", ["a"]) == []
    assert canonicalize_focal_x(None, ["a"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k canonicalize -v`
Expected: FAIL — `ImportError: cannot import name 'canonicalize_focal_x'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to variable_roles.py
def canonicalize_focal_x(raw: "str | list[str] | None", resolved_rhs: list[str]) -> list[str]:
    """Parse focal_x once into a canonical, ordered, de-duplicated list.

    Order follows resolved_rhs (model-matrix order), NOT user input order.
    Column names are case-sensitive; tokens not present in resolved_rhs are
    dropped (they cannot be regressors)."""
    if raw is None:
        tokens: list[str] = []
    elif isinstance(raw, str):
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
    else:
        tokens = [str(t).strip() for t in raw if str(t).strip()]
    wanted = set(tokens)
    return [col for col in resolved_rhs if col in wanted]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k canonicalize -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): canonicalize_focal_x ordered by resolved RHS, case-preserving"
```

---

### Task A3: `ResolvedRoleInputs` + `derive_roles` for the regression family

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
from workbench.lineage.variable_roles import ResolvedRoleInputs, derive_roles, Role

def _roles(assignments):
    return {(a.column, a.role) for a in assignments}

def test_regression_focal_declared():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="ols",
        outcome="y", rhs=["education", "age", "region"], focal_x=["education"],
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME),
        ("education", Role.FOCAL),
        ("age", Role.COVARIATES),
        ("region", Role.COVARIATES),
    }

def test_regression_focal_empty_is_unspecified():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="logit",
        outcome="y", rhs=["a", "b"], focal_x=[],
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME),
        ("a", Role.EXPLANATORY_UNSPECIFIED),
        ("b", Role.EXPLANATORY_UNSPECIFIED),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k regression -v`
Expected: FAIL — `ImportError: cannot import name 'ResolvedRoleInputs'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to variable_roles.py

@dataclass(frozen=True)
class ResolvedRoleInputs:
    estimator_family: str            # regression | panel | iv | did
    estimator_key: str               # ols | logit | … | cs_did | dcdh
    outcome: str
    rhs: list[str] = field(default_factory=list)      # resolved RHS (already exposure-stripped for poisson)
    focal_x: list[str] = field(default_factory=list)  # canonical; empty for iv/did
    # poisson
    exposure: str | None = None
    # panel / did
    unit: str | None = None
    time: str | None = None
    # iv
    endog: list[str] = field(default_factory=list)
    instruments: list[str] = field(default_factory=list)
    # did / dcdh
    treatment: list[str] = field(default_factory=list)
    cluster: str | None = None


def _a(col, role, source, ri, dropped=False) -> RoleAssignment:
    return RoleAssignment(column=col, role=role, source=source,
                          estimator_family=ri.estimator_family,
                          estimator_key=ri.estimator_key, dropped=dropped)


def _user_focal_rhs(ri: ResolvedRoleInputs) -> list[RoleAssignment]:
    """Shared rule for user-focal families (regression, poisson, panel)."""
    out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
    if ri.focal_x:
        for col in ri.rhs:
            if col in set(ri.focal_x):
                out.append(_a(col, Role.FOCAL, "focal_x", ri))
            else:
                out.append(_a(col, Role.COVARIATES, "rhs", ri))
    else:
        for col in ri.rhs:
            out.append(_a(col, Role.EXPLANATORY_UNSPECIFIED, "rhs", ri))
    return out


def derive_roles(ri: ResolvedRoleInputs) -> list[RoleAssignment]:
    if ri.estimator_family == "regression":
        out = _user_focal_rhs(ri)
        if ri.exposure:
            out.append(_a(ri.exposure, Role.EXPOSURE, "exposure_col", ri))
        return dedup_edges(out)
    raise ValueError(f"unsupported estimator_family {ri.estimator_family!r}")
```

Also add a temporary `dedup_edges` stub so the import resolves; it is fully implemented in Task A7:

```python
def dedup_edges(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    return list(assignments)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k regression -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): ResolvedRoleInputs + derive_roles regression family"
```

---

### Task A4: Poisson exposure branch + focal/exposure conflict

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from workbench.lineage.variable_roles import RoleConflictError

def test_poisson_rate_exposure_is_offset_not_covariate():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="poisson_rate",
        outcome="claims", rhs=["age"], focal_x=[], exposure="exposure_years",
    )
    got = {(a.column, a.role) for a in derive_roles(ri)}
    assert got == {
        ("claims", Role.OUTCOME),
        ("age", Role.EXPLANATORY_UNSPECIFIED),
        ("exposure_years", Role.EXPOSURE),
    }

def test_poisson_focal_must_not_be_exposure():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="poisson_rate",
        outcome="claims", rhs=["age"], focal_x=["exposure_years"],
        exposure="exposure_years",
    )
    with pytest.raises(RoleConflictError):
        derive_roles(ri)
```

Note: `rhs` is already exposure-stripped by the caller (Task B3), so `exposure_years` is not in `rhs`; the guard catches it appearing in `focal_x`.

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k poisson -v`
Expected: FAIL — `ImportError: cannot import name 'RoleConflictError'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add near top of variable_roles.py
class RoleConflictError(ValueError):
    """A column was assigned conflicting roles (spec §4.8)."""

# in derive_roles, before building regression roles:
    if ri.estimator_family == "regression":
        if ri.exposure and ri.exposure in set(ri.focal_x):
            raise RoleConflictError(
                f"exposure column {ri.exposure!r} cannot also be a focal regressor"
            )
        out = _user_focal_rhs(ri)
        if ri.exposure:
            out.append(_a(ri.exposure, Role.EXPOSURE, "exposure_col", ri))
        return dedup_edges(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k poisson -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): poisson exposure offset + focal/exposure conflict"
```

---

### Task A5: Panel + IV families

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
def test_panel_unit_time_plus_focal():
    ri = ResolvedRoleInputs(
        estimator_family="panel", estimator_key="panel_ols",
        outcome="y", rhs=["x1", "x2"], focal_x=["x1"], unit="firm", time="year",
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME), ("x1", Role.FOCAL), ("x2", Role.COVARIATES),
        ("firm", Role.UNIT), ("year", Role.TIME),
    }

def test_iv_endog_is_focal_instruments_separate():
    ri = ResolvedRoleInputs(
        estimator_family="iv", estimator_key="iv_2sls",
        outcome="wage", rhs=["age"], endog=["schooling"],
        instruments=["quarter_of_birth"],
    )
    assert _roles(derive_roles(ri)) == {
        ("wage", Role.OUTCOME),
        ("schooling", Role.FOCAL),
        ("quarter_of_birth", Role.INSTRUMENTS),
        ("age", Role.COVARIATES),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k "panel or iv" -v`
Expected: FAIL — `ValueError: unsupported estimator_family 'panel'`.

- [ ] **Step 3: Write minimal implementation**

```python
# extend derive_roles dispatch
    if ri.estimator_family == "panel":
        out = _user_focal_rhs(ri)
        if ri.unit:
            out.append(_a(ri.unit, Role.UNIT, "entity", ri))
        if ri.time:
            out.append(_a(ri.time, Role.TIME, "time", ri))
        return validate_role_conflicts(dedup_edges(out))

    if ri.estimator_family == "iv":
        out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
        for col in ri.endog:
            out.append(_a(col, Role.FOCAL, "_iv_endog", ri))
        for col in ri.instruments:
            out.append(_a(col, Role.INSTRUMENTS, "_iv_instruments", ri))
        for col in ri.rhs:
            out.append(_a(col, Role.COVARIATES, "exog", ri))
        return validate_role_conflicts(dedup_edges(out))
```

Add a temporary pass-through `validate_role_conflicts` (fully implemented in Task A7), and wrap the regression/poisson return in it too:

```python
def validate_role_conflicts(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    return assignments
```

Update the `regression` branch's final line to `return validate_role_conflicts(dedup_edges(out))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k "panel or iv" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): panel + iv families"
```

---

### Task A6: DID family (treatment / unit / time / covariates / cluster)

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
def test_classic_did_multi_column_treatment():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="did",
        outcome="emp", rhs=["sector"], unit="county", time="year",
        treatment=["treat", "post"], cluster=None,
    )
    assert _roles(derive_roles(ri)) == {
        ("emp", Role.OUTCOME), ("treat", Role.TREATMENT), ("post", Role.TREATMENT),
        ("sector", Role.COVARIATES), ("county", Role.UNIT), ("year", Role.TIME),
    }

def test_sa_did_has_cluster_no_covariates():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="sa_did",
        outcome="emp", rhs=[], unit="county", time="year",
        treatment=["cohort"], cluster="county",
    )
    got = {(a.column, a.role) for a in derive_roles(ri)}
    assert got == {
        ("emp", Role.OUTCOME), ("cohort", Role.TREATMENT),
        ("county", Role.UNIT), ("year", Role.TIME), ("county", Role.CLUSTER),
    }

def test_did_no_cluster_when_absent():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="dcdh",
        outcome="emp", rhs=[], unit="county", time="year",
        treatment=["switch"], cluster=None,
    )
    assert not any(a.role == Role.CLUSTER for a in derive_roles(ri))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k did -v`
Expected: FAIL — `ValueError: unsupported estimator_family 'did'`.

- [ ] **Step 3: Write minimal implementation**

```python
# extend derive_roles dispatch
    if ri.estimator_family == "did":
        out = [_a(ri.outcome, Role.OUTCOME, "outcome", ri)]
        for col in ri.treatment:        # deterministic order from caller
            out.append(_a(col, Role.TREATMENT, "treatment", ri))
        for col in ri.rhs:
            out.append(_a(col, Role.COVARIATES, "covariates", ri))
        if ri.unit:
            out.append(_a(ri.unit, Role.UNIT, "entity", ri))
        if ri.time:
            out.append(_a(ri.time, Role.TIME, "time", ri))
        if ri.cluster:                  # only when present
            out.append(_a(ri.cluster, Role.CLUSTER, "_cs_cluster_var", ri))
        return validate_role_conflicts(dedup_edges(out))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k did -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): DID family (treatment/unit/time/covariates/cluster)"
```

---

### Task A7: Conflict policy + edge de-dup (real implementations)

**Files:**
- Modify: `backend/workbench/lineage/variable_roles.py`
- Test: `tests/lineage/test_variable_roles.py`

- [ ] **Step 1: Write the failing test**

```python
def test_unit_plus_cluster_allowed():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="cs_did",
        outcome="y", rhs=["z"], unit="firm", time="year",
        treatment=["cohort"], cluster="firm",   # cluster == unit -> allowed
    )
    pairs = {(a.column, a.role) for a in derive_roles(ri)}
    assert ("firm", Role.UNIT) in pairs and ("firm", Role.CLUSTER) in pairs

def test_unit_plus_covariate_rejected():
    # firm appears both as entity AND as a covariate -> hard conflict
    ri = ResolvedRoleInputs(
        estimator_family="panel", estimator_key="panel_ols",
        outcome="y", rhs=["firm", "x"], focal_x=[], unit="firm", time="year",
    )
    with pytest.raises(RoleConflictError):
        derive_roles(ri)

def test_dedup_same_column_role_two_sources_one_edge():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="did",
        outcome="y", rhs=[], unit="c", time="t",
        treatment=["treat", "treat"],   # duplicate source resolution
    )
    treat = [a for a in derive_roles(ri) if a.column == "treat"]
    assert len(treat) == 1
    assert "treatment" in treat[0].source  # provenance retained
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -k "allowed or rejected or dedup" -v`
Expected: FAIL — `test_unit_plus_covariate_rejected` does not raise; `test_dedup…` returns 2 assignments.

- [ ] **Step 3: Write minimal implementation**

```python
# replace the stubs with real implementations

def dedup_edges(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    """Collapse by (column, role, edge_kind); merge sources into provenance."""
    merged: dict[tuple[str, Role, str], RoleAssignment] = {}
    for a in assignments:
        key = (a.column, a.role, a.edge_kind)
        if key in merged:
            prev = merged[key]
            if a.source not in prev.source.split("|"):
                merged[key] = RoleAssignment(
                    column=prev.column, role=prev.role,
                    source=f"{prev.source}|{a.source}",
                    estimator_family=prev.estimator_family,
                    estimator_key=prev.estimator_key,
                    dropped=prev.dropped or a.dropped,
                )
        else:
            merged[key] = a
    return list(merged.values())


_ALLOWED_OVERLAPS: frozenset[frozenset[Role]] = frozenset({
    frozenset({Role.UNIT, Role.CLUSTER}),
    frozenset({Role.TIME, Role.CLUSTER}),
    frozenset({Role.COVARIATES, Role.CLUSTER}),
})


def validate_role_conflicts(assignments: list[RoleAssignment]) -> list[RoleAssignment]:
    by_col: dict[str, set[Role]] = {}
    for a in assignments:
        by_col.setdefault(a.column, set()).add(a.role)
    for col, roles in by_col.items():
        if len(roles) <= 1:
            continue
        # two mutually-exclusive roles on one column -> always a conflict
        if len(roles & MUTUALLY_EXCLUSIVE) >= 2:
            raise RoleConflictError(f"{col!r} holds conflicting roles {sorted(r.value for r in roles)}")
        # any non-allowlisted overlap -> conflict (Cluster is the only role
        # permitted to overlap a substantive role)
        if roles not in _ALLOWED_OVERLAPS:
            raise RoleConflictError(f"{col!r} holds non-allowlisted roles {sorted(r.value for r in roles)}")
    return assignments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_variable_roles.py -v`
Expected: PASS (all Phase A tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/variable_roles.py tests/lineage/test_variable_roles.py
git commit -m "feat(roles): conflict policy (tiered allowlist) + edge de-dup"
```

---

## Phase B — Persistence (`focal_x`)

### Task B1: Parse `focal_x` from the run form

**Files:**
- Modify: `backend/workbench/api.py` (the `/runs` form handler and `_start_run` dispatch — see `x_columns = form.get("x", "")…` around line 164)
- Test: `tests/test_api_focal_x.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_focal_x.py
from workbench.api import _parse_focal_x   # thin parser we add

def test_parse_focal_x_canonicalizes_against_x():
    assert _parse_focal_x("income, education", ["age", "education", "income"]) == ["education", "income"]

def test_parse_focal_x_empty():
    assert _parse_focal_x("", ["a"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_api_focal_x.py -v`
Expected: FAIL — `ImportError: cannot import name '_parse_focal_x'`.

- [ ] **Step 3: Write minimal implementation**

```python
# in api.py, near x_columns parsing
from .lineage.variable_roles import canonicalize_focal_x

def _parse_focal_x(raw: str, x_columns: list[str]) -> list[str]:
    return canonicalize_focal_x(raw, x_columns)
```

And in the `/runs` handler add `focal_x: str = Form("")` and, right after `x_columns = …`:

```python
    focal_x = _parse_focal_x(form.get("focal_x", ""), x_columns)
```

Thread `focal_x` into `write_run_inputs(...)` and `_write_manifest(...)` calls (wired in B2).

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_api_focal_x.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/api.py tests/test_api_focal_x.py
git commit -m "feat(roles): parse + canonicalize focal_x from run form"
```

---

### Task B2: Persist `focal_x` in manifest + run_inputs

**Files:**
- Modify: `backend/workbench/orchestrator/_manifest.py` (`_write_manifest`, around line 87)
- Modify: `backend/workbench/lineage/run_inputs.py` (`write_run_inputs`, around line 32)
- Test: `tests/test_focal_x_persistence.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_focal_x_persistence.py
import json
from pathlib import Path
from workbench.orchestrator._manifest import _write_manifest

def test_manifest_includes_focal_x(tmp_path: Path):
    _write_manifest(tmp_path, "run1", "auto", "running", [],
                    started_at="t", y="y", x=["a", "b"],
                    requested_model_type="ols", focal_x=["a"])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["focal_x"] == ["a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_focal_x_persistence.py -v`
Expected: FAIL — `_write_manifest() got an unexpected keyword argument 'focal_x'`.

- [ ] **Step 3: Write minimal implementation**

In `_manifest.py`, add `focal_x: list[str] | None = None` to `_write_manifest`'s signature and include `"focal_x": list(focal_x or [])` in the manifest dict. In `run_inputs.py`, add `focal_x` to the persisted `form` payload (canonical list). Update the call sites in `api.py` to pass `focal_x=focal_x`.

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_focal_x_persistence.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/orchestrator/_manifest.py backend/workbench/lineage/run_inputs.py backend/workbench/api.py tests/test_focal_x_persistence.py
git commit -m "feat(roles): persist focal_x in manifest + run_inputs"
```

---

### Task B3: Thread `focal_x` into ctx artifacts

**Files:**
- Modify: the engine entry that seeds `ctx.artifacts` from the run inputs (search: `ctx.artifacts["_normalized_x"]` producer in `engine/stages/ytype.py` and the parse stage that reads the form). Add `ctx.artifacts["_focal_x"]`.
- Test: extend `tests/test_focal_x_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
def test_focal_x_reaches_ctx_artifacts(run_a_minimal_ols_run):
    # fixture runs a tiny OLS with focal_x=["x1"]; assert artifact present
    ctx = run_a_minimal_ols_run(focal_x=["x1"])
    assert ctx.artifacts["_focal_x"] == ["x1"]
```

(If no such fixture exists, assert on the recorded graph instead — see Task C2 — and skip this micro-test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_focal_x_persistence.py -k ctx -v`
Expected: FAIL — `KeyError: '_focal_x'`.

- [ ] **Step 3: Write minimal implementation**

Seed `ctx.artifacts["_focal_x"]` where the other `_normalized_*`/form-derived artifacts are seeded (same stage that sets `_normalized_x`). Re-canonicalize against `_normalized_x` defensively: `canonicalize_focal_x(form_focal_x, normalized_x)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_focal_x_persistence.py -k ctx -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine tests/test_focal_x_persistence.py
git commit -m "feat(roles): thread focal_x into ctx artifacts"
```

---

## Phase C — Recording integration + golden regen

### Task C1: Build `ResolvedRoleInputs` from `ctx` (the bridge)

**Files:**
- Create: `backend/workbench/lineage/role_inputs_from_ctx.py`
- Test: `tests/lineage/test_role_inputs_from_ctx.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lineage/test_role_inputs_from_ctx.py
from workbench.lineage.role_inputs_from_ctx import build_resolved_inputs

class _Ctx:
    def __init__(self, artifacts, exposure_col=None):
        self.artifacts = artifacts
        self.exposure_col = exposure_col

def test_iv_inputs_mapped():
    ctx = _Ctx({
        "_model_results": [("iv_2sls_1", {"model_type": "iv_2sls"})],
        "_normalized_y": "wage", "_normalized_x": ["age"],
        "_poisson_x": ["age"], "_focal_x": [],
        "_iv_endog": ["schooling"], "_iv_instruments": ["qob"],
    })
    ri = build_resolved_inputs(ctx)
    assert ri.estimator_family == "iv"
    assert ri.endog == ["schooling"] and ri.instruments == ["qob"]
    assert ri.outcome == "wage" and ri.rhs == ["age"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_role_inputs_from_ctx.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/workbench/lineage/role_inputs_from_ctx.py
from __future__ import annotations
from .variable_roles import ResolvedRoleInputs

_FAMILY = {
    "ols": "regression", "logit": "regression", "probit": "regression",
    "poisson": "regression", "poisson_rate": "regression",
    "negative_binomial": "regression", "glm": "regression",
    "panel_ols": "panel", "iv_2sls": "iv",
    "did": "did", "cs_did": "did", "sa_did": "did", "dcdh": "did",
}

def _family(key: str) -> str:
    if key.startswith("glm"):
        return "regression"
    return _FAMILY.get(key, "regression")

def build_resolved_inputs(ctx) -> ResolvedRoleInputs:
    art = ctx.artifacts
    model_results = art.get("_model_results") or []
    key = model_results[0][0].rsplit("_", 1)[0] if model_results else "ols"
    # normalize handler ids like "iv_2sls_1" -> "iv_2sls", "cs_did_1" -> "cs_did"
    key = model_results[0][1].get("model_type", key) if model_results else "ols"
    family = _family(key)
    exposure = getattr(ctx, "exposure_col", None)
    rhs = art.get("_poisson_x", art.get("_normalized_x", [])) if family == "regression" \
        else art.get("_normalized_x", [])
    did = art.get("_did_normalized")
    treatment = []
    unit = time = None
    if family == "did":
        treatment = [c for c in (
            art.get("_did_cohort_col"), art.get("_did_treat_col"),
            art.get("_did_post_col"), art.get("_did_status_col"),
            art.get("_dcdh_treatment_col"),
        ) if c]
        unit = getattr(did, "entity", None) if did else None
        time = getattr(did, "time", None) if did else None
    if family == "panel":
        idc = art.get("_id_candidates") or []
        tc = art.get("_time_candidates") or []
        unit = idc[0] if idc else None
        time = tc[0] if tc else None
    return ResolvedRoleInputs(
        estimator_family=family, estimator_key=key,
        outcome=art["_normalized_y"], rhs=list(rhs),
        focal_x=list(art.get("_focal_x") or []),
        exposure=exposure if family == "regression" else None,
        unit=unit, time=time,
        endog=list(art.get("_iv_endog") or []),
        instruments=list(art.get("_iv_instruments") or []),
        treatment=treatment,
        cluster=art.get("_cs_cluster_var") or None,
    )
```

(The `key` normalization keeps `model_type` as the estimator key, matching `_FAMILY`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/lineage/test_role_inputs_from_ctx.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/role_inputs_from_ctx.py tests/lineage/test_role_inputs_from_ctx.py
git commit -m "feat(roles): build ResolvedRoleInputs from ctx artifacts"
```

---

### Task C2: Emit role edges in `recording.py`

**Files:**
- Modify: `backend/workbench/engine/stages/recording.py`
- Test: `tests/engine/test_recording_roles.py` (new) — drive a minimal OLS run and assert edges.

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_recording_roles.py
# Uses the existing end-to-end run helper (see other engine tests for the fixture
# that fits a tiny OLS and returns the run root). Assert role edges exist.
import json
from tests.engine.helpers import run_ols_fixture   # existing helper pattern

def test_ols_emits_role_edges(tmp_path):
    run_root = run_ols_fixture(tmp_path, y="y", x=["x1", "x2"], focal_x=["x1"])
    graph = json.loads((run_root / "graph.json").read_text())
    ops = {(e["source_id"], e["target_id"], e["op"]) for e in graph["edges"].values()}
    assert ("var:x1:cleaned", "model:ols_1", "enters_as_focal") in ops
    assert ("var:x2:cleaned", "model:ols_1", "enters_as_covariates") in ops
    assert ("var:y:cleaned", "model:ols_1", "enters_as_outcome") in ops
```

(Confirm the exact run helper name/signature from a neighbouring test in `tests/engine/`; reuse it rather than building a new harness.)

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/engine/test_recording_roles.py -v`
Expected: FAIL — no `enters_as_*` edges in the graph.

- [ ] **Step 3: Write minimal implementation**

In `recording.py`, after the model node is recorded (the `if model_results:` block, around line 137), add role-edge emission. Variable identity nodes for `[normalized_y, *normalized_x]` already exist; add identity nodes for any role column not yet recorded (unit/time/treatment/instruments/exposure/cluster), then emit edges:

```python
from ...lineage.variable_roles import derive_roles, dedup_edges, validate_role_conflicts
from ...lineage.role_inputs_from_ctx import build_resolved_inputs

# inside RecordingStage.run, after the primary model node + its cleaned->model edge:
if model_results:
    primary_model_node = f"model:{model_results[0][0]}"
    assignments = derive_roles(build_resolved_inputs(ctx))
    seen_var: set[str] = set()
    for a in assignments:
        var_id = f"var:{a.column}:cleaned"
        if var_id not in _recorder._nodes and var_id not in seen_var:
            _recorder.record_variable(
                node_id=var_id, display_label=a.column,
                parent_stage_id="stage:cleaned", stage=Stage.TRANSFORM,
            )
            _recorder.record_edge(
                edge_id=f"e:cleaned-{a.column}", source_id="stage:cleaned",
                target_id=var_id, op="select_column",
            )
        seen_var.add(var_id)
    for a in assignments:
        _recorder.record_edge(
            edge_id=f"e:role:{a.column}:{a.role.value}",
            source_id=f"var:{a.column}:cleaned",
            target_id=primary_model_node,
            op=a.edge_op,
            params={"role": a.role.value, "source": a.source,
                    "estimator_family": a.estimator_family,
                    "dropped": a.dropped},
        )
```

Keep the existing `e:cleaned-model-primary` edge — it is the data-provenance edge; the role edges are additive. (If goldens prefer a single representation, drop the old `stage:cleaned -> model` edge here and let role edges carry the flow; decide during golden regen, Task C4, and keep the choice consistent.)

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/engine/test_recording_roles.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/recording.py tests/engine/test_recording_roles.py
git commit -m "feat(roles): emit role-bearing var->model edges in recording"
```

---

### Task C3: Dropped variables retain pre-drop role

**Files:**
- Modify: `backend/workbench/engine/stages/recording.py`
- Test: `tests/engine/test_recording_roles.py`

- [ ] **Step 1: Write the failing test**

```python
def test_dropped_focal_keeps_role(tmp_path):
    # x1 is collinear and gets dropped; it was declared focal
    run_root = run_ols_fixture(tmp_path, y="y", x=["x1", "x1_dup"],
                               focal_x=["x1"], force_drop=["x1"])
    graph = json.loads((run_root / "graph.json").read_text())
    role_edges = [e for e in graph["edges"].values()
                  if e["source_id"] == "var:x1:cleaned" and e["op"] == "enters_as_focal"]
    assert role_edges and role_edges[0]["params"]["dropped"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/engine/test_recording_roles.py -k dropped -v`
Expected: FAIL — `dropped` is False (assignment built before drop info applied).

- [ ] **Step 3: Write minimal implementation**

Per spec §4.9 the `dropped` flag is applied **after** role assignment. After computing `assignments`, mark dropped using the existing `dropped_vars` list already computed in `recording.py`:

```python
dropped_cols = {entry["variable"] for entry in dropped_vars}
assignments = [
    a if a.column not in dropped_cols else
    RoleAssignment(column=a.column, role=a.role, source=a.source,
                   estimator_family=a.estimator_family,
                   estimator_key=a.estimator_key, dropped=True)
    for a in assignments
]
```

(Import `RoleAssignment` alongside `derive_roles`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/engine/test_recording_roles.py -k dropped -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/recording.py tests/engine/test_recording_roles.py
git commit -m "feat(roles): mark dropped role assignments post-derivation"
```

---

### Task C4: Regenerate graph goldens + assert coefficient goldens unchanged

**Files:**
- Modify: golden snapshot fixtures under the golden directory (find with `git grep -l "graph.json" backend/tests` and the golden harness root).
- Test: the existing golden suite (`scripts/gate.sh` golden phase).

- [ ] **Step 1: Run the golden suite to see the expected diff**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` (or the golden-only entry point).
Expected: **graph** goldens drift (new role edges/nodes) for in-scope families; **coefficient / estimation-result** goldens must show **0 drift**. If any coefficient golden drifts, STOP — estimation leaked (spec §1); fix before regenerating.

- [ ] **Step 2: Inspect the diff to confirm only graph structure changed**

Run: `git diff -- <golden-dir>` and verify every change is an added `enters_as_*` / `offsets_as_exposure` / `identifies_as_instruments` / `configures_*` edge (and any new identity nodes), nothing numeric.

- [ ] **Step 3: Regenerate goldens**

Run the project's golden-update command (search `scripts/` / Makefile for `--update`/`UPDATE_GOLDEN=1`; use the established mechanism, do not hand-edit numbers).

- [ ] **Step 4: Re-run the gate**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`
Expected: `>>> GATE PASSED` — golden 0-drift after regen, coefficients unchanged.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(roles): regenerate graph goldens (coefficients unchanged)"
```

---

## Phase D — Frontend rendering

### Task D1: Shared role constants + edge-op map

**Files:**
- Create: `frontend/src/lineage/roles.ts`
- Test: `frontend/src/lineage/roles.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lineage/roles.test.ts
import { describe, it, expect } from "vitest";
import { ROLE_OF_EDGE_OP, ROLE_GROUP_ORDER, roleLabel } from "./roles";

describe("roles", () => {
  it("maps edge ops to roles", () => {
    expect(ROLE_OF_EDGE_OP["enters_as_focal"]).toBe("focal");
    expect(ROLE_OF_EDGE_OP["offsets_as_exposure"]).toBe("exposure");
    expect(ROLE_OF_EDGE_OP["identifies_as_instruments"]).toBe("instruments");
    expect(ROLE_OF_EDGE_OP["configures_cluster"]).toBe("cluster");
  });
  it("orders groups canonically with treatment", () => {
    expect(ROLE_GROUP_ORDER).toEqual([
      "outcome", "focal", "treatment", "covariates",
      "instruments", "exposure", "unit", "time", "cluster",
    ]);
  });
  it("labels roles for humans", () => {
    expect(roleLabel("outcome")).toBe("Outcome Variable (Y)");
    expect(roleLabel("focal")).toBe("Focal Explanatory Variable (X)");
    expect(roleLabel("covariates")).toBe("Covariates (Z)");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lineage/roles.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lineage/roles.ts
export type Role =
  | "outcome" | "focal" | "treatment" | "covariates"
  | "explanatory_unspecified" | "instruments" | "exposure"
  | "unit" | "time" | "cluster";

export const ROLE_OF_EDGE_OP: Record<string, Role> = {
  enters_as_outcome: "outcome",
  enters_as_focal: "focal",
  enters_as_treatment: "treatment",
  enters_as_covariates: "covariates",
  enters_as_explanatory_unspecified: "explanatory_unspecified",
  offsets_as_exposure: "exposure",
  identifies_as_instruments: "instruments",
  configures_unit: "unit",
  configures_time: "time",
  configures_cluster: "cluster",
};

export const ROLE_GROUP_ORDER: Role[] = [
  "outcome", "focal", "treatment", "covariates",
  "instruments", "exposure", "unit", "time", "cluster",
];

const LABELS: Record<Role, string> = {
  outcome: "Outcome Variable (Y)",
  focal: "Focal Explanatory Variable (X)",
  treatment: "Treatment (D)",
  covariates: "Covariates (Z)",
  explanatory_unspecified: "Explanatory variables (role unspecified)",
  instruments: "Instruments",
  exposure: "Exposure / offset",
  unit: "Unit (entity)",
  time: "Time",
  cluster: "Cluster (inference)",
};

export function roleLabel(role: Role): string {
  return LABELS[role];
}

export const DASHED_ROLES: Set<Role> = new Set(["unit", "time", "cluster"]);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lineage/roles.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/roles.ts frontend/src/lineage/roles.test.ts
git commit -m "feat(roles): frontend role constants + edge-op map"
```

---

### Task D2: Group variables by role in `RunSnapshotAdapter`

**Files:**
- Modify: `frontend/src/workbench/RunSnapshotAdapter.ts`
- Test: `frontend/src/workbench/RunSnapshotAdapter.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { groupVariablesByRole } from "./RunSnapshotAdapter";

describe("groupVariablesByRole", () => {
  it("buckets variable edges into ordered role groups", () => {
    const edges = [
      { source: "var:y:cleaned", target: "model:ols_1", op: "enters_as_outcome", params: {} },
      { source: "var:x1:cleaned", target: "model:ols_1", op: "enters_as_focal", params: {} },
      { source: "var:age:cleaned", target: "model:ols_1", op: "enters_as_covariates", params: {} },
    ];
    const groups = groupVariablesByRole(edges, "model:ols_1");
    expect(groups.map((g) => g.role)).toEqual(["outcome", "focal", "covariates"]);
    expect(groups[1].columns).toEqual(["x1"]);
  });

  it("renders empty focal as a single unspecified group", () => {
    const edges = [
      { source: "var:y:cleaned", target: "model:ols_1", op: "enters_as_outcome", params: {} },
      { source: "var:a:cleaned", target: "model:ols_1", op: "enters_as_explanatory_unspecified", params: {} },
    ];
    const groups = groupVariablesByRole(edges, "model:ols_1");
    expect(groups.some((g) => g.role === "explanatory_unspecified")).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/workbench/RunSnapshotAdapter.test.ts -t groupVariablesByRole`
Expected: FAIL — `groupVariablesByRole` undefined.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/workbench/RunSnapshotAdapter.ts
import { ROLE_OF_EDGE_OP, ROLE_GROUP_ORDER, type Role } from "../lineage/roles";

type RoleEdge = { source: string; target: string; op: string; params?: Record<string, unknown> };
export type RoleGroup = { role: Role; columns: string[]; dropped: Set<string> };

function columnOf(varNodeId: string): string {
  // "var:x1:cleaned" -> "x1"
  const m = /^var:(.+):cleaned$/.exec(varNodeId);
  return m ? m[1] : varNodeId;
}

export function groupVariablesByRole(edges: RoleEdge[], modelNodeId: string): RoleGroup[] {
  const byRole = new Map<Role, RoleGroup>();
  for (const e of edges) {
    if (e.target !== modelNodeId) continue;
    const role = ROLE_OF_EDGE_OP[e.op];
    if (!role) continue;
    const g = byRole.get(role) ?? { role, columns: [], dropped: new Set<string>() };
    const col = columnOf(e.source);
    if (!g.columns.includes(col)) g.columns.push(col);
    if (e.params?.dropped === true) g.dropped.add(col);
    byRole.set(role, g);
  }
  const order = [...ROLE_GROUP_ORDER, "explanatory_unspecified" as Role];
  return order.filter((r) => byRole.has(r)).map((r) => byRole.get(r)!);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/workbench/RunSnapshotAdapter.test.ts -t groupVariablesByRole`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workbench/RunSnapshotAdapter.ts frontend/src/workbench/RunSnapshotAdapter.test.ts
git commit -m "feat(roles): group variable edges by role in adapter"
```

---

### Task D3: Render role groups in the lineage view

**Files:**
- Modify: the component that draws variables under the model (the variable-rendering path used by `GraphView.tsx` / `GraphCanvas`). Add role-group sections using `groupVariablesByRole`, dashed edges for `DASHED_ROLES`, a `roles: unspecified` / `legacy_unspecified` tag on the model node.
- Test: a component test alongside that file (vitest + testing-library), asserting role group headers render and dashed class applies to unit/time/cluster.

- [ ] **Step 1: Write the failing test**

```tsx
// near the variable-rendering component, e.g. RoleGroups.test.tsx
import { render, screen } from "@testing-library/react";
import { RoleGroups } from "./RoleGroups";

it("shows role headers and marks dropped focal", () => {
  render(<RoleGroups groups={[
    { role: "outcome", columns: ["y"], dropped: new Set() },
    { role: "focal", columns: ["x1"], dropped: new Set(["x1"]) },
  ]} />);
  expect(screen.getByText("Outcome Variable (Y)")).toBeInTheDocument();
  expect(screen.getByText(/x1/)).toHaveAttribute("data-dropped", "true");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/**/RoleGroups.test.tsx`
Expected: FAIL — `RoleGroups` missing.

- [ ] **Step 3: Write minimal implementation**

Create `RoleGroups.tsx` rendering each group with `roleLabel(role)` as header, columns as chips (`data-dropped` when in `group.dropped`), and `data-edge="dashed"` when `DASHED_ROLES.has(role)`. Wire it into the lineage view where variables for the focused model are shown. Add the model-node tag: when the only RHS group is `explanatory_unspecified`, show `roles: unspecified`; when the run has no role edges at all, show `roles: legacy_unspecified` (back-compat per spec §5).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/**/RoleGroups.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(roles): render role groups in lineage view"
```

---

### Task D4: Node detail drawer — separated spec blocks

**Files:**
- Modify: the node detail drawer component (the one that shows model node info / "View Raw JSON" lives in `NodeActionMenu`; the drawer body component renders node payload).
- Test: drawer component test.

- [ ] **Step 1: Write the failing test**

```tsx
it("splits formula / identification / offset / inference blocks", () => {
  render(<ModelSpecBlocks spec={{
    outcome: "wage", focal: ["schooling"], covariates: ["age"],
    instruments: ["qob"], exposure: null, unit: null, time: null, cluster: null,
    se_type: "robust", estimator: "iv_2sls",
  }} />);
  expect(screen.getByText("wage ~ schooling + age")).toBeInTheDocument();
  expect(screen.getByText(/Identification/)).toBeInTheDocument();
  expect(screen.queryByText(/qob/)).not.toBeNull();
});

it("shows explanatory-variables formula when focal empty", () => {
  render(<ModelSpecBlocks spec={{
    outcome: "y", focal: [], covariates: [], explanatory: ["a", "b"],
    instruments: [], exposure: null, unit: null, time: null, cluster: null,
    se_type: "HC1", estimator: "ols",
  }} />);
  expect(screen.getByText("y ~ a + b")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/**/ModelSpecBlocks.test.tsx`
Expected: FAIL — `ModelSpecBlocks` missing.

- [ ] **Step 3: Write minimal implementation**

Create `ModelSpecBlocks.tsx`: Formula block (`y ~ focal + covariates`, or `y ~ <explanatory>` when focal empty, plus `se_type`/`estimator`); Identification block (instruments) only when present; Offset block (exposure) only when present; Panel/inference block (unit, time, cluster) only when present. Never concatenate instruments/exposure into the RHS formula. Derive Focal/Treatment from structural fields for causal families (never stale `focal_x`). Wire into the drawer.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/**/ModelSpecBlocks.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(roles): drawer spec blocks (formula/identification/offset/inference)"
```

---

## Phase E — Declaration UX

### Task E1: Focal multi-select on the run form

**Files:**
- Modify: `frontend/src/runForm/RunForm.tsx` (and a new `frontend/src/runForm/FocalSelect.tsx`)
- Test: `frontend/src/runForm/FocalSelect.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { FocalSelect } from "./FocalSelect";

it("lets the user mark a subset of x as focal", () => {
  const onChange = vi.fn();
  render(<FocalSelect xColumns={["education", "age"]} focal={[]} onChange={onChange} />);
  fireEvent.click(screen.getByLabelText("education"));
  expect(onChange).toHaveBeenCalledWith(["education"]);
});

it("is hidden for IV/DID families (focal is structural)", () => {
  const { container } = render(
    <FocalSelect xColumns={["age"]} focal={[]} onChange={() => {}} family="iv" />,
  );
  expect(container).toBeEmptyDOMElement();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runForm/FocalSelect.test.tsx`
Expected: FAIL — `FocalSelect` missing.

- [ ] **Step 3: Write minimal implementation**

Create `FocalSelect.tsx`: renders a checkbox per `xColumns`, toggling membership in `focal`; renders nothing when `family` ∈ {iv, did, cs_did, sa_did, dcdh}. Wire into `RunForm.tsx`, posting `focal_x` (comma-joined) only for user-focal families; clear it otherwise.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/runForm/FocalSelect.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm
git commit -m "feat(roles): focal multi-select on run form"
```

---

### Task E2: Edit `focal_x` in the draft model-node inspector

**Files:**
- Modify: `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`
- Modify (backend): the PipelineDraft model-node `editable_schema` to include a `focal_x` control for user-focal families, and the draft PATCH → execute path to carry `focal_x` into the child run form.
- Test: `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("exposes a focal_x control and saves it", () => {
  const onSave = vi.fn();
  render(<ModelNodeInspector
    node={{ node_type: "model", node_id: "m", model_type: "ols", schema_id: "s",
      params: { focal_x: [] }, source_params: { focal_x: [] },
      editable_schema: [{ key: "focal_x", kind: "multiselect", label: "Focal X",
        options: ["education", "age"], value: [] }] } as any}
    draftHash="h" onSave={onSave} />);
  fireEvent.click(screen.getByLabelText("education"));
  fireEvent.click(screen.getByText("Save changes"));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    params: expect.objectContaining({ focal_x: ["education"] }),
  }));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pipelineDrafts/ModelNodeInspector.test.tsx -t focal_x`
Expected: FAIL — no multiselect control rendered (or `renderControl` lacks `multiselect`).

- [ ] **Step 3: Write minimal implementation**

Ensure `renderControl` (in `lineage/controls/controlFactory`) supports a `multiselect` control kind; the inspector already maps `editable_schema` → controls and writes into `params`. On the backend, add `focal_x` to the model node's `editable_schema` for user-focal families and pass it through draft execute into the child run's `focal_x` form field. For IV/DID drafts, omit the control (focal is structural).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pipelineDrafts/ModelNodeInspector.test.tsx -t focal_x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pipelineDrafts backend/workbench
git commit -m "feat(roles): edit focal_x in draft model-node inspector"
```

---

## Phase F — Problem 6: distinguish same-named model nodes

### Task F1: Model-node identity badge in the forest

**Files:**
- Modify: the forest model-node rendering component (the one that draws `ols_robust (primary)` across runs).
- Test: badge component test.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { ModelNodeBadge } from "./ModelNodeBadge";

it("shows run short id, hash short, and source/rerun", () => {
  render(<ModelNodeBadge runId="20260630_021506_881210_d5cbd8a7" nodeHash="bb21bce…" role="source" />);
  expect(screen.getByText(/021506/)).toBeInTheDocument();
  expect(screen.getByText(/bb21b/)).toBeInTheDocument();
  expect(screen.getByText(/source/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/**/ModelNodeBadge.test.tsx`
Expected: FAIL — `ModelNodeBadge` missing.

- [ ] **Step 3: Write minimal implementation**

Create `ModelNodeBadge.tsx` rendering `…<run-short> · #<hash-short> · <role>`. `run-short` = a stable slice of the run id (e.g. the `HHMMSS` segment), `hash-short` = first 5 chars of `nodeHash`, `role` = `source` for the originating run / `rerun` for child reruns (already known in the forest model). Render it on each forest model node.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/**/ModelNodeBadge.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(roles): model-node identity badge across the forest"
```

---

## Phase G — Final gate

### Task G1: Full gate + edge-case sweep

**Files:** none (verification only).

- [ ] **Step 1: Run the full gate**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`
Expected: `>>> GATE PASSED` — backend, golden (0-drift after regen), frontend, typecheck all green.

- [ ] **Step 2: Confirm the spec's headline guardrail**

Run: `git diff <golden-dir> --stat` against the pre-C4 baseline tag/commit and confirm no estimation-result golden changed numerically (only graph structure).

- [ ] **Step 3: Manual smoke (optional, mirrors v1.6.4 smoke)**

Submit a tiny OLS with a declared focal, open lineage, confirm Outcome/Focal/Covariates groups render and flow into the model; submit an IV run, confirm Instruments render via `identifies_as_instruments`; submit a DID run, confirm Treatment/Unit/Time appear (previously invisible).

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "chore(roles): final gate fixups"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §3 role vocabulary + edge ops → A1; roles-on-edge → C2.
- §4 per-family derivation → A3–A6; §4.8 conflict policy → A7; §4.9 phase order → C1–C3 ordering + C3 dropped-after.
- §5 data model / persistence / focal_x canonical / IV-DID clear / backward-compat → A2, B1–B3, E1–E2 (clear for causal in form/draft), D3 (`legacy_unspecified`).
- §6 recording (identity node + role edges, de-dup, cluster-absent, dropped) → C2, C3, A7.
- §7 declaration UX (form + draft editor + drawer blocks) → E1, E2, D4.
- §8 frontend rendering (generic groups, canonical order, unspecified fallback, dropped-in-role, badge) → D1–D3, F1.
- §9 testing (per-family, conflict, fallback, cluster-absent, multi-role, estimation-invariance golden) → A3–A7, C2–C4.

**Placeholder scan:** Task B3's micro-test is marked optional with a concrete fallback; C4 uses the project's golden-update mechanism (named, not invented). Drawer/badge/role-group component file names are explicit; the host wiring points to the exact existing files identified during exploration.

**Type consistency:** `RoleAssignment`, `ResolvedRoleInputs`, `Role`, `ROLE_EDGE_OP`, `derive_roles`, `dedup_edges`, `validate_role_conflicts`, `canonicalize_focal_x` names are identical across Phase A tasks and reused verbatim in B–C. Frontend `Role`, `ROLE_OF_EDGE_OP`, `ROLE_GROUP_ORDER`, `roleLabel`, `groupVariablesByRole` are consistent across D tasks.
