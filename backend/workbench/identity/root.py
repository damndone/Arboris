"""Validated filesystem bindings used by project identity revisions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ProjectRootError(ValueError):
    """Base error for a root that cannot be safely bound by the authority."""

    code = "PROJECT_ROOT_INVALID"


class InvalidProjectRootError(ProjectRootError):
    """The supplied value is not an existing absolute directory."""


class ProjectRootRelocatedError(ProjectRootError):
    """A path is occupied by a different filesystem root than its prior binding."""

    code = "PROJECT_ROOT_RELOCATED"


@dataclass(frozen=True)
class ValidatedProjectRoot:
    """Server-observed facts for one canonical directory."""

    path: Path
    canonical_path: str
    device: int
    inode: int
    binding_key: str

    def to_binding_dict(self) -> dict[str, object]:
        return {
            "binding_key": self.binding_key,
            "canonical_path": self.canonical_path,
            "device": self.device,
            "inode": self.inode,
        }


def validate_project_root(project_root: Path | str) -> ValidatedProjectRoot:
    """Resolve and validate a project root without trusting identity claims.

    The returned binding key is derived only from server-observed filesystem
    metadata.  The path is retained as binding evidence, never as a project id.
    """

    if not isinstance(project_root, (Path, str)):
        raise InvalidProjectRootError("project root must be an absolute path")
    try:
        supplied = Path(project_root).expanduser()
    except (TypeError, ValueError, RuntimeError) as exc:
        raise InvalidProjectRootError("project root is not a valid path") from exc
    if not supplied.is_absolute():
        raise InvalidProjectRootError("project root must be an absolute path")
    try:
        resolved = supplied.resolve(strict=True)
        stat = resolved.stat()
    except (FileNotFoundError, NotADirectoryError, OSError, RuntimeError) as exc:
        raise InvalidProjectRootError(
            f"project root does not resolve to an existing directory: {supplied}"
        ) from exc
    if not resolved.is_dir():
        raise InvalidProjectRootError(
            f"project root is not a directory: {resolved}"
        )
    device = int(stat.st_dev)
    inode = int(stat.st_ino)
    return ValidatedProjectRoot(
        path=resolved,
        canonical_path=os.fspath(resolved),
        device=device,
        inode=inode,
        binding_key=f"fs:{device}:{inode}",
    )


__all__ = [
    "InvalidProjectRootError",
    "ProjectRootError",
    "ProjectRootRelocatedError",
    "ValidatedProjectRoot",
    "validate_project_root",
]
