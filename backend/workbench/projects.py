from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import write_environment_snapshot, write_json


@dataclass(frozen=True)
class Project:
    root: Path
    name: str


@dataclass(frozen=True)
class Run:
    root: Path
    run_id: str
    mode: str


def create_project(parent: Path, name: str) -> Project:
    root = parent / name
    (root / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(parents=True, exist_ok=True)
    write_json(root / "project.yaml", {"name": name})
    write_json(root / "config.yml", {})
    return Project(root=root, name=name)


def create_run(project_root: Path, mode: str) -> Run:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    root = project_root / "runs" / run_id
    for dirname in [
        "raw_snapshot",
        "staged",
        "processed",
        "model_results",
        "figures",
        "tables",
        "reports",
        "exports",
    ]:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    write_json(
        root / "run_manifest.json",
        {"run_id": run_id, "mode": mode, "status": "created", "lineage": []},
    )
    write_environment_snapshot(root / "environment.json")
    (root / "workflow_log.jsonl").write_text("", encoding="utf-8")
    write_json(root / "decisions.json", {"decisions": []})
    write_json(root / "errors.json", {"issues": []})
    write_json(root / "artifacts_index.json", {"artifacts": []})
    return Run(root=root, run_id=run_id, mode=mode)
