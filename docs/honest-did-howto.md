# honest-DID (Rambachan-Roth ΔRM) — How-To

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
that set. The reported grid is **M̄ ∈ {0, 0.5, 1, 1.5, 2}**.

## How to enable it

honest-DID is **opt-in** and only available on **Callaway-Sant'Anna DID**
(`cs_did`).

### GUI

Configure a CS DID run as usual, then tick the **"honest-DID 敏感性
(Rambachan-Roth)"** checkbox in the CS controls. The robustness panel appears in
the CS diagnostics card after the run completes.

### API (`POST /runs`, multipart form)

Set `model_type=cs_did` plus the usual CS fields, and add **`honest_did=true`**.

The M̄ grid and grid resolution are fixed module constants
(`runner.HONEST_MBAR_GRID`, `runner.HONEST_GRID_POINTS`); they are not exposed as
per-run knobs.

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

## Method note — Conditional / ARP (simulation-free)

We use the **simulation-free Conditional / ARP** variant of the moment-inequality
test (the conditional hybrid with the degenerate-dual fallback), **not** the
least-favourable / conditional-LF hybrid. The C-LF hybrid requires drawing
least-favourable critical values by **simulation (an RNG)**, which would make the
output non-deterministic; the Conditional/ARP variant is **fully deterministic**,
so identical inputs always yield identical CIs — important for reproducibility and
for our 0-drift golden tests.

## Validation

The honest-DID engine is a **self-implemented, faithful port of R `HonestDiD`
0.2.8** (the ΔRM constraint construction, the ARP conditional test, and the
degenerate-dual path), with **0 new runtime dependencies**. It is validated
**element-wise against R HonestDiD** on an identical θ-grid: robust CI endpoints
match to **~1e-3**, and the element-wise grid accept/reject decisions agree.

## Cost / 性能

honest-DID is **opt-in** because it is the most expensive step in a CS run:
roughly **~157 s** at the full M̄ grid (5 values × 1000 grid points). It runs
**asynchronously** and never blocks the rest of the CS output. Leave the checkbox
off if you don't need the sensitivity analysis.

## Degrade, never fail

honest-DID **never fails the run**. If the sensitivity computation hits an
internal error (e.g. a degenerate variance or an unidentified pre-period
structure), the `honest_did` block is returned as
`{"skipped": true, "reason": ...}` and the rest of the CS DID result ships
normally. The GUI shows a skipped note instead of the grid.

## Limitations / 限制

- **Only ΔRM (relative magnitudes) is implemented.** The smoothness restrictions
  **ΔSD** and the **FLCI** (fixed-length confidence interval) construction are
  **deferred to v1.5.7.1**.
- The sensitivity is reported for the **post-treatment average** aggregation.
- honest-DID applies to **cs_did only** — it is not available on classic Layer 1
  DID.
