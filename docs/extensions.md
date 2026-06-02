# Workbench Engine Extension Contract (V1.5.4)

## 1. Overview

V1.5.4 decomposed the monolithic `_run_workflow` into a thin pipeline driver
plus an explicit `Stage` sequence. The point of that decomposition is to make
the engine **extensible by addition, not by editing**: third-party or
future-feature packs (Panel / DID / RDD / TimeSeries / ML) can register new
models, new defaults, and new stages without touching `_run_workflow` and
without modifying the core stage set. The kernel itself uses the same
mechanism — the built-in OLS / logit / poisson / probit / GLM / panel_ols /
negative_binomial handlers are registered through `CORE_PACK`, which goes
through `register_pack` exactly like an external pack would.

All engine code lives at `backend/workbench/engine/`:

- `engine/context.py` — `DataHandle`, `ModelingContext`, `RunEnv`
- `engine/registry.py` — `ModelHandler`, `MODEL_REGISTRY`, `resolve`
- `engine/pack.py` — `AnalysisPack`, `register_pack`, `REGISTERED_PACKS`
- `engine/stages/__init__.py` — `Stage` Protocol and the ordered `PIPELINE`
- `engine/stages/*.py` — the 16 stage implementations
- The driver is `backend/workbench/orchestrator.py::_run_workflow` (53 lines).

## 2. Core abstractions

### `DataHandle`

`engine/context.py`. Frozen dataclass binding a `pandas.DataFrame` to its
provenance identity:

- `frame: pd.DataFrame`
- `artifact_id: str` — the lineage id callers must use when writing
  artifacts derived from this frame.
- `provenance: tuple[str, ...]` — the lineage chain of raw inputs.
- `schema_fingerprint`, `row_count`, `column_count` — optional metadata.
- `classmethod DataHandle.of(frame, *, artifact_id, provenance)` — builds
  a handle and fills in `row_count` / `column_count` for you.

The handle exists so that "fit on frame A, record artifact B" cannot be
expressed by accident: models, diagnostics, reports, and lineage all read
the frame and the `artifact_id` from the same object.

### `ModelingContext`

`engine/context.py`. Mutable cross-stage state — the things that used to be
loose locals inside `_run_workflow`:

- `data: DataHandle`
- `y_col: str`, `x_cols: list[str]`
- `requested_model_type: str | None` — the V1.5.3.2 explicit-routing field;
  `"auto"` or `None` means "let the engine resolve from `y_type`".
- `y_type: str | None`, `primary_type: str | None`
- `exposure_col: str | None`, `roles: dict | None`
- `diagnostics: list | None`
- `artifacts: dict[str, Any]` — the shared scratch space stages use to pass
  intermediate state (`_normalized_y`, `_normalized_x`, `_categorical_vars`,
  `_input_files`, `_model_results`, ...). Underscore-prefixed keys are
  internal to the pipeline; treat them as private.
- `terminal_status: str | None` — when a stage sets this to `"blocked"` or
  `"failed"`, the driver short-circuits and returns immediately.

`ctx.with_data(handle)` returns a new context with a swapped `DataHandle`,
preserving everything else. Used after cleaning / imputation to swap in the
processed frame while keeping the old one available in `ctx.artifacts` for
post-imputation stages.

### `RunEnv`

`engine/context.py`. Run-time side-effect dependencies — kept OUT of
`ModelingContext` so the context stays pure-constructible in unit tests:

- `run_root: Path` — the run's working directory.
- `run_id: str`
- `recorder: Any` — the `GraphRecorder` that captures lineage events.
- `on_step: Callable[[str, str, str], None] | None` — optional step callback.
- `env.step(name, state, message)` — convenience that forwards to `on_step`
  when set. Stages use this to emit progress events.

### `Stage` (Protocol) and `PIPELINE`

`engine/stages/__init__.py`. A stage is anything matching:

```python
class Stage(Protocol):
    name: str
    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext: ...
```

The ordered execution sequence is the module-level `PIPELINE: list[Stage]`.
In V1.5.4 it has 16 entries:

```
SourceStage, CleaningStage, ProfileStage, ValidationStage, RoutingStage,
YTypeStage, PreEstimationChecksStage, RoleInferenceStage,
ExposureDetectionStage, StatisticalTestsStage, ImputationStage,
EstimationStage, RecordingStage, DiagnosticsStage, ReliabilityStage,
ReportStage
```

The driver iterates `PIPELINE`, passing the context forward and stopping as
soon as any stage sets `ctx.terminal_status in ("blocked", "failed")`.

### `ModelHandler`

`engine/registry.py`. One handler runs one model:

- `model_type: str` — the registry key (`"ols"`, `"logit"`, `"glm"`, ...).
- `model_id: str` — the default written `model_id` for this handler
  (`"ols_1"`, `"logit_1"`, ...).
- `serves_y_types: tuple[str, ...]` — the y-type families this handler is
  valid for. Informational in V1.5.4; used by future router rules.
- `fit: HandlerFn` — callable `(ctx, env) -> (model_id, primary, fitted)`.
  Each handler is responsible for pulling its own kwargs out of `ctx` (e.g.
  `panel_ols` reads `ctx.artifacts["_id_candidates"]` and
  `_time_candidates`; `poisson` reads `ctx.exposure_col` and
  `_poisson_x`).

`MODEL_REGISTRY: dict[str, ModelHandler]` and
`DEFAULT_BY_Y_TYPE: dict[str, str]` are the two registries the engine reads
from at resolve time.

### `AnalysisPack`

`engine/pack.py`. The single declarative container packs use to ship their
contributions:

- `pack_id: str`
- **Wired in V1.5.4:**
  - `model_handlers: list[ModelHandler]`
  - `defaults_by_y_type: dict[str, str]`
  - `stages: list[Stage]` (importing module is responsible for appending
    these into `PIPELINE` — see §3)
- **Declared-only** (slots reserved for V1.5.6+ / agent; the V1.5.4 engine
  reads but does not act on these):
  - `diagnostics: list[DiagnosticRule]` (the existing orchestrator `_check_*`
    helpers remain — V1.5.4 does NOT build a `DiagnosticRule` engine)
  - `report_blocks`
  - `recommended_actions`
  - `interpretation_restrictions`
  - `rerun_actions`

## 3. The `register_pack(pack)` mechanism

`engine/pack.py::register_pack` does exactly three things:

1. For each `ModelHandler` in `pack.model_handlers`, call
   `register_model(handler)` — i.e. write into `MODEL_REGISTRY`.
2. For each `(y_type, model_type)` in `pack.defaults_by_y_type`, call
   `set_default(y_type, model_type)` — i.e. write into `DEFAULT_BY_Y_TYPE`.
3. Append the pack to `REGISTERED_PACKS` for auditing.

**`register_pack` does NOT touch `PIPELINE` on your behalf.** Stage
insertion is the importing module's responsibility, on purpose: where a new
stage sits in the pipeline is meaningful (before vs after profiling, before
vs after estimation), so it stays explicit. Append directly:

```python
from workbench.engine.stages import PIPELINE
PIPELINE.append(MyNewStage())
```

…or splice into a specific position when ordering matters.

`REGISTERED_PACKS: list[AnalysisPack]` is the audit trail of everything
registered, in registration order. `CORE_PACK` (the kernel) is the first
entry.

## 4. Stage authoring contract

A stage has the signature:

```python
class MyStage:
    name = "my_stage"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        ...
        return ctx
```

Where state lives:

- **Read inputs** from `ctx` (typed fields like `ctx.data`, `ctx.y_col`,
  `ctx.x_cols`, `ctx.y_type`, `ctx.exposure_col`) and from `ctx.artifacts`
  (the cross-stage scratch dict).
- **Write side-effecting state** through `env`:
  - `env.run_root` — files go under this directory.
  - `env.recorder` — lineage events.
  - `env.step(name, state, message)` — progress callback.
- **Update context** by mutating `ctx` (and/or returning a `ctx.with_data(...)`
  variant when swapping the frame).

### The lineage invariant

**Any artifact a stage writes MUST use `inputs=[ctx.data.artifact_id]` (or
another `artifact_id` obtained from a stage-stashed `DataHandle`, never a
hardcoded literal).** This is the property that keeps the lineage graph
honest: the recorded lineage of every artifact resolves back to whichever
`DataHandle` was current when the stage ran. See `CleaningStage` and
`EstimationStage` for canonical examples (e.g. `EstimationStage` builds
`model_input_ids = [ctx.data.artifact_id]` and passes that as `inputs=` to
`_write_model_result`).

### Reusing orchestrator helpers

Many of the V1.5.3 helpers (`_write_model_result`, `_write_manifest`,
`_lineage`, `_safe_flush_recorder`, `_model_failure_details`, the `_check_*`
diagnostics) still live in `backend/workbench/orchestrator.py`. To use them
from inside a stage without producing a circular import at module load,
use the lazy import pattern:

```python
def run(self, ctx, env):
    from ...orchestrator import _write_model_result, _write_manifest
    ...
```

This is the pattern `EstimationStage` and the other extracted stages already
use. It is the supported way to share orchestrator helpers.

## 5. Resolve semantics & the V1.5.3.2 explicit-routing contract

`engine/registry.py::resolve(ctx)` implements V1.5.3.2's contract verbatim:

- If `ctx.requested_model_type` is set and not `"auto"`, **explicit wins**.
  The key is the requested string (so `"ols"`, `"logit"`, `"poisson"`,
  `"panel_ols"`, `"glm"`, ...) with one carve-out: `"glm:<family>"` collapses
  to the `"glm"` key, and the family travels through `ctx.artifacts["_glm_family"]`.
- If the explicit key is not in `MODEL_REGISTRY`, `resolve` raises
  `KeyError`. The caller (`EstimationStage`) lets this propagate; the
  outer `_run_workflow` handler surfaces it as a structured `failed`
  status. **There is NO silent fallback to OLS for explicit failures.**
- If `ctx.requested_model_type` is `None` or `"auto"`, `resolve` returns
  `MODEL_REGISTRY[DEFAULT_BY_Y_TYPE[ctx.y_type]]`.

### `_PREDICTION_PASSTHROUGH` carve-out

`engine/stages/estimation.py` defines:

```python
_PREDICTION_PASSTHROUGH = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}
```

These legacy model_types are *primary-estimated* via the y_type default
(typically OLS for continuous), and the actual prediction model is run later
as a supplementary step inside `DiagnosticsStage` (sklearn-backed). Before
calling `resolve`, `EstimationStage` masks these to `"auto"`:

```python
if model_type in _PREDICTION_PASSTHROUGH:
    from dataclasses import replace
    resolve_ctx = replace(ctx, requested_model_type="auto")
handler = resolve(resolve_ctx)
```

This reproduces the original if/elif fall-through behavior exactly. **To
add a new model_type that should similarly fall through to the y_type
default for primary estimation, add it to `_PREDICTION_PASSTHROUGH`.**

## 6. What is wired in V1.5.4 vs declared-only

| Item                                  | Status                           | Where                                              |
| ------------------------------------- | -------------------------------- | -------------------------------------------------- |
| `Stage` Protocol + `PIPELINE`         | **Wired**                        | `engine/stages/__init__.py`                        |
| `ModelHandler` + `MODEL_REGISTRY`     | **Wired**                        | `engine/registry.py`                               |
| `resolve(ctx)`                        | **Wired**                        | `engine/registry.py`                               |
| `DEFAULT_BY_Y_TYPE`                   | **Wired**                        | `engine/registry.py`                               |
| `AnalysisPack.model_handlers`         | **Wired** (via `register_pack`)  | `engine/pack.py`                                   |
| `AnalysisPack.defaults_by_y_type`     | **Wired** (via `register_pack`)  | `engine/pack.py`                                   |
| `AnalysisPack.stages`                 | **Wired** — importing module appends to `PIPELINE` | `engine/pack.py`         |
| `CORE_PACK` dogfooding the registry   | **Wired**                        | `engine/stages/estimation.py`                      |
| `AnalysisPack.diagnostics`            | **Declared-only** — existing `_check_*` helpers remain; no `DiagnosticRule` engine in V1.5.4 | `engine/pack.py` |
| `AnalysisPack.report_blocks`          | **Declared-only** (V1.5.6+)      | `engine/pack.py`                                   |
| `AnalysisPack.recommended_actions`    | **Declared-only** (V1.5.6+)      | `engine/pack.py`                                   |
| `AnalysisPack.interpretation_restrictions` | **Declared-only** (V1.5.6+) | `engine/pack.py`                                   |
| `AnalysisPack.rerun_actions`          | **Declared-only** (V1.5.6+)      | `engine/pack.py`                                   |

## 7. Worked example: registering a `ridge` model handler

```python
from workbench.engine.context import ModelingContext, RunEnv
from workbench.engine.pack import AnalysisPack, register_pack
from workbench.engine.registry import ModelHandler
from workbench.econometrics.runner import run_ols  # or your own ridge runner


def _fit_ridge(ctx: ModelingContext, env: RunEnv):
    # Adapter: return (model_id, primary_result_dict, primary_fitted_or_None).
    # Build kwargs from ctx; do not read globals.
    primary, fitted = run_ols(   # placeholder — replace with your ridge runner
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        robust=True,
        model_id="ridge_1",
        categorical_x=ctx.artifacts.get("_categorical_vars"),
    )
    return "ridge_1", primary, fitted


RIDGE_PACK = AnalysisPack(
    pack_id="ridge",
    model_handlers=[
        ModelHandler(
            model_type="ridge",
            model_id="ridge_1",
            serves_y_types=("continuous",),
            fit=_fit_ridge,
        ),
    ],
    # If you want ridge to be the AUTO default for continuous y, override:
    # defaults_by_y_type={"continuous": "ridge"},
)
register_pack(RIDGE_PACK)
```

After import, `MODEL_REGISTRY["ridge"]` resolves to `_fit_ridge`. A run
launched with `requested_model_type="ridge"` will route to it directly
through `EstimationStage` — **`_run_workflow` is never edited**. This
property is exercised by
`tests/test_engine_registry.py::test_register_model_extends_registry_without_touching_orchestrator`,
which adds a new model via `register_model` only and asserts the resulting
run completes successfully.

## 8. Boundaries

V1.5.4 deliberately does NOT implement dynamic plugin loading,
entry-points-based discovery, or any form of sandboxed pack execution.
Registration is **import-time, in-process**: a pack module is imported, its
top level calls `register_pack(...)`, and the engine sees its
contributions. Packs are trusted code that runs in the same Python process
as the kernel — review them with the same care you'd review a direct edit
of `engine/`. Dynamic / discovery / sandbox concerns are explicitly out of
scope for V1.5.4 and reserved for later work.
