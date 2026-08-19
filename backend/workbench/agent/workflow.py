"""Server-owned compilation and execution contracts for step workflows."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..exploration_log import ExplorationLog
from .operations import OperationValidationError
from .storage import append_jsonl_atomic, read_jsonl
from .workflow_contracts import WORKFLOW_TEMPLATE, validate_workflow_steps


# Written into every plan and state record. Nothing compares it on read, so
# older records keep their previous value; it is metadata, not a gate.
WORKFLOW_SCHEMA_VERSION = "workflow.v1"

# ``produced_dataset`` remains a read-compatible name for pre-v1.8.9 state.
# New state is typed by output name and binding type.
PERSISTED_STEP_OUTPUT = "produced_dataset"
PERSISTED_OUTPUT_BINDINGS = "output_bindings"
PERSISTED_LINEAGE = "lineage"
MAX_PERSISTED_OUTPUT_BINDINGS = 16
MAX_PERSISTED_METADATA_BYTES = 64 * 1024
MAX_PERSISTED_METADATA_DEPTH = 6
MAX_PERSISTED_METADATA_ITEMS = 128
MAX_PERSISTED_ARTIFACT_IDS = 256
SERVER_COMPILER_AUTHORITY = "workbench.server.workflow"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _workflow_scope_ref(
    target: Mapping[str, Any], preconditions: Mapping[str, Any]
) -> str:
    context = preconditions.get("context_fingerprint")
    run_id = target.get("run_id")
    active_head = preconditions.get("active_head_run_id")
    if (
        not isinstance(context, str)
        or not context
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(active_head, str)
        or not active_head
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_SCOPE_MISSING: workflow admission scope is incomplete"
        )
    return f"{run_id}:{context}:{active_head}"


def _workflow_contract_fingerprint(step: "WorkflowStep") -> str:
    return hashlib.sha256(_canonical(step.to_dict()).encode("utf-8")).hexdigest()


def _workflow_admission_fingerprint(
    *,
    workflow_id: str,
    workflow_template: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    bindings: Mapping[str, Any],
    steps: tuple["WorkflowStep", ...],
    plan_fingerprint: str,
) -> str:
    """Bind every server admission input into one immutable plan identity."""

    return _fingerprint(
        {
            "workflow_id": workflow_id,
            "workflow_template": workflow_template,
            "target": dict(target),
            "preconditions": dict(preconditions),
            "bindings": dict(bindings),
            "steps": [step.to_dict() for step in steps],
            "plan_fingerprint": plan_fingerprint,
        }
    )


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    operation_id: str
    operation_version: str
    depends_on: tuple[str, ...]
    spec: dict[str, Any]
    expected_artifacts: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "depends_on": list(self.depends_on),
            "spec": self.spec,
            "expected_artifacts": list(self.expected_artifacts),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class WorkflowCompilerReceipt:
    """Opaque process-scoped authority issued only by ``compile_workflow``."""

    workflow_id: str
    receipt_id: str
    plan_fingerprint: str
    target_fingerprint: str
    scope_ref: str
    step_contracts: tuple[tuple[str, str, str], ...]
    admission_fingerprint: str
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "receipt_id": self.receipt_id,
            "plan_fingerprint": self.plan_fingerprint,
            "target_fingerprint": self.target_fingerprint,
            "scope_ref": self.scope_ref,
            "admission_fingerprint": self.admission_fingerprint,
            "step_contracts": [
                {
                    "step_id": step_id,
                    "step_fingerprint": step_fingerprint,
                    "contract_fingerprint": contract_fingerprint,
                }
                for step_id, step_fingerprint, contract_fingerprint in self.step_contracts
            ],
        }


_WORKFLOW_COMPILER_ISSUER_TOKEN = object()
_WORKFLOW_COMPILER_RECEIPTS: dict[
    int, tuple[WorkflowCompilerReceipt, tuple[Any, ...]]
] = {}


def _issue_workflow_compiler_receipt(
    *,
    workflow_id: str,
    plan_fingerprint: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    workflow_template: str,
    bindings: Mapping[str, Any],
    steps: tuple["WorkflowStep", ...],
) -> WorkflowCompilerReceipt:
    step_contracts = tuple(
        (
            step.step_id,
            step.fingerprint,
            _workflow_contract_fingerprint(step),
        )
        for step in steps
    )
    admission_fingerprint = _workflow_admission_fingerprint(
        workflow_id=workflow_id,
        workflow_template=workflow_template,
        target=target,
        preconditions=preconditions,
        bindings=bindings,
        steps=steps,
        plan_fingerprint=plan_fingerprint,
    )
    receipt = WorkflowCompilerReceipt(
        workflow_id=workflow_id,
        receipt_id=f"workflow-compile:{secrets.token_hex(16)}",
        plan_fingerprint=plan_fingerprint,
        target_fingerprint=_fingerprint(dict(target)),
        scope_ref=_workflow_scope_ref(target, preconditions),
        step_contracts=step_contracts,
        admission_fingerprint=admission_fingerprint,
        _issuer_token=_WORKFLOW_COMPILER_ISSUER_TOKEN,
    )
    # The identity registry prevents ``dataclasses.replace`` or a serialized
    # copy from becoming a new server authority merely by copying the token.
    _WORKFLOW_COMPILER_RECEIPTS[id(receipt)] = (
        receipt,
        (
            receipt.workflow_id,
            receipt.receipt_id,
            receipt.plan_fingerprint,
            receipt.target_fingerprint,
            receipt.scope_ref,
            receipt.step_contracts,
            receipt.admission_fingerprint,
        ),
    )
    return receipt


def _require_server_compiler_receipt(draft: "WorkflowDraft") -> WorkflowCompilerReceipt:
    receipt = draft.compiler_receipt
    if draft.compiler_authority != SERVER_COMPILER_AUTHORITY or type(receipt) is not WorkflowCompilerReceipt:
        raise WorkflowExecutionError(
            "WORKFLOW_CLIENT_COMPILED: workflow draft is not server-issued"
        )
    issued = _WORKFLOW_COMPILER_RECEIPTS.get(id(receipt))
    if (
        issued is None
        or issued[0] is not receipt
        or receipt._issuer_token is not _WORKFLOW_COMPILER_ISSUER_TOKEN
        or issued[1]
        != (
            receipt.workflow_id,
            receipt.receipt_id,
            receipt.plan_fingerprint,
            receipt.target_fingerprint,
            receipt.scope_ref,
            receipt.step_contracts,
            receipt.admission_fingerprint,
        )
    ):
        raise WorkflowExecutionError(
            "WORKFLOW_CLIENT_COMPILED: server compiler receipt is not current"
        )
    try:
        expected_steps = tuple(
            (
                step.step_id,
                step.fingerprint,
                _workflow_contract_fingerprint(step),
            )
            for step in draft.steps
        )
        expected = (
            draft.workflow_id,
            draft.plan_fingerprint,
            _fingerprint(dict(draft.target)),
            _workflow_scope_ref(draft.target, draft.preconditions),
            expected_steps,
            _workflow_admission_fingerprint(
                workflow_id=draft.workflow_id,
                workflow_template=draft.workflow_template,
                target=draft.target,
                preconditions=draft.preconditions,
                bindings=draft.bindings,
                steps=draft.steps,
                plan_fingerprint=draft.plan_fingerprint,
            ),
        )
    except (KeyError, TypeError, ValueError, WorkflowExecutionError) as exc:
        raise WorkflowExecutionError(
            "WORKFLOW_CLIENT_COMPILED: workflow draft binding is invalid"
        ) from exc
    if (
        receipt.workflow_id,
        receipt.plan_fingerprint,
        receipt.target_fingerprint,
        receipt.scope_ref,
        receipt.step_contracts,
        receipt.admission_fingerprint,
    ) != expected:
        raise WorkflowExecutionError(
            "WORKFLOW_CLIENT_COMPILED: compiler receipt binding changed"
        )
    return receipt
@dataclass(frozen=True)
class WorkflowDraft:
    workflow_id: str
    workflow_template: str
    target: dict[str, Any]
    preconditions: dict[str, Any]
    bindings: dict[str, Any]
    steps: tuple[WorkflowStep, ...]
    plan_fingerprint: str
    status: str = "planned"
    compiler_authority: str = SERVER_COMPILER_AUTHORITY
    compiler_receipt: WorkflowCompilerReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "workflow_id": self.workflow_id,
            "workflow_template": self.workflow_template,
            "target": self.target,
            "preconditions": self.preconditions,
            "bindings": self.bindings,
            "steps": [step.to_dict() for step in self.steps],
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
            "compiler_authority": self.compiler_authority,
            "compiler_receipt": (
                self.compiler_receipt.to_dict()
                if isinstance(self.compiler_receipt, WorkflowCompilerReceipt)
                else self.compiler_receipt
            ),
        }


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow cannot safely continue or resume."""


def _source_commitment_digest(
    draft: WorkflowDraft, commitment: Mapping[str, Any]
) -> str:
    source_fingerprint = draft.preconditions.get(
        "source_artifact_fingerprint", draft.preconditions.get("context_fingerprint")
    )
    payload: dict[str, Any] = {
        "artifact_id": str(commitment.get("artifact_id", draft.target["artifact_id"])),
        "node_ref": str(commitment.get("node_ref", draft.target["node_ref"])),
        "run_id": str(commitment.get("run_id", draft.target["run_id"])),
        "source_artifact_fingerprint": str(source_fingerprint),
    }
    if "from_step" in commitment:
        payload["from_step"] = str(commitment["from_step"])
    if "output" in commitment:
        payload["output"] = str(commitment["output"])
    if "content_sha256" in commitment:
        payload["content_sha256"] = str(commitment["content_sha256"])
    return _fingerprint(payload)


def _bounded_metadata(value: Any, *, depth: int = 0) -> Any:
    """Copy explicit workflow metadata under a strict JSON budget."""

    if depth > MAX_PERSISTED_METADATA_DEPTH:
        raise WorkflowExecutionError("workflow persisted metadata exceeds its depth bound")
    if isinstance(value, Mapping):
        if len(value) > MAX_PERSISTED_METADATA_ITEMS:
            raise WorkflowExecutionError("workflow persisted metadata exceeds its item bound")
        return {str(key): _bounded_metadata(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_PERSISTED_METADATA_ITEMS:
            raise WorkflowExecutionError("workflow persisted metadata exceeds its item bound")
        return [_bounded_metadata(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise WorkflowExecutionError("workflow persisted metadata contains an unsupported value")


def _validated_metadata(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkflowExecutionError(
            f"workflow step state {field_name} must be an object, got {type(value).__name__}"
        )
    copied = _bounded_metadata(value)
    encoded = json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PERSISTED_METADATA_BYTES:
        raise WorkflowExecutionError(f"workflow step state {field_name} exceeds its persistence bound")
    return copied


def _typed_output_bindings(result: "WorkflowStepResult") -> dict[str, dict[str, Any]]:
    """Normalize typed outputs while keeping legacy producers executable."""

    explicit: Any = result.output_bindings
    if not explicit:
        explicit = result.payload.get(PERSISTED_OUTPUT_BINDINGS)
    if explicit is None and PERSISTED_STEP_OUTPUT in result.payload:
        explicit = {PERSISTED_STEP_OUTPUT: result.payload[PERSISTED_STEP_OUTPUT]}
    if explicit in (None, {}):
        return {}
    if not isinstance(explicit, Mapping):
        raise WorkflowExecutionError(f"workflow {PERSISTED_OUTPUT_BINDINGS} must be an object")
    if len(explicit) > MAX_PERSISTED_OUTPUT_BINDINGS:
        raise WorkflowExecutionError("workflow step published too many output bindings")
    bindings: dict[str, dict[str, Any]] = {}
    for name, value in explicit.items():
        if not isinstance(name, str) or not name:
            raise WorkflowExecutionError("workflow output binding names must be non-empty strings")
        if not isinstance(value, Mapping):
            raise WorkflowExecutionError(f"workflow output binding {name!r} must be an object")
        binding = _validated_metadata(value, field_name=f"output binding {name}")
        binding.setdefault("binding_type", "dataset" if name == PERSISTED_STEP_OUTPUT else "workflow_output")
        bindings[name] = binding
    return bindings


def _publishable_binding(result: "WorkflowStepResult") -> dict[str, Any] | None:
    """Return the historical dataset body for in-process compatibility."""

    binding = _typed_output_bindings(result).get(PERSISTED_STEP_OUTPUT)
    if binding is None:
        return None
    return {key: value for key, value in binding.items() if key != "binding_type"}


def _persisted_lineage(result: "WorkflowStepResult") -> dict[str, Any]:
    lineage: Any = result.lineage or result.payload.get(PERSISTED_LINEAGE)
    if lineage is None and isinstance(result.payload.get("branches"), list):
        lineage = {"branches": result.payload["branches"]}
    if lineage in (None, {}):
        return {}
    return _validated_metadata(lineage, field_name=PERSISTED_LINEAGE)


def _binding_body(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in binding.items() if key != "binding_type"}


def _validated_artifact_ids(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_PERSISTED_ARTIFACT_IDS:
        raise WorkflowExecutionError("workflow artifact identity list exceeds its persistence bound")
    result = [str(item) for item in value]
    if any(not item for item in result):
        raise WorkflowExecutionError("workflow artifact identities must be non-empty strings")
    return result


def _state_lineage(
    draft: "WorkflowDraft",
    step: "WorkflowStep",
    result: "WorkflowStepResult",
    completed_results: Mapping[str, "WorkflowStepResult"],
) -> dict[str, Any]:
    lineage = _persisted_lineage(result)
    if "source_commitments" not in lineage:
        commitment = step.spec.get("source")
        if isinstance(commitment, Mapping):
            from_step = str(commitment.get("from_step", ""))
            output = str(commitment.get("output", ""))
            record: dict[str, Any] = {"from_step": from_step, "output": output}
            upstream = completed_results.get(from_step)
            if upstream is not None:
                binding = _typed_output_bindings(upstream).get(output)
                if isinstance(binding, Mapping):
                    record.update(_binding_body(binding))
            lineage["source_commitments"] = [record]
        else:
            lineage["source_commitments"] = [{
                "run_id": str(draft.target["run_id"]),
                "node_ref": str(draft.target["node_ref"]),
                "artifact_id": str(draft.target["artifact_id"]),
            }]
    source_commitments = lineage.get("source_commitments")
    if source_commitments is not None:
        if not isinstance(source_commitments, list):
            raise WorkflowExecutionError(
                "workflow persisted source_commitments must be an array"
            )
        normalized_commitments: list[dict[str, Any]] = []
        for raw_commitment in source_commitments:
            if not isinstance(raw_commitment, Mapping):
                raise WorkflowExecutionError(
                    "workflow persisted source commitment must be an object"
                )
            normalized = dict(raw_commitment)
            expected_digest = _source_commitment_digest(draft, normalized)
            supplied_digest = normalized.get("source_digest")
            if supplied_digest is not None and supplied_digest != expected_digest:
                raise WorkflowExecutionError(
                    "workflow source commitment digest does not match canonical source identity"
                )
            normalized["source_digest"] = expected_digest
            normalized_commitments.append(normalized)
        lineage["source_commitments"] = normalized_commitments
    return _validated_metadata(lineage, field_name=PERSISTED_LINEAGE)


def _restored_payload(state: "WorkflowStepState") -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if state.output_bindings:
        payload[PERSISTED_OUTPUT_BINDINGS] = {
            key: dict(value) for key, value in state.output_bindings.items()
        }
        produced = state.output_bindings.get(PERSISTED_STEP_OUTPUT)
        if produced is not None:
            payload[PERSISTED_STEP_OUTPUT] = _binding_body(produced)
    if state.lineage:
        payload[PERSISTED_LINEAGE] = dict(state.lineage)
        if isinstance(state.lineage.get("branches"), list):
            payload["branches"] = state.lineage["branches"]
    return payload


@dataclass(frozen=True)
class WorkflowStepResult:
    """Bounded result returned by one workflow step executor."""

    artifact_ids: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    empty_group_values: list[Any] = field(default_factory=list)
    result_fingerprint: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    # Explicit, typed outputs are the only values carried between workflow
    # steps and across a restart.  ``payload`` remains an in-process result
    # surface for existing adapters; it is never persisted wholesale.
    output_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    # True only for results the executor reconstructed from persisted state on
    # resume, never for one an executor just returned. A consumer that cannot
    # find what it needs has to tell the two apart: an absent binding on a live
    # result means the upstream published nothing, while on a restored result it
    # means the state record did not carry it, and the upstream is blameless.
    restored_from_state: bool = False


@dataclass(frozen=True)
class WorkflowStepState:
    step_id: str
    fingerprint: str
    status: str = "pending"
    artifact_ids: tuple[str, ...] = ()
    row_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    result_fingerprint: str | None = None
    output_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    # Compatibility view for callers that still inspect the old field. New
    # records write only the typed map; old records are normalized on read.
    produced_dataset: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        bindings = self.output_bindings
        if not bindings and self.produced_dataset is not None:
            bindings = {
                PERSISTED_STEP_OUTPUT: {
                    "binding_type": "dataset",
                    **dict(self.produced_dataset),
                }
            }
        normalized_bindings = {
            key: _validated_metadata(value, field_name=f"output binding {key}")
            for key, value in bindings.items()
        }
        return {
            "step_id": self.step_id,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "artifact_ids": _validated_artifact_ids(self.artifact_ids),
            "row_counts": dict(self.row_counts),
            "error": self.error,
            "result_fingerprint": self.result_fingerprint,
            PERSISTED_OUTPUT_BINDINGS: {
                key: dict(value) for key, value in normalized_bindings.items()
            },
            PERSISTED_LINEAGE: _validated_metadata(self.lineage, field_name=PERSISTED_LINEAGE),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowStepState":
        raw_bindings = value.get(PERSISTED_OUTPUT_BINDINGS)
        produced = value.get(PERSISTED_STEP_OUTPUT)
        if raw_bindings is not None and produced is not None and not isinstance(produced, Mapping):
            raise WorkflowExecutionError(
                f"workflow step state {value.get('step_id')!r} carries a malformed legacy "
                f"{PERSISTED_STEP_OUTPUT} alias"
            )
        if raw_bindings is None:
            # Historical state had one untyped dataset block.  Normalize it
            # without making old workflow files unreadable.
            if produced is None:
                bindings: dict[str, dict[str, Any]] = {}
            else:
                if not isinstance(produced, Mapping):
                    raise WorkflowExecutionError(
                        f"workflow step state {value.get('step_id')!r} carries a "
                        f"{PERSISTED_STEP_OUTPUT} that must be an object, got "
                        f"{type(produced).__name__}"
                    )
                bindings = {PERSISTED_STEP_OUTPUT: {"binding_type": "dataset", **dict(produced)}}
        else:
            if not isinstance(raw_bindings, Mapping):
                raise WorkflowExecutionError(
                    f"workflow step state {value.get('step_id')!r} carries "
                    f"{PERSISTED_OUTPUT_BINDINGS} that must be an object, got "
                    f"{type(raw_bindings).__name__}"
                )
            if len(raw_bindings) > MAX_PERSISTED_OUTPUT_BINDINGS:
                raise WorkflowExecutionError("workflow step state carries too many output bindings")
            bindings = {}
            for name, binding in raw_bindings.items():
                if not isinstance(name, str) or not name or not isinstance(binding, Mapping):
                    raise WorkflowExecutionError("workflow step state contains an invalid output binding")
                normalized = _validated_metadata(binding, field_name=f"output binding {name}")
                if "binding_type" not in normalized:
                    raise WorkflowExecutionError(f"workflow output binding {name!r} lacks binding_type")
                bindings[name] = normalized
            if isinstance(produced, Mapping) and PERSISTED_STEP_OUTPUT in bindings:
                if _binding_body(bindings[PERSISTED_STEP_OUTPUT]) != dict(produced):
                    raise WorkflowExecutionError(
                        "workflow step state has conflicting typed and legacy output bindings"
                    )
        raw_lineage = value.get(PERSISTED_LINEAGE) or {}
        lineage = _validated_metadata(raw_lineage, field_name=PERSISTED_LINEAGE)
        legacy = bindings.get(PERSISTED_STEP_OUTPUT)
        return cls(
            step_id=str(value["step_id"]),
            fingerprint=str(value["fingerprint"]),
            status=str(value.get("status", "pending")),
            artifact_ids=tuple(_validated_artifact_ids(value.get("artifact_ids", []))),
            row_counts={str(key): int(item) for key, item in (value.get("row_counts") or {}).items()},
            error=value.get("error"),
            result_fingerprint=value.get("result_fingerprint"),
            output_bindings=bindings,
            lineage=lineage,
            produced_dataset=_binding_body(legacy) if legacy is not None else None,
        )


@dataclass(frozen=True)
class WorkflowExecutionState:
    workflow_id: str
    plan_fingerprint: str
    status: str
    steps: dict[str, WorkflowStepState]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "workflow_state",
            "workflow_id": self.workflow_id,
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
            "steps": {key: value.to_dict() for key, value in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowExecutionState":
        return cls(
            workflow_id=str(value["workflow_id"]),
            plan_fingerprint=str(value["plan_fingerprint"]),
            status=str(value.get("status", "planned")),
            steps={
                str(key): WorkflowStepState.from_dict(item)
                for key, item in (value.get("steps") or {}).items()
            },
        )


class WorkflowStateStore:
    """Append-only workflow execution state used for resumable runs."""

    def __init__(self, project_root: Path | str, workflow_id: str) -> None:
        if not workflow_id or Path(workflow_id).name != workflow_id:
            raise ValueError("workflow_id must be path-safe")
        self.path = Path(project_root) / "workbench" / "workflows" / f"{workflow_id}.jsonl"

    def append(self, state: WorkflowExecutionState) -> None:
        append_jsonl_atomic(self.path, state.to_dict())

    def current(self) -> WorkflowExecutionState | None:
        records = [item for item in read_jsonl(self.path) if item.get("record_type") == "workflow_state"]
        return WorkflowExecutionState.from_dict(records[-1]) if records else None


class WorkflowExecutor:
    """Execute a compiled workflow with fail-closed dependencies and resume."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)

    def execute(
        self,
        draft: WorkflowDraft,
        step_executor,
        *,
        evidence_port=None,
        host_endpoint=None,
    ) -> WorkflowExecutionState:
        from .workflow_runtime import (
            EvidencePersistencePort,
            WorkflowAdmissionReceipt,
            _ReceiptGatedWorkflowExecutor,
            issue_server_evidence_port,
        )

        if evidence_port is None:
            evidence_port = issue_server_evidence_port(
                self.project_root, host_endpoint
            )
        elif host_endpoint is not None:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_PORT_CONFLICT: provide either evidence_port or host_endpoint, not both"
            )
        if type(evidence_port) is not EvidencePersistencePort:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_PORT_REQUIRED: execution requires the server EvidencePersistencePort"
            )
        evidence_port.require_server_host()
        # Reject forged or stale compiler authority before constructing the
        # state store. A missing admission receipt must not even create a
        # workflow state record, let alone call the step executor.
        evidence_port.require_server_draft(draft)
        if type(step_executor) is not _ReceiptGatedWorkflowExecutor:
            raise WorkflowExecutionError(
                "WORKFLOW_RECEIPT_GATED_CALLBACK_REQUIRED: workflow execution requires "
                "the server receipt-gated callback"
            )
        step_executor._bind_evidence_port(evidence_port)
        store = WorkflowStateStore(self.project_root, draft.workflow_id)
        existing = store.current()
        if existing is not None and existing.plan_fingerprint != draft.plan_fingerprint:
            raise WorkflowExecutionError("source fingerprint changed; workflow plan cannot resume")

        states: dict[str, WorkflowStepState] = {}
        if existing is not None:
            for step in draft.steps:
                previous = existing.steps.get(step.step_id)
                if previous is not None and previous.status == "completed":
                    if previous.fingerprint != step.fingerprint:
                        raise WorkflowExecutionError(
                            "source fingerprint changed; completed step cannot be reused"
                        )
                    states[step.step_id] = previous
                    continue
                states[step.step_id] = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                )
        else:
            states = {
                step.step_id: WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                )
                for step in draft.steps
            }

        state = WorkflowExecutionState(
            workflow_id=draft.workflow_id,
            plan_fingerprint=draft.plan_fingerprint,
            status="running",
            steps=states,
        )
        log = ExplorationLog(self.project_root, workflow_id=draft.workflow_id)
        completed_results: dict[str, WorkflowStepResult] = {
            step_id: WorkflowStepResult(
                artifact_ids=list(step_state.artifact_ids),
                row_counts=dict(step_state.row_counts),
                result_fingerprint=(
                    step_state.result_fingerprint or step_state.fingerprint
                ),
                # Rebuilt from persisted state, so only what the state carries
                # is available here -- never the payload the step returned in
                # the earlier pass, which died with that process.
                # `is not None`, matching `from_dict`: absence and emptiness are
                # one question, and answering it two ways in two places is how
                # the halves of a round trip drift apart.
                payload=_restored_payload(step_state),
                output_bindings={
                    key: dict(value) for key, value in step_state.output_bindings.items()
                },
                lineage=dict(step_state.lineage),
                restored_from_state=True,
            )
            for step_id, step_state in states.items()
            if step_state.status == "completed"
        }

        for step in draft.steps:
            current = states[step.step_id]
            if current.status == "completed":
                continue
            dependency_states = [states[dependency] for dependency in step.depends_on]
            if any(item.status in {"failed", "blocked"} for item in dependency_states):
                states[step.step_id] = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="blocked",
                    error="dependency failed or was blocked",
                )
                state = self._persist_state(store, draft, states, "failed")
                self._log_transition(log, draft, step, states[step.step_id], states)
                continue
            if any(item.status != "completed" for item in dependency_states):
                raise WorkflowExecutionError(
                    f"workflow dependency is not complete for {step.step_id}"
                )

            running = WorkflowStepState(
                step_id=step.step_id,
                fingerprint=step.fingerprint,
                status="running",
            )
            states[step.step_id] = running
            receipt = evidence_port.admit(draft, step)
            if type(receipt) is not WorkflowAdmissionReceipt:
                raise WorkflowExecutionError(
                    "WORKFLOW_ADMISSION_RECEIPT_REQUIRED: admission did not return a server receipt"
                )
            evidence_port.require_receipt(receipt)
            state = self._persist_state(store, draft, states, "running")
            self._log_transition(log, draft, step, running, states)
            try:
                result = receipt.completed_result
                if result is None:
                    result = step_executor(
                        step,
                        completed_results,
                        admission_receipt=receipt,
                    )
                if not isinstance(result, WorkflowStepResult):
                    raise WorkflowExecutionError(
                        f"workflow step {step.step_id} returned an invalid result"
                    )
                if result.empty_group_values:
                    raise WorkflowExecutionError(
                        f"workflow step {step.step_id} produced empty group values: "
                        + ", ".join(str(value) for value in result.empty_group_values)
                    )
                output_bindings = _typed_output_bindings(result)
                lineage = _state_lineage(draft, step, result, completed_results)
                normalized_result = WorkflowStepResult(
                    artifact_ids=list(result.artifact_ids),
                    row_counts=dict(result.row_counts),
                    empty_group_values=list(result.empty_group_values),
                    result_fingerprint=result.result_fingerprint,
                    payload=dict(result.payload),
                    output_bindings=output_bindings,
                    lineage=lineage,
                    restored_from_state=result.restored_from_state,
                )
                evidence_port.complete(receipt, normalized_result)
                completed = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="completed",
                    artifact_ids=tuple(result.artifact_ids),
                    row_counts=dict(result.row_counts),
                    result_fingerprint=(result.result_fingerprint or step.fingerprint),
                    output_bindings=output_bindings,
                    lineage=lineage,
                    produced_dataset=_publishable_binding(normalized_result),
                )
                states[step.step_id] = completed
                completed_results[step.step_id] = normalized_result
                state = self._persist_state(store, draft, states, "running")
                self._log_transition(log, draft, step, completed, states)
            except Exception as exc:
                evidence_port.abort(receipt, str(exc))
                failed = WorkflowStepState(
                    step_id=step.step_id,
                    fingerprint=step.fingerprint,
                    status="failed",
                    error=str(exc),
                )
                states[step.step_id] = failed
                self._persist_state(store, draft, states, "failed")
                self._log_transition(log, draft, step, failed, states)
                changed = True
                while changed:
                    changed = False
                    for dependent in draft.steps:
                        if states[dependent.step_id].status != "pending":
                            continue
                        if any(
                            states[dependency].status in {"failed", "blocked"}
                            for dependency in dependent.depends_on
                        ):
                            states[dependent.step_id] = WorkflowStepState(
                                step_id=dependent.step_id,
                                fingerprint=dependent.fingerprint,
                                status="blocked",
                                error="dependency failed or was blocked",
                            )
                            self._log_transition(
                                log,
                                draft,
                                dependent,
                                states[dependent.step_id],
                                states,
                            )
                            changed = True
                break

        status = "failed" if any(item.status in {"failed", "blocked"} for item in states.values()) else "completed"
        return self._persist_state(store, draft, states, status)

    @staticmethod
    def _persist_state(store, draft, states, status):
        state = WorkflowExecutionState(
            workflow_id=draft.workflow_id,
            plan_fingerprint=draft.plan_fingerprint,
            status=status,
            steps=dict(states),
        )
        store.append(state)
        return state

    @staticmethod
    def _log_transition(log, draft, step, state, states) -> None:
        dependency_artifacts = [
            artifact_id
            for dependency in step.depends_on
            for artifact_id in states[dependency].artifact_ids
        ]
        log.append_event(
            {
                "event_id": f"{step.step_id}:{state.status}:{state.fingerprint[:16]}",
                "workflow_id": draft.workflow_id,
                "workflow_step_id": step.step_id,
                "operation_id": f"{step.operation_id}@{step.operation_version}",
                "spec_fingerprint": step.fingerprint,
                "source_artifact_ids": [str(draft.target["artifact_id"])],
                "dependency_artifact_ids": dependency_artifacts,
                "row_counts": state.row_counts,
                "status": state.status,
                "error": state.error,
                "artifact_ids": list(state.artifact_ids),
                "dependency_fingerprints": [
                    states[dependency].result_fingerprint
                    or states[dependency].fingerprint
                    for dependency in step.depends_on
                ],
            }
        )


def _make_step(
    *,
    step_id: str,
    operation_id: str,
    depends_on: tuple[WorkflowStep, ...],
    spec: dict[str, Any],
    expected_artifacts: tuple[str, ...],
) -> WorkflowStep:
    dependency_ids = tuple(step.step_id for step in depends_on)
    identity = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "step_id": step_id,
        "operation_id": operation_id,
        "operation_version": "v1",
        "depends_on": list(dependency_ids),
        "dependency_fingerprints": [step.fingerprint for step in depends_on],
        "spec": spec,
        "expected_artifacts": list(expected_artifacts),
    }
    return WorkflowStep(
        step_id=step_id,
        operation_id=operation_id,
        operation_version="v1",
        depends_on=dependency_ids,
        spec=spec,
        expected_artifacts=expected_artifacts,
        fingerprint=_fingerprint(identity),
    )


def compile_workflow(
    *,
    workflow_id: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    steps: Any,
    available_columns: list[str] | tuple[str, ...] | None = None,
    workflow_template: str = "agent-composed-v1",
) -> WorkflowDraft:
    """Compile an Agent-composed plan of arbitrary shape.

    The server owns the step KINDS and validates every spec with the same
    validators the manual UI uses; the plan's length, ordering and column
    choices belong to the request being answered, not to any one assignment.
    """

    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise OperationValidationError("workflow_id must be a non-empty string")
    missing_target = {
        key for key in ("run_id", "node_ref", "artifact_id") if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            "workflow target missing: " + ", ".join(sorted(missing_target))
        )
    if not preconditions.get("context_fingerprint"):
        raise OperationValidationError("workflow source context_fingerprint is required")

    ordered = validate_workflow_steps(steps, available_columns=available_columns)
    source_artifact_fingerprint = str(
        preconditions.get("source_artifact_fingerprint")
        or preconditions["context_fingerprint"]
    )

    compiled: dict[str, WorkflowStep] = {}
    for entry in ordered:
        compiled[entry["step_id"]] = _make_step(
            step_id=entry["step_id"],
            operation_id=entry["operation_id"],
            depends_on=tuple(compiled[dep] for dep in entry["depends_on"]),
            spec={
                **entry["spec"],
                "source_artifact_fingerprint": source_artifact_fingerprint,
            },
            expected_artifacts=tuple(entry["expected_artifacts"]),
        )
    compiled_steps = tuple(compiled[entry["step_id"]] for entry in ordered)
    plan_fingerprint = _fingerprint(
        {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "workflow_template": workflow_template,
            "target": dict(target),
            "preconditions": dict(preconditions),
            "bindings": {},
            "steps": [step.to_dict() for step in compiled_steps],
        }
    )
    return WorkflowDraft(
        workflow_id=workflow_id,
        workflow_template=workflow_template,
        target=dict(target),
        preconditions=dict(preconditions),
        bindings={},
        steps=compiled_steps,
        plan_fingerprint=plan_fingerprint,
        compiler_authority=SERVER_COMPILER_AUTHORITY,
        compiler_receipt=_issue_workflow_compiler_receipt(
            workflow_id=workflow_id,
            plan_fingerprint=plan_fingerprint,
            target=target,
            preconditions=preconditions,
            workflow_template=workflow_template,
            bindings={},
            steps=compiled_steps,
        ),
    )


def execute_workflow(
    project_root: Path | str,
    draft: WorkflowDraft,
    *,
    custom_step_executor=None,
    evidence_port=None,
    host_endpoint=None,
) -> WorkflowExecutionState:
    """Execute a compiled workflow plan using native Workbench services.

    A custom capability gateway is opt-in and must already be bound to the
    existing authorization and containment lifecycle.
    """

    from .workflow_runtime import (
        EvidencePersistencePort,
        build_workflow_step_executor,
        issue_server_evidence_port,
    )

    if evidence_port is None:
        evidence_port = issue_server_evidence_port(project_root, host_endpoint)
    elif host_endpoint is not None:
        raise WorkflowExecutionError(
            "WORKFLOW_EVIDENCE_PORT_CONFLICT: provide either evidence_port or host_endpoint, not both"
        )

    return WorkflowExecutor(project_root).execute(
        draft,
        build_workflow_step_executor(
            project_root,
            draft,
            custom_step_executor=custom_step_executor,
            evidence_port=evidence_port,
        ),
        evidence_port=evidence_port,
    )


__all__ = [
    "PERSISTED_STEP_OUTPUT",
    "PERSISTED_OUTPUT_BINDINGS",
    "PERSISTED_LINEAGE",
    "SERVER_COMPILER_AUTHORITY",
    "WORKFLOW_SCHEMA_VERSION",
    "WorkflowDraft",
    "WorkflowCompilerReceipt",
    "WorkflowExecutionError",
    "WorkflowExecutionState",
    "WorkflowExecutor",
    "WorkflowStateStore",
    "WorkflowStepResult",
    "WorkflowStep",
    "compile_workflow",
    "execute_workflow",
]
