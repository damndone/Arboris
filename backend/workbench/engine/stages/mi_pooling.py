"""Fit a model to every imputed dataset and pool the fits (Rubin's rules).

The model is fitted by its own handler, once per dataset, exactly as a single
run would fit it; only the kernels are combined. The first dataset is fitted
alone first, so a family or covariance whose pooling is not validated is
refused before the remaining m - 1 fits are spent.

The pooled packet keeps only what the m fits agree on -- the model, its terms,
the covariance declaration -- and the pooled coefficients. A field whose value
differs between the fits is a figure of one dataset (R², residuals, odds
ratios, marginal effects, whatever a family reports), so it is left out and
named rather than shown from imputation 1; the rule needs no list per family.
No fitted object is returned, so residual diagnostics are not computed either.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...artifacts import register_artifact, write_json
from ...combinators.multiple_imputation import (
    POOLING_METHOD,
    MultipleImputationRefusal,
    pool_kernels,
    pooled_kernel_reason,
    require_poolable,
)
from ...contracts.model.inference_kernel import resolve_inference_kernel, unavailable_inference_kernel
from ..inference_kernels import record_inference_kernel

#: Packet fields that describe one dataset's fit, never the pooled result.
SINGLE_FIT_FIELDS = (
    "r_squared", "r_squared_adj", "adjusted_r_squared", "pseudo_r2", "pseudo_r_squared",
    "aic", "bic", "llf", "loglik", "log_likelihood", "llnull", "llr", "llr_pvalue",
    "f_statistic", "f_p_value", "f_pvalue", "df_model", "df_resid", "rmse", "ssr",
    "fitted_values", "residuals", "fitted_values_preview", "residuals_preview",
    "analysis_sample", "dataset_snapshot_fingerprint", "analysis_sample_fingerprint",
    "point_estimation_fingerprint", "inference_config_fingerprint",
)
#: Coefficient fields computed from one dataset that the pooled values replace.
_STALE_COEFFICIENT_FIELDS = ("p_value_display", "display_estimate", "t_value", "z_value", "statistic")


def fit_multiply_imputed(handler: Any, ctx: Any, env: Any, handles: list[Any], *, kernel_for) -> tuple[str, dict, None]:
    """Fit ``handler`` on every dataset handle and return the pooled packet.

    ``kernel_for(model_id, primary, fitted)`` resolves the kernel of one fit,
    the same rule the single-dataset path follows.
    """
    kernels: list[dict[str, Any]] = []
    primaries: list[dict[str, Any]] = []
    model_id = ""
    for index, handle in enumerate(handles):
        model_id, primary, fitted = handler.fit(ctx.with_data(handle), env)
        kernel = kernel_for(model_id, primary, fitted)
        if index == 0:
            require_poolable(str(kernel.get("model_type")), kernel)
        kernels.append(kernel)
        primaries.append(primary)
    pooled = pool_kernels(kernels)
    source_artifacts = [handle.artifact_id for handle in handles]
    first_primary = primaries[0]

    varying = sorted(
        key for key in first_primary
        if key != "coefficients" and any(other.get(key) != first_primary[key] for other in primaries[1:])
    )
    omitted = sorted(set(varying) | (set(SINGLE_FIT_FIELDS) & set(first_primary)))
    packet = {key: value for key, value in first_primary.items() if key not in omitted}
    terms = list(first_primary.get("coefficients") or {})
    if sorted(terms) != sorted(pooled["terms"]):
        raise MultipleImputationRefusal(
            "TERMS_UNMATCHED",
            "the result's terms do not match the parameters that were pooled "
            f"({', '.join(sorted(set(terms) ^ set(pooled['terms'])))}); nothing is reported",
        )
    coefficients: dict[str, dict[str, Any]] = {}
    for term, entry in first_primary["coefficients"].items():
        pooled_term = pooled["terms"][term]
        updated = {key: value for key, value in dict(entry).items() if key not in _STALE_COEFFICIENT_FIELDS}
        updated.update(
            estimate=pooled_term["estimate"],
            std_error=pooled_term["std_error"],
            p_value=pooled_term["p_value"],
            ci_lower=pooled_term["ci_lower"],
            ci_upper=pooled_term["ci_upper"],
            df=pooled_term["df"],
            fmi=pooled_term["fmi"],
            riv=pooled_term["riv"],
        )
        coefficients[term] = updated
    packet["coefficients"] = coefficients
    # The single fit's inference description named its own t(N - K); the pooled
    # tests use a Barnard-Rubin df per coefficient instead.
    for key in ("covariance_evidence", "inference_config"):
        evidence = first_primary.get(key)
        if isinstance(evidence, dict):
            packet[key] = {
                **evidence,
                "inference_distribution": "t",
                "effective_df": None,
                "df_method": "barnard_rubin",
                "p_value_method": "t_barnard_rubin",
                "confidence_interval_method": "t_barnard_rubin",
                "multiple_imputation_m": pooled["m"],
            }
    packet["warnings"] = list(first_primary.get("warnings") or []) + [
        f"Pooled from m = {pooled['m']} imputations; fit statistics and residuals describe a "
        "single imputed dataset and are not reported."
    ]
    packet["multiple_imputation"] = {
        "m": pooled["m"],
        "method": POOLING_METHOD,
        "dfcom": pooled["dfcom"],
        "dfcom_basis": pooled["dfcom_basis"],
        "covariance_estimator": pooled["covariance_estimator"],
        "source_artifacts": source_artifacts,
        "pool_artifact": f"rubin_pool_{model_id}",
        # Figures of one imputed dataset each; not reported for the pooled model.
        "omitted_single_dataset_fields": omitted,
    }

    run_root = Path(env.run_root)
    pool_path = run_root / "imputation" / f"rubin_pool_{model_id}.json"
    write_json(pool_path, {**pooled, "model_id": model_id, "source_artifacts": source_artifacts})
    register_artifact(run_root, f"rubin_pool_{model_id}", pool_path, "model_result", "imputation", source_artifacts)

    # The pooled result has no kernel post-estimation can use yet (D1); the
    # kernel says so, which is what every post-estimation refusal reads.
    record_inference_kernel(
        ctx,
        unavailable_inference_kernel(
            model_id=model_id, model_type=str(kernels[0]["model_type"]),
            nobs=kernels[0].get("nobs"), reason=pooled_kernel_reason(pooled["m"]),
        ),
    )
    summary = ctx.artifacts.get("_imputation_summary")
    if isinstance(summary, dict):
        summary = {
            **summary, "pooled_estimates": True, "pooling_method": POOLING_METHOD,
            "pooling_artifact": f"rubin_pool_{model_id}", "pooling_model_ids": [model_id],
        }
        ctx.artifacts["_imputation_summary"] = summary
        # The imputation stage wrote its summary before anything was pooled.
        write_json(run_root / "imputation_summary.json", summary)
    ctx.artifacts["_mi_pooling"] = {"m": pooled["m"], "method": POOLING_METHOD, "source_artifacts": source_artifacts}
    return model_id, packet, None


def kernel_resolver(ctx: Any, handler_model_type: str, *, kernel_source, recorded, public_name):
    """The single-run kernel rule, applied to one imputation's fit."""

    def resolve(model_id: str, primary: dict, fitted: Any) -> dict[str, Any]:
        kernel = resolve_inference_kernel(
            model_id=model_id,
            model_type=str(primary.get("model_type") or handler_model_type),
            primary=kernel_source(primary),
            fitted=fitted,
            recorded=recorded(ctx, model_id),
            public_name=public_name,
        )
        # A kernel a runtime recorded belongs to this fit only; the next
        # imputation must not inherit it.
        recorded_kernels = ctx.artifacts.get("_inference_kernels")
        if isinstance(recorded_kernels, dict):
            recorded_kernels.pop(model_id, None)
        return kernel

    return resolve
