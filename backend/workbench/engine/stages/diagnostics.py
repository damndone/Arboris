from __future__ import annotations

from typing import Any

import pandas as pd

from ..context import ModelingContext, RunEnv


class DiagnosticsStage:
    """Compute per-model econometric diagnostics, run the optional prediction
    model, time-series diagnostics, and create diagnostic figures.

    Extracted verbatim from orchestrator._run_workflow (the block running from
    ``_s("diagnostics", "start")`` through the ``visualization`` complete step,
    i.e. up to — but not including — the ``narrative``/reliability block) as
    part of the V1.5.4 engine decomposition. Behavior stays byte-identical.

    Diagnostic-artifact lineage reads ``model_input_ids`` (= the single working
    handle id ``ctx.data.artifact_id``); the goldens lock this — e.g. the
    imputation golden's ``diagnostics_ols_1 -> ["imputed_dataset"]``.
    """

    name = "diagnostics"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Import workflow-level callables through the orchestrator module so
        # tests that monkeypatch ``orchestrator.<name>`` still intercept them
        # (these were module-level names in the original inline block).
        from ... import orchestrator as _orch
        from ...orchestrator import (
            _PREDICTION_MODEL_TYPES,
            _check_model_validity,
            _check_overdispersion_issue,
            _diagnostic_family,
            _model_failure_details,
        )
        from ...artifacts import register_artifact, write_json
        from ...domain import GuardrailIssue, Severity
        from ...econometrics.optional_deps import OptionalDependencyNotInstalled

        compute_diagnostics = _orch.compute_diagnostics
        run_time_series_diagnostics = _orch.run_time_series_diagnostics
        run_prediction_model = _orch.run_prediction_model
        create_figures = _orch.create_figures

        run_root = env.run_root

        modeling_frame = ctx.data.frame
        cleaned = ctx.artifacts["_cleaned"]
        normalized_x = ctx.artifacts["_normalized_x"]
        normalized_y = ctx.artifacts["_normalized_y"]
        exposure_col = ctx.exposure_col
        fitted_models = ctx.artifacts["_fitted_models"]
        model_results = ctx.artifacts["_model_results"]
        issue_dicts = ctx.artifacts["_issue_dicts"]
        model_input_ids = ctx.artifacts["_model_input_ids"]
        model_type = ctx.artifacts["_model_type"]
        config = ctx.artifacts["_config"]
        req_pred_type = ctx.artifacts.get("_prediction_model_type") or ""
        req_pred_folds = ctx.artifacts.get("_prediction_cv_folds") or 0
        req_pred_sampling = ctx.artifacts.get("_prediction_sampling_method") or ""
        routing = ctx.artifacts["_routing"]
        time_candidates = ctx.artifacts["_time_candidates"]

        env.step("diagnostics", "start", "Running regression diagnostics...")
        diag_x = [v for v in normalized_x if v != exposure_col] if exposure_col else normalized_x
        exog = modeling_frame[diag_x] if diag_x else pd.DataFrame(index=modeling_frame.index)
        diagnostic_artifacts: dict[str, dict[str, Any]] = {}
        for model_id, fitted in fitted_models.items():
            result_dict = dict(model_results)
            result = result_dict.get(model_id, {})
            fitted_model_type = result.get("model_type", "ols")
            family = _diagnostic_family(result)
            diag = compute_diagnostics(fitted, exog, model_id, model_family=family)
            diag["model_type"] = fitted_model_type
            diag_path = run_root / "model_results" / f"diagnostics_{model_id}.json"
            write_json(diag_path, diag)
            register_artifact(
                run_root,
                f"diagnostics_{model_id}",
                diag_path,
                "model_diagnostic",
                "econometrics",
                model_input_ids,
            )
            diagnostic_artifacts[model_id] = diag
            _check_model_validity(diag, model_id, issue_dicts, run_root)
            if family == "poisson":
                _check_overdispersion_issue(diag, model_id, issue_dicts, run_root)
            sep = diag.get("separation", {})
            if isinstance(sep, dict) and sep.get("warning"):
                issue_dicts.append(GuardrailIssue(
                    Severity.WARNING,
                    "SEPARATION_WARNING",
                    f"Model {model_id}: {sep['warning']} "
                    f"(converged={sep.get('converged')}, max|coef|={sep.get('max_abs_coef')}, "
                    f"max SE={sep.get('max_std_error')}). "
                    f"Consider Firth penalized likelihood or removing problematic predictors.",
                    {"model_id": model_id, **{k: v for k, v in sep.items() if v is not None}},
                ).to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})
        env.step("diagnostics", "complete", f"Diagnostics computed for {len(fitted_models)} model(s)")

        if model_type == "iv_2sls":
            from ..iv_diagnostics import build_iv_diagnostics
            iv_fitted = fitted_models.get("iv_2sls_1")
            if iv_fitted is not None:
                n_endog = len(ctx.artifacts.get("_iv_endog") or [])
                n_instr = len(ctx.artifacts.get("_iv_instruments") or [])
                iv_diag = build_iv_diagnostics(iv_fitted, n_endog, n_instr)
                iv_diag_path = run_root / "iv_diagnostics.json"
                write_json(iv_diag_path, iv_diag)
                register_artifact(
                    run_root,
                    "iv_diagnostics",
                    iv_diag_path,
                    "model_diagnostic",
                    "econometrics",
                    model_input_ids,
                )

        prediction_model_type = (
            model_type
            if model_type in _PREDICTION_MODEL_TYPES
            else req_pred_type
            or (config.prediction_model_type if config.prediction_enabled else "")
        )
        if prediction_model_type:
            prediction_model_id = f"{prediction_model_type}_1"
            cv_folds = req_pred_folds or config.prediction_cv_folds
            sampling_method = req_pred_sampling or config.prediction_sampling_method
            try:
                run_prediction_model(
                    modeling_frame,
                    run_root,
                    y=normalized_y,
                    x=normalized_x,
                    model_type=prediction_model_type,
                    model_id=prediction_model_id,
                    cv_folds=cv_folds,
                    random_seed=config.random_seed,
                    inputs=model_input_ids,
                    sampling_method=sampling_method,
                )
            except OptionalDependencyNotInstalled as dep_exc:
                # Prediction is supplementary; missing optional deps should
                # not block the econometric workflow.  Write a structured
                # issue and continue.
                details = dep_exc.to_issue_details()
                evidence = _model_failure_details(
                    model_type=prediction_model_type,
                    y=normalized_y,
                    x=normalized_x,
                    root_cause=str(dep_exc),
                    step="prediction",
                )
                evidence.update(details["details"])
                issue_dicts.append(GuardrailIssue(
                    Severity.WARNING,
                    "OPTIONAL_DEPENDENCY_MISSING",
                    str(dep_exc),
                    evidence,
                ).to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})
            except ValueError as exc:
                issue_dicts.append(GuardrailIssue(
                    Severity.WARNING,
                    "PREDICTION_FAILED",
                    str(exc),
                    _model_failure_details(
                        model_type=prediction_model_type,
                        y=normalized_y,
                        x=normalized_x,
                        root_cause=str(exc),
                        step="prediction",
                    ),
                ).to_dict())
                write_json(run_root / "errors.json", {"issues": issue_dicts})

        if routing["kind"] == "time_series" and time_candidates:
            diagnostics = run_time_series_diagnostics(
                cleaned, normalized_y, time_candidates[0]
            )
            diagnostics_path = run_root / "model_results" / "time_series_diagnostics.json"
            write_json(diagnostics_path, diagnostics)
            register_artifact(
                run_root,
                "time_series_diagnostics",
                diagnostics_path,
                "model_diagnostic",
                "econometrics",
                ["cleaned_dataset"],
            )

        if env.on_step:
            primary_result = model_results[0][1] if model_results else {}
            r2 = primary_result.get("r_squared") or primary_result.get("pseudo_r2")
            if r2 is not None:
                kind_label = "pseudo-R²" if primary_result.get("pseudo_r2") is not None else "R²"
                env.step("estimation", "complete", f"Model(s) fitted, {kind_label}={r2:.4f}")
            else:
                env.step("estimation", "complete", "Model(s) fitted")

        env.step("visualization", "start", "Creating figures...")
        numeric_columns = [
            str(column)
            for column in cleaned.select_dtypes(include="number").columns
        ]
        create_figures(
            cleaned,
            run_root,
            numeric_columns=numeric_columns,
            time_column=time_candidates[0] if time_candidates else None,
            model_results=model_results,
        )
        env.step("visualization", "complete", "Created diagnostic figures")

        ctx.artifacts["_diagnostic_artifacts"] = diagnostic_artifacts
        return ctx
