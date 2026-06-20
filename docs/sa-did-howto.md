# Sun-Abraham event study (`sa_did`) — how-to

Sun-Abraham (SA) interaction-weighted (IW) estimation is a staggered-adoption
difference-in-differences method that, like Callaway-Sant'Anna (CS), gives you an
event-study path of cohort-by-event-time treatment effects that is **robust to the
"bad comparison" bias of two-way fixed-effects (TWFE) DID** under staggered timing.

In Workbench v1.5.8, SA is exposed as the `sa_did` model type. It produces the **same
result shape** as `cs_did` — the same event-study aggregation, the same simultaneous
confidence bands, and the same honest-DID (Rambachan-Roth) sensitivity panels — so the
results card and controls are shared.

## SA vs CS — when to use which

| | Sun-Abraham (`sa_did`) | Callaway-Sant'Anna (`cs_did`) |
|---|---|---|
| Estimator | One **saturated** TWFE regression: `y ~ unit FE + time FE + Σ cohort×event-time interactions` (reference event time = −1). The interaction coefficients ARE the per-cohort, per-event-time effects CATT(g,e). | Per-cell doubly-robust DRDID (a separate 2×2 comparison for each group-time cell). |
| Covariates | **None** (classic SA is uncovariated). | Supports covariate adjustment via DR / IPW / outcome-regression. |
| Comparison group | Never-treated; or, when there is no never-treated group, the **last-treated** cohort as the normalization baseline (its effective window is set by support/collinearity, it is **not** treated as a clean control). | Never-treated or not-yet-treated, chosen explicitly. |
| Strength | Transparent single-regression estimand; matches `fixest::sunab` exactly. | Flexible control group + covariate double-robustness. |

**Rule of thumb:** reach for `cs_did` when you need covariate adjustment or an explicit
not-yet-treated control; reach for `sa_did` when you want the classic saturated
interaction event study and want to cross-check CS with a structurally different estimator.

## Running it

Pick **Sun-Abraham DID** in the model-type selector, then assign the same roles as CS:
**entity**, **time**, and the **cohort / treatment-timing** column (never-treated encoded
as a non-positive or blank cohort). Optionally tick **honest-DID** for the
sensitivity analysis. SA ignores the CS-only knobs (control group, estimation method,
base period, anticipation) — they have no effect on an SA run.

## Reading the results

The results card is the shared DID event-study card (it labels itself "Sun-Abraham" for
SA runs):

- **Event-study path** — CATT(e) at each event time, with pointwise CIs and a
  simultaneous (sup-t) band. Pre-period coefficients (event time < −1) are shown for the
  visual parallel-trends check; −1 is the dropped reference period.
- **Honest-DID panels** (if enabled) — the Rambachan-Roth robust confidence sets under
  relaxed parallel trends, both **ΔRM** (relative-magnitudes) and **ΔSD** (smoothness via
  FLCI). These run on SA's event study exactly as they do on CS's — no SA-specific code.

## The unbalanced-panel caveat

SA's dynamic event study reuses CS's aggregation, which weights each cohort by its
**cohort size** (`n_g`). On a **balanced** panel with common event-time support this is
identical to `fixest::sunab`'s own weighting (validated to ~1e-6). On an **unbalanced**
panel the two can differ: `fixest::sunab` weights by the **observed count at each relative
period** (`N_{g,e}`), while Workbench keeps the `did`-style `n_g` weighting for consistency
with the shipped CS path. When the panel is unbalanced, the dynamic block carries an
`interpretation_restrictions` note saying so. The per-cohort effects CATT(g,e), their
standard errors, and the honest-DID inputs are **exact regardless of balance** — only the
*aggregation weighting* of the event-study path carries this qualitative caveat. A
SA-faithful observed-period aggregation is deferred (see the release notes).

## What's deferred

DR/IPW/covariate adjustment, flexible relative-time binning, the SA-faithful
observed-period unbalanced aggregation, user-chosen `l_vec` honest-DID targets, and any
large SA-specific UI are out of scope for this "estimator-slot validation" version.
