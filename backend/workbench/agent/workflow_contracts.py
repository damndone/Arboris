"""Compatibility imports for server-owned composed workflow contracts.

Behavior lives in ``workflow_contract_parts``. The registry alone owns live
operation declarations and republishes its immutable compatibility views here.
"""
from __future__ import annotations

from .workflow_contract_parts import registry as _registry
from .workflow_contract_parts.contracts import (
    GENESIS_RUN_LEVEL_FIELDS, NOTEBOOK_GENESIS_MODEL_PARAMS,
    SUPPORTED_STEP_OUTPUTS, WORKFLOW_OPERATION_ID, WORKFLOW_OPERATION_VERSION,
    WORKFLOW_TEMPLATE, _REPORTED_PERCENTILES, _STEP_ID_PATTERN,
)
from ..contracts.common.errors import OperationValidationError
from .workflow_contract_parts.contracts import (
    StepSpecContract,
    pack_step_contract,
)
from .workflow_contract_parts.declarations import (
    _p5_exposure_note,
    statistical_workflow_step_contracts,
    prediction_workflow_step_contracts,
    data_preparation_workflow_step_contracts,
    recipe_workflow_step_contracts,
    _string_list_field_schema,
    _growth_policy_field_schema,
    _data_management_step_contracts,
)
from .workflow_contract_parts.registry import (
    _validate_workflow_step_entry,
    WorkflowStepContractRegistry,
    _refresh_workflow_contract_views,
    selector_workflow_step_contracts,
    _p5_workflow_step_contracts,
    register_workflow_step,
    workflow_step_operations,
    workflow_step_vocabulary,
    workflow_dispatcher_key,
)
from .workflow_contract_parts.validation import (
    genesis_run_params,
    notebook_workflow_capability_ids,
    _validate_multiple_imputations,
    _validate_by_group,
    validate_model_genesis_spec,
    _validate_step_spec,
    _validate_positive_integer_field,
    _validate_nonnegative_integer_field,
    _validate_fraction_field,
    _recipe_option_mapping,
    _validate_recipe_workflow_spec,
    _validate_auto_workflow_spec,
    _schema_value_matches,
    _schema_mismatch,
    _validate_data_management_step,
    _validate_declared_field_types,
)
from .workflow_contract_parts.graph import (
    _spec_columns,
    _data_output_columns,
    validate_workflow_steps,
    _step_ancestors,
    _reject_unreadable_data_sources,
    _validate_source_commitment,
    _topological_order,
)
from .workflow_contract_parts.proposal import (
    workflow_authorization,
    workflow_proposal_schema,
    validate_workflow_operation,
)
from .workflow_contract_parts.registry import WORKFLOW_STEP_SPEC_CONTRACTS


def _refresh_compatibility_views() -> None:
    """Bind each legacy view to the exact object published by its owner."""

    global WORKFLOW_STEP_OPERATIONS, _ALLOWED_SPEC_FIELDS
    global STEP_CONSUMES_INPUT_FRAME, STEP_PRODUCES_DATASET, STEP_REPLAYABLE_BY_RECIPE
    WORKFLOW_STEP_OPERATIONS = _registry.WORKFLOW_STEP_OPERATIONS
    _ALLOWED_SPEC_FIELDS = _registry._ALLOWED_SPEC_FIELDS
    STEP_CONSUMES_INPUT_FRAME = _registry.STEP_CONSUMES_INPUT_FRAME
    STEP_PRODUCES_DATASET = _registry.STEP_PRODUCES_DATASET
    STEP_REPLAYABLE_BY_RECIPE = _registry.STEP_REPLAYABLE_BY_RECIPE


_registry._set_compatibility_view_refresher(_refresh_compatibility_views)

__all__ = [
    "STEP_CONSUMES_INPUT_FRAME",
    "STEP_PRODUCES_DATASET",
    "STEP_REPLAYABLE_BY_RECIPE",
    "SUPPORTED_STEP_OUTPUTS",
    "WORKFLOW_OPERATION_ID",
    "WORKFLOW_OPERATION_VERSION",
    "WORKFLOW_STEP_OPERATIONS",
    "WORKFLOW_STEP_SPEC_CONTRACTS",
    "WORKFLOW_TEMPLATE",
    "StepSpecContract",
    "WorkflowStepContractRegistry",
    "data_preparation_workflow_step_contracts",
    "pack_step_contract",
    "prediction_workflow_step_contracts",
    "recipe_workflow_step_contracts",
    "register_workflow_step",
    "selector_workflow_step_contracts",
    "statistical_workflow_step_contracts",
    "validate_workflow_operation",
    "validate_workflow_steps",
    "workflow_authorization",
    "workflow_proposal_schema",
    "workflow_step_operations",
    "workflow_step_vocabulary",
    "workflow_dispatcher_key",
]
