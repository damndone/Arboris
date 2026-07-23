"""Convergence is blocking, never a warning that still shows numbers."""

from __future__ import annotations

import pytest

from tests.fixtures.models.ets.known_truth import short_stable_series
from workbench.contracts.model.ets import CONVERGENCE_CODES, ETSSpecification
from workbench.engine.packs.ets import estimation
from workbench.engine.packs.ets.diagnostics import (
    NON_CONVERGENCE_CODE,
    classify_convergence,
    non_convergence_diagnostic,
    simplification_candidates,
)
from workbench.engine.packs.ets.errors import ETSEstimationError
from workbench.engine.packs.ets.runner import fit_ets


def _options(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "time_column": "date",
        "value_column": "y",
        "error": "add",
        "trend": "add",
        "seasonal": None,
        "damped_trend": False,
    }
    payload.update(overrides)
    return payload


class _FakeFit:
    param_names = ("smoothing_level", "smoothing_trend")
    params = (0.5, 0.1)
    aic = 1.0
    bic = 2.0
    llf = -3.0
    mse = 1.0

    def __init__(self, mle_retvals) -> None:
        self.mle_retvals = mle_retvals


@pytest.mark.parametrize(
    ("retvals", "expected"),
    [
        ({"converged": True, "warnflag": 0}, "converged"),
        ({"converged": False, "warnflag": 1}, "max_iterations"),
        ({"converged": False, "warnflag": 2}, "failed"),
        ({}, "failed"),
        (None, "failed"),
    ],
)
def test_convergence_codes_are_contract_codes(retvals, expected) -> None:
    code = classify_convergence(retvals)
    assert code == expected
    assert code in CONVERGENCE_CODES


@pytest.mark.parametrize("retvals", [{"converged": False, "warnflag": 1}, {}])
def test_non_convergence_blocks_instead_of_reporting_numbers(monkeypatch, retvals) -> None:
    monkeypatch.setattr(
        estimation, "_fit_statsmodels", lambda prepared: _FakeFit(retvals)
    )
    with pytest.raises(ETSEstimationError) as excinfo:
        fit_ets(short_stable_series().frame(), _options(damped_trend=True))

    error = excinfo.value
    assert error.code == NON_CONVERGENCE_CODE
    assert error.diagnostic.severity == "blocking"
    assert error.evidence["convergence_code"] in {"max_iterations", "failed"}
    assert error.evidence["specification"] == "ETS(A,Ad,N)"
    assert error.evidence["n_obs"] == 120
    payload = error.to_dict()
    assert set(payload["evidence"]) == {"convergence_code", "specification", "n_obs"}
    assert "aic" not in payload["evidence"]


def test_non_convergence_offers_recommended_action_candidates() -> None:
    specification = ETSSpecification(
        error="add", trend="add", seasonal="add", seasonal_periods=4, damped_trend=True
    )
    diagnostic_ = non_convergence_diagnostic(
        convergence_code="failed", specification=specification, n_obs=200
    )
    actions = diagnostic_.to_dict()["recommended_actions"]

    assert [action["action_id"] for action in actions] == [
        "ets.drop_damping",
        "ets.drop_seasonal",
        "ets.drop_trend",
    ]
    assert all(action["required_confirmation"] is True for action in actions)
    assert actions[0]["patch"] == {"damped_trend": False}
    assert actions[1]["patch"] == {"seasonal": None, "seasonal_periods": None}


def test_simplest_specification_has_no_simplification_candidate() -> None:
    specification = ETSSpecification(
        error="add", trend=None, seasonal=None, seasonal_periods=None, damped_trend=False
    )
    assert simplification_candidates(specification) == ()


def test_estimator_exception_is_a_blocking_diagnostic(monkeypatch) -> None:
    def _boom(prepared):
        raise FloatingPointError("optimizer blew up")

    monkeypatch.setattr(estimation, "_fit_statsmodels", _boom)
    with pytest.raises(ETSEstimationError) as excinfo:
        fit_ets(short_stable_series().frame(), _options())

    assert excinfo.value.code == "ETS_ESTIMATION_FAILED"
    assert excinfo.value.evidence["error_type"] == "FloatingPointError"


def test_non_finite_estimates_are_blocking(monkeypatch) -> None:
    class _NanFit(_FakeFit):
        aic = float("nan")

    monkeypatch.setattr(
        estimation,
        "_fit_statsmodels",
        lambda prepared: _NanFit({"converged": True}),
    )
    with pytest.raises(ETSEstimationError) as excinfo:
        fit_ets(short_stable_series().frame(), _options())

    assert excinfo.value.code == "ETS_NON_FINITE_ESTIMATE"
    assert list(excinfo.value.evidence["fields"]) == ["aic"]


def test_volatility_shaped_parameter_is_refused(monkeypatch) -> None:
    class _VolatilityFit(_FakeFit):
        param_names = ("smoothing_level", "conditional_variance")
        params = (0.5, 1.2)

    monkeypatch.setattr(
        estimation,
        "_fit_statsmodels",
        lambda prepared: _VolatilityFit({"converged": True}),
    )
    with pytest.raises(ETSEstimationError) as excinfo:
        fit_ets(short_stable_series().frame(), _options())

    assert excinfo.value.code == "ETS_FORBIDDEN_PARAMETER"
    assert list(excinfo.value.evidence["params"]) == ["conditional_variance"]
