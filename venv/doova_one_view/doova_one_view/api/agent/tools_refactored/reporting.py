# api/agent/tools_refactored/reporting.py

import re
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from .common import AgentConfig
from .sales import get_sales_summary_tool
from .finance import get_business_health_score_tool

_NAVY = colors.HexColor('#1a3d5c')
_BLUE = colors.HexColor('#2c5f8a')
_GREY_LINE = colors.HexColor('#aaaaaa')
_ROW_ALT = colors.HexColor('#f0f4f8')


def _st_h2():
    return ParagraphStyle('H2', fontSize=13, fontName='Helvetica-Bold',
                          textColor=_NAVY, spaceBefore=14, spaceAfter=4)

def _st_h3():
    return ParagraphStyle('H3', fontSize=11, fontName='Helvetica-Bold',
                          textColor=_BLUE, spaceBefore=10, spaceAfter=3)

def _st_body():
    return ParagraphStyle('Body', fontSize=10, fontName='Helvetica', leading=15, spaceAfter=4)

def _st_bullet():
    return ParagraphStyle('Bullet', fontSize=10, fontName='Helvetica',
                          leading=15, leftIndent=16, spaceAfter=2)

def _st_section():
    return ParagraphStyle('Section', fontSize=14, fontName='Helvetica-Bold',
                          textColor=_NAVY, spaceAfter=6)

def _st_tc():
    return ParagraphStyle('TC', fontSize=9, fontName='Helvetica', leading=12, spaceAfter=0)


def _parse_inline(text: str) -> str:
    """Escape XML special chars then convert **bold** and *italic* to ReportLab tags."""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    return text


def _is_separator(cells: list) -> bool:
    return all(re.match(r'^:?-+:?$', c.replace(' ', '')) for c in cells if c.strip())


def _build_table(table_lines: list, usable_width: float) -> Table | None:
    rows = []
    tc = _st_tc()
    for line in table_lines:
        cells = [c.strip() for c in line[1:-1].split('|')]
        if _is_separator(cells):
            continue
        rows.append([Paragraph(_parse_inline(c), tc) for c in cells])

    if not rows:
        return None

    col_count = max(len(r) for r in rows)
    for r in rows:
        while len(r) < col_count:
            r.append(Paragraph('', tc))

    col_w = usable_width / col_count
    t = Table(rows, colWidths=[col_w] * col_count, repeatRows=1)

    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), _NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    for idx in range(1, len(rows)):
        bg = colors.white if idx % 2 == 1 else _ROW_ALT
        style_cmds.append(('BACKGROUND', (0, idx), (-1, idx), bg))

    t.setStyle(TableStyle(style_cmds))
    return t


def _markdown_to_flowables(text: str, usable_width: float) -> list:
    elements = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            elements.append(Spacer(1, 6))
            i += 1
            continue

        if line.startswith('## '):
            elements.append(Paragraph(_parse_inline(line[3:]), _st_h2()))
            i += 1
            continue

        if line.startswith('### '):
            elements.append(Paragraph(_parse_inline(line[4:]), _st_h3()))
            i += 1
            continue

        if re.match(r'^-{3,}$', line) or re.match(r'^\*{3,}$', line):
            elements.append(Spacer(1, 4))
            elements.append(HRFlowable(width='100%', thickness=0.5, color=_GREY_LINE))
            elements.append(Spacer(1, 4))
            i += 1
            continue

        if line.startswith('|') and line.endswith('|'):
            table_lines = []
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith('|') and stripped.endswith('|'):
                    table_lines.append(stripped)
                    i += 1
                else:
                    break
            t = _build_table(table_lines, usable_width)
            if t:
                elements.append(t)
                elements.append(Spacer(1, 8))
            continue

        if line.startswith('- ') or line.startswith('* '):
            elements.append(Paragraph(f'• {_parse_inline(line[2:])}', _st_bullet()))
            i += 1
            continue

        m = re.match(r'^(\d+)\.\s+(.*)', line)
        if m:
            elements.append(Paragraph(f'{m.group(1)}. {_parse_inline(m.group(2))}', _st_bullet()))
            i += 1
            continue

        content = _parse_inline(line)
        if content:
            elements.append(Paragraph(content, _st_body()))
        i += 1

    return elements


def _draw_header_footer(canv, doc, tenant_id: str, generated: str):
    canv.saveState()
    width, height = letter

    canv.setStrokeColorRGB(0.1, 0.4, 0.7)
    canv.setLineWidth(2)
    canv.line(40, height - 60, width - 40, height - 60)

    canv.setFont('Helvetica-Bold', 18)
    canv.setFillColorRGB(0.1, 0.3, 0.5)
    canv.drawString(40, height - 50, 'DOOVA ONEVIEW')

    canv.setFont('Helvetica-Bold', 12)
    canv.setFillColorRGB(0, 0, 0)
    canv.drawRightString(width - 40, height - 50, 'Strategic Business Report')

    canv.setFont('Helvetica', 10)
    canv.setFillColorRGB(0, 0, 0)
    canv.drawString(40, height - 78, f'Generated: {generated}')
    canv.drawRightString(width - 40, height - 78, f'Tenant ID: {tenant_id}')

    canv.setFont('Helvetica', 8)
    canv.setFillColorRGB(0.5, 0.5, 0.5)
    canv.drawCentredString(width / 2, 30, 'Confidential - Powered by Doova Finance Brain')

    canv.restoreState()


def generate_report_tool(
    tenant_id: str,
    company_id: int | None = None,
    company_ids: list[int] | None = None,
    custom_content: str | None = None,
) -> dict:
    # company_ids takes precedence; fall back to legacy company_id
    resolved_company_id = company_id
    if company_ids:
        resolved_company_id = company_ids[0] if len(company_ids) == 1 else None

    reports_dir = Path('reports')
    reports_dir.mkdir(exist_ok=True)
    generated = datetime.now().strftime('%B %d, %Y %H:%M')
    filename = f"business_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = reports_dir / filename

    sales = get_sales_summary_tool(tenant_id, resolved_company_id)
    health = get_business_health_score_tool(tenant_id, resolved_company_id)

    width, _ = letter
    left_margin = right_margin = 40
    usable_width = width - left_margin - right_margin

    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        topMargin=100,
        bottomMargin=50,
        leftMargin=left_margin,
        rightMargin=right_margin,
    )

    on_page = lambda canv, d: _draw_header_footer(canv, d, tenant_id, generated)

    body = _st_body()
    story = []

    # Business Vital Signs
    story.append(Paragraph('BUSINESS VITAL SIGNS', _st_section()))
    story.append(HRFlowable(width='100%', thickness=1, color=_NAVY))
    story.append(Spacer(1, 10))

    vital_rows = [
        [Paragraph('<b>Overall Health Score:</b>', body),
         Paragraph(f"{health['business_health_score']} / 100", body)],
        [Paragraph('<b>Total Annual Revenue:</b>', body),
         Paragraph(f"{sales['total_revenue']:,}", body)],
    ]
    vital_table = Table(vital_rows, colWidths=[150, usable_width - 150])
    vital_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(vital_table)
    story.append(Spacer(1, 20))

    # Executive Analysis
    story.append(Paragraph('EXECUTIVE ANALYSIS & RECOMMENDATIONS', _st_section()))
    story.append(HRFlowable(width='100%', thickness=1, color=_NAVY))
    story.append(Spacer(1, 10))

    if custom_content:
        story.extend(_markdown_to_flowables(custom_content, usable_width))
    else:
        story.append(Paragraph('No custom AI analysis provided for this report.',
                                ParagraphStyle('Italic', fontSize=10, fontName='Helvetica-Oblique')))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    return {
        'tool_name': 'generate_report_tool',
        'download_url': f"{AgentConfig.API_BASE_URL}/financial-advisor/reports/{filename}",
        'filename': filename,
    }


def get_last_report_tool(tenant_id: str, company_id: int | None = None) -> dict:
    reports_dir = Path('reports')
    files = list(reports_dir.glob(f'business_report_{tenant_id}_*.pdf'))
    if not files:
        return {'status': 'no_reports'}
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    filename = files[0].name
    return {
        'tool_name': 'get_last_report_tool',
        'filename': filename,
        'download_url': f"{AgentConfig.API_BASE_URL}/financial-advisor/reports/{filename}",
    }
