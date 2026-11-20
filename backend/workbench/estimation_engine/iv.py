"""IV 2SLS on the native engine, returned as a result object with the parts of linearmodels'
IVResults the product reads (estimates, covariance, first-stage and specification tests, data).

Anything else is deliberately absent, so a new consumer fails loudly in the end-to-end
comparison against the reference instead of reading a guessed value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from ..checks.ar_cancellation import check_cancellation

from . import (
    AGREEMENT_ABSOLUTE, AGREEMENT_ABSOLUTE_PER_ROW, AGREEMENT_RELATIVE, FAST, FAST_ENGINE_NAME, REFERENCE,
    EngineSelection, native,
)

COVERED_COVARIANCES = frozenset(native.COVARIANCE_CODES)
CONSTANT = "Intercept"


@dataclass(frozen=True)
class TestStatistic:
    stat: float
    df: int
    df_denom: int | None = None

    @property
    def dist_name(self) -> str:
        return f"chi2({self.df})" if self.df_denom is None else f"F({self.df},{self.df_denom})"

    @property
    def pval(self) -> float:
        if not np.isfinite(self.stat):
            return float("nan")
        if self.df_denom is None:
            return float(stats.chi2.sf(self.stat, self.df))
        return float(stats.f.sf(self.stat, self.df, self.df_denom))


@dataclass(frozen=True)
class InvalidTestStatistic:
    reason: str
    stat: float = float("nan")
    pval: float = float("nan")
    dist_name: str | None = None


@dataclass(frozen=True)
class Variables:
    ndarray: np.ndarray
    cols: list[str]

    @property
    def shape(self) -> tuple[int, ...]:
        return self.ndarray.shape

    @property
    def pandas(self) -> pd.DataFrame:
        return pd.DataFrame(self.ndarray, columns=self.cols)


@dataclass(frozen=True)
class IVModel:
    dependent: Variables
    exog: Variables
    endog: Variables
    instruments: Variables
    weights: Variables
    notnull: np.ndarray
    has_constant: bool = True


@dataclass(frozen=True)
class FirstStage:
    diagnostics: pd.DataFrame


@dataclass
class FastIVResults:
    model: IVModel
    cov_type: str
    params: pd.Series
    cov: pd.DataFrame
    nobs: int
    ssr: float
    centered_tss: float
    first_stage: FirstStage
    wooldridge_regression: TestStatistic
    wooldridge_overid: TestStatistic | InvalidTestStatistic
    sargan: TestStatistic | InvalidTestStatistic
    wu_hausman_test: TestStatistic | None
    engine_selection: EngineSelection
    debiased: bool = False
    cov_config: dict[str, Any] = field(default_factory=dict)

    @property
    def df_model(self) -> int:
        return len(self.params)

    @property
    def df_resid(self) -> int:
        return self.nobs - len(self.params)

    @property
    def rsquared(self) -> float:
        return 1.0 - self.ssr / self.centered_tss

    @property
    def rsquared_adj(self) -> float:
        return 1.0 - (1.0 - self.rsquared) * (self.nobs - 1) / self.df_resid

    @cached_property
    def std_errors(self) -> pd.Series:
        return pd.Series(np.sqrt(np.diag(self.cov.to_numpy())), index=self.params.index, name="std_error")

    @cached_property
    def tstats(self) -> pd.Series:
        return self.params / self.std_errors

    @cached_property
    def pvalues(self) -> pd.Series:
        return pd.Series(2 * stats.norm.sf(np.abs(self.tstats.to_numpy())), index=self.params.index, name="pvalue")

    def conf_int(self, level: float = 0.95) -> pd.DataFrame:
        critical = stats.norm.ppf(1 - (1 - level) / 2)
        return pd.DataFrame({"lower": self.params - critical * self.std_errors,
                             "upper": self.params + critical * self.std_errors})

    def wu_hausman(self) -> TestStatistic:
        if self.wu_hausman_test is None:
            raise AttributeError("wu_hausman is computed for the unadjusted covariance only")
        return self.wu_hausman_test


def _coverage_gap(data: pd.DataFrame, columns: list[str], covariance: str) -> str | None:
    if covariance not in COVERED_COVARIANCES:
        return f"covariance {covariance!r} is not covered by the fast engine (covered: {', '.join(sorted(COVERED_COVARIANCES))})"
    if len(set(columns)) != len(columns):
        return "a column appears in more than one role"
    for column in columns:
        if column not in data.columns:
            return f"column {column!r} is missing"
        if not column.isidentifier():
            return f"column {column!r} needs formula quoting, which the fast engine does not reproduce"
        dtype = data[column].dtype
        if not (pd.api.types.is_integer_dtype(dtype) or pd.api.types.is_float_dtype(dtype)) or pd.api.types.is_bool_dtype(dtype):
            return f"column {column!r} is not an integer or float column"
    if not native.available():
        return "the native engine is not built (native/engine/build.py)"
    return None


def _first_stage(names: list[str], walds: np.ndarray, n_instruments: int, df_resid: int, covariance: str) -> FirstStage:
    rows = {}
    for name, wald in zip(names, walds):
        test = (TestStatistic(float(wald) / n_instruments, n_instruments, df_resid) if covariance == "unadjusted"
                else TestStatistic(float(wald), n_instruments))
        rows[name] = {"f.stat": test.stat, "f.pval": test.pval, "f.dist": test.dist_name}
    return FirstStage(pd.DataFrame.from_dict(rows, orient="index"))


def _full_rank_as_the_reference_requires(exog: np.ndarray, endog: np.ndarray, instruments: np.ndarray) -> bool:
    """linearmodels refuses a design whose regressors or instruments lack full column rank by
    numpy.linalg.matrix_rank; the same call on the same arrays refuses exactly the same designs."""
    regressors = np.column_stack([exog, endog])
    if np.linalg.matrix_rank(regressors) != regressors.shape[1]:
        return False
    del regressors
    all_instruments = np.column_stack([exog, instruments])
    return np.linalg.matrix_rank(all_instruments) == all_instruments.shape[1]


def _fit(data: pd.DataFrame, y: str, exog: list[str], endog: list[str], instruments: list[str],
         covariance: str, selection: EngineSelection) -> FastIVResults | None:
    columns = (y, *exog, *endog, *instruments)
    complete = np.empty((len(data), len(columns)), dtype=float, order="F")
    notnull = np.ones(len(data), dtype=bool)
    for target, column in zip(complete.T, columns, strict=True):
        check_cancellation()
        target[:] = data[column].to_numpy(dtype=float, na_value=np.nan)
        notnull &= ~np.isnan(target)
    del target
    if not notnull.all():
        complete = complete[notnull]
    check_cancellation()
    if not np.isfinite(complete).all():
        return None
    rows = len(complete)
    dependent, exogenous = complete[:, 0], complete[:, 1:1 + len(exog)]
    endogenous = complete[:, 1 + len(exog):1 + len(exog) + len(endog)]
    excluded = complete[:, 1 + len(exog) + len(endog):]
    exog_matrix = np.empty((rows, len(exog) + 1), order="F")
    exog_matrix[:, 0] = 1.0
    exog_matrix[:, 1:] = exogenous
    check_cancellation()
    full_rank = _full_rank_as_the_reference_requires(exog_matrix, endogenous, excluded)
    check_cancellation()
    if not full_rank:
        return None
    if covariance == "unadjusted":
        from ..engine.iv_diagnostics import _wu_control_projection

        # A valid point estimate need not identify its augmented Wu regression.
        # Admit only the native diagnostic domain before calling the ABI; do
        # not reclassify arbitrary native numerical errors as reference dispatch.
        _wu_control_projection(dependent, exog_matrix, endogenous, excluded)
    out = native.iv_2sls(dependent, list(exog_matrix.T), list(endogenous.T), list(excluded.T), covariance)
    if out is None:
        return None
    k_exog, k_endog, k_instruments = exog_matrix.shape[1], len(endog), len(instruments)
    k = k_exog + k_endog
    names = [CONSTANT, *exog, *endog]
    cov = out[k:k + k * k].reshape(k, k)
    cursor = k + k * k
    ssr, tss = out[cursor], out[cursor + 1]
    walds = out[cursor + 2:cursor + 2 + k_endog]
    first_df, regression, overid, sargan, wu_hausman = out[cursor + 2 + k_endog:]
    overidentifying = k_instruments - k_endog
    just = "Test requires more instruments than endogenous variables."
    unadjusted = covariance == "unadjusted"
    model = IVModel(
        dependent=Variables(dependent[:, None], [y]), exog=Variables(exog_matrix, [CONSTANT, *exog]),
        endog=Variables(endogenous, list(endog)), instruments=Variables(excluded, list(instruments)),
        weights=Variables(np.ones((rows, 1)), ["weights"]), notnull=notnull)
    return FastIVResults(
        model=model, cov_type=covariance, params=pd.Series(out[:k], index=names, name="parameter"),
        cov=pd.DataFrame((cov + cov.T) / 2, index=names, columns=names), nobs=rows, ssr=float(ssr), centered_tss=float(tss),
        first_stage=_first_stage(list(endog), walds, k_instruments, int(first_df), covariance),
        wooldridge_regression=TestStatistic(float(regression), k_endog),
        wooldridge_overid=TestStatistic(float(overid), overidentifying) if overidentifying else InvalidTestStatistic(just),
        sargan=(TestStatistic(float(sargan), overidentifying) if unadjusted and overidentifying else InvalidTestStatistic(just)),
        wu_hausman_test=(TestStatistic(float(wu_hausman), k_endog, rows - k_exog - 2 * k_endog) if unadjusted else None),
        engine_selection=selection,
    )


def comparable_numbers(fitted: Any) -> dict[str, float]:
    """Inference agreement, with stable survival tails for the reference statistics.

    linearmodels uses 1-cdf for some probabilities, losing small nonzero tails.
    Re-evaluate its declared distributions for comparison only; persisted reference
    results stay unchanged. This is not an independent probability oracle.
    """
    reference_result = not isinstance(fitted, FastIVResults)
    numbers = {f"params.{name}": float(value) for name, value in fitted.params.items()}
    numbers |= {f"std_errors.{name}": float(value) for name, value in fitted.std_errors.items()}
    for attribute in ("tstats", "pvalues"):
        numbers |= {f"{attribute}.{name}": float(value) for name, value in getattr(fitted, attribute).items()}
    if reference_result:
        numbers |= {f"pvalues.{name}": float(2 * stats.norm.sf(abs(value))) for name, value in fitted.tstats.items()}
    for column, values in fitted.cov.items():
        numbers |= {f"cov.{row}.{column}": float(value) for row, value in values.items()}
    for column, values in fitted.conf_int().items():
        numbers |= {f"conf_int.{row}.{column}": float(value) for row, value in values.items()}
    numbers |= {name: float(getattr(fitted, name)) for name in ("nobs", "df_model", "df_resid")}
    numbers |= {"rsquared": float(fitted.rsquared), "rsquared_adj": float(fitted.rsquared_adj),
                "wooldridge_regression": float(fitted.wooldridge_regression.stat)}
    for name, row in fitted.first_stage.diagnostics.iterrows():
        numbers[f"first_stage.{name}"] = float(row["f.stat"])
        numbers[f"first_stage.{name}.pval"] = float(row["f.pval"])
        numbers[f"first_stage.{name}.distribution:{row['f.dist']}"] = 1.0
        if reference_result:
            distribution, _, parameters = row["f.dist"].partition("(")
            degrees = [int(value) for value in parameters.rstrip(")").split(",")]
            numbers[f"first_stage.{name}.pval"] = float(
                stats.f.sf(row["f.stat"], *degrees) if distribution == "F" else stats.chi2.sf(row["f.stat"], *degrees))
    if np.isfinite(getattr(fitted.wooldridge_overid, "stat", np.nan)):
        numbers["wooldridge_overid"] = float(fitted.wooldridge_overid.stat)
    if fitted.cov_type == "unadjusted":
        from ..engine.iv_diagnostics import wu_hausman_statistic

        wu_hausman = wu_hausman_statistic(fitted)
        numbers["wu_hausman"] = float(wu_hausman.stat)
        if np.isfinite(getattr(fitted.sargan, "stat", np.nan)):
            numbers["sargan"] = float(fitted.sargan.stat)
    tests = {"wooldridge_regression": fitted.wooldridge_regression,
             "wooldridge_overid": fitted.wooldridge_overid}
    if fitted.cov_type == "unadjusted":
        tests |= {"sargan": fitted.sargan, "wu_hausman": wu_hausman}
    for name, test in tests.items():
        valid = np.isfinite(test.stat)
        numbers[f"{name}.valid"] = float(valid)
        if valid:
            probability = float(test.pval)
            if reference_result:
                probability = float(stats.chi2.sf(test.stat, test.df) if test.df_denom is None
                                    else stats.f.sf(test.stat, test.df, test.df_denom))
            numbers[f"{name}.pval"] = probability
            numbers[f"{name}.df"] = float(test.df)
            if test.df_denom is not None:
                numbers[f"{name}.df_denom"] = float(test.df_denom)
    return numbers


N_R_SQUARED_STATISTICS = frozenset({"wooldridge_overid", "sargan"})


def disagreements(mine: dict[str, float], reference: dict[str, float], nobs: int) -> list[str]:
    out = [f"{name}: unexpected fast field" for name in sorted(mine.keys() - reference.keys())]
    for name, value in reference.items():
        other = mine.get(name)
        absolute = max(AGREEMENT_ABSOLUTE, nobs * AGREEMENT_ABSOLUTE_PER_ROW) if name in N_R_SQUARED_STATISTICS \
            else AGREEMENT_ABSOLUTE
        matches = other is not None and np.isclose(other, value, rtol=AGREEMENT_RELATIVE, atol=absolute)
        if matches:
            if name in {"nobs", "df_model", "df_resid"} or name.endswith((".df", ".df_denom", ".valid")):
                matches = other == value
            elif name.startswith("std_errors."):
                matches = np.isclose(other, value, rtol=AGREEMENT_RELATIVE, atol=0)
            elif name.startswith("pvalues.") or name.endswith(".pval"):
                matches = (other == value if value == 0 else
                           0 < other <= 1 and np.isclose(other, value, rtol=AGREEMENT_RELATIVE, atol=0)
                           and abs(np.log(other) - np.log(value)) <= AGREEMENT_RELATIVE)
            elif name.startswith("cov."):
                _, row, column = name.split(".")
                scale = np.sqrt(reference[f"cov.{row}.{row}"]) * np.sqrt(reference[f"cov.{column}.{column}"])
                matches = abs(other - value) <= AGREEMENT_RELATIVE * scale
        if not matches:
            out.append(f"{name}: fast {other!r} vs reference {value!r}")
    return out


def _self_check_fixture() -> pd.DataFrame:
    rng = np.random.default_rng(20261103)
    rows = 400
    z1, z2, u, w = (rng.normal(size=rows) for _ in range(4))
    d = 0.6 * z1 + 0.4 * z2 + 0.5 * u + rng.normal(size=rows)
    return pd.DataFrame({"y": d + 0.3 * w + u * (1 + np.abs(w)), "d": d, "w": w, "z1": z1, "z2": z2})


@lru_cache(maxsize=1)
def _self_check() -> str | None:
    """Once per process the built library proves itself against linearmodels on a fixed fixture."""
    from linearmodels.iv import IV2SLS

    data = _self_check_fixture()
    for covariance in sorted(COVERED_COVARIANCES):
        fast = _fit(data, "y", ["w"], ["d"], ["z1", "z2"], covariance, EngineSelection(FAST, FAST_ENGINE_NAME))
        check_cancellation()
        reference = IV2SLS.from_formula("y ~ 1 + w + [d ~ z1 + z2]", data=data).fit(cov_type=covariance)
        check_cancellation()
        if fast is None:
            return f"self-check fit failed for covariance {covariance}"
        problems = disagreements(comparable_numbers(fast), comparable_numbers(reference), fast.nobs)
        if problems:
            return "the built native engine disagrees with the reference on its self-check fixture"
    return None


def fast_iv_2sls(data: pd.DataFrame, *, y: str, exog: list[str], endog: list[str], instruments: list[str],
                 covariance: str) -> tuple[FastIVResults | None, EngineSelection]:
    """The fast fit, or None with the reason the reference must run instead."""
    check_cancellation()
    gap = _coverage_gap(data, [y, *exog, *endog, *instruments], covariance)
    check_cancellation()
    if gap is not None:
        return None, EngineSelection(FAST, REFERENCE, gap)
    failure = _self_check()
    check_cancellation()
    if failure is not None:
        raise RuntimeError(f"native engine self-check failed: {failure}; rebuild and validate the native engine")
    selection = EngineSelection(FAST, FAST_ENGINE_NAME, build=native.build_record())
    from ..engine.iv_diagnostics import WuHausmanUnavailable

    try:
        fitted = _fit(data, y, exog, endog, instruments, covariance, selection)
    except WuHausmanUnavailable as error:
        check_cancellation()
        return None, EngineSelection(FAST, REFERENCE,
            f"the native homoskedastic Wu-Hausman diagnostic domain is unavailable ({error.reason}); "
            "the reference fits the point estimate and records the unavailable diagnostic")
    check_cancellation()
    if fitted is None:
        return None, EngineSelection(FAST, REFERENCE, "the native engine does not cover this fitting/diagnostic domain "
                                     "(collinear regressors, too few complete rows or non-finite values)")
    return fitted, selection
