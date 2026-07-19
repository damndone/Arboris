"""Deterministic statsmodels runner for the locked LMM recipe."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from .input import prepare_lmm_input
from .result import dataset_fingerprint_for_csv, normalize_lmm_result


def _fit_prepared(prepared: Any) -> Any:
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        return smf.mixedlm(
            prepared.formula,
            prepared.frame,
            groups=prepared.frame[prepared.input.subject_id],
            re_formula=(
                "1 + " + f"Q({prepared.input.time!r})"
                if prepared.input.random_slope
                else "1"
            ),
        ).fit(
            reml=prepared.input.fit_method == "reml",
            method="lbfgs",
            maxiter=200,
            disp=False,
        )


def _write_contract(run_root: Path, result: Mapping[str, Any]) -> None:
    output_path = Path(run_root) / "linear_mixed_effects_contract.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )


def fit_linear_mixed_effects(
    *,
    csv_path: Path,
    outcome: str,
    controls: Sequence[str],
    options: Mapping[str, object],
    run_root: Path,
) -> tuple[dict[str, Any], Any]:
    """Fit the v1 recipe and persist its deterministic contract facts."""

    source_path = Path(csv_path)
    source_frame = pd.read_csv(source_path, float_precision="round_trip")
    prepared = prepare_lmm_input(
        source_frame,
        outcome=outcome,
        controls=controls,
        options=options,
    )
    fitted = _fit_prepared(prepared)

    result = normalize_lmm_result(
        dataset_fingerprint=dataset_fingerprint_for_csv(source_path),
        source_row_count=len(source_frame),
        outcome=outcome,
        prepared=prepared,
        fitted=fitted,
    )
    _write_contract(run_root, result)
    return result, fitted


def fit_from_context(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    """Engine-handler adapter using only normalized context and bound options."""

    options = ctx.artifacts.get("_model_options")
    outcome = ctx.artifacts.get("_normalized_y", ctx.y_col)
    controls = ctx.artifacts.get("_normalized_x", ctx.x_cols)
    if not isinstance(outcome, str) or not isinstance(options, Mapping):
        raise ValueError("LMM_INVALID_CONFIGURATION: normalized outcome and options are required")
    if not isinstance(controls, list) or not all(isinstance(item, str) for item in controls):
        raise ValueError("LMM_INVALID_CONFIGURATION: normalized controls must be a list of strings")

    env.progress("linear_mixed_effects", "Starting Linear Mixed Effects fit.")
    prepared = prepare_lmm_input(
        ctx.data.frame,
        outcome=outcome,
        controls=controls,
        options=options,
    )
    fitted = _fit_prepared(prepared)
    fingerprint = ctx.artifacts.get("_upload_hash") or ctx.data.artifact_id
    result = normalize_lmm_result(
        dataset_fingerprint=str(fingerprint),
        source_row_count=len(ctx.data.frame),
        outcome=outcome,
        prepared=prepared,
        fitted=fitted,
    )
    ctx.artifacts["_linear_mixed_effects_result"] = result
    _write_contract(env.run_root, result)
    env.progress("linear_mixed_effects", "Linear Mixed Effects fit completed.")
    env.checkpoint()
    return "linear_mixed_effects_1", result, fitted
