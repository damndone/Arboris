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
from .statistical_tests import StatisticalTestsStage
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
    StatisticalTestsStage(),
    ImputationStage(),
    EstimationStage(),
    RecordingStage(),
    DiagnosticsStage(),
    ReliabilityStage(),
    ReportStage(),
]


def splice_stage(insertion) -> None:
    """Insert insertion.stage into PIPELINE relative to a named anchor.
    Raises PackContractError if the anchor is not present."""
    from ..pack import PackContractError
    names = [s.name for s in PIPELINE]
    anchor = insertion.after or insertion.before
    if anchor is None or anchor not in names:
        raise PackContractError(
            f"StageInsertion anchor {anchor!r} is not a PIPELINE stage. "
            f"Known stages: {names}"
        )
    idx = names.index(anchor)
    pos = idx + 1 if insertion.after else idx
    PIPELINE.insert(pos, insertion.stage)
