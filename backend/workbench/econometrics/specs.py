from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    model_type: str
    y: str
    x: tuple[str, ...]
    entity: str | None = None
    time: str | None = None
    robust: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", tuple(self.x))
