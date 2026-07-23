"""The published artifact vocabulary (spec §5.4).

`required` in an artifact contract may only name an artifact the system is
already known to produce. Without this, an agent that hallucinates a chart turns
a perfectly good run into a failed one — the exact inversion §5.4 forbids.

The vocabulary is declared here rather than imported from the pack because
`engine/packs/**` is not this lane's to reshape, and because a *vocabulary* is a
published promise, not an implementation detail. `tests/test_notebook_vocabulary.py`
asserts it stays exactly equal to the pack's own required-artifact set, so the
two cannot drift apart silently.

Types are the ones the artifact registry actually persists. The ARMA-GARCH pack
registers every logical time-series artifact as `time_series_json` (charts
included — they carry plot *data*, not images) and its manifest as
`time_series_manifest`. Declaring `ts.parameters` as a `table` here would read
better and be false.
"""

from __future__ import annotations

from types import MappingProxyType

_TIME_SERIES_JSON_ARTIFACTS = (
    "ts.analysis_contract",
    "ts.analysis_view_manifest",
    "ts.arma_candidates",
    "ts.arma_diagnostics",
    "ts.arma_selection",
    "ts.arma_vs_garch_comparison",
    "ts.chart.abs_return_vs_volatility",
    "ts.chart.acf",
    "ts.chart.conditional_variance",
    "ts.chart.conditional_volatility",
    "ts.chart.in_sample_interval_comparison",
    "ts.chart.model_comparison",
    "ts.chart.pacf",
    "ts.chart.qq",
    "ts.chart.quantile_exceptions",
    "ts.chart.residual_acf",
    "ts.chart.residual_pacf",
    "ts.chart.residual_series",
    "ts.chart.rolling_interval",
    "ts.chart.series_transform",
    "ts.chart.squared_residual_acf",
    "ts.chart.squared_residual_series",
    "ts.chart.squared_standardized_residual_series",
    "ts.chart.standardized_residual_series",
    "ts.conditional_series",
    "ts.data_audit",
    "ts.final_diagnostics",
    "ts.final_model",
    "ts.forecast_metrics",
    "ts.next_forecast",
    "ts.parameters",
    "ts.report",
    "ts.rolling_forecasts",
    "ts.train_validation_split",
    "ts.transform_profile",
    "ts.volatility_candidates",
    "ts.volatility_selection",
)

ARTIFACT_VOCABULARY_VERSION = "arma-garch-artifacts/v1"

DECLARED_ARTIFACT_TYPES = MappingProxyType(
    {
        **{artifact_id: "time_series_json" for artifact_id in _TIME_SERIES_JSON_ARTIFACTS},
        "ts.artifact_manifest": "time_series_manifest",
    }
)


def is_declared(artifact_id: str) -> bool:
    return artifact_id in DECLARED_ARTIFACT_TYPES


def declared_type(artifact_id: str) -> str | None:
    return DECLARED_ARTIFACT_TYPES.get(artifact_id)


__all__ = [
    "ARTIFACT_VOCABULARY_VERSION",
    "DECLARED_ARTIFACT_TYPES",
    "declared_type",
    "is_declared",
]
