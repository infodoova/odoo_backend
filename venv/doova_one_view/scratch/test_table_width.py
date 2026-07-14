import lxml.html

def add_dynamic_table_widths(html_content: str) -> str:
    if not html_content.strip(): return html_content
    try:
        fragments = lxml.html.fragments_fromstring(html_content)
        output = []
        for root in fragments:
            if isinstance(root, str):
                output.append(root)
                continue
                
            for table in root.xpath('.//table') + ([root] if root.tag == 'table' else []):
                rows = table.xpath('.//tr')
                if not rows: continue
                
                col_max = {}
                for row in rows:
                    cells = row.xpath('./th|./td')
                    for i, cell in enumerate(cells):
                        text = "".join(cell.itertext()).strip()
                        col_max[i] = max(col_max.get(i, 0), len(text))
                
                total_len = sum(col_max.values())
                if total_len == 0: continue
                
                first_row_cells = rows[0].xpath('./th|./td')
                for i, cell in enumerate(first_row_cells):
                    if i in col_max:
                        # Minimum 12% to prevent extreme shrinking
                        pct = max(12, int((col_max[i] / total_len) * 100))
                        style = cell.get('style', '')
                        if 'width' not in style:
                            new_style = (style + f"; width: {pct}%;").strip(';')
                            cell.set('style', new_style)
                            
            output.append(lxml.html.tostring(root, encoding='unicode'))
        return "".join(output)
    except Exception as e:
        print(f"Error adding dynamic widths: {e}")
        return html_content

html = """
<table>
<thead>
<tr>
<th></th>
<th>Accounts Receivable</th>
<th>Accounts Payable</th>
<th>Net</th>
</tr>
</thead>
<tbody>
<tr>
<td><strong>Total Outstanding</strong></td>
<td>XAF 980.5M</td>
<td>XAF 1,061.3M</td>
<td><strong>-XAF 80.8M</strong> (AP Exceeds AR)</td>
</tr>
<tr>
<td><strong>90+ Day Concentration</strong></td>
<td>95.0%</td>
<td>14.1% (tracked)</td>
<td>AR far more aged</td>
</tr>
</tbody>
</table>
"""

print(add_dynamic_table_widths(html))
