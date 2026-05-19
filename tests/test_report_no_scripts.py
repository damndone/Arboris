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


def _minimal_view_model() -> dict:
    return {
        "title": "Test Report",
        "facts": ["Fact 1", "Fact 2"],
        "critical_errors": [],
        "warnings": [],
        "cautions": [],
        "system_notes": [],
        "coefficient_interpretations": [],
        "causal_caution": "These estimates are associations, not necessarily causal effects.",
        "descriptive_stats": None,
        "statistical_tests": None,
        "model_diagnostics": {},
        "model_quality": None,
    }


class TestReportContent:
    def test_no_script_tags(self):
        html = _environment().get_template("report.html.j2").render(view_model=_minimal_view_model())
        assert "<script" not in html

    def test_no_javascript_uris(self):
        html = _environment().get_template("report.html.j2").render(view_model=_minimal_view_model())
        assert "javascript:" not in html.lower()

    def test_no_inline_event_handlers(self):
        html = _environment().get_template("report.html.j2").render(view_model=_minimal_view_model())
        assert not re.search(r"\son[a-zA-Z]+\s*=", html, re.IGNORECASE)

    def test_warnings_section_renders(self):
        vm = _minimal_view_model()
        vm["warnings"] = [{"text": "Warning: multicollinearity detected", "code": "X", "severity": "WARNING"}]
        html = _environment().get_template("report.html.j2").render(view_model=vm)
        assert "multicollinearity detected" in html
        assert "warning" in html.lower()

    def test_critical_errors_section_renders(self):
        vm = _minimal_view_model()
        vm["critical_errors"] = [{"text": "Model failed to converge", "code": "X", "severity": "BLOCKER"}]
        html = _environment().get_template("report.html.j2").render(view_model=vm)
        assert "Model failed to converge" in html
        assert "This report may not be reliable" in html

    def test_empty_view_model_renders(self):
        vm = _minimal_view_model()
        html = _environment().get_template("report.html.j2").render(view_model=vm)
        assert "Test Report" in html
        assert "Fact 1" in html
        assert "Causal Caution" in html
