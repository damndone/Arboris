"""Candidate-bound acceptance primitives for Workbench v1.8.9.

This module is an acceptance boundary, not a second product runtime.  It
derives its denominator from the live provider catalog and consumer coverage
declarations, preserves blocked rows, and verifies that a candidate remains an
unchanged exact commit while fixed product-path tests run.
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AcceptanceStatus(str, Enum):
    PASS = "PASS"
    COVERED = "covered"
    BLOCKED = "BLOCKED"
    NOT_VERIFIED = "NOT_VERIFIED"
    FAIL = "FAIL"


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _required_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _required_digest(value: object, name: str) -> str:
    value = _required_text(value, name)
    if SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _ref_identity(ref: object) -> str:
    logical_id = getattr(ref, "logical_id", None)
    semantic_version = getattr(ref, "semantic_version", None)
    kind = getattr(ref, "kind", None)
    if not all(type(value) is str and value for value in (kind, logical_id, semantic_version)):
        raise ValueError("contract reference is unavailable")
    return f"{kind}:{logical_id}@{semantic_version}"


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
    input_contract_refs: tuple[str, ...] = ()
    output_contract_refs: tuple[str, ...] = ()
    evidence_contract_refs: tuple[str, ...] = ()
    consumer_version: str = "unresolved"
    compile_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED
    runtime_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED
    evidence_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED
    consumer_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED
    browser_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED
    provider_status: AcceptanceStatus = AcceptanceStatus.NOT_VERIFIED

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "provider_version",
            "path_id",
            "operation_version",
            "capability_ref",
            "consumer_id",
            "projection_ref",
            "reason",
            "consumer_version",
        ):
            _required_text(getattr(self, name), name)
        for name in (
            "input_contract_refs",
            "output_contract_refs",
            "evidence_contract_refs",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(value) is not str or not value for value in values
            ):
                raise ValueError(f"{name} must be a tuple of references")
        for name in (
            "status",
            "compile_status",
            "runtime_status",
            "evidence_status",
            "consumer_status",
            "browser_status",
            "provider_status",
        ):
            if type(getattr(self, name)) is not AcceptanceStatus:
                raise ValueError(f"{name} must be an AcceptanceStatus")

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
            "input_contract_refs": list(self.input_contract_refs),
            "output_contract_refs": list(self.output_contract_refs),
            "evidence_contract_refs": list(self.evidence_contract_refs),
            "consumer_version": self.consumer_version,
            "compile_status": self.compile_status.value,
            "runtime_status": self.runtime_status.value,
            "evidence_status": self.evidence_status.value,
            "consumer_status": self.consumer_status.value,
            "browser_status": self.browser_status.value,
            "provider_status": self.provider_status.value,
        }


@dataclass(frozen=True)
class AcceptanceMatrixV1:
    rows: tuple[AcceptanceRowV1, ...]
    matrix_digest: str

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple or any(
            type(row) is not AcceptanceRowV1 for row in self.rows
        ):
            raise ValueError("rows must contain AcceptanceRowV1")
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


def build_acceptance_matrix(
    path_rows: Sequence[Mapping[str, object]],
    coverage_rows: Sequence[Mapping[str, object]],
) -> AcceptanceMatrixV1:
    """Expand every declared consumer path and retain blocked rows."""

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
        input_refs = tuple(path.get("input_contract_refs") or ())
        output_refs = tuple(path.get("output_contract_refs") or ())
        evidence_refs = tuple(path.get("evidence_contract_refs") or ())
        for name, values in (
            ("input_contract_refs", input_refs),
            ("output_contract_refs", output_refs),
            ("evidence_contract_refs", evidence_refs),
        ):
            if any(type(value) is not str or not value for value in values):
                raise ValueError(f"{name} must contain text references")
        for consumer in consumers:
            if not isinstance(consumer, Mapping):
                raise ValueError("consumer declaration must be an object")
            consumer_id = _required_text(consumer.get("consumer_id"), "consumer_id")
            projection_ref = _required_text(consumer.get("projection_ref"), "projection_ref")
            coverage = coverage_index.get((provider_id, path_id, consumer_id))
            if coverage is None:
                status = AcceptanceStatus.BLOCKED
                reason = "projection_missing"
                consumer_version = "unresolved"
            elif coverage.get("status") == "covered":
                status = AcceptanceStatus.COVERED
                reason = _required_text(coverage.get("reason"), "coverage.reason")
                consumer_version = _required_text(
                    coverage.get("consumer_version", consumer.get("consumer_version", "resolved")),
                    "consumer_version",
                )
            else:
                status = AcceptanceStatus.BLOCKED
                reason = _required_text(coverage.get("reason"), "coverage.reason")
                consumer_version = _required_text(
                    coverage.get("consumer_version", consumer.get("consumer_version", "unresolved")),
                    "consumer_version",
                )
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
                    input_contract_refs=input_refs,
                    output_contract_refs=output_refs,
                    evidence_contract_refs=evidence_refs,
                    consumer_version=consumer_version,
                    consumer_status=(
                        AcceptanceStatus.PASS
                        if status is AcceptanceStatus.COVERED
                        else AcceptanceStatus.BLOCKED
                    ),
                )
            )
    immutable_rows = tuple(
        sorted(rows, key=lambda row: json.dumps(row.to_dict(), sort_keys=True))
    )
    return AcceptanceMatrixV1(
        rows=immutable_rows,
        matrix_digest=_digest([row.to_dict() for row in immutable_rows]),
    )


def live_acceptance_inventory() -> dict[str, object]:
    """Return the live catalog, coverage and derived acceptance denominator."""

    from workbench.evidence.coverage import build_consumer_coverage
    from workbench.providers.catalog import load_builtin_catalog

    catalog = load_builtin_catalog()
    coverage = build_consumer_coverage(catalog)
    path_rows: list[dict[str, object]] = []
    for provider in catalog.providers:
        for path in provider.exposure_paths:
            refs = [path.capability_ref]
            refs.extend(
                ref
                for ref in (
                    path.operation_ref,
                    path.step_contract_ref,
                    path.family_contract_ref,
                    path.execution_adapter_ref,
                )
                if ref is not None
            )
            path_rows.append(
                {
                    "provider_id": provider.provider_id,
                    "provider_version": provider.semantic_version,
                    "path_id": path.path_id,
                    "operation_version": path.semantic_version,
                    "capability_ref": _ref_identity(path.capability_ref),
                    "input_contract_refs": tuple(_ref_identity(ref) for ref in refs),
                    "output_contract_refs": tuple(
                        _ref_identity(ref) for ref in path.result_contract_refs
                    ),
                    "evidence_contract_refs": tuple(
                        _ref_identity(ref) for ref in path.evidence_contract_refs
                    ),
                    "consumers": [
                        {
                            "consumer_id": consumer_id,
                            "projection_ref": _ref_identity(projection_ref),
                        }
                        for consumer_id, projection_ref in sorted(path.projection_refs.items())
                    ],
                }
            )
    coverage_rows = [
        {
            "provider_id": row.raw_key.provider_id,
            "path_id": row.raw_key.exposure_path,
            "consumer_id": row.raw_key.consumer_id,
            "consumer_version": row.raw_key.consumer_version,
            "status": row.status,
            "reason": row.reason,
        }
        for row in coverage.rows
    ]
    return {
        "catalog": catalog,
        "coverage": coverage,
        "matrix": build_acceptance_matrix(path_rows, coverage_rows),
    }


def live_acceptance_matrix() -> AcceptanceMatrixV1:
    return live_acceptance_inventory()["matrix"]  # type: ignore[return-value]


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
    return (
        normalized == ".venv"
        or normalized.startswith(".venv/")
        or normalized == "frontend/node_modules"
        or normalized.startswith("frontend/node_modules/")
    )


def inspect_candidate(
    worktree: Path,
    candidate_sha: str,
    *,
    interpreter: str | Path | None = None,
) -> CandidateIdentityV1:
    """Prove exact HEAD, clean source state and trusted execution roots."""

    worktree = Path(worktree)
    if not _is_regular_directory(worktree):
        raise CandidateIdentityError("candidate worktree is unavailable or unsafe")
    if type(candidate_sha) is not str or SHA1_RE.fullmatch(candidate_sha) is None:
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
    try:
        inspect_candidate(worktree, candidate_sha, interpreter=interpreter)
    except CandidateIdentityError as error:
        return {"status": AcceptanceStatus.FAIL.value, "reason": str(error)}
    return {"status": AcceptanceStatus.PASS.value, "reason": "candidate remained unchanged"}


def provider_mode_status(
    *, provider_requested: bool, provider_configured: bool
) -> ProviderModeResult:
    if not provider_requested:
        return ProviderModeResult(
            AcceptanceStatus.NOT_VERIFIED,
            False,
            "provider mode was not requested",
        )
    if not provider_configured:
        return ProviderModeResult(
            AcceptanceStatus.NOT_VERIFIED,
            False,
            "provider is not explicitly configured",
        )
    return ProviderModeResult(
        AcceptanceStatus.NOT_VERIFIED,
        False,
        "provider execution requires an authorized provider adapter",
    )


def write_sidecar_once(path: Path, payload: Mapping[str, object]) -> None:
    """Write one canonical sidecar and never overwrite prior evidence."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
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
    "live_acceptance_inventory",
    "live_acceptance_matrix",
    "provider_mode_status",
    "write_sidecar_once",
]
