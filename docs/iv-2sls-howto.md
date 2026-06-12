# IV / 2SLS — How-To

## What it's for

Instrumental-variables / two-stage least squares (IV/2SLS) estimates a causal
effect when a regressor is **endogenous** — correlated with the error term, so
OLS is biased. The classic case is omitted-variable bias: an unobserved factor
(e.g. innate ability) drives *both* the regressor (schooling) and the outcome
(wage). IV replaces the endogenous regressor with variation predicted by an
**instrument** — a variable that moves the regressor but affects the outcome
*only through* it.

## Running it in the GUI

1. Select model **IV / 2SLS** (it is explicit-only; auto mode never picks it).
2. Put **all involved variables** into **X**: exogenous controls + the
   endogenous regressor(s) + the instrument(s).
3. In the **IV role table**, tag the endogenous regressor(s) and the
   instrument(s). Everything left untagged is treated as an exogenous control.
4. The **order condition** requires `#instruments ≥ #endogenous`. With more
   instruments than endogenous regressors the model is *over-identified* (and
   the Sargan test becomes available).

## Using the example dataset

`examples/datasets/iv_returns_to_schooling.csv` is a small (300-row) simulated
returns-to-schooling setup with valid-by-construction instruments. Set it up as:

| Field | Value |
|-------|-------|
| y | `wage` |
| X | `age, educ, dist, momeduc` |
| endogenous | `educ` |
| instruments | `dist`, `momeduc` |
| exogenous control | `age` (left untagged) |

This is **over-identified**: 2 instruments (`dist` = distance to college,
`momeduc` = mother's education) for 1 endogenous regressor (`educ`). By
construction the unobserved `ability` term enters both `educ` and `wage` (so
OLS is biased), while the instruments enter only `educ` — never `wage`
directly — making them valid.

## Reading the three diagnostics

- **Weak-instrument first-stage F** — strength of the instruments. Rule of
  thumb: `F > 10` means strong; below that the IV estimate is unreliable.
- **Wu-Hausman endogeneity** — `p < 0.05` ⇒ endogeneity is real and IV is
  warranted; otherwise plain OLS suffices and is more efficient.
- **Sargan over-identification** — only when over-identified. Tests instrument
  exogeneity jointly; `p < 0.05` casts doubt that the extra instruments are
  truly excludable.

On the shipped example you should see first-stage `F ≈ 232` (strong),
Wu-Hausman `p ≈ 0` (endogenous, IV warranted), and Sargan `p ≈ 0.38`
(exogeneity not rejected).
