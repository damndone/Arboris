"""Operation definitions: the declaration dataclass, rerun and workflow-step classification, and the registry's errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationRecordTransitionError(RuntimeError):
    """Raised when an operation record attempts an invalid state transition."""


class UnknownOperationError(RuntimeError):
    """Raised when an agent proposes an operation that is not registered."""


OperationValidator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]


@dataclass(frozen=True)
class OperationDefinition:
    operation_id: str
    operation_version: str = "v1"
    effect_level: str = "mutation"
    scope_requirements: tuple[str, ...] = ()
    scope: str = ""
    risk_level: str = "mutating"
    confirmation_policy: str = "required"
    proposal_schema: dict[str, Any] = field(default_factory=dict)
    editable_schema: dict[str, Any] = field(default_factory=dict)
    # Who answers `inspect_operation_contract` for this operation. "lineage"
    # means the node's own pack publishes the editable shape; "operation_
    # registry" means this definition is the contract, because the operation
    # does not act on a single node's editable surface. An operation an agent
    # may propose must be able to state its own contract, so this is declared
    # rather than inferred from scope_requirements.
    contract_owner: str = "lineage"
    # Optional extra vocabulary published alongside the contract: closed value
    # sets, field meanings, composition rules. A schema says `spec: object`;
    # this is what says what may go inside it.
    vocabulary_builder: Callable[[], dict[str, Any]] | None = None
    executor_key: str = ""
    reconciler_key: str = ""
    diff_builder_key: str = ""
    verification_builder_key: str = ""
    ui_description: str = ""
    example_prompts: tuple[str, ...] = ()
    natural_language_enabled: bool = False
    validator: OperationValidator | None = None

    @property
    def risk_authorization_policy(self) -> str:
        """Return the backend policy implied by the registry risk level."""

        return "explicit_single_use" if self.risk_level == "high" else "none"

    @property
    def requires_risk_authorization(self) -> bool:
        return self.risk_level == "high"

    def validate(
        self,
        *,
        target: dict[str, Any],
        preconditions: dict[str, Any],
        changes: dict[str, Any],
    ) -> None:
        if self.validator is not None:
            self.validator(target, preconditions, changes)


WORKFLOW_STEP_DISPATCHER_PREFIX = "workbench.agent.workflow_runtime."


# Operations executed as a rerun of the target run: they share the rerun
# executor, reconciliation and child-run binding.
RERUN_OPERATIONS = frozenset({"model.rerun", "metadata.edit"})


def is_rerun_operation(operation_id: object) -> bool:
    return operation_id in RERUN_OPERATIONS


def is_workflow_step_only(definition: OperationDefinition) -> bool:
    """A step identity that only a composed workflow can execute.

    Such definitions carry a workflow-step dispatcher and require a workflow
    and step id; proposed on their own they failed validation or, after the
    user confirmed, execution. The Agent reaches them through
    operation.multi_step (a plan may have one step), which is the one path.
    """

    return str(definition.executor_key).startswith(WORKFLOW_STEP_DISPATCHER_PREFIX)
