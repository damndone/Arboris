from __future__ import annotations

from ...cleaning import normalize_column_name
from ...router import detect_y_kind
from ..context import ModelingContext, RunEnv


class YTypeStage:
    """Detect the y variable type, honoring the 1.5.3.2 explicit model_type
    routing contract.

    Extracted verbatim from orchestrator._run_workflow (the y_type block) as
    part of the V1.5.4 engine decomposition. Behavior must stay byte-identical.
    """

    name = "ytype"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Lazy import to avoid a module-load cycle: orchestrator imports this
        # stage at the top of its module, while these helpers live there.
        from ...orchestrator import (
            _map_model_type,
            _validate_requested_model_type,
            dpf,
        )

        cleaned = ctx.data.frame
        y = ctx.y_col
        x = ctx.x_cols
        model_type = ctx.requested_model_type

        env.step("y_type", "start", "Detecting y variable type...")
        normalized_y = normalize_column_name(y)
        normalized_x = [normalize_column_name(column) for column in x]

        _missing_values_dp = dpf.handle_missing_values(
            variables=[normalized_y, *normalized_x],
        )

        if normalized_y in cleaned.columns:
            data_detected_y_type = detect_y_kind(cleaned, normalized_y).value
        else:
            data_detected_y_type = "continuous"

        # v1.8.7 A2. A declared measurement level is executed, not weighed
        # against the detector: `1,2,3,4` is a rating, a count, a coded region
        # or a grade depending only on how it was measured, and the user is the
        # one who knows. Undeclared columns route exactly as before.
        declared_level = _declared_level(ctx, normalized_y)
        if declared_level:
            data_detected_y_type = _LEVEL_TO_Y_TYPE.get(
                declared_level, data_detected_y_type
            )
        glm_family = _validate_requested_model_type(model_type)
        if model_type != "auto":
            # Explicit model type: use its mapped y_type when defined; for
            # data-driven types (e.g. glm:*) _map_model_type returns None, so
            # fall back to the detected y_type (keeps y_type data-driven per spec §5).
            y_type = _map_model_type(model_type) or data_detected_y_type
            _model_type_dp = None
        else:
            y_type = data_detected_y_type
            _model_type_dp = dpf.model_type_auto_select(
                selected=y_type,
                y_unique=int(cleaned[normalized_y].nunique()) if normalized_y in cleaned.columns else 0,
                y_dtype=str(cleaned[normalized_y].dtype) if normalized_y in cleaned.columns else "unknown",
            )
        env.step("y_type", "complete", f"y classified as {y_type}")

        ctx.y_type = y_type
        ctx.artifacts["_normalized_y"] = normalized_y
        ctx.artifacts["_normalized_x"] = normalized_x
        ctx.artifacts["_missing_values_dp"] = _missing_values_dp
        ctx.artifacts["_data_detected_y_type"] = data_detected_y_type
        ctx.artifacts["_glm_family"] = glm_family
        ctx.artifacts["_model_type_dp"] = _model_type_dp
        ctx.artifacts["_declared_measurement_level"] = declared_level
        _write_measurement_advisory(
            ctx, env, frame=cleaned, y=normalized_y, x=normalized_x, routed_as=y_type
        )
        return ctx


#: A declared level names a y-type; the estimation stage already routes on that,
#: so this is the whole of the wiring rather than a second dispatch table.
_LEVEL_TO_Y_TYPE = {
    "ordinal": "ordinal",
    "nominal": "nominal",
    "count": "count",
    "scale": "continuous",
}


def _declared_level(ctx: ModelingContext, column: str) -> str | None:
    labels = ctx.artifacts.get("_labels") or {}
    if not isinstance(labels, dict):
        return None
    levels = labels.get("measurement_level") or {}
    if not isinstance(levels, dict):
        return None
    declared = levels.get(column)
    if not declared or declared == "unspecified":
        return None
    return str(declared)


def _write_measurement_advisory(
    ctx: ModelingContext,
    env: RunEnv,
    *,
    frame,
    y: str,
    x: list[str],
    routed_as: str,
) -> None:
    """Say what was assumed, for the columns nobody declared.

    Only written when there is something to raise: an advisory attached to every
    run teaches users to close it unread, which costs more than silence.
    """
    from ...artifacts import register_artifact, write_json
    from ...measurement import build_advisory

    labels = ctx.artifacts.get("_labels") or {}
    labels = labels if isinstance(labels, dict) else {}

    advisory = build_advisory(
        frame,
        [y, *x],
        declared=labels.get("measurement_level") or {},
        routed_as={y: routed_as},
        value_labels=labels.get("value_labels") or {},
        variable_labels=labels.get("variable_labels") or {},
    )
    if not advisory["entries"]:
        return

    path = env.run_root / "measurement" / "advisory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, advisory)
    register_artifact(
        env.run_root, "measurement_advisory", path, "measurement_advisory", "ytype",
        ["cleaned_dataset"],
    )
