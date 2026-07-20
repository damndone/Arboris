from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class DataHandle:
    """A dataframe bound to its provenance identity. Models, diagnostics,
    reports and lineage must all read frame AND artifact_id from the same
    handle — making 'fit on A, record B' impossible by construction."""

    frame: pd.DataFrame
    artifact_id: str
    provenance: tuple[str, ...]
    schema_fingerprint: str | None = None
    row_count: int | None = None
    column_count: int | None = None

    @classmethod
    def of(cls, frame: pd.DataFrame, *, artifact_id: str, provenance: tuple[str, ...]) -> "DataHandle":
        return cls(
            frame=frame,
            artifact_id=artifact_id,
            provenance=tuple(provenance),
            row_count=len(frame),
            column_count=len(frame.columns),
        )


@dataclass
class ModelingContext:
    """Cross-stage state, previously loose locals in _run_workflow."""

    data: DataHandle
    y_col: str
    x_cols: list[str]
    requested_model_type: str | None = None   # 1.5.3.2 explicit routing
    y_type: str | None = None
    primary_type: str | None = None
    exposure_col: str | None = None
    roles: dict[str, Any] | None = None
    diagnostics: list[Any] | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    terminal_status: str | None = None  # short-circuit signal (blocked/failed)

    def with_data(self, handle: DataHandle) -> "ModelingContext":
        return replace(self, data=handle)


class RunInterruptionRequested(RuntimeError):
    """Cooperative cancellation/timeout signal for a background run."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class RunEnv:
    """Side-effecting dependencies, kept OUT of ModelingContext so the
    context stays pure-constructible in unit tests."""

    run_root: Path
    run_id: str
    recorder: Any
    on_step: Callable[[str, str, str], None] | None = None
    stop_reason: Callable[[], str | None] | None = None
    lmm_execution_admission: object | None = None

    def checkpoint(self, message: str = "") -> None:
        if self.stop_reason is not None:
            reason = self.stop_reason()
            if reason:
                raise RunInterruptionRequested(reason)

    def step(self, name: str, state: str, message: str) -> None:
        self.checkpoint(message)
        if self.on_step:
            self.on_step(name, state, message)

    def progress(self, name: str, message: str) -> None:
        """Emit a durable heartbeat without changing stage terminal semantics."""

        self.checkpoint(message)
        if self.on_step:
            self.on_step(name, "progress", message)
