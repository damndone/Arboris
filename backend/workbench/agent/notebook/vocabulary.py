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

from ..recipe_contracts import RECIPE_CONTRACTS

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
CAPABILITY_ARTIFACT_VOCABULARY_VERSION = "workbench-capability-artifacts/v1"

DECLARED_ARTIFACT_TYPES = MappingProxyType(
    {
        **{artifact_id: "time_series_json" for artifact_id in _TIME_SERIES_JSON_ARTIFACTS},
        "ts.artifact_manifest": "time_series_manifest",
    }
)

# The ARMA-GARCH pack owns the historical ``ts.*`` vocabulary above.  The
# Notebook also exposes registered model capabilities whose primary result ids
# are stable and already written by the estimation stage.  Keep this second
# map separate: extending the pack-owned set would falsely claim that the pack
# produces cross-family model artifacts.
_CAPABILITY_PRIMARY_ARTIFACTS = {
    "ols": {"ols_1": "model_result"},
    "logit": {"logit_1": "model_result"},
    "probit": {"probit_1": "model_result"},
    "poisson": {"poisson_1": "model_result"},
    "negative_binomial": {"negative_binomial_1": "model_result"},
    "panel_ols": {"panel_ols_1": "model_result"},
    "iv_2sls": {"iv_2sls_1": "model_result"},
    "did": {"did_1": "model_result"},
    "cs_did": {"cs_did_1": "model_result"},
    "sa_did": {"sa_did_1": "model_result"},
    "dcdh": {"dcdh_1": "model_result"},
    "glm:binomial": {"glm_1": "model_result"},
    "glm:poisson": {"glm_1": "model_result"},
    "glm:negative_binomial": {"glm_1": "model_result"},
    "linear_mixed_effects": {
        "linear_mixed_effects_1.result": "model_result_packet"
    },
    "arma_garch_1": {"ts.artifact_manifest": "time_series_manifest"},
    **{
        contract.recipe_id: dict(contract.artifact_types)
        for contract in RECIPE_CONTRACTS.values()
    },
}
CAPABILITY_ARTIFACT_TYPES = MappingProxyType(
    {
        capability_id: MappingProxyType(dict(artifact_types))
        for capability_id, artifact_types in _CAPABILITY_PRIMARY_ARTIFACTS.items()
    }
)


def capability_artifact_types(capability_id: str) -> MappingProxyType:
    """Return the server-published artifact ids for one executable capability."""

    return CAPABILITY_ARTIFACT_TYPES.get(capability_id, MappingProxyType({}))


def is_declared(artifact_id: str) -> bool:
    return artifact_id in DECLARED_ARTIFACT_TYPES


def declared_type(artifact_id: str) -> str | None:
    return DECLARED_ARTIFACT_TYPES.get(artifact_id)


__all__ = [
    "ARTIFACT_VOCABULARY_VERSION",
    "CAPABILITY_ARTIFACT_TYPES",
    "CAPABILITY_ARTIFACT_VOCABULARY_VERSION",
    "DECLARED_ARTIFACT_TYPES",
    "capability_artifact_types",
    "declared_type",
    "is_declared",
]
