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
