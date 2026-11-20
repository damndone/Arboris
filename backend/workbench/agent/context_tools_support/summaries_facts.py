"""Summaries: bounded read-only context projection. (facts)."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
from typing import Any
from ...artifacts import read_json
from ..context_compiler import read_context_run_manifest
from ..bounds import _bounded_label, _bounded_labels, _public_positive_int, _public_stat_number
from .identification import _identification_fields, _omitted_terms
from .summaries_public_values import (
    _MAX_GROUPS_PROJECTED,
)


def _read_manifest(run_root: Path) -> dict[str, Any]:
    try:
        value = read_context_run_manifest(run_root)
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _analysis_contract_from_run_inputs(
    run_inputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Recover the frozen analysis contract from persisted run inputs.

    A run that failed before its artifacts were written still has the options
    it was asked to execute, and those options are the only honest basis for
    judging a patch against that node.
    """

    for section_name in ("executed_payload", "confirmed_payload", "form"):
        section = run_inputs.get(section_name)
        options = section.get("model_options") if isinstance(section, dict) else None
        if not isinstance(options, dict):
            continue
        try:
            from ...contracts.model.arma_garch import ArmaGarchAnalysisContract

            return ArmaGarchAnalysisContract.from_dict(options).to_dict()
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _read_diagnostic_summary(run_root: Path) -> tuple[dict[str, Any] | None, str]:
    summary_path = run_root / "diagnostic_summary.json"
    if not summary_path.is_file():
        return None, "missing"
    try:
        value = read_json(summary_path)
    except (OSError, ValueError):
        return None, "malformed"
    if not isinstance(value, dict):
        return None, "malformed"
    return value, "complete"


def _bounded_family_diagnostic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "contract": _bounded_label(value.get("contract")),
        "model_type": _bounded_label(value.get("model_type")),
        "nobs": _public_positive_int(value.get("nobs")),
        "outcome_levels": _bounded_labels(value.get("outcome_levels")),
        "base_category": _bounded_label(value.get("base_category")),
        "validation": {
            key[:64]: label[:128]
            for key, label in (value.get("validation") or {}).items()
            if isinstance(key, str) and isinstance(label, str)
        } if isinstance(value.get("validation"), dict) else {},
    }


def _model_evidence_ref(run_root, result):
    from ..context_compiler import model_evidence_ref
    return model_evidence_ref(run_root, result, run_id=run_root.name)


def _bounded_persisted_model_facts(
    model_results: list[dict[str, Any]],
    run_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Project the public facts needed to answer a selected model question.

    Diagnostic summaries are narrative-facing and may intentionally omit a
    coefficient table.  The model-result contract is the durable numerical
    authority, so return a small schema-owned projection rather than forcing
    an Agent to guess from a report or to read a raw result payload.
    """

    projected: list[dict[str, Any]] = []
    # A by-group run is one result per group; two would hide the rest. Each
    # projected group still states n_groups, and the coefficient tool returns all.
    grouped = any(isinstance(result.get("by_group"), Mapping) for result in model_results if isinstance(result, dict))
    for result in model_results[: _MAX_GROUPS_PROJECTED if grouped else 2]:
        model_id = result.get("model_id")
        coefficients = result.get("coefficients")
        if not isinstance(model_id, str) or not isinstance(coefficients, dict):
            continue
        rows: list[dict[str, Any]] = []
        for term, coefficient in list(coefficients.items())[:8]:
            if not isinstance(term, str) or not isinstance(coefficient, dict):
                continue
            rows.append(
                {
                    "term": term,
                    "estimate": _public_stat_number(coefficient.get("estimate")),
                    "std_error": _public_stat_number(coefficient.get("std_error")),
                    "p_value": _public_stat_number(coefficient.get("p_value")),
                    "ci_lower": _public_stat_number(coefficient.get("ci_lower")),
                    "ci_upper": _public_stat_number(coefficient.get("ci_upper")),
                    **_pooled_coefficient_fields(coefficient),
                    **_identification_fields(result, term, coefficient),
                }
            )
        projected.append(
            {
                "model_id": model_id,
                **({"evidence_ref": _model_evidence_ref(run_root, result)} if run_root is not None else {}),
                # What n counts: rows, or units for estimators that aggregate
                # over units (v1.8.10: CS reported 12 units beside 120 rows).
                "nobs": result.get("nobs") if isinstance(result.get("nobs"), int) else None,
                "nobs_basis": result.get("nobs_basis") or "rows",
                **_fit_statistics(result),
                "inference": _bounded_inference(result),
                # The estimator that ran, from the kernel; a requested default
                # the family does not use is never shown as if it had run.
                "covariance_executed": _executed_covariance(run_root, model_id),
                "inference_suppressed": result.get("inference_suppressed"),
                "multiple_imputation": _bounded_multiple_imputation(result),
                "by_group": _bounded_by_group(result),
                "coefficients": rows,
                **({"omitted_terms": _omitted_terms(result)} if _omitted_terms(result) else {}),
            }
        )
    return projected


def _bounded_by_group(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Which group this result is, the groups not estimated, and how to compare them."""
    block = result.get("by_group")
    if not isinstance(block, Mapping):
        return None
    return {
        "column": block.get("column"),
        "group": block.get("key"),
        "group_index": block.get("index"),
        "n_groups": block.get("n_groups"),
        "semantics": block.get("semantics"),
        "not_estimable": [
            {"group": item.get("key"), "nobs": item.get("nobs"), "reason": str(item.get("reason") or "")[:300]}
            for item in (block.get("not_estimable") or [])[:10] if isinstance(item, Mapping)
        ],
        "difference_tests": _bounded_difference_tests(block.get("difference_tests")),
        "comparing_groups": (
            "Coefficients of separate groups side by side are not a test of a difference; "
            "cite the group-difference test before saying groups differ."
        ),
    }


def _bounded_difference_tests(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("status") != "estimated":
        return {"status": value.get("status"), "reason": str(value.get("reason") or "")[:300]}
    return {
        "status": "estimated",
        "method": value.get("method"),
        "reference_group": value.get("reference_group"),
        "covariance_estimator": value.get("covariance_estimator"),
        "tests": [
            {key: test.get(key) for key in ("label", "statistic", "df_num", "df_den", "p_value", "distribution",
                                             "status", "reason") if test.get(key) is not None}
            for test in (value.get("tests") or [])[:12] if isinstance(test, Mapping)
        ],
    }


def _pooled_coefficient_fields(coefficient: Mapping[str, Any]) -> dict[str, Any]:
    """A pooled multiple-imputation coefficient's own Barnard-Rubin df and
    fraction of missing information; nothing for an ordinary fit."""
    if "fmi" not in coefficient:
        return {}
    return {"df": _public_stat_number(coefficient.get("df")), "fmi": _public_stat_number(coefficient.get("fmi"))}


def _bounded_multiple_imputation(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """m and the pooling rule, so the Agent says how the figures were combined."""
    block = result.get("multiple_imputation")
    if not isinstance(block, Mapping):
        return None
    return {
        "m": block.get("m"),
        "method": "Rubin's rules, Barnard-Rubin df per coefficient",
        "complete_data_df": block.get("dfcom"),
        "not_reported": "R-squared, residuals and diagnostics (they describe one imputed dataset)",
        "post_estimation": "joint tests on pooled estimates are not available yet (needs D1)",
    }


def _executed_covariance(run_root: Path | None, model_id: Any) -> str | None:
    if run_root is None or not isinstance(model_id, str):
        return None
    from ...contracts.model.inference_kernel import kernel_relative_path, validate_inference_kernel

    path = run_root / kernel_relative_path(model_id)
    try:
        if not path.is_file():
            return None
        kernel = read_json(path)
        validate_inference_kernel(kernel)
        if kernel.get("model_id") != model_id:
            return None
        from ...postestimation.comparison_data import assert_completed_kernel

        assert_completed_kernel(run_root, kernel)
        return kernel.get("covariance_estimator")
    except (OSError, ValueError):
        return None


_INFERENCE_FIELDS = (
    "covariance", "covariance_estimator", "inference_distribution", "effective_df", "df_method",
    "cluster_count", "cluster_variable", "inference_version", "hac",
)


def _fit_statistics(result: Mapping[str, Any]) -> dict[str, Any]:
    """R-squared, unless the result is pooled over imputations.

    A pooled result has no R-squared of its own; any one dataset's would be
    shown as if it were the pooled model's, so the fields are left out rather
    than sent as null (v1.8.10 evaluation A04).
    """
    if result.get("multiple_imputation"):
        return {}
    return {
        "r_squared": _public_stat_number(result.get("r_squared")),
        "r_squared_adj": _public_stat_number(result.get("r_squared_adj")),
    }


def _bounded_inference(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """How the model's standard errors and p-values were computed.

    A result without `inference_version` predates inference engine v2; with a
    robust or clustered covariance its p-values used the normal distribution,
    and the Agent has to be able to say so.
    """
    design = result.get("survey_design")
    if isinstance(design, Mapping):
        # Derive design inference independently of legacy pre-design evidence.
        from ...survey.design import recorded_df_convention

        convention, df = recorded_df_convention(design)
        return {
            "covariance": "survey_design",
            "covariance_estimator": f"survey_design_{design.get('variance_method') or 'linearization'}",
            "inference_distribution": "t", "effective_df": df, "df_method": convention,
            "legacy_asymptotic": False,
        }
    evidence = result.get("covariance_evidence") or result.get("inference_config")
    if not isinstance(evidence, Mapping):
        return None
    out = {key: evidence.get(key) for key in _INFERENCE_FIELDS if evidence.get(key) is not None}
    out["legacy_asymptotic"] = (
        "inference_version" not in evidence
        and evidence.get("inference_distribution") == "normal"
        and evidence.get("covariance") in {"robust", "clustered"}
    )
    # A panel or DID fit (it names its entity) with robust errors did not
    # cluster by entity; since v1.8.11 the default clusters, so an older result
    # is marked and the Agent can offer the rerun.
    if evidence.get("covariance") == "robust" and isinstance(result.get("entity_col"), str) \
            and evidence.get("cluster_entity") is not True:
        out["not_clustered_by_entity"] = True
        out["inference_note"] = (
            "Heteroskedasticity-robust standard errors not clustered by entity: inconsistent with a "
            "fixed number of periods. "
            + ("This result predates v1.8.11; rerunning clusters by entity." if "inference_version" not in evidence
               else "Chosen explicitly; the default clusters by entity.")
        )
    return out
