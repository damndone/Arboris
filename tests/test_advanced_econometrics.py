import numpy as np
import pandas as pd
import pytest

from workbench.econometrics import runner
from workbench.econometrics.normalize import normalize_statsmodels_result
from workbench.econometrics.runner import (
    run_glm,
    run_negative_binomial,
    run_probit,
)
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_probit_binary_y_returns_normalized_result():
    rng = np.random.default_rng(42)
    n = 80
    x1 = rng.normal(size=n)
    latent = -0.2 + 0.9 * x1 + rng.normal(size=n)
    y = (latent > 0).astype(int)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_probit(frame, y="y", x=["x1"], model_id="probit_1")

    assert result["schema_version"] == 1
    assert result["model_id"] == "probit_1"
    assert result["model_type"] == "probit"
    assert result["engine"] == "statsmodels"
    assert result["nobs"] == n
    assert "x1" in result["coefficients"]
    assert len(result["fitted_values_preview"]) <= 500
    # The original guard here was `"fitted_values" not in result`, protecting
    # against an unbounded vector in the payload. The full vector is now emitted
    # so diagnostic plots describe the analysis sample rather than its first 500
    # rows — but the bound it was protecting still holds.
    from workbench.econometrics.normalize import FULL_SEQUENCE_LIMIT

    assert len(result["fitted_values"]) == n
    assert len(result["fitted_values"]) < FULL_SEQUENCE_LIMIT


def test_run_negative_binomial_count_y_returns_irr():
    rng = np.random.default_rng(43)
    n = 120
    x1 = rng.uniform(0, 3, n)
    mu = np.exp(0.2 + 0.4 * x1)
    y = rng.negative_binomial(n=2, p=2 / (2 + mu))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_negative_binomial(frame, y="y", x=["x1"], model_id="nb_1")

    assert result["model_type"] == "negative_binomial"
    assert result["engine"] == "statsmodels"
    assert "irr" in result
    assert "x1" in result["coefficients"]


def test_run_glm_poisson_returns_requested_family():
    rng = np.random.default_rng(44)
    n = 60
    x1 = rng.uniform(0, 2, n)
    y = rng.poisson(np.exp(0.1 + 0.3 * x1))
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_glm(
        frame,
        y="y",
        x=["x1"],
        model_id="glm_1",
        family_name="poisson",
    )

    assert result["model_type"] == "glm"
    assert result["glm_family"] == "poisson"
    assert result["engine"] == "statsmodels"


def test_run_panel_ols_requires_entity_or_time():
    from workbench.econometrics.runner import run_panel_ols

    frame = pd.DataFrame({"y": [1.0, 2.0], "x1": [0.1, 0.2]})

    with pytest.raises(ValueError, match="PANEL_FIELDS_MISSING"):
        run_panel_ols(
            frame,
            y="y",
            x=["x1"],
            entity=None,
            time=None,
            model_id="panel_ols_1",
        )


def test_run_panel_ols_with_linearmodels_if_installed():
    pytest.importorskip("linearmodels")
    from workbench.econometrics.runner import run_panel_ols

    frame = pd.DataFrame(
        {
            "firm_id": ["a", "a", "a", "b", "b", "b", "c", "c", "c"],
            "year": [2020, 2021, 2022, 2020, 2021, 2022, 2020, 2021, 2022],
            "y": [1.0, 1.4, 1.8, 2.0, 2.5, 3.0, 1.5, 1.9, 2.4],
            "x1": [0.2, 0.5, 0.8, 0.3, 0.7, 1.0, 0.1, 0.4, 0.9],
        }
    )

    result, _ = run_panel_ols(
        frame,
        y="y",
        x=["x1"],
        entity="firm_id",
        time="year",
        model_id="panel_ols_1",
    )

    assert result["model_type"] == "panel_ols"
    assert result["engine"] == "linearmodels"


def test_run_iv_2sls_requires_complete_spec():
    from workbench.econometrics.runner import run_iv_2sls

    frame = pd.DataFrame({"y": [1.0, 2.0], "x1": [0.1, 0.2]})

    with pytest.raises(ValueError, match="IV_SPEC_INCOMPLETE"):
        run_iv_2sls(
            frame,
            y="y",
            exog=["x1"],
            endog=[],
            instruments=[],
            model_id="iv_2sls_1",
        )


class _FailingModel:
    def fit(self, **kwargs):
        raise RuntimeError("singular matrix")


@pytest.mark.parametrize(
    ("name", "fit_call"),
    [
        (
            "Probit",
            lambda frame: run_probit(frame, y="y", x=["x1"], model_id="probit_bad"),
        ),
        (
            "Negative Binomial",
            lambda frame: run_negative_binomial(frame, y="y", x=["x1"], model_id="nb_bad"),
        ),
        (
            "GLM",
            lambda frame: run_glm(
                frame,
                y="y",
                x=["x1"],
                model_id="glm_bad",
                family_name="poisson",
            ),
        ),
    ],
)
def test_advanced_model_fit_errors_include_root_cause(monkeypatch, name, fit_call):
    frame = pd.DataFrame({"y": [0, 1, 1, 2], "x1": [0.1, 0.2, 0.3, 0.4]})
    monkeypatch.setattr(runner.smf, name.lower().replace(" ", ""), lambda **kwargs: _FailingModel())

    with pytest.raises(ValueError, match="Root cause: singular matrix") as exc_info:
        fit_call(frame)

    assert name in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


class _GuardedValues:
    """A finite source of exactly ``nobs`` values.

    The normalizer makes two bounded passes over this (the 500-row preview and
    the full analysis-sample vector).  Runaway consumption is guarded by
    ``test_full_sequence_conversion_stays_bounded_for_an_oversized_model``,
    which feeds a genuinely infinite generator — a stricter check than the
    fixed 500-element trap this class used to carry.
    """

    def __iter__(self):
        for _ in range(1000):
            yield 1.0


class _FakeModel:
    exog_names = ["x1"]


class _FakeFitted:
    model = _FakeModel()
    params = [1.0]
    bse = [0.1]
    pvalues = [0.01]
    nobs = 1000
    fittedvalues = _GuardedValues()
    resid = _GuardedValues()


def test_normalize_statsmodels_result_caps_preview_conversion():
    result = normalize_statsmodels_result(_FakeFitted(), "ols_guard")

    assert len(result["fitted_values_preview"]) == 500
    assert len(result["residuals_preview"]) == 500
    assert len(result["fitted_values"]) == 1000
    assert len(result["residuals"]) == 1000


def test_full_sequence_conversion_stays_bounded_for_an_oversized_model():
    """Past the ceiling the payload keeps only the preview, so plots say so."""
    from workbench.econometrics.normalize import _json_safe_sequence_preview

    def endless():
        while True:
            yield 1.0

    assert len(_json_safe_sequence_preview(endless(), limit=64)) == 64


def test_run_workflow_explicit_probit_writes_model_result(tmp_path):
    rng = np.random.default_rng(45)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "explicit_probit")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="probit",
    )

    model_path = project.root / "runs" / result["run_id"] / "model_results" / "probit_1.json"
    model_result = read_json(model_path)
    assert model_result["model_type"] == "probit"
    assert model_result["engine"] == "statsmodels"


def test_run_workflow_auto_still_routes_binary_to_logit(tmp_path):
    rng = np.random.default_rng(46)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "auto_binary")

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])

    model_dir = project.root / "runs" / result["run_id"] / "model_results"
    assert (model_dir / "logit_1.json").exists()
    assert not (model_dir / "probit_1.json").exists()


def test_run_workflow_glm_poisson_keeps_data_driven_y_type(tmp_path):
    rng = np.random.default_rng(47)
    n = 80
    x = rng.uniform(0, 2, n)
    y = rng.poisson(np.exp(0.2 + 0.3 * x))
    source = tmp_path / "counts.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "glm_poisson")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="glm:poisson",
    )

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "glm_1.json")
    manifest = read_json(run_root / "run_manifest.json")

    assert model_result["model_type"] == "glm"
    assert model_result["glm_family"] == "poisson"
    assert manifest["model_routing"]["requested_model_type"] == "glm:poisson"
    assert manifest["model_routing"]["effective_y_type"] == "count"
    diagnostics = read_json(run_root / "model_results" / "diagnostics_glm_1.json")
    assert "overdispersion" in diagnostics


def test_run_workflow_explicit_negative_binomial_writes_model_result(tmp_path):
    rng = np.random.default_rng(48)
    n = 120
    x = rng.uniform(0, 2, n)
    mu = np.exp(0.2 + 0.4 * x)
    y = rng.negative_binomial(n=2, p=2 / (2 + mu))
    source = tmp_path / "counts.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "explicit_negative_binomial")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="negative_binomial",
    )

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(
        run_root / "model_results" / "negative_binomial_1.json"
    )
    manifest = read_json(run_root / "run_manifest.json")

    assert model_result["model_type"] == "negative_binomial"
    assert model_result["engine"] == "statsmodels"
    assert manifest["model_routing"]["requested_model_type"] == "negative_binomial"
    assert manifest["model_routing"]["effective_y_type"] == "count"


def test_run_workflow_panel_ols_requires_panel_fields(tmp_path):
    rng = np.random.default_rng(49)
    n = 80
    x = rng.normal(size=n)
    y = 0.2 + 0.5 * x + rng.normal(size=n)
    source = tmp_path / "cross_section.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "panel_missing_fields")

    with pytest.raises(ValueError, match="panel_ols requires entity or time"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            model_type="panel_ols",
        )

    run_root = next((project.root / "runs").iterdir())
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "panel_ols"
    assert not (run_root / "model_results" / "ols_1.json").exists()
    issue = errors["issues"][0]
    assert issue["code"] == "PANEL_FIELDS_MISSING"
    assert "panel_ols requires entity or time" in issue["message"]
    assert issue["evidence"]["model_type"] == "panel_ols"


def test_run_workflow_panel_ols_skips_statsmodels_diagnostics(monkeypatch, tmp_path):
    import workbench.orchestrator as orchestrator

    def fake_panel_ols(frame, y, x, entity, time, model_id, covariance="robust"):
        assert entity == "firm_id"
        assert time == "year"
        return (
            {
                "schema_version": 1,
                "model_id": model_id,
                "model_type": "panel_ols",
                "engine": "linearmodels",
                "nobs": len(frame),
                "r_squared": 0.5,
                "coefficients": {
                    "x": {"estimate": 1.0, "std_error": 0.1, "p_value": 0.01}
                },
                "warnings": [],
            },
            object(),
        )

    source = tmp_path / "panel.csv"
    firms = [f"firm_{idx:02d}" for idx in range(30)]
    pd.DataFrame(
        {
            "firm_id": [firm for firm in firms for _ in range(2)],
            "year": [2020, 2021] * len(firms),
            "y": [1.0 + idx * 0.1 for idx in range(len(firms) * 2)],
            "x": [float(idx % 2) for idx in range(len(firms) * 2)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "panel_success_without_diagnostics")
    monkeypatch.setattr(orchestrator, "run_panel_ols", fake_panel_ols)

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="panel_ols",
    )

    run_root = project.root / "runs" / result["run_id"]
    model_result = read_json(run_root / "model_results" / "panel_ols_1.json")
    manifest = read_json(run_root / "run_manifest.json")

    assert result["status"] == "completed"
    assert model_result["model_type"] == "panel_ols"
    assert manifest["model_routing"]["effective_model_type"] == "panel_ols"
    assert not (run_root / "model_results" / "diagnostics_panel_ols_1.json").exists()


def test_run_workflow_panel_ols_missing_dependency_writes_structured_issue(
    monkeypatch,
    tmp_path,
):
    import workbench.orchestrator as orchestrator
    from workbench.econometrics.optional_deps import OptionalDependencyNotInstalled

    def missing_panel(*args, **kwargs):
        raise OptionalDependencyNotInstalled(
            extra="panel",
            package="linearmodels.panel",
            model_type="panel_ols",
            engine="linearmodels",
        )

    source = tmp_path / "panel.csv"
    firms = [f"firm_{idx:02d}" for idx in range(30)]
    pd.DataFrame(
        {
            "firm_id": [firm for firm in firms for _ in range(2)],
            "year": [2020, 2021] * len(firms),
            "y": [1.0 + idx * 0.1 for idx in range(len(firms) * 2)],
            "x": [float(idx % 2) for idx in range(len(firms) * 2)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "panel_missing_dependency")
    monkeypatch.setattr(orchestrator, "run_panel_ols", missing_panel)

    with pytest.raises(OptionalDependencyNotInstalled):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            model_type="panel_ols",
        )

    run_root = next((project.root / "runs").iterdir())
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")
    issue = errors["issues"][0]

    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "panel_ols"
    assert issue["code"] == "OPTIONAL_DEPENDENCY_MISSING"
    assert issue["evidence"]["engine"] == "linearmodels"
    assert issue["evidence"]["model_type"] == "panel_ols"
    assert issue["evidence"]["extra"] == "panel"


def test_explicit_model_fit_failure_on_wrong_y_type_fails_no_fallback(tmp_path):
    """Explicit model_type on incompatible y must fail with structured issue, no OLS fallback."""
    rng = np.random.default_rng(50)
    n = 80
    x = rng.normal(size=n)
    y = 0.2 + 0.5 * x + rng.normal(size=n)
    source = tmp_path / "continuous.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "negative_binomial_no_fallback")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="negative_binomial",
    )

    run_root = project.root / "runs" / result["run_id"]
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    assert result["status"] == "failed"
    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "negative_binomial"
    # No OLS fallback for explicit model
    assert not (run_root / "model_results" / "ols_1.json").exists()
    assert not (run_root / "model_results" / "negative_binomial_1.json").exists()
    issue = errors["issues"][0]
    assert issue["code"] == "MODEL_FIT_FAILED"
    assert issue["severity"] == "BLOCKER"
    assert issue["evidence"]["model_type"] == "negative_binomial"
    assert issue["evidence"]["model_id"] == "negative_binomial_1"
    assert issue["evidence"]["engine"] == "statsmodels"
    assert issue["evidence"]["step"] == "estimation"
    assert "y" in issue["evidence"]
    assert "x" in issue["evidence"]
    assert "root_cause" in issue["evidence"]


def test_unsupported_glm_family_fails_before_ols_fallback(tmp_path):
    rng = np.random.default_rng(51)
    n = 80
    x = rng.uniform(0, 2, n)
    y = rng.poisson(np.exp(0.2 + 0.3 * x))
    source = tmp_path / "counts.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "unsupported_glm_family")

    with pytest.raises(ValueError, match="Unsupported GLM family: poissonn"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            model_type="glm:poissonn",
        )

    run_root = next((project.root / "runs").iterdir())
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "glm:poissonn"
    assert not (run_root / "model_results" / "ols_1.json").exists()
    issue = errors["issues"][0]
    assert issue["code"] == "UNSUPPORTED_GLM_FAMILY"
    assert "Unsupported GLM family: poissonn" in issue["message"]
    assert issue["evidence"]["model_type"] == "glm:poissonn"
    assert issue["evidence"]["glm_family"] == "poissonn"
    assert "binomial" in issue["evidence"]["supported_families"]


def test_unsupported_explicit_model_type_fails_before_ols_fallback(tmp_path):
    rng = np.random.default_rng(52)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "unsupported_model_type")

    with pytest.raises(ValueError, match="Unsupported model type: probt"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            model_type="probt",
        )

    run_root = next((project.root / "runs").iterdir())
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    assert manifest["status"] == "failed"
    assert manifest["requested_model_type"] == "probt"
    assert not (run_root / "model_results" / "ols_1.json").exists()
    issue = errors["issues"][0]
    assert issue["code"] == "UNSUPPORTED_MODEL_TYPE"
    assert "Unsupported model type: probt" in issue["message"]
    assert issue["evidence"]["model_type"] == "probt"
    assert "supported_types" in issue["evidence"]


# ============================================================
# Task 10: Structured model failure issues
# ============================================================


def test_auto_mode_fallback_writes_structured_model_fit_failed(monkeypatch, tmp_path):
    """Auto mode fallback to OLS must write a structured MODEL_FIT_FAILED issue."""
    import workbench.orchestrator as orchestrator

    def fake_logit(*args, **kwargs):
        raise ValueError("Logit perfect separation")

    monkeypatch.setattr(orchestrator, "run_logit", fake_logit)

    rng = np.random.default_rng(53)
    n = 80
    x = rng.normal(size=n)
    y = (-0.1 + 0.8 * x + rng.normal(size=n) > 0).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "auto_fallback")

    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"],
    )

    run_root = project.root / "runs" / result["run_id"]
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    # Auto mode falls back to OLS, so workflow completes
    assert result["status"] == "completed"
    assert manifest["status"] == "completed"
    assert (run_root / "model_results" / "ols_1.json").exists()

    # Structured MODEL_FIT_FAILED issue must be present
    model_issues = [i for i in errors["issues"] if i["code"] == "MODEL_FIT_FAILED"]
    assert len(model_issues) >= 1
    issue = model_issues[0]
    assert issue["severity"] == "WARNING"  # auto mode: warning, not blocker
    assert "y" in issue["evidence"]
    assert "x" in issue["evidence"]
    assert "root_cause" in issue["evidence"]
    assert "y_type" in issue["evidence"]
    # H-1: auto mode must report the actual model attempted, not y_type
    assert issue["evidence"]["model_type"] == "logit"
    assert issue["evidence"]["model_id"] == "logit_1"
    assert issue["evidence"]["engine"] == "statsmodels"


def test_explicit_model_failure_includes_all_required_context(tmp_path):
    """Explicit model fit failure issue must contain model_type, model_id,
    engine, step, y, x, and root_cause."""
    rng = np.random.default_rng(54)
    n = 80
    x = rng.normal(size=n)
    y = 0.2 + 0.5 * x + rng.normal(size=n)
    source = tmp_path / "cont.csv"
    pd.DataFrame({"y": y, "x": x}).to_csv(source, index=False)
    project = create_project(tmp_path, "explicit_failure_context")

    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"],
        model_type="negative_binomial",
    )

    run_root = project.root / "runs" / result["run_id"]
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")

    assert result["status"] == "failed"
    assert manifest["status"] == "failed"
    issue = errors["issues"][0]
    assert issue["code"] == "MODEL_FIT_FAILED"
    assert issue["severity"] == "BLOCKER"
    evidence = issue["evidence"]
    assert evidence["model_type"] == "negative_binomial"
    assert evidence["model_id"] == "negative_binomial_1"
    assert evidence["engine"] == "statsmodels"
    assert evidence["step"] == "estimation"
    assert evidence["y"] is not None
    assert isinstance(evidence["x"], list)
    assert "root_cause" in evidence
    assert "requested_model_type" in evidence


def test_workflow_model_failure_details_helper():
    """Unit test for _model_failure_details producing consistent evidence."""
    from workbench.orchestrator import _model_failure_details

    details = _model_failure_details(
        model_type="probit",
        y="outcome",
        x=["x1", "x2"],
        root_cause="Perfect separation detected",
        step="estimation",
    )

    assert details["model_type"] == "probit"
    assert details["model_id"] == "probit_1"
    assert details["engine"] == "statsmodels"
    assert details["step"] == "estimation"
    assert details["y"] == "outcome"
    assert details["x"] == ["x1", "x2"]
    assert details["root_cause"] == "Perfect separation detected"


def test_workflow_model_failure_details_for_glm():
    """_model_failure_details for glm:<family> resolves model_id and engine."""
    from workbench.orchestrator import _model_failure_details

    details = _model_failure_details(
        model_type="glm:binomial",
        y="y",
        x=["x"],
        root_cause="LinAlgError",
    )

    assert details["model_id"] == "glm_1"
    assert details["engine"] == "statsmodels"
    assert details["model_type"] == "glm:binomial"


def test_prediction_failure_in_workflow_writes_structured_issue_and_continues(
    monkeypatch, tmp_path,
):
    """Prediction ValueError must not crash the econometric workflow."""
    import workbench.orchestrator as orchestrator

    def fake_prediction(*args, **kwargs):
        raise ValueError("Too few samples for prediction")

    monkeypatch.setattr(orchestrator, "run_prediction_model", fake_prediction)

    source = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [float(i) for i in range(40)], "x": [float(i) for i in range(40)]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_failure")
    (project.root / "config.yml").write_text(
        "prediction_enabled: true\n"
        "prediction_model_type: prediction_lasso\n",
        encoding="utf-8",
    )

    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"],
    )

    run_root = project.root / "runs" / result["run_id"]
    errors = read_json(run_root / "errors.json")

    # Econometric workflow must still complete
    assert result["status"] == "completed"
    assert (run_root / "model_results" / "ols_1.json").exists()

    # Prediction failure issue must be present
    pred_issues = [i for i in errors["issues"] if i["code"] == "PREDICTION_FAILED"]
    assert len(pred_issues) >= 1
    issue = pred_issues[0]
    assert issue["severity"] == "WARNING"
    assert "Too few samples" in issue["message"]
    assert issue["evidence"]["model_type"] == "prediction_lasso"
    assert issue["evidence"]["step"] == "prediction"


def test_prediction_missing_dependency_in_workflow_continues_workflow(
    monkeypatch, tmp_path,
):
    """Prediction OptionalDependencyNotInstalled must not crash the workflow."""
    import workbench.orchestrator as orchestrator
    from workbench.econometrics.optional_deps import OptionalDependencyNotInstalled

    def fake_prediction(*args, **kwargs):
        raise OptionalDependencyNotInstalled(
            extra="ml", package="sklearn", model_type="prediction_lasso",
        )

    monkeypatch.setattr(orchestrator, "run_prediction_model", fake_prediction)

    source = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [float(i) for i in range(40)], "x": [float(i) for i in range(40)]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_missing_dep")
    (project.root / "config.yml").write_text(
        "prediction_enabled: true\n"
        "prediction_model_type: prediction_lasso\n",
        encoding="utf-8",
    )

    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x"],
    )

    run_root = project.root / "runs" / result["run_id"]
    errors = read_json(run_root / "errors.json")

    assert result["status"] == "completed"
    assert (run_root / "model_results" / "ols_1.json").exists()
    dep_issues = [
        i for i in errors["issues"]
        if i["code"] == "OPTIONAL_DEPENDENCY_MISSING"
    ]
    assert len(dep_issues) >= 1
    assert dep_issues[0]["severity"] == "WARNING"
    # M-3: evidence uses _model_failure_details (includes y, x, root_cause)
    evidence = dep_issues[0]["evidence"]
    assert evidence["model_type"] == "prediction_lasso"
    assert evidence["step"] == "prediction"
    assert evidence["y"] is not None
    assert "x" in evidence
    assert evidence["extra"] == "ml"
    assert evidence["package"] == "sklearn"
    assert "install" in evidence


def test_normalize_reports_adjusted_r_squared_and_the_full_analysis_sample():
    """Stata `reg` prints Adj R-squared and plots residuals over every row.

    Without `r_squared_adj` a reader cannot answer "what is the adjusted R2"
    from Workbench output at all; without the full residual/fitted vectors the
    diagnostic plots silently describe the first 500 observations only.
    """
    import statsmodels.formula.api as smf

    rng = np.random.default_rng(7)
    n = 900
    x1 = rng.normal(size=n)
    frame = pd.DataFrame({"y": 2.0 + 1.5 * x1 + rng.normal(size=n), "x1": x1})
    fitted = smf.ols("y ~ x1", data=frame).fit()

    result = normalize_statsmodels_result(fitted, "ols_1")

    assert result["r_squared_adj"] == pytest.approx(fitted.rsquared_adj)
    assert result["r_squared_adj"] < result["r_squared"]
    assert len(result["residuals"]) == n
    assert len(result["fitted_values"]) == n
    # The bounded preview stays for compact surfaces that never wanted 900 rows.
    assert len(result["residuals_preview"]) == 500
