"""A chart drawn in the conversation from numbers the Agent actually received.

The model sends a typed specification, never code; the panel draws it. Every plotted value
must already be in a tool result of this conversation, under the same rule as numbers in a
reply, so a chart cannot show a figure the analysis did not produce.
"""
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import numeric_grounding
from .session import JsonlSessionRepository
from .tools import ToolDefinition, ToolVisibleError

_TEXT = {"type": "string", "minLength": 1, "maxLength": 120}
_POINT_LIMIT = 200


def _unsupported(chart, evidence):
    values = []
    for point in chart["points"]:
        values += [point.get(key) for key in ("y", "low", "high")]
        if isinstance(point.get("x"), float) and not point["x"].is_integer():
            values.append(point["x"])
    if chart.get("reference") not in (None, 0):
        values.append(chart["reference"])
    missing = []
    for value in values:
        if value is None:
            continue
        try:
            supported = evidence.supports(Decimal(str(value)))
        except InvalidOperation:
            supported = False
        if not supported and value not in missing:
            missing.append(value)
    return missing


def chart_tool(project_root, *, session_id):
    def show_chart(arguments, context):
        if context.session_id != session_id:
            raise ToolVisibleError("CHART_SESSION_MISMATCH: use the current session's tools.")
        repository = JsonlSessionRepository(Path(project_root) / "workbench")
        messages = [entry.payload for entry in repository.get_branch(session_id)
                    if entry.entry_type in {"message", "custom_message"}]
        missing = _unsupported(arguments, numeric_grounding.evidence_from_messages(messages))
        if missing:
            raise ToolVisibleError("CHART_NUMBER_UNVERIFIED: these values are in no tool result of this conversation: "
                                   + ", ".join(map(str, missing[:12])) + ". Read the result first and plot its values.")
        if len({point.get("series") for point in arguments["points"]}) > 4:
            raise ToolVisibleError("CHART_TOO_MANY_SERIES: at most four series; split into separate charts.")
        low_high = [point for point in arguments["points"]
                    if point.get("low") is not None and point.get("high") is not None and point["low"] > point["high"]]
        if low_high:
            raise ToolVisibleError("CHART_INTERVAL_INVALID: an interval has low above high.")
        return {"shown": True, "points": len(arguments["points"]), "chart": arguments}

    return ToolDefinition(
        tool_id="show_chart", version="v1", side_effect="none",
        scope_requirements=("project",), max_output_budget=24_000,
        description="Draw a chart in the conversation when a picture says more than a table: coefficients with "
                    "intervals, a comparison across groups, an estimate across specifications or over time. Every "
                    "value must come from a tool result you already received; other values are refused. "
                    "The person sees the chart; do not repeat all its numbers in prose.",
        input_schema={"type": "object", "required": ["kind", "title", "points"], "additionalProperties": False,
            "properties": {
                "kind": {"enum": ["coefficients", "bar", "line", "scatter"]},
                "title": _TEXT,
                "x_label": _TEXT,
                "y_label": _TEXT,
                "reference": {"type": "number", "description": "A reference line, such as 0 for coefficients."},
                "points": {"type": "array", "minItems": 1, "maxItems": _POINT_LIMIT, "items": {
                    "type": "object", "required": ["y"], "additionalProperties": False,
                    "properties": {
                        "label": _TEXT, "series": _TEXT,
                        "x": {"type": "number"}, "y": {"type": "number"},
                        "low": {"type": "number"}, "high": {"type": "number"},
                    }}},
            }},
        handler=show_chart)
