"""
Email Utilities — Shared Markdown-to-HTML rendering for email alerts and reports.
"""

import re


def md_to_html(text: str) -> str:
    """Convert AI-generated markdown summaries to email-safe styled HTML."""
    if not text:
        return ""

    def inline(s: str) -> str:
        s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        s = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'__(.*?)__',     r'<strong>\1</strong>', s)
        s = re.sub(r'\*(.*?)\*',     r'<em>\1</em>', s)
        s = re.sub(r'`(.*?)`',       r'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px;">\1</code>', s)
        return s

    def is_sep(cells):
        return all(re.match(r'^:?-+:?$', c.strip()) for c in cells if c.strip())

    TH  = 'style="text-align:left;padding:8px 12px;background:#1e3a5f;color:#fff;font-size:12px;font-weight:700;"'
    TD  = 'style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151;vertical-align:top;"'
    TDa = 'style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151;vertical-align:top;background:#f8fafc;"'

    lines  = text.splitlines()
    out    = []
    i      = 0
    in_ul  = False
    in_ol  = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append('</ul>')
            in_ul = False
        if in_ol:
            out.append('</ol>')
            in_ol = False

    while i < len(lines):
        raw  = lines[i]
        line = raw.strip()

        # blank line
        if not line:
            close_lists()
            i += 1
            continue

        # H1
        if re.match(r'^# [^#]', line):
            close_lists()
            out.append(f'<h2 style="font-size:17px;font-weight:700;color:#1e3a5f;margin:18px 0 6px;padding-bottom:6px;border-bottom:2px solid #e5e7eb;">{inline(line[2:])}</h2>')
            i += 1; continue

        # H2
        if re.match(r'^## [^#]', line):
            close_lists()
            out.append(f'<h3 style="font-size:15px;font-weight:700;color:#1e3a5f;margin:16px 0 5px;padding-bottom:4px;border-bottom:1.5px solid #dbeafe;">{inline(line[3:])}</h3>')
            i += 1; continue

        # H3
        if re.match(r'^### [^#]', line):
            close_lists()
            out.append(f'<h4 style="font-size:13px;font-weight:700;color:#1d4ed8;margin:12px 0 4px;">{inline(line[4:])}</h4>')
            i += 1; continue

        # H4
        if re.match(r'^#### ', line):
            close_lists()
            out.append(f'<h5 style="font-size:12px;font-weight:700;color:#374151;margin:10px 0 3px;">{inline(line[5:])}</h5>')
            i += 1; continue

        # HR
        if re.match(r'^[-*]{3,}$', line):
            close_lists()
            out.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0;"/>')
            i += 1; continue

        # Blockquote — collect consecutive lines
        if line.startswith('> '):
            close_lists()
            bq = []
            while i < len(lines) and lines[i].strip().startswith('> '):
                bq.append(inline(lines[i].strip()[2:]))
                i += 1
            content = ' '.join(bq)
            out.append(
                f'<div style="border-left:4px solid #f59e0b;background:#fffbeb;'
                f'padding:10px 14px;margin:10px 0;border-radius:0 6px 6px 0;">'
                f'<p style="margin:0;font-size:13px;color:#92400e;font-style:italic;">{content}</p></div>'
            )
            continue

        # Table
        if line.startswith('|') and line.endswith('|'):
            close_lists()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            # separate header / separator / body
            rows = [row for row in table_lines if not is_sep([c for c in row[1:-1].split('|')])]
            if rows:
                out.append('<table style="border-collapse:collapse;width:100%;margin:10px 0 14px;font-size:12px;">')
                for ridx, row in enumerate(rows):
                    cells = [c.strip() for c in row[1:-1].split('|')]
                    tag = 'th' if ridx == 0 else 'td'
                    attr = TH if ridx == 0 else (TD if ridx % 2 == 1 else TDa)
                    out.append('<tr>' + ''.join(f'<{tag} {attr}>{inline(c)}</{tag}>' for c in cells) + '</tr>')
                out.append('</table>')
            continue

        # Unordered list
        if re.match(r'^[-*+] ', line):
            if not in_ul:
                close_lists()
                out.append('<ul style="margin:6px 0 10px 18px;padding:0;">')
                in_ul = True
            out.append(f'<li style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:3px;">{inline(line[2:])}</li>')
            i += 1; continue

        # Ordered list
        m = re.match(r'^(\d+)\.\s+(.*)', line)
        if m:
            if not in_ol:
                close_lists()
                out.append('<ol style="margin:6px 0 10px 18px;padding:0;">')
                in_ol = True
            out.append(f'<li style="font-size:13px;color:#374151;line-height:1.6;margin-bottom:3px;">{inline(m.group(2))}</li>')
            i += 1; continue

        # Regular paragraph
        close_lists()
        out.append(f'<p style="font-size:13.5px;color:#374151;line-height:1.65;margin:0 0 8px;">{inline(line)}</p>')
        i += 1

    close_lists()
    return '\n'.join(out)
