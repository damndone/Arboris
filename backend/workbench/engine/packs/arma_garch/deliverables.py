"""Human-facing, deterministic exports for a completed ARMA--GARCH run.

The pack's typed ``ts.*`` artifacts are authoritative.  This module deliberately
projects those artifacts into a small report view and tabular workbook rather
than trying to reconstruct estimates from a generic regression result packet.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ....artifacts import read_json


def build_arma_garch_deliverables(run_root: Path) -> dict[str, Any]:
    """Return deterministic report and workbook views from registered ``ts.*`` artifacts."""
    artifacts = _artifact_payloads(run_root)
    contract = _as_mapping(artifacts.get("ts.analysis_contract"))
    data_audit = _as_mapping(artifacts.get("ts.data_audit"))
    data_quality = _as_mapping(data_audit.get("data_quality"))
    arma_selection = _as_mapping(artifacts.get("ts.arma_selection"))
    variance_selection = _as_mapping(artifacts.get("ts.volatility_selection"))
    parameters = _as_mapping(artifacts.get("ts.parameters"))
    metrics = _as_mapping(artifacts.get("ts.forecast_metrics"))
    forecast = _as_mapping(artifacts.get("ts.next_forecast"))
    diagnostics = _as_mapping(artifacts.get("ts.final_diagnostics"))

    arma = _as_mapping(contract.get("arma"))
    variance = _as_mapping(contract.get("variance"))
    model_label = (
        f"ARMA({_value(arma, 'p', 0)},{_value(arma, 'q', 0)})"
        f"–{str(_value(variance, 'model', 'garch')).upper()}"
        f"({_variance_p(variance)},{_variance_q(variance)})"
    )
    if arma.get("constant_mode") == "exclude":
        model_label += " · no mean constant"

    parameter_rows = _parameter_rows(parameters)
    diagnostic_rows = _diagnostic_rows(diagnostics)
    candidate_rows = _candidate_rows(artifacts.get("ts.arma_candidates"))
    volatility_rows = _volatility_rows(artifacts.get("ts.volatility_candidates"))
    rolling_rows = _rolling_rows(artifacts.get("ts.rolling_forecasts"))
    overview = [
        {"field": "Dataset", "value": contract.get("dataset_ref", "—")},
        {"field": "Time column", "value": contract.get("time_column", "—")},
        {"field": "Value column", "value": contract.get("value_column", "—")},
        {"field": "Transform", "value": contract.get("transform", "—")},
        {"field": "Analysis observations", "value": _first(data_audit, "analysis_row_count", "row_count", default=_first(data_quality, "finite_value_count", default="—"))},
        {"field": "Selected model", "value": model_label},
        {"field": "Estimation", "value": contract.get("estimation_strategy", "—")},
        {"field": "Innovation distribution", "value": contract.get("innovation_distribution", "—")},
        {"field": "Validation role", "value": arma_selection.get("validation_data_role", variance_selection.get("validation_data_role", "—"))},
        {"field": "Selection basis", "value": arma_selection.get("final_selection_basis", arma_selection.get("selection_basis", "—"))},
    ]
    acceptance = [
        {"measure": "Validation observations", "value": metrics.get("validation_n", "—")},
        {"measure": "Successful forecasts", "value": metrics.get("successful_forecast_n", "—")},
        {"measure": "MAE", "value": metrics.get("mae", "—")},
        {"measure": "RMSE", "value": metrics.get("rmse", "—")},
        {"measure": "Interval coverage", "value": metrics.get("interval_coverage", "—")},
        {"measure": "Average interval width", "value": metrics.get("average_interval_width", "—")},
        {"measure": "Validation was used for selection", "value": arma_selection.get("candidate_selection_used_validation", "—")},
    ]
    next_forecast_rows = [
        {"field": "Forecast origin", "value": _as_mapping(forecast.get("forecast_origin")).get("time", "—")},
        {"field": "Conditional mean", "value": forecast.get("conditional_mean", "—")},
        {"field": "Conditional variance", "value": forecast.get("conditional_variance", "—")},
        {"field": "Conditional volatility", "value": forecast.get("conditional_volatility", "—")},
        {"field": "Lower bound", "value": forecast.get("lower_bound", "—")},
        {"field": "Upper bound", "value": forecast.get("upper_bound", "—")},
        {"field": "Model scale", "value": forecast.get("model_scale", "—")},
    ]
    chart_artifacts = sorted(key for key in artifacts if key.startswith("ts.chart."))
    limitations = [
        "Forecast metrics are rolling, one-step evaluation results; they are not in-sample fit claims.",
        "When an MA term is present, the current sequential ARMA then ARCH/GARCH strategy is a workflow regression against the Stata joint likelihood, not a numerical reproduction of joint ARMA–GARCH maximum likelihood.",
    ]
    warnings = diagnostics.get("warnings") if isinstance(diagnostics.get("warnings"), list) else []
    if warnings:
        limitations.extend(str(item) for item in warnings)
    return {
        "report": {
            "report_kind": "arma_garch",
            "title": "ARMA–GARCH Volatility Report",
            "model_label": model_label,
            "overview": overview,
            "metrics": metrics,
            "parameters": parameter_rows,
            "diagnostics": diagnostic_rows,
            "next_forecast": next_forecast_rows,
            "selection": [
                {"stage": "Mean", "selected_candidate": arma_selection.get("final_selected_candidate_id", "—"), "basis": arma_selection.get("final_selection_basis", "—")},
                {"stage": "Variance", "selected_candidate": variance_selection.get("selected_candidate_id", "—"), "basis": variance_selection.get("selection_basis", "—")},
            ],
            "chart_artifacts": chart_artifacts,
            "limitations": limitations,
        },
        "tables": {
            "Overview": overview,
            "ARMA candidates": candidate_rows or [{"status": "No ARMA candidate table was registered."}],
            "Volatility candidates": volatility_rows or [{"status": "No volatility candidate table was registered."}],
            "Parameters": parameter_rows or [{"status": "No fitted parameter table was registered."}],
            "Diagnostics": diagnostic_rows or [{"status": "No diagnostics were registered."}],
            "Rolling forecasts": rolling_rows or [{"status": "No rolling forecast rows were registered."}],
            "Next forecast": next_forecast_rows,
            "Acceptance": acceptance,
        },
    }


def _artifact_payloads(run_root: Path) -> dict[str, Any]:
    index = _as_mapping(read_json(run_root / "artifacts_index.json"))
    payloads: dict[str, Any] = {}
    for record in index.get("artifacts", []):
        if not isinstance(record, Mapping):
            continue
        artifact_id = record.get("artifact_id")
        path = record.get("path")
        if not isinstance(artifact_id, str) or not artifact_id.startswith("ts.") or not isinstance(path, str):
            continue
        try:
            value = read_json(run_root / path)
        except (OSError, ValueError):
            continue
        payloads[artifact_id] = value.get("payload", value) if isinstance(value, Mapping) else value
    return payloads


def _as_mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _value(values: Mapping[str, Any], key: str, default: Any) -> Any:
    value = values.get(key, default)
    return default if value is None else value


def _variance_p(variance: Mapping[str, Any]) -> Any:
    return _value(variance, "garch_p", _value(variance, "arch_p", 0))


def _variance_q(variance: Mapping[str, Any]) -> Any:
    return _value(variance, "garch_q", 0)


def _first(values: Mapping[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if values.get(key) is not None:
            return values[key]
    return default


def _parameter_rows(parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component, key in (("mean", "mean_candidate"), ("variance", "selected_variance_candidate"), ("final variance", "final_fit")):
        values = _as_mapping(parameters.get(key))
        if component == "final variance" and values == _as_mapping(parameters.get("selected_variance_candidate")):
            continue
        for parameter, estimate in values.items():
            rows.append({"component": component, "parameter": parameter, "estimate": estimate})
    return rows


def _diagnostic_rows(diagnostics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project every registered residual diagnostic, not just the ADF row.

    The acceptance warnings a reader sees ("mean-residual autocorrelation",
    "rejects normality") are produced by Ljung--Box and Jarque--Bera.  Exporting
    only ADF shipped the verdict without the evidence behind it.
    """
    rows: list[dict[str, Any]] = []
    adf = _as_mapping(diagnostics.get("adf"))
    if adf:
        rows.append(
            _diagnostic_row(
                "ADF",
                adf,
                detail=_detail(("used_lag", adf.get("used_lag")), ("nobs", adf.get("nobs"))),
            )
        )

    ljung_box = diagnostics.get("ljung_box")
    for entry in ljung_box if isinstance(ljung_box, list) else []:
        entry = _as_mapping(entry)
        if not entry:
            continue
        # A Ljung--Box entry carries no status of its own, and the producer
        # emits None for a non-finite statistic; derive it rather than assume.
        computed = entry.get("statistic") is not None and entry.get("p_value") is not None
        rows.append(
            _diagnostic_row(
                f"Ljung–Box residuals (lag {_value(entry, 'lag', '—')})",
                entry,
                status="ok" if computed else "unavailable",
            )
        )

    arch_lm = _as_mapping(diagnostics.get("arch_lm"))
    if arch_lm:
        rows.append(
            _diagnostic_row(
                "ARCH-LM residuals",
                arch_lm,
                detail=_detail(
                    ("lag", arch_lm.get("lag")),
                    ("F", arch_lm.get("f_statistic")),
                    ("F p_value", arch_lm.get("f_p_value")),
                ),
            )
        )

    normality = _as_mapping(diagnostics.get("normality"))
    if normality:
        rows.append(
            _diagnostic_row(
                "Jarque–Bera residuals",
                normality,
                detail=_detail(
                    ("skew", normality.get("skew")),
                    ("kurtosis", normality.get("kurtosis")),
                ),
            )
        )
        for key, label in (("shapiro_wilk", "Shapiro–Wilk residuals"), ("shapiro_francia", "Shapiro–Francia residuals")):
            nested = _as_mapping(normality.get(key))
            if nested:
                rows.append(_diagnostic_row(label, nested))

    exceedance = _as_mapping(diagnostics.get("residual_exceedance"))
    if exceedance:
        rows.append(
            {
                "test": "Residual exceedance rate",
                "statistic": _value(exceedance, "rate", "—"),
                "p_value": "—",
                "status": "ok",
                "detail": _detail(
                    ("threshold", exceedance.get("threshold")),
                    ("count", exceedance.get("count")),
                    ("n", exceedance.get("n")),
                ),
            }
        )

    for warning in diagnostics.get("warnings", []) if isinstance(diagnostics.get("warnings"), list) else []:
        rows.append({"test": "warning", "statistic": "—", "p_value": "—", "status": str(warning), "detail": ""})
    return rows


def _diagnostic_row(test: str, values: Mapping[str, Any], *, status: str | None = None, detail: str = "") -> dict[str, Any]:
    return {
        "test": test,
        "statistic": _value(values, "statistic", "—"),
        "p_value": _value(values, "p_value", "—"),
        "status": status if status is not None else _value(values, "status", "—"),
        "detail": detail,
    }


def _detail(*pairs: tuple[str, Any]) -> str:
    return ", ".join(f"{label}={value}" for label, value in pairs if value is not None)


def _candidate_rows(payload: object) -> list[dict[str, Any]]:
    values = _as_mapping(payload).get("candidates", payload)
    return _rows(
        values,
        (
            "candidate_id",
            "p",
            "q",
            "constant",
            "converged",
            "stationary",
            "invertible",
            "nobs",
            "effective_sample",
            "log_likelihood",
            "parameter_count",
            "aic",
            "aicc",
            "bic",
            "failure_code",
        ),
    )


def _volatility_rows(payload: object) -> list[dict[str, Any]]:
    """Flatten ``searches[].candidates[]`` into one row per variance candidate.

    ``ts.volatility_candidates`` groups candidates under the mean candidate they
    were fitted against, so a one-level flatten only ever reached the search
    metadata and dropped every candidate on the floor.
    """
    searches = _as_mapping(payload).get("searches", payload)
    if isinstance(searches, Mapping):
        searches = list(searches.values())
    if not isinstance(searches, list):
        return []

    rows: list[dict[str, Any]] = []
    for search in searches:
        search = _as_mapping(search)
        if not search:
            continue
        selected_id = search.get("selected_candidate_id")
        shortlist = search.get("shortlist_candidate_ids")
        shortlist = shortlist if isinstance(shortlist, list) else []
        candidates = search.get("candidates")
        for candidate in candidates if isinstance(candidates, list) else []:
            candidate = _as_mapping(candidate)
            if not candidate:
                continue
            candidate_id = candidate.get("candidate_id")
            row: dict[str, Any] = {"mean_candidate_id": _value(search, "mean_candidate_id", "—")}
            row.update(
                {
                    key: candidate.get(key, "")
                    for key in (
                        "candidate_id",
                        "variance_model",
                        "p",
                        "q",
                        "distribution",
                        "estimation_strategy",
                        "joint_likelihood",
                        "mean_binding_status",
                        "converged",
                        "nobs",
                        "effective_sample",
                        "hold_back",
                        "log_likelihood",
                        "parameter_count",
                        "aic",
                        "aicc",
                        "bic",
                        "failure_code",
                    )
                    if key in candidate
                }
            )
            row["shortlisted"] = candidate_id in shortlist
            row["selected"] = candidate_id == selected_id
            row["selection_status"] = _value(search, "selection_status", "—")
            rows.append(row)
    return rows


def _rolling_rows(payload: object) -> list[dict[str, Any]]:
    """Project one row per rolling origin, flattening the nested row identity.

    ``forecast_origin`` and ``target`` are mappings, and the evaluated values are
    named ``observed_value``/``conditional_mean``/``interval_covered``.  Guessing
    flat ``actual``/``forecast``/``covered`` names matched only the two interval
    bounds, which was enough to defeat the fallback in :func:`_rows` and ship a
    two-column sheet that could not be reconciled against the reported RMSE.
    """
    values = _as_mapping(payload).get("rows", payload)
    if not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for value in values:
        value = _as_mapping(value)
        if not value:
            continue
        origin = _as_mapping(value.get("forecast_origin"))
        target = _as_mapping(value.get("target"))
        row: dict[str, Any] = {
            "origin_time": _value(origin, "time", "—"),
            "origin_row_id": _value(origin, "row_id", "—"),
            "target_time": _value(target, "time", "—"),
            "target_row_id": _value(target, "row_id", "—"),
        }
        row.update(
            {
                key: value.get(key, "")
                for key in (
                    "observed_value",
                    "conditional_mean",
                    "conditional_variance",
                    "conditional_volatility",
                    "lower_bound",
                    "upper_bound",
                    "lower_quantile",
                    "interval_covered",
                    "quantile_exception",
                    "fit_status",
                    "fit_method",
                    "model_scale",
                    "predictive_interval",
                    "parameter_uncertainty_included",
                    "warning",
                )
                if key in value
            }
        )
        rows.append(row)
    return rows


# Wall-clock timings and free-form convergence blobs are not reproducible across
# runs; a deliverable that embeds them stops being a deterministic projection.
_NON_DETERMINISTIC_KEYS = frozenset({"elapsed_seconds", "convergence_details"})


def _rows(values: object, preferred: tuple[str, ...]) -> list[dict[str, Any]]:
    """Project mappings onto ``preferred`` columns, falling back to scalars.

    A *partial* key match used to be indistinguishable from a full one: the
    projection kept whatever happened to match and the fallback below never
    fired, so an exporter written against a guessed schema silently shipped a
    truncated sheet instead of an obviously wrong one.  The projections above
    are now derived from real persisted payloads; the fallback stays for
    genuinely unknown shapes only.
    """
    if not isinstance(values, list):
        return []
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        row = {key: value.get(key, "") for key in preferred if key in value}
        rows.append(
            row
            or {
                str(key): item
                for key, item in value.items()
                if not isinstance(item, (dict, list)) and key not in _NON_DETERMINISTIC_KEYS
            }
        )
    return rows
