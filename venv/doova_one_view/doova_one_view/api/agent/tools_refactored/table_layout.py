import lxml.html

def add_dynamic_table_widths(html_content: str) -> str:
    """
    Parses HTML content, finds all tables, and injects proportional percentage
    widths into the first row's columns based on the maximum text length in each column.
    This provides a dynamic layout solution for xhtml2pdf, which struggles with
    auto-layout on empty table headers.
    """
    if not html_content.strip(): 
        return html_content
        
    try:
        fragments = lxml.html.fragments_fromstring(html_content)
        output = []
        for root in fragments:
            if isinstance(root, str):
                output.append(root)
                continue
                
            # Process any tables found within this root element, or the root itself
            tables_to_process = root.xpath('.//table')
            if root.tag == 'table':
                tables_to_process.append(root)
                
            for table in tables_to_process:
                rows = table.xpath('.//tr')
                if not rows: continue
                
                # 1. Calculate max character length per column
                col_max = {}
                for row in rows:
                    cells = row.xpath('./th|./td')
                    for i, cell in enumerate(cells):
                        text = "".join(cell.itertext()).strip()
                        col_max[i] = max(col_max.get(i, 0), len(text))
                
                total_len = sum(col_max.values())
                if total_len == 0: continue
                
                # 2. Inject proportional widths into the first row
                first_row_cells = rows[0].xpath('./th|./td')
                for i, cell in enumerate(first_row_cells):
                    if i in col_max:
                        # Ensure no column shrinks below 10%
                        pct = max(10, int((col_max[i] / total_len) * 100))
                        style = cell.get('style', '')
                        if 'width' not in style:
                            new_style = (style + f"; width: {pct}%;").strip(';')
                            cell.set('style', new_style)
                            
            output.append(lxml.html.tostring(root, encoding='unicode'))
        return "".join(output)
    except Exception as e:
        print(f"Error adding dynamic table widths: {e}")
        return html_content
