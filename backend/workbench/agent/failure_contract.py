"""Stable compiler codes mapped to the locked C0 failure envelope."""

from __future__ import annotations

from ..contracts.agent.planning import FailureEnvelopeV1 as ContractFailureEnvelopeV1


FAILURE_CODES = frozenset(
    {
        "CROSS_SCOPE",
        "CONTRACT_DIGEST_MISMATCH",
        "DISCOVERY_QUERY_LIMIT",
        "DRAFT_INVALID",
        "DRAFT_TYPE_REQUIRED",
        "DURABLE_RESERVATION_REQUIRED",
        "DUPLICATE_IDENTITY",
        "FORGED_AUTHORITY",
        "HOST_COMPILER_INTEGRATION_REQUIRED",
        "HOST_COMPILER_RESULT_INVALID",
        "IDEMPOTENCY_CONFLICT",
        "INPUT_LIMIT",
        "INTENT_MISMATCH",
        "MANIFEST_LIMIT_EXCEEDED",
        "MODEL_PROVIDER_INJECTION",
        "NATURAL_LANGUAGE_DISABLED",
        "PATH_LIKE_INPUT",
        "PORT_DIRECTION_MISMATCH",
        "PORT_SCHEMA_MISMATCH",
        "PORT_KIND_MISMATCH",
        "PORT_NULLABILITY_MISMATCH",
        "PORT_TYPE_INVALID",
        "RECURSIVE_INPUT",
        "REPLAY_NOT_FOUND",
        "SAFETY_POLICY",
        "SOURCE_DIGEST_MISMATCH",
        "UNKNOWN_CAPABILITY",
        "UNKNOWN_OPERATION",
    }
)

_STAGES = frozenset({"manifest", "discovery", "compile", "store", "context"})

# The local compiler has more precise diagnostic codes than C0 intentionally
# exposes. This table is the only translation boundary; callers inspect
# ``CompilationFailure.code`` for the local code and the C0 object for the
# public contract.
_C0_REASON_BY_CODE = {code: "PARTIAL" for code in FAILURE_CODES}
_C0_CLASS_BY_CODE = {
    "CROSS_SCOPE": "policy_block",
    "FORGED_AUTHORITY": "policy_block",
    "HOST_COMPILER_INTEGRATION_REQUIRED": "optional_dependency",
    "HOST_COMPILER_RESULT_INVALID": "corrupted_state",
    "MODEL_PROVIDER_INJECTION": "policy_block",
    "SAFETY_POLICY": "policy_block",
    "PORT_DIRECTION_MISMATCH": "incompatible_input",
    "PORT_KIND_MISMATCH": "incompatible_input",
    "PORT_NULLABILITY_MISMATCH": "incompatible_input",
    "PORT_SCHEMA_MISMATCH": "incompatible_input",
    "PORT_TYPE_INVALID": "incompatible_input",
    "DISCOVERY_QUERY_LIMIT": "resource_limit",
    "DURABLE_RESERVATION_REQUIRED": "optional_dependency",
    "INPUT_LIMIT": "resource_limit",
    "MANIFEST_LIMIT_EXCEEDED": "resource_limit",
    "NATURAL_LANGUAGE_DISABLED": "policy_block",
    "REPLAY_NOT_FOUND": "unavailable_evidence",
    "IDEMPOTENCY_CONFLICT": "corrupted_state",
}

_FAILURE_CLASS_VALUES = {
    "invalid_request",
    "incompatible_input",
    "stale",
    "unavailable_evidence",
    "optional_dependency",
    "nonconvergence",
    "resource_limit",
    "policy_block",
    "execution_failure",
    "corrupted_state",
}


def _safe_failure_ref(value: object, prefix: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(prefix)
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise ValueError("failure reference is invalid")
    return value


def _reject_path(value: object) -> None:
    if value in (None, ""):
        return
    if type(value) is not str or any(token in value for token in ("/", "\\", "..", "://")):
        raise ValueError("path-like failure context is rejected")
    if len(value) > 96:
        raise ValueError("failure context is oversized")
    # A safe field path is an internal diagnostic concern and is deliberately
    # not copied into the C0 public envelope.


FailureEnvelope = ContractFailureEnvelopeV1
FailureEnvelopeV1 = ContractFailureEnvelopeV1


class CompilationFailure(ValueError):
    """Raised with a local stable code and the locked C0 public envelope."""

    def __init__(self, code: str, envelope: ContractFailureEnvelopeV1) -> None:
        if code not in FAILURE_CODES:
            raise ValueError("unknown compiler failure code")
        if type(envelope) is not ContractFailureEnvelopeV1:
            raise TypeError("CompilationFailure requires the C0 FailureEnvelopeV1")
        self.code = code
        self.envelope = envelope
        super().__init__(code)

    def to_dict(self) -> dict[str, object]:
        return self.envelope.to_dict()


def failure(
    code: str,
    *,
    stage: str,
    path: str = "",
    retryable: bool = False,
    remediation: str = "reject",
    capability_ref: str = "capability:agent.compiler",
    step_ref: str | None = None,
    evidence_refs: tuple[str, ...] = ("evidence:agent.compiler",),
    confirmation_required: bool = False,
    partial_output_refs: tuple[str, ...] = (),
) -> CompilationFailure:
    if code not in FAILURE_CODES:
        raise ValueError("unknown compiler failure code")
    if stage not in _STAGES:
        raise ValueError("unknown compiler failure stage")
    if type(retryable) is not bool or type(confirmation_required) is not bool:
        raise ValueError("failure booleans must be exact booleans")
    if remediation not in {"reject", "retry", "refresh_manifest", "recompile"}:
        raise ValueError("unknown compiler failure remediation")
    _reject_path(path)
    capability_ref = _safe_failure_ref(capability_ref, "capability:")
    step_ref = _safe_failure_ref(step_ref or f"step:agent.compiler.{stage}", "step:")
    if not isinstance(evidence_refs, (tuple, list)) or any(
        type(item) is not str for item in evidence_refs
    ):
        raise ValueError("failure evidence refs are invalid")
    evidence_refs = tuple(_safe_failure_ref(item, "evidence:") for item in evidence_refs)
    if not isinstance(partial_output_refs, (tuple, list)) or any(
        type(item) is not str for item in partial_output_refs
    ):
        raise ValueError("partial output refs are invalid")
    partial_output_refs = tuple(_safe_failure_ref(item, "output:") for item in partial_output_refs)
    failure_class = _C0_CLASS_BY_CODE.get(code, "invalid_request")
    if failure_class not in _FAILURE_CLASS_VALUES:
        raise ValueError("failure class mapping is invalid")
    remediation_codes = ("recompile",) if remediation in {"reject", "recompile"} else ("reconfirm",)
    envelope = ContractFailureEnvelopeV1(
        failure_class=failure_class,
        reason_code=_C0_REASON_BY_CODE[code],
        capability_ref=capability_ref,
        step_ref=step_ref,
        evidence_refs=evidence_refs,
        retryable=retryable,
        remediation_codes=remediation_codes,
        confirmation_required=confirmation_required,
        partial_output_refs=partial_output_refs,
        partial_output_trust="not_available",
    )
    return CompilationFailure(code, envelope)


__all__ = [
    "CompilationFailure",
    "ContractFailureEnvelopeV1",
    "FailureEnvelope",
    "FailureEnvelopeV1",
    "FAILURE_CODES",
    "failure",
]
