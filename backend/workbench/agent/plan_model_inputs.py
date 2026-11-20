"""Bounded model input checks for plan review, without running a fit."""
from __future__ import annotations

import numpy as np

from ..contracts.model.family import model_family_contract
from ..econometrics.fit_support import _ensure_numeric_x, _ensure_numeric_y
from ..model_terms import expand_branch_terms


def _check_numeric_sample(frame, outcome, predictors):
    columns = list(dict.fromkeys([outcome, *predictors]))
    selected = _ensure_numeric_y(frame.loc[:, columns].copy(), outcome)
    selected = _ensure_numeric_x(selected, predictors).dropna()
    if selected.empty:
        raise ValueError("There are no complete rows for the declared outcome and predictors.")
    if not np.isfinite(selected.select_dtypes(include="number").to_numpy(dtype=float)).all():
        raise ValueError("The complete input rows contain nonfinite numeric values.")
    return selected


def check_model_inputs(frame, spec) -> str | None:
    """Check the root frame with the model's own input preparation and validators."""
    family = spec["model_family"]
    contract = model_family_contract(family)
    if spec.get("by_group") or spec.get("multiple_imputations"):
        return None  # The execution sample differs from the unpartitioned input.
    if family not in {"ols", "panel_ols", "iv_2sls", "did", "cs_did", "sa_did"} and contract.validate_branch_frame is None:
        return None
    for branch in spec["branches"]:
        branch_frame, predictors, _ = expand_branch_terms(frame, branch)
        outcome = branch["outcome"]
        if contract.validate_branch_frame is not None:
            contract.validate_branch_frame(branch_frame, {**branch, "model_options": spec.get("model_options") or {}})
        elif family in {"did", "cs_did", "sa_did"}:
            from ..engine.did_spec import validate_did_spec

            params = contract.build_model_params(spec, branch, predictors, contract.default_covariance)
            validate_did_spec(branch_frame, mode=params["did_mode"], entity=params["entity_col"],
                time=params["time_col"], y=outcome, cohort=params.get("did_cohort_col"),
                treat=params.get("did_treat_col"), post=params.get("did_post_col"), status=params.get("did_status_col"))
            _check_numeric_sample(branch_frame, outcome, predictors)
        elif family == "iv_2sls":
            from ..econometrics.panel_iv import _all_numeric, _iv_2sls_without_incomplete_rows
            from ..engine.iv_spec import validate_iv_spec

            endog, instruments = spec["iv_endog"], spec["iv_instruments"]
            validate_iv_spec(y=outcome, exog=predictors, endog=endog, instruments=instruments)
            design = [*predictors, *endog, *instruments]
            if len(design) > 64 or len(branch_frame) > 20_000:
                return None
            rows = _check_numeric_sample(branch_frame, outcome, design)
            if not _all_numeric(rows, [outcome, *design]):
                return None  # The reference formula encodes categorical predictors at execution.
            try:
                from linearmodels import iv
            except ImportError:
                return None
            _iv_2sls_without_incomplete_rows(iv, rows, outcome, predictors, endog, instruments)
        else:
            _check_numeric_sample(branch_frame, outcome, predictors)
    if family == "iv_2sls":
        return "The reference IV input constructor accepted the complete rows and instrument design."
    if family in {"did", "cs_did", "sa_did"}:
        return "The DID input validator accepted the unit-period and treatment declarations."
    if contract.validate_branch_frame is not None:
        return "The model family's input validator accepted the bound branch data."
    return "The bound branch data has a numeric outcome and usable rows for its declared predictors."
