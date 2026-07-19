from __future__ import annotations

from copy import deepcopy

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.linear_mixed_effects import LmmDiagnostic
from workbench.model_options import (
    ModelOptionsError,
    verify_bound_model_options,
)

from tests.evaluation.linear_mixed_effects._candidate import require_candidate_module


SOURCE_OPTIONS = {
    "subject_id": "participant_id",
    "time": "week",
    "group": "arm",
    "fit_method": "reml",
    "random_slope": True,
}
SOURCE_BINDING = {
    "owner_model_type": "linear_mixed_effects",
    "owner_model_id": "linear_mixed_effects_1",
    "producer_version": "linear_mixed_effects@1.0",
    "input_contract_version": "1.0",
    "normalized_options_hash": "a5bfb0cb983acb1fd5909622ec3fe9eed7d04de2a2b7c3f21d6b49f66f7457e5",
}
SOURCE = {
    "model_type": "linear_mixed_effects",
    "model_options": SOURCE_OPTIONS,
    "model_options_binding": SOURCE_BINDING,
}
RECOVERY = {
    "action_id": "lmm.simplify_random_effects_v1",
    "operation_id": "model.rerun",
    "patch": {"model_options": {"random_slope": False}},
    "required_confirmation": True,
}


def _recoverable_diagnostic() -> dict[str, object]:
    return LmmDiagnostic(
        code="LMM_RANDOM_SLOPE_NEAR_ZERO",
        severity="warning",
        status="complete",
        evidence={"slope_variance": 0.0},
        action_candidate=RECOVERY,
    ).to_dict()


def _blocking_diagnostic(code: str, status: str) -> dict[str, object]:
    return LmmDiagnostic(
        code=code,
        severity="error",
        status=status,
        evidence={"fixture": "evaluation"},
        action_candidate=None,
    ).to_dict()


def _recipe(source: dict[str, object], diagnostics: list[dict[str, object]]) -> dict[str, object]:
    module = require_candidate_module(
        "workbench.agent.recipes.repeated_measures"
    )
    result = module.build_repeated_measures_recipe(
        source=source,
        diagnostics=diagnostics,
    )
    assert isinstance(result, dict)
    return result


def test_agent_source_fixture_has_a_valid_c1_server_owned_binding() -> None:
    bound = verify_bound_model_options(SOURCE_OPTIONS, SOURCE_BINDING)

    assert bound.payload == SOURCE_OPTIONS
    assert bound.binding is not None
    assert bound.binding.to_dict() == SOURCE_BINDING


def test_recoverable_random_slope_produces_one_confirmable_rerun() -> None:
    source = deepcopy(SOURCE)
    recipe = _recipe(source, [_recoverable_diagnostic()])

    assert source == SOURCE
    assert recipe["proposal"] == {
        "operation": "model.rerun",
        "patch": {"model_options": {"random_slope": False}},
        "requires_confirmation": True,
    }
    assert "execution" not in recipe
    assert "child_run" not in recipe


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("LMM_SUBJECT_ID_MISSING", "blocked"),
        ("LMM_TIME_NOT_NUMERIC", "blocked"),
        ("LMM_GROUP_NOT_BINARY", "blocked"),
        ("LMM_GROUP_VARIES_WITHIN_SUBJECT", "blocked"),
        ("LMM_INSUFFICIENT_REPEATED_OBSERVATIONS", "blocked"),
        ("LMM_CONVERGENCE_FAILED", "failed"),
    ],
)
def test_blocking_diagnostics_never_create_a_proposal(code: str, status: str) -> None:
    recipe = _recipe(deepcopy(SOURCE), [_blocking_diagnostic(code, status)])

    assert recipe["proposal"] is None


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        (
            {"model_type": "linear_mixed_effects", "model_options": SOURCE_OPTIONS},
            "MODEL_OPTIONS_OWNER_MISSING",
        ),
        (
            {
                **SOURCE,
                "model_options_binding": {
                    **SOURCE_BINDING,
                    "normalized_options_hash": "0" * 64,
                },
            },
            "MODEL_OPTIONS_INTEGRITY_ERROR",
        ),
        (
            {
                **SOURCE,
                "model_options_binding": {
                    **SOURCE_BINDING,
                    "owner_model_id": "foreign_lmm_1",
                },
            },
            "MODEL_OPTIONS_OWNER_MISMATCH",
        ),
    ],
)
def test_invalid_source_binding_never_creates_a_proposal(
    source: dict[str, object], expected_code: str
) -> None:
    with pytest.raises(ModelOptionsError) as error:
        _recipe(deepcopy(source), [_recoverable_diagnostic()])

    assert error.value.code == expected_code


def test_malformed_diagnostic_never_creates_a_proposal() -> None:
    malformed = _recoverable_diagnostic()
    malformed.pop("severity")

    recipe = _recipe(deepcopy(SOURCE), [malformed])

    assert recipe["proposal"] is None


def test_unknown_diagnostic_and_patch_fail_closed() -> None:
    module = require_candidate_module(
        "workbench.agent.recipes.repeated_measures"
    )
    recipe = _recipe(
        deepcopy(SOURCE),
        [
            {
                "code": "LMM_UNKNOWN_DIAGNOSTIC",
                "severity": "warning",
                "status": "complete",
                "evidence": {"fixture": "evaluation"},
                "action_candidate": RECOVERY,
            }
        ],
    )

    assert recipe["proposal"] is None
    with pytest.raises(ValueError, match="unsupported LMM recovery patch"):
        module.validate_recovery_patch({"model_options": {"fit_method": "ml"}})


def test_malformed_lmm_diagnostic_fixture_is_rejected_by_c1() -> None:
    malformed = _recoverable_diagnostic()
    malformed.pop("severity")

    with pytest.raises((ContractError, TypeError)):
        LmmDiagnostic(**malformed)
