"""'Draft from this project': the project-instructions template with the
project's datasets, variables and fitted models filled in, without a model.

It reads run profiles for a person editing AGENTS.md in Settings; nothing
here reaches the Agent's context, which is why it lives outside agent/
(tests/test_context_compiler_entry_point.py keeps agent modules off
compiler-owned sources such as data_profile.json).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..agent.instructions import template

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
