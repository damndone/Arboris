# V1.5.4.2 — GUI Gap Closure: Panel + Prediction (Design)

- **Date:** 2026-06-06
- **Status:** Approved (brainstorming) — pending spec review
- **Branch (to create):** `workbench-v1.5.4.2`
- **Worktree (to create):** `.worktrees/workbench-v1.5.4.2`
- **Base:** `main` head (includes shipped `v1.5.4.1`)
- **Theme:** Surface backend estimation capabilities that exist but are unreachable from the GUI (panel entity/time, prediction/ML, imbalanced sampling, panel covariance), display their results, and apply an iOS design language to the run form and result/history pages.

## 1. Problem & Motivation

V1.5.3.2 added substantial backend capability (explicit model_type routing, prediction/ML models, imbalanced sampling, extended diagnostics, MICE). V1.5.4.1 wired model-type selection + imputation to the GUI. A codebase audit (2026-06-06) found three families of backend capability still **stranded** — runnable only via `config.yml` / CLI, with no GUI entry point:

1. **Prediction / ML models** (`prediction_lasso`, `prediction_ridge`, `prediction_random_forest`) — driven only by `config.prediction_*`; `run_workflow` has no params for them; not in the capability manifest (`MODEL_UI_META`/`MODEL_UI_ORDER` list only the 9 regression model types); frontend renders **nothing** for prediction results (verified empty).
2. **Panel OLS entity/time columns** — `_fit_panel_ols` reads `ctx.artifacts["_id_candidates"]/["_time_candidates"]`, which are **auto-detected heuristics** set by `RoutingStage`. There is no `entity`/`time` parameter anywhere in `run_workflow` / API. The UI lets a user *select* Panel OLS but provides no way to specify the panel columns → broken UX.
3. **Imbalanced sampling** (`smote`/`oversample`/`undersample`, prediction-only) and **panel covariance** (`run_panel_ols(covariance=...)`) — backend supports them, no GUI surface.

This is the prerequisite gap-closure before the Agent Harness work (the agent would otherwise drive an operation surface it cannot fully reach). IV/2SLS is deliberately deferred to V1.5.4.3 because it is the only item requiring a new engine `CORE_PACK` registration (highest risk; isolated).

## 2. Goals / Non-Goals

**Goals:**
- Let users specify panel `entity`/`time` columns (either one suffices) from the GUI, end-to-end to `run_panel_ols`.
- Let users run prediction/ML models from the GUI (algorithm + cv_folds + sampling) and **see the results** (CV metrics / coefficients).
- Expose panel covariance choice (robust / cluster).
- Friendly client-side validation for the new inputs.
- Apply an iOS design language: full redesign of the run form; design-token application (rounded grouped cards, system fonts, system colors) to result/history pages **without restructuring their information**.
- All new backend params optional; omitting them reproduces current behavior (golden snapshots must not drift).

**Non-Goals (YAGNI):**
- IV/2SLS (→ V1.5.4.3).
- Multi-column entity, automatic-detection algorithm improvements.
- Information re-architecture of the result/history pages (tokens only).
- Agent Harness (deferred).

## 3. Scope (8 items)

| # | Item | Layer | Risk |
|---|------|-------|------|
| 1 | Panel entity/time selection | BE plumb + RoutingStage override + FE | low |
| 2 | Prediction runnable (algorithm / cv_folds) | BE config→request promotion + FE | med |
| 3 | Prediction result display panel (**required**) | FE renders `prediction_result` | med |
| 4 | iOS-style run form | FE | low |
| 5 | Imbalanced sampling option | BE (exists) + FE | low |
| 6 | Panel covariance option (robust/cluster) | BE covariance plumb + FE | low-med |
| 7 | Input validation & friendly errors | FE + BE structured failure | med |
| 8 | iOS token rollout to result/history pages | FE (styling only) | low |

## 4. Architecture & Injection Points

### 4.1 Backend parameter chain
Add optional params, defaulting to current behavior, across:
`API POST /runs` (FastAPI `Form` fields) → `run_workflow()` → `_run_workflow()`:
- `entity_col: str = ""`, `time_col: str = ""`
- `covariance: str = ""` (panel; `""` → current default `"robust"`)
- `prediction_model_type: str = ""`, `prediction_cv_folds: int = 0` (`0` → config/default), `prediction_sampling_method: str = ""`

All optional. **Omitting every new param must reproduce existing golden output byte-for-byte.**

### 4.2 Panel injection — `RoutingStage`
When `entity_col`/`time_col` are supplied, **override** `ctx.artifacts["_id_candidates"]`/`["_time_candidates"]` (single-element list of the user's choice, normalized against the cleaned frame) instead of the auto-detected candidates. When empty, keep existing auto-detection. Downstream (`estimation` pre-check and `_fit_panel_ols`) is unchanged — it already reads `[0]` of these lists.

### 4.3 Prediction injection — request-over-config
`diagnostics.py` already does `requested or (config if enabled)`. Extend so the prediction model type / cv_folds / sampling come from the **request first, config as fallback**. No behavior change when request params are empty and config disabled.

### 4.4 Capability manifest — `build_capabilities()`
Extend the manifest (delivers V1.5.4.1's capability-driven pattern) with:
- `prediction_models`: `[{key, label, description}]` for lasso/ridge/random_forest
- `sampling_methods`: `[{key, label}]` for smote/oversample/undersample
- panel `covariance_options`: `[{key, label}]` for robust/cluster
- minimal param schema (e.g. cv_folds range) so the frontend renders controls dynamically

### 4.5 Frontend components
- `runForm/PanelControls.tsx` — entity/time side-by-side + covariance, iOS grouped-card styling; shown when model = panel_ols.
- `runForm/PredictionControls.tsx` — toggle + algorithm segmented control + cv_folds stepper + sampling select.
- `runResult` → new `PredictionResultCard` — renders the `prediction_result` artifact (CV metrics, coefficients). Presence detected from the loaded artifacts list (same pattern as `ImputationSummary` in V1.5.4.1).
- iOS design tokens lifted into `styles.css` (CSS variables: radius, grouped-card surfaces, system colors `#007AFF`/`#34C759`, `-apple-system` font stack); run form fully restyled; result/history pages adopt tokens without information restructure.
- Validation: selecting Panel with both entity/time empty **and** data not classified panel; entity == time; prediction toggled on but no algorithm — surfaced as inline client-side messages, not backend errors.

### 4.6 Design language (iOS)
Approved mockup: `.superpowers/brainstorm/.../panel-ios.html`. Settings-style inset grouped cards, row-based label/value with disclosure chevrons, segmented controls, switches, steppers. Result/history pages: tokens only (rounded cards, fonts, colors) — no layout re-architecture.

## 5. Testing Strategy

**Backend:**
- Golden no-drift: running without any new param reproduces the 7 existing goldens.
- New golden: panel run with user-supplied entity/time override.
- e2e: prediction via `POST /runs` request params → `prediction_result` artifact present.
- Unit: covariance plumb, sampling validation (prediction-only guard already exists), request-over-config precedence.
- Structured failure: illegal combos (entity == time, sampling on non-prediction) return structured `failed`, not crashes.

**Frontend:**
- Unit: `PanelControls`, `PredictionControls`, `PredictionResultCard`.
- Capability manifest new fields render dynamically.
- Validation logic unit tests.

## 6. Version Discipline

- Branch `workbench-v1.5.4.2`, worktree `.worktrees/workbench-v1.5.4.2`, base = `main` head.
- Per-worktree venv (`~/.local/bin/python3.11 -m venv .venv`, install `-e ".[dev,panel,ml,imbalanced,imputation]"`).
- Gates before ship: full BE suite (full extras), FE `npx vitest run`, 7 goldens 0-drift, CLI smoke.
- This is a sizeable version; the implementation plan will be **phased** (BE plumb → manifest → FE controls → results render → iOS tokens → validation), each phase independently green.

## 7. Roadmap Context

- **V1.5.4.2** (this) — Panel + Prediction GUI gap + iOS design.
- **V1.5.4.3** — IV/2SLS (requires engine `CORE_PACK` registration; isolated for risk).
- **Later** — Agent Harness (BYO API key), editable/partial rerun, feature packs.
