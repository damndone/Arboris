from pathlib import Path

from workbench.artifacts import read_json
from workbench.exports import export_pdf, export_xlsx
from workbench.narrative import build_claims
from workbench.projects import create_project, create_run
from workbench.reporting import render_html_report


def test_claims_have_source_ids():
    model_result = {
        "model_id": "regression_1",
        "coefficients": {
            "x": {
                "estimate": 2.0,
                "p_value": 0.01,
                "source_id": "model_results.regression_1.coefficients.x",
            }
        },
    }
    claims = build_claims([model_result], warnings=[])
    assert claims[0]["source_id"] == "model_results.regression_1.coefficients.x"


def test_claims_include_magnitude_significance_and_r_squared():
    model_result = {
        "model_id": "ols_1",
        "r_squared": 0.834,
        "coefficients": {
            "x": {
                "estimate": 2.5,
                "p_value": 0.04,
                "source_id": "model_results.ols_1.coefficients.x",
            }
        },
    }

    claims = build_claims([model_result], warnings=[])

    assert "one-unit increase in x" in claims[0]["claim"]
    assert "2.5000" in claims[0]["claim"]
    assert "5% level" in claims[0]["claim"]
    assert claims[1]["claim"] == (
        "Model ols_1 (R²) explains 83.4% of dependent-variable variation."
    )


def test_warning_claims_bind_to_errors_source():
    claims = build_claims([], warnings=["High missingness"])

    assert claims == [
        {"claim": "High missingness", "source_id": "errors.json", "confidence": 1.0}
    ]


def test_claims_skip_unavailable_estimates():
    model_result = {
        "model_id": "regression_1",
        "coefficients": {
            "x": {
                "estimate": None,
                "source_id": "model_results.regression_1.coefficients.x",
            },
            "z": {
                "estimate": "nan",
                "source_id": "model_results.regression_1.coefficients.z",
            },
            "w": {
                "estimate": float("inf"),
                "source_id": "model_results.regression_1.coefficients.w",
            },
        },
    }

    assert build_claims([model_result], warnings=[]) == []


def test_render_and_export_reports(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": ["n=5"],
        "claims": [
            {
                "claim": "x is positive",
                "source_id": "model_results.regression_1.coefficients.x",
                "confidence": 0.9,
            }
        ],
        "warnings": [],
    }
    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)
    xlsx_path = export_xlsx({"coefficients": [{"term": "x", "estimate": 2.0}]}, run.root)
    assert html_path.exists()
    assert pdf_path.exists()
    assert xlsx_path.exists()
    assert b"model_results.regression_1.coefficients.x" in pdf_path.read_bytes()
    artifacts = read_json(run.root / "artifacts_index.json")["artifacts"]
    artifact_types = {
        artifact["artifact_id"]: artifact["artifact_type"] for artifact in artifacts
    }
    artifact_inputs = {
        artifact["artifact_id"]: artifact["inputs"] for artifact in artifacts
    }
    assert artifact_types["report_html"] == "report"
    assert artifact_types["report_pdf"] == "report"
    assert artifact_types["tables_xlsx"] == "table_export"
    assert artifact_inputs["report_pdf"] == []


def test_render_html_report_escapes_untrusted_content(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")

    html_path = render_html_report(
        {
            "title": "<script>alert(1)</script>",
            "facts": [],
            "claims": [
                {
                    "claim": "<b>unsafe</b>",
                    "source_id": "model_results.regression_1.coefficients.x",
                }
            ],
            "warnings": [],
        },
        run.root,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html


def test_report_renders_statistical_tests_section(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": [],
        "claims": [],
        "variable_importance": [
            {
                "variable": "x",
                "correlation": 0.98,
                "best_p_value": 0.001,
                "test_type": "correlation",
            }
        ],
        "statistical_tests": {
            "y_related": [
                {
                    "label": "Pearson correlation: y vs x",
                    "statistic": 0.98,
                    "p_value": 0.001,
                    "interpretation": "Statistic 0.9800; p = 0.001.",
                    "source_id": "statistical_tests.correlations.y.x",
                }
            ],
            "other": [],
            "other_truncated": 0,
        },
        "warnings": [],
    }

    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)

    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Statistical tests</h2>" in html
    assert "Pearson correlation: y vs x" in html
    assert 'data-source-id="statistical_tests.correlations.y.x"' in html
    assert b"Statistical tests" in pdf_path.read_bytes()


def test_report_renders_descriptive_statistics_section(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": [],
        "claims": [],
        "descriptive_stats": [
            {
                "column": "y",
                "dtype": "float64",
                "count": 35,
                "missing": 0,
                "missing_rate": 0.0,
                "unique_count": 35,
                "mean": 10.5,
                "std": 3.2,
                "min": 1.0,
                "max": 20.0,
            },
            {
                "column": "x",
                "dtype": "float64",
                "count": 35,
                "missing": 0,
                "missing_rate": 0.0,
                "unique_count": 35,
                "mean": 5.25,
                "std": 2.1,
                "min": 0.0,
                "max": 10.0,
            },
        ],
        "statistical_tests": [],
        "warnings": [],
    }

    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)

    html = html_path.read_text(encoding="utf-8")
    assert "<h2>Descriptive statistics</h2>" in html
    assert "y" in html
    assert "float64" in html
    assert "10.5" in html
    assert "3.2" in html
    assert b"Descriptive statistics" in pdf_path.read_bytes()
