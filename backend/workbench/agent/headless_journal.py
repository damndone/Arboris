"""Admission-gated FD I/O for the three files of a headless journal."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
from typing import Iterator

from ..identity.root import ProjectRootAdmission, open_validated_project_root


class HeadlessJournalError(ValueError):
    """The admitted journal or one of its files cannot be used safely."""


_NAMES = frozenset({'runtime.json', 'model.jsonl', 'business.jsonl'})


def _identity(observed) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _snapshot(observed) -> tuple[int, int, int, int, int]:
    return (*_identity(observed), observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns)


class _RuntimeWriter:
    def __init__(self, journal: HeadlessJournal, fd: int):
        self._journal = journal
        self._fd = fd
        self._identity = _identity(os.fstat(fd))

    def save(self, value: bytes) -> None:
        if type(value) is not bytes:
            raise HeadlessJournalError('runtime journal content must be bytes')
        self._journal._check()
        self._journal._file(self._fd, 'runtime.json', expected=self._identity)
        os.lseek(self._fd, 0, os.SEEK_SET)
        remaining = memoryview(value)
        while remaining:
            written = os.write(self._fd, remaining)
            if written <= 0:
                raise HeadlessJournalError('runtime journal write did not complete')
            remaining = remaining[written:]
        os.ftruncate(self._fd, len(value))
        os.fsync(self._fd)
        self._journal._file(self._fd, 'runtime.json', expected=self._identity)
        os.fsync(self._journal._fd)


class HeadlessJournal:
    """An operation-scoped capability, obtained only by root FD admission."""

    def __init__(self, admission: ProjectRootAdmission):
        self._fd = admission.fd
        self._path = admission.validated.path
        self._binding = admission.validated.binding_key
        self._identity = _identity(os.fstat(self._fd))
        self._closed = False

    def _check(self) -> None:
        if self._closed or _identity(os.fstat(self._fd)) != self._identity:
            raise HeadlessJournalError('headless journal admission is closed or changed')
        # Reopening is a read-only relocation check. Every file read/write below
        # still uses the original admitted directory FD, never this path.
        with open_validated_project_root(self._path) as current:
            if current.validated.path != self._path or current.validated.binding_key != self._binding:
                raise HeadlessJournalError('headless journal directory binding changed')

    def _file(self, fd: int, name: str, *, expected=None):
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise HeadlessJournalError('headless journal file must be regular and single-link')
        linked = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
        if _identity(linked) != _identity(observed) or expected is not None and _identity(observed) != expected:
            raise HeadlessJournalError('headless journal file binding changed')
        return observed

    def _open(self, name: str, flags: int) -> int:
        if name not in _NAMES:
            raise HeadlessJournalError('unsupported headless journal file')
        self._check()
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self._fd)
        try:
            self._file(fd, name)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def create_runtime(self, value: bytes) -> Iterator[_RuntimeWriter]:
        fd = self._open('runtime.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        writer = _RuntimeWriter(self, fd)
        try:
            writer.save(value)
            yield writer
        finally:
            os.close(fd)

    def _read(self, name: str, *, digest: bool):
        fd = self._open(name, os.O_RDONLY)
        with os.fdopen(fd, 'rb') as handle:
            before = self._file(handle.fileno(), name)
            value = hashlib.file_digest(handle, 'sha256').hexdigest() if digest else handle.read()
            after = self._file(handle.fileno(), name, expected=_identity(before))
            if _snapshot(before) != _snapshot(after):
                raise HeadlessJournalError('headless journal file changed during read')
            self._check()
        return value

    def read_runtime(self) -> bytes:
        return self._read('runtime.json', digest=False)

    def sha256(self, name: str) -> str:
        if name not in {'model.jsonl', 'business.jsonl'}:
            raise HeadlessJournalError('only model and business journals have payload digests')
        return self._read(name, digest=True)


@contextmanager
def open_headless_journal(root: Path | str) -> Iterator[HeadlessJournal]:
    path = Path(root)
    if not path.is_absolute() or '..' in path.parts:
        raise HeadlessJournalError('headless journal requires an existing absolute directory')
    with open_validated_project_root(path) as admission:
        if admission.validated.path != path:
            raise HeadlessJournalError('headless journal directory must not contain symlinks')
        journal = HeadlessJournal(admission)
        try:
            yield journal
        finally:
            journal._closed = True
