"""Typed, source-bound statistical exploration contracts.

The code lives in the statistical_exploration_* modules; this module keeps the import path.
"""

from __future__ import annotations

from .statistical_exploration_spec import (  # noqa: F401
    ExplorationOperation,
    ExplorationSpec,
    FilterOperator,
    FilterSpec,
    GROUPABLE_OPERATIONS,
    SCHEMA_VERSION,
    STATA_QUANTILE_METHOD,
    StatisticalExplorationValidationError,
    _FILTER_SPELLINGS,
    _canonical_value,
    canonical_spec_json,
    exploration_fingerprint,
)
from .statistical_exploration_compute import (  # noqa: F401
    MAX_TABULATE_VALUES,
    _apply_filters,
    _correlation_result,
    _derived_boolean_result,
    _derived_boolean_series,
    _derived_definition,
    _detail_variables,
    _frequency_tables,
    _numeric_columns,
    _quantile_method,
    _require_column,
    _safe_number,
    _scatter_columns,
    _selected_columns,
    _split_numeric,
    _stata_moments,
    _stata_percentile,
    _summarize_groups,
    _summary_variables,
    _validate_filter_value,
    _validate_frame,
    execute_exploration,
)
from .statistical_exploration_persist import (  # noqa: F401
    _artifact_is_registered,
    _correlation_table_rows,
    _ensure_exploration_artifact,
    _exploration_descriptive_rows,
    _exploration_report,
    _exploration_tables,
    _persist_derived_boolean,
    _persist_exploration_exports,
    _persist_statistical_scatter,
    _result_table_rows,
    _table_cell,
    persist_exploration,
    resolve_statistical_source,
)

__all__ = [
    "SCHEMA_VERSION",
    "STATA_QUANTILE_METHOD",
    "ExplorationSpec",
    "FilterSpec",
    "StatisticalExplorationValidationError",
    "canonical_spec_json",
    "execute_exploration",
    "exploration_fingerprint",
]
