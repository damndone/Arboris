"""Fail-closed extension registry for model-specific Analysis Loop packets."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


BuildPacket = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AnalysisLoopAdapter:
    model_type: str
    build_source_facts: BuildPacket
    build_validation: BuildPacket
    build_compare: BuildPacket


class AnalysisLoopAdapterRegistry:
    """Explicit model dispatch with no implicit fallback to an OLS adapter."""

    def __init__(self) -> None:
        self._items: dict[str, AnalysisLoopAdapter] = {}

    def register(self, adapter: AnalysisLoopAdapter) -> None:
        if adapter.model_type in self._items:
            raise ValueError(f"duplicate analysis-loop adapter: {adapter.model_type}")
        self._items[adapter.model_type] = adapter

    def resolve(self, model_type: str) -> AnalysisLoopAdapter:
        try:
            return self._items[model_type]
        except KeyError as exc:
            raise KeyError(
                f"no analysis-loop adapter for model type: {model_type}"
            ) from exc
