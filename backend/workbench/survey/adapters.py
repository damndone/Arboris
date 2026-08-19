"""Turning a declared model family into something the engine can drive.

There is exactly one adapter here and it is shared.  A family opts in by
declaring the capabilities its fit provides; nothing in this module or in the
engine asks which family it is.  That is what keeps the promise that a new
family costs one declaration -- if adding a family ever required editing this
file, the enumeration matrix would be back, just moved.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, DecimalException

import numpy as np
import pandas as pd

from .design import SURVEY_WEIGHT_FRAME_VALUES, SurveyDesign
from .errors import SurveyEngineError
from .estimator import EstimatorSpec

#: statsmodels GLM families reachable through the shared adapter, keyed by the
#: `glm_family` a model family declares.  The optional link is explicit because
#: Probit is binomial with a non-canonical link; routing it through the default
#: Binomial constructor would silently fit Logit instead.
_GLM_FAMILIES: dict[str, tuple[str, str | None]] = {
    "gaussian": ("Gaussian", None),
    "binomial": ("Binomial", None),
    "binomial_probit": ("Binomial", "Probit"),
    "poisson": ("Poisson", None),
}

_MAX_INVALID_EXPOSURE_ROWS = 16


def _exposure_failure(
    *,
    exposure: str,
    reason: str,
    invalid_rows: list[str] | None = None,
    detail: str | None = None,
) -> SurveyEngineError:
    return SurveyEngineError(
        "SURVEY_POISSON_EXPOSURE_INVALID",
        detail or f"exposure column {exposure!r} violates the Poisson exposure contract",
        exposure_column=exposure,
        reason=reason,
        invalid_rows=list(invalid_rows or [])[:_MAX_INVALID_EXPOSURE_ROWS],
    )


def validate_poisson_exposure(frame: pd.DataFrame, exposure: str | None) -> None:
    """Reject an exposure before a Poisson family can treat it as an input."""
    if not exposure:
        return
    if exposure not in frame.columns:
        raise _exposure_failure(
            exposure=exposure,
            reason="missing",
            detail=f"exposure column {exposure!r} is not in the modeling frame",
        )
    try:
        raw_values = frame[exposure].to_numpy(dtype=object)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _exposure_failure(
            exposure=exposure,
            reason="non_numeric",
            detail=f"exposure column {exposure!r} cannot be read safely",
        ) from exc

    decimals: list[Decimal] = []
    non_numeric_rows: list[str] = []
    boolean_rows: list[str] = []
    nonfinite_rows: list[str] = []
    nonpositive_rows: list[str] = []
    for index, raw_value in zip(frame.index, raw_values, strict=True):
        row = str(index)
        if isinstance(raw_value, (bool, np.bool_)):
            boolean_rows.append(row)
            continue
        try:
            parsed = Decimal(str(raw_value).strip())
        except (DecimalException, OverflowError, TypeError, ValueError, UnicodeError):
            non_numeric_rows.append(row)
            continue
        decimals.append(parsed)
        if not parsed.is_finite():
            nonfinite_rows.append(row)
        elif parsed <= 0:
            nonpositive_rows.append(row)

    if boolean_rows:
        raise _exposure_failure(
            exposure=exposure,
            reason="boolean",
            invalid_rows=boolean_rows,
            detail=f"exposure column {exposure!r} must not contain boolean values",
        )
    if non_numeric_rows:
        raise _exposure_failure(
            exposure=exposure,
            reason="non_numeric",
            invalid_rows=non_numeric_rows,
            detail=f"exposure column {exposure!r} contains values that cannot be parsed safely",
        )
    if nonfinite_rows:
        raise _exposure_failure(
            exposure=exposure,
            reason="nonfinite",
            invalid_rows=nonfinite_rows,
            detail=f"exposure column {exposure!r} must contain finite values",
        )
    if nonpositive_rows:
        raise _exposure_failure(
            exposure=exposure,
            reason="nonpositive",
            invalid_rows=nonpositive_rows,
            detail=f"exposure column {exposure!r} must be strictly positive",
        )

    overflow_rows: list[str] = []
    for index, parsed in zip(frame.index, decimals, strict=True):
        try:
            converted = float(parsed)
        except (DecimalException, OverflowError, TypeError, ValueError):
            overflow_rows.append(str(index))
            continue
        if not np.isfinite(converted):
            overflow_rows.append(str(index))
    if overflow_rows:
        raise _exposure_failure(
            exposure=exposure,
            reason="not_float_representable",
            invalid_rows=overflow_rows,
            detail=f"exposure column {exposure!r} cannot be represented as finite float values",
        )


def _poisson_result_postprocessor(
    *,
    primary: dict[str, object],
    term: str,
    entry: dict[str, object],
    estimate: float,
    ci_lower: float,
    ci_upper: float,
) -> None:
    """Keep Poisson-derived intervals aligned with the survey coefficient."""
    from math import exp, isfinite

    max_log = 700.0
    values = {"estimate": estimate, "ci_lower": ci_lower, "ci_upper": ci_upper}
    if any(
        not isfinite(value) or abs(value) > max_log
        for value in values.values()
    ):
        raise SurveyEngineError(
            "SURVEY_POSTPROCESS_INVALID",
            "Poisson exp transform is outside the finite bounded range",
            reason="exponential_out_of_bounds",
            term=term,
        )
    try:
        irr = {
            "irr": exp(estimate),
            "irr_ci_lower": exp(ci_lower),
            "irr_ci_upper": exp(ci_upper),
        }
    except (OverflowError, ValueError) as exc:
        raise SurveyEngineError(
            "SURVEY_POSTPROCESS_INVALID",
            "Poisson exp transform could not be represented safely",
            reason="exponential_overflow",
            term=term,
        ) from exc
    if any(not isfinite(float(value)) for value in irr.values()):
        raise SurveyEngineError(
            "SURVEY_POSTPROCESS_INVALID",
            "Poisson exp transform returned a non-finite value",
            reason="nonfinite_transform",
            term=term,
        )
    entry.update(irr)
    primary_irr = primary.get("irr")
    if isinstance(primary_irr, dict) and isinstance(primary_irr.get(term), dict):
        primary_irr[term].update(irr)


def apply_result_postprocessor(
    estimator: EstimatorSpec,
    *,
    primary: dict[str, object],
    term: str,
    entry: dict[str, object],
    estimate: float,
    ci_lower: float,
    ci_upper: float,
) -> None:
    """Apply family-owned result decoration through the adapter metadata seam."""
    callback = estimator.metadata.get("survey_result_postprocessor")
    if callback is None:
        return
    if not callable(callback):
        raise SurveyEngineError(
            "SURVEY_ADAPTER_METADATA_INVALID",
            "survey_result_postprocessor must be callable",
            estimator=estimator.name,
        )
    try:
        callback(
            primary=primary,
            term=term,
            entry=entry,
            estimate=estimate,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
        )
    except OverflowError as exc:
        raise SurveyEngineError(
            "SURVEY_POSTPROCESS_INVALID",
            "survey result postprocessor overflowed",
            reason="overflow",
            term=term,
        ) from exc


def supports_glm_family(glm_family: str | None) -> bool:
    """Return whether a declared survey GLM family has a live adapter path."""

    return isinstance(glm_family, str) and glm_family in _GLM_FAMILIES


def build_design_from_artifacts(frame: pd.DataFrame, artifacts: dict) -> SurveyDesign | None:
    """Assemble a design from the declarations block 1 wired into ctx.

    Returns None when nothing was declared, which is what keeps every existing
    run byte-identical: no declaration, no design, no change of path.
    """
    strata = str(artifacts.get("_survey_strata_col") or "").strip()
    psu = str(artifacts.get("_survey_psu_col") or "").strip()
    weight = str(artifacts.get("_sampling_weight") or "").strip()
    fpc = str(artifacts.get("_survey_fpc_col") or "").strip()
    replicate_columns = list(artifacts.get("_survey_replicate_weights") or [])
    replicate_type = str(artifacts.get("_survey_replicate_type") or "").strip()
    lonely_psu = str(artifacts.get("_survey_lonely_psu") or "").strip()
    subpopulation = str(artifacts.get("_survey_subpop") or "").strip()
    weight_frame = str(artifacts.get("_survey_weight_frame") or "").strip()
    if weight_frame and weight_frame not in SURVEY_WEIGHT_FRAME_VALUES:
        raise SurveyEngineError(
            "SURVEY_WEIGHT_FRAME_INVALID",
            f"unknown survey weight frame {weight_frame!r}",
            allowed=list(SURVEY_WEIGHT_FRAME_VALUES),
        )
    if fpc:
        raise SurveyEngineError(
            "SURVEY_FPC_UNSUPPORTED",
            "finite population correction is declared but this survey variance "
            "engine does not apply FPC; remove survey_fpc_col or use an engine "
            "with explicit FPC support",
            fpc_column=fpc,
        )
    if not weight:
        declared_fields = [
            name for name, value in (
                ("survey_strata_col", strata),
                ("survey_psu_col", psu),
                ("survey_replicate_weights", replicate_columns),
                ("survey_replicate_type", replicate_type),
                ("survey_lonely_psu", lonely_psu),
                ("survey_subpop", subpopulation),
                ("survey_weight_frame", weight_frame),
            ) if value
        ]
        if declared_fields:
            raise SurveyEngineError(
                "SURVEY_DESIGN_INCOMPLETE",
                "survey design declarations require sampling_weight before "
                "estimation; no declared design field may be silently ignored",
                missing=["sampling_weight"],
                declared_fields=declared_fields,
            )
        return None
    if not (strata or psu):
        raise SurveyEngineError(
            "SURVEY_DESIGN_INCOMPLETE",
            "sampling_weight needs a declared design: give survey_strata_col "
            "and/or survey_psu_col. A clustered covariance is not a substitute -- "
            "it ignores the variance reduction stratification buys and yields no "
            "design degrees of freedom.",
            missing=[
                name for name, value in (
                    ("survey_strata_col", strata), ("survey_psu_col", psu)
                ) if not value
            ],
        )

    if replicate_columns and not replicate_type:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_TYPE_REQUIRED",
            "replicate weight columns require survey_replicate_type",
            replicate_weight_columns=replicate_columns[:16],
        )
    return SurveyDesign(
        frame=frame,
        weight=weight,
        strata=strata or None,
        psu=psu or None,
        lonely_psu=lonely_psu or "fail",
        subpop=subpopulation or None,
        replicate_type=replicate_type or None,
        replicate_weight_columns=replicate_columns,
        weight_frame=weight_frame or None,
    )


def glm_estimator_spec(
    *,
    family: str,
    glm_family: str,
    y: str,
    x: Sequence[str],
    exposure: str | None = None,
) -> EstimatorSpec:
    """One adapter for every family that declares a statsmodels GLM link.

    Both capabilities come for free here: GLMs are refittable under arbitrary
    weights and expose a score, so these families get the linearization channel
    as well as the replicate one.
    """
    import statsmodels.api as sm

    family_spec = _GLM_FAMILIES.get(glm_family)
    if family_spec is None:
        raise SurveyEngineError(
            "SURVEY_GLM_FAMILY_UNSUPPORTED",
            f"{family!r} declares glm_family={glm_family!r}, which the shared "
            "adapter does not link to statsmodels",
            declared=glm_family,
            available=sorted(_GLM_FAMILIES),
        )
    family_name, link_name = family_spec
    family_class = getattr(sm.families, family_name)
    if link_name is None:
        sm_family = family_class()
    else:
        sm_family = family_class(link=getattr(sm.families.links, link_name)())
    terms = ["(Intercept)", *x]

    def _design_matrix(frame: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [np.ones(len(frame))] + [frame[name].to_numpy(dtype=float) for name in x]
        )

    def _fit(frame: pd.DataFrame, weights: np.ndarray):
        kwargs: dict[str, object] = {"freq_weights": np.asarray(weights, float)}
        if exposure and glm_family == "poisson":
            validate_poisson_exposure(frame, exposure)
            exposure_values = frame[exposure].to_numpy(dtype=float)
            kwargs["exposure"] = exposure_values
        return sm.GLM(
            frame[y].to_numpy(dtype=float),
            _design_matrix(frame),
            family=sm_family,
            **kwargs,
        ).fit()

    def refit(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
        fitted = _fit(frame, weights)
        return dict(zip(terms, (float(v) for v in fitted.params), strict=True))

    def influence(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, np.ndarray]:
        exog = _design_matrix(frame)
        endog = frame[y].to_numpy(dtype=float)
        w = np.asarray(weights, dtype=float)
        fitted = _fit(frame, weights)
        mu = fitted.fittedvalues
        # The canonical-link shortcut is not valid for Probit.  Use the
        # general GLM score and expected Hessian so the same influence channel
        # remains truthful for both Binomial links.
        variance = fitted.family.variance(mu)
        link_derivative = fitted.family.link.deriv(mu)
        score = (endog - mu) / (variance * link_derivative)
        bread = np.linalg.inv(
            (exog.T * (w * fitted.family.weights(mu))) @ exog
        )
        contrib = (exog * (w * score)[:, None]) @ bread.T
        return dict(zip(terms, contrib.T, strict=True))

    return EstimatorSpec(
        name=f"survey::{family}",
        refit=refit,
        influence=influence,
        consumes_design=False,
        metadata={
            "family": family,
            "glm_family": glm_family,
            "terms": terms,
            "exposure": exposure,
            "survey_result_postprocessor": (
                _poisson_result_postprocessor if glm_family == "poisson" else None
            ),
        },
    )
