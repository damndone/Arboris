"""Own the live workflow registry and its derived publication views."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ...contracts.common.errors import OperationValidationError
from .contracts import (
    StepSpecContract, SUPPORTED_STEP_OUTPUTS, _REPORTED_PERCENTILES, _STEP_ID_PATTERN,
)
from .declarations import (
    base_workflow_step_contracts, _data_management_step_contracts, _p5_exposure_note,
    statistical_workflow_step_contracts, prediction_workflow_step_contracts,
    data_preparation_workflow_step_contracts, recipe_workflow_step_contracts,
)

_compatibility_view_refresher: Callable[[], None] | None = None

def _validate_workflow_step_entry(
    operation_id: str,
    contract: StepSpecContract,
) -> None:
    if type(operation_id) is not str or not operation_id.strip():
        raise ValueError("workflow step operation_id must be a non-empty string")
    if not isinstance(contract, StepSpecContract):
        raise TypeError("workflow step registry values must be StepSpecContract instances")


class WorkflowStepContractRegistry(dict[str, StepSpecContract]):
    """Live workflow declarations with synchronized derived projections."""

    def __init__(
        self,
        initial: Mapping[str, StepSpecContract] | None = None,
    ) -> None:
        values = dict(initial or {})
        for operation_id, contract in values.items():
            _validate_workflow_step_entry(operation_id, contract)
        super().__init__(values)

    def __setitem__(self, operation_id: str, contract: StepSpecContract) -> None:
        _validate_workflow_step_entry(operation_id, contract)
        super().__setitem__(operation_id, contract)
        _refresh_workflow_contract_views()

    def __delitem__(self, operation_id: str) -> None:
        super().__delitem__(operation_id)
        _refresh_workflow_contract_views()

    def update(
        self,
        *args: Mapping[str, StepSpecContract],
        **kwargs: StepSpecContract,
    ) -> None:
        values = dict(*args, **kwargs)
        for operation_id, contract in values.items():
            _validate_workflow_step_entry(operation_id, contract)
        super().update(values)
        _refresh_workflow_contract_views()


def _refresh_workflow_contract_views() -> None:
    """Refresh every compatibility projection from the live declaration map."""

    global _ALLOWED_SPEC_FIELDS
    global STEP_CONSUMES_INPUT_FRAME
    global STEP_PRODUCES_DATASET
    global STEP_REPLAYABLE_BY_RECIPE
    global WORKFLOW_STEP_OPERATIONS

    WORKFLOW_STEP_OPERATIONS = tuple(WORKFLOW_STEP_SPEC_CONTRACTS)
    _ALLOWED_SPEC_FIELDS = {
        operation_id: contract.allowed
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
    }
    STEP_PRODUCES_DATASET = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.produces_dataset
    )
    STEP_CONSUMES_INPUT_FRAME = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.consumes_input_frame
    )
    STEP_REPLAYABLE_BY_RECIPE = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.replayable_by_recipe
    )
    if _compatibility_view_refresher is not None:
        _compatibility_view_refresher()


def selector_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive selector steps from the live model selector registry."""

    from ..capability_contract import MODEL_TYPE_SELECTORS

    genesis = WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"]
    fields = {
        name: description
        for name, description in genesis.fields.items()
        if name != "model_family"
    }
    field_types = {
        name: type_name
        for name, type_name in genesis.field_types.items()
        if name != "model_family"
    }
    return {
        f"model.{selector}": StepSpecContract(
            summary=(
                f"Resolve the live {selector} model selector against the declared "
                "branches and target structure."
            ),
            fields=fields,
            required=("branches",),
            field_types=field_types,
            semantic_validator_key="model.auto",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="model.auto",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.auto/v1",
            dispatcher_key="workbench.agent.workflow_runtime.model_auto",
            scope="automatic model selector",
            risk_level="high",
            reconciler_key="model.auto",
            diff_builder_key="model.auto.diff.v1",
            verification_builder_key="model.auto.verification.v1",
            ui_description=f"Resolve and run the live {selector} model selector.",
            capability_kind="selector",
            top_level_exposure_note=_p5_exposure_note(f"model.{selector}"),
        )
        for selector in sorted(MODEL_TYPE_SELECTORS)
    }


def _p5_workflow_step_contracts() -> dict[str, StepSpecContract]:
    contracts: dict[str, StepSpecContract] = {}
    for derived in (
        statistical_workflow_step_contracts(),
        prediction_workflow_step_contracts(),
        data_preparation_workflow_step_contracts(),
        recipe_workflow_step_contracts(),
        selector_workflow_step_contracts(),
    ):
        overlap = set(contracts) & set(derived)
        if overlap:
            raise ValueError(
                "P5 workflow contract identity collision: "
                + ", ".join(sorted(overlap))
            )
        contracts.update(derived)
    return contracts


def register_workflow_step(operation_id: str, contract: StepSpecContract) -> None:
    """Register one workflow step and refresh all declaration projections."""

    WORKFLOW_STEP_SPEC_CONTRACTS[operation_id] = contract


def workflow_step_operations() -> tuple[str, ...]:
    """Return the current operation IDs from the live step registry."""

    return tuple(WORKFLOW_STEP_SPEC_CONTRACTS)


def workflow_step_vocabulary() -> dict[str, Any]:
    """The composable-step vocabulary, for publication to a planning agent.

    Read before a plan is written, this is what makes the difference between
    composing against real field names and guessing at them.
    """

    return {
        "step_operations": {
            operation_id: contract.to_payload()
            for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        },
        "reported_percentiles": list(_REPORTED_PERCENTILES),
        "step_id_pattern": _STEP_ID_PATTERN.pattern,
        # The composition seam. Every value below is read from the same
        # declarations the validator refuses against, so an operation that
        # gains `produces_dataset` becomes nameable by a plan in the same edit
        # that registers it. A hand-written list here would be the second place
        # to remember, and the one that goes stale.
        "source": {
            "purpose": (
                "By default every step reads the workflow's own target dataset. "
                "A step that must instead read the dataset an earlier step "
                "produced declares `source` inside its `spec`."
            ),
            "shape": {
                "from_step": (
                    "The step_id of the earlier step in this same plan whose "
                    "output this step reads."
                ),
                "output": (
                    "Which of that step's outputs to read, from the supported "
                    "output values listed with this entry."
                ),
            },
            "outputs": sorted(SUPPORTED_STEP_OUTPUTS),
            "produced_by": sorted(STEP_PRODUCES_DATASET),
            "declarable_by": sorted(STEP_CONSUMES_INPUT_FRAME),
            "semantics": (
                "from_step may only name a step whose operation is one of the "
                "dataset producers listed here, and only a step whose operation "
                "is listed as able to declare a source may carry one. Declaring "
                "a source is also "
                "declaring a dependency: from_step is folded into depends_on, so "
                "the step runs after its producer and is blocked, never run "
                "against the original table, if that producer fails. A step has "
                "exactly one data source -- `source` is a single object, never a "
                "list -- and a step that declares none reads the workflow target. "
                "To work from two produced datasets, produce the combination in "
                "one step and read that step."
            ),
        },
        "ordering": (
            "Steps form a DAG via `depends_on` (step_ids) and run in topological "
            "order. A step whose dependency failed is blocked, never skipped."
        ),
    }


def workflow_dispatcher_key(operation_id: str) -> str:
    """Return the trusted runtime key published by one step contract."""

    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
    if contract is None or not contract.dispatcher_key:
        raise OperationValidationError(
            f"workflow step operation has no trusted dispatcher: {operation_id!r}"
        )
    return contract.dispatcher_key


def _set_compatibility_view_refresher(refresher: Callable[[], None]) -> None:
    """Keep the legacy facade's bound views current without importing it."""

    global _compatibility_view_refresher
    _compatibility_view_refresher = refresher
    refresher()


from ..p7_pack_registry import p7_workflow_step_contracts  # noqa: E402
from ..workflow_capability_registry import workflow_capability_step_contracts  # noqa: E402
from ..postestimation_steps import postestimation_step_contracts  # noqa: E402

WORKFLOW_STEP_SPEC_CONTRACTS = WorkflowStepContractRegistry(base_workflow_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(_p5_workflow_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(p7_workflow_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(workflow_capability_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(postestimation_step_contracts())
_refresh_workflow_contract_views()
for _data_operation_id, _data_operation_contract in _data_management_step_contracts().items():
    WORKFLOW_STEP_SPEC_CONTRACTS[_data_operation_id] = _data_operation_contract
