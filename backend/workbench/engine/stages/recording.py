from __future__ import annotations

from typing import Any

from ..context import ModelingContext, RunEnv


class RecordingStage:
    """Compute dropped-variable DecisionPoints and record the lineage graph
    nodes (cleaned stage, per-variable nodes, primary model, report).

    Extracted verbatim from orchestrator._run_workflow (the block that runs
    immediately after model estimation: ``primary_type``/``dropped_vars``
    computation through the ``_recorder.record_*`` calls) as part of the
    V1.5.4 engine decomposition. Behavior must stay byte-identical.

    All ``inputs=``/lineage in this block reference the same working modeling
    handle ids (``model_input_ids`` etc.) the original code used; the goldens
    lock these.
    """

    name = "recording"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        from ...orchestrator import (
            _check_dropped_variables,
            _model_summary,
            _variable_summary,
        )
        from ... import graph_decision_factory as dpf
        from ...graph_model import Stage

        run_root = env.run_root
        _recorder = env.recorder

        cleaned = ctx.data.frame
        model_results = ctx.artifacts["_model_results"]
        fitted_models = ctx.artifacts["_fitted_models"]
        issue_dicts = ctx.artifacts["_issue_dicts"]
        poisson_x = ctx.artifacts["_poisson_x"]
        normalized_x = ctx.artifacts["_normalized_x"]
        normalized_y = ctx.artifacts["_normalized_y"]
        categorical_vars = ctx.artifacts["_categorical_vars"]
        exposure_col = ctx.exposure_col
        raw_row_count = ctx.artifacts["_raw_row_count"]
        actions = ctx.artifacts["_actions"]
        _missing_values_dp = ctx.artifacts["_missing_values_dp"]
        _categorical_dummy_dps = ctx.artifacts["_categorical_dummy_dps"]
        _coerce_dps = ctx.artifacts["_coerce_dps"]
        _model_type_dp = ctx.artifacts["_model_type_dp"]
        _robust_se_dp = ctx.artifacts["_robust_se_dp"]

        primary_type = model_results[0][1].get("model_type", "ols") if model_results else "ols"
        drop_check_x = poisson_x if primary_type == "poisson_rate" else normalized_x
        dropped_vars = _check_dropped_variables(drop_check_x, model_results, cleaned, issue_dicts, run_root, categorical_vars=categorical_vars)

        _dropped_dps: dict[str, Any] = {}
        _dropped_reason_display: dict[str, str] = {}
        for entry in dropped_vars:
            _dropped_dps[entry["variable"]] = dpf.variable_silently_dropped(
                variable=entry["variable"],
                drop_reason=entry["reason"],
            )
            _dropped_reason_display[entry["variable"]] = entry["reason_display"]

        # -- Record lineage graph nodes with accumulated DecisionPoints ----------
        _dropped_count = raw_row_count - len(cleaned)
        _recorder.record_stage(
            node_id="stage:cleaned",
            display_label="Cleaned data",
            payload_ref="processed/cleaned_dataset.parquet",
            decision_points=(_missing_values_dp,) if _missing_values_dp else (),
            summary=(
                f"Cleaned: {len(cleaned)} rows ({_dropped_count} dropped)"
                if _dropped_count > 0 else f"Cleaned: {len(cleaned)} rows"
            ),
            stage=Stage.CLEAN,
        )
        _recorder.record_edge(
            edge_id="e:raw-cleaned",
            source_id="stage:raw",
            target_id="stage:cleaned",
            op="clean_frame",
            params={"cleaning_actions_count": len(actions)},
        )

        for var in [normalized_y, *normalized_x]:
            _cat_dp = _categorical_dummy_dps.get(var)
            _coer_dp = _coerce_dps.get(var)
            if _cat_dp is not None and _coer_dp is not None:
                import warnings as _warnings
                _warnings.warn(
                    f"Variable {var!r} has both categorical_dummy and auto_coerce "
                    f"DecisionPoints. Recording both; summary prefers categorical_dummy. "
                    f"This is unexpected — a column should not be both categorical "
                    f"and coerced-to-numeric.",
                    UserWarning, stacklevel=2,
                )
            _dps_for_var = tuple(dp for dp in (_cat_dp, _coer_dp) if dp is not None)
            _recorder.record_variable(
                node_id=f"var:{var}:cleaned",
                display_label=f"{var} (cleaned)",
                parent_stage_id="stage:cleaned",
                decision_points=_dps_for_var,
                summary=_variable_summary(_cat_dp, _coer_dp),
                stage=Stage.TRANSFORM,
            )

        for var_name, dropped_dp in _dropped_dps.items():
            _recorder.record_variable(
                node_id=f"var:{var_name}:dropped",
                display_label=f"{var_name} (dropped)",
                parent_stage_id="stage:cleaned",
                decision_points=(dropped_dp,),
                summary=f"Dropped: {_dropped_reason_display.get(var_name, 'unknown')}",
                stage=Stage.TRANSFORM,
            )

        if model_results:
            primary_model_id = model_results[0][0]
            primary_result = model_results[0][1]
            primary_model_type = primary_result.get("model_type", "ols")
            _dps_for_model = tuple(dp for dp in (_model_type_dp, _robust_se_dp) if dp is not None)
            _recorder.record_model(
                node_id=f"model:{primary_model_id}",
                display_label=f"{primary_model_type} (primary)",
                payload_ref=f"model_results/{primary_model_id}.json",
                decision_points=_dps_for_model,
                summary=_model_summary(
                    primary_model_type,
                    primary_result,
                    robust_se_dp=_robust_se_dp,
                    exposure_col=exposure_col,
                    fallback_n=len(cleaned),
                ),
                stage=Stage.MODEL,
            )
            _recorder.record_edge(
                edge_id="e:cleaned-model-primary",
                source_id="stage:cleaned",
                target_id=f"model:{primary_model_id}",
                op=f"{primary_model_type}.fit",
            )

            _recorder.record_report(
                node_id="report:html",
                display_label="HTML report",
                payload_ref="reports/report.html",
                summary="HTML report",
                stage=Stage.REPORT,
            )
            _recorder.record_edge(
                edge_id="e:model-report",
                source_id=f"model:{primary_model_id}",
                target_id="report:html",
                op="render_report",
            )

        ctx.primary_type = primary_type
        ctx.artifacts["_dropped_vars"] = dropped_vars
        return ctx
