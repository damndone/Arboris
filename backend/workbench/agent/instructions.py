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
import json
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


# ---------------------------------------------------------------------------
# "Draft from this project": the template with the data filled in, no model.

_MAX_DATASETS = 6
_MAX_COLUMNS = 60


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None


def project_facts(project_root: Path) -> dict[str, Any]:
    """Datasets (by upload) and models fitted, newest run first."""

    runs_root = Path(project_root) / "runs"
    runs = sorted((path for path in runs_root.glob("*") if path.is_dir() and not path.name.startswith("_")), reverse=True) if runs_root.is_dir() else []
    datasets: dict[str, dict[str, Any]] = {}
    models: list[str] = []
    for run in runs:
        inputs = _json(run / "run_inputs.json") or {}
        upload = inputs.get("upload") if isinstance(inputs, dict) else None
        form = inputs.get("form") if isinstance(inputs, dict) else None
        key = (upload or {}).get("sha256") or run.name
        name = (upload or {}).get("filename") or run.name
        if key not in datasets and len(datasets) < _MAX_DATASETS:
            profile = _json(run / "staged" / "data_profile.json")
            labels = (_json(run / "staged" / "metadata_registry.json") or {}).get("variable_labels") or {}
            if isinstance(profile, dict) and isinstance(profile.get("columns"), dict):
                columns = [
                    {
                        "name": column,
                        "dtype": meta.get("dtype"),
                        "missing_rate": meta.get("missing_rate"),
                        "label": labels.get(column) if isinstance(labels, dict) else None,
                    }
                    for column, meta in profile["columns"].items()
                    if isinstance(meta, dict)
                ]
                datasets[key] = {
                    "name": name,
                    "rows": profile.get("row_count"),
                    "columns": columns,
                }
        if isinstance(form, dict) and form.get("y"):
            spec = f"{form.get('model_type') or 'auto'}: {form['y']} ~ {form.get('x') or ''}".strip()
            if spec not in models:
                models.append(spec)
    return {"datasets": list(datasets.values()), "models": models[:12]}


def draft(project_root: Path) -> str:
    facts = project_facts(project_root)
    lines: list[str] = []
    for dataset in facts["datasets"]:
        rows = f"{dataset['rows']} rows" if dataset.get("rows") else "rows unknown"
        lines.append(f"- `{dataset['name']}` ({rows}, {len(dataset['columns'])} columns):")
        for column in dataset["columns"][:_MAX_COLUMNS]:
            details = [str(column["dtype"])] if column.get("dtype") else []
            if column.get("missing_rate"):
                details.append(f"{float(column['missing_rate']):.1%} missing")
            meaning = column.get("label") or "meaning?"
            lines.append(f"  - {column['name']} - {meaning} - {', '.join(details) or 'type?'}")
        hidden = len(dataset["columns"]) - _MAX_COLUMNS
        if hidden > 0:
            lines.append(f"  - ... {hidden} more columns")
    text = template("project")
    if lines:
        text = text.replace(
            "- Key variables (name - meaning - unit or coding):",
            "- Key variables (name - meaning - unit or coding); filled from the project's data, replace each '?':\n"
            + "\n".join(lines),
        )
    if facts["models"]:
        text = text.replace(
            "- Methods agreed, or ruled out and why:",
            "- Methods agreed, or ruled out and why. Fitted so far: " + "; ".join(facts["models"]),
        )
    return text
