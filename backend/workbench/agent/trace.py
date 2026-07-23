"""Gate 3 — Core Agent Trace v1 (spec §13, DEC-TRACE-001).

Records what actually happened during notebook planning and option execution.
Not an evaluation harness: episode boundaries, success labels, rewards and
scoring metrics are deferred to v1.8.2 and are actively refused here (see
`_USER_DECISION_FORBIDDEN`).

The distinction matters because these two things decay differently. A label can
be attached later by a human looking at the record; the record itself cannot be
reconstructed after the fact. So v1.8.1 stores the record, in a shape a later
harness can consume, and stores nothing that pretends to be a judgement.

Storage delegates to `AgentEventStream` — already durable, replayable, idempotent
and atomically appended. What this module adds is the part that was missing: a
versioned envelope and typed payloads, so the stream is evidence rather than a
debug log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..artifacts import read_json, write_json
from ..canonical import sha256_canonical
from .events import AgentEventStream

TRACE_SCHEMA = "agent-trace-event/v1"

REQUIRED_SCOPE_KEYS = ("project_id", "notebook_id", "run_family_id")
REQUIRED_VERSION_KEYS = (
    "app_commit",
    "model_id",
    "prompt_version",
    "vocabulary_version",
    "context_profile",
)


class UnknownTraceEventType(ValueError):
    """An event type with no registered payload schema.

    Refused rather than written through: an untyped event is exactly the
    `payload: any` that makes a stream unconsumable later.
    """


class TracePayloadError(ValueError):
    """A payload that does not match its registered schema."""


class _Schema:
    """A deliberately small schema: required keys, optional keys, nothing else.

    Not jsonschema. The point is to pin field *names* across versions; the
    repo's real validation lives in the operation contracts. Keeping this
    minimal is what makes it cheap enough to apply to every event.
    """

    def __init__(
        self,
        payload_schema: str,
        *,
        required: tuple[str, ...],
        optional: tuple[str, ...] = (),
        forbidden: tuple[str, ...] = (),
    ) -> None:
        self.payload_schema = payload_schema
        self.required = required
        self.optional = optional
        self.forbidden = forbidden

    def validate(self, payload: dict[str, Any], *, event_type: str) -> None:
        keys = set(payload)
        missing = [key for key in self.required if key not in keys]
        if missing:
            raise TracePayloadError(
                f"{event_type}: payload is missing required field(s): {', '.join(missing)}"
            )
        smuggled = sorted(keys & set(self.forbidden))
        if smuggled:
            raise TracePayloadError(
                f"{event_type}: field(s) {', '.join(smuggled)} do not belong in a trace. "
                "The Core Trace records what occurred; labels, rewards and scores are "
                "the v1.8.2 evaluation harness's job (DEC-TRACE-001)."
            )
        unexpected = sorted(keys - set(self.required) - set(self.optional))
        if unexpected:
            raise TracePayloadError(
                f"{event_type}: unexpected payload field(s): {', '.join(unexpected)}"
            )


# Anything that would turn an observation into a judgement. Listed explicitly so
# the refusal message can explain itself rather than reading as a typo check.
_USER_DECISION_FORBIDDEN = ("reward", "label", "correct", "score", "is_good", "rating")


USER_DECISIONS = (
    "selected",
    "deferred",
    "rejected",
    "edited",
    "requested_more_options",
    "requested_explanation",
)


TRACE_EVENT_SCHEMAS: dict[str, _Schema] = {
    "context.compiled": _Schema(
        "context-compiled/v1",
        required=(
            "context_id",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
            "compiled_context_blob_ref",
            "omitted_sections",
            "content_chars",
        ),
    ),
    "agent.plan.requested": _Schema(
        "agent-plan-requested/v1",
        required=("context_id", "requested_option_count"),
        optional=("user_prompt_ref",),
    ),
    "agent.plan.completed": _Schema(
        "agent-plan-completed/v1",
        required=("context_id", "generated_option_count", "duration_ms"),
        optional=(
            "stop_reason",
            "raw_output_ref",
            "recommendation_decision_id",
            "recommendation_outcome",
            "recommended_option_id",
            "evidence_pack_hashes",
            "comparison_protocol_refs",
        ),
    ),
    "option.revision.created": _Schema(
        "option-revision-created/v1",
        required=(
            "option_id",
            "option_revision",
            "generation_context_hash",
            "freshness_dependency_fingerprint",
        ),
        optional=("supersedes_option_revision", "rank", "risk_level"),
    ),
    "option.lifecycle.changed": _Schema(
        "option-lifecycle-changed/v1",
        required=("option_id", "option_revision", "from_status", "to_status", "axis"),
        optional=("reason",),
    ),
    "user.decision.recorded": _Schema(
        "user-decision-recorded/v1",
        required=("option_id", "option_revision", "decision"),
        optional=("edited_fields", "note_ref"),
        forbidden=_USER_DECISION_FORBIDDEN,
    ),
    "proposal.validation.completed": _Schema(
        "proposal-validation-completed/v1",
        required=("option_id", "option_revision", "proposal_id", "validation_status"),
        optional=("issues",),
    ),
    "option.execution.started": _Schema(
        "option-execution-started/v1",
        required=("option_id", "option_revision", "proposal_id", "proposal_revision"),
        optional=("freshness_dependency_fingerprint",),
    ),
    "option.execution.completed": _Schema(
        "option-execution-completed/v1",
        required=("option_id", "option_revision", "execution_status"),
        optional=("run_id", "duration_ms", "error_code"),
    ),
    "artifact_contract.validation.completed": _Schema(
        "artifact-contract-validation-completed/v1",
        required=("option_id", "option_revision", "validation_status"),
        optional=("missing_required", "warnings", "checked_dimensions"),
    ),
    "active_head.changed": _Schema(
        "active-head-changed/v1",
        required=("from_run_id", "to_run_id", "reason"),
    ),
    "operation.error": _Schema(
        "operation-error/v1",
        required=("code", "fatal"),
        optional=("option_id", "option_revision", "detail"),
    ),
    "evidence.inspection.requested": _Schema(
        "evidence-inspection-requested/v1",
        required=("inspection_id", "target_ref", "request_hash"),
    ),
    "evidence.inspection.completed": _Schema(
        "evidence-inspection-completed/v1",
        required=("inspection_id", "evidence_id", "result_hash", "status"),
        optional=("omissions",),
    ),
    "evidence.inspection.failed": _Schema(
        "evidence-inspection-failed/v1",
        required=("inspection_id", "failure_code", "evidence_id"),
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceWriter:
    """Append typed trace events for one planning/execution trace."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        scope: dict[str, Any],
        versions: dict[str, Any],
        trace_id: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> None:
        missing_scope = [key for key in REQUIRED_SCOPE_KEYS if not scope.get(key)]
        if missing_scope:
            raise TracePayloadError(
                f"trace scope is missing: {', '.join(missing_scope)}"
            )
        missing_versions = [key for key in REQUIRED_VERSION_KEYS if not versions.get(key)]
        if missing_versions:
            # A trace that cannot say which prompt, model or vocabulary produced
            # it cannot answer the only question worth asking of it later.
            raise TracePayloadError(
                f"trace versions are missing: {', '.join(missing_versions)}"
            )
        self.project_root = Path(project_root)
        self.scope = dict(scope)
        self.versions = dict(versions)
        self.actor = dict(actor or {"type": "agent"})
        self.trace_id = trace_id or f"trace_{uuid4().hex}"
        self._stream = AgentEventStream(self.project_root)
        self._sequence = len(self._stream.replay(self.trace_id))

    def emit(
        self,
        event_type: str,
        *,
        payload: dict[str, Any],
        refs: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        schema = TRACE_EVENT_SCHEMAS.get(event_type)
        if schema is None:
            raise UnknownTraceEventType(
                f"no payload schema registered for trace event {event_type!r}; "
                f"known types: {', '.join(sorted(TRACE_EVENT_SCHEMAS))}"
            )
        schema.validate(payload, event_type=event_type)
        self._sequence += 1
        envelope = {
            "trace_schema": TRACE_SCHEMA,
            "trace_id": self.trace_id,
            "sequence": self._sequence,
            "occurred_at": _now(),
            "event_type": f"{event_type}/v1",
            "scope": dict(self.scope),
            "actor": dict(self.actor),
            "versions": dict(self.versions),
            "refs": dict(refs or {}),
            "payload_schema": schema.payload_schema,
            "payload": dict(payload),
        }
        stored = self._stream.emit(
            self.trace_id,
            f"{event_type}/v1",
            envelope,
            command_id=command_id,
        )
        return {**envelope, "event_id": stored.event_id}

    @staticmethod
    def replay(project_root: Path | str, trace_id: str) -> list[dict[str, Any]]:
        """Read a trace back in emission order."""

        stream = AgentEventStream(Path(project_root), create=False)
        return [event.payload for event in stream.replay(trace_id)]


def telemetry_projection(event: dict[str, Any]) -> dict[str, Any]:
    """The de-identified view safe to leave the project (spec §13.5).

    A whitelist, not a redaction pass: redaction fails open when a new field is
    added, a whitelist fails closed. Project traces are never automatically
    uploaded, and nothing here carries content, prompts or data values.
    """

    return {
        "trace_schema": event.get("trace_schema"),
        "event_type": event.get("event_type"),
        "sequence": event.get("sequence"),
        "occurred_at": event.get("occurred_at"),
        "payload_schema": event.get("payload_schema"),
        "versions": dict(event.get("versions") or {}),
    }


CONTEXT_BLOB_DIRNAME = "agent-context-blobs"


class ContextBlobStore:
    """Content-addressed storage for compiled context bundles.

    Kept out of the JSONL stream on purpose (spec §13.4): a bundle is kilobytes
    and is frequently identical across events, while the stream should stay
    small enough to scan. Content addressing means re-recording the same context
    costs nothing, which matters because most turns recompile an unchanged one.

    Project-scoped, so a bundle inherits the project's access control and
    retention rather than acquiring its own.
    """

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root)
        self.directory = self.project_root / CONTEXT_BLOB_DIRNAME

    def put(self, context: Any) -> str:
        """Store a compiled context and return its ref."""

        from .context_compiler import (
            freshness_dependency_fingerprint,
            generation_context_hash,
        )

        digest = generation_context_hash(context)
        payload = {
            "schema_version": "compiled-context-blob.v1",
            "generation_context_hash": digest,
            "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
            "context_profile": context.context_profile,
            "content": context.hashable_payload(),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(digest)
        if not path.exists():
            write_json(path, payload)
        return f"blob:{digest}"

    def get(self, ref: str) -> dict[str, Any]:
        """Return a stored bundle, verifying it still hashes to its own ref.

        The check is not paranoia about disk corruption: a bundle that no longer
        matches its ref would let a trace claim provenance it does not have.
        """

        digest = ref.removeprefix("blob:")
        payload = read_json(self._path(digest))
        if not isinstance(payload, dict):
            raise ValueError(f"context blob is not an object: {ref}")
        recomputed = "sha256:" + sha256_canonical(payload.get("content"))
        if recomputed != payload.get("generation_context_hash") or recomputed != digest:
            raise ValueError(
                f"context blob {ref} does not hash to its ref; refusing to serve it as "
                "the context the agent saw"
            )
        return payload

    def _path(self, digest: str) -> Path:
        safe = digest.replace(":", "__")
        if Path(safe).name != safe:
            raise ValueError(f"invalid blob digest: {digest!r}")
        return self.directory / f"{safe}.json"


def record_compiled_context(
    writer: TraceWriter,
    context: Any,
    *,
    store: ContextBlobStore | None = None,
) -> dict[str, Any]:
    """Store the bundle and emit the `context.compiled` event that points at it."""

    from .context_compiler import (
        freshness_dependency_fingerprint,
        generation_context_hash,
    )

    store = store or ContextBlobStore(writer.project_root)
    ref = store.put(context)
    return writer.emit(
        "context.compiled",
        payload={
            "context_id": context.context_id,
            "generation_context_hash": generation_context_hash(context),
            "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
            "compiled_context_blob_ref": ref,
            "omitted_sections": sorted({o["section"] for o in context.omissions}),
            "content_chars": context.content_chars(),
        },
        refs={"context_id": context.context_id},
    )
