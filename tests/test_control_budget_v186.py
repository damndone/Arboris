from __future__ import annotations

import pandas as pd
import pytest

from workbench.predictive_research.contracts import (
    AvailabilitySpecV1, SampleSpecV1, SamplingSpecV1, SplitPlanV1, StructureSpecV1,
)


def test_control_packet_records_its_budget_stop_reason_and_completeness() -> None:
    """Design 8.4: a bounded control run must say what budget it actually used.

    Without it a packet cannot be told apart from one that stopped early, so
    "the controls passed" is unverifiable.
    """
    from workbench.predictive_research.prediction_protocol import _control_budget_record

    record = _control_budget_record(
        requested=("permuted_target", "seeded_noise_features"),
        executed=("permuted_target", "seeded_noise_features"),
    )
    assert record["policy_version"] == 1
    assert record["max_permutations"] >= 1
    assert record["max_noise_features"] >= 1
    assert record["executed_controls"] == 2
    assert record["fully_executed"] is True
    assert record["stop_reason"] == "BUDGET_NOT_EXHAUSTED"

    partial = _control_budget_record(
        requested=("permuted_target", "seeded_noise_features"),
        executed=("permuted_target",),
    )
    assert partial["fully_executed"] is False
    assert partial["stop_reason"] == "CONTROL_NOT_EXECUTED"
