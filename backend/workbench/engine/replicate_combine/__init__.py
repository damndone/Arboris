"""Public surface for the bounded replicate-and-combine foundation."""

from .combiners import CombinerDescriptor, dispatch_combiner
from .errors import ReplicateCombineError, ReplicateExecutionError
from .runner import ReplicateRegistry, execute, execute_and_combine
from .survey_adapter import (
    MAX_SURVEY_REPLICATE_CELLS,
    MAX_SURVEY_TERMS,
    SurveyCovarianceCombiner,
    SurveyEstimatorAdapter,
    SurveyPackAdapterError,
    SurveyReplicateStrategy,
    run_survey_replicate_covariance,
)
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
    "MAX_SURVEY_REPLICATE_CELLS",
    "MAX_SURVEY_TERMS",
    "SurveyCovarianceCombiner",
    "SurveyEstimatorAdapter",
    "SurveyPackAdapterError",
    "SurveyReplicateStrategy",
    "compute_provenance_commitment",
    "dispatch_combiner",
    "execute",
    "execute_and_combine",
    "run_survey_replicate_covariance",
]
