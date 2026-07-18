# v1.7.3 LMM bounded feasibility spike

Status: **pass with warnings**. This is an environment feasibility record, not
Model Pack acceptance and not a release claim.

## Reproducibility boundary

- Worktree: `/Users/jiayuanren/项目规划/.worktrees/integration-v1.7.3`
- Interpreter: `/Users/jiayuanren/项目规划/.venv/bin/python`
- `statsmodels`: `0.14.6`
- Fixture: `tests/fixtures/models/linear_mixed_effects/known_truth.csv`
- Fixture SHA-256: `ba4017566369ffa29360101f94346f41e2e49e19d5d0fe873634633ce0295c8b`
- Formula: `score ~ C(arm, Treatment(reference='control')) * week + baseline_score`
- Random-effects formula: `1 + week`
- Optimizer boundary: `lbfgs`, `maxiter=200`, `disp=False`

The committed feasibility guard is:

```bash
PYTHONPATH=backend /Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/models/linear_mixed_effects/test_feasibility.py -q
```

Observed on 2026-07-18: `1 passed, 4 warnings in 1.43s` (wall-clock command
time `1.90s`). No package was installed, upgraded, or otherwise changed.

## Observed fits

| Fit | `converged` | interaction estimate | fit duration |
| --- | --- | ---: | ---: |
| REML | `True` | `0.9404735706546893` | `0.155968s` |
| ML | `True` | `0.9404735706546876` | `0.101103s` |

The verified interaction parameter label is:

```text
C(arm, Treatment(reference='control'))[T.treated]:week
```

REML covariance estimate: intercept variance `0.32792061086690694`,
intercept/slope covariance `0.010480647024342591`, slope variance
`0.00033498311533255136`, residual scale `0.3276988581805301`.

ML covariance estimate: intercept variance `0.3134684431623855`,
intercept/slope covariance `0.010166599074239335`, slope variance
`0.00032972936385061675`, residual scale `0.3260483256773687`.

## Warning boundary

Both fits emitted the following warning pair:

```text
UserWarning: Random effects covariance is singular
ConvergenceWarning: The MLE may be on the boundary of the parameter space.
```

The test remains feasible because both estimators report `converged=True` and
the declared interaction parameter is present. The warning is deliberately not
treated as a clean statistical result: the later Model Pack must classify this
condition deterministically and may offer only the locked,
confirmation-required `lmm.simplify_random_effects_v1` → `model.rerun` patch
when its deterministic eligibility conditions hold. It must not silently
simplify the random-effects structure, change the fit method, or infer a
comparison conclusion from this spike.

If the same bounded command later fails, stop before Model Pack implementation
and ask for a scope/dependency decision; do not install or modify the shared
runtime as a workaround.
