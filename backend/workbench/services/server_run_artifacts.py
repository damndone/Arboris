"""Verified reads of server-owned run artifacts for consumer services.

The Agent layer may request a bounded artifact projection, but it must not
read compiler-owned run sources directly.  Keeping manifest parsing and file
fingerprint checks here gives every server-owned consumer one fail-closed
filesystem boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..api_errors import WorkbenchAPIError
from ..artifacts import register_artifact, sha256_file
from ..repository.run_repository import _read_artifact_records


class ServerOwnedArtifactManifestError(ValueError):
    """A server-owned artifact manifest cannot be trusted for completion."""

    def __init__(self, message: str, *, run_id: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.details = dict(details)
        if run_id is not None:
            self.details["run_id"] = run_id


def read_server_owned_run_artifacts(
    project_root: Path,
    run_id: str | None,
    *,
    required: bool = False,
) -> list[dict[str, Any]]:
    """Read run records, verifying every referenced file when required.

    Non-required reads preserve the ambient-artifact behavior used by legacy
    Notebook paths: unavailable or malformed indexes produce no ambient
    records.  Server-owned completion passes ``required=True`` and therefore
    refuses missing indexes, malformed records, path escapes, missing files,
    and changed fingerprints.
    """

    if not run_id:
        if required:
            raise ServerOwnedArtifactManifestError(
                "server-owned completion requires a run artifact manifest"
            )
        return []

    run_root = project_root / "runs" / run_id
    try:
        records = _read_artifact_records(run_root)
    except (
        AttributeError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        WorkbenchAPIError,
    ) as exc:
        if required:
            raise ServerOwnedArtifactManifestError(
                "server-owned completion run artifact manifest is unreadable",
                run_id=run_id,
            ) from exc
        return []

    if not required:
        return [dict(item) for item in records if isinstance(item, Mapping)]

    if not (run_root / "artifacts_index.json").is_file():
        raise ServerOwnedArtifactManifestError(
            "server-owned completion run has no artifact manifest",
            run_id=run_id,
        )

    resolved_run_root = run_root.resolve()
    verified: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            raise ServerOwnedArtifactManifestError(
                "server-owned completion artifact manifest contains a non-object record",
                run_id=run_id,
            )
        relative = item.get("path")
        if not isinstance(relative, str) or not relative:
            raise ServerOwnedArtifactManifestError(
                "server-owned completion artifact has no path",
                run_id=run_id,
            )
        path = (resolved_run_root / relative).resolve()
        try:
            path.relative_to(resolved_run_root)
        except ValueError as exc:
            raise ServerOwnedArtifactManifestError(
                "server-owned completion artifact escapes the run root",
                run_id=run_id,
                artifact_id=item.get("artifact_id"),
            ) from exc
        if not path.is_file():
            raise ServerOwnedArtifactManifestError(
                "server-owned completion artifact file is missing",
                run_id=run_id,
                artifact_id=item.get("artifact_id"),
            )
        expected_sha = item.get("sha256")
        if not isinstance(expected_sha, str) or expected_sha != sha256_file(path):
            raise ServerOwnedArtifactManifestError(
                "server-owned completion artifact fingerprint changed",
                run_id=run_id,
                artifact_id=item.get("artifact_id"),
            )
        verified.append(dict(item))
    return verified


def register_server_owned_run_artifact(
    project_root: Path,
    run_id: str,
    *,
    artifact_id: str,
    artifact_path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> dict[str, Any]:
    """Register one server-produced artifact without exposing the run index to Agent code."""

    run_root = project_root / "runs" / run_id
    resolved_run_root = run_root.resolve()
    resolved_artifact = artifact_path.resolve()
    try:
        relative_path = resolved_artifact.relative_to(resolved_run_root).as_posix()
    except ValueError as exc:
        raise ServerOwnedArtifactManifestError(
            "server-owned artifact escapes the run root",
            run_id=run_id,
            artifact_id=artifact_id,
        ) from exc
    if not resolved_artifact.is_file():
        raise ServerOwnedArtifactManifestError(
            "server-owned artifact file is missing",
            run_id=run_id,
            artifact_id=artifact_id,
        )

    records = read_server_owned_run_artifacts(project_root, run_id, required=True)
    existing = [item for item in records if item.get("artifact_id") == artifact_id]
    if len(existing) > 1:
        raise ServerOwnedArtifactManifestError(
            "server-owned artifact identity is duplicated",
            run_id=run_id,
            artifact_id=artifact_id,
        )
    expected = {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "path": relative_path,
        "step": step,
        "sha256": sha256_file(resolved_artifact),
        "inputs": list(inputs),
    }
    if existing:
        record = existing[0]
        if any(record.get(key) != value for key, value in expected.items()):
            raise ServerOwnedArtifactManifestError(
                "server-owned artifact identity is inconsistent",
                run_id=run_id,
                artifact_id=artifact_id,
            )
        return record
    return register_artifact(
        run_root,
        artifact_id,
        resolved_artifact,
        artifact_type,
        step,
        inputs,
    ).to_dict()


__all__ = [
    "ServerOwnedArtifactManifestError",
    "read_server_owned_run_artifacts",
    "register_server_owned_run_artifact",
]
