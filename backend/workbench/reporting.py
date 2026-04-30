from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .artifacts import register_artifact, write_text_durable


def render_html_report(report: dict[str, Any], run_root: Path) -> Path:
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_path = reports_dir / "report.html"

    environment = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    template = environment.get_template("report.html.j2")
    write_text_durable(html_path, template.render(report=report))
    register_artifact(run_root, "report_html", html_path, "report", "reporting", [])
    return html_path
