# honest-DID (Rambachan-Roth) — How-To

This guide covers **two honest-DID sensitivity families**, both layered on
Callaway-Sant'Anna DID and both produced by the **single `honest_did`
checkbox**:

- **ΔRM (relative magnitudes)** — the original v1.5.7 track, inferred via the
  simulation-free Conditional / ARP test.
- **ΔSD (smoothness)** — added in v1.5.7.1, inferred via the **FLCI**
  (fixed-length confidence interval) construction, R HonestDiD's default for
  smoothness.

One run now ships **both tracks side by side**.

## What it's for

Callaway-Sant'Anna DID identifies dynamic effects **off parallel trends**: the
pre-treatment event-study coefficients are assumed to be exactly zero in
expectation. honest-DID asks the practical follow-up question — *how big a
violation of parallel trends would it take to overturn my conclusion?* — and
reports robust confidence intervals that are valid under a bounded violation,
rather than asserting that the parallel-trends assumption holds exactly.

It is a **post-processor** layered on top of CS DID. **Point estimates are
unchanged** — the dynamic ATT(g,t) path and all four aggregations are exactly
what CS DID already produced. honest-DID only *widens the inference* to account
for a deviation from parallel trends.

## ΔRM — relative magnitudes

We implement the **relative-magnitudes (ΔRM)** restriction. The idea: bound the
post-treatment differential trend by the **largest violation visible in the
pre-treatment periods**, scaled by a sensitivity parameter **M̄** (Mbar):

> the period-to-period post-treatment violation of parallel trends is **at most
> M̄ × the maximum pre-treatment violation**.

- **M̄ = 0** — parallel trends holds exactly (this recovers the standard CS band).
- **M̄ = 1** — post-treatment trends may deviate as much as the worst observed
  pre-trend deviation.
- **M̄ = 2** — up to twice that, and so on.

Concretely ΔRM is a **union of polyhedra** over each pre-period `s` and each sign
of the violation; the robust CI is the union of the conditional intervals across
that set. The reported grid is **M̄ ∈ {0, 0.5, 1, 1.5, 2}**. ΔRM result rows use
the **`Mbar`** key.

## ΔSD — smoothness (NEW in v1.5.7.1)

ΔSD bounds the **second differences** of the differential trend. Intuitively:

> the pre-trend may have a **slope**, but after treatment it cannot suddenly
> **bend** — the period-to-period *change in slope* is bounded by **M**.

This is R `HonestDiD`'s **headline restriction**, and its **default inference
method for smoothness is FLCI** (fixed-length confidence interval) — which is what
we implement here.

- **M = 0** — the differential trend is exactly **linear** (no curvature). This is
  the most restrictive case and recovers the minimum-smoothness classical band.
- **M > 0** — the trend may curve, by up to **M** per period, after treatment.

### FLCI — fixed-length confidence interval

FLCI builds an **affine, minimum-length** confidence interval by **convex
optimization over the estimator weights**, explicitly trading **worst-case bias**
against **variance** to find the shortest interval guaranteed to cover under the
smoothness budget. It is usually **shorter and more usable** than test-inversion.
The interval is symmetric around its center, with

> **half-length = sqrt(variance) × (folded-normal critical value)**.

### ΔSD's M is an absolute curvature scale

Unlike ΔRM's scale-free M̄ (a *multiplier* on observed pre-trend violations),
ΔSD's **M is an absolute curvature scale** in the units of the outcome. We pick a
**data-adaptive default grid**:

> **M ∈ {0, 0.5, 1, 1.5, 2} × s**, where **s = max(sqrt(diag(Σ)))** is the largest
> event-study standard error, floored at **1e-8** to avoid grid collapse on a
> near-degenerate Σ.

**Caveat:** because M is data-adaptive, **`M = 1` is not the same physical
quantity across datasets** (it's a curvature scale, not the estimation-noise
scale). Compare M-grids *within* a dataset, not across datasets. ΔSD result rows
use the **`M`** key (not `Mbar`).

## How to enable it

honest-DID is **opt-in** and only available on **Callaway-Sant'Anna DID**
(`cs_did`).

### GUI

Configure a CS DID run as usual, then tick the **"honest-DID 敏感性
(Rambachan-Roth)"** checkbox in the CS controls. The robustness panel appears in
the CS diagnostics card after the run completes.

### API (`POST /runs`, multipart form)

Set `model_type=cs_did` plus the usual CS fields, and add **`honest_did=true`**.
The **single** `honest_did=true` flag produces **both** the ΔRM and ΔSD tracks.

The M̄ grid and grid resolution are fixed module constants
(`runner.HONEST_MBAR_GRID`, `runner.HONEST_GRID_POINTS`); they are not exposed as
per-run knobs.

## Result shape — nested, always explainable

The `cs_did.json` `honest_did` block is **nested** — one sub-block per track:

```json
"honest_did": {
  "rm": { "status": "...", "reason": "...", ... },
  "sd": { "status": "...", "reason": "...", ... }
}
```

Each track carries a **`status ∈ {"ok", "degraded", "not_available"}`** plus a
**`reason`**, so a track that can't be computed is **always explainable, never
silently dropped**. The two tracks are independent: one can be `ok` while the
other is `degraded`/`not_available`.

The frontend renders **each track three-state**:

- **`ok`** → the full M-grid panel.
- **`degraded`** → a collapsed panel with the `reason`.
- **`not_available`** → a "not available" note with the `reason`.

## Reading the result

The sensitivity sub-panel shows one row per M̄ value, each with the **robust CI**
for the **post-treatment average** effect under that violation budget:

- **Scan down the grid.** As M̄ grows the CI widens. The estimate (and thus the
  centre of the analysis) does not move — only the interval.
- **Breakdown M̄ (突破 M̄).** The smallest M̄ at which the robust CI **first
  includes 0** — i.e. the violation budget at which the effect is no longer
  distinguishable from zero. A *large* breakdown M̄ means the result is robust
  (it survives a big assumed pre-trend violation); a *small* one means even a
  modest violation overturns significance. If the CI never includes 0 across the
  whole grid, the panel reports **无突破 (始终含 0 means the opposite — never
  loses significance)**.

### ΔSD / FLCI

The ΔSD panel shows an **M-grid table per target** — the **post-period average**
plus **each event time** — and at each M the **FLCI** `[lb, ub]`:

- **Read the M-grid.** As the curvature budget **M** grows, the FLCI widens.
- **Per-target rows.** Each target (post average + per-event-time) gets its own
  row, so you can see which horizons stay robust and which don't.
- **Breakdown M.** The **largest M at which the CI still excludes 0** — beyond it
  the effect is no longer **robustly distinguishable from 0** under the smoothness
  budget. (Note this is the *opposite end* of the grid from ΔRM's breakdown M̄,
  which is the *smallest* M̄ that first *includes* 0; same idea — the budget at
  which significance is lost.)
- **`null` endpoints** render as **"—"** (a CI that could not be formed at that
  M).

## Method note — Conditional / ARP (simulation-free)

We use the **simulation-free Conditional / ARP** variant of the moment-inequality
test (the conditional hybrid with the degenerate-dual fallback), **not** the
least-favourable / conditional-LF hybrid. The C-LF hybrid requires drawing
least-favourable critical values by **simulation (an RNG)**, which would make the
output non-deterministic; the Conditional/ARP variant is **fully deterministic**,
so identical inputs always yield identical CIs — important for reproducibility and
for our 0-drift golden tests.

## Method note — FLCI uses an *analytic* folded-normal quantile (ΔSD)

The FLCI half-length uses a **folded-normal critical value**. R `HonestDiD`'s
`.qfoldednormal` computes this by **Monte-Carlo simulation** (`set.seed(0);
rnorm(1e6); quantile(...)`), so R's FLCI carries **~1e-3 of MC noise** and is not
analytically reproducible — the same determinism problem as ΔRM's C-LF hybrid. We
instead use the **analytic folded-normal quantile** (a Brent root-find on the
folded-normal CDF), which is **fully deterministic**. There is **no Monte Carlo,
no bootstrap, no random sampling** anywhere in the ΔSD/FLCI path, so there is **no
statistical source of random error**.

(We do **not** claim bit-for-bit determinism: the SciPy quadratic program is
subject to BLAS / solver / float drift, so the golden snapshot freezes only
**status / artifacts / coefficients — never the FLCI numbers**. Numerical
correctness is asserted by the engine **oracle tests**, not the golden.)

## Validation

The honest-DID engine is a **self-implemented, faithful port of R `HonestDiD`
0.2.8** (the ΔRM constraint construction, the ARP conditional test, and the
degenerate-dual path), with **0 new runtime dependencies**. It is validated
**element-wise against R HonestDiD** on an identical θ-grid: robust CI endpoints
match to **~1e-3**, and the element-wise grid accept/reject decisions agree.

### ΔSD / FLCI validation

The FLCI engine is a faithful Python/SciPy port of R `HonestDiD` 0.2.8's
`findOptimalFLCI` (the worst-case-bias-given-`h` convex sub-problem via SLSQP,
`findLowestH` / `findHForMinimumBias` for hMin / h0, and the derivative bisection
over `[hMin, h0]` with a grid fallback). R 0.2.8 is used **only** to generate the
committed JSON oracles — the test suite **never invokes R**. The oracle was
regenerated with the **analytic** folded-normal quantile injected into R (via
`assignInNamespace`) so it is reproducible.

- **FLCI half-length** matches R to **<1e-9** for all M.
- **CI endpoints** match R to **<1e-6** for M > 0.
- **M = 0** reduces to the minimum-SD classical CI
  (half-length = `z_{0.975}·hMin`), exact to **1e-8**.
- **M = 0 CI center** matches R only to **~2.25e-6** — **documented, not a bug**:
  at M = 0 the worst-case-bias objective is *flat along a degenerate manifold*, so
  R's CVXR/ECOS solver leaves ~2e-10 of slack in hMin that amplifies ~1e4× into
  the weight vector. The CI **width** (the statistically meaningful quantity) is
  exact; chasing R's solver slack would yield a *less-optimal* estimator, so we
  did not.

## Cost / 性能

honest-DID is **opt-in** because it is the most expensive step in a CS run. The
cost is dominated by **ΔRM** (~157 s at the full M̄ grid, 5 values × 1000 grid
points × LP). **ΔSD/FLCI adds only seconds** (a small QP × an h-grid), so enabling
both tracks leaves the overall runtime **essentially unchanged (~157 s)**. Both
tracks are computed from **one frozen Σ snapshot** — Σ is not recomputed between
them. honest-DID runs **asynchronously** and never blocks the rest of the CS
output. Leave the checkbox off if you don't need the sensitivity analysis.

## Degrade, never fail

honest-DID **never fails the run** — the **whole honest block (both tracks)**
degrades rather than failing. Per-track:

- Known guard conditions → **`status: "not_available"`** with a `reason`:
  `HONEST_NO_PRE_PERIODS`, `HONEST_NO_POST_PERIODS`, `HONEST_DEGENERATE_SIGMA`.
- Unexpected internal errors → **`status: "degraded"`** with a `reason`.

The rest of the CS DID result ships normally; the GUI renders each track's
three-state view (panel / degraded+reason / not-available+reason).

## Limitations / 限制

- **Both ΔRM (relative magnitudes) and ΔSD (smoothness, via FLCI) are
  implemented.** ΔSD via **test-inversion** is **deferred** (code-cheap but ~30×
  runtime, and FLCI is R's default for ΔSD — a possible later patch).
- **`honest_sd` requires `num_pre ≥ 1`** (matching the validated engine and ΔRM),
  **not `num_pre ≥ 2`**. The design spec had hypothesized a `num_pre ≥ 2`
  identifiability requirement (from a 2-equality derivation), but R's actual
  `findOptimalFLCI` imposes only **one** sum-weights equality and computes for
  `num_pre ≥ 1` — we verified R runs cleanly at `num_pre = 1`. The `≥ 1` guard is
  a deliberate **faithfulness-to-R** choice.
- The sensitivity is reported for the **post-treatment average** plus
  **each event time**; **user-chosen `l_vec` target selection** is **deferred to
  v1.5.8** (it overlaps with the Sun-Abraham target UI).
- honest-DID applies to **cs_did only** — it is not available on classic Layer 1
  DID.
