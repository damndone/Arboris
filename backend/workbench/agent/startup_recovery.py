"""Discover known projects and interrupt local orphans; never run a provider."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import stat
from uuid import uuid4

from ..identity.root import ProjectRootRelocatedError, open_validated_project_root
from .turn_store import TurnExecutionBusyError, TurnStore

logger = logging.getLogger(__name__)


class RecoveryProjectCatalog:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or os.environ.get("WORKBENCH_AGENT_RECOVERY_DIR")
                              or Path.home() / ".config/econometrics-workbench/agent-recovery")

    def remember(self, project_root: Path):
        with open_validated_project_root(project_root) as project:
            binding = project.validated.to_binding_dict()
        name = hashlib.sha256(binding["canonical_path"].encode()).hexdigest() + ".json"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open_validated_project_root(self.directory) as catalog:
            temporary = "." + uuid4().hex + ".tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=catalog.fd)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(binding, handle, ensure_ascii=False, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, name, src_dir_fd=catalog.fd, dst_dir_fd=catalog.fd)
                os.fsync(catalog.fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=catalog.fd)
                except FileNotFoundError:
                    pass

    def projects(self):
        if not self.directory.exists():
            return []
        bindings = []
        with open_validated_project_root(self.directory) as catalog:
            for name in sorted(os.listdir(catalog.fd)):
                if not name.endswith(".json"):
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=catalog.fd)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16_384:
                        raise ValueError("recovery project entry must be a bounded regular file")
                    binding = json.loads(os.read(fd, 16_385))
                finally:
                    os.close(fd)
                if (not isinstance(binding, dict)
                        or set(binding) != {"canonical_path", "device", "inode", "binding_key"}
                        or not isinstance(binding["canonical_path"], str)
                        or not Path(binding["canonical_path"]).is_absolute()
                        or any(type(binding[key]) is not int for key in ("device", "inode"))
                        or not isinstance(binding["binding_key"], str)):
                    raise ValueError("recovery project entry has an invalid binding")
                if hashlib.sha256(binding["canonical_path"].encode()).hexdigest() + ".json" != name:
                    raise ValueError("recovery project filename does not match its binding")
                bindings.append(binding)
        return bindings

    def reconcile(self):
        outcomes = []
        try:
            projects = self.projects()
        except (OSError, ValueError) as error:
            logger.warning("Agent startup catalog unavailable: %s", str(error)[:300])
            return [{"status": "catalog_unavailable", "error": str(error)[:300]}]
        for binding in projects:
            root = Path(binding["canonical_path"])
            try:
                with open_validated_project_root(root) as project:
                    if project.validated.to_binding_dict() != binding:
                        raise ProjectRootRelocatedError("registered project root was replaced")
                if not (root / "workbench/agent-turns").is_dir():
                    continue
                store = TurnStore(root, project_identity=(binding["device"], binding["inode"]))
                for original in store.list_active():
                    if original.status != "running":
                        continue
                    try:
                        with store.execution_guard(original.session_id) as guard:
                            current = store.get(original.turn_id)
                            if current.status != "running":
                                continue
                            store.interrupt_orphaned(current.turn_id, expected_version=current.version, guard=guard)
                            outcomes.append({"status": "interrupted", "turn_id": current.turn_id})
                    except TurnExecutionBusyError:
                        outcomes.append({"status": "busy", "turn_id": original.turn_id})
            except ProjectRootRelocatedError as error:
                logger.warning("Agent startup project binding changed: %s", str(error)[:300])
                outcomes.append({"status": "project_binding_changed", "project_root": str(root)})
            except (OSError, ValueError) as error:
                logger.warning("Agent startup project unavailable: %s", str(error)[:300])
                outcomes.append({"status": "project_unavailable", "project_root": str(root),
                                 "error": str(error)[:300]})
        return outcomes
