# Joint ARMA--GARCH independent fixtures

VERIFICATION LEVEL: Stata 18 MP was run locally; no reference values are fitted
by Workbench or copied from its output. Seed is 181104. `generate.do` simulates
four normal processes with N=2540 or 1800, fits each with OPG/OIM/robust, and
exports double precision data, coefficients, covariance and conditional series.

Run the generator in a **new** output directory:

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python tests/fixtures/arma_garch_joint/generate_oracle.py tests/fixtures/arma_garch_joint/new_oracle_directory
```

`oracle_v1/` holds the accepted references and do-file log segment. TSVs are
Stata's direct output; JSONs reorder to frozen C1 names. Stata's actual matrix
stripe places ARCH/GARCH terms before the variance intercept; C1's public order
places omega before arch/garch. Both name orders are recorded in each JSON.
AIC/BIC JSON values use the documented formulas and are separately checked
against Stata `estat ic` in `auxiliary_v1/`.

`probe_default_v1/` confirms the defaults exactly equal explicit arch0(xb) and
arma0(zero), with all N=2540 observations. The initial conditional variance is
omega+(alpha+beta)*mean(innovations^2). `auxiliary_v1/` checks full-sample variance
priming, IC, GARCH(1,1) persistence/half-life, and Ljung--Box at lags 5/10/20 for
standardized innovations and their squares. CSV imports use asdouble and preserve
variable-name case.

`legacy_q0_payload.json` was captured before editing estimation/volatility,
from baseline 6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3. It is a byte-regression
anchor for the existing arch backend, not a statistical oracle. The capture
script documents the exact call.

`comparison_v1.json` stores all twelve Workbench/Stata parameter and inference
comparisons and timing measurements. Raw Stata logs remain local and ignored
because their startup headers include host license metadata; committed `.txt`
logs begin at the do-file command and preserve its complete output.
