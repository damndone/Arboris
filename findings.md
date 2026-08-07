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
