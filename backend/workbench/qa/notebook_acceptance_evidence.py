"""Collect P7 browser acceptance evidence from durable Notebook records.

The acceptance ledger never treats caller-authored identity strings as proof.
This module cross-checks the visible confirmation observation and captured DOM
bytes against the Notebook option journal, Agent trace, workflow terminal
state, artifact index, workflow receipt, and produced P7 artifact bytes.  The
local QA operator remains a trust boundary; the digest is an audit-integrity
check, not remote attestation of a human identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow_contracts import validate_workflow_steps
from workbench.qa.p7_acceptance import CompletionAuthority, CompletionEvidence
from workbench.qa.witness import (
    BrowserWitnessAttestation,
    WitnessChallenge,
    WitnessError,
    WitnessVerifier,
    WITNESS_CHALLENGE_TTL_SECONDS,
    verify_witness_attestation,
)


_ID = re.compile(r"[A-Za-z0-9_.:-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OBSERVATION_SCHEMA = "workbench.p7-browser-confirmation/v1"
_MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024


class NotebookAcceptanceEvidenceError(ValueError):
    """Raised when the durable Notebook chain cannot prove completion."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _workflow_fingerprint(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _recompute_workflow_identity(
    *,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> tuple[str, dict[str, str]]:
    """Independently bind a durable proposal to its compiled workflow identity."""

    try:
        ordered = validate_workflow_steps(changes.get("steps"))
    except OperationValidationError as error:
        raise NotebookAcceptanceEvidenceError(
            "durable workflow proposal cannot be validated"
        ) from error
    source_fingerprint = preconditions.get("source_artifact_fingerprint") or preconditions.get(
        "context_fingerprint"
    )
    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise NotebookAcceptanceEvidenceError(
            "durable workflow proposal has no source fingerprint"
        )
    workflow_template = changes.get("workflow_template", "agent-composed-v1")
    if not isinstance(workflow_template, str) or not workflow_template:
        raise NotebookAcceptanceEvidenceError(
            "durable workflow proposal has an invalid workflow template"
        )

    compiled: dict[str, dict[str, Any]] = {}
    step_fingerprints: dict[str, str] = {}
    for entry in ordered:
        dependency_fingerprints = [
            step_fingerprints[dependency] for dependency in entry["depends_on"]
        ]
        spec = {
            **entry["spec"],
            "source_artifact_fingerprint": source_fingerprint,
        }
        identity = {
            "schema_version": "workflow.v1",
            "step_id": entry["step_id"],
            "operation_id": entry["operation_id"],
            "operation_version": "v1",
            "depends_on": list(entry["depends_on"]),
            "dependency_fingerprints": dependency_fingerprints,
            "spec": spec,
            "expected_artifacts": list(entry["expected_artifacts"]),
        }
        fingerprint = _workflow_fingerprint(identity)
        step_fingerprints[entry["step_id"]] = fingerprint
        compiled[entry["step_id"]] = {
            "step_id": entry["step_id"],
            "operation_id": entry["operation_id"],
            "operation_version": "v1",
            "depends_on": list(entry["depends_on"]),
            "spec": spec,
            "expected_artifacts": list(entry["expected_artifacts"]),
            "fingerprint": fingerprint,
        }
    plan_fingerprint = _workflow_fingerprint(
        {
            "schema_version": "workflow.v1",
            "workflow_template": workflow_template,
            "target": dict(target),
            "steps": [compiled[entry["step_id"]] for entry in ordered],
        }
    )
    return plan_fingerprint, step_fingerprints


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise NotebookAcceptanceEvidenceError(f"{label} must be non-empty text")
    return value


def _safe_id(value: object, label: str) -> str:
    text = _required_text(value, label)
    if _ID.fullmatch(text) is None:
        raise NotebookAcceptanceEvidenceError(f"{label} is not a safe identifier")
    return text


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label).casefold()
    if _SHA256.fullmatch(text) is None:
        raise NotebookAcceptanceEvidenceError(f"{label} is not a SHA-256 digest")
    return text


def _timestamp(value: object, label: str) -> float:
    text = _required_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise NotebookAcceptanceEvidenceError(
            f"{label} is not an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise NotebookAcceptanceEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


@dataclass(frozen=True)
class BrowserConfirmationObservation:
    """Browser metadata bound to separately captured visible DOM bytes."""

    schema_version: str
    browser_session_id: str
    notebook_id: str
    option_id: str
    option_revision: int
    confirmation_recorded_at: str
    observed_url: str
    confirmation_control_name: str
    dom_snapshot_sha256: str
    observation_digest: str

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "browser_session_id": self.browser_session_id,
            "notebook_id": self.notebook_id,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "confirmation_recorded_at": self.confirmation_recorded_at,
            "observed_url": self.observed_url,
            "confirmation_control_name": self.confirmation_control_name,
            "dom_snapshot_sha256": self.dom_snapshot_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "observation_digest": self.observation_digest}

    @classmethod
    def create(
        cls,
        *,
        browser_session_id: str,
        notebook_id: str,
        option_id: str,
        option_revision: int,
        confirmation_recorded_at: str,
        observed_url: str,
        confirmation_control_name: str,
        dom_snapshot_sha256: str,
    ) -> "BrowserConfirmationObservation":
        unsigned = {
            "schema_version": _OBSERVATION_SCHEMA,
            "browser_session_id": _safe_id(
                browser_session_id, "browser_session_id"
            ),
            "notebook_id": _safe_id(notebook_id, "notebook_id"),
            "option_id": _safe_id(option_id, "option_id"),
            "option_revision": option_revision,
            "confirmation_recorded_at": _required_text(
                confirmation_recorded_at, "confirmation_recorded_at"
            ),
            "observed_url": _required_text(observed_url, "observed_url"),
            "confirmation_control_name": _required_text(
                confirmation_control_name, "confirmation_control_name"
            ),
            "dom_snapshot_sha256": _sha256(
                dom_snapshot_sha256, "dom_snapshot_sha256"
            ),
        }
        if type(option_revision) is not int or option_revision <= 0:
            raise NotebookAcceptanceEvidenceError(
                "option_revision must be a positive integer"
            )
        control = str(unsigned["confirmation_control_name"]).casefold()
        if "confirm" not in control and "确认" not in control:
            raise NotebookAcceptanceEvidenceError(
                "confirmation control must identify a visible confirm action"
            )
        return cls(**unsigned, observation_digest=_digest(unsigned))

    @classmethod
    def from_mapping(cls, value: object) -> "BrowserConfirmationObservation":
        if not isinstance(value, Mapping):
            raise NotebookAcceptanceEvidenceError(
                "browser confirmation observation must be an object"
            )
        expected = {
            "schema_version",
            "browser_session_id",
            "notebook_id",
            "option_id",
            "option_revision",
            "confirmation_recorded_at",
            "observed_url",
            "confirmation_control_name",
            "dom_snapshot_sha256",
            "observation_digest",
        }
        if set(value) != expected:
            raise NotebookAcceptanceEvidenceError(
                "browser confirmation observation fields are incomplete"
            )
        observation = cls.create(
            browser_session_id=value["browser_session_id"],
            notebook_id=value["notebook_id"],
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            confirmation_recorded_at=value["confirmation_recorded_at"],
            observed_url=value["observed_url"],
            confirmation_control_name=value["confirmation_control_name"],
            dom_snapshot_sha256=value["dom_snapshot_sha256"],
        )
        if value["schema_version"] != _OBSERVATION_SCHEMA:
            raise NotebookAcceptanceEvidenceError(
                "browser confirmation observation schema drifted"
            )
        if value["observation_digest"] != observation.observation_digest:
            raise NotebookAcceptanceEvidenceError(
                "browser confirmation observation digest does not match"
            )
        return observation


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NotebookAcceptanceEvidenceError(
                f"evidence JSON contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _read_regular_bytes(path: Path, label: str) -> bytes:
    current = path.anchor and Path(path.anchor) or Path()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as error:
            raise NotebookAcceptanceEvidenceError(f"{label} is unavailable") from error
        if stat.S_ISLNK(info.st_mode):
            raise NotebookAcceptanceEvidenceError(f"{label} cannot traverse a symlink")
    try:
        info = os.lstat(path)
    except OSError as error:
        raise NotebookAcceptanceEvidenceError(f"{label} is unavailable") from error
    if not stat.S_ISREG(info.st_mode):
        raise NotebookAcceptanceEvidenceError(f"{label} must be a regular file")
    if info.st_size > _MAX_EVIDENCE_FILE_BYTES:
        raise NotebookAcceptanceEvidenceError(f"{label} exceeds the evidence size cap")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise NotebookAcceptanceEvidenceError(f"{label} cannot be opened safely") from error
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > _MAX_EVIDENCE_FILE_BYTES:
                raise NotebookAcceptanceEvidenceError(
                    f"{label} exceeds the evidence size cap"
                )
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _parse_json(path: Path, label: str) -> Mapping[str, Any]:
    raw = _read_regular_bytes(path, label)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotebookAcceptanceEvidenceError(f"{label} is not strict JSON") from error
    if not isinstance(value, Mapping):
        raise NotebookAcceptanceEvidenceError(f"{label} must contain an object")
    return value


def _parse_jsonl(path: Path, label: str) -> tuple[Mapping[str, Any], ...]:
    raw = _read_regular_bytes(path, label)
    if not raw or not raw.endswith(b"\n"):
        raise NotebookAcceptanceEvidenceError(
            f"{label} must be a non-empty newline-terminated journal"
        )
    records: list[Mapping[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise NotebookAcceptanceEvidenceError(
                f"{label} contains a blank record at line {line_no}"
            )
        try:
            value = json.loads(
                line.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NotebookAcceptanceEvidenceError(
                f"{label} has invalid JSON at line {line_no}"
            ) from error
        if not isinstance(value, Mapping):
            raise NotebookAcceptanceEvidenceError(
                f"{label} record {line_no} must be an object"
            )
        records.append(value)
    return tuple(records)


def _exactly_one(
    values: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    label: str,
) -> Mapping[str, Any]:
    if len(values) != 1:
        raise NotebookAcceptanceEvidenceError(
            f"{label} must have exactly one durable record"
        )
    return values[0]


def _matching(
    records: tuple[Mapping[str, Any], ...],
    *,
    record_type: str,
    option_id: str,
    option_revision: int,
) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records
        if record.get("record_type") == record_type
        and record.get("option_id") == option_id
        and record.get("option_revision") == option_revision
    ]


def _event_payload(record: Mapping[str, Any]) -> Mapping[str, Any]:
    outer = record.get("payload")
    if not isinstance(outer, Mapping):
        return {}
    inner = outer.get("payload")
    return inner if isinstance(inner, Mapping) else {}


def _trace_proves_option(
    records: tuple[Mapping[str, Any], ...],
    *,
    option_id: str,
    option_revision: int,
) -> bool:
    required = {
        "user.decision.recorded/v1": lambda payload: payload.get("decision")
        == "selected",
        "option.execution.completed/v1": lambda payload: payload.get(
            "execution_status"
        )
        == "succeeded",
        "artifact_contract.validation.completed/v1": lambda payload: payload.get(
            "validation_status"
        )
        == "passed",
    }
    found: set[str] = set()
    for record in records:
        event_type = record.get("event_type")
        predicate = required.get(event_type)
        payload = _event_payload(record)
        if (
            predicate is not None
            and payload.get("option_id") == option_id
            and payload.get("option_revision") == option_revision
            and predicate(payload)
        ):
            found.add(str(event_type))
    return found == set(required)


def _artifact_entry(
    entries: list[Mapping[str, Any]], artifact_id: str
) -> Mapping[str, Any]:
    matches = [entry for entry in entries if entry.get("artifact_id") == artifact_id]
    return _exactly_one(matches, label=f"artifact index entry {artifact_id}")


def _artifact_path(run_root: Path, entry: Mapping[str, Any]) -> Path:
    relative_text = _required_text(entry.get("path"), "artifact path")
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise NotebookAcceptanceEvidenceError("artifact path escapes its run")
    return run_root / relative


def _observation_for_project(
    observation: BrowserConfirmationObservation,
    *,
    project_root: Path,
    notebook_id: str,
    option_id: str,
    option_revision: int,
    confirmation_recorded_at: str,
) -> None:
    if (
        observation.notebook_id != notebook_id
        or observation.option_id != option_id
        or observation.option_revision != option_revision
        or observation.confirmation_recorded_at != confirmation_recorded_at
    ):
        raise NotebookAcceptanceEvidenceError(
            "browser confirmation observation does not match the durable option"
        )
    parsed = urlparse(observation.observed_url)
    values = parse_qs(parsed.query).get("project_root", [])
    if len(values) != 1 or Path(values[0]).resolve() != project_root:
        raise NotebookAcceptanceEvidenceError(
            "browser confirmation URL does not name the accepted project"
        )


def collect_notebook_completion_evidence(
    *,
    project_root: str | os.PathLike[str],
    operation_id: str,
    notebook_id: str,
    option_id: str,
    option_revision: int,
    observation: BrowserConfirmationObservation | Mapping[str, object] | None,
    browser_snapshot: str | os.PathLike[str],
    authority: CompletionAuthority,
    witness_attestation: BrowserWitnessAttestation
    | Mapping[str, object]
    | None = None,
    witness_verifier: WitnessVerifier | None = None,
) -> CompletionEvidence:
    """Cross-check one completed P7 child against its real Notebook chain."""

    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotebookAcceptanceEvidenceError("project_root must be a directory")
    if not isinstance(authority, CompletionAuthority):
        raise NotebookAcceptanceEvidenceError(
            "completion authority is required for evidence collection"
        )
    try:
        authority_root = Path(authority.project_root).resolve(strict=True)
    except OSError as error:
        raise NotebookAcceptanceEvidenceError(
            "completion authority project_root is unavailable"
        ) from error
    if authority_root != root:
        raise NotebookAcceptanceEvidenceError(
            "project_root does not match the active fixture authority"
        )
    operation_id = _safe_id(operation_id, "operation_id")
    notebook_id = _safe_id(notebook_id, "notebook_id")
    option_id = _safe_id(option_id, "option_id")
    if type(option_revision) is not int or option_revision <= 0:
        raise NotebookAcceptanceEvidenceError(
            "option_revision must be a positive integer"
        )
    parsed_witness: BrowserWitnessAttestation | None = None
    if witness_attestation is not None:
        try:
            parsed_witness = (
                BrowserWitnessAttestation.from_mapping(witness_attestation)
                if isinstance(witness_attestation, Mapping)
                else witness_attestation
            )
        except WitnessError as error:
            raise NotebookAcceptanceEvidenceError(str(error)) from error
        if not isinstance(parsed_witness, BrowserWitnessAttestation):
            raise NotebookAcceptanceEvidenceError(
                "witness_attestation must be a browser witness envelope"
            )
        if observation is not None:
            raise NotebookAcceptanceEvidenceError(
                "witness-attested collection cannot mix caller observation metadata"
            )
        observation = BrowserConfirmationObservation.create(
            browser_session_id=parsed_witness.browser_session_id,
            notebook_id=parsed_witness.notebook_id,
            option_id=parsed_witness.option_id,
            option_revision=parsed_witness.option_revision,
            confirmation_recorded_at=parsed_witness.confirmation_recorded_at,
            observed_url=parsed_witness.observed_url,
            confirmation_control_name=parsed_witness.confirmation_control_name,
            dom_snapshot_sha256=parsed_witness.dom_snapshot_sha256,
        )
    elif isinstance(observation, Mapping):
        observation = BrowserConfirmationObservation.from_mapping(observation)
    if not isinstance(observation, BrowserConfirmationObservation):
        raise NotebookAcceptanceEvidenceError(
            "a browser confirmation observation is required"
        )
    snapshot_bytes = _read_regular_bytes(
        Path(browser_snapshot), "browser DOM snapshot"
    )
    if hashlib.sha256(snapshot_bytes).hexdigest() != observation.dom_snapshot_sha256:
        raise NotebookAcceptanceEvidenceError(
            "browser DOM snapshot hash does not match the observation"
        )
    try:
        snapshot_text = snapshot_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise NotebookAcceptanceEvidenceError(
            "browser DOM snapshot is not UTF-8 text"
        ) from error
    visible_control = " ".join(
        observation.confirmation_control_name.casefold().split()
    )
    visible_snapshot = " ".join(snapshot_text.casefold().split())
    if visible_control not in visible_snapshot:
        raise NotebookAcceptanceEvidenceError(
            "browser DOM snapshot does not contain the visible confirmation control"
        )

    notebook_records = _parse_jsonl(
        root / "notebooks" / notebook_id / "notebook.jsonl",
        "Notebook journal",
    )
    trace_ids = tuple(
        _safe_id(record.get("trace_id"), "trace_id")
        for record in notebook_records
        if record.get("record_type") == "notebook_state"
        and record.get("reason") == "trace_started"
    )
    if not trace_ids:
        raise NotebookAcceptanceEvidenceError("Notebook has no durable Agent trace")
    focus_records = [
        record
        for record in notebook_records
        if record.get("record_type") == "notebook_state"
        and record.get("reason") == "set_focus"
        and isinstance(record.get("user_focus"), Mapping)
    ]
    if not focus_records or focus_records[-1]["user_focus"].get("goal") != authority.prompt:
        raise NotebookAcceptanceEvidenceError(
            "durable Notebook goal does not match the frozen acceptance prompt"
        )
    notebook_record = _exactly_one(
        [record for record in notebook_records if record.get("record_type") == "notebook"],
        label="Notebook root record",
    )
    projection_source = notebook_record.get("projection_source")
    workflow_source = (
        projection_source.get("workflow_source")
        if isinstance(projection_source, Mapping)
        else None
    )
    if not isinstance(workflow_source, Mapping):
        raise NotebookAcceptanceEvidenceError(
            "Notebook has no immutable workflow source projection"
        )

    option_records = _parse_jsonl(
        root / "notebooks" / notebook_id / "options" / f"{option_id}.jsonl",
        "Notebook option journal",
    )
    revision = _exactly_one(
        _matching(
            option_records,
            record_type="revision",
            option_id=option_id,
            option_revision=option_revision,
        ),
        label="option revision",
    )
    revision_recorded_at = _required_text(
        revision.get("recorded_at"), "option revision recorded_at"
    )
    if _timestamp(revision_recorded_at, "option revision recorded_at") < float(
        authority.attempt_started_at
    ):
        raise NotebookAcceptanceEvidenceError(
            "option revision predates the active acceptance submission"
        )
    proposal = revision.get("typed_proposal")
    if not isinstance(proposal, Mapping) or proposal.get("operation_id") != "operation.multi_step":
        raise NotebookAcceptanceEvidenceError(
            "parent operation is not the durable operation.multi_step proposal"
        )
    changes = proposal.get("changes")
    steps = changes.get("steps") if isinstance(changes, Mapping) else None
    if not isinstance(steps, list):
        raise NotebookAcceptanceEvidenceError("parent proposal has no durable child steps")
    if any(not isinstance(step, Mapping) for step in steps):
        raise NotebookAcceptanceEvidenceError("parent proposal child step is invalid")
    step_operation_ids = [step.get("operation_id") for step in steps]
    step_ids = [step.get("step_id") for step in steps]
    if (
        len(step_operation_ids) != len(authority.operation_ids)
        or set(step_operation_ids) != set(authority.operation_ids)
        or len(step_operation_ids) != len(set(step_operation_ids))
        or any(not isinstance(step_id, str) or not step_id for step_id in step_ids)
        or len(step_ids) != len(set(step_ids))
    ):
        raise NotebookAcceptanceEvidenceError(
            "parent proposal operations do not exactly match the frozen submission"
        )
    child_steps = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("operation_id") == operation_id
    ]
    child = _exactly_one(child_steps, label="target child operation")
    step_id = _safe_id(child.get("step_id"), "workflow step_id")
    target = proposal.get("target")
    if not isinstance(target, Mapping):
        raise NotebookAcceptanceEvidenceError("parent proposal target is missing")
    run_id = _safe_id(target.get("run_id"), "source run_id")
    node_ref = _safe_id(target.get("node_ref"), "source node_ref")
    source_artifact_id = _safe_id(
        target.get("artifact_id"), "source artifact_id"
    )
    source_sha = _sha256(workflow_source.get("source_sha256"), "source sha256")
    if (
        workflow_source.get("run_id") != run_id
        or workflow_source.get("node_ref") != node_ref
        or workflow_source.get("artifact_id") != source_artifact_id
    ):
        raise NotebookAcceptanceEvidenceError(
            "proposal target does not match the immutable Notebook source"
        )
    preconditions = proposal.get("preconditions")
    if not isinstance(preconditions, Mapping):
        raise NotebookAcceptanceEvidenceError(
            "parent proposal preconditions are missing"
        )
    computed_plan_fingerprint, computed_step_fingerprints = (
        _recompute_workflow_identity(
            target=target,
            preconditions=preconditions,
            changes=changes,
        )
    )

    confirmations = [
        record
        for record in _matching(
            option_records,
            record_type="lifecycle",
            option_id=option_id,
            option_revision=option_revision,
        )
        if record.get("actor") == "user"
        and record.get("reason") == "workflow_confirmed"
        and record.get("to_status") == "executing"
    ]
    confirmation = _exactly_one(
        confirmations, label="browser confirmation lifecycle"
    )
    confirmation_at = _required_text(
        confirmation.get("recorded_at"), "confirmation recorded_at"
    )
    if _timestamp(confirmation_at, "confirmation recorded_at") < float(
        authority.attempt_started_at
    ):
        raise NotebookAcceptanceEvidenceError(
            "browser confirmation predates the active acceptance submission"
        )
    _observation_for_project(
        observation,
        project_root=root,
        notebook_id=notebook_id,
        option_id=option_id,
        option_revision=option_revision,
        confirmation_recorded_at=confirmation_at,
    )

    execution = _exactly_one(
        _matching(
            option_records,
            record_type="execution",
            option_id=option_id,
            option_revision=option_revision,
        ),
        label="option execution",
    )
    workflow_id = _safe_id(execution.get("workflow_id"), "workflow_id")
    plan_fingerprint = _required_text(
        execution.get("workflow_plan_fingerprint"), "workflow plan fingerprint"
    )
    if plan_fingerprint != computed_plan_fingerprint:
        raise NotebookAcceptanceEvidenceError(
            "workflow plan fingerprint does not match the durable proposal"
        )
    result = _exactly_one(
        _matching(
            option_records,
            record_type="execution_result",
            option_id=option_id,
            option_revision=option_revision,
        ),
        label="option execution result",
    )
    validation = result.get("artifact_validation")
    workflow_execution = result.get("workflow_execution")
    if (
        result.get("committed") is not True
        or result.get("execution_status") != "succeeded"
        or not isinstance(validation, Mapping)
        or validation.get("validation_status") != "passed"
        or validation.get("issues") not in ([], ())
        or not isinstance(workflow_execution, Mapping)
        or workflow_execution.get("workflow_id") != workflow_id
        or workflow_execution.get("plan_fingerprint") != plan_fingerprint
        or workflow_execution.get("status") != "completed"
    ):
        raise NotebookAcceptanceEvidenceError(
            "option execution is not committed with a passed artifact contract"
        )

    workflow_records = _parse_jsonl(
        root / "workbench" / "workflows" / f"{workflow_id}.jsonl",
        "workflow journal",
    )
    workflow_terminal = workflow_records[-1]
    workflow_steps = workflow_terminal.get("steps")
    expected_step_ids = set(step_ids)
    if (
        not isinstance(workflow_steps, Mapping)
        or set(workflow_steps) != expected_step_ids
        or any(
            not isinstance(terminal, Mapping)
            or terminal.get("step_id") != expected_step_id
            or terminal.get("status") != "completed"
            or terminal.get("error") is not None
            for expected_step_id, terminal in workflow_steps.items()
        )
    ):
        raise NotebookAcceptanceEvidenceError(
            "workflow terminal steps do not exactly match the frozen submission"
        )
    if any(
        workflow_steps[expected_step_id].get("fingerprint")
        != computed_step_fingerprints[expected_step_id]
        for expected_step_id in expected_step_ids
    ):
        raise NotebookAcceptanceEvidenceError(
            "workflow step fingerprint does not match the durable proposal"
        )
    child_terminal = (
        workflow_steps.get(step_id) if isinstance(workflow_steps, Mapping) else None
    )
    if (
        workflow_terminal.get("workflow_id") != workflow_id
        or workflow_terminal.get("plan_fingerprint") != plan_fingerprint
        or workflow_terminal.get("status") != "completed"
        or not isinstance(child_terminal, Mapping)
        or child_terminal.get("step_id") != step_id
        or child_terminal.get("status") != "completed"
        or child_terminal.get("error") is not None
    ):
        raise NotebookAcceptanceEvidenceError(
            "workflow terminal does not prove the completed child"
        )
    child_artifact_ids = child_terminal.get("artifact_ids")
    if not isinstance(child_artifact_ids, list) or not child_artifact_ids:
        raise NotebookAcceptanceEvidenceError(
            "workflow terminal child has no durable artifact identity"
        )

    run_root = root / "runs" / run_id
    index = _parse_json(run_root / "artifacts_index.json", "artifact index")
    raw_entries = index.get("artifacts")
    if not isinstance(raw_entries, list) or any(
        not isinstance(entry, Mapping) for entry in raw_entries
    ):
        raise NotebookAcceptanceEvidenceError("artifact index entries are invalid")
    entries: list[Mapping[str, Any]] = list(raw_entries)
    artifact_ids = [entry.get("artifact_id") for entry in entries]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise NotebookAcceptanceEvidenceError("artifact index contains duplicate IDs")
    source_entry = _artifact_entry(entries, source_artifact_id)
    source_path = _artifact_path(run_root, source_entry)
    source_digest = hashlib.sha256(
        _read_regular_bytes(source_path, "source artifact")
    ).hexdigest()
    if (
        _sha256(source_entry.get("sha256"), "source artifact index sha256")
        != source_sha
        or source_digest != source_sha
    ):
        raise NotebookAcceptanceEvidenceError(
            "source artifact hash does not match the immutable Notebook source"
        )
    p7_candidates = [
        artifact_id
        for artifact_id in child_artifact_ids
        if isinstance(artifact_id, str)
        and (
            entry := _artifact_entry(entries, artifact_id)
        ).get("artifact_type")
        == "p7_analysis"
        and entry.get("step") == operation_id
    ]
    if len(p7_candidates) != 1:
        raise NotebookAcceptanceEvidenceError(
            "workflow child must produce exactly one indexed P7 artifact"
        )
    artifact_id = p7_candidates[0]
    artifact_entry = _artifact_entry(entries, artifact_id)
    artifact_path = _artifact_path(run_root, artifact_entry)
    artifact_bytes = _read_regular_bytes(artifact_path, "P7 artifact")
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_sha != _sha256(artifact_entry.get("sha256"), "artifact index sha256"):
        raise NotebookAcceptanceEvidenceError("P7 artifact hash does not match its index")
    try:
        artifact = json.loads(
            artifact_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotebookAcceptanceEvidenceError("P7 artifact is not strict JSON") from error
    source = artifact.get("source") if isinstance(artifact, Mapping) else None
    artifact_result = artifact.get("result") if isinstance(artifact, Mapping) else None
    if (
        not isinstance(source, Mapping)
        or source.get("run_id") != run_id
        or source.get("node_ref") != node_ref
        or source.get("artifact_id") != source_artifact_id
        or source.get("sha256") != source_sha
        or source.get("workflow_id") != workflow_id
        or source.get("workflow_step_id") != step_id
        or source.get("operation_id") != operation_id
        or not isinstance(artifact_result, Mapping)
        or artifact_result.get("operation_id") != operation_id
        or artifact_result.get("status") != "completed"
    ):
        raise NotebookAcceptanceEvidenceError(
            "P7 artifact provenance does not match the completed child"
        )
    provenance_id = _required_text(
        source.get("workflow_step_fingerprint"),
        "artifact provenance fingerprint",
    )
    if provenance_id != computed_step_fingerprints[step_id]:
        raise NotebookAcceptanceEvidenceError(
            "artifact workflow step fingerprint does not match the durable proposal"
        )

    receipt_entries = [
        entry
        for entry in entries
        if entry.get("artifact_type") == "notebook_workflow_result"
    ]
    operation_to_step_id = {
        str(step["operation_id"]): str(step["step_id"])
        for step in steps
    }
    expected_outputs: dict[str, dict[str, str]] = {}
    for expected_operation_id in authority.operation_ids:
        expected_step_id = operation_to_step_id[expected_operation_id]
        terminal = workflow_steps[expected_step_id]
        terminal_artifact_ids = terminal.get("artifact_ids")
        if not isinstance(terminal_artifact_ids, list):
            raise NotebookAcceptanceEvidenceError(
                "workflow terminal child has no durable artifact identity"
            )
        matching_artifacts: list[Mapping[str, Any]] = []
        for candidate_id in terminal_artifact_ids:
            if not isinstance(candidate_id, str):
                continue
            candidate_entry = _artifact_entry(entries, candidate_id)
            if (
                candidate_entry.get("artifact_type") == "p7_analysis"
                and candidate_entry.get("step") == expected_operation_id
            ):
                matching_artifacts.append(candidate_entry)
        matching_entry = _exactly_one(
            matching_artifacts,
            label=f"workflow output for {expected_operation_id}",
        )
        expected_outputs[expected_operation_id] = {
            "artifact_id": _safe_id(
                matching_entry.get("artifact_id"),
                f"artifact id for {expected_operation_id}",
            ),
            "artifact_type": "p7_analysis",
            "sha256": _sha256(
                matching_entry.get("sha256"),
                f"artifact sha256 for {expected_operation_id}",
            ),
            "step": expected_operation_id,
        }
    valid_receipts: list[Mapping[str, Any]] = []
    for receipt_entry in receipt_entries:
        receipt_path = _artifact_path(run_root, receipt_entry)
        receipt_bytes = _read_regular_bytes(receipt_path, "workflow receipt")
        receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        if receipt_sha != _sha256(
            receipt_entry.get("sha256"), "workflow receipt index sha256"
        ):
            raise NotebookAcceptanceEvidenceError(
                "workflow receipt hash does not match its index"
            )
        try:
            receipt = json.loads(
                receipt_bytes.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NotebookAcceptanceEvidenceError(
                "workflow receipt is not strict JSON"
            ) from error
        receipt_workflow = receipt.get("workflow") if isinstance(receipt, Mapping) else None
        outputs = receipt.get("output_artifacts") if isinstance(receipt, Mapping) else None
        expected_source = {
            "run_id": run_id,
            "node_ref": node_ref,
            "artifact_id": source_artifact_id,
        }
        expected_output_values = list(expected_outputs.values())
        if (
            receipt.get("schema_version")
            == "workbench.notebook.workflow-result/v1"
            and isinstance(receipt_workflow, Mapping)
            and receipt_workflow.get("workflow_id") == workflow_id
            and receipt_workflow.get("plan_fingerprint") == plan_fingerprint
            and receipt_workflow.get("status") == "completed"
            and receipt_workflow.get("source") == expected_source
            and receipt_workflow.get("p7_capability_ids")
            == list(authority.operation_ids)
            and isinstance(outputs, list)
            and all(isinstance(output, Mapping) for output in outputs)
            and len(outputs) == len(expected_output_values)
            and sorted(
                (dict(output) for output in outputs),
                key=lambda output: output["step"],
            )
            == sorted(expected_output_values, key=lambda output: output["step"])
        ):
            valid_receipts.append(receipt)
    _exactly_one(valid_receipts, label="completed workflow receipt")

    matching_traces: list[str] = []
    matching_trace_records: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for trace_id in dict.fromkeys(trace_ids):
        trace_records = _parse_jsonl(
            root / "agent-events" / f"{trace_id}.jsonl",
            f"Agent trace {trace_id}",
        )
        if _trace_proves_option(
            trace_records,
            option_id=option_id,
            option_revision=option_revision,
        ):
            matching_traces.append(trace_id)
            matching_trace_records[trace_id] = trace_records
    if len(matching_traces) != 1:
        raise NotebookAcceptanceEvidenceError(
            "Agent trace does not uniquely prove selection, execution, and artifact validation"
        )
    trace_id = matching_traces[0]
    durable_chain_sha256 = _digest(
        {
            "notebook_records": notebook_records,
            "option_records": option_records,
            "workflow_records": workflow_records,
            "artifact_index": index,
            "workflow_receipts": valid_receipts,
            "matching_trace_records": matching_trace_records,
            "source_artifact_sha256": source_sha,
            "p7_artifact_sha256": artifact_sha,
            "expected_outputs": expected_outputs,
        }
    )
    if parsed_witness is not None:
        try:
            witness_challenge = WitnessChallenge.create(
                manifest_digest=authority.manifest_digest,
                submission_id=authority.submission_id,
                attempt_no=authority.attempt_no,
                operation_ids_digest=authority.operation_ids_digest,
                notebook_id=parsed_witness.notebook_id,
                option_id=parsed_witness.option_id,
                option_revision=parsed_witness.option_revision,
                attempt_started_at=authority.attempt_started_at,
                issued_at=authority.attempt_started_at,
                expires_at=(
                    authority.attempt_started_at
                    + WITNESS_CHALLENGE_TTL_SECONDS
                ),
            )
            verify_witness_attestation(
                witness_challenge,
                parsed_witness,
                verifier=witness_verifier,
                now=_timestamp(confirmation_at, "confirmation recorded_at"),
                expected_durable_chain_sha256=durable_chain_sha256,
            )
        except WitnessError as error:
            raise NotebookAcceptanceEvidenceError(str(error)) from error
    parent_record_id = f"option:{notebook_id}:{option_id}:{option_revision}"
    child_record_id = f"workflow:{workflow_id}:{step_id}"
    return CompletionEvidence(
        evidence_kind=(
            "browser_witness_attested"
            if parsed_witness is not None
            else "browser_visible_agent"
        ),
        manifest_digest=authority.manifest_digest,
        submission_id=authority.submission_id,
        attempt_no=authority.attempt_no,
        attempt_started_at=authority.attempt_started_at,
        fixture_id=authority.fixture_id,
        prompt_sha256=authority.prompt_sha256,
        provider=authority.provider,
        model=authority.model,
        submission_operation_ids_digest=authority.operation_ids_digest,
        project_root=str(root),
        source_run_id=run_id,
        source_node_ref=node_ref,
        source_artifact_id=source_artifact_id,
        source_artifact_sha256=source_sha,
        option_revision_recorded_at=revision_recorded_at,
        confirmation_recorded_at=confirmation_at,
        workflow_plan_fingerprint=plan_fingerprint,
        agent_session_id=trace_id,
        parent_operation_id="operation.multi_step",
        parent_record_id=parent_record_id,
        parent_record_status="completed",
        parent_record_durable=True,
        child_operation_id=operation_id,
        child_record_id=child_record_id,
        child_parent_record_id=parent_record_id,
        child_record_status="completed",
        child_record_durable=True,
        confirmation_id=(
            parsed_witness.attestation_digest
            if parsed_witness is not None
            else observation.observation_digest
        ),
        confirmation_surface="browser",
        confirmation_actor="user",
        confirmation_session_id=trace_id,
        confirmation_parent_record_id=parent_record_id,
        nested_result_status="completed",
        nested_result_parent_record_id=parent_record_id,
        nested_result_child_record_id=child_record_id,
        nested_artifact_id=artifact_id,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha,
        artifact_provenance_id=provenance_id,
        artifact_producer_record_id=child_record_id,
        witness_attestation=(
            parsed_witness.to_dict() if parsed_witness is not None else None
        ),
    )


__all__ = [
    "BrowserConfirmationObservation",
    "NotebookAcceptanceEvidenceError",
    "collect_notebook_completion_evidence",
]
