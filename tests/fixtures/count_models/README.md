# Count model verification artifacts

Authoritative inner-point native oracles are in `reference-v3/`: deterministic
NB2 (N=1200), NB1 (N=1500), fixed NB2 alpha=.5, and a Poisson sample (N=2000).
CSV values and native outputs retain 17 significant digits. Stata reads
`asdouble clear case(preserve)`; R fixes the GLM scale to 1. NB2 R covariance
uses the joint observed information; fixed-alpha GLM uses expected information.

`reference/` preserves the first generation attempt (invalid Stata ancillary
lookup); `reference-v2/` preserves the second attempt (R Pearson scale was not
yet explicitly set, and the original Poisson draw was slightly overdispersed).
They are investigation evidence and are never loaded as acceptance references.
They were preserved because lane instructions prohibit deleting artifacts.

`generate_oracle.py <fresh-directory-name>` generates all three data files,
runs Stata in fresh subdirectories through `tests/stata_oracle.py`, and invokes
`generate_oracle.R`. It refuses an existing output directory. The Stata log's
initial profile.do GUI error precedes the actual batch do-file; the actual
commands complete without a Stata error in `reference-v3/`.

`boundary_profile.R <reference-v3-path> <new-output.json>` stores an independent
R likelihood profile. `boundary_profile.json` records R's dnbinom values;
`boundary_profile_stable.json` additionally evaluates the identical likelihood
through integer probability products using log1p. R dnbinom itself loses up to
8e-7 in log likelihood at alpha=1e-8 here. The grid supports the boundary study
but does not prove a global constrained optimum, and no alpha or LR is clipped.

`glm_precision.R <admission-data.csv> <new-output.json>` retains R fits at
both epsilon=1e-14 and 1e-16. The second converges to the same optimum as
Workbench to about 2e-14; the historical epsilon=1e-14 coefficient differs by
1.056e-8. The strict 1e-8 test of that historical oracle is intentionally still
failing, rather than changing the reference, tolerance or fitted optimum.

`capture_evidence.py <new-output-name>` records exact Workbench/native errors,
score, information eigenvalues and convergence metadata. It does not modify
native oracles. Run native, numerical and performance jobs under the release's
shared `run_exclusive.py` lock, with `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
PYTHONPATH=backend` and the worktree's `.venv/bin/python`.
