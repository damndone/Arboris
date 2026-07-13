import pytest

import workbench.engine.stages.estimation  # noqa: F401  (populate MODEL_REGISTRY)
from workbench.lineage.op_contract import (
    OpOverrideError,
    resolve_operation_contract,
    resolve_overrides_target,
    validate_overrides,
)


def test_resolve_model_node_by_effective_model_type():
    manifest = {"model_routing": {"effective_model_type": "iv_2sls"}}
    contract = resolve_operation_contract(stage="model", manifest=manifest)
    assert contract is not None
    assert contract.op_type == "iv_2sls"
    assert contract.schema_id == "iv_2sls@v1"
    assert {p["key"] for p in contract.editable_schema} >= {"iv_endog", "covariance", "x"}


def test_ols_contract_exposes_regressors():
    contract = resolve_operation_contract(
        stage="model", manifest={"model_routing": {"effective_model_type": "ols"}}
    )
    assert contract is not None
    regressors = next(p for p in contract.editable_schema if p["key"] == "x")
    assert regressors["kind"] == "columns"


def test_resolve_uses_requested_model_type_when_effective_is_engine_id():
    # Real manifest shape: effective_model_type is an engine id ("ols_robust"),
    # requested_model_type is the capabilities key ("ols").
    manifest = {"model_routing": {
        "requested_model_type": "ols", "effective_model_type": "ols_robust"}}
    contract = resolve_operation_contract(stage="model", manifest=manifest)
    assert contract is not None and contract.op_type == "ols"


def test_resolve_normalizes_effective_id_for_auto_runs():
    # Auto run: requested is "auto" (no params); fall back to normalizing the
    # effective engine id by longest-prefix match -> "ols".
    manifest = {"model_routing": {
        "requested_model_type": "auto", "effective_model_type": "ols_robust"}}
    contract = resolve_operation_contract(stage="model", manifest=manifest)
    assert contract is not None and contract.op_type == "ols"


def test_non_editable_stage_returns_none():
    assert resolve_operation_contract(stage="clean", manifest={}) is None


def test_unresolvable_model_type_returns_none():
    assert resolve_operation_contract(
        stage="model", manifest={"model_routing": {"effective_model_type": "???"}}
    ) is None


def test_validate_rejects_unknown_key():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    with pytest.raises(OpOverrideError):
        validate_overrides(c, {"not_a_field": "x"})


def test_validate_rejects_bad_enum():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    with pytest.raises(OpOverrideError):
        validate_overrides(c, {"covariance": "not_an_option"})


def test_validate_accepts_good_override():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    validate_overrides(c, {"covariance": "robust"})  # no raise


def test_model_type_switch_uses_new_schema():
    manifest = {"model_routing": {"effective_model_type": "ols"}}
    c = resolve_operation_contract(stage="model", manifest=manifest)
    switched = resolve_overrides_target(c, {"model_type": "iv_2sls"})
    assert switched.op_type == "iv_2sls"
    validate_overrides(switched, {"model_type": "iv_2sls", "iv_endog": "[\"educ\"]",
                                  "iv_instruments": "[\"nearc\"]"})
