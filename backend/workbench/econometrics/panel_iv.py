"""Panel and instrumental-variable estimators: fixed effects, PanelOLS and IV 2SLS."""

from __future__ import annotations

from .fit_support import (
    _formula_term,
    _ols_formula,
    _ensure_numeric_y,
    _ensure_numeric_x,
    _add_engine,
)
from typing import Any
import pandas as pd
import statsmodels.formula.api as smf
from .normalize import normalize_statsmodels_result
from .optional_deps import require_optional_dependency
from .ols_contract import _linearmodels_term, _normalize_linearmodels_result


def run_fixed_effects(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str | None,
    model_id: str,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    cat = categorical_x or set()
    terms = [_formula_term(column, column in cat) for column in x]
    terms.append(f"C({_formula_term(entity)})")
    if time is not None:
        terms.append(f"C({_formula_term(time)})")
    fitted = smf.ols(formula=_ols_formula(y, terms), data=frame).fit()
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "fixed_effects"
    return _add_engine(result), fitted


PANEL_COVARIANCE_VALUES = ("clustered", "robust", "unadjusted")


def _panel_covariance(covariance: str | None, cluster_col: str | None) -> str:
    """The covariance a panel fit uses: clustered unless another is chosen."""
    value = (covariance or "").strip().lower() or "clustered"
    if value not in PANEL_COVARIANCE_VALUES:
        raise ValueError(
            f"PANEL_COVARIANCE_UNSUPPORTED: unsupported covariance {value!r}; panel and DID "
            "models offer " + ", ".join(PANEL_COVARIANCE_VALUES) + "."
        )
    if cluster_col is not None and value != "clustered":
        raise ValueError(
            "PANEL_CLUSTER_WITHOUT_CLUSTERING: a cluster variable applies only to clustered "
            f"standard errors, not to {value!r}."
        )
    return value


def _panel_covariance_warnings(covariance: str) -> list[str]:
    if covariance == "robust":
        return [
            "Heteroskedasticity-robust standard errors that ignore the clustering by entity are not "
            "consistent with a fixed number of periods (Stock & Watson 2008); use them only to "
            "reproduce earlier work. The default clusters by entity, as Stata's xtreg, fe vce(robust)."
        ]
    if covariance == "unadjusted":
        return [
            "Conventional standard errors assume independent, homoskedastic errors; within an entity "
            "the errors are usually correlated over time."
        ]
    return []


def _panel_estimation_rows(data: pd.DataFrame, columns: list[str], cluster_source: str) -> pd.DataFrame:
    """The rows the fit uses: complete in the model's columns and the cluster variable."""
    if cluster_source not in data.columns:
        raise ValueError(
            f"PANEL_CLUSTER_COLUMN_MISSING: the cluster variable {cluster_source!r} is not in the data."
        )
    return data.dropna(subset=[*dict.fromkeys([*columns, cluster_source])])


def _cluster_panel_fit(
    fitted: Any,
    data: pd.DataFrame,
    *,
    y: str,
    regressors: list[str],
    entity_effects: bool,
    time_effects: bool,
    cluster_source: str,
) -> Any:
    from .panel_inference import ClusteredPanelResult, PanelInferenceError, clustered_covariance

    entity_level, time_level = data.index.names[0], data.index.names[1]
    clusters = (
        pd.Series(data.index.get_level_values(entity_level), index=data.index)
        if cluster_source == entity_level else data[cluster_source]
    )
    try:
        inference = clustered_covariance(
            data,
            y=y,
            regressors=regressors,
            entity=pd.Series(data.index.get_level_values(entity_level)) if entity_effects else None,
            time=pd.Series(data.index.get_level_values(time_level)) if time_effects else None,
            clusters=clusters,
            cluster_variable=cluster_source,
            params=fitted.params,
        )
    except PanelInferenceError as error:
        raise ValueError(f"PANEL_CLUSTER_INFERENCE_FAILED: {error}") from error
    return ClusteredPanelResult(fitted, inference)


def run_panel_ols(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str | None,
    time: str | None,
    model_id: str,
    covariance: str = "clustered",
    cluster_col: str | None = None,
    *,
    time_effects: bool | None = None,
) -> tuple[dict[str, Any], Any]:
    """PanelOLS of y on x with entity and/or time fixed effects.

    ``time`` indexes the panel; ``time_effects`` (default: whenever ``time`` is
    given) decides whether it also gets fixed effects, so an entity-only fit
    keeps the real time order for its panel diagnostics.
    """
    time_effects = time is not None if time_effects is None else bool(time_effects and time is not None)
    if entity is None and not time_effects:
        raise ValueError(
            "PANEL_FIELDS_MISSING: PanelOLS requires at least an entity or time field."
        )
    covariance = _panel_covariance(covariance, cluster_col)
    if covariance == "clustered" and entity is None and cluster_col is None:
        raise ValueError(
            "PANEL_CLUSTER_ENTITY_REQUIRED: clustered PanelOLS requires an entity field "
            "or a cluster variable."
        )

    panel_module = require_optional_dependency(
        "linearmodels.panel",
        extra="panel",
        engine="linearmodels",
        model_type="panel_ols",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    cluster_source = cluster_col or entity
    if covariance == "clustered":
        data = _panel_estimation_rows(data, [y, *x], cluster_source)

    declared_entity = entity
    declared_time = time if time_effects else None
    index_cols: list[str] = []
    if entity is None:
        entity = "_panel_entity"
        data[entity] = "entity"
    index_cols.append(entity)
    if time is not None and not time_effects and data.duplicated([entity, time]).any():
        # Not a panel on this time column: keep the fit and drop the ordering.
        time = None
    if time is None:
        time = "_panel_time"
        data[time] = range(len(data))
    index_cols.append(time)
    data = data.set_index(index_cols)

    terms = ["1", *[_linearmodels_term(column) for column in x]]
    if index_cols[0] != "_panel_entity":
        terms.append("EntityEffects")
    if time_effects:
        terms.append("TimeEffects")
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    if covariance == "clustered":
        fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(cov_type="unadjusted")
        fitted = _cluster_panel_fit(
            fitted, data, y=y, regressors=list(x),
            entity_effects=index_cols[0] != "_panel_entity",
            time_effects=time_effects,
            cluster_source=cluster_source,
        )
    else:
        fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(cov_type=covariance)
    return (
        _normalize_linearmodels_result(
            fitted,
            model_id,
            "panel_ols",
            y_column=y,
            covariance=covariance,
            entity_col=declared_entity,
            time_col=declared_time,
            inference=getattr(fitted, "inference", None),
            warnings=_panel_covariance_warnings(covariance),
        ),
        fitted,
    )


def run_iv_2sls(
    frame: pd.DataFrame,
    y: str,
    exog: list[str],
    endog: list[str],
    instruments: list[str],
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    if not endog or not instruments:
        raise ValueError(
            "IV_SPEC_INCOMPLETE: IV2SLS requires endogenous variables and instruments."
        )

    iv_module = require_optional_dependency(
        "linearmodels.iv",
        extra="panel",
        engine="linearmodels",
        model_type="iv_2sls",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, [*exog, *endog, *instruments])

    rhs_terms = ["1", *[_linearmodels_term(column) for column in exog]]
    iv_terms = " + ".join(_linearmodels_term(column) for column in endog)
    instrument_terms = " + ".join(
        _linearmodels_term(column) for column in instruments
    )
    formula = (
        f"{_linearmodels_term(y)} ~ {' + '.join(rhs_terms)} "
        f"[{iv_terms} ~ {instrument_terms}]"
    )
    fitted = iv_module.IV2SLS.from_formula(formula, data=data).fit(
        cov_type=covariance
    )
    return _normalize_linearmodels_result(fitted, model_id, "iv_2sls"), fitted
