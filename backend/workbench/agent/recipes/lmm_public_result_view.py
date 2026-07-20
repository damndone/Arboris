"""Read-only, fail-closed projection of one persisted LMM run into WO-A text."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmModelInput,
    lookup_registered_lmm_contract_without_bootstrap,
    validate_lmm_executed_options_v1,
)
from workbench.services.lmm_result_adapter import VersionedResultReadError, read_lmm_public_results_from_pinned_run
from workbench.services.pinned_run_directory import PinnedRunDirectory, PinnedRunError, open_pinned_run_directory
from .lmm_explanation import validate_lmm_diagnostics
from .repeated_measures import build_repeated_measures_recipe_from_validated_facts

_NEUTRAL = {"proposal": None, "plan_diff": None, "explanation": "未提供可用于生成说明的受控 LMM 诊断。"}

class _NeutralEvidence(ValueError):
    pass

def _neutral_recipe() -> dict[str, object]:
    return dict(_NEUTRAL)

def _select_verified_lmm_result(results: list[dict[str, object]]) -> dict[str, object]:
    matches = [result for result in results if (
        result.get("model_id") == "linear_mixed_effects_1"
        and result.get("model_type") == LMM_MODEL_TYPE
        and result.get("source_contract") == "linear_mixed_effects.result"
        and result.get("source_contract_version") == LMM_CONTRACT_VERSION
        and result.get("source_producer_version") == "linear_mixed_effects@1.0"
    )]
    if len(matches) != 1:
        raise _NeutralEvidence
    return matches[0]

def _representation_and_input(snapshot: Mapping[str, object]) -> tuple[dict[str, object], LmmModelInput]:
    executed = snapshot.get("executed_payload")
    if not isinstance(executed, Mapping) or executed.get("model_type") != LMM_MODEL_TYPE:
        raise _NeutralEvidence
    try:
        model_input = validate_lmm_executed_options_v1(
            executed.get("model_options"), executed.get("model_options_binding")
        )
    except (ContractError, TypeError, ValueError):
        raise _NeutralEvidence from None
    representation = {
        "schema_version": 1, "model_type": LMM_MODEL_TYPE,
        "model_options": model_input.to_dict(),
        "model_options_binding": dict(executed["model_options_binding"]),
    }
    return representation, model_input

def _verify_bound_current_run(
    result: Mapping[str, object], pinned_run: PinnedRunDirectory, snapshot: Mapping[str, object]
) -> tuple[LmmModelInput, tuple[object, ...]]:
    payload = result.get("payload")
    binding = result.get("execution_binding")
    if not isinstance(payload, Mapping) or not isinstance(binding, Mapping):
        raise _NeutralEvidence
    if (payload.get("model_id"), payload.get("model_type"), payload.get("contract_version")) != ("linear_mixed_effects_1", LMM_MODEL_TYPE, "1.0"):
        raise _NeutralEvidence
    if result.get("model_id") != payload.get("model_id") or result.get("model_type") != payload.get("model_type"):
        raise _NeutralEvidence
    if payload.get("status") != "complete" or payload.get("converged") is not True:
        raise _NeutralEvidence
    if not all(isinstance(result.get(key), str) and result.get(key) for key in ("artifact_id", "artifact_path", "artifact_sha256", "source_packet_digest")):
        raise _NeutralEvidence
    representation, model_input = _representation_and_input(snapshot)
    if binding.get("run_id") != pinned_run.run_id or binding.get("executed_input_digest") != sha256_canonical(representation):
        raise _NeutralEvidence
    try:
        seal = pinned_run.read_execution_seal()
    except PinnedRunError:
        raise _NeutralEvidence from None
    from workbench.canonical import canonical_json_v1
    if seal != canonical_json_v1(representation).encode("utf-8"):
        raise _NeutralEvidence
    if model_input.fit_method != payload.get("fit_method"):
        raise _NeutralEvidence
    expected_random = "1" if not model_input.random_slope else "1 + Q(%r)" % model_input.time
    if payload.get("random_effects_specification") != expected_random:
        raise _NeutralEvidence
    diagnostics = validate_lmm_diagnostics(payload.get("diagnostics"))
    if diagnostics is None or not diagnostics or not lookup_registered_lmm_contract_without_bootstrap():
        raise _NeutralEvidence
    return model_input, diagnostics

def build_repeated_measures_recipe_from_run(runs_root: Path, run_id: str) -> dict[str, object]:
    """Return a presentation-only recipe; every unsuitable fact becomes neutral."""
    try:
        with open_pinned_run_directory(runs_root, run_id) as pinned_run:
            result = _select_verified_lmm_result(read_lmm_public_results_from_pinned_run(pinned_run))
            snapshot = pinned_run.read_run_inputs_snapshot().value
            model_input, diagnostics = _verify_bound_current_run(result, pinned_run, snapshot)
            recipe = build_repeated_measures_recipe_from_validated_facts(model_input, diagnostics)
    except (PinnedRunError, VersionedResultReadError, _NeutralEvidence, ContractError, TypeError, ValueError):
        return _neutral_recipe()
    return recipe if set(recipe) == set(_NEUTRAL) else _neutral_recipe()

__all__ = ["build_repeated_measures_recipe_from_run"]
