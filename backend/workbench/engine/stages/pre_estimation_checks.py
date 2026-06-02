from __future__ import annotations

from typing import Any

from ..context import ModelingContext, RunEnv


class PreEstimationChecksStage:
    """Pre-estimation model-column validation, X-column numeric coercion,
    and categorical-X detection.

    Extracted verbatim from orchestrator._run_workflow (the block previously
    inlined between YTypeStage and RoleInferenceStage) as part of the V1.5.4
    engine decomposition. Behavior must stay byte-identical.

    Three responsibilities, in order:
      1. ``_model_column_issue`` check — if the user-requested y/x cannot be
         resolved against the cleaned frame, short-circuit ``blocked`` (writes
         errors.json + manifest, flushes recorder).
      2. ``_coerce_x_columns_to_numeric`` — coerce string-typed X columns that
         look numeric. Builds the ``_coerce_dps`` DecisionPoints used by the
         RecordingStage lineage graph.
      3. ``_detect_categorical_x_vars`` — pick out C() encoding candidates and
         build the ``_categorical_dummy_dps`` lineage DecisionPoints.

    All produced locals are stashed into ``ctx.artifacts`` so later stages
    (Estimation, Recording) can read them without bridge re-binding in the
    orchestrator.
    """

    name = "pre_estimation_checks"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        from ...orchestrator import (
            _model_column_issue,
            _coerce_x_columns_to_numeric,
            _detect_categorical_x_vars,
            _write_manifest,
            _safe_flush_recorder,
            _lineage,
            dpf,
        )
        from ...artifacts import write_json

        cleaned = ctx.data.frame
        normalized_y = ctx.artifacts["_normalized_y"]
        normalized_x = ctx.artifacts["_normalized_x"]
        actions = ctx.artifacts["_actions"]
        issue_dicts = ctx.artifacts["_issue_dicts"]
        y = ctx.artifacts["_y"]
        x = ctx.artifacts["_x"]
        model_type = ctx.artifacts["_model_type"]
        input_files = ctx.artifacts["_input_files"]
        mode = ctx.artifacts["_mode"]
        started_at = ctx.artifacts["_started_at"]
        run_root = env.run_root
        run_id = env.run_id

        env.step("model_check", "start", "Checking model columns...")
        model_issue = _model_column_issue(cleaned, normalized_y, normalized_x, y, x)
        if model_issue is not None:
            issue_dicts.append(model_issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
            env.step("model_check", "blocked", "Requested model columns not found")
            _write_manifest(
                run_root,
                run_id,
                mode,
                "blocked",
                _lineage(input_files),
                started_at=started_at,
                y=y,
                x=x,
                requested_model_type=model_type,
            )
            _safe_flush_recorder(env.recorder, context="blocked@model_check")
            ctx.terminal_status = "blocked"
            return ctx
        env.step("model_check", "complete", "Model columns valid")

        coercion_actions = _coerce_x_columns_to_numeric(cleaned, normalized_x, run_root)

        _coerce_dps: dict[str, Any] = {}
        for action in [*actions, *coercion_actions]:
            if action.get("action") != "coerce_to_numeric" and "conversion_rate" not in action:
                continue
            col = action.get("column")
            if not col:
                continue
            if col not in normalized_x:
                continue
            _coerce_dps[col] = dpf.auto_coerce_to_numeric(
                variable=col,
                conversion_rate=action["conversion_rate"],
            )

        # Detect categorical X variables for C() encoding in model formula
        categorical_vars = _detect_categorical_x_vars(cleaned, normalized_x)

        _categorical_dummy_dps: dict[str, Any] = {}
        for cat_var in categorical_vars:
            if cat_var in cleaned.columns:
                uniques = cleaned[cat_var].dropna().unique()
                # Mixed-dtype object columns can't be sorted directly (TypeError);
                # coerce to str for the audit-trail reference level.
                ref = sorted(map(str, uniques))[0] if len(uniques) else "?"
            else:
                ref = "?"
            _categorical_dummy_dps[cat_var] = dpf.categorical_auto_dummy(
                variable=cat_var,
                n_unique=int(cleaned[cat_var].nunique()) if cat_var in cleaned.columns else 0,
                reference_level=str(ref),
            )

        ctx.artifacts["_coercion_actions"] = coercion_actions
        ctx.artifacts["_coerce_dps"] = _coerce_dps
        ctx.artifacts["_categorical_vars"] = categorical_vars
        ctx.artifacts["_categorical_dummy_dps"] = _categorical_dummy_dps
        return ctx
