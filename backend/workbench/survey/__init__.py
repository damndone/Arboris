"""Design-based variance for arbitrary deterministic estimators.

The engine composes three independent objects -- a `SurveyDesign`, an
`EstimatorSpec` and a variance channel -- and derives which combinations are
legal from the capabilities the estimator declares.  There is no family axis:
an estimator this package has never heard of, including one written at runtime,
obtains a design-based variance on exactly the same terms as a built-in one.
"""

from importlib import import_module

_EXPORT_MODULES = {'DesignEffects': 'design',
 'SurveyDesign': 'design',
 'MAX_REPLICATE_FAILURE_RATE': 'engine',
 'DesignEstimate': 'engine',
 'JointTest': 'engine',
 'ReplicateSummary': 'engine',
 'estimate_with_design': 'engine',
 'SurveyCompositionError': 'errors',
 'SurveyEngineError': 'errors',
 'CAPABILITY_CONSUMES_DESIGN': 'estimator',
 'CAPABILITY_DETERMINISTIC_REFIT': 'estimator',
 'CAPABILITY_INFLUENCE_FUNCTION': 'estimator',
 'VARIANCE_METHOD_REQUIREMENTS': 'estimator',
 'EstimatorSpec': 'estimator',
 'missing_capabilities': 'estimator'}

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


def __getattr__(name: str):
    """Keep declaration readers independent of numerical runtime imports."""
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
