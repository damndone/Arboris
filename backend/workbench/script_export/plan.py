"""The script-export contract (v1.8.11 step 7): what goes in, what comes out.

A ``ScriptPlan`` is an analysis path read off the lineage: the source files and
the ordered steps exactly as Workbench executed them, each with the numbers it
produced. The integration side builds it from the graph and the run inputs;
the renderers turn it into a Stata do-file, an R script or a Python script and
never read the graph themselves.

Every step is exported one of three ways, listed in a coverage table at the
top of the script: natively; natively with an equivalence note (the target
software computes it differently but within the stated tolerance); or not
natively, in which case the script loads the data snapshot taken after the
step, checks its SHA-256 and carries on, saying the step was done in
Workbench. Nothing is silently dropped or approximated: the script ends with
assertions on the numbers in ``expected`` and fails when the target software
does not reproduce them.

This module is frozen at the v1.8.11 contract lock. Renderers may add modules
next to it, never change it; a change goes through the integration owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json

SCRIPT_PLAN_SCHEMA_VERSION = 1

Language = Literal["stata", "r", "python"]
LANGUAGES: tuple[Language, ...] = ("stata", "r", "python")

SourceFormat = Literal["csv", "dta", "sav", "xlsx", "parquet"]
SOURCE_FORMATS: tuple[SourceFormat, ...] = ("csv", "dta", "sav", "xlsx", "parquet")

StepKind = Literal["data_operation", "model", "postestimation"]
STEP_KINDS: tuple[StepKind, ...] = ("data_operation", "model", "postestimation")

CoverageStatus = Literal["native", "native_with_equivalence_note", "snapshot"]
COVERAGE_STATUSES: tuple[CoverageStatus, ...] = ("native", "native_with_equivalence_note", "snapshot")

SnapshotFormat = Literal["csv", "parquet", "dta"]


@dataclass(frozen=True)
class ScriptSource:
    """One input file. Scripts refer to it by ``filename`` next to the script."""

    source_id: str
    format: SourceFormat
    filename: str
    sha256: str
    # Reader options as Workbench applied them, e.g. sheet_name, transpose,
    # delimiter, encoding. Keys are the form keys of the run inputs.
    read_options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.format not in SOURCE_FORMATS:
            raise ContractError(f"unsupported source format: {self.format}")
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ContractError("source filename must be a bare file name")
        _require_sha256(self.sha256, "source sha256")
        object.__setattr__(self, "read_options", freeze_json(self.read_options, "source.read_options"))


@dataclass(frozen=True)
class ScriptSnapshot:
    """The data after a step, written by the integration side, local only."""

    filename: str
    format: SnapshotFormat
    sha256: str
    nrows: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.filename or "/" in self.filename or "\\" in self.filename:
            raise ContractError("snapshot filename must be a bare file name")
        _require_sha256(self.sha256, "snapshot sha256")
        object.__setattr__(self, "columns", tuple(self.columns))


@dataclass(frozen=True)
class ScriptStep:
    """One executed step.

    ``operation`` is the workflow operation id: ``data.<operation>`` for a
    declared data operation (``data_operation_registry``), ``model.<model_type>``
    for a model family (``glm`` carries its family in ``parameters``), and
    ``postestimation.<operation>`` (wald, lincom, nlcom, lr, margins).

    ``parameters`` are the validated parameters exactly as executed. For a
    model step they are normalized to: model_type, y, x (list), categorical_x
    (list), covariance, cluster (column or null), hac_lags, weights (object or
    null), entity, time, model_options (object). For a post-estimation step:
    the operation's spec plus ``models`` (list of model step ids, in order).

    ``expected`` holds the numbers the script must reproduce, keyed by kind:
    ``nobs``; ``coefficients`` and ``std_errors`` ({term: value}); ``statistics``
    ({name: {value, df, df_denominator, p_value, distribution}}); for data
    steps ``nrows`` and ``columns``. ``tolerances`` overrides the defaults
    ({kind: {"abs": x, "rel": y}}).
    """

    step_id: str
    kind: StepKind
    operation: str
    parameters: Mapping[str, Any]
    inputs: tuple[str, ...]
    output_dataset: str | None = None
    expected: Mapping[str, Any] = field(default_factory=dict)
    tolerances: Mapping[str, Any] = field(default_factory=dict)
    seed: int | None = None
    snapshot: ScriptSnapshot | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ContractError(f"unsupported step kind: {self.kind}")
        prefix = {"data_operation": "data.", "model": "model.", "postestimation": "postestimation."}[self.kind]
        if not self.operation.startswith(prefix):
            raise ContractError(f"{self.kind} step operation must start with {prefix!r}")
        if not self.step_id:
            raise ContractError("step_id must be non-empty")
        object.__setattr__(self, "inputs", tuple(self.inputs))
        for name in ("parameters", "expected", "tolerances"):
            object.__setattr__(self, name, freeze_json(getattr(self, name), f"step.{name}"))


@dataclass(frozen=True)
class ScriptPlan:
    project_id: str
    run_id: str
    sources: tuple[ScriptSource, ...]
    steps: tuple[ScriptStep, ...]
    workbench_version: str
    lineage_hash: str
    schema_version: int = SCRIPT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCRIPT_PLAN_SCHEMA_VERSION:
            raise ContractError(f"unsupported script plan schema version: {self.schema_version}")
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "steps", tuple(self.steps))
        known = {source.source_id for source in self.sources}
        for step in self.steps:
            if step.step_id in known:
                raise ContractError(f"duplicate step or source id: {step.step_id}")
            missing = [ref for ref in step.inputs if ref not in known]
            if missing:
                raise ContractError(f"step {step.step_id} refers to unknown inputs: {', '.join(missing)}")
            known.add(step.step_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "workbench_version": self.workbench_version,
            "lineage_hash": self.lineage_hash,
            "sources": [
                {
                    "source_id": s.source_id, "format": s.format, "filename": s.filename,
                    "sha256": s.sha256, "read_options": thaw_json(s.read_options),
                }
                for s in self.sources
            ],
            "steps": [_step_dict(step) for step in self.steps],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScriptPlan":
        return cls(
            schema_version=value["schema_version"],
            project_id=value["project_id"],
            run_id=value["run_id"],
            workbench_version=value["workbench_version"],
            lineage_hash=value["lineage_hash"],
            sources=tuple(ScriptSource(**source) for source in value["sources"]),
            steps=tuple(_step_from_dict(step) for step in value["steps"]),
        )


@dataclass(frozen=True)
class CoverageEntry:
    step_id: str
    operation: str
    status: CoverageStatus
    # Why: the equivalence note, or the reason the step is not exported natively.
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in COVERAGE_STATUSES:
            raise ContractError(f"unsupported coverage status: {self.status}")
        if self.status != "native" and not self.note:
            raise ContractError(f"coverage status {self.status} requires a note")


@dataclass(frozen=True)
class ScriptExport:
    language: Language
    filename: str
    text: str
    coverage: tuple[CoverageEntry, ...]
    # Step ids whose snapshot the script loads; the files must sit next to it.
    snapshots_required: tuple[str, ...]
    required_packages: tuple[str, ...]

    @property
    def fully_native(self) -> bool:
        return all(entry.status != "snapshot" for entry in self.coverage)


class ScriptExportRefusal(ValueError):
    """An export that cannot be produced as asked, with the steps responsible."""

    def __init__(self, code: str, message: str, *, steps: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.steps = steps


# Default comparison tolerances for the closing self-check, per expected kind.
# A renderer may loosen one only for a native_with_equivalence_note step, and
# says so in that step's note.
DEFAULT_TOLERANCES: Mapping[str, Mapping[str, float]] = {
    "coefficients": {"abs": 1e-8, "rel": 1e-6},
    "std_errors": {"abs": 1e-8, "rel": 1e-5},
    "statistics.value": {"abs": 1e-8, "rel": 1e-5},
    "statistics.p_value": {"abs": 1e-6, "rel": 0.0},
    "nobs": {"abs": 0.0, "rel": 0.0},
    "nrows": {"abs": 0.0, "rel": 0.0},
}


def _require_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ContractError(f"{name} must be 64 lowercase hex characters")


def _step_dict(step: ScriptStep) -> dict[str, Any]:
    snapshot = step.snapshot
    return {
        "step_id": step.step_id,
        "kind": step.kind,
        "operation": step.operation,
        "label": step.label,
        "parameters": thaw_json(step.parameters),
        "inputs": list(step.inputs),
        "output_dataset": step.output_dataset,
        "expected": thaw_json(step.expected),
        "tolerances": thaw_json(step.tolerances),
        "seed": step.seed,
        "snapshot": None if snapshot is None else {
            "filename": snapshot.filename, "format": snapshot.format, "sha256": snapshot.sha256,
            "nrows": snapshot.nrows, "columns": list(snapshot.columns),
        },
    }


def _step_from_dict(value: Mapping[str, Any]) -> ScriptStep:
    snapshot = value.get("snapshot")
    return ScriptStep(
        step_id=value["step_id"],
        kind=value["kind"],
        operation=value["operation"],
        label=value.get("label", ""),
        parameters=value["parameters"],
        inputs=tuple(value["inputs"]),
        output_dataset=value.get("output_dataset"),
        expected=value.get("expected", {}),
        tolerances=value.get("tolerances", {}),
        seed=value.get("seed"),
        snapshot=None if snapshot is None else ScriptSnapshot(
            filename=snapshot["filename"], format=snapshot["format"], sha256=snapshot["sha256"],
            nrows=snapshot["nrows"], columns=tuple(snapshot["columns"]),
        ),
    )


__all__ = [
    "COVERAGE_STATUSES",
    "CoverageEntry",
    "DEFAULT_TOLERANCES",
    "LANGUAGES",
    "SCRIPT_PLAN_SCHEMA_VERSION",
    "ScriptExport",
    "ScriptExportRefusal",
    "ScriptPlan",
    "ScriptSnapshot",
    "ScriptSource",
    "ScriptStep",
]
