from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WorkbenchConfig:
    max_single_file_gb: float = 2.0
    max_rows: int = 5_000_000
    max_excel_sheets: int = 20
    max_upload_files: int = 20
    min_join_overlap: float = 0.7
    max_missing_rate: float = 0.4
    min_model_n: int = 30
    max_panel_missing_cells: float = 0.5
    min_variable_role_confidence: float = 0.65
    random_seed: int = 20260429
    imputation_method: str = ""
    imputation_m: int = 5
    imputation_max_iter: int = 10


def load_config(path: Path | None) -> WorkbenchConfig:
    if path is None or not path.exists():
        return WorkbenchConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return WorkbenchConfig()
    if not isinstance(raw, Mapping):
        raise ValueError(f"Config file {path} must contain a mapping of config keys.")
    allowed = {field.name for field in fields(WorkbenchConfig)}
    values: dict[str, Any] = {key: value for key, value in raw.items() if key in allowed}
    return WorkbenchConfig(**values)
