"""Bootstrap confidence intervals over a closed statistic registry."""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Any

import numpy as np
from scipy import stats

from workbench.contracts.model.replicate_combine import ReplicatePlan
from workbench.engine.replicate_combine import (
    ReplicateAdapter,
    ReplicateCombiner,
    ReplicateCombineError,
    ReplicateEvidence,
    ReplicateRegistry,
    ReplicateStrategy,
    execute_and_combine,
)

from .common import (
    BOOTSTRAP_STATISTICS,
    ResamplingPackError,
    bounded_resamples,
    bounded_seed,
    completed_envelope,
    confidence_alpha,
    numeric_sample,
    statistic_value,
)


BOOTSTRAP_INTERVAL_METHODS = frozenset({"percentile", "basic", "bca"})


def _reject(reason_code: str, message: str) -> None:
    raise ResamplingPackError(reason_code, message)


class _BootstrapStrategy(ReplicateStrategy):
    strategy_id = "resampling.bootstrap.strategy.v1"

    def __init__(self, values: np.ndarray, statistic_id: str) -> None:
        self._values = values.copy()
        self._statistic_id = statistic_id

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        generator = np.random.default_rng(seed)
        indices = generator.integers(0, len(self._values), size=len(self._values))
        statistic = statistic_value(self._statistic_id, self._values[indices])
        return ReplicateEvidence(scalars={"statistic": statistic})


class _BootstrapAdapter(ReplicateAdapter):
    adapter_id = "resampling.bootstrap.adapter.v1"

    def adapt(
        self,
        evidence: ReplicateEvidence,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
    ) -> ReplicateEvidence:
        if set(evidence.scalars) != {"statistic"}:
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_FAILED", "bootstrap evidence schema is not declared"
            )
        statistic = evidence.scalars["statistic"]
        if type(statistic) not in {int, float} or not math.isfinite(float(statistic)):
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_FAILED", "bootstrap statistic must be finite"
            )
        return ReplicateEvidence(scalars={"statistic": float(statistic)})


class _BootstrapCombiner(ReplicateCombiner):
    combiner_id = "distribution_ci"

    def __init__(
        self,
        *,
        values: np.ndarray,
        statistic_id: str,
        observed: float,
        confidence_level: float,
        interval_method: str,
    ) -> None:
        self._values = values.copy()
        self._statistic_id = statistic_id
        self._observed = observed
        self._confidence_level = confidence_level
        self._interval_method = interval_method

    def _jackknife(self) -> np.ndarray:
        if len(self._values) < 3:
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL",
                "BCa requires at least three observations for jackknife acceleration",
            )
        values = np.empty(len(self._values), dtype=float)
        for index in range(len(self._values)):
            values[index] = statistic_value(
                self._statistic_id,
                np.delete(self._values, index),
            )
        if not np.isfinite(values).all():
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL", "BCa jackknife values are not finite"
            )
        return values

    def _confidence_interval(
        self, bootstrap_values: np.ndarray
    ) -> tuple[float, float, dict[str, Any] | None, str]:
        alpha = 1.0 - self._confidence_level
        lower_probability, upper_probability = alpha / 2.0, 1.0 - alpha / 2.0
        lower_quantile, upper_quantile = np.quantile(
            bootstrap_values,
            [lower_probability, upper_probability],
            method="linear",
        )
        if self._interval_method == "percentile":
            return (
                float(lower_quantile),
                float(upper_quantile),
                None,
                "bootstrap_percentile_quantile_type_7",
            )
        if self._interval_method == "basic":
            return (
                float(2.0 * self._observed - upper_quantile),
                float(2.0 * self._observed - lower_quantile),
                None,
                "bootstrap_basic_reflection",
            )

        jackknife = self._jackknife()
        less = float(np.count_nonzero(bootstrap_values < self._observed))
        equal = float(np.count_nonzero(bootstrap_values == self._observed))
        probability = (less + 0.5 * equal) / len(bootstrap_values)
        epsilon = 1.0 / (2.0 * len(bootstrap_values))
        probability = min(1.0 - epsilon, max(epsilon, probability))
        z0 = float(stats.norm.ppf(probability))
        jackknife_mean = float(np.mean(jackknife))
        deviations = jackknife_mean - jackknife
        denominator = float(np.sum(deviations**2) ** 1.5)
        if not math.isfinite(denominator) or denominator <= 0.0:
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL",
                "BCa jackknife acceleration is undefined",
            )
        acceleration = float(np.sum(deviations**3) / (6.0 * denominator))
        if not math.isfinite(acceleration):
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL",
                "BCa acceleration is not finite",
            )

        def adjusted_probability(z_alpha: float) -> float:
            denominator = 1.0 - acceleration * (z0 + z_alpha)
            if not math.isfinite(denominator) or denominator <= 0.0:
                raise ReplicateCombineError(
                    "RESAMPLING_DEGENERATE_INTERVAL",
                    "BCa adjusted probability is undefined",
                )
            adjusted = float(stats.norm.cdf(z0 + (z0 + z_alpha) / denominator))
            if not math.isfinite(adjusted) or not 0.0 < adjusted < 1.0:
                raise ReplicateCombineError(
                    "RESAMPLING_DEGENERATE_INTERVAL",
                    "BCa adjusted probability is outside (0, 1)",
                )
            return adjusted

        adjusted_lower = adjusted_probability(float(stats.norm.ppf(lower_probability)))
        adjusted_upper = adjusted_probability(float(stats.norm.ppf(upper_probability)))
        if adjusted_lower >= adjusted_upper:
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL",
                "BCa adjusted probabilities are not ordered",
            )
        lower, upper = np.quantile(
            bootstrap_values,
            [adjusted_lower, adjusted_upper],
            method="linear",
        )
        if not np.isfinite([lower, upper]).all() or lower > upper:
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_INTERVAL", "BCa interval is not finite and ordered"
            )
        return (
            float(lower),
            float(upper),
            {
                "bias_correction": z0,
                "acceleration": acceleration,
                "jackknife_count": len(jackknife),
                "adjusted_probabilities": [adjusted_lower, adjusted_upper],
            },
            "bootstrap_bca_jackknife",
        )

    def combine(
        self,
        evidence: Sequence[ReplicateEvidence],
        *,
        plan: ReplicatePlan,
        batch,
    ) -> dict[str, Any]:
        if len(evidence) < 2:
            raise ReplicateCombineError(
                "RESAMPLING_TOO_FEW_REPLICATES", "at least two bootstrap replicates are required"
            )
        bootstrap_values = np.asarray(
            [float(item.scalars["statistic"]) for item in evidence], dtype=float
        )
        if not np.isfinite(bootstrap_values).all():
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_STATISTIC", "bootstrap distribution is not finite"
            )
        standard_error = float(np.std(bootstrap_values, ddof=1))
        lower, upper, bca, semantics = self._confidence_interval(bootstrap_values)
        result: dict[str, Any] = {
            "statistic_id": self._statistic_id,
            "estimate": self._observed,
            "standard_error": standard_error,
            "bias": float(np.mean(bootstrap_values) - self._observed),
            "confidence_level": self._confidence_level,
            "confidence_interval": [lower, upper],
            "interval_method": self._interval_method,
            "interval_semantics": semantics,
            "n_resamples": plan.requested_replicates,
            "successful_resamples": len(evidence),
        }
        if bca is not None:
            result["bca"] = bca
        return result


def run_bootstrap(
    values: Any,
    *,
    statistic_id: str = "mean",
    n_resamples: int = 2_000,
    seed: int = 0,
    confidence_level: float = 0.95,
    interval_method: str = "percentile",
) -> dict[str, Any]:
    """Run bounded bootstrap inference using a declared statistic and CI method."""

    if type(statistic_id) is not str or statistic_id not in BOOTSTRAP_STATISTICS:
        _reject("RESAMPLING_UNSUPPORTED_STATISTIC", "statistic_id is not declared for bootstrap")
    if type(interval_method) is not str or interval_method not in BOOTSTRAP_INTERVAL_METHODS:
        _reject("RESAMPLING_UNSUPPORTED_METHOD", "interval_method is not declared")
    n_replicates = bounded_resamples(n_resamples)
    base_seed = bounded_seed(seed)
    level, _alpha = confidence_alpha(confidence_level)
    sample = numeric_sample(values, label="values")
    observed = statistic_value(statistic_id, sample)

    registry = ReplicateRegistry()
    registry.register_strategy(_BootstrapStrategy(sample, statistic_id))
    registry.register_adapter(_BootstrapAdapter())
    registry.register_combiner(
        _BootstrapCombiner(
            values=sample,
            statistic_id=statistic_id,
            observed=observed,
            confidence_level=level,
            interval_method=interval_method,
        )
    )
    plan = ReplicatePlan(
        kind="bootstrap",
        requested_replicates=n_replicates,
        seed=base_seed,
        strategy_id=_BootstrapStrategy.strategy_id,
        adapter_id=_BootstrapAdapter.adapter_id,
        combiner_id=_BootstrapCombiner.combiner_id,
        max_failures=0,
        max_evidence_scalars=n_replicates,
    )
    try:
        combined = execute_and_combine(plan, registry=registry)
    except ReplicateCombineError as exc:
        raise ResamplingPackError(
            exc.reason_code if exc.reason_code.startswith("RESAMPLING_") else "RESAMPLING_BATCH_FAILED",
            str(exc),
        ) from exc
    return completed_envelope(
        operation_id="resampling.bootstrap",
        n_observations=len(sample),
        combined=combined,
        result=combined.result,
    )


__all__ = ["BOOTSTRAP_INTERVAL_METHODS", "run_bootstrap"]
