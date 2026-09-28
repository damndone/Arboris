"""One declaration per data operation, read by every surface that offers it.

A data operation used to be written out separately for the executor, the HTTP
route's operation list, the Agent's workflow step schema, its column
extractor, its output-column projection and its pre-execution validator, so a
new operation reached the UI but not the Agent. A declaration here is the only
thing a new operation needs: the executor dispatches to ``execute``, the route
admits it, and the Agent's workflow vocabulary, validation and compile checks
are derived from it -- including a worked ``example`` the Agent is shown.

Every data operation is declared here, including the ones that predate the
registry (their declarations live in ``data_operation_catalog``).

``describe`` renders a spec as one line a person can check at a glance --
"Keep rows where age is between 25 and 55" -- with variable labels when the
data declares them. Proposal cards and the Agent's closing reply use it; the
raw parameters stay one click away.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

ColumnsOf = Callable[[Mapping[str, Any]], set[str]]
OutputColumns = Callable[[Mapping[str, Any], set[str]], set[str]]
Validate = Callable[[Mapping[str, Any]], None]
# execute(frame, spec) -- or execute(frame, spec, secondary) when the
# declaration takes a second dataset (merge, append).
Execute = Callable[..., pd.DataFrame]
Describe = Callable[[Mapping[str, Any], "Labels"], str]
Labels = Mapping[str, str]


@dataclass(frozen=True)
class DataOperationDeclaration:
    operation: str
    summary: str
    fields: Mapping[str, str]
    required: tuple[str, ...]
    field_types: Mapping[str, str]
    field_schemas: Mapping[str, Mapping[str, Any]]
    referenced_columns: ColumnsOf
    output_columns: OutputColumns
    validate: Validate
    execute: Execute
    # A complete, valid parameter object, shown to the Agent and executed by
    # the registry's contract test against ``example_frame``.
    example: Mapping[str, Any]
    example_frame: Callable[[], pd.DataFrame]
    field_enums: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    natural_language_enabled: bool = True
    describe: Describe | None = None
    # Two-input operations receive the secondary dataset as a third argument;
    # their example is executed against ``example_secondary_frame``.
    secondary_input: bool = False
    example_secondary_frame: Callable[[], pd.DataFrame] | None = None
    # Spec fields that bind an input dataset (the secondary run, node and
    # artifact) rather than parameterize the operation; the executor never
    # sees them.
    binding_fields: tuple[str, ...] = ()

    def parameters_of(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in spec.items() if key not in self.binding_fields}

    def run(self, frame: pd.DataFrame, spec: Mapping[str, Any], secondary: pd.DataFrame | None = None) -> pd.DataFrame:
        parameters = self.parameters_of(spec)
        if self.secondary_input:
            return self.execute(frame, parameters, secondary)
        return self.execute(frame, parameters)

    def sentence(self, spec: Mapping[str, Any], labels: Labels | None = None) -> str:
        """One readable line for this spec; falls back to the summary."""

        if self.describe is None:
            return self.summary.split(". ")[0].rstrip(".")
        try:
            return self.describe(spec, labels or {})
        except (KeyError, TypeError, ValueError, AttributeError):
            return self.summary.split(". ")[0].rstrip(".")

    @property
    def workflow_operation_id(self) -> str:
        return f"data.{self.operation}"


_REGISTRY: dict[str, DataOperationDeclaration] = {}


def register_data_operation(declaration: DataOperationDeclaration) -> None:
    existing = _REGISTRY.get(declaration.operation)
    if existing is not None and existing is not declaration:
        raise ValueError(f"data operation already declared: {declaration.operation}")
    _REGISTRY[declaration.operation] = declaration


def _ensure_loaded() -> None:
    # Declarations live beside their executors; importing the modules
    # registers them. Imported lazily so this module stays free of cycles.
    from . import data_operation_catalog, data_operations  # noqa: F401


def get_data_operation(operation: str) -> DataOperationDeclaration | None:
    _ensure_loaded()
    return _REGISTRY.get(operation.removeprefix("data."))


def data_operation_declarations() -> tuple[DataOperationDeclaration, ...]:
    _ensure_loaded()
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))
