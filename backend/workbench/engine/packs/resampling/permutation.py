"""Exact and Monte Carlo permutation tests over a closed statistic registry."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
import math
from typing import Any

import numpy as np

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
    MAX_EXACT_PERMUTATION_STATES,
    PERMUTATION_STATISTICS,
    ResamplingPackError,
    bounded_resamples,
    bounded_seed,
    completed_envelope,
    numeric_sample,
    two_sample_statistic,
)


PERMUTATION_ALTERNATIVES = frozenset({"two-sided", "greater", "less"})


def _reject(reason_code: str, message: str) -> None:
    raise ResamplingPackError(reason_code, message)


class _PermutationStrategy(ReplicateStrategy):
    strategy_id = "resampling.permutation.strategy.v1"

    def __init__(
        self,
        left: np.ndarray,
        right: np.ndarray,
        statistic_id: str,
        *,
        exact: bool,
    ) -> None:
        self._left_size = len(left)
        self._pooled = np.concatenate((left, right))
        self._statistic_id = statistic_id
        self._exact = exact
        self._exact_assignments = (
            tuple(combinations(range(len(self._pooled)), self._left_size))
            if exact
            else None
        )

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        if self._exact:
            assert self._exact_assignments is not None
            left_positions = self._exact_assignments[replicate_index]
            left_mask = np.zeros(len(self._pooled), dtype=bool)
            left_mask[list(left_positions)] = True
            left = self._pooled[left_mask]
            right = self._pooled[~left_mask]
        else:
            generator = np.random.default_rng(seed)
            shuffled = generator.permutation(self._pooled)
            left = shuffled[: self._left_size]
            right = shuffled[self._left_size :]
        statistic = two_sample_statistic(self._statistic_id, left, right)
        return ReplicateEvidence(scalars={"statistic": statistic})


class _PermutationAdapter(ReplicateAdapter):
    adapter_id = "resampling.permutation.adapter.v1"

    def adapt(
        self,
        evidence: ReplicateEvidence,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
    ) -> ReplicateEvidence:
        if set(evidence.scalars) != {"statistic"}:
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_FAILED", "permutation evidence schema is not declared"
            )
        statistic = evidence.scalars["statistic"]
        if type(statistic) not in {int, float} or not math.isfinite(float(statistic)):
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_FAILED", "permutation statistic must be finite"
            )
        return ReplicateEvidence(scalars={"statistic": float(statistic)})


class _PermutationCombiner(ReplicateCombiner):
    combiner_id = "permutation_null"

    def __init__(
        self,
        *,
        statistic_id: str,
        observed: float,
        alternative: str,
        exact: bool,
    ) -> None:
        self._statistic_id = statistic_id
        self._observed = observed
        self._alternative = alternative
        self._exact = exact

    def _is_extreme(self, value: float) -> bool:
        tolerance = 1e-12 * max(1.0, abs(value), abs(self._observed))
        if self._alternative == "greater":
            return value >= self._observed - tolerance
        if self._alternative == "less":
            return value <= self._observed + tolerance
        return abs(value) >= abs(self._observed) - tolerance

    def combine(
        self,
        evidence: Sequence[ReplicateEvidence],
        *,
        plan: ReplicatePlan,
        batch,
    ) -> dict[str, Any]:
        if not evidence:
            raise ReplicateCombineError(
                "RESAMPLING_TOO_FEW_REPLICATES", "permutation produced no statistics"
            )
        values = np.asarray(
            [float(item.scalars["statistic"]) for item in evidence], dtype=float
        )
        if not np.isfinite(values).all():
            raise ReplicateCombineError(
                "RESAMPLING_DEGENERATE_STATISTIC", "permutation null is not finite"
            )
        extreme_count = int(sum(self._is_extreme(float(value)) for value in values))
        if self._exact:
            p_value = extreme_count / len(values)
            semantics = "exact_inclusive_extreme_over_all_allocations"
            method = "exact"
        else:
            p_value = (extreme_count + 1) / (len(values) + 1)
            semantics = "monte_carlo_plus_one"
            method = "monte_carlo"
        return {
            "statistic_id": self._statistic_id,
            "observed_statistic": self._observed,
            "p_value": float(p_value),
            "alternative": self._alternative,
            "method": method,
            "p_value_semantics": semantics,
            "null_mean": float(np.mean(values)),
            "null_standard_error": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
            "n_resamples": plan.requested_replicates,
            "successful_resamples": len(values),
            "extreme_count": extreme_count,
        }


def run_permutation(
    left: Any,
    right: Any,
    *,
    statistic_id: str = "difference_in_means",
    n_resamples: int = 2_000,
    seed: int = 0,
    alternative: str = "two-sided",
    exact: bool = False,
) -> dict[str, Any]:
    """Run a bounded two-sample permutation test."""

    if type(statistic_id) is not str or statistic_id not in PERMUTATION_STATISTICS:
        _reject("RESAMPLING_UNSUPPORTED_STATISTIC", "statistic_id is not declared for permutation")
    if type(alternative) is not str or alternative not in PERMUTATION_ALTERNATIVES:
        _reject("RESAMPLING_INVALID_INPUT", "alternative is not declared")
    if type(exact) is not bool:
        _reject("RESAMPLING_INVALID_INPUT", "exact must be a boolean")
    left_values = numeric_sample(left, label="left")
    right_values = numeric_sample(right, label="right")
    base_seed = bounded_seed(seed)
    observed = two_sample_statistic(statistic_id, left_values, right_values)
    state_count = math.comb(len(left_values) + len(right_values), len(left_values))
    if exact:
        if state_count > MAX_EXACT_PERMUTATION_STATES:
            _reject(
                "RESAMPLING_EXACT_STATE_SPACE_EXCEEDED",
                "exact permutation state space exceeds the hard bound",
            )
        n_replicates = state_count
    else:
        n_replicates = bounded_resamples(n_resamples)

    registry = ReplicateRegistry()
    registry.register_strategy(
        _PermutationStrategy(
            left_values,
            right_values,
            statistic_id,
            exact=exact,
        )
    )
    registry.register_adapter(_PermutationAdapter())
    registry.register_combiner(
        _PermutationCombiner(
            statistic_id=statistic_id,
            observed=observed,
            alternative=alternative,
            exact=exact,
        )
    )
    plan = ReplicatePlan(
        kind="permutation",
        requested_replicates=n_replicates,
        seed=base_seed,
        strategy_id=_PermutationStrategy.strategy_id,
        adapter_id=_PermutationAdapter.adapter_id,
        combiner_id=_PermutationCombiner.combiner_id,
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
        operation_id="resampling.permutation",
        n_observations=len(left_values) + len(right_values),
        combined=combined,
        result=combined.result,
    )


__all__ = ["PERMUTATION_ALTERNATIVES", "run_permutation"]
