"""Deterministic statsmodels runner for the locked LMM recipe."""

from __future__ import annotations

import json
import os
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from workbench.contracts.common.envelope import PacketEnvelope
from workbench.canonical import canonical_json_v1
from workbench.services.pinned_run_directory import PinnedRunDirectory, PinnedRunError, SealedExecutionInput

from .covariance import REML_LIKELIHOOD_REASON, GlsFixedEffectResults
from .diagnostics import terminal_input_error_diagnostic
from .input import LmmInputError, prepare_lmm_input
from .packets import build_lmm_diagnostic_packet, build_lmm_recovery_packet
from .result import (
    build_lmm_result_packet,
    build_unexpected_fit_failure_result_packet,
    dataset_fingerprint_for_csv,
)


_TERMINAL_RESULT_ARTIFACT_ID = "model_results.linear_mixed_effects_1"
_TERMINAL_RESULT_PATH = "artifacts/model_results/linear_mixed_effects_1.result.json"


def _fit_prepared(prepared: Any) -> Any:
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        model = smf.mixedlm(
            prepared.formula,
            prepared.frame,
            groups=prepared.frame[prepared.input.subject_id],
            re_formula=(
                "1 + " + f"Q({prepared.input.time!r})"
                if prepared.input.random_slope
                else "1"
            ),
        )
        reml = prepared.input.fit_method == "reml"
        fitted = model.fit(reml=reml, method="lbfgs", maxiter=200, disp=False)
        if not fitted.converged:
            return fitted
        fitted = _refined(model, reml, fitted)
    # Report fixed-effect inference on the covariance lme4 and Stata report.
    return GlsFixedEffectResults(fitted)


def _refined(model: Any, reml: bool, fitted: Any) -> Any:
    # L-BFGS-B's default stopping leaves variance ratios ~1e-5 short of the
    # (RE)ML optimum that lme4 reaches. A tighter refit reaches it to ~1e-8;
    # it is kept only when it also converges without lowering the likelihood,
    # so boundary fits it cannot certify keep the first result.
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        refined = model.fit(
            reml=reml, method="lbfgs", maxiter=200, pgtol=1e-10, factr=10, disp=False
        )
    if refined.converged and refined.llf >= fitted.llf:
        return refined
    return fitted


def _persist_result_packets(admission: object, result_packet: Mapping[str, Any]) -> None:
    """Persist result and its C1 diagnostic/recovery companion packets."""

    result = PacketEnvelope.from_dict(result_packet).to_dict()
    payload = result["payload"]
    diagnostics = payload["diagnostics"]
    assert isinstance(payload["status"], str)
    assert isinstance(diagnostics, list)
    from workbench.services.pinned_run_directory import (
        _persist_lmm_diagnostic_packet,
        _persist_lmm_recovery_packet,
        _persist_lmm_terminal_packet,
    )
    terminal = _persist_lmm_terminal_packet(admission=admission, packet=result)
    diagnostic_packet = build_lmm_diagnostic_packet(
        status=payload["status"],
        diagnostics=diagnostics,
    )
    _persist_lmm_diagnostic_packet(admission=admission, packet=diagnostic_packet, terminal=terminal)
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            continue
        candidate = diagnostic.get("action_candidate")
        if isinstance(candidate, Mapping):
            _persist_lmm_recovery_packet(
                admission=admission,
                packet=build_lmm_recovery_packet(candidate),
                terminal=terminal,
            )
            break


def _assert_terminal_result_slot_is_empty(run_root: Path, result_path: Path) -> None:
    """Prevent a second terminal write from overwriting its evidence or index."""

    if os.path.lexists(result_path):
        raise RuntimeError("LMM_TERMINAL_RESULT_ALREADY_EXISTS")
    index_path = run_root / "artifacts_index.json"
    if not os.path.lexists(index_path):
        return
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        artifacts = index["artifacts"]
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("LMM_ARTIFACT_INDEX_INVALID") from exc
    if type(artifacts) is not list:
        raise RuntimeError("LMM_ARTIFACT_INDEX_INVALID")
    for record in artifacts:
        if not isinstance(record, Mapping):
            raise RuntimeError("LMM_ARTIFACT_INDEX_INVALID")
        if (
            record.get("artifact_id") == _TERMINAL_RESULT_ARTIFACT_ID
            or record.get("path") == _TERMINAL_RESULT_PATH
            or record.get("artifact_type") == "model_result_packet"
        ):
            raise RuntimeError("LMM_TERMINAL_RESULT_ALREADY_EXISTS")


def _fit_and_build_terminal_result(
    *,
    dataset_fingerprint: str,
    source_row_count: int,
    outcome: str,
    prepared: Any,
    sealed_execution_input: SealedExecutionInput,
) -> tuple[dict[str, Any], Any | None]:
    """Contain post-preparation exceptions in a non-disclosing terminal packet."""

    try:
        fitted = _fit_prepared(prepared)
    except Exception:
        return (
            build_unexpected_fit_failure_result_packet(
                dataset_fingerprint=dataset_fingerprint,
                source_row_count=source_row_count,
                outcome=outcome,
                prepared=prepared,
                execution_binding=_execution_binding(sealed_execution_input),
            ),
            None,
        )
    return (
        build_lmm_result_packet(
            dataset_fingerprint=dataset_fingerprint,
            source_row_count=source_row_count,
            outcome=outcome,
            prepared=prepared,
            fitted=fitted,
            execution_binding=_execution_binding(sealed_execution_input),
        ),
        fitted,
    )


def _execution_binding(seal: SealedExecutionInput) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": seal.run_id,
        "executed_input_digest": seal.digest,
    }


def _require_live_seal(
    sealed_execution_input: object, pinned_run: object, run_root: Path,
    options: object, model_options_binding: object,
) -> tuple[SealedExecutionInput, PinnedRunDirectory]:
    if not isinstance(sealed_execution_input, SealedExecutionInput) or not isinstance(pinned_run, PinnedRunDirectory):
        raise RuntimeError("LMM_EXECUTION_BINDING_REQUIRED")
    try:
        if Path(run_root).name != sealed_execution_input.run_id:
            raise PinnedRunError("LMM_EXECUTION_BINDING_INVALID")
        expected = canonical_json_v1({
            "schema_version": 1,
            "model_type": "linear_mixed_effects",
            "model_options": options,
            "model_options_binding": model_options_binding,
        }).encode("utf-8")
        if expected != sealed_execution_input.canonical_bytes:
            raise PinnedRunError("LMM_EXECUTION_BINDING_INVALID")
        pinned_run.verify_sealed_execution_input(sealed_execution_input)
    except PinnedRunError as exc:
        raise RuntimeError("LMM_EXECUTION_BINDING_INVALID") from exc
    return sealed_execution_input, pinned_run


def fit_linear_mixed_effects(
    *,
    csv_path: Path,
    outcome: str,
    controls: Sequence[str],
    options: Mapping[str, object],
    run_root: Path,
    sealed_execution_input: SealedExecutionInput | None = None,
    pinned_run: PinnedRunDirectory | None = None,
    model_options_binding: Mapping[str, object] | None = None,
    lmm_execution_admission: object | None = None,
) -> tuple[dict[str, Any], Any]:
    """Fit the v1 recipe and persist its deterministic contract facts."""

    from workbench.services.pinned_run_directory import (
        _commit_lmm_execution_admission,
        _consume_lmm_execution_admission,
        _consume_lmm_provisional_admission_for_preflight,
        _invalidate_lmm_execution_admission,
        _persist_lmm_input_blocked_diagnostic,
    )
    if lmm_execution_admission is None:
        raise RuntimeError("LMM_EXECUTION_BINDING_REQUIRED")
    live_pinned_run, seal = _consume_lmm_provisional_admission_for_preflight(
        lmm_execution_admission
    )
    seal, live_pinned_run = _require_live_seal(seal, live_pinned_run, run_root, options, model_options_binding)
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
        blocked = _invalidate_lmm_execution_admission(lmm_execution_admission, error.code)
        diagnostic = terminal_input_error_diagnostic(error)
        packet = build_lmm_diagnostic_packet(
            status=diagnostic.status,
            diagnostics=[diagnostic.to_dict()],
        )
        _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=packet)
        raise
    _commit_lmm_execution_admission(lmm_execution_admission)
    live_pinned_run, seal = _consume_lmm_execution_admission(lmm_execution_admission)
    result, fitted = _fit_and_build_terminal_result(
        dataset_fingerprint=dataset_fingerprint_for_csv(source_path),
        source_row_count=len(source_frame),
        outcome=outcome,
        prepared=prepared,
        sealed_execution_input=seal,
    )
    _require_live_seal(seal, live_pinned_run, run_root, options, model_options_binding)
    _persist_result_packets(lmm_execution_admission, result)
    return result, fitted


def _record_fixed_effects_kernel(ctx: Any, fitted: Any, *, result_status: str = "complete") -> None:
    """Expose fixed effects, with their actual fitted covariance block.

    Only a completed result offers them: a fit that did not converge or failed
    its diagnostics has no estimates fit to test.
    """
    from workbench.contracts.model.inference_kernel import kernel_from_fitted, unavailable_inference_kernel
    from workbench.engine.inference_kernels import record_inference_kernel
    from workbench.econometrics.normalize import _public_term

    if fitted is None:
        return
    if result_status != "complete":
        record_inference_kernel(ctx, unavailable_inference_kernel(model_id="linear_mixed_effects_1",
            model_type="linear_mixed_effects", nobs=int(getattr(fitted, "nobs", 0) or 0),
            reason="The LMM fit did not complete (it did not converge or failed its diagnostics), "
                   "so its estimates are not offered for post-estimation."))
        return
    fixed = getattr(fitted, "fe_params", None)
    params = getattr(fitted, "params", None)
    try:
        names = list(params.index)
        fixed_names = list(fixed.index)
        if len(set(names)) != len(names) or len(set(fixed_names)) != len(fixed_names):
            raise ValueError("Fixed-effect parameter mapping is ambiguous.")
        positions = tuple(names.index(name) for name in fixed_names)
        view = fitted.kernel_view() if isinstance(fitted, GlsFixedEffectResults) else fitted
        reml = isinstance(fitted, GlsFixedEffectResults) and fitted.is_reml
        kernel = kernel_from_fitted(view, model_id="linear_mixed_effects_1",
            model_type="linear_mixed_effects", nobs=int(fitted.nobs),
            param_positions=positions, public_name=_public_term,
            unavailable={"loglik": REML_LIKELIHOOD_REASON} if reml else None)
    except (AttributeError, ValueError, TypeError):
        kernel = None
    if kernel is None:
        kernel = unavailable_inference_kernel(model_id="linear_mixed_effects_1",
            model_type="linear_mixed_effects", nobs=int(getattr(fitted,"nobs",0)),
            reason="The runtime cannot identify the fixed-effect covariance block.")
    record_inference_kernel(ctx, kernel)


def fit_from_context(ctx: Any, env: Any) -> tuple[str, dict[str, Any], Any]:
    """Engine-handler adapter using only normalized context and bound options."""

    from workbench.services.pinned_run_directory import (
        _commit_lmm_execution_admission,
        _consume_lmm_execution_admission,
        _consume_lmm_provisional_admission_for_preflight,
        _invalidate_lmm_execution_admission,
        _persist_lmm_input_blocked_diagnostic,
    )
    admission = getattr(env, "lmm_execution_admission", None)
    live_pinned_run, admission_seal = _consume_lmm_provisional_admission_for_preflight(admission)
    seal, live_pinned_run = _require_live_seal(
        admission_seal, live_pinned_run, env.run_root,
        ctx.artifacts.get("_model_options"), ctx.artifacts.get("_model_options_binding"),
    )
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
        blocked = _invalidate_lmm_execution_admission(admission, error.code)
        diagnostic = terminal_input_error_diagnostic(error)
        packet = build_lmm_diagnostic_packet(status=diagnostic.status, diagnostics=[diagnostic.to_dict()])
        _persist_lmm_input_blocked_diagnostic(admission=blocked, packet=packet)
        ctx.artifacts["_linear_mixed_effects_diagnostic"] = diagnostic.to_dict()
        raise
    _commit_lmm_execution_admission(admission)
    live_pinned_run, admission_seal = _consume_lmm_execution_admission(admission)
    fingerprint = ctx.artifacts.get("_upload_hash") or ctx.data.artifact_id
    result, fitted = _fit_and_build_terminal_result(
        dataset_fingerprint=str(fingerprint),
        source_row_count=len(ctx.data.frame),
        outcome=outcome,
        prepared=prepared,
        sealed_execution_input=seal,
    )
    _require_live_seal(seal, live_pinned_run, env.run_root, options, ctx.artifacts.get("_model_options_binding"))
    ctx.artifacts["_linear_mixed_effects_result"] = result
    _record_fixed_effects_kernel(ctx, fitted, result_status=str(result["payload"]["status"]))
    _persist_result_packets(admission, result)
    env.progress("linear_mixed_effects", "Linear Mixed Effects fit completed.")
    env.checkpoint()
    return "linear_mixed_effects_1", result, fitted
