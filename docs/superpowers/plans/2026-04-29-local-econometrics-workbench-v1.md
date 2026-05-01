# Local Econometrics Workbench V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first V1 econometrics workbench that imports CSV/Excel data, creates auditable project/run artifacts, identifies dataset structure, runs basic econometric analysis, and exports an HTML/PDF/XLSX report.

**Architecture:** Use a Python backend as the source of truth for data processing, artifacts, metadata, validation, econometrics, reporting, exports, and a local FastAPI API. Use a lightweight React UI for local project creation, upload, run mode selection, report viewing, and artifact browsing. Every workflow run writes immutable run-scoped outputs with `run_manifest.json`, `environment.json`, `decisions.json`, `errors.json`, and `artifacts_index.json`.

**Tech Stack:** Python 3.11+, FastAPI, pandas, pyarrow, statsmodels, scipy, matplotlib, jinja2, reportlab, openpyxl, pytest, React, Vite, TypeScript, Vitest.

---

## Scope Decision

The approved spec describes a full application. This plan implements the V1 core slice that produces working software end to end:

- Project/run directory creation.
- CSV/Excel ingestion within configured V1 size limits.
- Metadata registry, profiling, validation, merge advice, cleaning, analysis routing.
- OLS, robust standard errors, basic fixed effects, simple time-series diagnostics, descriptive statistics, and correlation analysis.
- HTML report, PDF report, and XLSX table export.
- Template datasets for cross-section, time series, and panel workflows.
- Local API and UI that can run the workflow and inspect outputs.

V1.x export formats Word, Notebook, and LaTeX are represented in the report/export model but are not generated in this plan because the approved spec makes HTML/PDF/XLSX the first core milestone.

## File Structure

- Create: `pyproject.toml` - Python package, dependencies, pytest config, CLI entrypoint.
- Create: `backend/workbench/__init__.py` - package marker and version.
- Create: `backend/workbench/domain.py` - shared enums and dataclasses for runs, artifacts, metadata, issues, decisions, models, and reports.
- Create: `backend/workbench/config.py` - default V1 thresholds and YAML loading.
- Create: `backend/workbench/projects.py` - project and run directory manager.
- Create: `backend/workbench/artifacts.py` - JSON/file hashing, artifact registration, lineage, environment snapshot.
- Create: `backend/workbench/ingestion.py` - CSV/Excel reading and raw snapshot registration.
- Create: `backend/workbench/metadata.py` - schema and semantic role inference.
- Create: `backend/workbench/profiling.py` - missingness, uniqueness, distribution, correlation, and time profile summaries.
- Create: `backend/workbench/validation.py` - BLOCKER/WARNING/INFO guardrail checks.
- Create: `backend/workbench/merge.py` - join-key and join-type recommendation.
- Create: `backend/workbench/cleaning.py` - deterministic column normalization, date parsing, duplicate handling, and action logging.
- Create: `backend/workbench/router.py` - cross-section, time-series, panel, repeated cross-section, unknown/mixed structure classification.
- Create: `backend/workbench/econometrics/specs.py` - model specification builder.
- Create: `backend/workbench/econometrics/runner.py` - OLS, robust OLS, fixed effects, time-series diagnostics.
- Create: `backend/workbench/econometrics/normalize.py` - statsmodels output normalization.
- Create: `backend/workbench/visualization.py` - figure generation and artifact registration.
- Create: `backend/workbench/narrative.py` - rule-based narrative assistant with source-bound claims.
- Create: `backend/workbench/reporting.py` - report document model and HTML rendering.
- Create: `backend/workbench/templates/report.html.j2` - HTML report template.
- Create: `backend/workbench/exports.py` - PDF and XLSX exports.
- Create: `backend/workbench/orchestrator.py` - end-to-end workflow coordination.
- Create: `backend/workbench/api.py` - local FastAPI app.
- Create: `backend/workbench/cli.py` - command-line entrypoints for testing and batch runs.
- Create: `tests/` - backend unit, integration, failure, traceability, and acceptance tests.
- Create: `examples/datasets/` - cross-section, time-series, and panel sample datasets.
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/App.test.tsx`, `frontend/src/styles.css` - local React UI.

## Task 1: Bootstrap Python Package and Shared Domain Types

**Files:**
- Create: `pyproject.toml`
- Create: `backend/workbench/__init__.py`
- Create: `backend/workbench/domain.py`
- Create: `backend/workbench/config.py`
- Test: `tests/test_config_and_domain.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_config_and_domain.py
from pathlib import Path

from workbench.config import WorkbenchConfig, load_config
from workbench.domain import ArtifactRecord, DatasetKind, Severity


def test_default_config_matches_v1_boundaries():
    config = WorkbenchConfig()
    assert config.max_single_file_gb == 2.0
    assert config.max_rows == 5_000_000
    assert config.max_excel_sheets == 20
    assert config.max_upload_files == 20
    assert config.min_join_overlap == 0.7
    assert config.max_missing_rate == 0.4
    assert config.min_model_n == 30


def test_load_config_allows_project_override(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("max_rows: 100\nmin_join_overlap: 0.8\n", encoding="utf-8")
    config = load_config(path)
    assert config.max_rows == 100
    assert config.min_join_overlap == 0.8
    assert config.max_upload_files == 20


def test_domain_records_are_serializable():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=[],
    )
    assert record.to_dict()["artifact_id"] == "raw_file"
    assert Severity.BLOCKER.value == "BLOCKER"
    assert DatasetKind.PANEL.value == "panel"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_config_and_domain.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'workbench'`.

- [x] **Step 3: Create the package and shared types**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "local-econometrics-workbench"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.111",
  "uvicorn[standard]>=0.30",
  "python-multipart>=0.0.9",
  "pandas>=2.2",
  "openpyxl>=3.1",
  "pyarrow>=16.0",
  "statsmodels>=0.14",
  "scipy>=1.13",
  "matplotlib>=3.8",
  "jinja2>=3.1",
  "reportlab>=4.2",
  "pyyaml>=6.0",
  "typer>=0.12"
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "httpx>=0.27"]

[project.scripts]
workbench = "workbench.cli:app"

[tool.setuptools.packages.find]
where = ["backend"]

[tool.pytest.ini_options]
pythonpath = ["backend"]
testpaths = ["tests"]
```

```python
# backend/workbench/__init__.py
__version__ = "0.1.0"
```

```python
# backend/workbench/domain.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunMode(str, Enum):
    AUTO = "auto"
    STEPPED = "stepped"


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class DatasetKind(str, Enum):
    CROSS_SECTION = "cross_section"
    TIME_SERIES = "time_series"
    PANEL = "panel"
    REPEATED_CROSS_SECTION = "repeated_cross_section"
    UNKNOWN_MIXED = "unknown_mixed"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    path: str
    artifact_type: str
    step: str
    sha256: str
    inputs: list[str] = field(default_factory=list)
    config_hash: str = ""
    code_version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardrailIssue:
    severity: Severity
    code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        return data


@dataclass(frozen=True)
class DecisionRecord:
    step: str
    suggestion: str
    confidence: float
    evidence: list[str]
    user_action: str
    final_decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    dtype: str
    semantic_role: str
    confidence: float
    source_file: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetSchema:
    dataset_id: str
    source_files: list[str]
    columns: list[ColumnMetadata]
    primary_key_candidates: list[str]
    time_candidates: list[str]
    id_candidates: list[str]
    transformations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

```python
# backend/workbench/config.py
from __future__ import annotations

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


def load_config(path: Path | None) -> WorkbenchConfig:
    if path is None or not path.exists():
        return WorkbenchConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowed = {field.name for field in fields(WorkbenchConfig)}
    values: dict[str, Any] = {key: value for key, value in raw.items() if key in allowed}
    return WorkbenchConfig(**values)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_config_and_domain.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml backend/workbench/__init__.py backend/workbench/domain.py backend/workbench/config.py tests/test_config_and_domain.py
git commit -m "feat: bootstrap workbench package"
```

## Task 2: Project, Run, Artifact, and Environment Management

**Files:**
- Create: `backend/workbench/projects.py`
- Create: `backend/workbench/artifacts.py`
- Test: `tests/test_project_run_artifacts.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_project_run_artifacts.py
import json
from pathlib import Path

from workbench.artifacts import register_artifact, sha256_file
from workbench.projects import create_project, create_run


def test_create_project_and_run_directories(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    assert (project.root / "project.yaml").exists()
    assert (project.root / "config.yml").exists()
    assert (project.root / "data" / "raw").is_dir()

    run = create_run(project.root, mode="auto")
    assert run.run_id
    assert (run.root / "run_manifest.json").exists()
    assert (run.root / "environment.json").exists()
    assert (run.root / "artifacts_index.json").exists()
    assert (run.root / "decisions.json").exists()
    assert (run.root / "errors.json").exists()
    assert (run.root / "staged").is_dir()
    assert (run.root / "processed").is_dir()


def test_register_artifact_writes_index_and_hash(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    source = run.root / "staged" / "sample.txt"
    source.write_text("abc", encoding="utf-8")
    record = register_artifact(run.root, "sample", source, "text", "unit", [])
    index = json.loads((run.root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert index["artifacts"][0]["artifact_id"] == "sample"
    assert index["artifacts"][0]["sha256"] == sha256_file(source)
    assert record.path.endswith("sample.txt")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_project_run_artifacts.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.projects`.

- [x] **Step 3: Implement project/run and artifact management**

```python
# backend/workbench/projects.py
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
    for dirname in ["raw_snapshot", "staged", "processed", "model_results", "figures", "tables", "reports", "exports"]:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    write_json(root / "run_manifest.json", {"run_id": run_id, "mode": mode, "status": "created", "lineage": []})
    write_environment_snapshot(root / "environment.json")
    (root / "workflow_log.jsonl").write_text("", encoding="utf-8")
    write_json(root / "decisions.json", {"decisions": []})
    write_json(root / "errors.json", {"issues": []})
    write_json(root / "artifacts_index.json", {"artifacts": []})
    return Run(root=root, run_id=run_id, mode=mode)
```

```python
# backend/workbench/artifacts.py
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


def register_artifact(run_root: Path, artifact_id: str, path: Path, artifact_type: str, step: str, inputs: list[str]) -> ArtifactRecord:
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_project_run_artifacts.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/projects.py backend/workbench/artifacts.py tests/test_project_run_artifacts.py
git commit -m "feat: add project run artifact management"
```

## Task 3: Data Ingestion and Metadata Registry

**Files:**
- Create: `backend/workbench/ingestion.py`
- Create: `backend/workbench/metadata.py`
- Test: `tests/test_ingestion_metadata.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_ingestion_metadata.py
from pathlib import Path

import pandas as pd

from workbench.config import WorkbenchConfig
from workbench.ingestion import ingest_files
from workbench.metadata import infer_schema
from workbench.projects import create_project, create_run


def test_ingest_csv_copies_raw_snapshot_and_registers_schema(tmp_path: Path):
    source = tmp_path / "source.csv"
    pd.DataFrame({"firm_id": [1, 2], "year": [2020, 2021], "sales": [10.0, 12.5]}).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    frames = ingest_files([source], run.root, WorkbenchConfig())
    assert list(frames.keys()) == ["source.csv"]
    assert (run.root / "raw_snapshot" / "source.csv").exists()

    schema = infer_schema("dataset_1", frames, run.root)
    assert "year" in schema.time_candidates
    assert "firm_id" in schema.id_candidates
    roles = {column.name: column.semantic_role for column in schema.columns}
    assert roles["sales"] == "numeric_measure"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ingestion_metadata.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.ingestion`.

- [x] **Step 3: Implement ingestion and schema inference**

```python
# backend/workbench/ingestion.py
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from .artifacts import register_artifact
from .config import WorkbenchConfig


def ingest_files(paths: list[Path], run_root: Path, config: WorkbenchConfig) -> dict[str, pd.DataFrame]:
    if len(paths) > config.max_upload_files:
        raise ValueError(f"upload file count exceeds limit: {len(paths)} > {config.max_upload_files}")
    frames: dict[str, pd.DataFrame] = {}
    for path in paths:
        size_gb = path.stat().st_size / (1024 ** 3)
        if size_gb > config.max_single_file_gb:
            raise ValueError(f"file exceeds size limit: {path.name}")
        target = run_root / "raw_snapshot" / path.name
        shutil.copy2(path, target)
        register_artifact(run_root, f"raw_{path.name}", target, "raw_data", "ingestion", [])
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(target)
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            excel = pd.ExcelFile(target)
            if len(excel.sheet_names) > config.max_excel_sheets:
                raise ValueError(f"excel sheet count exceeds limit: {path.name}")
            frame = pd.read_excel(target, sheet_name=excel.sheet_names[0])
        else:
            raise ValueError(f"unsupported file type: {path.suffix}")
        if len(frame) > config.max_rows:
            raise ValueError(f"row count exceeds limit: {path.name}")
        frames[path.name] = frame
    return frames
```

```python
# backend/workbench/metadata.py
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .artifacts import write_json
from .domain import ColumnMetadata, DatasetSchema


TIME_TOKENS = ("date", "time", "timestamp", "year", "month", "quarter")
ID_TOKENS = ("id", "code", "key", "gvkey", "permno", "firm", "user", "store")


def infer_schema(dataset_id: str, frames: dict[str, pd.DataFrame], run_root: Path) -> DatasetSchema:
    columns: list[ColumnMetadata] = []
    time_candidates: list[str] = []
    id_candidates: list[str] = []
    primary_key_candidates: list[str] = []
    for source_file, frame in frames.items():
        row_count = max(len(frame), 1)
        for name in frame.columns:
            series = frame[name]
            normalized = str(name).lower()
            dtype = str(series.dtype)
            evidence: list[str] = []
            role = "categorical"
            confidence = 0.5
            if pd.api.types.is_numeric_dtype(series):
                role = "numeric_measure"
                confidence = 0.7
            if any(token in normalized for token in TIME_TOKENS):
                role = "time"
                confidence = 0.85
                time_candidates.append(str(name))
                evidence.append("name_matches_time_token")
            if any(token in normalized for token in ID_TOKENS):
                role = "entity_id"
                confidence = 0.8
                id_candidates.append(str(name))
                evidence.append("name_matches_id_token")
            unique_ratio = float(series.nunique(dropna=True) / row_count)
            if unique_ratio == 1.0:
                primary_key_candidates.append(str(name))
                evidence.append("unique_column")
            columns.append(ColumnMetadata(str(name), dtype, role, confidence, source_file, evidence))
    schema = DatasetSchema(dataset_id, list(frames.keys()), columns, primary_key_candidates, time_candidates, id_candidates)
    write_json(run_root / "staged" / "metadata_registry.json", schema.to_dict())
    return schema
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ingestion_metadata.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/ingestion.py backend/workbench/metadata.py tests/test_ingestion_metadata.py
git commit -m "feat: add ingestion metadata registry"
```

## Task 4: Profiling and Validation Guardrails

**Files:**
- Create: `backend/workbench/profiling.py`
- Create: `backend/workbench/validation.py`
- Test: `tests/test_profiling_validation.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_profiling_validation.py
import pandas as pd

from workbench.config import WorkbenchConfig
from workbench.domain import Severity
from workbench.profiling import profile_frame
from workbench.validation import validate_profile


def test_profile_frame_records_missing_and_correlation():
    frame = pd.DataFrame({"x": [1.0, 2.0, None], "y": [2.0, 4.0, 6.0], "group": ["a", "b", "b"]})
    profile = profile_frame(frame)
    assert profile["row_count"] == 3
    assert profile["columns"]["x"]["missing_rate"] == 1 / 3
    assert "x" in profile["correlations"]


def test_validation_flags_missing_rate_warning():
    frame = pd.DataFrame({"x": [None, None, 3.0], "y": [1.0, 2.0, 3.0]})
    profile = profile_frame(frame)
    issues = validate_profile(profile, WorkbenchConfig(max_missing_rate=0.4, min_model_n=2))
    assert any(issue.severity == Severity.WARNING and issue.code == "HIGH_MISSING_RATE" for issue in issues)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_profiling_validation.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.profiling`.

- [x] **Step 3: Implement profiling and guardrails**

```python
# backend/workbench/profiling.py
from __future__ import annotations

from typing import Any

import pandas as pd


def profile_frame(frame: pd.DataFrame) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for name in frame.columns:
        series = frame[name]
        columns[str(name)] = {
            "dtype": str(series.dtype),
            "missing_rate": float(series.isna().mean()),
            "unique_count": int(series.nunique(dropna=True)),
            "unique_ratio": float(series.nunique(dropna=True) / max(len(series), 1)),
        }
        if pd.api.types.is_numeric_dtype(series):
            columns[str(name)]["mean"] = None if series.dropna().empty else float(series.mean())
            columns[str(name)]["std"] = None if series.dropna().empty else float(series.std())
    numeric = frame.select_dtypes(include="number")
    correlations = numeric.corr(numeric_only=True).fillna(0.0).to_dict() if len(numeric.columns) else {}
    return {"row_count": int(len(frame)), "column_count": int(len(frame.columns)), "columns": columns, "correlations": correlations}
```

```python
# backend/workbench/validation.py
from __future__ import annotations

from .config import WorkbenchConfig
from .domain import GuardrailIssue, Severity


def validate_profile(profile: dict, config: WorkbenchConfig) -> list[GuardrailIssue]:
    issues: list[GuardrailIssue] = []
    if profile["row_count"] < config.min_model_n:
        issues.append(GuardrailIssue(Severity.BLOCKER, "INSUFFICIENT_SAMPLE", "Sample size is below the configured modeling minimum.", {"row_count": profile["row_count"]}))
    for name, column in profile["columns"].items():
        if column["missing_rate"] > config.max_missing_rate:
            issues.append(GuardrailIssue(Severity.WARNING, "HIGH_MISSING_RATE", f"Column {name} exceeds missing-rate threshold.", {"column": name, "missing_rate": column["missing_rate"]}))
    return issues


def has_blockers(issues: list[GuardrailIssue]) -> bool:
    return any(issue.severity == Severity.BLOCKER for issue in issues)
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_profiling_validation.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/profiling.py backend/workbench/validation.py tests/test_profiling_validation.py
git commit -m "feat: add profiling guardrails"
```

## Task 5: Merge Advisor and Cleaning Engine

**Files:**
- Create: `backend/workbench/merge.py`
- Create: `backend/workbench/cleaning.py`
- Test: `tests/test_merge_cleaning.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_merge_cleaning.py
import pandas as pd

from workbench.cleaning import clean_frame
from workbench.config import WorkbenchConfig
from workbench.merge import recommend_merge


def test_recommend_merge_uses_overlap_and_uniqueness():
    left = pd.DataFrame({"firm_id": [1, 2, 3], "sales": [10, 12, 13]})
    right = pd.DataFrame({"firm_id": [1, 2, 4], "assets": [20, 30, 40]})
    plan = recommend_merge(left, right, WorkbenchConfig(min_join_overlap=0.5))
    assert plan["join_key"] == "firm_id"
    assert plan["join_type"] == "inner"
    assert plan["confidence"] >= 0.5


def test_clean_frame_normalizes_columns_and_records_actions():
    frame = pd.DataFrame({"Firm ID": [1, 1, 2], "Year": ["2020", "2020", "2021"], "Sales": [10.0, 10.0, None]})
    cleaned, actions = clean_frame(frame, date_candidates=["year"])
    assert list(cleaned.columns) == ["firm_id", "year", "sales"]
    assert len(cleaned) == 2
    assert any(action["action"] == "drop_duplicate_rows" for action in actions)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_merge_cleaning.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.merge`.

- [x] **Step 3: Implement merge advice and deterministic cleaning**

```python
# backend/workbench/merge.py
from __future__ import annotations

from typing import Any

import pandas as pd

from .config import WorkbenchConfig


def recommend_merge(left: pd.DataFrame, right: pd.DataFrame, config: WorkbenchConfig) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for column in sorted(set(left.columns).intersection(set(right.columns))):
        left_values = set(left[column].dropna().unique())
        right_values = set(right[column].dropna().unique())
        denominator = max(min(len(left_values), len(right_values)), 1)
        overlap = len(left_values.intersection(right_values)) / denominator
        left_unique = left[column].is_unique
        right_unique = right[column].is_unique
        confidence = overlap
        if left_unique or right_unique:
            confidence += 0.1
        candidates.append({"join_key": str(column), "join_type": "inner" if overlap >= config.min_join_overlap else "left", "overlap": overlap, "confidence": min(confidence, 1.0)})
    if not candidates:
        return {"join_key": "", "join_type": "none", "overlap": 0.0, "confidence": 0.0}
    return max(candidates, key=lambda item: item["confidence"])
```

```python
# backend/workbench/cleaning.py
from __future__ import annotations

import re
from typing import Any

import pandas as pd


def normalize_column_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


def clean_frame(frame: pd.DataFrame, date_candidates: list[str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = []
    cleaned = frame.copy()
    rename_map = {column: normalize_column_name(str(column)) for column in cleaned.columns}
    cleaned = cleaned.rename(columns=rename_map)
    actions.append({"action": "normalize_column_names", "details": rename_map})
    for candidate in date_candidates:
        normalized = normalize_column_name(candidate)
        if normalized in cleaned.columns:
            cleaned[normalized] = pd.to_datetime(cleaned[normalized], errors="ignore")
            actions.append({"action": "parse_date_candidate", "column": normalized})
    before = len(cleaned)
    cleaned = cleaned.drop_duplicates()
    dropped = before - len(cleaned)
    if dropped:
        actions.append({"action": "drop_duplicate_rows", "rows_dropped": dropped})
    return cleaned, actions
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_merge_cleaning.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/merge.py backend/workbench/cleaning.py tests/test_merge_cleaning.py
git commit -m "feat: add merge advisor cleaning"
```

## Task 6: Analysis Router

**Files:**
- Create: `backend/workbench/router.py`
- Test: `tests/test_analysis_router.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_analysis_router.py
import pandas as pd

from workbench.domain import DatasetKind
from workbench.router import classify_dataset


def test_classifies_cross_section_without_time():
    result = classify_dataset(pd.DataFrame({"firm_id": [1, 2, 3], "sales": [10, 12, 9]}), id_candidates=["firm_id"], time_candidates=[])
    assert result["kind"] == DatasetKind.CROSS_SECTION.value


def test_classifies_unbalanced_panel():
    frame = pd.DataFrame({"firm_id": [1, 1, 2], "year": [2020, 2021, 2020], "sales": [10, 11, 20]})
    result = classify_dataset(frame, id_candidates=["firm_id"], time_candidates=["year"])
    assert result["kind"] == DatasetKind.PANEL.value
    assert "panel_unbalanced" in result["secondary_labels"]


def test_classifies_repeated_cross_section():
    frame = pd.DataFrame({"year": [2020, 2020, 2021, 2021], "sales": [1, 2, 3, 4]})
    result = classify_dataset(frame, id_candidates=[], time_candidates=["year"])
    assert result["kind"] == DatasetKind.REPEATED_CROSS_SECTION.value
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_analysis_router.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.router`.

- [x] **Step 3: Implement dataset classification**

```python
# backend/workbench/router.py
from __future__ import annotations

from typing import Any

import pandas as pd

from .domain import DatasetKind


def classify_dataset(frame: pd.DataFrame, id_candidates: list[str], time_candidates: list[str]) -> dict[str, Any]:
    ids = [column for column in id_candidates if column in frame.columns]
    times = [column for column in time_candidates if column in frame.columns]
    labels: list[str] = []
    if not times:
        return {"kind": DatasetKind.CROSS_SECTION.value, "confidence": 0.75, "secondary_labels": labels, "evidence": ["no_time_candidate"]}
    time_col = times[0]
    if ids:
        id_col = ids[0]
        duplicate_pairs = frame.duplicated(subset=[id_col, time_col]).any()
        if duplicate_pairs:
            return {"kind": DatasetKind.UNKNOWN_MIXED.value, "confidence": 0.4, "secondary_labels": ["id_time_not_unique"], "evidence": [f"{id_col}-{time_col} duplicates"]}
        counts = frame.groupby(id_col)[time_col].nunique()
        if counts.nunique() == 1:
            labels.append("panel_balanced")
        else:
            labels.append("panel_unbalanced")
        return {"kind": DatasetKind.PANEL.value, "confidence": 0.85, "secondary_labels": labels, "evidence": [f"id={id_col}", f"time={time_col}"]}
    per_time = frame.groupby(time_col).size()
    if len(per_time) > 1 and per_time.max() > 1:
        return {"kind": DatasetKind.REPEATED_CROSS_SECTION.value, "confidence": 0.7, "secondary_labels": ["multiple_observations_per_period"], "evidence": [f"time={time_col}"]}
    return {"kind": DatasetKind.TIME_SERIES.value, "confidence": 0.8, "secondary_labels": ["single_observation_per_period"], "evidence": [f"time={time_col}"]}
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_analysis_router.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/router.py tests/test_analysis_router.py
git commit -m "feat: add analysis router"
```

## Task 7: Econometrics Engine

**Files:**
- Create: `backend/workbench/econometrics/__init__.py`
- Create: `backend/workbench/econometrics/specs.py`
- Create: `backend/workbench/econometrics/runner.py`
- Create: `backend/workbench/econometrics/normalize.py`
- Test: `tests/test_econometrics_engine.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_econometrics_engine.py
import pandas as pd

from workbench.econometrics.runner import run_fixed_effects, run_ols, run_time_series_diagnostics


def test_run_ols_returns_source_bound_coefficients():
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))})
    result = run_ols(frame, y="y", x=["x"], robust=True, model_id="regression_1")
    assert result["model_id"] == "regression_1"
    assert result["nobs"] == 35
    assert abs(result["coefficients"]["x"]["estimate"] - 2.0) < 1e-8
    assert result["coefficients"]["x"]["source_id"] == "model_results.regression_1.coefficients.x"


def test_run_fixed_effects_includes_entity_terms():
    frame = pd.DataFrame({"y": [1, 2, 2, 3], "x": [0, 1, 0, 1], "firm_id": [1, 1, 2, 2]})
    result = run_fixed_effects(frame, y="y", x=["x"], entity="firm_id", time=None, model_id="fe_1")
    assert result["model_id"] == "fe_1"
    assert result["nobs"] == 4


def test_time_series_diagnostics_reports_autocorrelation():
    frame = pd.DataFrame({"y": [1.0, 1.5, 2.2, 2.8, 3.6], "date": pd.date_range("2020-01-01", periods=5)})
    result = run_time_series_diagnostics(frame, y="y", time="date")
    assert "lag1_autocorrelation" in result
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_econometrics_engine.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.econometrics`.

- [x] **Step 3: Implement model runners and normalization**

```python
# backend/workbench/econometrics/__init__.py
"""Econometrics model specification, execution, and normalization."""
```

```python
# backend/workbench/econometrics/normalize.py
from __future__ import annotations

from typing import Any


def normalize_statsmodels_result(fitted: Any, model_id: str) -> dict[str, Any]:
    coefficients: dict[str, Any] = {}
    names = list(getattr(fitted.model, "exog_names", []))
    for index, term in enumerate(names):
        coefficients[str(term)] = {
            "estimate": float(fitted.params[index]),
            "std_error": float(fitted.bse[index]),
            "p_value": float(fitted.pvalues[index]),
            "source_id": f"model_results.{model_id}.coefficients.{term}",
        }
    return {
        "model_id": model_id,
        "nobs": int(fitted.nobs),
        "r_squared": float(getattr(fitted, "rsquared", 0.0)),
        "coefficients": coefficients,
    }
```

```python
# backend/workbench/econometrics/runner.py
from __future__ import annotations

from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from .normalize import normalize_statsmodels_result


def _formula(y: str, x: list[str]) -> str:
    return f"{y} ~ " + " + ".join(x)


def run_ols(frame: pd.DataFrame, y: str, x: list[str], robust: bool, model_id: str) -> dict[str, Any]:
    fitted = smf.ols(_formula(y, x), data=frame).fit()
    if robust:
        fitted = fitted.get_robustcov_results(cov_type="HC1")
        fitted.model.data.param_names = fitted.model.exog_names
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "ols_robust" if robust else "ols"
    return result


def run_fixed_effects(frame: pd.DataFrame, y: str, x: list[str], entity: str, time: str | None, model_id: str) -> dict[str, Any]:
    terms = list(x) + [f"C({entity})"]
    if time is not None:
        terms.append(f"C({time})")
    fitted = smf.ols(f"{y} ~ " + " + ".join(terms), data=frame).fit()
    result = normalize_statsmodels_result(fitted, model_id)
    result["model_type"] = "fixed_effects"
    return result


def run_time_series_diagnostics(frame: pd.DataFrame, y: str, time: str) -> dict[str, Any]:
    ordered = frame.sort_values(time)
    series = ordered[y].astype(float)
    return {"target": y, "time": time, "lag1_autocorrelation": float(series.autocorr(lag=1))}
```

```python
# backend/workbench/econometrics/specs.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_type: str
    y: str
    x: list[str]
    entity: str | None = None
    time: str | None = None
    robust: bool = True
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_econometrics_engine.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/econometrics tests/test_econometrics_engine.py
git commit -m "feat: add econometrics engine"
```

## Task 8: Visualization Engine

**Files:**
- Create: `backend/workbench/visualization.py`
- Test: `tests/test_visualization.py`

- [x] **Step 1: Write the failing test**

```python
# tests/test_visualization.py
from pathlib import Path

import pandas as pd

from workbench.projects import create_project, create_run
from workbench.visualization import create_figures


def test_create_figures_writes_png_artifacts(tmp_path: Path):
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]})
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    figures = create_figures(frame, run.root, numeric_columns=["x", "y"], time_column=None)
    assert "correlation_heatmap" in figures
    assert (run.root / figures["correlation_heatmap"]).exists()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_visualization.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.visualization`.

- [x] **Step 3: Implement figure generation**

```python
# backend/workbench/visualization.py
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from .artifacts import register_artifact


def create_figures(frame: pd.DataFrame, run_root: Path, numeric_columns: list[str], time_column: str | None) -> dict[str, str]:
    figures: dict[str, str] = {}
    if len(numeric_columns) >= 2:
        corr = frame[numeric_columns].corr(numeric_only=True)
        fig, ax = plt.subplots(figsize=(6, 4))
        image = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr.columns)), corr.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(corr.index)), corr.index)
        fig.colorbar(image, ax=ax)
        path = run_root / "figures" / "correlation_heatmap.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        register_artifact(run_root, "correlation_heatmap", path, "figure", "visualization", [])
        figures["correlation_heatmap"] = str(path.relative_to(run_root))
    if time_column and time_column in frame.columns and numeric_columns:
        fig, ax = plt.subplots(figsize=(7, 4))
        ordered = frame.sort_values(time_column)
        ax.plot(ordered[time_column], ordered[numeric_columns[0]])
        ax.set_title(f"{numeric_columns[0]} over {time_column}")
        path = run_root / "figures" / "time_trend.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        register_artifact(run_root, "time_trend", path, "figure", "visualization", [])
        figures["time_trend"] = str(path.relative_to(run_root))
    return figures
```

- [x] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_visualization.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/visualization.py tests/test_visualization.py
git commit -m "feat: add visualization engine"
```

## Task 9: Narrative, Reporting, and Exports

**Files:**
- Create: `backend/workbench/narrative.py`
- Create: `backend/workbench/reporting.py`
- Create: `backend/workbench/templates/report.html.j2`
- Create: `backend/workbench/exports.py`
- Test: `tests/test_reporting_exports.py`

- [x] **Step 1: Write the failing tests**

```python
# tests/test_reporting_exports.py
from pathlib import Path

from workbench.exports import export_pdf, export_xlsx
from workbench.narrative import build_claims
from workbench.projects import create_project, create_run
from workbench.reporting import render_html_report


def test_claims_have_source_ids():
    model_result = {"model_id": "regression_1", "coefficients": {"x": {"estimate": 2.0, "p_value": 0.01, "source_id": "model_results.regression_1.coefficients.x"}}}
    claims = build_claims([model_result], warnings=[])
    assert claims[0]["source_id"] == "model_results.regression_1.coefficients.x"


def test_render_and_export_reports(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {"title": "Demo Report", "facts": ["n=5"], "claims": [{"claim": "x is positive", "source_id": "model_results.regression_1.coefficients.x", "confidence": 0.9}], "warnings": []}
    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)
    xlsx_path = export_xlsx({"coefficients": [{"term": "x", "estimate": 2.0}]}, run.root)
    assert html_path.exists()
    assert pdf_path.exists()
    assert xlsx_path.exists()
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_reporting_exports.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.exports`.

- [x] **Step 3: Implement source-bound reporting and exports**

```python
# backend/workbench/narrative.py
from __future__ import annotations

from typing import Any


def build_claims(model_results: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for result in model_results:
        for term, stats in result.get("coefficients", {}).items():
            if term == "Intercept":
                continue
            direction = "positive" if stats["estimate"] >= 0 else "negative"
            claims.append({"claim": f"Coefficient {term} is {direction} in {result['model_id']}.", "source_id": stats["source_id"], "confidence": 0.8})
    for warning in warnings:
        claims.append({"claim": warning, "source_id": "errors.json", "confidence": 1.0})
    return claims
```

```python
# backend/workbench/reporting.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .artifacts import register_artifact


def render_html_report(report: dict[str, Any], run_root: Path) -> Path:
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape())
    template = env.get_template("report.html.j2")
    path = run_root / "reports" / "report.html"
    path.write_text(template.render(report=report), encoding="utf-8")
    register_artifact(run_root, "report_html", path, "report", "reporting", [])
    return path
```

```html
<!-- backend/workbench/templates/report.html.j2 -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ report.title }}</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 32px; color: #17202a; }
    h1 { font-size: 28px; }
    section { margin: 24px 0; }
    .warning { color: #8a4b00; font-weight: 600; }
    code { background: #f2f4f7; padding: 2px 4px; }
  </style>
</head>
<body>
  <h1>{{ report.title }}</h1>
  <section><h2>Facts</h2><ul>{% for fact in report.facts %}<li>{{ fact }}</li>{% endfor %}</ul></section>
  <section><h2>Interpretation</h2><ul>{% for claim in report.claims %}<li>{{ claim.claim }} <code>{{ claim.source_id }}</code></li>{% endfor %}</ul></section>
  <section><h2>Warnings</h2><ul>{% for warning in report.warnings %}<li class="warning">{{ warning }}</li>{% endfor %}</ul></section>
</body>
</html>
```

```python
# backend/workbench/exports.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .artifacts import register_artifact


def export_pdf(report: dict[str, Any], run_root: Path) -> Path:
    path = run_root / "reports" / "report.pdf"
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.drawString(72, 740, report["title"])
    y = 710
    for fact in report.get("facts", []):
        pdf.drawString(72, y, f"Fact: {fact}")
        y -= 18
    for claim in report.get("claims", []):
        pdf.drawString(72, y, f"Claim: {claim['claim']}")
        y -= 18
    pdf.save()
    register_artifact(run_root, "report_pdf", path, "report", "export", ["report_html"])
    return path


def export_xlsx(tables: dict[str, list[dict[str, Any]]], run_root: Path) -> Path:
    path = run_root / "exports" / "tables.xlsx"
    workbook = Workbook()
    first = True
    for name, rows in tables.items():
        sheet = workbook.active if first else workbook.create_sheet()
        first = False
        sheet.title = name[:31]
        if rows:
            headers = list(rows[0].keys())
            sheet.append(headers)
            for row in rows:
                sheet.append([row.get(header) for header in headers])
    workbook.save(path)
    register_artifact(run_root, "tables_xlsx", path, "table_export", "export", [])
    return path
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_reporting_exports.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/narrative.py backend/workbench/reporting.py backend/workbench/templates/report.html.j2 backend/workbench/exports.py tests/test_reporting_exports.py
git commit -m "feat: add source bound reporting exports"
```

## Task 10: End-to-End Workflow Orchestrator and CLI

**Files:**
- Create: `backend/workbench/orchestrator.py`
- Create: `backend/workbench/cli.py`
- Test: `tests/test_orchestrator_e2e.py`

- [x] **Step 1: Write the failing integration test**

```python
# tests/test_orchestrator_e2e.py
from pathlib import Path

import pandas as pd

from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_workflow_creates_traceable_outputs(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35)), "firm_id": list(range(100, 135))}).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "run_manifest.json").exists()
    assert (run_root / "reports" / "report.html").exists()
    assert (run_root / "reports" / "report.pdf").exists()
    assert (run_root / "exports" / "tables.xlsx").exists()
    assert (run_root / "artifacts_index.json").exists()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator_e2e.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.orchestrator`.

- [x] **Step 3: Implement the workflow orchestrator and CLI**

```python
# backend/workbench/orchestrator.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import write_json
from .cleaning import clean_frame
from .config import load_config
from .econometrics.runner import run_ols
from .exports import export_pdf, export_xlsx
from .ingestion import ingest_files
from .metadata import infer_schema
from .narrative import build_claims
from .profiling import profile_frame
from .projects import create_run
from .reporting import render_html_report
from .router import classify_dataset
from .domain import Severity
from .validation import validate_profile
from .visualization import create_figures


def run_workflow(project_root: Path, input_files: list[Path], mode: str, y: str, x: list[str]) -> dict[str, Any]:
    config = load_config(project_root / "config.yml")
    run = create_run(project_root, mode)
    frames = ingest_files(input_files, run.root, config)
    schema = infer_schema("dataset_1", frames, run.root)
    frame = next(iter(frames.values()))
    cleaned, actions = clean_frame(frame, schema.time_candidates)
    write_json(run.root / "processed" / "cleaning_actions.json", actions)
    cleaned_path = run.root / "processed" / "cleaned_dataset.parquet"
    cleaned.to_parquet(cleaned_path)
    profile = profile_frame(cleaned)
    write_json(run.root / "staged" / "data_profile.json", profile)
    issues = validate_profile(profile, config)
    write_json(run.root / "errors.json", {"issues": [issue.to_dict() for issue in issues]})
    if any(issue.severity == Severity.BLOCKER for issue in issues):
        write_json(run.root / "run_manifest.json", {"run_id": run.run_id, "mode": mode, "status": "blocked", "lineage": [str(path) for path in input_files]})
        return {"run_id": run.run_id, "status": "blocked"}
    structure = classify_dataset(cleaned, [c.lower() for c in schema.id_candidates], [c.lower() for c in schema.time_candidates])
    write_json(run.root / "staged" / "analysis_router.json", structure)
    model_result = run_ols(cleaned, y=y, x=x, robust=True, model_id="regression_1")
    write_json(run.root / "model_results" / "regression_1.json", model_result)
    numeric_columns = [column for column in cleaned.columns if str(cleaned[column].dtype).startswith(("int", "float"))]
    create_figures(cleaned, run.root, numeric_columns, time_column=None)
    warnings = [issue.message for issue in issues]
    claims = build_claims([model_result], warnings)
    report = {"title": "Econometrics Workbench Report", "facts": [f"Rows: {len(cleaned)}", f"Dataset structure: {structure['kind']}"], "claims": claims, "warnings": warnings}
    render_html_report(report, run.root)
    export_pdf(report, run.root)
    export_xlsx({"coefficients": [{"term": term, **stats} for term, stats in model_result["coefficients"].items()]}, run.root)
    write_json(run.root / "run_manifest.json", {"run_id": run.run_id, "mode": mode, "status": "completed", "lineage": [str(path) for path in input_files]})
    return {"run_id": run.run_id, "status": "completed"}
```

```python
# backend/workbench/cli.py
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .orchestrator import run_workflow
from .projects import create_project

app = typer.Typer()


@app.command()
def create(parent: Annotated[Path, typer.Argument()], name: Annotated[str, typer.Argument()]) -> None:
    project = create_project(parent, name)
    typer.echo(str(project.root))


@app.command()
def run(project_root: Annotated[Path, typer.Argument()], data_file: Annotated[Path, typer.Argument()], y: str, x: list[str], mode: str = "auto") -> None:
    result = run_workflow(project_root, [data_file], mode=mode, y=y, x=x)
    typer.echo(result["run_id"])
```

- [x] **Step 4: Run the integration test to verify it passes**

Run: `pytest tests/test_orchestrator_e2e.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/workbench/orchestrator.py backend/workbench/cli.py tests/test_orchestrator_e2e.py
git commit -m "feat: add workflow orchestrator"
```

## Task 11: Local FastAPI API and React UI

**Files:**
- Create: `backend/workbench/api.py`
- Create: `tests/test_api.py`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/src/styles.css`

- [x] **Step 1: Write the failing API test**

```python
# tests/test_api.py
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app


def test_api_creates_project_and_runs_upload(tmp_path: Path):
    client = TestClient(app)
    response = client.post("/projects", json={"parent": str(tmp_path), "name": "demo"})
    assert response.status_code == 200
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    assert run_response.status_code == 200
    assert run_response.json()["status"] == "completed"
```

- [x] **Step 2: Run the API test to verify it fails**

Run: `pytest tests/test_api.py -v`

Expected: FAIL with `ModuleNotFoundError` for `workbench.api`.

- [x] **Step 3: Implement the FastAPI API**

```python
# backend/workbench/api.py
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

from .orchestrator import run_workflow
from .projects import create_project

app = FastAPI(title="Local Econometrics Workbench")


class ProjectRequest(BaseModel):
    parent: str
    name: str


@app.post("/projects")
def create_project_endpoint(request: ProjectRequest) -> dict[str, str]:
    project = create_project(Path(request.parent), request.name)
    return {"project_root": str(project.root)}


@app.post("/runs")
async def run_endpoint(project_root: str = Form(...), mode: str = Form("auto"), y: str = Form(...), x: str = Form(...), file: UploadFile = File(...)) -> dict[str, str]:
    temp_dir = Path(tempfile.mkdtemp(prefix="workbench_upload_"))
    target = temp_dir / file.filename
    target.write_bytes(await file.read())
    result = run_workflow(Path(project_root), [target], mode=mode, y=y, x=[part.strip() for part in x.split(",") if part.strip()])
    return {"run_id": result["run_id"], "status": result["status"]}
```

- [x] **Step 4: Add the React UI files**

```json
// frontend/package.json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "test": "vitest run"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/react": "^15.0.0",
    "@testing-library/jest-dom": "^6.4.0",
    "typescript": "^5.5.0",
    "vitest": "^2.0.0",
    "jsdom": "^24.1.0"
  }
}
```

```ts
// frontend/src/api.ts
export async function createProject(parent: string, name: string) {
  const response = await fetch("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent, name })
  });
  return response.json();
}

export async function runWorkflow(projectRoot: string, mode: string, y: string, x: string, file: File) {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("y", y);
  form.append("x", x);
  form.append("file", file);
  const response = await fetch("/runs", { method: "POST", body: form });
  return response.json();
}
```

```tsx
// frontend/src/App.tsx
import { useState } from "react";
import { createProject, runWorkflow } from "./api";
import "./styles.css";

export default function App() {
  const [parent, setParent] = useState("");
  const [name, setName] = useState("demo");
  const [projectRoot, setProjectRoot] = useState("");
  const [mode, setMode] = useState("auto");
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState("");

  async function onCreateProject() {
    const result = await createProject(parent, name);
    setProjectRoot(result.project_root);
  }

  async function onRun() {
    if (!file) return;
    const result = await runWorkflow(projectRoot, mode, y, x, file);
    setStatus(`${result.status}: ${result.run_id}`);
  }

  return (
    <main>
      <h1>Local Econometrics Workbench</h1>
      <section>
        <input aria-label="parent folder" value={parent} onChange={(event) => setParent(event.target.value)} />
        <input aria-label="project name" value={name} onChange={(event) => setName(event.target.value)} />
        <button onClick={onCreateProject}>Create project</button>
      </section>
      <section>
        <select aria-label="run mode" value={mode} onChange={(event) => setMode(event.target.value)}>
          <option value="auto">Auto</option>
          <option value="stepped">Stepped</option>
        </select>
        <input aria-label="dependent variable" value={y} onChange={(event) => setY(event.target.value)} />
        <input aria-label="independent variables" value={x} onChange={(event) => setX(event.target.value)} />
        <input aria-label="data file" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <button disabled={!projectRoot || !file} onClick={onRun}>Run workflow</button>
      </section>
      <p>{projectRoot}</p>
      <p>{status}</p>
    </main>
  );
}
```

```tsx
// frontend/src/App.test.tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders workbench controls", () => {
  render(<App />);
  expect(screen.getByText("Local Econometrics Workbench")).toBeTruthy();
  expect(screen.getByLabelText("run mode")).toBeTruthy();
});
```

```ts
// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/projects": "http://127.0.0.1:8000",
      "/runs": "http://127.0.0.1:8000"
    }
  },
  test: {
    environment: "jsdom"
  }
});
```

```css
/* frontend/src/styles.css */
body { margin: 0; font-family: system-ui, sans-serif; background: #f7f8fa; color: #17202a; }
main { max-width: 960px; margin: 32px auto; padding: 0 20px; }
section { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
input, select, button { font: inherit; padding: 8px 10px; border: 1px solid #c8ced8; border-radius: 6px; }
button { background: #1f6feb; color: white; border-color: #1f6feb; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [x] **Step 5: Run API and frontend tests**

Run: `pytest tests/test_api.py -v`

Expected: PASS.

Run: `cd frontend && npm install && npm test`

Expected: PASS with the `renders workbench controls` test.

- [x] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_api.py frontend
git commit -m "feat: add local api ui"
```

## Task 12: Template Datasets and Acceptance Tests

**Files:**
- Create: `examples/datasets/cross_section.csv`
- Create: `examples/datasets/time_series.csv`
- Create: `examples/datasets/panel.csv`
- Create: `tests/test_acceptance_templates.py`
- Modify: `README.md`

- [x] **Step 1: Write the failing acceptance tests**

```python
# tests/test_acceptance_templates.py
from pathlib import Path

from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_cross_section_template_runs(tmp_path: Path):
    project = create_project(tmp_path, "cross_section_demo")
    result = run_workflow(project.root, [Path("examples/datasets/cross_section.csv")], mode="auto", y="wage", x=["education"])
    assert result["status"] == "completed"


def test_panel_template_runs(tmp_path: Path):
    project = create_project(tmp_path, "panel_demo")
    result = run_workflow(project.root, [Path("examples/datasets/panel.csv")], mode="auto", y="sales", x=["assets"])
    assert result["status"] == "completed"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_acceptance_templates.py -v`

Expected: FAIL because `examples/datasets/cross_section.csv` does not exist.

- [x] **Step 3: Add template datasets**

```csv
wage,education,experience,region
20,12,2,East
21,12,3,East
22,13,3,West
23,13,4,West
24,14,4,South
25,14,5,South
26,15,5,East
27,15,6,East
28,16,6,West
29,16,7,West
30,17,7,South
31,17,8,South
32,18,8,East
33,18,9,East
34,19,9,West
35,19,10,West
36,20,10,South
37,20,11,South
38,21,11,East
39,21,12,East
40,22,12,West
41,22,13,West
42,23,13,South
43,23,14,South
44,24,14,East
45,24,15,East
46,25,15,West
47,25,16,West
48,26,16,South
49,26,17,South
```

```csv
date,gdp,interest_rate
2020-01-01,100,1.5
2020-02-01,101,1.5
2020-03-01,99,1.2
2020-04-01,102,1.1
2020-05-01,104,1.0
2020-06-01,105,1.0
2020-07-01,106,0.9
2020-08-01,107,0.9
2020-09-01,108,0.8
2020-10-01,109,0.8
2020-11-01,111,0.7
2020-12-01,112,0.7
2021-01-01,113,0.7
2021-02-01,114,0.8
2021-03-01,116,0.8
2021-04-01,117,0.9
2021-05-01,118,0.9
2021-06-01,120,1.0
2021-07-01,121,1.0
2021-08-01,123,1.1
2021-09-01,124,1.1
2021-10-01,126,1.2
2021-11-01,127,1.2
2021-12-01,129,1.3
2022-01-01,130,1.3
2022-02-01,132,1.4
2022-03-01,133,1.4
2022-04-01,135,1.5
2022-05-01,136,1.5
2022-06-01,138,1.6
```

```csv
firm_id,year,sales,assets
1,2020,10,20
1,2021,12,22
2,2020,8,18
2,2021,11,19
3,2020,14,30
3,2021,16,33
4,2020,9,17
4,2021,10,18
5,2020,18,35
5,2021,20,38
6,2020,21,40
6,2021,24,44
7,2020,15,28
7,2021,17,31
8,2020,12,24
8,2021,13,26
9,2020,19,37
9,2021,22,41
10,2020,25,50
10,2021,27,54
11,2020,16,32
11,2021,18,34
12,2020,13,25
12,2021,15,29
13,2020,28,55
13,2021,31,60
14,2020,23,46
14,2021,26,49
15,2020,30,62
15,2021,34,68
```

- [x] **Step 4: Add user-facing README**

````markdown
# Local Econometrics Workbench

Run the backend tests:

```bash
pytest
```

Create a project and run a sample dataset:

```bash
workbench create /tmp workbench-demo
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv --y wage --x education
```

Start the local API:

```bash
uvicorn workbench.api:app --reload
```

Start the local UI:

```bash
cd frontend
npm install
npm run dev
```

The V1 workflow writes outputs into `project/runs/{run_id}/`, including `run_manifest.json`, `environment.json`, `decisions.json`, `errors.json`, `artifacts_index.json`, reports, figures, tables, and processed data.
````

- [x] **Step 5: Run full verification**

Run: `pytest -v`

Expected: PASS.

Run: `cd frontend && npm test`

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add README.md examples/datasets tests/test_acceptance_templates.py
git commit -m "test: add template dataset acceptance"
```

## Self-Review

Spec coverage:

- V1 data scale limits are covered by Task 1 config and Task 3 ingestion checks.
- Project/run directories, immutable run outputs, artifact index, lineage, and environment snapshots are covered by Task 2 and Task 10.
- Metadata Registry is covered by Task 3.
- Profiling, Validation & Guardrails, and error severity are covered by Task 4.
- Merge advice and cleaning action logs are covered by Task 5.
- Dataset structure recognition for cross-section, time series, panel, repeated cross-section, and unknown/mixed is covered by Task 6.
- Basic econometrics are covered by Task 7.
- Figures are covered by Task 8.
- Fact/interpretation/warning report layers and source-bound narrative claims are covered by Task 9.
- HTML/PDF/XLSX exports are covered by Task 9.
- End-to-end local workflow and traceable artifacts are covered by Task 10.
- Local API/UI is covered by Task 11.
- Template onboarding datasets and acceptance tests are covered by Task 12.

No V1 core requirement from the approved spec is intentionally omitted. Word, Notebook, LaTeX, advanced causality, cloud collaboration, and API platformization are outside this V1 core plan by the approved product boundary.

Completion marker scan:

- No unresolved markers were found.
- Every task includes concrete test code, commands, expected outcomes, implementation code, and a commit command.

Type consistency:

- `ArtifactRecord`, `GuardrailIssue`, `DatasetSchema`, `WorkbenchConfig`, and `DatasetKind` names are introduced before use.
- `run_manifest.json`, `environment.json`, `decisions.json`, `errors.json`, and `artifacts_index.json` filenames match the approved spec and later tasks.
- `source_id` is used consistently for narrative/report claim binding.
