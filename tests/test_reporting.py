"""Formal report/export writers must fail before any filesystem IO."""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.exports import export_pdf, export_xlsx
from workbench.reporting import render_html_report


@pytest.mark.parametrize(
    "writer, kwargs, expected_name",
    (
        (render_html_report, ({"title": "Report"},), "report.html"),
        (export_pdf, ({"title": "Report"},), "report.pdf"),
        (export_xlsx, ({"facts": []},), "tables.xlsx"),
    ),
)
def test_formal_writers_require_an_admitted_receipt_before_io(
    tmp_path: Path, writer, kwargs, expected_name: str
) -> None:
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)

    with pytest.raises(TypeError, match="writer|capability|projection|Report"):
        writer(*kwargs, run_root=run_root)

    assert not list(run_root.rglob(expected_name))
    assert not (run_root / "reports").exists()
    assert not (run_root / "exports").exists()


def test_formal_html_writer_rejects_a_symlinked_parent_before_external_write(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs" / "run-1"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_root / "reports").symlink_to(outside, target_is_directory=True)

    from tests.test_v189_evidence_report_boundary import _owner_issued_document_writer

    writer = _owner_issued_document_writer(
        tmp_path / "owner",
        {"title": "Report"},
        run_root,
    )
    with pytest.raises((OSError, ValueError)):
        render_html_report(writer, run_root, filename="escape.html")

    assert not (outside / "escape.html").exists()
