"""PDF report for one analysis result (A4, ReportLab)."""

from __future__ import annotations

import base64
import contextlib
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    CondPageBreak,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.ml.severity import HEX, ORDER

INK = colors.HexColor("#14212e")
MUTED = colors.HexColor("#5b6b7b")
RULE = colors.HexColor("#d5dce3")
BONE = colors.HexColor("#eef1f4")
WASH = {"Normal/Mild": "#dcfce7", "Moderate": "#fef9c3", "Severe": "#fee2e2"}
DARK = {"Normal/Mild": "#15803d", "Moderate": "#a16207", "Severe": "#b91c1c"}
PRIORITY = {
    "high": ("Act first", "#ef4444", "#b91c1c"),
    "medium": ("Review", "#eab308", "#a16207"),
    "low": ("Keep in mind", "#2b59c3", "#1f4396"),
}
CONTENT_WIDTH = A4[0] - 32 * mm


def _styles():
    base = getSampleStyleSheet()["BodyText"]

    def style(name, **kw):
        return ParagraphStyle(name, parent=base, textColor=kw.pop("textColor", INK), **kw)

    return {
        "title": style("title", fontName="Helvetica-Bold", fontSize=20, leading=24),
        "sub": style("sub", fontSize=9.5, leading=13, textColor=MUTED),
        "h2": style(
            "h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=6
        ),
        "body": style("body", fontSize=9, leading=12.5),
        "bold": style("bold", fontName="Helvetica-Bold", fontSize=9, leading=12.5),
        "small": style("small", fontSize=7.5, leading=10, textColor=MUTED),
        "cell": style("cell", fontSize=8.5, leading=11),
        "chip_n": style("chip_n", fontName="Helvetica-Bold", fontSize=18, leading=21),
        "chip_l": style("chip_l", fontSize=8, leading=10),
    }


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _image(data: str, width: float) -> Image:
    raw = base64.b64decode(data)
    w, h = ImageReader(BytesIO(raw)).getSize()
    return Image(BytesIO(raw), width=width, height=width * h / float(w))


def _grid(cells: list, columns: int) -> Table:
    rows = [cells[i : i + columns] for i in range(0, len(cells), columns)]
    rows[-1] += [""] * (columns - len(rows[-1]))
    table = Table(rows, colWidths=[CONTENT_WIDTH / columns] * columns, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _figure(data: str, caption: str, width: float, styles) -> Table:
    figure = Table([[_image(data, width)], [_p(caption, styles["small"])]], colWidths=[width])
    figure.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 1), (-1, 1), 3),
            ]
        )
    )
    return figure


def _summary_chips(summary: dict, styles) -> Table:
    counts = summary.get("counts", {})
    cells, style = [], [("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for index, name in enumerate(ORDER):
        number = f'<font color="{DARK[name]}">{counts.get(name, 0)}</font>'
        cells.append([Paragraph(number, styles["chip_n"]), _p(name, styles["chip_l"])])
        style += [
            ("BACKGROUND", (index, 0), (index, 0), colors.HexColor(WASH[name])),
            ("LINEBEFORE", (index, 0), (index, 0), 4, colors.HexColor(HEX[name])),
        ]
    missing = len(summary.get("not_assessed", []))
    note = "to double-check" + (f", {missing} not assessed" if missing else "")
    cells.append([_p(str(summary.get("flagged", 0)), styles["chip_n"]), _p(note, styles["chip_l"])])
    style += [
        ("BACKGROUND", (3, 0), (3, 0), BONE),
        ("LINEBEFORE", (3, 0), (3, 0), 4, MUTED),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    table = Table([cells], colWidths=[CONTENT_WIDTH / 4] * 4)
    table.setStyle(TableStyle(style))
    return table


def _findings_table(findings: list[dict]) -> Table:
    rows = [["ID", "Level", "Grade", "Normal/Mild", "Moderate", "Severe", "Check"]]
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row, f in enumerate(findings, start=1):
        scores = f["class_scores"]
        rows.append(
            [
                f["id"],
                f["level_label"],
                f["severity"],
                *(f"{scores.get(name, 0) * 100:.0f}%" for name in ORDER),
                "Yes" if f["uncertainty"]["status"] == "review" else "",
            ]
        )
        grade = f["severity"]
        style += [
            ("BACKGROUND", (2, row), (2, row), colors.HexColor(WASH.get(grade, "#f1f5f9"))),
            ("TEXTCOLOR", (2, row), (2, row), colors.HexColor(DARK.get(grade, "#334155"))),
            ("FONTNAME", (2, row), (2, row), "Helvetica-Bold"),
        ]
    widths = [12, 26, 28, 28, 26, 24, 18]
    scale = CONTENT_WIDTH / (sum(widths) * mm)
    table = Table(rows, colWidths=[w * mm * scale for w in widths], repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def _chart(findings: list[dict]) -> Drawing:
    """Stacked horizontal bars: score per grade for every assessed level."""
    labels = [f["level_label"] for f in findings][::-1]
    data = [[f["class_scores"].get(name, 0) * 100 for f in findings][::-1] for name in ORDER]
    bar_area = 15 * len(labels)
    drawing = Drawing(CONTENT_WIDTH, bar_area + 46)
    chart = HorizontalBarChart()
    chart.x, chart.y = 22 * mm, 28
    chart.width, chart.height = CONTENT_WIDTH - 26 * mm, bar_area
    chart.data = data
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.fillColor = INK
    chart.categoryAxis.style = "stacked"
    chart.categoryAxis.strokeColor = RULE
    chart.valueAxis.valueMin, chart.valueAxis.valueMax, chart.valueAxis.valueStep = 0, 100, 25
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = MUTED
    chart.valueAxis.labelTextFormat = "%d%%"
    chart.valueAxis.strokeColor = RULE
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.gridStrokeColor = colors.HexColor("#e9edf1")
    chart.barSpacing = 1
    chart.groupSpacing = 4
    chart.bars.strokeColor = None
    for index, name in enumerate(ORDER):
        chart.bars[index].fillColor = colors.HexColor(HEX[name])
    drawing.add(chart)
    x = 22 * mm
    for name in ORDER:  # legend drawn as shapes: no font-dependent glyphs
        drawing.add(Rect(x, 4, 7, 7, fillColor=colors.HexColor(HEX[name]), strokeColor=None))
        drawing.add(String(x + 10, 5, name, fontSize=7.5, fillColor=INK))
        x += 30 * mm
    return drawing


def _recommendation(item: dict, styles) -> Table:
    label, bar, ink = PRIORITY.get(item["priority"], PRIORITY["low"])
    evidence = f"  [{', '.join(item['evidence'])}]" if item.get("evidence") else ""
    heading = (
        f'<font color="{ink}"><b>{escape(label)}</b></font>  <b>{escape(item["title"])}</b>'
        f'<font color="#5b6b7b">{escape(evidence)}</font>'
    )
    body = [Paragraph(heading, styles["body"]), Spacer(1, 2), _p(item["clinician"], styles["body"])]
    table = Table([[body]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, 0), 3.5, colors.HexColor(bar)),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _decorate(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(INK)
    canvas.rect(0, height - 9 * mm, width, 9 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(16 * mm, height - 6 * mm, "SpineScope")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(width - 16 * mm, height - 6 * mm, "Lumbar spine MRI analysis")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(
        16 * mm, 8 * mm, "AI research output, not a diagnosis. Review with a qualified clinician."
    )
    canvas.drawRightString(width - 16 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_scan_report(result: dict, label: str = "") -> bytes:
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Lumbar spine AI analysis report",
        author="SpineScope",
    )
    findings = result.get("findings", [])
    summary = result.get("summary", {})
    created = result.get("created_at", "")
    with contextlib.suppress(ValueError):
        created = datetime.fromisoformat(created).strftime("%d %b %Y, %H:%M UTC")
    mode = "full series" if result.get("mode") == "multi" else "single slice"
    slices = f", {result['slice_count']} slices" if result.get("slice_count") else ""

    elements = [
        _p(result.get("condition_name", "Lumbar spine analysis"), styles["title"]),
        _p(
            f"{result.get('plane', '')} {result.get('sequence', '')}, {mode}{slices}. "
            f"Analysed {created}.",
            styles["sub"],
        ),
        Spacer(1, 8),
    ]
    half = CONTENT_WIDTH / 2
    info = Table(
        [
            [
                _p("Reference", styles["small"]),
                _p(label or "Not provided", styles["bold"]),
                _p("Analysis ID", styles["small"]),
                _p(str(result.get("analysis_id", ""))[:18], styles["cell"]),
            ]
        ],
        colWidths=[22 * mm, half - 22 * mm, 22 * mm, half - 22 * mm],
    )
    info.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    elements += [info, Spacer(1, 10), _summary_chips(summary, styles)]

    if findings:
        elements += [
            _p("Grades by level", styles["h2"]),
            _findings_table(findings),
            Spacer(1, 6),
            _p("Score profile", styles["h2"]),
            _chart(findings),
        ]
    else:
        elements += [Spacer(1, 8), _p("No level was detected in this upload.", styles["body"])]

    recommendations = result.get("recommendations", [])
    if recommendations:
        elements += [CondPageBreak(60 * mm), _p("Suggested next steps", styles["h2"])]
        for item in recommendations:
            elements += [_recommendation(item, styles), Spacer(1, 5)]

    images = result.get("images", [])
    if images:
        elements += [
            CondPageBreak(110 * mm),
            _p("Annotated slices", styles["h2"]),
            _p(
                "Box and label colors show the grade: green normal/mild, yellow moderate, red "
                "severe.",
                styles["small"],
            ),
            Spacer(1, 4),
        ]
        columns = 1 if len(images) == 1 else 2
        width = min(CONTENT_WIDTH / columns - 6, 120 * mm)
        cells = [
            _figure(
                image["annotated"],
                f"Slice {image['slice_number']}" if image.get("slice_number") else "Image",
                width,
                styles,
            )
            for image in images
        ]
        elements.append(_grid(cells, columns))

    maps = [f for f in findings if (f.get("explanation") or {}).get("heatmap_image")]
    if maps:
        elements += [
            CondPageBreak(70 * mm),
            _p("Focus maps", styles["h2"]),
            _p(
                "Where the grading model looked, tinted with the predicted grade. Highlights show "
                "model sensitivity, not proof of a lesion.",
                styles["small"],
            ),
            Spacer(1, 4),
        ]
        width = CONTENT_WIDTH / 5 - 6
        cells = [
            _figure(
                f["explanation"]["heatmap_image"],
                f"{f['id']} {f['level_label']}, {f['severity']}",
                width,
                styles,
            )
            for f in maps
        ]
        elements.append(_grid(cells, 5))

    quality = result.get("quality", {})
    notes = quality.get("issues", []) + quality.get("notes", [])
    provenance = result.get("provenance", {})
    elements += [
        CondPageBreak(40 * mm),
        _p("Image checks and model details", styles["h2"]),
        _p(
            "Review suggested." if quality.get("status") == "review" else "No basic input flags.",
            styles["body"],
        ),
    ]
    elements += [_p(f"- {note}", styles["body"]) for note in notes]
    elements += [
        Spacer(1, 6),
        _p(
            f"Pipeline {provenance.get('pipeline_version', '')}. Calibration: "
            f"{provenance.get('calibration', 'unavailable')}. Scores are model outputs, not "
            "calibrated probabilities.",
            styles["small"],
        ),
    ]
    doc.build(elements, onFirstPage=_decorate, onLaterPages=_decorate)
    return buffer.getvalue()
