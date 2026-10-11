"""Compatibility facade for modular, bounded Workbench context tools."""

from .family_evidence import bounded_model_family_evidence as _bounded_model_family_evidence

from .context_tools_support.requests import (
    InspectArtifactPreviewRequest,
    InspectCompletedOperationsRequest,
    InspectDataSchemaRequest,
    InspectDiagnosticsRequest,
    InspectNodeContextRequest,
    InspectNotebookWorkflowResultsRequest,
    InspectOperationArtifactRequest,
    InspectOperationContractRequest,
    InspectProjectCoefficientTransformsRequest,
    InspectProjectDatasetSchemaRequest,
    InspectProjectLinearInteractionEffectsRequest,
    InspectProjectModelCoefficientsRequest,
    InspectProjectModelFigureEvidenceRequest,
    InspectProjectNotebookWorkflowResultsRequest,
    InspectProjectNumericSummaryRequest,
    InspectProjectStatisticalEvidenceRequest,
    InspectRepeatedMeasuresRecipeRequest,
    InspectResultSummaryRequest,
    InspectTimeSeriesSummaryRequest,
    ListProjectDatasetsRequest,
    OperationContractUnavailableError,
    WorkbenchContextProvider,
    _FOREST_NODE_KEY,
    _MAX_PUBLIC_MODEL_PREDICTORS,
    _PROJECT_RUN_ID_RE,
    _run_local_node_id,
)
from .context_tools_support.workflow_results import (
    _committed_notebook_workflow_receipt,
    _notebook_option_revision_key,
    _notebook_source_runs_by_revision,
)
from .context_tools_support.coefficients import (
    _MAX_AVAILABLE_TERMS,
    _MAX_METADATA_COLUMNS,
    _MAX_VALUE_LABELS_PER_COLUMN,
    _bounded_declared_metadata,
    _kernel_fixed_effects,
    _lmm_published_results,
    _public_probability,
    _public_requested_model_coefficients,
    _run_declared_labels,
    _run_term_labeler,
)
from .context_tools_support.summaries import (
    RECIPE_RESULT_PROJECTIONS,
    RecipeResultProjection,
    _BY_GROUP_TEST_FIELDS,
    _INFERENCE_FIELDS,
    _MAX_BY_GROUP_TEST_ROWS,
    _MAX_GROUPS_PROJECTED,
    _PUBLIC_RESULT_DENIED_KEYS,
    _PublicResultBudget,
    _analysis_contract_from_run_inputs,
    _bounded_artifact_manifest,
    _bounded_average_marginal_effects,
    _bounded_by_group,
    _bounded_checks,
    _bounded_coefficient_row,
    _bounded_completed_operation,
    _bounded_diagnostics,
    _bounded_difference_tests,
    _bounded_family_diagnostic,
    _bounded_inference,
    _bounded_multiple_imputation,
    _bounded_node,
    _bounded_persisted_model_facts,
    _bounded_public_result_value,
    _bounded_regression_table,
    _bounded_result_summary,
    _bounded_statistics_evidence,
    _bounded_survey_design,
    _bounded_test_by_group,
    _executed_covariance,
    _fit_statistics,
    _lift_group_variables,
    _node_public_result_evidence,
    _operation_artifact_ids,
    _pooled_coefficient_fields,
    _public_operation_artifact_result,
    _public_test_by_group,
    _read_diagnostic_summary,
    _read_manifest,
    _resolve_verified_registered_artifact,
)
from .context_tools_support.figures import (
    _align_figure_context_rows,
    _bounded_model_figure_numeric_source,
    _bounded_residuals_vs_predictor_source,
    _bounded_run_figure_evidence,
    _figure_artifact_suffix,
    _finite_numeric_values,
    _numeric_mean,
    _numeric_quantile,
    _numeric_standard_deviation,
    _read_cleaned_dataset_for_figure_context,
)
from .context_tools_support.analysis_loop import (
    AnalysisLoopContextError,
    AnalysisLoopPacketPayloadError,
    _ANALYSIS_LOOP_SCOPES,
    _ANALYSIS_LOOP_SOURCE_FIELDS,
    _analysis_loop_packet_payload,
    _safe_analysis_loop_source_context,
    inspect_analysis_loop_context,
    parse_analysis_loop_packet_payloads,
    read_prediction_research_evidence,
)
from .context_tools_support.node_tools import NodeToolsMixin
from .context_tools_support.registration import RegistrationMixin
from .context_tools_support.datasets import DatasetsMixin
from .context_tools_support.model_tools import ModelToolsMixin
from .context_tools_support.workflow_results import WorkflowResultsMixin


class NodeOperationContextProvider(
    NodeToolsMixin,
    RegistrationMixin,
    DatasetsMixin,
    ModelToolsMixin,
    WorkflowResultsMixin,
):
    """Read node-operation context from one explicitly scoped project."""
