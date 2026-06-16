# v1.5.6.1 — cs_did Variable-Clustering Completion (Design)

Date: 2026-06-16
Status: design approved (pending user review of this spec)
Base: `main` @ `3b8dce2` (v1.5.6 ship). Own worktree `.worktrees/workbench-v1.5.6.1`.
Predecessor: [[did-v1-5-6-execution-progress]] — DID Layer 2 (Callaway-Sant'Anna) shipped with
variable-clustering **deferred** behind a guard (`CS_CLUSTERING_DEFERRED`) and the dormant
scaffolding marked UNVALIDATED. This version makes that path correct and validated.

## 1. Problem

The v1.5.6 final adversarial review found that one-way variable-clustering by a non-entity
column **crashed** (entity-vs-cluster IF row mismatch). The fix at the time was to *defer*:
`estimate_att_gt` raises `CS_CLUSTERING_DEFERRED` whenever `cluster_var` is set, the
cluster-var UI selector was removed, and the default cluster=entity path (validated) ships.

Reading the dormant path shows the crash is not a small bug — it is a **structural
contradiction**: the inference pipeline carries two conflicting conventions for what a *row*
of an influence function (IF) is.

- `estimate_att_gt` (cs_attgt.py:403–411), when clustered, **collapses** `bundle.influence_func`
  to cluster rows `(n_clusters, K)`; the dataclass docstring even says "cluster rows".
- `_attach_influence` (cs_aggregate.py:187–217) operates **entity-level**: it builds `_wif`
  from the entity-level `row_cohort` (N rows) and forms `IF[:, ks] @ w + wif @ att`. With
  `IF` of shape `(n_clusters, K)` and `wif` of shape `(N, J)`, the two terms cannot add →
  the row-mismatch crash.
- `_se` (cs_aggregate.py:78–92) *already* does it the R way: keep IF entity-level, `rowsum`
  by `row_cluster` only at the final variance step.
- `run_cs_did` (runner.py:544) reshapes `overall_if` to `(G, 1)` with
  `G = influence_func.shape[0]`; this also breaks once those two row-counts diverge.

The backend wiring already exists end-to-end (api.py carries `cs_cluster_var` at :111/:161/
:291/:336); only the engine guard kills it and the UI selector was removed.

## 2. Goal & Non-Goals

**Goal.** Make one-way variable-clustering correct and validated to oracle precision:
entity-level IF aggregated by cluster in BOTH the analytical SE and the multiplier bootstrap;
remove the deferral guard with real validation; restore the cluster-var UI selector; fix the
`metadata.n_units` mislabel; validate against a deterministic clustered R oracle.

**Non-Goals (do not scope-creep).** Two-way / multi-way clustering; time-varying covariates;
propensity trimming beyond DRDID's 0.995; honest-DID under clustering. Each is left to a
later version. This version does exactly **one-way variable clustering + entity default**,
done right and verifiable.

## 3. Core design decision — a single row convention (R-faithful)

The IF is **entity-level everywhere** (`(N, K)`). Clustering is a `rowsum` applied *only* at
the two variance steps (the analytical `_se` and the multiplier bootstrap). This mirrors
`did`, which keeps `inffunc` at the individual level through `wif` / `get_agg_inf_func` and
clusters via `rowsum()` only inside `getSE` / `mboot`.

The grouping source of truth is `bundle.aux["row_cluster"]` — a length-N vector mapping each
entity row to its cluster id (== entity id when unclustered). `bundle.cluster_ids` becomes
purely descriptive; nothing downstream pivots on the IF being pre-collapsed.

### 3.1 Backend changes

**① `cs_attgt.py` — IF always entity rows.**
- Delete the `CS_CLUSTERING_DEFERRED` raise (:338) and the cluster-collapse block (:403–411).
  `bundle.influence_func` is always `(N, K)`.
- When `cluster_var` is set: resolve the cluster column → `aux["row_cluster"]` (per-entity
  cluster id). Replace the deleted guard with **real validation** (see §5): missing column,
  NaN in cluster column, every-entity-its-own-cluster (degenerate → identity), single cluster.
- `cluster_ids` retained for description only; `vcov_config["cluster_level"]` already carries
  the descriptive tag (entity vs column name).
- Remove the now-dead `cluster_influence` helper (:193–199) — superseded by the single
  convention.

**② `cs_aggregate.py:_se` — `n` normalization decided by the oracle.**
- The clustered branch already does `S = rowsum(entity_if, row_cluster)` then
  `sqrt(Σ_c S_c²) / n`. The single open question is whether `n` is **N (entities)** or
  **n_clusters**. Current code hard-codes `n = n_total = N`. R's `mboot`/`getSE` likely switch
  to `n = n_clusters` after the rowsum. **This is NOT hand-derived** — it is read off the
  clustered oracle (which emits the `n` it used) and the code is set to match, same discipline
  as the v1.5.6 IF (operational definition, fixture is the oracle).

**③ `cs_inference.py:multiplier_bootstrap` — per-cluster multipliers.**
- New keyword `clusters=None`. When given (length-N cluster ids aligned to `if_matrix` rows):
  `Psi = rowsum(if_matrix, clusters)` → `(n_clusters, K)`; draw one Mammen multiplier per
  cluster row; the SE/scale divisor follows the oracle's `n` convention. When `None`, behavior
  is byte-identical to today (per-entity) → unclustered golden 0-drift.

**④ `runner.py:run_cs_did`.**
- Pass `bundle.aux["row_cluster"]` into `multiplier_bootstrap` (overall and per-label).
- The `.reshape(G, 1)` is now safe because `G = N` always; keep but assert the invariant.
- `metadata`: `n_units` (entities, never overwritten), new `n_clusters`, new `cluster_level`
  ('entity' or the cluster column name).

## 4. Validation strategy (the scientific core)

R's `did` forces `bstrap=TRUE` whenever `clustervars` is set, so it has no native *analytical*
clustered SE, and a bootstrap SE cannot be matched element-wise across RNGs. We therefore build
a **deterministic CRVE oracle from R's already-validated influence functions** (user-chosen).

### 4.1 Fixture
- Add a `cluster` column to the existing `tests/fixtures/cs_did/panel.csv` (60 units →
  20 clusters of 3 units, **crossing cohorts** so within-cluster correlation actually moves the
  SE relative to entity clustering). The column does NOT enter any point estimate. The three
  existing oracles (`att_gt.json`, `aggte.json`, `drdid_inffunc.json`) do not read it →
  **zero drift** on the existing 1e-8 oracle tests.

### 4.2 Oracle generation (`generate_fixtures.R`, deterministic)
- Run `att_gt(..., bstrap=TRUE, clustervars="cluster")` and `aggte(...)`; extract the
  entity-level aggregation IFs `aggte$inf.function$overall.inf.func` and `$egt.inf.func`
  (already 1e-8-validated in v1.5.6) plus `att_gt`'s `$inffunc`.
- **In R**, `rowsum` each IF by `cluster`, apply the closed-form CRVE `sqrt(Σ_c S_c²) / n`,
  and also for att_gt cell columns. Emit `aggte_clustered.json` with per-aggregate
  `overall_se` / `se_egt` **and the `n` used** (so the Python side reads, not guesses, the
  normalization). Structured by est_method (dr/ipw/reg) like the existing `aggte.json`.

### 4.3 Python assertions
- **Point invariance:** with/without `cluster_var`, att_gt + all four aggregation point
  estimates equal to 1e-12 (clustering ⟂ point; pure regression, no R needed).
- **Analytical clustered SE:** `_se` clustered branch matches `aggte_clustered.json` to
  **1e-8/1e-10**. The `n` (N vs n_clusters) is taken from the oracle field.
- **Bootstrap (clustered):** (a) seed-determinism / golden 0-drift; (b) internal consistency —
  the bootstrap's own `sqrt(Σ Psi_cluster²)/n` equals the `_se` clustered value; (c) sanity —
  a coarser clustering yields a band ⊇ the entity band (positive within-cluster correlation
  widens). NOT compared element-wise to R's RNG.
- **Degenerate / hardening:** missing cluster column, NaN cluster values, single cluster,
  every-entity-its-own-cluster (→ identity, band element-wise equal to unclustered) — each a
  structured `CS_*` MODEL_FIT_FAILED or an identity pass. Added to `test_cs_did_hardening.py`.

## 5. Error handling

All bad clustering inputs raise a `CS_*`-prefixed `CSSpecError` so the estimation stage maps
them to structured `MODEL_FIT_FAILED` (never escape to `WORKFLOW_FAILED`):
- `CS_CLUSTER_COL_MISSING` — `cluster_var` not a column of the frame.
- `CS_CLUSTER_COL_NAN` — cluster column has missing values for in-sample entities.
- `CS_CLUSTER_SINGLE` — only one cluster (SE undefined / degenerate).
- Every-entity-its-own-cluster is NOT an error: it collapses to the entity identity and ships.

## 6. Frontend & reporting

- `runForm/CSControls.tsx`: **restore the cluster-var selector** — an optional column dropdown
  (empty = cluster by entity). Posts `cs_cluster_var` (api param already exists end-to-end).
- `runResult/CSDiagnosticsCard.tsx`: show `cluster_level` (entity or column name) + `n_clusters`;
  label the SE "cluster-robust". Degraded-safe (absent fields → entity defaults).
- `metadata`: `n_units` (entities) + `n_clusters` + `cluster_level`.

## 7. Golden & contracts

- Add ONE additive clustered cs_did golden (a run with `cs_cluster_var` set); the existing 18
  goldens/invariants/snapshots stay 0-drift.
- If exposing cluster-var requires a capabilities surface, do the 4-way sync (backend key /
  drift-guard / FE type / contract schema+sample). The covariance `clustered` option in
  capabilities is unrelated (panel covariance, not the CS cluster var) — do not conflate.

## 8. Files touched (anticipated)

Backend: `engine/cs_attgt.py`, `engine/cs_aggregate.py`, `engine/cs_inference.py`,
`econometrics/runner.py`; possibly `engine/capabilities.py` (only if a new surface is needed).
Tests: `tests/fixtures/cs_did/{panel.csv,generate_fixtures.R,aggte_clustered.json}`,
`tests/test_cs_inference.py`, `tests/test_cs_did_oracle.py` (or a new
`test_cs_did_clustering.py`), `tests/test_cs_did_hardening.py`, golden additive.
Frontend: `runForm/CSControls.tsx`, `runResult/CSDiagnosticsCard.tsx`.
Docs: `docs/cs-did-howto.md` (clustering note), release notes.

## 9. Gate (ship criteria)

Full backend suite green (`python -m pytest`), golden + invariants + snapshot 0-drift (existing
18 + 1 additive clustered), FE vitest green, `tsc --noEmit` 0, `./scripts/gate.sh` PASSED.
Whole-feature adversarial review before merge (the v1.5.5.1 lesson). Per-version push to main
requires explicit authorization; `--no-ff` merge + tag `v1.5.6.1`; verify gated-branch-head vs
merged-tree empty diff.

## 10. Why this de-risks Layer 3 (v1.5.7)

Layer 3 (Sun-Abraham / dCDH / honest-DID) reuses `EffectEstimateBundle` + `cs_aggregate` +
`cs_inference`. The single row convention (entity-level IF; clustering only at the variance
steps) is exactly the stable contract Layer 3 plugs into: SA/dCDH emit their IF as `(N, K)`
entity rows and inherit clustering + bands for free. Fixing the contradiction now means Layer 3
does not import the row-mismatch crash, and it satisfies part of the "re-verify the bundle
contract at Layer 3" hook left in the Layer 2 spec.
