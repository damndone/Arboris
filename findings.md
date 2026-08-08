# Findings

## Current integration state

- This is the existing `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p7-multivariate` worktree, branch `workbench-v1.8.8-p7-multivariate`.
- Baseline for the prior P7 work is commit `d032958`; it already contains the standalone PCA/EFA/Cronbach alpha pack and its tests.
- Claude's worktree `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8` is at `baab593` with an uncommitted change only in `backend/workbench/agent/workflow_contracts.py` at kickoff; those paths remain protected.

## Existing patterns to reuse

- `backend/workbench/engine/packs/multivariate/common.py` provides numeric complete-case preparation, stable pack errors, and JSON-native conversion.
- `backend/workbench/contracts/model/multivariate.py` provides the versioned result envelope and closed operation IDs for the existing C pack.
- Existing dependencies include pandas, NumPy, SciPy, and statsmodels; no new dependency should be introduced.
- `backend/workbench/contracts/model/time_series_diagnostics.py` is an existing diagnostics C1 contract owned by a separate line; the new model kernel uses a new `time_series_pack.py` contract instead of editing it.

## Design findings

- Clustering must make scale, distance/linkage, cluster-count policy, random seed, iteration caps, and assignment-output bounds explicit.
- Discriminant analysis must make class labels, priors, covariance regularization, and evaluation split explicit; singular covariance is a hard error unless regularization is declared.
- Time-series kernels must not sort or infer frequency silently. ARIMA/SARIMA orders, VAR lag, deterministic trend, and Granger direction are explicit. Unit-root and ACF/PACF diagnostics are evidence, not autonomous model-selection commands.

## Phase 2 design findings

- statsmodels 0.14.6 exposes `coint_johansen`, `VECM`, IR standard errors, and VAR stability helpers; no new Python dependency is required.
- Rscript is available with base R and MASS, but `vars` and `FactoMineR` are unavailable. CA oracle coverage therefore uses base-R SVD; time-series oracle coverage uses direct statsmodels reference calls.
- `VARResults.is_stable()` is available on the wrapper, while `VARResults.roots` are inverse characteristic roots; stability evidence will report companion eigenvalues explicitly to avoid root-convention ambiguity.
- VECM rank must be derived before fitting. A rank-zero Johansen result is not silently converted into a rank-one VECM.
- CA/MCA will use a shared SVD core. MCA output will identify itself as `indicator_ca` and will not claim corrected inertia.

## Stage 10 design findings

- MANOVA belongs in the existing multivariate result envelope, while power analysis and categorical tests need independent envelopes because their inputs are not multivariate column selections.
- The installed statsmodels 0.14.6 exposes `MANOVA.from_formula`, `FTestAnovaPower`, `TTestIndPower`, `NormalIndPower`, and McNemar support; no dependency installation is required.
- Runtime formula construction must quote column names and must not accept arbitrary formula text from a future Agent.
- Power analysis must solve exactly one declared unknown and retain the effect-size convention in the result; sensitivity grids must be explicit and bounded.
- Categorical tables must be finite, non-negative integer counts. A 2x2 McNemar table with no discordant pairs is a rejection, not a zero statistic.

## Stage 10 verification findings

- MANOVA uses quoted structured terms rather than accepting arbitrary formula text; term-ID collisions fail closed, residual response degeneracy is distinct from design singularity, retained positions are bounded, and statistic-specific ranges are checked.
- Power Analysis rejects nonfinite/oversized inputs at both contract and solver boundaries, requires one declared unknown, validates design-specific semantics, uses exact Cartesian sensitivity-grid signatures, and carries a SHA-256 evidence digest for result/grid readback.
- Cramér's V/McNemar reject counts that cannot be exactly represented by the float backend before conversion, preserve exact McNemar discordant counts, require operation-specific payload fields, and match a base-R oracle.
- The P7/new-module suite passed 171 tests with two known statsmodels Johansen ComplexWarnings; the adjacent Agent/workflow suite passed 81 tests with existing numerical/third-party warnings.
- No Claude-owned Agent/workflow/frontend path changed; these kernels remain unreachable from natural-language Agent until the later CapabilityContract/P1/P2 integration.

## Stage 11 design findings

- The installed environment has statsmodels 0.14.6, SciPy 1.18.0, NumPy 2.5.0, and pandas 3.0.4; `AnovaRM` and `statsmodels.stats.meta_analysis` are available without installing dependencies.
- R 4.6.0 has the `survival` and `lme4` packages, but not `pROC`, `metafor`, or `meta`; ROC and meta Oracles therefore use independent base-R formulas rather than unavailable packages.
- Statsmodels `AnovaRM` explicitly rejects between-subject effects; mixed ANOVA needs a separate balanced error-layer calculation and must not be falsely labelled as an AnovaRM result.
- Existing automatic `statistical_tests` already contains Mann-Whitney, Kruskal-Wallis, Wilcoxon, rank correlations, and variance/normality evidence; Stage 11 must not duplicate those functions.
- Existing `survival_cox` remains a separate model family. The new survival pack is limited to KM, log-rank, and RMST and must not modify Cox files.
- ROC accepts labels and scores only; meta-analysis accepts study-level effects/variances only. Neither module may create training splits, retrieve source studies, or call Agent/runtime code.

## Stage 11 verification findings

- RM-ANOVA uses explicit balanced long-form input, one within factor, optional single between factor, subject/error strata, GG/HF corrections, and R-validated Mauchly evidence. Mixed HF uses residual error degrees of freedom; two-level sphericity corrections are reported as not applicable.
- Survival uses pre-aggregated risk tables, R-compatible strict delayed-entry semantics (`entry < time`), explicit tie policy, log-domain underflow fail-closed behavior, exact integer/Fraction RMST where safe, and stable rejection for unsafe large-float tau or `entry == duration`. `survdiff` remains unavailable for delayed-entry counting-process Oracle checks in the installed R package.
- ROC separates exact rank AUC from bounded grid-sampled ROC/PR areas, protects score-only provenance through persisted envelopes, and never trains, cross-validates, or silently selects a threshold.
- Meta-analysis exposes fixed-effect, DerSimonian-Laird, and Paule-Mandel paths with explicit CI semantics, HKSJ support, converters, correction policies, bounded LOO evidence, recursive study-row validation, and digest-bound readback.
- Independent quality review concluded `QUALITY_APPROVED` for all four packs. Final local verification is 150 focused tests, 10 external Oracle tests, 171 adjacent P7 tests, and 81 Agent/workflow tests; no Claude-owned path changed.
- These are standalone evidence-bearing kernels only. Natural-language Agent reachability is intentionally deferred until the later CapabilityContract/P1/P2 integration wave, so no claim is made for browser, full gate, or end-to-end execution.

## Stage 12 design findings

- The P7 worktree already contains independent ANOVA post-hoc/statistical-test
  behavior, so the future multiple-comparison pack must be an explicit
  extension/adaptor rather than a duplicate implementation.
- No standalone bootstrap/permutation pack exists in the current engine. It can
  be added without touching the Agent, OperationRegistry, orchestrator, or
  existing model-family runtimes.
- Existing dependencies are sufficient: NumPy/SciPy provide random generation
  and numerical primitives; R is available for fixed-input Oracle checks. No
  dependency installation is required.
- A runtime callback or formula string would undermine the Agent safety
  boundary. The resampling kernel will use an immutable statistic-ID registry
  and keep future statistic additions code-reviewed and test-bound.
- Exact permutation is useful for small state spaces, but unrestricted
  enumeration is an allocation risk. The contract therefore exposes an exact
  state cap and reports exact versus Monte Carlo semantics.
- BCa is not a safe “best effort” fallback: insufficient or degenerate
  jackknife evidence must be a stable rejection, not an unlabelled percentile
  interval.

## Stage 12 isolation findings

- Formal line `v1-8-8-p7-extensions` was explicitly rescoped through
  `scripts/devline_control.py rescope-context` to include the five future pack
  directories/contracts/tests/docs while retaining all existing P7 paths.
- Claude-owned protected paths remain unchanged. The current worktree is
  `workbench-v1.8.8-p7-multivariate` at `a4bbd5f`; no source code was changed
  before the Stage 12 design/plan update.

## Stage 12 correction findings

- The user audit corrected the five-way inventory. `iv_2sls` and
  `iv_diagnostics.py` are already shipped; only GMM/expanded weak-instrument
  evidence remains. The v1.8.7 survey design already covers sampling weights,
  strata, PSU, FPC, five lonely-PSU policies, Taylor linearization, BRR,
  jackknife, bootstrap, and provided replicate weights. Existing statistical
  evidence covers Tukey, Bonferroni, `multipletests`, and effect sizes; only
  Scheffé/Games--Howell are new in that lane.
- `run_mice_imputation` has an `m` parameter, but the value is metadata-only:
  one `MICEData` object is iterated `max_iter` times, one parquet dataset is
  persisted, and the stage binds that one dataset as the model input. The
  current test suite passes while asserting `persisted_datasets == 1` and
  `pooled_estimates is False` for `m=2`.
- Fresh baseline evidence: MICE/config tests `26 passed`; survey design,
  composition, and wiring tests `38 passed` with 3 existing deprecation
  warnings; post-hoc/statistical-test tests `14 passed`; IV engine/spec/
  diagnostics tests `16 passed`. These greens do not refute the MI problem;
  they confirm that the tests do not yet assert Rubin pooling.
- Root cause is now traceable across the stage boundary: `run_mice_imputation`
  emits one file, `ImputationStage` reads one file into `ctx.data`, and
  `EstimationStage` calls the handler once. A fix must address generation,
  lineage, model pooling, and downstream diagnostic labelling together.
- The architecture is therefore split into a common replicate execution/
  provenance layer and distinct combiners. Rubin pooling, bootstrap intervals,
  permutation p-values, and survey covariance share audit boundaries but do not
  share a falsely generic formula.

## Stage 12/13 implementation findings

- The shared runner originally published aggregate provenance only. A typed
  `execute_and_combine` boundary was added so consumer packs can combine scalar
  evidence internally while `ReplicateBatch` and the public result remain free
  of replicate rows/values. The original `execute` behavior remains unchanged.
- MI generation now uses independent derived seeds per dataset, validates every
  requested dataset before writing any output, restores global NumPy RNG state,
  and preserves the established first-seed behavior for `m=1` compatibility.
- Rubin pooling is generic over aligned coefficient mappings and uses unrounded
  estimates/variances. OLS fit statistics and residual diagnostics are marked
  unavailable for the pooled result; carrying the first fit's metrics would be
  numerically misleading and was caught in review.
- Bootstrap exposes only closed statistic IDs and explicit percentile/basic/BCa
  semantics. BCa jackknife or endpoint degeneracy rejects; it never falls back
  silently. Permutation labels exact enumeration versus Monte Carlo plus-one
  p-values and enforces an exact state-space cap.
- The resampling result digest is content-bound to `{batch,result}` and both
  consumers use local NumPy generators. Base R 4.6 checks agree for the fixed
  quantile/SE and exact-combination Oracles.
- Final Stage 12/13 adjacent slice is 211 passed with 2 external R checks in the
  resampling subset; no Claude-owned path or survey mathematical core changed.

## Stage 14/15 implementation findings

- GMM is kept separate from the existing `iv_2sls` model family: the pack owns
  one-step/two-step weighting, heteroskedastic sandwich covariance, exact- versus
  over-identification status, Hansen J, and per-endogenous-variable weak evidence.
  The result deliberately labels weak-instrument output descriptive and does not
  manufacture an automatic Stock--Yogo threshold decision.
- The first GMM Oracle attempted to compare statsmodels' optimizer-based
  `IVGMM.fit` with a closed-form one-step estimator. That mismatch was resolved by
  using statsmodels `IV2SLS` for the one-step closed-form reference and `IVGMM` for
  the two-step reference.
- Games--Howell cannot use `statsmodels.libqsturng.psturng` as its evidence source:
  that public API floors upper-tail p-values at 0.001. A bounded direct
  Gauss--Legendre studentized-range tail is now used for finite df >= 2; df < 2
  uses an explicit SciPy fallback. Critical values use SciPy's inverse CDF.
- Games--Howell's public `standard_error` is the denominator of its studentized
  range statistic; Welch's unhalved SE is separately named. This prevents a
  report consumer from pairing a Welch SE with a studentized-range q statistic.
- Scheffé and Games--Howell remain separate named combiners, not a shared
  "Tukey-like" implementation. The current focused verification is GMM 11 tests
  and post-hoc 10 tests, including 2 base-R numerical checks; no survey kernel,
  Agent registry, or Claude-owned path changed.

## Stage 16 implementation findings

- The survey adapter is intentionally placed under `engine/replicate_combine`,
  not under `backend/workbench/survey`. It consumes `SurveyDesign`'s existing
  weight builders and a typed `EstimatorSpec`, so a future pack adds an estimator
  declaration rather than a new survey-family branch.
- The public adapter result contains only the base estimates, aggregate
  covariance, standard errors, design degrees of freedom, design structure,
  scale semantics, and bounded failure summary. Replicate rows and scalar values
  stay inside the runner and are commitment-bound only.
- Subpopulation rows remain in the survey replicate construction and are masked
  only at estimator refit time, preserving the existing design-internal
  subpopulation semantics. A hard replicate-cell allocation bound prevents a
  large provided-weight matrix from becoming an unbounded memory request.
- Stage 16 verification is 137 adapter/shared tests plus 33 existing survey
  engine/composition/wiring tests. The fixed R-generated jackknife and
  Hadamard-BRR references match; `backend/workbench/survey/**` is unchanged.

## Stage 17 closeout findings

- The final cross-pack regression passed 607 tests with 5 existing warnings. The
  relevant contracts, engines, pack tests, MI consumers, survey adapter, and
  existing survey regressions were exercised together.
- The protected Claude Agent/P0/P1/P2 paths and `backend/workbench/survey/**`
  are unchanged. The only scoped orchestrator change is the MI report-consumer
  boundary; it is not an Agent context seam.
- The runtime safety scan found no shell/R execution, arbitrary `eval`/`exec`,
  or import-path execution in the new runtime modules. Relevant-module compile,
  `git diff --check`, and formal FMS verification passed.
- This is a standalone kernel/contract/test completion. Agent/orchestrator/
  frontend reachability, native browser acceptance, full gate, merge, push, and
  release remain intentionally deferred until the P1/P2 integration wave.

## Stage 18 approved design findings

- The final extension batch is split into five independent packs so their
  numerical code, contracts, tests, and Oracles do not share mutable files.
  A small bounded P7 scope-metadata contract is the only sequential foundation.
- Every new completed result must expose `estimand`/input semantics,
  assumptions, limitations, not-claimed statements, and unsupported extensions
  as bounded JSON-safe fields. This prevents an Agent or report consumer from
  turning a valid statistic into a broader unsupported claim.
- GLM extension scope excludes the already-shipped Negative Binomial model and
  adds only zero-inflated, hurdle, and Beta regression semantics. Model choice
  remains explicit; zero counts do not trigger automatic selection.
- Spatial scope is global Moran's I, Geary's C, Getis--Ord, explicit weight
  policies, and permutation inference. Spatial lag/error regression, local
  hotspot scans, and learned adjacency are deferred.
- Matching and Synthetic Control are evidence packs with explicit identifying
  assumptions and quality diagnostics. Common support, balance, donor-pool
  feasibility, and pre-fit quality are gates; no unconditional causal claim is
  emitted.
- Stage 18 is the P7 freeze boundary. Once its contracts/Oracles/adversarial
  tests and protected-path/FMS checks pass, further statistical families must
  be planned as a separate line after P1/P2 integration rather than appended to
  this worktree indefinitely.

## Stage 18 Oracle environment findings

- The worktree runtime has statsmodels 0.14.6 and SciPy 1.18.0. The installed
  statsmodels surface includes `ZeroInflatedPoisson`,
  `ZeroInflatedNegativeBinomialP`, and `BetaModel`.
- R 4.6.0 is available with base `stats`/`lmtest`/`car`, but the optional
  packages `pscl`, `betareg`, `spdep`, `MatchIt`, `Synth`, and `quadprog` are
  not installed. New Oracle tests must therefore use base-R/direct-formula
  references where possible, use statsmodels as a cross-check where it is an
  independent implementation, and skip optional-package checks explicitly.
- A missing optional R package is not evidence of correctness. The pack must
  record which Oracle actually ran and must never label a single runtime
  implementation as an external Oracle.

## Stage 18 Task 1 implementation findings

- `P7ScopeMetadata` is the only shared sequential foundation. It closes the
  six-field shape, bounds scalar/list text, converts internal sequences to
  tuples, and emits detached JSON-safe dictionaries. `make_p7_scope` is a
  construction helper, not an execution or registration surface.
- The scope-text safety policy rejects explicit local roots (`/etc`, `/tmp`,
  `/Users`, etc.), drive/UNC/home/relative path shapes, path-context tokens,
  filename-extension tokens, repeated backslashes, standalone import
  statements, `exec`/`eval`, and formula-only strings. It allows normal
  statistical prose such as `A/B`, `x/y`, `group/time`, `/api/v1`, `file:`
  semantics, and conceptual use of the word `import`.
- This is deliberately a bounded heuristic rather than a universal natural
  language path classifier. Its margin is fail-closed for the known unsafe
  shapes, not a claim that every possible path spelling is recognized. Future
  packs must keep the positive/negative boundary tests and add novel cases
  locally; they must not solve false positives by deleting the safety check or
  reverting to broad substring rejection.
- Task 1 focused verification: 33 passed under the worktree `.venv`, relevant
  modules compile, `git diff --check` passes, and independent spec/quality
  reviews both approved the final repeated-backslash policy. Commit: `02cded2`.

## Stage 18 final implementation findings

- The final batch is five extension areas but six independent packs. Matching and Synthetic Control are intentionally separate contracts because their data shapes, estimands, diagnostics, and future Agent prompts are different even though both are assumption-labelled causal evidence.
- All six packs use closed operation IDs and typed policy fields. Runtime code does not call R or a shell and does not accept formulas, callbacks, `eval`/`exec`, import paths, or dynamically selected estimator code. External implementations appear only in test Oracle fixtures.
- Nonparametric boundaries are deliberate: exact methods reject unsupported ties/zero conditions rather than silently changing semantics; permutation evidence is bounded and seeded; robust summaries are descriptive and do not replace a model-based estimand; complex survey rank variance and automatic post-hoc expansion are not implemented.
- GLM boundaries are deliberate: zero-inflated and hurdle processes are selected by the request, not by a zero-count heuristic; Beta outcomes must be strictly inside `(0, 1)`; offsets/formulas/random effects/automatic model comparison are out of scope; nonconvergence and unsafe linear predictors fail closed. Hurdle negative-binomial positive-process uncertainty is approximate and must be labelled as such by future consumers.
- Diagnostic boundaries are deliberate: the request carries design/residual/fitted semantics and the typed `run_model_diagnostics` entry point rejects a raw operation-string call. Outputs are evidence for one diagnostic at a time and never a composite validity score; high-dimensional, cluster-robust, survey, nonlinear, and post-selection semantics require separate contracts.
- Spatial statistics are conditional on the declared graph. Row normalization, symmetry, zero diagonal, islands, negative weights, connected components, permutation count, and seed are explicit. Global statistics are not local hotspot evidence and are not spatial causal/regression coefficients.
- Matching has an important v1 margin that must remain visible: `distance_policy="logit"` currently controls propensity fitting/support reporting, but matching pairs use `standardized_covariate_euclidean_v1`. The result reports both `support_distance` and `match_distance`; future true propensity-score matching must introduce a separate typed geometry policy and new Oracle coverage before changing the claim. Likewise, `common_support_policy="trim"` is a declared boundary policy, not permission for silent row deletion; v1 rejects disjoint support and does not claim target-population trimming.
- Synthetic Control is a constrained simplex estimator with explicit sorted periods and donor pool. v1 rejects predictor matrices rather than substituting outcomes, and placebo output is descriptive evidence without an automatic p-value/significance label. Augmented SCM, ridge/elastic-net weights, automatic donor selection, interference adjustment, and probabilistic inference are future extensions.
- Oracle availability is part of the evidence record. Base R/direct formulas validated nonparametric, spatial, Matching, and Synthetic Control; statsmodels validated GLM and diagnostics. Optional `spdep`, `MatchIt`, and `Synth`/`quadprog` packages were absent and their checks remain explicit skips, not hidden claims.
- P7’s boundary is now reached: the remaining marginal value is in adapters, capability discovery, confirmation/audit, report rendering, and true end-to-end validation—not in continuing to append statistical families to this line. Any extension beyond these six packs requires a new scope, new Oracles, and an explicit post-P1/P2 decision.
