from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .artifacts import register_artifact


def export_pdf(report: Mapping[str, Any], run_root: Path) -> Path:
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = reports_dir / "report.pdf"

    pdf = canvas.Canvas(str(pdf_path), pagesize=letter, pageCompression=0)
    _, height = letter
    y = height - 72
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(72, y, str(report.get("title", "Report")))
    y -= 32

    y = _draw_section(pdf, "Facts", report.get("facts", []), y)
    y = _draw_section(pdf, "Interpretation", report.get("claims", []), y)
    y = _draw_section(pdf, "Statistical tests", report.get("statistical_tests", []), y)
    _draw_section(pdf, "Warnings", report.get("warnings", []), y)
    pdf.save()

    register_artifact(run_root, "report_pdf", pdf_path, "report", "export", [])
    return pdf_path


def export_xlsx(tables: Mapping[str, Sequence[Mapping[str, Any]]], run_root: Path) -> Path:
    exports_dir = run_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = exports_dir / "tables.xlsx"

    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    for name, rows in tables.items():
        worksheet = workbook.create_sheet(title=_sheet_title(name))
        normalized_rows = list(rows)
        headers = _headers(normalized_rows)
        worksheet.append(headers)
        for row in normalized_rows:
            worksheet.append([row.get(header, "") for header in headers])
    if not workbook.worksheets:
        workbook.create_sheet(title="tables")
    workbook.save(xlsx_path)

    register_artifact(run_root, "tables_xlsx", xlsx_path, "table_export", "export", [])
    return xlsx_path


def _draw_section(pdf: canvas.Canvas, title: str, items: Any, y: float) -> float:
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(72, y, title)
    y -= 18
    pdf.setFont("Helvetica", 10)
    for item in items:
        text = _report_item_text(item)
        pdf.drawString(90, y, f"- {text}")
        y -= 14
        if y < 72:
            pdf.showPage()
            y = letter[1] - 72
            pdf.setFont("Helvetica", 10)
    return y - 10


def _report_item_text(item: Any) -> str:
    if not isinstance(item, Mapping):
        return str(item)
    if item.get("label") and item.get("interpretation"):
        text = f"{item['label']}: {item['interpretation']}"
    else:
        text = str(item.get("claim", item.get("message", "")))
    source_id = item.get("source_id")
    if source_id:
        text = f"{text} [source: {source_id}]"
    confidence = item.get("confidence")
    if confidence is not None:
        text = f"{text} [confidence: {confidence}]"
    return text


def _headers(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(str(key))
    return headers


def _sheet_title(name: str) -> str:
    invalid_characters = set("[]:*?/\\")
    title = "".join(
        character if character not in invalid_characters else "_"
        for character in str(name)
    )
    return (title or "table")[:31]
