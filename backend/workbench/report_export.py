"""Dependency-light exports for the LLM report path.

The frontend and this module intentionally share the same small Markdown
contract: headings (#--####), unordered/ordered lists, fenced code, bold,
italic, inline code, horizontal rules, and ``[[fig:artifact_id]]`` figure
markers. The model never receives pixels; export resolves each marker against
the run's figure artifact and embeds the original bytes.
"""

from __future__ import annotations

import base64
import html
import io
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .artifacts import read_json

FIGURE_MARKER = re.compile(r"\[\[fig:([A-Za-z0-9._-]+)\]\]")
_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_ORDERED = re.compile(r"^\d+[.)]\s+(.*)$")


class ReportExportError(ValueError):
    """A user-visible report export validation or materialisation error."""


def _figure_assets(run_root: Path, figures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index = read_json(run_root / "artifacts_index.json")
    records = {
        str(record.get("artifact_id")): record
        for record in index.get("artifacts", [])
        if isinstance(record, dict)
    }
    assets: dict[str, dict[str, Any]] = {}
    for item in figures:
        artifact_id = str(item.get("artifact_id", ""))
        if FIGURE_MARKER.fullmatch(f"[[fig:{artifact_id}]]") is None:
            raise ReportExportError(f"Invalid figure artifact id: {artifact_id!r}")
        record = records.get(artifact_id)
        if record is None or record.get("artifact_type") != "figure":
            raise ReportExportError(f"Figure artifact was not found: {artifact_id}")
        path = (run_root / str(record.get("path", ""))).resolve()
        try:
            path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise ReportExportError("Figure artifact escapes the run root") from exc
        if not path.is_file():
            raise ReportExportError(f"Figure artifact file was not found: {artifact_id}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        assets[artifact_id] = {
            "artifact_id": artifact_id,
            "caption": str(item.get("chart_type") or artifact_id),
            "path": path,
            "extension": path.suffix.lower().lstrip(".") or "bin",
            "mime": mime,
            "data": data,
            "data_uri": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
        }
    return assets


def _inline_html(text: str, assets: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    last = 0
    for match in FIGURE_MARKER.finditer(text):
        parts.append(_inline_text_html(text[last:match.start()]))
        asset = assets.get(match.group(1))
        if asset is None:
            parts.append(f"<span class=\"missing-figure\">[Figure unavailable: {html.escape(match.group(1))}]</span>")
        else:
            caption = html.escape(asset["caption"])
            parts.append(
                f'<figure><img src="{asset["data_uri"]}" alt="{caption}">'  # noqa: E501
                f"<figcaption>{caption}</figcaption></figure>"
            )
        last = match.end()
    parts.append(_inline_text_html(text[last:]))
    return "".join(parts)


def _inline_text_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*\s][^*]*)\*", r"<em>\1</em>", escaped)
    return escaped


def _blocks(markdown: str) -> list[tuple[str, Any]]:
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[tuple[str, Any]] = []
    paragraph: list[str] = []
    current_list: tuple[str, list[str]] | None = None
    fence: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(("paragraph", " ".join(paragraph)))
            paragraph = []

    def flush_list() -> None:
        nonlocal current_list
        if current_list is not None:
            blocks.append(("list", current_list))
            current_list = None

    for line in lines:
        if fence is not None:
            if line.strip().startswith("```"):
                blocks.append(("code", "\n".join(fence)))
                fence = None
            else:
                fence.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            fence = []
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            flush_list()
            blocks.append(("heading", (len(heading.group(1)), heading.group(2))))
            continue
        if re.fullmatch(r"(?:-{3,}|\*{3,})", stripped):
            flush_paragraph()
            flush_list()
            blocks.append(("rule", None))
            continue
        bullet = _BULLET.match(stripped)
        ordered = _ORDERED.match(stripped)
        if bullet or ordered:
            flush_paragraph()
            kind = "ordered" if ordered else "bullet"
            if current_list is None or current_list[0] != kind:
                flush_list()
                current_list = (kind, [])
            current_list[1].append((bullet or ordered).group(1))
            continue
        if stripped == "":
            flush_paragraph()
            flush_list()
            continue
        if current_list is not None:
            current_list[1][-1] += " " + stripped
        else:
            paragraph.append(stripped)
    if fence is not None:
        blocks.append(("code", "\n".join(fence)))
    flush_paragraph()
    flush_list()
    return blocks


def render_report_html(markdown: str, assets: dict[str, dict[str, Any]]) -> str:
    body: list[str] = []
    for kind, value in _blocks(markdown):
        if kind == "heading":
            level, text = value
            body.append(f"<h{level}>{_inline_html(text, assets)}</h{level}>")
        elif kind == "paragraph":
            body.append(f"<p>{_inline_html(value, assets)}</p>")
        elif kind == "code":
            body.append(f"<pre><code>{html.escape(value)}</code></pre>")
        elif kind == "rule":
            body.append("<hr>")
        else:
            list_kind, items = value
            tag = "ol" if list_kind == "ordered" else "ul"
            body.append("<" + tag + ">" + "".join(f"<li>{_inline_html(item, assets)}</li>" for item in items) + f"</{tag}>")
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>Econometrics Workbench report</title>
<style>body{font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:32px auto;padding:0 24px;line-height:1.6;color:#202124}figure{margin:20px 0;break-inside:avoid}figure img{max-width:100%;height:auto}figcaption{color:#666;font-size:.9em}pre{background:#f4f4f4;padding:12px;overflow:auto}@media print{body{margin:0;max-width:none}figure{break-inside:avoid}}</style>
</head><body>""" + "\n".join(body) + "</body></html>"


def _latex_text(text: str) -> str:
    value = re.sub(r"[*`]+", "", text)
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}
    return "".join(replacements.get(char, char) for char in value)


def render_report_tex(markdown: str, assets: dict[str, dict[str, Any]]) -> str:
    lines = [
        r"\documentclass{article}",
        r"\usepackage{graphicx}",
        r"\usepackage[margin=1in]{geometry}",
        r"\begin{document}",
    ]
    for kind, value in _blocks(markdown):
        if kind == "heading":
            level, text = value
            command = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}[level]
            lines.append(f"\\{command}{{{_latex_text(text)}}}")
        elif kind == "paragraph":
            last = 0
            for match in FIGURE_MARKER.finditer(value):
                if match.start() > last:
                    lines.append(_latex_text(value[last:match.start()]))
                asset = assets.get(match.group(1))
                if asset:
                    lines.extend([
                        r"\begin{figure}[ht]",
                        r"\centering",
                        f"\\includegraphics[width=0.95\\linewidth]{{figures/{asset['artifact_id']}.{asset['extension']}}}",
                        f"\\caption{{{_latex_text(asset['caption'])}}}",
                        r"\end{figure}",
                    ])
                else:
                    lines.append(_latex_text(f"[Figure unavailable: {match.group(1)}]"))
                last = match.end()
            if last < len(value):
                lines.append(_latex_text(value[last:]))
            lines.append("")
        elif kind == "code":
            lines.extend([r"\begin{verbatim}", value, r"\end{verbatim}"])
        elif kind == "rule":
            lines.append(r"\hrulefill")
        else:
            list_kind, items = value
            env = "enumerate" if list_kind == "ordered" else "itemize"
            lines.append(f"\\begin{{{env}}}")
            lines.extend(f"\\item {_latex_text(item)}" for item in items)
            lines.append(f"\\end{{{env}}}")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _docx_run(text: str, *, bold: bool = False, italic: bool = False) -> str:
    props = ""
    if bold:
        props += "<w:b/>"
    if italic:
        props += "<w:i/>"
    return f"<w:r>{('<w:rPr>' + props + '</w:rPr>') if props else ''}<w:t xml:space=\"preserve\">{xml_escape(text)}</w:t></w:r>"


def _docx_paragraph(text: str, *, style: str | None = None) -> str:
    ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
    return f"<w:p>{ppr}{_docx_run(text)}</w:p>"


_DOCX_INLINE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)")


def _docx_text_runs(text: str) -> str:
    """Render the shared inline Markdown subset as Word runs."""
    runs: list[str] = []
    last = 0
    for match in _DOCX_INLINE.finditer(text):
        if match.start() > last:
            runs.append(_docx_run(text[last:match.start()]))
        token = match.group(1)
        if token.startswith("**") and token.endswith("**"):
            runs.append(_docx_run(token[2:-2], bold=True))
        elif token.startswith("`") and token.endswith("`"):
            runs.append(_docx_run(token[1:-1]))
        else:
            runs.append(_docx_run(token[1:-1], italic=True))
        last = match.end()
    if last < len(text):
        runs.append(_docx_run(text[last:]))
    return "".join(runs)


def _docx_image_run(
    asset: dict[str, Any],
    *,
    image_index: int,
) -> tuple[str, str, str, bytes]:
    rid = f"rId{image_index + 1}"
    filename = f"image{image_index}.{asset['extension']}"
    relationship = (
        f'<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/{filename}"/>'
    )
    drawing = (
        f"<w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
        f"<wp:extent cx=\"5486400\" cy=\"3657600\"/>"
        f"<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
        f"<wp:docPr id=\"{image_index}\" name=\"Picture {image_index}\"/>"
        f"<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect=\"1\"/></wp:cNvGraphicFramePr>"
        f"<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        f"<pic:pic><pic:nvPicPr><pic:cNvPr id=\"{image_index}\" name=\"{xml_escape(filename)}\"/>"
        f"<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed=\"{rid}\"/>"
        f"<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        f"<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"5486400\" cy=\"3657600\"/></a:xfrm>"
        f"<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>"
        f"</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )
    return drawing, relationship, filename, asset["data"]


def _docx_paragraph_with_inline(
    text: str,
    *,
    assets: dict[str, dict[str, Any]],
    rels: list[str],
    media: list[tuple[str, bytes]],
    image_counter: list[int],
    style: str | None = None,
) -> str:
    ppr = f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""
    runs: list[str] = []
    last = 0
    for match in FIGURE_MARKER.finditer(text):
        if match.start() > last:
            runs.append(_docx_text_runs(text[last:match.start()]))
        asset = assets.get(match.group(1))
        if asset is None:
            runs.append(_docx_text_runs(f"[Figure unavailable: {match.group(1)}]"))
        else:
            image_counter[0] += 1
            drawing, relationship, filename, data = _docx_image_run(
                asset, image_index=image_counter[0]
            )
            rels.append(relationship)
            media.append((filename, data))
            runs.append(drawing)
        last = match.end()
    if last < len(text):
        runs.append(_docx_text_runs(text[last:]))
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def render_report_docx(markdown: str, assets: dict[str, dict[str, Any]]) -> bytes:
    rels: list[str] = []
    media: list[tuple[str, bytes]] = []
    body: list[str] = []
    image_counter = [0]
    for kind, value in _blocks(markdown):
        if kind == "heading":
            level, text = value
            body.append(
                _docx_paragraph_with_inline(
                    text,
                    assets=assets,
                    rels=rels,
                    media=media,
                    image_counter=image_counter,
                    style=f"Heading{level}",
                )
            )
        elif kind == "paragraph":
            body.append(
                _docx_paragraph_with_inline(
                    value,
                    assets=assets,
                    rels=rels,
                    media=media,
                    image_counter=image_counter,
                )
            )
        elif kind == "code":
            body.append(_docx_paragraph(value))
        elif kind == "rule":
            body.append(_docx_paragraph("――――――――"))
        else:
            list_kind, items = value
            for index, item in enumerate(items, start=1):
                prefix = f"{index}. " if list_kind == "ordered" else "• "
                body.append(
                    _docx_paragraph_with_inline(
                        prefix + item,
                        assets=assets,
                        rels=rels,
                        media=media,
                        image_counter=image_counter,
                    )
                )

    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<w:body>" + "".join(body) + "<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpg" ContentType="image/jpeg"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    root_rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    document_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        for filename, data in media:
            archive.writestr(f"word/media/{filename}", data)
    return output.getvalue()


def export_report(
    run_root: Path,
    *,
    markdown: str,
    figures: list[dict[str, Any]],
    format: str,
) -> tuple[bytes, str, str]:
    if format not in {"html", "docx", "tex", "pdf-print"}:
        raise ReportExportError(f"Unsupported report export format: {format}")
    assets = _figure_assets(run_root, figures)
    if format in {"html", "pdf-print"}:
        filename = "report-print.html" if format == "pdf-print" else "report.html"
        return render_report_html(markdown, assets).encode("utf-8"), "text/html", filename
    if format == "docx":
        return render_report_docx(markdown, assets), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "report.docx"
    tex = render_report_tex(markdown, assets)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.tex", tex)
        for asset in assets.values():
            archive.writestr(f"figures/{asset['artifact_id']}.{asset['extension']}", asset["data"])
    return output.getvalue(), "application/zip", "report.tex.zip"


__all__ = ["ReportExportError", "export_report", "render_report_html", "render_report_docx", "render_report_tex"]
