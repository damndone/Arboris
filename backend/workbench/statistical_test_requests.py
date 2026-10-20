"""Native statistical request declarations consumed by manual and Agent paths.

The two execution modes deliberately retain their existing input semantics and
multiplicity scopes. This module binds requests; it computes no statistics.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class TestParameter:
    description: str
    field_type: str
    schema: Mapping[str, Any]
    column_role: str | None = None


DEFAULT_TEST_PARAMETERS = {
    "reference_means": TestParameter(
        "Optional column-to-population-mean declarations for the evidence family.",
        "object", {"type":"object"}, column_role="mapping_keys"),
    "paired_columns": TestParameter(
        "Optional list of explicit two-column before/after pairs for the evidence family.",
        "list", {"type":"array"}, column_role="pairs"),
}


@dataclass(frozen=True)
class StatisticalTestRequest:
    parameters: Mapping[str, TestParameter]

    @property
    def fields(self):
        return {
            "analysis_columns": (
                "Explicit source columns for this named statistical family; "
                "columns are never inferred or silently dropped."
            ),
            **{name: parameter.description for name, parameter in self.parameters.items()},
            "by_group": (
                "Optional grouping column: the test runs separately within each group "
                "(a missing value is a group of its own; at most 50 groups), and each "
                "test's p-values are also adjusted across groups (Holm and "
                "Benjamini-Hochberg). Groups side by side are not a test of a difference."
            ),
        }

    @property
    def field_types(self):
        return {
            "analysis_columns": "list",
            **{name: parameter.field_type for name, parameter in self.parameters.items()},
            "by_group": "string",
        }

    @property
    def field_schemas(self):
        # Existing fields keep their original semantic checks and error text.
        return {
            name: deepcopy(dict(parameter.schema)) for name, parameter in self.parameters.items()
            if name not in DEFAULT_TEST_PARAMETERS
        }

    @property
    def option_schemas(self):
        return {name: deepcopy(dict(parameter.schema)) for name, parameter in self.parameters.items()}

    def _validate_new_parameters(self, operation_id, values):
        for name, parameter in self.parameters.items():
            if name in DEFAULT_TEST_PARAMETERS or name not in values or values[name] is None:
                continue
            if not Draft202012Validator(parameter.schema).is_valid(values[name]):
                raise ValueError(f"{operation_id} {name} does not match its declared {parameter.field_type}")

    def validate_named_spec(self, operation_id, spec):
        by_group = spec.get("by_group")
        if by_group is not None:
            if not isinstance(by_group, str) or not by_group.strip():
                raise ValueError(f"{operation_id} by_group must name one column")
            if by_group in (spec.get("analysis_columns") or []):
                raise ValueError(
                    f"{operation_id} by_group cannot also be an analysis column"
                )
        analysis_columns = spec.get("analysis_columns")
        if not isinstance(analysis_columns, list) or not analysis_columns:
            raise ValueError(
                f"{operation_id} requires a non-empty analysis_columns list"
            )
        if any(not isinstance(column, str) or not column for column in analysis_columns):
            raise ValueError(
                f"{operation_id} analysis_columns must contain non-empty strings"
            )
        if len(set(analysis_columns)) != len(analysis_columns):
            raise ValueError(
                f"{operation_id} analysis_columns must not contain duplicates"
            )
        reference_means = spec.get("reference_means")
        if reference_means is not None:
            if not isinstance(reference_means, Mapping):
                raise ValueError(
                    f"{operation_id} reference_means must be an object"
                )
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in reference_means.values()
            ):
                raise ValueError(
                    f"{operation_id} reference_means values must be finite numbers"
                )
        paired_columns = spec.get("paired_columns")
        if paired_columns is not None:
            if not isinstance(paired_columns, list):
                raise ValueError(
                    f"{operation_id} paired_columns must be a list"
                )
            for pair in paired_columns:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(not isinstance(column, str) or not column for column in pair)
                    or pair[0] == pair[1]
                ):
                    raise ValueError(
                        f"{operation_id} paired_columns must contain distinct two-column lists"
                    )

        self._validate_new_parameters(operation_id, spec)

    def referenced_columns(self, spec):
        columns = {str(item) for item in spec.get("analysis_columns", []) or []}
        if isinstance(spec.get("by_group"), str) and spec["by_group"]:
            columns.add(spec["by_group"])
        for name, parameter in self.parameters.items():
            columns.update(self._parameter_columns(parameter, spec.get(name)))
        return columns

    @staticmethod
    def _parameter_columns(parameter, value):
        if parameter.column_role == "mapping_keys":
            return {str(column) for column in value or {}}
        if parameter.column_role == "pairs":
            return {
                str(column) for pair in value or []
                if isinstance(pair, (list, tuple)) for column in pair if column
            }
        if parameter.column_role == "column":
            return {value} if value else set()
        if parameter.column_role == "columns":
            return set(value or [])
        return set()

    def kernel_arguments(self, values, *, named):
        arguments = {
            name: values.get(name) for name in self.parameters
            if name in values or name in DEFAULT_TEST_PARAMETERS
        }
        if named:
            for name, parameter in self.parameters.items():
                if parameter.column_role == "pairs" and name in arguments:
                    arguments[name] = [tuple(pair) for pair in arguments[name] or []]
        return arguments

    def validate_options(self, operation_id, columns, options):
        reference_means = options.get("reference_means")
        if reference_means is not None:
            if not isinstance(reference_means, Mapping):
                raise ValueError(
                    f"{operation_id} reference_means must be an object mapping columns to finite numbers"
                )
            for column, value in reference_means.items():
                if type(column) is not str or not column or column not in columns:
                    raise ValueError(
                        f"{operation_id} reference_means columns must be present in the declared columns"
                    )
                if type(value) not in (int, float):
                    raise ValueError(
                        f"{operation_id} reference_means values must be finite numbers"
                    )
                try:
                    finite = math.isfinite(float(value))
                except (OverflowError, TypeError):
                    finite = False
                if not finite:
                    raise ValueError(
                        f"{operation_id} reference_means values must be finite numbers"
                    )

        paired_columns = options.get("paired_columns")
        if paired_columns is not None:
            if not isinstance(paired_columns, (list, tuple)):
                raise ValueError(
                    f"{operation_id} paired_columns must be a list of two-column pairs"
                )
            for pair in paired_columns:
                if (
                    not isinstance(pair, (list, tuple))
                    or len(pair) != 2
                    or any(type(column) is not str or not column for column in pair)
                ):
                    raise ValueError(
                        f"{operation_id} paired_columns entries must contain exactly two column names"
                    )
                left, right = pair
                if left == right or left not in columns or right not in columns:
                    raise ValueError(
                        f"{operation_id} paired_columns entries must name two distinct declared columns"
                    )

        self._validate_new_parameters(operation_id, options)
        for name, parameter in self.parameters.items():
            if name in DEFAULT_TEST_PARAMETERS:
                continue
            if self._parameter_columns(parameter, options.get(name)) - set(columns):
                raise ValueError(f"{operation_id} {name} must reference declared columns")
