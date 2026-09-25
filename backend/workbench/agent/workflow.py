"""Server-owned compilation and execution contracts for step workflows."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import fcntl
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..exploration_log import ExplorationLog
from .operations import OperationValidationError
from .workflow_contracts import WORKFLOW_TEMPLATE, validate_workflow_steps


# Written into every plan record. Workflow execution state has its own exact
# version gate below because a resumed callback can consume persisted output
# bindings and evidence receipts. A missing or unknown execution-state schema
# must never be normalized into the current runtime.
WORKFLOW_SCHEMA_VERSION = "workflow.v1"
WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION = "workflow-execution-state.v1.8.9"

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
# State is append-only, but a corrupted or hostile file must not turn Resume
# into an unbounded memory/CPU read.  These are deployment-independent format
# limits, not a claim about the maximum size of a statistical result artifact.
MAX_WORKFLOW_STATE_BYTES = 16 * 1024 * 1024
MAX_WORKFLOW_STATE_RECORDS = 4096
# Counts cross the Python/JSON/TypeScript boundary.  Keep them bounded rather
# than allowing Python's arbitrary-precision integers to become unbounded
# persisted metadata.
MAX_PERSISTED_ROW_COUNT = 2**63 - 1
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
    project_ref: str | None = None
    session_ref: str | None = None

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
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "compiler_authority": self.compiler_authority,
            "compiler_receipt": (
                self.compiler_receipt.to_dict()
                if isinstance(self.compiler_receipt, WorkflowCompilerReceipt)
                else self.compiler_receipt
            ),
        }


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow cannot safely continue or resume."""


class UnsupportedVersionError(WorkflowExecutionError):
    """Raised when persisted workflow state is not the current exact contract."""

    code = "UNSUPPORTED_VERSION"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


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


def _validated_model_branch_ids(value: Any) -> dict[str, tuple[str, ...]]:
    """Validate the explicit model-branch identity index carried by Resume."""

    if not isinstance(value, Mapping) or len(value) > MAX_PERSISTED_OUTPUT_BINDINGS:
        raise WorkflowExecutionError("workflow model branch identity index is invalid")
    normalized: dict[str, tuple[str, ...]] = {}
    for step_id, branch_ids in value.items():
        if type(step_id) is not str or not step_id:
            raise WorkflowExecutionError(
                "workflow model branch identity index contains an invalid step id"
            )
        if not isinstance(branch_ids, (list, tuple)) or not branch_ids:
            raise WorkflowExecutionError(
                f"workflow model branch identity index for {step_id!r} is invalid"
            )
        if len(branch_ids) > MAX_PERSISTED_ARTIFACT_IDS:
            raise WorkflowExecutionError(
                "workflow model branch identity index exceeds its persistence bound"
            )
        ids = tuple(str(branch_id) for branch_id in branch_ids)
        if any(not branch_id for branch_id in ids) or len(set(ids)) != len(ids):
            raise WorkflowExecutionError(
                f"workflow model branch identity index for {step_id!r} is not unique"
            )
        normalized[step_id] = ids
    return normalized


def _model_branch_ids(states: Mapping[str, "WorkflowStepState"]) -> dict[str, tuple[str, ...]]:
    """Derive the Resume branch identity index from typed completed outputs."""

    result: dict[str, tuple[str, ...]] = {}
    for step_id, state in states.items():
        binding = state.output_bindings.get("model_branches")
        branches = binding.get("branches") if isinstance(binding, Mapping) else None
        if not isinstance(branches, list) or not branches:
            continue
        branch_ids: list[str] = []
        for branch in branches:
            if not isinstance(branch, Mapping) or type(branch.get("branch_id")) is not str:
                raise WorkflowExecutionError(
                    f"workflow step {step_id!r} has an invalid model branch identity"
                )
            branch_ids.append(branch["branch_id"])
        result[step_id] = tuple(branch_ids)
    return result


def _validated_persisted_row_counts(
    value: Any, *, field_name: str = "row_counts"
) -> dict[str, int]:
    """Parse persisted counts without leaking conversion or overflow errors."""

    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise WorkflowExecutionError(
            f"workflow step state {field_name} must be an object, got {type(value).__name__}"
        )
    normalized: dict[str, int] = {}
    for key, count in value.items():
        if type(key) is not str or not key:
            raise WorkflowExecutionError(
                f"workflow step state {field_name} contains an invalid key"
            )
        if (
            type(count) is not int
            or count < 0
            or count > MAX_PERSISTED_ROW_COUNT
        ):
            raise WorkflowExecutionError(
                f"workflow step state {field_name} contains an invalid count"
            )
        normalized[key] = count
    return normalized


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
            row_counts=_validated_persisted_row_counts(value.get("row_counts")),
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
    schema_version: str = WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION
    project_ref: str | None = None
    session_ref: str | None = None
    model_branch_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "workflow_state",
            "schema_version": WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION,
            "workflow_id": self.workflow_id,
            "plan_fingerprint": self.plan_fingerprint,
            "status": self.status,
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "model_branch_ids": {
                step_id: list(branch_ids)
                for step_id, branch_ids in _validated_model_branch_ids(
                    self.model_branch_ids
                ).items()
            },
            "steps": {key: value.to_dict() for key, value in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowExecutionState":
        if not isinstance(value, Mapping):
            raise UnsupportedVersionError("UNSUPPORTED_VERSION: workflow execution state is not an object")
        schema_version = value.get("schema_version")
        if schema_version != WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION:
            supplied = "missing" if schema_version is None else repr(schema_version)
            raise UnsupportedVersionError(
                "UNSUPPORTED_VERSION: workflow execution state schema "
                f"{supplied} is not {WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION}"
            )
        required_identity_fields = ("project_ref", "session_ref", "model_branch_ids")
        if any(field_name not in value for field_name in required_identity_fields):
            raise UnsupportedVersionError(
                "UNSUPPORTED_VERSION: workflow execution state lacks the v1.8.9 "
                "Resume identity and model-branch fields"
            )
        project_ref = value.get("project_ref")
        session_ref = value.get("session_ref")
        if project_ref is not None and (
            type(project_ref) is not str or not project_ref.strip()
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_STATE_CORRUPT: project_ref is invalid"
            )
        if session_ref is not None and (
            type(session_ref) is not str or not session_ref.strip()
        ):
            raise WorkflowExecutionError(
                "WORKFLOW_STATE_CORRUPT: session_ref is invalid"
            )
        model_branch_ids = _validated_model_branch_ids(value.get("model_branch_ids"))
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, Mapping):
            raise WorkflowExecutionError("WORKFLOW_STATE_CORRUPT: workflow steps must be an object")
        normalized_steps: dict[str, WorkflowStepState] = {}
        for key, item in raw_steps.items():
            if type(key) is not str or not isinstance(item, Mapping):
                raise WorkflowExecutionError("WORKFLOW_STATE_CORRUPT: workflow step identity is invalid")
            if item.get("step_id") != key:
                raise WorkflowExecutionError(
                    "WORKFLOW_STATE_CORRUPT: persisted step key does not match step_id"
                )
            normalized_steps[key] = WorkflowStepState.from_dict(item)
        return cls(
            workflow_id=str(value["workflow_id"]),
            plan_fingerprint=str(value["plan_fingerprint"]),
            status=str(value.get("status", "planned")),
            steps=normalized_steps,
            schema_version=schema_version,
            project_ref=project_ref,
            session_ref=session_ref,
            model_branch_ids=model_branch_ids,
        )


class WorkflowStateStore:
    """FD-admitted append-only workflow state used for resumable runs."""

    def __init__(
        self,
        project_root: Path | str,
        workflow_id: str,
        *,
        evidence_port: object | None = None,
    ) -> None:
        if not workflow_id or Path(workflow_id).name != workflow_id:
            raise ValueError("workflow_id must be path-safe")
        root = Path(project_root).expanduser().resolve(strict=False)
        self.path = root / "workbench" / "workflows" / f"{workflow_id}.jsonl"
        self._owner_pid = os.getpid()
        self._workflow_root_fd = -1
        if evidence_port is not None:
            from .workflow_runtime import EvidencePersistencePort

            if type(evidence_port) is not EvidencePersistencePort:
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_PORT_REQUIRED: state store requires the server evidence port"
                )
            evidence_port._require_server_host()
            endpoint_root = Path(evidence_port.project_root).expanduser().resolve(strict=False)
            if endpoint_root != root:
                raise WorkflowExecutionError(
                    "WORKFLOW_SCOPE_MISMATCH: workflow state root does not match the server evidence port"
                )
            source_fd = getattr(evidence_port, "_host_endpoint_fd", None)
            if type(source_fd) is not int or source_fd < 0:
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store endpoint fd is unavailable"
                )
            try:
                self._workflow_root_fd = os.dup(source_fd)
            except OSError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store endpoint fd could not be retained"
                ) from exc
        else:
            # Direct package callers are still required to pass through the
            # local bootstrap seam on the verified Darwin host. This keeps
            # focused state tests usable without reintroducing a pathname
            # writer into the product execution path.
            from .workflow_runtime import bootstrap_local_workflow_host

            endpoint = bootstrap_local_workflow_host(root)
            try:
                self._workflow_root_fd = os.dup(endpoint.workflow_evidence_root_fd)
            except OSError as exc:
                raise WorkflowExecutionError(
                    "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: local state store endpoint fd is unavailable"
                ) from exc
        try:
            root_stat = os.fstat(self._workflow_root_fd)
        except OSError as exc:
            self.close()
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store root is unavailable"
            ) from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            self.close()
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store root is not a directory"
            )

    def append(self, state: WorkflowExecutionState) -> None:
        self._require_open()
        if type(state) is not WorkflowExecutionState:
            raise TypeError("workflow state store accepts only WorkflowExecutionState")
        raw = (
            json.dumps(
                state.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        lock_fd = os.dup(self._workflow_root_fd)
        state_fd = -1
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            state_fd = os.open(
                self.path.name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_APPEND
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=self._workflow_root_fd,
            )
            if not stat.S_ISREG(os.fstat(state_fd).st_mode):
                raise WorkflowExecutionError("WORKFLOW_STATE_PATH_INVALID: state file is not regular")
            offset = 0
            while offset < len(raw):
                offset += os.write(state_fd, raw[offset:])
            os.fsync(state_fd)
        except WorkflowExecutionError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_STATE_WRITE_FAILED: workflow state could not be persisted safely"
            ) from exc
        finally:
            if state_fd >= 0:
                os.close(state_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def current(self) -> WorkflowExecutionState | None:
        self._require_open()
        lock_fd = os.dup(self._workflow_root_fd)
        state_fd = -1
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            state_fd = os.open(
                self.path.name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=self._workflow_root_fd,
            )
            if not stat.S_ISREG(os.fstat(state_fd).st_mode):
                raise WorkflowExecutionError("WORKFLOW_STATE_PATH_INVALID: state file is not regular")
            file_size = os.fstat(state_fd).st_size
            if file_size > MAX_WORKFLOW_STATE_BYTES:
                raise WorkflowExecutionError(
                    "WORKFLOW_STATE_TOO_LARGE: workflow state file exceeds its bounded size"
                )
            with os.fdopen(state_fd, "rb", closefd=True) as handle:
                state_fd = -1
                raw = handle.read(MAX_WORKFLOW_STATE_BYTES + 1)
            if len(raw) > MAX_WORKFLOW_STATE_BYTES:
                raise WorkflowExecutionError(
                    "WORKFLOW_STATE_TOO_LARGE: workflow state file exceeds its bounded size"
                )
        except FileNotFoundError:
            return None
        except WorkflowExecutionError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_STATE_READ_FAILED: workflow state could not be read safely"
            ) from exc
        finally:
            if state_fd >= 0:
                os.close(state_fd)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        records: list[Mapping[str, Any]] = []
        record_count = 0
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            record_count += 1
            if record_count > MAX_WORKFLOW_STATE_RECORDS:
                raise WorkflowExecutionError(
                    "WORKFLOW_STATE_TOO_LARGE: workflow state contains too many records"
                )
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkflowExecutionError(
                    f"WORKFLOW_STATE_CORRUPT: invalid JSON at line {line_number}"
                ) from exc
            if not isinstance(value, Mapping) or value.get("record_type") != "workflow_state":
                continue
            records.append(value)
        return WorkflowExecutionState.from_dict(records[-1]) if records else None

    def _require_open(self) -> None:
        if self._owner_pid != os.getpid() or self._workflow_root_fd < 0:
            raise WorkflowExecutionError(
                "WORKFLOW_PROCESS_BOUNDARY: workflow state store belongs to another process"
            )
        try:
            identity = os.fstat(self._workflow_root_fd)
        except OSError as exc:
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store root is unavailable"
            ) from exc
        if not stat.S_ISDIR(identity.st_mode):
            raise WorkflowExecutionError(
                "WORKFLOW_EVIDENCE_HOST_ENDPOINT_REQUIRED: state store root is not a directory"
            )

    def close(self) -> None:
        fd = getattr(self, "_workflow_root_fd", -1)
        self._workflow_root_fd = -1
        if isinstance(fd, int) and fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass

    def __del__(self) -> None:
        self.close()


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
        store = WorkflowStateStore(
            self.project_root,
            draft.workflow_id,
            evidence_port=evidence_port,
        )
        existing = store.current()
        if existing is not None:
            if existing.workflow_id != draft.workflow_id:
                raise WorkflowExecutionError(
                    "WORKFLOW_SCOPE_MISMATCH: persisted workflow identity cannot resume this draft"
                )
            if existing.plan_fingerprint != draft.plan_fingerprint:
                raise WorkflowExecutionError("source fingerprint changed; workflow plan cannot resume")
            if (
                existing.project_ref != draft.project_ref
                or existing.session_ref != draft.session_ref
            ):
                raise WorkflowExecutionError(
                    "WORKFLOW_SCOPE_MISMATCH: persisted project/session binding cannot resume this draft"
                )

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

        if existing is not None and existing.model_branch_ids != _model_branch_ids(states):
            raise WorkflowExecutionError(
                "WORKFLOW_RESUME_AUTHORITY_REQUIRED: persisted model branch identity index does not match typed outputs"
            )

        state = WorkflowExecutionState(
            workflow_id=draft.workflow_id,
            plan_fingerprint=draft.plan_fingerprint,
            status="running",
            steps=states,
            project_ref=draft.project_ref,
            session_ref=draft.session_ref,
            model_branch_ids=_model_branch_ids(states),
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

        # A persisted state record is only a resume hint.  Before any
        # dependent callback is admitted, rebind every completed step to its
        # sealed server completion, unique admission, and frozen artifact
        # registry rows.  The returned result is rebuilt from that server
        # record, so tampered state metadata cannot reach a callback.
        for step in draft.steps:
            step_state = states[step.step_id]
            if step_state.status == "completed":
                completed_results[step.step_id] = evidence_port.validate_resumed_step_state(
                    draft,
                    step,
                    step_state,
                )

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
            project_ref=draft.project_ref,
            session_ref=draft.session_ref,
            model_branch_ids=_model_branch_ids(states),
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
    bindings: Mapping[str, Any] | None = None,
    project_ref: str | None = None,
    session_ref: str | None = None,
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
    normalized_bindings = _validated_metadata(
        bindings or {}, field_name="workflow bindings"
    )
    resolved_project_ref = project_ref
    if resolved_project_ref is None:
        candidate = target.get("project_ref", preconditions.get("project_ref"))
        resolved_project_ref = candidate if isinstance(candidate, str) else None
    resolved_session_ref = session_ref
    if resolved_session_ref is None:
        candidate = target.get("session_ref", preconditions.get("session_ref"))
        resolved_session_ref = candidate if isinstance(candidate, str) else None
    for name, value in (
        ("project_ref", resolved_project_ref),
        ("session_ref", resolved_session_ref),
    ):
        if value is not None and (
            type(value) is not str or not value.strip() or "\x00" in value
        ):
            raise OperationValidationError(
                f"workflow {name} must be a non-empty string when provided"
            )
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
            "bindings": normalized_bindings,
            "steps": [step.to_dict() for step in compiled_steps],
        }
    )
    return WorkflowDraft(
        workflow_id=workflow_id,
        workflow_template=workflow_template,
        target=dict(target),
        preconditions=dict(preconditions),
        bindings=normalized_bindings,
        steps=compiled_steps,
        plan_fingerprint=plan_fingerprint,
        project_ref=resolved_project_ref,
        session_ref=resolved_session_ref,
        compiler_authority=SERVER_COMPILER_AUTHORITY,
        compiler_receipt=_issue_workflow_compiler_receipt(
            workflow_id=workflow_id,
            plan_fingerprint=plan_fingerprint,
            target=target,
            preconditions=preconditions,
            workflow_template=workflow_template,
            bindings=normalized_bindings,
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
    "MAX_WORKFLOW_STATE_BYTES",
    "MAX_WORKFLOW_STATE_RECORDS",
    "SERVER_COMPILER_AUTHORITY",
    "WORKFLOW_SCHEMA_VERSION",
    "WORKFLOW_EXECUTION_STATE_SCHEMA_VERSION",
    "WorkflowDraft",
    "WorkflowCompilerReceipt",
    "WorkflowExecutionError",
    "UnsupportedVersionError",
    "WorkflowExecutionState",
    "WorkflowExecutor",
    "WorkflowStateStore",
    "WorkflowStepResult",
    "WorkflowStep",
    "compile_workflow",
    "execute_workflow",
]
