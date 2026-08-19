"""Manual typed data-operation endpoints for the V11 cast vertical slice."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
import pandas as pd
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..artifacts import read_json

from ..agent.chains import ChainHeadConflict, ensure_chain_root
from ..agent.events import AgentEventStream
from ..agent.operations import (
    OperationRecordStore,
    OperationRecordTransitionError,
    OperationRegistry,
    OperationValidationError,
)
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.risk import (
    RiskAuthorizationError,
    RiskAuthorizationExpired,
    RiskAuthorizationReplay,
    RiskAuthorizationRequired,
    RiskAuthorizationStore,
    RiskAuthorizationStale,
)
from ..agent.session import JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from ..data_operations import (
    DataCastItem,
    DataColumnCastSpecV1,
    DataColumnCastValidationError,
    DataMetadataUnavailableError,
    DataColumnsCastSpecV1,
    FeatureRecipeOperationSpecV1,
    DataTransformSpecV1,
    apply_metadata_mutation,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_column_cast,
    preview_data_columns_cast,
    preview_feature_recipe,
    preview_data_transform,
    preview_metadata_mutation,
    read_metadata_mutation_record,
    resolve_data_column_cast_context,
    resolve_metadata_registry,
    _read_frame,
    _resolve_source,
)
from ..data_profile import DatasetRefV1, build_data_profile
from ..metadata import build_metadata_loss_manifest
from ..metadata import MetadataMutationSpecV1
from ..code_execution import (
    MAX_CODE_CHARS,
    CodeExecuteSpecV1,
    CodeExecuteValidationError,
    NondeterministicCodeError,
    preview_code_execute,
)
from ..figure_context import FigureContextError, resolve_figure_ai_context
from ..sandbox import SandboxUnavailableError

router = APIRouter()


def _public_data_operation_manifest() -> dict[str, Any]:
    """Return the package-owned descriptor projection without executing code."""

    from ..data_operation_manifest import build_data_operation_manifest

    manifest = build_data_operation_manifest()
    if hasattr(manifest, "to_dict"):
        payload = manifest.to_dict()
    elif isinstance(manifest, dict):
        payload = dict(manifest)
    else:
        raise TypeError("data operation manifest must expose a JSON projection")
    if not isinstance(payload.get("operations"), list):
        raise ValueError("data operation manifest has no bounded operations projection")
    return payload


def _require_live_data_operation_descriptor(
    operation_id: str,
    *,
    preview_ref: str | None = None,
    confirm_ref: str | None = None,
):
    """Resolve route authority from the one server-owned live manifest."""

    from .. import data_operation_manifest

    manifest = data_operation_manifest.build_data_operation_manifest()
    descriptor = next(
        (item for item in manifest.operations if item.operation_id == operation_id),
        None,
    )
    if descriptor is None:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_NOT_ADVERTISED",
            message="The requested data operation is not advertised by the live server manifest.",
            details={"operation_id": operation_id},
        )
    if preview_ref is not None and descriptor.preview_ref != preview_ref:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_ROUTE_IDENTITY_MISMATCH",
            message="The route does not match the live data-operation descriptor.",
            details={"operation_id": operation_id, "expected": descriptor.preview_ref},
        )
    if confirm_ref is not None and descriptor.confirm_ref != confirm_ref:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_ROUTE_IDENTITY_MISMATCH",
            message="The route does not match the live data-operation descriptor.",
            details={"operation_id": operation_id, "expected": descriptor.confirm_ref},
        )
    return descriptor


def _live_data_operation_ids() -> frozenset[str]:
    """Return the record lookup allowlist from the live manifest projection."""

    payload = _public_data_operation_manifest()
    return frozenset(
        str(item["operation_id"])
        for item in payload["operations"]
        if isinstance(item, dict) and isinstance(item.get("operation_id"), str)
    )


def _resolve_profile(
    root: Path,
    *,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> dict[str, Any]:
    probe = DataColumnCastSpecV1(
        source_run_id=source_run_id,
        source_node_id=source_node_id,
        source_artifact_id=source_artifact_id,
        column="__profile_source__",
        target_dtype="string",
    )
    _run_root, _graph, _node, artifact, source_path = _resolve_source(root, probe)
    frame = _read_frame(source_path)
    content_sha256 = artifact.get("sha256")
    if not isinstance(content_sha256, str) or not content_sha256:
        content_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    registry = resolve_metadata_registry(
        root,
        source_run_id=source_run_id,
        source_node_id=source_node_id,
        source_artifact_id=source_artifact_id,
    )
    if registry is None:
        raise DataMetadataUnavailableError(
            "profile requires a confirmed server-owned metadata artifact"
        )
    declared_metadata = registry.to_profile_metadata(
        tuple(str(column) for column in frame.columns)
    )
    profile = build_data_profile(
        frame=frame,
        dataset_ref=DatasetRefV1(
            run_id=source_run_id,
            node_id=source_node_id,
            artifact_id=source_artifact_id,
            content_sha256=content_sha256,
            schema_revision=registry.schema_revision,
            metadata_revision=registry.metadata_revision,
        ),
        declared_metadata=declared_metadata,
    )
    if not hasattr(profile, "to_dict"):
        raise TypeError("data profile must expose a JSON projection")
    return profile.to_dict()


class DataColumnCastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    column: str = Field(min_length=1, max_length=200)
    target_dtype: Literal["numeric", "string", "datetime"]


class DataColumnCastConfirmRequest(DataColumnCastRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class DataColumnsCastItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=200)
    target_dtype: Literal["numeric", "string", "datetime"]


class DataColumnsCastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    casts: list[DataColumnsCastItem] = Field(min_length=1, max_length=200)
    output_format: Literal["csv", "xlsx"] = "csv"


class DataColumnsCastConfirmRequest(DataColumnsCastRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class FeatureRecipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    recipe_id: str = Field(min_length=1, max_length=200)
    # The manifest calls this field recipe_operation_id so it cannot be
    # confused with the outer operation identity (data.feature_recipe).  Keep
    # operation_id as an input alias for existing clients.
    operation_id: Literal["derived_variable", "recode", "interaction", "log", "ratio"] = Field(
        validation_alias=AliasChoices("operation_id", "recipe_operation_id")
    )
    inputs: list[str] = Field(min_length=1, max_length=2)
    output: str = Field(min_length=1, max_length=200)
    output_type: str = Field(default="numeric", min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    fit_scope: Literal["stateless", "date_local", "period_fitted"] = "stateless"
    missing_policy: str = Field(default="fail_closed", min_length=1, max_length=40)
    outlier_policy: str = Field(default="preserve", min_length=1, max_length=40)


class FeatureRecipeConfirmRequest(FeatureRecipeRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class DataTransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    operation: Literal[
        "merge",
        "append",
        "reshape",
        "subset",
        "dedupe",
        "rename",
        "aggregate",
        "fill_missing",
        "tsset",
        "lag",
        "sort",
        "split",
        "recode",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    secondary_run_id: str | None = Field(default=None, max_length=200)
    secondary_node_id: str | None = Field(default=None, max_length=300)
    secondary_artifact_id: str | None = Field(default=None, max_length=200)


class DataTransformConfirmRequest(DataTransformRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class MetadataMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    weight: dict[str, Any] | None = None
    split: dict[str, Any] | None = None
    group: dict[str, Any] | None = None


class MetadataMutationConfirmRequest(MetadataMutationRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)


class MetadataLossPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_format: str = Field(min_length=1, max_length=40)
    target_format: str = Field(min_length=1, max_length=40)
    metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DataModelRunRequest(BaseModel):
    """Start the existing OLS lifecycle from a materialized data-operation node."""

    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    model_type: Literal["ols"] = "ols"
    y: str = Field(min_length=1, max_length=200)
    x: list[str] = Field(min_length=1, max_length=200)
    covariance: Literal["", "unadjusted", "robust", "clustered"] = "robust"


class CodeExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    language: Literal["python"] = "python"
    output_format: Literal["csv", "xlsx"] = "csv"


class CodeExecuteConfirmRequest(CodeExecuteRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)
    risk_authorization_id: str | None = Field(default=None, min_length=1, max_length=200)
    risk_authorization_token: str | None = Field(default=None, min_length=1, max_length=500)


class CodeExecuteRiskAuthorizationRequest(CodeExecuteRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)
    session_id: str = Field(default="agent_data_ui", min_length=1, max_length=200)
    acknowledge_risk: Literal[True]


def _root(project_root: str):
    from pathlib import Path

    requested = Path(project_root).expanduser()
    root = requested.resolve()
    if requested.is_symlink() or not root.is_dir() or not (root / "runs").is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _spec(body: DataColumnCastRequest) -> DataColumnCastSpecV1:
    return DataColumnCastSpecV1(
        source_run_id=body.source_run_id,
        source_node_id=body.source_node_id,
        source_artifact_id=body.source_artifact_id,
        column=body.column,
        target_dtype=body.target_dtype,
    )


def _preview_or_error(root, spec: DataColumnCastSpecV1, *, confirm: bool):
    try:
        return preview_data_column_cast(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "data.column.cast", "reason": str(exc)},
        ) from exc


def _batch_spec(body: DataColumnsCastRequest) -> DataColumnsCastSpecV1:
    try:
        return DataColumnsCastSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            casts=tuple(DataCastItem(item.column, item.target_dtype) for item in body.casts),
            output_format=body.output_format,
        )
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed batch cast specification is invalid.",
            details={"operation_id": "data.columns.cast", "reason": str(exc)},
        ) from exc


def _batch_preview_or_error(root, spec: DataColumnsCastSpecV1, *, confirm: bool):
    try:
        return preview_data_columns_cast(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "data.columns.cast", "reason": str(exc)},
        ) from exc


def _feature_recipe_spec(body: FeatureRecipeRequest) -> FeatureRecipeOperationSpecV1:
    from ..predictive_research.contracts import FeatureRecipeV1

    try:
        recipe = FeatureRecipeV1(
            recipe_id=body.recipe_id,
            operation_id=body.operation_id,
            operation_version=1,
            inputs=tuple(body.inputs),
            outputs=(body.output,),
            output_types=(body.output_type,),
            parameters=body.parameters,
            fit_scope=body.fit_scope,
            source_artifact=body.source_artifact_id,
            lineage_parent=body.source_node_id,
            missing_policy=body.missing_policy,
            outlier_policy=body.outlier_policy,
        )
        return FeatureRecipeOperationSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            recipe=recipe,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed FeatureRecipe specification is invalid.",
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc


def _feature_recipe_preview_or_error(root, spec: FeatureRecipeOperationSpecV1, *, confirm: bool):
    try:
        return preview_feature_recipe(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The FeatureRecipe source changed before confirmation."
                if confirm
                else "The typed FeatureRecipe cannot be previewed."
            ),
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc


def _data_transform_spec(body: DataTransformRequest) -> DataTransformSpecV1:
    try:
        return DataTransformSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            operation=body.operation,
            parameters=body.parameters,
            secondary_run_id=body.secondary_run_id,
            secondary_node_id=body.secondary_node_id,
            secondary_artifact_id=body.secondary_artifact_id,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed data transform specification is invalid.",
            details={"operation_id": f"data.{body.operation}", "reason": str(exc)},
        ) from exc


def _data_transform_preview_or_error(root, spec: DataTransformSpecV1, *, confirm: bool):
    try:
        return preview_data_transform(root, spec)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The data transform source changed before confirmation."
                if confirm
                else "The typed data transform cannot be previewed."
            ),
            details={"operation_id": f"data.{spec.operation}", "reason": str(exc)},
        ) from exc


def _metadata_mutation_spec(body: MetadataMutationRequest) -> MetadataMutationSpecV1:
    try:
        return MetadataMutationSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            metadata=body.metadata,
            weight=body.weight,
            split=body.split,
            group=body.group,
        )
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The typed metadata mutation specification is invalid.",
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc


def _metadata_mutation_preview_or_error(
    root,
    spec: MetadataMutationSpecV1,
    *,
    confirm: bool,
):
    try:
        return preview_metadata_mutation(root, spec)
    except DataMetadataUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_METADATA_UNAVAILABLE",
            message="The selected data artifact has no confirmed server-owned metadata registry.",
            details={"reason": str(exc)},
        ) from exc
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The metadata source changed before confirmation."
                if confirm
                else "The typed metadata mutation cannot be previewed."
            ),
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc


def _model_source_or_error(root, body: DataModelRunRequest) -> tuple[Path, dict[str, Any], str | None]:
    """Resolve and fingerprint a materialized data node before dispatch."""

    if len(set(body.x)) != len(body.x):
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The model predictors must be unique.",
            details={"source_node_id": body.source_node_id},
        )
    if body.y in body.x:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The outcome cannot also be a predictor.",
            details={"outcome": body.y},
        )
    probe = DataColumnCastSpecV1(
        source_run_id=body.source_run_id,
        source_node_id=body.source_node_id,
        source_artifact_id=body.source_artifact_id,
        column="__model_source__",
        target_dtype="string",
    )
    try:
        run_root, _graph, node, artifact, source_path = _resolve_source(root, probe)
        frame = _read_frame(source_path)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The selected graph node is not a usable materialized dataset.",
            details={"source_node_id": body.source_node_id, "reason": str(exc)},
        ) from exc
    missing = [column for column in [body.y, *body.x] if column not in frame.columns]
    if missing:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The model columns are not present in the selected data node.",
            details={"missing_columns": missing},
        )
    non_numeric = [
        column
        for column in [body.y, *body.x]
        if not pd.api.types.is_numeric_dtype(frame[column])
    ]
    if non_numeric:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_INVALID",
            message="The v1.8.6 data-node model entry currently requires numeric OLS columns.",
            details={"non_numeric_columns": non_numeric},
        )
    node_hash: str | None = getattr(node, "node_hash", None)
    index_path = run_root / "node_index.json"
    if index_path.is_file():
        try:
            indexed = read_json(index_path).get(body.source_node_id) or {}
            if indexed.get("node_hash"):
                node_hash = str(indexed["node_hash"])
        except (OSError, ValueError, AttributeError):
            pass
    return source_path, {"artifact": artifact, "node_hash": node_hash}, body.source_node_id


def _code_spec(body: CodeExecuteRequest) -> CodeExecuteSpecV1:
    try:
        return CodeExecuteSpecV1(
            source_run_id=body.source_run_id,
            source_node_id=body.source_node_id,
            source_artifact_id=body.source_artifact_id,
            code=body.code,
            language=body.language,
            output_format=body.output_format,
        )
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The code.execute specification is invalid.",
            details={"operation_id": "code.execute", "reason": str(exc)},
        ) from exc


def _code_preview_or_error(root, spec: CodeExecuteSpecV1, *, confirm: bool):
    """Preview really runs the code in the sandbox; a missing sandbox is a 503.

    Sandbox absence is not the user's mistake and not a stale context — the
    capability does not exist on this host, and we never run the code without it.
    """

    try:
        return preview_code_execute(root, spec)
    except SandboxUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=503,
            code="SANDBOX_UNAVAILABLE",
            message=(
                "Running code requires an OS sandbox, which is unavailable on this host. "
                "The code was not run."
            ),
            details={"operation_id": "code.execute", "reason": str(exc)},
        ) from exc
    except (CodeExecuteValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409 if confirm else 422,
            code="DATA_OPERATION_STALE" if confirm else "DATA_OPERATION_INVALID",
            message=(
                "The source data context changed before confirmation."
                if confirm
                else "The typed data operation cannot be previewed."
            ),
            details={"operation_id": "code.execute", "reason": str(exc)},
        ) from exc


def _require_ready_code_preview(
    body: CodeExecuteConfirmRequest | CodeExecuteRiskAuthorizationRequest,
    preview,
) -> None:
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The code failed when it was run in the sandbox.",
            details={"operation_id": "code.execute", "error": preview.error},
        )
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message=(
                "The preview fingerprint no longer matches. Either the source data "
                "changed, or the code does not produce the same result every run."
            ),
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )


def _code_operation_context(
    root,
    body: CodeExecuteConfirmRequest | CodeExecuteRiskAuthorizationRequest,
    spec,
    preview,
) -> dict[str, Any]:
    """Build the same canonical typed proposal context for authorize and confirm."""

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{body.source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=body.session_id,
        chain_id=chain_id,
        active_head_run_id=body.source_run_id,
    )
    main_session_id = _ensure_main_session(repository, root)
    proposal_store = ProposalStore(workbench_root)
    registry = OperationRegistry()
    definition = registry.require("code.execute", "v1")
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "code": spec.code,
        "language": spec.language,
        "output_format": spec.output_format,
    }
    preconditions = {
        "context_version": "code-execute.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
        "source_sha256": preview.source_sha256,
    }
    changes = {
        "code": spec.code,
        "language": spec.language,
        "output_format": spec.output_format,
    }
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_code_exec_{preview.fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=body.session_id,
            chain_id=chain_id,
            operation_id="code.execute",
            operation_version="v1",
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=["code-execute-preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=[
                "arbitrary user code, run sandboxed against a copy of the source",
                "sandboxed does not mean low risk; downstream model rerun required",
            ],
            proposal_id=proposal_id,
        )
        events.emit(body.session_id, "proposal_ready", proposal.to_dict())
        events.emit(
            body.session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if proposal.target != target or proposal.preconditions != preconditions:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=main_session_id,
        proposal_store=proposal_store,
        operation_store=OperationRecordStore(workbench_root),
        operation_registry=registry,
        risk_authorization_store=RiskAuthorizationStore(workbench_root),
    )
    return {
        "workbench_root": workbench_root,
        "repository": repository,
        "events": events,
        "chain_id": chain_id,
        "proposal_store": proposal_store,
        "registry": registry,
        "definition": definition,
        "proposal": proposal,
        "orchestrator": orchestrator,
    }


def _ensure_session(repository: JsonlSessionRepository, session_id: str, chain_id: str) -> None:
    try:
        metadata = repository.get_metadata(session_id)
    except (KeyError, ValueError):
        repository.create_session(session_id, chain_id=chain_id, role="chain")
        return
    if metadata.get("role") != "chain" or metadata.get("chain_id") != chain_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_SCOPE_INVALID",
            message="The manual data operation session is outside this Chain scope.",
            details={"session_id": session_id, "chain_id": chain_id},
        )


def _ensure_data_chain_scope(
    root,
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    chain_id: str,
    active_head_run_id: str,
) -> None:
    _ensure_session(repository, session_id, chain_id)
    try:
        ensure_chain_root(
            root / "workbench",
            runs_root=root / "runs",
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=session_id,
        )
    except ChainHeadConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed operation Chain active head changed before confirmation.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _ensure_main_session(repository: JsonlSessionRepository, root) -> str:
    try:
        repository.get_metadata("agent_main")
    except (KeyError, ValueError):
        repository.create_session("agent_main", chain_id=f"project:{root}", role="main")
    return "agent_main"


def _confirm_direct_data_operation(
    root: Path,
    *,
    operation_id: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
    preview_fingerprint: str,
    source_sha256: str,
    secondary_source_sha256: str | None,
    session_id: str,
    target_fields: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Bind a legacy direct data route to the server proposal gate.

    The route keeps the existing proposal gate, then creates the same durable
    OperationRecord used by the central operation lifecycle.  The package-owned
    data-consumer adapter completes that record after the immutable effect is
    committed.
    """

    descriptor = _require_live_data_operation_descriptor(operation_id)
    from ..data_operation_manifest import build_data_consumer_runtime_adapter

    try:
        # Validate the server-owned runtime join before the package effect can
        # be reached.  Completion validates the same join against typed ports.
        build_data_consumer_runtime_adapter()
    except (ImportError, OSError, TypeError, ValueError, RuntimeError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_CONSUMER_RUNTIME_UNAVAILABLE",
            message="The server-owned data-consumer runtime is unavailable; execution was blocked.",
            details={"operation_id": operation_id, "reason": str(exc)},
        ) from exc

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=session_id,
        chain_id=chain_id,
        active_head_run_id=source_run_id,
    )
    local_operation = descriptor.executor_key.startswith("executor:workbench.data_consumer.")
    definition = (
        None
        if local_operation
        else OperationRegistry().require(operation_id, descriptor.operation_version)
    )
    target = {
        "run_id": source_run_id,
        "node_ref": source_node_id,
        "artifact_id": source_artifact_id,
        "workflow_id": f"route:{operation_id}",
        "step_id": f"preview:{preview_fingerprint[:32]}",
        **target_fields,
    }
    dependency_fingerprints = [source_sha256]
    if secondary_source_sha256:
        dependency_fingerprints.append(secondary_source_sha256)
    preconditions = {
        "context_version": f"{operation_id}.v1",
        "context_fingerprint": preview_fingerprint,
        "source_fingerprint": preview_fingerprint,
        "dependency_fingerprints": dependency_fingerprints,
        "active_head_run_id": source_run_id,
        "owner_resolution": "typed_data_node",
    }
    if definition is not None:
        definition.validate(target=target, preconditions=preconditions, changes=changes)
    else:
        if any(not isinstance(value, str) or not value.strip() for value in target.values() if isinstance(value, str)):
            raise WorkbenchAPIError(
                status_code=422,
                code="DATA_OPERATION_INVALID",
                message="The local data-consumer operation has an invalid identity.",
                details={"operation_id": operation_id},
            )
    proposal_store = ProposalStore(workbench_root)
    safe_operation_id = operation_id.replace(".", "_")
    proposal_id = f"proposal_{safe_operation_id}_{preview_fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=session_id,
            chain_id=chain_id,
            operation_id=operation_id,
            operation_version=descriptor.operation_version,
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=[f"{operation_id}:preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=["downstream model rerun required"],
            proposal_id=proposal_id,
        )
        events.emit(session_id, "proposal_ready", proposal.to_dict())
        events.emit(
            session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if (
        proposal.target != target
        or proposal.preconditions != preconditions
        or proposal.changes != changes
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )
    try:
        confirmation = proposal_store.confirm(
            proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview_fingerprint,
            current_active_head_run_id=source_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data proposal became stale before confirmation.",
            details={"proposal_id": proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    record_store = OperationRecordStore(workbench_root)
    operation_record = record_store.create_pending(
        confirmation,
        command_id=confirmation.command_id,
    )
    if operation_record.status not in {"completed", "failed", "stale", "cancelled"}:
        operation_record = record_store.claim_execution(
            operation_record.record_id,
            execution_key=f"exec_{preview_fingerprint[:32]}",
            lease_owner="data-consumer-route",
        )
    return {
        "proposal": proposal_store.latest_revision(proposal_id).to_dict(),
        "confirmation": confirmation.to_dict(),
        "operation_record": operation_record.to_dict(),
    }


def _complete_direct_data_operation(
    root: Path,
    confirmation_result: dict[str, Any],
    effect: Any,
    *,
    method: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a package effect to OperationRecord and expose bounded evidence ports."""

    from ..data_operation_manifest import (
        DataConsumerDerivedPortV1,
        DataConsumerEvidencePortV1,
        DataConsumerOutputPortsV1,
        DataConsumerServerEvidenceV1,
        build_data_consumer_runtime_adapter,
    )

    operation_record_payload = confirmation_result.get("operation_record")
    if not isinstance(operation_record_payload, dict):
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation has no durable OperationRecord.",
            details={},
        )
    record_id = operation_record_payload.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation record identity is invalid.",
            details={},
        )
    store = OperationRecordStore(root / "workbench")
    record = store.get(record_id)
    if record.status == "completed":
        return record.to_dict()
    execution_key = record.execution.get("execution_key")
    if not isinstance(execution_key, str) or not execution_key:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_RECORD_UNAVAILABLE",
            message="The data operation record has no execution claim.",
            details={"record_id": record_id},
        )
    adapter = build_data_consumer_runtime_adapter()
    derived_port = DataConsumerDerivedPortV1(effect=effect)
    evidence_port = DataConsumerEvidencePortV1.from_server(
        method,
        DataConsumerServerEvidenceV1(method=method, payload=dict(evidence or {})),
    )
    effect_payload = derived_port.to_dict()
    bindings = {
        key: str(value)
        for key, value in effect_payload.items()
        if key.endswith("_id") and value is not None
    }
    record = store.bind_effect(
        record_id,
        execution_key=execution_key,
        bindings=bindings,
    )
    output_ports = DataConsumerOutputPortsV1(
        operation_record=record,
        derived=derived_port,
        evidence=evidence_port,
    )
    adapter.adapt_operation_record(record, output_ports)
    outputs = output_ports.to_dict(catalog_digest=adapter.catalog_digest)
    record = store.append_status(
        record_id,
        "completed",
        outputs=outputs,
        diff_ref={
            "kind": "data-consumer-effect.v1",
            "artifact_id": effect_payload.get("artifact_id")
            or effect_payload.get("metadata_artifact_id"),
        },
        verification={
            "passed": True,
            "mode": "immutable_artifact_and_lineage",
            "child_node_id": effect_payload.get("child_node_id"),
        },
        effect_status="committed",
        projection_status="committed",
    )
    return record.to_dict()


@router.get("/data-operations/manifest")
def get_data_operation_manifest() -> dict[str, Any]:
    """Expose the read-only package descriptor used by data consumers."""

    try:
        return _public_data_operation_manifest()
    except (ImportError, OSError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=500,
            code="DATA_OPERATION_MANIFEST_UNAVAILABLE",
            message="The data-operation descriptor is unavailable.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/data-operations/metadata-loss/preview")
def preview_metadata_loss(body: MetadataLossPreviewRequest) -> dict[str, Any]:
    """Report interchange loss without writing or exporting any file."""

    try:
        manifest = build_metadata_loss_manifest(
            source_format=body.source_format,
            target_format=body.target_format,
            metadata=body.metadata,
        )
        return {"manifest": manifest.to_dict()}
    except (TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="METADATA_LOSS_PREVIEW_INVALID",
            message="The metadata-loss preview request is invalid.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/data-operations/metadata/preview")
def preview_metadata_mutation_route(
    project_root: str,
    body: MetadataMutationRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.metadata.update",
        preview_ref="/data-operations/metadata/preview",
    )
    spec = _metadata_mutation_spec(body)
    preview = _metadata_mutation_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/metadata/confirm")
def confirm_metadata_mutation_route(
    project_root: str,
    body: MetadataMutationConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.metadata.update",
        confirm_ref="/data-operations/metadata/confirm",
    )
    spec = _metadata_mutation_spec(body)
    preview = _metadata_mutation_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The metadata mutation preview fingerprint no longer matches the source.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    confirmation = _confirm_direct_data_operation(
        root,
        operation_id="data.metadata.update",
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        preview_fingerprint=preview.fingerprint,
        source_sha256=preview.source_sha256,
        secondary_source_sha256=None,
        session_id=body.session_id,
        target_fields={
            "metadata_fingerprint": preview.metadata_fingerprint,
            "changed_columns": list(preview.changed_columns),
        },
        changes=spec.to_dict(),
    )
    try:
        effect = apply_metadata_mutation(root, spec, preview)
        metadata_operation = read_metadata_mutation_record(root, effect.record_id)
        operation = _complete_direct_data_operation(
            root,
            confirmation,
            effect,
            method="metadata_update",
            evidence={
                "metadata_artifact_id": effect.metadata_artifact_id,
                "metadata_revision": effect.metadata_revision,
            },
        )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The metadata mutation could not be applied because its source changed.",
            details={"operation_id": "data.metadata.update", "reason": str(exc)},
        ) from exc
    return {
        "status": "completed",
        "effect": effect.to_dict(),
        "preview": preview.to_dict(),
        "operation": metadata_operation,
        "operation_record": operation,
        **confirmation,
    }


@router.get("/data-operations/metadata/{record_id}")
def get_metadata_mutation_route(project_root: str, record_id: str) -> dict[str, Any]:
    root = _root(project_root)
    try:
        operation = read_metadata_mutation_record(root, record_id)
        source = operation.get("source")
        artifact = operation.get("metadata_artifact")
        if not isinstance(source, dict) or not isinstance(artifact, dict):
            raise ValueError("metadata operation record is malformed")
        run_id = source.get("run_id")
        relative = artifact.get("path")
        expected_sha = artifact.get("sha256")
        if not isinstance(run_id, str) or not isinstance(relative, str):
            raise ValueError("metadata operation record has invalid artifact identity")
        artifact_path = (root / "runs" / run_id / relative).resolve()
        run_root = (root / "runs" / run_id).resolve()
        artifact_path.relative_to(run_root)
        if not artifact_path.is_file():
            raise FileNotFoundError("metadata artifact is missing")
        from ..artifacts import sha256_file

        if expected_sha != sha256_file(artifact_path):
            raise ValueError("metadata artifact fingerprint changed")
        artifact_payload = read_json(artifact_path)
        metadata = artifact_payload.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("metadata artifact payload is malformed")
        reloaded = {
            "record_id": record_id,
            "operation_id": operation.get("operation_id"),
            "source": source,
            "metadata_fingerprint": operation.get("metadata_fingerprint"),
            **metadata,
            "child_node_id": operation.get("child_node_id"),
        }
        return {"metadata": reloaded, "operation": operation}
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed metadata mutation record was not found or is invalid.",
            details={"record_id": record_id, "reason": str(exc)},
        ) from exc


@router.get("/data-operations/profile")
def get_data_operation_profile(
    project_root: str,
    source_run_id: str,
    source_node_id: str,
    source_artifact_id: str,
) -> dict[str, Any]:
    """Return a bounded server-built profile for one immutable data artifact."""

    root = _root(project_root)
    try:
        profile = _resolve_profile(
            root,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
        )
        return {"profile": profile}
    except DataMetadataUnavailableError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_METADATA_UNAVAILABLE",
            message="The selected data artifact has no confirmed server-owned metadata registry.",
            details={"reason": str(exc)},
        ) from exc
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_PROFILE_INVALID",
            message="The selected data artifact cannot be profiled.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/data-operations/column-cast/preview")
def preview_column_cast(project_root: str, body: DataColumnCastRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.column.cast",
        preview_ref="/data-operations/column-cast/preview",
    )
    spec = _spec(body)
    preview = _preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/column-cast/confirm")
async def confirm_column_cast(
    project_root: str,
    body: DataColumnCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.column.cast",
        confirm_ref="/data-operations/column-cast/confirm",
    )
    spec = _spec(body)
    preview = _preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={"failure_count": preview.failure_count},
        )

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{body.source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=body.session_id,
        chain_id=chain_id,
        active_head_run_id=body.source_run_id,
    )
    main_session_id = _ensure_main_session(repository, root)
    proposal_store = ProposalStore(workbench_root)
    registry = OperationRegistry()
    definition = registry.require("data.column.cast", "v1")
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "column": spec.column,
        "target_dtype": spec.target_dtype,
    }
    preconditions = {
        "context_version": "data-column-cast.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
    }
    changes = {"column": spec.column, "target_dtype": spec.target_dtype}
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_data_cast_{preview.fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=body.session_id,
            chain_id=chain_id,
            operation_id="data.column.cast",
            operation_version="v1",
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=["data-column-cast-preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=["downstream model rerun required"],
            proposal_id=proposal_id,
        )
        events.emit(
            body.session_id,
            "proposal_ready",
            proposal.to_dict(),
        )
        events.emit(
            body.session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if proposal.target != target or proposal.preconditions != preconditions:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )

    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=main_session_id,
        proposal_store=proposal_store,
        operation_store=OperationRecordStore(workbench_root),
        operation_registry=registry,
    )
    try:
        confirmation = proposal_store.confirm(
            proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        record = orchestrator.operation_store.create_pending(
            confirmation,
            command_id=confirmation.command_id,
        )
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before execution.",
            details={"proposal_id": proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": proposal_store.latest_revision(proposal_id).to_dict(),
        "operation": record.to_dict(),
        "status": record.status,
    }


@router.post("/data-operations/columns-cast/preview")
def preview_columns_cast(project_root: str, body: DataColumnsCastRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.columns.cast",
        preview_ref="/data-operations/columns-cast/preview",
    )
    spec = _batch_spec(body)
    preview = _batch_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/columns-cast/confirm")
async def confirm_columns_cast(
    project_root: str,
    body: DataColumnsCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.columns.cast",
        confirm_ref="/data-operations/columns-cast/confirm",
    )
    spec = _batch_spec(body)
    preview = _batch_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={
                "blocked_columns": [
                    item.column for item in preview.items if item.status != "ready"
                ]
            },
        )

    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    events = AgentEventStream(workbench_root)
    chain_id = f"data_chain:{body.source_run_id}"
    _ensure_data_chain_scope(
        root,
        repository,
        session_id=body.session_id,
        chain_id=chain_id,
        active_head_run_id=body.source_run_id,
    )
    main_session_id = _ensure_main_session(repository, root)
    proposal_store = ProposalStore(workbench_root)
    registry = OperationRegistry()
    definition = registry.require("data.columns.cast", "v1")
    casts = [item.to_dict() for item in spec.casts]
    target = {
        "run_id": spec.source_run_id,
        "node_ref": spec.source_node_id,
        "artifact_id": spec.source_artifact_id,
        "casts": casts,
        "output_format": spec.output_format,
    }
    preconditions = {
        "context_version": "data-columns-cast.v1",
        "context_fingerprint": preview.fingerprint,
        "active_head_run_id": spec.source_run_id,
        "owner_resolution": "typed_data_node",
    }
    changes = {"casts": casts, "output_format": spec.output_format}
    definition.validate(target=target, preconditions=preconditions, changes=changes)
    proposal_id = f"proposal_data_casts_{preview.fingerprint[:24]}"
    try:
        proposal = proposal_store.latest_revision(proposal_id)
    except KeyError:
        proposal = proposal_store.create(
            session_id=body.session_id,
            chain_id=chain_id,
            operation_id="data.columns.cast",
            operation_version="v1",
            target=target,
            preconditions=preconditions,
            changes=changes,
            evidence_refs=["data-columns-cast-preview"],
            expected_effect=["create one immutable child data artifact"],
            risks=["downstream model rerun required"],
            proposal_id=proposal_id,
        )
        events.emit(body.session_id, "proposal_ready", proposal.to_dict())
        events.emit(
            body.session_id,
            "needs_confirmation",
            {"proposal_id": proposal_id, "revision": proposal.revision},
        )
    if proposal.target != target or proposal.preconditions != preconditions:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="A different typed proposal already owns this preview fingerprint.",
            details={"proposal_id": proposal_id},
        )

    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=main_session_id,
        proposal_store=proposal_store,
        operation_store=OperationRecordStore(workbench_root),
        operation_registry=registry,
    )
    try:
        confirmation = proposal_store.confirm(
            proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        record = orchestrator.operation_store.create_pending(
            confirmation,
            command_id=confirmation.command_id,
        )
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before execution.",
            details={"proposal_id": proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": proposal_store.latest_revision(proposal_id).to_dict(),
        "operation": record.to_dict(),
        "status": record.status,
    }


@router.post("/data-operations/feature-recipe/preview")
def preview_feature_recipe_route(project_root: str, body: FeatureRecipeRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.feature_recipe",
        preview_ref="/data-operations/feature-recipe/preview",
    )
    spec = _feature_recipe_spec(body)
    preview = _feature_recipe_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/feature-recipe/confirm")
def confirm_feature_recipe_route(
    project_root: str,
    body: FeatureRecipeConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        "data.feature_recipe",
        confirm_ref="/data-operations/feature-recipe/confirm",
    )
    spec = _feature_recipe_spec(body)
    preview = _feature_recipe_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The FeatureRecipe preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The FeatureRecipe preview has blocking validation failures.",
            details={"reason": preview.reason, "next_step": preview.next_step},
        )
    confirmation = _confirm_direct_data_operation(
        root,
        operation_id="data.feature_recipe",
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        preview_fingerprint=preview.fingerprint,
        source_sha256=preview.source_sha256,
        secondary_source_sha256=None,
        session_id=body.session_id,
        target_fields={
            "recipe_id": spec.recipe.recipe_id,
            "recipe_operation_id": spec.recipe.operation_id,
            "output": spec.recipe.outputs[0],
        },
        changes=spec.recipe.to_dict(),
    )
    try:
        effect = apply_feature_recipe_operation(root, spec, preview)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The FeatureRecipe could not be applied because its source changed.",
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc
    operation = _complete_direct_data_operation(
        root,
        confirmation,
        effect,
        method="feature_recipe",
        evidence={"recipe_artifact_id": effect.recipe_artifact_id},
    )
    return {
        "status": "completed",
        "effect": effect.to_dict(),
        "preview": preview.to_dict(),
        "operation": operation,
        **confirmation,
    }


@router.post("/data-operations/transform/preview")
def preview_data_transform_route(project_root: str, body: DataTransformRequest) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        f"data.{body.operation}",
        preview_ref="/data-operations/transform/preview",
    )
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/transform/confirm")
def confirm_data_transform_route(
    project_root: str,
    body: DataTransformConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    _require_live_data_operation_descriptor(
        f"data.{body.operation}",
        confirm_ref="/data-operations/transform/confirm",
    )
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data transform preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
        )
    confirmation = _confirm_direct_data_operation(
        root,
        operation_id=f"data.{spec.operation}",
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        preview_fingerprint=preview.fingerprint,
        source_sha256=preview.source_sha256,
        secondary_source_sha256=preview.secondary_source_sha256,
        session_id=body.session_id,
        target_fields={
            "operation": spec.operation,
            "secondary_run_id": spec.secondary_run_id,
            "secondary_node_id": spec.secondary_node_id,
            "secondary_artifact_id": spec.secondary_artifact_id,
        },
        changes=spec.to_dict(),
    )
    try:
        effect = apply_data_transform(root, spec, preview)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data transform could not be applied because its source changed.",
            details={"operation_id": f"data.{spec.operation}", "reason": str(exc)},
        ) from exc
    operation = _complete_direct_data_operation(
        root,
        confirmation,
        effect,
        method=preview.method or f"data.{spec.operation}",
        evidence=dict(preview.evidence),
    )
    return {
        "status": "completed",
        "effect": effect.to_dict(),
        "preview": preview.to_dict(),
        "operation": operation,
        **confirmation,
    }


@router.post("/data-operations/model-run")
def start_model_from_data_node_route(
    project_root: str,
    body: DataModelRunRequest,
) -> dict[str, Any]:
    """Dispatch a real OLS run from a confirmed, materialized data-operation node.

    This is intentionally a narrow bridge: it reuses the existing run lifecycle,
    keeps the source node in ``run_inputs`` lineage, and does not invent a second
    estimator path for data operations.
    """

    root = _root(project_root)
    source_path, source, source_node_id = _model_source_or_error(root, body)
    from ..events import get_event_manager
    from ..services.run_service import _submit_run

    events = get_event_manager()
    if not events.try_acquire_slot():
        raise WorkbenchAPIError(
            status_code=429,
            code="RUN_SLOT_BUSY",
            message="A run is already in progress.",
            details={"source_node_id": source_node_id},
        )
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        result = _submit_run(
            root,
            form={
                "mode": "auto",
                "model_type": body.model_type,
                "covariance": body.covariance or "robust",
                "y": body.y,
                "x": ",".join(body.x),
            },
            upload_bytes=source_path.read_bytes(),
            upload_filename=Path(source["artifact"].get("path") or "data.csv").name,
            started_at=started_at,
            rerun_of=body.source_run_id,
            from_node=source_node_id,
            rerun_reason="data_operation_model",
            rerun_from={
                "source_run_id": body.source_run_id,
                "op_node_id": source_node_id,
                "source_artifact_id": body.source_artifact_id,
                "source_node_hash": source.get("node_hash"),
            },
        )
    except WorkbenchAPIError:
        events.release_slot(None)
        raise
    except Exception as exc:
        events.release_slot(None)
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_MODEL_DISPATCH_FAILED",
            message="The data node could not be submitted to the existing model lifecycle.",
            details={"reason": str(exc), "source_node_id": source_node_id},
        ) from exc
    return {
        "status": result["status"],
        "run_id": result["run_id"],
        "model_type": body.model_type,
        "source_lineage": {
            "source_run_id": body.source_run_id,
            "source_node_id": source_node_id,
            "source_artifact_id": body.source_artifact_id,
            "source_node_hash": source.get("node_hash"),
        },
    }


@router.post("/data-operations/code-execute/preview")
def preview_code_execute_route(project_root: str, body: CodeExecuteRequest) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/code-execute/risk-authorize")
def authorize_code_execute_risk(
    project_root: str,
    body: CodeExecuteRiskAuthorizationRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=True)
    _require_ready_code_preview(body, preview)
    context = _code_operation_context(root, body, spec, preview)
    proposal_store = context["proposal_store"]
    proposal = context["proposal"]
    try:
        proposal_store.confirm(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        grant = RiskAuthorizationStore(context["workbench_root"]).issue(
            operation_id="code.execute",
            operation_version="v1",
            proposal_id=proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            session_id=proposal.session_id,
            chain_id=proposal.chain_id,
            active_head_run_id=spec.source_run_id,
            actor_type="human_ui",
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before risk authorization.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    return {
        "proposal": proposal_store.latest_revision(proposal.proposal_id).to_dict(),
        "risk_authorization": grant.to_dict(include_token=True),
        "status": "risk_authorized",
    }


@router.post("/data-operations/code-execute/confirm")
async def confirm_code_execute(
    project_root: str,
    body: CodeExecuteConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _code_spec(body)
    preview = _code_preview_or_error(root, spec, confirm=True)
    _require_ready_code_preview(body, preview)
    context = _code_operation_context(root, body, spec, preview)
    proposal_store = context["proposal_store"]
    proposal = context["proposal"]
    orchestrator = context["orchestrator"]
    try:
        confirmation = proposal_store.confirm(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
        )
        record = orchestrator.operation_store.create_pending(
            confirmation,
            command_id=confirmation.command_id,
        )
        if not body.risk_authorization_id or not body.risk_authorization_token:
            raise RiskAuthorizationRequired(
                "code.execute requires explicit risk authorization before apply"
            )
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=spec.source_run_id,
            risk_authorization_id=body.risk_authorization_id,
            risk_authorization_token=body.risk_authorization_token,
        )
    except RiskAuthorizationExpired as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_EXPIRED",
            message="The high-risk authorization expired; review the preview again.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationReplay as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REPLAY",
            message="The high-risk authorization has already been consumed.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationStale as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_STALE",
            message="The high-risk authorization no longer matches this preview or active head.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationRequired as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REQUIRED",
            message="A high-risk operation needs explicit risk authorization before it can run.",
            details={
                "proposal_id": proposal.proposal_id,
                "operation_id": "code.execute",
                "risk_authorization_endpoint": "/data-operations/code-execute/risk-authorize",
            },
        ) from exc
    except NondeterministicCodeError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="CODE_NOT_DETERMINISTIC",
            message=(
                "The code produced a different result when it was run again, so it is "
                "not a deterministic transform. Nothing was written."
            ),
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The typed data operation became stale before execution.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_CONFLICT",
            message="The typed data proposal is no longer confirmable.",
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except OperationRecordTransitionError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_REPLAY",
            message=(
                "This operation already has an execution claim with another "
                "risk authorization."
            ),
            details={"proposal_id": proposal.proposal_id},
        ) from exc
    except RiskAuthorizationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="RISK_AUTHORIZATION_INVALID",
            message="The high-risk authorization could not be validated.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    return {
        "proposal": proposal_store.latest_revision(proposal.proposal_id).to_dict(),
        "operation": record.to_dict(),
        "status": record.status,
    }


@router.get("/figures/ai-context")
def get_figure_ai_context(
    project_root: str,
    run_id: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Resolve a figure's chart type and backing numeric source for AI interpretation."""

    root = _root(project_root)
    try:
        return resolve_figure_ai_context(root, run_id=run_id, artifact_id=artifact_id)
    except (FigureContextError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="FIGURE_CONTEXT_NOT_FOUND",
            message="The figure or its numeric source could not be resolved.",
            details={"run_id": run_id, "artifact_id": artifact_id, "reason": str(exc)},
        ) from exc


@router.get("/data-operations/column-cast/context")
def get_column_cast_context(
    project_root: str,
    source_run_id: str,
    source_node_id: str,
) -> dict[str, Any]:
    root = _root(project_root)
    try:
        return resolve_data_column_cast_context(
            root,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
        )
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_INVALID",
            message="The selected graph node is not a materialized dataset source.",
            details={"operation_id": "data.column.cast", "reason": str(exc)},
        ) from exc


@router.get("/data-operations/column-cast/by-child-node")
def get_column_cast_operation_by_child_node(
    project_root: str,
    child_node_id: str,
) -> dict[str, Any]:
    """Resolve the durable operation record from its typed child-node binding."""

    root = _root(project_root)
    store = OperationRecordStore(root / "workbench", create=False)
    matches = [
        record
        for record in store.list_records()
        if record.operation_id in _live_data_operation_ids()
        and record.execution.get("bindings", {}).get("data_child_node_id") == child_node_id
    ]
    if not matches:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="No typed data operation record is bound to this child node.",
            details={"child_node_id": child_node_id},
        )
    matches.sort(key=lambda record: record.updated_at)
    return {"operation": matches[-1].to_dict()}


@router.get("/data-operations/column-cast/{record_id}")
def get_column_cast_operation(record_id: str, project_root: str) -> dict[str, Any]:
    root = _root(project_root)
    try:
        record = OperationRecordStore(root / "workbench").get(record_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed data operation record was not found.",
            details={"record_id": record_id},
        ) from exc
    if record.operation_id not in _live_data_operation_ids():
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed data operation record was not found.",
            details={"record_id": record_id},
        )
    return {"operation": record.to_dict()}
