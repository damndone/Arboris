# DID Layer 2 — Callaway-Sant'Anna Group-Time ATT (Design Spec)

**Date:** 2026-06-15
**Version target:** V1.5.6 (own branch `workbench-v1.5.6` + own worktree `.worktrees/workbench-v1.5.6` per the version-isolation rule)
**Theme:** Second vertical-depth causal-inference layer — the Callaway-Sant'Anna (2021) heterogeneity-robust DID estimator (group-time ATT), self-implemented and validated element-wise against R `did` / `DRDID`, built end-to-end on the proven IV/2SLS + DID-Layer-1 template, golden 0-drift (all new params inert when empty).

---

## 1. Goal & Scope

Add a `cs_did` model type delivering the Callaway-Sant'Anna estimator as one coherent version:

1. **Group-time ATT** `ATT(g,t)` for every treatment cohort `g` × calendar period `t`, using only *clean* comparison units (never-treated, or not-yet-treated) — never already-treated units as controls. This is what eliminates the staggered-adoption (forbidden-comparison) bias that Layer 1's Goodman-Bacon decomposition only *quantifies*.
2. **Three estimands** `dr` / `ipw` / `reg` (doubly-robust Sant'Anna-Zhao / inverse-probability-weighting Abadie / outcome-regression), with optional pre-treatment covariates `X` (conditional parallel trends). Empty `X` ⟹ all three collapse to the clean 2×2 mean-difference.
3. **Four aggregations** of `ATT(g,t)`: `overall` (simple), `dynamic` (event-study), `group` (per-cohort), `calendar` (per-period), with cohort-size weights.
4. **Inference**: cluster-robust analytical SEs + a **multiplier (wild) bootstrap** giving pointwise CIs and **simultaneous (sup-t) uniform confidence bands** per aggregation. Seeded RNG ⟹ deterministic ⟹ golden-safe.

**Core extensibility decision:** the estimator slot outputs a standardized `EffectEstimateBundle`, NOT a bare `ATT(g,t)` array. Aggregation and inference depend only on the bundle. See §2.

**Explicitly OUT of scope (deferred — recorded so scope does not creep):**

| Deferred item | Reason | When |
|---|---|---|
| Sun-Abraham IW, de Chaisemartin-D'Haultfœuille, honest-DID / Rambachan-Roth sensitivity | Different estimands/weights/identifiable samples; the bundle contract is *likely* reusable but must be re-verified against each before claiming so | Layer 3 |
| Sparse / chunked / out-of-core influence-function storage | Local single-user workbench; DID `K = #(g,t)` is realistically tens; cluster-row IF storage already removes the main memory pressure | A dedicated profiler-driven performance version, only if a real large-panel use case appears. Until then a `CS_PROBLEM_TOO_LARGE` guard rejects oversized `G×K`. |
| Two-way clustering | R `did` default is one-way; this is an extension | Later layer |
| Time-varying covariates | Risk of post-treatment contamination; needs extra identification argument | Later layer |
| Covariate trimming / propensity trimming | Default = none, to match the R oracle; trimming changes the estimand | Later layer (must be recorded in `cell_metadata` when added) |

**Non-negotiable constraints:** zero new runtime dependencies (NumPy + SciPy + statsmodels + pandas already present); golden 0-drift (a run that does not request `cs_did` is byte-identical); `cs_did` is **explicit-only** (in `MODEL_REGISTRY`, never in `defaults_by_y_type`, never auto-selected by `resolve()`), exactly like `did` and `iv_2sls`; every failure raises a `CS_*`- or `DID_*`-prefixed `ValueError` (caught → structured `MODEL_FIT_FAILED`), never a bare `KeyError`/`TypeError` (which would escape as `WORKFLOW_FAILED`) — the v1.5.5.1 convention.

---

## 2. Core Architectural Decision — the `EffectEstimateBundle` contract

The single most important design choice and the foundation for Layer 3. The estimator slot does **not** emit a bare `ATT(g,t)` array — `ATT(g,t)` is CS's natural object but is **not** a universal interface across heterogeneity-robust estimators (Sun-Abraham, dCDH have different estimands, weight structures, and identifiable samples). Emitting a bare array would let the aggregation layer silently assume all estimators estimate the same thing.

**Decision:** the estimator slot (`cs_attgt.py`) emits a standardized bundle. Aggregation and inference depend ONLY on the bundle, never on a specific CS internal.

```
EffectEstimateBundle
├── estimates:         float array, shape (K,)            # one per effect cell
├── influence_func:    float array, shape (G, K)          # G = independent sampling
│                                                          #   units (clusters; default
│                                                          #   = entity), NOT observation
│                                                          #   rows. mean-zero columns.
├── cluster_ids:       array, shape (G,)                  # row labels of influence_func
├── cell_metadata:     list of K records, each:
│       { g, t, event_time,                               #   = t - g
│         estimand_type,                                  #   "att_gt"
│         control_group_rule,                             #   "never" | "not_yet"
│         reference_period,                               #   = g - 1 - anticipation
│         n_treated, n_control,                           #   in the cell sub-sample
│         valid: bool, warning: str|None }                #   support / overlap flags
├── weights:           per-cell weight inputs (cohort size n_g, group share p̂_g)
├── vcov_config:       { cluster_var, cluster_level,      #   how IF rows were formed
│                        confidence_level, band_type }    #   "pointwise" | "uniform"
└── diagnostics:       { overlap, common_support, omitted_cells, ... }
```

**Why now, not speculation:** every one of these fields is needed by a *correct CS implementation itself* — the cell metadata, valid mask, cluster-row IF, cohort-size weights, and overlap diagnostics are CS's own honest output. We are not pre-fitting SA/dCDH's unknown needs; we are refusing to throw away information CS already produces. Layer 3 will *likely* reuse this contract, and must re-verify it suffices before doing so (the diagram label is "接入契约时复核", not "只换插槽").

**did_spec stays thin (§4.1):** the canonical cohort table (`_did_cohort`/`_did_D`/`_did_event_time`) is *descriptive and estimator-agnostic* — it is reused from Layer 1 unchanged. The estimator-specific sample-construction rules (control-group rule, reference period, anticipation, balance) are NOT data facts; they belong to the estimator, which applies them and records the *actually-applied* rule into `cell_metadata` + a top-level `sample_spec`. This keeps did_spec reusable and makes every cell self-describing and reproducible.

---

## 3. Scientific Core (the math, nailed)

Notation: units `i = 1..n`, periods `t = 1..T`, outcome `Y_it`, pre-treatment time-invariant covariates `X_i`. `G_i` = first period unit `i` is treated (cohort); never-treated ⟹ `G_i = ∞`. Treatment is absorbing / no reversal (Layer 1's `status` mode enforces `DID_NON_ABSORBING`). `δ` = anticipation (default 0).

**Anticipation anchors (used everywhere; never bare `g`):**
```
effective_treatment_start = g - δ
reference_period(g)       = g - 1 - δ
```

### 3.1 Target estimand

```
ATT(g,t) = E[ Y_t(g) - Y_t(0) | G = g ]
```
the ATT for cohort `g` at calendar time `t`. Estimated for post periods (real effect) and pre periods (`t < effective_treatment_start`, placebo / event-study leads).

### 3.2 Base period (forms the long difference ΔY = Y_t − Y_base_t)

```
if t >= effective_treatment_start:          # post
    base_t = reference_period(g) = g - 1 - δ
elif base_period == "universal":            # pre, fixed
    base_t = reference_period(g) = g - 1 - δ
elif base_period == "varying":              # pre, sequential  (DEFAULT, matches R)
    base_t = t - 1
```
Invariant: under `universal`, `ATT(g, reference_period(g)) = 0` exactly. Default `varying` (matches R `did`). Exact pre-period index conventions match the `did` package and are pinned by fixtures.

### 3.3 Comparison group (per cell, explicit)

```
comparison_safe_until = max(t, base_t)

never-treated:    C_i(g,t) = 1{ G_i = ∞ }
not-yet-treated:  C_i(g,t) = 1{ G_i = ∞  OR  G_i > comparison_safe_until + δ }
```
Plain statement: a comparison unit must begin treatment at least `δ` periods *after* the latest relevant outcome period of the cell; never-treated always qualifies; already-treated (`G_i <= comparison_safe_until + δ` and finite) is always excluded. Tests assert: `δ=0` ⟹ boundary is `G_i > max(t, base_t)`; `δ>0` ⟹ `G_i > max(t, base_t) + δ`. The actually-applied rule is recorded in `cell_metadata.control_group_rule`.

### 3.4 The three estimands

Cell sub-sample `S(g,t) = {i: G_i = g} ∪ {i: C_i(g,t) = 1}`. Let `Gg = 1{G_i = g}`, `ΔY = Y_t − Y_base_t`. **All expectations `E[·]` below are empirical means over `S(g,t)`, NOT the full sample.** Two nuisances are fit **per cell**:
- propensity `p_g(X) = P(Gg=1 | i ∈ S(g,t), X)` — logit on `S(g,t)`;
- outcome regression `m_{g,t}(X) = E[ΔY | C=1, X]` — OLS on the comparison units of `S(g,t)`.

```
w1 = Gg / mean_S(Gg)
w0 = [ p_g(X)·C/(1−p_g(X)) ] / mean_S[ p_g(X)·C/(1−p_g(X)) ]

dr  :  ATT = mean_S[ (w1 − w0)·(ΔY − m_{g,t}(X)) ]          # Sant'Anna-Zhao DR
ipw :  ATT = mean_S[ (w1 − w0)·ΔY ]                          # m ≡ 0  (Abadie)
reg :  ATT = mean_S[ w1·(ΔY − m_{g,t}(X)) ]                  # p constant
        (intuition: ATT_reg = E[ ΔY − m_{g,t}(X) | G=g ])
```
Implementation MUST write `reg` as `mean(w1·(ΔY − m(X)))`; it MUST NOT be written as `E[w1·ΔY] − E[w0·m]`, and `m(X)` MUST NOT be averaged over the comparison group. Empty-`X` collapse: `p_g`, `m` become constants ⟹ all three equal `mean_S[ΔY | Gg=1] − mean_S[ΔY | C=1]` (clean 2×2).

### 3.5 Influence function — operational definition (NO hand-derived formula)

The IF is the error-prone center, so the spec gives an **operational** definition, not an algebraic one:

> The per-cell influence function is defined operationally as the `DRDID` closed-form influence function returned by the corresponding panel estimator (`DRDID::drdid_panel` / `ipwdid_panel` / `reg_did_panel`) under the same nuisance fits, the same normalization convention, the same weight-normalization correction, the same nuisance-score correction, and the same sample restriction `S(g,t)`.

Implementation requirements (binding):
- The implementation MUST reproduce the `DRDID` panel IF algebra. It MUST NOT substitute a self-derived simplified IF.
- All normalization, nuisance-score correction, and weight-normalization correction terms are taken as whatever makes the result match the `DRDID` fixture element-wise (tol 1e-8).
- Observation-level IF contributions for units **outside** `S(g,t)` are **zero** before cluster aggregation (keeps the `G × K` matrix aligned across cells).
- After computing observation-level IF, **aggregate to cluster rows** (default cluster = entity): `influence_func` has `G` rows, one per independent sampling unit, mean-zero columns.

### 3.6 Aggregations (cohort-size weights, valid-cell-masked denominators)

`n_g` = number of units with `G_i = g` in sample (constant across cells). Eligibility of a cohort to enter an aggregate is decided by `valid_cell_mask`; the weight magnitude uses the constant `n_g`.

```
group:    θ_group(g) = mean over valid post cells { (g,t): t >= effective_treatment_start }

overall:  groups with ≥1 valid post cell; weight_g ∝ n_g
          θ_overall = Σ_g weight_g · θ_group(g)

dynamic:  for event time e:   G_e = { g : cell (g, g+e) is valid }
          weight_g(e) = n_g / Σ_{h∈G_e} n_h
          θ_dyn(e)    = Σ_{g∈G_e} weight_g(e) · ATT(g, g+e)

calendar: for period t:        G_t = { g : g <= t AND cell (g,t) is valid }
          weight_g(t) = n_g / Σ_{h∈G_t} n_h
          θ_cal(t)    = Σ_{g∈G_t} weight_g(t) · ATT(g,t)
```
Denominators are over **valid** cells only — a cohort whose `(g, g+e)` cell is masked (no clean comparison, no support) does not enter the `e` numerator *or* denominator.

**Aggregation IF must include the weight-estimation term** (the cohort shares `p̂_g` are themselves estimated):
```
ψ^θ_i = Σ_k w_k · ψ^k_i  +  Σ_k ATT_k · (influence function of ŵ_k)_i
```
Omitting the second term understates aggregate SEs. Validated against R `aggte`.

### 3.7 Inference — analytical SE + multiplier bootstrap sup-t bands (seeded)

Cluster-level IF matrix `Ψ` (`G × K`, `K` = the components of one aggregation, e.g. all event times). Analytical SE (no small-sample correction by default — added only if the R oracle adds it):
```
V̂_k = G^{-2} · Σ_{c=1}^G Ψ_{ck}^2          # equivalently  mean_c(Ψ_{ck}^2) / G
se_k = sqrt(V̂_k)
```
Multiplier (wild) bootstrap (primary, matches R `did` default `bstrap=TRUE`):
```
for b in 1..B           # B = 1000 default; fixed RNG seed → bit-identical → golden 0-drift
    draw V_c^(b) iid mean-0 var-1 (Mammen 2-point), independent of data
    R_k^(b) = (1/G) Σ_c V_c^(b) · Ψ_{ck}
Σ̂_k = (q_.75 − q_.25) / (z_.75 − z_.25)  of { R_k^(b) }      # robust IQR scale (CS)
pointwise:  θ̂_k ± z_{1−α/2} · Σ̂_k
uniform:    ĉ = quantile_{1−α} ( max_k |R_k^(b)| / Σ̂_k );   θ̂_k ± ĉ · Σ̂_k
```
The sup-t critical value `ĉ` is computed **within each aggregation** over that aggregation's joint components (e.g. simultaneous over all event-time coefficients), NOT across all estimands at once. `vcov_config` records cluster var/level, confidence level, and band type; the artifact reports them.

---

## 4. Backend Components (mirrors IV/2SLS + DID-Layer-1 file topology)

### 4.1 `engine/did_spec.py` — REUSED UNCHANGED
The canonical cohort normalizer from Layer 1 (`normalize_did_input` → `NormalizedDID` with `_did_cohort`/`_did_D`/`_did_event_time`). CS consumes the cohort table directly. **No edits.**

### 4.2 `engine/cs_attgt.py` (NEW — the estimator slot, the only Layer-3-swappable piece)
- `class CSSpecError(ValueError)` — `CS_*`-prefixed messages.
- `estimate_att_gt(norm, *, control_group, est_method, base_period, anticipation, covariates, cluster_var) -> EffectEstimateBundle`. Builds each cell sub-sample `S(g,t)`, applies §3.3 comparison rule, forms ΔY per §3.2, fits per-cell `p_g`/`m_{g,t}` (statsmodels logit/OLS; constant when `X` empty), computes `ATT(g,t)` per §3.4, computes the `DRDID`-equivalent IF per §3.5, aggregates IF to cluster rows, records `cell_metadata` + `sample_spec`, sets `valid`/`warning` flags (empty treated or control cell → `valid=False`, never silently 0; overlap failure → warning, no drop). Raises `CS_NO_VALID_CELLS` if every cell is invalid; `CS_PROBLEM_TOO_LARGE` if `G×K` exceeds the guard threshold.
- `@dataclass EffectEstimateBundle` per §2.

### 4.3 `engine/cs_aggregate.py` (NEW — estimator-agnostic)
- `aggregate(bundle, kind) -> dict` for `kind ∈ {overall, dynamic, group, calendar}`, per §3.6, propagating the aggregation IF (including the weight-estimation term). Returns estimates + component-level cluster IF for the inference layer. Pure function over the bundle.

### 4.4 `engine/cs_inference.py` (NEW — estimator-agnostic)
- `multiplier_bootstrap(if_matrix, *, B, alpha, seed) -> {se, pointwise_ci, uniform_band, crit_value}` per §3.7. Seeded `numpy.random.default_rng(seed)`. Pure function over a cluster-IF matrix.

### 4.5 `econometrics/runner.py` — `run_cs_did(...)`
Orchestrates: `normalize_did_input` → `estimate_att_gt` → `cs_aggregate` (4 kinds) → `cs_inference` (per aggregation). Returns the structured `cs_did` result (point ATT(g,t) table + 4 aggregations with bands + diagnostics + warnings). Mirrors `run_iv_2sls` / `run_did` placement. No new optional-dependency gate (uses already-present libs).

### 4.6 `engine/stages/estimation.py` — `_fit_cs_did` adapter + CORE_PACK
`_fit_cs_did` adapter registered in CORE_PACK `model_handlers` (explicit-only; in `MODEL_REGISTRY`, NOT in `defaults_by_y_type`). `RerunAction(key="cs_did_switch_to_did", param_overrides={"model_type":"did"}, applies_to=["cs_did"])` → "fall back to Layer 1 TWFE" on failure.

### 4.7 `engine/stages/diagnostics.py` — write the `cs_did` artifact
Writes the `cs_did` artifact, wrapped in `except Exception` → degraded `{available: false, error}` so a diagnostics crash never fails an already-fit run (v1.5.5.1 convention). Red-if-deleted spy test.

### 4.8 `orchestrator/_model_types.py`
`_MODEL_TYPE_MAP["cs_did"] = "continuous"` + `_MODEL_METADATA` entry. Namespace-freeze guard updated additively.

### 4.9 `orchestrator/__init__.py` (`run_workflow` / `_run_workflow`)
Thread the new params into `ctx.artifacts`: reuse Layer 1's `did_mode`/`did_cohort_col`/`did_treat_col`/`did_post_col`/`did_status_col` role params + `x` covariates, plus new `cs_control_group`, `cs_est_method`, `cs_base_period`, `cs_anticipation`, `cs_cluster_var`. Re-export `run_cs_did` (namespace guard additive). All new params inert when `model_type != "cs_did"` → golden 0-drift.

### 4.10 `api.py`
`POST /runs` accepts the `cs_*` params via the existing `RunExtraParams` JSON mechanism (mirrors `iv_endog`/`did_*`). Empty → no effect.

### 4.11 `engine/capabilities.py`
`cs_did` entry (group "DID", `requires` the same roles as `did`), 5-way sync: `MODEL_UI_META` / `MODEL_ORDER`, contract sample JSON, the two group-vocab drift tests, frontend `ModelGroup` TS union.

---

## 5. Frontend Components

### 5.1 `frontend/src/runForm/DIDControls.tsx` (EXTENDED)
Add a `cs_did` path to the existing DID controls: control-group selector (`never` / `not_yet`), est-method selector (`dr` / `ipw` / `reg`), base-period selector (`varying` / `universal`), anticipation integer input, optional cluster-var selector. Reuses the existing entity/time/cohort role assignment and `x` covariate roles. `RunForm` posts the `cs_*` params.

### 5.2 `frontend/src/runResult/CSDiagnosticsCard.tsx` (NEW)
Tiered card mirroring `DIDDiagnosticsCard`: overall ATT (one number + band), an event-study (dynamic) plot with the uniform band shaded, group and calendar tables, and a **metadata/warnings panel** (estimand name, method, control group, base period, n treated / n control, #cohorts, #valid cells, omitted cells, SE type, confidence level, band type, common-support warnings). Must render gracefully when `available === false` and when an aggregation has too few valid cells.

---

## 6. Data Flow (end to end)

```
POST /runs (model_type="cs_did", did_* roles, x covariates, cs_* params)
  → _bg_run → run_workflow → _run_workflow → ctx.artifacts["_cs_*"]
  → EstimationStage._fit_cs_did → runner.run_cs_did
        → did_spec.normalize_did_input            (reused cohort table)
        → cs_attgt.estimate_att_gt                → EffectEstimateBundle
        → cs_aggregate.aggregate × {overall,dynamic,group,calendar}
        → cs_inference.multiplier_bootstrap (seeded) per aggregation
  → DiagnosticsStage writes "cs_did" artifact (degraded-safe)
  → GET /runs/{id}/artifacts/cs_did → CSDiagnosticsCard
```

---

## 7. Testing & Golden Strategy

**R oracle (frozen fixtures committed to the repo; the IF is the primary validation target):**

| Quantity | Oracle | Tolerance |
|---|---|---|
| `ATT(g,t)` point estimates (dr/ipw/reg × never/not-yet × with-X/no-X) | R `did::att_gt` | 1e-6 |
| Per-cell influence function | R `DRDID::drdid_panel`$inf.func (and ipw/reg variants) | 1e-8 |
| 4 aggregations point estimates + SE | R `did::aggte` (simple/dynamic/group/calendar) | 1e-6 |
| Empty-X collapse: dr = ipw = reg = clean 2×2 | self-consistency + Layer 1 | machine precision |
| Bootstrap uniform-band critical value | locked as a golden under a fixed seed | 0-drift |

**Invariant unit tests (each maps to a test):**
1. Empty X ⟹ `dr = ipw = reg = (treated mean ΔY) − (comparison mean ΔY)`.
2. Universal base ⟹ `ATT(g, reference_period(g)) = 0` exactly.
3. Varying pre-period ⟹ `ATT(g,t)` uses `ΔY = Y_t − Y_{t−1}` for `t < effective_treatment_start`.
4. No already-treated controls ⟹ for every comparison unit in cell (g,t): `G_i > max(t, base_t) + δ` or `G_i = ∞`.
5. Cell support ⟹ `n_treated_cell = 0` or `n_control_cell = 0` ⟹ cell `valid=False`, NOT zero.
6. Aggregation ⟹ invalid cells excluded from BOTH numerator and denominator.
7. Influence function ⟹ cluster-level IF columns have empirical mean ≈ 0.
8. Aggregated IF ⟹ equals weighted sum of cell IF plus the weight-estimation IF.
9. R oracle ⟹ cell IF matches `DRDID` before aggregation; `aggte` estimates and SE match `did` after aggregation.

**Golden 0-drift:** additive golden(s) `tests/golden/cs_did_*.json`; existing goldens unchanged byte-for-byte. New params inert when `cs_did` not requested. Full gate `./scripts/gate.sh` (BE full + golden 0-drift + vitest + `tsc --noEmit`).

---

## 8. Risks & Mitigations

- **IF algebra is the #1 implementation risk.** Mitigation: operational definition pinned to `DRDID` (§3.5), element-wise fixture at 1e-8, no self-derived simplification permitted.
- **Bootstrap non-determinism would break golden 0-drift.** Mitigation: the multiplier bootstrap acts on the IF matrix (no refit) and uses a fixed-seed `default_rng`; the critical value is locked as a golden.
- **Silent sample-rule divergence** (the "cohort table hides assumptions" risk). Mitigation: rules applied by the estimator and recorded per cell in `cell_metadata` + `sample_spec`; never absorbed into the descriptive cohort table.
- **Large `G×K` memory blow-up.** Mitigation: cluster-row IF (shrinks rows ~T-fold) + `CS_PROBLEM_TOO_LARGE` guard; out-of-core deferred (§1).
- **Aggregation weight ambiguity.** Mitigation: weights and valid-cell-masked denominators pinned mechanically (§3.6) and validated against `aggte`.

---

## 9. Touch List (IV/2SLS + Layer-1 template parity)

| Layer | Files |
|---|---|
| Engine (NEW) | `engine/cs_attgt.py` (+ `EffectEstimateBundle`), `engine/cs_aggregate.py`, `engine/cs_inference.py` |
| Engine (reused) | `engine/did_spec.py` (unchanged) |
| Estimator | `econometrics/runner.py` (`run_cs_did`) |
| Wiring | `engine/stages/estimation.py` (`_fit_cs_did` + CORE_PACK + RerunAction), `engine/stages/diagnostics.py` (`cs_did` artifact), `orchestrator/_model_types.py`, `orchestrator/__init__.py` (params + re-export), `api.py`, `engine/capabilities.py` (5-way sync) |
| Frontend | `runForm/DIDControls.tsx` (extend) + `RunForm` post, `runResult/CSDiagnosticsCard.tsx` (new) |
| Tests / data / docs | R-oracle fixtures + invariant tests + additive golden(s), `examples/datasets/cs_did_staggered.csv`, `docs/cs-did-howto.md` |
