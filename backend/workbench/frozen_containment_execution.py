"""Private C2 lifecycle and typed IPC validation without process creation.

Only a future reviewed OS layer may implement actual child creation.  This
module accepts an injected test double, keeps its single-use permission inside
the parent service, and returns an untrusted observation as non-passing until
the separate evaluator/ingestion phase exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import struct
import threading
import time
from typing import Callable, Protocol

from .frozen_containment_adapters import BubblewrapPlanV1, RoleBindingsV1, SeatbeltPlanV1, render_bubblewrap_plan, render_seatbelt_plan
from .frozen_containment_canary import CanaryAuditReceiptV1, CanaryOutcomeV1
from .frozen_containment_c2 import HostAdmissionV1, RuntimePolicyC2


_MAX_FRAME_BYTES = 64 * 1024
_MAX_STREAM_BYTES = 1024 * 1024
_HEX = frozenset("0123456789abcdef")


class C2LifecycleError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class C2ExecutionRequestV1:
    schema_version: str
    candidate_manifest_sha256: str
    evaluator_manifest_sha256: str
    output_root_identity_sha256: str
    deadline_monotonic_ns: int

    def validate(self) -> None:
        if self.schema_version != "1":
            raise C2LifecycleError("C2_LIFECYCLE_FAILED", "unsupported execution request schema")
        for value in (self.candidate_manifest_sha256, self.evaluator_manifest_sha256, self.output_root_identity_sha256):
            if not _is_sha256(value):
                raise C2LifecycleError("C2_LIFECYCLE_FAILED", "execution request identity is malformed")
        if not isinstance(self.deadline_monotonic_ns, int) or isinstance(self.deadline_monotonic_ns, bool) or self.deadline_monotonic_ns <= 0:
            raise C2LifecycleError("C2_LIFECYCLE_FAILED", "execution request deadline is malformed")


@dataclass(frozen=True)
class TerminationReportV1:
    deadline_expired: bool
    term_sent: bool
    kill_sent: bool
    reaped: bool
    descendants_reaped: bool


@dataclass(frozen=True)
class C2LaunchResultV1:
    exit_code: int
    timed_out: bool
    result_frame: bytes
    stdout: bytes
    stderr: bytes
    termination: TerminationReportV1


@dataclass(frozen=True)
class CandidateObservationV1:
    schema_version: str
    status: str
    measurements: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class C2ExecutionOutcomeV1:
    verdict: str
    code: str
    observation: CandidateObservationV1 | None
    canary_audit_receipt_sha256: str | None


class CanaryVerifierV1(Protocol):
    def verify(self, *, policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1) -> CanaryOutcomeV1: ...


class C2LaunchAdapterV1(Protocol):
    def launch(
        self,
        *,
        plan: SeatbeltPlanV1 | BubblewrapPlanV1,
        request: C2ExecutionRequestV1,
    ) -> C2LaunchResultV1: ...


class _C2Capability:
    """An identity-only private handle: it carries no serializable token."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<C2Capability redacted>"


@dataclass
class _CapabilityRecord:
    binding_digest: str
    expires_at_ns: int
    consumed: bool = False


class _CapabilityRegistry:
    """Non-exported, in-memory, single-use parent state."""

    def __init__(self, *, monotonic_ns: Callable[[], int] = time.monotonic_ns):
        self._monotonic_ns = monotonic_ns
        self._records: dict[_C2Capability, _CapabilityRecord] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        request: C2ExecutionRequestV1,
        policy: RuntimePolicyC2,
        canary_audit_sha256: str,
        plan_template_digest: str,
        *,
        ttl_ns: int,
    ) -> _C2Capability:
        request.validate()
        if ttl_ns <= 0:
            raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability lifetime is invalid")
        capability = _C2Capability()
        with self._lock:
            self._records[capability] = _CapabilityRecord(
                binding_digest=_binding_digest(request, policy, canary_audit_sha256, plan_template_digest),
                expires_at_ns=self._monotonic_ns() + ttl_ns,
            )
        return capability

    def consume(
        self,
        capability: _C2Capability,
        request: C2ExecutionRequestV1,
        policy: RuntimePolicyC2,
        canary_audit_sha256: str,
        plan_template_digest: str,
    ) -> None:
        if not isinstance(capability, _C2Capability):
            raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability was not parent-issued")
        with self._lock:
            record = self._records.get(capability)
            if record is None or record.consumed:
                raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability is unknown or replayed")
            if self._monotonic_ns() >= record.expires_at_ns:
                raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability expired")
            if record.binding_digest != _binding_digest(request, policy, canary_audit_sha256, plan_template_digest):
                raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability binding changed")
            record.consumed = True


class _UnsupportedCanary:
    def verify(self, **_kwargs: object) -> CanaryOutcomeV1:
        return CanaryOutcomeV1(False, "C2_UNSUPPORTED_HOST", None, "no real host canary has been accepted")


class _UnavailableLaunch:
    def launch(self, **_kwargs: object) -> C2LaunchResultV1:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "no reviewed launch adapter is installed")


class C2ContainmentExecutor:
    """One parent operation; it cannot issue or return a capability."""

    def __init__(
        self,
        *,
        policy: RuntimePolicyC2,
        admission: HostAdmissionV1,
        bindings: RoleBindingsV1,
        canary_verifier: CanaryVerifierV1 | None = None,
        launch_adapter: C2LaunchAdapterV1 | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ):
        policy.validate()
        self._policy = policy
        self._admission = admission
        self._bindings = bindings
        self._canary_verifier = canary_verifier or _UnsupportedCanary()
        self._launch_adapter = launch_adapter or _UnavailableLaunch()
        self._monotonic_ns = monotonic_ns
        self._registry = _CapabilityRegistry(monotonic_ns=monotonic_ns)

    def execute_c2_request(self, request: C2ExecutionRequestV1) -> C2ExecutionOutcomeV1:
        try:
            request.validate()
            if self._monotonic_ns() >= request.deadline_monotonic_ns:
                raise C2LifecycleError("C2_LIFECYCLE_FAILED", "execution deadline elapsed before launch")
            canary = self._canary_verifier.verify(policy=self._policy, admission=self._admission, bindings=self._bindings)
            if not isinstance(canary, CanaryOutcomeV1) or not canary.passed or canary.audit_receipt is None:
                code = canary.code if isinstance(canary, CanaryOutcomeV1) else "C2_CANARY_FAILED"
                return C2ExecutionOutcomeV1("non_passing", code, None, None)
            plan = _render_plan(self._policy, self._admission, self._bindings)
            if (
                canary.audit_receipt.policy_digest != self._policy.policy_digest
                or canary.audit_receipt.template_digest != plan.template_digest
                or canary.audit_receipt.host_fingerprint_sha256 != self._admission.host_fingerprint_sha256
            ):
                return C2ExecutionOutcomeV1("non_passing", "C2_CANARY_FAILED", None, None)
            receipt_sha = canary.audit_receipt.audit_record_sha256
            capability = self._registry.issue(request, self._policy, receipt_sha, plan.template_digest, ttl_ns=1_000_000_000)
            self._registry.consume(capability, request, self._policy, receipt_sha, plan.template_digest)
            result = self._launch_adapter.launch(plan=plan, request=request)
            observation = _validate_launch_result(result)
        except C2LifecycleError as error:
            return C2ExecutionOutcomeV1("non_passing", error.code, None, None)
        except Exception:
            return C2ExecutionOutcomeV1("non_passing", "C2_LIFECYCLE_FAILED", None, None)
        # Candidate status is deliberately only an observation.  The parent
        # evaluator/ingestion stage is the sole future source of a pass.
        return C2ExecutionOutcomeV1("non_passing", "C2_EVALUATOR_NONPASSING", observation, receipt_sha)


def _render_plan(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1) -> SeatbeltPlanV1 | BubblewrapPlanV1:
    if admission.backend_name == "seatbelt":
        return render_seatbelt_plan(policy, admission, bindings)
    if admission.backend_name == "bubblewrap":
        return render_bubblewrap_plan(policy, admission, bindings)
    raise C2LifecycleError("C2_UNSUPPORTED_HOST", "admitted backend has no reviewed plan renderer")


def _validate_launch_result(result: object) -> CandidateObservationV1:
    if not isinstance(result, C2LaunchResultV1):
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "launch adapter returned malformed result")
    if not all(isinstance(stream, bytes) and len(stream) <= _MAX_STREAM_BYTES for stream in (result.stdout, result.stderr)):
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "bounded stream limit exceeded")
    report = result.termination
    if not isinstance(report, TerminationReportV1) or not report.reaped or not report.descendants_reaped:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "child lifecycle did not reap all processes")
    if result.timed_out:
        if not (report.deadline_expired and report.term_sent and report.kill_sent):
            raise C2LifecycleError("C2_LIFECYCLE_FAILED", "timeout did not complete TERM then KILL lifecycle")
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "timed out candidate is non-passing")
    if report.deadline_expired or result.exit_code != 0:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "candidate lifecycle ended unexpectedly")
    return _parse_observation_frame(result.result_frame)


def _parse_observation_frame(frame: object) -> CandidateObservationV1:
    if not isinstance(frame, bytes) or len(frame) < 4:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "result frame is missing")
    declared = struct.unpack(">I", frame[:4])[0]
    if declared > _MAX_FRAME_BYTES or len(frame) != 4 + declared:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "result frame length is invalid")
    try:
        decoded = json.loads(frame[4:].decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "result frame is malformed") from error
    if not isinstance(decoded, dict) or set(decoded) != {"schema_version", "status", "measurements"} or decoded["schema_version"] != "1":
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "result frame schema is invalid")
    if decoded["status"] not in {"passed", "failed"} or not isinstance(decoded["measurements"], dict):
        raise C2LifecycleError("C2_LIFECYCLE_FAILED", "result observation fields are invalid")
    return CandidateObservationV1("1", decoded["status"], tuple(sorted(decoded["measurements"].items())))


def _binding_digest(request: C2ExecutionRequestV1, policy: RuntimePolicyC2, canary_audit_sha256: str, plan_template_digest: str) -> str:
    request.validate()
    if not _is_sha256(canary_audit_sha256) or not _is_sha256(plan_template_digest):
        raise C2LifecycleError("C2_CAPABILITY_REJECTED", "capability binding digest is malformed")
    return hashlib.sha256(
        json.dumps(
            {
                "candidate_manifest_sha256": request.candidate_manifest_sha256,
                "evaluator_manifest_sha256": request.evaluator_manifest_sha256,
                "output_root_identity_sha256": request.output_root_identity_sha256,
                "deadline_monotonic_ns": request.deadline_monotonic_ns,
                "policy_digest": policy.policy_digest,
                "runner_identity_sha256": policy.runner.content_sha256,
                "canary_audit_sha256": canary_audit_sha256,
                "plan_template_digest": plan_template_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


__all__ = [
    "C2ContainmentExecutor",
    "C2ExecutionOutcomeV1",
    "C2ExecutionRequestV1",
    "C2LaunchResultV1",
    "C2LifecycleError",
    "CandidateObservationV1",
    "TerminationReportV1",
]
