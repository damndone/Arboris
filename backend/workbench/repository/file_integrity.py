"""Safe, shared reads of server-owned regular files under a run root."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat


_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_PATH_COMPONENTS = 64
_MAX_PATH_BYTES = 512
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_READ_CHUNK_BYTES = 1024 * 1024


def validate_run_relative_path(value: object) -> tuple[str, ...]:
    """Validate and split the server-owned relative path grammar."""

    if type(value) is not str or not value or value != value.strip() or "\\" in value:
        raise ValueError("artifact path is not a normalized relative POSIX path")
    try:
        encoded = value.encode("ascii", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError("artifact path is not an ASCII server-owned path") from exc
    if len(encoded) > _MAX_PATH_BYTES:
        raise ValueError("artifact path is too long")
    parts = tuple(value.split("/"))
    if len(parts) > _MAX_PATH_COMPONENTS or any(
        part in {"", ".", ".."} or _PATH_COMPONENT.fullmatch(part) is None
        for part in parts
    ):
        raise ValueError("artifact path is not normalized")
    return parts


@dataclass
class OpenedRunFile:
    """One regular file opened beneath a run-root descriptor."""

    fd: int
    relative_parts: tuple[str, ...]
    _closed: bool = False

    @property
    def relative_path(self) -> str:
        return "/".join(self.relative_parts)

    @property
    def name(self) -> str:
        return self.relative_parts[-1]

    def close(self) -> None:
        if not self._closed:
            os.close(self.fd)
            self._closed = True

    def __enter__(self) -> "OpenedRunFile":
        if self._closed:
            raise OSError("opened run file is already closed")
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    def _read_snapshot_from_fd(self) -> bytes:
        if self._closed:
            raise OSError("opened run file is closed")
        before = os.fstat(self.fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("opened run file is not regular")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(self.fd, min(_READ_CHUNK_BYTES, before.st_size - offset), offset)
            if not chunk:
                raise OSError("opened run file changed while it was read")
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(self.fd)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
        ):
            raise OSError("opened run file changed while it was read")
        return b"".join(chunks)

    def read_bytes_and_sha256(self) -> tuple[bytes, str]:
        data = self._read_snapshot_from_fd()
        return data, hashlib.sha256(data).hexdigest()

    def sha256(self) -> str:
        data = self._read_snapshot_from_fd()
        return hashlib.sha256(data).hexdigest()


def open_run_relative_file(run_root: Path, relative_path: object) -> OpenedRunFile:
    """Open one bounded run-relative regular file without pathname TOCTOU."""

    relative_parts = validate_run_relative_path(relative_path)
    if not _O_NOFOLLOW or not _O_DIRECTORY:
        raise OSError("safe no-follow directory traversal is unavailable")
    open_flags = os.O_RDONLY | _O_CLOEXEC | _O_NOFOLLOW
    directory_fds: list[int] = []
    artifact_fd = -1
    try:
        root_fd = os.open(os.fspath(run_root), open_flags | _O_DIRECTORY)
        directory_fds.append(root_fd)
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise OSError("run root is not a directory")
        parent_fd = root_fd
        for component in relative_parts[:-1]:
            child_fd = os.open(component, open_flags | _O_DIRECTORY, dir_fd=parent_fd)
            directory_fds.append(child_fd)
            if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                raise OSError("artifact path component is not a directory")
            parent_fd = child_fd
        artifact_fd = os.open(relative_parts[-1], open_flags, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(artifact_fd).st_mode):
            raise OSError("indexed artifact is not a regular file")
        opened = OpenedRunFile(fd=artifact_fd, relative_parts=relative_parts)
        artifact_fd = -1
        return opened
    finally:
        if artifact_fd >= 0:
            os.close(artifact_fd)
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)
