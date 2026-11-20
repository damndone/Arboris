"""orchestration commands: methods over the existing shared state."""
from __future__ import annotations
import asyncio
from typing import Any, Iterable
from uuid import uuid4
from .orchestration_command import (AgentCommand)

class OrchestrationCommands:
    def dispatch_to_chain(
        self,
        chain_id: str,
        *,
        objective: str,
        allowed_operations: Iterable[str],
        budget: dict[str, Any],
        context_fingerprint: str | None = None,
        command_type: str = "inspect",
        command_id: str | None = None,
    ) -> AgentCommand:
        """Append and publish one Main→Chain command, idempotently."""

        existing = self._load_command(command_id) if command_id else None
        if existing is not None:
            return existing
        try:
            session_id, _agent = self._chains[chain_id]
        except KeyError as exc:
            raise KeyError(f"unknown chain: {chain_id}") from exc

        command = AgentCommand(
            command_id=command_id or uuid4().hex,
            dispatch_seq=self._next_dispatch_seq(chain_id),
            child_agent_id=session_id,
            chain_id=chain_id,
            objective=objective,
            allowed_operations=tuple(allowed_operations),
            budget=dict(budget),
            context_fingerprint=context_fingerprint,
            command_type=command_type,
        )
        self.repository.append(
            session_id,
            "custom_message",
            {
                "message_type": "main_to_chain_command",
                "audience": "model",
                "content": objective,
                "command": command.to_dict(),
            },
        )
        self.events.emit(
            self.main_session_id,
            "command_dispatched",
            command.to_dict(),
            command_id=command.command_id,
        )
        self._commands[command.command_id] = command
        return command


    async def execute(self, command_id: str) -> str:
        """Run a dispatched chain command through its AgentCore exactly once at a time."""

        command = self._load_command(command_id)
        if command is None:
            raise KeyError(f"unknown agent command: {command_id}")
        completed = self._completed_result(command_id)
        if completed is not None:
            return completed
        lock = self._execution_locks.setdefault(command_id, asyncio.Lock())
        async with lock:
            completed = self._completed_result(command_id)
            if completed is not None:
                return completed
            _session_id, agent = self._chains[command.chain_id]
            result = await agent.prompt(
                command.objective,
                tool_context={
                    "command_id": command.command_id,
                    "allowed_operations": list(command.allowed_operations),
                    "context_fingerprint": command.context_fingerprint,
                },
                budget=command.budget,
            )
            self.events.emit(
                self.main_session_id,
                "command_completed",
                {"command_id": command.command_id, "chain_id": command.chain_id, "result": result},
                command_id=command.command_id,
            )
            return result


    def _load_command(self, command_id: str | None) -> AgentCommand | None:
        if command_id is None:
            return None
        if command_id in self._commands:
            return self._commands[command_id]
        for event in self.events.replay(self.main_session_id):
            if event.event_type == "command_dispatched" and event.payload.get("command_id") == command_id:
                command = AgentCommand.from_dict(event.payload)
                self._commands[command_id] = command
                return command
        return None


    def _next_dispatch_seq(self, chain_id: str) -> int:
        sequence = [
            int(event.payload.get("dispatch_seq", 0))
            for event in self.events.replay(self.main_session_id)
            if event.event_type == "command_dispatched"
            and event.payload.get("chain_id") == chain_id
        ]
        return max(sequence, default=0) + 1


    def _completed_result(self, command_id: str) -> str | None:
        for event in self.events.replay(self.main_session_id):
            if event.event_type == "command_completed" and event.payload.get("command_id") == command_id:
                return str(event.payload.get("result", ""))
        return None

