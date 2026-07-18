"""Append-only logical storage for Agent Analysis Loop plan packets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from ..agent.storage import append_jsonl_atomic, read_jsonl
from .plan import PlanDiff, PlanValidationError
from .validation import ValidationPacket


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TerminalPacketConflictError(ValueError):
    """A terminal packet already exists for the logical key with other content."""


@dataclass(frozen=True)
class TerminalPacket:
    logical_key: str
    plan_diff: PlanDiff
    created_at: str
    status: str = "complete"
    packet_type: str = "plan_diff"

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_type": self.packet_type,
            "status": self.status,
            "logical_key": self.logical_key,
            "created_at": self.created_at,
            "plan_diff": self.plan_diff.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TerminalPacket":
        packet = cls(
            logical_key=str(value["logical_key"]),
            plan_diff=PlanDiff.from_dict(value["plan_diff"]),
            created_at=str(value["created_at"]),
            status=str(value.get("status", "complete")),
            packet_type=str(value.get("packet_type", "plan_diff")),
        )
        if packet.status != "complete" or packet.packet_type != "plan_diff":
            raise ValueError("terminal packet has an unsupported status or type")
        if packet.logical_key != packet.plan_diff.logical_key:
            raise ValueError("terminal packet logical key does not match plan diff")
        return packet


class PlanDiffStore:
    """Store attempts append-only and terminal plans write-once by logical key."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        supplied_root = Path(root)
        self.workbench_root = (
            supplied_root if supplied_root.name == "workbench" else supplied_root / "workbench"
        )
        self.root = self.workbench_root / "analysis-packets"
        self.attempts_path = self.root / "build-attempts.jsonl"
        self.terminals_dir = self.root / "terminal"
        if create:
            self.terminals_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def persist_terminal_plan(self, plan_diff: PlanDiff) -> TerminalPacket:
        if not isinstance(plan_diff, PlanDiff):
            raise TypeError("plan_diff must be a PlanDiff")
        with self._lock:
            existing = self.get_terminal_packet(plan_diff.logical_key)
            candidate = TerminalPacket(
                logical_key=plan_diff.logical_key,
                plan_diff=plan_diff,
                created_at=_now(),
            )
            if existing is not None:
                if existing.to_dict()["plan_diff"] != candidate.to_dict()["plan_diff"]:
                    raise TerminalPacketConflictError(
                        f"terminal plan cannot be replaced: {plan_diff.logical_key}"
                    )
                self._append_attempt(
                    logical_key=plan_diff.logical_key,
                    status="reused",
                    plan_hash=plan_diff.plan_hash,
                )
                return existing

            path = self._terminal_path(plan_diff.logical_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                existing = self.get_terminal_packet(plan_diff.logical_key)
                if existing is not None and existing.to_dict()["plan_diff"] == candidate.to_dict()["plan_diff"]:
                    return existing
                raise TerminalPacketConflictError(
                    f"terminal plan cannot be replaced: {plan_diff.logical_key}"
                )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(candidate.to_dict(), handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            self._append_attempt(
                logical_key=plan_diff.logical_key,
                status="completed",
                plan_hash=plan_diff.plan_hash,
            )
            return candidate

    persist_plan = persist_terminal_plan
    persist_terminal_packet = persist_terminal_plan

    def build_plan(
        self,
        *,
        logical_key: str,
        builder: Callable[[], PlanDiff],
    ) -> TerminalPacket:
        existing = self.get_terminal_packet(logical_key)
        if existing is not None:
            self._append_attempt(
                logical_key=logical_key,
                status="reused",
                plan_hash=existing.plan_diff.plan_hash,
            )
            return existing
        try:
            plan_diff = builder()
            if not isinstance(plan_diff, PlanDiff):
                raise TypeError("plan builder must return PlanDiff")
            if plan_diff.logical_key != logical_key:
                raise PlanValidationError(
                    "built plan logical key does not match the requested key",
                    code="PLAN_LOGICAL_KEY_MISMATCH",
                )
            return self.persist_terminal_plan(plan_diff)
        except Exception as exc:
            self._append_attempt(
                logical_key=logical_key,
                status="failed",
                error={
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                },
            )
            raise

    build = build_plan

    def get_terminal_packet(self, logical_key: str) -> TerminalPacket | None:
        path = self._terminal_path(logical_key)
        if not path.exists():
            return None
        return TerminalPacket.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_terminal_packets(self) -> list[TerminalPacket]:
        if not self.terminals_dir.exists():
            return []
        return [
            TerminalPacket.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.terminals_dir.glob("*.json"))
        ]

    def list_build_attempts(self, *, logical_key: str | None = None) -> list[dict[str, Any]]:
        attempts = read_jsonl(self.attempts_path)
        if logical_key is None:
            return attempts
        return [item for item in attempts if item.get("logical_key") == logical_key]

    def _append_attempt(
        self,
        *,
        logical_key: str,
        status: str,
        plan_hash: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        append_jsonl_atomic(
            self.attempts_path,
            {
                "record_type": "plan_build_attempt",
                "attempt_id": f"attempt_{uuid4().hex}",
                "logical_key": logical_key,
                "status": status,
                "plan_hash": plan_hash,
                "error": error,
                "created_at": _now(),
            },
        )

    def _terminal_path(self, logical_key: str) -> Path:
        if not logical_key or Path(logical_key).name != logical_key:
            raise ValueError("logical_key must be path-safe")
        return self.terminals_dir / f"{logical_key}.json"


class ValidationPacketStore:
    """Append-only attempts and write-once terminal ValidationPackets."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        supplied_root = Path(root)
        self.workbench_root = (
            supplied_root if supplied_root.name == "workbench" else supplied_root / "workbench"
        )
        self.root = self.workbench_root / "analysis-packets"
        self.attempts_path = self.root / "validation-build-attempts.jsonl"
        self.terminals_dir = self.root / "validation-terminal"
        if create:
            self.terminals_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def persist_terminal_packet(self, packet: ValidationPacket) -> ValidationPacket:
        if not isinstance(packet, ValidationPacket):
            raise TypeError("packet must be a ValidationPacket")
        if packet.status == "pending":
            raise ValueError("pending validation packets cannot be terminalized")
        with self._lock:
            existing = self.get_terminal_packet(packet.logical_key)
            if existing is not None:
                if existing.to_dict() != packet.to_dict():
                    raise TerminalPacketConflictError(
                        f"terminal validation packet cannot be replaced: {packet.logical_key}"
                    )
                self._append_attempt(
                    logical_key=packet.logical_key,
                    status="reused",
                    packet=packet,
                )
                return existing

            path = self._terminal_path(packet.logical_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                existing = self.get_terminal_packet(packet.logical_key)
                if existing is not None and existing.to_dict() == packet.to_dict():
                    return existing
                raise TerminalPacketConflictError(
                    f"terminal validation packet cannot be replaced: {packet.logical_key}"
                )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(packet.to_dict(), handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            self._append_attempt(
                logical_key=packet.logical_key,
                status="completed",
                packet=packet,
            )
            return packet

    def build_packet(
        self,
        *,
        logical_key: str,
        builder: Callable[[], ValidationPacket],
    ) -> ValidationPacket:
        existing = self.get_terminal_packet(logical_key)
        if existing is not None:
            self._append_attempt(
                logical_key=logical_key,
                status="reused",
                packet=existing,
            )
            return existing
        try:
            packet = builder()
            if not isinstance(packet, ValidationPacket):
                raise TypeError("validation packet builder must return ValidationPacket")
            if packet.logical_key != logical_key:
                raise ValueError("validation packet logical key does not match requested key")
            if packet.status == "pending":
                self._append_attempt(
                    logical_key=logical_key,
                    status="pending",
                    packet=packet,
                )
                return packet
            return self.persist_terminal_packet(packet)
        except Exception as exc:
            self._append_attempt(
                logical_key=logical_key,
                status="failed",
                packet=None,
                error={
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", type(exc).__name__),
                    "message": str(exc),
                },
            )
            raise

    build = build_packet

    def get_terminal_packet(self, logical_key: str) -> ValidationPacket | None:
        path = self._terminal_path(logical_key)
        if not path.exists():
            return None
        return ValidationPacket.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_terminal_packets(self) -> list[ValidationPacket]:
        if not self.terminals_dir.exists():
            return []
        return [
            ValidationPacket.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.terminals_dir.glob("*.json"))
        ]

    def list_build_attempts(self, *, logical_key: str | None = None) -> list[dict[str, Any]]:
        attempts = read_jsonl(self.attempts_path)
        if logical_key is None:
            return attempts
        return [item for item in attempts if item.get("logical_key") == logical_key]

    def _append_attempt(
        self,
        *,
        logical_key: str,
        status: str,
        packet: ValidationPacket | None,
        error: dict[str, Any] | None = None,
    ) -> None:
        append_jsonl_atomic(
            self.attempts_path,
            {
                "record_type": "validation_build_attempt",
                "attempt_id": f"attempt_{uuid4().hex}",
                "logical_key": logical_key,
                "status": status,
                "packet_status": packet.status if packet is not None else None,
                "error": error,
                "created_at": _now(),
            },
        )

    def _terminal_path(self, logical_key: str) -> Path:
        if not logical_key or Path(logical_key).name != logical_key:
            raise ValueError("logical_key must be path-safe")
        return self.terminals_dir / f"{logical_key}.json"


AnalysisPacketStore = PlanDiffStore
PlanStorage = PlanDiffStore
TerminalPacketConflict = TerminalPacketConflictError


__all__ = [
    "AnalysisPacketStore",
    "PlanDiffStore",
    "PlanStorage",
    "TerminalPacket",
    "TerminalPacketConflict",
    "TerminalPacketConflictError",
    "ValidationPacketStore",
]
