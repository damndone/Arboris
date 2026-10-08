"""Runs: submission, list, detail, deletion, artifacts, exports and AI reports."""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from pydantic import ConfigDict
from typing_extensions import TypedDict

from ...engine.packs.arma_garch.transforms import TRANSFORM_IDS
from ...predictive_research.contracts import StructureKind, StructureProvenance
from ...report_quality import ReportQualityStatus
from ...report_store import AiReportRecordRequest
from .common import RunLabels, view_of


class RunSubmitted(TypedDict):
    run_id: str
    status: str


class BatchRunEntry(TypedDict):
    y: str
    run_id: str
    status: str
    model_id: str | None
    model_type: str | None


class BatchRunSubmitted(TypedDict):
    status: str
    runs: list[BatchRunEntry]


class RunSummary(TypedDict):
    run_id: str
    status: str | None
    mode: str | None
    started_at: str | None
    y: str | None
    x: list[str] | None


class RunList(TypedDict):
    runs: list[RunSummary]


class LineageEntry(TypedDict):
    source: str
    artifact_id: str


class IssueRecord(TypedDict):
    """A stored issue. Runs written by earlier versions may carry other fields,
    so the record is open and every field is optional."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    severity: NotRequired[str]
    code: NotRequired[str]
    message: NotRequired[str]
    evidence: NotRequired[dict[str, Any]]
    issue_id: NotRequired[str]
    affected_stage: NotRequired[str]
    variables: NotRequired[list[str]]
    metric: NotRequired[str | None]
    value: NotRequired[float | None]
    threshold: NotRequired[float | None]
    template_key: NotRequired[str | None]
    template_params: NotRequired[dict[str, Any]]
    recommended_action_key: NotRequired[str | None]
    is_user_action_required: NotRequired[bool]


class IssueStream(TypedDict):
    issues: list[IssueRecord]


class CoefficientRecord(TypedDict):
    """One coefficient. Families add their own fields (IRR, odds ratios, df/FMI
    under multiple imputation), so the record is open."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    estimate: NotRequired[float | None]
    std_error: NotRequired[float | None]
    p_value: NotRequired[float | None]
    p_value_display: NotRequired[str | None]
    ci_lower: NotRequired[float | None]
    ci_upper: NotRequired[float | None]
    source_id: NotRequired[str]
    df: NotRequired[float | None]
    fmi: NotRequired[float | None]


class AncillaryParameter(TypedDict):
    name: str
    estimate: float
    std_error: float | None
    conf_low: float | None
    conf_high: float | None
    scale: str


class OverdispersionTest(TypedDict):
    statistic: float
    df: float
    p_value: float
    distribution: str


class ModelWarning(TypedDict):
    code: str
    message: str


class ModelResult(TypedDict):
    """A fitted model as stored in the versioned result envelope. Only the
    identity is common to every family; the rest is family-specific, so the
    record is open and the shared fields are optional."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    model_id: str
    model_type: str
    schema_version: NotRequired[str | int]
    engine: NotRequired[str]
    nobs: NotRequired[int | float | None]
    r_squared: NotRequired[float | None]
    r_squared_adj: NotRequired[float | None]
    pseudo_r2: NotRequired[float | None]
    llf: NotRequired[float | None]
    aic: NotRequired[float | None]
    bic: NotRequired[float | None]
    coefficients: NotRequired[dict[str, CoefficientRecord]]
    dispersion: NotRequired[str | None]
    alpha_estimated: NotRequired[bool]
    alpha_fixed_value: NotRequired[float | None]
    ancillary_parameters: NotRequired[list[AncillaryParameter]]
    overdispersion_test: NotRequired[OverdispersionTest | None]
    information_matrix: NotRequired[str]
    warnings: NotRequired[list[str | ModelWarning]]


TrustStatus = Literal["ok", "usable_with_caution", "blocked", "failed"]
TrustLabel = Literal[
    "analysis_running", "ready_to_interpret", "interpret_with_caution", "not_ready_to_interpret",
    "run_failed", "lifecycle_unavailable", "legacy_unavailable", "contract_unavailable",
]


class PreviewRunStatus(TypedDict):
    status: TrustStatus
    status_scope: str
    safe_to_generate_report: bool
    safe_to_interpret: str
    has_blockers: bool
    has_warnings: bool
    has_cautions: bool
    model_results_available: bool
    report_render_status: NotRequired[str]
    report_available: NotRequired[bool]


class TrustCounts(TypedDict):
    blockers: int
    warnings: int
    cautions: int
    info: int


class PrimaryReason(TypedDict):
    reason_id: str
    reason_key: str
    severity: str
    message: str
    message_params: NotRequired[dict[str, Any]]
    affected_variables: list[str]
    linked_issue_ids: list[str]


class ModelIdentity(TypedDict):
    primary_model_id: str
    model_label: str
    model_type: str
    y_variable: str
    n_observations: int | float | None
    x_variables: NotRequired[list[str]]
    x_variable_count: NotRequired[int]
    standard_error_type: NotRequired[str]


class DiagnosticSummaryPreview(TypedDict):
    """The run's trust summary (preview contract, versioned by
    ``preview_contract_version``). Nested evidence lists stay dictionaries."""

    available: bool
    preview_contract_version: str
    source_schema_version: str
    preview_status: str
    contract_warnings: list[str]
    run_lifecycle_status: str
    trust_label: TrustLabel
    primary_reasons: list[PrimaryReason]
    run_status: NotRequired[PreviewRunStatus]
    trust_counts: NotRequired[TrustCounts]
    model_identity: NotRequired[ModelIdentity]
    artifact_manifest: NotRequired[dict[str, Any]]
    diagnostic_highlights: NotRequired[list[dict[str, Any]]]
    coefficient_risk: NotRequired[dict[str, Any] | None]
    interpretation_restrictions: NotRequired[list[dict[str, Any]]]
    recommended_actions: NotRequired[list[dict[str, Any]]]


class PostEstimationResult(TypedDict):
    """A durable post-estimation answer; ``result`` varies by operation."""

    artifact_id: str
    artifact_type: str
    operation_id: str
    run_id: str
    model_run_id: str
    workflow_id: str
    workflow_step_id: str
    pack_family: NotRequired[str]
    source_sha256: NotRequired[str]
    request_fingerprint: NotRequired[str]
    result_sha256: NotRequired[str]
    result_schema: NotRequired[str]
    result: dict[str, Any]


class LegacyPredictionArtifact(TypedDict):
    artifact_id: str | None
    model_id: str | None
    model_type: str | None
    status: str | None
    nobs: int | None
    cv_folds: int | None
    sampling_method: str | None
    metrics: dict[str, float | None]


class LegacyPredictionEvidence(TypedDict):
    status: Literal["legacy"]
    consumer: str
    protocol: str
    validation: str
    comparability: str
    message: str
    model_id: str | None
    legacy_artifacts: list[LegacyPredictionArtifact]


class PredictionMetrics(TypedDict):
    n: NotRequired[int]
    metrics: dict[str, float | None]


class PredictionBaseline(TypedDict):
    model_id: NotRequired[str]
    metrics: dict[str, float | None]


class PredictionStructure(TypedDict):
    """StructureSpecV1 as a sample spec carries it; older specs omit the
    columns and the provenance."""

    kind: StructureKind
    group_column: NotRequired[str | None]
    time_column: NotRequired[str | None]
    entity_column: NotRequired[str | None]
    provenance: NotRequired[StructureProvenance]


class PredictionControl(TypedDict):
    """One negative control; each control type adds its own fields."""

    __pydantic_config__ = ConfigDict(extra="allow")  # type: ignore[misc]
    control: str
    seed: NotRequired[int | None]
    status: NotRequired[str]
    metrics: NotRequired[dict[str, float | None]]
    metric_gap: NotRequired[dict[str, float | None]]
    fold_importance: NotRequired[list[dict[str, Any]]]
    receipt: NotRequired[dict[str, Any]]


class PredictionDevelopment(TypedDict):
    cv: list[dict[str, Any]]


class ValidatedPredictionEvidence(TypedDict):
    """Predictive-research evidence validated against its payload contracts;
    nested packets keep their own versioned shapes."""

    status: Literal["validated"]
    consumer: str
    model_id: str
    sample_spec_hash: str | None
    dataset_sha256: str | None
    structure: PredictionStructure | None
    split_plan_hash: str | None
    split_parameters: dict[str, Any]
    oos: PredictionMetrics
    development: PredictionDevelopment
    baseline: PredictionBaseline
    controls: list[PredictionControl]
    limits: list[str]
    payload_versions: dict[str, Any]


class UnavailablePredictionEvidence(TypedDict):
    status: Literal["unavailable"]


PredictionResearchEvidence = ValidatedPredictionEvidence | LegacyPredictionEvidence | UnavailablePredictionEvidence


class RunDetail(TypedDict):
    run_id: str
    status: str | None
    mode: str | None
    started_at: str | None
    y: str | None
    x: list[str] | None
    lineage: list[LineageEntry]
    artifact_counts: dict[str, int]
    errors: IssueStream
    model_results: list[ModelResult]
    diagnostic_summary_preview: DiagnosticSummaryPreview
    table_1: list[dict[str, Any]]
    statistical_evidence: dict[str, Any] | None
    labels: RunLabels
    term_labels: dict[str, str]
    model_family_evidence: dict[str, Any] | None
    family_evidence: dict[str, Any] | None
    prediction_evidence: PredictionResearchEvidence | None
    post_estimation_results: list[PostEstimationResult]
    post_estimation_results_total: int


class RunDeletionPreview(TypedDict):
    run_id: str
    deletable: bool
    blocking_descendant_run_ids: list[str]
    blocking_status: str | None
    artifact_counts: dict[str, int]
    report_count: int
    agent_session_ids: list[str]
    agent_event_session_ids: list[str]
    proposal_ids: list[str]
    operation_record_ids: list[str]
    retained_shared_record_ids: list[str]
    fingerprint: str


class RunDeletionPreviewResponse(TypedDict):
    preview: RunDeletionPreview


class RunDeletionReceipt(TypedDict):
    run_id: str
    deleted_agent_session_ids: list[str]
    deleted_agent_event_session_ids: list[str]
    deleted_proposal_ids: list[str]
    deleted_operation_record_ids: list[str]


class RunDeletionResponse(TypedDict):
    deletion: RunDeletionReceipt


class ArtifactItem(TypedDict):
    artifact_id: str
    path: str
    artifact_type: str
    step: str
    sha256: str


class ArtifactGroup(TypedDict):
    artifact_type: str
    items: list[ArtifactItem]


class ArtifactGroups(TypedDict):
    groups: list[ArtifactGroup]


DatasetExportFormat = Literal["sav", "zsav", "dta", "csv", "xlsx"]


class DatasetExportNote(TypedDict):
    column: str
    field: str
    message: str


class DatasetExportReport(TypedDict):
    run_id: str
    node_id: str
    source_artifact_id: str
    source_rows: int
    rows: int
    columns: int
    column_names: list[str]
    options: dict[str, Any]
    format: DatasetExportFormat
    renamed: dict[str, str]
    notes: list[DatasetExportNote]


class DatasetExportResult(TypedDict):
    artifact_id: str
    filename: str
    download_url: str
    report: DatasetExportReport


class DatasetExportPreview(DatasetExportReport):
    sample: list[dict[str, Any]]
    filename: str


AiReportRecord = view_of(
    AiReportRecordRequest,
    "AiReportRecord",
    stored=True,
    fact_snapshot_hash=NotRequired[str],
    artifact_ids=NotRequired[list[str]],
    validation_status=NotRequired[ReportQualityStatus],
)
"""A stored AI report: the browser's evidence snapshot plus the server-derived
audit fields. Reports stored before a field existed omit it (the audit fields
date from v1.8.6; the store from v1.8.0)."""


class AiReportSaved(TypedDict):
    schema_version: str
    record: AiReportRecord


class AiReportList(TypedDict):
    reports: list[AiReportRecord]


TransformId = Literal[TRANSFORM_IDS]  # type: ignore[valid-type]
"""The ARMA-GARCH pack's transform vocabulary (engine.packs.arma_garch.transforms)."""


class TransformRecommendation(TypedDict):
    transform_id: TransformId
    score: float
    reason: str


class TransformPreflight(TypedDict):
    """ARMA-GARCH transform preflight; per-transform profiles and diagnostics
    are the pack's own versioned evidence."""

    schema_version: int
    source_row_count: int
    analysis_row_count: int
    diagnostics: list[dict[str, Any]]
    transform_profiles: dict[str, dict[str, Any]]
    recommendation: TransformRecommendation
    transform_confirmation_required: Literal[True]
