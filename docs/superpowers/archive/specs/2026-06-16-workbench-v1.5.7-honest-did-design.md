# v1.5.7 — DID Layer 3a: honest-DID / Rambachan-Roth Sensitivity (Design)

Date: 2026-06-16
Status: design approved (pending user review of this spec)
Base: `main` @ `399fc53` (v1.5.6.1 ship). Own worktree `.worktrees/workbench-v1.5.7`.
Roadmap: [[did-layer3-roadmap]] — Layer 3 split into 3 versions; honest-DID FIRST (estimator-agnostic
post-processor, lowest architectural risk), then v1.5.8 Sun-Abraham IW, v1.5.9 dCDH.

## 1. What this is

honest-DID (Rambachan & Roth 2023, *A More Credible Approach to Parallel Trends*) is NOT an
estimator. It is a **sensitivity post-processor**: given an event-study coefficient vector
(pre-treatment "placebo" + post-treatment dynamic effects) and its covariance matrix, it returns
**robust confidence sets** for a target parameter that remain valid when parallel trends is
*relaxed* rather than assumed exactly. Its input is exactly what the already-shipped
Callaway-Sant'Anna (`cs_did`) **dynamic** aggregation produces.

This version applies it to the shipped CS event study. Because the engine is built
estimator-agnostic, v1.5.8 (Sun-Abraham) reuses it for free via a thin adapter.

## 2. Scope (locked decisions)

- **Restriction class: ΔRM (relative magnitudes) ONLY.** The post-treatment differential-trend
  violation is bounded by M̄ × the maximal pre-treatment violation; sweep M̄ over a grid. This is
  the applied-literature workhorse (HonestDiD's relative-magnitudes path). ΔSD/FLCI (smoothness) is
  **deferred to v1.5.7.1**.
- **Inference: ARP conditional / conditional-LF-hybrid moment-inequality test** (the method R's
  `HonestDiD` uses for ΔRM), via test inversion over a grid of candidate parameter values.
- **Targets reported: the post-treatment average** (l = uniform over post coefficients, = the CS
  dynamic "overall") **AND each post event-time** (l = indicator), mirroring the CS card's
  per-event-time + overall display.
- **Invocation: a parameter switch inside the `cs_did` run.** No new `model_type`, no new pipeline.
  When enabled, the result carries a `honest_did` block. Default M̄ grid `[0, 0.5, 1, 1.5, 2]`,
  not user-editable in the UI (avoid bloat).
- **Dependency: self-implement with SciPy (`linprog`/optimization), zero new Python deps.** Validate
  against R `HonestDiD` (one-time install for oracle generation).

## 3. Architecture — two modules + a thin adapter

The estimator-agnostic engine is isolated from any knowledge of CS/SA.

### 3.1 `backend/workbench/engine/honest_did.py` — pure engine (estimator-agnostic)
Signature (operational):
```
honest_rm(*, betahat, sigma, num_pre, num_post, l_vec, mbar_grid, alpha=0.05) -> dict
```
- `betahat` (num_pre+num_post,): event-study coefficients ordered pre (earliest→latest, EXCLUDING
  the normalized reference period) then post (e=0,1,...).
- `sigma` ((num_pre+num_post)²): the joint covariance of `betahat`.
- `l_vec` (num_post,): weights selecting the target θ = l'·(post effects).
- `mbar_grid`: list of M̄ values (0 = the original parallel-trends CI).
- Returns per-M̄ `{Mbar, lb, ub}` robust CI for θ, plus the `breakdown` M̄ (the largest M̄ at which
  the CI still excludes 0; None if it excludes/includes 0 throughout).

Internals: builds the ΔRM(M̄) constraint matrices (the linear inequalities defining the allowed
differential-trend set) and runs the ARP test inversion. **The constraint construction and the ARP
test are defined OPERATIONALLY as a faithful port of R `HonestDiD`'s ΔRM path — NOT a hand-derived
formula** (same discipline as the v1.5.6 DRDID influence-function port). The committed R oracle is
the source of truth.

This module is the design's center of gravity / risk center. It knows nothing about cs_did.

### 3.2 `backend/workbench/engine/honest_did_adapter.py` — thin CS adapter
```
honest_did_from_cs_dynamic(agg_dynamic, *, row_cluster, n_total, mbar_grid, alpha) -> dict
```
- Reads the CS `aggregate(bundle, "dynamic")` output: `label` (event times), `estimate` (β_e),
  `component_if` (N × n_event_times).
- Builds the **cluster-robust** covariance Σ = (1/N²) Σ_c S_c S_cᵀ with S_c = Σ_{i∈c} component_if_i,
  reusing the v1.5.6.1 cluster reduction (so honest-DID automatically follows the run's clustering).
- Splits event times by sign into **pre (e<0)** and **post (e≥0)**; the reference period (e=−1, the
  structural zero) is excluded from `betahat`. Maps the ordering to HonestDiD's
  `(numPrePeriods, numPostPeriods)` convention. **This event-time ↔ (pre,post) mapping is a key
  correctness point and gets its own test** (an off-by-one here silently corrupts every CI).
- Computes the post-average l_vec (uniform) and per-event-time l_vecs, calls `honest_rm` for each,
  returns the assembled `honest_did` block.

## 4. Validation strategy (two layers)

R `HonestDiD` is the oracle. Tolerance is **looser than CS** (~1e-3..1e-4 on CI endpoints) because
the result comes from LP/optimization + test-inversion grids, not a closed form. Grid step is set
fine enough that the oracle endpoints are stable to that tolerance.

1. **Engine layer (fixed (betahat, sigma)):** use the HonestDiD package's own example inputs
   (e.g. the Medicaid/LWdata `betahat`+`sigma`), run
   `createSensitivityResults_relativeMagnitudes()`, write `tests/fixtures/honest_did/honest_rm.json`
   (per-M̄ lb/ub + breakdown). Assert `honest_rm(...)` matches to ~1e-3..1e-4. This isolates engine
   correctness from any CS plumbing.
2. **Adapter layer (end-to-end):** from the cs_did fixture panel, build the dynamic aggregation,
   extract (betahat, sigma) via the adapter, and confirm (a) the extracted Σ matches an
   independently-computed cluster-robust covariance, and (b) the per-event-time/(pre,post) mapping is
   correct. Optionally feed the extracted (betahat, sigma) through R for an end-to-end oracle.

**Determinism (golden 0-drift):** the ARP *conditional* test is simulation-free (truncated-normal
critical values) → deterministic. R's ΔRM default is the conditional-LF *hybrid*, whose
least-favorable critical value MAY be simulated. Resolution (to be nailed in the plan, with the R
oracle as truth): prefer the simulation-free conditional variant where it matches R; if the hybrid's
LF step is simulated, **seed it** so the result is reproducible. Either way the committed result must
be byte-stable across runs.

## 5. Wiring (rides the existing cs_did pipeline)

- New param `honest_did` (bool/off-default) threads `api.py` → `orchestrator`
  (`ctx.artifacts["_honest_did"]`) → estimation stage → `run_cs_did(honest_did=...)`, identical
  pattern to `cs_cluster_var`.
- `run_cs_did`, when enabled, calls `honest_did_from_cs_dynamic(...)` on the dynamic aggregation
  (passing the run's `row_cluster`/`n_total`) and attaches `result["honest_did"]`. When disabled the
  key is absent (golden 0-drift for every existing cs_did run).

## 6. Error handling — honest-DID degrades, never fails the run

honest-DID is supplementary; the estimation already succeeded, so its failure must NOT produce a
`MODEL_FIT_FAILED` or `WORKFLOW_FAILED`. On any of the following, omit the `honest_did` block (or set
it to `{skipped: true, reason: ...}`) and let the cs_did run COMPLETE:
- `HONEST_NO_PRE_PERIODS` — num_pre == 0: ΔRM is undefined without a pre-period to bound against.
- `HONEST_DEGENERATE_SIGMA` — Σ not positive-definite / near-singular.
- `HONEST_NO_POST_PERIODS` — num_post == 0.
- Any solver/optimization failure → caught, reason recorded, block omitted.

These are warnings on a successful run, not structured model-fit failures.

## 7. Frontend

- `runForm/CSControls.tsx`: a **checkbox** "honest-DID 敏感性 (Rambachan-Roth)" → posts `honest_did`.
- `runResult/CSDiagnosticsCard.tsx`: a **sensitivity sub-panel**, rendered only when
  `result.honest_did` is present (degraded-safe). For the post-average and each post event-time:
  show the robust CI across the M̄ grid (compact table or a small plot) + the breakdown M̄. When the
  block is `{skipped, reason}`, show the reason quietly.

## 8. Golden & tests

- Additive golden: a `honest_did=on` cs_did run (the `_capture` snapshot freezes run shape; honest-DID
  numbers are guarded by the `honest_rm.json` oracle test, not the golden). Existing 19 goldens stay
  0-drift.
- `tests/fixtures/honest_did/{generate_oracle.R, honest_rm.json}` + `tests/test_honest_did.py`
  (engine vs oracle), `tests/test_honest_did_adapter.py` (Σ extraction + pre/post mapping),
  hardening cases (no-pre/degenerate-Σ → skipped, run still completes), FE vitest for the sub-panel.

## 9. Files touched (anticipated)

Backend: NEW `engine/honest_did.py`, `engine/honest_did_adapter.py`; modify
`econometrics/runner.py` (`run_cs_did`), `api.py`, `orchestrator/__init__.py`,
`engine/stages/estimation.py` (thread `honest_did`). Maybe `engine/capabilities.py`.
Tests: fixtures + 2 new test modules + hardening + golden additive.
Frontend: `runForm/CSControls.tsx`, `runResult/CSDiagnosticsCard.tsx` (+ types/api.ts).
Docs: `docs/honest-did-howto.md`, release notes.

## 10. Deferrals (scheduled by shared-machinery + dependency + YAGNI)

- **ΔSD/FLCI (smoothness) → v1.5.7.1** — genuinely different inference (convex FLCI); its own version.
  Fold in **user-chosen l_vec** there (orthogonal UX, same honest-DID surface).
- **Combo (ΔSDRM) + sign/monotonicity restrictions → NOT pre-scheduled (YAGNI).** Cheap incremental
  constraint-row additions once the ARP framework (this version) + ΔSD (v1.5.7.1) exist; add on-demand
  if a real use case appears. Document as "framework-enabled."
- **honest-DID on Sun-Abraham → intrinsic to v1.5.8**, not a separate item: the estimator-agnostic
  engine + a thin SA adapter give it for free.

## 11. Gate (ship criteria)

Full backend suite green (`python -m pytest`), golden+invariants+snapshot 0-drift (existing 19 + 1
additive `honest_did` golden), FE vitest green, `tsc --noEmit` 0, `./scripts/gate.sh` PASSED.
Whole-feature adversarial review before merge. `--no-ff` merge + tag `v1.5.7`; verify gated-head vs
merged-tree empty diff. Per-version main-push needs explicit authorization.

## 12. Dependency / R note

One-time `install.packages("HonestDiD")` in the v1.5.7 Task 0 (needs `~/.R/Makevars`
`CC=clang -std=gnu17`, already in place). R is used ONLY to generate the committed oracle JSON; after
that, tests run against the JSON with no R. did/DRDID + this HonestDiD persist outside the worktree
(survive cache cleanups). Zero new Python deps (SciPy already present).
