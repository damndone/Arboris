"""Read-only verification of the reviewed WO-D evaluator harness inventory.

The manifest references exact committed Git objects in the separate lane.  It
does not copy, import, execute, or inspect the lane's dirty working files.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ROLE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_GIT = Path("/usr/bin/git")


class HarnessManifestError(ValueError):
    pass


@dataclass(frozen=True)
class HarnessFileV1:
    path: str
    sha256: str
    owner: str
    role: str


@dataclass(frozen=True)
class HarnessTestCommandV1:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class EvaluatorHarnessManifestV1:
    schema_version: str
    lane_commit_sha: str
    lane_tree_sha: str
    integration_base_sha: str
    assembled_integration_sha: str | None
    migration_allowed: bool
    files: tuple[HarnessFileV1, ...]
    test_commands: tuple[HarnessTestCommandV1, ...]


@dataclass(frozen=True)
class VerifiedHarnessInventoryV1:
    lane_commit_sha: str
    lane_tree_sha: str
    integration_base_sha: str
    assembled_integration_sha: str | None
    file_count: int
    migration_allowed: bool


def load_harness_manifest(path: Path) -> EvaluatorHarnessManifestV1:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, HarnessManifestError) as error:
        raise HarnessManifestError("harness manifest is invalid JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "lane_commit_sha", "lane_tree_sha", "integration_base_sha", "assembled_integration_sha", "migration_allowed", "files", "test_commands"
    }:
        raise HarnessManifestError("harness manifest schema is invalid")
    files = tuple(_parse_file(value) for value in _require_list(raw["files"], "files"))
    commands = tuple(_parse_command(value) for value in _require_list(raw["test_commands"], "test commands"))
    manifest = EvaluatorHarnessManifestV1(
        schema_version=raw["schema_version"],
        lane_commit_sha=raw["lane_commit_sha"],
        lane_tree_sha=raw["lane_tree_sha"],
        integration_base_sha=raw["integration_base_sha"],
        assembled_integration_sha=raw["assembled_integration_sha"],
        migration_allowed=raw["migration_allowed"],
        files=files,
        test_commands=commands,
    )
    _validate_manifest(manifest)
    return manifest


def verify_harness_manifest(
    manifest: EvaluatorHarnessManifestV1,
    *,
    lane_repository: Path,
    integration_base_sha: str,
) -> VerifiedHarnessInventoryV1:
    """Verify Git object bytes, explicitly ignoring the lane worktree state."""

    _validate_manifest(manifest)
    if integration_base_sha != manifest.integration_base_sha:
        raise HarnessManifestError("Integration base SHA does not match the reviewed inventory")
    tree_sha = _git(lane_repository, "rev-parse", f"{manifest.lane_commit_sha}^{{tree}}")
    if tree_sha != manifest.lane_tree_sha:
        raise HarnessManifestError("lane tree SHA does not match the reviewed inventory")
    tree_files = tuple(
        line
        for line in _git(lane_repository, "ls-tree", "-r", "--name-only", manifest.lane_commit_sha, "--", "scripts/collect_v173_lmm_evidence.py", "tests/evaluation/linear_mixed_effects").splitlines()
        if line
    )
    manifest_paths = tuple(entry.path for entry in manifest.files)
    if tree_files != manifest_paths:
        raise HarnessManifestError("lane file inventory does not match the reviewed manifest")
    for entry in manifest.files:
        contents = _git_bytes(lane_repository, "show", f"{manifest.lane_commit_sha}:{entry.path}")
        if hashlib.sha256(contents).hexdigest() != entry.sha256:
            raise HarnessManifestError(f"lane file sha256 mismatch: {entry.path}")
    return VerifiedHarnessInventoryV1(
        lane_commit_sha=manifest.lane_commit_sha,
        lane_tree_sha=manifest.lane_tree_sha,
        integration_base_sha=manifest.integration_base_sha,
        assembled_integration_sha=manifest.assembled_integration_sha,
        file_count=len(manifest.files),
        migration_allowed=manifest.migration_allowed,
    )


def _validate_manifest(manifest: EvaluatorHarnessManifestV1) -> None:
    if manifest.schema_version != "1":
        raise HarnessManifestError("unsupported harness manifest schema")
    for label, value in (("lane commit", manifest.lane_commit_sha), ("lane tree", manifest.lane_tree_sha), ("Integration base", manifest.integration_base_sha)):
        if not isinstance(value, str) or not _COMMIT.fullmatch(value):
            raise HarnessManifestError(f"{label} SHA must be exact lowercase Git SHA")
    if manifest.assembled_integration_sha is not None:
        if not isinstance(manifest.assembled_integration_sha, str) or not _COMMIT.fullmatch(manifest.assembled_integration_sha):
            raise HarnessManifestError("assembled Integration SHA must be null or exact lowercase Git SHA")
    if manifest.migration_allowed is not False or manifest.assembled_integration_sha is not None:
        raise HarnessManifestError("inventory-only manifest must not authorize migration")
    if not manifest.files or len({entry.path for entry in manifest.files}) != len(manifest.files):
        raise HarnessManifestError("harness file inventory is missing or duplicated")
    if not manifest.test_commands or len({command.name for command in manifest.test_commands}) != len(manifest.test_commands):
        raise HarnessManifestError("harness test commands are missing or duplicated")


def _parse_file(value: Any) -> HarnessFileV1:
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "owner", "role"}:
        raise HarnessManifestError("harness file entry schema is invalid")
    entry = HarnessFileV1(**value)
    if not _safe_relative_path(entry.path) or not _SHA256.fullmatch(entry.sha256) or entry.owner != "WO-D evaluation" or not _ROLE.fullmatch(entry.role):
        raise HarnessManifestError("harness file entry is invalid")
    return entry


def _parse_command(value: Any) -> HarnessTestCommandV1:
    if not isinstance(value, dict) or set(value) != {"name", "argv"} or not isinstance(value["name"], str) or not value["name"]:
        raise HarnessManifestError("harness test command schema is invalid")
    argv = value["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part for part in argv):
        raise HarnessManifestError("harness test command argv is invalid")
    return HarnessTestCommandV1(value["name"], tuple(argv))


def _safe_relative_path(value: str) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and str(path) == value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise HarnessManifestError(f"harness {label} must be a list")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessManifestError("duplicate harness manifest JSON key")
        result[key] = value
    return result


def _git(repository: Path, *args: str) -> str:
    return _git_bytes(repository, *args).decode("utf-8").strip()


def _git_bytes(repository: Path, *args: str) -> bytes:
    if not _GIT.is_file():
        raise HarnessManifestError("fixed Git executable is unavailable")
    try:
        completed = subprocess.run(
            [str(_GIT), "-C", str(repository), *args],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"LC_ALL": "C", "LANG": "C"},
            timeout=10,
        )
    except OSError as error:
        raise HarnessManifestError("could not inspect exact lane Git object") from error
    if completed.returncode != 0:
        raise HarnessManifestError("could not inspect exact lane Git object")
    return completed.stdout


__all__ = [
    "EvaluatorHarnessManifestV1",
    "HarnessFileV1",
    "HarnessManifestError",
    "HarnessTestCommandV1",
    "VerifiedHarnessInventoryV1",
    "load_harness_manifest",
    "verify_harness_manifest",
]
