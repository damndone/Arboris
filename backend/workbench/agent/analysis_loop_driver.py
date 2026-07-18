"""Pure typed intent classification for the Agent Analysis Loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any, Literal, TYPE_CHECKING

from ..analysis_loop.recovery import RECOVERY_ACTION_REGISTRY

if TYPE_CHECKING:
    from ..analysis_loop.compare import ComparePacket
    from ..analysis_loop.plan import PlanDiff
    from ..analysis_loop.validation import ValidationPacket


IntentKind = Literal["ask", "rerun", "compare"]

_SUPPORTED_INTENTS = frozenset({"ask", "rerun", "compare"})
_SUPPORTED_FIELDS = frozenset(
    {"intent", "action_id", "cluster_variable", "result_id", "patch", "target"}
)


@dataclass(frozen=True)
class AnalysisLoopPackets:
    """Opaque backend packets carried through the thin driver unchanged."""

    plan_diff: PlanDiff | None = None
    validation_packet: ValidationPacket | None = None
    compare_packet: ComparePacket | None = None


@dataclass(frozen=True)
class TypedAnalysisIntent:
    """The only intent shape the thin driver is allowed to forward."""

    kind: IntentKind
    action_id: str | None = None
    cluster_variable: str | None = None
    result_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _SUPPORTED_INTENTS:
            raise ValueError("unsupported analysis-loop intent")

    def to_dict(self) -> dict[str, str]:
        result = {"kind": self.kind}
        if self.action_id is not None:
            result["action_id"] = self.action_id
        if self.cluster_variable is not None:
            result["cluster_variable"] = self.cluster_variable
        if self.result_id is not None:
            result["result_id"] = self.result_id
        return result


@dataclass(frozen=True)
class IntentRejection:
    """Machine-readable fail-closed rejection returned by the driver."""

    code: str
    message: str
    field: str | None = None
    details: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class AnalysisLoopDecision:
    """Classification result plus optional packet passthrough."""

    accepted: bool
    intent: TypedAnalysisIntent | None = None
    rejection: IntentRejection | None = None
    packets: AnalysisLoopPackets | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "intent": self.intent.to_dict() if self.intent is not None else None,
            "rejection": (
                self.rejection.to_dict() if self.rejection is not None else None
            ),
        }


def _rejected(
    code: str,
    message: str,
    *,
    field_name: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> AnalysisLoopDecision:
    return AnalysisLoopDecision(
        accepted=False,
        rejection=IntentRejection(
            code=code,
            field=field_name,
            message=message,
            details=dict(details or {}),
        ),
    )


def classify_analysis_intent(value: Mapping[str, Any]) -> AnalysisLoopDecision:
    """Classify a typed intent without parsing prose or consulting state."""

    if not isinstance(value, Mapping):
        return _rejected(
            "INTENT_NOT_OBJECT",
            "the analysis-loop intent must be an object",
        )

    if "patch" in value:
        return _rejected(
            "UNSUPPORTED_PATCH",
            "analysis-loop patches are not accepted by the thin driver",
            field_name="patch",
        )
    if "target" in value:
        return _rejected(
            "FUZZY_TARGET",
            "comparison targets must be forwarded as an exact result_id",
            field_name="target",
        )

    extra_fields = set(value) - _SUPPORTED_FIELDS
    if extra_fields:
        return _rejected(
            "UNSUPPORTED_INTENT_FIELD",
            "the intent contains unsupported field(s)",
            details={"fields": sorted(str(item) for item in extra_fields)},
        )

    kind = value.get("intent")
    if type(kind) is not str or kind not in _SUPPORTED_INTENTS:
        return _rejected(
            "UNSUPPORTED_INTENT",
            "only ask, rerun, and compare intents are supported",
            field_name="intent",
            details={"received": kind},
        )

    action_id = value.get("action_id")
    if action_id is not None and (type(action_id) is not str or not action_id):
        return _rejected(
            "ACTION_ID_REQUIRED",
            "action_id must be a non-empty registered action id",
            field_name="action_id",
        )
    if action_id is not None and RECOVERY_ACTION_REGISTRY.get(action_id) is None:
        return _rejected(
            "UNSUPPORTED_ACTION",
            "action_id is not registered for the analysis loop",
            field_name="action_id",
            details={"received": action_id, "registered": list(RECOVERY_ACTION_REGISTRY.action_ids)},
        )
    if action_id is not None and kind != "rerun":
        return _rejected(
            "ACTION_INTENT_MISMATCH",
            "the registered covariance action can only accompany a rerun intent",
            field_name="action_id",
        )

    cluster_variable = value.get("cluster_variable")
    if cluster_variable is not None and (
        type(cluster_variable) is not str or not cluster_variable
    ):
        return _rejected(
            "EXACT_CLUSTER_VARIABLE_REQUIRED",
            "cluster_variable must be a non-empty exact string",
            field_name="cluster_variable",
        )
    if kind == "rerun" and cluster_variable is None:
        return _rejected(
            "EXACT_CLUSTER_VARIABLE_REQUIRED",
            "rerun requires an exact cluster_variable",
            field_name="cluster_variable",
        )

    result_id = value.get("result_id")
    if result_id is not None and (type(result_id) is not str or not result_id):
        return _rejected(
            "EXACT_RESULT_ID_REQUIRED",
            "result_id must be a non-empty exact string",
            field_name="result_id",
        )
    if kind == "compare" and result_id is None:
        return _rejected(
            "EXACT_RESULT_ID_REQUIRED",
            "compare requires an exact result_id",
            field_name="result_id",
        )

    return AnalysisLoopDecision(
        accepted=True,
        intent=TypedAnalysisIntent(
            kind=kind,
            action_id=action_id,
            cluster_variable=cluster_variable,
            result_id=result_id,
        ),
    )


def forward_analysis_intent(
    value: Mapping[str, Any],
    *,
    packets: AnalysisLoopPackets | None = None,
) -> AnalysisLoopDecision:
    """Forward only a classified intent and carry packets without inspection."""

    return replace(classify_analysis_intent(value), packets=packets)


__all__ = [
    "AnalysisLoopDecision",
    "AnalysisLoopPackets",
    "IntentKind",
    "IntentRejection",
    "TypedAnalysisIntent",
    "classify_analysis_intent",
    "forward_analysis_intent",
]
