# Workbench v1.5.8 — Sun-Abraham estimator-slot validation (design)

Date: 2026-06-19
Status: design approved (brainstorm), pending plan
Base: origin/main `1423e1d` (tag `v1.5.7.1`)
Predecessors: v1.5.6 Callaway-Sant'Anna (the `EffectEstimateBundle` contract), v1.5.7/v1.5.7.1 honest-DID (ΔRM + ΔSD/FLCI).

## 1. Goal & framing

This version is **not** "full Sun-Abraham." It is a deliberately minimal, faithful
Sun-Abraham (SA) interaction-weighted estimator whose purpose is to **validate the
"swap the estimator slot" hypothesis** the v1.5.6 architecture bet on: that an estimator
producing an `EffectEstimateBundle` of the same shape as Callaway-Sant'Anna (CS) inherits
the entire downstream — `cs_aggregate` (simple/dynamic/group/calendar + multiplier-bootstrap
sup-t bands), `cs_inference`, and honest-DID (ΔRM **and** the v1.5.7.1 ΔSD/FLCI) — for free.

**Success criterion (one sentence):** SA produces an `EffectEstimateBundle` isomorphic to
CS's, and the cell coefficients / cluster vcov / *balanced* dynamic aggregation validate
element-wise against `fixest::sunab`, and the honest-DID chain runs on SA's dynamic
aggregation for free → v1.5.8 succeeds.

**Architectural acceptance test (hard requirement):** `run_sa_did` must contain **no
estimator-specific downstream logic** beyond constructing the SA bundle; both CS and SA
go through one shared `_finalize_did_bundle`, and CS routed through it must be **golden
0-drift** (proven by empty-diff). If this cannot hold, the bundle is not the clean seam
the architecture claims — that finding is itself a valid (if negative) outcome to report.

### In scope
- Saturated SA TWFE: `y ~ unit FE + time FE + cohort × relative-time`, self-implemented
  within-OLS with an analytic influence function.
- Reference period = −1; reference cohort = never-treated, or last-treated when no
  never-treated cohort exists.
- Output an `EffectEstimateBundle` (estimator-agnostic contract).
- Reuse `cs_aggregate` / `cs_inference` / honest-DID (ΔRM + ΔSD/FLCI) **unchanged**.
- Element-wise oracle vs `fixest::sunab` (balanced + unbalanced), with a locked
  small-sample correction (`ssc`) so the vcov口径 matches the bare sandwich.
- Explicitly characterize the balanced/unbalanced aggregation-weight equivalence.

### Out of scope (deferred)
- DR / IPW / covariate double-robustness (that is CS's strength; SA classic is uncovariated).
- Flexible binned relative time; multiple reference-period strategies.
- A faithful unbalanced `observed_relative_period` aggregation weighting (the SA-specific
  path) — characterized here, built later only if needed.
- User-chosen `l_vec` honest-DID target selection (deferred again; its own later patch).
- Any large SA-specific UI; new honest-DID methods.

## 2. The estimator (`engine/sa_attgt.py`) — the linchpin

### 2.1 Saturated model
```
y_it = α_i + λ_t + Σ_g Σ_{e≠−1} β_{g,e} · 1{cohort_i = g} · 1{t − g = e} + ε_it
```
- `g` ranges over treated cohorts EXCLUDING the reference cohort (never-treated; or, when
  there is **no** never-treated group, the last-treated cohort used as the
  **normalization / reference cohort**). The reference cohort contributes **no interaction
  columns**. NOTE: the last-treated cohort is NOT a clean control after its own treatment
  begins — it serves only as the normalization baseline, and the **effective comparison
  window is determined by the support / collinearity rules** (§2.2), not by treating
  last-treated as if it were never-treated.
- `e` ranges over the relative times present in the data EXCEPT `e = −1` (the reference
  period). **Pre-period coefficients (`e < 0`, `e ≠ −1`) ARE estimated** and enter the
  bundle as cells with `event_time < 0` (honest-DID needs `num_pre`; parallel-trends viz
  needs the pre path).
- `β_{g,e} = CATT(g, g+e)`.

### 2.2 Fitting — exact two-way FE, unbalanced-safe
Design `D = [time dummies (drop one), interaction dummies]`. Entity-demean `y` and every
column of `D` (the within transform). Then OLS of demeaned `ỹ` on `D̃`. By Frisch-Waugh-Lovell,
the interaction block of the resulting coefficients equals the two-way FE coefficients
(entity-demeaning absorbs `α_i` exactly; time FE absorbed via the in-regression dummies).

**Unbalanced rule (locked):** entity-demeaning is computed over each entity's **actually
observed rows**, never over a balanced-padded panel. Do not pad to balance for any reason.

**Sparsity / memory (locked):** `D = [time dummies, cohort×relative-time dummies]` is huge
and ~all-zero on large panels. Construct `D` as a **sparse** matrix (`scipy.sparse`, not a
new dependency), entity-demean in sparse form, and only materialize a **dense `K×K` bread**
(`D̃'D̃` on the identified columns) after the crossproduct. Never form a dense `(NT)×P` design.

**No direct inverse (locked).** `(D̃'D̃)^{-1}` is mathematical notation only. Saturated SA
routinely yields empty cells / perfectly collinear columns / zero-support cohort×period
combinations. Solve via a rank-revealing method (QR or SVD / `np.linalg.lstsq`) with rank
detection. Record, in `diagnostics`:
- `dropped_cells` — (g,e) columns removed because of zero support (no observations).
- `collinear_cells` — (g,e) columns removed by rank deficiency / perfect collinearity.
- `support_zero_cells` — cohort×period combinations with no clean comparison.

**Dropped/collinear cells do NOT enter the bundle** (`estimates`, `influence_func`,
`cell_metadata`). Downstream must never see them as if they were identified CATTs. The
IF/coefficients use the pseudo-inverse on the **identified subspace** only.

### 2.3 Analytic influence function (the honest-DID命门)
Entity-level IF for the interaction coefficients:
```
ψ_i = (D̃'D̃)^{+} · Σ_t D̃_it · ε̂_it     (pseudo-inverse on the identified subspace)
```
Take the interaction-block rows → `influence_func` shape `(N, K)`. **Rows are
entity/cluster-level, NOT observation-level** (each `ψ_i` already sums over that entity's
`t`). Get this scaling wrong and honest-DID's Σ is silently wrong everywhere.

**IF scaling contract (locked — hard test, risk #2命门).** SA's `influence_func` MUST adopt
the *exact* scaling convention of `cs_attgt`'s `EffectEstimateBundle.influence_func` (read
it from the code and replicate — do NOT invent a parallel scaling), so the shared
`cs_aggregate` SE path and the honest-DID adapter (`Σ` built from `component_if`, the
v1.5.6 single-row / v1.5.7 `(S'S)/N²` cluster convention) are correct for SA with no
modification. A **hard test** pins it end-to-end: the bare clustered sandwich reconstructed
from `influence_func` (`influence_func.T @ influence_func`, or the bundle's documented
reconstruction if the convention carries an extra `1/N`/`1/N²` factor — whichever
`cs_attgt` uses) **equals `fixest` bare cluster vcov (locked `ssc`, §2.4) to ~1e-6** for the
interaction coefficients. The implementation's FIRST step is to confirm the `cs_attgt`
scaling factor and write that one reconstruction test; only then build the rest. For
honest-DID Σ the bare form is required; the finite-sample-corrected SE (if ever shown to
users) is a separate scalar adjustment, never the validation口径.

### 2.4 Small-sample correction口径 (locked — risk #1 from review)
`fixest`'s default `vcov(cluster=~entity)` applies finite-sample / cluster corrections
(`G/(G−1)`, `(N−1)/(N−K)`). Our IF is a bare sandwich. Therefore the oracle MUST be
generated with the correction explicitly disabled:
`feols(..., ssc = ssc(adj = FALSE, cluster.adj = FALSE))` (and `vcov` taken with the same
`ssc`). This makes coefficient AND vcov comparisons bare-to-bare. The chosen `ssc` setting
is documented in the spec, the generator, and the release notes so the口径 is unambiguous.

## 3. Bundle mapping + reference encoding (`EffectEstimateBundle`)

Per identified `(g, e≠−1)` cell:
- `cell_metadata`: `{g, t: g+e, event_time: e, valid: True}` (+ any descriptive counts).
- `estimates[k] = β_{g,e}`; `influence_func[:,k] = ψ·,k`.
- `weights["n_g"]` = cohort entity counts; `aux = {n_total: N, row_cohort, row_cluster}`
  (mirror `cs_attgt`; never-treated counted in `N` and carried in `row_cohort` via the
  sentinel, so `cs_aggregate`'s `pg = n_g/N` is consistent).

**`valid` is a downstream filtering rule, not just a field (locked — risk #3):** only
cells that are valid AND identified AND non-reference AND non-collinear enter `estimates`
/ `influence_func` / aggregation. Reference period (`e=−1`), the reference cohort, and
dropped/collinear cells are **absent** (no placeholder rows). With this, `cs_aggregate`,
`cs_inference`, and `honest_did_from_cs_dynamic` consume the SA bundle unchanged.

**Column-mapping contract (locked — SA oracles die on column mapping, not math).** Do NOT
align engine columns to `fixest` by array position. Define a canonical coefficient key
`f"g={g}|e={e}|t={g+e}"`, sort cells by `(g, e)`, and map `fixest::sunab` coefficient names
to that key through an **explicit parser** (fixest names look like
`cohort::<g>:rel::<e>`-style strings — parse `g` and `e` out, never trust order). The
oracle fixture stores the parsed `(g,e)` key alongside each coefficient; every element-wise
test joins on the key, not the index.

## 4. Downstream reuse + unbalanced handling

### 4.1 `_finalize_did_bundle` (the architectural acceptance point)
Factor the current `run_cs_did` downstream — the four aggregations, sup-t bands, honest-DID
(ΔRM + ΔSD/FLCI), and `_json_safe` serialization (~80 lines) — into one estimator-agnostic
`_finalize_did_bundle(bundle, *, alpha, honest_did, seed, B, ...) -> dict`. `run_cs_did`
and `run_sa_did` both call it. This is a **behavior-frozen refactor**: CS routed through
`_finalize_did_bundle` MUST be golden 0-drift (prove by empty-diff of `cs_did.json` and
the golden snapshot before/after).

**Anti-fork guard (locked — protects the estimator-slot architecture).** `_finalize_did_bundle`
must contain **no estimator branch** — no `if estimator == "cs"/"sa"`, no estimator-name
parameter that switches behavior. A guard test enforces this (assert the function source has
no estimator-name conditional, mirroring the v1.5.4.5 namespace guard) so the seam cannot
silently grow estimator-specific logic later. All estimator-specific work lives in
`sa_attgt` / `cs_attgt`; everything past the bundle is uniform. (This is the operational
form of the §1 acceptance test.)

### 4.2 Unbalanced aggregation-weight characterization (risk #1)
Under **balanced panel + common event-time support across cohorts + no binning + the same
sample restriction as `sunab`**, `fixest::sunab`'s aggregation weight `N_{g,e}/Σ_h N_{h,e}`
equals `cs_aggregate`'s `n_g/Σ n_h` (each entity observed at every in-range relative period,
so `N_{g,e}=n_g`) → reuse is exact, validated to 1e-6 (proves the bet). The qualifier
matters: if some cohort's event-time support is incomplete, a mismatch may be a **support**
issue, not a weighting issue — the balanced oracle fixture must therefore have full common
support so the test isolates the weighting claim. On an **unbalanced**
panel they differ: `cs_aggregate` uses `did`-style `n_g` (cohort-size) weighting; `sunab`
uses observed-relative-period weighting. We reuse `cs_aggregate` (so SA's dynamic follows
the `did` weighting, consistent with the shipped CS path) and, when the panel is
unbalanced, attach an `interpretation_restrictions` / warning to the dynamic block:

> "This event-study uses `did`-style cohort-size (n_g) aggregation weights. In unbalanced
> panels this **may differ from `fixest::sunab`'s aggregation** (which weights by observed
> counts per relative period)."

**Do NOT over-promise a quantified difference** (risk #5): the warning states the weighting
difference qualitatively; no "X%" figure is computed (computing it would require building
the deferred observed-period diagnostic aggregate). Cell-level estimates, vcov, and the
honest-DID Σ all still reuse unchanged — only the dynamic aggregation *weighting* carries
this caveat.

## 5. Validation & oracle

R oracle = **`fixest::sunab`** (install `fixest` once; commit JSON fixtures; the test suite
never invokes R). All comparisons use the locked `ssc(adj=FALSE, cluster.adj=FALSE)`口径.

All element-wise tests **join on the canonical `(g,e)` key (§3 column-mapping), never on
array index.**
1. **CATT coefficients** `β_{g,e}` vs `sunab`, balanced & unbalanced, ~1e-8.
2. **Cluster vcov** of `β` vs `sunab` `vcov(cluster=~entity, ssc=...)`, ~1e-6 — the
   honest-DID "free inheritance"命门. This is the **IF scaling contract hard test** (§2.3):
   the vcov reconstructed from `influence_func` equals `sunab`'s bare cluster vcov.
3. **Dynamic aggregation** (reuse `cs_aggregate`) vs `sunab`'s aggregated event study:
   **balanced + common support + no binning + same sample restriction → 1e-6 (the bet)**;
   **unbalanced: characterize the difference** (assert the documented behavior, do not force
   equality).
4. **honest-DID chain:** SA dynamic → ΔRM + ΔSD/FLCI runs, finite, deterministic (reuses
   the already-validated v1.5.7/v1.5.7.1 engine; assert it executes and degrades-not-fails,
   not a new numeric oracle).
5. **Collinearity/empty-cell handling:** a fixture with a zero-support cohort×period → that
   cell is in `dropped_cells`/`support_zero_cells`, absent from `estimates`, and the run
   still completes.

## 6. Integration

- `engine/sa_attgt.py` (estimator → bundle), `engine/sa_spec.py` (`SASpecError`, ref-cohort
  selection never|last-treated, role validation).
- `econometrics/runner.py`: extract `_finalize_did_bundle`; `run_cs_did` calls it
  (behavior-frozen); new `run_sa_did` = `sa_attgt` → `_finalize_did_bundle`.
- `orchestrator/_model_types.py`: `sa_did` → continuous + metadata.
- `estimation.py`: register `_fit_sa_did` in CORE_PACK `model_handlers`, **explicit-only**
  (in MODEL_REGISTRY, NOT `defaults_by_y_type`).
- `engine/capabilities.py`: "SA" group, `requires` roles (entity/time/cohort), 4-way sync.
- `api.py` / `_run_workflow`: thread `sa_did` with the same `did_mode`/cohort/entity/time
  params as `cs_did` (mirror the cs wiring).
- Frontend: SA controls reuse `CSControls`' cohort/entity/time role assignment + the
  honest-DID checkbox; results reuse `CSDiagnosticsCard`'s aggregation + honest rendering
  (SA event-study card). No large SA-specific UI.
- `tests/fixtures/sa_did/` (fixest::sunab oracle, balanced + unbalanced, locked ssc);
  `docs/sa-did-howto.md`; `docs/v1.5.8-release-notes.md`.

## 7. Testing & process

- Self-implement + validate vs R (v1.5.6 philosophy); zero new Python deps (NumPy/SciPy).
  New R package `fixest` installed once to generate committed JSON oracles; `~/.R/Makevars`
  `CC=clang -std=gnu17` if R packages get rebuilt.
- Own worktree `.worktrees/workbench-v1.5.8` off main `1423e1d`; rebuild venv +
  `frontend/npm install`; gate via `./scripts/gate.sh` (never bare pytest). Per-task TDD +
  two-stage review (spec then quality), golden 0-drift, commit each green task **locally**.
- **Every implementer prompt explicitly forbids `git push`** (the v1.5.7.1 incident).
- Whole-feature two-role adversarial review (Reviewer + Test&QA) before ship.
- `--no-ff` merge + tag `v1.5.8`, verify gated-head vs merged-tree empty diff; push needs
  explicit per-version authorization; ask about worktree cache cleanup after ship.

### Risk register (review-ranked)
1. **Aggregation weights** — RESOLVED: reuse `cs_aggregate` + balanced oracle + unbalanced
   qualitative warning; faithful observed-period path deferred.
2. **OLS IF / cluster vcov** — the honest-DID命门; locked `ssc`口径 + element-wise vcov
   oracle (§2.3, §2.4, §5.2).
3. **Reference encoding** — `valid` as a downstream filter; reference period/cohort and
   collinear/empty cells absent, never placeholdered (§2.2, §3).

## 8. Design provenance

Approved over a brainstorm that first laid out the SA-vs-CS panorama, then settled: minimal
faithful SA (not full SA); self-implemented within-OLS + analytic IF (no black-box vcov);
reuse `cs_aggregate` with an unbalanced caveat; `_finalize_did_bundle` shared seam; `l_vec`
deferred. Five first-round corrections folded in: locked `ssc`口径, QR/SVD + collinearity
metadata, observed-row demeaning, `valid` as a downstream filter rule, and no over-promised
quantified unbalanced difference. Six second-round corrections folded in: (1) IF scaling
contract as a hard test with entity/cluster-level rows; (2) balanced-oracle qualifier
(common support + no binning + same sample restriction); (3) last-treated as
normalization/reference cohort, not a clean control; (4) explicit `(g,e)` column-mapping
contract (no positional alignment); (5) sparse `D` + dense `K×K` bread only after
crossproduct; (6) anti-fork guard test forbidding an estimator branch in
`_finalize_did_bundle`.
