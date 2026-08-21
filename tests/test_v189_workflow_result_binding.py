from __future__ import annotations

from pathlib import Path

import pytest


def _artifact_backed_result() -> dict[str, object]:
    refit_summary = {
        "fit_scope": "all_available_observations",
        "nobs": 120,
        "effective_sample": 119,
        "converged": True,
        "finite_parameters": True,
        "parameters": {
            "const": 0.1,
            "omega": 0.2,
        },
        "convergence_details": {
            "optimization_flag": 0,
            "optimization_message": "converged",
        },
    }
    return {
        "model_type": "time_series.arma_garch",
        "model_id": "arma_garch_1",
        "status": "accepted",
        "nobs": 120,
        "artifact_refs": {
            "ts.artifact_manifest": "artifacts/time_series/ts.artifact_manifest.json",
            "ts.final_model": "artifacts/time_series/ts.final_model.json",
            "ts.forecast_metrics": "artifacts/time_series/ts.forecast_metrics.json",
            "ts.next_forecast": "artifacts/time_series/ts.next_forecast.json",
            "ts.report": "artifacts/time_series/ts.report.json",
        },
        "validation": {
            "data_role": "independent_evaluation_after_selection",
            "candidate_selection_used_validation": False,
            "metrics": {
                "validation_n": 20,
                "successful_forecast_n": 20,
                "mae": 1.0,
                "rmse": 1.2,
                "mean_error": 0.0,
                "interval_coverage": 0.9,
                "average_interval_width": 2.0,
                "coverage_count": 18,
                "coverage_uncertainty": {
                    "method": "wilson_95pct",
                    "lower": 0.7,
                    "upper": 1.0,
                },
                "exception_rate": 0.1,
                "exception_count": 2,
                "pinball_loss": 0.4,
            },
                "acceptance": {
                    "overall_status": "accepted",
                    "model_fit_succeeded": True,
                    "dimensions": {
                        name: {
                            "status": "accepted",
                            "reasons": ["fixture evidence"],
                            "evidence": {"source": "fixture"},
                        }
                        for name in (
                            "data_readiness",
                            "mean_adequacy",
                            "volatility_adequacy",
                            "distribution_adequacy",
                            "forecast_validation",
                            "volatility_value_added",
                        )
                    },
                },
        },
        "production_child": {
            "result_id": "arma_garch_1:production-final",
            "result_role": "production_final_child",
            "parent_result_id": "arma_garch_1",
            "does_not_overwrite_parent": True,
            "fit_scope": "all_available_observations",
            "validation_metrics_recomputed": False,
            "refit_summary": refit_summary,
            "next_forecast": {
                "forecast_origin": {"row_id": "row-119", "time": "2026-01-01T00:00:00Z"},
                "target_label": "next_observation",
                "target_time": "2026-01-02T00:00:00Z",
                "conditional_mean": 1.0,
                "conditional_variance": 2.0,
                "conditional_volatility": 1.4,
                "lower_bound": -1.0,
                "upper_bound": 3.0,
                "lower_quantile": -0.8,
                "model_scale": "transformed",
                "original_scale": {
                    "transform": "level",
                    "backtransform_method": "identity",
                    "point_statistic": "conditional_mean",
                    "point_or_median": 1.0,
                    "lower_bound": -1.0,
                    "upper_bound": 3.0,
                    "lower_quantile": -0.8,
                    "variance_available": False,
                },
                "frozen_spec": {
                    "mean_candidate_id": "arma_1_0",
                    "mean_order": [1, 0],
                    "mean_constant": True,
                    "variance_candidate_id": "garch_1_1",
                    "variance_model": "garch",
                    "variance_order": [1, 1],
                    "innovation_distribution": "normal",
                    "resolved_strategy": "sequential_arma_garch",
                    "hold_back": 1,
                    "transform": "level",
                },
                "refit_summary": refit_summary,
                "fit_method": "full_sample_refit",
                "predictive_interval": "plugin_conditional",
                "parameter_uncertainty_included": False,
                "warning": None,
            },
        },
    }


def _materialize_indexed_artifacts(run_root: Path, result: dict[str, object]) -> None:
    from workbench.artifacts import initialize_artifact_index, register_artifact, write_json

    initialize_artifact_index(run_root)
    refs = result["artifact_refs"]
    assert isinstance(refs, dict)
    for artifact_id, relative_path in refs.items():
        assert isinstance(artifact_id, str)
        assert isinstance(relative_path, str)
        path = run_root / relative_path
        write_json(path, {"artifact_id": artifact_id, "payload": {"source": artifact_id}})
        register_artifact(run_root, artifact_id, path, "time_series_json", "arma_garch", ["raw_input"])


def test_artifact_backed_result_binding_is_typed_and_does_not_invent_coefficients(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    attach_result_binding(
        run_root,
        "run-1",
        "arma_garch_1",
        result,
        ["raw_input"],
        strategy_key="artifact_backed_v1",
        expected_model_type="time_series.arma_garch",
    )

    binding = result["result_binding"]
    assert isinstance(binding, dict)
    assert binding["strategy"] == "artifact_backed_v1"
    assert binding["source_artifact_ids"] == ["raw_input"]
    assert "coefficients" not in result
    assert binding["production_child_id"] == "arma_garch_1:production-final"
    assert isinstance(binding["production_child_digest"], str)
    assert isinstance(binding["validation_digest"], str)
    assert set(binding["result_artifact_sha256"]) == set(result["artifact_refs"])
    assert binding["result_artifact_bindings"]["ts.report"]["path"] == result["artifact_refs"]["ts.report"]  # type: ignore[index]


def test_artifact_backed_binding_rejects_indexed_content_tampering(tmp_path: Path) -> None:
    from workbench.artifacts import write_json
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    write_json(
        run_root / result["artifact_refs"]["ts.report"],  # type: ignore[index]
        {"artifact_id": "ts.report", "payload": {"tampered": True}},
    )

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_missing_required_artifact_ref(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    del result["artifact_refs"]["ts.next_forecast"]  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_foreign_or_malformed_production_child(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["production_child"] = {
        **result["production_child"],  # type: ignore[dict-item]
        "parent_result_id": "foreign-model",
    }

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_result_without_declared_strategy_fails_closed(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = {
        "model_type": "future.unknown",
        "model_id": "future_1",
        "nobs": 10,
        "validation": {},
    }

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            result,
            ["raw_input"],
            strategy_key="unknown_strategy_v1",
        )


def test_coefficient_result_requires_explicit_strategy_key(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = {
        "model_type": "ols",
        "model_id": "ols_1",
        "nobs": 10,
        "coefficients": {"Intercept": {"estimate": 1.0}},
    }

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "ols_1",
            result,
            ["raw_input"],
        )


def test_future_handler_without_declared_strategy_is_not_admitted(tmp_path: Path) -> None:
    from workbench.engine.registry import ModelHandler, ModelRegistryError, require_result_binding_key
    from workbench.engine.result_binding import attach_result_binding

    handler = ModelHandler(
        model_type="future.result_family",
        model_id="future_result_family_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_result_family_1", {}, None),
    )
    assert handler.result_binding_key is None
    with pytest.raises(ModelRegistryError, match="no declared result-binding strategy") as exc_info:
        require_result_binding_key(handler)
    assert exc_info.value.code == "MODEL_RESULT_INVALID"
    assert exc_info.value.evidence == {
        "model_type": "future.result_family",
        "result_binding_key": None,
        "result_binding_key_type": "NoneType",
        "reason": "has no declared result-binding strategy",
    }

    result = {
        "model_type": "future.result_family",
        "model_id": "future_result_family_1",
        "nobs": 10,
        "coefficients": {"fake": {"estimate": 1.0}},
    }
    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_result_family_1",
            result,
            ["raw_input"],
            strategy_key=handler.result_binding_key,
        )


def test_custom_registered_result_strategy_does_not_require_central_allowlist_edit() -> None:
    from workbench.engine.registry import MODEL_REGISTRY, ModelHandler, register_model, require_result_binding_key
    from workbench.engine.result_binding import register_result_binding_adapter

    model_type = "future.custom_result_family"
    strategy_key = "future.custom_packet_v1"
    handler = ModelHandler(
        model_type=model_type,
        model_id="future_custom_result_family_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_custom_result_family_1", {}, None),
        result_binding_key=strategy_key,
    )
    try:
        register_result_binding_adapter(
            strategy_key,
            lambda _run_root, _run_id, _model_id, _primary, _inputs: {
                "strategy": strategy_key
            },
        )
        register_model(handler)
        assert require_result_binding_key(handler) == strategy_key
    finally:
        MODEL_REGISTRY.pop(model_type, None)


def test_handler_with_unregistered_result_strategy_is_not_admitted() -> None:
    from workbench.engine.registry import ModelHandler, ModelRegistryError, require_result_binding_key

    handler = ModelHandler(
        model_type="future.unregistered_result_family",
        model_id="future_unregistered_result_family_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_unregistered_result_family_1", {}, None),
        result_binding_key="future.unregistered_packet_v1",
    )
    with pytest.raises(ModelRegistryError, match="unregistered result-binding strategy") as exc_info:
        require_result_binding_key(handler)
    assert exc_info.value.code == "MODEL_RESULT_INVALID"
    assert exc_info.value.evidence["model_type"] == "future.unregistered_result_family"


def test_invalid_result_strategy_error_evidence_is_json_safe() -> None:
    import json

    from workbench.engine.registry import ModelHandler, ModelRegistryError, require_result_binding_key

    handler = ModelHandler(
        model_type="future.invalid_result_family",
        model_id="future_invalid_result_family_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_invalid_result_family_1", {}, None),
        result_binding_key=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(ModelRegistryError, match="invalid result-binding strategy") as exc_info:
        require_result_binding_key(handler)
    assert exc_info.value.code == "MODEL_RESULT_INVALID"
    json.dumps(exc_info.value.evidence)
    assert exc_info.value.evidence["result_binding_key"] is None
    assert exc_info.value.evidence["result_binding_key_type"] == "object"


def test_auto_workflow_does_not_ols_fallback_after_result_binding_admission_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from workbench.artifacts import read_json
    from workbench.engine.registry import MODEL_REGISTRY
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    import workbench.orchestrator as orchestrator

    source = tmp_path / "binding-admission.csv"
    source.write_text(
        "\n".join(["y,x", *[f"{value}.0,{value}.0" for value in range(1, 41)]]) + "\n",
        encoding="utf-8",
    )
    original_handler = MODEL_REGISTRY["ols"]
    fallback_calls: list[object] = []

    def unexpected_ols_fallback(*_args: object, **_kwargs: object):
        fallback_calls.append(object())
        raise AssertionError("OLS fallback must not run after result-binding admission failure")

    monkeypatch.setattr(orchestrator, "run_ols", unexpected_ols_fallback)
    MODEL_REGISTRY["ols"] = replace(
        original_handler,
        result_binding_key="future.unregistered_packet_v1",
    )
    try:
        project = create_project(tmp_path, "binding-admission")
        result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    finally:
        MODEL_REGISTRY["ols"] = original_handler

    assert result["status"] == "failed"
    run_root = project.root / "runs" / result["run_id"]
    errors = read_json(run_root / "errors.json")
    codes = [issue["code"] for issue in errors["issues"]]
    assert "MODEL_RESULT_INVALID" in codes
    assert "MODEL_FIT_FAILED" not in codes
    assert fallback_calls == []
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_explicit_workflow_result_binding_failure_is_blocker_without_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dataclasses import replace

    from workbench.artifacts import read_json
    from workbench.engine.registry import MODEL_REGISTRY
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    import workbench.orchestrator as orchestrator

    source = tmp_path / "explicit-binding-admission.csv"
    source.write_text(
        "\n".join(["y,x", *[f"{value}.0,{value}.0" for value in range(1, 41)]]) + "\n",
        encoding="utf-8",
    )
    original_handler = MODEL_REGISTRY["ols"]
    fallback_calls: list[object] = []

    def unexpected_ols_fallback(*_args: object, **_kwargs: object):
        fallback_calls.append(object())
        raise AssertionError("OLS fallback must not run after explicit result-binding failure")

    monkeypatch.setattr(orchestrator, "run_ols", unexpected_ols_fallback)
    MODEL_REGISTRY["ols"] = replace(
        original_handler,
        result_binding_key="future.unregistered_packet_v1",
    )
    try:
        project = create_project(tmp_path, "explicit-binding-admission")
        result = run_workflow(
            project.root,
            [source],
            mode="auto",
            model_type="ols",
            y="y",
            x=["x"],
        )
    finally:
        MODEL_REGISTRY["ols"] = original_handler

    assert result["status"] == "failed"
    run_root = project.root / "runs" / result["run_id"]
    errors = read_json(run_root / "errors.json")
    issue = next(issue for issue in errors["issues"] if issue["code"] == "MODEL_RESULT_INVALID")
    assert issue["severity"] == "BLOCKER"
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "ols"
    assert fallback_calls == []
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_builtin_coefficient_strategy_admits_real_ols_workflow(tmp_path: Path) -> None:
    from workbench.artifacts import read_json
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    source = tmp_path / "registered-coefficient.csv"
    source.write_text(
        "\n".join(["y,x", *[f"{value}.0,{value}.0" for value in range(1, 41)]]) + "\n",
        encoding="utf-8",
    )
    project = create_project(tmp_path, "registered-coefficient")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    assert read_json(run_root / "model_results" / "ols_1.json")["model_type"] in {
        "ols",
        "ols_robust",
        "ols_clustered",
    }


def test_coefficient_binding_remains_compatible(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = {
        "model_type": "ols",
        "model_id": "ols_1",
        "nobs": 10,
        "coefficients": {"Intercept": {"estimate": 1.0}},
    }
    attach_result_binding(
        tmp_path / "runs" / "run-1",
        "run-1",
        "ols_1",
        result,
        ["raw_input"],
        strategy_key="coefficient_table_v1",
        expected_model_type=("ols", "ols_robust", "ols_clustered"),
    )

    assert result["coefficients"]["Intercept"]["source_id"] == "model_results.ols_1.coefficients.Intercept"  # type: ignore[index]
    assert result["result_binding"]["source_artifact_ids"] == ["raw_input"]  # type: ignore[index]


def test_coefficient_binding_rejects_foreign_model_identity(tmp_path: Path) -> None:
    from workbench.engine.result_binding import ResultBindingError, attach_result_binding

    result = {
        "model_type": "foreign.family",
        "model_id": "ols_1",
        "nobs": 10,
        "coefficients": {"Intercept": {"estimate": 1.0}},
    }
    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "ols_1",
            result,
            ["raw_input"],
            strategy_key="coefficient_table_v1",
            expected_model_type="ols",
        )


def test_result_binding_requires_explicit_expected_model_identity(tmp_path: Path) -> None:
    from workbench.engine.result_binding import ResultBindingError, attach_result_binding

    result = {
        "model_type": "foreign.family",
        "model_id": "ols_1",
        "nobs": 10,
        "coefficients": {"Intercept": {"estimate": 1.0}},
    }
    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID") as exc_info:
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "ols_1",
            result,
            ["raw_input"],
            strategy_key="coefficient_table_v1",
        )

    assert "expected model identity" in str(exc_info.value)
    assert "result_binding" not in result


def test_custom_adapter_rejects_foreign_model_identity(tmp_path: Path) -> None:
    from workbench.engine.result_binding import ResultBindingError, attach_result_binding, register_result_binding_adapter

    strategy_key = "future.identity_checked_v1"
    register_result_binding_adapter(
        strategy_key,
        lambda _run_root, _run_id, _model_id, _primary, _inputs: {"strategy": strategy_key},
    )
    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "foreign.family"},
            ["raw_input"],
            strategy_key=strategy_key,
            expected_model_type="future.expected_family",
        )


def test_non_json_safe_adapter_binding_is_structured_and_not_attached(tmp_path: Path) -> None:
    from workbench.engine.result_binding import (
        ResultBindingError,
        attach_result_binding,
        register_result_binding_adapter,
    )

    strategy_key = "future.non_json_safe_binding_v1"
    register_result_binding_adapter(
        strategy_key,
        lambda _run_root, _run_id, _model_id, _primary, _inputs: {
            "strategy": strategy_key,
            "unsafe": object(),
        },
    )
    result = {"model_type": "future.family"}
    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID") as exc_info:
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            result,
            ["raw_input"],
            strategy_key=strategy_key,
            expected_model_type="future.family",
        )

    assert "JSON-safe" in str(exc_info.value)
    assert "result_binding" not in result


def test_typed_packet_binding_preserves_pack_owned_result_shape(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = {
        "result": {
            "model_type": "time_series.ets",
            "result_identity": "ets-result-identity",
            "params": {"alpha": 0.2},
        },
        "sample_fingerprint": "sample-fingerprint",
        "producer_version": "time_series.ets@1.0",
    }
    attach_result_binding(
        tmp_path / "runs" / "run-1",
        "run-1",
        "ets_1",
        result,
        ["raw_input"],
        strategy_key="typed_packet_v1",
        expected_model_type="time_series.ets",
    )

    assert result["result_binding"]["strategy"] == "typed_packet_v1"  # type: ignore[index]
    assert result["result"]["model_type"] == "time_series.ets"  # type: ignore[index]
    assert "coefficients" not in result


def test_registry_requires_handler_identity_in_accepted_aliases() -> None:
    from workbench.engine.registry import ModelHandler, ModelRegistryError, register_model

    handler = ModelHandler(
        model_type="future.alias_family",
        model_id="future_alias_family_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_alias_family_1", {}, None),
        result_binding_key="coefficient_table_v1",
        accepted_result_model_types=("future.alias_family_alias",),
    )
    with pytest.raises(ModelRegistryError, match="must include handler model identity"):
        register_model(handler)


def test_typed_packet_binding_rejects_foreign_packet_identity(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = {
        "result": {
            "model_type": "ols",
            "result_identity": "foreign-result-identity",
        },
        "sample_fingerprint": "sample-fingerprint",
        "producer_version": "time_series.ets@1.0",
    }

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "ets_1",
            result,
            ["raw_input"],
            strategy_key="typed_packet_v1",
            expected_model_type="time_series.ets",
        )


def test_result_binding_failure_exposes_structured_issue_code(tmp_path: Path) -> None:
    from workbench.engine.result_binding import ResultBindingError, attach_result_binding

    with pytest.raises(ResultBindingError) as exc_info:
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "future.unknown", "model_id": "future_1"},
            ["raw_input"],
            strategy_key="future.unknown_v1",
        )

    assert exc_info.value.code == "MODEL_RESULT_INVALID"
    assert isinstance(exc_info.value.evidence, dict)


def test_custom_adapter_return_shape_is_fail_closed(tmp_path: Path) -> None:
    from workbench.engine.result_binding import (
        ResultBindingError,
        attach_result_binding,
        register_result_binding_adapter,
    )

    strategy_key = "future.invalid_return_v1"
    register_result_binding_adapter(
        strategy_key,
        lambda _run_root, _run_id, _model_id, _primary, _inputs: None,  # type: ignore[return-value]
    )

    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "future.unknown", "model_id": "future_1"},
            ["raw_input"],
            strategy_key=strategy_key,
        )


def test_custom_adapter_exception_is_normalized(tmp_path: Path) -> None:
    from workbench.engine.result_binding import (
        ResultBindingError,
        attach_result_binding,
        register_result_binding_adapter,
    )

    strategy_key = "future.raising_adapter_v1"
    called = False

    def raising_adapter(*_args: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise KeyError("malformed adapter state")

    register_result_binding_adapter(strategy_key, raising_adapter)

    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "future.unknown", "model_id": "future_1"},
            ["raw_input"],
            strategy_key=strategy_key,
            expected_model_type="future.unknown",
        )
    assert called is True


def test_custom_adapter_type_error_is_normalized(tmp_path: Path) -> None:
    from workbench.engine.result_binding import (
        ResultBindingError,
        attach_result_binding,
        register_result_binding_adapter,
    )

    strategy_key = "future.type_error_adapter_v1"
    called = False

    def raising_adapter(*_args: object) -> dict[str, object]:
        nonlocal called
        called = True
        raise TypeError("malformed adapter input")

    register_result_binding_adapter(strategy_key, raising_adapter)

    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "future.unknown", "model_id": "future_1"},
            ["raw_input"],
            strategy_key=strategy_key,
            expected_model_type="future.unknown",
        )
    assert called is True


def test_unhashable_result_strategy_is_structured_and_fail_closed(tmp_path: Path) -> None:
    from workbench.engine.result_binding import ResultBindingError, attach_result_binding

    with pytest.raises(ResultBindingError, match="MODEL_RESULT_INVALID") as exc_info:
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "future_1",
            {"model_type": "future.unknown"},
            ["raw_input"],
            strategy_key=[],  # type: ignore[arg-type]
            expected_model_type="future.unknown",
        )

    assert "strategy" in str(exc_info.value)


def test_artifact_backed_binding_rejects_incomplete_acceptance_contract(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    del result["validation"]["acceptance"]["model_fit_succeeded"]  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_malformed_acceptance_dimension(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["validation"]["acceptance"]["dimensions"]["mean_adequacy"]["status"] = []  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_reversed_forecast_interval(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["production_child"]["next_forecast"]["lower_bound"] = 4.0  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_incomplete_frozen_spec(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["production_child"]["next_forecast"]["frozen_spec"] = {}  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_malformed_nested_validation_metadata(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["validation"]["metrics"]["validation_n"] = "not-an-int"  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_malformed_acceptance_status(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["validation"]["acceptance"]["overall_status"] = []  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_zero_validation_n(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["validation"]["metrics"]["validation_n"] = 0  # type: ignore[index]
    result["validation"]["metrics"]["successful_forecast_n"] = 0  # type: ignore[index]
    result["validation"]["metrics"]["coverage_count"] = 0  # type: ignore[index]
    result["validation"]["metrics"]["exception_count"] = 0  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_invalid_coverage_uncertainty_bounds(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["validation"]["metrics"]["coverage_uncertainty"] = {  # type: ignore[index]
        "method": "wilson_95pct",
        "lower": 0.9,
        "upper": 0.8,
    }

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_requires_complete_coverage_uncertainty(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    del result["validation"]["metrics"]["coverage_uncertainty"]["upper"]  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_requires_current_artifact_index_schema(
    tmp_path: Path,
) -> None:
    from workbench.artifacts import read_json, write_json
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    index = read_json(run_root / "artifacts_index.json")
    index["schema_version"] = 2
    write_json(run_root / "artifacts_index.json", index)

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_symlinked_artifact_index(
    tmp_path: Path,
) -> None:
    import shutil

    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    index_path = run_root / "artifacts_index.json"
    copy_path = run_root / "artifacts_index-copy.json"
    shutil.copyfile(index_path, copy_path)
    index_path.unlink()
    index_path.symlink_to(copy_path)

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_symlinked_artifact_path(
    tmp_path: Path,
) -> None:
    import shutil

    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    report_path = run_root / result["artifact_refs"]["ts.report"]  # type: ignore[index]
    copy_path = run_root / "artifacts/time_series/ts.report-copy.json"
    shutil.copyfile(report_path, copy_path)
    report_path.unlink()
    report_path.symlink_to(copy_path)

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_malformed_nested_production_child(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["production_child"]["next_forecast"]["conditional_mean"] = "bad"  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_refit_sample_larger_than_nobs(
    tmp_path: Path,
) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    run_root = tmp_path / "runs" / "run-1"
    _materialize_indexed_artifacts(run_root, result)
    result["production_child"]["refit_summary"]["effective_sample"] = 121  # type: ignore[index]

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            run_root,
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_requires_indexed_live_artifacts(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )


def test_artifact_backed_binding_rejects_mixed_coefficient_shape(tmp_path: Path) -> None:
    from workbench.engine.result_binding import attach_result_binding

    result = _artifact_backed_result()
    result["coefficients"] = {"fake": {"estimate": 1.0}}

    with pytest.raises(ValueError, match="MODEL_RESULT_INVALID"):
        attach_result_binding(
            tmp_path / "runs" / "run-1",
            "run-1",
            "arma_garch_1",
            result,
            ["raw_input"],
            strategy_key="artifact_backed_v1",
        )
