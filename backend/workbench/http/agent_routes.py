"""HTTP seam for the project-scoped Workbench Agent surface."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from threading import RLock
from typing import Any, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, Query, Request, Response
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
from ..agent.orchestrator import (
    CutoverCompilerError,
    ServerConfirmationReceiptV1,
    WorkbenchOrchestrator,
    validate_server_proposal_revision,
)
from ..agent.proposals import (
    ProposalConfirmationError,
    ProposalRevision,
    ProposalStaleError,
    ProposalStore,
    ProposalStoreCapabilityError,
    ProposalStoreCapabilityV1,
)
from ..agent.session import EntryRef, JsonlSessionRepository
from ..agent.tools import ToolRegistry
from ..api_errors import WorkbenchAPIError
from ..control_plane import control_plane_capability
from ..llm.config import load_llm_config
from ..lineage.node_index import NODE_INDEX_FILENAME

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
    # The dict is not the prompt: only what is rendered here reaches the Agent.
    # A step's input source is published as prose for the same reason the field
    # names above are -- a capability the Agent cannot name is a capability it
    # never uses.
    source = vocabulary["source"]
    shape = ", ".join(f"{name} ({text})" for name, text in source["shape"].items())
    lines.append(f"  - {source['purpose']} Its fields are: {shape}")
    lines.append(f"      source.output must be one of: {', '.join(source['outputs'])}.")
    lines.append(
        "      Only these steps produce a dataset a source may name: "
        + ", ".join(source["produced_by"])
        + "."
    )
    lines.append(
        "      Only these steps may declare a source: "
        + ", ".join(source["declarable_by"])
        + "."
    )
    lines.append(f"      {source['semantics']}")
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


def _canonicalize_chain_context_packet(
    root: Path,
    *,
    chain_id: str,
    packet: dict[str, Any],
    active_head_run_id: str,
) -> dict[str, Any]:
    """Bind a selected-node preview to the durable Chain context.

    The browser packet is a bounded preview used to open the Agent surface. It
    is not an authorization source: the Chain head, node hash, owner
    resolution, and context fingerprint must come from the same backend
    snapshot that the typed inspection tools use. A historical selected node
    remains a valid source hint when it is not the current Chain head.
    """

    target = packet.get("operation_target")
    ownership = packet.get("ownership")
    if target is None and ownership is None:
        inferred = _infer_minimal_chain_target(root, packet, active_head_run_id)
        if inferred is None:
            return packet
        target = {}
        ownership = {}
        owner_run_id, op_node_id = inferred
    elif not isinstance(target, dict) or not isinstance(ownership, dict):
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="A selected Chain node context must include operation target and ownership.",
            details={"chain_id": chain_id},
        )
    else:
        owner_run_id = target.get("owner_run_id") or ownership.get("owner_run_id")
        op_node_id = target.get("op_node_id")
    if not isinstance(owner_run_id, str) or not owner_run_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain context has no source owner run.",
            details={"chain_id": chain_id},
        )
    if not isinstance(op_node_id, str) or not op_node_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain context has no source operation node.",
            details={"chain_id": chain_id, "owner_run_id": owner_run_id},
        )

    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id="agent-session-context",
                owner_run_id=owner_run_id,
                op_node_id=op_node_id,
                active_head_run_id=active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node context could not be rebuilt from project facts.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc

    canonical = dict(packet)
    canonical_target = dict(target)
    canonical_target.update(
        {
            "owner_run_id": snapshot["owner_run_id"],
            "op_node_id": snapshot["op_node_id"],
            "node_hash": snapshot["node_hash"],
        }
    )
    canonical["operation_target"] = canonical_target
    canonical_ownership = dict(ownership)
    canonical_ownership.update(
        {
            "active_head_run_id": snapshot["active_head_run_id"],
            "owner_run_id": snapshot["owner_run_id"],
            "owner_resolution": snapshot["owner_resolution"],
        }
    )
    canonical["ownership"] = canonical_ownership
    selection = packet.get("selection")
    if isinstance(selection, dict):
        canonical_selection = dict(selection)
        canonical_selection["node_hash"] = snapshot["node_hash"]
        canonical["selection"] = canonical_selection
    diagnostics = packet.get("context_diagnostics")
    canonical_diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
    raw_warnings = canonical_diagnostics.get("warnings")
    warnings = [item for item in raw_warnings if isinstance(item, str)] if isinstance(raw_warnings, list) else []
    client_head = ownership.get("active_head_run_id")
    if client_head != snapshot["active_head_run_id"]:
        warnings.append(
            "The client preview active head was replaced by the durable Chain active head; "
            "the selected source owner was retained."
        )
    canonical_diagnostics["warnings"] = warnings
    canonical["context_diagnostics"] = canonical_diagnostics
    canonical["context_fingerprint"] = snapshot["context_fingerprint"]
    return canonical


def _infer_minimal_chain_target(
    root: Path,
    packet: dict[str, Any],
    active_head_run_id: str,
) -> tuple[str, str] | None:
    """Recover a node target from the stable forest-key encoding when needed.

    Older Workbench surfaces can send only ``selection.forest_node_key``. The
    key is a presentation hint until its hash and node ref are matched against
    the server-owned node indexes. An active-head match wins; otherwise a
    single verified owner is required. Ambiguous or unverifiable selections
    remain blocked rather than becoming guessed Chain context.
    """

    selection = packet.get("selection")
    if not isinstance(selection, dict):
        return None
    forest_node_key = selection.get("forest_node_key")
    if not isinstance(forest_node_key, str) or "::" not in forest_node_key:
        return None
    node_hash, op_node_id = forest_node_key.split("::", 1)
    if not node_hash or not op_node_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain forest key is not a complete node identity.",
            details={"forest_node_key": forest_node_key},
        )
    declared_node_hash = selection.get("node_hash")
    if declared_node_hash is not None and declared_node_hash != node_hash:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node hash disagrees with its forest key.",
            details={"forest_node_key": forest_node_key},
        )

    runs_root = root / "runs"
    candidates: list[str] = []
    try:
        run_roots = sorted(path for path in runs_root.iterdir() if path.is_dir())
    except OSError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The project run index could not be read for Chain context.",
            details={"reason": str(exc)},
        ) from exc
    for run_root in run_roots:
        index_path = run_root / NODE_INDEX_FILENAME
        if not index_path.is_file():
            continue
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_CONTEXT_STALE",
                message="A project node index is unreadable; Chain context is not safe to infer.",
                details={"run_id": run_root.name, "reason": str(exc)},
            ) from exc
        entry = index.get(op_node_id) if isinstance(index, dict) else None
        if isinstance(entry, dict) and entry.get("node_hash") == node_hash:
            candidates.append(run_root.name)

    if active_head_run_id in candidates:
        return active_head_run_id, op_node_id
    if len(candidates) == 1:
        return candidates[0], op_node_id
    if not candidates:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node is not present in a verified project node index.",
            details={"forest_node_key": forest_node_key},
        )
    raise WorkbenchAPIError(
        status_code=409,
        code="AGENT_CONTEXT_AMBIGUOUS",
        message="The selected Chain node has multiple verified owners outside the active head.",
        details={"forest_node_key": forest_node_key, "candidate_run_ids": candidates},
    )


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


_ROUTE_PROPOSAL_STORE_OWNER = object()
_ROUTE_PROPOSAL_STORE_OWNER_LOCK = RLock()
_ROUTE_PROPOSAL_REFERENCE_ADMISSIONS: dict[int, tuple[object, ProposalStoreCapabilityV1, ProposalRevision]] = {}


def _server_proposal_store(root: Path) -> ProposalStoreCapabilityV1:
    """Issue the route-owned persisted ProposalStore view for one project."""

    return ProposalStore._issue_server_capability(
        root,
        owner_token=_ROUTE_PROPOSAL_STORE_OWNER,
    )


@dataclass(frozen=True, init=False)
class ServerOwnedLegacyProposalReferenceV1:
    """An opaque route reference issued only after a persisted reread."""

    store: ProposalStoreCapabilityV1
    revision: ProposalRevision

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("legacy proposal references are issued by the route boundary")

    @classmethod
    def _issue(
        cls,
        store: ProposalStoreCapabilityV1,
        revision: ProposalRevision,
    ) -> "ServerOwnedLegacyProposalReferenceV1":
        if type(store) is not ProposalStoreCapabilityV1 or type(revision) is not ProposalRevision:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route requires a server-owned persisted proposal reference.",
            )
        try:
            store._require_admitted(_ROUTE_PROPOSAL_STORE_OWNER)
        except ProposalStoreCapabilityError as exc:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route requires a server-owned persisted proposal reference.",
            ) from exc
        reference = object.__new__(cls)
        object.__setattr__(reference, "store", store)
        object.__setattr__(reference, "revision", revision)
        with _ROUTE_PROPOSAL_STORE_OWNER_LOCK:
            _ROUTE_PROPOSAL_REFERENCE_ADMISSIONS[id(reference)] = (reference, store, revision)
        return reference

    def _require_admitted(self) -> tuple[ProposalStoreCapabilityV1, ProposalRevision]:
        if type(self) is not ServerOwnedLegacyProposalReferenceV1:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route requires a server-owned persisted proposal reference.",
            )
        with _ROUTE_PROPOSAL_STORE_OWNER_LOCK:
            admission = _ROUTE_PROPOSAL_REFERENCE_ADMISSIONS.get(id(self))
        if admission is None or admission[0] is not self:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route requires a server-owned persisted proposal reference.",
            )
        _reference, store, revision = admission
        if self.store is not store or self.revision is not revision:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route proposal reference binding changed.",
            )
        try:
            store._require_admitted(_ROUTE_PROPOSAL_STORE_OWNER)
        except ProposalStoreCapabilityError as exc:
            raise WorkbenchAPIError(
                status_code=403,
                code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
                message="The legacy route requires a live server-owned proposal store.",
            ) from exc
        return store, revision

    def __copy__(self) -> "ServerOwnedLegacyProposalReferenceV1":
        raise TypeError("legacy proposal references cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "ServerOwnedLegacyProposalReferenceV1":
        raise TypeError("legacy proposal references cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("legacy proposal references cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("legacy proposal references cannot be serialized")


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
    store: ProposalStoreCapabilityV1,
    *,
    proposal_id: str,
    session_id: str,
    chain_id: str | None,
    actor_ref: str | None = None,
    project_ref: str | None = None,
):
    if type(store) is not ProposalStoreCapabilityV1:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_PROPOSAL_STORE_CAPABILITY_REQUIRED",
            message="Agent proposal reads require the server-owned ProposalStore capability.",
            details={"proposal_id": proposal_id},
        )
    try:
        store._require_admitted(_ROUTE_PROPOSAL_STORE_OWNER)
    except ProposalStoreCapabilityError as exc:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_PROPOSAL_STORE_CAPABILITY_REQUIRED",
            message="Agent proposal reads require the server-owned ProposalStore capability.",
            details={"proposal_id": proposal_id},
        ) from exc
    try:
        proposal = store.latest_revision(proposal_id)
    except (KeyError, OSError, TypeError, ValueError, ProposalStoreCapabilityError) as exc:
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
    try:
        validate_server_proposal_revision(
            proposal,
            actor_ref=actor_ref,
            session_ref=session_id,
            project_ref=project_ref,
        )
    except CutoverCompilerError as exc:
        code = str(getattr(exc, "code", "SERVER_PROPOSAL_INTEGRITY"))
        if code == "SERVER_PROPOSAL_COMPILATION_REQUIRED":
            api_code = "AGENT_LEGACY_COMPILATION_REQUIRED"
            status_code = 409
        elif code == "PROPOSAL_SCOPE_MISMATCH":
            api_code = "AGENT_LEGACY_BINDING_MISMATCH"
            status_code = 403
        else:
            api_code = "AGENT_PROPOSAL_INTEGRITY"
            status_code = 403
        raise WorkbenchAPIError(
            status_code=status_code,
            code=api_code,
            message="The persisted Agent proposal failed server-owned integrity validation.",
            details={"proposal_id": proposal_id, "reason": code},
        ) from exc
    return ServerOwnedLegacyProposalReferenceV1._issue(store, proposal)


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
        authoritative_active_head = _authoritative_active_head(
            root,
            chain_id=chain_id,
            requested_active_head_run_id=active_head_run_id,
        )
        context_packet = _canonicalize_chain_context_packet(
            root,
            chain_id=chain_id,
            packet=body.context_packet,
            active_head_run_id=authoritative_active_head,
        )
    else:
        context_packet = body.context_packet
    serialized, fingerprint = _context_serialized(context_packet)
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
    store = _server_proposal_store(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
        actor_ref=f"actor:agent:{session_id}",
        project_ref=f"project:{root.resolve()}",
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
    store = _server_proposal_store(repository.root)
    _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
        actor_ref=f"actor:agent:{session_id}",
        project_ref=f"project:{root.resolve()}",
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
    request: Request = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    repository, events, metadata = _get_session(root, session_id)
    store = _server_proposal_store(repository.root)
    proposal = _proposal_for_session(
        store,
        proposal_id=proposal_id,
        session_id=session_id,
        chain_id=metadata.get("chain_id"),
        actor_ref=f"actor:agent:{session_id}",
        project_ref=f"project:{root.resolve()}",
    )
    if type(proposal) is not ServerOwnedLegacyProposalReferenceV1:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
            message=(
                "Historical Agent confirmation requires a route-issued reference "
                "to a server-reread ProposalStore revision."
            ),
        )
    proposal._require_admitted()
    proposal_revision = proposal.revision.revision
    if proposal_revision is not None and body.revision != proposal_revision:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision or fingerprint is no longer confirmable.",
            details={"proposal_id": proposal_id},
        )
    proposal_fingerprint = proposal.revision.fingerprint
    if body.fingerprint != proposal_fingerprint:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_CONFLICT",
            message="The proposal revision or fingerprint is no longer confirmable.",
            details={"proposal_id": proposal_id},
        )

    # Historical Agent proposals are not allowed to instantiate the legacy
    # WorkbenchOrchestrator.  A proposal may continue only if an earlier
    # server-owned AgentNotebookCompilerV1 compile and confirmation were
    # persisted into its opaque binding; otherwise this route is typed
    # fail-closed.
    cutover = _execute_legacy_agent_proposal_via_server_boundary(
        proposal,
        proposal_id=proposal_id,
        root=root,
        session_id=session_id,
        request=request,
    )
    return {
        "proposal": _public_proposal(store, proposal_id),
        "operation": cutover["operation"],
        "status": cutover["status"],
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
    if record.operation_id == "graph.fork":
        return {"operation": record.to_dict(), "status": record.status}
    raise WorkbenchAPIError(
        status_code=409,
        code="AGENT_LEGACY_RECONCILE_COMPILATION_REQUIRED",
        message=(
            "Historical Agent operation reconciliation requires the server-owned "
            "Agent/Notebook compilation boundary before it can execute."
        ),
        details={"record_id": record_id, "operation_id": record.operation_id},
    )


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


# Wave C shared Agent/Notebook cutover ----------------------------------------
#
# The HTTP layer never constructs a runtime contribution and never accepts a
# client-shaped confirmation object. Application startup must explicitly
# register a server-composed compiler for a project/session scope. Until that
# join exists, these endpoints fail closed with 503 rather than silently
# falling back to the legacy provider path.
class AgentNotebookCutoverCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    actor_ref: str = Field(min_length=1, max_length=300)
    session_ref: str = Field(min_length=1, max_length=300)
    project_ref: str = Field(min_length=1, max_length=300)
    entrypoint: Literal["agent", "notebook"] = "agent"
    normalized_fields: dict[str, Any] | None = None


class AgentNotebookCutoverScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_ref: str = Field(min_length=1, max_length=300)
    session_ref: str = Field(min_length=1, max_length=300)
    project_ref: str = Field(min_length=1, max_length=300)


class AgentNotebookCutoverExecuteRequest(AgentNotebookCutoverScopeRequest):
    confirmation_id: str = Field(min_length=1, max_length=300)
    current_data_snapshot_digest: str | None = Field(default=None, min_length=64, max_length=64)


@dataclass
class AgentNotebookCutoverAuthorityStoreV1:
    """One authority/receipt store owned by an application instance.

    The direct function fallback is retained only for old unit tests that call
    route handlers without a FastAPI ``Request``. HTTP requests always resolve
    this store from ``request.app.state`` so two app instances cannot share
    compiler bindings or confirmation handles by accident.
    """

    authorities: dict[tuple[str, str], Any] = field(default_factory=dict)
    confirmations: dict[tuple[str, str, str], Any] = field(default_factory=dict)
    confirmation_digests: dict[tuple[str, str, str], str] = field(default_factory=dict)
    confirmation_authorities: dict[tuple[str, str, str], Any] = field(default_factory=dict)
    confirmation_receipts: dict[tuple[str, str, str], ServerConfirmationReceiptV1] = field(
        default_factory=dict
    )
    confirmation_serializations: dict[tuple[str, str, str], dict[str, object]] = field(
        default_factory=dict
    )
    # A retained legacy compilation record may be used by only the proposal
    # that first claimed it.  This is server-owned state, not a client hint.
    legacy_proposal_bindings: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    lock: RLock = field(default_factory=RLock, repr=False)

    def retain_confirmation(
        self,
        project_ref: str,
        session_ref: str,
        compilation_record_id: str,
        receipt: ServerConfirmationReceiptV1,
        *,
        authority: Any | None = None,
    ) -> None:
        if type(receipt) is not ServerConfirmationReceiptV1:
            raise TypeError("confirmation receipt must be server-issued")
        key = (project_ref, session_ref, compilation_record_id)
        with self.lock:
            if authority is not None:
                bound_authority = self.authorities.get((project_ref, session_ref))
                issued_receipt = getattr(bound_authority, "_issued_receipts", {}).get(
                    compilation_record_id
                )
                authority_token = getattr(bound_authority, "_authority_token", None)
                if (
                    bound_authority is not authority
                    or authority_token is None
                    or receipt._authority_token is not authority_token
                    or issued_receipt is not receipt
                ):
                    raise WorkbenchAPIError(
                        status_code=403,
                        code="AGENT_CONFIRMATION_AUTHORITY_REQUIRED",
                        message="The confirmation receipt was not issued by the bound server authority.",
                        details={"compilation_record_id": compilation_record_id},
                    )
            existing_digest = self.confirmation_digests.get(key)
            if existing_digest is not None and existing_digest != receipt.confirmation_digest:
                raise ValueError("confirmation receipt identity changed")
            serialized = receipt.to_dict()
            existing_serialized = self.confirmation_serializations.get(key)
            if existing_serialized is not None and existing_serialized != serialized:
                raise ValueError("confirmation receipt serialization changed")
            self.confirmations[key] = receipt
            self.confirmation_digests[key] = receipt.confirmation_digest
            if authority is not None:
                self.confirmation_authorities[key] = authority
                self.confirmation_receipts[key] = receipt
            self.confirmation_serializations[key] = serialized


_DEFAULT_CUTOVER_STORE = AgentNotebookCutoverAuthorityStoreV1()


def new_agent_notebook_cutover_authority_store() -> AgentNotebookCutoverAuthorityStoreV1:
    return AgentNotebookCutoverAuthorityStoreV1()


def set_default_agent_notebook_cutover_authority_store(
    store: AgentNotebookCutoverAuthorityStoreV1,
) -> None:
    """Point legacy direct route calls at the main app's single store."""

    if type(store) is not AgentNotebookCutoverAuthorityStoreV1:
        raise TypeError("store must be an AgentNotebookCutoverAuthorityStoreV1")
    global _DEFAULT_CUTOVER_STORE
    _DEFAULT_CUTOVER_STORE = store


def _cutover_store(
    *,
    request: Request | None = None,
    app_instance: Any | None = None,
) -> AgentNotebookCutoverAuthorityStoreV1:
    owner = app_instance
    if request is not None:
        owner = request.app
    if owner is not None:
        store = getattr(getattr(owner, "state", None), "agent_notebook_cutover_store", None)
        if type(store) is not AgentNotebookCutoverAuthorityStoreV1:
            raise WorkbenchAPIError(
                status_code=503,
                code="AGENT_NOTEBOOK_CUTOVER_STORE_NOT_BOUND",
                message="The application has no valid Agent/Notebook authority store.",
            )
        return store
    return _DEFAULT_CUTOVER_STORE


def resolve_agent_notebook_server_identity(
    request: Request,
    *,
    project_ref: str,
    claimed_session_ref: str | None,
    notebook_id: str | None,
) -> tuple[str, str, str | None]:
    """Resolve the authenticated actor/session/project at the HTTP boundary.

    ``claimed_session_ref`` is supplied only as a lookup hint for generic
    Agent calls. A host resolver may ignore it and derive the session from its
    own authenticated request state. Notebook calls always provide the
    server-loaded Notebook id as the stable resource key.
    """

    resolver = getattr(request.app.state, "notebook_cutover_identity_resolver", None)
    if not callable(resolver):
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
            message="The host has not bound a server-owned Agent/Notebook identity.",
        )
    try:
        resolved = resolver(request, project_ref, claimed_session_ref, notebook_id)
    except WorkbenchAPIError:
        raise
    except Exception as exc:
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
            message="The requested Agent/Notebook scope has no server-owned identity binding.",
        ) from exc
    if not isinstance(resolved, tuple) or len(resolved) not in {2, 3}:
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
            message="The host identity resolver returned an invalid binding.",
        )
    if any(
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        for value in resolved[:2]
    ):
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
            message="The host identity resolver returned an invalid actor/session binding.",
        )
    canonical_project_ref = resolved[2] if len(resolved) == 3 else None
    if canonical_project_ref is not None and (
        type(canonical_project_ref) is not str
        or not canonical_project_ref
        or canonical_project_ref != canonical_project_ref.strip()
        or "\x00" in canonical_project_ref
    ):
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_PROJECT_NOT_BOUND",
            message="The host identity resolver returned no valid project scope.",
        )
    if notebook_id is None and canonical_project_ref is None:
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_PROJECT_NOT_BOUND",
            message="Generic Agent HTTP calls require a server-owned project scope.",
        )
    return resolved[0], resolved[1], canonical_project_ref


def _assert_server_identity(
    request: Request | None,
    *,
    project_ref: str,
    claimed_actor_ref: str,
    claimed_session_ref: str,
    notebook_id: str | None = None,
) -> tuple[str, str, str]:
    if request is None:
        # Direct route-function calls are a compatibility/testing seam. Real
        # HTTP requests always receive a Request and therefore require the
        # host identity binding above.
        return claimed_actor_ref, claimed_session_ref, project_ref
    actor_ref, session_ref, canonical_project_ref = resolve_agent_notebook_server_identity(
        request,
        project_ref=project_ref,
        claimed_session_ref=claimed_session_ref,
        notebook_id=notebook_id,
    )
    if (claimed_actor_ref, claimed_session_ref) != (actor_ref, session_ref):
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_NOTEBOOK_IDENTITY_MISMATCH",
            message="The request identity does not match the server-owned scope.",
        )
    if canonical_project_ref is not None and canonical_project_ref != project_ref:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_NOTEBOOK_PROJECT_MISMATCH",
            message="The request project does not match the server-owned scope.",
        )
    return actor_ref, session_ref, canonical_project_ref or project_ref


def _require_cutover_scope_ref(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty scope reference")
    return value


def configure_agent_notebook_cutover_authority(
    *,
    project_ref: str,
    session_ref: str,
    compiler: Any | None,
    app_instance: Any | None = None,
) -> None:
    """Bind or clear one server-owned compiler for one exact scope.

    Rebinding also drops retained confirmations for that scope so a receipt
    issued by an earlier compiler cannot cross a bootstrap generation.
    """

    project_ref = _require_cutover_scope_ref(project_ref, "project_ref")
    session_ref = _require_cutover_scope_ref(session_ref, "session_ref")
    if compiler is not None:
        from ..agent.orchestrator import AgentNotebookCompilerV1

        if type(compiler) is not AgentNotebookCompilerV1:
            raise TypeError("compiler must be an AgentNotebookCompilerV1")
        if not callable(getattr(compiler, "evidence_committer", None)):
            raise ValueError("compiler must have a server-owned evidence committer")

    store = _cutover_store(app_instance=app_instance)
    scope = (project_ref, session_ref)
    for key in tuple(store.confirmations):
        if key[:2] == scope:
            store.confirmations.pop(key, None)
    for key in tuple(store.confirmation_digests):
        if key[:2] == scope:
            store.confirmation_digests.pop(key, None)
    for key in tuple(store.confirmation_authorities):
        if key[:2] == scope:
            store.confirmation_authorities.pop(key, None)
    for key in tuple(store.confirmation_receipts):
        if key[:2] == scope:
            store.confirmation_receipts.pop(key, None)
    for key in tuple(store.confirmation_serializations):
        if key[:2] == scope:
            store.confirmation_serializations.pop(key, None)
    for key in tuple(store.legacy_proposal_bindings):
        if key[:2] == scope:
            store.legacy_proposal_bindings.pop(key, None)
    if compiler is None:
        store.authorities.pop(scope, None)
    else:
        store.authorities[scope] = compiler


def lookup_agent_notebook_cutover_authority(
    project_ref: str,
    session_ref: str,
    request: Request | None = None,
) -> Any:
    """Return only the compiler bound to this exact project/session scope."""

    project_ref = _require_cutover_scope_ref(project_ref, "project_ref")
    session_ref = _require_cutover_scope_ref(session_ref, "session_ref")
    compiler = _cutover_store(request=request).authorities.get((project_ref, session_ref))
    if compiler is None:
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_CUTOVER_NOT_BOUND",
            message="The shared Agent/Notebook runtime is not server-bound for this scope.",
            details={"project_ref": project_ref, "session_ref": session_ref},
        )
    return compiler


def register_agent_notebook_cutover_authority(
    *,
    project_ref: str,
    session_ref: str,
    compiler: Any,
    app_instance: Any | None = None,
) -> None:
    """Bind one server-composed compiler to one project/session scope.

    This is intentionally explicit and process-local in Wave C. Production
    startup is responsible for supplying a durable authority and trusted
    provider contributions in a later integration line; the HTTP route never
    guesses or imports a provider implementation.
    """

    configure_agent_notebook_cutover_authority(
        project_ref=project_ref,
        session_ref=session_ref,
        compiler=compiler,
        app_instance=app_instance,
    )


def _cutover_authority(
    project_ref: str,
    session_ref: str,
    request: Request | None = None,
) -> Any:
    return lookup_agent_notebook_cutover_authority(project_ref, session_ref, request=request)


def _cutover_error(exc: Exception, *, action: str) -> WorkbenchAPIError:
    code = str(getattr(exc, "code", "CUTOVER_FAILED"))
    status = 422 if action == "compile" else 409
    if code in {"RUNTIME_CATALOG_NOT_BOUND", "PROVIDER_RUNTIME_NOT_BOUND", "CAPABILITY_BINDING_MISSING"}:
        status = 503
    return WorkbenchAPIError(status_code=status, code=code, message=str(exc))


def _legacy_cutover_binding(proposal: Any) -> dict[str, Any]:
    """Read only the server-handle envelope accepted by legacy proposals.

    The values are lookup hints, never execution authority.  The compiler's
    persisted record and the app-owned confirmation store must agree with all
    scope values before execution is possible.
    """

    raw_preconditions = getattr(proposal, "preconditions", None)
    if not isinstance(raw_preconditions, Mapping):
        raw_preconditions = {}
    candidate: Mapping[str, Any] = raw_preconditions
    for key in ("server_compilation", "agent_notebook_cutover", "cutover"):
        nested = raw_preconditions.get(key)
        if isinstance(nested, Mapping):
            candidate = nested
            break

    def first_string(*keys: str) -> str | None:
        for key in keys:
            value = candidate.get(key)
            if type(value) is str and value and value == value.strip() and "\x00" not in value:
                return value
        return None

    def first_int(*keys: str) -> int | None:
        for key in keys:
            value = candidate.get(key)
            if type(value) is int and value > 0:
                return value
        return None

    return {
        "compilation_record_id": first_string(
            "compilation_record_id", "server_compilation_record_id"
        ),
        "confirmation_id": first_string(
            "confirmation_id", "server_confirmation_id"
        ),
        "actor_ref": first_string("actor_ref", "principal_ref"),
        "session_ref": first_string("session_ref"),
        "project_ref": first_string("project_ref"),
        "proposal_id": first_string("proposal_id"),
        "proposal_revision": first_int("proposal_revision", "revision"),
        "proposal_fingerprint": first_string("proposal_fingerprint", "fingerprint"),
        "operation_id": first_string("operation_id", "operation"),
        "semantic_plan_hash": first_string("semantic_plan_hash", "plan_hash"),
        "data_snapshot_digest": first_string(
            "current_data_snapshot_digest", "data_snapshot_digest"
        ),
    }


def _legacy_agent_route_scope(
    root: Path,
    session_id: str,
    *,
    request: Request | None,
) -> tuple[str, str, str]:
    """Resolve the route-owned historical Agent scope before any lookup.

    The proposal is an untrusted compatibility envelope.  Its preconditions
    may carry a retained server handle, but they never choose the authority
    used to resolve that handle.
    """

    project_ref = f"project:{root.resolve()}"
    actor_ref = f"actor:agent:{session_id}"
    return _assert_server_identity(
        request,
        project_ref=project_ref,
        claimed_actor_ref=actor_ref,
        claimed_session_ref=session_id,
    )


def _object_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _execute_legacy_agent_proposal_via_server_boundary(
    proposal: Any,
    *,
    proposal_id: str,
    root: Path,
    session_id: str,
    request: Request | None,
) -> dict[str, Any]:
    """Execute a legacy proposal only through a retained cutover receipt."""

    if type(proposal) is not ServerOwnedLegacyProposalReferenceV1:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_CANONICAL_PROPOSAL_REQUIRED",
            message=(
                "Historical Agent confirmation requires a route-issued reference "
                "to a server-reread ProposalStore revision."
            ),
        )
    proposal_store, referenced_revision = proposal._require_admitted()
    if proposal_id != referenced_revision.proposal_id:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The request proposal id does not match the route-owned persisted proposal.",
            details={"fields": ["proposal_id"]},
        )
    canonical_actor, canonical_session, canonical_project = _legacy_agent_route_scope(
        root,
        session_id,
        request=request,
    )
    # Re-read the exact route-owned store immediately before any precondition
    # parsing, authority lookup, record read, claim, or write. A stale opaque
    # reference cannot authorize a changed persisted revision.
    reread = _proposal_for_session(
        proposal_store,
        proposal_id=proposal_id,
        session_id=canonical_session,
        chain_id=referenced_revision.chain_id,
        actor_ref=canonical_actor,
        project_ref=canonical_project,
    )
    if reread.revision != referenced_revision:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_INTEGRITY",
            message="The route-owned proposal revision changed after admission.",
            details={"proposal_id": proposal_id},
        )
    proposal = reread.revision
    persisted_proposal = True
    binding = _legacy_cutover_binding(proposal)
    if persisted_proposal:
        # Proposal identity is derived from the server revision. A nested
        # caller-shaped identity is only a consistency hint and is rejected
        # below if it disagrees with this route-owned value.
        for field_name, value in (
            ("proposal_id", proposal.proposal_id),
            ("proposal_revision", proposal.revision),
            ("proposal_fingerprint", proposal.fingerprint),
        ):
            if binding.get(field_name) is None:
                binding[field_name] = value
    required = ("compilation_record_id", "confirmation_id", "semantic_plan_hash")
    missing = [name for name in required if binding.get(name) is None]
    if missing:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_LEGACY_COMPILATION_REQUIRED",
            message=(
                "Historical Agent proposals require a server-owned AgentNotebookCompilerV1 "
                "compilation record and retained confirmation before execution."
            ),
            details={"missing": missing},
        )

    persisted_proposal_id = _object_value(proposal, "proposal_id")
    if persisted_proposal_id != proposal_id:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The request proposal id does not match the route-owned persisted proposal.",
            details={"fields": ["proposal_id"]},
        )
    expected_proposal = {
        "proposal_id": persisted_proposal_id,
        "proposal_revision": _object_value(proposal, "revision"),
        "proposal_fingerprint": _object_value(proposal, "fingerprint"),
        "operation_id": _object_value(proposal, "operation_id"),
    }
    if any(value is None for value in expected_proposal.values()):
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_LEGACY_COMPILATION_REQUIRED",
            message=(
                "Historical Agent proposals require a server-owned proposal binding "
                "with revision, fingerprint, and operation identity."
            ),
            details={"missing": [key for key, value in expected_proposal.items() if value is None]},
        )
    persisted_session = _object_value(proposal, "session_id")
    if persisted_session is not None and persisted_session != canonical_session:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The route-owned proposal is not bound to this Agent session.",
            details={"fields": ["session_ref"]},
        )
    expected_binding = {
        **expected_proposal,
        "actor_ref": canonical_actor,
        "session_ref": canonical_session,
        "project_ref": canonical_project,
    }
    binding_mismatches = [
        name
        for name, expected in expected_binding.items()
        if binding.get(name) is not None and binding.get(name) != expected
    ]
    if binding_mismatches:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The retained Agent compilation binding does not match the route-owned proposal scope.",
            details={"fields": binding_mismatches},
        )

    record_id = binding["compilation_record_id"]
    cutover_store = _cutover_store(request=request)
    confirmation = cutover_store.confirmations.get(
        (canonical_project, canonical_session, record_id)
    )
    confirmation_mismatches = []
    if confirmation is None:
        confirmation_mismatches.append("confirmation_id")
    elif binding.get("semantic_plan_hash") is not None and _object_value(
        confirmation, "semantic_plan_hash"
    ) != binding["semantic_plan_hash"]:
        confirmation_mismatches.append("semantic_plan_hash")
    elif type(confirmation) is not ServerConfirmationReceiptV1:
        # A serialized receipt or a duck-typed object is data, not a server
        # authority object. It must never be promoted into an executable
        # handle by a legacy compatibility route.
        confirmation_mismatches.append("receipt_type")
    else:
        for field_name, expected in (
            ("confirmation_id", binding["confirmation_id"]),
            ("compilation_record_id", record_id),
            ("actor_ref", canonical_actor),
            ("session_ref", canonical_session),
            ("project_ref", canonical_project),
        ):
            if _object_value(confirmation, field_name) != expected:
                confirmation_mismatches.append(field_name)
        digest = _object_value(confirmation, "confirmation_digest")
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            confirmation_mismatches.append("confirmation_digest")
        retained_digest = getattr(cutover_store, "confirmation_digests", {}).get(
            (canonical_project, canonical_session, record_id)
        )
        if retained_digest is None or digest != retained_digest:
            confirmation_mismatches.append("confirmation_digest")
        retained_serialization = getattr(cutover_store, "confirmation_serializations", {}).get(
            (canonical_project, canonical_session, record_id)
        )
        if not isinstance(retained_serialization, Mapping) or dict(
            confirmation.to_dict()
        ) != dict(retained_serialization):
            confirmation_mismatches.append("receipt_serialization")
        retained_authority = getattr(cutover_store, "confirmation_authorities", {}).get(
            (canonical_project, canonical_session, record_id)
        )
        retained_receipt = getattr(cutover_store, "confirmation_receipts", {}).get(
            (canonical_project, canonical_session, record_id)
        )
        authority_token = getattr(retained_authority, "_authority_token", None)
        if (
            retained_authority is None
            or retained_receipt is not confirmation
            or authority_token is None
            or confirmation._authority_token is not authority_token
        ):
            confirmation_mismatches.append("receipt_authority")
    if confirmation_mismatches:
        raise WorkbenchAPIError(
            status_code=409,
            code=(
                "SERVER_CONFIRMATION_UNKNOWN"
                if confirmation is None
                or (
                    type(confirmation) is not ServerConfirmationReceiptV1
                    and "receipt_type" in confirmation_mismatches
                )
                else "AGENT_LEGACY_BINDING_MISMATCH"
            ),
            message="The legacy proposal has no matching server-retained confirmation handle.",
            details={"compilation_record_id": record_id, "fields": confirmation_mismatches},
        )
    receipt_binding = {
        "proposal_id": _object_value(confirmation, "proposal_id"),
        "proposal_revision": _object_value(confirmation, "proposal_revision"),
        "proposal_fingerprint": _object_value(confirmation, "proposal_fingerprint"),
        "semantic_plan_hash": _object_value(confirmation, "semantic_plan_hash"),
        "confirmation_id": _object_value(confirmation, "confirmation_id"),
        "compilation_record_id": _object_value(confirmation, "compilation_record_id"),
        "actor_ref": _object_value(confirmation, "actor_ref"),
        "session_ref": _object_value(confirmation, "session_ref"),
        "project_ref": _object_value(confirmation, "project_ref"),
    }
    binding_key = (canonical_project, canonical_session, record_id)
    with cutover_store.lock:
        if cutover_store.legacy_proposal_bindings.get(binding_key) is not None:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_LEGACY_PROPOSAL_BINDING_REPLAY",
                message=(
                    "The retained compilation confirmation has already been used. "
                    "Recompile and reconfirm."
                ),
                details={"compilation_record_id": record_id},
            )
    receipt_proposal_mismatches = [
        name
        for name, expected in {
            "proposal_id": expected_proposal["proposal_id"],
            "proposal_revision": expected_proposal["proposal_revision"],
            "proposal_fingerprint": expected_proposal["proposal_fingerprint"],
        }.items()
        if receipt_binding.get(name) != expected
    ]
    if receipt_proposal_mismatches:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The server confirmation receipt is not bound to this Agent proposal.",
            details={"fields": receipt_proposal_mismatches},
        )
    compiler = _cutover_authority(canonical_project, canonical_session, request=request)
    try:
        record = compiler.record(record_id)
    except Exception as exc:
        raise _cutover_error(exc, action="confirm") from exc
    record_mismatches = []
    if _object_value(record, "record_id") != record_id:
        record_mismatches.append("compilation_record_id")
    if _object_value(record, "principal_ref") != canonical_actor:
        record_mismatches.append("actor_ref")
    if _object_value(record, "session_ref") != canonical_session:
        record_mismatches.append("session_ref")
    if _object_value(record, "project_ref") != canonical_project:
        record_mismatches.append("project_ref")
    if _object_value(record, "semantic_plan_hash") != receipt_binding["semantic_plan_hash"]:
        record_mismatches.append("semantic_plan_hash")
    record_operation = _object_value(record, "operation_id")
    if record_operation is None:
        compiled_workflow = _object_value(record, "compiled_workflow")
        record_operation = _object_value(compiled_workflow, "operation_id")
        if record_operation is None:
            plan_diff = _object_value(compiled_workflow, "plan_diff")
            record_operation = _object_value(plan_diff, "operation_id")
    if record_operation is not None and record_operation != expected_proposal["operation_id"]:
        record_mismatches.append("operation_id")
    if record_mismatches:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The server compilation record is not bound to the canonical Agent proposal.",
            details={"fields": record_mismatches},
        )
    receipt_scope_mismatches = [
        name
        for name, expected in {
            "compilation_record_id": record_id,
            "semantic_plan_hash": _object_value(record, "semantic_plan_hash"),
            "actor_ref": canonical_actor,
            "session_ref": canonical_session,
            "project_ref": canonical_project,
        }.items()
        if receipt_binding.get(name) != expected
    ]
    if receipt_scope_mismatches:
        raise WorkbenchAPIError(
            status_code=403,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The server confirmation receipt is not bound to the canonical Agent scope.",
            details={"fields": receipt_scope_mismatches},
        )
    proposal_binding = {
        "proposal_id": receipt_binding["proposal_id"],
        "proposal_revision": receipt_binding["proposal_revision"],
        "proposal_fingerprint": receipt_binding["proposal_fingerprint"],
        "operation_id": expected_proposal["operation_id"],
        "semantic_plan_hash": receipt_binding["semantic_plan_hash"],
        "confirmation_id": receipt_binding["confirmation_id"],
        "actor_ref": canonical_actor,
        "session_ref": canonical_session,
        "project_ref": canonical_project,
    }
    with cutover_store.lock:
        retained = cutover_store.legacy_proposal_bindings.get(binding_key)
        if retained is not None:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_LEGACY_PROPOSAL_BINDING_REPLAY",
                message=(
                    "The retained compilation confirmation is already bound to a "
                    "different historical Agent proposal. Recompile and reconfirm."
                ),
                details={"compilation_record_id": record_id},
            )
        if retained is None:
            cutover_store.legacy_proposal_bindings[binding_key] = proposal_binding
    try:
        result = compiler.execute(
            record_id,
            confirmation,
            current_data_snapshot_digest=binding.get("data_snapshot_digest"),
        )
    except Exception as exc:
        raise _cutover_error(exc, action="execute") from exc
    if not hasattr(result, "to_dict"):
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_CUTOVER_RESULT_INVALID",
            message="The server compiler returned no typed execution result.",
        )
    result_dict = result.to_dict()
    if not isinstance(result_dict, Mapping):
        raise WorkbenchAPIError(
            status_code=503,
            code="AGENT_NOTEBOOK_CUTOVER_RESULT_INVALID",
            message="The server compiler returned an invalid execution result envelope.",
        )
    if (
        result_dict.get("compilation_record_id") not in {None, record_id}
        or type(result_dict.get("operation_id")) is not str
        or not result_dict.get("operation_id")
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_LEGACY_BINDING_MISMATCH",
            message="The server execution result is not bound to the confirmed compilation record.",
            details={"field": "compilation_record_id"},
        )
    operation = {
        "record_id": record_id,
        "operation_id": result_dict.get("operation_id"),
        "status": result_dict.get("status"),
        "cutover_execution": result_dict,
    }
    return {"operation": operation, "status": result_dict.get("status")}


def _assert_cutover_record_scope(
    compiler: Any,
    compilation_record_id: str,
    body: AgentNotebookCutoverScopeRequest,
) -> None:
    try:
        record = compiler.record(compilation_record_id)
    except Exception as exc:
        raise _cutover_error(exc, action="confirm") from exc
    if (record.principal_ref, record.session_ref, record.project_ref) != (
        body.actor_ref,
        body.session_ref,
        body.project_ref,
    ):
        raise WorkbenchAPIError(
            status_code=403,
            code="CUTOVER_SCOPE_MISMATCH",
            message="The record is bound to another actor, session or project.",
        )


@router.post("/agent/cutover/compile")
def compile_agent_notebook_cutover(
    body: AgentNotebookCutoverCompileRequest,
    request: Request = None,
) -> dict[str, Any]:
    """Compile one natural-language request into a server-owned preview."""

    actor_ref, session_ref, project_ref = _assert_server_identity(
        request,
        project_ref=body.project_ref,
        claimed_actor_ref=body.actor_ref,
        claimed_session_ref=body.session_ref,
    )
    compiler = _cutover_authority(project_ref, session_ref, request=request)
    try:
        preview = compiler.compile_natural_language(
            body.text,
            actor_ref=actor_ref,
            session_ref=session_ref,
            project_ref=project_ref,
            normalized_fields=body.normalized_fields,
            entrypoint=body.entrypoint,
        )
    except Exception as exc:
        raise _cutover_error(exc, action="compile") from exc
    return {"preview": preview.to_dict()}


@router.post("/agent/cutover/{compilation_record_id}/confirm")
def confirm_agent_notebook_cutover(
    compilation_record_id: str,
    body: AgentNotebookCutoverScopeRequest,
    request: Request = None,
) -> dict[str, Any]:
    """Issue and retain a server confirmation for one compiled record."""

    _assert_server_identity(
        request,
        project_ref=body.project_ref,
        claimed_actor_ref=body.actor_ref,
        claimed_session_ref=body.session_ref,
    )
    compiler = _cutover_authority(body.project_ref, body.session_ref, request=request)
    _assert_cutover_record_scope(compiler, compilation_record_id, body)
    try:
        receipt = compiler.confirm(compilation_record_id)
    except Exception as exc:
        raise _cutover_error(exc, action="confirm") from exc
    _cutover_store(request=request).retain_confirmation(
        body.project_ref,
        body.session_ref,
        compilation_record_id,
        receipt,
        authority=compiler,
    )
    return {"confirmation": receipt.to_dict()}


@router.post("/agent/cutover/{compilation_record_id}/execute")
def execute_agent_notebook_cutover(
    compilation_record_id: str,
    body: AgentNotebookCutoverExecuteRequest,
    request: Request = None,
) -> dict[str, Any]:
    """Execute only with the server-retained confirmation handle."""

    _assert_server_identity(
        request,
        project_ref=body.project_ref,
        claimed_actor_ref=body.actor_ref,
        claimed_session_ref=body.session_ref,
    )
    compiler = _cutover_authority(body.project_ref, body.session_ref, request=request)
    _assert_cutover_record_scope(compiler, compilation_record_id, body)
    confirmation = _cutover_store(request=request).confirmations.get(
        (body.project_ref, body.session_ref, compilation_record_id)
    )
    if (
        type(confirmation) is not ServerConfirmationReceiptV1
        or confirmation.confirmation_id != body.confirmation_id
    ):
        raise WorkbenchAPIError(
            status_code=409,
            code="SERVER_CONFIRMATION_UNKNOWN",
            message="The confirmation is not a server-retained handle for this scope and record.",
        )
    try:
        result = compiler.execute(
            compilation_record_id,
            confirmation,
            current_data_snapshot_digest=body.current_data_snapshot_digest,
        )
    except Exception as exc:
        raise _cutover_error(exc, action="execute") from exc
    return {"result": result.to_dict()}
