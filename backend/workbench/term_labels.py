"""Readable display labels for model coefficient terms.

Estimators name terms by their design encoding: ``C(Q('region'))[T.2]`` for a
treatment-coded level, ``experience_pow2`` for a declared polynomial,
``region_north`` for a materialized dummy, ``a:b`` for an interaction. Tables and
the Agent show the user's own variable and value labels instead. The raw term
stays the identifier everywhere; only the display text changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .formula_terms import categorical_level, unquote_column

_POWER = re.compile(r"^(?P<col>.+)_pow(?P<degree>[2-9])$")
_PATSY_POWER = re.compile(r"^I\((?P<col>[^*()]+?)\s*\*\*\s*(?P<degree>[2-9])\)$")
_SUPERSCRIPT = {"2": "²", "3": "³"}


def _level_keys(level: str) -> list[str]:
    keys = [level]
    try:
        number = float(level)
    except ValueError:
        return keys
    if number.is_integer():
        keys.append(str(int(number)))
    return keys


class TermLabeler:
    def __init__(
        self,
        *,
        variable_labels: Mapping[str, object] | None = None,
        value_labels: Mapping[str, object] | None = None,
        columns: Iterable[str] = (),
    ) -> None:
        self.variable_labels = {
            str(key): str(value)
            for key, value in (variable_labels or {}).items()
            if isinstance(value, str) and value
        }
        self.value_labels = {
            str(column): {str(key): str(label) for key, label in mapping.items()}
            for column, mapping in (value_labels or {}).items()
            if isinstance(mapping, Mapping)
        }
        known = set(columns) | set(self.variable_labels) | set(self.value_labels)
        # Longest first, so `region_code_north` resolves to `region_code`.
        self._columns = sorted(known, key=len, reverse=True)

    def variable(self, column: str) -> str:
        return self.variable_labels.get(column, column)

    def value(self, column: str, level: str) -> str:
        mapping = self.value_labels.get(column, {})
        for key in _level_keys(level):
            if key in mapping:
                return mapping[key]
        return level

    def _level_term(self, column: str, level: str) -> str:
        return f"{self.variable(column)}: {self.value(column, level)}"

    def label(self, term: str) -> str:
        term = str(term)
        categorical = categorical_level(term)
        column = unquote_column(term)
        if ":" in term and categorical is None and column is None:
            parts = term.split(":")
            if all(parts):
                return " × ".join(self.label(part) for part in parts)
        if categorical is not None:
            return self._level_term(*categorical)
        if column is not None:
            return self.variable(column)
        match = _POWER.match(term) or _PATSY_POWER.match(term)
        if match:
            column = match.group("col").strip()
            degree = match.group("degree")
            return self.variable(column) + _SUPERSCRIPT.get(degree, f"^{degree}")
        if term in self.variable_labels:
            return self.variable_labels[term]
        for column in self._columns:
            prefix = f"{column}_"
            if term.startswith(prefix) and column in self.value_labels:
                return self._level_term(column, term[len(prefix):])
        return term


def term_display_label(
    term: str,
    *,
    variable_labels: Mapping[str, object] | None = None,
    value_labels: Mapping[str, object] | None = None,
    columns: Iterable[str] = (),
) -> str:
    return TermLabeler(
        variable_labels=variable_labels, value_labels=value_labels, columns=columns
    ).label(term)
