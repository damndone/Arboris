"""Read-only policy and exact request checks for one plan version."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Any

from ..contracts.common.errors import OperationValidationError
from ..graph_model import NodeKind
from ..graph_store import GraphStore
from ..lineage.node_write_validation import build_rerun_operation_context
from . import permissions
from .chains import ChainStore, session_owns_chain
from .context_compiler import registered_artifact_records
from .operation_definitions import UnknownOperationError
from .operations import OperationRegistry
from .permission_config import project_permission_rules
from .plans import MAX_STEPS, Plan, PlanProposalRef, PlanStep
from .proposals import ProposalRevision, ProposalStore


class PlanBindingError(ValueError):
    """An exact request or its current source could not be verified."""


_SOURCE_BYTES = 1_000_000
_SOURCE_READS = 4
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CONTEXT_FIELDS = ("context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")
PROJECT_OPERATION_DENIED = "PROJECT_OPERATION_DENIED"
WORKFLOW_STEP_OPERATIONS_REQUIRED = "WORKFLOW_STEP_OPERATIONS_REQUIRED"


@dataclass(frozen=True)
class RegisteredSource:
    run_id: str
    node_ref: str
    artifact_id: str
    sha256: str
    path: Path

    def view(self) -> dict[str, str]:
        return {"run_id": self.run_id, "node_ref": self.node_ref, "artifact_id": self.artifact_id, "sha256": self.sha256}

    @property
    def schema_sidecar(self) -> Path:
        from ..data_operations.frames import _schema_sidecar_path

        return _schema_sidecar_path(self.path)

    def file_generation(self) -> str | None:
        """Identify an unchanged regular source with no unbound type schema."""
        try:
            self.schema_sidecar.lstat()
        except FileNotFoundError:
            value = self.path.lstat()
            if S_ISREG(value.st_mode):
                return ":".join(str(part) for part in (
                    value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                ))
        return None


def registered_workflow_source(root: Path, target: dict[str, Any]) -> RegisteredSource:
    """Read the graph and registered digest without opening observation rows."""
    run_id, node_ref = target["run_id"], target["node_ref"]
    runs = root.resolve() / "runs"
    run_root = runs / run_id
    if (Path(run_id).name != run_id or run_id.startswith(".") or "\\" in run_id
            or run_root.resolve() != run_root):
        raise PlanBindingError("The dataset run is outside the project run directory.")
    node = GraphStore(runs).read(run_id).nodes[node_ref]
    if node.kind != NodeKind.DATASET_STAGE:
        raise PlanBindingError("The request does not target a dataset stage.")
    records = registered_artifact_records(run_root)
    if node.payload_ref:
        matches = [item for item in records if item.get("path") == node.payload_ref]
    else:
        matches = [item for item in records if node_ref in {"stage:raw", "stage:source"}
                   and item.get("artifact_type") == "raw_data"
                   and str(item.get("path") or "").startswith("raw_snapshot/")]
    if len(matches) != 1:
        raise PlanBindingError("The dataset stage needs one registered source artifact.")
    item = matches[0]
    artifact_id, digest = item.get("artifact_id"), item.get("sha256")
    if (not isinstance(artifact_id, str) or not artifact_id or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest) or sum(r.get("artifact_id") == artifact_id for r in records) != 1):
        raise PlanBindingError("The dataset artifact needs an unambiguous registered digest.")
    path = (run_root / item["path"]).resolve()
    if not path.is_relative_to(run_root) or not path.is_file():
        raise PlanBindingError("The registered dataset artifact is unavailable in its run directory.")
    return RegisteredSource(run_id, node_ref, artifact_id, digest, path)


def operation_ids(proposal: ProposalRevision) -> list[str]:
    if proposal.operation_id == "operation.multi_step":
        return [str(step.get("operation_id", "")) for step in proposal.changes.get("steps") or ()
                if isinstance(step, dict)]
    return [proposal.operation_id]


def resolve_proposal(repository, session_id: str, ref: PlanProposalRef) -> ProposalRevision:
    store = ProposalStore(repository.root, create=False)
    try:
        proposal = store.latest_revision(ref.proposal_id)
        if (proposal.session_id != session_id or not session_owns_chain(repository, session_id=session_id,
                                                                       chain_id=proposal.chain_id)):
            raise PlanBindingError("The proposal does not belong to this conversation.")
        if PlanProposalRef.of(proposal) != ref or not proposal.has_valid_fingerprint():
            raise PlanBindingError("The referenced proposal revision or fingerprint has changed. Bind the current revision.")
        if store.latest_status(ref.proposal_id) not in {"plan_prepared", "pending"}:
            raise PlanBindingError("The referenced proposal has already been decided. Bind a new proposal for new work.")
    except (KeyError, OSError, TypeError) as exc:
        raise PlanBindingError("The referenced proposal is unavailable.") from exc
    return proposal


def _check(level, status, code, message, **details):
    return {"level": level, "status": status, "code": code, "message": message, **details}


def _status(checks):
    states = {check["status"] for check in checks}
    return "blocked" if "blocked" in states else "deferred" if "deferred" in states else "ready"


def _bounded_frame(root, source, cache):
    if source in cache:
        return cache[source]
    size = source.path.stat().st_size
    if len(cache) >= _SOURCE_READS or size > _SOURCE_BYTES:
        return None
    if source.path.suffix.lower() in {".parquet", ".pq"}:
        from pyarrow.parquet import ParquetFile

        metadata = ParquetFile(source.path).metadata
        uncompressed = sum(metadata.row_group(index).total_byte_size for index in range(metadata.num_row_groups))
        if uncompressed > 2 * _SOURCE_BYTES or metadata.num_rows * metadata.num_columns > 500_000:
            return None
    elif source.path.suffix.lower() != ".csv":
        return None

    from ..statistical_exploration import resolve_statistical_source

    context, frame = resolve_statistical_source(root, source_run_id=source.run_id, source_node_id=source.node_ref,
                                                 source_artifact_id=source.artifact_id)
    if context["source_sha256"] != source.sha256:
        raise PlanBindingError("The registered dataset contents changed during preflight.")
    cache[source] = frame
    return frame


def _automatic_exploration_group(operation_id, spec):
    if operation_id != "statistical.explore" or "plots" in spec:
        return None
    from ..statistical_exploration import GROUPABLE_OPERATIONS

    options = spec.get("options") or {}
    column = options.get("group_by")
    if (spec["operation"] in GROUPABLE_OPERATIONS and options.get("group_values") is None
            and isinstance(column, str)):
        return column
    return None


def _check_automatic_exploration_groups(frame, column):
    from ..combinators.by_group import ByGroupRefusal, check_group_cardinality

    try:
        check_group_cardinality(frame, column)
    except ByGroupRefusal as exc:
        message = exc.message
        if exc.code == "TOO_MANY_GROUPS":
            message += " Remove options.group_by for a pooled summary or select options.group_values."
        raise OperationValidationError(message) from exc


def check_workflow_group_limits(frame, steps):
    """Check automatic grouping on the resolved base before admitting a workflow."""
    checked = set()
    for step in steps:
        spec = step["spec"]
        column = _automatic_exploration_group(step["operation_id"], spec)
        if column is None or "source" in spec or column not in frame or column in checked:
            continue
        try:
            _check_automatic_exploration_groups(frame, column)
        except OperationValidationError as exc:
            raise OperationValidationError(f"workflow step {step['step_id']}: {exc}") from exc
        checked.add(column)


def _workflow_checks(root, proposal, checks, cache, *, completion=None):
    from ..native_research import NATIVE_RESEARCH_OPERATIONS, validate_native_research_size
    from ..statistical_tests import TEST_FAMILIES
    from .p7_pack_adapters.base import validate_frame_request_passthrough
    from .p7_pack_registry import p7_pack_registry
    from .plan_model_inputs import check_model_inputs
    from .postestimation_steps import model_step_reference
    from .workflow_capability_adapters import preflight_statistical
    from .workflow import compile_workflow
    from .workflow_contract_parts.graph import _spec_columns
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    source = registered_workflow_source(root, proposal.target)
    if source.artifact_id != proposal.target["artifact_id"]:
        raise PlanBindingError("The registered artifact is no longer owned by the selected dataset stage.")
    digest = proposal.preconditions.get("source_artifact_fingerprint")
    if digest is not None and digest != source.sha256:
        raise PlanBindingError("The registered dataset digest changed since the proposal was prepared.")
    if digest is None:
        checks.append(_check("L0", "deferred", "SOURCE_DIGEST_UNBOUND",
                             "This proposal does not pin a dataset digest. Prepare a new exact request to bind the data."))
    if len(proposal.changes["steps"]) > MAX_STEPS:
        checks.append(_check("L1", "deferred", "WORKFLOW_CHECK_LIMIT",
                             f"Plan preflight checks at most {MAX_STEPS} operations per workflow."))
        return source, None
    sidecar = source.schema_sidecar
    if sidecar.exists() or sidecar.is_symlink():
        checks.append(_check("L0", "deferred", "SOURCE_SCHEMA_UNBOUND",
                             "The dataset has an auxiliary type schema outside the proposal's source digest."))
        frame = None
    else:
        frame = _bounded_frame(root, source, cache)
    draft = compile_workflow(
        workflow_id="plan-preflight", target=proposal.target, preconditions=proposal.preconditions,
        steps=proposal.changes["steps"], available_columns=list(frame.columns) if frame is not None else None,
    )
    checks.append(_check("L0", "passed", "WORKFLOW_SPEC_CHECKED",
                         "The workflow parameter and dependency declarations passed the registered contract."
                         if frame is None else
                         "The workflow parameter declarations passed the registered contract and source column checks."))
    if completion and completion.get("scope", "analysis") == "analysis":
        from .report_sources import validate_plan_report_sources
        from .workflow import WorkflowExecutionError

        try:
            validate_plan_report_sources(root, proposal.target, [item.to_dict() for item in draft.steps])
        except WorkflowExecutionError as exc:
            checks.append(_check("L0", "blocked", "PLAN_REPORT_RESULT_REFS_REQUIRED", str(exc)[:600],
                                 operation_id="report.compose"))
            return source, draft
    pack_ops = set(p7_pack_registry.operation_ids())
    for item in draft.steps:
        op, spec = item.operation_id, item.spec
        fields = [f"{field}.{name}" if name else field
                  for field, value in spec.items() if field not in {"source", "source_artifact_fingerprint"}
                  for name in (value if isinstance(value, dict) and value else [""])]
        details = {"operation_id": op, "workflow_step_id": item.step_id,
                   "columns": [column[:160] for column in sorted(_spec_columns(op, spec))[:32]],
                   "parameter_fields": [field[:160] for field in sorted(fields)[:32]]}
        if "source" in spec or any(model_step_reference(spec.get(field)) is not None
                                  for field in WORKFLOW_STEP_SPEC_CONTRACTS[op].model_reference_fields):
            checks.append(_check("L1", "deferred", "UPSTREAM_SOURCE_PENDING",
                                 "The declared input will be produced by an earlier workflow step.", **details))
            continue
        if frame is None:
            checks.append(_check("L1", "deferred", "SOURCE_CHECK_DEFERRED",
                                 "This dataset is outside the bounded source scope of plan preflight.", **details))
            continue
        pack = p7_pack_registry.get(op) if op in pack_ops else None
        test = TEST_FAMILIES.get(op.removeprefix("test.")) if op.startswith("test.") else None
        request = {"operation_id": op, "input_mode": spec.get("input_mode"),
                   "column_bindings": spec.get("column_bindings"), "options": spec.get("options")}
        message = None
        try:
            column = _automatic_exploration_group(op, spec)
            if column is not None and column in frame:
                _check_automatic_exploration_groups(frame, column)
                message = "Automatic grouping is within the registered group limit."
            elif pack is not None and pack.validate_frame_request is not validate_frame_request_passthrough:
                pack.preflight(frame if pack.input_mode == "frame" else None, request)
                message = "The operation's input validator accepted the bound parameters."
            elif test is not None and test.preflight is not None and not spec.get("by_group"):
                preflight_statistical(frame, request)
                message = "The test family's data validator accepted the bound parameters and source values."
            elif op in NATIVE_RESEARCH_OPERATIONS:
                validate_native_research_size(op, spec, len(frame))
                message = "The native operation's size policy accepted the bound parameters and row count."
            elif op == "model.genesis":
                message = check_model_inputs(frame, spec)
        except (ValueError, OperationValidationError) as exc:
            checks.append(_check("L1", "blocked", "OWNER_CHECK_FAILED", str(exc)[:600], **details))
            continue
        if message is not None:
            checks.append(_check("L1", "passed", "OWNER_CHECK_PASSED", message, **details))
        else:
            checks.append(_check("L1", "deferred", "OWNER_CHECK_UNAVAILABLE",
                                 "This operation has no supported pre-execution data check here.", **details))
    return source, draft


def _project_deny_checks(registry, rules, step: PlanStep, proposal: ProposalRevision | None = None):
    if rules is None or not rules.deny:
        return []
    if proposal is not None:
        definition = registry.require(proposal.operation_id, proposal.operation_version)
        requests = [permissions.request_for_operation(proposal.operation_id, proposal.changes,
                                                      risk_level=definition.risk_level)]
    else:
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        requests = []
        for operation_id in step.operation_ids:
            # The wrapper's class depends on workflow members the plan has yet to bind.
            if operation_id == "operation.multi_step":
                continue
            workflow_step = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
            if workflow_step is not None:
                # The Agent reaches model.genesis as a workflow step, not the separate manual action.
                risk_level = workflow_step.risk_level
            else:
                versions = registry.versions(operation_id)
                if len(versions) != 1:
                    continue
                risk_level = registry.require(operation_id, next(iter(versions))).risk_level
            requests.append(permissions.request_for_operation(operation_id, {}, risk_level=risk_level))

    denied_operations = []
    for request in requests:
        if permissions.decide(permissions.Mode.AUTO, request, rules).outcome == permissions.Outcome.DENY:
            members = [part.operation_id for part in request.components
                       if permissions.decide(permissions.Mode.AUTO, part, rules).outcome == permissions.Outcome.DENY]
            denied_operations.extend(members or [request.operation_id])
    return [_check("L0", "blocked", PROJECT_OPERATION_DENIED,
                   f"The current project rules deny {operation_id}.", operation_id=operation_id)
            for operation_id in dict.fromkeys(denied_operations)]


def check_step(root: Path, repository, session_id: str, step: PlanStep, *, registry, cache,
               rules: permissions.Rules | None = None, completion=None) -> dict[str, Any]:
    checks, source, draft = [], None, None
    if step.status in {"done", "skipped", "failed"}:
        checks.append(_check("L0", "deferred", "STEP_CLOSED", "This step is already recorded as closed."))
    elif step.proposal_ref is None:
        if "operation.multi_step" in step.operation_ids:
            checks.append(_check("L0", "blocked", WORKFLOW_STEP_OPERATIONS_REQUIRED,
                                 "Ask the Agent to revise this plan with the actual workflow step operation IDs "
                                 "for operation.multi_step.", operation_id="operation.multi_step"))
        else:
            checks.append(_check("L0", "deferred", "REQUEST_UNBOUND", "No exact operation proposal is bound to this step."))
        checks.extend(_project_deny_checks(registry, rules, step))
    else:
        try:
            proposal = resolve_proposal(repository, session_id, step.proposal_ref)
            if set(operation_ids(proposal)) != set(step.operation_ids):
                raise PlanBindingError("The proposal's operations do not match this plan step's declared operations.")
            registry.require(proposal.operation_id, proposal.operation_version).validate(
                target=proposal.target, preconditions=proposal.preconditions, changes=proposal.changes)
            head = ChainStore(repository.root, create=False).resolve_active_head(proposal.chain_id)
            if head != proposal.preconditions.get("active_head_run_id"):
                raise PlanBindingError("The active chain head changed since the proposal was prepared.")
            if proposal.operation_id == "operation.multi_step":
                snapshot = build_rerun_operation_context(root / "runs", request_id="plan-preflight",
                    owner_run_id=proposal.target["run_id"], op_node_id=proposal.target["node_ref"], active_head_run_id=head)
                if any(getattr(snapshot, field) != proposal.preconditions.get(field) for field in _CONTEXT_FIELDS):
                    raise PlanBindingError("The dataset node context changed since the proposal was prepared.")
                source, draft = _workflow_checks(root, proposal, checks, cache, completion=completion)
            else:
                checks.append(_check("L1", "deferred", "OWNER_CHECK_UNAVAILABLE",
                                     "This proposal type has no supported plan preflight validator."))
            checks.extend(_project_deny_checks(registry, rules, step, proposal))
        except (PlanBindingError, OperationValidationError, UnknownOperationError) as exc:
            checks.append(_check("L0", "blocked", "REQUEST_OR_SOURCE_INVALID", str(exc)[:600]))
        except (OSError, ValueError, KeyError, TypeError):
            checks.append(_check("L0", "blocked", "SOURCE_UNAVAILABLE",
                                 "The proposal's current source, registered bytes or context could not be verified."))
    status = _status(checks)
    estimate = None
    if status != "blocked" and draft is not None and source is not None:
        from .workflow_timing import estimated_workflow_seconds

        estimate = estimated_workflow_seconds(root, draft, source)
    return {"step_id": step.step_id, "status": status, "checks": checks, "estimated_seconds": estimate,
            **({"source": source.view()} if source is not None else {})}


def check_plan(root, repository, session_id: str, plan: Plan, *, registry=None) -> dict[str, Any]:
    """Evaluate one version against current policy with a shared source-frame cache."""
    root = Path(root)
    rules = project_permission_rules(root)
    cache = {}
    if registry is None and (rules.deny or any(step.proposal_ref is not None for step in plan.steps)):
        registry = OperationRegistry()
    steps = [check_step(root, repository, session_id, step, registry=registry, cache=cache, rules=rules,
                        completion=plan.completion)
             for step in plan.steps]
    states = {step["status"] for step in steps}
    status = "blocked" if "blocked" in states else "deferred" if "deferred" in states else "ready"
    return {"plan_id": plan.plan_id, "plan_version": plan.version, "status": status,
            "can_approve": status != "blocked", "steps": steps}
