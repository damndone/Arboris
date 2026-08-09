"""HTTP seam for the v1.8.1 Agent Notebook lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
import threading
from typing import Any, Literal, Mapping

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..canonical import canonical_json_v1
from ..agent.context_compiler import (
    NotebookPlanningContextV1,
    attach_domain_memory_projection,
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from ..agent.notebook.memory_defaults import (
    DEFAULT_TARGET_CONTRACTS,
    DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
)
from ..agent.recipe_contracts import RECIPE_CONTRACTS
from ..agent.workflow_contracts import (
    MODEL_FAMILY_CONTRACTS,
    notebook_workflow_capability_ids,
)
from ..agent.notebook import NotebookService, OptionDraft, TypedProposal
from ..agent.notebook.evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from ..agent.notebook.errors import NotebookOptionError, OptionRevisionStale
from ..agent.model import CancellableOpenAICompatibleModelAdapter
from ..agent.notebook.planning_agent import (
    NotebookNoEligibleCapability,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    NotebookPlanningUnavailable,
)
from ..llm.config import load_llm_config
from ..agent.trace import (
    TraceWriter,
    record_compiled_context,
    record_domain_memory_retrieval,
)
from ..domain_memory.local_runtime import (
    LocalDomainMemoryRuntime,
    LocalDomainMemoryRuntimeError,
)
from ..domain_memory.retrieval import DomainMemoryRetrieval
from ..api_errors import WorkbenchAPIError
from ..contracts.agent.notebook_option import ExpectedArtifact
from ..engine.capabilities import build_capabilities
from ..agent.notebook.vocabulary import capability_artifact_types
from ..agent.recipes.registry import build_option_vocabulary
from ..capability_factory.notebook_catalog import (
    CapabilityBindingCatalog,
    CapabilityBindingCatalogError,
)
from ..capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from ..capability_factory.execution_authorization import (
    ExecutionAuthorizationError,
    OptionExecutionAuthorization,
)

router = APIRouter()

NOTEBOOK_PROVIDER_TIMEOUT_S = 300.0

# A local user can cancel a planning pass at any time. Do not impose a short
# aggregate deadline across its bounded provider turns: a valid inspect →
# correction → submit conversation can legitimately outlast it. Each provider
# call still has the five-minute timeout above, and inspection/correction turn
# limits remain owned by NotebookPlanningAgent.
NOTEBOOK_PLANNING_DEADLINE_S: float | None = None
_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES = 8
_DOMAIN_MEMORY_CONTEXT_MAX_BYTES = 8192
_DOMAIN_MEMORY_CONTEXT_MAX_OMISSIONS = 32
_RECIPE_DEFAULT_SCAN_INCOMPLETE_REASONS = frozenset({"entry_budget", "byte_budget"})
_ACTIVE_PLANNING_ATTEMPTS: dict[
    tuple[str, str, str], asyncio.Task[Any]
] = {}
_ACTIVE_PLANNING_ATTEMPTS_LOCK = threading.Lock()

_TRACE_VERSIONS = {
    "app_commit": "local-workbench",
    "model_id": "notebook-planner",
    "prompt_version": "notebook-plan/1",
    "vocabulary_version": "notebook/1",
    "context_profile": "notebook-plan/v1",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotebookCreateRequest(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    created_by: str = Field(min_length=1, max_length=200)
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    analysis_contract: dict[str, Any] = Field(default_factory=dict)
    user_focus: dict[str, Any] = Field(default_factory=dict)
    available_capabilities: list[str] = Field(default_factory=list, max_length=100)


class DatasetProjectionRequest(_StrictModel):
    upload_sha256: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    sheet_names: list[str] = Field(default_factory=list, max_length=100)


class NotebookProjectionRequest(_StrictModel):
    from_run_id: str | None = Field(default=None, min_length=1, max_length=200)
    dataset: DatasetProjectionRequest | None = None
    created_by: str = Field(min_length=1, max_length=200)
    title: str = Field(default="Analysis Notebook", min_length=1, max_length=300)


class RunDatasetNotebookProjectionRequest(_StrictModel):
    """Request a new dataset-rooted Notebook from a run's verified upload."""

    from_run_id: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    title: str = Field(default="Analysis Notebook", min_length=1, max_length=300)


class NotebookFocusRequest(_StrictModel):
    """User-authored intent and interaction mode; both are freshness dependencies."""

    goal: str | None = Field(default=None, min_length=1, max_length=4_000)
    interaction_mode: Literal["plan", "action"] | None = None


class ExpectedArtifactRequest(_StrictModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    artifact_type: str = Field(min_length=1, max_length=200)
    required: bool = True
    count: int = Field(default=1, ge=0)
    step: str | None = Field(default=None, min_length=1, max_length=200)


class OptionDraftRequest(_StrictModel):
    rank: int = Field(ge=1, le=3)
    rationale: str = Field(min_length=1, max_length=4_000)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    proposal: dict[str, Any]
    expected_artifacts: list[ExpectedArtifactRequest] = Field(
        default_factory=list, max_length=50
    )
    option_id: str | None = Field(default=None, min_length=1, max_length=200)
    capability_id: str | None = Field(default=None, min_length=1, max_length=200)


class ProposeOptionsRequest(_StrictModel):
    drafts: list[OptionDraftRequest] = Field(default_factory=list, max_length=3)
    count: int | None = Field(default=None, ge=1, le=3)
    attempt_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )


class RevalidateOptionRequest(OptionDraftRequest):
    pass


class ConfirmOptionRequest(_StrictModel):
    option_revision: int = Field(ge=1)
    proposal_id: str = Field(min_length=1, max_length=200)
    proposal_revision: int = Field(ge=1)


class AuthorizeOptionExecutionRequest(_StrictModel):
    """Untrusted receipt envelope; the service rechecks every server-owned pin."""

    authorization: dict[str, Any]


class DecisionRequest(_StrictModel):
    decision: Literal[
        "selected",
        "deferred",
        "rejected",
        "edited",
        "requested_more_options",
        "requested_explanation",
    ]
    actor: str = Field(min_length=1, max_length=200)
    edited_fields: list[str] | None = Field(default=None, max_length=50)
    note_ref: str | None = Field(default=None, max_length=500)


class ExecuteOptionRequest(_StrictModel):
    execution_status: str = Field(min_length=1, max_length=100)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)
    produced_artifacts: list[dict[str, Any]] | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=200)


def _project_root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _service(request: Request, project_root: str) -> tuple[Path, NotebookService]:
    root = _project_root(project_root)
    runtime = getattr(request.app.state, "capability_factory_runtime", None)
    catalog = (
        runtime.catalog
        if runtime is not None
        else getattr(request.app.state, "notebook_capability_bindings", None)
    )
    if catalog is not None and not isinstance(catalog, CapabilityBindingCatalog):
        raise WorkbenchAPIError(
            status_code=500,
            code="NOTEBOOK_CAPABILITY_BINDING_PROVIDER_INVALID",
            message="The server-owned Notebook capability binding provider is invalid.",
        )
    gateway = (
        runtime.execution_gateway
        if runtime is not None
        else getattr(request.app.state, "notebook_execution_gateway", None)
    )
    if gateway is not None and not isinstance(gateway, AuthorizedCapabilityExecutionGateway):
        raise WorkbenchAPIError(
            status_code=500,
            code="NOTEBOOK_EXECUTION_GATEWAY_PROVIDER_INVALID",
            message="The server-owned Notebook execution gateway is invalid.",
        )
    return root, NotebookService(
        root,
        capability_bindings=catalog,
        execution_gateway=gateway,
    )


def _trace(
    root: Path,
    notebook_id: str,
    run_family_id: str,
    *,
    trace_id: str | None = None,
) -> TraceWriter:
    return TraceWriter(
        root,
        scope={
            "project_id": root.name,
            "notebook_id": notebook_id,
            "run_family_id": run_family_id,
        },
        versions=dict(_TRACE_VERSIONS),
        trace_id=trace_id,
    )


def _notebook_trace(root: Path, service: NotebookService, notebook_id: str) -> TraceWriter:
    """Open the Notebook's persisted trace, creating it exactly once."""

    notebook = service.get_notebook(notebook_id)
    trace_id = service.store.ensure_trace_id(notebook_id)
    return _trace(
        root,
        notebook.notebook_id,
        notebook.run_family_id,
        trace_id=trace_id,
    )


def _compile(
    root: Path,
    service: NotebookService,
    notebook_id: str,
    *,
    focused_run_id: str | None = None,
    request: Request | None = None,
) -> tuple[NotebookPlanningContextV1, TraceWriter]:
    notebook = service.get_notebook(notebook_id)
    trace = _notebook_trace(root, service, notebook.notebook_id)
    context = replace(
        service.compile_context(notebook_id, focused_run_id=focused_run_id), trace_id=trace.trace_id
    )
    projection = _domain_memory_projection(
        request,
        root,
        service,
        notebook_id,
        context=context,
    )
    if projection is not None:
        context = attach_domain_memory_projection(context, projection)
        record_domain_memory_retrieval(trace, projection)
    record_compiled_context(trace, context)
    return context, trace


def _domain_memory_projection(
    request: Request | None,
    root: Path,
    service: NotebookService,
    notebook_id: str,
    *,
    context: NotebookPlanningContextV1 | None = None,
) -> dict[str, Any] | None:
    """Ask only the server-owned provider for an already-bounded projection.

    Compilation is deliberately complete before this call.  A deployment
    provider may therefore build/read a Project/RunFamily index from the
    canonical Notebook context before it retrieves approved cross-project
    hints; the memory result cannot retroactively change capability inputs or
    freshness dependencies.
    """

    provider = getattr(request.app.state, "domain_memory_context_provider", None) if request else None
    runtime = getattr(request.app.state, "domain_memory_runtime", None) if request else None
    if isinstance(runtime, LocalDomainMemoryRuntime):
        if context is None:
            raise WorkbenchAPIError(
                status_code=503,
                code="DOMAIN_MEMORY_CONTEXT_UNAVAILABLE",
                message="A compiled Notebook context is required before memory retrieval.",
            )
        try:
            now = datetime.now(timezone.utc).isoformat()
            facts = _domain_memory_facts(context)
            generic_result = runtime.retrieve_for_project(
                root,
                facts=facts,
                now=now,
                max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
            )
            if generic_result.outcome == "not_used":
                return None
            generic_result = _generic_fallback_retrieval(generic_result)
            default_results = [
                _registered_default_retrieval(
                    runtime.retrieve_for_project(
                        root,
                        facts={
                            **facts,
                            "analysis_family": recipe_id,
                            "model_family": recipe.model_family,
                        },
                        now=now,
                        max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                        max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                        vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
                    ),
                    model_type=recipe_id,
                    target_refs=frozenset(recipe.memory_target_refs),
                )
                for recipe_id, recipe in sorted(RECIPE_CONTRACTS.items())
                if _recipe_default_targets_are_published(recipe_id, recipe.memory_target_refs)
            ]
            native_default_model_types = sorted(
                {
                    target.model_type
                    for target_ref, target in DEFAULT_TARGET_CONTRACTS.items()
                    if not _is_published_recipe_default_target(target_ref)
                }
            )
            default_results.extend(
                _registered_default_retrieval(
                    runtime.retrieve_for_project(
                        root,
                        facts={
                            **facts,
                            "analysis_family": model_type,
                            "model_family": model_type,
                        },
                        now=now,
                        max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                        max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                        vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
                    ),
                    model_type=model_type,
                    target_refs=frozenset(
                        target_ref
                        for target_ref, target in DEFAULT_TARGET_CONTRACTS.items()
                        if target.model_type == model_type
                        and not _is_published_recipe_default_target(target_ref)
                    ),
                )
                for model_type in native_default_model_types
            )
            result = _merge_recipe_default_retrievals(
                generic_result=generic_result,
                recipe_results=default_results,
            )
        except LocalDomainMemoryRuntimeError as error:
            raise WorkbenchAPIError(
                status_code=503,
                code="DOMAIN_MEMORY_UNAVAILABLE",
                message="The local memory runtime is unavailable.",
            ) from error
        # Default-off is intentionally invisible to planning. The absence of a
        # projection means no memory participated; an enabled-but-empty library
        # remains observable as a bounded empty projection.
        return result.to_context_projection()
    if provider is None:
        # A legacy service object has no local preference authority. Do not let
        # its mere presence implicitly turn memory on for every project.
        return None
    projection = provider(
        request=request,
        project_root=root,
        notebook_service=service,
        notebook_id=notebook_id,
        context=context,
    )
    if projection is not None and not isinstance(projection, dict):
        raise WorkbenchAPIError(
            status_code=503,
            code="DOMAIN_MEMORY_PROVIDER_INVALID",
            message="The server-owned domain-memory provider returned an invalid projection.",
        )
    return projection


def _domain_memory_facts(context: NotebookPlanningContextV1) -> dict[str, Any]:
    """Project a small, server-compiled applicability vocabulary for retrieval."""

    facts: dict[str, Any] = {}
    for source in (context.analysis_contract, context.user_focus):
        for key in ("analysis_family", "model_family", "goal", "domain", "data_kind"):
            value = source.get(key)
            if isinstance(value, str) and value and len(value) <= 128:
                facts.setdefault(key, value)
    return facts


def _recipe_default_targets_are_published(
    recipe_id: str,
    target_refs: tuple[str, ...],
) -> bool:
    """Admit only a Recipe's exact registry-owned suggestion surface.

    The planner has not selected a Recipe yet, so this bridge may broaden the
    *server-derived lookup facts* to each published Recipe.  It must not turn
    an opaque memory target into a writable field or accept a target that the
    current Recipe did not publish.
    """

    if not target_refs:
        return False
    for target_ref in target_refs:
        target = DEFAULT_TARGET_CONTRACTS.get(target_ref)
        if target is None or target.model_type != recipe_id:
            return False
    return True


def _registered_default_retrieval(
    result: DomainMemoryRetrieval,
    *,
    model_type: str,
    target_refs: frozenset[str],
) -> DomainMemoryRetrieval:
    """Keep only current default targets owned by one model family.

    A generic memory predicate can truthfully match a server-derived family
    fact while its target reference belongs to a different family. Such a
    hint must never enter this preselection bridge: final proposal application
    would reject it too, but filtering it here prevents irrelevant model
    advice from influencing the provider before a model is chosen.
    """

    # A retrieval truncation hides a candidate value.  Keeping the visible
    # entries would make a high-risk default depend on result ordering, so the
    # exact Recipe path fails closed until the candidate set is complete.
    if any(
        omission.reason in _RECIPE_DEFAULT_SCAN_INCOMPLETE_REASONS
        for omission in result.omissions
    ):
        return replace(
            result,
            outcome="empty",
            reason="recipe_default_scan_incomplete",
            entries=(),
        )

    kept = []
    for entry in result.entries:
        refs = entry.recommended_target_refs
        is_current_default = (
            entry.apply_mode == "suggest_default"
            and entry.apply_mode_reason == "verifier_current"
            and entry.vocabulary_version == DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION
        )
        is_exact_recipe_target = is_current_default and bool(refs) and all(
            ref in target_refs
            and (target := DEFAULT_TARGET_CONTRACTS.get(ref)) is not None
            and target.model_type == model_type
            for ref in refs
        )
        if is_exact_recipe_target:
            kept.append(entry)
    if len(kept) == len(result.entries):
        return result
    return replace(
        result,
        outcome="used" if kept else "empty",
        reason="retrieved" if kept else "no_eligible_memory",
        entries=tuple(kept),
    )


def _recipe_default_retrieval(
    result: DomainMemoryRetrieval,
    *,
    recipe_id: str,
    target_refs: frozenset[str],
) -> DomainMemoryRetrieval:
    """Compatibility wrapper for Recipe-specific callers and tests."""

    return _registered_default_retrieval(
        result, model_type=recipe_id, target_refs=target_refs
    )


def _is_published_recipe_default_target(target_ref: str) -> bool:
    """Return whether a target belongs to a Recipe-specific default surface."""

    target = DEFAULT_TARGET_CONTRACTS.get(target_ref)
    if target is None:
        return False
    recipe = RECIPE_CONTRACTS.get(target.model_type)
    return recipe is not None and target_ref in recipe.memory_target_refs


def _is_published_default_target(target_ref: str) -> bool:
    """Return whether a target belongs to the server-owned default registry."""

    return target_ref in DEFAULT_TARGET_CONTRACTS


def _generic_fallback_retrieval(
    result: DomainMemoryRetrieval,
) -> DomainMemoryRetrieval:
    """Keep generic hints, but never leak Recipe default targets through them.

    A Recipe target is admissible only through its own lookup, where current
    verifier status, target ownership, and scan completeness have been
    checked.  This preserves ordinary generic-memory guidance (including OLS
    defaults outside a Recipe) without letting a declared or guessed family
    bypass the Recipe-specific authority boundary.
    """

    entries = tuple(
        entry
        for entry in result.entries
        if not any(
            _is_published_default_target(target_ref)
            for target_ref in entry.recommended_target_refs
        )
    )
    if len(entries) == len(result.entries):
        return result
    return replace(
        result,
        outcome="used" if entries else "empty",
        reason="retrieved" if entries else "no_eligible_memory",
        entries=entries,
    )


def _merge_recipe_default_retrievals(
    *,
    generic_result: DomainMemoryRetrieval,
    recipe_results: list[DomainMemoryRetrieval],
) -> DomainMemoryRetrieval:
    """Merge a bounded default preselection without expanding omissions.

    The generic lookup remains the public explanation of memory omissions.
    Per-Recipe lookups exist only to make an exact registered default visible
    before the provider selects a model, so their internal predicate and
    entry-budget misses must not multiply the public context packet. Exact
    Recipe defaults take the bounded entry slots first; generic hints retain
    their historic fallback role and cannot displace one.
    """

    entries_with_origin: list[tuple[Any, str | None]] = []
    selected_ids: set[tuple[str, int]] = set()
    used_bytes = 0

    def encoded_size(entry: Any) -> int:
        return len(
            json.dumps(
                entry.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    # A Recipe result is an atomic default candidate group.  Filling the
    # global entry budget one entry at a time could hide a later conflicting
    # target from the same Recipe, so admit the group whole or not at all.
    for result in recipe_results:
        group: list[Any] = []
        group_ids: set[tuple[str, int]] = set()
        group_bytes = 0
        for entry in result.entries:
            identity = (entry.memory_id, entry.revision)
            if identity in selected_ids or identity in group_ids:
                group = []
                break
            entry_bytes = encoded_size(entry)
            if entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES:
                group = []
                break
            group_ids.add(identity)
            group.append(entry)
            group_bytes += entry_bytes
        if not group:
            continue
        recipe_id = _default_model_type_for_entry(group[0])
        if recipe_id is None or any(
            _default_model_type_for_entry(entry) != recipe_id for entry in group
        ):
            continue
        if (
            len(entries_with_origin) + len(group) > _DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES
            or used_bytes + group_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
        ):
            continue
        selected_ids.update(group_ids)
        entries_with_origin.extend((entry, recipe_id) for entry in group)
        used_bytes += group_bytes

    # Generic entries have no published Recipe-default target, so they cannot
    # materialize a model setting and may use any remaining bounded slots.
    for entry in generic_result.entries:
        identity = (entry.memory_id, entry.revision)
        if identity in selected_ids or len(entries_with_origin) >= _DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES:
            continue
        entry_bytes = encoded_size(entry)
        if (
            entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
            or used_bytes + entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
        ):
            continue
        selected_ids.add(identity)
        entries_with_origin.append((entry, None))
        used_bytes += entry_bytes
    omissions = list(
        omission
        for omission in generic_result.omissions
        if (omission.memory_id, omission.revision) not in selected_ids
    )[:_DOMAIN_MEMORY_CONTEXT_MAX_OMISSIONS]

    def result() -> DomainMemoryRetrieval:
        entries = tuple(entry for entry, _origin in entries_with_origin)
        return DomainMemoryRetrieval(
            retrieval_ref=generic_result.retrieval_ref,
            scope_ref=generic_result.scope_ref,
            outcome="used" if entries else "empty",
            reason="retrieved" if entries else "no_eligible_memory",
            entries=entries,
            omissions=tuple(omissions),
            bounded=True,
            preference_ref=generic_result.preference_ref,
        )

    # ``LocalDomainMemoryRuntime`` budgets entry bytes, while this API projects
    # an envelope that also contains identifiers/reasons for omitted entries.
    # Enforce the real, complete context budget here.  Omission detail is
    # discarded first; if entries must be removed, generic hints are weakest.
    # Recipe defaults are removed as an entire Recipe group, never partially,
    # so a byte budget cannot manufacture a false unambiguous default.
    while (
        len(canonical_json_v1(result().to_context_projection()).encode("utf-8"))
        > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
    ):
        if omissions:
            omissions.pop()
            continue
        generic_index = next(
            (
                index
                for index in range(len(entries_with_origin) - 1, -1, -1)
                if entries_with_origin[index][1] is None
            ),
            None,
        )
        if generic_index is not None:
            entries_with_origin.pop(generic_index)
            continue
        recipe_ids = [
            origin
            for _entry, origin in entries_with_origin
            if origin is not None
        ]
        if not recipe_ids:
            break
        recipe_id = recipe_ids[-1]
        entries_with_origin[:] = [
            (entry, origin)
            for entry, origin in entries_with_origin
            if origin != recipe_id
        ]
    return result()


def _default_model_type_for_entry(entry: Any) -> str | None:
    """Return one server-registered model family for an exact default entry."""

    refs = getattr(entry, "recommended_target_refs", ())
    if not isinstance(refs, tuple):
        return None
    recipe_ids = {
        DEFAULT_TARGET_CONTRACTS[target_ref].model_type
        for target_ref in refs
        if _is_published_default_target(target_ref)
    }
    if len(recipe_ids) != 1:
        return None
    return next(iter(recipe_ids))


def _recipe_id_for_default_entry(entry: Any) -> str | None:
    """Return a published Recipe id only for an exact Recipe default entry."""

    model_type = _default_model_type_for_entry(entry)
    return model_type if model_type in RECIPE_CONTRACTS else None


def _draft(request: OptionDraftRequest) -> OptionDraft:
    expected = tuple(
        ExpectedArtifact(
            artifact_id=item.artifact_id,
            artifact_type=item.artifact_type,
            required=item.required,
            count=item.count,
            step=item.step,
        )
        for item in request.expected_artifacts
    )
    return OptionDraft(
        rank=request.rank,
        rationale=request.rationale,
        assumptions=tuple(request.assumptions),
        proposal=TypedProposal.from_dict(request.proposal),
        expected_artifacts=expected,
        option_id=request.option_id,
        capability_id=request.capability_id,
    )


def _context_packet(context: NotebookPlanningContextV1) -> dict[str, Any]:
    """Serialize the context plus the two distinct contract fingerprints."""

    packet = context.to_dict()
    packet["generation_context_hash"] = generation_context_hash(context)
    packet["freshness_dependency_fingerprint"] = freshness_dependency_fingerprint(context)
    if NOTEBOOK_PLANNING_DEADLINE_S is not None:
        packet["planning_deadline_s"] = NOTEBOOK_PLANNING_DEADLINE_S
    return packet


def _materializations_packet(
    service: NotebookService, notebook_id: str, revisions: list[Any]
) -> dict[str, dict[str, Any]]:
    """Project persisted Draft handoffs alongside the current option revisions."""

    materializations: dict[str, dict[str, Any]] = {}
    for revision in revisions:
        materialization = service.store.read_materialization(
            notebook_id, revision.option_id, revision.option_revision
        )
        if materialization is not None:
            materializations[revision.option_id] = materialization.to_dict()
    return materializations


def _execution_results_packet(
    service: NotebookService, notebook_id: str, revisions: list[Any]
) -> dict[str, dict[str, Any]]:
    """Project the latest result for each current Option revision.

    The Notebook is a durable projection.  A browser remount must therefore
    be able to recover a completed Draft/Run without relying on the transient
    confirmation state that initiated it.  Keep this packet model-neutral:
    the result contract records execution and artifact-contract facts, while
    model-specific result payloads remain in the Run's artifacts.
    """

    results: dict[str, dict[str, Any]] = {}
    for revision in revisions:
        view = service.store.read_option(notebook_id, revision.option_id)
        if not view.execution_results:
            continue
        raw = dict(view.execution_results[-1])
        if raw.get("option_revision") != revision.option_revision:
            # Do not display a result from an older revision as if it proved
            # the current proposal.  The option revision is the pin.
            continue
        validation = raw.get("artifact_validation")
        if not isinstance(validation, dict):
            capability_execution = raw.get("capability_execution")
            if isinstance(capability_execution, dict):
                # CF4 has already committed the full ArtifactContract@1.1
                # aggregate in its own durable store.  The Notebook route
                # exposes only its server-owned refs; it never accepts or
                # reconstructs adapter payloads here.
                results[revision.option_id] = {
                    "option_id": revision.option_id,
                    "option_revision": revision.option_revision,
                    "run_id": raw.get("run_id"),
                    "execution_status": raw.get("execution_status"),
                    "committed": raw.get("committed"),
                    "capability_execution": {
                        key: capability_execution.get(key)
                        for key in (
                            "dispatch_status",
                            "attempt_id",
                            "receipt_ref",
                            "completion_ref",
                            "artifact_validation_ref",
                            "object_graph_ref",
                            "assessment_ref",
                            "output_bundle_ref",
                            "attestation_ref",
                        )
                    },
                }
            continue
        raw_issues = [dict(issue) for issue in validation.get("issues", [])]
        bounded_issues = raw_issues[:64]
        validation_packet: dict[str, Any] = {
            "contract_profile": validation.get("contract_profile"),
            "validation_status": validation.get("validation_status"),
            "checked_dimensions": list(validation.get("checked_dimensions", [])),
            "not_evaluated_dimensions": list(
                validation.get("not_evaluated_dimensions", [])
            ),
            "issues": bounded_issues,
        }
        if len(raw_issues) > len(bounded_issues):
            validation_packet["omitted_issue_count"] = len(raw_issues) - len(bounded_issues)
        results[revision.option_id] = {
            "option_id": revision.option_id,
            "option_revision": revision.option_revision,
            "run_id": raw.get("run_id"),
            "execution_status": raw.get("execution_status"),
            "committed": raw.get("committed") is True,
            "artifact_validation": validation_packet,
            **(
                {"artifact_validation_scope": dict(raw["artifact_validation_scope"])}
                if isinstance(raw.get("artifact_validation_scope"), Mapping)
                else {}
            ),
            **(
                {"workflow_execution": dict(raw["workflow_execution"])}
                if isinstance(raw.get("workflow_execution"), Mapping)
                else {}
            ),
        }
    return results


def _notebook_error(exc: NotebookOptionError) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=exc.status_code,
        code=exc.code,
        message=str(exc),
        details=exc.details,
    )


def _record_planning_terminal_error(
    trace: TraceWriter | None,
    *,
    code: str,
    fatal: bool,
    detail: str,
) -> None:
    """Persist one bounded terminal outcome for a planning attempt.

    A planning failure is a user-visible product event, not merely an HTTP
    response. Provider bodies and prompts never enter this record: the typed
    code is sufficient for replay, diagnosis, and the UI timeline.
    """

    if trace is not None:
        trace.emit(
            "operation.error",
            payload={"code": code, "fatal": fatal, "detail": detail},
        )


def _notebook_planner_manifest_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Project only fields accepted by the published model-family contract.

    The general engine capability manifest is also used by the manual rerun UI,
    where a covariance selector may be useful for a different handler.  The
    Notebook planner emits ``model.genesis`` proposals, so its provider-facing
    catalog must be narrower: advertising an OLS-only field to a family whose
    contract rejects it creates a provider-visible option that can never become
    a valid Draft.
    """

    projected = dict(entry)
    family = MODEL_FAMILY_CONTRACTS.get(str(entry.get("key")))
    params = entry.get("params")
    if family is not None and isinstance(params, list):
        projected_params = [
            dict(param)
            for param in params
            if not (
                isinstance(param, Mapping)
                and not family.allows_covariance
                and param.get("key") == "covariance"
            )
        ]
        if not any(param.get("key") == "y" for param in projected_params):
            projected_params.insert(
                1,
                {
                    "key": "y",
                    "kind": "columns",
                    "label": "Outcome (Y)",
                    "required": True,
                    "role": "y",
                },
            )
        projected["params"] = projected_params
        published_artifacts = capability_artifact_types(str(entry.get("key")))
        if published_artifacts and not isinstance(projected.get("artifact_types"), Mapping):
            projected["artifact_types"] = dict(published_artifacts)
        option_vocabulary = build_option_vocabulary(str(entry.get("key")))
        if option_vocabulary is not None:
            fields = option_vocabulary.get("fields")
            projected["notebook_model_options_policy"] = {
                "supported": True,
                "allowed_fields": sorted(fields) if isinstance(fields, Mapping) else [],
                "forbidden_fields": [],
                "submission_rule": "use_published_fields",
            }
        else:
            projected["notebook_model_options_policy"] = {
                "supported": False,
                "allowed_fields": [],
                "forbidden_fields": ["covariance", "model_options"],
                "submission_rule": "omit_model_options",
            }
    return projected


def _planning_agent(
    root: Path,
    service: NotebookService,
    notebook_id: str,
    context: NotebookPlanningContextV1,
    trace: TraceWriter,
) -> NotebookPlanningAgent:
    if context.projection_source is None:
        raise NotebookPlanningUnavailable(
            "a source-bound Notebook projection is required before planning"
        )
    config = load_llm_config()
    if not config.is_configured():
        raise NotebookPlanningUnavailable(config.configuration_error_message())
    admitted_native = set(notebook_workflow_capability_ids())
    manifest = {
        str(entry["key"]): _notebook_planner_manifest_entry(entry)
        for entry in build_capabilities().get("model_types", [])
        if (
            isinstance(entry, dict)
            and entry.get("key") in admitted_native
        )
    }
    proposal_adapter = (
        "model.genesis"
        if context.projection_source
        and context.projection_source.get("kind") == "dataset"
        else "model.rerun"
    )
    source_model_type = _source_model_type(root, context)
    server_projections: tuple[dict[str, Any], ...] = ()
    if service.capability_bindings is not None:
        notebook = service.get_notebook(notebook_id)
        try:
            server_projections = service.capability_bindings.planner_projections(
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                )
            )
        except CapabilityBindingCatalogError as error:
            raise NotebookPlanningUnavailable(
                "a server-owned capability planner projection is unavailable"
            ) from error
    server_manifest = {
        str(item["key"]): dict(item)
        for item in server_projections
        if isinstance(item, Mapping) and isinstance(item.get("key"), str)
    }
    server_model_types = {
        capability: str(item["model_type"])
        for capability, item in server_manifest.items()
    }
    dynamic_artifact_types = {
        capability: dict(item["artifact_types"])
        for capability, item in server_manifest.items()
        if capability not in manifest
        and isinstance(item.get("artifact_types"), Mapping)
    }
    candidate_capabilities = tuple(
        dict.fromkeys(
            (
                *(capability for capability in context.available_capabilities if capability in manifest),
                *server_manifest,
            )
        )
    )
    catalog = {
        capability: {
            **(
                manifest[capability]
                if capability in manifest
                else server_manifest[capability]
            ),
            "model_type": server_model_types.get(capability, capability),
            "notebook_proposal_adapters": [proposal_adapter],
            **_model_options_catalog_metadata(root, context, capability),
        }
        for capability in candidate_capabilities
        if (
            capability in manifest
            or capability in server_manifest
        )
        and (
            capability_artifact_types(capability)
            or capability in dynamic_artifact_types
        )
        and (
            capability not in server_manifest
            or proposal_adapter in server_manifest[capability].get(
                "notebook_proposal_adapters", [proposal_adapter]
            )
        )
        and (
            proposal_adapter == "model.genesis"
            or source_model_type is None
            or server_model_types.get(capability, capability) == source_model_type
        )
        and (
            proposal_adapter == "model.genesis"
            or capability not in manifest
            or _supports_rerun_model_options(manifest[capability])
        )
    }
    if not catalog:
        raise NotebookNoEligibleCapability(
            _no_eligible_capability_message(
                proposal_adapter=proposal_adapter,
                source_model_type=source_model_type,
            )
        )

    def execute_inspections(requests, current):
        return service.compile_evidence_pack(
            notebook_id,
            requests=requests,
            trace=trace,
        )

    def validate_proposal(_context, submission) -> None:
        """Validate the provider packet against the server-owned model contract.

        The operation registry is intentionally provider-neutral. This second
        seam resolves the actual source handler and validates the merged
        payload, so a provider cannot turn a model-specific alias into a Draft
        that only fails after the user confirms it.
        """

        proposal = submission.proposal
        changes = proposal.changes
        if proposal.operation_id == "model.rerun":
            from ..lineage.run_inputs import read_run_inputs
            from ..repository.run_repository import _resolve_run_root
            from ..services.run_service import merge_form_overrides

            source_root = _resolve_run_root(str(root), str(proposal.target["run_id"]))
            inputs = read_run_inputs(source_root)
            source_form = inputs.get("form") or {}
            patch = changes.get("model_options") or {}
            if not isinstance(source_form, Mapping):
                raise ValueError("SOURCE_RUN_FORM_INVALID")
            if not isinstance(patch, Mapping):
                raise ValueError("MODEL_OPTIONS_PATCH_NOT_OBJECT")
            merge_form_overrides(source_form, {"model_options": dict(patch)})
            return

        if proposal.operation_id == "model.genesis":
            from ..agent.recipe_contracts import recipe_contract_for_model_type
            from ..model_options import bind_new_model_options

            model_params = changes.get("model_params") or {}
            if not isinstance(model_params, Mapping):
                return
            model_type = model_params.get("model_type")
            payload = changes.get("model_options")
            if payload is None:
                payload = model_params.get("model_options")
            if payload:
                if not isinstance(model_type, str) or not model_type:
                    raise ValueError("MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED")
                recipe_contract = recipe_contract_for_model_type(model_type)
                if recipe_contract is not None:
                    source = _context.projection_source or {}
                    source_hash = source.get("upload_sha256") if isinstance(source, Mapping) else None
                    if not isinstance(source_hash, str) or not source_hash:
                        raise ValueError("RECIPE_SOURCE_BINDING_INVALID")
                    payload = recipe_contract.bind_server_owned_options(
                        payload,
                        source_reference=f"upload:{source_hash}",
                    )
                bind_new_model_options(model_type, payload)

    notebook_config = (
        config
        if config.timeout_s >= NOTEBOOK_PROVIDER_TIMEOUT_S
        else replace(config, timeout_s=NOTEBOOK_PROVIDER_TIMEOUT_S)
    )
    return NotebookPlanningAgent(
        adapter=CancellableOpenAICompatibleModelAdapter(notebook_config),
        capability_catalog=catalog,
        capability_artifact_types=dynamic_artifact_types,
        inspection_executor=execute_inspections,
        proposal_validator=validate_proposal,
        available_inspections=tuple(INSPECTIONS),
        model_timeout_s=notebook_config.timeout_s,
        planning_timeout_s=NOTEBOOK_PLANNING_DEADLINE_S,
    )


def _baseline_planning_evidence(
    service: NotebookService,
    notebook_id: str,
    context: NotebookPlanningContextV1,
    trace: TraceWriter,
) -> DataEvidencePackV1:
    """Compile one bounded source profile before asking the provider to plan."""

    if context.projection_source is None:
        return DataEvidencePackV1(source_id="notebook", records=())
    target_ref = (
        "run:active"
        if context.projection_source
        and context.projection_source.get("kind") == "run"
        else "dataset:active"
    )
    requests = tuple(
        InspectionRequest(inspection_id, target_ref, {})
        for inspection_id in ("profile.v1", "quality.v1", "time_index.v1", "sample.v1")
    )
    return service.compile_evidence_pack(
        notebook_id,
        requests=requests,
        trace=trace,
    )


def _supports_rerun_model_options(declaration: Mapping[str, Any]) -> bool:
    """Whether a registered model pack owns the rerun ``model_options`` envelope.

    ``model.rerun`` is intentionally narrower than Genesis: it may only patch
    a model pack's server-owned options. A capability is eligible only when
    its declaration explicitly publishes that envelope; this keeps the Agent
    catalog aligned with the Draft materialization seam.
    """

    params = declaration.get("params") if isinstance(declaration, Mapping) else None
    return any(
        isinstance(item, Mapping) and item.get("key") == "model_options"
        for item in (params or ())
    )


def _no_eligible_capability_message(
    *,
    proposal_adapter: str,
    source_model_type: str | None,
) -> str:
    """Explain an empty planner catalog without weakening fail-closed admission."""

    if proposal_adapter == "model.rerun" and source_model_type:
        return (
            f"the active run model {source_model_type!r} has no editable "
            "model_options contract, so no rerun capability is eligible; "
            "choose Start new analysis from source data to plan a new typed analysis"
        )
    if proposal_adapter == "model.rerun":
        return (
            "the active run has no server-pinned model capability eligible for rerun; "
            "choose Start new analysis from source data to plan a new typed analysis"
        )
    return "the Notebook has no server-registered executable capability"


def _source_model_type(root: Path, context: NotebookPlanningContextV1) -> str | None:
    source = context.projection_source or {}
    if source.get("kind") != "run" or not context.active_head_run_id:
        return None
    try:
        from ..lineage.run_inputs import read_run_inputs
        from ..repository.run_repository import _resolve_run_root

        inputs = read_run_inputs(_resolve_run_root(str(root), context.active_head_run_id))
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return None
    model_type = (inputs.get("form") or {}).get("model_type")
    return model_type if isinstance(model_type, str) and model_type else None


def _model_options_catalog_metadata(
    root: Path,
    context: NotebookPlanningContextV1,
    capability: str,
) -> dict[str, Any]:
    """Expose only bounded, server-owned option shape facts to the provider."""

    metadata: dict[str, Any] = {}
    vocabulary = build_option_vocabulary(capability)
    if vocabulary:
        metadata["model_options_vocabulary"] = vocabulary
    source = context.projection_source or {}
    if source.get("kind") == "run" and context.active_head_run_id:
        try:
            from ..lineage.run_inputs import read_run_inputs
            from ..repository.run_repository import _resolve_run_root

            inputs = read_run_inputs(_resolve_run_root(str(root), context.active_head_run_id))
            form = inputs.get("form") or {}
            if form.get("model_type") == capability and isinstance(
                form.get("model_options"), Mapping
            ):
                metadata["notebook_model_options_contract"] = {
                    "model_type": capability,
                    "current_payload": dict(form["model_options"]),
                    "patch_rule": "Use exact existing top-level and nested field names; server validates the merged payload.",
                }
        except (FileNotFoundError, OSError, TypeError, ValueError):
            pass
    return metadata


def _request_error(exc: Exception) -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=422,
        code="NOTEBOOK_REQUEST_INVALID",
        message="The Notebook request could not be validated.",
        details={"reason": str(exc)},
    )


@router.post("/notebooks", status_code=201)
def create_notebook_endpoint(
    request: Request, project_root: str, body: NotebookCreateRequest
) -> dict[str, Any]:
    _root, service = _service(request, project_root)
    try:
        return service.create_notebook(
            title=body.title,
            created_by=body.created_by,
            from_run_id=body.from_run_id,
            analysis_contract=body.analysis_contract,
            user_focus=body.user_focus,
            available_capabilities=body.available_capabilities,
        ).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/projection")
def ensure_notebook_projection_endpoint(
    request: Request, project_root: str, body: NotebookProjectionRequest
) -> dict[str, Any]:
    """Ensure a source-bound default projection; this is the new UI boundary."""

    _root, service = _service(request, project_root)
    if (body.from_run_id is None) == (body.dataset is None):
        raise WorkbenchAPIError(
            status_code=422,
            code="NOTEBOOK_PROJECTION_SOURCE_INVALID",
            message="Provide exactly one of from_run_id or dataset.",
        )
    try:
        admitted_native = set(notebook_workflow_capability_ids())
        available_capabilities = tuple(
            str(entry["key"])
            for entry in build_capabilities().get("model_types", [])
            if isinstance(entry, dict) and entry.get("key") in admitted_native
        )
        notebook = service.ensure_default_projection(
            from_run_id=body.from_run_id,
            dataset=(
                {"kind": "dataset", **body.dataset.model_dump()}
                if body.dataset is not None
                else None
            ),
            created_by=body.created_by,
            title=body.title,
            available_capabilities=available_capabilities,
        )
        return {
            **notebook.to_dict(),
            "current_family_head_run_id": (
                notebook.focused_run_id if notebook.projection_source and notebook.projection_source.kind == "run" else None
            ),
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/projection/from-run-dataset")
def ensure_notebook_dataset_projection_from_run_endpoint(
    request: Request,
    project_root: str,
    body: RunDatasetNotebookProjectionRequest,
) -> dict[str, Any]:
    """Start a fresh analysis from a selected run's server-verified upload."""

    _root, service = _service(request, project_root)
    try:
        admitted_native = set(notebook_workflow_capability_ids())
        available_capabilities = tuple(
            str(entry["key"])
            for entry in build_capabilities().get("model_types", [])
            if isinstance(entry, dict) and entry.get("key") in admitted_native
        )
        notebook = service.ensure_dataset_projection_from_run(
            from_run_id=body.from_run_id,
            created_by=body.created_by,
            title=body.title,
            available_capabilities=available_capabilities,
        )
        return {
            **notebook.to_dict(),
            "current_family_head_run_id": None,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks")
def list_notebooks_endpoint(request: Request, project_root: str) -> list[dict[str, Any]]:
    _root, service = _service(request, project_root)
    return [notebook.to_dict() for notebook in service.list_notebooks()]


@router.get("/notebooks/{notebook_id}")
def get_notebook_endpoint(
    request: Request, project_root: str, notebook_id: str
) -> dict[str, Any]:
    _root, service = _service(request, project_root)
    try:
        return service.get_notebook(notebook_id).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc


@router.put("/notebooks/{notebook_id}/focus")
def set_notebook_focus_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    body: NotebookFocusRequest,
) -> dict[str, Any]:
    """Persist the user's intent/mode before the planner proposes options."""

    _root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        if body.goal is None and body.interaction_mode is None:
            raise ValueError("provide a goal or interaction_mode")
        focus = dict(notebook.user_focus)
        if body.goal is not None:
            focus["goal"] = body.goal.strip()
        if body.interaction_mode is not None:
            focus["interaction_mode"] = body.interaction_mode
        return service.set_focus(notebook_id, user_focus=focus).to_dict()
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/context/compile")
def compile_notebook_context_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    focused_run_id: str | None = None,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(
            root,
            service,
            notebook_id,
            focused_run_id=focused_run_id,
            request=request,
        )
        return _context_packet(context)
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


def _planning_attempt_key(
    root: Path,
    notebook_id: str,
    attempt_id: str,
) -> tuple[str, str, str]:
    return (str(root.resolve()), notebook_id, attempt_id)


async def _run_planning_agent(
    agent: NotebookPlanningAgent,
    *,
    context: NotebookPlanningContextV1,
    initial_evidence: DataEvidencePackV1,
):
    plan_async = getattr(agent, "plan_async", None)
    if callable(plan_async):
        return await plan_async(context=context, initial_evidence=initial_evidence)
    return await asyncio.to_thread(
        agent.plan,
        context=context,
        initial_evidence=initial_evidence,
    )


@router.delete("/notebooks/{notebook_id}/planning/{attempt_id}")
async def cancel_planning_attempt_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    attempt_id: str,
) -> dict[str, str]:
    root, service = _service(request, project_root)
    service.get_notebook(notebook_id)
    key = _planning_attempt_key(root, notebook_id, attempt_id)
    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
        task = _ACTIVE_PLANNING_ATTEMPTS.get(key)
    if task is None or task.done():
        return {"attempt_id": attempt_id, "status": "not_active"}
    task.get_loop().call_soon_threadsafe(task.cancel)
    return {"attempt_id": attempt_id, "status": "cancelled"}


@router.post("/notebooks/{notebook_id}/options/propose")
async def propose_options_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    body: ProposeOptionsRequest,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    trace: TraceWriter | None = None
    planning_started = False
    try:
        notebook = service.get_notebook(notebook_id)
        if notebook.user_focus.get("interaction_mode") == "action":
            if body.count not in {None, 1} or len(body.drafts) > 1:
                raise ValueError(
                    "Action mode permits exactly one checked Draft path"
                )
        context, trace = _compile(
            root,
            service,
            notebook_id,
            request=request,
        )
        recommendation_decision = None
        drafts = (
            [_draft(item) for item in body.drafts]
            if body.drafts
            else []
        )
        if not drafts:
            planning_started = True
            attempt_key = None
            current_task = None
            try:
                agent = _planning_agent(root, service, notebook_id, context, trace)
                initial_evidence = _baseline_planning_evidence(
                    service, notebook_id, context, trace
                )
                attempt_key = (
                    _planning_attempt_key(root, notebook_id, body.attempt_id)
                    if body.attempt_id is not None
                    else None
                )
                current_task = asyncio.current_task()
                if attempt_key is not None and current_task is not None:
                    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
                        active = _ACTIVE_PLANNING_ATTEMPTS.get(attempt_key)
                        if active is not None and not active.done():
                            raise WorkbenchAPIError(
                                status_code=409,
                                code="NOTEBOOK_PLANNING_ATTEMPT_ACTIVE",
                                message="Notebook planning attempt is already active",
                            )
                        _ACTIVE_PLANNING_ATTEMPTS[attempt_key] = current_task
                result = await _run_planning_agent(
                    agent,
                    context=context,
                    initial_evidence=initial_evidence,
                )
            except asyncio.CancelledError as exc:
                _record_planning_terminal_error(
                    trace,
                    code="NOTEBOOK_PLANNING_CANCELLED",
                    fatal=False,
                    detail="notebook planning cancelled by user",
                )
                raise WorkbenchAPIError(
                    status_code=409,
                    code="NOTEBOOK_PLANNING_CANCELLED",
                    message="Notebook planning was cancelled",
                ) from exc
            finally:
                if attempt_key is not None and current_task is not None:
                    with _ACTIVE_PLANNING_ATTEMPTS_LOCK:
                        if _ACTIVE_PLANNING_ATTEMPTS.get(attempt_key) is current_task:
                            _ACTIVE_PLANNING_ATTEMPTS.pop(attempt_key, None)
            # Each bounded inspection is persisted separately by the service.
            # Persist the planner's final append-only view as well, because the
            # recommendation decision may cite evidence from more than one
            # inspection round and materialization must be able to replay that
            # exact pack by hash.
            final_evidence = getattr(result, "evidence_pack", None)
            if isinstance(final_evidence, DataEvidencePackV1):
                service.store.append_evidence_pack(notebook_id, final_evidence.to_dict())
            recommendation_evidence = (
                final_evidence
                if isinstance(final_evidence, DataEvidencePackV1)
                else initial_evidence
            )
            # Inspection calls persist Evidence Packs. Recompile the context
            # before pinning the v1.1 revision so evidence_pack_refs belong to
            # the same freshness fingerprint that the Draft gate will observe.
            context, trace = _compile(
                root,
                service,
                notebook_id,
                request=request,
            )
            drafts, recommendation_decision = service.derive_server_recommendation(
                notebook_id,
                context=context,
                drafts=tuple(result.option_drafts),
                batch_id=result.decision.batch_id,
                evidence_pack=recommendation_evidence,
            )
        revisions = service.propose_batch(
            notebook_id,
            context=context,
            drafts=drafts,
            trace=trace,
            batch_id=(recommendation_decision.batch_id if not body.drafts else None),
            recommendation_decision=(recommendation_decision if not body.drafts else None),
            # Provider-generated planning is the only path that may
            # deliberately revalidate existing stable option ids.  Manual
            # draft submission keeps the strict reuse-conflict behavior.
            revalidate_existing=not bool(body.drafts),
        )
        # The Notebook projection is the fold of every persisted option, not
        # only the candidates returned by the latest planning pass.  This is
        # especially important for explicit replans: unchanged/deferred
        # siblings must remain visible while the replanned stable ids expose
        # their new option revisions.
        projected = service.list_options(notebook_id, context=context)
        projected_revisions = [
            replace(
                item.current_revision,
                lifecycle_status=item.lifecycle_status,
                freshness_status=item.freshness_status
                or item.current_revision.freshness_status,
            )
            for item in projected
        ]
        return {
            "context": _context_packet(context),
            "options": [revision.to_dict() for revision in projected_revisions],
            "materializations": _materializations_packet(
                service, notebook_id, projected_revisions
            ),
            "execution_results": _execution_results_packet(
                service, notebook_id, projected_revisions
            ),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise _notebook_error(exc) from exc
    except NotebookNoEligibleCapability as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=409, code=exc.code, message=str(exc)) from exc
    except NotebookPlanningContractError as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=422, code=exc.code, message=str(exc)) from exc
    except NotebookPlanningUnavailable as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code=exc.code,
                fatal=True,
                detail="notebook planning failed",
            )
        raise WorkbenchAPIError(status_code=409, code=exc.code, message=str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        if planning_started:
            _record_planning_terminal_error(
                trace,
                code="NOTEBOOK_REQUEST_INVALID",
                fatal=True,
                detail="notebook planning failed",
            )
        raise _request_error(exc) from exc


@router.get("/notebooks/{notebook_id}/options")
def list_options_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    focused_run_id: str | None = None,
) -> dict[str, Any]:
    """Return the current options against one freshly compiled context.

    This is intentionally a read-time projection. It evaluates freshness for
    display and records the bounded context trace, but it never creates an
    option revision. That lets a browser remount without turning navigation
    into a new agent-generation event.
    """

    root, service = _service(request, project_root)
    try:
        context, trace = _compile(
            root,
            service,
            notebook_id,
            focused_run_id=focused_run_id,
            request=request,
        )
        options = service.list_options(notebook_id, context=context)
        revisions = [
            replace(
                item.current_revision,
                lifecycle_status=item.lifecycle_status,
                freshness_status=item.freshness_status
                or item.current_revision.freshness_status,
            )
            for item in options
        ]
        return {
            "context": _context_packet(context),
            "options": [revision.to_dict() for revision in revisions],
            "materializations": _materializations_packet(service, notebook_id, revisions),
            "execution_results": _execution_results_packet(service, notebook_id, revisions),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.get("/notebooks/{notebook_id}/traces/{trace_id}")
def get_notebook_trace_endpoint(
    request: Request, project_root: str, notebook_id: str, trace_id: str
) -> dict[str, Any]:
    """Replay the typed trace for a notebook without exposing other scopes."""

    root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        events = TraceWriter.replay(root, trace_id)
        if events and any(
            event.get("scope", {}).get("notebook_id") != notebook_id
            or event.get("scope", {}).get("run_family_id") != notebook.run_family_id
            for event in events
        ):
            raise WorkbenchAPIError(
                status_code=404,
                code="NOTEBOOK_TRACE_SCOPE_MISMATCH",
                message="The requested trace does not belong to this notebook.",
            )
        return {"trace_id": trace_id, "events": events}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/revalidate")
def revalidate_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: RevalidateOptionRequest,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        revision = service.revalidate_option(
            notebook_id,
            option_id,
            context=context,
            draft=_draft(body),
            trace=trace,
        )
        return {
            "context": _context_packet(context),
            "option": revision.to_dict(),
            "trace_id": trace.trace_id,
        }
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/confirm")
def confirm_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ConfirmOptionRequest,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        current = service.store.read_option(notebook_id, option_id).current_revision
        proposal = service.store.read_option(notebook_id, option_id).current_stored_revision.proposal
        if proposal.operation_id == "operation.multi_step":
            result = service.confirm_and_execute_workflow(
                notebook_id,
                option_id,
                option_revision=body.option_revision,
                proposal_id=body.proposal_id,
                proposal_revision=body.proposal_revision,
                context=context,
                trace=trace,
            )
            return {**result, "trace_id": trace.trace_id}
        if current.materializable:
            if (body.option_revision, body.proposal_id, body.proposal_revision) != (
                current.option_revision,
                current.typed_proposal_id,
                current.typed_proposal_revision,
            ):
                raise OptionRevisionStale(
                    "materialization request does not match the current option revision",
                    option_id=option_id,
                    requested_revision=body.option_revision,
                    current_revision=current.option_revision,
                    reason="proposal_pin_mismatch",
                )
            result = service.materialize_option(
                notebook_id,
                option_id,
                context=context,
                trace=trace,
            )
            return {**result.to_dict(), "trace_id": trace.trace_id}
        execution = service.confirm(
            notebook_id,
            option_id,
            option_revision=body.option_revision,
            proposal_id=body.proposal_id,
            proposal_revision=body.proposal_revision,
            context=context,
            trace=trace,
        )
        return {"execution": execution.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute")
def confirm_and_execute_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ConfirmOptionRequest,
) -> dict[str, Any]:
    """Explicitly dispatch one low-risk bound option through server CF4.

    The request carries only the current option/proposal pins.  Authorization,
    Run intent, dispatch reservation, and all result facts are server-owned.
    """

    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        current = service.store.read_option(notebook_id, option_id).current_revision
        if (body.option_revision, body.proposal_id, body.proposal_revision) != (
            current.option_revision,
            current.typed_proposal_id,
            current.typed_proposal_revision,
        ):
            raise OptionRevisionStale(
                "execution request does not match the current option revision",
                option_id=option_id,
                requested_revision=body.option_revision,
                current_revision=current.option_revision,
                reason="proposal_pin_mismatch",
            )
        dispatch = service.confirm_and_execute(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )
        return {"dispatch": dispatch.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/materialize")
def materialize_option_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        context, trace = _compile(root, service, notebook_id)
        result = service.materialize_option(
            notebook_id,
            option_id,
            context=context,
            trace=trace,
        )
        return {**result.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/authorize-execution")
def authorize_option_execution_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: AuthorizeOptionExecutionRequest,
) -> dict[str, Any]:
    """Legacy control-plane seam for unbound compatibility records.

    A capability-bound V1.2 option cannot use this client-envelope route. Its
    authorization is constructed by the server only inside
    ``confirm-and-execute``.
    """

    root, service = _service(request, project_root)
    try:
        current = service.store.read_option(notebook_id, option_id).current_revision
        if getattr(current, "capability_resolution_binding_ref", None) is not None:
            raise OptionRevisionStale(
                "capability execution authorization is server-owned; use explicit confirm-and-execute",
                option_id=option_id,
                option_revision=current.option_revision,
                reason="authorization_server_owned",
            )
        context, trace = _compile(root, service, notebook_id)
        authorization = OptionExecutionAuthorization.from_dict(body.authorization)
        persisted = service.authorize_option_execution(
            notebook_id,
            option_id,
            context=context,
            authorization=authorization,
        )
        return {"authorization": persisted.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except ExecutionAuthorizationError as exc:
        raise _request_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/decision")
def record_decision_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: DecisionRequest,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        trace = _notebook_trace(root, service, notebook.notebook_id)
        option = service.record_decision(
            notebook_id,
            option_id,
            decision=body.decision,
            actor=body.actor,
            edited_fields=body.edited_fields,
            note_ref=body.note_ref,
            trace=trace,
        )
        # The service needs the full OptionView to fold lifecycle state, but
        # this public route is consumed by the frontend revision parser. Do
        # not leak the internal view (revisions, execution history, and
        # materialization details) as if it were a NotebookOptionRevision.
        return {**option.current_revision.to_dict(), "lifecycle_status": option.lifecycle_status}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


@router.post("/notebooks/{notebook_id}/options/{option_id}/execute")
def complete_option_execution_endpoint(
    request: Request,
    project_root: str,
    notebook_id: str,
    option_id: str,
    body: ExecuteOptionRequest,
) -> dict[str, Any]:
    root, service = _service(request, project_root)
    try:
        notebook = service.get_notebook(notebook_id)
        trace = _notebook_trace(root, service, notebook.notebook_id)
        outcome = service.complete_execution(
            notebook_id,
            option_id,
            execution_status=body.execution_status,
            run_id=body.run_id,
            produced_artifacts=body.produced_artifacts,
            error_code=body.error_code,
            trace=trace,
        )
        return {**outcome.to_dict(), "trace_id": trace.trace_id}
    except NotebookOptionError as exc:
        raise _notebook_error(exc) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise _request_error(exc) from exc


__all__ = ["router"]
