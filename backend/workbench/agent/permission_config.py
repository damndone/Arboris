"""Project permission rules shared by manual and Agent entry points."""

from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
from stat import S_ISREG
from typing import Any, Iterator
from uuid import uuid4

from ..api_errors import WorkbenchAPIError
from .permissions import Rules, rules_from_payload

_RULES_FILENAME = "agent-permissions.json"
MISSING_PERMISSIONS_REVISION = "missing"


def _parse_rules(document: str) -> Rules:
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate permission key")
            result[key] = value
        return result

    try:
        return rules_from_payload(json.loads(document, object_pairs_hook=unique_keys))
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=503, code="AGENT_PERMISSION_RULES_INVALID",
            message="The project permission rules are invalid; repair the permission file before continuing.",
        ) from exc


def _unreadable_rules() -> WorkbenchAPIError:
    return WorkbenchAPIError(
        status_code=503, code="AGENT_PERMISSION_RULES_INVALID",
        message="The project permission rules cannot be read; repair the permission file before continuing.",
    )


def project_permission_rules(root: Path) -> Rules:
    """Read complete project rules; an invalid store must not discard denies."""

    path = root / "workbench" / _RULES_FILENAME
    try:
        document = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if not path.is_symlink():
            return Rules()
        raise _unreadable_rules() from exc
    except (OSError, UnicodeError) as exc:
        raise _unreadable_rules() from exc
    return _parse_rules(document)


def permission_rules_document(rules: Rules) -> dict[str, list[dict[str, str]]]:
    return {
        outcome: [
            {"class": rule.permission_class.value, **(
                {"operation_id": rule.operation_id} if rule.operation_id is not None else {}
            )}
            for rule in entries
        ]
        for outcome, entries in (("allow", rules.allow), ("ask", rules.ask), ("deny", rules.deny))
    }


@contextmanager
def _permission_directory(root: Path, *, create: bool = False) -> Iterator[int | None]:
    directory = root / "workbench"
    try:
        if create:
            directory.mkdir(exist_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        if create:
            raise _unreadable_rules() from exc
        yield None
        return
    except OSError as exc:
        raise _unreadable_rules() from exc
    try:
        yield directory_fd
    finally:
        os.close(directory_fd)


def _permission_snapshot(directory_fd: int) -> tuple[Rules, str]:
    try:
        file_fd = os.open(_RULES_FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return Rules(), MISSING_PERMISSIONS_REVISION
    except OSError as exc:
        raise _unreadable_rules() from exc
    try:
        with os.fdopen(file_fd, "rb") as handle:
            if not S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise _unreadable_rules()
            raw = handle.read()
        return _parse_rules(raw.decode("utf-8")), sha256(raw).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise _unreadable_rules() from exc


def read_project_permission_settings(root: Path) -> tuple[Rules, str]:
    """Read the settings and a revision bound to the complete file bytes."""

    with _permission_directory(root) as directory_fd:
        if directory_fd is None:
            return Rules(), MISSING_PERMISSIONS_REVISION
        return _permission_snapshot(directory_fd)


def _replace_permission_document(directory_fd: int, raw: bytes) -> None:
    temporary = f".{_RULES_FILENAME}.{uuid4().hex}.tmp"
    file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(file_fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _RULES_FILENAME, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    except OSError:
        os.unlink(temporary, dir_fd=directory_fd)
        raise
    os.fsync(directory_fd)


def save_project_permission_settings(
    root: Path, *, expected_revision: str, payload: object
) -> tuple[Rules, str]:
    """Validate and replace a project policy only if the user's revision is current."""

    rules = rules_from_payload(payload)
    raw = (json.dumps(permission_rules_document(rules), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        with _permission_directory(root, create=True) as directory_fd:
            assert directory_fd is not None
            # Each writer holds its own descriptor to the same project directory.
            # The lock is released when the directory context closes.
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            _, current_revision = _permission_snapshot(directory_fd)
            if current_revision != expected_revision:
                raise WorkbenchAPIError(
                    status_code=409, code="AGENT_PERMISSION_RULES_CONFLICT",
                    message="The project rules changed. Reload rules before saving.",
                )
            _replace_permission_document(directory_fd, raw)
    except OSError as exc:
        raise WorkbenchAPIError(
            status_code=500, code="AGENT_PERMISSION_RULES_UNWRITABLE",
            message="The project permission rules could not be saved.",
        ) from exc
    return rules, sha256(raw).hexdigest()

