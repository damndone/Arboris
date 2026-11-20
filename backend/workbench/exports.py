from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
import io
import textwrap
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .artifacts import register_artifact


def export_pdf(
    report: Mapping[str, Any],
    run_root: Path,
    *,
    filename: str = "report.pdf",
    artifact_id: str = "report_pdf",
    inputs: Sequence[str] = (),
) -> Path:
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = reports_dir / filename

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
        regression_table = report.get("regression_table")
        if isinstance(regression_table, Mapping):
            y = _draw_section(
                pdf,
                "Regression table",
                _regression_pdf_items(regression_table),
                y,
            )
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
    curve = report.get("specification_curve")
    if curve:
        for image in curve["images"]:
            pdf.showPage()
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(54, height-48, "Specification curve")
            reader = ImageReader(io.BytesIO(base64.b64decode(image.split(",",1)[1])))
            width_px, height_px = reader.getSize()
            draw_height = min(480, 504*height_px/width_px)
            pdf.drawImage(reader, 54, height-100-draw_height, width=504, height=draw_height)
            pdf.setFont("Helvetica", 8)
            pdf.drawString(54, 72, "All frozen members retained. Preregistration/comparability unverified; intervals not simultaneous.")
        pdf.showPage()
        lines = []
        for row in curve["rows"]:
            for key in ["step_id", "branch_id", "status", "estimate", "std_error", "ci_lower", "ci_upper", "nobs", "reason"]:
                value = row.get(key)
                lines.extend(textwrap.wrap(f"{key}: {value if value is not None else 'Unavailable'}", width=78))
            lines.append("")
        _draw_section(pdf, "Specification curve native values", lines, height-72)
    if report.get("research_specifications"):
        sections = report["research_specifications"]
        for key, title in (("pre_specified", "Pre-specified analyses"), ("exploratory", "Exploratory analyses")):
            pdf.showPage()
            lines = []
            for row in sections[key]:
                text = f"{row['step_id']} / {row['operation_id']} | {row['status']} | {row['verification']}: {row['reason']} | {row['run_id']} / {row['record_id']}"
                lines.extend(textwrap.wrap(text, width=85))
            _draw_section(pdf, title, lines or ["No analyses with this classification are recorded."], height-72)
    if report.get("research_review"):
        _draw_research_review_pdf(pdf, report["research_review"], report["research_review_rows"])
    pdf.save()

    register_artifact(run_root, artifact_id, pdf_path, "report", "export", list(inputs))
    return pdf_path


def _draw_research_review_pdf(pdf, review, rows):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Embed a subset of the supported macOS host's Unicode font: a viewer must
    # not need an external CJK language pack to render a saved review.
    font = "ArborisReviewUnicode"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
    pdf.showPage()
    y = letter[1] - 60
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(54, y, "Isolated research review")
    y -= 28
    lines = [review['scope'], 'Evidence status: ' + review['evidence_status'],
        'Original verdict: ' + review['result']['verdict'], 'Review: ' + review['review_id'],
        'Evidence packet: ' + review['packet_sha256'], 'Evidence manifest: ' + review['manifest_sha256']]
    if review['evidence_status'] != 'unchanged':
        lines.append('Historical opinion: current evidence changed or could not be verified.')
    for row in rows:
        lines.extend(['', row['severity'] + ': ' + row['message'], 'References: ' + row['evidence_refs']])
    for paragraph in lines:
        for line in textwrap.wrap(paragraph, width=50) or ['']:
            if y < 60:
                pdf.showPage()
                y = letter[1] - 60
            pdf.setFont(font, 10)
            pdf.drawString(54, y, line)
            y -= 15


def export_xlsx(
    tables: Mapping[str, Sequence[Mapping[str, Any]]],
    run_root: Path,
    *,
    filename: str = "tables.xlsx",
    artifact_id: str = "tables_xlsx",
    inputs: Sequence[str] = (),
) -> Path:
    exports_dir = run_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = exports_dir / filename

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
            worksheet.append([_excel_value(row.get(header, "")) for header in headers])
        worksheet.auto_filter.ref = worksheet.dimensions
        for index, header in enumerate(headers, start=1):
            values = [str(header)] + [str(row.get(header, "")) for row in normalized_rows[:200]]
            worksheet.column_dimensions[get_column_letter(index)].width = min(48, max(12, max(map(len, values)) + 2))
    if not workbook.worksheets:
        workbook.create_sheet(title="tables")
    workbook.save(xlsx_path)

    register_artifact(run_root, artifact_id, xlsx_path, "table_export", "export", list(inputs))
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


def _number(value: Any) -> str:
    # A one-row column has no standard deviation; the PDF said so by failing the whole step (QRData 403,
    # 3724e8b2 round: "unsupported format string passed to NoneType.__format__").
    return "n/a" if value is None else f"{value:.4f}"


def _report_item_text(item: Any) -> str:
    if not isinstance(item, Mapping):
        return str(item)
    if "column" in item and "dtype" in item:
        raw_column = str(item.get("column", ""))
        display_column = str(item.get("label") or raw_column)
        column_text = (
            display_column
            if display_column == raw_column
            else f"{display_column} ({raw_column})"
        )
        value_labels = _value_labels_text(item.get("value_labels"))
        dtype = item.get("dtype", "")
        missing = item.get("missing", 0)
        unique = item.get("unique_count", 0)
        if item.get("mean") is not None:
            return (
                f"{column_text} ({dtype}): "
                f"mean={_number(item['mean'])} std={_number(item.get('std'))} "
                f"min={_number(item.get('min'))} max={_number(item.get('max'))} "
                f"missing={missing} unique={unique}{value_labels}"
            )
        return (
            f"{column_text} ({dtype}): "
            f"missing={missing} unique={unique}{value_labels}"
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


def _value_labels_text(value_labels: object) -> str:
    if not isinstance(value_labels, Mapping) or not value_labels:
        return ""
    rendered = ", ".join(
        f"{value}={label}" for value, label in value_labels.items()
    )
    return f" values: {rendered}"


def _excel_value(value: Any) -> Any:
    """Convert structured metadata into a lossless, Excel-safe scalar."""
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _regression_pdf_items(table: Mapping[str, Any]) -> list[str]:
    models = [model for model in table.get("models", []) if isinstance(model, Mapping)]
    items: list[str] = []
    for row in table.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        parts = [f"{row.get('label', row.get('term', ''))} ({row.get('term', '')})"]
        cells = row.get("models", {})
        for model in models:
            model_id = str(model.get("id", ""))
            cell = cells.get(model_id) if isinstance(cells, Mapping) else None
            if not isinstance(cell, Mapping):
                parts.append(f"{model.get('label', model_id)}: unavailable")
                continue
            value = (
                f"{model.get('label', model_id)}: estimate={cell.get('estimate', '—')}"
                f" se={cell.get('std_error', '—')} p={cell.get('p_value', '—')}"
                f" {cell.get('significance', '')}".rstrip()
            )
            source_id = cell.get("source_id")
            if source_id:
                value += f" [source: {source_id}]"
            parts.append(value)
        items.append(" | ".join(parts))
    return items


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
