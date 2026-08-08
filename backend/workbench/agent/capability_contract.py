"""One capability's identity and the paths by which it can be asked for.

A capability is not an operation. `model.genesis` is a single operation that
carries twenty-three model families, so a guard written over operations stays
green when the twenty-fourth family is unreachable -- which is exactly how the
previous version's reachability check missed the data-operation family. This
contract is the layer that makes "every capability" enumerable, and reach a
property each capability states about itself rather than one a human re-checks.
"""

from __future__ import annotations

from dataclasses import dataclass


CAPABILITY_KINDS = frozenset(
    # "selector" is not an estimator or a transform: it is a user-selectable
    # entry that resolves to one of the others. `auto` is one, and it needs a
    # kind of its own -- calling it a model family would have the inventory
    # assert an estimator exists that does not, and leaving it out would hide a
    # capability the product visibly offers.
    {"model_family", "selector", "data_operation", "statistical_test", "pack"}
)

#: model_types keys that resolve to a family rather than being one. Declared
#: here so a future selector is a one-line addition instead of a family the
#: inventory misdescribes.
MODEL_TYPE_SELECTORS = frozenset({"auto"})


@dataclass(frozen=True)
class CapabilityContract:
    capability_id: str
    kind: str
    summary: str
    #: operation_ids that can propose this capability at the top level.
    #: A tuple rather than a flag: a guard has to be able to say *through what*
    #: a capability is reachable, and a family wired to an operation that does
    #: not exist is invisible to a boolean.
    proposed_by: tuple[str, ...] = ()
    #: workflow step operation_ids that can compose this capability in a plan.
    composable_as: tuple[str, ...] = ()
    #: Deliberately closed capabilities say so here. Absence from the inventory
    #: and presence with a stated reason are different claims, and only the
    #: second one survives someone asking "was this an oversight?".
    reachability_exempt_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string")
        if self.kind not in CAPABILITY_KINDS:
            raise ValueError(
                f"capability {self.capability_id} kind must be one of: "
                + ", ".join(sorted(CAPABILITY_KINDS))
            )
        if not self.summary.strip():
            raise ValueError(
                f"capability {self.capability_id} needs a summary: it is what a "
                "reader and a model both see first"
            )

    @property
    def is_reachable(self) -> bool:
        return bool(self.proposed_by or self.composable_as)


def _model_capabilities() -> list[CapabilityContract]:
    """Every model type, from the two registries that between them define one.

    Neither registry alone is the answer, and the gap between them is the point:

    * `build_capabilities()["model_types"]` is what a user can pick and run, and
      is the only place a family's human description lives.
    * `MODEL_FAMILY_CONTRACTS` is what `model_family_contract()` admits into a
      workflow step, and therefore what `operation.multi_step` can compose.

    Taking the union means a family registered in either one shows up without
    anybody editing this function; splitting the two paths across `proposed_by`
    and `composable_as` means a family present in only one is reported as the
    partial-reach state it really is instead of being rounded to reachable or
    dropped.
    """

    # Imported here: workbench.engine.capabilities pulls in the pack loader and
    # the whole stage pipeline, and importing that at module scope makes this
    # module a participant in the engine/orchestrator import cycle.
    from workbench.engine.capabilities import build_capabilities

    from .workflow_contracts import MODEL_FAMILY_CONTRACTS

    selectable = {
        str(entry["key"]): entry for entry in build_capabilities()["model_types"]
    }

    capabilities: list[CapabilityContract] = []
    for key in sorted({*selectable, *MODEL_FAMILY_CONTRACTS}):
        entry = selectable.get(key)
        admitted = key in MODEL_FAMILY_CONTRACTS
        if entry is not None:
            summary = str(entry.get("description") or "")
        else:
            # A family the workflow admits but the selector never offers. It has
            # no description anywhere, so say what is actually known about it
            # and that the description is missing -- echoing the id back would
            # satisfy the summary check while telling a planner nothing.
            contract = MODEL_FAMILY_CONTRACTS[key]
            summary = (
                "Workflow-executable model family returning a "
                f"{contract.result_shape} result. No selector description is "
                "registered for it."
            )
        capabilities.append(
            CapabilityContract(
                capability_id=f"model.{key}",
                kind="selector" if key in MODEL_TYPE_SELECTORS else "model_family",
                summary=summary,
                # Top-level model.genesis does not restrict model_type to the
                # admission table, so anything the selector offers can be
                # proposed directly.
                proposed_by=("model.genesis",) if entry is not None else (),
                # ...but a model.genesis *step* inside a plan calls
                # model_family_contract(), which refuses anything not admitted.
                composable_as=("model.genesis",) if admitted else (),
            )
        )
    return capabilities


def _operation_capabilities() -> list[CapabilityContract]:
    """Every registered operation, once, carrying the paths it can be asked on.

    An operation that is also a workflow step is one capability with two paths,
    not two capabilities: counting it twice would inflate the denominator of any
    "how much of the product is reachable" claim.
    """

    from .operations import OperationRegistry
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    registry = OperationRegistry()
    summaries: dict[str, str] = {}
    for entry in registry.capabilities():
        # capabilities() is keyed by (id, version); the capability is the id, so
        # the first registered version supplies the description.
        summaries.setdefault(str(entry["operation_id"]), str(entry["ui_description"]))

    return [
        CapabilityContract(
            capability_id=operation_id,
            kind="data_operation",
            summary=summaries[operation_id],
            proposed_by=(operation_id,),
            composable_as=(
                (operation_id,) if operation_id in WORKFLOW_STEP_SPEC_CONTRACTS else ()
            ),
        )
        for operation_id in sorted(summaries)
    ]


def _statistical_test_capabilities() -> list[CapabilityContract]:
    """Every statistical test family, with the reach it actually has: none.

    These run as a pipeline stage inside every model run and are selected by
    column types, so no operation can name one. They are listed as unreachable
    rather than omitted, because "cannot be asked for by name" is a finding the
    inventory exists to make visible, not a reason to leave them out.
    """

    from ..statistical_tests import TEST_FAMILIES

    return [
        CapabilityContract(
            capability_id=f"test.{family}",
            kind="statistical_test",
            summary=contract.summary,
        )
        for family, contract in sorted(TEST_FAMILIES.items())
    ]


def capability_inventory() -> tuple[CapabilityContract, ...]:
    """The enumerable set of things this product can be asked to do.

    Derived from the live registries on every call. A hand-kept copy would be a
    second place to remember, and the one that gets forgotten -- which is how
    the previous version came to claim full natural-language reach while an
    entire operation family was unreachable.
    """

    return (
        *_model_capabilities(),
        *_operation_capabilities(),
        *_statistical_test_capabilities(),
    )


__all__ = [
    "CAPABILITY_KINDS",
    "MODEL_TYPE_SELECTORS",
    "CapabilityContract",
    "capability_inventory",
]
