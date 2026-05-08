"""Report output must not contain executable content that
would be blocked by the sandbox attribute."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


_TEMPLATE_DIR = Path(__file__).parent.parent / "backend" / "workbench" / "templates"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )


def _minimal_report() -> dict:
    return {
        "title": "Test Report",
        "facts": ["Fact 1", "Fact 2"],
        "claims": [
            {"claim": "Claim 1", "source_id": "src1", "confidence": 0.95},
        ],
        "warnings": [],
    }


class TestReportContent:
    def test_no_script_tags(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert "<script" not in html

    def test_no_javascript_uris(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert "javascript:" not in html.lower()

    def test_no_inline_event_handlers(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert not re.search(r"\son[a-zA-Z]+\s*=", html, re.IGNORECASE)

    def test_overdispersion_section_renders(self):
        report = _minimal_report()
        report["overdispersion"] = {
            "overdispersion_ratio": 1.25,
            "zero_rate": 0.15,
            "mean_y": 2.5,
            "var_y": 4.5,
        }
        html = _environment().get_template("report.html.j2").render(report=report)
        assert "Poisson overdispersion" in html
        assert "1.2500" in html
        assert "15.0%" in html
        assert "2.5000" in html
        assert "4.5000" in html

    def test_overdispersion_warning_renders(self):
        report = _minimal_report()
        report["overdispersion"] = {
            "overdispersion_ratio": 3.5,
            "zero_rate": 0.4,
            "mean_y": 1.2,
            "var_y": 8.0,
            "warning": "Severe overdispersion detected",
        }
        html = _environment().get_template("report.html.j2").render(report=report)
        assert "Warning: Severe overdispersion detected" in html

    def test_overdispersion_missing_fields_handled(self):
        report = _minimal_report()
        report["overdispersion"] = {
            "overdispersion_ratio": None,
            "zero_rate": None,
            "mean_y": 0.0,
            "var_y": 0.0,
        }
        html = _environment().get_template("report.html.j2").render(report=report)
        assert "Poisson overdispersion" in html
        assert "N/A" in html
