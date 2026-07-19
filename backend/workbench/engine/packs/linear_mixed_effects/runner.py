"""Deterministic statsmodels runner for the locked LMM recipe."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from workbench.contracts.common.envelope import PacketEnvelope

from .diagnostics import terminal_input_error_diagnostic
from .input import LmmInputError, prepare_lmm_input
from .packets import build_lmm_diagnostic_packet, build_lmm_recovery_packet
from .result import build_lmm_result_packet, dataset_fingerprint_for_csv


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


def _write_packet(run_root: Path, filename: str, packet: Mapping[str, Any]) -> None:
    """Persist a C1 envelope only after validating its exact public wire shape."""

    parsed = PacketEnvelope.from_dict(packet)
    output_path = Path(run_root) / filename
    output_path.write_text(
        json.dumps(parsed.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )


def _persist_result_packets(run_root: Path, result_packet: Mapping[str, Any]) -> None:
    """Persist result and its C1 diagnostic/recovery companion packets."""

    result = PacketEnvelope.from_dict(result_packet).to_dict()
    payload = result["payload"]
    diagnostics = payload["diagnostics"]
    assert isinstance(payload["status"], str)
    assert isinstance(diagnostics, list)
    _write_packet(run_root, "linear_mixed_effects_contract.json", result)
    diagnostic_packet = build_lmm_diagnostic_packet(
        status=payload["status"],
        diagnostics=diagnostics,
    )
    _write_packet(run_root, "linear_mixed_effects_diagnostic.json", diagnostic_packet)
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            continue
        candidate = diagnostic.get("action_candidate")
        if isinstance(candidate, Mapping):
            _write_packet(
                run_root,
                "linear_mixed_effects_recovery_proposal.json",
                build_lmm_recovery_packet(candidate),
            )
            break


def _persist_input_error_packet(run_root: Path, error: LmmInputError) -> dict[str, Any]:
    """Persist the existing input error as a C1 diagnostic packet, then re-raise."""

    diagnostic = terminal_input_error_diagnostic(error)
    packet = build_lmm_diagnostic_packet(
        status=diagnostic.status,
        diagnostics=[diagnostic.to_dict()],
    )
    _write_packet(run_root, "linear_mixed_effects_diagnostic.json", packet)
    return packet


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
    try:
        prepared = prepare_lmm_input(
            source_frame,
            outcome=outcome,
            controls=controls,
            options=options,
        )
    except LmmInputError as error:
        _persist_input_error_packet(Path(run_root), error)
        raise
    fitted = _fit_prepared(prepared)

    result = build_lmm_result_packet(
        dataset_fingerprint=dataset_fingerprint_for_csv(source_path),
        source_row_count=len(source_frame),
        outcome=outcome,
        prepared=prepared,
        fitted=fitted,
    )
    _persist_result_packets(run_root, result)
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
    try:
        prepared = prepare_lmm_input(
            ctx.data.frame,
            outcome=outcome,
            controls=controls,
            options=options,
        )
    except LmmInputError as error:
        ctx.artifacts["_linear_mixed_effects_diagnostic"] = _persist_input_error_packet(
            env.run_root, error
        )
        raise
    fitted = _fit_prepared(prepared)
    fingerprint = ctx.artifacts.get("_upload_hash") or ctx.data.artifact_id
    result = build_lmm_result_packet(
        dataset_fingerprint=str(fingerprint),
        source_row_count=len(ctx.data.frame),
        outcome=outcome,
        prepared=prepared,
        fitted=fitted,
    )
    ctx.artifacts["_linear_mixed_effects_result"] = result
    _persist_result_packets(env.run_root, result)
    env.progress("linear_mixed_effects", "Linear Mixed Effects fit completed.")
    env.checkpoint()
    return "linear_mixed_effects_1", result, fitted
