import inspect
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json, write_json
from workbench.econometrics.optional_deps import OptionalDependencyNotInstalled
from workbench.orchestrator import run_workflow
from workbench.prediction import run_prediction_model
from workbench.projects import create_project


def _init_artifacts(run_root: Path) -> None:
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})


def test_run_prediction_model_writes_lightweight_artifact(tmp_path: Path):
    pytest.importorskip("sklearn")
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "x1": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "x2": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        }
    )

    result = run_prediction_model(
        frame,
        run_root,
        y="y",
        x=["x1", "x2"],
        model_type="prediction_ridge",
        model_id="prediction_ridge_1",
        cv_folds=10,
        random_seed=42,
    )

    assert result["model_type"] == "prediction_ridge"
    assert result["engine"] == "scikit-learn"
    assert result["status"] == "completed"
    assert result["cv_folds"] <= 5
    assert result["nobs"] == 6
    assert result["sampling_method"] is None
    assert "predictions" not in result
    assert result["warnings"] == [
        "Prediction results are not causal effects and are not regression inference."
    ]
    path = run_root / "prediction_results" / "prediction_ridge_1.json"
    assert path.is_file()
    saved = read_json(path)
    assert saved["status"] == "completed"
    artifact = next(
        item
        for item in read_json(run_root / "artifacts_index.json")["artifacts"]
        if item["artifact_id"] == "prediction_ridge_1"
    )
    assert artifact["artifact_type"] == "prediction_result"
    assert artifact["inputs"] == ["cleaned_dataset"]


def test_workflow_writes_prediction_artifact_only_when_configured(tmp_path: Path):
    pytest.importorskip("sklearn")
    project = create_project(tmp_path, "demo")
    (project.root / "config.yml").write_text(
        "prediction_enabled: true\n"
        "prediction_model_type: prediction_random_forest\n"
        "prediction_cv_folds: 20\n",
        encoding="utf-8",
    )
    source = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "y": [float(i * 2 + 1) for i in range(40)],
            "x1": [float(i) for i in range(40)],
            "x2": [float(i % 3) for i in range(40)],
        }
    ).to_csv(source, index=False)

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x1", "x2"],
        prediction_data_structure="iid",
    )

    run_root = project.root / "runs" / result["run_id"]
    prediction = read_json(
        run_root / "prediction_results" / "prediction_random_forest_1.json"
    )
    assert prediction["model_type"] == "prediction_random_forest"
    evaluation = read_json(
        run_root / "evaluation_results" / "prediction_random_forest_1.json"
    )
    split_plan = read_json(
        run_root / "prediction_splits" / "prediction_random_forest_1.json"
    )
    assert len(evaluation["cv"]) == 20
    assert split_plan["effective_parameters"]["cv_folds"] == 20
    assert (run_root / "model_results" / "ols_1.json").is_file()
    report_html = (run_root / "reports" / "report.html").read_text(encoding="utf-8")
    assert "prediction_random_forest" not in report_html


def test_workflow_accepts_explicit_prediction_model_type(tmp_path: Path):
    pytest.importorskip("sklearn")
    project = create_project(tmp_path, "explicit_prediction")
    source = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "y": [float(i * 3 + 2) for i in range(36)],
            "x1": [float(i) for i in range(36)],
            "x2": [float(i % 4) for i in range(36)],
        }
    ).to_csv(source, index=False)

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x1", "x2"],
        model_type="prediction_lasso",
        prediction_data_structure="iid",
    )

    run_root = project.root / "runs" / result["run_id"]
    prediction = read_json(run_root / "prediction_results" / "prediction_lasso_1.json")
    assert prediction["model_type"] == "prediction_lasso"
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["model_routing"]["requested_model_type"] == "prediction_lasso"
    assert "prediction_lasso" not in (
        run_root / "reports" / "report.html"
    ).read_text(encoding="utf-8")


def test_prediction_missing_sklearn_raises_structured_optional_dependency(monkeypatch, tmp_path: Path):
    import workbench.prediction as prediction

    def fake_require(module_name: str, **kwargs):
        raise OptionalDependencyNotInstalled(
            extra=kwargs["extra"],
            package=module_name,
            model_type=kwargs["model_type"],
            step=kwargs["step"],
            engine=kwargs["engine"],
        )

    monkeypatch.setattr(prediction, "require_optional_dependency", fake_require)
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame({"y": [1.0, 2.0], "x": [1.0, 2.0]})

    try:
        run_prediction_model(
            frame,
            run_root,
            y="y",
            x=["x"],
            model_type="prediction_lasso",
            model_id="prediction_lasso_1",
        )
    except OptionalDependencyNotInstalled as exc:
        details = exc.to_issue_details()
        assert details["step"] == "prediction"
        assert details["engine"] == "scikit-learn"
        assert details["model_type"] == "prediction_lasso"
        assert details["details"]["extra"] == "ml"
    else:
        raise AssertionError("Expected structured optional dependency error")


def test_prediction_requires_enough_complete_rows(tmp_path: Path):
    pytest.importorskip("sklearn")
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, None, 4.0],
            "x": [1.0, 2.0, 3.0, None],
        }
    )

    try:
        run_prediction_model(
            frame,
            run_root,
            y="y",
            x=["x"],
            model_type="prediction_ridge",
            model_id="prediction_ridge_1",
        )
    except ValueError as exc:
        assert "at least four complete rows" in str(exc)
    else:
        raise AssertionError("Expected complete-row validation error")


def test_unsupported_prediction_model_type_fails_before_optional_import(monkeypatch, tmp_path: Path):
    import workbench.prediction as prediction

    def fail_if_called(module_name: str, **kwargs):
        raise AssertionError(f"optional import should not run for unsupported model: {module_name}")

    monkeypatch.setattr(prediction, "require_optional_dependency", fail_if_called)
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame({"y": [1.0, 2.0, 3.0], "x": [1.0, 2.0, 3.0]})

    try:
        run_prediction_model(
            frame,
            run_root,
            y="y",
            x=["x"],
            model_type="prediction_rigde",
            model_id="prediction_rigde_1",
        )
    except ValueError as exc:
        assert "Unsupported prediction model_type: prediction_rigde" in str(exc)
    else:
        raise AssertionError("Expected unsupported prediction model_type error")


def test_prediction_sampling_requires_prediction_context():
    from workbench.prediction import build_sampler

    sampler = build_sampler("", model_type="prediction_random_forest", random_seed=42)
    assert sampler is None

    try:
        build_sampler("smote", model_type="ols", random_seed=42)
    except ValueError as exc:
        assert "prediction-only" in str(exc)
    else:
        raise AssertionError("Expected prediction-only validation error")


def test_unsupported_sampling_method_fails_before_optional_import(monkeypatch):
    import workbench.prediction as prediction

    def fail_if_called(module_name: str, **kwargs):
        raise AssertionError(f"optional import should not run for unsupported sampling: {module_name}")

    monkeypatch.setattr(prediction, "require_optional_dependency", fail_if_called)

    try:
        prediction.build_sampler(
            "bad_sampling",
            model_type="prediction_random_forest",
            random_seed=42,
        )
    except ValueError as exc:
        assert "Unsupported sampling method: bad_sampling" in str(exc)
    else:
        raise AssertionError("Expected unsupported sampling method error")


def test_prediction_sampling_missing_imblearn_raises_structured_optional_dependency(monkeypatch):
    import workbench.prediction as prediction

    def fake_require(module_name: str, **kwargs):
        raise OptionalDependencyNotInstalled(
            extra=kwargs["extra"],
            package=module_name,
            model_type=kwargs["model_type"],
            step=kwargs["step"],
            engine=kwargs["engine"],
        )

    monkeypatch.setattr(prediction, "require_optional_dependency", fake_require)

    try:
        prediction.build_sampler(
            "oversample",
            model_type="prediction_random_forest",
            random_seed=42,
        )
    except OptionalDependencyNotInstalled as exc:
        details = exc.to_issue_details()
        assert details["step"] == "prediction"
        assert details["engine"] == "imbalanced-learn"
        assert details["model_type"] == "prediction_random_forest"
        assert details["details"]["extra"] == "imbalanced"
    else:
        raise AssertionError("Expected structured optional dependency error")


def test_run_prediction_model_applies_oversampling_when_imblearn_installed(tmp_path: Path):
    pytest.importorskip("imblearn")
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame(
        {
            "y": [0.0] * 24 + [1.0] * 8,
            "x1": [float(i) for i in range(32)],
            "x2": [float(i % 5) for i in range(32)],
        }
    )

    result = run_prediction_model(
        frame,
        run_root,
        y="y",
        x=["x1", "x2"],
        model_type="prediction_random_forest",
        model_id="prediction_random_forest_1",
        sampling_method="oversample",
        random_seed=42,
    )

    assert result["status"] == "completed"
    assert result["sampling_method"] == "oversample"
    saved = read_json(run_root / "prediction_results" / "prediction_random_forest_1.json")
    assert saved["sampling_method"] == "oversample"


def test_prediction_sampling_rejects_continuous_target(tmp_path: Path):
    pytest.importorskip("imblearn")
    run_root = tmp_path / "run"
    run_root.mkdir()
    _init_artifacts(run_root)
    frame = pd.DataFrame(
        {
            "y": [float(i) for i in range(24)],
            "x": [float(i % 4) for i in range(24)],
        }
    )

    try:
        run_prediction_model(
            frame,
            run_root,
            y="y",
            x=["x"],
            model_type="prediction_random_forest",
            model_id="prediction_random_forest_1",
            sampling_method="oversample",
        )
    except ValueError as exc:
        assert "requires a discrete target" in str(exc)
    else:
        raise AssertionError("Expected sampling target validation error")


def test_legacy_prediction_helper_is_explicitly_historical_and_declares_shuffle():
    signature = inspect.signature(run_prediction_model)
    assert "shuffle" in signature.parameters
    assert "historical" in (run_prediction_model.__doc__ or "").lower()
