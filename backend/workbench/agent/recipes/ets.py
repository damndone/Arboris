"""Bounded, read-only Agent projection for persisted ETS model results."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any

from ...contracts.model.ets import ETSResultContract


_MAX_PUBLIC_PARAMETERS = 24
_MAX_PUBLIC_DIAGNOSTICS = 8
_MAX_PUBLIC_EXCLUSION_REASONS = 16
_MAX_PUBLIC_STRING = 300
_MAX_PUBLIC_BYTES = 8192


def _unavailable(reason_code: str) -> dict[str, object]:
    return {"available": False, "reason_code": reason_code}


def build_ets_public_result_view(
    payload: Mapping[str, object],
    *,
    artifact_id: str,
    artifact_sha256: str,
) -> dict[str, object]:
    """Expose reportable ETS facts without returning source rows or previews."""

    result = payload.get("result")
    if not isinstance(result, Mapping):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    try:
        contract = ETSResultContract.from_dict(result)
    except (TypeError, ValueError, KeyError):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")

    params = contract.params
    exclusions = contract.exclusion_reasons
    if not isinstance(params, Mapping) or not isinstance(exclusions, Mapping):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    if any(
        not math.isfinite(float(getattr(contract, field)))
        for field in ("aic", "bic", "log_likelihood", "sigma2")
    ):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    if (
        type(contract.n_obs) is not int
        or contract.n_obs <= 0
        or type(contract.n_excluded) is not int
        or contract.n_excluded < 0
    ):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    if any(
        type(value) is not int or value < 0
        for key, value in exclusions.items()
        if isinstance(key, str)
    ) or any(
        not isinstance(key, str) or not key or len(key) > 120
        for key in exclusions
    ):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    if any(
        len(value) > _MAX_PUBLIC_STRING
        for value in (
            contract.endog,
            contract.fit_method,
            contract.result_identity,
        )
    ):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    if any(
        not isinstance(name, str)
        or not name
        or len(name) > 120
        or type(value) not in (int, float)
        or not math.isfinite(float(value))
        for name, value in params.items()
    ):
        return _unavailable("ETS_PUBLIC_RESULT_MALFORMED")
    parameter_names = sorted(params)
    public_params = {
        name: float(params[name]) for name in parameter_names[:_MAX_PUBLIC_PARAMETERS]
    }
    omitted_parameters = max(len(parameter_names) - len(public_params), 0)
    exclusion_items = sorted(exclusions.items(), key=lambda item: item[0])
    public_exclusions = dict(exclusion_items[:_MAX_PUBLIC_EXCLUSION_REASONS])
    omitted_exclusions = max(len(exclusion_items) - len(public_exclusions), 0)

    diagnostics: list[dict[str, str]] = []
    raw_diagnostics = payload.get("diagnostics")
    if isinstance(raw_diagnostics, (list, tuple)):
        for item in raw_diagnostics[:_MAX_PUBLIC_DIAGNOSTICS]:
            if not isinstance(item, Mapping):
                continue
            code = item.get("code")
            severity = item.get("severity")
            if isinstance(code, str) and code and isinstance(severity, str) and severity:
                diagnostics.append({"code": code[:120], "severity": severity[:32]})

    view: dict[str, object] = {
        "available": True,
        "projection": "forecast_summary",
        "model_type": contract.model_type,
        "series_column": contract.endog,
        "time_index_semantics": contract.time_index_semantics,
        "specification": contract.specification.to_dict(),
        "sample": {
            "n_obs": contract.n_obs,
            "n_excluded": contract.n_excluded,
            "exclusion_reasons": public_exclusions,
            "exclusion_reasons_omitted": omitted_exclusions,
        },
        "fit": {
            "convergence_code": contract.convergence_code,
            "fit_method": contract.fit_method,
        },
        "information_criteria": {
            "aic": float(contract.aic),
            "bic": float(contract.bic),
            "log_likelihood": float(contract.log_likelihood),
            "sigma2": float(contract.sigma2),
        },
        "parameters": public_params,
        "evidence_ref": {
            "artifact_id": artifact_id,
            "artifact_type": "model_result",
            "artifact_sha256": artifact_sha256,
            "result_identity": contract.result_identity,
        },
        "diagnostics": diagnostics,
    }
    omitted_sections: list[str] = ["raw_series", "sample_fingerprint"]
    if omitted_parameters:
        view["parameters_omitted"] = omitted_parameters
        omitted_sections.append("additional_parameters")
    diagnostic_count = (
        len(raw_diagnostics) if isinstance(raw_diagnostics, (list, tuple)) else 0
    )
    if len(diagnostics) < diagnostic_count:
        omitted_sections.append("additional_diagnostics")
    view["omitted_sections"] = omitted_sections
    encoded = json.dumps(
        view,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_PUBLIC_BYTES:
        return _unavailable("ETS_PUBLIC_RESULT_TOO_LARGE")
    return view


__all__ = ["build_ets_public_result_view"]
