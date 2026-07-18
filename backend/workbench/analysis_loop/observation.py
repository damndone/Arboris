"""Deterministic terminal observation for the OLS Agent Analysis Loop."""

from __future__ import annotations

import math
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

from ..diagnostic_preview.artifact_manifest import build_artifact_manifest
from .canonical import sha256_canonical
from .compare import ComparePacket, build_compare_packet
from .contracts import ComparisonTarget, SourceRunContract
from .plan import PlanDiff
from .resolver import ResolvedAnalysisLoopRun
from .storage import ComparePacketStore, ValidationPacketStore
from .validation import ValidationPacket, build_and_store_validation_packet


class AnalysisLoopObservationError(ValueError):
    """A terminal packet observation could not be built from persisted facts."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AnalysisLoopPacketObservation:
    """Persisted post-rerun evidence and the exact packet identities."""

    validation: ValidationPacket
    compare: ComparePacket | None
    timings_ms: Mapping[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.validation.status,
            "validation": {
                "logical_key": self.validation.logical_key,
                "status": self.validation.status,
                "overall_status": self.validation.overall_status,
            },
            "compare": (
                {
                    "logical_key": self.compare.logical_key,
                    "compare_status": self.compare.compare_status,
                    "validation_status": self.compare.validation_status,
                    "conclusion": self.compare.to_dict()["conclusion_diff"],
                }
                if self.compare is not None
                else None
            ),
        }


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def _run_snapshot(run: ResolvedAnalysisLoopRun) -> dict[str, Any]:
    result = run.result or {}
    fingerprints = {
        key: result.get(key)
        for key in (
            "dataset_snapshot_fingerprint",
            "analysis_sample_fingerprint",
            "point_estimation_fingerprint",
            "coefficient_schema_fingerprint",
        )
    }
    inference = result.get("inference_config")
    if not isinstance(inference, Mapping):
        inference = result.get("covariance_evidence")
    if not isinstance(inference, Mapping):
        inference = {}
    coefficients = result.get("coefficients")
    if not isinstance(coefficients, Mapping):
        coefficients = {}
    source_run_id = run.run_inputs.get("rerun_of") or run.manifest.get("source_run_id")
    return {
        "run_id": run.run_id,
        "status": str(run.manifest.get("status") or "unknown"),
        "source_run_id": source_run_id,
        "lineage": {
            "source_run_id": source_run_id,
            "child_run_id": run.run_id,
        },
        "fingerprints": fingerprints,
        "inference_config": dict(inference),
        "results": dict(coefficients),
        "formula": result.get("formula"),
        "y_column": result.get("y_column"),
        "x_columns": result.get("x_columns", []),
        "nobs": result.get("nobs"),
    }


def _model_evidence(child: ResolvedAnalysisLoopRun) -> dict[str, Any]:
    result = child.result
    if result is None:
        return {
            "fit": "fail" if child.manifest.get("status") != "completed" else "unknown",
            "convergence": "unknown",
            "singular": "unknown",
            "collinearity": "unknown",
            "standard_errors": "unknown",
            "nobs": "unknown",
        }
    coefficients = result.get("coefficients")
    coefficients = coefficients if isinstance(coefficients, Mapping) else {}
    standard_errors = [
        coefficient.get("std_error")
        for coefficient in coefficients.values()
        if isinstance(coefficient, Mapping)
    ]
    return {
        "fit": "pass",
        "convergence": "pass",
        "singular": "pass",
        "collinearity": "pass",
        "standard_errors": "pass"
        if standard_errors and all(_finite(value) for value in standard_errors)
        else "fail",
        "nobs": "pass" if _finite(result.get("nobs")) else "unknown",
    }


def _artifact_evidence(child: ResolvedAnalysisLoopRun) -> dict[str, Any]:
    model_results = [child.result] if child.result is not None else []
    manifest = build_artifact_manifest(child.run_root, model_results)
    lifecycle_status = str(child.manifest.get("status") or "unknown")
    complete = lifecycle_status in {"completed", "failed", "cancelled", "interrupted", "partial"}
    if child.result is None:
        complete = False
    return {
        "manifest_hash": sha256_canonical(manifest),
        "complete": complete,
        "terminal_state": "complete" if lifecycle_status == "completed" else lifecycle_status,
        "manifest": manifest,
    }


def _comparison_evidence(
    *,
    source: ResolvedAnalysisLoopRun,
    child: ResolvedAnalysisLoopRun,
    plan: PlanDiff,
) -> dict[str, Any]:
    source_result = source.result or {}
    child_result = child.result or {}
    fingerprint_names = (
        "dataset_snapshot",
        "analysis_sample",
        "point_estimation",
        "coefficient_schema",
    )
    source_fingerprints = {
        name: source_result.get(f"{name}_fingerprint") for name in fingerprint_names
    }
    child_fingerprints = {
        name: child_result.get(f"{name}_fingerprint") for name in fingerprint_names
    }
    expected = {
        "covariance": plan.wire_patch.get("covariance"),
        "entity_col": plan.wire_patch.get("entity_col"),
    }
    observed = {
        "covariance": child_result.get("covariance_wire") or child_result.get("covariance"),
        "entity_col": child_result.get("entity_col"),
    }
    source_ids = source_result.get("stable_result_ids") or []
    child_ids = child_result.get("stable_result_ids") or []
    return {
        "source_run_id": source.run_id,
        "child_run_id": child.run_id,
        "source_result_ids": list(source_ids),
        "child_result_ids": list(child_ids),
        "primary_target_id": plan.target_identity.get("result_id"),
        "source_fingerprints": source_fingerprints,
        "child_fingerprints": child_fingerprints,
        "expected_inference_config": expected,
        "observed_inference_config": observed,
    }


def build_and_store_analysis_loop_packets(
    *,
    source: SourceRunContract,
    source_run: ResolvedAnalysisLoopRun,
    child_run: ResolvedAnalysisLoopRun,
    plan: PlanDiff,
    execution_evidence: Mapping[str, Any],
    validation_store: ValidationPacketStore,
    compare_store: ComparePacketStore,
) -> AnalysisLoopPacketObservation:
    """Build and persist validation/compare packets from terminal facts only."""

    observation_started = perf_counter()
    child_snapshot = _run_snapshot(child_run)
    source_snapshot = _run_snapshot(source_run)
    artifact_evidence = _artifact_evidence(child_run)
    validation_started = perf_counter()
    validation = build_and_store_validation_packet(
        store=validation_store,
        source=source,
        child=child_snapshot,
        plan_diff=plan,
        execution_evidence=dict(execution_evidence),
        model_evidence=_model_evidence(child_run),
        artifact_evidence=artifact_evidence,
        comparison_evidence=_comparison_evidence(
            source=source_run,
            child=child_run,
            plan=plan,
        ),
    )
    validation_ms = round((perf_counter() - validation_started) * 1000, 3)
    if validation.status == "pending":
        return AnalysisLoopPacketObservation(
            validation=validation,
            compare=None,
            timings_ms={
                "validation_packet_ms": validation_ms,
                "compare_packet_ms": 0.0,
                "packet_observation_ms": round(
                    (perf_counter() - observation_started) * 1000,
                    3,
                ),
            },
        )

    target = ComparisonTarget.from_dict(plan.target_identity)
    compare_started = perf_counter()
    candidate = build_compare_packet(
        source=source_snapshot,
        child=child_snapshot,
        validation=validation,
        target=target,
    )
    compare = compare_store.build_packet(
        logical_key=candidate.logical_key,
        builder=lambda: candidate,
    )
    return AnalysisLoopPacketObservation(
        validation=validation,
        compare=compare,
        timings_ms={
            "validation_packet_ms": validation_ms,
            "compare_packet_ms": round((perf_counter() - compare_started) * 1000, 3),
            "packet_observation_ms": round(
                (perf_counter() - observation_started) * 1000,
                3,
            ),
        },
    )


__all__ = [
    "AnalysisLoopObservationError",
    "AnalysisLoopPacketObservation",
    "build_and_store_analysis_loop_packets",
]
