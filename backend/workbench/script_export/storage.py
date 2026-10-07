"""FD-bound publication of immutable script artifacts within an admitted owner."""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
import stat
from uuid import uuid4

from .. import __version__
from ..domain import ArtifactRecord
from ..artifact_index import locked_owner_index
from ..identity.root import open_validated_project_root
from .plan import ScriptExportRefusal


def _directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _read(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ScriptExportRefusal('INVALID_EXPORT_PATH', 'Artifact is not a singly linked regular file')
        return stream.read()


def _same(parent, name, bound):
    fresh = _directory(parent, name)
    try:
        left, right = os.fstat(fresh), os.fstat(bound)
        if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
            raise ScriptExportRefusal('INVALID_EXPORT_PATH', 'Owner directory changed during publication')
    finally:
        os.close(fresh)


def publish_script_bundle(project, run_id, artifact_id, raw, digest):
    """Hold the project admission and owner lock through file/index publication."""
    try:
        with open_validated_project_root(project) as admission, ExitStack() as stack:
            def directory(parent, name, **kwargs):
                fd = _directory(parent, name, **kwargs)
                stack.callback(os.close, fd)
                return fd
            runs = directory(admission.fd, 'runs')
            owner = directory(runs, run_id)
            stack.enter_context(locked_owner_index(owner))
            index = json.loads(_read(owner, 'artifacts_index.json'))
            folder = directory(owner, 'exports', create=True)
            scripts = directory(folder, 'scripts', create=True)
            filename = artifact_id + '.zip'
            relative = 'exports/scripts/' + filename
            matches = [item for item in index['artifacts'] if item.get('artifact_id') == artifact_id]
            if matches:
                if (len(matches) != 1 or matches[0].get('path') != relative
                        or matches[0].get('sha256') != digest or _read(scripts, filename) != raw):
                    raise ScriptExportRefusal('EXPORT_ARTIFACT_CHANGED', 'Existing artifact owner or bytes changed')
            else:
                fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=scripts)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.fsync(scripts)
                _same(admission.fd, 'runs', runs); _same(runs, run_id, owner)
                _same(owner, 'exports', folder); _same(folder, 'scripts', scripts)
                record = ArtifactRecord(artifact_id, relative, 'script_export', 'export.analysis_script', digest,
                                        inputs=(), code_version=__version__).to_dict()
                index['artifacts'].append(record)
                temporary = '.script-export-index-' + uuid4().hex + '.tmp'
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=owner)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(json.dumps(index, indent=2, ensure_ascii=False).encode())
                    stream.flush(); os.fsync(stream.fileno())
                os.rename(temporary, 'artifacts_index.json', src_dir_fd=owner, dst_dir_fd=owner)
                os.fsync(owner)
            _same(admission.fd, 'runs', runs); _same(runs, run_id, owner)
            _same(owner, 'exports', folder); _same(folder, 'scripts', scripts)
    except ScriptExportRefusal:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ScriptExportRefusal('INVALID_EXPORT_PATH', 'Owner-bound script publication failed') from exc
