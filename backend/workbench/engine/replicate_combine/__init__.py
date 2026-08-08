"""Public surface for the bounded replicate-and-combine foundation."""

from .combiners import CombinerDescriptor, dispatch_combiner
from .errors import ReplicateCombineError, ReplicateExecutionError
from .runner import ReplicateRegistry, execute
from .types import (
    ReplicateAdapter,
    ReplicateBatch,
    ReplicateEvidence,
    ReplicateStrategy,
    compute_provenance_commitment,
)

__all__ = [
    "CombinerDescriptor",
    "ReplicateAdapter",
    "ReplicateBatch",
    "ReplicateCombineError",
    "ReplicateEvidence",
    "ReplicateExecutionError",
    "ReplicateRegistry",
    "ReplicateStrategy",
    "compute_provenance_commitment",
    "dispatch_combiner",
    "execute",
]
