from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
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
    if report.get("report_kind") == "arma_garch":
        _draw_arma_garch_pdf(pdf, report, y)
    else:
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(72, y, str(report.get("title", "Report")))
        y -= 32

        y = _draw_section(pdf, "Facts", report.get("facts", []), y)
        y = _draw_section(pdf, "Descriptive statistics", report.get("descriptive_stats", []), y)
        y = _draw_section(pdf, "Interpretation", report.get("claims", []), y)
        st = report.get("statistical_tests")
        if isinstance(st, Mapping):
            y = _draw_section(pdf, "Statistical tests (outcome-related)", st.get("y_related", []), y)
            other = st.get("other", [])
            truncated = st.get("other_truncated", 0)
            if other:
                y = _draw_section(pdf, f"Other tests (+{truncated} truncated)", other, y)
        else:
            y = _draw_section(pdf, "Statistical tests", st or [], y)
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
        worksheet.freeze_panes = "A2"
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        for row in normalized_rows:
            worksheet.append([row.get(header, "") for header in headers])
        worksheet.auto_filter.ref = worksheet.dimensions
        for index, header in enumerate(headers, start=1):
            values = [str(header)] + [str(row.get(header, "")) for row in normalized_rows[:200]]
            worksheet.column_dimensions[get_column_letter(index)].width = min(48, max(12, max(map(len, values)) + 2))
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


def _draw_arma_garch_pdf(pdf: canvas.Canvas, report: Mapping[str, Any], y: float) -> None:
    """Render the native time-series evidence in a paginated, searchable PDF."""
    _, height = letter

    def heading(text: str, position: float, level: int = 1) -> float:
        if position < 86:
            pdf.showPage()
            position = height - 72
        pdf.setFont("Helvetica-Bold", 14 if level == 1 else 11)
        pdf.drawString(54, position, text)
        return position - (24 if level == 1 else 18)

    def line(label: str, value: object, position: float) -> float:
        if position < 72:
            pdf.showPage()
            position = height - 72
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(64, position, _pdf_text(label, 27))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(210, position, _pdf_text(value, 70))
        return position - 13

    y = heading(str(report.get("title", "ARMA-GARCH Volatility Report")), y)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(54, y, _pdf_text(report.get("model_label", ""), 100))
    y -= 24
    y = heading("Run and model contract", y, level=2)
    for row in report.get("overview", []):
        if isinstance(row, Mapping):
            y = line(str(row.get("field", "")), row.get("value", ""), y)
    y = heading("Rolling forecast evaluation", y, level=2)
    for key in ("validation_n", "successful_forecast_n", "mae", "rmse", "interval_coverage", "average_interval_width"):
        y = line(key.replace("_", " ").title(), report.get("metrics", {}).get(key, "—") if isinstance(report.get("metrics"), Mapping) else "—", y)
    y = heading("Selected parameters", y, level=2)
    for row in report.get("parameters", []):
        if isinstance(row, Mapping):
            y = line(f"{row.get('component', '')}: {row.get('parameter', '')}", row.get("estimate", ""), y)
    y = heading("Production next-observation forecast", y, level=2)
    for row in report.get("next_forecast", []):
        if isinstance(row, Mapping):
            y = line(str(row.get("field", "")), row.get("value", ""), y)
    y = heading("Residual diagnostics", y, level=2)
    for row in report.get("diagnostics", []):
        if not isinstance(row, Mapping):
            continue
        statistic, p_value = row.get("statistic", "—"), row.get("p_value", "—")
        detail = row.get("detail", "")
        summary = f"stat={statistic} p={p_value} [{row.get('status', '—')}]"
        y = line(str(row.get("test", "")), f"{summary} {detail}".strip(), y)
    y = heading("Interpretation limits", y, level=2)
    for item in report.get("limitations", []):
        y = line("Limit", item, y)
    y = heading("Chart evidence", y, level=2)
    chart_artifacts = report.get("chart_artifacts", [])
    y = line("Registered chart artifacts", len(chart_artifacts), y)
    # Every registered chart is listed: a fixed cap here silently disagreed with
    # the count printed directly above it as soon as the pack grew a chart.
    for artifact_id in chart_artifacts:
        y = line("artifact", artifact_id, y)


def _pdf_text(value: object, length: int) -> str:
    text = str(value).replace("\n", " ").replace("–", "-")
    return text if len(text) <= length else f"{text[: length - 1]}…"


def _report_item_text(item: Any) -> str:
    if not isinstance(item, Mapping):
        return str(item)
    if "column" in item and "dtype" in item:
        dtype = item.get("dtype", "")
        missing = item.get("missing", 0)
        unique = item.get("unique_count", 0)
        if item.get("mean") is not None:
            return (
                f"{item['column']} ({dtype}): "
                f"mean={item['mean']:.4f} std={item['std']:.4f} "
                f"min={item['min']:.4f} max={item['max']:.4f} "
                f"missing={missing} unique={unique}"
            )
        return (
            f"{item['column']} ({dtype}): "
            f"missing={missing} unique={unique}"
        )
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
