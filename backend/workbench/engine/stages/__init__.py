from __future__ import annotations
from typing import Protocol
from ..context import ModelingContext, RunEnv

class Stage(Protocol):
    name: str
    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext: ...

from .source import SourceStage
from .cleaning import CleaningStage
from .profile import ProfileStage
from .validation import ValidationStage
from .routing import RoutingStage
from .ytype import YTypeStage

# Stages are appended in pipeline order as each is extracted.
PIPELINE: list[Stage] = [
    SourceStage(),
    CleaningStage(),
    ProfileStage(),
    ValidationStage(),
    RoutingStage(),
    YTypeStage(),
]
