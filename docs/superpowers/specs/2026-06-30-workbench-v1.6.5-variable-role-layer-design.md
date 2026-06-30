# Workbench v1.6.5 — Variable Role Layer (Research-Design Semantics in Lineage)

- **Status:** Design approved (brainstorming), pending spec review → writing-plans
- **Date:** 2026-06-30
- **Worktree:** `.worktrees/workbench-v1.6.5`, branch `codex/workbench-v1.6.5` (off `codex/workbench-v1.6.4` @ `ddf58c9`)
- **Predecessor:** v1.6.4 Pipeline Draft MVP (draft create → edit params → validate → execute → child run → compare)

---

## 1. Problem & Root Cause

In the lineage graph today, a run's variables and its model are recorded as **siblings hanging off `Cleaned data`**, with no edges between them and no role information:

```
Raw → Cleaned ──(parent_stage_id, no edge)──┬─ y (cleaned)
                                            ├─ x1 (cleaned)
                                            └─ model:ols_1   ── render_report → report
```

This is **wrong as research design**. Econometric logic is:

```
research question → theory/DAG → define Outcome Y / Focal X / Covariates Z → model spec → estimate → interpret
```

Variables are **upstream inputs that play roles in the model specification**, not co-equal byproducts of the cleaned dataset. The current graph is a *data-artifact* lineage; it does not express *research-design* semantics.

**Root cause (verified in code):** the model spec stores only a flat `y` and a flat comma-separated `x` (`api.py` `x_columns = form["x"].split(",")`). The system has **no concept of variable role** — which regressor is focal vs. control — so `recording.py` can only record `var:{y}:cleaned` and `var:{x}:cleaned` as cleaned-data children. For causal/panel estimators the identifying columns (treatment, instruments, entity, time, exposure, cluster) are pulled from separate form fields and are **not recorded as nodes at all** — they are invisible in lineage.

**This is not a rendering bug to be patched in the frontend.** The fix is to make variable role a first-class, persisted part of the spec, derive roles per estimator family, and record role-bearing variable nodes that flow into the model.

### Estimation invariance (key guardrail)

Roles are **interpretive metadata**. Focal vs. covariate both enter the regression RHS identically; the role only changes which coefficient the analyst focuses on. The columns passed to every estimator runner are **unchanged**. Therefore:

> **Coefficient / estimation-result goldens MUST stay 0-drift across all families.** Only the lineage *graph* goldens regenerate (new role nodes + edges). A coefficient drift means the change leaked into the math and is a bug.

---

## 2. Scope

### In scope (v1.6.5)

The root fix covers **every estimator that produces a lineage model node**, audited from `engine/stages/estimation.py`:

- **Regression family:** `ols`, `logit`, `probit`, `poisson` / `poisson_rate`, `negative_binomial`, `glm:binomial|poisson|negative_binomial`
- **Panel:** `panel_ols` (FE/RE)
- **IV:** `iv_2sls`
- **DID family:** `did`, `cs_did`, `sa_did`, `dcdh`

Plus the v1.6.4 product issues that ride on the same surfaces:
- Problem 6 — distinguish same-named model nodes across the forest (run id + node hash + source/rerun badge).
- Node detail drawer carries the reproducible spec.

### Out of scope (explicitly deferred)

- **Statistical-tests family** (Pearson/Spearman/Kendall correlation, Welch t-test, Mann-Whitney U, Kruskal-Wallis, ANOVA, chi-square): audited in `statistical_tests.py`. These **do not call `record_*`** — they are not lineage graph nodes — and they **already use role-correct names** (symmetric `left`/`right`; `outcome`/`group`). No X/Y bug. No change. (Promoting tests into the graph is a separate future feature.)
- **Functional-form / transformation layer** (`log(y)`, `x²`, interactions): needs new capture + parsing. Future version.
- **Research-question / causal-DAG layer** (confounder/mediator/collider analysis, backdoor criterion): the largest research-design layer. Future version. v1.6.5 stops at *roles*, which is self-consistent.
- The v1.6.4 draft/pipeline UI polish items (Pipeline tab MVP entry, Draft Graph return/layout) are **not** part of this spec except where the draft editor must host role declaration (§7).

---

## 3. Role Vocabulary (frozen)

```
Outcome                 Y — the dependent variable
Focal                   the variable(s) of interest (see per-family source below)
Covariates              Z — other regressors entering the RHS
Instruments             IV instruments
Unit                    panel / DID entity dimension
Time                    panel / DID time dimension
Exposure                Poisson-rate exposure / offset
Cluster                 clustering variable for standard errors (inference design)
Explanatory_unspecified regression-family regressors when no focal_x was declared
```

### Two kinds of variable → model edge

A role is either a **substantive input** to the model or a **structural/inference dimension** that configures the estimator. The graph edge distinguishes them so Cluster/Unit/Time are never misread as RHS covariates:

| Edge op | Roles | Rendering |
|---|---|---|
| `enters_as_{role}` | Outcome, Focal, Covariates, Instruments, Exposure, Explanatory_unspecified | solid edge into model |
| `configures_{role}` | Unit, Time, Cluster | dashed edge into model (structural / inference design) |

`Focal` source differs by family — it is **user-declared only for the regression/panel family**; for IV and DID it is **structural** (endogenous / treatment) and not user-overridable via `focal_x`.

---

## 4. Per-Family Role Derivation (grounded in `estimation.py`)

A single pure function `derive_roles(spec) -> RoleMap` produces `{column: role}` per run, dispatching on estimator family. Sources below are the exact artifacts each handler reads.

### 4.1 Regression: ols / logit / probit / negative_binomial / glm
`_fit_ols/_fit_logit/_fit_probit/_fit_negative_binomial/_fit_glm` → `y=_normalized_y, x=_normalized_x`.
```
Outcome     = _normalized_y
Focal       = focal_x            (⊆ _normalized_x, user-declared)
Covariates  = _normalized_x − focal_x
if focal_x is empty:
    Explanatory_unspecified = _normalized_x   (no forced X/Z split)
```

### 4.2 Poisson rate
`_fit_poisson` → `x=_poisson_x` where `_poisson_x = _normalized_x − exposure_col`; `exposure_col=ctx.exposure_col`.
```
Outcome     = _normalized_y
Focal       = focal_x ∩ _poisson_x        (if declared)
Covariates  = _poisson_x − focal_x
Exposure    = exposure_col                 (independent role — NOT a covariate)
```

### 4.3 Panel FE/RE
`_fit_panel_ols` → `x=_normalized_x, entity=id_cands[0], time=t_cands[0]`.
```
Outcome     = _normalized_y
Focal       = focal_x
Covariates  = _normalized_x − focal_x
Unit        = id_cands[0]       (configures_)
Time        = t_cands[0]        (configures_)
```

### 4.4 IV / 2SLS
`_fit_iv_2sls` → `exog=_normalized_x, endog=_iv_endog, instruments=_iv_instruments`.
**Invariant (enforced by `validate_iv_spec`, `iv_spec.py`):** `{exog, endog, instruments}` is a strict partition; no column appears in two buckets and none equals `y`. `derive_roles` relies on this.
```
Outcome                = _normalized_y
Focal (= Endogenous)   = _iv_endog          (structural focal, NOT focal_x)
Instruments            = _iv_instruments
Covariates (exogenous) = _normalized_x
```

### 4.5 Classic DID
`_fit_did` → `normalize_did_input(mode, entity, time, y, cohort, treat, post, status)`, then `run_did(y, x=_normalized_x, entity, time)`.
```
Outcome     = norm.y
Treatment   = mode-dependent columns:        (Focal role, source = Treatment design)
                mode=cohort → _did_cohort_col
                else        → _did_treat_col / _did_post_col / _did_status_col
Unit        = entity   (configures_)
Time        = time     (configures_)
Covariates  = _normalized_x
```
The Treatment group may hold **multiple columns** (e.g. treat + post) — the role group is not single-column.

### 4.6 CS-DID / SA-DID
`_fit_cs_did` (`covariates=_normalized_x`) / `_fit_sa_did` (**no covariates passed**); both `normalize_did_input(...)`, `cluster_var=_cs_cluster_var`.
```
CS-DID: Outcome + Treatment(cohort) + Unit + Time + Covariates(_normalized_x) + Cluster(_cs_cluster_var)
SA-DID: Outcome + Treatment(cohort) + Unit + Time + Cluster(_cs_cluster_var)        (no Covariates)
```

### 4.7 dCDH
`_fit_dcdh` → `normalize_treatment_path(entity, time, y, treatment=_dcdh_treatment_col)`, `run_dcdh(norm, cluster_var=_cs_cluster_var)`. **No covariates.**
```
Outcome   = norm.y
Treatment = _dcdh_treatment_col       (switching path, structural focal)
Unit      = entity   (configures_)
Time      = time     (configures_)
Cluster   = _cs_cluster_var (optional inference role)
(no Covariates)
```

### Frozen per-family summary
```
Regression : Outcome + Focal? + Covariates  | or Explanatory_unspecified
Poisson    : Outcome + Focal? + Covariates + Exposure
Panel      : Outcome + Focal? + Covariates + Unit + Time
IV/2SLS    : Outcome + Endogenous(Focal) + Instruments + Exogenous Covariates
DID        : Outcome + Treatment + Unit + Time + Covariates
CS-DID     : Outcome + Treatment + Unit + Time + Covariates + Cluster
SA-DID     : Outcome + Treatment + Unit + Time + Cluster
dCDH       : Outcome + Treatment + Unit + Time + Cluster
```

---

## 5. Data Model & Persistence

- New **optional** spec field `focal_x` (comma-separated, same style/parse as `x`). Subset of `x`. Empty ⇒ unspecified.
- Validation (regression/panel only): `focal_x ⊆ x`, `focal_x ∌ y`, de-duplicated. IV/DID ignore `focal_x` (focal is structural).
- `x` (the full RHS) is **unchanged** → estimation identical.
- Persisted in `run_inputs.json` `form` and in `manifest.json` (next to `y`/`x`). Flows through the rerun/draft path so a child run carries edited roles.
- All other role sources (`_iv_endog`, `_did_treat_col`, `exposure_col`, `_cs_cluster_var`, entity/time candidates, …) already persist; `derive_roles` reads them — no new capture for causal roles beyond `focal_x`.

---

## 6. Lineage Recording (`engine/stages/recording.py`)

The single recording path gains role awareness. Behavior with the role layer:

1. `derive_roles(spec)` computes `{column: role}` for the run.
2. For **every** role column (including the previously-invisible Unit / Time / Treatment / Instruments / Exposure / Cluster), record a variable node carrying `role` and keep `Cleaned → var` provenance (op `select_column`).
3. Record `var → model` edges with op `enters_as_{role}` (substantive) or `configures_{role}` (structural/inference).
4. **Dropped variables** (`var:*:dropped`) carry their role and render inside the matching role group, flagged `dropped` (a dropped Focal/Treatment is highlighted — it threatens identification).
5. **Unspecified fallback:** when `focal_x` is empty for a regression-family run, regressors get role `Explanatory_unspecified` and the model node is tagged `roles: unspecified`. No fake focal/covariate split.
6. Model node summary stays **estimation identity only** (`OLS · HC1 · n=36`); the reproducible spec (`y ~ x…`, `se_type`, `estimator`, per-variable roles) lives in the node detail drawer.

**Golden impact:** graph goldens across all in-scope families regenerate (new nodes + edges). Estimation-result goldens stay 0-drift (§1 guardrail).

---

## 7. Declaration UX

- **Submit form:** after picking `y` and `x`, the user marks which `x` are **Focal** (multi-select; ≥1 allowed). Unmarked ⇒ `Explanatory_unspecified`. Zero change to existing fields. IV/DID forms keep their existing endog/treatment fields — those drive Focal structurally.
- **Draft editor** (`ModelNodeInspector`, built in v1.6.4): extend the PATCH params surface to edit `focal_x`, so a rerun can re-assign the focal/covariate split (research-design iteration on an existing model node).
- **Node detail drawer:** reproducible spec block (formula + se_type + estimator + role list).

---

## 8. Frontend Rendering

- **Generic role-group rendering** driven by the role vocabulary — not hardcoded per estimator. Groups in canonical order: Outcome → Focal → Covariates → Instruments → Exposure, then structural/inference (Unit, Time, Cluster) drawn with dashed `configures_` edges.
- **Unspecified fallback:** single "Explanatory variables (role unspecified)" group + model `roles: unspecified` tag.
- **Dropped-in-role:** dropped variable shown inside its role group, marked dropped.
- **Problem 6 badge:** across the forest, same-named model nodes carry `run short-id · node_hash short · source|rerun`. FE-only; data already in the forest model.

---

## 9. Testing

- **Backend unit:** `derive_roles` per family (table-driven over §4); `focal_x` validation; empty→unspecified; exposure excluded from covariates; IV partition invariant; DID multi-column treatment; SA/dCDH no-covariates.
- **Recording:** role + `enters_as_`/`configures_` edges emitted; dropped-in-role; previously-invisible columns now recorded.
- **Golden:** **regenerate graph goldens** for all in-scope families; **assert estimation-result goldens unchanged** (the estimation-invariance guardrail) — this is the headline test.
- **Frontend:** generic role grouping; unspecified fallback; dropped-in-role; badge; draft-editor focal edit.
- **Gate:** `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` — backend / golden / frontend / typecheck all green, run inside the worktree.

---

## 10. Process & Constraints

- New worktree `.worktrees/workbench-v1.6.5`, branch `codex/workbench-v1.6.5` (already created off `ddf58c9`).
- Do **not** push / merge / tag without explicit authorization. Do **not** touch `.worktrees/workbench-v1.6.3` or `…-v1.6.4`. Do **not** commit `frontend/node_modules`.
- Three-level review per change: Implementer → Test & QA → Reviewer, then commit.
- After ship, ask before cleaning dev caches.

---

## 11. Open Questions

None blocking. Functional-form and research-question/DAG layers are explicitly deferred (§2). Cluster as an optional inference role is included and rendered distinctly (§3, §6).
