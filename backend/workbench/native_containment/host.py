"""Host identity and canary assessment facts for B1."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from ..capability_factory.contracts import _content_digest, _digest, _positive_int, _text


class HostAssessmentError(ValueError):
    """Raised when a host fact cannot be bound to a canary result."""


@dataclass(frozen=True, slots=True)
class HostIdentity:
    os_name: str
    kernel_release: str
    architecture: str
    backend_executable: str
    backend_version: str
    backend_digest: str

    def __post_init__(self) -> None:
        for field in ("os_name", "kernel_release", "architecture", "backend_version"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        path = _text(self.backend_executable, "backend_executable", maximum=1024)
        if not path.startswith("/") or "/../" in path or path.endswith("/.."):
            raise HostAssessmentError("backend_executable must be an absolute non-traversing identity")
        object.__setattr__(self, "backend_executable", path)
        object.__setattr__(self, "backend_digest", _digest(self.backend_digest, "backend_digest"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class CanaryAssertion:
    case_id: str
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        if not isinstance(self.passed, bool):
            raise HostAssessmentError("canary assertion passed must be boolean")
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=512))


@dataclass(frozen=True, slots=True)
class CanaryResult:
    status: str
    reason_code: str
    assertions: tuple[CanaryAssertion, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"supported", "unsupported", "failed"}:
            raise HostAssessmentError("unsupported canary result status")
        object.__setattr__(self, "status", self.status)
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        assertions = tuple(self.assertions)
        if len(assertions) > 32 or any(not isinstance(item, CanaryAssertion) for item in assertions):
            raise HostAssessmentError("canary assertions must be bounded")
        object.__setattr__(self, "assertions", assertions)

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    @classmethod
    def unsupported(cls, reason_code: str) -> "CanaryResult":
        return cls(status="unsupported", reason_code=reason_code)


@dataclass(frozen=True, slots=True)
class HostContainmentAssessment:
    assessment_id: str
    host: HostIdentity
    profile_id: str
    canary_suite_ref: str
    outcome: str
    reason_code: str
    validity_revision: int
    control_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_id", _text(self.assessment_id, "assessment_id"))
        if not isinstance(self.host, HostIdentity):
            raise HostAssessmentError("host must be a HostIdentity")
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "canary_suite_ref", _digest(self.canary_suite_ref, "canary_suite_ref"))
        if self.outcome not in {"supported", "unsupported", "failed"}:
            raise HostAssessmentError("unsupported host assessment outcome")
        object.__setattr__(self, "outcome", self.outcome)
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "validity_revision", _positive_int(self.validity_revision, "validity_revision"))
        if not isinstance(self.control_sequence, int) or isinstance(self.control_sequence, bool) or self.control_sequence < 0:
            raise HostAssessmentError("control_sequence must be non-negative")

    @classmethod
    def from_canary(
        cls,
        *,
        assessment_id: str,
        host: HostIdentity,
        profile_id: str,
        result: CanaryResult,
        validity_revision: int,
        control_sequence: int,
    ) -> "HostContainmentAssessment":
        if not isinstance(result, CanaryResult):
            raise HostAssessmentError("result must be a CanaryResult")
        return cls(
            assessment_id=assessment_id,
            host=host,
            profile_id=profile_id,
            canary_suite_ref=result.content_digest,
            outcome=result.status,
            reason_code=result.reason_code,
            validity_revision=validity_revision,
            control_sequence=control_sequence,
        )

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class HostContainmentValidityRecord:
    assessment_ref: str
    revision: int
    status: str
    reason_code: str
    authority_ref: str
    control_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "assessment_ref", _digest(self.assessment_ref, "assessment_ref"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        if self.status not in {"valid", "unsupported", "expired", "revoked"}:
            raise HostAssessmentError("unsupported host validity status")
        object.__setattr__(self, "status", self.status)
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "authority_ref", _digest(self.authority_ref, "authority_ref"))
        if not isinstance(self.control_sequence, int) or isinstance(self.control_sequence, bool) or self.control_sequence < 0:
            raise HostAssessmentError("control_sequence must be non-negative")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class HostContainmentValidityStore:
    """Append-only validity stream; terminal host facts cannot be restored."""

    def __init__(self) -> None:
        self._history: dict[str, list[HostContainmentValidityRecord]] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        assessment: HostContainmentAssessment,
        status: str,
        reason_code: str,
        authority_ref: str,
        control_sequence: int,
    ) -> HostContainmentValidityRecord:
        if not isinstance(assessment, HostContainmentAssessment):
            raise HostAssessmentError("assessment must be a HostContainmentAssessment")
        assessment_ref = assessment.content_digest
        with self._lock:
            history = self._history.setdefault(assessment_ref, [])
            latest = history[-1] if history else None
            if latest is not None:
                if latest.status in {"unsupported", "expired", "revoked"}:
                    raise HostAssessmentError("terminal host validity cannot be restored")
                if status == latest.status:
                    raise HostAssessmentError("duplicate host validity status")
            record = HostContainmentValidityRecord(
                assessment_ref=assessment_ref,
                revision=len(history) + 1,
                status=status,
                reason_code=reason_code,
                authority_ref=authority_ref,
                control_sequence=control_sequence,
            )
            history.append(record)
            return record

    def latest(self, assessment_ref: str) -> HostContainmentValidityRecord:
        assessment_ref = _digest(assessment_ref, "assessment_ref")
        try:
            return self._history[assessment_ref][-1]
        except (KeyError, IndexError) as error:
            raise HostAssessmentError("host validity was not found") from error

    def require_current(self, validity_ref: str) -> HostContainmentValidityRecord:
        """Resolve an exact validity record and require that it is still valid."""

        validity_ref = _digest(validity_ref, "validity_ref")
        with self._lock:
            for history in self._history.values():
                for record in history:
                    if record.content_digest != validity_ref:
                        continue
                    if history[-1] != record or record.status != "valid":
                        raise HostAssessmentError("host validity record is not current")
                    return record
        raise HostAssessmentError("host validity record was not found")


__all__ = [
    "CanaryAssertion",
    "CanaryResult",
    "HostAssessmentError",
    "HostContainmentAssessment",
    "HostContainmentValidityRecord",
    "HostContainmentValidityStore",
    "HostIdentity",
]
