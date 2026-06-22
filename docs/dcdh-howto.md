# de Chaisemartin–D'Haultfœuille (dCDH) — how-to

`model_type = "dcdh"` (v1.5.9). A dynamic difference-in-differences estimator for
**binary, non-absorbing (switching) treatment** — treatment that can turn **on and
off** over time — using **not-yet-switched** units as controls.

## When to use dCDH vs CS / SA

| | Treatment | Controls | Use when |
|---|---|---|---|
| Callaway-Sant'Anna (`cs_did`) | absorbing (once on, stays on) | never / not-yet treated | staggered adoption, heterogeneous effects |
| Sun-Abraham (`sa_did`) | absorbing | clean-control cohorts | staggered adoption, event study |
| **dCDH (`dcdh`)** | **NON-absorbing (can switch off)** | not-yet-switched | treatment that turns on **and off**; switching designs |

If your treatment is absorbing (a one-time adoption), use CS or SA. Use dCDH when
units can **enter and exit** treatment.

## Input

dCDH needs a **per-(unit, period) treatment column** `D_it ∈ {0,1}` — the raw treatment
*status* each period, NOT a first-treatment cohort/adoption time.

In the run form (model type **de Chaisemartin-D'Haultfœuille DID**):
- **entity**, **time**, **outcome** — the panel identifiers + y.
- **处理路径列 (treatment D_it, 0/1)** — the binary treatment-status column (`did_treatment_path`).
- **聚类变量** (optional) — defaults to clustering by entity.

## What v1.5.9 estimates (minimal-faithful scope)

- **Analysis sample = "first-up switchers"**: units that start untreated (baseline=0)
  and whose **first** switch is `0→1`. After that first up-switch a unit may switch
  back to 0 — it stays in the sample (this is the genuinely non-absorbing part).
- **`effect_ℓ`** (event_time ≥ 0): the dynamic effect ℓ periods after the first
  up-switch (`effect_0` = the switch period vs the period before).
- **`placebo_ℓ`** (event_time < 0): pre-trend tests. Near zero ⇒ parallel-trends
  evidence. **Placebos are dCDH's native pre-trend tool** — there is no Honest-DID
  sensitivity panel for dCDH this version.
- **Overall ATT**: a switcher-weighted average, shown with an **`experimental`** badge
  (its weighting口径 vs `DIDmultiplegtDYN` is being finalized — read `effect_ℓ` as the
  primary result).
- Simultaneous **sup-t bands** over the event-time axis, and per-event-time switcher counts.

## Scope limits (deferred)

- Binary treatment only (continuous/multi-valued intensity deferred).
- baseline=1 units (already treated at the start) and units whose first switch is
  `1→0` are **excluded** (with a recorded reason) — direction-specific exit effects
  are deferred.
- No covariates; regular (consecutive) time grid expected.

## Validation

Estimates and per-ℓ SEs are validated element-wise against R `DIDmultiplegtDYN` 2.3.4
(`same_switchers=TRUE`, cluster by id) to machine precision. The test suite never calls
R — it reads committed JSON oracles under `tests/fixtures/dcdh/`.
