"""Instructions the Agent reads at the start of every conversation.

Three layers, joined general to specific so the more specific one wins
(Codex's AGENTS.md order):

1. the built-in Arboris analysis guide (read-only, ships with the Workbench);
2. personal instructions, ``~/.config/econometrics-workbench/AGENTS.md``;
3. project instructions, ``<project>/AGENTS.md`` -- the file Codex, Claude
   Code and pi also read in that folder.

Each conversation receives them once, as a standing message (a frozen
snapshot, as in Hermes). The total is capped; anything cut is said so.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

GUIDES = Path(__file__).with_name("guides")
INSTRUCTIONS_NAME = "workbench_instructions"
FILENAME = "AGENTS.md"
# Codex's project_doc_max_bytes default.
MAX_BYTES = 32 * 1024
PERSONAL_PATH_ENV = "WORKBENCH_AGENT_INSTRUCTIONS_PATH"

Kind = Literal["guide", "personal", "project"]
EDITABLE: tuple[Kind, ...] = ("personal", "project")


def personal_path() -> Path:
    override = os.environ.get(PERSONAL_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "econometrics-workbench" / FILENAME


def project_path(project_root: Path) -> Path:
    return Path(project_root) / FILENAME


def layer_path(kind: Kind, project_root: Path) -> Path:
    if kind == "guide":
        return GUIDES / "analysis_guide.md"
    if kind == "personal":
        return personal_path()
    return project_path(project_root)


def template(kind: Literal["personal", "project"]) -> str:
    return (GUIDES / f"{kind}_template.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Layer:
    kind: Kind
    path: Path
    content: str

    @property
    def exists(self) -> bool:
        return bool(self.content.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "exists": self.exists,
            "editable": self.kind in EDITABLE,
            "content": self.content,
            "bytes": len(self.content.encode("utf-8")),
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, UnicodeDecodeError):
        return ""


def layers(project_root: Path) -> list[Layer]:
    return [Layer(kind, layer_path(kind, project_root), _read(layer_path(kind, project_root))) for kind in ("guide", "personal", "project")]


_HEADINGS = {
    "guide": "Built-in Arboris analysis guide",
    "personal": "The person's own instructions (all projects)",
    "project": "This project's instructions (AGENTS.md)",
}


def compose(project_root: Path) -> tuple[str, dict[str, Any]]:
    """The standing message and what went into it (for the record)."""

    parts = [
        "Instructions for this conversation, general to specific: where they disagree, the later one wins. "
        "None of them relaxes the analysis-integrity rules. Follow them without restating them."
    ]
    record: list[dict[str, Any]] = []
    used = len(parts[0].encode("utf-8"))
    truncated = False
    for layer in layers(project_root):
        if not layer.exists:
            record.append({"kind": layer.kind, "present": False})
            continue
        body = layer.content.strip()
        block = f"\n\n## {_HEADINGS[layer.kind]}\n\n{body}"
        size = len(block.encode("utf-8"))
        if used + size > MAX_BYTES:
            room = max(MAX_BYTES - used - 200, 0)
            block = block.encode("utf-8")[:room].decode("utf-8", "ignore") + (
                f"\n\n[The rest of the {layer.kind} instructions was cut: together they exceed {MAX_BYTES // 1024} KiB. "
                "Tell the person if something they rely on may be missing.]"
            )
            truncated = True
        parts.append(block)
        used += len(block.encode("utf-8"))
        record.append({
            "kind": layer.kind,
            "present": True,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "bytes": len(body.encode("utf-8")),
        })
        if truncated:
            break
    return "".join(parts), {"layers": record, "truncated": truncated, "max_bytes": MAX_BYTES}


def save(kind: Literal["personal", "project"], project_root: Path, content: str) -> Path:
    """Write one editable layer atomically. An empty text removes nothing: it
    is written as empty, which the Agent treats as absent."""

    if kind not in EDITABLE:
        raise ValueError("only personal and project instructions can be edited")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"instructions are limited to {MAX_BYTES // 1024} KiB")
    path = layer_path(kind, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path
