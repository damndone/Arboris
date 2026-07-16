# DID Layer 1 — Classic DID Full Kit (Design Spec)

**Date:** 2026-06-13
**Version target:** next version (own branch + own worktree per the version-isolation rule)
**Theme:** First vertical-depth causal-inference feature pack — classic Difference-in-Differences, full kit, built end-to-end on the proven IV/2SLS template, golden 0-drift (all new params inert when empty).

---

## 1. Goal & Scope

Add a `did` model type that delivers the **classic DID full kit** in one coherent version:

1. **ATT** (average treatment effect on the treated) via TWFE — two-way fixed effects, the coefficient on the current-treatment-status indicator `D_it`. Reuses the existing `run_panel_ols` PanelOLS machinery (EntityEffects + TimeEffects), so the estimator is nearly free.
2. **Event study** (dynamic DID) — a coefficient path indexed by event-time `= t − first_treatment_period`, with leads (pre) and lags (post), reference period normalized to −1. Backend emits the coefficient table; frontend draws the line.
3. **Parallel-trends test** — joint F-test that the pre-period (lead) event-study coefficients are zero.
4. **Goodman-Bacon decomposition** — decomposes the TWFE estimate into its component 2×2 DiD comparisons with their variance weights, surfacing the weight on "forbidden" (later-treated-vs-earlier-as-control) comparisons. Self-implemented (no offline Python library exists), validated against published reference values.

**Explicitly OUT of scope (later layers):** Callaway-Sant'Anna group-time ATT (Layer 2, the `differences` package), Sun-Abraham IW estimator, de Chaisemartin-D'Haultfœuille, honest-DID / Rambachan-Roth sensitivity (Layer 3). Staggered adoption is **mechanically supported** by the TWFE/event-study/Bacon code, but when staggered we attach an `interpretation_restriction` warning pointing the user to Layer 2.

**Non-negotiable constraints:** zero new runtime dependencies; golden 0-drift (a run that does not request `did` is byte-identical); the `did` model type is **explicit-only** (never auto-selected by `resolve()`), exactly like `iv_2sls`.

---

## 2. Core Architectural Decision — Canonical Cohort Representation

The single most important design choice, and the foundation for Layers 2/3.

**Decision:** All user input forms normalize to **one canonical cohort table** before any estimation. Downstream code (ATT / event-study / parallel-trends / Goodman-Bacon) consumes only this table.

Canonical columns produced by the normalizer: `entity`, `time`, `y`, plus derived `_did_cohort` (first treatment period per entity; sentinel for never-treated), `_did_D` (0/1 current treatment status = `time >= cohort`), `_did_event_time` (`time − cohort`, undefined for never-treated).

Three accepted input modes, all funneled through one normalizer:

| Mode | User supplies | Maps to cohort by |
|------|---------------|-------------------|
| **cohort** (primary) | `entity`, `time`, `first_treat` column (never-treated = blank/0) | identity |
| **two_by_two** (degenerate) | `treat` (time-invariant group), `post` (period) | cohort = earliest `time` where `post==1` for treated units; never for control |
| **status** (D_it) | `entity`, `time`, `D_it` (0/1) | cohort = earliest `time` where `D_it==1`; requires absorbing (monotonic non-decreasing) treatment, else fail-loud |

**Why this is the foundation:** Layer 2 (Callaway-Sant'Anna) and Layer 3 (Sun-Abraham, dCDH) all operate on cohort / group-time structure. Building the canonical cohort table now means those layers reuse it instead of re-deriving treatment timing. Adding a future input form = one more adapter branch, downstream untouched.

---

## 3. Backend Components

Mirrors the IV/2SLS file topology exactly.

### 3.1 `engine/did_spec.py` (mirror of `iv_spec.py`)

- `class DIDSpecError(ValueError)` — carries a `DID_*`-prefixed message so the estimation failure path surfaces it as a structured `MODEL_FIT_FAILED` (same mechanism as `IVSpecError`).
- `validate_did_spec(...)` — order/partition checks: requires ≥2 distinct time periods; requires at least one treated unit AND at least one comparison group (never-treated OR not-yet-treated); role columns (entity/time/cohort/treat/post/status) are disjoint and none equals `y`; for `status` mode, treatment must be absorbing (monotonic non-decreasing within each entity) → `DID_NON_ABSORBING` otherwise.
- `normalize_did_input(frame, mode, *, entity, time, y, cohort=None, treat=None, post=None, status=None) -> NormalizedDID` — returns the canonical cohort table + a small spec summary dict (`n_treated_units`, `n_never_treated`, `staggered: bool`, resolved role column names). Pure function, no I/O.

### 3.2 `econometrics/runner.py` — two estimation helpers (mirror `run_iv_2sls`)

- `run_did(frame, y, x, entity, time, model_id, covariance="robust") -> (primary, fitted)` — the **ATT fit**. Builds a PanelOLS two-way-FE formula `y ~ 1 + D_it + x... + EntityEffects + TimeEffects`, reusing the same `_linearmodels_term` / `_normalize_linearmodels_result` helpers `run_panel_ols` uses. The coefficient on `D_it` is the ATT. `x` = additional covariates (controls), excluding all role columns.
- `run_event_study(frame, y, x, entity, time, event_time_col, ref_period, covariance="robust") -> dict` — the **dynamic spec**. Regresses `y` on event-time dummies (one per event_time except the reference period −1) under two-way FE; returns the coefficient/SE/CI path keyed by event_time. The pre-period (lead) coefficients feed the parallel-trends F-test.

These live in `runner.py` because they are estimators. Both gate `linearmodels` via the existing `require_optional_dependency(..., extra="panel")`.

### 3.3 `engine/goodman_bacon.py` (NEW pure module — the risk center, isolated)

- `goodman_bacon_decompose(frame, y, entity, time, cohort) -> dict` — pure, deterministic, NumPy/pandas only. Enumerates all 2×2 DiD comparisons among timing groups (treated-vs-never-treated, earlier-vs-later [good], later-vs-earlier [forbidden/bad]), computes each comparison's 2×2 DiD estimate and its variance-based weight; the weighted average equals the TWFE ATT (this identity is a correctness assertion in tests). Returns `components[]` (type/weight/estimate), `weighted_avg`, `forbidden_weight`.
- **No hard verdict threshold.** Reports the forbidden-comparison weight as a number; the "TWFE may be biased" judgment is delivered as an `interpretation_restriction` string, not a pass/fail boolean — there is no field-wide consensus threshold and we will not invent one.
- Isolated in its own module precisely because it is the only self-implemented estimator; it gets the heaviest unit-test coverage (see §6).

### 3.4 `engine/did_diagnostics.py` (mirror of `iv_diagnostics.py`)

- `build_did_diagnostics(fitted, normalized_did, frame, *, covariance) -> dict` — orchestrates the diagnostic bundle into one JSON-safe dict:
  - `att` — pulled from the fitted ATT result (`estimate`, `std_error`, `pvalue`, `ci`, `spec="twfe"`, `covariance`).
  - `event_study` — calls `run_event_study`; emits `event_time[]`, `coef[]`, `se[]`, `ci_lower[]`, `ci_upper[]`, `ref_period=-1`.
  - `parallel_trends` — joint F-test (`statistic`, `pvalue`, `n_pre_leads`, `verdict ∈ {not_rejected, rejected}`, `message`) on the lead coefficients from the event-study fit. The verdict here IS a test outcome (objective), unlike Bacon.
  - `goodman_bacon` — calls `goodman_bacon_decompose`; includes `components[]`, `weighted_avg`, `forbidden_weight`, and a `message`.
  - `spec` — the normalizer's summary (`entity`, `time`, `cohort`, `n_treated_units`, `n_never_treated`, `staggered`).
  - When `staggered == true`: append an `interpretation_restriction` pointing to Layer 2.
  - All numeric values are plain Python floats (JSON-serializable), same discipline as `build_iv_diagnostics`.

### 3.5 `engine/stages/estimation.py` — `_fit_did` adapter + CORE_PACK

- `_fit_did(ctx, env)` — mirror of `_fit_iv_2sls`: pulls `_did_*` artifacts, calls `validate_did_spec` + `normalize_did_input`, stores the normalized cohort table into `ctx.artifacts["_did_normalized"]` (so DiagnosticsStage reuses it), calls `_orch().run_did(...)`, returns `("did_1", primary, fitted)` — **MUST return fitted** (diagnostics needs it).
- Register `ModelHandler("did", "did_1", ("continuous",), _fit_did)` in `CORE_PACK.model_handlers`. **NOT** added to `defaults_by_y_type` → explicit-only.
- **Optional** rerun action `RerunAction(key="did_switch_to_panel_ols", label="Switch to plain Panel FE", param_overrides={"model_type": "panel_ols"}, applies_to=["did"])` — surfaces on DID fit failure. (Decide during planning; low-risk, follows the `iv_switch_to_ols` precedent.)

### 3.6 `engine/stages/diagnostics.py` — write the `did_diagnostics` artifact

Add a branch mirroring the `iv_2sls` one (diagnostics.py:105): `if model_type == "did":` → fetch the fitted ATT + `ctx.artifacts["_did_normalized"]`, call `build_did_diagnostics`, write `run_root / "did_diagnostics.json"`, register the `did_diagnostics` artifact.

### 3.7 `orchestrator/_model_types.py`

Add `"did": "continuous"` to `_MODEL_TYPE_MAP` (so the validation gate accepts it and routes `y` as continuous). Add a `_MODEL_METADATA` entry if the IV one set a precedent (model id / engine label).

### 3.8 `orchestrator/__init__.py` (`run_workflow` / `_run_workflow`)

Thread new params (mirror the `iv_endog` threading at __init__.py:172/209/396): `did_mode`, `did_cohort_col`, `did_treat_col`, `did_post_col`, `did_status_col`. Each normalized via `normalize_column_name` and written to `ctx.artifacts["_did_mode"]`, `ctx.artifacts["_did_cohort"]`, etc. Reuse the existing `entity_col` / `time_col` params for entity/time (already threaded → RoutingStage → `_id_candidates`/`_time_candidates`). All default empty → inert.

### 3.9 `api.py`

Add Form fields (mirror `iv_endog` at api.py:101): `did_mode: str = Form("")`, `did_cohort_col`, `did_treat_col`, `did_post_col`, `did_status_col`. Thread through `_bg_run` → `run_workflow`. (Cohort/treat/post/status are single column names → plain strings, no JSON array parsing needed, unlike IV's lists.)

### 3.10 `engine/capabilities.py`

Add a `"did"` entry: `label: "DID"`, `group: "DID"`, `requires: ["panel", "treatment_timing"]` (informational, drives the frontend role UI). Bump nothing else; the capabilities manifest is additive. Apply the standard 4-way sync (backend key / drift-guard / FE type / contract schema+sample) per antifragility gate G0-5.

---

## 4. Frontend Components

Mirrors `IVControls.tsx` + `IVDiagnosticsCard.tsx`.

### 4.1 `frontend/src/runForm/DIDControls.tsx`

Role-assignment UI with an input-mode selector (cohort / two_by_two / status):
- **cohort mode** (default): assign entity, time, and a `first_treat` column.
- **two_by_two mode**: assign `treat` (group) and `post` (period) columns.
- **status mode**: assign entity, time, and a `D_it` status column.
Live validity hint (e.g., "needs ≥2 periods, ≥1 treated + ≥1 comparison group"), same spirit as IV's identification badge. Covariates (`x`) are the remaining selected columns, excluding all role columns — `RunForm` posts `x` minus the DID role columns, exactly as IV posts `x = exog`.

`RunForm` posts `model_type="did"`, `entity_col`, `time_col`, and the new `did_*` fields via the existing `RunExtraParams` mechanism.

### 4.2 `frontend/src/runResult/DIDDiagnosticsCard.tsx`

**Tiered / progressive-disclosure card** (per the agreed UX principle — core data retained, no redundancy, full data on demand):
- **Collapsed (default):** ATT headline number (estimate, SE, p, 95% CI); event-study line chart (drawn in-component from the coefficient table — leads left of the dashed treatment line, lags right, CI bars); parallel-trends verdict pill; Goodman-Bacon verdict pill + forbidden weight + weighted average.
- **Expanded (on "展开完整数据"):** full per-period event-study table (event_time / coef / SE / CI); full Goodman-Bacon 2×2 component table (type / weight / estimate + weighted-average row); spec summary; the `interpretation_restriction` warning when staggered.
- **Raw layer:** the `did_diagnostics` artifact is fetchable via the existing artifacts panel + `fetchArtifactJson` (no new mechanism).

Event-study chart is drawn client-side from the numeric table (SVG/existing chart util) — **no backend image, no new dependency**, keeping the artifact reproducible and golden-able.

---

## 5. Data Flow (end to end)

```
DIDControls (mode + role cols)  →  RunForm POST /runs (model_type=did, entity_col,
  time_col, did_mode, did_cohort_col/…, x=covariates)
    →  api._bg_run  →  run_workflow / _run_workflow  (threads did_* → ctx.artifacts["_did_*"])
      →  RoutingStage  (entity_col/time_col → _id_candidates/_time_candidates)
        →  EstimationStage._fit_did:
             validate_did_spec → normalize_did_input → ctx.artifacts["_did_normalized"]
             → run_did (ATT, PanelOLS two-way FE)  → returns fitted
        →  DiagnosticsStage  (model_type=="did"):
             build_did_diagnostics(fitted, _did_normalized, frame)
               ├─ run_event_study           (dynamic path)
               ├─ parallel-trends joint F    (on lead coefs)
               └─ goodman_bacon_decompose    (pure decomposition)
             → write did_diagnostics.json + register artifact
  →  RunDetail loads artifacts  →  DIDDiagnosticsCard renders (tiered)
```

---

## 6. Testing & Golden Strategy

**Golden (additive, 0-drift discipline):**
- New `tests/golden/did.json` — a small **staggered-adoption** example (e.g., 3 cohorts + never-treated, ~4 periods) captured via the existing `_capture` harness in `test_engine_golden.py`. Captures the ATT model result + the `did_diagnostics` artifact. Additive only; existing 8 goldens untouched.
- New `tests/golden/` case may also include a **2×2 degenerate** run to pin the `two_by_two` → cohort normalization path.

**Goodman-Bacon correctness (the risk center — dedicated unit tests):**
- A small synthetic dataset where the 2×2 component estimates and variance weights are **hand-derivable**; assert each component + weights + that `weighted_avg == TWFE ATT` to tolerance.
- A cross-check against **published reference values** (Goodman-Bacon 2021 / R `bacondecomp` on a standard dataset such as `castle` or the divorce panel) — pin the decomposition table to documented numbers.

**Spec validation tests** (`did_spec`): non-absorbing status → `DID_NON_ABSORBING`; <2 periods; no comparison group; role/y overlap. Each rides the `except ValueError` → `MODEL_FIT_FAILED` path (assert structured failure, not exception escape).

**Event-study / parallel-trends:** a dataset with a deliberately violated pre-trend → parallel_trends `verdict == "rejected"`; a clean dataset → `not_rejected`. Assert event_time keys, ref_period=−1 normalization, lead/lag counts.

**Wiring tests (G0-3 "go red if wiring deleted"):** monkeypatch-spy on `orch.run_did` asserting real kwargs (entity/time/x), mirroring the panel_ols covariance-spy lesson; assert `_fit_did` returns the fitted object so DiagnosticsStage can build the bundle.

**Frontend (vitest + tsc):** DIDControls mode-switch + role partition; DIDDiagnosticsCard collapsed/expanded render + event-study chart from a fixture table; `tsc --noEmit` zero errors.

**Full gate:** `./scripts/gate.sh` (BE full + golden 0-drift + vitest + tsc). Example dataset `examples/datasets/did_staggered_adoption.csv` (3 cohorts + never-treated, ~4 periods) + `docs/did-howto.md`.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Goodman-Bacon self-implementation correctness | Isolated pure module; hand-derived + published-reference golden; assert weighted-avg == TWFE identity. |
| Event-study collinearity / dropped periods (unbalanced panels, gaps) | Reference period explicit (−1); drop-and-report absent event-times; covered by an unbalanced-panel test. |
| Staggered TWFE bias misleading users | `interpretation_restriction` when staggered; Bacon forbidden-weight surfaced; pointer to Layer 2. |
| Golden drift from new params | All `did_*` params default empty/inert; `did` explicit-only (not in `defaults_by_y_type`); additive goldens only. |
| Scope creep into Layer 2 estimators | Hard scope line in §1; `differences` package deliberately not added this version. |

---

## 8. Touch List (IV/2SLS template parity)

**New files:** `engine/did_spec.py`, `engine/goodman_bacon.py`, `engine/did_diagnostics.py`, `frontend/src/runForm/DIDControls.tsx`, `frontend/src/runResult/DIDDiagnosticsCard.tsx`, `tests/golden/did.json`, `tests/test_did_spec.py`, `tests/test_goodman_bacon.py`, `tests/test_did_diagnostics.py`, `examples/datasets/did_staggered_adoption.csv`, `docs/did-howto.md`.
**Edited files:** `econometrics/runner.py` (`run_did`, `run_event_study`), `engine/stages/estimation.py` (`_fit_did` + CORE_PACK handler [+ optional rerun action]), `engine/stages/diagnostics.py` (did branch), `orchestrator/_model_types.py` (`_MODEL_TYPE_MAP`), `orchestrator/__init__.py` (param threading), `api.py` (Form fields), `engine/capabilities.py` (did entry + 4-way sync), `frontend/src/runForm/RunForm.tsx` (post did params), `tests/test_engine_golden.py` (additive did golden), contract schema+sample (capabilities bump).

**Cleanup ride-along (low-risk, optional):** delete the stranded `run_fixed_effects` in `runner.py` (superseded by `run_panel_ols` EntityEffects, never called) — confirm zero callers first.
