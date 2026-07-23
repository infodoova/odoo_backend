from doova_one_view.api.agent.query_context import build_tenant_filter_sql
from typing import Optional
# api/agent/tools_refactored/reporting.py

import re
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether,
)
from .common import AgentConfig
from .sales import get_sales_summary_tool
from .finance import get_business_health_score_tool
from ..utils import make_report_url

# Ã¢â€â‚¬Ã¢â€â‚¬ Palette Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
_NAVY       = colors.HexColor('#1e3a5f')
_BLUE       = colors.HexColor('#2563eb')
_BLUE_MID   = colors.HexColor('#1d4ed8')
_BLUE_LIGHT = colors.HexColor('#eff6ff')
_SLATE      = colors.HexColor('#64748b')
_GREY_LINE  = colors.HexColor('#e2e8f0')
_ROW_ALT    = colors.HexColor('#f8fafc')
_AMBER      = colors.HexColor('#d97706')
_AMBER_BG   = colors.HexColor('#fffbeb')
_AMBER_BORD = colors.HexColor('#f59e0b')
_GREEN      = colors.HexColor('#16a34a')
_RED        = colors.HexColor('#dc2626')


# Ã¢â€â‚¬Ã¢â€â‚¬ Paragraph styles Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _st_h1():
    return ParagraphStyle('H1', fontSize=15, fontName='Helvetica-Bold',
                          textColor=_NAVY, spaceBefore=18, spaceAfter=6)

def _st_h2():
    return ParagraphStyle('H2', fontSize=13, fontName='Helvetica-Bold',
                          textColor=_NAVY, spaceBefore=14, spaceAfter=4)

def _st_h3():
    return ParagraphStyle('H3', fontSize=11, fontName='Helvetica-Bold',
                          textColor=_BLUE_MID, spaceBefore=10, spaceAfter=3)

def _st_h4():
    return ParagraphStyle('H4', fontSize=10, fontName='Helvetica-Bold',
                          textColor=_SLATE, spaceBefore=8, spaceAfter=2)

def _st_body():
    return ParagraphStyle('Body', fontSize=10, fontName='Helvetica',
                          leading=15, spaceAfter=4, textColor=colors.HexColor('#1f2937'))

def _st_bullet():
    return ParagraphStyle('Bullet', fontSize=10, fontName='Helvetica',
                          leading=15, leftIndent=14, spaceAfter=3,
                          textColor=colors.HexColor('#1f2937'))

def _st_tc():
    return ParagraphStyle('TC', fontSize=9, fontName='Helvetica',
                          leading=12, spaceAfter=0,
                          textColor=colors.HexColor('#374151'))

def _st_blockquote():
    return ParagraphStyle('BQ', fontSize=9.5, fontName='Helvetica-Oblique',
                          leading=14, leftIndent=12, rightIndent=4,
                          spaceAfter=2, textColor=colors.HexColor('#92400e'))

def _st_caption():
    return ParagraphStyle('Cap', fontSize=8, fontName='Helvetica',
                          textColor=_SLATE, spaceAfter=2)


# Ã¢â€â‚¬Ã¢â€â‚¬ Inline markdown parser Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _parse_inline(text: str) -> str:
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__',     r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', text)
    text = re.sub(r'`(.*?)`',       r'<font name="Courier">\1</font>', text)
    return text


def _is_separator(cells: list) -> bool:
    return all(re.match(r'^:?-+:?$', c.replace(' ', '')) for c in cells if c.strip())


# Ã¢â€â‚¬Ã¢â€â‚¬ Table builder Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
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

    cmds = [
        ('BACKGROUND',    (0, 0),  (-1, 0),  _NAVY),
        ('TEXTCOLOR',     (0, 0),  (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0),  (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0),  (-1, 0),  9),
        ('GRID',          (0, 0),  (-1, -1), 0.4, _GREY_LINE),
        ('LINEBELOW',     (0, 0),  (-1, 0),  1.5, _BLUE_MID),
        ('VALIGN',        (0, 0),  (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0),  (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0),  (-1, -1), 6),
        ('LEFTPADDING',   (0, 0),  (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0),  (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
    ]
    t.setStyle(TableStyle(cmds))
    return t


# Ã¢â€â‚¬Ã¢â€â‚¬ Blockquote builder Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _build_blockquote(text: str, usable_width: float) -> Table:
    inner = Paragraph(_parse_inline(text), _st_blockquote())
    data = [[inner]]
    t = Table(data, colWidths=[usable_width])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), _AMBER_BG),
        ('LINEBEFORE',    (0, 0), (0, -1),  4, _AMBER_BORD),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
    ]))
    return t


# Ã¢â€â‚¬Ã¢â€â‚¬ Section header builder Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _section_header(title: str, usable_width: float) -> list:
    label = Paragraph(
        f'<font color="white"><b>{title}</b></font>',
        ParagraphStyle('SH', fontSize=11, fontName='Helvetica-Bold',
                       textColor=colors.white, leading=14),
    )
    t = Table([[label]], colWidths=[usable_width])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), _NAVY),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 12),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
    ]))
    return [t, Spacer(1, 10)]


# Ã¢â€â‚¬Ã¢â€â‚¬ Markdown Ã¢â€ â€™ flowables Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _markdown_to_flowables(text: str, usable_width: float) -> list:
    elements = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            elements.append(Spacer(1, 5))
            i += 1
            continue

        # H1
        if line.startswith('# ') and not line.startswith('## '):
            elements.append(Paragraph(_parse_inline(line[2:]), _st_h1()))
            i += 1
            continue

        # H2
        if line.startswith('## ') and not line.startswith('### '):
            elements.append(Spacer(1, 4))
            elements.append(Paragraph(_parse_inline(line[3:]), _st_h2()))
            elements.append(HRFlowable(width='100%', thickness=0.75,
                                       color=_BLUE_MID, spaceAfter=4))
            i += 1
            continue

        # H3
        if line.startswith('### ') and not line.startswith('#### '):
            elements.append(Paragraph(_parse_inline(line[4:]), _st_h3()))
            i += 1
            continue

        # H4
        if line.startswith('#### '):
            elements.append(Paragraph(_parse_inline(line[5:]), _st_h4()))
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^[-*]{3,}$', line):
            elements.append(Spacer(1, 4))
            elements.append(HRFlowable(width='100%', thickness=0.5, color=_GREY_LINE))
            elements.append(Spacer(1, 4))
            i += 1
            continue

        # Blockquote Ã¢â‚¬â€ collect consecutive `>` lines
        if line.startswith('> '):
            bq_lines = []
            while i < len(lines) and lines[i].strip().startswith('> '):
                bq_lines.append(lines[i].strip()[2:])
                i += 1
            combined = ' '.join(bq_lines)
            elements.append(_build_blockquote(combined, usable_width))
            elements.append(Spacer(1, 6))
            continue

        # Table
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

        # Bullet list
        if line.startswith('- ') or line.startswith('* '):
            elements.append(Paragraph(f'Ã¢â‚¬Â¢ {_parse_inline(line[2:])}', _st_bullet()))
            i += 1
            continue

        # Numbered list
        m = re.match(r'^(\d+)\.\s+(.*)', line)
        if m:
            elements.append(Paragraph(
                f'<b>{m.group(1)}.</b> {_parse_inline(m.group(2))}', _st_bullet()))
            i += 1
            continue

        # Body text
        content = _parse_inline(line)
        if content:
            elements.append(Paragraph(content, _st_body()))
        i += 1

    return elements


# Ã¢â€â‚¬Ã¢â€â‚¬ Header / footer drawn on every page Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _draw_header_footer(canv, doc, tenant_id: str, generated: str, tenant_ids: Optional[list[str]] = None):
    canv.saveState()
    w, h = letter

    # Ã¢â€â‚¬Ã¢â€â‚¬ Top banner Ã¢â€â‚¬Ã¢â€â‚¬
    banner_h = 60
    canv.setFillColor(_NAVY)
    canv.rect(0, h - banner_h, w, banner_h, fill=1, stroke=0)

    # accent stripe
    canv.setFillColor(_BLUE)
    canv.rect(0, h - banner_h - 4, w, 4, fill=1, stroke=0)

    # Brand name
    canv.setFont('Helvetica-Bold', 22)
    canv.setFillColor(colors.white)
    canv.drawString(40, h - 38, 'NEXUS')

    # Report type
    canv.setFont('Helvetica-Bold', 11)
    canv.setFillColor(colors.HexColor('#93c5fd'))
    canv.drawRightString(w - 40, h - 36, 'Strategic Business Report')

    # Sub-row
    canv.setFont('Helvetica', 8.5)
    canv.setFillColor(colors.HexColor('#cbd5e1'))
    canv.drawString(40, h - 52, f'Generated: {generated}')
    canv.drawRightString(w - 40, h - 52, f'Tenant ID: {tenant_id}')

    # Ã¢â€â‚¬Ã¢â€â‚¬ Bottom footer Ã¢â€â‚¬Ã¢â€â‚¬
    canv.setFillColor(_NAVY)
    canv.rect(0, 0, w, 32, fill=1, stroke=0)

    canv.setFont('Helvetica', 8)
    canv.setFillColor(colors.HexColor('#94a3b8'))
    canv.drawCentredString(w / 2, 11, 'Confidential  Ã¢â‚¬â€  Powered by Nexus')

    canv.restoreState()


# Ã¢â€â‚¬Ã¢â€â‚¬ Health-score card Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def _health_score_card(score: float, revenue: float, usable_width: float) -> Table:
    if score >= 75:
        score_color = '#16a34a'
        rating = 'Healthy'
    elif score >= 50:
        score_color = '#d97706'
        rating = 'Moderate'
    else:
        score_color = '#dc2626'
        rating = 'Critical'

    score_cell = Paragraph(
        f'<font size="32" color="{score_color}"><b>{score}</b></font>'
        f'<font size="13" color="#64748b"> / 100</font>',
        ParagraphStyle('SC', fontName='Helvetica', leading=36, alignment=1),
    )
    rating_cell = Paragraph(
        f'<font size="10" color="{score_color}"><b>{rating}</b></font>',
        ParagraphStyle('RT', fontName='Helvetica-Bold', alignment=1),
    )
    label_cell = Paragraph(
        '<font size="9" color="#64748b">Overall Health Score</font>',
        ParagraphStyle('LB', fontName='Helvetica', alignment=1),
    )

    rev_cell = Paragraph(
        f'<font size="20" color="#1e3a5f"><b>${revenue:,.0f}</b></font>',
        ParagraphStyle('RV', fontName='Helvetica', leading=26, alignment=1),
    )
    rev_label = Paragraph(
        '<font size="9" color="#64748b">Total Annual Revenue (USD)</font>',
        ParagraphStyle('RL', fontName='Helvetica', alignment=1),
    )

    half = usable_width / 2 - 6
    card = Table(
        [
            [
                Table(
                    [[score_cell], [rating_cell], [label_cell]],
                    colWidths=[half],
                    style=TableStyle([
                        ('TOPPADDING',    (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
                    ]),
                ),
                Table(
                    [[rev_cell], [Spacer(1, 4)], [rev_label]],
                    colWidths=[half],
                    style=TableStyle([
                        ('TOPPADDING',    (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
                    ]),
                ),
            ]
        ],
        colWidths=[half + 6, half + 6],
    )
    card.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), _BLUE_LIGHT),
        ('BOX',           (0, 0), (-1, -1), 1,   _GREY_LINE),
        ('LINEBEFORE',    (1, 0), (1, -1),  0.5, _GREY_LINE),
        ('TOPPADDING',    (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return card


# Ã¢â€â‚¬Ã¢â€â‚¬ Main entry point Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
def generate_report_tool(
    tenant_id: str, 
    custom_content: str = "", 
    company_id: int | None = None,
    base_currency: str | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None
) -> dict:
    from ..utils import get_tenant_currency
    
    # In some places company_id string might slip in, parse properly in future
    resolved_company_id = company_id
    
    # Fetch core data needed for the scorecard
    try:
        sales  = get_sales_summary_tool(tenant_id, resolved_company_id, base_currency=base_currency, company_ids=company_ids, tenant_ids=tenant_ids)
        health = get_business_health_score_tool(tenant_id, resolved_company_id, base_currency=base_currency, company_ids=company_ids, tenant_ids=tenant_ids)
    except Exception:
        sales = {}
        health = {}
        
    # If the user did not provide custom Markdown, auto-generate a generic executive summary.
    if not custom_content.strip():
        try:
            currency = base_currency or get_tenant_currency(tenant_id, resolved_company_id)
            rev = sales.get('total_revenue', 0)
            score = health.get('business_health_score', 0)
            
            custom_content = f"""
## Automated Summary
The business is currently operating with a health score of **{score}/100** and generated **{rev:,.2f} {currency}** in revenue during this period.
            """
        except Exception as e:
            custom_content = f"Failed to generate summary: {str(e)}"

    reports_dir = Path('reports')
    reports_dir.mkdir(exist_ok=True)
    generated = datetime.now().strftime('%B %d, %Y %H:%M')
    filename = f"business_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = reports_dir / filename

    w, _ = letter
    left_margin = right_margin = 44
    usable_width = w - left_margin - right_margin

    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        topMargin=80,
        bottomMargin=52,
        leftMargin=left_margin,
        rightMargin=right_margin,
    )

    on_page = lambda canv, d: _draw_header_footer(canv, d, tenant_id, generated)

    story = []

    # Ã¢â€â‚¬Ã¢â€â‚¬ Business Vital Signs Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    story.extend(_section_header('BUSINESS VITAL SIGNS', usable_width))
    story.append(
        _health_score_card(
            health.get('business_health_score', 0),
            sales.get('total_revenue', 0),
            usable_width,
        )
    )
    story.append(Spacer(1, 22))

    # Ã¢â€â‚¬Ã¢â€â‚¬ Executive Analysis Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    story.extend(_section_header('EXECUTIVE ANALYSIS & RECOMMENDATIONS', usable_width))

    if custom_content:
        story.extend(_markdown_to_flowables(custom_content, usable_width))
    else:
        story.append(
            Paragraph(
                'No custom AI analysis provided for this report.',
                ParagraphStyle('Italic', fontSize=10, fontName='Helvetica-Oblique',
                               textColor=_SLATE),
            )
        )

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'generate_report_tool',
        'download_url': make_report_url(filename),
        'path': relative_path,
        'filename': filename,
    }


def get_last_report_tool(tenant_id: str, company_id: int | None = None, company_ids: Optional[list[int]] = None, tenant_ids: Optional[list[str]] = None) -> dict:
    reports_dir = Path('reports')
    files = list(reports_dir.glob(f'business_report_{tenant_id}_*.pdf'))
    if not files:
        return {'status': 'no_reports'}
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    filename = files[0].name
    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'get_last_report_tool',
        'filename': filename,
        'download_url': make_report_url(filename),
        'path': relative_path,
    }


