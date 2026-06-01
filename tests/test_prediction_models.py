from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json, write_json
from workbench.econometrics.optional_deps import OptionalDependencyNotInstalled
from workbench.orchestrator import run_workflow
from workbench.prediction import run_prediction_model
from workbench.projects import create_project


def _init_artifacts(run_root: Path) -> None:
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})


def test_run_prediction_model_writes_lightweight_artifact(tmp_path: Path):
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

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1", "x2"])

    run_root = project.root / "runs" / result["run_id"]
    prediction = read_json(
        run_root / "prediction_results" / "prediction_random_forest_1.json"
    )
    assert prediction["model_type"] == "prediction_random_forest"
    assert prediction["cv_folds"] <= 5
    assert (run_root / "model_results" / "ols_1.json").is_file()
    report_html = (run_root / "reports" / "report.html").read_text(encoding="utf-8")
    assert "prediction_random_forest" not in report_html


def test_workflow_accepts_explicit_prediction_model_type(tmp_path: Path):
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
