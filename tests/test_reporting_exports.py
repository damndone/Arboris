from pathlib import Path

from workbench.artifacts import read_json
from workbench.exports import export_pdf, export_xlsx
from workbench.narrative import build_claims
from workbench.projects import create_project, create_run
from workbench.reporting import render_html_report
from workbench.report_view_model import (
    build_regression_table,
    regression_table_export_rows,
)


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


def test_warning_claims_bind_to_severity_aware_sources():
    claims = build_claims([], warnings=[
        {"severity": "BLOCKER", "message": "Bad data"},
        {"severity": "WARNING", "message": "High correlation"},
        {"severity": "INFO", "message": "Dummy-coded categorical"},
        "Legacy issue",
    ])

    assert claims == [
        {"claim": "Bad data", "source_id": "errors.json", "confidence": 1.0},
        {"claim": "High correlation", "source_id": "warnings.json", "confidence": 1.0},
        {"claim": "Dummy-coded categorical", "source_id": "diagnostics.warnings", "confidence": 1.0},
        {"claim": "Legacy issue", "source_id": "errors.json", "confidence": 1.0},
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


def test_regression_table_projects_multiple_models_side_by_side_with_configurable_stars():
    table = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_id": "ols_1",
                    "model_label": "Baseline",
                    "nobs": 100,
                    "r_squared": 0.81,
                    "coefficients": {
                        "x": {
                            "estimate": 1.25,
                            "std_error": 0.2,
                            "confidence_interval": [0.8, 1.7],
                            "p_value": 0.15,
                            "source_id": "model_results.ols_1.coefficients.x",
                        },
                        "z": {
                            "estimate": -0.4,
                            "std_error": 0.1,
                            "p_value": 0.009,
                            "source_id": "model_results.ols_1.coefficients.z",
                        },
                    },
                },
            ),
            (
                "ols_2",
                {
                    "model_id": "ols_2",
                    "model_label": "With control",
                    "nobs": 95,
                    "r_squared": 0.84,
                    "coefficients": {
                        "x": {
                            "estimate": 1.1,
                            "std_error": 0.18,
                            "p_value": 0.04,
                            "source_id": "model_results.ols_2.coefficients.x",
                        },
                        "control": {
                            "estimate": 0.7,
                            "std_error": 0.3,
                            "p_value": 0.25,
                            "source_id": "model_results.ols_2.coefficients.control",
                        },
                    },
                },
            ),
        ],
        variable_labels={"x": "Treatment label", "z": "Baseline control"},
        significance_levels={"***": 0.01, "**": 0.05, "*": 0.20},
    )

    assert table["payload_schema"] == "workbench.regression-table"
    assert [(model["id"], model["label"]) for model in table["models"]] == [
        ("ols_1", "Baseline"),
        ("ols_2", "With control"),
    ]
    rows = {row["term"]: row for row in table["rows"]}
    assert set(rows) == {"x", "z", "control"}
    assert rows["x"]["label"] == "Treatment label"
    assert rows["x"]["models"]["ols_1"] == {
        "estimate": 1.25,
        "std_error": 0.2,
        "confidence_interval": [0.8, 1.7],
        "p_value": 0.15,
        "significance": "*",
        "source_id": "model_results.ols_1.coefficients.x",
    }
    assert rows["x"]["models"]["ols_2"]["significance"] == "**"
    assert rows["z"]["models"]["ols_1"]["significance"] == "***"
    assert rows["z"]["models"]["ols_2"] is None
    assert rows["control"]["models"]["ols_1"] is None
    assert rows["control"]["models"]["ols_2"]["source_id"] == (
        "model_results.ols_2.coefficients.control"
    )


def test_regression_table_packet_reaches_html_pdf_and_xlsx_exports(tmp_path: Path):
    project = create_project(tmp_path, "regression-table")
    run = create_run(project.root, mode="auto")
    packet = build_regression_table(
        [
            (
                "ols_1",
                {
                    "model_label": "Baseline",
                    "coefficients": {
                        "x": {
                            "estimate": 1.25,
                            "std_error": 0.2,
                            "confidence_interval": [0.8, 1.7],
                            "p_value": 0.04,
                            "source_id": "model_results.ols_1.coefficients.x",
                        }
                    },
                },
            )
        ],
        variable_labels={"x": "Treatment label"},
    )
    report = {
        "title": "Regression table report",
        "facts": [],
        "claims": [],
        "warnings": [],
        "regression_table": packet,
    }

    html_path = render_html_report(report, run.root)
    pdf_path = export_pdf(report, run.root)
    from workbench.engine.stages.report import _xlsx_export_rows

    xlsx_path = export_xlsx(
        {"regression_table": _xlsx_export_rows(regression_table_export_rows(packet))},
        run.root,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "Treatment label" in html
    assert "model_results.ols_1.coefficients.x" in html
    assert b"Regression table" in pdf_path.read_bytes()
    assert b"model_results.ols_1.coefficients.x" in pdf_path.read_bytes()
    workbook = __import__("openpyxl").load_workbook(xlsx_path, read_only=True)
    rows = list(workbook["regression_table"].iter_rows(values_only=True))
    assert "ols_1 significance" in rows[0]
    assert "model_results.ols_1.coefficients.x" in rows[1]
    assert "[0.8,1.7]" in rows[1]


def test_pdf_and_xlsx_keep_variable_and_value_labels(tmp_path: Path):
    project = create_project(tmp_path, "labelled-exports")
    run = create_run(project.root, mode="auto")
    table_1 = [
        {
            "column": "group",
            "label": "Treatment group",
            "label_source": "declared",
            "value_labels": {"0": "Control", "1": "Treated"},
            "dtype": "int64",
            "count": 4,
            "missing": 0,
            "unique_count": 2,
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
        }
    ]
    report = {
        "title": "Labelled export report",
        "facts": [],
        "claims": [],
        "descriptive_stats": table_1,
        "warnings": [],
    }

    pdf_path = export_pdf(report, run.root)
    xlsx_path = export_xlsx({"table_1": table_1}, run.root)

    pdf_bytes = pdf_path.read_bytes()
    assert b"Treatment group" in pdf_bytes
    assert b"Control" in pdf_bytes
    assert b"Treated" in pdf_bytes
    workbook = __import__("openpyxl").load_workbook(xlsx_path, read_only=True)
    rows = list(workbook["table_1"].iter_rows(values_only=True))
    flattened = " ".join(str(value) for row in rows for value in row)
    assert "Treatment group" in flattened
    assert "Control" in flattened
    assert "Treated" in flattened


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


def test_lmm_export_rows_are_excel_scalar_safe() -> None:
    """Versioned LMM coefficients include CI arrays that XLSX cannot store raw."""

    from workbench.engine.stages.report import _xlsx_export_rows

    rows = _xlsx_export_rows([
        {
            "model_id": "linear_mixed_effects_1",
            "term": "group_time_interaction",
            "estimate": 0.94,
            "confidence_interval": [0.88, 1.00],
        }
    ])

    assert rows == [
        {
            "model_id": "linear_mixed_effects_1",
            "term": "group_time_interaction",
            "estimate": 0.94,
            "confidence_interval": "[0.88,1.0]",
        }
    ]


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
    assert "<h2>Statistical Tests</h2>" in html
    assert "Pearson correlation: y vs x" in html
    assert b"Statistical tests" in pdf_path.read_bytes()


def test_report_renders_typed_statistical_evidence_and_preserves_table_fields(tmp_path: Path):
    project = create_project(tmp_path, "evidence-report")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Evidence Report",
        "facts": [],
        "claims": [],
        "descriptive_stats": [{"column": "y", "dtype": "float64", "count": 9, "missing": 0, "missing_rate": 0.0, "mean": 2.0, "std": 0.8}],
        "statistical_tests": {"y_related": [], "other": [], "other_truncated": 0},
        "statistical_evidence": {
            "payload_schema": "workbench.statistics.evidence-packet",
            "schema_version": 1,
            "correction_scope": "advanced_evidence_family",
            "results": [
                {
                    "test_type": "anova_posthoc",
                    "test_id": "anova_posthoc:y:region",
                    "nobs": 9,
                    "statistic": 12.0,
                    "p_value": 0.01,
                    "p_value_corrected": 0.02,
                    "effect_size": {"effect_size_name": "eta_squared", "value": 0.7},
                    "assumptions": ["independent observations"],
                    "warnings": [],
                }
            ],
        },
        "warnings": [],
    }

    html_path = render_html_report(report, run.root)
    html = html_path.read_text(encoding="utf-8")

    assert "Statistical Evidence" in html
    assert "anova_posthoc" in html
    assert "eta_squared" in html
    assert "advanced_evidence_family" in html


def test_report_formats_tiny_variable_importance_p_values(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": [],
        "claims": [{"claim": "x is significant at the 1% level", "source_id": "src"}],
        "warnings": [],
    }

    html_path = render_html_report(report, run.root)

    html = html_path.read_text(encoding="utf-8")
    assert "significant at the 1% level" in html


def test_report_formats_tiny_diagnostic_p_values(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    report = {
        "title": "Demo Report",
        "facts": [],
        "claims": [],
        "warnings": [],
        "diagnostics": {
            "ols_1": {
                "breusch_pagan": {"lm": 25.0, "p_value": 0.0000002},
                "jarque_bera": {"statistic": 40.0, "p_value": 0.0000003},
            }
        },
    }

    html_path = render_html_report(report, run.root)

    html = html_path.read_text(encoding="utf-8")
    assert "p &lt; 0.001" in html
    assert "p = 0.0000" not in html


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
    assert "<h2>Descriptive Statistics</h2>" in html
    assert "y" in html
    assert "float64" in html
    assert "10.5" in html
    assert "3.2" in html
    assert b"Descriptive statistics" in pdf_path.read_bytes()
