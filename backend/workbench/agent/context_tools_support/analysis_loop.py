"""Analysis loop: bounded read-only context projection."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from ...analysis_loop.compare import ComparePacket
from ...analysis_loop.plan import PlanDiff
from ...analysis_loop.validation import ValidationPacket
from ...predictive_research.consumer_projection import read_prediction_evidence_from_run_root

_ANALYSIS_LOOP_SCOPES = frozenset({"inspect", "plan", "validation", "compare"})


_ANALYSIS_LOOP_SOURCE_FIELDS = frozenset({
    "run_id",
    "status",
    "model",
    "covariance",
    "primary_target",
    "diagnostics",
})


class AnalysisLoopContextError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class AnalysisLoopPacketPayloadError(AnalysisLoopContextError):
    """A JSON packet cannot cross the typed Agent context boundary."""


def _safe_analysis_loop_source_context(source_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source_context, dict):
        raise AnalysisLoopContextError(
            "source_context must be a mapping",
            code="SOURCE_CONTEXT_INVALID",
        )
    extra = set(source_context) - _ANALYSIS_LOOP_SOURCE_FIELDS
    if extra:
        raise AnalysisLoopContextError(
            "source_context contains unsupported fields",
            code="SOURCE_CONTEXT_SCOPE_VIOLATION",
        )
    return {key: source_context[key] for key in sorted(source_context)}


def _analysis_loop_packet_payload(
    packet: Any,
    expected_type: type[Any],
    scope: str,
) -> dict[str, Any] | None:
    if packet is None:
        return None
    if not isinstance(packet, expected_type):
        raise AnalysisLoopContextError(
            f"{scope} packet has an unsupported type",
            code="PACKET_TYPE_INVALID",
        )
    return packet.to_dict()


def parse_analysis_loop_packet_payloads(
    *,
    plan_diff: Any = None,
    validation_packet: Any = None,
    compare_packet: Any = None,
) -> tuple[PlanDiff | None, ValidationPacket | None, ComparePacket | None]:
    """Deserialize optional JSON packets for the read-only context seam."""

    try:
        parsed_plan = PlanDiff.from_dict(plan_diff) if plan_diff is not None else None
        parsed_validation = (
            ValidationPacket.from_dict(validation_packet)
            if validation_packet is not None
            else None
        )
        parsed_compare = (
            ComparePacket.from_dict(compare_packet)
            if compare_packet is not None
            else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisLoopPacketPayloadError(
            "analysis-loop packet payload is invalid",
            code="ANALYSIS_LOOP_PACKET_INVALID",
        ) from exc
    return parsed_plan, parsed_validation, parsed_compare


def inspect_analysis_loop_context(
    *,
    source_context: dict[str, Any],
    scope: str = "inspect",
    plan_diff: PlanDiff | None = None,
    validation_packet: ValidationPacket | None = None,
    compare_packet: ComparePacket | None = None,
) -> dict[str, Any]:
    """Return only typed, read-only context for one declared scope.

    The seam accepts packets supplied by a trusted backend resolver. It never
    reads files, calls providers, computes comparisons, or infers fields.
    """
    if type(scope) is not str or scope not in _ANALYSIS_LOOP_SCOPES:
        raise AnalysisLoopContextError(
            "unsupported analysis-loop context scope",
            code="CONTEXT_SCOPE_UNSUPPORTED",
        )
    result: dict[str, Any] = {
        "scope": scope,
        "source": _safe_analysis_loop_source_context(source_context),
    }
    if scope == "inspect":
        result["status"] = "available"
        return result
    if scope == "plan":
        payload = _analysis_loop_packet_payload(plan_diff, PlanDiff, scope)
        result.update({
            "status": "available" if payload is not None else "not_available",
            "packet": payload,
        })
    elif scope == "validation":
        payload = _analysis_loop_packet_payload(
            validation_packet,
            ValidationPacket,
            scope,
        )
        result.update({
            "status": validation_packet.status if validation_packet is not None else "absent",
            "packet": payload,
        })
    else:
        payload = _analysis_loop_packet_payload(compare_packet, ComparePacket, scope)
        result.update({
            "status": "available" if payload is not None else "not_available",
            "packet": payload,
        })
    return result


def read_prediction_research_evidence(
    run_root: Path,
    *,
    consumer: str = "agent",
) -> dict[str, Any]:
    """Read v1.8.6 prediction evidence through the shared projection."""

    return read_prediction_evidence_from_run_root(run_root, consumer=consumer)

