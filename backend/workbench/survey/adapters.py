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
#: `glm_family` a model family declares.  Adding a row here adds a link in the
#: chain, not a branch in the logic.
_GLM_LINKS: dict[str, str] = {
    "gaussian": "Gaussian",
    "binomial": "Binomial",
    "poisson": "Poisson",
}


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
        fpc=str(artifacts.get("_survey_fpc_col") or "").strip() or None,
        lonely_psu=str(artifacts.get("_survey_lonely_psu") or "").strip() or "fail",
        subpop=str(artifacts.get("_survey_subpop") or "").strip() or None,
        replicate_type=str(artifacts.get("_survey_replicate_type") or "").strip() or None,
        replicate_weight_columns=replicate_columns,
    )


def glm_estimator_spec(
    *, family: str, glm_family: str, y: str, x: Sequence[str]
) -> EstimatorSpec:
    """One adapter for every family that declares a statsmodels GLM link.

    Both capabilities come for free here: GLMs are refittable under arbitrary
    weights and expose a score, so these families get the linearization channel
    as well as the replicate one.
    """
    import statsmodels.api as sm

    link = _GLM_LINKS.get(glm_family)
    if link is None:
        raise SurveyEngineError(
            "SURVEY_GLM_FAMILY_UNSUPPORTED",
            f"{family!r} declares glm_family={glm_family!r}, which the shared "
            "adapter does not link to statsmodels",
            declared=glm_family,
            available=sorted(_GLM_LINKS),
        )
    sm_family = getattr(sm.families, link)()
    terms = ["(Intercept)", *x]

    def _design_matrix(frame: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [np.ones(len(frame))] + [frame[name].to_numpy(dtype=float) for name in x]
        )

    def refit(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
        exog = _design_matrix(frame)
        endog = frame[y].to_numpy(dtype=float)
        fitted = sm.GLM(endog, exog, family=sm_family, freq_weights=np.asarray(weights, float)).fit()
        return dict(zip(terms, (float(v) for v in fitted.params), strict=True))

    def influence(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, np.ndarray]:
        exog = _design_matrix(frame)
        endog = frame[y].to_numpy(dtype=float)
        w = np.asarray(weights, dtype=float)
        fitted = sm.GLM(endog, exog, family=sm_family, freq_weights=w).fit()
        mu = fitted.fittedvalues
        # d(eta)/d(mu) cancels for canonical links, leaving (y - mu) as the score.
        score = (endog - mu)
        bread = np.linalg.inv((exog.T * (w * fitted.family.weights(mu) if hasattr(fitted.family, "weights") else w)) @ exog)
        contrib = (exog * (w * score)[:, None]) @ bread.T
        return dict(zip(terms, contrib.T, strict=True))

    return EstimatorSpec(
        name=f"survey::{family}",
        refit=refit,
        influence=influence,
        consumes_design=False,
        metadata={"family": family, "glm_family": glm_family, "terms": terms},
    )
