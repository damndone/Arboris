"""Survey designs for fitted models: declared-design checks, design estimators, design-term mapping, design variance and composition checks."""

from __future__ import annotations

from ..inference_kernels import record_inference_kernel
from ...contracts.model.inference_kernel import (
    InferenceKernelError,
    build_inference_kernel,
    unavailable_inference_kernel,
)


def _survey_design_declared(ctx) -> bool:
    """Whether the run carries a complex sampling design.

    Deliberately a presence check over the declarations block 1 wired through --
    no family appears here, and none may.  Which families can *use* the design is
    derived from what each declares, in `_survey_estimator_for`.
    """
    return bool(
        str(ctx.artifacts.get("_survey_strata_col") or "").strip()
        or str(ctx.artifacts.get("_survey_psu_col") or "").strip()
    )


def _survey_estimator_for(model_type: str, y: str, x: list[str]):
    """Build the engine-side estimator from what the family declared.

    Returns None when the family declared no link, which is a refusal to guess:
    a family that has not said how it fits under arbitrary weights does not get a
    design-based variance invented on its behalf.
    """
    from ...contracts.model.family import MODEL_FAMILY_CONTRACTS
    from ...survey.adapters import glm_estimator_spec

    contract = MODEL_FAMILY_CONTRACTS.get(model_type)
    glm_family = getattr(contract, "survey_glm_family", None) if contract else None
    if not glm_family:
        return None
    return glm_estimator_spec(family=model_type, glm_family=glm_family, y=y, x=list(x))


#: Terms the result payload and the design engine spell differently.  The engine
#: follows R (`(Intercept)`) so its output can be compared to `survey` directly;
#: the payload has used `Intercept` since well before this version.  One mapping
#: here beats each caller guessing.
_DESIGN_TERM_ALIASES = {"Intercept": "(Intercept)"}


def _design_term(payload_term: str) -> str:
    """The name the design engine uses for a term the payload calls `payload_term`."""
    return _DESIGN_TERM_ALIASES.get(payload_term, payload_term)


def _apply_survey_design_variance(ctx, model_type: str, primary: dict) -> None:
    """Replace the naive variance with the design-based one, in place.

    The point estimate is already right -- weighted least squares gives the same
    coefficients either way -- so nothing about an un-corrected result looks
    wrong.  Only the uncertainty is off, and on the committed fixture it is off
    by more than half: 0.0850 where the design gives 0.1773. A user reading the
    first number believes the estimate is twice as sharp as it is.
    """
    from scipy import stats

    from ...survey.adapters import build_design_from_artifacts, fpc_summary
    from ...survey.engine import estimate_with_design
    from ...survey.errors import SurveyEngineError

    # The design variance must describe the same observations as the point
    # estimate: rows missing a modelled variable are left out of both (Stata's
    # svy default). Without this a single missing covariate crashed the run
    # inside the design refit. design_precheck reports the rows left out.
    frame = ctx.data.frame
    modelled = [
        column
        for column in [ctx.artifacts["_normalized_y"], *ctx.artifacts["_normalized_x"]]
        if column in frame.columns
    ]
    if modelled:
        frame = frame.loc[frame[modelled].notna().all(axis=1)]
    design = build_design_from_artifacts(frame, ctx.artifacts)
    if design is None:
        return
    estimator = _survey_estimator_for(
        model_type, ctx.artifacts["_normalized_y"], ctx.artifacts["_normalized_x"]
    )
    if estimator is None:
        return

    declared_replicate = str(ctx.artifacts.get("_survey_replicate_type") or "").strip()
    method = "replicate" if declared_replicate else "linearization"
    result = estimate_with_design(
        design, estimator, method=method,
        replicate_type=declared_replicate or None,
        df_convention=str(ctx.artifacts.get("_survey_df") or "").strip() or "design",
    )

    critical = float(stats.t.ppf(0.975, result.inference_degf))
    coefficients = primary.get("coefficients") or {}
    unmatched = [
        term for term in coefficients if _design_term(term) not in result.standard_errors
    ]
    if unmatched:
        # Skipping these is what a browser run exposed: the payload names the
        # intercept `Intercept` while the engine names it `(Intercept)`, so the
        # intercept quietly kept its naive 0.7804 next to slopes carrying the
        # design's 0.1773.  A coefficient that silently keeps the wrong variance
        # is worse than a run that refuses, because nothing marks it as different.
        raise SurveyEngineError(
            "design variance produced no standard error for "
            f"{unmatched}; the engine reported {sorted(result.standard_errors)}"
        )
    for term, entry in coefficients.items():
        se = result.standard_errors[_design_term(term)]
        # The engine's estimate, refitted on the subpopulation when one is
        # declared. The packet's own was fitted on every row: with a subpop it
        # paired a full-sample coefficient with the domain's standard error
        # (found in v1.8.10 against Stata svy, subpop()); without one the two
        # are the same weighted least squares.
        estimate = float(result.estimates[_design_term(term)])
        entry["estimate"] = estimate
        entry["std_error"] = se
        entry["ci_lower"] = estimate - critical * se
        entry["ci_upper"] = estimate + critical * se
        entry["p_value"] = float(
            2 * stats.t.sf(abs(estimate / se), result.inference_degf)
        ) if se > 0 else (None if design.fpc is not None else float("nan"))
        entry["variance_source"] = "survey_design"

    if design.fpc is not None and any(
        entry["std_error"] == 0 for entry in coefficients.values()
    ):
        primary["warnings"] = list(primary.get("warnings") or []) + [{
            "code": "SURVEY_ZERO_VARIANCE_INFERENCE_UNAVAILABLE",
            "message": "The finite population correction gives zero sampling variance; "
                       "coefficient p-values with zero standard errors are unavailable.",
        }]

    # The kernel must carry the variance the user now sees. Without this a joint
    # test would read the naive covariance still attached to the fitted object.
    import numpy as np

    payload_terms = list(coefficients)
    positions = [result.terms.index(_design_term(term)) for term in payload_terms]
    model_id = str(primary.get("model_id"))
    nobs = int(primary.get("nobs") or 0)
    try:
        kernel = build_inference_kernel(
            model_id=model_id,
            model_type=model_type,
            param_names=payload_terms,
            params=[result.estimates[_design_term(term)] for term in payload_terms],
            vcov=np.asarray(result.covariance, dtype=float)[np.ix_(positions, positions)],
            reference_distribution="t",
            df_resid=float(result.inference_degf),
            # "design" (degf) or "design_minus_p" (degf - p + 1): joint tests
            # read it to pick the Korn-Graubard F or R's regTermTest F.
            df_method=result.df_convention,
            loglik=None,
            nobs=nobs,
            covariance_estimator=f"survey_design_{result.method}",
            unavailable={
                "loglik": (
                    "The variance is design-based, so a likelihood-ratio test is not valid; "
                    "joint tests use the design-based Wald test."
                ),
            },
        )
    except InferenceKernelError as error:
        # Never fall back to the naive covariance still on the fitted object.
        kernel = unavailable_inference_kernel(
            model_id=model_id, model_type=model_type, nobs=nobs,
            reason=f"The design-based covariance matrix could not be used: {error}.",
        )
    record_inference_kernel(ctx, kernel)

    if design.subpop:
        # Fit statistics, residuals and fitted values were computed on every row,
        # not on the subpopulation the estimates describe.
        primary["nobs_subpopulation"] = int(design.subpop_mask().sum())
        for field in ("r_squared", "r_squared_adj", "adjusted_r_squared", "f_statistic", "f_p_value",
                      "fitted_values", "residuals", "fitted_values_preview", "residuals_preview",
                      "llf", "aic", "bic", "df_model", "df_resid"):
            primary.pop(field, None)
        primary["warnings"] = list(primary.get("warnings") or []) + [
            "Estimated for a subpopulation (domain); fit statistics and residuals describe all rows "
            "and are not reported."
        ]
    effects = design.design_effects(ctx.artifacts["_normalized_y"])
    summary = result.replicate_summary
    primary["survey_design"] = {
        "strata_column": design.strata,
        "psu_column": design.psu,
        "weight_column": design.weight,
        "subpopulation": design.subpop,
        "n_obs": design.n_obs,
        "n_strata": design.n_strata,
        "n_psu": design.n_psu,
        "degf": result.degf,
        "residual_degf": result.residual_degf,
        "df_convention": result.df_convention,
        "inference_degf": result.inference_degf,
        "variance_method": result.method,
        "replicate_type": declared_replicate or None,
        "lonely_psu_policy": design.lonely_psu,
        "design_effect": effects.deff,
        "effective_sample_size": effects.kish_n_eff,
        # Reported rather than silently absorbed: replicates that could not be
        # fitted shrink the variance, and nothing on screen would say so.
        "replicates_attempted": summary.attempted if summary else None,
        "replicates_succeeded": summary.succeeded if summary else None,
        "replicates_failed": summary.failed if summary else None,
        "replicate_failure_reasons": summary.failure_reasons if summary else None,
    }
    if design.fpc is not None:
        primary["survey_design"]["fpc"] = fpc_summary(design)

    # Every public reader must describe the replacement, not the fitted
    # object's earlier covariance. Keep submitted wire options unchanged.
    evidence = {
        "covariance": "survey_design",
        "covariance_estimator": f"survey_design_{result.method}",
        "variance_source": "survey_design",
        "engine": "workbench.survey",
        "use_t": True,
        "df_method": result.df_convention,
        "effective_df": float(result.inference_degf),
        "inference_distribution": "t",
        "p_value_method": "t",
        "confidence_interval_method": "t",
        "confidence_level": 0.95,
        "alpha": 0.05,
        "survey_design": primary["survey_design"],
    }
    primary.update(covariance="survey_design", covariance_estimator=evidence["covariance_estimator"],
                   variance_source="survey_design", covariance_evidence=evidence,
                   inference_config=evidence, source_eligible=False)
    from ...analysis_loop.fingerprints import inference_config_fingerprint
    primary["inference_config_fingerprint"] = inference_config_fingerprint(
        covariance="survey_design", cluster_var=design.psu, cluster_count=design.n_psu,
        corrections={"survey_design": primary["survey_design"]}, df=result.inference_degf,
        use_t=True, confidence_level=0.95, engine="workbench.survey",
        inference_distribution="t", p_value_method="t", confidence_interval_method="t",
    )


def _check_survey_composition(ctx, model_type: str, sampling_weight: str) -> None:
    """Surface a survey composition refusal as a typed workflow failure."""
    from ...orchestrator._errors import WorkflowValidationError
    from ...survey.composability import (
        SurveyCompositionRefusal,
        check_design_composition,
    )

    strata = str(ctx.artifacts.get("_survey_strata_col") or "").strip()
    psu = str(ctx.artifacts.get("_survey_psu_col") or "").strip()
    try:
        check_design_composition(
            model_type=model_type,
            has_design=bool(strata or psu),
            has_sampling_weight=bool(sampling_weight),
            entity_column=str(ctx.artifacts.get("_entity_col") or "").strip() or None,
            time_column=str(ctx.artifacts.get("_time_col") or "").strip() or None,
            weight_frame=str(ctx.artifacts.get("_survey_weight_frame") or "").strip() or None,
        )
    except SurveyCompositionRefusal as exc:
        raise WorkflowValidationError(
            exc.code,
            str(exc),
            {
                "model_type": model_type,
                "survey_strata_col": strata,
                "survey_psu_col": psu,
                "sampling_weight": sampling_weight,
            },
        ) from exc
