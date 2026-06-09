# V1.5.4.3 — Foundation Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn silent failure modes into loud, gated ones — wire the AnalysisPack extension points (fail-loud + explicit stage insertion + rerun_actions reference), add a frontend type gate, split the App.tsx god-component, and codify the gates — with zero user-facing behavior change.

**Architecture:** Backend changes are guarded so the only existing pack (CORE_PACK, which populates none of the alarmed fields and adds no stages/rerun_actions) produces byte-identical output → golden 0-drift. Frontend gains `tsc --noEmit` as a real gate, which then acts as the safety net for the behavior-frozen run-form split. A `scripts/gate.sh` makes the antifragility gates executable.

**Tech Stack:** Python 3.11, pytest, dataclasses; React + TypeScript + Vitest + tsc; bash.

**Spec:** `docs/superpowers/specs/2026-06-09-workbench-v1.5.4.3-foundation-hardening-design.md`

---

## File Structure

**Backend (modify):**
- `backend/workbench/engine/pack.py` — `PackContractError`, fail-loud `register_pack`, `StageInsertion`, `RerunAction`, `RERUN_ACTION_REGISTRY`, stage splicing.
- `backend/workbench/engine/stages/__init__.py` — expose a splice helper / keep PIPELINE the single ordered list.
- `backend/workbench/engine/recommended_actions.py` — append registry rerun_actions to failure actions.

**Backend (tests):**
- `tests/test_pack_contract.py` — fail-loud + annotations.
- `tests/test_pack_stage_insertion.py` — explicit insertion + bad anchor.
- `tests/test_pack_rerun_actions.py` — rerun_actions flow-through + reverse-check.

**Tooling:**
- `pyproject.toml` — `pythonpath = ["backend", "."]`.
- `scripts/gate.sh` — one-command gate.

**Frontend:**
- `frontend/tsconfig.json` (create) + `frontend/package.json` (typecheck script) + whatever source files `tsc` flags.
- `frontend/src/runForm/RunForm.tsx` (create) + `frontend/src/App.tsx` (slim down).

---

## Phase 0 — Worktree Setup

### Task 0: Create branch, worktree, environments

**Files:** none (environment only)

- [ ] **Step 1: Create branch + worktree from main head**

```bash
cd "/Users/jiayuanren/项目规划"
git fetch origin
git worktree add -b workbench-v1.5.4.3 .worktrees/workbench-v1.5.4.3 main
cd .worktrees/workbench-v1.5.4.3
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

```bash
.venv/bin/python -m pytest -q
cd frontend && npx vitest run && cd ..
```
Expected: backend 751 passed, frontend 582 passed. Record the counts — the no-regression baseline.

- [ ] **Step 5: Commit (worktree marker)**

```bash
git commit --allow-empty -m "chore: start V1.5.4.3 worktree (foundation hardening)"
```

---

## Phase 1 — Backend pack guardrail

### Task 1: PackContractError + fail-loud registration (a1, a4)

**Files:**
- Modify: `backend/workbench/engine/pack.py`
- Test: `tests/test_pack_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pack_contract.py
import pytest

from workbench.engine.pack import AnalysisPack, PackContractError, register_pack


def test_unwired_field_raises_with_planned_version():
    pack = AnalysisPack(pack_id="t_diag", diagnostics=["anything"])
    with pytest.raises(PackContractError) as exc:
        register_pack(pack)
    msg = str(exc.value)
    assert "diagnostics" in msg
    assert "V1.5.6" in msg  # the annotated planned version


@pytest.mark.parametrize("field", [
    "diagnostics", "report_blocks", "recommended_actions", "interpretation_restrictions",
])
def test_each_alarmed_field_raises(field):
    pack = AnalysisPack(pack_id=f"t_{field}", **{field: ["x"]})
    with pytest.raises(PackContractError):
        register_pack(pack)


def test_wired_fields_do_not_raise():
    # empty pack — wired fields default empty — must register cleanly
    register_pack(AnalysisPack(pack_id="t_empty"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pack_contract.py -v`
Expected: FAIL — `ImportError: cannot import name 'PackContractError'`.

- [ ] **Step 3: Implement in pack.py**

Add near the top of `backend/workbench/engine/pack.py` (after imports):

```python
class PackContractError(ValueError):
    """Raised when a pack declares a contribution the engine does not yet wire."""


# Fields declared on AnalysisPack but NOT yet consumed by the engine.
# Maps field -> planned wiring version (kept in code so the roadmap is
# self-documenting). register_pack refuses to register a pack that
# populates any of these — silent no-ops become loud errors.
_UNWIRED_FIELDS: dict[str, str] = {
    "diagnostics": "V1.5.6",
    "report_blocks": "V1.5.6",
    "recommended_actions": "when a pack needs it",
    "interpretation_restrictions": "V1.5.6",
}
```

Then rewrite `register_pack` (keep the existing model_handlers/defaults loops; add the guard FIRST):

```python
def register_pack(pack: AnalysisPack) -> None:
    """Register a pack's contributions. Wired: model_handlers, defaults_by_y_type,
    stages (explicit insertion, Task 2), rerun_actions (Task 3). Declaring a
    not-yet-wired field raises PackContractError (no silent no-ops)."""
    for field_name, planned in _UNWIRED_FIELDS.items():
        if getattr(pack, field_name):
            raise PackContractError(
                f"AnalysisPack.{field_name} is declared but not wired "
                f"(planned: {planned}). Remove it or wire it before registering "
                f"pack {pack.pack_id!r}."
            )
    for handler in pack.model_handlers:
        register_model(handler)
    for y_type, model_type in pack.defaults_by_y_type.items():
        set_default(y_type, model_type)
    REGISTERED_PACKS.append(pack)
```

Also update the `AnalysisPack` docstring/field comments so each alarmed field notes its planned version inline (a4), e.g. `recommended_actions: list[Any] = field(default_factory=list)  # NOT wired -> when a pack needs it`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pack_contract.py -v`
Expected: PASS (3 + parametrized).

- [ ] **Step 5: Golden no-drift + CORE_PACK still registers**

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_engine_pack.py -v`
Expected: PASS. CORE_PACK populates none of the alarmed fields, so it registers fine and behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/pack.py tests/test_pack_contract.py
git commit -m "feat(engine): fail-loud on unwired AnalysisPack fields"
```

---

### Task 2: `stages` explicit-insertion API (a2)

**Files:**
- Modify: `backend/workbench/engine/pack.py`
- Modify: `backend/workbench/engine/stages/__init__.py`
- Test: `tests/test_pack_stage_insertion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pack_stage_insertion.py
import pytest

from workbench.engine.pack import AnalysisPack, StageInsertion, PackContractError, register_pack
from workbench.engine.stages import PIPELINE


class _NoopStage:
    name = "noop_test"
    def run(self, ctx, env):
        return ctx


@pytest.fixture
def restore_pipeline():
    snapshot = list(PIPELINE)
    yield
    PIPELINE[:] = snapshot


def _names():
    return [s.name for s in PIPELINE]


def test_stage_spliced_after_anchor(restore_pipeline):
    register_pack(AnalysisPack(
        pack_id="t_stage",
        stages=[StageInsertion(stage=_NoopStage(), after="estimation")],
    ))
    names = _names()
    assert "noop_test" in names
    assert names.index("noop_test") == names.index("estimation") + 1


def test_bad_anchor_raises(restore_pipeline):
    with pytest.raises(PackContractError):
        register_pack(AnalysisPack(
            pack_id="t_bad",
            stages=[StageInsertion(stage=_NoopStage(), after="no_such_stage")],
        ))
    assert "noop_test" not in _names()  # nothing spliced on failure
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pack_stage_insertion.py -v`
Expected: FAIL — `cannot import name 'StageInsertion'`.

- [ ] **Step 3: Add StageInsertion + splice in pack.py**

In `backend/workbench/engine/pack.py`, add the dataclass (after `RErun`/near top-level dataclasses):

```python
@dataclass
class StageInsertion:
    """Declares a pipeline stage contribution and where it goes.
    `after` (or `before`) names an existing PIPELINE stage by `.name`."""
    stage: Any
    after: str | None = None
    before: str | None = None
```

In `register_pack`, after the model/defaults loops and before `REGISTERED_PACKS.append`, splice stages:

```python
    if pack.stages:
        from .stages import splice_stage
        for insertion in pack.stages:
            splice_stage(insertion)
```

> The splice helper lives in the stages module (which owns PIPELINE), keeping the import direction clean.

- [ ] **Step 4: Add splice_stage to stages/__init__.py**

In `backend/workbench/engine/stages/__init__.py`, after the `PIPELINE` list, add:

```python
def splice_stage(insertion) -> None:
    """Insert insertion.stage into PIPELINE relative to a named anchor.
    Raises PackContractError if the anchor is not present."""
    from ..pack import PackContractError
    names = [s.name for s in PIPELINE]
    anchor = insertion.after or insertion.before
    if anchor is None or anchor not in names:
        raise PackContractError(
            f"StageInsertion anchor {anchor!r} is not a PIPELINE stage. "
            f"Known stages: {names}"
        )
    idx = names.index(anchor)
    pos = idx + 1 if insertion.after else idx
    PIPELINE.insert(pos, insertion.stage)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pack_stage_insertion.py -v`
Expected: PASS (2). The `restore_pipeline` fixture prevents leakage.

- [ ] **Step 6: Golden no-drift (CORE_PACK adds no stages)**

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_engine_pack.py -q`
Expected: PASS, 0 drift.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/pack.py backend/workbench/engine/stages/__init__.py tests/test_pack_stage_insertion.py
git commit -m "feat(engine): explicit StageInsertion API splices packs into PIPELINE"
```

---

### Task 3: `rerun_actions` reference wiring (a3)

**Files:**
- Modify: `backend/workbench/engine/pack.py`
- Modify: `backend/workbench/engine/recommended_actions.py`
- Test: `tests/test_pack_rerun_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pack_rerun_actions.py
import pytest

from workbench.engine.pack import (
    AnalysisPack, RerunAction, register_pack, RERUN_ACTION_REGISTRY,
)
from workbench.engine.recommended_actions import actions_for_model_fit_failure


@pytest.fixture
def restore_rerun_registry():
    snapshot = list(RERUN_ACTION_REGISTRY)
    yield
    RERUN_ACTION_REGISTRY[:] = snapshot


def test_pack_rerun_action_reaches_failure_actions(restore_rerun_registry):
    register_pack(AnalysisPack(
        pack_id="t_rerun",
        rerun_actions=[RerunAction(
            key="rerun_robust", label="Re-run robust",
            param_overrides={"covariance": "robust"},
        )],
    ))
    actions = actions_for_model_fit_failure(
        requested_model_type="panel_ols", y_type="continuous",
    )
    keys = {a["key"] for a in actions}
    assert "rerun_robust" in keys
    action = next(a for a in actions if a["key"] == "rerun_robust")
    assert action["label"] == "Re-run robust"
    assert action["form_overrides"] == {"covariance": "robust"}


def test_empty_registry_leaves_actions_unchanged(restore_rerun_registry):
    RERUN_ACTION_REGISTRY[:] = []
    actions = actions_for_model_fit_failure(
        requested_model_type="panel_ols", y_type="continuous",
    )
    assert all("rerun_robust" != a["key"] for a in actions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pack_rerun_actions.py -v`
Expected: FAIL — `cannot import name 'RerunAction'`.

- [ ] **Step 3: Add RerunAction + registry + collection in pack.py**

In `backend/workbench/engine/pack.py`:

```python
@dataclass
class RerunAction:
    """A pack-declared one-click re-run option. param_overrides maps run-form
    fields to override values (mapped to the FailureCard form_overrides schema)."""
    key: str
    label: str
    param_overrides: dict = field(default_factory=dict)


RERUN_ACTION_REGISTRY: list[RerunAction] = []
```

In `register_pack`, after the stages splice and before `REGISTERED_PACKS.append`:

```python
    for rerun in pack.rerun_actions:
        RERUN_ACTION_REGISTRY.append(rerun)
```

- [ ] **Step 4: Consume the registry in recommended_actions.py**

In `backend/workbench/engine/recommended_actions.py`, add a mapper and append registered rerun_actions at the END of `actions_for_model_fit_failure` (just before its `return`):

```python
def _rerun_action_to_dict(ra) -> dict:
    return {
        "key": ra.key,
        "label": ra.label,
        "severity": "secondary",
        "form_overrides": dict(ra.param_overrides),
    }
```

At the end of `actions_for_model_fit_failure`, before returning the `actions` list:

```python
    from .pack import RERUN_ACTION_REGISTRY
    actions.extend(_rerun_action_to_dict(ra) for ra in RERUN_ACTION_REGISTRY)
    return actions
```

> When the registry is empty (the production default — CORE_PACK declares no rerun_actions), output is byte-identical to today → golden 0-drift. The socket is live and proven by the test pack; real packs get it for free.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pack_rerun_actions.py -v`
Expected: PASS (2).

- [ ] **Step 6: Reverse-check (G0-3) + golden no-drift**

Temporarily comment the `actions.extend(...)` line; run `tests/test_pack_rerun_actions.py` — `test_pack_rerun_action_reaches_failure_actions` MUST fail. Restore it.
Then run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_recommended_actions.py -q` — expect PASS, 0 drift (registry empty in prod).

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/pack.py backend/workbench/engine/recommended_actions.py tests/test_pack_rerun_actions.py
git commit -m "feat(engine): wire pack rerun_actions into failure recovery actions"
```

---

## Phase 2 — pytest footgun

### Task 4: Make bare `pytest` work (kill the sys.path footgun)

**Files:**
- Modify: `pyproject.toml`
- Test: manual (both invocations)

- [ ] **Step 1: Reproduce the footgun**

Run: `.venv/bin/pytest tests/test_engine_capabilities.py --co -q 2>&1 | tail -5`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'tests'` (bare pytest lacks repo root on sys.path).

- [ ] **Step 2: Fix pythonpath in pyproject.toml**

In `pyproject.toml` under `[tool.pytest.ini_options]`, change:

```toml
pythonpath = ["backend"]
```
to:
```toml
pythonpath = ["backend", "."]
```

> `tests/contracts/__init__.py` exists and `tests/` resolves as a namespace package, so adding the repo root makes `from tests.contracts... import ...` work under bare `pytest` too.

- [ ] **Step 3: Verify BOTH invocations collect + pass**

```bash
.venv/bin/pytest tests/test_engine_capabilities.py -q
.venv/bin/python -m pytest tests/test_engine_capabilities.py -q
```
Expected: both PASS (no collection errors).

- [ ] **Step 4: Full suite under bare pytest**

Run: `.venv/bin/pytest -q`
Expected: 751 + new pack tests passed, 0 errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "fix(test): put repo root on pythonpath so bare pytest works"
```

---

## Phase 3 — Frontend type gate

### Task 5: tsconfig + fix all type errors (b)

**Files:**
- Create: `frontend/tsconfig.json`
- Modify: `frontend/package.json`
- Modify: whatever source files `tsc` flags

- [ ] **Step 1: Add tsconfig.json**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "types": ["vitest/globals", "node"]
  },
  "include": ["src"]
}
```

- [ ] **Step 2: Add the typecheck script**

In `frontend/package.json` `"scripts"`, add:

```json
    "typecheck": "tsc --noEmit"
```

Ensure `typescript` is available: `cd frontend && npm ls typescript || npm install -D typescript`.

- [ ] **Step 3: Run tsc and capture the error list**

Run: `cd frontend && npx tsc --noEmit 2>&1 | tee /tmp/tsc-errors.txt; tail -30 /tmp/tsc-errors.txt`
Expected: either zero errors (done) or a list of `error TS####` lines.

- [ ] **Step 4: Fix every reported error, re-running until zero**

For each `error TSxxxx` in the output, open the cited `file:line` and fix the type issue at its source. Common fix patterns in this codebase:
- Missing/loose prop or state types → add the explicit type (mirror existing `interface`s in `api.ts`/`capabilities/types.ts`).
- `possibly undefined` on optional manifest fields (`prediction_models?` etc.) → guard with `?? []` / `?.` as existing components already do.
- Event handler param types → `React.ChangeEvent<HTMLInputElement|HTMLSelectElement>`.
- Test globals (`vi`, `describe`) → covered by `"types": ["vitest/globals"]`; if a test still errors, import from `vitest` explicitly.

Do NOT suppress with `// @ts-ignore` or loosen `strict`. Fix at the source. Re-run `npx tsc --noEmit` after each batch until it prints **zero errors**.

If the error count is very large, fix in file-sized batches and commit per batch (`fix(types): <file>`) so progress is bisectable — but the task is not done until `tsc --noEmit` is clean.

- [ ] **Step 5: Verify zero errors + tests still green**

```bash
cd frontend && npx tsc --noEmit && echo "TSC CLEAN"
cd frontend && npx vitest run
```
Expected: "TSC CLEAN" + 582 tests pass (type fixes must not change runtime behavior).

- [ ] **Step 6: Commit**

```bash
git add frontend/tsconfig.json frontend/package.json frontend/package-lock.json frontend/src
git commit -m "feat(frontend): add tsconfig + typecheck, fix all type errors (zero-error gate)"
```

---

## Phase 4 — Gate script

### Task 6: `scripts/gate.sh`

**Files:**
- Create: `scripts/gate.sh`

- [ ] **Step 1: Write the gate script**

Create `scripts/gate.sh`:

```bash
#!/usr/bin/env bash
# V1.5.4.3 one-command antifragility gate. Run from a version worktree root.
set -uo pipefail
fail=0
banner() { printf '\n========== %s ==========\n' "$1"; }

banner "BACKEND full suite (python -m pytest)"
.venv/bin/python -m pytest -q || fail=1

banner "GOLDEN / invariants / snapshot (0-drift)"
.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -q || fail=1

banner "FRONTEND tests (vitest)"
( cd frontend && npx vitest run ) || fail=1

banner "FRONTEND typecheck (tsc --noEmit)"
( cd frontend && npx tsc --noEmit ) || fail=1

if [ "$fail" -ne 0 ]; then
  printf '\n>>> GATE FAILED\n'; exit 1
fi
printf '\n>>> GATE PASSED\n'
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/gate.sh
```

- [ ] **Step 3: Run it — expect PASS**

Run: `./scripts/gate.sh`
Expected: all four banners, ends ">>> GATE PASSED", exit 0.

- [ ] **Step 4: Verify it fails fast on an injected failure**

Temporarily add `assert False` to a throwaway test, run `./scripts/gate.sh`, confirm it prints ">>> GATE FAILED" and exits 1. Remove the injected failure.

- [ ] **Step 5: Commit**

```bash
git add scripts/gate.sh
git commit -m "chore: add one-command antifragility gate script"
```

---

## Phase 5 — App.tsx run-form split

### Task 7: Extract `RunForm` from `App.tsx` (behavior-frozen, B)

**Files:**
- Create: `frontend/src/runForm/RunForm.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Study the seam**

Read `frontend/src/App.tsx`. The run-form lives in `SubmitRoute()` (starts ~line 80): the run-form `useState` block (lines ~86-123), the `onRun()` handler (~245), and the form JSX rendering `ModelTypeSelect`/`ImputationControls`/`PanelControls`/`PredictionControls` + the submit button (~454-596). `validatePanelPrediction` is module-scope (line 42) and must stay exported.

- [ ] **Step 2: Create RunForm.tsx and move the run-form body into it**

Create `frontend/src/runForm/RunForm.tsx` exporting `function RunForm(props: { projectRoot: string; onRan?: (r: RunResponse) => void })`. Move into it: the run-form state block, `onRun()`, the preview/file logic that belongs to running, and the form JSX. Keep `validatePanelPrediction` imported from `../App` (or move it to `runForm/validation.ts` and re-export from App to preserve its existing import path + tests — pick the lower-churn option; if moving, update `App.test.tsx` import). `SubmitRoute()` becomes a thin wrapper that renders `<RunForm projectRoot={...} />` plus whatever non-form chrome it had.

Do NOT change behavior, prop semantics, or the `runWorkflow(...)` call. The goal is relocation, not redesign.

- [ ] **Step 3: Typecheck catches relocation breakage**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors. Fix any import/type breaks from the move (this is exactly why the type gate landed first).

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all pass. If `App.test.tsx` referenced internals that moved, update imports WITHOUT weakening assertions. If a test asserted run-form behavior, it should still pass against the relocated component (behavior unchanged). `validatePanelPrediction` unit tests must remain intact.

- [ ] **Step 5: Confirm App.tsx shrank and RunForm is focused**

Run: `wc -l frontend/src/App.tsx frontend/src/runForm/RunForm.tsx`
Expected: App.tsx materially smaller; RunForm holds the run-form responsibility.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/runForm/RunForm.tsx frontend/src/App.test.tsx
git commit -m "refactor(frontend): extract RunForm from App.tsx (behavior-frozen)"
```

---

## Phase 6 — Final gate

### Task 8: Full gate + release notes

**Files:**
- Create: `docs/v1.5.4.3-release-notes.md`

- [ ] **Step 1: Run the gate script**

Run: `./scripts/gate.sh`
Expected: ">>> GATE PASSED". This is now the single source of truth for the version gate.

- [ ] **Step 2: Bare-pytest confirmation**

Run: `.venv/bin/pytest -q`
Expected: PASS, no collection errors (footgun gone).

- [ ] **Step 3: Write release notes**

Create `docs/v1.5.4.3-release-notes.md` summarizing: pack guardrail (fail-loud + StageInsertion + rerun_actions wired, reserved slots alarmed+annotated), frontend type gate (zero-error), App.tsx run-form split, gate script + pytest footgun fix. State the behavior-freeze guarantee (golden 0-drift; registry/PIPELINE unchanged in prod) and the deferred items (orchestrator split → V1.5.4.5, IV → V1.5.4.4).

- [ ] **Step 4: Commit + push branch**

```bash
git add docs/v1.5.4.3-release-notes.md
git commit -m "docs: V1.5.4.3 release notes"
git push -u origin workbench-v1.5.4.3
```

---

## Self-Review Notes

- **Spec coverage:** §4.1→Task1, §4.2→Task2, §4.3→Task3, §4.4→Task1 (annotations) + Task3 docstrings, §4.5(b)→Task5, §4.6(B)→Task7, §4.7→Task4 (footgun) + Task6 (gate). Testing §5 covered per-task + Task8.
- **Behavior-freeze:** every backend task has a golden 0-drift step; CORE_PACK populates no alarmed field, adds no stages, declares no rerun_actions → production output byte-identical. Task3 has the explicit G0-3 reverse-check.
- **Deferred honored:** no diagnostics/report_blocks/recommended_actions/interpretation_restrictions wiring; no orchestrator split; no IV.
- **Type consistency:** `PackContractError`, `StageInsertion(stage, after, before)`, `RerunAction(key, label, param_overrides)`, `RERUN_ACTION_REGISTRY`, `splice_stage`, `_rerun_action_to_dict` are defined once and referenced consistently. `param_overrides → form_overrides` mapping is fixed in `_rerun_action_to_dict`.
- **Known runtime-discovered content:** Task 5 Step 4 fixes are discovered by running `tsc` (can't enumerate ahead); the task gives the tsconfig, the process, concrete fix patterns, and a hard zero-error acceptance — not a placeholder.
