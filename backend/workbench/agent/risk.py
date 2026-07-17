"""Durable, one-time authorization for registry-defined high-risk operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import fcntl
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .storage import append_jsonl_atomic, read_jsonl


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RiskAuthorizationError(RuntimeError):
    """Base class for fail-closed high-risk authorization errors."""


class RiskAuthorizationRequired(RiskAuthorizationError):
    """The high-risk operation has no valid authorization binding."""


class RiskAuthorizationExpired(RiskAuthorizationError):
    """The authorization passed its short validity window."""


class RiskAuthorizationReplay(RiskAuthorizationError):
    """A one-time authorization was replayed with another execution identity."""


class RiskAuthorizationStale(RiskAuthorizationError):
    """The proposal or active-head binding no longer matches."""


@dataclass(frozen=True)
class RiskAuthorization:
    authorization_id: str
    operation_id: str
    operation_version: str
    proposal_id: str
    revision: int
    fingerprint: str
    session_id: str
    chain_id: str
    active_head_run_id: str
    actor_type: str
    issued_at: str
    expires_at: str
    status: str = "issued"
    consumed_at: str | None = None
    execution_key: str | None = None
    token: str | None = None

    def to_dict(self, *, include_token: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "record_type": "risk_authorization",
            "authorization_id": self.authorization_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "revision": self.revision,
            "fingerprint": self.fingerprint,
            "session_id": self.session_id,
            "chain_id": self.chain_id,
            "active_head_run_id": self.active_head_run_id,
            "actor_type": self.actor_type,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "status": self.status,
            "consumed_at": self.consumed_at,
            "execution_key": self.execution_key,
        }
        if include_token and self.token is not None:
            value["token"] = self.token
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RiskAuthorization":
        return cls(
            authorization_id=str(value["authorization_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            proposal_id=str(value["proposal_id"]),
            revision=int(value["revision"]),
            fingerprint=str(value["fingerprint"]),
            session_id=str(value["session_id"]),
            chain_id=str(value["chain_id"]),
            active_head_run_id=str(value["active_head_run_id"]),
            actor_type=str(value["actor_type"]),
            issued_at=str(value["issued_at"]),
            expires_at=str(value["expires_at"]),
            status=str(value.get("status", "issued")),
            consumed_at=value.get("consumed_at"),
            execution_key=value.get("execution_key"),
        )


class RiskAuthorizationStore:
    """Project-local append-only risk authorization store.

    The raw token is intentionally never written to disk. This store is
    single-worker compatible with the existing Workbench JSONL stores. The
    in-process lock protects re-entrant calls and the per-authorization file
    lock makes the read/check/append consume transition atomic across
    request-local store instances and worker processes.
    """

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.authorizations_dir = self.root / "risk-authorizations"
        if create:
            self.authorizations_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def issue(
        self,
        *,
        operation_id: str,
        operation_version: str,
        proposal_id: str,
        revision: int,
        fingerprint: str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        actor_type: str,
        ttl_seconds: int = 300,
    ) -> RiskAuthorization:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        issued_at = _now()
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
        token = secrets.token_urlsafe(32)
        authorization = RiskAuthorization(
            authorization_id=f"risk_{uuid4().hex}",
            operation_id=operation_id,
            operation_version=operation_version,
            proposal_id=proposal_id,
            revision=revision,
            fingerprint=fingerprint,
            session_id=session_id,
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            actor_type=actor_type,
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat(),
            token=token,
        )
        with self._lock:
            append_jsonl_atomic(
                self._path(authorization.authorization_id),
                {
                    **authorization.to_dict(),
                    "token_digest": self._digest(token),
                },
            )
        return authorization

    def read(self, authorization_id: str) -> dict[str, Any]:
        records = read_jsonl(self._path(authorization_id))
        if not records:
            raise KeyError(f"unknown risk authorization: {authorization_id}")
        return dict(records[-1])

    def consume(
        self,
        authorization_id: str,
        *,
        token: str,
        operation_id: str,
        operation_version: str,
        proposal_id: str,
        revision: int,
        fingerprint: str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        execution_key: str,
    ) -> RiskAuthorization:
        with self._lock, self._file_lock(authorization_id):
            current = self._current(authorization_id)
            if not hmac.compare_digest(
                str(current.get("token_digest", "")), self._digest(token)
            ):
                raise RiskAuthorizationReplay("risk authorization token mismatch")
            expected = self._binding(
                operation_id=operation_id,
                operation_version=operation_version,
                proposal_id=proposal_id,
                revision=revision,
                fingerprint=fingerprint,
                session_id=session_id,
                chain_id=chain_id,
                active_head_run_id=active_head_run_id,
            )
            self._check_binding(current, expected)
            if current.get("status") == "consumed":
                if current.get("execution_key") == execution_key:
                    return RiskAuthorization.from_dict(current)
                raise RiskAuthorizationReplay("risk authorization was already consumed")
            if self._expired(current):
                raise RiskAuthorizationExpired("risk authorization expired")
            consumed = {
                **current,
                "status": "consumed",
                "consumed_at": _now().isoformat(),
                "execution_key": execution_key,
            }
            append_jsonl_atomic(self._path(authorization_id), consumed)
            return RiskAuthorization.from_dict(consumed)

    def require_consumed(
        self,
        authorization_id: str,
        *,
        operation_id: str,
        operation_version: str,
        proposal_id: str,
        revision: int,
        fingerprint: str,
        session_id: str,
        chain_id: str,
        active_head_run_id: str,
        execution_key: str,
    ) -> RiskAuthorization:
        with self._lock, self._file_lock(authorization_id):
            current = self._current(authorization_id)
            expected = self._binding(
                operation_id=operation_id,
                operation_version=operation_version,
                proposal_id=proposal_id,
                revision=revision,
                fingerprint=fingerprint,
                session_id=session_id,
                chain_id=chain_id,
                active_head_run_id=active_head_run_id,
            )
            self._check_binding(current, expected)
            if current.get("status") != "consumed":
                raise RiskAuthorizationRequired("risk authorization has not been consumed")
            if current.get("execution_key") != execution_key:
                raise RiskAuthorizationReplay("risk authorization execution key mismatch")
            return RiskAuthorization.from_dict(current)

    def _current(self, authorization_id: str) -> dict[str, Any]:
        try:
            current = self.read(authorization_id)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            raise RiskAuthorizationRequired("risk authorization was not found") from exc
        return current

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _binding(**kwargs: Any) -> dict[str, Any]:
        return kwargs

    @staticmethod
    def _check_binding(current: dict[str, Any], expected: dict[str, Any]) -> None:
        for key, value in expected.items():
            if current.get(key) != value:
                raise RiskAuthorizationStale(
                    f"risk authorization binding changed: {key}"
                )

    @staticmethod
    def _expired(current: dict[str, Any]) -> bool:
        return _now() >= datetime.fromisoformat(str(current["expires_at"]))

    def _path(self, authorization_id: str) -> Path:
        if not authorization_id or Path(authorization_id).name != authorization_id:
            raise ValueError("authorization_id must be path-safe")
        return self.authorizations_dir / f"{authorization_id}.jsonl"

    @contextmanager
    def _file_lock(self, authorization_id: str):
        """Serialize authorization transitions across store instances/processes."""

        self._path(authorization_id)
        lock_path = self.authorizations_dir / f".{authorization_id}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
