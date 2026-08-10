"""Bounded execution over code-registered replicate strategies."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
from typing import Any

from workbench.contracts.model.replicate_combine import MAX_EVIDENCE_SCALARS, ReplicatePlan

from .combiners import dispatch_combiner
from .errors import STABLE_FAILURE_REASONS, ReplicateCombineError, ReplicateExecutionError
from .types import (
    ReplicateAdapter,
    ReplicateBatch,
    ReplicateCombiner,
    ReplicateCombinedResult,
    ReplicateEvidence,
    ReplicateStrategy,
    _batch_digest,
    evidence_commitment,
    compute_provenance_commitment,
    validate_scalar_evidence,
)


class ReplicateRegistry:
    """Closed runtime registry for typed strategy and adapter objects."""

    def __init__(self) -> None:
        self._strategies: dict[str, ReplicateStrategy] = {}
        self._adapters: dict[str, ReplicateAdapter] = {}
        self._combiners: dict[str, ReplicateCombiner] = {}

    def register_strategy(self, strategy: ReplicateStrategy) -> None:
        if not isinstance(strategy, ReplicateStrategy):
            raise ReplicateCombineError(
                "REPLICATE_STRATEGY_NOT_TYPED", "strategy must implement ReplicateStrategy"
            )
        strategy_id = getattr(strategy, "strategy_id", None)
        if type(strategy_id) is not str or not strategy_id:
            raise ReplicateCombineError("REPLICATE_STRATEGY_NOT_TYPED", "strategy_id is required")
        self._strategies[strategy_id] = strategy

    def register_adapter(self, adapter: ReplicateAdapter) -> None:
        if not isinstance(adapter, ReplicateAdapter):
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_NOT_TYPED", "adapter must implement ReplicateAdapter"
            )
        adapter_id = getattr(adapter, "adapter_id", None)
        if type(adapter_id) is not str or not adapter_id:
            raise ReplicateCombineError("REPLICATE_ADAPTER_NOT_TYPED", "adapter_id is required")
        self._adapters[adapter_id] = adapter

    def register_combiner(self, combiner: ReplicateCombiner) -> None:
        if not isinstance(combiner, ReplicateCombiner):
            raise ReplicateCombineError(
                "REPLICATE_COMBINER_NOT_TYPED", "combiner must implement ReplicateCombiner"
            )
        combiner_id = getattr(combiner, "combiner_id", None)
        if type(combiner_id) is not str or not combiner_id:
            raise ReplicateCombineError("REPLICATE_COMBINER_NOT_TYPED", "combiner_id is required")
        self._combiners[combiner_id] = combiner

    def strategy(self, strategy_id: str) -> ReplicateStrategy:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            raise ReplicateCombineError(
                "REPLICATE_STRATEGY_NOT_REGISTERED", "strategy_id is not registered"
            ) from exc

    def adapter(self, adapter_id: str) -> ReplicateAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise ReplicateCombineError(
                "REPLICATE_ADAPTER_NOT_REGISTERED", "adapter_id is not registered"
            ) from exc

    def combiner(self, combiner_id: str) -> ReplicateCombiner:
        try:
            return self._combiners[combiner_id]
        except KeyError as exc:
            raise ReplicateCombineError(
                "REPLICATE_COMBINER_NOT_REGISTERED", "combiner_id is not registered"
            ) from exc


def _derive_seed(base_seed: int, replicate_index: int) -> int:
    material = f"replicate-combine:v1:{base_seed}:{replicate_index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & ((1 << 63) - 1)


def _empty_provenance(plan: ReplicatePlan, *, derived_seeds: list[int], order: list[int], count: int, records: list[Mapping[str, Any]]) -> dict[str, Any]:
    public_provenance = {
        "strategy_id": plan.strategy_id,
        "adapter_id": plan.adapter_id,
        "base_seed": plan.seed,
        "derived_seeds": list(derived_seeds),
        "replicate_order": list(order),
        "evidence_scalar_count": count,
        "evidence_commitment": evidence_commitment(records),
    }
    return public_provenance


def _make_batch(
    *,
    plan: ReplicatePlan,
    status: str,
    reason_code: str,
    succeeded: int,
    failed: int,
    failure_reasons: Mapping[str, int],
    provenance: Mapping[str, Any],
) -> ReplicateBatch:
    public_provenance = {
        key: value for key, value in provenance.items() if key != "provenance_commitment"
    }
    committed_provenance = public_provenance | {
        "provenance_commitment": compute_provenance_commitment(
            public_provenance,
            context={
                "requested_count": plan.requested_replicates,
                "succeeded_count": succeeded,
                "failed_count": failed,
                "status": status,
                "reason_code": reason_code,
            },
        ),
    }
    base_payload: dict[str, Any] = {
        "contract": "replicate_combine.batch",
        "contract_version": "1.0",
        "kind": plan.kind,
        "requested_count": plan.requested_replicates,
        "succeeded_count": succeeded,
        "failed_count": failed,
        "seed": plan.seed,
        "status": status,
        "reason_code": reason_code,
        "failure_reasons": dict(failure_reasons),
        "provenance": committed_provenance,
    }
    digest = None if status == "failed" else _batch_digest(base_payload)
    return ReplicateBatch(
        kind=plan.kind,
        requested_count=plan.requested_replicates,
        succeeded_count=succeeded,
        failed_count=failed,
        seed=plan.seed,
        status=status,
        reason_code=reason_code,
        failure_reasons=dict(failure_reasons),
        provenance=committed_provenance,
        digest=digest,
    )


def _execute_internal(
    plan: ReplicatePlan, *, registry: ReplicateRegistry
) -> tuple[ReplicateBatch, tuple[ReplicateEvidence, ...]]:
    """Execute a plan and retain adapted evidence only for an internal combiner."""

    if not isinstance(plan, ReplicatePlan):
        raise ReplicateCombineError("REPLICATE_INVALID_PLAN", "plan must be a ReplicatePlan")
    if not isinstance(registry, ReplicateRegistry):
        raise ReplicateCombineError("REPLICATE_INVALID_REGISTRY", "registry is not typed")
    # Validate the declared combiner without invoking any mathematical combiner.
    dispatch_combiner(plan.combiner_id)
    strategy = registry.strategy(plan.strategy_id)
    adapter = registry.adapter(plan.adapter_id)

    if plan.max_evidence_scalars == 0:
        provenance = _empty_provenance(
            plan,
            derived_seeds=[],
            order=[],
            count=0,
            records=[{"status": "evidence_budget_exceeded"}],
        )
        return _make_batch(
            plan=plan,
            status="failed",
            reason_code="REPLICATE_EVIDENCE_BUDGET_EXCEEDED",
            succeeded=0,
            failed=0,
            failure_reasons={},
            provenance=provenance,
        ), ()

    derived_seeds: list[int] = []
    order = list(range(plan.requested_replicates))
    records: list[Mapping[str, Any]] = []
    failure_reasons: Counter[str] = Counter()
    scalar_count = 0
    succeeded = 0
    adapted_evidence: list[ReplicateEvidence] = []

    for replicate_index in range(plan.requested_replicates):
        seed = _derive_seed(plan.seed, replicate_index)
        derived_seeds.append(seed)
        try:
            raw_evidence = strategy.generate(
                plan=plan,
                replicate_index=replicate_index,
                seed=seed,
            )
        except ReplicateExecutionError as exc:
            reason_code = (
                exc.reason_code
                if exc.reason_code in STABLE_FAILURE_REASONS
                else "REPLICATE_STRATEGY_FAILED"
            )
            failure_reasons[reason_code] += 1
            records.append(
                {"index": replicate_index, "seed": seed, "status": "failed", "reason_code": reason_code}
            )
            continue
        except Exception:
            failure_reasons["REPLICATE_STRATEGY_EXCEPTION"] += 1
            records.append(
                {
                    "index": replicate_index,
                    "seed": seed,
                    "status": "failed",
                    "reason_code": "REPLICATE_STRATEGY_EXCEPTION",
                }
            )
            continue

        raw_scalar_count = len(validate_scalar_evidence(raw_evidence))
        if raw_scalar_count > MAX_EVIDENCE_SCALARS:
            raise ReplicateCombineError(
                "REPLICATE_EVIDENCE_BUDGET_EXCEEDED", "strategy scalar evidence exceeds the hard limit"
            )
        try:
            adapted = adapter.adapt(
                raw_evidence,
                plan=plan,
                replicate_index=replicate_index,
            )
        except ReplicateExecutionError as exc:
            reason_code = (
                exc.reason_code
                if exc.reason_code in STABLE_FAILURE_REASONS
                else "REPLICATE_ADAPTER_FAILED"
            )
            failure_reasons[reason_code] += 1
            records.append(
                {"index": replicate_index, "seed": seed, "status": "failed", "reason_code": reason_code}
            )
            continue
        except Exception:
            failure_reasons["REPLICATE_ADAPTER_EXCEPTION"] += 1
            records.append(
                {
                    "index": replicate_index,
                    "seed": seed,
                    "status": "failed",
                    "reason_code": "REPLICATE_ADAPTER_EXCEPTION",
                }
            )
            continue
        normalized = validate_scalar_evidence(adapted)
        scalar_count += len(normalized)
        if scalar_count > plan.max_evidence_scalars:
            raise ReplicateCombineError(
                "REPLICATE_EVIDENCE_BUDGET_EXCEEDED", "bounded scalar evidence budget exceeded"
            )
        # Keep only the adapter-consumed values for the commitment.  Raw
        # strategy evidence is validated above but never enters the digest.
        records.append(
            {
                "index": replicate_index,
                "seed": seed,
                "status": "completed",
                "adapter": normalized,
            }
        )
        adapted_evidence.append(ReplicateEvidence(scalars=normalized))
        succeeded += 1

    failed = plan.requested_replicates - succeeded
    failure_map = dict(sorted(failure_reasons.items()))
    if failed == 0:
        status = "completed"
        reason_code = "REPLICATE_COMPLETED"
    elif failed <= plan.max_failures:
        status = "completed_with_failures"
        reason_code = "REPLICATE_PARTIAL_FAILURE"
    else:
        status = "failed"
        reason_code = "REPLICATE_FAILURE_BUDGET_EXCEEDED"
    provenance = _empty_provenance(
        plan,
        derived_seeds=derived_seeds,
        order=order,
        count=scalar_count,
        records=records,
    )
    return (
        _make_batch(
            plan=plan,
            status=status,
            reason_code=reason_code,
            succeeded=succeeded,
            failed=failed,
            failure_reasons=failure_map,
            provenance=provenance,
        ),
        tuple(adapted_evidence),
    )


def execute(plan: ReplicatePlan, *, registry: ReplicateRegistry) -> ReplicateBatch:
    """Execute a bounded plan and publish only aggregate provenance."""

    batch, _evidence = _execute_internal(plan, registry=registry)
    return batch


def execute_and_combine(
    plan: ReplicatePlan, *, registry: ReplicateRegistry
) -> ReplicateCombinedResult:
    """Execute and combine through the declared code-registered combiner.

    Adapted scalar evidence stays inside this function.  The returned object
    contains only the aggregate result and the public batch provenance.
    """

    if not isinstance(plan, ReplicatePlan):
        raise ReplicateCombineError("REPLICATE_INVALID_PLAN", "plan must be a ReplicatePlan")
    if not isinstance(registry, ReplicateRegistry):
        raise ReplicateCombineError("REPLICATE_INVALID_REGISTRY", "registry is not typed")
    dispatch_combiner(plan.combiner_id)
    combiner = registry.combiner(plan.combiner_id)
    batch, evidence = _execute_internal(plan, registry=registry)
    if batch.status == "failed":
        raise ReplicateCombineError(
            "REPLICATE_COMBINE_UNAVAILABLE",
            "a failed replicate batch cannot be combined",
        )
    try:
        result = combiner.combine(evidence, plan=plan, batch=batch)
    except ReplicateCombineError:
        raise
    except Exception as exc:
        raise ReplicateCombineError(
            "REPLICATE_COMBINER_FAILED", "combiner failed closed"
        ) from exc
    return ReplicateCombinedResult(batch=batch, result=result)


__all__ = ["ReplicateRegistry", "execute", "execute_and_combine"]
