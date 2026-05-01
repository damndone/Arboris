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
