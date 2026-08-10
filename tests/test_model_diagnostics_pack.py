from __future__ import annotations

import json

import numpy as np
import pytest
import statsmodels.api as sm
from statsmodels.stats.diagnostic import (
    acorr_breusch_godfrey,
    het_breuschpagan,
    het_white,
    linear_reset,
)
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor


def _fit_fixture():
    x1 = np.linspace(-2.5, 2.5, 30)
    x2 = np.sin(np.linspace(-1.7, 2.1, 30)) + np.linspace(-0.2, 0.2, 30)
    design = np.column_stack((np.ones(30), x1, x2))
    response = 1.25 + 0.8 * x1 - 0.35 * x2 + 0.04 * x1**2 + 0.18 * np.cos(x1 * 2.0)
    fitted = sm.OLS(response, design).fit()
    metadata = {
        "model_type": "ols",
        "parameter_count": int(fitted.df_model + 1),
        "residual_df": int(fitted.df_resid),
        "residual_variance": float(fitted.mse_resid),
        "covariance": "unadjusted",
        "parameter_names": ["const", "x1", "x2"],
    }
    return response, design, fitted, metadata


def _kwargs(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "design_columns": ["const", "x1", "x2"],
        "intercept": True,
        "intercept_column": "const",
        "model_metadata": metadata,
    }


def test_all_declared_operations_return_bounded_scope_results():
    from workbench.engine.packs.model_diagnostics import (
        run_breusch_godfrey,
        run_breusch_pagan,
        run_influence,
        run_reset,
        run_vif,
        run_white,
    )

    response, design, fitted, metadata = _fit_fixture()
    residuals = fitted.resid
    kwargs = _kwargs(metadata)

    packets = [
        run_vif(design, **kwargs),
        run_breusch_pagan(response, design, residuals, fitted_values=fitted.fittedvalues, **kwargs),
        run_white(response, design, residuals, fitted_values=fitted.fittedvalues, **kwargs),
        run_breusch_godfrey(
            response,
            design,
            residuals,
            fitted_values=fitted.fittedvalues,
            lag=2,
            time_order="declared_monotonic",
            **kwargs,
        ),
        run_reset(
            response,
            design,
            residuals,
            fitted_values=fitted.fittedvalues,
            reset_powers=(2, 3),
            **kwargs,
        ),
        run_influence(
            response,
            design,
            residuals,
            fitted_values=fitted.fittedvalues,
            **kwargs,
        ),
    ]

    assert [packet["operation_id"] for packet in packets] == [
        "diagnostics.vif",
        "diagnostics.breusch_pagan",
        "diagnostics.white",
        "diagnostics.breusch_godfrey",
        "diagnostics.reset",
        "diagnostics.influence",
    ]
    for packet in packets:
        assert packet["status"] == "completed"
        assert packet["result"]["scope"]["not_claimed"]
        assert any(
            "valid" in statement.lower() and "invalid" in statement.lower()
            for statement in packet["result"]["scope"]["not_claimed"]
        )
        json.dumps(packet, allow_nan=False)


def test_vif_matches_statsmodels_for_non_intercept_predictors_and_exposes_intercept():
    from workbench.engine.packs.model_diagnostics import run_vif

    _, design, fitted, metadata = _fit_fixture()
    packet = run_vif(design, **_kwargs(metadata))
    values = packet["result"]["vif"]

    assert packet["result"]["intercept"] == {
        "included": True,
        "column": "const",
        "excluded_from_vif": True,
    }
    assert values["x1"] == pytest.approx(variance_inflation_factor(design, 1))
    assert values["x2"] == pytest.approx(variance_inflation_factor(design, 2))
    assert packet["result"]["condition"]["full_rank"] is True
    assert packet["result"]["variables"] == ["x1", "x2"]


def test_breusch_pagan_and_white_match_statsmodels_statistics_and_df():
    from workbench.engine.packs.model_diagnostics import run_breusch_pagan, run_white

    response, design, fitted, metadata = _fit_fixture()
    kwargs = _kwargs(metadata)
    bp = run_breusch_pagan(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        **kwargs,
    )
    white = run_white(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        **kwargs,
    )

    expected_bp = het_breuschpagan(fitted.resid, design)
    expected_white = het_white(fitted.resid, design)
    assert bp["result"]["statistic"] == pytest.approx(expected_bp[0])
    assert bp["result"]["p_value"] == pytest.approx(expected_bp[1])
    assert bp["result"]["f_statistic"] == pytest.approx(expected_bp[2])
    assert bp["result"]["f_p_value"] == pytest.approx(expected_bp[3])
    assert bp["result"]["df"] == 2
    assert bp["result"]["auxiliary_regression"]["df_residual"] == 27
    assert white["result"]["statistic"] == pytest.approx(expected_white[0])
    assert white["result"]["p_value"] == pytest.approx(expected_white[1])
    assert white["result"]["f_statistic"] == pytest.approx(expected_white[2])
    assert white["result"]["f_p_value"] == pytest.approx(expected_white[3])
    assert white["result"]["df"] == 5
    assert white["result"]["auxiliary_regression"]["df_residual"] == 25


def test_breusch_godfrey_and_reset_match_statsmodels_finite_sample_statistics():
    from workbench.engine.packs.model_diagnostics import run_breusch_godfrey, run_reset

    response, design, fitted, metadata = _fit_fixture()
    kwargs = _kwargs(metadata)
    bg = run_breusch_godfrey(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        lag=2,
        time_order="declared_monotonic",
        **kwargs,
    )
    reset = run_reset(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        reset_powers=(2, 3),
        **kwargs,
    )

    expected_bg = acorr_breusch_godfrey(fitted, nlags=2)
    expected_reset = linear_reset(fitted, power=(2, 3), use_f=True)
    assert bg["result"]["statistic"] == pytest.approx(expected_bg[0])
    assert bg["result"]["p_value"] == pytest.approx(expected_bg[1])
    assert bg["result"]["f_statistic"] == pytest.approx(expected_bg[2])
    assert bg["result"]["f_p_value"] == pytest.approx(expected_bg[3])
    assert bg["result"]["df"] == 2
    assert reset["result"]["f_statistic"] == pytest.approx(float(expected_reset.fvalue))
    assert reset["result"]["p_value"] == pytest.approx(float(expected_reset.pvalue))
    assert reset["result"]["powers"] == [2, 3]
    assert reset["result"]["df_num"] == 2


def test_influence_matches_statsmodels_leverage_cook_studentized_and_dfbetas():
    from workbench.engine.packs.model_diagnostics import run_influence

    response, design, fitted, metadata = _fit_fixture()
    packet = run_influence(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        **_kwargs(metadata),
    )
    expected = OLSInfluence(fitted)
    rows = packet["result"]["observations"]

    assert len(rows) == len(response)
    assert packet["result"]["rows_truncated"] is False
    for index in (0, 7, 29):
        row = rows[index]
        assert row["observation_index"] == index
        assert row["leverage"] == pytest.approx(expected.hat_matrix_diag[index])
        assert row["cooks_distance"] == pytest.approx(expected.cooks_distance[0][index])
        assert row["studentized_residual_internal"] == pytest.approx(
            expected.resid_studentized_internal[index]
        )
        assert row["studentized_residual_external"] == pytest.approx(
            expected.resid_studentized_external[index]
        )
        for name, value in row["dfbetas"].items():
            column = ["const", "x1", "x2"].index(name)
            assert value == pytest.approx(expected.dfbetas[index, column])


@pytest.mark.parametrize(
    "operation",
    [
        "diagnostics.vif",
        "diagnostics.breusch_pagan",
        "diagnostics.white",
        "diagnostics.breusch_godfrey",
        "diagnostics.reset",
        "diagnostics.influence",
    ],
)
def test_invalid_numeric_or_fitted_inputs_fail_closed_without_a_normal_result(operation: str):
    from workbench.engine.packs.model_diagnostics import (
        ModelDiagnosticsPackError,
        run_model_diagnostics,
    )

    response, design, fitted, metadata = _fit_fixture()
    kwargs = _kwargs(metadata)
    kwargs["design"] = design
    kwargs["response"] = response
    kwargs["residuals"] = fitted.resid
    kwargs["fitted_values"] = fitted.fittedvalues
    if operation == "diagnostics.breusch_godfrey":
        kwargs.update(lag=2, time_order="declared_monotonic")
    if operation == "diagnostics.reset":
        kwargs.update(reset_powers=(2, 3))
    if operation == "diagnostics.influence":
        kwargs["residuals"] = fitted.resid.copy()
        kwargs["residuals"][0] += 0.25

    with pytest.raises(ModelDiagnosticsPackError) as error:
        run_model_diagnostics(operation, **kwargs)
    assert error.value.reason_code in {
        "DIAGNOSTICS_FITTED_RESIDUAL_MISMATCH",
        "DIAGNOSTICS_NON_FINITE_INPUT",
        "DIAGNOSTICS_NUMERIC_FAILURE",
    }


def test_influence_uses_deterministic_cook_order_when_output_is_truncated():
    from workbench.engine.packs.model_diagnostics import run_influence

    response, design, fitted, metadata = _fit_fixture()
    packet = run_influence(
        response,
        design,
        fitted.resid,
        fitted_values=fitted.fittedvalues,
        max_output_rows=3,
        **_kwargs(metadata),
    )
    rows = packet["result"]["observations"]
    expected = OLSInfluence(fitted).cooks_distance[0]
    selected = sorted(range(len(expected)), key=lambda i: (-expected[i], i))[:3]
    assert packet["result"]["rows_truncated"] is True
    assert packet["result"]["rows_returned"] == 3
    assert [row["observation_index"] for row in rows] == sorted(selected)
