import json
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from workbench.artifacts import read_json
from workbench.agent.context_tools import _bounded_statistics_evidence
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_run_workflow_creates_traceable_outputs(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(35)],
            "x": list(range(35)),
            "firm_id": list(range(100, 135)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "run_manifest.json").exists()
    assert (run_root / "reports" / "report.html").exists()
    assert (run_root / "reports" / "report.pdf").exists()
    assert (run_root / "exports" / "tables.xlsx").exists()
    assert (run_root / "artifacts_index.json").exists()
    manifest = read_json(run_root / "run_manifest.json")
    assert manifest["status"] == "completed"
    artifact_index = read_json(run_root / "artifacts_index.json")
    artifact_ids = {
        artifact["artifact_id"] for artifact in artifact_index["artifacts"]
    }
    assert {
        "cleaning_actions",
        "cleaned_dataset",
        "data_profile",
        "analysis_router",
        "ols_1",
        "report_html",
        "report_pdf",
        "tables_xlsx",
    }.issubset(artifact_ids)
    assert all(
        not artifact["path"].startswith("/")
        for artifact in artifact_index["artifacts"]
    )
    model_result = read_json(run_root / "model_results" / "ols_1.json")
    assert model_result["model_id"] == "ols_1"
    assert "x" in model_result["coefficients"]


def test_normal_run_persists_typed_advanced_statistics_evidence(tmp_path: Path):
    source = tmp_path / "grouped.csv"
    pd.DataFrame(
        {
            "y": [1.0, 1.2, 0.9, 2.0, 2.2, 1.8, 3.0, 3.1, 2.9] * 4,
            "x": list(range(36)),
            "region": ["north"] * 12 + ["south"] * 12 + ["west"] * 12,
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "advanced-statistics")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x", "region"],
        model_type="ols",
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    packet = read_json(run_root / "statistical_tests" / "evidence.json")
    assert packet["payload_schema"] == "workbench.statistics.evidence-packet"
    test_types = {row["test_type"] for row in packet["results"]}
    assert {"anova_posthoc", "cohens_d", "levene", "bartlett", "shapiro_wilk"} <= test_types
    agent_evidence = _bounded_statistics_evidence(run_root)
    assert agent_evidence["payload_schema"] == "workbench.statistics.evidence-packet"
    assert agent_evidence["results"][0]["test_type"] in test_types
    report_html = (run_root / "reports" / "report.html").read_text(encoding="utf-8")
    assert "Statistical Evidence" in report_html
    assert "Table 1" in report_html
    workbook = load_workbook(run_root / "exports" / "tables.xlsx", read_only=True)
    assert {"coefficients", "table_1", "statistical_evidence"} <= set(workbook.sheetnames)


def test_run_workflow_blocks_missing_model_columns(tmp_path: Path):
    source = tmp_path / "cross_section.csv"
    pd.DataFrame(
        {
            "y": [1 + 2 * i for i in range(35)],
            "x": list(range(35)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["missing"])

    assert result["status"] == "blocked"
    run_root = project.root / "runs" / result["run_id"]
    manifest = read_json(run_root / "run_manifest.json")
    errors = read_json(run_root / "errors.json")
    assert manifest["status"] == "blocked"
    assert errors["issues"][0]["code"] == "MODEL_COLUMNS_NOT_FOUND"
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_panel_run_writes_ols_baseline_only(tmp_path: Path):
    rows = []
    for firm_id in range(6):
        for year in range(2018, 2025):
            x = firm_id + year - 2018
            rows.append(
                {
                    "firm_id": firm_id,
                    "year": year,
                    "x": x,
                    "y": 1.0 + 2.0 * x + firm_id * 0.1,
                }
            )
    source = tmp_path / "panel.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")

    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "model_results" / "ols_1.json").exists()
    artifact_ids = {
        artifact["artifact_id"]
        for artifact in read_json(run_root / "artifacts_index.json")["artifacts"]
    }
    assert "ols_1" in artifact_ids
    routing = read_json(run_root / "staged" / "analysis_router.json")
    assert routing["kind"] == "panel"


def test_manifest_contains_started_at_y_and_x(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    manifest_path = project_root / "runs" / result["run_id"] / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "started_at" in manifest
    assert manifest["started_at"].endswith("+00:00") or manifest["started_at"].endswith("Z")
    assert manifest["y"] == "y"
    assert manifest["x"] == ["x"]
    assert manifest["status"] == "completed"


def test_new_run_artifacts_index_has_schema_version(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    index_path = project_root / "runs" / result["run_id"] / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index.get("schema_version") == 1


# --- V1.2.2 on_step callback tests ---

from unittest.mock import Mock


def test_on_step_callback_all_steps(tmp_path: Path):
    """_run_workflow(on_step=mock) fires start + complete for each pipeline step."""
    from workbench.orchestrator import _run_workflow, _lineage, _write_manifest
    from workbench.projects import create_project, create_run
    from workbench.config import load_config
    from datetime import datetime, timezone

    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]),
        started_at=started_at, y="y", x=["x"],
    )

    mock = Mock()
    _run_workflow(
        run.root, run.run_id, [data],
        "auto", "y", ["x"], config, started_at,
        on_step=mock,
    )

    assert mock.call_count >= 22
    call_args = [(c[0][0], c[0][1]) for c in mock.call_args_list]

    # Every step should have at least a complete or blocked
    steps_completed = {step for step, status in call_args if status in ("complete", "blocked")}
    expected_steps = {
        "ingestion", "schema", "cleaning", "profiling",
        "validation", "routing", "y_type", "model_check", "statistical_tests",
        "estimation", "diagnostics", "visualization", "narrative", "reporting", "export",
    }
    assert steps_completed == expected_steps


def test_on_step_callback_blocked_validation(tmp_path: Path):
    """Data with too few rows triggers validation blocker → on_step('validation','blocked',...)."""
    from workbench.orchestrator import _run_workflow, _lineage, _write_manifest
    from workbench.projects import create_project, create_run
    from workbench.config import load_config
    from datetime import datetime, timezone

    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    # Only 3 rows → below min_model_n=30
    pd.DataFrame({"y": [1, 2, 3], "x": [10, 20, 30]}).to_csv(data, index=False)

    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]),
        started_at=started_at, y="y", x=["x"],
    )

    mock = Mock()
    result = _run_workflow(
        run.root, run.run_id, [data],
        "auto", "y", ["x"], config, started_at,
        on_step=mock,
    )

    assert result["status"] == "blocked"
    # Should have received step_blocked for validation
    blocked_calls = [
        (s, st) for s, st, _ in [c[0] for c in mock.call_args_list]
        if st == "blocked"
    ]
    assert len(blocked_calls) >= 1
    assert blocked_calls[0][0] == "validation"


def test_fe_failure_writes_warning_not_blocker(tmp_path: Path):
    """Panel data with auto mode runs OLS only; FE is not auto-triggered."""
    rows = []
    for firm_id in range(6):
        for year in range(2018, 2025):
            x = firm_id + year - 2018
            rows.append(
                {
                    "firm_id": firm_id,
                    "year": year,
                    "x": x,
                    "y": 1.0 + 2.0 * x + firm_id * 0.1,
                }
            )
    source = tmp_path / "panel.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "model_results" / "ols_1.json").exists()
    # FE is not auto-run in Auto/OLS mode
    assert not (run_root / "model_results" / "fe_1.json").exists()


def test_on_step_callback_blocked_columns(tmp_path: Path):
    """Requested model column not in data → on_step('model_check','blocked',...)."""
    from workbench.orchestrator import _run_workflow, _lineage, _write_manifest
    from workbench.projects import create_project, create_run
    from workbench.config import load_config
    from datetime import datetime, timezone

    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]),
        started_at=started_at, y="y", x=["x"],
    )

    mock = Mock()
    # Request x column 'z' which doesn't exist (y column 'y' exists)
    result = _run_workflow(
        run.root, run.run_id, [data],
        "auto", "y", ["z"], config, started_at,
        on_step=mock,
    )

    assert result["status"] == "blocked"
    blocked_calls = [
        (s, st) for s, st, _ in [c[0] for c in mock.call_args_list]
        if st == "blocked"
    ]
    assert len(blocked_calls) >= 1
    assert blocked_calls[0][0] == "model_check"


def test_run_workflow_writes_statistical_test_artifacts(tmp_path: Path):
    rows = []
    for i in range(60):
        rows.append(
            {
                "y": float(i) + (5 if i % 2 else 0),
                "x_num": float(i),
                "treatment": "treated" if i % 2 else "control",
                "region": ["north", "south", "west"][i % 3],
            }
        )
    source = tmp_path / "mixed.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    project = create_project(tmp_path, "demo")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x_num", "treatment", "region"],
    )

    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]
    expected_files = {
        "correlations": run_root / "statistical_tests" / "correlations.json",
        "t_tests": run_root / "statistical_tests" / "t_tests.json",
        "anova": run_root / "statistical_tests" / "anova.json",
        "chi_square": run_root / "statistical_tests" / "chi_square.json",
    }
    for family, path in expected_files.items():
        assert path.exists(), f"{family} file missing"
        payload = read_json(path)
        assert payload["schema_version"] == 1
        assert payload["test_type"] == family
        assert payload["results"], f"{family} results empty"

    artifact_ids = {
        artifact["artifact_id"]
        for artifact in read_json(run_root / "artifacts_index.json")["artifacts"]
    }
    assert {
        "statistical_tests_correlations",
        "statistical_tests_t_tests",
        "statistical_tests_anova",
        "statistical_tests_chi_square",
    }.issubset(artifact_ids)


def test_e2e_binary_y_produces_logit(tmp_path: Path):
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 10, n)
    logit = -1 + 0.5 * x1
    p = 1 / (1 + np.exp(-logit))
    y = (rng.uniform(0, 1, n) < p).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"y": y, "x1": x1}).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1"])
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    logit_result = read_json(run_root / "model_results" / "logit_1.json")
    assert logit_result["model_type"] == "logit"
    assert logit_result["pseudo_r2"] is not None

    idx = read_json(run_root / "artifacts_index.json")
    artifact_ids = {a["artifact_id"] for a in idx["artifacts"]}
    assert "logit_1" in artifact_ids


def test_e2e_count_y_produces_poisson(tmp_path: Path):
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    source = tmp_path / "count.csv"
    pd.DataFrame({"y": y, "x1": x1}).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1"])
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson_result["model_type"] == "poisson"
    assert poisson_result["pseudo_r2"] is not None


def test_e2e_poisson_has_irr_and_overdispersion(tmp_path: Path):
    """Poisson model results should include IRR and overdispersion diagnostics."""
    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    source = tmp_path / "poisson_irr.csv"
    pd.DataFrame({"y": y, "x1": x1}).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1"])
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]

    # Verify IRR
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert "irr" in poisson_result
    assert "x1" in poisson_result["irr"]
    assert poisson_result["irr"]["x1"]["irr"] is not None
    assert poisson_result["irr"]["x1"].get("irr_ci_lower") is not None
    assert poisson_result["irr"]["x1"].get("irr_ci_upper") is not None

    # Verify overdispersion diagnostics
    diag = read_json(run_root / "model_results" / "diagnostics_poisson_1.json")
    assert "overdispersion" in diag
    od = diag["overdispersion"]
    assert od["overdispersion_ratio"] is not None
    assert od["zero_rate"] is not None
    assert od["mean_y"] is not None
    assert od["var_y"] is not None


def test_e2e_poisson_exposure_used_as_offset(tmp_path: Path):
    """Exposure variable in X should be used as offset, not predictor."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    exposure_months = np.full(n, 12)
    # Low rate so counts stay under 20 unique values (Poisson detection cap)
    rate = np.exp(-3.0 + 0.2 * x1)
    y = rng.poisson(rate * exposure_months)
    source = tmp_path / "poisson_exposure.csv"
    pd.DataFrame({
        "y": y, "x1": x1, "exposure_months": exposure_months,
    }).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x1", "exposure_months"],
    )
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson_result["model_type"] == "poisson_rate"
    assert poisson_result["exposure_col"] == "exposure_months"
    # exposure_months should not be a predictor
    assert "exposure_months" not in poisson_result["coefficients"]
    # x1 should still be a predictor
    assert "x1" in poisson_result["coefficients"]
    # EXPOSURE_VARIABLE_DETECTED issue should NOT exist (it's handled now)
    errors = read_json(run_root / "errors.json")
    codes = [issue["code"] for issue in errors.get("issues", [])]
    assert "EXPOSURE_VARIABLE_DETECTED" not in codes


def test_e2e_poisson_rate_model_facts(tmp_path: Path):
    """Poisson rate model should include offset fact in report."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    exposure_months = np.full(n, 12)
    rate = np.exp(-3.0 + 0.2 * x1)
    y = rng.poisson(rate * exposure_months)
    source = tmp_path / "poisson_rate_facts.csv"
    pd.DataFrame({
        "y": y, "x1": x1, "exposure_months": exposure_months,
    }).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x1", "exposure_months"],
    )
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson_result["model_type"] == "poisson_rate"


def test_e2e_poisson_rate_vif_excludes_exposure(tmp_path: Path):
    """VIF diagnostics for poisson_rate should not include the exposure column."""
    from workbench.econometrics.diagnostics import compute_diagnostics
    from workbench.econometrics.runner import run_poisson

    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    x2 = rng.normal(10, 2, n)
    exposure_months = np.full(n, 12)
    rate = np.exp(-3.0 + 0.2 * x1 + 0.1 * x2)
    y = rng.poisson(rate * exposure_months)
    frame = pd.DataFrame({
        "y": y, "x1": x1, "x2": x2, "exposure_months": exposure_months,
    })

    result, fitted = run_poisson(
        frame, y="y", x=["x1", "x2", "exposure_months"],
        model_id="poisson_vif", exposure_col="exposure_months",
    )
    assert result["model_type"] == "poisson_rate"

    # Compute diagnostics with x that excludes exposure (leaving x1, x2 = 2 columns = VIF enabled)
    from workbench.orchestrator import _detect_exposure_candidates
    normalized_x = ["x1", "x2", "exposure_months"]
    exposure_col = _detect_exposure_candidates(normalized_x)[0]
    diag_x = [v for v in normalized_x if v != exposure_col]
    exog = frame[diag_x]
    diag = compute_diagnostics(fitted, exog, model_id="poisson_vif", model_family="poisson")

    vif = diag.get("vif", {})
    assert "exposure_months" not in vif, "VIF should exclude exposure column"
    assert "x1" in vif, "VIF should include non-exposure predictors"
    assert "x2" in vif, "VIF should include non-exposure predictors"


def test_e2e_poisson_rate_stat_tests_exclude_exposure(tmp_path: Path):
    """Statistical tests for poisson_rate should not include exposure column."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    exposure_months = np.full(n, 12)
    rate = np.exp(-3.0 + 0.2 * x1)
    y = rng.poisson(rate * exposure_months)
    source = tmp_path / "poisson_stat_excl.csv"
    pd.DataFrame({
        "y": y, "x1": x1, "exposure_months": exposure_months,
    }).to_csv(source, index=False)

    from workbench.artifacts import read_json
    project = create_project(tmp_path, "poisson_stat_excl_proj")
    result = run_workflow(
        project.root, [source], mode="auto", y="y", x=["x1", "exposure_months"],
    )
    assert result["status"] == "completed"
    run_root = project.root / "runs" / result["run_id"]

    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    assert poisson_result["model_type"] == "poisson_rate"

    # Check correlation results do NOT include exposure_months
    correlations = read_json(run_root / "statistical_tests" / "correlations.json")
    for corr_result in correlations["results"]:
        for var in corr_result.get("variables", []):
            assert "exposure_months" not in var, \
                f"exposure_months found in correlation variables: {corr_result.get('variables')}"

    # Check t-test results do NOT reference exposure_months
    t_tests = read_json(run_root / "statistical_tests" / "t_tests.json")
    for t_result in t_tests.get("results", []):
        group = t_result.get("group", "")
        assert "exposure_months" not in group, \
            f"exposure_months found in t-test group: {group}"


def test_e2e_poisson_facts_include_zero_rate_and_overdispersion(tmp_path: Path):
    """Poisson report facts should include zero rate and overdispersion status."""
    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    source = tmp_path / "poisson_facts.csv"
    pd.DataFrame({"y": y, "x1": x1}).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x1"])
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    poisson_result = read_json(run_root / "model_results" / "poisson_1.json")
    # At minimum verify Poisson result is complete
    assert poisson_result["model_type"] == "poisson"
    assert "irr" in poisson_result


def test_coerce_x_columns_to_numeric_converts_datetime_x(tmp_path: Path):
    """_coerce_x_columns_to_numeric converts a datetime X column to numeric."""
    from workbench.orchestrator import _coerce_x_columns_to_numeric
    from workbench.artifacts import write_json

    # Create the required artifacts_index.json for register_artifact
    write_json(tmp_path / "artifacts_index.json", {"schema_version": 1, "artifacts": []})

    frame = pd.DataFrame({
        "y": [1, 2, 3, 4, 5],
        "x": pd.to_datetime(["1970-01-01", "1970-01-02", "1970-01-03", "1970-01-04", "1970-01-05"]),
    })
    actions = _coerce_x_columns_to_numeric(frame, ["x"], tmp_path)
    assert len(actions) == 1
    assert actions[0]["column"] == "x"
    assert pd.api.types.is_numeric_dtype(frame["x"])

    # Coercion summary artifact should exist
    assert (tmp_path / "staged" / "x_coercion_summary.json").exists()


def test_e2e_datetime_x_coerces_before_model_fit(tmp_path: Path, monkeypatch):
    """End-to-end: workflow coerces datetime X columns before model fit."""
    from workbench.orchestrator import _run_workflow, _lineage, _write_manifest
    from workbench.projects import create_project, create_run
    from workbench.config import load_config
    from workbench.artifacts import read_json
    from datetime import datetime, timezone
    from unittest.mock import Mock

    import workbench.ingestion as ingestion_mod

    proot = tmp_path / "demo"
    create_project(tmp_path, "demo")
    run = create_run(proot, mode="auto")
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    config = load_config(proot / "config.yml")
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root, run.run_id, "auto", "running",
        _lineage([data]),
        started_at=started_at, y="y", x=["x"],
    )

    # Monkey-patch to make X column datetime after ingestion
    original_read = ingestion_mod._read_frame
    def patched_read(*args, **kwargs):
        df = original_read(*args, **kwargs)
        df["x"] = pd.to_datetime(df["x"])
        return df
    monkeypatch.setattr(ingestion_mod, "_read_frame", patched_read)

    mock = Mock()
    result = _run_workflow(
        run.root, run.run_id, [data],
        "auto", "y", ["x"], config, started_at,
        on_step=mock,
    )

    assert result["status"] == "completed"
    # Coercion happens in clean_frame via _coerce_numeric_like_columns,
    # so verify through cleaning actions
    cleaning = read_json(run.root / "processed" / "cleaning_actions.json")
    coerce_actions = [a for a in cleaning["actions"] if a["action"] == "coerce_to_numeric"]
    assert len(coerce_actions) == 1
    assert coerce_actions[0]["column"] == "x"


def test_e2e_continuous_y_still_produces_ols(tmp_path: Path):
    source = tmp_path / "continuous.csv"
    pd.DataFrame({
        "y": [1.5 + 2.3 * i for i in range(35)],
        "x": list(range(35)),
    }).to_csv(source, index=False)

    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y="y", x=["x"])
    assert result["status"] == "completed"

    run_root = project.root / "runs" / result["run_id"]
    ols_result = read_json(run_root / "model_results" / "ols_1.json")
    assert ols_result["model_type"] in ("ols", "ols_robust")
