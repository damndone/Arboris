# backend/workbench/lineage/role_inputs_from_ctx.py
"""Bridge: turn the engine's resolved estimator inputs (ctx.artifacts) into a
ResolvedRoleInputs for derive_roles. Reads the columns the estimator ACTUALLY
consumed (the `_normalized_*`/`_poisson_x`/`_iv_*`/`_did_*` artifacts), never
re-parsing the raw form (spec §4)."""
from __future__ import annotations

from .role_layer import ResolvedRoleInputs

# estimator_key (model_id minus trailing "_N") -> estimator_family
_FAMILY: dict[str, str] = {
    "ols": "regression",
    "logit": "regression",
    "probit": "regression",
    "poisson": "regression",
    "negative_binomial": "regression",
    "glm": "regression",
    "panel_ols": "panel",
    "iv_2sls": "iv",
    "did": "did",
    "cs_did": "did",
    "sa_did": "did",
    "dcdh": "did",
}


def _family(key: str) -> str:
    if key.startswith("glm"):
        return "regression"
    return _FAMILY.get(key, "regression")


def build_resolved_inputs(ctx) -> ResolvedRoleInputs:
    art = ctx.artifacts
    model_results = art.get("_model_results") or []
    model_id = model_results[0][0] if model_results else "ols_1"
    key = model_id.rsplit("_", 1)[0]          # "cs_did_1" -> "cs_did"
    family = _family(key)

    normalized_x = list(art.get("_normalized_x", []))
    # regression RHS is the exposure-stripped _poisson_x (== normalized_x when no
    # exposure); causal/panel families use normalized_x directly.
    rhs = list(art.get("_poisson_x", normalized_x)) if family == "regression" else normalized_x

    exposure = getattr(ctx, "exposure_col", None) or None

    unit = time = None
    treatment: list[str] = []
    if family == "did":
        did = art.get("_did_normalized")
        unit = getattr(did, "entity", None) if did else None
        time = getattr(did, "time", None) if did else None
        treatment = [
            c for c in (
                art.get("_did_cohort_col"), art.get("_did_treat_col"),
                art.get("_did_post_col"), art.get("_did_status_col"),
                art.get("_dcdh_treatment_col"),
            ) if c
        ]
    elif family == "panel":
        idc = art.get("_id_candidates") or []
        tc = art.get("_time_candidates") or []
        unit = idc[0] if idc else None
        time = tc[0] if tc else None

    return ResolvedRoleInputs(
        estimator_family=family,
        estimator_key=key,
        outcome=art["_normalized_y"],
        rhs=rhs,
        focal_x=list(art.get("_focal_x") or []),
        exposure=exposure if family == "regression" else None,
        unit=unit,
        time=time,
        endog=list(art.get("_iv_endog") or []),
        instruments=list(art.get("_iv_instruments") or []),
        treatment=treatment,
        cluster=art.get("_cs_cluster_var") or None,
    )
