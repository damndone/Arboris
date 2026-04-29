from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from . import __version__
from .domain import ArtifactRecord


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_artifact(
    run_root: Path,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> ArtifactRecord:
    record = ArtifactRecord(
        artifact_id=artifact_id,
        path=str(path.relative_to(run_root)),
        artifact_type=artifact_type,
        step=step,
        sha256=sha256_file(path),
        inputs=inputs,
        code_version=__version__,
    )
    index_path = run_root / "artifacts_index.json"
    index = read_json(index_path)
    index["artifacts"].append(record.to_dict())
    write_json(index_path, index)
    return record


def write_environment_snapshot(path: Path) -> None:
    write_json(
        path,
        {
            "python_version": platform.python_version(),
            "app_version": __version__,
            "os": platform.platform(),
            "random_seed": 20260429,
        },
    )
