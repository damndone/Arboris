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
    {"model_family", "data_operation", "statistical_test", "pack"}
)


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


__all__ = ["CAPABILITY_KINDS", "CapabilityContract"]
