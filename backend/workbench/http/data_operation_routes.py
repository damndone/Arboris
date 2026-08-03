"""Manual typed data-operation endpoints for the V11 cast vertical slice."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

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
    DataColumnsCastSpecV1,
    FeatureRecipeOperationSpecV1,
    DataTransformSpecV1,
    apply_data_transform,
    apply_feature_recipe_operation,
    preview_data_column_cast,
    preview_data_columns_cast,
    preview_feature_recipe,
    preview_data_transform,
    resolve_data_column_cast_context,
)
from ..code_execution import (
    MAX_CODE_CHARS,
    CodeExecuteSpecV1,
    CodeExecuteValidationError,
    NondeterministicCodeError,
    preview_code_execute,
)
from ..figure_context import FigureContextError, resolve_figure_ai_context
from ..sandbox import SandboxUnavailableError

# Typed operations that derive a child data node, and whose records the data
# drawer resolves by child node id for provenance.
_DATA_OPERATION_IDS = frozenset({"data.column.cast", "data.columns.cast", "code.execute"})

router = APIRouter()


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
    operation_id: Literal["derived_variable", "recode", "interaction", "log", "ratio"]
    inputs: list[str] = Field(min_length=1, max_length=2)
    output: str = Field(min_length=1, max_length=200)
    output_type: str = Field(default="numeric", min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    fit_scope: Literal["stateless", "date_local", "period_fitted"] = "stateless"
    missing_policy: str = Field(default="fail_closed", min_length=1, max_length=40)
    outlier_policy: str = Field(default="preserve", min_length=1, max_length=40)


class FeatureRecipeConfirmRequest(FeatureRecipeRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)


class DataTransformRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_id: str = Field(min_length=1, max_length=300)
    source_artifact_id: str = Field(min_length=1, max_length=200)
    operation: Literal["merge", "append", "reshape", "subset"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    secondary_run_id: str | None = Field(default=None, max_length=200)
    secondary_node_id: str | None = Field(default=None, max_length=300)
    secondary_artifact_id: str | None = Field(default=None, max_length=200)


class DataTransformConfirmRequest(DataTransformRequest):
    preview_fingerprint: str = Field(min_length=1, max_length=200)


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

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
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


@router.post("/data-operations/column-cast/preview")
def preview_column_cast(project_root: str, body: DataColumnCastRequest) -> dict[str, Any]:
    root = _root(project_root)
    spec = _spec(body)
    preview = _preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/column-cast/confirm")
async def confirm_column_cast(
    project_root: str,
    body: DataColumnCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
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
    spec = _batch_spec(body)
    preview = _batch_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/columns-cast/confirm")
async def confirm_columns_cast(
    project_root: str,
    body: DataColumnsCastConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
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
    spec = _feature_recipe_spec(body)
    preview = _feature_recipe_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/feature-recipe/confirm")
def confirm_feature_recipe_route(
    project_root: str,
    body: FeatureRecipeConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
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
    try:
        effect = apply_feature_recipe_operation(root, spec, preview)
    except (DataColumnCastValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The FeatureRecipe could not be applied because its source changed.",
            details={"operation_id": "data.feature_recipe", "reason": str(exc)},
        ) from exc
    return {"status": "completed", "effect": effect.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/transform/preview")
def preview_data_transform_route(project_root: str, body: DataTransformRequest) -> dict[str, Any]:
    root = _root(project_root)
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=False)
    return {"spec": spec.to_dict(), "preview": preview.to_dict()}


@router.post("/data-operations/transform/confirm")
def confirm_data_transform_route(
    project_root: str,
    body: DataTransformConfirmRequest,
) -> dict[str, Any]:
    root = _root(project_root)
    spec = _data_transform_spec(body)
    preview = _data_transform_preview_or_error(root, spec, confirm=True)
    if preview.fingerprint != body.preview_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="DATA_OPERATION_STALE",
            message="The data transform preview fingerprint no longer matches the source data.",
            details={"expected": preview.fingerprint, "received": body.preview_fingerprint},
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
    return {"status": "completed", "effect": effect.to_dict(), "preview": preview.to_dict()}


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
        if record.operation_id in _DATA_OPERATION_IDS
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
    if record.operation_id not in _DATA_OPERATION_IDS:
        raise WorkbenchAPIError(
            status_code=404,
            code="DATA_OPERATION_NOT_FOUND",
            message="The typed data operation record was not found.",
            details={"record_id": record_id},
        )
    return {"operation": record.to_dict()}
