from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .artifacts import write_environment_snapshot, write_json, write_text_durable
from .config import load_config


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
    project_path = root / "project.yaml"
    config_path = root / "config.yml"
    if not project_path.exists():
        write_json(project_path, {"name": name})
    if not config_path.exists():
        write_json(config_path, {})
    return Project(root=root, name=name)


def create_run(project_root: Path, mode: str) -> Run:
    config_path = project_root / "config.yml"
    config = load_config(config_path)
    runs_root = project_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    while True:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        run_id = f"{timestamp}_{uuid4().hex[:8]}"
        root = runs_root / run_id
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        break
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
        (root / dirname).mkdir(parents=True, exist_ok=False)
    write_json(
        root / "run_manifest.json",
        {"run_id": run_id, "mode": mode, "status": "created", "lineage": []},
    )
    write_environment_snapshot(
        root / "environment.json",
        config_path=config_path,
        random_seed=config.random_seed,
    )
    write_text_durable(root / "workflow_log.jsonl", "")
    write_json(root / "decisions.json", {"decisions": []})
    write_json(root / "errors.json", {"issues": []})
    write_json(root / "artifacts_index.json", {"artifacts": []})
    return Run(root=root, run_id=run_id, mode=mode)
