from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    y: str
    x: tuple[str, ...] = ()
    robust: bool = False
    entity: str | None = None
    time: str | None = None
