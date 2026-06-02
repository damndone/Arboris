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
from .pre_estimation_checks import PreEstimationChecksStage
from .roles import RoleInferenceStage
from .exposure import ExposureDetectionStage
from .imputation import ImputationStage
from .estimation import EstimationStage
from .recording import RecordingStage
from .diagnostics import DiagnosticsStage
from .reliability import ReliabilityStage
from .report import ReportStage

# Stages are appended in pipeline order as each is extracted.
PIPELINE: list[Stage] = [
    SourceStage(),
    CleaningStage(),
    ProfileStage(),
    ValidationStage(),
    RoutingStage(),
    YTypeStage(),
    PreEstimationChecksStage(),
    RoleInferenceStage(),
    ExposureDetectionStage(),
    ImputationStage(),
    EstimationStage(),
    RecordingStage(),
    DiagnosticsStage(),
    ReliabilityStage(),
    ReportStage(),
]
