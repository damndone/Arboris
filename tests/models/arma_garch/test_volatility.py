from __future__ import annotations

import json
import math

import numpy as np
import pytest

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract


def _contract(
    *,
    selection_mode: str = "auto",
    variance: dict[str, object] | None = None,
    distribution: str = "normal",
    time_semantics: str = "observation_order",
) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
        "dataset_ref": "dataset:variance:1",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": time_semantics,
        "transform": "level",
        "transform_confirmed": True,
        "selection_mode": selection_mode,
        "innovation_distribution": distribution,
        "validation": {"validation_n": 20},
    }
    if selection_mode == "manual":
        payload["arma"] = {"p": 1, "q": 0, "constant_mode": "include"}
        payload["variance"] = variance or {"model": "garch", "garch_p": 1, "garch_q": 1}
    return ArmaGarchAnalysisContract.from_dict(payload)


def _garch_residuals(n: int = 500, seed: int = 20260720) -> np.ndarray:
    rng = np.random.default_rng(seed)
    errors = np.empty(n)
    variances = np.empty(n)
    variances[0] = 1.0
    errors[0] = rng.normal()
    for index in range(1, n):
        variances[index] = 0.08 + 0.12 * errors[index - 1] ** 2 + 0.82 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
    return errors


def test_auto_enumerates_constant_arch_1_to_10_and_garch_1_1() -> None:
    from workbench.engine.packs.arma_garch.volatility import enumerate_variance_candidates

    candidates = enumerate_variance_candidates(_contract())

    assert len(candidates) == 12
    assert candidates[0].model == "constant_variance"
    assert candidates[0].display_name == "Constant Variance"
    assert "ARCH(0)" not in candidates[0].display_name
    assert {(item.model, item.p, item.q) for item in candidates} == {
        ("constant_variance", 0, 0),
        *(("arch", p, 0) for p in range(1, 11)),
        ("garch", 1, 1),
    }
    assert len({item.candidate_id for item in candidates}) == 12


@pytest.mark.parametrize(
    ("variance", "expected"),
    [
        ({"model": "constant_variance"}, ("constant_variance", 0, 0)),
        ({"model": "arch", "arch_p": 5}, ("arch", 5, 0)),
        ({"model": "garch", "garch_p": 2, "garch_q": 1}, ("garch", 2, 1)),
    ],
)
def test_manual_enumerates_only_the_confirmed_variance_model(
    variance: dict[str, object], expected: tuple[str, int, int]
) -> None:
    from workbench.engine.packs.arma_garch.volatility import enumerate_variance_candidates

    candidates = enumerate_variance_candidates(
        _contract(selection_mode="manual", variance=variance, distribution="student_t")
    )

    assert len(candidates) == 1
    assert (candidates[0].model, candidates[0].p, candidates[0].q) == expected
    assert candidates[0].distribution == "student_t"


@pytest.mark.parametrize(
    ("model", "p", "q", "distribution"),
    [
        ("constant_variance", 0, 0, "normal"),
        ("arch", 2, 0, "normal"),
        ("garch", 1, 1, "normal"),
        ("garch", 1, 1, "student_t"),
    ],
)
def test_real_arch_zero_mean_candidate_smoke(
    model: str, p: int, q: int, distribution: str
) -> None:
    from workbench.engine.packs.arma_garch.volatility import (
        VarianceCandidateSpec,
        fit_variance_candidate,
    )

    residuals = _garch_residuals()
    candidate = fit_variance_candidate(
        residuals,
        VarianceCandidateSpec.create(model=model, p=p, q=q, distribution=distribution),
        hold_back=10,
    )

    assert candidate.failure_code is None
    assert candidate.converged is True
    assert candidate.parameters_valid is True
    assert candidate.nobs == len(residuals) - 10
    assert candidate.hold_back == 10
    assert candidate.effective_sample == candidate.nobs
    assert candidate.log_likelihood is not None
    assert candidate.aic is not None
    assert candidate.aicc is not None
    assert candidate.bic is not None
    assert len(candidate.conditional_variance) == len(residuals)
    assert len(candidate.standardized_residuals) == len(residuals)
    json.dumps(candidate.to_dict(), allow_nan=False)


def test_search_uses_equal_hold_back_and_isolates_one_candidate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.volatility as volatility_module

    residuals = _garch_residuals(n=180)
    seen: list[tuple[str, int]] = []
    original = volatility_module.fit_variance_candidate

    def wrapped(
        values,
        spec,
        *,
        hold_back,
        mean_candidate_id,
        mean_order,
        mean_constant,
    ):
        seen.append((spec.candidate_id, hold_back))
        if spec.model == "arch" and spec.p == 4:
            raise RuntimeError("single optimizer failure")
        return original(
            values,
            spec,
            hold_back=hold_back,
            mean_candidate_id=mean_candidate_id,
            mean_order=mean_order,
            mean_constant=mean_constant,
        )

    monkeypatch.setattr(volatility_module, "fit_variance_candidate", wrapped)
    result = volatility_module.search_variance_candidates(
        residuals,
        _contract(),
        mean_candidate_id="arma-p0-q0-n",
        mean_order=(0, 0),
        mean_constant=False,
    )

    assert len(result.candidates) == 12
    assert {hold_back for _, hold_back in seen} == {10}
    failed = next(item for item in result.candidates if item.model == "arch" and item.p == 4)
    assert failed.failure_code == "VOLATILITY_FIT_FAILED"
    assert result.selected_candidate_id != failed.candidate_id


def test_checkpoint_can_stop_candidate_loop() -> None:
    from workbench.engine.packs.arma_garch.volatility import search_variance_candidates

    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt("cancelled")

    with pytest.raises(KeyboardInterrupt, match="cancelled"):
        search_variance_candidates(
            _garch_residuals(n=100),
            _contract(),
            mean_candidate_id="arma-p0-q0-n",
            mean_order=(0, 0),
            mean_constant=False,
            checkpoint=checkpoint,
        )


def test_parameter_gate_rejects_invalid_variance_nu_and_garch_coefficients() -> None:
    from workbench.engine.packs.arma_garch.volatility import validate_variance_parameters

    assert validate_variance_parameters(
        model="constant_variance", p=0, q=0, distribution="normal", parameters={"sigma2": 0.0}
    ).valid is False
    assert validate_variance_parameters(
        model="garch",
        p=1,
        q=1,
        distribution="normal",
        parameters={"omega": 0.1, "alpha[1]": -0.1, "beta[1]": 0.8},
    ).valid is False
    assert validate_variance_parameters(
        model="garch",
        p=1,
        q=1,
        distribution="student_t",
        parameters={"omega": 0.1, "alpha[1]": 0.1, "beta[1]": 0.8, "nu": 2.0},
    ).valid is False


@pytest.mark.parametrize(
    ("model", "p", "q", "parameters"),
    [
        ("arch", 2, 0, {"omega": 0.1, "alpha[1]": 0.6, "alpha[2]": 0.4}),
        ("garch", 1, 1, {"omega": 0.1, "alpha[1]": 0.6, "beta[1]": 0.5}),
    ],
)
def test_parameter_gate_rejects_nonstationary_aggregate_persistence(
    model: str,
    p: int,
    q: int,
    parameters: dict[str, float],
) -> None:
    from workbench.engine.packs.arma_garch.volatility import (
        validate_variance_parameters,
    )

    validation = validate_variance_parameters(
        model=model,
        p=p,
        q=q,
        distribution="normal",
        parameters=parameters,
    )

    assert validation.valid is False
    assert validation.failure_code == "GARCH_NONSTATIONARY_PERSISTENCE"
    assert any(
        item["parameter"] == "aggregate_persistence"
        and item["constraint"] == "< 1"
        and item["satisfied"] is False
        for item in validation.constraints
    )


def test_no_eligible_candidate_returns_structured_blocking_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.volatility as volatility_module

    def failed(
        values,
        spec,
        *,
        hold_back,
        mean_candidate_id,
        mean_order,
        mean_constant,
    ):
        return volatility_module.failed_variance_candidate(
            spec,
            total_observations=len(values),
            hold_back=hold_back,
            warning="forced failure",
            mean_candidate_id=mean_candidate_id,
            mean_order=mean_order,
            mean_constant=mean_constant,
        )

    monkeypatch.setattr(volatility_module, "fit_variance_candidate", failed)
    result = volatility_module.search_variance_candidates(
        _garch_residuals(n=120),
        _contract(),
        mean_candidate_id="arma-p0-q0-n",
        mean_order=(0, 0),
        mean_constant=False,
    )

    assert result.selected_candidate_id is None
    assert result.selection_status == "blocked"
    assert result.blocking_diagnostic is not None
    assert result.blocking_diagnostic.code == "NO_VOLATILITY_CANDIDATE_CONVERGED"
    assert result.blocking_diagnostic.evidence["candidate_count"] == 12
    assert result.blocking_diagnostic.impact
    assert result.blocking_diagnostic.recommended_actions


@pytest.mark.parametrize(
    ("persistence", "expected_half_life", "warning"),
    [
        (0.0, None, None),
        (0.5, 1.0, None),
        (0.9995, pytest.approx(1385.947, rel=1e-3), "GARCH_HIGH_PERSISTENCE"),
        (1.0, None, "GARCH_NONSTATIONARY_PERSISTENCE"),
        (1.1, None, "GARCH_NONSTATIONARY_PERSISTENCE"),
    ],
)
def test_garch_1_1_persistence_half_life_boundaries(
    persistence: float, expected_half_life: object, warning: str | None
) -> None:
    from workbench.engine.packs.arma_garch.volatility import calculate_persistence

    result = calculate_persistence(
        model="garch",
        p=1,
        q=1,
        parameters={"alpha[1]": persistence, "beta[1]": 0.0},
        time_index_semantics="observation_order",
    )

    assert result.persistence == persistence
    assert result.half_life == expected_half_life
    assert result.half_life_unit == "observation_periods"
    assert warning in result.warnings if warning else not result.warnings


def test_persistence_unit_is_trading_observation_periods_and_high_order_is_not_approximated() -> None:
    from workbench.engine.packs.arma_garch.volatility import calculate_persistence

    trading = calculate_persistence(
        model="garch",
        p=1,
        q=1,
        parameters={"alpha[1]": 0.1, "beta[1]": 0.8},
        time_index_semantics="business_or_trading_observations",
    )
    high_order = calculate_persistence(
        model="garch",
        p=2,
        q=1,
        parameters={"alpha[1]": 0.1, "alpha[2]": 0.1, "beta[1]": 0.7},
        time_index_semantics="regular_calendar",
    )

    assert trading.half_life_unit == "business_or_trading_observation_periods"
    assert trading.half_life == pytest.approx(math.log(0.5) / math.log(0.9))
    assert high_order.persistence is None
    assert high_order.half_life is None
    assert "HIGH_ORDER_PERSISTENCE_NOT_REPORTED" in high_order.warnings


def test_negative_garch_component_never_produces_a_half_life() -> None:
    from workbench.engine.packs.arma_garch.volatility import calculate_persistence

    result = calculate_persistence(
        model="garch",
        p=1,
        q=1,
        parameters={"alpha[1]": -0.1, "beta[1]": 0.7},
        time_index_semantics="observation_order",
    )

    assert result.persistence == pytest.approx(0.6)
    assert result.half_life is None
    assert result.warnings == ("GARCH_INVALID_VARIANCE_PARAMETERS",)


def test_candidate_payload_is_strict_json_and_nested_state_is_immutable() -> None:
    from workbench.engine.packs.arma_garch.volatility import (
        VarianceCandidateSpec,
        fit_variance_candidate,
    )

    candidate = fit_variance_candidate(
        _garch_residuals(n=240),
        VarianceCandidateSpec.create(model="garch", p=1, q=1, distribution="normal"),
        hold_back=10,
    )

    json.dumps(candidate.to_dict(), allow_nan=False)
    with pytest.raises(TypeError):
        candidate.parameters["omega"] = 999.0
    with pytest.raises(TypeError):
        candidate.parameter_constraints[0]["satisfied"] = False
    with pytest.raises(TypeError):
        candidate.standardized_residual_diagnostics[0]["p_value"] = 0.0


def test_provisional_selection_does_not_claim_validation_or_final_selection() -> None:
    from workbench.engine.packs.arma_garch.volatility import search_variance_candidates

    result = search_variance_candidates(
        _garch_residuals(n=260),
        _contract(),
        mean_candidate_id="arma-p0-q0-n",
        mean_order=(0, 0),
        mean_constant=False,
    )

    assert result.selection_status == "provisional_pre_validation"
    assert {candidate.estimation_strategy for candidate in result.candidates} == {
        "sequential"
    }
    assert {candidate.joint_likelihood for candidate in result.candidates} == {False}
    payload = result.to_dict()
    assert payload["selection_status"] == "provisional_pre_validation"
    assert "final_selected_candidate_id" not in payload
    assert "rolling" not in json.dumps(payload).lower()
