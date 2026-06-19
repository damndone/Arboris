# Workbench v1.5.7.1 — honest-DID ΔSD / FLCI smoothness sensitivity (design)

Date: 2026-06-19
Status: design approved (brainstorm), pending plan
Base: origin/main `c2a9c08` (tag `v1.5.7`)
Predecessor: v1.5.7 honest-DID ΔRM (Rambachan-Roth relative magnitudes), shipped 2026-06-17.

## 1. Goal & scope

v1.5.7 shipped **one** of the two sensitivity families in Rambachan-Roth (2023): ΔRM
(relative magnitudes), inferred via the simulation-free Conditional/ARP test. This
version adds the **second, and R's own default for smoothness restrictions**:

- **ΔSD (smoothness):** the differential trend's **second differences** are bounded,
  `|δ_{s-1} − 2δ_s + δ_{s+1}| ≤ M`. Intuition: the pre-trend may have a slope, but it
  cannot suddenly bend after treatment. This is the restriction practitioners most
  often want (smooth extrapolation of the pre-trend), and is RR's headline example.
- **FLCI (Fixed-Length Confidence Interval):** the inference method R defaults to for
  ΔSD. Constructs an affine minimum-length CI via **convex optimization** over the
  estimator weights subject to worst-case bias. Typically shorter / more usable than
  test-inversion, and is the second curve in RR's canonical comparison figure.

**In scope:** ΔSD constraint + FLCI inference (primary, new convex machinery), wired
onto the existing CS dynamic event study via the existing adapter; auto targets
(post-period average + per event-time); nested `{rm, sd}` JSON contract; FE three-state
rendering.

**Out of scope (deferred):**
- **ΔSD via test-inversion (Conditional/ARP):** code-cheap (reuses the v1.5.7 engine
  with a new constraint matrix) but runtime-expensive (~30× FLCI: 1000-pt grid × LP ×
  M-grid × targets ≈ +150s). R defaults to FLCI for ΔSD; test-inversion's distinctive
  value (non-convex Δ) does not apply to the convex ΔSD ball, and the RM block already
  exposes a test-inversion flavor. → possible later patch, not this version.
- **User-chosen `l_vec`** (target parameter selection): pure UX/plumbing, no numerical
  content. Overlaps with the "choose target" UI that v1.5.8 Sun-Abraham will need →
  deferred to v1.5.8 to design once.

## 2. Mathematical design (engine layer)

Notation: `p = num_pre`, `q = num_post`, `T = p + q`. Σ is the `T×T` event-study
covariance, ordered **pre (event time < 0) then post (≥ 0), excluding e = −1**, matching
the v1.5.7 adapter convention. Target `θ = l'τ_post`, `l ∈ R^q`.

### 2.1 ΔSD constraint operator

`A_D` = the second-difference operator, shape `(T−2)×T`, rows
`δ_{s-1} − 2δ_s + δ_{s+1}`. `Δ^SD(M) = { δ : ‖A_D δ‖_∞ ≤ M }`. A single convex
polyhedron — no `(s, sign)` union (the structural simplification over ΔRM): the solver
faces one standard feasible region, not an enumeration.

`A_D` has full row rank `T−2` for all `T ≥ 3`. `ker(A_D) = span{1, t}` (constants and
linear trends — the lineality space of `Δ^SD`), where `t` is the relative-event-time
index vector.

### 2.2 Affine estimator & the bias functional

The affine estimator is the full weight vector applied to `β̂`:

    θ̂ = w_full' β̂,    w_full = (−w_pre, l) ∈ R^T

with only `w_pre ∈ R^p` free (the post block is pinned to `l`). Under the DID model
`β̂_pre = δ_pre`, `β̂_post = τ_post + δ_post`, so `E[θ̂ | δ=0] = l'τ_post` regardless of
`w_pre` (unbiased at δ=0). The entire bias is the trend term:

    bias(δ) = w_full' δ.

### 2.3 Consistency equalities ⇒ p ≥ 2 is an identifiability condition

`Δ^SD` is invariant under adding any affine `δ = a + b·t` (its lineality space). For the
worst-case bias to be **finite**, the bias functional must vanish on that space:

    w_full' 1 = 0,    w_full' t = 0.

Two linear equalities on `w_pre`. This makes the pre-period requirement **structural,
not heuristic**: ΔRM with few pre-periods is merely *unstable*; ΔSD with `p < 2` is
*non-identifiable* (infeasible to bound bias). Guard `HONEST_SD_INSUFFICIENT_PERIODS`
carries severity = mathematically-infeasible, not a warning.

### 2.4 Worst-case bias = exact L1 dual (tight, not conservative)

Because §2.3 forces `w_full ⊥ ker(A_D)`, i.e. `w_full ∈ col(A_D')`, and `A_D'` is full
**column** rank (`T−2`), the system `A_D' z = w_full` has a **unique** closed-form
solution

    z = B · w_full,    B = (A_D A_D')⁻¹ A_D    (constant (T−2)×T matrix).

The support function of the L∞ second-difference ball is then exactly

    maxBias(w_full) = sup_{‖A_D δ‖_∞ ≤ M} w_full' δ = M · ‖z‖_1 = M · ‖B w_full‖_1.

**L1 is the exact dual of the L∞ ball — this is tight, no extra conservativeness.** The
only residual conservativeness is the folded-normal CI's own, which is intrinsic to an
honest CI. (`B` is **never** formed via matrix inverse; computed via Cholesky `solve` of
`(A_D A_D')`.)

`z` is a **deterministic linear map**, eliminated from the optimization. This removes the
primal-dual coupling / nullspace-drift risk entirely: the solver sees a pure QP with
linear inequalities.

### 2.5 Per-h convex QP

For a candidate worst-case-bias bound `h`:

    minimize    w_full' Σ w_full
    over        w_pre ∈ R^p,  u ∈ R^{T-2}
    subject to  w_full = (−w_pre, l)
                w_full' 1 = 0,  w_full' t = 0          (consistency)
                −u ≤ B w_full ≤ u                       (L1 linearization)
                1' u ≤ h / M                            (bias ≤ h)

Convex QP (Σ PSD, linear constraints), solved with SciPy. `minVar(h)` = optimal value;
clamp small negatives to 0 (rounding).

### 2.6 Folded-normal critical value & outer h-search

Half-length as a function of `h`:

    hl(h) = sqrt(minVar(h)) · c_α( h / sqrt(minVar(h)) )

where `c_α(t)` = the `(1−α)` quantile of the folded normal `|N(t,1)|`, i.e. the root of
`Φ(c − t) − Φ(−c − t) = 1 − α` (Brent). `t(h)` is **not** monotone in `h`, so:

- `c_α(t)` is theoretically strictly increasing in `t`; implement via Brent root-find,
  **cache over the h-grid and enforce monotonicity** (`c(t_{i+1}) ≥ c(t_i)`) to kill
  solver-noise `argmin` jitter. (Enforcing monotonicity here corrects numerical noise,
  not the math — standard FLCI-literature practice.)

Mirror R's `h`-grid (`numPoints`, default ~100). FLCI `= [l'β̂_post − hl*, l'β̂_post + hl*]`,
`hl* = min_h hl(h)`.

### 2.7 Public engine entry & guards

`flci(*, betahat, sigma, num_pre, num_post, l_vec, m, alpha, h_grid_points) -> dict`
(single-M FLCI), and `honest_sd(*, betahat, sigma, num_pre, num_post, l_vec, m_grid,
alpha, ...) -> dict` (mirrors `honest_rm`): M-grid loop + **breakdown M** (smallest M at
which the CI first includes 0) + guards.

Guards (all degrade-not-fail, never raise out of the adapter):
- `p < 2` → `HONEST_SD_INSUFFICIENT_PERIODS` (identifiability, §2.3)
- `q < 1` → reuse `HONEST_NO_POST_PERIODS`
- Σ non-finite / degenerate (eigvalsh) → reuse `HONEST_DEGENERATE_SIGMA`
- QP infeasible / non-convergent → `HONEST_FLCI_OPT_FAILED`
- `M = 0` → reduces to the classical CI `hl = sqrt(l'Σ_post l) · z_{1−α/2}` —
  **promoted to a regression self-check anchor** (FLCI → classical Gaussian CI limit).

### 2.8 Determinism statement (deliberately de-absolutized)

FLCI uses **no Monte Carlo, no bootstrap, no random sampling → no statistical source of
random error**. It is *not* claimed bit-for-bit deterministic: QP via SciPy is subject
to BLAS/LAPACK path, interior-point stopping rules, and float rounding (~ULP drift).
Therefore the **golden snapshot freezes only `status`/`artifacts`/`coef`, never FLCI
numbers**; numerical correctness is asserted by engine-layer oracle tests at tol 1e-6.

## 3. System integration

### 3.1 Frozen-snapshot semantics (adapter)

`engine/honest_did_adapter.honest_did_from_cs_dynamic` computes Σ, the per-coefficient
SEs, `num_pre`/`num_post`, `l_avg` and per-event `l` **once**, into a single frozen
snapshot, then runs **both** `honest_rm` (unchanged) and `honest_sd` (new) from that same
snapshot. Spec requirement: *both rm and sd are computed from one identical frozen
snapshot — no recompute between paths.* This forbids any future caching / lazy /
parallel execution from introducing a stale-Σ race between rm and sd.

### 3.2 M-grid scaling (data-adaptive) + clamp guard

ΔSD's `M` is an absolute curvature scale (unlike ΔRM's scale-free `M̄ ∈ [0,2]`). Default
grid is anchored to the noise scale:

    s = max_i sqrt(diag(Σ))_i          # sup SE over event-study coefficients
    if s < HONEST_SD_SCALE_FLOOR: s = HONEST_SD_SCALE_FLOOR   # clamp (decision B)
    m_grid = [0, 0.5, 1.0, 1.5, 2.0] · s

Clamp prevents near-degenerate small SE → M-grid collapse → over-narrow CI → numerical
instability. **Documented caveat:** this is data-adaptive normalization, so `M = 1` is
**not** the same physical quantity across datasets (curvature scale vs estimation-noise
scale). Accepted by design (this is an adaptive framework). Constants
`HONEST_SD_M_MULT`, `HONEST_SD_SCALE_FLOOR`, `HONEST_FLCI_H_POINTS` exposed in the runner
for test monkeypatching.

### 3.3 Runner wiring

The existing `honest_did` flag now produces **both** rm and sd blocks (one checkbox =
"give the complete picture", consistent with the fidelity-over-speed choice in v1.5.7).
Runtime: RM ~157s (1000-pt grid × LP, unchanged) + SD-FLCI ~seconds (small QP × h-grid,
no 1000-pt grid) ≈ unchanged overall. Whole honest block remains degrade-not-fail
(`except Exception` → status + reason, never fails the run). Run is async `_bg_run`.

### 3.4 JSON contract — nested `{rm, sd}` with failure taxonomy

`run_root/cs_did.json` `honest_did` block restructured (one-time contract change; FE +
golden guard updated together):

```
"honest_did": {
  "rm": { "status": "ok|degraded|not_available", "reason": <str|null>,
          "mbar_grid": [...], "post_average": {...}, "events": [...], "breakdown": <num|null> },
  "sd": { "status": "ok|degraded|not_available", "reason": <str|null>,
          "method": "FLCI", "m_grid": [...], "scale": <num>,
          "post_average": {lb, ub}, "events": [{event_time, lb, ub}, ...],
          "breakdown": <num|null> }
}
```

Both `rm` and `sd` are **always present** and carry an explicit
`status ∈ {ok, degraded, not_available}` + `reason`. Non-finite numbers → `null` (reuse
`_json_safe`). Rationale: explainable failure is the core value of an honest system —
the FE must never silently drop a panel.

### 3.5 Frontend — three-state rendering

`CSDiagnosticsCard` `HonestDidBlock` type → `{ rm: HonestRmResult, sd: HonestSdResult }`,
each with the `status`/`reason` taxonomy. Render two sub-panels:
- existing RM panel (now reads `rm.status`)
- new `cs-honest-did-sd-panel`: M-grid table (M / FLCI lb / ub), breakdown ("无突破"
  when null), microcopy explaining the smoothness restriction + FLCI minimum-length CI.

Per-panel three-state:
- `status="ok"` → full panel
- `status="degraded"` → collapsed panel + explanation
- `status="not_available"` → show the guard reason (e.g. `HONEST_SD_INSUFFICIENT_PERIODS`)

Renders only when `d.honest_did` present (degrade-safe), but **does not** silence on
sub-block failure — it surfaces the reason.

## 4. Testing & validation

- **Engine oracle (the real work):** R `findOptimalFLCI` +
  `createSensitivityResults(Delta="DeltaSD", method="FLCI")` across the M-grid →
  committed JSON oracle. Element-wise assert on `optimalHalfLength`, FLCI endpoints,
  `minVar(h)` trajectory, tol **1e-6** (optimizer-grade, not the 1e-11 of ΔRM).
  R HonestDiD 0.2.8 already installed — **no new R packages**.
- `honest_sd` entry test; M=0 anchor = classical CI (self-check, §2.7); breakdown
  detection both `lb>0` and `ub<0`.
- Adapter: sd block shape, frozen-snapshot (rm & sd same Σ), NaN-safety, guards
  (`p<2`, `q=0`, degenerate Σ), M-grid clamp.
- Wiring: end-to-end via runner with `honest_did=True` (monkeypatch small grid for
  speed); no-flag → no honest block (golden 0-drift); pre-guard fires before post-guard.
- **Golden:** existing `cs_did_honest` `_capture` freezes only status/artifacts/coef →
  numbers do not drift; the cs_did.json **structure guard** changes from flat to
  `{rm, sd}` (one-time update).
- Whole-feature adversarial review (Reviewer + Test&QA roles) before ship — the
  v1.5.6.1 / v1.5.7 lesson (each caught a real escape the per-task reviews missed).

## 5. Files touched (anticipated)

- `backend/workbench/engine/honest_did.py` — `_create_sd_constraints`/`A_D`, `B` builder,
  `flci`, `_folded_normal_quantile` (cached/monotone), `honest_sd`, SD guards.
- `backend/workbench/engine/honest_did_adapter.py` — frozen snapshot, run rm+sd, nested
  `{rm, sd}` return with status/reason, M-grid scaling+clamp.
- `backend/workbench/econometrics/runner.py` — `HONEST_SD_M_MULT`,
  `HONEST_SD_SCALE_FLOOR`, `HONEST_FLCI_H_POINTS`; nested block assembly.
- `backend/workbench/.../diagnostics.py` — `_json_safe` already non-finite→null; verify
  nested structure passes through.
- `frontend/.../CSDiagnosticsCard.tsx` (+ types) — `{rm, sd}` + three-state rendering.
- `tests/` — engine FLCI oracle + `honest_sd` + adapter sd + wiring + nan-safety + M=0
  anchor; update cs_did.json structure guard; additive/updated golden.
- `tests/golden/`, oracle JSON fixtures.
- `docs/honest-did-howto.md` (+ ΔSD/FLCI section), `docs/v1.5.7.1-release-notes.md`.

## 6. Process

Own worktree `.worktrees/workbench-v1.5.7.1` off latest main (`c2a9c08`); rebuild venv +
`frontend/npm install`; gate via `./scripts/gate.sh` (never bare pytest). Per-task TDD +
two-stage review (spec then quality), golden 0-drift, commit each green task. Whole-
feature adversarial review before ship. `--no-ff` merge + tag `v1.5.7.1`, verify gated-
head vs merged-tree empty diff; push needs explicit per-version authorization; ask about
worktree cache cleanup after ship.

## 7. Design provenance

Approved over a 4-block brainstorm (engine math / decisions / QP formulation /
integration). Key validated decisions: ΔSD↔L1 is a *tight* duality (not conservative);
`p ≥ 2` is an identifiability condition, not a heuristic; `z` eliminated in closed form
(largest engineering win — removes nullspace-drift risk); FE failure taxonomy is
mandatory (explainable failure). Result is a two-track sensitivity engine: RM = legacy
test-inversion path, SD/FLCI = clean convex path.
