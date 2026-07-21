from __future__ import annotations

import json

import pytest


def _metrics(*, validation_n: int = 30, successful_n: int = 30):
    from workbench.engine.packs.arma_garch.forecast import ForecastMetrics

    return ForecastMetrics(
        validation_n=validation_n,
        successful_forecast_n=successful_n,
        mae=0.8,
        rmse=1.0,
        mean_error=0.1,
        interval_coverage=0.93,
        average_interval_width=3.0,
        coverage_count=min(successful_n, round(0.93 * successful_n)),
        coverage_interval=(0.79, 0.98),
        exception_rate=0.07,
        exception_count=min(successful_n, round(0.07 * successful_n)),
        pinball_loss=0.12,
    )


def test_acceptance_rejects_invalid_variance_parameters() -> None:
    from workbench.engine.packs.arma_garch.acceptance import assess_acceptance

    result = assess_acceptance(
        forecast_metrics=_metrics(),
        split_forecast_status="pending",
        estimation_converged=True,
        finite_parameters=True,
        variance_parameters_valid=False,
        mean_residual_autocorrelation=False,
        squared_standardized_residual_arch=False,
        normality_rejected=False,
        volatility_value_added=True,
    )

    assert result.dimensions["volatility_adequacy"].status == "rejected"
    assert result.overall_status == "rejected"


def test_short_validation_is_inconclusive_not_accepted() -> None:
    from workbench.engine.packs.arma_garch.acceptance import assess_acceptance

    result = assess_acceptance(
        forecast_metrics=_metrics(validation_n=8, successful_n=8),
        split_forecast_status="inconclusive",
        estimation_converged=True,
        finite_parameters=True,
        variance_parameters_valid=True,
        mean_residual_autocorrelation=False,
        squared_standardized_residual_arch=False,
        normality_rejected=False,
        volatility_value_added=None,
    )

    assert result.dimensions["data_readiness"].status == "inconclusive"
    assert result.dimensions["forecast_validation"].status == "inconclusive"
    assert result.overall_status == "inconclusive"


def test_normality_rejection_and_no_incremental_value_do_not_erase_successful_fit() -> None:
    from workbench.engine.packs.arma_garch.acceptance import assess_acceptance

    result = assess_acceptance(
        forecast_metrics=_metrics(),
        split_forecast_status="pending",
        estimation_converged=True,
        finite_parameters=True,
        variance_parameters_valid=True,
        mean_residual_autocorrelation=False,
        squared_standardized_residual_arch=False,
        normality_rejected=True,
        volatility_value_added=False,
    )

    assert result.dimensions["distribution_adequacy"].status == "accepted_with_warnings"
    assert result.dimensions["volatility_value_added"].status == "rejected"
    assert result.overall_status == "accepted_with_warnings"
    assert result.model_fit_succeeded is True
    json.dumps(result.to_dict(), allow_nan=False)


def test_remaining_arch_lowers_volatility_adequacy_and_payload_is_immutable() -> None:
    from workbench.engine.packs.arma_garch.acceptance import assess_acceptance

    result = assess_acceptance(
        forecast_metrics=_metrics(),
        split_forecast_status="pending",
        estimation_converged=True,
        finite_parameters=True,
        variance_parameters_valid=True,
        mean_residual_autocorrelation=False,
        squared_standardized_residual_arch=True,
        normality_rejected=False,
        volatility_value_added=True,
    )

    assert result.dimensions["volatility_adequacy"].status == "accepted_with_warnings"
    assert result.overall_status == "accepted_with_warnings"
    with pytest.raises(TypeError):
        result.dimensions["volatility_adequacy"] = result.dimensions["data_readiness"]
