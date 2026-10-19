"""The shared, durable authority for a confirmed operation's execution.

Capability receipts and risk tokens describe execution bindings. Neither can
replace this approval or extend its lifetime, scope or revocation state.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from threading import RLock

from .jsonl_store import append_jsonl_atomic, read_jsonl


class OperationApprovalError(ValueError):
    """An operation has no usable approval for the requested execution."""


class OperationApprovalStore:
    def __init__(self, root, *, clock=None):
        self.root = Path(root)
        self.directory = self.root / "operation-approvals"
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self._lock = RLock()

    def _path(self, approval_id):
        if not approval_id or Path(approval_id).name != approval_id:
            raise ValueError("approval_id must be path-safe")
        return self.directory / f"{approval_id}.jsonl"

    @contextmanager
    def _locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._lock, (self.directory / ".control.lock").open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self, approval_id):
        rows = read_jsonl(self._path(approval_id))
        if not rows:
            raise OperationApprovalError("operation approval is missing")
        return rows[-1]

    def issue(self, confirmation, *, ttl_seconds=300):
        """Called after the common policy and confirmation gate, never by a model."""
        binding = {key:confirmation.to_dict()[key] for key in (
            "proposal_id", "revision", "fingerprint", "operation_id", "operation_version", "session_id", "chain_id")}
        approval_id = "approval_" + hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        with self._locked():
            if self._path(approval_id).exists():
                return self.read(approval_id)
            issued = datetime.fromisoformat(confirmation.confirmed_at)
            row = {**binding, "approval_id":approval_id, "actor_type":confirmation.actor_type,
                "status":"approved", "issued_at":issued.isoformat(),
                "expires_at":(issued + timedelta(seconds=ttl_seconds)).isoformat(),
                "execution_key":None}
            append_jsonl_atomic(self._path(approval_id), row)
            return row

    def claim(self, approval_id, *, execution_key, credential_digest=None):
        with self._locked():
            current = self.read(approval_id)
            if current["status"] == "revoked":
                raise OperationApprovalError("operation approval was revoked")
            if current["execution_key"] is not None:
                if current["execution_key"] != execution_key:
                    raise OperationApprovalError("operation approval belongs to another execution")
                if credential_digest is None or current.get("credential_digest") == credential_digest:
                    return current
                if current.get("credential_digest") is not None:
                    raise OperationApprovalError("operation approval is bound to another execution credential")
            elif self.clock() >= datetime.fromisoformat(current["expires_at"]):
                raise OperationApprovalError("operation approval expired before execution")
            row = {**current, "status":"claimed", "execution_key":execution_key,
                   "claimed_at":current.get("claimed_at") or self.clock().isoformat(),
                   "credential_digest":credential_digest}
            append_jsonl_atomic(self._path(approval_id), row)
            return row

    def revoke(self, approval_id, *, actor_type):
        with self._locked():
            current = self.read(approval_id)
            if current["status"] == "revoked":
                return current
            row = {**current, "status":"revoked", "revoked_by":actor_type,
                   "revoked_at":self.clock().isoformat()}
            append_jsonl_atomic(self._path(approval_id), row)
            return row

    def start(self, approval_id, *, execution_key):
        with self._locked():
            current = self.read(approval_id)
            if current["status"] == "revoked":
                raise OperationApprovalError("operation approval was revoked")
            if current["execution_key"] != execution_key:
                raise OperationApprovalError("operation approval execution changed")
            if current.get("started_at") is not None:
                return current
            row = {**current, "started_at":self.clock().isoformat()}
            append_jsonl_atomic(self._path(approval_id), row)
            return row

    @contextmanager
    def dispatch_permit(self, approval_id, *, execution_key, credential_digest):
        """Serialize the last dispatch boundary with revocation of this approval."""
        with self._locked():
            current = self.read(approval_id)
            if current["status"] == "revoked":
                raise OperationApprovalError("operation approval was revoked")
            if current["status"] != "claimed" or current["execution_key"] != execution_key:
                raise OperationApprovalError("operation approval execution is not claimed")
            if current.get("credential_digest") != credential_digest:
                raise OperationApprovalError("operation approval execution credential changed")
            yield current

    def require_binding(self, approval_id, *, proposal_id, fingerprint, execution_key, credential_digest=None, reconcile=False):
        """Bind a derived execution credential to its original approved proposal."""
        if not approval_id:
            raise OperationApprovalError("operation approval is missing")
        with self._locked():
            current = self.read(approval_id)
            if current["proposal_id"] != proposal_id or current["fingerprint"] != fingerprint:
                raise OperationApprovalError("operation approval proposal binding changed")
            if reconcile and current.get("started_at") is not None and current["execution_key"] == execution_key:
                return current
        return self.claim(approval_id, execution_key=execution_key, credential_digest=credential_digest)
