"""Bounded, read-only Agent view for public ARMA-GARCH artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ...contracts.model.arma_garch import ArmaGarchAnalysisContract
from .arma_garch_vocabulary import LABELLING_INVARIANTS


_CANDIDATE_LIMIT = 8
# Per candidate table. The tool declares a 12,288-byte output budget and the
# non-candidate sections of a real summary run to roughly 6,000; two tables of
# this size leave usable headroom on either side.
_CANDIDATE_TABLE_BUDGET = 2000
_MEAN_FIELDS = (
    "candidate_id",
    "p",
    "q",
    "constant",
    "nobs",
    "converged",
    "stationary",
    "invertible",
    "parameter_count",
    "aic",
    "aicc",
    "bic",
    "failure_code",
    "warnings",
)
_VARIANCE_FIELDS = (
    "candidate_id",
    "variance_candidate_id",
    "display_name",
    "variance_model",
    "p",
    "q",
    "distribution",
    "nobs",
    "converged",
    "parameters_valid",
    "aic",
    "aicc",
    "bic",
    "failure_code",
    "warnings",
)


def _object(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _reportable(value: object) -> bool:
    """Is this field worth spending tool-output budget on?

    ``failure_code: null`` and ``warnings: []`` appear on every converged
    candidate and say nothing; across a bounded candidate table they were a
    large fraction of the payload. ``False`` and ``0`` are kept -- a candidate
    that did not converge, or an order of zero, is a real answer.
    """
    if value is None:
        return False
    return not (isinstance(value, (list, tuple, dict, str)) and len(value) == 0)


def _bounded_rows(
    values: object,
    *,
    allowed_fields: tuple[str, ...],
    max_bytes: int = _CANDIDATE_TABLE_BUDGET,
) -> tuple[list[dict[str, Any]], int]:
    """Bound a candidate table by rows *and* by serialized size.

    A fixed row count cannot bound a variable-width payload: on an automatic
    search the two candidate tables carried enough per-row detail to push the
    whole summary past the tool-output budget, and the Agent then received
    nothing at all rather than a shortened table. Rows are added while they
    fit; whatever is left is counted in ``candidate_rows_omitted``, and the
    full table stays in the artifact.
    """
    rows = _rows(values)
    bounded: list[dict[str, Any]] = []
    used = 0
    for row in rows[:_CANDIDATE_LIMIT]:
        projected = {
            field: row[field]
            for field in allowed_fields
            if field in row and _reportable(row[field])
        }
        size = len(json.dumps(projected, ensure_ascii=False)) + 1
        if bounded and used + size > max_bytes:
            break
        bounded.append(projected)
        used += size
    return bounded, max(len(rows) - len(bounded), 0)


def merge_model_options_patch(
    current: Mapping[str, object], patch: Mapping[str, object]
) -> dict[str, object]:
    """Apply a one-level patch, merging nested sections key-wise.

    This is the merge the rerun transport performs, reproduced here so a patch
    can be judged before anyone confirms it.
    """

    merged = dict(current)
    for key, value in patch.items():
        if not isinstance(key, str):
            raise TypeError("model_options patch keys must be strings")
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = {**dict(existing), **dict(value)}
        else:
            merged[key] = value
    return merged


def validate_arma_garch_model_options_patch(
    *,
    current_contract: Mapping[str, object],
    patch: Mapping[str, object],
) -> dict[str, object]:
    """Return the contract a patch would produce, or raise the pack's own error.

    Without this, an Agent-authored patch is only judged when the child run
    executes, so the user confirms a proposal that was never going to run and
    pays for it with a failed run. Judging it here turns that into a rejection
    the Agent can still act on.
    """

    hydrated = merge_model_options_patch(current_contract, patch)
    return ArmaGarchAnalysisContract.from_dict(hydrated).to_dict()


def normalize_arma_garch_recommended_action(
    *,
    contract: Mapping[str, object],
    action: Mapping[str, object],
) -> dict[str, object]:
    """Map pack action syntax onto the existing one-level rerun proposal seam."""

    operation = action.get("operation")
    if operation not in {"model.rerun", "graph.fork"}:
        raise ValueError("unsupported ARMA-GARCH recommended action")
    patch = action.get("patch", {})
    if not isinstance(patch, Mapping):
        raise TypeError("recommended action patch must be an object")

    source = dict(contract)
    normalized_patch: dict[str, object] = {}
    for key, value in patch.items():
        if not isinstance(key, str):
            raise TypeError("recommended action patch keys must be strings")
        current = source.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            normalized_patch[key] = {**dict(current), **dict(value)}
        else:
            normalized_patch[key] = value

    # The public pack diagnostic uses ``arma.q = 0`` as shorthand for the
    # supported joint-AR path. The frozen contract correctly forbids partially
    # fixed orders in auto mode, so expand that shorthand into the smallest
    # valid manual candidate instead of emitting an action that confirmation
    # would reject. GARCH(1,1) is already in the bounded public candidate set.
    proposed_arma = normalized_patch.get("arma")
    if (
        normalized_patch.get("estimation_strategy") == "joint"
        and isinstance(proposed_arma, Mapping)
        and proposed_arma.get("q") == 0
        and source.get("selection_mode") == "auto"
    ):
        normalized_patch["selection_mode"] = "manual"
        normalized_patch["arma"] = {
            **dict(proposed_arma),
            "p": proposed_arma.get("p")
            if isinstance(proposed_arma.get("p"), int)
            else 0,
            "q": 0,
        }
        proposed_variance = source.get("variance")
        if isinstance(proposed_variance, Mapping) and proposed_variance.get("model") == "auto":
            normalized_patch["variance"] = {
                **dict(proposed_variance),
                "model": "garch",
                "arch_p": None,
                "garch_p": 1,
                "garch_q": 1,
            }

    # Validate the exact payload that the existing one-level rerun merge will
    # produce. This prevents an Agent-facing suggestion from bypassing the pack
    # contract or relying on a deep-merge behavior the platform does not own.
    hydrated = {**source, **normalized_patch}
    ArmaGarchAnalysisContract.from_dict(hydrated)

    changes: dict[str, object]
    if operation == "model.rerun":
        changes = {"model_options": normalized_patch}
    else:
        reason = action.get("reason") or action.get("purpose")
        changes = {"reason": str(reason)[:1_000]} if reason else {}
    evidence_refs = action.get("evidence_refs", [])
    return {
        "operation": operation,
        "changes": changes,
        "evidence_refs": [
            item for item in evidence_refs if isinstance(item, str)
        ]
        if isinstance(evidence_refs, list)
        else [],
        "reason": action.get("reason")
        if isinstance(action.get("reason"), str)
        else None,
        "required_confirmation": True,
    }


def _recommended_actions(
    artifacts: Mapping[str, object], contract: Mapping[str, object]
) -> list[dict[str, object]]:
    audit = _object(artifacts.get("ts.data_audit"))
    actions: list[dict[str, object]] = []
    manifest = _object(artifacts.get("ts.artifact_manifest"))
    diagnostics = _rows(audit.get("diagnostics"))
    terminal_diagnostic = manifest.get("diagnostic")
    if isinstance(terminal_diagnostic, Mapping):
        diagnostics.append(dict(terminal_diagnostic))
    for diagnostic in diagnostics:
        for action in _rows(diagnostic.get("recommended_actions")):
            try:
                normalized = normalize_arma_garch_recommended_action(
                    contract=contract,
                    action=action,
                )
            except (KeyError, TypeError, ValueError):
                continue
            normalized["diagnostic_code"] = diagnostic.get("code")
            actions.append(normalized)
    return actions[:_CANDIDATE_LIMIT]


_COMPARISON_ROW_ID_FIELDS = (
    "locked_forecast_origin_row_ids",
    "locked_target_row_ids",
    "comparison_forecast_origin_row_ids",
    "comparison_target_row_ids",
)


def _bounded_comparison(comparison: Mapping[str, object]) -> dict[str, Any]:
    """Keep the conclusions; count the provenance row ids instead of listing them.

    On a real run these four lists are ~25,000 characters of row identifiers --
    three times the whole tool-output budget, so a live Agent turn asking for a
    time-series summary got `tool_output_budget_exceeded` and no summary at all.
    The ids matter for reproducibility and stay in the artifact; what the reader
    needs here is that the comparison ran over N locked common origins.
    """

    bounded = {
        key: value
        for key, value in comparison.items()
        if key not in _COMPARISON_ROW_ID_FIELDS
    }
    counts = {
        len(comparison[key])
        for key in _COMPARISON_ROW_ID_FIELDS
        if isinstance(comparison.get(key), (list, tuple))
    }
    if len(counts) == 1:
        bounded["locked_common_origins"] = counts.pop()
    elif counts:
        # Differing lengths would mean the locked and comparison sets diverged,
        # which is a fact worth surfacing rather than averaging away.
        bounded["row_id_counts_differ"] = sorted(counts)
    return bounded


def build_arma_garch_public_result_view(
    artifacts: Mapping[str, object],
) -> dict[str, object]:
    """Expose bounded persisted evidence; never calculate or return raw series."""

    report = _object(artifacts.get("ts.report"))
    contract = _object(artifacts.get("ts.analysis_contract"))
    artifact_manifest = _object(artifacts.get("ts.artifact_manifest"))
    terminal_diagnostic = _object(artifact_manifest.get("diagnostic"))
    if contract.get("pack_id") != "time_series.arma_garch":
        return {
            "available": False,
            "reason": "ARMA_GARCH_PUBLIC_ARTIFACTS_UNAVAILABLE",
        }
    if not report:
        return {
            "available": bool(terminal_diagnostic),
            "status": artifact_manifest.get("status"),
            "terminal_code": artifact_manifest.get("terminal_code"),
            "analysis_contract": contract,
            "diagnostic": terminal_diagnostic or None,
            "recommended_actions": _recommended_actions(artifacts, contract),
            "artifact_manifest": {
                key: artifact_manifest.get(key)
                for key in (
                    "status",
                    "terminal_code",
                    "complete",
                    "persisted_artifact_ids",
                    "missing_required_artifact_ids",
                )
                if key in artifact_manifest
            },
            "omitted_sections": ["raw_rows", "raw_artifact_payloads"],
        }

    mean_payload = _object(artifacts.get("ts.arma_candidates"))
    mean_rows = _rows(mean_payload.get("candidates"))
    bounded_mean, omitted_mean = _bounded_rows(
        mean_rows,
        allowed_fields=_MEAN_FIELDS,
    )
    volatility_payload = _object(artifacts.get("ts.volatility_candidates"))
    volatility_rows = [
        candidate
        for search in _rows(volatility_payload.get("searches"))
        for candidate in _rows(search.get("candidates"))
    ]
    bounded_volatility, omitted_volatility = _bounded_rows(
        volatility_rows,
        allowed_fields=_VARIANCE_FIELDS,
    )
    diagnostics = _object(artifacts.get("ts.final_diagnostics"))
    conditional = _object(artifacts.get("ts.conditional_series"))
    volatility = conditional.get("volatility")
    volatility_count = len(volatility) if isinstance(volatility, list) else 0

    return {
        "available": True,
        "analysis_contract": contract,
        "answer": report.get("answer"),
        "sample": _object(report.get("sample")),
        "estimation_semantics": _object(report.get("estimation_semantics")),
        "acceptance": _object(report.get("acceptance")),
        "warnings": list(report.get("warnings", []))
        if isinstance(report.get("warnings"), list)
        else [],
        "candidate_counts": {
            "mean": len(mean_rows),
            "volatility": len(volatility_rows),
        },
        "mean_candidates": bounded_mean,
        "volatility_candidates": bounded_volatility,
        "candidate_rows_omitted": {
            "mean": omitted_mean,
            "volatility": omitted_volatility,
        },
        "model_result": {
            "validation_fit": {
                key: value
                for key, value in _object(
                    _object(artifacts.get("ts.final_model")).get("validation_fit")
                ).items()
                if key
                in {
                    "model_family",
                    "mean_order",
                    "variance_order",
                    "estimation_strategy",
                    "resolved_strategy",
                    "joint_likelihood",
                    "innovation_distribution",
                }
            },
            "parameters": _object(artifacts.get("ts.parameters")),
        },
        "diagnostics": {
            "normality": _object(diagnostics.get("normality")),
            "arch_lm": _object(diagnostics.get("arch_lm")),
            "ljung_box": _rows(diagnostics.get("ljung_box"))[:_CANDIDATE_LIMIT],
            "warnings": list(diagnostics.get("warnings", []))
            if isinstance(diagnostics.get("warnings"), list)
            else [],
        },
        "forecast_metrics": _object(artifacts.get("ts.forecast_metrics")),
        # Co-located with the numbers on purpose: whoever reads these values is
        # the one about to name them.
        "labelling_invariants": list(LABELLING_INVARIANTS),
        "arma_vs_garch": _bounded_comparison(
            _object(artifacts.get("ts.arma_vs_garch_comparison"))
        ),
        "conditional_series": {
            "available": volatility_count > 0,
            "observation_count": volatility_count,
        },
        "artifact_manifest": {
            key: artifact_manifest.get(key)
            for key in ("status", "artifact_count_before_manifest")
            if key in artifact_manifest
        },
        "recommended_actions": _recommended_actions(artifacts, contract),
        "omitted_sections": [
            "raw_rows",
            "comparison_row_ids",
            "raw_conditional_series",
            "raw_residual_series",
            "chart_coordinates",
            "candidate_rows_after_limit",
        ],
    }


__all__ = [
    "build_arma_garch_public_result_view",
    "normalize_arma_garch_recommended_action",
]
