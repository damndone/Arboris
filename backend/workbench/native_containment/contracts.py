"""Generic B1 broker request/report contracts.

Only content-addressed references, attempt identity, pre-opened handle
references, and bounded budgets cross this boundary.  No host path, command,
source code, credential, or user payload is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..capability_factory.contracts import _content_digest, _digest, _positive_int, _text


class ResourceBudgetError(ValueError):
    """Raised when a process-tree resource budget is unsafe or unbounded."""


class ContainmentRequestError(ValueError):
    """Raised when a broker request contains an unsafe identity or path."""


class ContainmentReportError(ValueError):
    """Raised when a broker report is not a typed terminal result."""


def _safe_handle(value: str, field: str) -> str:
    value = _text(value, field, maximum=256)
    if value in {".", ".."} or "/" in value or chr(92) in value:
        raise ContainmentRequestError(f"{field} must be a handle identifier, not a path")
    return value


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    cpu_millis: int
    wall_millis: int
    memory_bytes: int
    pid_count: int
    stdout_bytes: int
    stderr_bytes: int

    def __post_init__(self) -> None:
        for field in (
            "cpu_millis",
            "wall_millis",
            "memory_bytes",
            "pid_count",
            "stdout_bytes",
            "stderr_bytes",
        ):
            try:
                value = _positive_int(getattr(self, field), field)
            except ValueError as error:
                raise ResourceBudgetError(str(error)) from error
            object.__setattr__(self, field, value)
        if self.cpu_millis > 86_400_000 or self.wall_millis > 86_400_000:
            raise ResourceBudgetError("CPU and wall budgets exceed the one-day hard limit")
        if self.memory_bytes > 64 * 1024 * 1024 * 1024:
            raise ResourceBudgetError("memory budget exceeds the hard limit")
        if self.pid_count > 4096:
            raise ResourceBudgetError("PID budget exceeds the hard limit")
        if self.stdout_bytes > 64 * 1024 * 1024 or self.stderr_bytes > 64 * 1024 * 1024:
            raise ResourceBudgetError("output budget exceeds the hard limit")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class ContainmentRequest:
    request_id: str
    attempt_id: str
    intent_digest: str
    input_bundle_ref: str
    output_namespace_ref: str
    policy_digest: str
    harness_digest: str
    preopened_handle_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("request_id", "attempt_id"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in (
            "intent_digest",
            "input_bundle_ref",
            "output_namespace_ref",
            "policy_digest",
            "harness_digest",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        handles = tuple(_safe_handle(item, "preopened_handle_ref") for item in self.preopened_handle_refs)
        if len(handles) > 32 or len(set(handles)) != len(handles):
            raise ContainmentRequestError("preopened_handle_refs must be bounded and unique")
        object.__setattr__(self, "preopened_handle_refs", handles)

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


_REPORT_STATUSES = frozenset({"completed", "failed", "unsupported", "dispatch_unknown"})


@dataclass(frozen=True, slots=True)
class ContainmentReport:
    attempt_id: str
    request_digest: str
    status: str
    reason_code: str
    assessment_ref: str | None = None
    output_bundle_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "request_digest", _digest(self.request_digest, "request_digest"))
        if self.status not in _REPORT_STATUSES:
            raise ContainmentReportError("unsupported containment report status")
        object.__setattr__(self, "status", self.status)
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        for field in ("assessment_ref", "output_bundle_ref"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _digest(value, field))
        if self.status == "completed" and self.output_bundle_ref is None:
            raise ContainmentReportError("completed containment requires output_bundle_ref")
        if self.status == "completed" and self.assessment_ref is None:
            raise ContainmentReportError("completed containment requires assessment_ref")
        if self.status != "completed" and self.output_bundle_ref is not None:
            raise ContainmentReportError("non-completed containment cannot expose output_bundle_ref")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = [
    "ContainmentReport",
    "ContainmentReportError",
    "ContainmentRequest",
    "ContainmentRequestError",
    "ResourceBudget",
    "ResourceBudgetError",
]
