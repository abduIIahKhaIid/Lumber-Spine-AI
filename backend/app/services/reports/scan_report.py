"""PDF report for one analysis result."""

from __future__ import annotations

import base64
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.ml.severity import HEX, ORDER

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")
BRAND = colors.HexColor("#0f766e")
PRIORITY = {"high": "#dc2626", "medium": "#d97706", "low": "#0f766e"}


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=19, textColor=INK, alignment=0),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontSize=12.5,
            textColor=INK,
            spaceBefore=10,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "b", parent=base["BodyText"], fontSize=9, leading=12.5, textColor=INK
        ),
        "small": ParagraphStyle(
            "s", parent=base["BodyText"], fontSize=7.5, leading=10, textColor=MUTED
        ),
    }


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _image(data: str, width: float) -> Image:
    raw = BytesIO(base64.b64decode(data))
    image = Image(raw)
    ratio = image.imageHeight / float(image.imageWidth)
    image.drawWidth, image.drawHeight = width, width * ratio
    return image


def _chart(findings: list[dict]) -> Drawing:
    """Horizontal stacked bars: score per class for every assessed level."""
    labels = [f["level_label"] for f in findings][::-1]
    data = [[f["class_scores"].get(name, 0) * 100 for f in findings][::-1] for name in ORDER]
    height = max(70, 16 * len(labels) + 30)
    drawing = Drawing(170 * mm, height)
    chart = HorizontalBarChart()
    chart.x, chart.y = 28 * mm, 18
    chart.width, chart.height = 135 * mm, height - 30
    chart.data = data
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.valueMin, chart.valueAxis.valueMax, chart.valueAxis.valueStep = 0, 100, 25
    chart.valueAxis.labels.fontSize = 7
    chart.categoryAxis.style = "stacked"
    chart.bars.strokeColor = None
    for index, name in enumerate(ORDER):
        chart.bars[index].fillColor = colors.HexColor(HEX[name])
    drawing.add(chart)
    x = 28 * mm
    for name in ORDER:
        drawing.add(String(x, 4, f"■ {name}", fontSize=7, fillColor=colors.HexColor(HEX[name])))
        x += 30 * mm
    return drawing


def build_scan_report(result: dict, label: str = "") -> bytes:
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Lumbar spine AI analysis report",
    )
    findings = result.get("findings", [])
    summary = result.get("summary", {})
    elements = [
        _p("Lumbar spine AI analysis", styles["title"]),
        _p(
            f"{result.get('condition_name', '')} · {result.get('plane', '')} "
            f"{result.get('sequence', '')} · {result.get('mode', '').title()} scan · "
            f"{result.get('created_at', '')[:19].replace('T', ' ')} UTC",
            styles["small"],
        ),
        Spacer(1, 6),
    ]
    meta = [["Reference", label or "Not provided"], ["Analysis ID", result.get("analysis_id", "")]]
    counts = summary.get("counts", {})
    meta.append(["Findings", ", ".join(f"{name}: {counts.get(name, 0)}" for name in ORDER)])
    meta.append(["Highest grade", summary.get("max_severity") or "None"])
    table = Table(meta, colWidths=[35 * mm, 143 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements += [table, Spacer(1, 6)]

    if findings:
        elements.append(_p("Findings by level", styles["h2"]))
        rows = [["ID", "Level", "Severity", "Normal/Mild", "Moderate", "Severe", "Review"]]
        for f in findings:
            s = f["class_scores"]
            rows.append(
                [
                    f["id"],
                    f["level_label"],
                    f["severity"],
                    *(f"{s.get(name, 0) * 100:.0f}%" for name in ORDER),
                    "Yes" if f["uncertainty"]["status"] == "review" else "",
                ]
            )
        grid = Table(
            rows, colWidths=[12 * mm, 26 * mm, 28 * mm, 26 * mm, 26 * mm, 26 * mm, 18 * mm]
        )
        style = [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for row, f in enumerate(findings, start=1):
            style.append(
                (
                    "TEXTCOLOR",
                    (2, row),
                    (2, row),
                    colors.HexColor(HEX.get(f["severity"], "#334155")),
                )
            )
            style.append(("FONTNAME", (2, row), (2, row), "Helvetica-Bold"))
        grid.setStyle(TableStyle(style))
        elements += [grid, Spacer(1, 6), _chart(findings)]

    recommendations = result.get("recommendations", [])
    if recommendations:
        elements.append(_p("Recommended review steps", styles["h2"]))
        for item in recommendations:
            color = PRIORITY.get(item["priority"], "#334155")
            evidence = f" [{', '.join(item['evidence'])}]" if item.get("evidence") else ""
            elements.append(
                Paragraph(
                    f'<font color="{color}"><b>{escape(item["priority"].upper())}</b></font> '
                    f"<b>{escape(item['title'])}</b>{escape(evidence)}<br/>{escape(item['clinician'])}",
                    styles["body"],
                )
            )
            elements.append(Spacer(1, 4))

    images = result.get("images", [])
    if images:
        elements.append(_p("Annotated slices", styles["h2"]))
        width = 86 * mm if len(images) > 1 else 120 * mm
        cells = [_image(image["annotated"], width) for image in images]
        rows = [cells[i : i + 2] for i in range(0, len(cells), 2)]
        elements.append(Table(rows, hAlign="LEFT"))

    maps = [f for f in findings if f.get("explanation", {}).get("heatmap_image")]
    if maps:
        elements.append(_p("Focus maps (colored by predicted severity)", styles["h2"]))
        cells = [
            KeepTogether(
                [
                    _image(f["explanation"]["heatmap_image"], 40 * mm),
                    _p(f"{f['id']} {f['level_label']} · {f['severity']}", styles["small"]),
                ]
            )
            for f in maps
        ]
        elements.append(Table([cells[i : i + 4] for i in range(0, len(cells), 4)], hAlign="LEFT"))

    quality = result.get("quality", {})
    elements.append(_p("Image quality checks", styles["h2"]))
    elements.append(
        _p(
            "Review suggested" if quality.get("status") == "review" else "No basic flags",
            styles["body"],
        )
    )
    for issue in quality.get("issues", []):
        elements.append(_p(f"• {issue}", styles["body"]))

    provenance = result.get("provenance", {})
    elements += [
        Spacer(1, 8),
        _p(
            f"Pipeline {provenance.get('pipeline_version', '')}. Calibration: "
            f"{provenance.get('calibration', 'unavailable')}. Scores are model outputs, not "
            "calibrated probabilities. Focus maps show model sensitivity, not proof of disease.",
            styles["small"],
        ),
        _p(
            "DISCLAIMER: Generated by an AI research system. It is not a diagnosis and must be "
            "reviewed by a qualified clinician together with the original images and the "
            "patient's history and examination.",
            styles["small"],
        ),
    ]
    doc.build(elements)
    return buffer.getvalue()
