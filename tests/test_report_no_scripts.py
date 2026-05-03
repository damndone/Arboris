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
