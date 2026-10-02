# Do-file Capability Completion (Workbench-first)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the six audited gaps between the reference VIXCLS Stata Do-file and the workbench, so the workbench implements the *whole* reference capability set. Agent capability follows afterwards (user-set priority: workbench first, then agent).

**Audit basis:** verified against a real VIXCLS run's artifacts (run `20260721_064801_125661_ab41a1af`), not from memory.

**Architecture:** All six are additive, backend-side enrichments of existing artifacts (`ts.transform_profile`, `ts.arma_candidates`/`ts.arma_selection`, `ts.final_diagnostics`, `ts.arma_vs_garch_comparison`) plus two new chart artifacts. No contract-breaking changes; existing fields keep their meaning so golden stays 0-drift.

**Tech Stack:** statsmodels (`adfuller` with `regression=` variants), scipy.stats (`shapiro`, normality), numpy; existing artifact writers.

---

### Gap 1 — ADF specification variants

`dfuller y, lags(0) / lags(5)` and `dfuller lvix, lags(5) drift / trend`.

**Files:** `backend/workbench/engine/packs/arma_garch/transforms.py` (or `diagnostics.py`), tests in `tests/models/arma_garch/test_input_and_transforms.py`.

- [ ] Add an `adf_variants` list to each transform profile: entries `{regression: "n"|"c"|"ct", lags: int|None, statistic, p_value, used_lag, n_obs}` covering constant-only, drift (constant), and trend (constant+trend), each at the auto lag and a fixed lag.
- [ ] Keep the existing scalar `adf_statistic` / `adf_p_value` unchanged (0-drift for existing consumers).
- [ ] Test: variants present, each finite or explicitly `status: "unavailable"`, and the legacy scalars unchanged.

### Gap 2 — AICc−AIC delta and rank agreement

Do-file's explicit "is AICc ≈ AIC?" table: `delta = aicc - aic`, `summarize delta` (max/mean), `rank_aic` vs `rank_aicc`, `corr`.

**Files:** `backend/workbench/engine/packs/arma_garch/arma.py` + the selection artifact writer in `runner.py`; tests in `tests/models/arma_garch/test_arma.py`.

- [ ] Add `aicc_minus_aic` to every ARMA candidate record (null when `aicc` is null).
- [ ] Add to `ts.arma_selection`: `information_criterion_agreement = {delta_max, delta_mean, rank_agreement_spearman, rank_agreement_identical}` computed over eligible candidates.
- [ ] Test: delta equals `aicc - aic` per candidate; ranking agreement is 1.0 when AIC and AICc order identically; nulls handled without crashing.

### Gap 3 — Normality test suite

Do-file runs `sktest` (skewness–kurtosis), `swilk` (Shapiro–Wilk), `sfrancia` (Shapiro–Francia).

**Files:** `backend/workbench/engine/packs/arma_garch/diagnostics.py`; tests in `tests/models/arma_garch/test_arma_garch_diagnostics.py`.

- [ ] Extend the `normality` payload to `{omnibus: {...existing...}, shapiro_wilk: {...}, shapiro_francia: {...}}` while **keeping the existing top-level `statistic`/`p_value`/`skew`/`kurtosis` keys** so current consumers and golden do not drift.
- [ ] Shapiro–Wilk via `scipy.stats.shapiro`; Shapiro–Francia as the Weisberg–Bingham W′ (correlation of ordered values with normal scores). Both must degrade to `status: "unavailable"` with a reason for n outside their valid range rather than raising.
- [ ] Test: all three reported on a normal sample (large p) and on a heavy-tailed sample (small p); explicit unavailable status for n < 3 and n > 5000 (Shapiro–Wilk's reliable range).

### Gap 4 — In-sample standardized-residual failure rate

Do-file: `gen fail = (abs(z) > 1.96)`, count and percentage.

**Files:** `backend/workbench/engine/packs/arma_garch/diagnostics.py` (or the conditional-series builder), tests alongside Gap 3.

- [ ] Add `standardized_residual_exceedance = {threshold: 1.96, count, rate, n}` to `ts.final_diagnostics`.
- [ ] Test: a standard-normal sample gives a rate near 0.05; a heavy-tailed sample gives a materially higher rate; threshold is reported, never hard-coded silently in the UI.

### Gap 5 — |y_t| vs conditional volatility overlay chart

Do-file: `twoway (line abs_y t) (line sd t, yaxis(2))`.

**Files:** `runner.py` chart writers; `tests/models/arma_garch/test_pack_runtime.py` (required-artifact set).

- [ ] Emit `ts.chart.abs_return_vs_volatility` with aligned `{index, abs_value, conditional_volatility}` series and an explicit `dual_axis: true` marker.
- [ ] Register it in the required-artifact inventory and the failure/interrupted manifest lists (so an incomplete run still reports it missing).
- [ ] Test: artifact present on a completed run, aligned lengths, node ownership = the volatility-selection stage.

### Gap 6 — In-sample PI bands, width difference, in-sample coverage

Do-file: full-history in-sample 95% PI for ARMA-only and GARCH, combined panel, `width_diff` summary, `cover_a`/`cover_g`.

**Files:** `forecast.py` comparison builder + `runner.py`; tests in `tests/models/arma_garch/test_forecast.py`.

- [ ] Add to `ts.arma_vs_garch_comparison`: `in_sample = {arma_garch: {coverage, average_width}, arma_only: {...}, width_difference: {mean, max, min}}` computed on the shared training window.
- [ ] Emit `ts.chart.in_sample_interval_comparison` carrying both bands plus the observed series.
- [ ] Test: coverage in [0,1] for both; `width_difference.mean` equals mean(garch_width − arma_width); bands align to the same rows.

---

### Final gate

- [ ] `PYTHONPATH=backend pytest tests/models/arma_garch tests/contracts/test_arma_garch_contracts.py tests/evaluation/arma_garch -q`
- [ ] `cd frontend && npm run typecheck && npm test -- --run`
- [ ] `bash scripts/gate.sh --full` → **golden must stay 0-drift** (all changes additive).
- [ ] Re-run the real VIXCLS benchmark and confirm every new field/chart is populated.

## Self-review

- **Coverage:** the six tasks map 1:1 onto the six audited gaps; every "already covered" item was verified against real artifacts and is intentionally untouched.
- **0-drift discipline:** every change is additive; existing keys keep their names and meanings, which is what keeps golden/snapshot green.
- **Deferred:** UI surfacing of the new fields/charts belongs to Slice B2 (inline SVG); agent vocabulary for these belongs to the agent slice, per the user's workbench-first ordering.
