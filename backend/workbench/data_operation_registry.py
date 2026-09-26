"""One declaration per data operation, read by every surface that offers it.

A data operation used to be written out separately for the executor, the HTTP
route's operation list, the Agent's workflow step schema, its column
extractor, its output-column projection and its pre-execution validator, so a
new operation reached the UI but not the Agent. A declaration here is the only
thing a new operation needs: the executor dispatches to ``execute``, the route
admits it, and the Agent's workflow vocabulary, validation and compile checks
are derived from it -- including a worked ``example`` the Agent is shown.

Operations that predate the registry keep their existing code paths; each
surface consults the registry first.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

ColumnsOf = Callable[[Mapping[str, Any]], set[str]]
OutputColumns = Callable[[Mapping[str, Any], set[str]], set[str]]
Validate = Callable[[Mapping[str, Any]], None]
Execute = Callable[[pd.DataFrame, Mapping[str, Any]], pd.DataFrame]


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
    # Declarations live beside their executors; importing the module registers
    # them. Imported lazily so this module stays free of import cycles.
    from . import data_operations  # noqa: F401


def get_data_operation(operation: str) -> DataOperationDeclaration | None:
    _ensure_loaded()
    return _REGISTRY.get(operation.removeprefix("data."))


def data_operation_declarations() -> tuple[DataOperationDeclaration, ...]:
    _ensure_loaded()
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))
