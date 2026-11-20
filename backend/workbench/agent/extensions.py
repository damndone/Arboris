"""Explicit human admission for bounded HTTPS queries and declarative hooks.

No project module, shell command or skill script is imported or executed.
Admission pins the entire manifest; changing it requires another human PUT.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError

from ..canonical import sha256_canonical
from ..identity.root import open_validated_project_root

MAX_BYTES = 64_000
EVENTS = ("before_operation", "after_operation", "turn_end", "plan_approved")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")


class ExtensionError(ValueError):
    pass


def _ref_free(value):
    if isinstance(value, dict):
        if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
            raise ExtensionError("EXTENSION_SCHEMA: references are not admitted")
        for item in value.values():
            _ref_free(item)
    elif isinstance(value, list):
        for item in value:
            _ref_free(item)


def validate_manifest(doc):
    try:
        raw = json.dumps(doc, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ExtensionError("EXTENSION_MANIFEST: finite JSON required") from exc
    if len(raw) > MAX_BYTES or type(doc) is not dict or set(doc) != {"schema", "tools", "hooks"} or doc["schema"] != "arboris.extensions.v1":
        raise ExtensionError("EXTENSION_MANIFEST: invalid bounded manifest")
    names = set()
    for kind in ("tools", "hooks"):
        if type(doc[kind]) is not list or len(doc[kind]) > 32:
            raise ExtensionError("EXTENSION_MANIFEST: at most 32 entries per slot")
        for entry in doc[kind]:
            fields = {"id", "version", "origin"} | ({"endpoint", "input_schema", "output_schema"} if kind == "tools" else {"event", "operation_ids", "action", "reason"})
            if type(entry) is not dict or set(entry) != fields:
                raise ExtensionError("EXTENSION_MANIFEST: unexpected entry fields")
            name = entry["id"]
            if type(name) is not str or not _SLUG.fullmatch(name) or name in names:
                raise ExtensionError("EXTENSION_ID: unique slug required")
            names.add(name)
            if any(type(entry[k]) is not str or not entry[k].strip() or len(entry[k]) > 240 for k in ("version", "origin")):
                raise ExtensionError("EXTENSION_PROVENANCE: bounded version and origin required")
            if kind == "tools":
                endpoint = entry["endpoint"]
                if type(endpoint) is not str or len(endpoint) > 2048:
                    raise ExtensionError("EXTENSION_ENDPOINT: invalid URL")
                url = urlsplit(endpoint)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ExtensionError("EXTENSION_ENDPOINT: fixed HTTPS URL without credentials, query or fragment required")
                for key in ("input_schema", "output_schema"):
                    _ref_free(entry[key])
                    try:
                        Draft202012Validator.check_schema(entry[key])
                    except SchemaError as exc:
                        raise ExtensionError("EXTENSION_SCHEMA: invalid schema") from exc
                    if type(entry[key]) is not dict or entry[key].get("type") != "object":
                        raise ExtensionError("EXTENSION_SCHEMA: object schema required")
            else:
                if entry["event"] not in EVENTS or entry["action"] not in {"record", "deny"} or (entry["action"] == "deny" and entry["event"] != "before_operation"):
                    raise ExtensionError("EXTENSION_HOOK: only before-operation hooks may deny; no grant or command actions")
                if type(entry["reason"]) is not str or len(entry["reason"]) > 240:
                    raise ExtensionError("EXTENSION_HOOK: bounded reason required")
                ops = entry["operation_ids"]
                if type(ops) is not list or len(ops) > 64 or any(type(op) is not str or len(op) > 160 for op in ops):
                    raise ExtensionError("EXTENSION_HOOK: invalid operation filter")
    return doc


@contextmanager
def _area(root, *, create=False):
    with open_validated_project_root(root) as admitted:
        if create:
            try:
                os.mkdir("workbench", mode=0o700, dir_fd=admitted.fd)
            except FileExistsError:
                pass
        try:
            fd = os.open("workbench", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=admitted.fd)
        except FileNotFoundError:
            yield None
            return
        try:
            yield fd
        finally:
            os.close(fd)


def _read(fd):
    if fd is None:
        return {"manifest": {"schema": "arboris.extensions.v1", "tools": [], "hooks": []}, "sha256": None, "disabled": []}
    try:
        source = os.open("extensions.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return _read(None)
    try:
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES + 4096:
            raise ExtensionError("EXTENSION_STORE: unsafe catalog")
        raw = os.read(source, MAX_BYTES + 4097)
        value = json.loads(raw)
        if set(value) != {"manifest", "sha256", "disabled"} or value["sha256"] != sha256_canonical(validate_manifest(value["manifest"])):
            raise ExtensionError("EXTENSION_STORE: changed catalog")
        names = {item["id"] for slot in ("tools", "hooks") for item in value["manifest"][slot]}
        if type(value["disabled"]) is not list or any(item not in names for item in value["disabled"]):
            raise ExtensionError("EXTENSION_STORE: invalid disabled entries")
        return value
    except (ValueError, TypeError, KeyError) as exc:
        raise ExtensionError("EXTENSION_STORE: invalid catalog") from exc
    finally:
        os.close(source)


class ExtensionStore:
    def __init__(self, root):
        self.root = Path(root)

    def view(self):
        with _area(self.root) as fd:
            return _read(fd)

    def _update(self, transform):
        with _area(self.root, create=True) as fd:
            lock = os.open(".extensions.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                value = transform(_read(fd))
                temp = f".extensions-{uuid4().hex}.tmp"
                out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(out, "wb") as stream:
                        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode())
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, "extensions.json", src_dir_fd=fd, dst_dir_fd=fd)
                    os.fsync(fd)
                finally:
                    try:
                        os.unlink(temp, dir_fd=fd)
                    except FileNotFoundError:
                        pass
                return value
            finally:
                os.close(lock)

    def admit(self, manifest, *, expected_sha256, previous_sha256):
        validate_manifest(manifest)
        version = sha256_canonical(manifest)
        if version != expected_sha256:
            raise ExtensionError("EXTENSION_VERSION: review the exact manifest before admission")
        def change(current):
            if current["sha256"] != previous_sha256:
                raise ExtensionError("EXTENSION_VERSION: catalog changed during review")
            return {"manifest": manifest, "sha256": version, "disabled": []}
        return self._update(change)

    def disable(self, name, disabled, *, expected_sha256):
        def change(current):
            if current["sha256"] != expected_sha256:
                raise ExtensionError("EXTENSION_VERSION: catalog changed during review")
            names = {item["id"] for slot in ("tools", "hooks") for item in current["manifest"][slot]}
            if name not in names:
                raise ExtensionError("EXTENSION_ID: unknown entry")
            active = set(current["disabled"])
            active.add(name) if disabled else active.discard(name)
            return {**current, "disabled": sorted(active)}
        return self._update(change)

    def require_tool(self, name, version):
        value = self.view()
        if value["sha256"] != version:
            raise ExtensionError("EXTENSION_VERSION: catalog is not the reviewed version")
        if name in value["disabled"]:
            raise ExtensionError("EXTENSION_DISABLED: entry is disabled")
        for item in value["manifest"]["tools"]:
            if item["id"] == name:
                return item
        raise ExtensionError("EXTENSION_ID: no admitted tool")
