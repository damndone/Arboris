"""Design-based variance for arbitrary deterministic estimators.

The engine composes three independent objects -- a `SurveyDesign`, an
`EstimatorSpec` and a variance channel -- and derives which combinations are
legal from the capabilities the estimator declares.  There is no family axis:
an estimator this package has never heard of, including one written at runtime,
obtains a design-based variance on exactly the same terms as a built-in one.
"""

from .design import DesignEffects, SurveyDesign
from .engine import (
    MAX_REPLICATE_FAILURE_RATE,
    DesignEstimate,
    JointTest,
    ReplicateSummary,
    estimate_with_design,
)
from .errors import SurveyCompositionError, SurveyEngineError
from .estimator import (
    CAPABILITY_CONSUMES_DESIGN,
    CAPABILITY_DETERMINISTIC_REFIT,
    CAPABILITY_INFLUENCE_FUNCTION,
    VARIANCE_METHOD_REQUIREMENTS,
    EstimatorSpec,
    missing_capabilities,
)

__all__ = [
    "CAPABILITY_CONSUMES_DESIGN",
    "CAPABILITY_DETERMINISTIC_REFIT",
    "CAPABILITY_INFLUENCE_FUNCTION",
    "MAX_REPLICATE_FAILURE_RATE",
    "VARIANCE_METHOD_REQUIREMENTS",
    "DesignEffects",
    "DesignEstimate",
    "EstimatorSpec",
    "JointTest",
    "ReplicateSummary",
    "SurveyCompositionError",
    "SurveyDesign",
    "SurveyEngineError",
    "estimate_with_design",
    "missing_capabilities",
]
