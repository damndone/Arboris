from __future__ import annotations

import json
import math

import numpy as np
import pytest

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec, fit_arma_candidate
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec


def _contract(
    *,
    strategy: str,
    q: int,
    p: int = 1,
    distribution: str = "normal",
    selection_mode: str = "manual",
) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
            "dataset_ref": "dataset:estimation:1",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "business_or_trading_observations",
            "transform": "level",
            "transform_confirmed": True,
            "selection_mode": selection_mode,
            "estimation_strategy": strategy,
            "innovation_distribution": distribution,
            "validation": {"validation_n": 20},
        }
    if selection_mode == "manual":
        payload["arma"] = {"p": p, "q": q, "constant_mode": "include"}
        payload["variance"] = {"model": "garch", "garch_p": 1, "garch_q": 1}
    return ArmaGarchAnalysisContract.from_dict(payload)


def _arma_garch_values(n: int = 600, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = np.zeros(n)
    errors = np.zeros(n)
    variances = np.ones(n)
    for index in range(1, n):
        variances[index] = 0.08 + 0.1 * errors[index - 1] ** 2 + 0.84 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
        values[index] = (
            0.15
            + 0.45 * values[index - 1]
            + errors[index]
            + 0.25 * errors[index - 1]
        )
    return values


def test_sequential_keeps_stage_specific_likelihoods_and_no_composite_ic() -> None:
    from workbench.engine.packs.arma_garch.estimation import fit_sequential_arma_garch

    values = _arma_garch_values(n=420)
    mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p1-q1-c", p=1, q=1, constant=True),
    )
    result = fit_sequential_arma_garch(
        values,
        mean,
        VarianceCandidateSpec.create(model="garch", p=1, q=1, distribution="normal"),
        hold_back=10,
        time_index_semantics="business_or_trading_observations",
    )

    payload = result.to_dict()
    assert payload["model_family"] == "arma_garch"
    assert payload["estimation_strategy"] == "sequential"
    assert payload["resolved_strategy"] == "sequential_arma_garch"
    assert payload["joint_likelihood"] is False
    assert payload["mean_stage"]["backend"] == "statsmodels_arima"
    assert payload["variance_stage"]["backend"] == "arch"
    encoded = json.dumps(payload, allow_nan=False).lower()
    assert "composite" not in encoded
    assert "joint_aic" not in encoded
    assert "joint_bic" not in encoded
    assert len(result.conditional_series["mean"]) == len(values)
    assert len(result.conditional_series["variance"]) == len(values)
    masks = {
        tuple(value is None for value in result.conditional_series[name])
        for name in (
            "mean",
            "residual",
            "variance",
            "volatility",
            "standardized_residual",
            "squared_standardized_residual",
        )
    }
    assert len(masks) == 1
    assert next(iter(masks))[:10] == (True,) * 10


def test_joint_q_zero_real_arch_fit_has_unified_likelihood_and_series() -> None:
    from workbench.engine.packs.arma_garch.estimation import fit_joint_ar_garch

    values = _arma_garch_values()
    result = fit_joint_ar_garch(
        values,
        mean_p=1,
        include_constant=True,
        variance_spec=VarianceCandidateSpec.create(
            model="garch", p=1, q=1, distribution="student_t"
        ),
        hold_back=10,
        time_index_semantics="business_or_trading_observations",
    )

    payload = result.to_dict()
    assert payload["model_family"] == "ar_garch"
    assert payload["mean_order"] == [1, 0]
    assert payload["estimation_strategy"] == "joint"
    assert payload["resolved_strategy"] == "joint_ar_garch"
    assert payload["joint_likelihood"] is True
    assert payload["backend"] == "arch"
    assert payload["log_likelihood"] is not None
    assert payload["aic"] is not None
    assert payload["bic"] is not None
    assert payload["innovation_distribution"] == "student_t"
    assert payload["hold_back"] == 10
    assert len(result.conditional_series["mean"]) == len(values)
    assert len(result.conditional_series["standardized_residual"]) == len(values)
    json.dumps(payload, allow_nan=False)


def test_joint_q_greater_than_zero_runtime_error_never_downgrades() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import search_variance_candidates

    contract = _contract(strategy="sequential", q=1)
    values = _arma_garch_values(n=180)
    mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p1-q1-c", p=1, q=1, constant=True),
    )
    search = search_variance_candidates(
        np.asarray(mean.residuals, dtype=float),
        contract,
        mean_candidate_id=mean.candidate_id,
        mean_order=(mean.p, mean.q),
        mean_constant=mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )
    unsafe_joint_contract = object.__new__(ArmaGarchAnalysisContract)
    for field_name in contract.__dataclass_fields__:
        object.__setattr__(unsafe_joint_contract, field_name, getattr(contract, field_name))
    object.__setattr__(unsafe_joint_contract, "estimation_strategy", "joint")

    with pytest.raises(ArmaGarchInputError) as caught:
        estimate_arma_garch(
            values,
            unsafe_joint_contract,
            mean_candidate=mean,
            variance_candidate=selected,
            frozen_hold_back=search.common_hold_back,
        )

    assert caught.value.code == "UNSUPPORTED_JOINT_ARMA_GARCH"
    assert caught.value.evidence["arma_q"] == 1
    assert len(caught.value.recommended_actions) == 2


@pytest.mark.parametrize(
    ("q", "expected"),
    [(0, "joint_ar_garch"), (1, "sequential_arma_garch")],
)
def test_auto_strategy_resolves_from_selected_mean_order(q: int, expected: str) -> None:
    from workbench.engine.packs.arma_garch.estimation import resolve_estimation_strategy

    assert resolve_estimation_strategy("auto", mean_q=q) == expected


def test_estimate_auto_reports_resolved_strategy() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import (
        search_joint_variance_candidates,
    )

    values = _arma_garch_values(n=260)
    contract = _contract(strategy="auto", q=0, selection_mode="auto")
    mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p1-q0-c", p=1, q=0, constant=True),
    )
    search = search_joint_variance_candidates(
        values,
        contract,
        mean_candidate_id=mean.candidate_id,
        mean_order=(mean.p, mean.q),
        mean_constant=mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )
    assert len(search.candidates) == 12
    assert {item.estimation_strategy for item in search.candidates} == {"joint"}
    assert {item.joint_likelihood for item in search.candidates} == {True}
    assert {item.hold_back for item in search.candidates} == {search.common_hold_back}
    assert selected.standardized_residual_diagnostics
    assert selected.squared_standardized_residual_diagnostics
    result = estimate_arma_garch(
        values,
        contract,
        mean_candidate=mean,
        variance_candidate=selected,
        frozen_hold_back=search.common_hold_back,
    )

    assert result.resolved_strategy == "joint_ar_garch"
    assert result.joint_likelihood is True
    assert result.hold_back == search.common_hold_back == selected.hold_back
    assert result.nobs == selected.effective_sample
    assert result.log_likelihood == pytest.approx(selected.log_likelihood)
    assert result.aic == pytest.approx(selected.aic)
    assert result.bic == pytest.approx(selected.bic)


def test_estimate_requires_frozen_search_hold_back_and_rejects_strategy_mismatch() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import search_variance_candidates

    values = _arma_garch_values(n=300)
    contract = _contract(strategy="sequential", p=2, q=1)
    mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p2-q1-c", p=2, q=1, constant=True),
    )
    search = search_variance_candidates(
        np.asarray(mean.residuals, dtype=float),
        contract,
        mean_candidate_id=mean.candidate_id,
        mean_order=(mean.p, mean.q),
        mean_constant=mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )

    assert search.common_hold_back == 2
    with pytest.raises(TypeError, match="frozen_hold_back"):
        estimate_arma_garch(
            values,
            contract,
            mean_candidate=mean,
            variance_candidate=selected,
        )

    result = estimate_arma_garch(
        values,
        contract,
        mean_candidate=mean,
        variance_candidate=selected,
        frozen_hold_back=search.common_hold_back,
    )
    assert result.hold_back == selected.hold_back == 2
    assert result.variance_stage["effective_sample"] == selected.effective_sample
    assert result.variance_stage["aic"] == pytest.approx(selected.aic)
    assert result.variance_stage["aicc"] == pytest.approx(selected.aicc)
    assert result.variance_stage["bic"] == pytest.approx(selected.bic)

    joint_contract = _contract(strategy="auto", p=1, q=0)
    joint_mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p1-q0-c", p=1, q=0, constant=True),
    )
    wrong_strategy_search = search_variance_candidates(
        np.asarray(joint_mean.residuals, dtype=float),
        joint_contract,
        mean_candidate_id=joint_mean.candidate_id,
        mean_order=(joint_mean.p, joint_mean.q),
        mean_constant=joint_mean.constant,
    )
    wrong_strategy_candidate = next(
        item
        for item in wrong_strategy_search.candidates
        if item.candidate_id == wrong_strategy_search.selected_candidate_id
    )
    with pytest.raises(ValueError, match="candidate strategy does not match"):
        estimate_arma_garch(
            values,
            joint_contract,
            mean_candidate=joint_mean,
            variance_candidate=wrong_strategy_candidate,
            frozen_hold_back=wrong_strategy_search.common_hold_back,
        )


def test_sequential_rejects_failed_mean_candidate() -> None:
    from workbench.engine.packs.arma_garch.estimation import fit_sequential_arma_garch

    failed = fit_arma_candidate(
        np.array([1.0, np.nan]),
        ArmaCandidateSpec(candidate_id="bad", p=1, q=1, constant=True),
    )

    with pytest.raises(ValueError, match="eligible fitted ARMA"):
        fit_sequential_arma_garch(
            np.arange(20.0),
                failed,
                VarianceCandidateSpec.create(model="garch", p=1, q=1, distribution="normal"),
                hold_back=1,
                time_index_semantics="observation_order",
            )


def test_estimation_payload_is_nested_immutable_and_strict_json() -> None:
    from workbench.engine.packs.arma_garch.estimation import fit_joint_ar_garch

    result = fit_joint_ar_garch(
        _arma_garch_values(n=260),
        mean_p=1,
        include_constant=True,
        variance_spec=VarianceCandidateSpec.create(
            model="garch", p=1, q=1, distribution="normal"
        ),
        hold_back=10,
        time_index_semantics="observation_order",
    )

    json.dumps(result.to_dict(), allow_nan=False)
    with pytest.raises(TypeError):
        result.parameters["omega"] = 1.0
    with pytest.raises(TypeError):
        result.conditional_series["variance"][20] = 0.0


def test_joint_candidate_mean_binding_rejects_ar0_to_ar1_swap() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import (
        search_joint_variance_candidates,
    )

    values = _arma_garch_values(n=300)
    contract = _contract(strategy="auto", q=0, selection_mode="auto")
    bound_mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(
            candidate_id="arma-p0-q0-n",
            p=0,
            q=0,
            constant=False,
        ),
    )
    search = search_joint_variance_candidates(
        values,
        contract,
        mean_candidate_id=bound_mean.candidate_id,
        mean_order=(bound_mean.p, bound_mean.q),
        mean_constant=bound_mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )
    payload = selected.to_dict()
    assert payload["mean_candidate_id"] == "arma-p0-q0-n"
    assert payload["mean_order"] == [0, 0]
    assert payload["mean_constant"] is False
    assert payload["mean_binding_status"] == "bound"
    with pytest.raises(TypeError):
        selected.mean_order[0] = 1

    replacement = fit_arma_candidate(
        values,
        ArmaCandidateSpec(
            candidate_id="arma-p1-q0-c",
            p=1,
            q=0,
            constant=True,
        ),
    )
    with pytest.raises(ValueError, match="mean binding does not match"):
        estimate_arma_garch(
            values,
            contract,
            mean_candidate=replacement,
            variance_candidate=selected,
            frozen_hold_back=search.common_hold_back,
        )


def test_sequential_candidate_mean_binding_rejects_id_and_spec_swaps() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import search_variance_candidates

    values = _arma_garch_values(n=420)
    contract = _contract(strategy="sequential", p=1, q=1)
    bound_mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(
            candidate_id="arma-p1-q1-c-bound",
            p=1,
            q=1,
            constant=True,
        ),
    )
    search = search_variance_candidates(
        np.asarray(bound_mean.residuals, dtype=float),
        contract,
        mean_candidate_id=bound_mean.candidate_id,
        mean_order=(bound_mean.p, bound_mean.q),
        mean_constant=bound_mean.constant,
    )
    selected = next(
        item for item in search.candidates if item.candidate_id == search.selected_candidate_id
    )

    replacements = (
        fit_arma_candidate(
            values,
            ArmaCandidateSpec(
                candidate_id="arma-p1-q1-c-other-id",
                p=1,
                q=1,
                constant=True,
            ),
        ),
        fit_arma_candidate(
            values,
            ArmaCandidateSpec(
                candidate_id="arma-p2-q1-c-other-spec",
                p=2,
                q=1,
                constant=True,
            ),
        ),
    )
    for replacement in replacements:
        with pytest.raises(ValueError, match="mean binding does not match"):
            estimate_arma_garch(
                values,
                contract,
                mean_candidate=replacement,
                variance_candidate=selected,
                frozen_hold_back=search.common_hold_back,
            )


def test_unbound_standalone_variance_candidate_cannot_enter_estimation() -> None:
    from workbench.engine.packs.arma_garch.estimation import estimate_arma_garch
    from workbench.engine.packs.arma_garch.volatility import fit_variance_candidate

    values = _arma_garch_values(n=300)
    contract = _contract(strategy="sequential", p=1, q=1)
    mean = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p1-q1-c", p=1, q=1, constant=True),
    )
    unbound = fit_variance_candidate(
        np.asarray(mean.residuals, dtype=float),
        VarianceCandidateSpec.create(model="garch", p=1, q=1, distribution="normal"),
        hold_back=1,
    )
    assert unbound.to_dict()["mean_binding_status"] == "unbound"

    with pytest.raises(ValueError, match="bound mean specification"):
        estimate_arma_garch(
            values,
            contract,
            mean_candidate=mean,
            variance_candidate=unbound,
            frozen_hold_back=unbound.hold_back,
        )
