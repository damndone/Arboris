"""Validated, server-observed filesystem bindings for project identities."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised through the capability test
    fcntl = None  # type: ignore[assignment]


_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_F_GETPATH = getattr(fcntl, "F_GETPATH", 50) if fcntl is not None else None


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
    """Facts observed from the directory FD for one canonical directory."""

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


@dataclass
class ProjectRootAdmission:
    """A validated root held open for the duration of one authority operation."""

    fd: int
    validated: ValidatedProjectRoot

    def __enter__(self) -> "ProjectRootAdmission":
        return self

    def __exit__(self, *_: object) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def _component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\x00" in value:
        raise InvalidProjectRootError("project root contains an unsafe path component")
    return value


def _require_root_fd_primitives() -> None:
    if fcntl is None or not hasattr(fcntl, "fcntl") or _F_GETPATH is None:
        raise InvalidProjectRootError(
            "safe project-root FD binding is unsupported on this host"
        )
    if not _O_DIRECTORY or not _O_NOFOLLOW or os.open not in os.supports_dir_fd:
        raise InvalidProjectRootError("safe project-root FD binding is unsupported")


def _path_value(project_root: Path | str) -> Path:
    if not isinstance(project_root, (Path, str)):
        raise InvalidProjectRootError("project root must be an absolute path")
    try:
        supplied = Path(project_root).expanduser()
    except (TypeError, ValueError, RuntimeError) as exc:
        raise InvalidProjectRootError("project root is not a valid path") from exc
    if not supplied.is_absolute():
        raise InvalidProjectRootError("project root must be an absolute path")
    return supplied


def _open_canonical_directory(path: Path) -> int:
    _require_root_fd_primitives()
    current: int | None = None
    try:
        current = os.open(os.path.sep, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
        for part in path.parts:
            if part in {"", os.path.sep}:
                continue
            try:
                next_fd = os.open(
                    _component(part),
                    os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                    dir_fd=current,
                )
            except (OSError, ValueError) as exc:
                raise InvalidProjectRootError(
                    "project root does not resolve to an existing directory"
                ) from exc
            os.close(current)
            current = next_fd
        if current is None or not stat.S_ISDIR(os.fstat(current).st_mode):
            raise InvalidProjectRootError("project root is not a directory")
        result = current
        current = None
        return result
    finally:
        if current is not None:
            try:
                os.close(current)
            except OSError:
                pass


def _observed_path(fd: int, canonical_hint: Path) -> str:
    _require_root_fd_primitives()
    try:
        raw = fcntl.fcntl(fd, _F_GETPATH, b"\0" * 1024)
        observed = raw.split(b"\0", 1)[0].decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        try:
            observed = os.readlink(f"/proc/self/fd/{fd}")
        except (OSError, ValueError) as exc:
            raise InvalidProjectRootError(
                "cannot observe the canonical project-root path from its FD"
            ) from exc
    if not observed.startswith("/") or os.path.normpath(observed) != observed:
        raise InvalidProjectRootError("project-root FD returned an unsafe canonical path")
    if observed.endswith(" (deleted)"):
        raise InvalidProjectRootError("project-root directory was replaced during binding")
    # The canonical hint is only a race detector.  The returned path itself is
    # obtained from the held FD and never from client identity fields.
    if observed != os.fspath(canonical_hint):
        raise InvalidProjectRootError("project-root canonical path changed during binding")
    return observed


def _verify_current_path_binding(
    supplied: Path, canonical_hint: Path, bound_fd: int
) -> None:
    """Reject a path replacement that happened after the bound FD was opened."""

    try:
        current_hint = supplied.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError, OSError, RuntimeError) as exc:
        raise InvalidProjectRootError("project root changed during FD admission") from exc
    if current_hint != canonical_hint:
        raise InvalidProjectRootError("project root alias changed during FD admission")
    current_fd = _open_canonical_directory(current_hint)
    try:
        bound_stat = os.fstat(bound_fd)
        current_stat = os.fstat(current_fd)
        if (bound_stat.st_dev, bound_stat.st_ino) != (
            current_stat.st_dev,
            current_stat.st_ino,
        ):
            raise InvalidProjectRootError("project root was replaced during FD admission")
    finally:
        try:
            os.close(current_fd)
        except OSError:
            pass


@contextmanager
def open_validated_project_root(project_root: Path | str) -> Iterator[ProjectRootAdmission]:
    """Open and hold a server-observed canonical root directory.

    Path resolution is only used to select the canonical traversal.  Every
    component is then reopened with ``O_NOFOLLOW`` and the returned identity
    facts come from ``fstat`` on the held directory FD.
    """

    supplied = _path_value(project_root)
    try:
        canonical_hint = supplied.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError, OSError, RuntimeError) as exc:
        raise InvalidProjectRootError(
            f"project root does not resolve to an existing directory: {supplied}"
        ) from exc
    if not canonical_hint.is_dir():
        raise InvalidProjectRootError(f"project root is not a directory: {canonical_hint}")
    fd = _open_canonical_directory(canonical_hint)
    try:
        try:
            observed_path = _observed_path(fd, canonical_hint)
            _verify_current_path_binding(supplied, canonical_hint, fd)
            observed_stat = os.fstat(fd)
            if not stat.S_ISDIR(observed_stat.st_mode):
                raise InvalidProjectRootError("project root is not a directory")
            device = int(observed_stat.st_dev)
            inode = int(observed_stat.st_ino)
            validated = ValidatedProjectRoot(
                path=Path(observed_path),
                canonical_path=observed_path,
                device=device,
                inode=inode,
                binding_key=f"fs:{device}:{inode}",
            )
        except OSError as exc:
            raise InvalidProjectRootError("project root could not be observed safely") from exc
        yield ProjectRootAdmission(fd=fd, validated=validated)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def validate_project_root(project_root: Path | str) -> ValidatedProjectRoot:
    """Return binding facts observed from a short-lived validated root FD."""

    with open_validated_project_root(project_root) as admission:
        return admission.validated


__all__ = [
    "InvalidProjectRootError",
    "ProjectRootAdmission",
    "ProjectRootError",
    "ProjectRootRelocatedError",
    "ValidatedProjectRoot",
    "open_validated_project_root",
    "validate_project_root",
]
