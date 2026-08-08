"""Public surface for the bounded replicate-and-combine foundation."""

from .combiners import CombinerDescriptor, dispatch_combiner
from .errors import ReplicateCombineError, ReplicateExecutionError
from .runner import ReplicateRegistry, execute, execute_and_combine
from .types import (
    ReplicateAdapter,
    ReplicateBatch,
    ReplicateCombiner,
    ReplicateCombinedResult,
    ReplicateEvidence,
    ReplicateStrategy,
    compute_provenance_commitment,
)

__all__ = [
    "CombinerDescriptor",
    "ReplicateAdapter",
    "ReplicateBatch",
    "ReplicateCombiner",
    "ReplicateCombinedResult",
    "ReplicateCombineError",
    "ReplicateEvidence",
    "ReplicateExecutionError",
    "ReplicateRegistry",
    "ReplicateStrategy",
    "compute_provenance_commitment",
    "dispatch_combiner",
    "execute",
    "execute_and_combine",
]
