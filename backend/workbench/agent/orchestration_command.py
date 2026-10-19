"""orchestration command: extracted behavior owner."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class AgentCommand:
    """A durable Main Agent to Chain Agent dispatch envelope."""

    command_id: str
    dispatch_seq: int
    child_agent_id: str
    chain_id: str
    objective: str
    allowed_operations: tuple[str, ...]
    budget: dict[str, Any]
    context_fingerprint: str | None = None
    command_type: str = "inspect"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "dispatch_seq": self.dispatch_seq,
            "child_agent_id": self.child_agent_id,
            "chain_id": self.chain_id,
            "objective": self.objective,
            "allowed_operations": list(self.allowed_operations),
            "budget": dict(self.budget),
            "context_fingerprint": self.context_fingerprint,
            "command_type": self.command_type,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentCommand":
        return cls(
            command_id=str(value["command_id"]),
            dispatch_seq=int(value["dispatch_seq"]),
            child_agent_id=str(value["child_agent_id"]),
            chain_id=str(value["chain_id"]),
            objective=str(value["objective"]),
            allowed_operations=tuple(str(item) for item in value.get("allowed_operations", [])),
            budget=dict(value.get("budget") or {}),
            context_fingerprint=value.get("context_fingerprint"),
            command_type=str(value.get("command_type", "inspect")),
        )

