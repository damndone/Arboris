"""Deterministic phases consumed by the existing AgentCore provider step."""

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Mapping, Protocol, Sequence, TypeVar

from .model import ModelStreamEvent

T = TypeVar("T")


class RecordedProviderError(Exception):
    """A persisted provider failure retains its original type without importing it."""

    def __init__(self, original_type):
        self.original_type = original_type
        super().__init__(original_type)


@dataclass(frozen=True)
class PhaseRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    response_schema: dict[str, Any] | None = None
    model_config: Mapping[str, Any] = field(default_factory=dict)
    provider_timeout_s: float | None = None


@dataclass(frozen=True)
class PhaseStep(Generic[T]):
    next: Literal["continue", "completed", "refused"]
    append_messages: tuple[dict[str, Any], ...] = ()
    result: T | None = None
    public_result: Mapping[str, Any] = field(default_factory=dict)


class CorePhase(Protocol[T]):
    """A replay-safe phase consumes original events without external writes.

    Only Core commits its returned transition. Mutating planning phases must
    leave replay_safe false and reconcile an unknown transition explicitly.
    """
    episode_id: str

    replay_safe: bool

    def request(self, transcript: Sequence[dict[str, Any]]) -> PhaseRequest | PhaseStep[T]: ...

    async def consume(
        self,
        events: Sequence[ModelStreamEvent],
        *,
        error: Exception | None = None,
    ) -> PhaseStep[T]: ...

    def checkpoint(self) -> dict[str, Any]: ...

    def failure(self, reason: str, error: Exception | None = None) -> Exception: ...
