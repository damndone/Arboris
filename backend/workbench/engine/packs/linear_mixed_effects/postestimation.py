"""Verified fixed-effect design for population LMM marginal derivatives."""
from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
from patsy import dmatrix

from ....contracts.model.inference_kernel import estimation_rows_fingerprint
from ....formula_terms import public_term
from ....postestimation.core import PostestimationRefusal
from ....postestimation.design import design_from_patsy
from ....services.lmm_result_adapter import read_lmm_public_results_from_pinned_run
from ....services.pinned_run_directory import PinnedRunError, open_pinned_run_directory
from .input import prepare_lmm_input



def population_design(run_root, kernel):
    from ....postestimation.comparison_data import _bound_bytes, assert_completed_kernel
    from ....postestimation.estimation_data import _dataset_path

    try:
        assert_completed_kernel(run_root, kernel)
        with open_pinned_run_directory(run_root.parent, run_root.name) as pinned:
            records = read_lmm_public_results_from_pinned_run(pinned)
            matches = [record for record in records if record["model_id"] == kernel["model_id"]]
            if len(matches) != 1:
                raise ValueError("model packet identity is not unique")
            payload = matches[0]["payload"]
            seal_bytes = pinned.read_execution_seal()
        if hashlib.sha256(seal_bytes).hexdigest() != payload["execution_binding"]["executed_input_digest"]:
            raise ValueError("executed options no longer match the result binding")
        if payload["status"] != "complete" or not payload["converged"]:
            raise ValueError("model fit did not complete")
        sealed = json.loads(seal_bytes)
        summary = json.loads(_bound_bytes(run_root, run_root / "diagnostic_summary.json"))
        identity = summary["model_identity"]
        frame = pd.read_parquet(io.BytesIO(_bound_bytes(run_root, _dataset_path(run_root))))
        prepared = prepare_lmm_input(frame, outcome=identity["y_variable"],
            controls=identity["x_variables"], options=sealed["model_options"])
        if prepared.formula != payload["fixed_effects_formula"]:
            raise ValueError("fixed-effect design differs from the completed model")
        design = dmatrix(prepared.formula.split(" ~ ", 1)[1], prepared.frame, return_type="dataframe")
        names = [public_term(name) for name in design.columns]
        if names != list(kernel["param_names"]) or len(design) != kernel["nobs"]:
            raise ValueError("design does not match the kernel parameters or observations")
        if estimation_rows_fingerprint(list(design.index)) != kernel["estimation_sample_fingerprint"]:
            raise ValueError("estimation rows changed")
        return design_from_patsy(design, design.design_info,
            continuous_variables=[prepared.input.time, *identity["x_variables"]])
    except (OSError, ValueError, KeyError, TypeError, PinnedRunError) as exc:
        if isinstance(exc, PostestimationRefusal):
            raise
        raise PostestimationRefusal("ESTIMATION_DATA_UNAVAILABLE", "The completed LMM fixed-effect design or its execution binding cannot be verified") from exc
