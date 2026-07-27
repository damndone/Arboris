"""CF4 execution receipt and Artifact Contract 1.1 aggregate facts.

The aggregate is deliberately independent from the process runner.  It is the
server-owned commit gate that joins a precise Option revision, one execution
attempt, one consumer projection, and one bounded lineage identity.  A fit
that returns bytes without these joins is not a consumable Workbench result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..agent.notebook.artifact_contract import (
    FAILED,
    PASSED,
    PASSED_WITH_WARNINGS,
    validate_produced_artifacts,
)
from ..contracts.agent.notebook_option import ArtifactContract
from ..custom_capability.canonical import domain_digest
from .trace_contracts import CapabilityTraceEvent, build_trace_event


ARTIFACT_CONTRACT_V11 = "ArtifactContractValidation@1.1"
ARTIFACT_CONTRACT_V11_PROFILE = "artifact-contract-lineage-consumer/v1"
ARTIFACT_V11_CHECKED_DIMENSIONS = (
    "artifact_id",
    "artifact_type",
    "count",
    "step",
    "lineage",
    "consumer_projection",
    "run_attempt",
    "option_revision",
)
ARTIFACT_V11_NOT_EVALUATED_DIMENSIONS = ("payload_schema",)
_HEX = frozenset("0123456789abcdef")
_STATUSES = frozenset({PASSED, PASSED_WITH_WARNINGS, FAILED})


class ExecutionReceiptError(ValueError):
    """Raised when a receipt or aggregate cannot be trusted."""


def _identifier(value: Any, field: str, *, maximum: int = 512) -> str:
    text = _text(value, field, maximum=maximum)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ExecutionReceiptError(f"{field} must be path-safe")
    return text


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ExecutionReceiptError(f"{field} must be bounded non-empty text")
    if any(ord(char) < 0x20 for char in value):
        raise ExecutionReceiptError(f"{field} contains a control character")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ExecutionReceiptError(f"{field} must be a lowercase SHA-256 digest")
    return text


def derive_stable_side_effect_ref(
    *,
    namespace: str,
    derivation_revision: int,
    producer_revision: int,
    slot_mapping_revision: int,
    stable_key: str,
) -> str:
    """Derive a content identity without allowing a raw path or author order."""

    namespace = _text(namespace, "namespace")
    stable_key = _text(stable_key, "stable_key")
    if any(separator in namespace or separator in stable_key for separator in ("/", "\\")):
        raise ExecutionReceiptError("stable side-effect identities cannot contain paths")
    for value, field in (
        (derivation_revision, "derivation_revision"),
        (producer_revision, "producer_revision"),
        (slot_mapping_revision, "slot_mapping_revision"),
    ):
        if type(value) is not int or value < 1:
            raise ExecutionReceiptError(f"{field} must be a positive integer")
    return domain_digest(
        "workbench.capability_factory.side_effect_ref/v1",
        {
            "namespace": namespace,
            "derivation_revision": derivation_revision,
            "producer_revision": producer_revision,
            "slot_mapping_revision": slot_mapping_revision,
            "stable_key": stable_key,
        },
    )


def _issue(code: str, severity: str, artifact_id: str, detail: str) -> dict[str, str]:
    return {
        "code": _text(code, "issue.code", maximum=128),
        "severity": _text(severity, "issue.severity", maximum=32),
        "artifact_id": _text(artifact_id, "issue.artifact_id", maximum=256),
        "detail": _text(detail, "issue.detail", maximum=512),
    }


def _artifact_identity(record: Mapping[str, Any], index: int) -> tuple[str, ...]:
    if not isinstance(record, Mapping):
        raise ExecutionReceiptError(f"produced artifact {index} must be an object")
    expected = {
        "artifact_id",
        "artifact_type",
        "step",
        "lineage_ref",
        "consumer_projection_ref",
        "run_attempt_ref",
        "option_revision_ref",
        "artifact_ref",
        "facet",
    }
    if set(record) != expected:
        raise ExecutionReceiptError(f"produced artifact {index} has unknown or missing fields")
    return (
        _text(record["artifact_id"], "artifact_id", maximum=256),
        _text(record["artifact_type"], "artifact_type", maximum=256),
        (None if record["step"] is None else _text(record["step"], "step", maximum=256)),
        _digest(record["lineage_ref"], "lineage_ref"),
        _digest(record["consumer_projection_ref"], "consumer_projection_ref"),
        _digest(record["run_attempt_ref"], "run_attempt_ref"),
        _digest(record["option_revision_ref"], "option_revision_ref"),
        _digest(record["artifact_ref"], "artifact_ref"),
        _text(record["facet"], "facet", maximum=256),
    )


@dataclass(frozen=True, slots=True)
class ArtifactContractValidationV11:
    """Bounded aggregate result used by completion and active-head gates."""

    aggregate_ref: str
    option_revision_ref: str
    run_attempt_ref: str
    consumer_projection_ref: str
    lineage_ref: str
    validation_status: str
    issues: tuple[Mapping[str, str], ...]
    artifact_refs: tuple[str, ...]
    checked_dimensions: tuple[str, ...] = ARTIFACT_V11_CHECKED_DIMENSIONS
    not_evaluated_dimensions: tuple[str, ...] = ARTIFACT_V11_NOT_EVALUATED_DIMENSIONS
    contract_version: str = ARTIFACT_CONTRACT_V11

    def __post_init__(self) -> None:
        if self.contract_version != ARTIFACT_CONTRACT_V11:
            raise ExecutionReceiptError("artifact validation contract is unsupported")
        object.__setattr__(self, "aggregate_ref", _digest(self.aggregate_ref, "aggregate_ref"))
        for field in ("option_revision_ref", "run_attempt_ref", "consumer_projection_ref", "lineage_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if self.validation_status not in _STATUSES:
            raise ExecutionReceiptError("artifact validation status is unsupported")
        if tuple(self.checked_dimensions) != ARTIFACT_V11_CHECKED_DIMENSIONS:
            raise ExecutionReceiptError("artifact checked dimensions are not the v1.1 profile")
        if tuple(self.not_evaluated_dimensions) != ARTIFACT_V11_NOT_EVALUATED_DIMENSIONS:
            raise ExecutionReceiptError("artifact not-evaluated dimensions are not the v1.1 profile")
        issues = tuple(dict(item) for item in self.issues)
        if len(issues) > 128:
            raise ExecutionReceiptError("artifact validation issues exceed the bounded limit")
        if any(set(item) != {"code", "severity", "artifact_id", "detail"} for item in issues):
            raise ExecutionReceiptError("artifact validation issue fields are invalid")
        object.__setattr__(self, "issues", issues)
        refs = tuple(_digest(item, "artifact_refs item") for item in self.artifact_refs)
        if len(refs) > 256 or len(set(refs)) != len(refs):
            raise ExecutionReceiptError("artifact refs are not a bounded unique sequence")
        object.__setattr__(self, "artifact_refs", refs)
        expected = self._expected_aggregate_ref
        if self.aggregate_ref != expected:
            raise ExecutionReceiptError("artifact aggregate ref does not match its contents")

    @property
    def _expected_aggregate_ref(self) -> str:
        return domain_digest(
            "workbench.capability_factory.artifact_contract_validation/v1",
            self._payload_without_ref(),
        )

    def _payload_without_ref(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "option_revision_ref": self.option_revision_ref,
            "run_attempt_ref": self.run_attempt_ref,
            "consumer_projection_ref": self.consumer_projection_ref,
            "lineage_ref": self.lineage_ref,
            "validation_status": self.validation_status,
            "issues": [dict(item) for item in self.issues],
            "artifact_refs": list(self.artifact_refs),
            "checked_dimensions": list(self.checked_dimensions),
            "not_evaluated_dimensions": list(self.not_evaluated_dimensions),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.contract_version, "aggregate_ref": self.aggregate_ref, **self._payload_without_ref()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactContractValidationV11":
        expected = {
            "contract_version",
            "aggregate_ref",
            "option_revision_ref",
            "run_attempt_ref",
            "consumer_projection_ref",
            "lineage_ref",
            "validation_status",
            "issues",
            "artifact_refs",
            "checked_dimensions",
            "not_evaluated_dimensions",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ExecutionReceiptError("artifact validation aggregate fields are invalid")
        result = cls(
            aggregate_ref=value["aggregate_ref"],
            option_revision_ref=value["option_revision_ref"],
            run_attempt_ref=value["run_attempt_ref"],
            consumer_projection_ref=value["consumer_projection_ref"],
            lineage_ref=value["lineage_ref"],
            validation_status=value["validation_status"],
            issues=tuple(value["issues"]),
            artifact_refs=tuple(value["artifact_refs"]),
            checked_dimensions=tuple(value["checked_dimensions"]),
            not_evaluated_dimensions=tuple(value["not_evaluated_dimensions"]),
            contract_version=value["contract_version"],
        )
        return result


def validate_artifact_contract_v11(
    contract: ArtifactContract,
    produced: Sequence[Mapping[str, Any]],
    *,
    option_revision_ref: str,
    run_attempt_ref: str,
    consumer_projection_ref: str,
    lineage_ref: str,
    allowed_facets: Iterable[str],
    trace_sink: Callable[[CapabilityTraceEvent], None] | None = None,
) -> ArtifactContractValidationV11:
    """Validate identity/count plus every v1.1 aggregate binding."""

    if not isinstance(contract, ArtifactContract):
        raise ExecutionReceiptError("artifact contract must be an ArtifactContract")
    pins = {
        "option_revision_ref": _digest(option_revision_ref, "option_revision_ref"),
        "run_attempt_ref": _digest(run_attempt_ref, "run_attempt_ref"),
        "consumer_projection_ref": _digest(consumer_projection_ref, "consumer_projection_ref"),
        "lineage_ref": _digest(lineage_ref, "lineage_ref"),
    }
    facets = {_text(item, "allowed facet", maximum=256) for item in allowed_facets}
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for index, record in enumerate(produced):
        identity = _artifact_identity(record, index)
        normalized.append(dict(record))
        fields = (
            ("lineage_ref", identity[3]),
            ("consumer_projection_ref", identity[4]),
            ("run_attempt_ref", identity[5]),
            ("option_revision_ref", identity[6]),
        )
        for field, observed in fields:
            if observed != pins[field]:
                issues.append(_issue("ARTIFACT_BINDING_MISMATCH", "blocking", identity[0], f"{field} does not match the execution aggregate"))
        if identity[8] not in facets:
            issues.append(_issue("ARTIFACT_FACET_UNDECLARED", "blocking", identity[0], "artifact facet is not declared by the admitted consumer projection"))

    base = validate_produced_artifacts(contract, normalized)
    for issue in base["issues"]:
        issues.append(_issue(issue["code"], issue["severity"], str(issue["artifact_id"]), str(issue["detail"])))
    if any(issue["severity"] == "blocking" for issue in issues):
        status = FAILED
    elif any(issue["severity"] == "warning" for issue in issues):
        status = PASSED_WITH_WARNINGS
    else:
        status = PASSED
    result = ArtifactContractValidationV11(
        aggregate_ref=domain_digest(
            "workbench.capability_factory.artifact_contract_validation/v1",
            {
                "contract_version": ARTIFACT_CONTRACT_V11,
                **pins,
                "validation_status": status,
                "issues": issues,
                "artifact_refs": [identity[7] for identity in (_artifact_identity(item, i) for i, item in enumerate(normalized))],
                "checked_dimensions": list(ARTIFACT_V11_CHECKED_DIMENSIONS),
                "not_evaluated_dimensions": list(ARTIFACT_V11_NOT_EVALUATED_DIMENSIONS),
            },
        ),
        option_revision_ref=pins["option_revision_ref"],
        run_attempt_ref=pins["run_attempt_ref"],
        consumer_projection_ref=pins["consumer_projection_ref"],
        lineage_ref=pins["lineage_ref"],
        validation_status=status,
        issues=tuple(issues),
        artifact_refs=tuple(identity[7] for identity in (_artifact_identity(item, i) for i, item in enumerate(normalized))),
    )
    if trace_sink is not None:
        trace_sink(
            build_trace_event(
                event_type="artifact_contract.v11.validation.completed",
                payload={
                    "aggregate_ref": result.aggregate_ref,
                    "option_revision_ref": result.option_revision_ref,
                    "run_attempt_ref": result.run_attempt_ref,
                    "outcome": result.validation_status,
                },
            )
        )
    return result


TERMINAL_RECONCILIATION_CONTRACT_VERSION = "TerminalSideEffectReconciliation@1.0"


@dataclass(frozen=True, slots=True)
class TerminalSideEffectReconciliation:
    """Trusted proof that all terminal side-effect families were reconciled."""

    attempt_ref: str
    authorization_id: str
    lease_epoch: int
    artifact_aggregate_ref: str
    object_graph_ref: str
    trace_event_ref: str
    artifact_reconciled: bool
    graph_reconciled: bool
    trace_reconciled: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_ref", _digest(self.attempt_ref, "attempt_ref"))
        object.__setattr__(self, "authorization_id", _identifier(self.authorization_id, "authorization_id"))
        if type(self.lease_epoch) is not int or self.lease_epoch < 1:
            raise ExecutionReceiptError("lease_epoch must be a positive integer")
        for field in ("artifact_aggregate_ref", "object_graph_ref", "trace_event_ref"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        for field in ("artifact_reconciled", "graph_reconciled", "trace_reconciled"):
            if type(getattr(self, field)) is not bool:
                raise ExecutionReceiptError(f"{field} must be boolean")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.terminal_side_effect_reconciliation/v1",
            {
                "contract_version": TERMINAL_RECONCILIATION_CONTRACT_VERSION,
                "attempt_ref": self.attempt_ref,
                "authorization_id": self.authorization_id,
                "lease_epoch": self.lease_epoch,
                "artifact_aggregate_ref": self.artifact_aggregate_ref,
                "object_graph_ref": self.object_graph_ref,
                "trace_event_ref": self.trace_event_ref,
                "artifact_reconciled": self.artifact_reconciled,
                "graph_reconciled": self.graph_reconciled,
                "trace_reconciled": self.trace_reconciled,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": TERMINAL_RECONCILIATION_CONTRACT_VERSION,
            "attempt_ref": self.attempt_ref,
            "authorization_id": self.authorization_id,
            "lease_epoch": self.lease_epoch,
            "artifact_aggregate_ref": self.artifact_aggregate_ref,
            "object_graph_ref": self.object_graph_ref,
            "trace_event_ref": self.trace_event_ref,
            "artifact_reconciled": self.artifact_reconciled,
            "graph_reconciled": self.graph_reconciled,
            "trace_reconciled": self.trace_reconciled,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TerminalSideEffectReconciliation":
        expected = {
            "contract_version",
            "attempt_ref",
            "authorization_id",
            "lease_epoch",
            "artifact_aggregate_ref",
            "object_graph_ref",
            "trace_event_ref",
            "artifact_reconciled",
            "graph_reconciled",
            "trace_reconciled",
            "content_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ExecutionReceiptError("terminal reconciliation fields are invalid")
        if value["contract_version"] != TERMINAL_RECONCILIATION_CONTRACT_VERSION:
            raise ExecutionReceiptError("terminal reconciliation contract is unsupported")
        result = cls(
            attempt_ref=value["attempt_ref"],
            authorization_id=value["authorization_id"],
            lease_epoch=value["lease_epoch"],
            artifact_aggregate_ref=value["artifact_aggregate_ref"],
            object_graph_ref=value["object_graph_ref"],
            trace_event_ref=value["trace_event_ref"],
            artifact_reconciled=value["artifact_reconciled"],
            graph_reconciled=value["graph_reconciled"],
            trace_reconciled=value["trace_reconciled"],
        )
        if value["content_digest"] != result.content_digest:
            raise ExecutionReceiptError("terminal reconciliation content digest mismatch")
        return result

    def assert_matches(
        self,
        *,
        attempt_ref: str,
        authorization_id: str,
        lease_epoch: int,
        artifact_aggregate_ref: str,
        object_graph_ref: str,
    ) -> None:
        if self.attempt_ref != _digest(attempt_ref, "attempt_ref"):
            raise ExecutionReceiptError("terminal reconciliation is bound to another attempt")
        if self.authorization_id != _identifier(authorization_id, "authorization_id"):
            raise ExecutionReceiptError("terminal reconciliation is bound to another authorization")
        if self.lease_epoch != lease_epoch:
            raise ExecutionReceiptError("terminal reconciliation lease epoch does not match")
        if self.artifact_aggregate_ref != _digest(artifact_aggregate_ref, "artifact_aggregate_ref"):
            raise ExecutionReceiptError("terminal reconciliation artifact aggregate does not match")
        if self.object_graph_ref != _digest(object_graph_ref, "object_graph_ref"):
            raise ExecutionReceiptError("terminal reconciliation graph reference does not match")
        if not (self.artifact_reconciled and self.graph_reconciled and self.trace_reconciled):
            raise ExecutionReceiptError("terminal reconciliation has unreconciled side effects")


@dataclass(frozen=True, slots=True)
class CapabilityDispatchReceipt:
    """The unique control-plane handoff from authorization to one attempt."""

    authorization_id: str
    authorization_payload_digest: str
    intent_digest: str
    reservation_id: str
    attempt_id: str
    lease_epoch: int
    status: str
    plan_digest: str

    def __post_init__(self) -> None:
        for field in ("authorization_id", "reservation_id", "attempt_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        for field in (
            "authorization_payload_digest",
            "intent_digest",
            "plan_digest",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if type(self.lease_epoch) is not int or self.lease_epoch < 1:
            raise ExecutionReceiptError("lease_epoch must be a positive integer")
        if self.status not in {"dispatch_reserved", "running", "dispatch_unknown", "failed", "consumed"}:
            raise ExecutionReceiptError("dispatch receipt status is unsupported")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.capability_dispatch_receipt/v1",
            {
                "authorization_id": self.authorization_id,
                "authorization_payload_digest": self.authorization_payload_digest,
                "intent_digest": self.intent_digest,
                "reservation_id": self.reservation_id,
                "attempt_id": self.attempt_id,
                "lease_epoch": self.lease_epoch,
                "status": self.status,
                "plan_digest": self.plan_digest,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "CapabilityDispatchReceipt@1.0",
            "authorization_id": self.authorization_id,
            "authorization_payload_digest": self.authorization_payload_digest,
            "intent_digest": self.intent_digest,
            "reservation_id": self.reservation_id,
            "attempt_id": self.attempt_id,
            "lease_epoch": self.lease_epoch,
            "status": self.status,
            "plan_digest": self.plan_digest,
            "content_digest": self.content_digest,
        }


class CapabilityDispatchCoordinator:
    """Linearize claim, reservation, and durable attempt creation.

    This class has no process or network dependency.  The only method that
    advances to ``running`` accepts an executor-supplied handle; that handle
    must come from the trusted B1 broker in a later host-specific adapter.
    """

    def __init__(
        self,
        *,
        authorization_store: Any,
        control_store: Any,
        supervisor_store: Any,
        trace_sink: Callable[[CapabilityTraceEvent], None] | None = None,
    ) -> None:
        from .control import ExecutionControlStore
        from .execution_authorization import OptionExecutionAuthorizationStore
        from .supervisor import DurableSupervisorStore

        if not isinstance(authorization_store, OptionExecutionAuthorizationStore):
            raise ExecutionReceiptError("authorization_store is invalid")
        if not isinstance(control_store, ExecutionControlStore):
            raise ExecutionReceiptError("control_store is invalid")
        if not isinstance(supervisor_store, DurableSupervisorStore):
            raise ExecutionReceiptError("supervisor_store is invalid")
        self.authorization_store = authorization_store
        self.control_store = control_store
        self.supervisor_store = supervisor_store
        self.trace_sink = trace_sink

    def _emit_trace(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.trace_sink is not None:
            self.trace_sink(build_trace_event(event_type=event_type, payload=payload))

    def _assert_receipt_binding(
        self,
        receipt: CapabilityDispatchReceipt,
        *,
        allow_prior_lease_epoch: bool = False,
    ) -> tuple[Any, Any]:
        """Join the receipt to the current authorization and attempt journals.

        A receipt is an untrusted transport value even when it originated from
        this coordinator.  Every consumer must rejoin it to both durable
        records before changing either journal; otherwise a valid handle or
        artifact could be attached to a different authorization or intent.
        """

        from .execution_authorization import OptionExecutionAuthorization

        if not isinstance(receipt, CapabilityDispatchReceipt):
            raise ExecutionReceiptError("dispatch receipt is invalid")
        try:
            authorization = self.authorization_store.read(receipt.authorization_id)
            attempt = self.supervisor_store.read(receipt.attempt_id)
        except Exception as error:
            raise ExecutionReceiptError("dispatch receipt references an unavailable journal record") from error
        if not isinstance(authorization, OptionExecutionAuthorization):
            raise ExecutionReceiptError("authorization receipt is invalid")
        if authorization.payload_digest != receipt.authorization_payload_digest:
            raise ExecutionReceiptError("dispatch receipt authorization payload does not match")
        if authorization.status != receipt.status:
            raise ExecutionReceiptError("dispatch receipt status does not match authorization")
        if attempt.authorization_id != receipt.authorization_id:
            raise ExecutionReceiptError("dispatch receipt attempt is bound to another authorization")
        if attempt.reservation_id != receipt.reservation_id:
            raise ExecutionReceiptError("dispatch receipt reservation does not match attempt")
        if attempt.intent_digest != receipt.intent_digest:
            raise ExecutionReceiptError("dispatch receipt intent does not match attempt")
        if attempt.lease_epoch != receipt.lease_epoch:
            if not allow_prior_lease_epoch or attempt.lease_epoch != receipt.lease_epoch + 1:
                raise ExecutionReceiptError("dispatch receipt lease epoch does not match attempt")
        allowed_attempt_statuses = {
            "dispatch_reserved": frozenset({"reserved", "spawn_requested", "spawn_acknowledged"}),
            "running": frozenset({"spawn_acknowledged", "running", "terminated", "failed", "dispatch_unknown", "consumed"}),
            "dispatch_unknown": frozenset({"dispatch_unknown"}),
            "failed": frozenset({"failed"}),
            "consumed": frozenset({"consumed"}),
        }
        if attempt.status not in allowed_attempt_statuses[receipt.status]:
            raise ExecutionReceiptError("dispatch receipt status does not match attempt")
        return authorization, attempt

    def reserve(
        self,
        *,
        authorization: Any,
        intent: Any,
        plan: Any,
        expectations: tuple[Any, ...] | list[Any],
        owner_id: str,
        lease_seconds: int,
        attempt_id: str,
        lease_epoch: int,
        executor_idempotency_key: str,
        reservation_id: str,
        reservation_idempotency_key: str,
        authorization_validity_revision: int = 1,
        now: Any = None,
    ) -> CapabilityDispatchReceipt:
        from .dispatch import DispatchReservation, PreparedRunIntent
        from .custom_dispatcher import CustomDispatchPlan
        from .execution_authorization import OptionExecutionAuthorization

        if not isinstance(authorization, OptionExecutionAuthorization):
            raise ExecutionReceiptError("authorization is invalid")
        if not isinstance(intent, PreparedRunIntent):
            raise ExecutionReceiptError("intent is invalid")
        if not isinstance(plan, CustomDispatchPlan):
            raise ExecutionReceiptError("custom dispatch plan is invalid")
        if plan.intent_digest != intent.content_digest:
            raise ExecutionReceiptError("dispatch plan does not match intent")
        if authorization.run_intent_id != intent.intent_id or authorization.draft_hash != intent.draft_hash:
            raise ExecutionReceiptError("authorization does not match the prepared intent")
        if authorization.capability_resolution_binding_ref != intent.binding_ref:
            raise ExecutionReceiptError("authorization binding does not match the prepared intent")
        current = self.authorization_store.read(authorization.authorization_id)
        if current.status == "dispatch_reserved":
            return self._replay_reserved(current, intent=intent, plan=plan)
        if current.status != "issued":
            raise ExecutionReceiptError(f"authorization is not claimable in status {current.status}")
        try:
            claimed = self.authorization_store.claim(
                authorization.authorization_id,
                idempotency_key=authorization.idempotency_key,
                current_binding_ref=intent.binding_ref,
                current_freshness_cursor_ref=authorization.freshness_cursor_ref,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
            )
            self._emit_trace(
                "option.authorization.changed",
                {
                    "authorization_ref": claimed.payload_digest,
                    "from_status": "issued",
                    "to_status": "claimed",
                    "receipt_ref": claimed.receipt_digest,
                },
            )
        except ExecutionAuthorizationError as error:
            raise ExecutionReceiptError(str(error)) from error
        try:
            reservation = DispatchReservation.reserve(
                control_store=self.control_store,
                intent=intent,
                authorization_id=claimed.authorization_id,
                authorization_payload_digest=claimed.payload_digest,
                authorization_validity_revision=authorization_validity_revision,
                attempt_id=attempt_id,
                lease_epoch=lease_epoch,
                executor_idempotency_key=executor_idempotency_key,
                record_id=reservation_id,
                idempotency_key=reservation_idempotency_key,
                expectations=expectations,
                now=now,
            )
        except Exception as error:
            try:
                self.authorization_store.transition(
                    claimed.authorization_id,
                    transition_id=_identifier(f"invalidate-{claimed.authorization_id}", "transition_id"),
                    idempotency_key=claimed.idempotency_key,
                    expected_status="claimed",
                    target_status="invalidated",
                    owner_id=claimed.claim_owner_id or owner_id,
                    lease_epoch=claimed.lease_epoch or lease_epoch,
                    prior_receipt_digest=claimed.receipt_digest,
                    metadata={"reason": "dispatch_reservation_rejected"},
                )
            except Exception as transition_error:
                raise ExecutionReceiptError(
                    "dispatch reservation failed and authorization invalidation could not be recorded: "
                    + str(transition_error)
                ) from transition_error
            raise ExecutionReceiptError("dispatch reservation rejected") from error
        try:
            reserved = self.authorization_store.transition(
                claimed.authorization_id,
                transition_id=_identifier(f"reserved-{reservation.reservation_id}", "transition_id"),
                idempotency_key=claimed.idempotency_key,
                expected_status="claimed",
                target_status="dispatch_reserved",
                owner_id=claimed.claim_owner_id or owner_id,
                lease_epoch=claimed.lease_epoch or lease_epoch,
                prior_receipt_digest=claimed.receipt_digest,
                metadata={"reason": "dispatch_reservation_created", "reservation_id": reservation.reservation_id},
            )
            attempt = self.supervisor_store.create(reservation)
            self._emit_trace(
                "option.authorization.changed",
                {
                    "authorization_ref": reserved.payload_digest,
                    "from_status": "claimed",
                    "to_status": "dispatch_reserved",
                    "receipt_ref": reserved.receipt_digest,
                },
            )
            self._emit_trace(
                "option.dispatch.reserved",
                {
                    "authorization_ref": reserved.payload_digest,
                    "reservation_ref": reservation.content_digest,
                    "control_sequence": reservation.control_sequence,
                },
            )
        except Exception as error:
            raise ExecutionReceiptError(
                "dispatch reservation exists but its durable attempt could not be recorded"
            ) from error
        return CapabilityDispatchReceipt(
            authorization_id=reserved.authorization_id,
            authorization_payload_digest=reserved.payload_digest,
            intent_digest=intent.content_digest,
            reservation_id=reservation.reservation_id,
            attempt_id=attempt.attempt_id,
            lease_epoch=attempt.lease_epoch,
            status="dispatch_reserved",
            plan_digest=plan.content_digest,
        )

    def acknowledge_executor(
        self,
        receipt: CapabilityDispatchReceipt,
        *,
        owner_id: str,
        process_handle_ref: str,
    ) -> CapabilityDispatchReceipt:
        """Record a trusted B1 executor handle; never create one here."""

        self._assert_receipt_binding(receipt)
        requested = self.supervisor_store.transition(
            receipt.attempt_id,
            target_status="spawn_requested",
            transition_id=_identifier(f"spawn-request-{receipt.attempt_id}", "transition_id"),
            owner_id=owner_id,
            lease_epoch=receipt.lease_epoch,
            reason="trusted executor requested spawn",
        )
        acknowledged = self.supervisor_store.transition(
            requested.attempt_id,
            target_status="spawn_acknowledged",
            transition_id=_identifier(f"spawn-ack-{receipt.attempt_id}", "transition_id"),
            owner_id=owner_id,
            lease_epoch=requested.lease_epoch,
            process_handle_ref=process_handle_ref,
            reason="trusted executor acknowledged handle",
        )
        running = self.supervisor_store.transition(
            acknowledged.attempt_id,
            target_status="running",
            transition_id=_identifier(f"running-{receipt.attempt_id}", "transition_id"),
            owner_id=owner_id,
            lease_epoch=acknowledged.lease_epoch,
            process_handle_ref=process_handle_ref,
            reason="trusted executor is running",
        )
        current = self.authorization_store.read(receipt.authorization_id)
        if current.status == "dispatch_reserved":
            current = self.authorization_store.transition(
                receipt.authorization_id,
                transition_id=_identifier(f"running-{receipt.authorization_id}", "transition_id"),
                idempotency_key=current.idempotency_key,
                expected_status="dispatch_reserved",
                target_status="running",
                owner_id=current.claim_owner_id or owner_id,
                lease_epoch=current.lease_epoch or receipt.lease_epoch,
                prior_receipt_digest=current.receipt_digest,
                metadata={"reason": "trusted_executor_acknowledged", "attempt_id": receipt.attempt_id},
            )
        return CapabilityDispatchReceipt(
            authorization_id=receipt.authorization_id,
            authorization_payload_digest=receipt.authorization_payload_digest,
            intent_digest=receipt.intent_digest,
            reservation_id=receipt.reservation_id,
            attempt_id=receipt.attempt_id,
            lease_epoch=running.lease_epoch,
            status="running",
            plan_digest=receipt.plan_digest,
        )

    def take_over_lease(
        self,
        receipt: CapabilityDispatchReceipt,
        *,
        owner_id: str,
        transition_id: str,
        lease_seconds: int,
        reason: str,
    ) -> CapabilityDispatchReceipt:
        """Fence an expired worker across authorization and supervisor journals.

        The two durable journals cannot be committed as one filesystem write.
        Recovery therefore advances authorization first, then requires the
        supervisor to reach the exact same newer epoch.  A crash between those
        writes is fail-closed: the old worker is fenced and a retry replays the
        same takeover transition instead of creating a second attempt.
        """

        _authorization, attempt = self._assert_receipt_binding(
            receipt,
            allow_prior_lease_epoch=True,
        )
        transition = _identifier(transition_id, "transition_id")
        authorization = self.authorization_store.read(receipt.authorization_id)
        if authorization.status not in {"dispatch_reserved", "running"}:
            raise ExecutionReceiptError(
                f"authorization cannot be recovered from status {authorization.status}"
            )
        if attempt.authorization_id != authorization.authorization_id:
            raise ExecutionReceiptError("supervisor attempt is bound to another authorization")
        owner = _identifier(owner_id, "owner_id")
        if authorization.lease_epoch is None:
            raise ExecutionReceiptError("authorization lease epoch is missing")

        receipt_epoch = receipt.lease_epoch
        authorization_epoch = authorization.lease_epoch
        attempt_epoch = attempt.lease_epoch
        if authorization_epoch == attempt_epoch == receipt_epoch:
            recovery_mode = "advance_both"
        elif authorization_epoch == receipt_epoch + 1 and attempt_epoch == receipt_epoch:
            if authorization.claim_owner_id != owner:
                raise ExecutionReceiptError(
                    "authorization takeover is owned by another recovery supervisor"
                )
            recovery_mode = "repair_supervisor"
        elif authorization_epoch == attempt_epoch == receipt_epoch + 1:
            if authorization.claim_owner_id != owner or attempt.lease_owner_id != owner:
                raise ExecutionReceiptError(
                    "completed lease takeover is owned by another recovery supervisor"
                )
            return CapabilityDispatchReceipt(
                authorization_id=authorization.authorization_id,
                authorization_payload_digest=authorization.payload_digest,
                intent_digest=receipt.intent_digest,
                reservation_id=receipt.reservation_id,
                attempt_id=attempt.attempt_id,
                lease_epoch=attempt.lease_epoch,
                status=authorization.status,
                plan_digest=receipt.plan_digest,
            )
        else:
            self._mark_dispatch_unknown(
                authorization,
                attempt,
                reason="authorization and supervisor lease epochs cannot be reconciled",
            )
            raise ExecutionReceiptError(
                "authorization and supervisor lease epochs are irreconcilable; dispatch_unknown recorded"
            )
        try:
            if recovery_mode == "advance_both":
                recovered_authorization = self.authorization_store.take_over_lease(
                    authorization.authorization_id,
                    owner_id=owner,
                    transition_id=transition,
                    lease_seconds=lease_seconds,
                    reason=reason,
                )
            else:
                recovered_authorization = authorization
            recovered_attempt = self.supervisor_store.take_over_lease(
                attempt.attempt_id,
                owner_id=owner,
                transition_id=_identifier(f"{transition}.supervisor", "transition_id"),
                reason=reason,
            )
        except Exception as error:
            raise ExecutionReceiptError("lease takeover could not be durably reconciled") from error
        if recovered_attempt.lease_epoch != recovered_authorization.lease_epoch:
            raise ExecutionReceiptError("lease takeover produced divergent authorization and supervisor epochs")
        return CapabilityDispatchReceipt(
            authorization_id=recovered_authorization.authorization_id,
            authorization_payload_digest=recovered_authorization.payload_digest,
            intent_digest=receipt.intent_digest,
            reservation_id=receipt.reservation_id,
            attempt_id=recovered_attempt.attempt_id,
            lease_epoch=recovered_attempt.lease_epoch,
            status=recovered_authorization.status,
            plan_digest=receipt.plan_digest,
        )

    def _mark_dispatch_unknown(self, authorization: Any, attempt: Any, *, reason: str) -> None:
        """Fence both journals when their epochs cannot be reconciled safely."""

        supervisor_statuses = {"reserved", "spawn_requested", "spawn_acknowledged", "running"}
        authorization_statuses = {"claimed", "dispatch_reserved", "running"}
        if attempt.status not in supervisor_statuses:
            raise ExecutionReceiptError(
                "irreconcilable supervisor state cannot be isolated as dispatch_unknown"
            )
        if authorization.status not in authorization_statuses:
            raise ExecutionReceiptError(
                "irreconcilable authorization state cannot be isolated as dispatch_unknown"
            )
        supervisor_owner = attempt.lease_owner_id or authorization.claim_owner_id
        authorization_owner = authorization.claim_owner_id or attempt.lease_owner_id
        if supervisor_owner is None or authorization_owner is None:
            raise ExecutionReceiptError("dispatch_unknown isolation requires durable lease owners")
        try:
            self.supervisor_store.transition(
                attempt.attempt_id,
                target_status="dispatch_unknown",
                transition_id=_identifier(f"dispatch-unknown-{attempt.attempt_id}", "transition_id"),
                owner_id=supervisor_owner,
                lease_epoch=attempt.lease_epoch,
                reason=reason,
                process_handle_ref=attempt.process_handle_ref,
            )
            self.authorization_store.transition(
                authorization.authorization_id,
                transition_id=_identifier(
                    f"dispatch-unknown-{authorization.authorization_id}", "transition_id"
                ),
                idempotency_key=authorization.idempotency_key,
                expected_status=authorization.status,
                target_status="dispatch_unknown",
                owner_id=authorization_owner,
                lease_epoch=authorization.lease_epoch,
                prior_receipt_digest=authorization.receipt_digest,
                metadata={"reason": reason, "attempt_id": attempt.attempt_id},
            )
        except Exception as error:
            raise ExecutionReceiptError("dispatch_unknown isolation could not be durably recorded") from error

    def reconcile(
        self,
        receipt: CapabilityDispatchReceipt,
        *,
        owner_id: str,
        artifact_validation: ArtifactContractValidationV11,
        object_graph_ref: str,
        termination_proof: Any | None = None,
        terminal_reconciliation: TerminalSideEffectReconciliation | None = None,
    ) -> CapabilityDispatchReceipt:
        """Close one running attempt only after the v1.1 aggregate gate.

        The method records no model payload and has no process-control power.
        A trusted executor supplies the artifact validation aggregate and graph
        reference; this coordinator only verifies their attempt identity and
        advances the already-authorized journals exactly once.
        """

        _authorization, attempt = self._assert_receipt_binding(receipt)
        if not isinstance(artifact_validation, ArtifactContractValidationV11):
            raise ExecutionReceiptError("artifact validation aggregate is invalid")
        _digest(object_graph_ref, "object_graph_ref")
        if artifact_validation.run_attempt_ref != attempt.content_digest:
            raise ExecutionReceiptError("artifact validation is bound to another attempt state")
        authorization = self.authorization_store.read(receipt.authorization_id)

        if attempt.status in {"spawn_acknowledged", "running"}:
            try:
                self.supervisor_store.record_termination_proof(termination_proof)
            except Exception as error:
                raise ExecutionReceiptError(str(error)) from error
            if not isinstance(terminal_reconciliation, TerminalSideEffectReconciliation):
                raise ExecutionReceiptError("terminal side-effect reconciliation proof is required")
            terminal_reconciliation.assert_matches(
                attempt_ref=attempt.content_digest,
                authorization_id=authorization.authorization_id,
                lease_epoch=attempt.lease_epoch,
                artifact_aggregate_ref=artifact_validation.aggregate_ref,
                object_graph_ref=object_graph_ref,
            )

        if artifact_validation.validation_status == FAILED:
            if attempt.status in {"spawn_acknowledged", "running"}:
                attempt = self.supervisor_store.transition(
                    attempt.attempt_id,
                    target_status="failed",
                    transition_id=_identifier(f"failed-{attempt.attempt_id}", "transition_id"),
                    owner_id=owner_id,
                    lease_epoch=attempt.lease_epoch,
                    reason="artifact_contract_failed",
                    process_handle_ref=attempt.process_handle_ref,
                )
            if authorization.status == "running":
                authorization = self.authorization_store.transition(
                    authorization.authorization_id,
                    transition_id=_identifier(
                        f"failed-{authorization.authorization_id}", "transition_id"
                    ),
                    idempotency_key=authorization.idempotency_key,
                    expected_status="running",
                    target_status="failed",
                    owner_id=authorization.claim_owner_id or owner_id,
                    lease_epoch=authorization.lease_epoch or receipt.lease_epoch,
                    prior_receipt_digest=authorization.receipt_digest,
                    metadata={"reason": "artifact_contract_failed", "attempt_id": receipt.attempt_id},
                )
            elif authorization.status != "failed":
                raise ExecutionReceiptError(
                    f"authorization cannot reconcile from status {authorization.status}"
                )
            self._emit_trace(
                "option.authorization.changed",
                {
                    "authorization_ref": authorization.payload_digest,
                    "from_status": "running",
                    "to_status": "failed",
                    "receipt_ref": authorization.receipt_digest,
                },
            )
            self._emit_trace(
                "option.execution.reconciled",
                {
                    "authorization_ref": authorization.payload_digest,
                    "lease_epoch": attempt.lease_epoch,
                    "outcome": "failed",
                    "object_graph_ref": _digest(object_graph_ref, "object_graph_ref"),
                },
            )
            return CapabilityDispatchReceipt(
                authorization_id=receipt.authorization_id,
                authorization_payload_digest=receipt.authorization_payload_digest,
                intent_digest=receipt.intent_digest,
                reservation_id=receipt.reservation_id,
                attempt_id=receipt.attempt_id,
                lease_epoch=attempt.lease_epoch,
                status="failed",
                plan_digest=receipt.plan_digest,
            )

        if artifact_validation.validation_status not in {PASSED, PASSED_WITH_WARNINGS}:
            raise ExecutionReceiptError("artifact validation did not reach a terminal pass")
        if attempt.status in {"spawn_acknowledged", "running"}:
            attempt = self.supervisor_store.transition(
                attempt.attempt_id,
                target_status="terminated",
                transition_id=_identifier(f"terminated-{attempt.attempt_id}", "transition_id"),
                owner_id=owner_id,
                lease_epoch=attempt.lease_epoch,
                reason="artifact_contract_reconciled",
                process_handle_ref=attempt.process_handle_ref,
            )
        if attempt.status == "terminated":
            attempt = self.supervisor_store.transition(
                attempt.attempt_id,
                target_status="consumed",
                transition_id=_identifier(f"consumed-{attempt.attempt_id}", "transition_id"),
                owner_id=owner_id,
                lease_epoch=attempt.lease_epoch,
                reason="artifact_contract_reconciled",
                process_handle_ref=attempt.process_handle_ref,
            )
        if authorization.status == "running":
            authorization = self.authorization_store.transition(
                authorization.authorization_id,
                transition_id=_identifier(
                    f"consumed-{authorization.authorization_id}", "transition_id"
                ),
                idempotency_key=authorization.idempotency_key,
                expected_status="running",
                target_status="consumed",
                owner_id=authorization.claim_owner_id or owner_id,
                lease_epoch=authorization.lease_epoch or receipt.lease_epoch,
                prior_receipt_digest=authorization.receipt_digest,
                metadata={"reason": "artifact_contract_reconciled", "attempt_id": receipt.attempt_id},
            )
        elif authorization.status != "consumed":
            raise ExecutionReceiptError(
                f"authorization cannot reconcile from status {authorization.status}"
            )
        self._emit_trace(
            "option.authorization.changed",
            {
                "authorization_ref": authorization.payload_digest,
                "from_status": "running",
                "to_status": "consumed",
                "receipt_ref": authorization.receipt_digest,
            },
        )
        self._emit_trace(
            "option.execution.reconciled",
            {
                "authorization_ref": authorization.payload_digest,
                "lease_epoch": attempt.lease_epoch,
                "outcome": "consumed",
                "object_graph_ref": _digest(object_graph_ref, "object_graph_ref"),
            },
        )
        return CapabilityDispatchReceipt(
            authorization_id=receipt.authorization_id,
            authorization_payload_digest=receipt.authorization_payload_digest,
            intent_digest=receipt.intent_digest,
            reservation_id=receipt.reservation_id,
            attempt_id=receipt.attempt_id,
            lease_epoch=attempt.lease_epoch,
            status="consumed",
            plan_digest=receipt.plan_digest,
        )

    def _replay_reserved(self, authorization: Any, *, intent: Any, plan: Any) -> CapabilityDispatchReceipt:
        from .dispatch import DispatchReservation

        candidates = [
            record
            for record in self.control_store.records()
            if record.request.record_type == "dispatch_reservation"
            and record.request.value.get("authorization_id") == authorization.authorization_id
            and record.request.value.get("intent_digest") == intent.content_digest
        ]
        if not candidates:
            raise ExecutionReceiptError("dispatch_reserved authorization has no matching reservation")
        reservation = DispatchReservation.from_control_record(
            intent=intent,
            control_record=candidates[-1],
        )
        attempt = self.supervisor_store.create(reservation)
        return CapabilityDispatchReceipt(
            authorization_id=authorization.authorization_id,
            authorization_payload_digest=authorization.payload_digest,
            intent_digest=intent.content_digest,
            reservation_id=reservation.reservation_id,
            attempt_id=attempt.attempt_id,
            lease_epoch=attempt.lease_epoch,
            status=authorization.status,
            plan_digest=plan.content_digest,
        )


__all__ = [
    "ARTIFACT_CONTRACT_V11",
    "ARTIFACT_CONTRACT_V11_PROFILE",
    "ArtifactContractValidationV11",
    "CapabilityDispatchCoordinator",
    "CapabilityDispatchReceipt",
    "ExecutionReceiptError",
    "TERMINAL_RECONCILIATION_CONTRACT_VERSION",
    "TerminalSideEffectReconciliation",
    "derive_stable_side_effect_ref",
    "validate_artifact_contract_v11",
]
