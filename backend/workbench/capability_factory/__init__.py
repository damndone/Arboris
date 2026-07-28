"""CF1 capability contracts and resolution primitives.

This package is a control-plane surface only.  It describes and resolves
registered capabilities; it does not fetch dependencies, execute code, or
mount an Agent/Notebook route.
"""

from .contracts import (
    CAPABILITY_FACTORY_SCHEMA_VERSION,
    CONSUMER_SLOTS,
    TRUST_ORDER,
    CandidateSet,
    CapabilityRequirementRevision,
    ContractError,
    ImplementationCandidate,
    ImplementationRevision,
    ResolutionBinding,
    ResolutionPolicySnapshot,
    SelectionDecision,
    SemanticProfile,
)

__all__ = [
    "CAPABILITY_FACTORY_SCHEMA_VERSION",
    "CONSUMER_SLOTS",
    "TRUST_ORDER",
    "CandidateSet",
    "CapabilityRequirementRevision",
    "ContractError",
    "ImplementationCandidate",
    "ImplementationRevision",
    "ResolutionBinding",
    "ResolutionPolicySnapshot",
    "SelectionDecision",
    "SemanticProfile",
]
