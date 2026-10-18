"""Persisted workflow schemas and projection bounds."""

_NUMERIC_DERIVATION_SCHEMA = "workflow-derived-numeric.v1"

# Read back from persisted state on resume; every dataset-producing operation
# publishes the same versioned block.
_PRODUCED_DATASET_SCHEMA = "workflow-produced-dataset.v1"

# Registered evidence accepted by the result projection.
POST_ESTIMATION_ARTIFACT_TYPES = (
    "post_estimation",
    "statistical_test",
    "p7_analysis",
    "workflow_capability_result",
)

# Inline product projections must report overflow rather than hide evidence.
MAX_PROJECTED_POST_ESTIMATION_RESULTS = 20


_PRODUCED_DATASET_FIELDS = ("run_id", "node_ref", "artifact_id", "content_sha256")

