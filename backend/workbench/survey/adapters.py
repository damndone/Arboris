"""Turning a declared model family into something the engine can drive.

There is exactly one adapter here and it is shared.  A family opts in by
declaring the capabilities its fit provides; nothing in this module or in the
engine asks which family it is.  That is what keeps the promise that a new
family costs one declaration -- if adding a family ever required editing this
file, the enumeration matrix would be back, just moved.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from .design import SurveyDesign
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
    if not weight:
        return None
    fpc = str(artifacts.get("_survey_fpc_col") or "").strip()
    if fpc:
        raise SurveyEngineError(
            "SURVEY_FPC_UNSUPPORTED",
            "finite population correction is declared but this survey variance "
            "engine does not apply FPC; remove survey_fpc_col or use an engine "
            "with explicit FPC support",
            fpc_column=fpc,
        )
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

    replicate_columns = list(artifacts.get("_survey_replicate_weights") or [])
    return SurveyDesign(
        frame=frame,
        weight=weight,
        strata=strata or None,
        psu=psu or None,
        lonely_psu=str(artifacts.get("_survey_lonely_psu") or "").strip() or "fail",
        subpop=str(artifacts.get("_survey_subpop") or "").strip() or None,
        replicate_type=str(artifacts.get("_survey_replicate_type") or "").strip() or None,
        replicate_weight_columns=replicate_columns,
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
            exposure_values = frame[exposure].to_numpy(dtype=float)
            if (exposure_values <= 0).any():
                raise SurveyEngineError(
                    "SURVEY_POISSON_EXPOSURE_INVALID",
                    f"exposure column {exposure!r} must be strictly positive "
                    "for a survey Poisson rate fit",
                    exposure_column=exposure,
                )
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
        },
    )
