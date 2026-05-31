from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import __version__
from .domain import ArtifactRecord

PACKAGE_VERSION_NAMES = (
    "fastapi",
    "uvicorn",
    "python-multipart",
    "pandas",
    "openpyxl",
    "pyarrow",
    "statsmodels",
    "scipy",
    "linearmodels",
    "scikit-learn",
    "imbalanced-learn",
    "matplotlib",
    "jinja2",
    "reportlab",
    "pyyaml",
    "typer",
)


def write_text_durable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.replace(path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    write_text_durable(path, text)


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
    resolved_run_root = run_root.resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_run_root)
    except ValueError as exc:
        raise ValueError(f"artifact path must be inside run root: {path}") from exc
    record = ArtifactRecord(
        artifact_id=artifact_id,
        path=relative_path.as_posix(),
        artifact_type=artifact_type,
        step=step,
        sha256=sha256_file(resolved_path),
        inputs=inputs,
        code_version=__version__,
    )
    index_path = run_root / "artifacts_index.json"
    index = read_json(index_path)
    index["artifacts"].append(record.to_dict())
    write_json(index_path, index)
    return record


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in PACKAGE_VERSION_NAMES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def write_environment_snapshot(
    path: Path,
    *,
    config_path: Path | None = None,
    random_seed: int = 20260429,
) -> None:
    config_hash = sha256_file(config_path) if config_path and config_path.exists() else ""
    write_json(
        path,
        {
            "python_version": platform.python_version(),
            "package_versions": package_versions(),
            "app_version": __version__,
            "os": platform.platform(),
            "config_hash": config_hash,
            "random_seed": random_seed,
        },
    )
