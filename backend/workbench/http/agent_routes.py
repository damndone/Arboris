"""HTTP seam for the project-scoped Workbench Agent surface."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ..agent.analysis_loop_driver import forward_analysis_intent
from ..agent.audit_export import (
    build_agent_audit,
    render_agent_audit_html,
    render_agent_audit_markdown,
)
from ..agent.context_tools import (
    AnalysisLoopContextError,
    inspect_analysis_loop_context,
    parse_analysis_loop_packet_payloads,
)
from ..agent.chains import (
    ChainHeadConflict,
    ChainHeadUnavailable,
    ChainStore,
    ensure_chain_root,
)
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..analysis_loop.compare import ComparePacket
from ..analysis_loop.lifecycle import (
    AnalysisLoopProposalError,
    confirm_analysis_loop_proposal,
    create_analysis_loop_proposal,
)
from ..analysis_loop.plan import PlanBindingError, PlanDiff, PlanValidationError
from ..analysis_loop.recovery import RECOVERY_ACTIONS
from ..analysis_loop.resolver import (
    AnalysisLoopSourceResolutionError,
    resolve_analysis_loop_inputs,
    resolve_analysis_loop_run,
)
from ..analysis_loop.storage import (
    ComparePacketStore,
    PlanDiffStore,
    ValidationPacketStore,
)
from ..analysis_loop.validation import ValidationPacket
from ..agent.core import AgentCore
from ..agent.events import AgentEventStream
from ..agent.model import OpenAICompatibleModelAdapter
from ..agent.navigation import AgentNavigationProjector, AgentNavigationRef
from ..agent.operations import (
    OperationRecordStore,
    OperationRegistry,
    OperationValidationError,
)
from ..agent.execution import OperationClaimConflict
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.proposals import ProposalConfirmationError, ProposalStaleError, ProposalStore
from ..agent.session import EntryRef, JsonlSessionRepository
from ..agent.tools import ToolRegistry
from ..api_errors import WorkbenchAPIError
from ..control_plane import control_plane_capability
from ..llm.config import load_llm_config

router = APIRouter()

MAX_CONTEXT_CHARS = 24_000
MAX_QUESTION_CHARS = 4_000
# One step = one provider call. A read-only inspection sweep is typically
# question → 5 inspect tools → summary, so 4 blocked legitimate turns in the
# live DeepSeek smoke; 8 leaves headroom without unbounding the loop.
# Raised to 10 after a live turn on an ARMA-GARCH node inspected, proposed on
# step 9, and then reported max_steps_exceeded even though the proposal had
# been created — the user saw a failed turn with a valid proposal sitting
# behind it. The protocol now also makes a successful proposal terminal, so
# this is headroom rather than permission to sprawl.
DEFAULT_MAX_STEPS = 10
DEFAULT_TIMEOUT_S = 120.0

# A live turn is process-local by design: the local Workbench server owns the
# in-flight provider stream and is the only component able to abort it safely.
# Durable session state remains in JsonlSessionRepository; this map contains no
# prompt text, provider secret, or replay state and is always cleared in the
# turn route's finally block.
_ACTIVE_TURNS: dict[tuple[str, str], AgentCore] = {}


def _active_turn_key(project_root: Path, session_id: str) -> tuple[str, str]:
    return (str(project_root.resolve()), session_id)

CHAIN_AGENT_PROTOCOL = """Workbench Chain Agent workflow protocol (agent/v1):
- You are the Workbench Chain Agent, running on the workbench's configured language-model provider. When asked what you are or which model powers you, identify yourself that way and name the configured provider and model given in your identity context. Never invent a product, brand, or vendor name (there is no product called "Vivistats"), and never deflect a question about your identity or model to external or "official" documentation.
- Read-only inspection tools are the evidence source for this turn.
- When the user asks for an OLS conventional-to-clustered Analysis Loop proposal, call propose_analysis_loop with the exact source_run_id, source_node_ref, active_head_run_id, cluster_variable, and (when supplied) result_id. This typed tool resolves the source facts and creates the PlanDiff binding.
- When the user asks for a multi-step statistical workflow over the selected Raw data node (for example: grouped descriptive statistics, missing-value checks, a correlation matrix, percentile-derived group comparisons, scatter plots, and one or more regressions), use operation.multi_step@v1 as a SINGLE workflow proposal covering the whole request.
- Compose that workflow yourself in changes.steps. Each step is {step_id, operation_id, spec, depends_on}. Field names are exact and unknown fields are rejected. The per-step vocabulary below is the registry's own, and inspect_operation_contract on operation.multi_step returns the same thing.
{step_vocabulary}
- A composed workflow runs over the dataset, not over one graph node. Once you have the data schema and the operation contract you have everything a plan needs: inspecting further nodes adds nothing and spends the budget that writing the plan requires. Do not walk the graph node by node.
- Use the columns and grouping values the DATA actually has, taken from inspection — never invented and never copied from an example. depends_on must name the step that produced the evidence a later step relies on; a percentile threshold must depend on the summarize_detail step that produced it.
- A requested post-estimation quantity requires its own actual typed step: use model.joint_f_test for a joint test and model.quadratic_stationary_point for a quadratic stationary point. Each must depend on the model.genesis step that declared its branch, and a report that includes either result must list that producing step in required_steps. A report section description does not execute a result and must never substitute for the producing step.
- The server owns statistical semantics: percentile method, missing-value policy, covariance validation, diagnostics and artifacts. Choose which steps to run over which columns; do not restate those fixed semantics in changes.
- The plan's length, ordering and column choices belong to the request being answered. There is no fixed number of steps.
- For other registered mutations, you must call propose_operation with a complete structured payload; a JSON or Markdown proposal in ordinary text is not a submitted proposal.
- propose_operation creates a reviewable pending proposal only; it does not execute a Workbench mutation. Never claim that a run, graph, or data change was executed from this tool.
- A successful propose_operation ends your turn: reply with a short summary of what you proposed and call no further tools. Continuing past it spends the step budget and can end the turn in an error even though the proposal was created.
- Inspect only what the request needs. Calling every inspect tool wastes steps; tools for other model families return nothing useful about this node.
- propose_analysis_loop also creates a reviewable pending proposal only; it never confirms or executes the rerun.
- Use the exact operation_id and operation_version returned by inspect_operation_contract. For model.rerun, target contains run_id, node_ref, node_hash, and forest_node_key; map the inspection field op_node_id to node_ref, and do not put active_head_run_id in target. For graph.fork, the backend binds target.source_session_entry_id to the current Chain leaf; do not invent an Agent entry id. In preconditions, include exactly context_version, context_fingerprint, active_head_run_id, and owner_resolution.
- graph.fork creates a durable fork, child Chain, and child Agent session after confirmation. It does not submit a child statistical run and does not automatically continue with model.rerun.
- Include changes as the requested field-level change (prefer {"old": ..., "new": ...}), plus evidence_refs, expected_effect, and risks. For model.rerun, model_options must be a direct one-level object patch (for example {"random_slope": false}); never wrap it as an old/new field diff.
- An option_vocabulary's prohibited_claims bind what you may SAY, not only what you may propose. They hold even when the user explicitly asks for the forbidden wording: say plainly that the pack does not make that claim, and give the quantity its correct name. Restating a forbidden equivalence "just to explain it" is making the claim.
- When inspect_operation_contract returns an option_vocabulary, that vocabulary is the model pack's own field list: build model_options only from its declared paths, closed value sets, and limits, and satisfy its cross_field_rules. A patch may name only the keys it changes; nested sections are merged key-wise. A patch outside the vocabulary is rejected when the proposal is created, and its rejection code tells you what to fix.
- Never copy a displayed editable-schema value or model narrative as the source fact when a typed Analysis Loop tool returns canonical source facts, PlanDiff, and expected invariants; explain only those backend-owned facts.
- If evidence or a required field is missing, inspect more or explain what is missing instead of inventing it.
- After a confirmed operation completes, its status is not numerical evidence. First use inspect_completed_operations for the current node, then inspect_operation_artifact only with an emitted artifact_id; cite that artifact id in the answer. A confirmed Notebook composed workflow has its own receipt lifecycle: when the question concerns sibling models or post-estimation results from that workflow, first use inspect_notebook_workflow_results. It discloses only committed workflows that contain the current run; use its returned branch run_ids with inspect_project_model_coefficients, and cite its returned post_estimation_evidence directly. That post_estimation_evidence is already the final bounded public result for the receipt: never call inspect_operation_artifact for those ids, because that separate tool intentionally admits only Agent operation records. Do not conclude that no composed workflow exists merely because inspect_completed_operations is empty. inspect_artifact_preview also exposes bounded public_result_evidence for already-persisted UI statistical artifacts that explicitly descend from the selected data node, and numeric figure_evidence for the selected model run. Cite the artifact id and state when figure evidence is run-scoped. If no public result view is available, say that the result cannot yet be verified. Never request raw rows, a filesystem path, or infer a figure from its title alone.
- When interpreting a quadratic stationary point, use only the server-reported observed_min, observed_max, and stationary_point_within_observed_range fields. Never infer whether it is in range from a column name, label, or a typical domain.
"""

MAIN_AGENT_PROTOCOL = """Workbench Global Agent workflow protocol (agent/v1):
- You are the Workbench Global Agent, running on the workbench's configured language-model provider. When asked what you are or which model powers you, identify yourself that way and name the configured provider and model given in your identity context. Never invent a product, brand, or vendor name (there is no product called "Vivistats"), and never deflect a question about your identity or model to external or "official" documentation.
- You are the project-level advisory Agent. Use the bounded project overview and durable summaries supplied in the context packet.
- You may summarize families, runs, heads, chains, and visible risks, and suggest questions or evidence-gathering steps.
- Never invent raw-data facts, model metrics, run results, chain state, or unsupported causal claims.
- You have no mutation or execution tools in this scope. Never claim that a proposal, run, graph mutation, or file change was created or executed.
- inspect_project_model_coefficients is a bounded, read-only evidence tool. When the user asks for an exact coefficient, standard error, p value, confidence interval, R-squared, adjusted R-squared, outcome, fixed-effect identifier, residual/model degrees of freedom, covariance details, or a side-by-side comparison from one or more visible runs, call it with the run ids and at most four exact persisted term names per call from the overview; split a longer list across calls. Report only its returned values and cite its run_id/model_id evidence_ref; do not calculate a new interval, read a report file, or infer a missing coefficient or specification field.
- inspect_project_dataset_schema is a bounded, read-only evidence tool. Before stating that a column is absent or suggesting a typed model composition for a visible run, call it with that run id when the bounded overview does not already establish the relevant column names. It returns names, dtypes, missingness, and unique counts only; never infer category labels, raw values, or a formula from it.
- inspect_project_notebook_workflow_results is the project-level receipt reader for a committed Notebook workflow. When a question concerns sibling models or post-estimation tests from such a workflow, make one receipt lookup with up to sixteen visible candidate run ids from the overview. From a returned completed receipt, use branch_runs to select model evidence and cite its returned post_estimation_evidence directly; do not claim a workflow exists without this receipt evidence.
- For a completed workflow's requested coefficients, use its returned branch run ids and call inspect_project_model_coefficients once with all requested branch ids and at most four requested terms. Then answer from that result and the receipt. Do not inspect a dataset schema merely to restate a declared model specification, and do not retrieve unrelated coefficients just to repeat the complete predictor list already returned with model evidence.
- inspect_project_numeric_summary is the bounded source for explicitly requested persisted means and standard deviations. Use it for a reported sample mean; it never returns raw rows or correlations.
- inspect_project_model_figure_evidence is the bounded source for an explicitly named persisted model figure. Give it only visible run ids and figure artifact ids; it returns aggregate numeric evidence, never pixels, paths, or observation rows. For a residual-versus-predictor question, use its bins before describing variance patterns; if it returns unavailable, say the figure cannot yet be numerically verified.
- inspect_project_linear_interaction_effects is the only source for an OLS interaction slope evaluated at a persisted moderator mean. It returns the marginal effect on the recorded outcome scale, but deliberately does not return an interval or standard error. Do not calculate this number yourself or apply this tool to a non-OLS model.
- inspect_project_coefficient_transforms performs only one of two server-side numeric transforms: scale_0_01 or expm1_percent. It does not establish that a percentage interpretation is appropriate. Before applying its value in prose, cite model evidence that establishes the relevant recorded term and outcome scale; do not do the arithmetic yourself.
- A coefficient is a change per one recorded unit of its term unless the visible model evidence documents another scale. Never convert it to a percentage-point, currency, or other unit from a variable name alone.
- Do not use overlap or non-overlap of two separately estimated confidence intervals as a test that their coefficients differ. Do not label a comparison Simpson's paradox, claim an omitted-variable direction, state a correlation not in evidence, or rank one specification as more credible without a separately reported diagnostic or contrast. You may explain that conditioning on additional declared variables changes the reported conditional association, and state the limit.
- When nonrobust and robust standard errors lead to different significance labels, report that the inference changes under the two covariance assumptions. Do not say the nonrobust significance is false, spurious, or caused by heteroskedasticity without a separate diagnostic that establishes that stronger claim.
- A difference in standard-error size alone does not establish serial correlation, heteroskedasticity, clustering validity, or a preferred covariance estimator. Do not describe that difference as evidence, a signal, an indication, a hint, or a suggestion of any residual process. State only the returned difference and any separately reported diagnostic.
- Interpret regression coefficients as conditional association, not a causal effect, unless the persisted model evidence explicitly supplies a causal identification claim. Do not infer a variable's real-world meaning from its name, abbreviation, or data type; use only the user's stated definition or persisted metadata.
- Schema-level unique counts do not establish whether a covariate changes within entities. To say a named variable is absorbed by entity fixed effects, cite direct persisted within-entity evidence or state the result conditionally on the user-supplied premise that it is time-invariant; do not promote a name or a low unique-count to that premise.
- Preserve the exact sign, digits, and interval endpoints returned by the evidence tool. Never "correct" a number from prose or a prior transcript; if earlier text conflicts with evidence, call the tool again and treat the new result as authoritative.
- Before sending a numeric answer, mechanically copy those returned fields rather than recalculate or silently retype them. Check that the displayed estimate, standard error, p value, and interval endpoints are mutually consistent with the returned record; if your prose rendering of a confidence interval contradicts the returned p value or interval endpoints, re-read the same evidence tool and report only its latest fields.
- If the bounded overview is insufficient to identify the relevant run or exact term, say what evidence is missing and ask the user to select a chain or node for a narrower evidence packet.
"""


def _step_vocabulary_lines() -> str:
    """Render the composable-step vocabulary from its single source.

    The protocol used to restate these field names by hand, so every new step
    operation had to be remembered in two places and a stale line would teach
    the Agent a name the validator rejects.
    """

    from ..agent.workflow_contracts import workflow_step_vocabulary

    vocabulary = workflow_step_vocabulary()
    lines: list[str] = []
    for operation_id, entry in vocabulary["step_operations"].items():
        required = ", ".join(entry["required"]) or "none"
        lines.append(f"  - {operation_id} -> {entry['summary']} Required: {required}.")
        for name, description in entry["fields"].items():
            lines.append(f"      {name}: {description}")
    grid = ", ".join(str(item) for item in vocabulary["reported_percentiles"])
    lines.append(
        f"  - Reported percentile grid: {grid}. Write 25 for the first quartile, never 0.25."
    )
    lines.append(f"  - {vocabulary['ordering']}")
    return "\n".join(lines)


def _chain_agent_protocol(registry: OperationRegistry) -> str:
    """Add the registry's current executable operation ids to the protocol."""

    operation_ids = registry.natural_language_operation_ids(
        scope_requirements=("chain", "active_head")
    )
    return (
        CHAIN_AGENT_PROTOCOL.replace("{step_vocabulary}", _step_vocabulary_lines())
        + "- The currently registered executable operation ids are: "
        + ", ".join(operation_ids)
        + ". Do not propose an id outside this registry.\n"
        + "- For an unsupported request, explain the boundary explicitly; never translate it into a nearby operation.\n"
    )


class AgentSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["main", "chain"] = "chain"
    chain_id: str | None = None
    run_id: str | None = None
    context_packet: dict[str, Any] = Field(default_factory=dict)


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class AgentProposalConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    fingerprint: str = Field(min_length=1)
    active_head_run_id: str = Field(min_length=1)
    confirmed_payload_hash: str | None = Field(default=None, min_length=1)


class AgentProposalDeclineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1_000)


class AgentProposalRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(gt=0)
    changes: dict[str, Any]
    expected_effect: list[str] | None = None
    risks: list[str] | None = None


class AgentForkProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    chain_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    source_session_entry_id: str | None = Field(default=None, min_length=1, max_length=200)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(
        default="Fork from verified graph context",
        min_length=1,
        max_length=1_000,
    )


class AnalysisLoopContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep this a string so the domain seam, rather than FastAPI's generic
    # validation error, owns the stable machine-readable scope code.
    scope: str = Field(min_length=1, max_length=32)
    source_context: dict[str, Any] = Field(default_factory=dict)
    plan_diff: dict[str, Any] | None = None
    validation_packet: dict[str, Any] | None = None
    compare_packet: dict[str, Any] | None = None


class AnalysisLoopIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # This is deliberately untrusted input. The route only classifies and
    # returns it; it never turns it into a proposal or operation record.
    intent: dict[str, Any] = Field(default_factory=dict)


class AnalysisLoopProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(min_length=1, max_length=200)
    source_node_ref: str = Field(min_length=1, max_length=300)
    active_head_run_id: str = Field(min_length=1, max_length=200)
    cluster_variable: str = Field(min_length=1, max_length=200)
    result_id: str | None = Field(default=None, min_length=1, max_length=300)


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


def _stores(root: Path) -> tuple[JsonlSessionRepository, AgentEventStream]:
    # Design §10.1: all Agent-managed metadata (sessions, events, and later
    # chains/forks/operation-records) lives under the project-local
    # `workbench/` namespace, kept out of the runs/graph scanners' inputs.
    storage_root = root / "workbench"
    return JsonlSessionRepository(storage_root), AgentEventStream(storage_root)


def _context_active_head(packet: dict[str, Any]) -> str | None:
    direct = packet.get("active_head_run_id")
    if isinstance(direct, str) and direct:
        return direct
    ownership = packet.get("ownership")
    if isinstance(ownership, dict):
        nested = ownership.get("active_head_run_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _ensure_chain_scope(
    root: Path,
    *,
    chain_id: str,
    active_head_run_id: str,
    agent_session_id: str,
) -> dict[str, Any]:
    try:
        return ensure_chain_root(
            root / "workbench",
            runs_root=root / "runs",
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=agent_session_id,
        )
    except ChainHeadConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_SCOPE_CONFLICT",
            message="The Chain session is outside the durable active-head scope.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _authoritative_active_head(
    root: Path,
    *,
    chain_id: str,
    requested_active_head_run_id: str | None,
) -> str:
    try:
        return ChainStore(root / "workbench", create=False).resolve_active_head(
            chain_id,
            requested_active_head_run_id=requested_active_head_run_id,
        )
    except KeyError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_NOT_MANAGED",
            message="The Chain has no durable active-head record.",
            details={"chain_id": chain_id},
        ) from exc
    except (ChainHeadConflict, ChainHeadUnavailable) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The durable Chain active head changed before this operation.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _context_serialized(packet: dict[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized) > MAX_CONTEXT_CHARS:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_TOO_LARGE",
            message="Agent context exceeds the bounded context budget.",
            details={"max_chars": MAX_CONTEXT_CHARS, "actual_chars": len(serialized)},
        )
    fingerprint = str(packet.get("context_fingerprint") or "")
    if not fingerprint:
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return serialized, fingerprint


def _ensure_current_global_protocol(
    repository: JsonlSessionRepository,
    session_id: str,
) -> None:
    """Append a protocol revision once when a durable Main session is older."""

    for entry in repository.get_branch(session_id):
        if entry.entry_type != "custom_message":
            continue
        payload = entry.payload
        if (
            payload.get("name") == "workbench_global_agent_protocol"
            and payload.get("content") == MAIN_AGENT_PROTOCOL
        ):
            return
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_protocol",
            "audience": "model",
            "name": "workbench_global_agent_protocol",
            "content": MAIN_AGENT_PROTOCOL,
            "metadata": {"protocol_version": "agent/v1"},
        },
    )


def _ensure_main_session(repository: JsonlSessionRepository, root: Path) -> str:
    """Durable per-project Main session anchor for the HTTP orchestrator.

    The read-only inspection slice never dispatches Main→Chain commands, but
    the orchestrator identity must be a real session so future command entries
    have a home instead of a made-up id.
    """
    main_session_id = "agent_main"
    try:
        repository.get_metadata(main_session_id)
    except (KeyError, ValueError):
        repository.create_session(
            main_session_id, chain_id=f"project:{root}", role="main"
        )
    return main_session_id


def _get_session(
    root: Path,
    session_id: str,
) -> tuple[JsonlSessionRepository, AgentEventStream, dict[str, Any]]:
    repository, events = _stores(root)
    try:
        metadata = repository.get_metadata(session_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_SESSION_NOT_FOUND",
            message="Agent session was not found in this project.",
            details={"session_id": session_id},
        ) from exc
    return repository, events, metadata


def _messages(repository: JsonlSessionRepository, session_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    projector = AgentNavigationProjector(repository.root.parent)
    for entry in repository.get_branch(session_id):
        if entry.entry_type != "message":
            continue
        role = entry.payload.get("role")
        content = entry.payload.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        message = {
            "entry_id": entry.entry_id,
            "role": role,
            "content": content,
            # Tool entries carry the tool id in `name`; the panel projects
            # it as the typed status label instead of a generic "tool".
            "name": entry.payload.get("name"),
            "stop_reason": entry.payload.get("stop_reason"),
            "error": entry.payload.get("error"),
        }
        try:
            message["navigation"] = [
                link.to_dict()
                for link in projector.entry(session_id, entry.entry_id).links
            ]
        except (KeyError, ValueError):
            # A legacy/corrupt entry must not make the whole session unreadable.
            message["navigation"] = []
        result.append(message)
    return result


def _context_fingerprint(repository: JsonlSessionRepository, session_id: str) -> str | None:
    for entry in repository.get_branch(session_id):
        if entry.entry_type != "custom_message":
            continue
        metadata = entry.payload.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("context_fingerprint"), str):
            return metadata["context_fingerprint"]
    return None


def _public_session(
    repository: JsonlSessionRepository,
    session_id: str,
    metadata: dict[str, Any],
    config,
) -> dict[str, Any]:
    proposal_store = ProposalStore(repository.root)
    return {
        "session_id": session_id,
        "role": metadata.get("role"),
        "chain_id": metadata.get("chain_id"),
        "status": metadata.get("status"),
        "context_fingerprint": _context_fingerprint(repository, session_id),
        "model": config.model or None,
        "provider_id": config.provider_id or None,
        "context_window_tokens": config.context_window_tokens,
        "messages": _messages(repository, session_id),
        "proposals": _public_proposals(proposal_store, session_id),
    }


def _public_proposals(store: ProposalStore, session_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for revision in store.latest_revisions_for_session(session_id):
        proposal = revision.to_dict()
        proposal["status"] = store.latest_status(revision.proposal_id)
        confirmation = store.latest_confirmation(revision.proposal_id)
        if confirmation is not None:
            proposal["confirmation"] = confirmation.to_dict()
        decision = store.latest_decision(revision.proposal_id)
        if decision is not None:
            proposal["decision"] = decision.to_dict()
        proposals.append(proposal)
    return proposals


def _proposal_for_session(
    store: ProposalStore,
    *,
    proposal_id: str,
    session_id: str,
    chain_id: str | None,
):
    try:
        proposal = store.latest_revision(proposal_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_PROPOSAL_NOT_FOUND",
            message="Agent proposal was not found in this project.",
            details={"proposal_id": proposal_id},
        ) from exc
    if proposal.session_id != session_id or (
        chain_id is not None and proposal.chain_id != chain_id
    ):
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_PROPOSAL_NOT_FOUND",
            message="Agent proposal was not found in this session.",
            details={"proposal_id": proposal_id, "session_id": session_id},
        )
    return proposal


def _public_proposal(store: ProposalStore, proposal_id: str) -> dict[str, Any]:
    revision = store.latest_revision(proposal_id)
    proposal = revision.to_dict()
    proposal["status"] = store.latest_status(proposal_id)
    confirmation = store.latest_confirmation(proposal_id)
    if confirmation is not None:
        proposal["confirmation"] = confirmation.to_dict()
    decision = store.latest_decision(proposal_id)
    if decision is not None:
        proposal["decision"] = decision.to_dict()
    return proposal


def _current_data_columns_cast_fingerprint(root: Path, proposal) -> str:
    """Re-derive a data cast's *preview* fingerprint before confirmation.

    For model.rerun/graph.fork the freshness identity is the node-operation
    context (`nocv1:…`). A data cast's identity is its preview over the real
    data, so re-previewing here is the same check, expressed in this
    operation's own vocabulary — and it is the same fingerprint the manual UI
    path confirms against.
    """

    from ..data_operations import (
        DataCastItem,
        DataColumnCastValidationError,
        DataColumnsCastSpecV1,
        preview_data_columns_cast,
    )

    target = proposal.target
    try:
        spec = DataColumnsCastSpecV1(
            source_run_id=str(target["run_id"]),
            source_node_id=str(target["node_ref"]),
            source_artifact_id=str(target["artifact_id"]),
            casts=tuple(
                DataCastItem(str(item["column"]), str(item["target_dtype"]))
                for item in target["casts"]
            ),
            output_format=str(target.get("output_format", "csv")),
        )
        preview = preview_data_columns_cast(root, spec)
    except (DataColumnCastValidationError, KeyError, OSError, TypeError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target or source data changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    if preview.status != "ready":
        raise WorkbenchAPIError(
            status_code=422,
            code="DATA_OPERATION_BLOCKED",
            message="The cast preview has blocking conversion failures.",
            details={
                "proposal_id": proposal.proposal_id,
                "blocked_columns": [
                    item.column for item in preview.items if item.status != "ready"
                ],
            },
        )
    return preview.fingerprint


def _current_proposal_context_fingerprint(
    root: Path,
    proposal,
    *,
    active_head_run_id: str,
) -> str:
    """Re-derive the current node context before creating a confirmation record."""

    active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=active_head_run_id,
    )
    if proposal.operation_id == "data.columns.cast":
        return _current_data_columns_cast_fingerprint(root, proposal)
    if proposal.operation_id not in {"model.rerun", "graph.fork", "operation.multi_step"}:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_OPERATION_UNSUPPORTED",
            message="This Agent endpoint does not confirm this operation.",
            details={"operation_id": proposal.operation_id},
        )
    target = proposal.target
    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"confirm:{proposal.proposal_id}",
                owner_run_id=str(target["run_id"]),
                op_node_id=str(target["node_ref"]),
                active_head_run_id=active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target or active head changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": str(exc)},
        ) from exc
    if target.get("node_hash") is not None and snapshot.get("node_hash") != target.get("node_hash"):
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal target changed before confirmation.",
            details={"proposal_id": proposal.proposal_id, "reason": "node_hash"},
        )
    fingerprint = snapshot.get("context_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The current proposal context could not be verified.",
            details={"proposal_id": proposal.proposal_id},
        )
    return fingerprint


@router.post("/agent/sessions")
def create_agent_session(
    project_root: str,
    body: AgentSessionCreateRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    serialized, fingerprint = _context_serialized(body.context_packet)
    repository, events = _stores(root)
    session_id = f"agent_{body.role}_{uuid4().hex}"
    chain_id = body.chain_id or f"project:{root}"
    active_head_run_id = body.run_id or _context_active_head(body.context_packet)
    if body.role == "chain" and active_head_run_id:
        try:
            _authoritative_active_head(
                root,
                chain_id=chain_id,
                requested_active_head_run_id=active_head_run_id,
            )
        except WorkbenchAPIError as exc:
            if exc.code != "AGENT_CHAIN_NOT_MANAGED":
                raise
    repository.create_session(session_id, chain_id=chain_id, role=body.role)
    if body.role == "chain" and active_head_run_id:
        _ensure_chain_scope(
            root,
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=session_id,
        )
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_context",
            "audience": "model",
            "name": "workbench_context",
            "content": (
                "Workbench read-only context. Do not invent facts or execute actions.\n"
                + serialized
            ),
            "metadata": {
                "context_fingerprint": fingerprint,
                "run_id": body.run_id,
            },
        },
    )
    identity_config = load_llm_config()
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_identity",
            "audience": "model",
            "name": "workbench_agent_identity",
            "content": (
                "Agent identity (authoritative): you are the Workbench "
                + ("Chain" if body.role == "chain" else "Global")
                + " Agent. You run on the configured provider "
                + f"'{identity_config.provider_id or 'unknown'}' using model "
                + f"'{identity_config.model or 'unknown'}'. Answer identity and "
                + "\"what model are you\" questions with exactly this; do not invent a "
                + "product, brand, or vendor name and do not deflect to external "
                + "documentation."
            ),
            "metadata": {"protocol_version": "agent/v1"},
        },
    )
    if body.role == "chain":
        registry = OperationRegistry()
        repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_protocol",
                "audience": "model",
                "name": "workbench_agent_protocol",
                "content": _chain_agent_protocol(registry),
                "metadata": {"protocol_version": "agent/v1"},
            },
        )
    else:
        _ensure_current_global_protocol(repository, session_id)
    events.emit(
        session_id,
        "session_created",
        {
            "role": body.role,
            "chain_id": chain_id,
            "run_id": body.run_id,
            "context_fingerprint": fingerprint,
        },
    )
    return _public_session(
        repository,
        session_id,
        repository.get_metadata(session_id),
        load_llm_config(),
    )


@router.get("/agent/sessions/{session_id}")
def get_agent_session(session_id: str, project_root: str) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, _events, metadata = _get_session(root, session_id)
    return _public_session(repository, session_id, metadata, load_llm_config())


@router.get("/agent/sessions/{session_id}/audit", response_model=None)
def get_agent_audit_export(
    session_id: str,
    project_root: str,
    format: Literal["json", "markdown", "html"] = Query("json"),
) -> dict[str, Any] | Response:
    root = _project_root(project_root)
    _get_session(root, session_id)
    audit = build_agent_audit(root, session_id)
    markdown = render_agent_audit_markdown(audit)
    if format == "markdown":
        return Response(markdown, media_type="text/markdown")
    html = render_agent_audit_html(audit)
    if format == "html":
        return Response(html, media_type="text/html")
    return {"audit": audit, "markdown": markdown, "html": html}


@router.get("/agent/sessions/{session_id}/proposals")
def get_agent_proposals(session_id: str, project_root: str) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, _events, _metadata = _get_session(root, session_id)
    return {"proposals": _public_proposals(ProposalStore(repository.root), session_id)}


@router.get("/agent/sessions/{session_id}/projection")
def get_agent_session_projection(
    session_id: str,
    project_root: str,
) -> dict[str, Any]:
    root = _project_root(project_root)
    _repository, _events, _metadata = _get_session(root, session_id)
    try:
        projection = AgentNavigationProjector(root).session(session_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent navigation projection was not found.",
            details={"session_id": session_id},
        ) from exc
    return {"projection": projection.to_dict()}


@router.get("/agent/navigation/graph")
def get_agent_graph_navigation(
    project_root: str,
    run_id: str = Query(min_length=1),
    node_ref: str | None = Query(default=None),
    forest_node_key: str | None = Query(default=None),
) -> dict[str, Any]:
    root = _project_root(project_root)
    projection = AgentNavigationProjector(root).graph(
        run_id=run_id,
        node_ref=node_ref,
        forest_node_key=forest_node_key,
    )
    if not projection.subject.available:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Graph navigation projection was not found.",
            details={"run_id": run_id, "node_ref": node_ref},
        )
    return {"projection": projection.to_dict()}


@router.get("/agent/activity")
def get_agent_activity(project_root: str) -> dict[str, Any]:
    """Return the durable, read-only operation projection for AI Activity."""

    root = _project_root(project_root)
    projection = AgentNavigationProjector(root)
    hierarchy = projection.activity_hierarchy()
    return {
        "activities": [item.to_dict() for item in projection.activity()],
        "events": [item.to_dict() for item in projection.activity_events()],
        "hierarchy": hierarchy.to_dict() if hierarchy is not None else None,
    }


@router.get("/agent/capabilities")
def get_agent_capabilities(
    project_root: str,
    scope: str | None = None,
) -> dict[str, Any]:
    """Return registry-owned operation capabilities without creating storage."""

    root = _project_root(project_root)
    capabilities = OperationRegistry().capabilities()
    if scope is not None:
        capabilities = [item for item in capabilities if item["scope"] == scope]
    return {
        "project_root": str(root),
        "scope": scope,
        **control_plane_capability(),
        "capabilities": capabilities,
        "boundary": OperationRegistry().boundary(),
    }


def _analysis_loop_run_facts(resolved) -> dict[str, Any]:
    """Expose bounded persisted OLS facts for the read-only detail surface."""

    result = resolved.result if isinstance(resolved.result, dict) else {}
    sample = result.get("analysis_sample")
    fingerprints = {
        key: result.get(key)
        for key in (
            "dataset_snapshot_fingerprint",
            "analysis_sample_fingerprint",
            "point_estimation_fingerprint",
            "coefficient_schema_fingerprint",
            "inference_config_fingerprint",
        )
        if result.get(key) is not None
    }
    return {
        "run_id": resolved.run_id,
        "status": resolved.manifest.get("status"),
        "model": result.get("model"),
        "contract_version": result.get("contract_version"),
        "covariance": result.get("covariance"),
        "covariance_product": (
            "conventional"
            if result.get("covariance") == "unadjusted"
            else result.get("covariance")
        ),
        "covariance_wire": result.get("covariance_wire"),
        "entity_col": result.get("entity_col"),
        "stable_result_ids": list(result.get("stable_result_ids") or []),
        "primary_estimand": result.get("primary_estimand"),
        "analysis_sample": {
            "row_count": sample.get("row_count"),
            "row_order": list(sample.get("row_order") or []),
        } if isinstance(sample, dict) else None,
        "fingerprints": fingerprints,
    }


def _analysis_loop_packet_bundle(
    *,
    validation_packet,
    compare_packets: list[ComparePacket],
    plan_packets,
) -> dict[str, Any]:
    compare = next(
        (
            packet
            for packet in compare_packets
            if packet.child_run_id == validation_packet.child_run_id
            and packet.source_run_id == validation_packet.source_run_id
        ),
        None,
    )
    plan = next(
        (
            packet.plan_diff
            for packet in plan_packets
            if packet.plan_diff.plan_hash == validation_packet.plan_hash
        ),
        None,
    )
    return {
        "child_run_id": validation_packet.child_run_id,
        "source_run_id": validation_packet.source_run_id,
        "plan_diff": plan.to_dict() if plan is not None else None,
        "validation_packet": validation_packet.to_dict(),
        "compare_packet": compare.to_dict() if compare is not None else None,
    }


@router.get("/analysis-loop/packets/{run_id}")
def get_analysis_loop_packets(
    run_id: str,
    project_root: str,
) -> dict[str, Any]:
    """Read persisted Analysis Loop facts for one graph run.

    This endpoint is deliberately read-only.  It never builds a packet or
    infers a comparison.  Terminal packets are selected by their durable
    child/source IDs; the UI receives the backend's exact packet payloads.
    """

    root = _project_root(project_root)
    try:
        resolved = resolve_analysis_loop_run(root, run_id=run_id, require_result=False)
    except AnalysisLoopSourceResolutionError as exc:
        status_code = 404 if exc.code == "SOURCE_RUN_NOT_FOUND" else 422
        raise WorkbenchAPIError(
            status_code=status_code,
            code=("ANALYSIS_LOOP_RUN_NOT_FOUND" if status_code == 404 else exc.code),
            message=str(exc),
            details={"run_id": run_id},
        ) from exc

    validation_store = ValidationPacketStore(root, create=False)
    compare_store = ComparePacketStore(root, create=False)
    plan_store = PlanDiffStore(root, create=False)
    validations = validation_store.list_terminal_packets()
    compares = compare_store.list_terminal_packets()
    plans = plan_store.list_terminal_packets()

    current = [packet for packet in validations if packet.child_run_id == run_id]
    current.sort(key=lambda packet: packet.logical_key)
    current_bundle = (
        _analysis_loop_packet_bundle(
            validation_packet=current[0],
            compare_packets=compares,
            plan_packets=plans,
        )
        if current
        else None
    )
    child_bundles = [
        _analysis_loop_packet_bundle(
            validation_packet=packet,
            compare_packets=compares,
            plan_packets=plans,
        )
        for packet in sorted(
            (item for item in validations if item.source_run_id == run_id),
            key=lambda item: item.logical_key,
        )
    ]

    source_run = None
    source_run_id = (
        current[0].source_run_id
        if current
        else str(
            resolved.run_inputs.get("rerun_of")
            or resolved.manifest.get("source_run_id")
            or run_id
        )
    )
    try:
        source_resolved = resolve_analysis_loop_run(
            root,
            run_id=source_run_id,
            require_result=False,
        )
        source_run = _analysis_loop_run_facts(source_resolved)
    except AnalysisLoopSourceResolutionError:
        # The packet remains inspectable even if a historical source has been
        # removed or became unreadable; do not hide the durable child evidence.
        source_run = {"run_id": source_run_id, "status": "unavailable"}

    lifecycle_status = str(resolved.manifest.get("status") or "")
    status = (
        current[0].status
        if current
        else "pending"
        if lifecycle_status in {"queued", "running", "pending"}
        else "absent"
    )
    return {
        "status": status,
        "run": _analysis_loop_run_facts(resolved),
        "source_run": source_run,
        "packet": current_bundle,
        "children": child_bundles,
    }


def _analysis_loop_packets_from_request(
    body: AnalysisLoopContextRequest,
) -> tuple[PlanDiff | None, ValidationPacket | None, ComparePacket | None]:
    """Parse packet payloads without reading or mutating project state."""

    try:
        return parse_analysis_loop_packet_payloads(
            plan_diff=body.plan_diff,
            validation_packet=body.validation_packet,
            compare_packet=body.compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message="The analysis-loop packet payload is invalid.",
            details={"reason": str(exc)},
        ) from exc


@router.post("/agent/sessions/{session_id}/analysis-loop/context")
def inspect_agent_analysis_loop_context(
    session_id: str,
    project_root: str,
    body: AnalysisLoopContextRequest,
) -> dict[str, Any]:
    """Return one scope of typed analysis-loop context, read-only.

    The HTTP seam intentionally accepts already-structured packet payloads so
    fixture clients and future backend resolvers share one strict domain
    boundary. It does not calculate packets, read arbitrary files, create a
    proposal, or execute an operation.
    """

    root = _project_root(project_root)
    _get_session(root, session_id)
    plan_diff, validation_packet, compare_packet = _analysis_loop_packets_from_request(body)
    try:
        context = inspect_analysis_loop_context(
            source_context=body.source_context,
            scope=body.scope,
            plan_diff=plan_diff,
            validation_packet=validation_packet,
            compare_packet=compare_packet,
        )
    except AnalysisLoopContextError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"scope": body.scope},
        ) from exc
    return {
        "status": context["status"],
        "context": context,
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/intents")
def submit_agent_analysis_loop_intent(
    session_id: str,
    project_root: str,
    body: AnalysisLoopIntentRequest,
) -> dict[str, Any]:
    """Classify one untrusted intent without creating a proposal or effect."""

    root = _project_root(project_root)
    _get_session(root, session_id)
    decision = forward_analysis_intent(body.intent)
    return {
        "status": "accepted" if decision.accepted else "rejected",
        "decision": decision.to_dict(),
        "registered_actions": [action.to_dict() for action in RECOVERY_ACTIONS.values()],
    }


@router.post("/agent/sessions/{session_id}/analysis-loop/proposals")
def create_agent_analysis_loop_proposal(
    session_id: str,
    project_root: str,
    body: AnalysisLoopProposalRequest,
) -> dict[str, Any]:
    """Resolve persisted OLS facts and create one confirmation-gated proposal."""

    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    if metadata.get("role") != "chain":
        raise WorkbenchAPIError(
            status_code=409,
            code="ANALYSIS_LOOP_SCOPE_INVALID",
            message="An analysis-loop proposal must belong to a Chain Agent session.",
            details={"session_id": session_id},
        )
    chain_id = str(metadata.get("chain_id") or "")
    authoritative_active_head_run_id = _authoritative_active_head(
        root,
        chain_id=chain_id,
        requested_active_head_run_id=body.active_head_run_id,
    )
    provider = NodeOperationContextProvider(root)
    context_started = perf_counter()
    try:
        snapshot = provider.inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"analysis-loop-proposal:{body.source_run_id}:{body.source_node_ref}",
                owner_run_id=body.source_run_id,
                op_node_id=body.source_node_ref,
                active_head_run_id=authoritative_active_head_run_id,
            )
        )
        context_ms = round((perf_counter() - context_started) * 1000, 3)
        resolved = resolve_analysis_loop_inputs(
            root,
            run_id=body.source_run_id,
            cluster_variable=body.cluster_variable,
        )
    except AnalysisLoopSourceResolutionError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details={"run_id": body.source_run_id},
        ) from exc
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected OLS node or active head could not be verified.",
            details={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
            },
        ) from exc
    if resolved.source.run_id != body.source_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="SOURCE_IDENTITY_MISMATCH",
            message="The resolved source does not match the requested run.",
            details={"run_id": body.source_run_id},
        )
    if snapshot.get("active_head_run_id") != authoritative_active_head_run_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The selected source is outside the current active head.",
            details={"run_id": body.source_run_id},
        )

    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=provider,
    )
    # Proposal creation needs a registered Chain identity but does not invoke
    # an LLM. The adapter is constructed locally; this read/plan path makes no
    # provider call.
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(load_llm_config()),
        session_id=session_id,
    )
    orchestrator.register_chain(chain_id, session_id, agent)
    plan_started = perf_counter()
    try:
        proposal = create_analysis_loop_proposal(
            orchestrator=orchestrator,
            chain_id=chain_id,
            plan_store=PlanDiffStore(repository.root, create=False),
            source=resolved.source,
            intent={
                "action_id": "ols.use_clustered_covariance_v1",
                "patch": {
                    "covariance": "clustered",
                    "cluster_variable": body.cluster_variable,
                },
            },
            cluster_values=resolved.cluster_values,
            model_row_ids=resolved.model_row_ids,
            requested_result_id=body.result_id,
            source_context_fingerprint=str(snapshot["context_fingerprint"]),
            source_identity={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "node_hash": str(snapshot["node_hash"]),
                "forest_node_key": str(snapshot["forest_node_key"]),
            },
            active_head_run_id=authoritative_active_head_run_id,
            owner_resolution=str(snapshot["owner_resolution"]),
        )
        plan_ms = round((perf_counter() - plan_started) * 1000, 3)
    except AnalysisLoopProposalError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except PlanValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        ) from exc
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="ANALYSIS_LOOP_PROPOSAL_INVALID",
            message="The canonical analysis-loop proposal was rejected by the operation registry.",
            details={"reason": str(exc)},
        ) from exc
    plan_store = PlanDiffStore(repository.root, create=False)
    logical_key = proposal.preconditions.get("plan_logical_key")
    packet = plan_store.get_terminal_packet(str(logical_key)) if logical_key else None
    if packet is None:
        raise WorkbenchAPIError(
            status_code=500,
            code="ANALYSIS_LOOP_PLAN_MISSING",
            message="The analysis-loop proposal has no persisted PlanDiff.",
            details={"proposal_id": proposal.proposal_id},
        )
    return {
        "session_id": session_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "plan_diff": packet.plan_diff.to_dict(),
        "registered_action": RECOVERY_ACTIONS["ols.use_clustered_covariance_v1"].to_dict(),
        "timings_ms": {
            "node_operation_context_ms": context_ms,
            "plan_diff_ms": plan_ms,
        },
        "status": "pending",
    }


def _ensure_fork_source_session(
    root: Path,
    body: AgentForkProposalRequest,
    snapshot: dict[str, Any],
) -> tuple[JsonlSessionRepository, AgentEventStream, dict[str, Any], str]:
    """Resolve a chain session and a reachable source entry for a fork proposal."""

    if body.session_id:
        repository, events, metadata = _get_session(root, body.session_id)
        if metadata.get("role") != "chain":
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_SCOPE_INVALID",
                message="A graph fork proposal must belong to a Chain Agent session.",
                details={"session_id": body.session_id},
            )
        if body.chain_id and metadata.get("chain_id") != body.chain_id:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_SCOPE_INVALID",
                message="The Agent session is outside the requested Chain scope.",
                details={"session_id": body.session_id, "chain_id": body.chain_id},
            )
    else:
        repository, events = _stores(root)
        session_id = f"agent_chain_fork_{uuid4().hex}"
        chain_id = body.chain_id or f"chain:{body.source_run_id}"
        try:
            _authoritative_active_head(
                root,
                chain_id=chain_id,
                requested_active_head_run_id=body.active_head_run_id,
            )
        except WorkbenchAPIError as exc:
            if exc.code != "AGENT_CHAIN_NOT_MANAGED":
                raise
        metadata = repository.create_session(session_id, chain_id=chain_id, role="chain")
        _ensure_chain_scope(
            root,
            chain_id=chain_id,
            active_head_run_id=body.active_head_run_id,
            agent_session_id=session_id,
        )
        context = {
            "packet_version": "agent/fork-context/v1",
            "context_fingerprint": snapshot.get("context_fingerprint"),
            "source": {
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "active_head_run_id": body.active_head_run_id,
            },
        }
        serialized, fingerprint = _context_serialized(context)
        context_entry = repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "agent_context",
                "audience": "model",
                "name": "workbench_context",
                "content": (
                    "Workbench verified fork context. Do not invent graph facts.\n"
                    + serialized
                ),
                "metadata": {
                    "context_fingerprint": fingerprint,
                    "run_id": body.source_run_id,
                },
            },
        )
        events.emit(
            session_id,
            "session_created",
            {
                "role": "chain",
                "chain_id": chain_id,
                "run_id": body.source_run_id,
                "context_fingerprint": fingerprint,
            },
        )
        metadata = repository.get_metadata(session_id)
        if body.source_session_entry_id and body.source_session_entry_id != context_entry.entry_id:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_FORK_ENTRY_NOT_FOUND",
                message="The requested source Agent entry is not present in the new session.",
                details={"entry_id": body.source_session_entry_id},
            )

    source_entry_id = body.source_session_entry_id or metadata.get("leaf_entry_id")
    if not isinstance(source_entry_id, str) or not source_entry_id:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The Chain Agent session has no durable source entry.",
            details={"session_id": metadata.get("session_id")},
        )
    try:
        repository.get_entry(EntryRef(str(metadata["session_id"]), source_entry_id))
        branch_ids = {
            entry.entry_id for entry in repository.get_branch(str(metadata["session_id"]))
        }
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The source Agent entry is not reachable from the current Chain head.",
            details={"entry_id": source_entry_id},
        ) from exc
    if source_entry_id not in branch_ids:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_FORK_ENTRY_NOT_FOUND",
            message="The source Agent entry is not reachable from the current Chain head.",
            details={"entry_id": source_entry_id},
        )
    return repository, events, metadata, source_entry_id


@router.post("/agent/fork-proposals")
def create_agent_fork_proposal(
    project_root: str,
    body: AgentForkProposalRequest,
) -> dict[str, Any]:
    """Create a confirmation-gated graph.fork proposal from verified context."""

    root = _project_root(project_root)
    authoritative_active_head_run_id = body.active_head_run_id
    if body.session_id:
        _repository, _events, metadata = _get_session(root, body.session_id)
        authoritative_active_head_run_id = _authoritative_active_head(
            root,
            chain_id=str(metadata.get("chain_id")),
            requested_active_head_run_id=body.active_head_run_id,
        )
    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id=f"fork-proposal:{body.source_run_id}:{body.source_node_ref}",
                owner_run_id=body.source_run_id,
                op_node_id=body.source_node_ref,
                active_head_run_id=authoritative_active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The graph node or active head could not be verified.",
            details={"run_id": body.source_run_id, "node_ref": body.source_node_ref},
        ) from exc

    repository, events, metadata, source_entry_id = _ensure_fork_source_session(
        root,
        body,
        snapshot,
    )
    session_id = str(metadata["session_id"])
    chain_id = str(metadata["chain_id"])
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(load_llm_config()),
        session_id=session_id,
    )
    orchestrator.register_chain(chain_id, session_id, agent)
    try:
        proposal = orchestrator.create_proposal(
            chain_id=chain_id,
            operation_id="graph.fork",
            target={
                "run_id": body.source_run_id,
                "node_ref": body.source_node_ref,
                "node_hash": snapshot["node_hash"],
                "forest_node_key": snapshot["forest_node_key"],
                "source_session_entry_id": source_entry_id,
            },
            preconditions={
                "context_version": snapshot["context_version"],
                "context_fingerprint": snapshot["context_fingerprint"],
                "active_head_run_id": snapshot["active_head_run_id"],
                "owner_resolution": snapshot["owner_resolution"],
            },
            changes={"reason": body.reason},
            evidence_refs=[
                f"graph:{body.source_run_id}:{body.source_node_ref}",
                f"agent_entry:{session_id}:{source_entry_id}",
            ],
            expected_effect=["create a durable child Chain and Agent session"],
            risks=["no child statistical run is submitted by graph.fork"],
        )
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_INVALID",
            message="The graph fork proposal is not valid for this context.",
            details={"reason": str(exc)},
        ) from exc
    navigation = AgentNavigationRef(
        kind="proposal",
        id=proposal.proposal_id,
        label=f"Proposal {proposal.proposal_id}",
        relation="audit",
        available=True,
        href={
            "view": "agent",
            "session_id": session_id,
            "proposal_id": proposal.proposal_id,
        },
    )
    return {
        "session_id": session_id,
        "source_session_entry_id": source_entry_id,
        "proposal": _public_proposal(orchestrator.proposal_store, proposal.proposal_id),
        "navigation": navigation.to_dict(),
        "status": "pending",
    }


@router.get("/agent/sessions/{session_id}/operations/{record_id}")
def get_agent_operation_projection(
    session_id: str,
    record_id: str,
    project_root: str,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, _events, metadata = _get_session(root, session_id)
    store = OperationRecordStore(repository.root)
    try:
        record = store.get(record_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent operation projection was not found.",
            details={"record_id": record_id},
        ) from exc
    if record.agent_session_id != session_id or record.chain_id != metadata.get("chain_id"):
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_NAVIGATION_NOT_FOUND",
            message="Agent operation projection was not found in this scope.",
            details={"record_id": record_id, "session_id": session_id},
        )
    projection = AgentNavigationProjector(root).operation(record_id)
    return {"operation": record.to_dict(), "projection": projection.to_dict()}


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/decline")
def decline_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalDeclineRequest | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    try:
        decision = orchestrator.decline_proposal(
            proposal_id,
            actor_type="user",
            reason=body.reason if body is not None else None,
        )
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal is no longer declinable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": _public_proposal(store, proposal_id),
        "status": decision.status,
    }


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/revise")
def revise_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalRevisionRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    try:
        revised = orchestrator.revise_proposal(
            proposal_id,
            base_revision=body.base_revision,
            changes=body.changes,
            expected_effect=body.expected_effect,
            risks=body.risks,
        )
    except OperationValidationError as exc:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_PROPOSAL_INVALID",
            message="The revised proposal changes are not valid for this operation.",
            details={"proposal_id": proposal_id, "reason": str(exc)},
        ) from exc
    except ProposalConfirmationError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision is no longer current or editable.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": _public_proposal(store, revised.proposal_id),
        "status": "pending",
    }


@router.post("/agent/sessions/{session_id}/proposals/{proposal_id}/confirm")
async def confirm_agent_proposal(
    session_id: str,
    proposal_id: str,
    project_root: str,
    body: AgentProposalConfirmRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = ProposalStore(repository.root)
    proposal = _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
    )
    authoritative_active_head_run_id = _authoritative_active_head(
        root,
        chain_id=str(proposal.chain_id),
        requested_active_head_run_id=body.active_head_run_id,
    )
    current_context_fingerprint = _current_proposal_context_fingerprint(
        root,
        proposal,
        active_head_run_id=authoritative_active_head_run_id,
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    is_analysis_loop = isinstance(proposal.preconditions.get("analysis_loop"), dict)
    try:
        if is_analysis_loop:
            cluster_variable = proposal.changes.get("entity_col")
            if type(cluster_variable) is not str or not cluster_variable:
                raise PlanBindingError(
                    "analysis-loop proposal has no exact cluster variable",
                    code="STALE_PLAN",
                )
            resolved = resolve_analysis_loop_inputs(
                root,
                run_id=str(proposal.target["run_id"]),
                cluster_variable=cluster_variable,
            )
            confirmed_payload_hash = (
                body.confirmed_payload_hash
                or proposal.preconditions.get("confirmed_payload_hash")
            )
            if type(confirmed_payload_hash) is not str or not confirmed_payload_hash:
                raise PlanBindingError(
                    "analysis-loop confirmation has no canonical payload hash",
                    code="CONFIRMED_PAYLOAD_MISMATCH",
                )
            record = confirm_analysis_loop_proposal(
                orchestrator=orchestrator,
                plan_store=PlanDiffStore(repository.root, create=False),
                proposal_id=proposal_id,
                current_source=resolved.source,
                current_source_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=authoritative_active_head_run_id,
                revision=body.revision,
                fingerprint=body.fingerprint,
                confirmed_payload_hash=confirmed_payload_hash,
            )
        else:
            record = orchestrator.confirm_proposal(
                proposal_id,
                revision=body.revision,
                fingerprint=body.fingerprint,
                actor_type="user",
                current_context_fingerprint=current_context_fingerprint,
                current_active_head_run_id=authoritative_active_head_run_id,
            )
    except PlanBindingError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code=exc.code,
            message=str(exc),
            details=getattr(exc, "details", {"proposal_id": proposal_id}),
        ) from exc
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal is stale and must be regenerated.",
            details={"proposal_id": proposal_id},
        ) from exc
    except (ProposalConfirmationError, KeyError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision or fingerprint is no longer confirmable.",
            details={"proposal_id": proposal_id},
        ) from exc
    # Design §8.2: the user confirmation IS the execution gate. The registry
    # selects the request-independent operation handler; no model text
    # participates in execution.
    try:
        record = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=root,
            current_context_fingerprint=current_context_fingerprint,
            current_active_head_run_id=authoritative_active_head_run_id,
        )
    except ProposalStaleError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The proposal became stale before execution.",
            details={"proposal_id": proposal_id},
        ) from exc
    except OperationClaimConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_OPERATION_CONFLICT",
            message="Another confirmed operation is already executing against this Chain head.",
            details={"proposal_id": proposal_id},
        ) from exc
    return {
        "proposal": _public_proposal(store, proposal_id),
        "operation": record.to_dict(),
        "status": record.status,
    }


@router.post("/agent/sessions/{session_id}/operations/{record_id}/reconcile")
async def reconcile_agent_operation(
    session_id: str,
    record_id: str,
    project_root: str,
) -> dict[str, Any]:
    """Idempotently reconcile one confirmed operation against its child run.

    Non-terminal children leave the record `running` unchanged; a terminal
    child produces the deterministic diff/verification, the completed (or
    failed) record, and the child chain/fork activation. Safe to poll.
    """
    root = _project_root(project_root)
    repository, events, _metadata = _get_session(root, session_id)
    store = OperationRecordStore(repository.root)
    try:
        record = store.get(record_id)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_OPERATION_NOT_FOUND",
            message="Agent operation record was not found in this project.",
            details={"record_id": record_id},
        ) from exc
    if record.agent_session_id != session_id:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_OPERATION_NOT_FOUND",
            message="Agent operation record was not found in this session.",
            details={"record_id": record_id, "session_id": session_id},
        )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id=_ensure_main_session(repository, root),
        context_provider=NodeOperationContextProvider(root),
    )
    if record.operation_id != "graph.fork":
        record = await orchestrator.reconcile_confirmed_proposal(
            record_id, project_root=root
        )
    return {"operation": record.to_dict(), "status": record.status}


@router.post("/agent/sessions/{session_id}/turns")
async def run_agent_turn(
    session_id: str,
    project_root: str,
    body: AgentTurnRequest,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    turn_key = _active_turn_key(root, session_id)
    if turn_key in _ACTIVE_TURNS:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_TURN_IN_PROGRESS",
            message="This Agent session already has a running turn.",
            details={"session_id": session_id},
        )
    config = load_llm_config()
    if not config.is_configured():
        raise WorkbenchAPIError(
            status_code=503,
            code="LLM_NOT_CONFIGURED",
            # A broken explicit store must say so — "configure a provider" is
            # the wrong advice when the operator already did and the pinned
            # file is missing.
            message=config.configuration_error_message(),
        )
    agent = AgentCore(
        repository,
        events,
        OpenAICompatibleModelAdapter(config),
        session_id=session_id,
    )
    tool_context: dict[str, Any] | None = None
    if metadata.get("role") == "main":
        _ensure_current_global_protocol(repository, session_id)
    if metadata.get("role") == "chain":
        # Handoff §7 slice: the ROUTE registers the chain-scoped read-only
        # tools through the existing orchestrator boundary — the model never
        # discovers Workbench capabilities on its own, and a plain inspection
        # turn performs zero Workbench mutation. Proposals stay allowlisted to
        # registry-enabled operations and remain confirmation-gated audit records.
        operation_registry = OperationRegistry()
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id=_ensure_main_session(repository, root),
            operation_registry=operation_registry,
            context_provider=NodeOperationContextProvider(root),
        )
        orchestrator.register_chain(str(metadata.get("chain_id")), session_id, agent)
        tool_context = {
            "allowed_operations": operation_registry.natural_language_operation_ids(
                scope_requirements=("chain", "active_head")
            )
        }
    else:
        provider = NodeOperationContextProvider(root)
        registry = ToolRegistry()
        for definition in provider.global_tool_definitions(session_id=session_id):
            registry.register(definition)
        agent.attach_tools(registry.descriptors(), registry)
    _ACTIVE_TURNS[turn_key] = agent
    try:
        await agent.prompt(
            body.question.strip(),
            budget={"max_steps": DEFAULT_MAX_STEPS, "timeout_s": DEFAULT_TIMEOUT_S},
            tool_context=tool_context,
        )
    finally:
        if _ACTIVE_TURNS.get(turn_key) is agent:
            _ACTIVE_TURNS.pop(turn_key, None)
    messages = _messages(repository, session_id)
    assistant = next(
        (message for message in reversed(messages) if message["role"] == "assistant"),
        None,
    )
    if assistant is None:
        raise WorkbenchAPIError(
            status_code=502,
            code="AGENT_NO_ASSISTANT_MESSAGE",
            message="Agent completed without producing an assistant message.",
        )
    return {
        "session": _public_session(repository, session_id, metadata, config),
        "assistant": assistant,
        "status": repository.get_metadata(session_id).get("status"),
    }


@router.post("/agent/sessions/{session_id}/abort")
async def abort_agent_turn(
    session_id: str,
    project_root: str,
) -> dict[str, Any]:
    """Request cancellation of the one active provider/tool turn for a session."""

    root = _project_root(project_root)
    _get_session(root, session_id)
    agent = _ACTIVE_TURNS.get(_active_turn_key(root, session_id))
    if agent is None:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_TURN_NOT_ACTIVE",
            message="This Agent session has no active turn to stop.",
            details={"session_id": session_id},
        )
    await agent.abort()
    return {"status": "cancelling", "session_id": session_id}


@router.get("/agent/sessions/{session_id}/events")
def get_agent_events(
    session_id: str,
    project_root: str,
    after_seq: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    root = _project_root(project_root)
    _repository, events, _metadata = _get_session(root, session_id)
    return {
        "events": [
            event.to_dict()
            for event in events.replay(session_id, after_seq=after_seq)
        ]
    }
