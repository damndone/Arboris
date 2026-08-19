"""Candidate-bound, live-derived acceptance primitives for Workbench v1.8.9.

This module is deliberately a QA boundary.  It does not compile plans or
execute provider output itself; it derives the acceptance denominator from
the provider catalog/consumer coverage declarations and runs only the fixed
product-path commands selected by the companion runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence


SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class AcceptanceStatus(str, Enum):
    PASS = "PASS"
    COVERED = "covered"
    BLOCKED = "BLOCKED"
    NOT_VERIFIED = "NOT_VERIFIED"
    FAIL = "FAIL"


@dataclass(frozen=True)
class AcceptanceRowV1:
    provider_id: str
    provider_version: str
    path_id: str
    operation_version: str
    capability_ref: str
    consumer_id: str
    projection_ref: str
    status: AcceptanceStatus
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "path_id": self.path_id,
            "operation_version": self.operation_version,
            "capability_ref": self.capability_ref,
            "consumer_id": self.consumer_id,
            "projection_ref": self.projection_ref,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AcceptanceMatrixV1:
    rows: tuple[AcceptanceRowV1, ...]
    matrix_digest: str

    def __post_init__(self) -> None:
        expected = _digest([row.to_dict() for row in self.rows])
        if self.matrix_digest != expected:
            raise ValueError("matrix_digest does not match rows")

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def covered_count(self) -> int:
        return sum(row.status is AcceptanceStatus.COVERED for row in self.rows)

    @property
    def blocked_count(self) -> int:
        return sum(row.status is AcceptanceStatus.BLOCKED for row in self.rows)

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": [row.to_dict() for row in self.rows],
            "matrix_digest": self.matrix_digest,
            "row_count": self.row_count,
            "covered_count": self.covered_count,
            "blocked_count": self.blocked_count,
        }


class CandidateIdentityError(ValueError):
    """The candidate cannot be safely evaluated."""


@dataclass(frozen=True)
class CandidateIdentityV1:
    worktree: Path
    commit_sha: str
    parent_sha: str
    backend_source: Path
    frontend_source: Path
    interpreter: Path


@dataclass(frozen=True)
class ProviderModeResult:
    status: AcceptanceStatus
    provider_called: bool
    reason: str


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _required_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def build_acceptance_matrix(
    path_rows: Sequence[Mapping[str, object]],
    coverage_rows: Sequence[Mapping[str, object]],
) -> AcceptanceMatrixV1:
    """Expand every declared consumer path, retaining blocked rows."""

    coverage_index: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for row in coverage_rows:
        key = (
            _required_text(row.get("provider_id"), "coverage.provider_id"),
            _required_text(row.get("path_id"), "coverage.path_id"),
            _required_text(row.get("consumer_id"), "coverage.consumer_id"),
        )
        if key in coverage_index:
            raise ValueError(f"duplicate coverage row: {key}")
        coverage_index[key] = row

    rows: list[AcceptanceRowV1] = []
    for path in path_rows:
        provider_id = _required_text(path.get("provider_id"), "provider_id")
        provider_version = _required_text(path.get("provider_version"), "provider_version")
        path_id = _required_text(path.get("path_id"), "path_id")
        operation_version = _required_text(path.get("operation_version"), "operation_version")
        capability_ref = _required_text(path.get("capability_ref"), "capability_ref")
        consumers = path.get("consumers")
        if not isinstance(consumers, Sequence) or isinstance(consumers, (str, bytes)):
            raise ValueError("path.consumers must be an array")
        for consumer in consumers:
            if not isinstance(consumer, Mapping):
                raise ValueError("consumer declaration must be an object")
            consumer_id = _required_text(consumer.get("consumer_id"), "consumer_id")
            projection_ref = _required_text(consumer.get("projection_ref"), "projection_ref")
            coverage = coverage_index.get((provider_id, path_id, consumer_id))
            if coverage is None:
                status = AcceptanceStatus.BLOCKED
                reason = "projection_missing"
            elif coverage.get("status") == "covered":
                status = AcceptanceStatus.COVERED
                reason = _required_text(coverage.get("reason"), "coverage.reason")
            else:
                status = AcceptanceStatus.BLOCKED
                reason = _required_text(coverage.get("reason"), "coverage.reason")
            rows.append(
                AcceptanceRowV1(
                    provider_id=provider_id,
                    provider_version=provider_version,
                    path_id=path_id,
                    operation_version=operation_version,
                    capability_ref=capability_ref,
                    consumer_id=consumer_id,
                    projection_ref=projection_ref,
                    status=status,
                    reason=reason,
                )
            )
    immutable_rows = tuple(sorted(rows, key=lambda row: row.to_dict().__repr__()))
    return AcceptanceMatrixV1(rows=immutable_rows, matrix_digest=_digest([row.to_dict() for row in immutable_rows]))


def live_acceptance_matrix() -> AcceptanceMatrixV1:
    """Derive the denominator from the live catalog and consumer coverage."""

    from workbench.evidence.coverage import build_consumer_coverage
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    coverage = build_consumer_coverage(catalog)
    path_rows: list[dict[str, object]] = []
    for provider in catalog.providers:
        for path in provider.exposure_paths:
            path_rows.append(
                {
                    "provider_id": provider.provider_id,
                    "provider_version": provider.semantic_version,
                    "path_id": path.path_id,
                    "operation_version": path.semantic_version,
                    "capability_ref": path.capability_ref.logical_id,
                    "consumers": [
                        {"consumer_id": consumer_id, "projection_ref": ref.logical_id}
                        for consumer_id, ref in sorted(path.projection_refs.items())
                    ],
                }
            )
    coverage_rows = [
        {
            "provider_id": row.raw_key.provider_id,
            "path_id": row.raw_key.exposure_path,
            "consumer_id": row.raw_key.consumer_id,
            "status": row.status,
            "reason": row.reason,
        }
        for row in coverage.rows
    ]
    return build_acceptance_matrix(path_rows, coverage_rows)


def _git(worktree: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), *args],
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateIdentityError(f"candidate git identity unavailable: {error}") from error
    return result.stdout.strip()


def _is_regular_directory(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _allowed_ignored(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized == ".venv" or normalized.startswith(".venv/") or normalized == "frontend/node_modules" or normalized.startswith("frontend/node_modules/")


def inspect_candidate(worktree: Path, candidate_sha: str, *, interpreter: str | Path | None = None) -> CandidateIdentityV1:
    """Prove candidate identity and reject all source dirt before evaluation."""

    worktree = Path(worktree)
    if not _is_regular_directory(worktree):
        raise CandidateIdentityError("candidate worktree is unavailable or unsafe")
    if type(candidate_sha) is not str or not SHA1_RE.fullmatch(candidate_sha):
        raise CandidateIdentityError("candidate SHA is invalid")
    actual_sha = _git(worktree, "rev-parse", "HEAD")
    if actual_sha != candidate_sha:
        raise CandidateIdentityError("candidate SHA does not match HEAD")
    status = _git(worktree, "status", "--short", "--ignored", "--untracked-files=all")
    dirty: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        path = line[3:]
        if code == "!!" and _allowed_ignored(path):
            continue
        dirty.append(line)
    if dirty:
        raise CandidateIdentityError("candidate worktree is dirty: " + "; ".join(dirty[:4]))
    backend_source = worktree / "backend"
    frontend_source = worktree / "frontend" / "src"
    if not _is_regular_directory(backend_source) or not _is_regular_directory(frontend_source):
        raise CandidateIdentityError("candidate source roots are unavailable")
    # Keep the lexical venv entrypoint for execution.  Resolving it here would
    # turn .venv/bin/python into the host interpreter and silently drop the
    # venv site-packages (including pytest).  Trust is checked on the real
    # target, while the original entrypoint is deliberately preserved.
    selected = Path(sys.executable if interpreter is None else interpreter).absolute()
    try:
        info = os.stat(selected)
    except OSError as error:
        raise CandidateIdentityError("candidate interpreter is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or not (info.st_mode & 0o111):
        raise CandidateIdentityError("candidate interpreter is not executable")
    if selected.resolve() != Path(sys.executable).resolve():
        raise CandidateIdentityError("candidate interpreter is not the trusted environment")
    try:
        parent_sha = _git(worktree, "rev-parse", "HEAD^")
    except CandidateIdentityError:
        parent_sha = ""
    return CandidateIdentityV1(
        worktree=worktree.resolve(),
        commit_sha=actual_sha,
        parent_sha=parent_sha,
        backend_source=backend_source.resolve(),
        frontend_source=frontend_source.resolve(),
        interpreter=selected,
    )


def candidate_integrity_status(
    worktree: Path,
    candidate_sha: str,
    *,
    interpreter: str | Path | None = None,
) -> dict[str, str]:
    """Return a typed post-command integrity result without hiding failures."""

    try:
        inspect_candidate(worktree, candidate_sha, interpreter=interpreter)
    except CandidateIdentityError as error:
        return {"status": AcceptanceStatus.FAIL.value, "reason": str(error)}
    return {"status": AcceptanceStatus.PASS.value, "reason": "candidate remained unchanged"}


def provider_mode_status(*, provider_requested: bool, provider_configured: bool) -> ProviderModeResult:
    if not provider_requested:
        return ProviderModeResult(AcceptanceStatus.NOT_VERIFIED, False, "provider mode was not requested")
    if not provider_configured:
        return ProviderModeResult(AcceptanceStatus.NOT_VERIFIED, False, "provider is not explicitly configured")
    return ProviderModeResult(AcceptanceStatus.NOT_VERIFIED, False, "provider execution requires an authorized provider adapter")


def write_sidecar_once(path: Path, payload: Mapping[str, object]) -> None:
    """Write a canonical sidecar exactly once, without overwriting evidence."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


__all__ = [
    "AcceptanceMatrixV1",
    "AcceptanceRowV1",
    "AcceptanceStatus",
    "CandidateIdentityError",
    "CandidateIdentityV1",
    "ProviderModeResult",
    "build_acceptance_matrix",
    "candidate_integrity_status",
    "inspect_candidate",
    "live_acceptance_matrix",
    "provider_mode_status",
    "write_sidecar_once",
]
