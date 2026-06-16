# Callaway-Sant'Anna DID — How-To

## What it's for

Callaway-Sant'Anna (CS) DID is the **staggered-adoption** estimator. When
different entities switch treatment on in **different periods** and the effect
evolves over time, classic two-way fixed-effects DID (**Layer 1**) is biased:
TWFE is a weighted average of all 2×2 comparisons, *including the "forbidden"
later-vs-earlier comparisons that use already-treated units as controls* — the
Goodman-Bacon decomposition in the Layer 1 output flags exactly this. CS sidesteps
the bias by estimating clean **group-time ATTs** (ATT(g,t): the effect for cohort
`g` at period `t`, differenced against a never- or not-yet-treated comparison
group) and then aggregating only valid comparisons. Reach for CS DID (**Layer 2**)
whenever Goodman-Bacon shows meaningful weight on the forbidden comparisons. It is
explicit-only; auto mode never picks it.

## The three input modes

CS DID shares the **same role assignment** as classic `did`. Every mode needs an
**entity** column and a **time** column; `y` is the outcome. Pick the mode that
matches how your treatment timing is recorded:

- **`cohort`** — staggered adoption (the natural fit for CS). One column holds each
  entity's **first-treatment period** (`did_cohort_col`); never-treated units use
  `0` or blank.
- **`two_by_two`** — a **treat-group** column (`did_treat_col`) and a **post-period**
  column (`did_post_col`); treatment = treat × post.
- **`status`** — a per-row **0/1 absorbing treatment indicator** (`did_status_col`).

The engine derives each entity's cohort `g` and per-row event time from whichever
mode you choose, then runs the same CS estimator.

## The knobs

CS-specific settings (the defaults match R's `did` package):

- **Control group** — `never` (default; compare only to never-treated units) or
  `not_yet` (compare to units not-yet-treated at period `t`, a larger comparison
  pool that uses eventually-treated units while they are still clean).
- **Estimation method** — `dr` (doubly-robust, default), `ipw`
  (inverse-probability weighting), or `reg` (outcome regression). **With no
  covariates the three collapse to the same simple 2×2 difference**, so the choice
  only matters when you supply covariates in **X**.
- **Base period** — `varying` (default; each event time differenced against the
  period immediately before it) or `universal` (everything differenced against a
  single fixed pre-period reference).
- **Anticipation** — number of pre-treatment periods (integer, default `0`) during
  which units may already respond; those periods are excluded from the clean
  baseline.
- **Clustering** — inference clusters by **entity** (the panel unit). Clustering by
  a different variable is a planned follow-up and not yet supported.

Defaults `never + dr + varying + anticipation 0` reproduce R `did`'s out-of-the-box
behaviour.

## Running it

### GUI

1. Select model **Callaway-Sant'Anna DID**.
2. Pick the **DID mode** and use the role controls to assign **entity**, **time**,
   **outcome**, and the mode-specific column(s) (cohort, or treat + post, or status).
3. Put any conditioning covariates in **X** (these activate `dr`/`ipw`/`reg`).
4. Set the CS knobs (control group, method, base period, anticipation). Inference
   clusters by entity.

### API (`POST /runs`, multipart form)

Set `model_type=cs_did`, `entity_col`, `time_col`, `y`, the mode fields (e.g.
`did_mode=cohort`, `did_cohort_col=...`), and the CS params: `cs_control_group`,
`cs_est_method`, `cs_base_period`, `cs_anticipation`. (Inference clusters by
entity; a `cs_cluster_var` parameter is a planned follow-up.)

### CLI

The CLI (`workbench run`) only threads `--y`, `--x`, `--mode`, `--model-type`,
`--imputation` — it does **not** expose the DID/CS role columns or the `cs_*`
knobs. Use the **GUI or the API** to run CS DID. (CLI support for these params is a
possible follow-up, the same limitation noted in the classic DID how-to.)

## Worked example

`examples/datasets/cs_did_staggered.csv` is a 120-row simulated panel: 12 US states
observed **2010-2019**, with a constructed treatment effect of **+2.0**. Three
cohorts adopt (2013, 2015, 2017) and three states are never treated
(`first_treated_year = 0`); `policy_intensity` is a pre-treatment covariate that
drives a mild conditional trend. Set it up in **`cohort`** mode:

| Field | Value |
|-------|-------|
| model | Callaway-Sant'Anna DID |
| DID mode | `cohort` |
| entity | `state` |
| time | `year` |
| y | `outcome` |
| cohort column | `first_treated_year` (never-treated = `0`) |
| X | `policy_intensity` |

With defaults (`never` + `dr` + `varying` + `0`) the overall (simple) ATT lands at
**≈ 2.02** (SE ≈ 0.13), and the dynamic, group, and calendar aggregations all sit
near **2.0** — matching the DGP. Extreme event times (e.g. ±6) trigger the
"supported by a single cohort" warning, which is expected on thin support.

## Reading the result card

- **Overall ATT** — the headline simple aggregation (estimate + SE + band): the
  average effect across all treated entity-periods.
- **Event-study (dynamic) plot** — ATT by event time relative to treatment, with a
  **simultaneous (uniform) band** that covers the whole path at once. **Pre-period
  estimates ≈ 0** is the visual evidence for parallel trends; post-period points
  trace the dynamic effect.
- **Group and calendar aggregations** — ATT by adopting cohort, and by calendar
  period — useful for spotting cohort heterogeneity or period-specific shocks.
- **Warnings** — e.g. *event time X supported by a single cohort* (thin support at
  that horizon) or omitted cells (no valid comparison group). Read these before
  trusting the tails of the event study.

## Validation

The CS estimator is **self-implemented** (no new dependencies) and validated
**element-wise against R `did` / `DRDID`**: group-time ATTs, the doubly-robust
influence function, the aggregations, and the multiplier-bootstrap bands are all
checked against the R reference fixtures.
