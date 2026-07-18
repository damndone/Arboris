from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.app import app
from workbench.artifacts import write_json
from workbench.projects import create_project, create_run
from workbench.report_export import export_report


def _fixture(tmp_path: Path) -> tuple[Path, str]:
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    (run.root / "figures").mkdir(parents=True, exist_ok=True)
    (run.root / "figures" / "coef_plot.png").write_bytes(b"\x89PNG fake")
    write_json(
        run.root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": "coef_plot",
                    "path": "figures/coef_plot.png",
                    "artifact_type": "figure",
                    "step": "visualization",
                    "sha256": "stub",
                    "inputs": [],
                }
            ],
        },
    )
    return project.root, run.run_id


def test_report_export_embeds_figures_in_html_and_print_html(tmp_path: Path) -> None:
    project_root, run_id = _fixture(tmp_path)
    markdown = "# Results\n\nThe effect is **positive**.\n\n[[fig:coef_plot]]"
    figures = [{"artifact_id": "coef_plot", "chart_type": "Coefficient plot"}]

    run_root = project_root / "runs" / run_id
    html, media, filename = export_report(
        run_root, markdown=markdown, figures=figures, format="html"
    )
    text = html.decode("utf-8")
    assert media == "text/html"
    assert filename == "report.html"
    assert "data:image/png;base64" in text
    assert "[[fig:" not in text
    assert "Coefficient plot" in text

    printed, _, print_name = export_report(
        run_root, markdown=markdown, figures=figures, format="pdf-print"
    )
    assert print_name == "report-print.html"
    assert b"@media print" in printed


def test_report_export_produces_docx_and_latex_zip_without_new_dependencies(tmp_path: Path) -> None:
    project_root, run_id = _fixture(tmp_path)
    run_root = project_root / "runs" / run_id
    markdown = "# Results\n\nThe effect is **positive** [[fig:coef_plot]].\n\n- one\n- two"
    figures = [{"artifact_id": "coef_plot", "chart_type": "Coefficient plot"}]

    docx, media, _ = export_report(
        run_root, markdown=markdown, figures=figures, format="docx"
    )
    assert media.startswith("application/vnd.openxmlformats")
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        names = set(archive.namelist())
        assert "word/document.xml" in names
        assert "word/media/image1.png" in names
        document = archive.read("word/document.xml")
        assert b"Results" in document
        assert b"<w:b/>" in document
        assert b"**positive**" not in document
        assert b"<w:drawing>" in document
        assert "• one".encode() in document

    tex_zip, media, filename = export_report(
        run_root, markdown=markdown, figures=figures, format="tex"
    )
    assert media == "application/zip"
    assert filename == "report.tex.zip"
    with zipfile.ZipFile(io.BytesIO(tex_zip)) as archive:
        assert "report.tex" in archive.namelist()
        assert "figures/coef_plot.png" in archive.namelist()
        tex = archive.read("report.tex").decode("utf-8")
        assert "includegraphics" in tex
        assert "[[fig:" not in tex


def test_report_export_route_rejects_unknown_figure_and_returns_file(tmp_path: Path) -> None:
    project_root, run_id = _fixture(tmp_path)
    client = TestClient(app)
    response = client.post(
        f"/runs/{run_id}/report/export",
        params={"project_root": str(project_root), "format": "html"},
        json={"markdown": "# Report\n\n[[fig:coef_plot]]", "figures": [{"artifact_id": "coef_plot"}]},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert b"data:image/png;base64" in response.content

    missing = client.post(
        f"/runs/{run_id}/report/export",
        params={"project_root": str(project_root), "format": "html"},
        json={"markdown": "[[fig:missing]]", "figures": [{"artifact_id": "missing"}]},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "REPORT_EXPORT_INVALID"
