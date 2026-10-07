"""One directory-FD transaction lock for all writers of an owner index."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
from uuid import uuid4


@contextmanager
def locked_owner_index(owner_fd):
    # Opening '.' creates a distinct file description. dup() would share the
    # flock with another thread using the same persistence admission.
    lock_fd = os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=owner_fd)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock_fd)


@contextmanager
def artifact_index_transaction(run_root):
    """Mutate the legacy registry under the same FD lock as admitted writers."""
    root = Path(run_root)
    owner = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with locked_owner_index(owner):
            fd = os.open('artifacts_index.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=owner)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Artifact index must be a singly linked regular file')
                index = json.load(stream)
            before = json.dumps(index, sort_keys=True, ensure_ascii=False)
            yield index
            if json.dumps(index, sort_keys=True, ensure_ascii=False) == before:
                return
            fresh = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if (os.fstat(fresh).st_dev,os.fstat(fresh).st_ino) != (os.fstat(owner).st_dev,os.fstat(owner).st_ino):
                    raise ValueError('Artifact owner changed during index transaction')
            finally:
                os.close(fresh)
            temporary = '.artifacts-index-' + uuid4().hex + '.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=owner)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(index, stream, indent=2, ensure_ascii=False)
                stream.flush(); os.fsync(stream.fileno())
            os.rename(temporary,'artifacts_index.json',src_dir_fd=owner,dst_dir_fd=owner)
            os.fsync(owner)
    finally:
        os.close(owner)
