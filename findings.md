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
