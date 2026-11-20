"""Summaries: bounded read-only context projection.

The code lives in the summaries_* modules; this module keeps the import path.
"""

from __future__ import annotations

from .summaries_public_values import (  # noqa: F401
    _MAX_GROUPS_PROJECTED,
    _PUBLIC_RESULT_DENIED_KEYS,
    _PublicResultBudget,
    _bounded_public_result_value,
    _bounded_test_by_group,
)
from .summaries_public import (  # noqa: F401
    _BY_GROUP_TEST_FIELDS,
    _MAX_BY_GROUP_TEST_ROWS,
    _lift_group_variables,
    _node_public_result_evidence,
    _public_iv_ar_result,
    _public_operation_artifact_result,
    _public_test_by_group,
)
from .summaries_facts import (  # noqa: F401
    _INFERENCE_FIELDS,
    _analysis_contract_from_run_inputs,
    _bounded_by_group,
    _bounded_difference_tests,
    _bounded_family_diagnostic,
    _bounded_inference,
    _bounded_multiple_imputation,
    _bounded_persisted_model_facts,
    _executed_covariance,
    _fit_statistics,
    _model_evidence_ref,
    _pooled_coefficient_fields,
    _read_diagnostic_summary,
    _read_manifest,
)
from .summaries_operations import (  # noqa: F401
    _bounded_artifact_manifest,
    _bounded_completed_operation,
    _operation_artifact_ids,
    _operation_artifact_source,
    _operation_model_branches,
)
from .summaries_diagnostics import (  # noqa: F401
    RECIPE_RESULT_PROJECTIONS,
    RecipeResultProjection,
    _bounded_diagnostics,
    _bounded_node,
    _resolve_verified_registered_artifact,
)
from .summaries_results import (  # noqa: F401
    _bounded_average_marginal_effects,
    _bounded_checks,
    _bounded_coefficient_row,
    _bounded_regression_table,
    _bounded_result_summary,
    _bounded_statistics_evidence,
    _bounded_survey_design,
)
