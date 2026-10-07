"""Frozen joint wiring and unchanged legacy AR-only behavior."""
from pathlib import Path
import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from workbench.engine.packs.arma_garch.estimation import (
    fit_joint_ar_garch, resolve_estimation_strategy, estimate_arma_garch,
)
from workbench.engine.packs.arma_garch.volatility import (
    VarianceCandidateSpec, fit_joint_variance_candidate, search_joint_variance_candidates,
)
from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "arma_garch_joint"

def _values():
    return pd.read_csv(ROOT / "oracle_v1" / "data_garch11_constant.csv")["y"].to_numpy()

def _contract():
    # The public contract remains Lane A's integration responsibility.
    contract = ArmaGarchAnalysisContract.from_dict({
        "dataset_ref": "dataset:joint:1", "time_column": "t", "value_column": "y",
        "time_index_semantics": "observation_order", "transform": "level",
        "transform_confirmed": True, "selection_mode": "manual", "estimation_strategy": "sequential",
        "innovation_distribution": "normal", "validation": {"validation_n": 20},
        "arma": {"p": 1, "q": 1, "constant_mode": "include"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
    })
    object.__setattr__(contract, "estimation_strategy", "joint")
    return contract


def test_joint_strategy_and_auto_mapping():
    assert resolve_estimation_strategy("joint", mean_q=1) == "joint_arma_garch"
    assert resolve_estimation_strategy("joint", mean_q=0) == "joint_ar_garch"
    assert resolve_estimation_strategy("auto", mean_q=1) == "sequential_arma_garch"
    assert resolve_estimation_strategy("auto", mean_q=0) == "joint_ar_garch"


def test_joint_q_positive_candidate_and_final_fit_use_all_observations():
    values = _values()
    mean = fit_arma_candidate(values, ArmaCandidateSpec("arma-joint", 1, 1, True))
    contract = _contract()
    search = search_joint_variance_candidates(values, contract, mean_candidate_id=mean.candidate_id,
        mean_order=(1, 1), mean_constant=True)
    assert search.common_hold_back == 0
    candidate = search.candidates[0]
    assert candidate.failure_code is None
    assert candidate.hold_back == 0
    assert candidate.estimation_strategy == "joint"
    assert candidate.joint_likelihood
    assert candidate.effective_sample == len(values)
    assert candidate.mean_order == (1, 1)
    result = estimate_arma_garch(values, contract, mean_candidate=mean,
        variance_candidate=candidate, frozen_hold_back=0)
    assert result.resolved_strategy == "joint_arma_garch"
    assert result.log_likelihood == pytest.approx(candidate.log_likelihood, abs=1e-8)
    assert result.aic == pytest.approx(candidate.aic, abs=1e-8)
    assert len(result.conditional_series["residual"]) == len(values)
    with pytest.raises(ValueError, match="hold_back"):
        estimate_arma_garch(values, contract, mean_candidate=mean,
            variance_candidate=replace(candidate, hold_back=1), frozen_hold_back=1)


def test_joint_candidate_requires_zero_hold_back_and_exact_mean_binding():
    values = _values()
    spec = VarianceCandidateSpec.create(model="garch", p=1, q=1, distribution="normal")
    kwargs = dict(mean_p=1, include_constant=True, mean_candidate_id="arma-joint", mean_order=(1,1), mean_constant=True)
    failed = fit_joint_variance_candidate(values, spec, hold_back=1, **kwargs)
    assert failed.failure_code is not None
    assert "hold_back" in " ".join(failed.warnings)
    with pytest.raises(ValueError, match="binding"):
        fit_joint_variance_candidate(values, spec, hold_back=0, **{**kwargs, "mean_order": (2,1)})


def test_legacy_q_zero_payload_is_byte_identical_to_frozen_baseline():
    result = fit_joint_ar_garch(_values()[:220], mean_p=1, include_constant=True,
        variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"),
        hold_back=2, time_index_semantics="observation_order")
    encoded = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert encoded == (ROOT / "legacy_q0_payload.json").read_text().strip()
