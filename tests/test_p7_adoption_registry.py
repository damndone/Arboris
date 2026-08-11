"""P7 adoption registry must be complete before workflow integration."""

from __future__ import annotations

from dataclasses import replace

import pytest


def test_frozen_p7_declarations_have_one_typed_adapter_each() -> None:
    """Every frozen operation is registered exactly once and fails closed."""

    from workbench.agent.p7_pack_registry import (
        declared_p7_operation_ids,
        p7_pack_registry,
    )

    declared = declared_p7_operation_ids()
    assert declared
    assert set(p7_pack_registry.operation_ids()) == declared
    for operation_id in declared:
        operation = p7_pack_registry.get(operation_id)
        assert operation.operation_id == operation_id
        assert operation.pack_family
        assert operation.input_mode in {"frame", "typed"}
        assert callable(operation.validate_request)
        assert callable(operation.execute)
        assert callable(operation.validate_result)


def test_registry_rejects_duplicate_or_missing_adapter_declarations() -> None:
    """The registry must not silently overwrite or omit an operation."""

    from workbench.agent.p7_pack_registry import (
        P7PackOperation,
        P7PackRegistry,
        P7PackRegistryError,
    )

    operation = P7PackOperation(
        operation_id="test.p7",
        pack_family="test",
        input_mode="typed",
        validate_request=lambda value: value,
        extract_columns=lambda value: (),
        execute=lambda value: value,
        validate_result=lambda value: value,
    )
    with pytest.raises(P7PackRegistryError, match="duplicate"):
        P7PackRegistry((operation, operation))


def test_registry_entry_rejects_a_request_for_another_operation() -> None:
    """A registry entry must fail closed when request identity does not match."""

    from workbench.agent.p7_pack_registry import P7PackRegistryError, p7_pack_registry

    operation = p7_pack_registry.get("categorical.cramers_v")
    with pytest.raises(P7PackRegistryError, match="operation_id"):
        operation.validate(
            {
                "operation_id": "categorical.mcnemar",
                "input_mode": "typed",
                "column_bindings": {"row": "row", "column": "column"},
                "options": {"correction": False, "exact": False},
            }
        )


def test_declared_operation_projection_includes_an_injected_family_entry() -> None:
    """The denominator is derived from declarations, including future additions."""

    from workbench.agent.p7_pack_registry import (
        P7FamilyDeclaration,
        P7_FAMILY_DECLARATIONS,
        declared_p7_operation_ids,
    )

    injected = P7FamilyDeclaration(
        "test_future_pack",
        frozenset({"test.future_operation"}),
        "typed",
        "test.future.result",
    )
    projected = declared_p7_operation_ids((*P7_FAMILY_DECLARATIONS, injected))
    assert "test.future_operation" in projected


def test_generated_step_contract_pins_the_registered_input_mode() -> None:
    """A generated P7 step cannot silently switch between frame and typed input."""

    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    for operation_id in p7_pack_registry.operation_ids():
        operation = p7_pack_registry.get(operation_id)
        contract = WORKFLOW_STEP_SPEC_CONTRACTS[operation_id]
        assert "input_mode" in contract.required
        assert contract.field_enums["input_mode"] == (operation.input_mode,)


def test_generated_step_contract_uses_the_declared_result_contract() -> None:
    """Workflow output references must come from the frozen family contract."""

    from workbench.agent.p7_pack_registry import (
        P7_FAMILY_DECLARATIONS,
        p7_workflow_step_contracts,
    )

    contracts = p7_workflow_step_contracts()
    for declaration in P7_FAMILY_DECLARATIONS:
        for operation_id in declaration.operation_ids:
            assert contracts[operation_id].output_schema_ref == declaration.result_contract


def test_registry_operation_cannot_be_constructed_without_all_adapter_hooks() -> None:
    """A missing family adapter must fail at construction, not at first use."""

    from workbench.agent.p7_pack_registry import P7PackOperation

    with pytest.raises(TypeError, match="extract_columns"):
        P7PackOperation(
            operation_id="test.p7",
            pack_family="test",
            input_mode="typed",
            validate_request=lambda value: value,
            execute=lambda value, request: value,
            validate_result=lambda value: None,
        )


def test_p7_is_registered_in_every_agent_consumer_and_reaches_multi_step() -> None:
    """Registration, vocabulary, operation lookup, and reachability share one set."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.p7_pack_registry import p7_pack_registry
    from workbench.agent.workflow_contracts import workflow_step_vocabulary

    p7_ids = set(p7_pack_registry.operation_ids())
    multi_step = OperationRegistry().require("operation.multi_step")
    operation_enum = set(
        multi_step.editable_schema["properties"]["steps"]["items"]["properties"]["operation_id"]["enum"]
    )
    assert p7_ids <= operation_enum
    assert p7_ids <= set(workflow_step_vocabulary()["step_operations"])
    inventory = {item.capability_id: item for item in capability_inventory()}
    for operation_id in p7_ids:
        definition = OperationRegistry().require(operation_id)
        capability = inventory[operation_id]
        assert definition.natural_language_enabled is False
        assert capability.kind == "pack"
        assert capability.proposed_by == ()
        assert capability.composable_as == (operation_id,)
        assert capability.reachability_exempt_reason is None
        assert capability.is_reachable is True


def test_p7_step_contract_publishes_nested_request_shapes_and_frame_semantics() -> None:
    """An Agent must see adapter-owned binding keys before it writes a step."""

    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    vif = WORKFLOW_STEP_SPEC_CONTRACTS["diagnostics.vif"]
    binding_schema = vif.field_schemas["column_bindings"]
    assert binding_schema["required"] == ["design"]
    assert binding_schema["properties"]["design"] == {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 1,
    }
    assert "predictors" not in binding_schema["properties"]

    power = WORKFLOW_STEP_SPEC_CONTRACTS["power_analysis.solve"]
    assert power.consumes_input_frame is False


def test_synthetic_control_step_does_not_publish_unsupported_predictors() -> None:
    """The v1 pre-outcome policy must not invite the Agent to bind donors as predictors."""

    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    synthetic = WORKFLOW_STEP_SPEC_CONTRACTS["synthetic_control.fit"]
    bindings = synthetic.field_schemas["column_bindings"]

    assert bindings["required"] == ["outcomes"]
    assert set(bindings["properties"]) == {"outcomes"}
    assert "predictors" not in bindings["properties"]


def test_power_step_rejects_a_source_commitment_it_cannot_consume() -> None:
    """A source declaration must not be accepted and then ignored by power."""

    from workbench.agent.operations import OperationValidationError
    from workbench.agent.workflow import compile_workflow

    with pytest.raises(OperationValidationError, match="does not read a workflow input frame"):
        compile_workflow(
            workflow_id="power-source-guard",
            target={"run_id": "run", "node_ref": "stage:data", "artifact_id": "artifact"},
            preconditions={"context_fingerprint": "fingerprint"},
            steps=[
                {
                    "step_id": "upstream",
                    "operation_id": "statistical.explore",
                    "spec": {"operation": "summarize", "selected_columns": ["x"]},
                },
                {
                    "step_id": "power",
                    "operation_id": "power_analysis.solve",
                    "depends_on": ["upstream"],
                    "spec": {
                        "input_mode": "typed",
                        "column_bindings": {},
                        "options": {"design": "independent_t", "solve_for": "power"},
                        "source": {"from_step": "upstream", "output": "produced_dataset"},
                    },
                },
            ],
        )


def test_p7_request_rejects_unknown_options_instead_of_dropping_them() -> None:
    """An option absent from the declaration must never be silently ignored."""

    from workbench.agent.p7_pack_registry import P7PackRegistryError, p7_pack_registry

    operation = p7_pack_registry.get("missingness.profile")
    with pytest.raises(P7PackRegistryError, match="unknown field\\(s\\): typo_policy"):
        operation.validate(
            {
                "operation_id": "missingness.profile",
                "input_mode": "frame",
                "column_bindings": {},
                "options": {"typo_policy": "ignore"},
            }
        )


def test_matching_missing_policy_is_declared_before_runtime_execution() -> None:
    """Matching's single supported missing-data policy reaches the Agent contract."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get("matching.balance")
    assert operation.request_schema.option_enums["missing_policy"] == ("reject",)


def test_matching_request_rejects_unsupported_missing_policy_before_runtime() -> None:
    """A matching step must reject unsupported missing-data semantics at admission."""

    from workbench.agent.p7_pack_registry import P7PackRegistryError, p7_pack_registry

    operation = p7_pack_registry.get("matching.balance")
    with pytest.raises(P7PackRegistryError, match="must be one of: reject"):
        operation.validate(
            {
                "operation_id": "matching.balance",
                "input_mode": "frame",
                "column_bindings": {
                    "treatment": "treated",
                    "id": "id",
                    "covariates": ["x", "z"],
                },
                "options": {
                    "balance_threshold": 0.1,
                    "missing_policy": "complete_case",
                },
            }
        )


def test_meta_analysis_required_semantics_are_published_to_the_agent() -> None:
    """Meta-analysis scale and pooling method are declaration-owned choices."""

    from workbench.contracts.model.meta_analysis import (
        META_ANALYSIS_COMBINE_METHODS,
        META_ANALYSIS_EFFECT_MEASURES,
    )
    from workbench.agent.p7_pack_registry import p7_pack_registry

    combine = p7_pack_registry.get("meta.combine").request_schema
    effect_size = p7_pack_registry.get("meta.effect_size").request_schema
    assert {"effect_measure", "method"} <= set(combine.required_options)
    assert "effect_measure" in effect_size.required_options
    assert combine.option_enums["effect_measure"] == tuple(
        sorted(META_ANALYSIS_EFFECT_MEASURES)
    )
    assert combine.option_enums["method"] == tuple(sorted(META_ANALYSIS_COMBINE_METHODS))


def test_meta_combine_rejects_missing_effect_measure_before_runtime() -> None:
    """A meta-analysis step must not reach the kernel without its scale."""

    from workbench.agent.p7_pack_registry import P7PackRegistryError, p7_pack_registry

    operation = p7_pack_registry.get("meta.combine")
    with pytest.raises(P7PackRegistryError, match="missing: effect_measure"):
        operation.validate(
            {
                "operation_id": "meta.combine",
                "input_mode": "typed",
                "column_bindings": {
                    "study_id": "study",
                    "effect": "effect",
                    "variance": "variance",
                },
                "options": {"method": "fixed_effect"},
            }
        )


def test_diagnostics_schema_does_not_advertise_an_unused_time_binding() -> None:
    """A binding that the adapter never reads must not be accepted or published."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    for operation_id in (
        "diagnostics.breusch_pagan",
        "diagnostics.white",
        "diagnostics.breusch_godfrey",
    ):
        schema = p7_pack_registry.get(operation_id).request_schema
        assert "time" not in schema.binding_shapes
        assert "time" not in schema.field_schemas()["column_bindings"]["properties"]


def test_p7_request_rejects_agent_code_and_missing_bindings() -> None:
    """Typed adapters reject unsafe or ambiguous input before engine execution."""

    from workbench.agent.p7_pack_adapters import P7PackAdapterError
    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get("categorical.cramers_v")
    with pytest.raises(P7PackAdapterError, match="forbidden field"):
        operation.validate(
            {
                "operation_id": "categorical.cramers_v",
                "input_mode": "typed",
                "column_bindings": {"row": "row", "column": "column"},
                "options": {"python": "raise SystemExit"},
            }
        )
    with pytest.raises(P7PackAdapterError, match="missing"):
        operation.validate(
            {
                "operation_id": "categorical.cramers_v",
                "input_mode": "typed",
                "column_bindings": {"row": "row"},
                "options": {},
            }
        )
    with pytest.raises(P7PackAdapterError, match="forbidden field"):
        operation.validate(
            {
                "operation_id": "categorical.cramers_v",
                "input_mode": "typed",
                "column_bindings": {"row": "row", "column": "column"},
                "options": {"policy": {"callback": "execute"}},
            }
        )
