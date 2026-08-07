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
