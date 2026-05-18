# api/agent/utils.py

import os
import re
from pathlib import Path

def get_public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

def make_report_url(report_path_or_filename: str | None) -> str | None:
    if not report_path_or_filename: return None
    filename = Path(report_path_or_filename).name
    public_base_url = get_public_base_url()
    return f"{public_base_url}/api/v1/financial-advisor/reports/{filename}" if public_base_url else f"/api/v1/financial-advisor/reports/{filename}"

def normalize_graph_for_frontend(graph_data):
    if not graph_data: return None
    if isinstance(graph_data, list):
        normalized = []
        for item in graph_data:
            if not isinstance(item, dict): continue
            if "name" in item and "value" in item: normalized.append(item)
            elif "x" in item and "y" in item: normalized.append({"name": str(item.get("x")), "value": float(item.get("y") or 0)})
        return normalized if normalized else None
    if isinstance(graph_data, dict):
        if isinstance(graph_data.get("x"), list) and isinstance(graph_data.get("y"), list):
            return [{"name": str(xv), "value": float(graph_data["y"][i] or 0)} for i, xv in enumerate(graph_data["x"])]
    return None

def parse_graph_data_from_text(text: str) -> list | None:
    """
    Intelligently parse lists, markdown tables, ASCII graphs, or series numbers
    from AI-generated assistant text and structure them for Recharts frontend.
    Handles metric suffixes like K, M, and B (e.g., $141.4M -> 141,400,000).
    Requires at least 2 distinct data points to qualify as graph data.
    """
    if not text:
        return None
        
    items = []

    def parse_value_with_suffix(val_str: str) -> float | None:
        # Strip currency symbols, asterisks, commas, spaces
        clean = re.sub(r"[^\d.\-kKmMBb]", "", val_str)
        if not clean:
            return None
        
        # Check suffix
        multiplier = 1.0
        suffix = clean[-1].lower() if clean[-1].isalpha() else ""
        if suffix:
            num_part = clean[:-1]
            if suffix == 'k':
                multiplier = 1000.0
            elif suffix == 'm':
                multiplier = 1000000.0
            elif suffix == 'b':
                multiplier = 1000000000.0
        else:
            num_part = clean
            
        try:
            return float(num_part) * multiplier
        except ValueError:
            return None

    # Helper to clean labels of markdown asterisks/formatting
    def clean_label(l_str: str) -> str:
        return re.sub(r"\*\*|\*|#", "", l_str).strip()

    # 1. Parse ASCII table / series formats (e.g. "May 2025    $141.4M")
    ascii_rows = re.findall(
        r"(?:^|\n)\s*([a-zA-Z0-9\s\-_/*#]{3,20})\s+([$₦€]?\s*-?[\d,]+(?:\.\d+)?\s*[kKmMBb]?)(?:\s|█|▊|▉|▎|▌|▏|—|$)",
        text
    )
    if ascii_rows:
        for label, val_str in ascii_rows:
            label_clean = clean_label(label)
            # Skip noise or headers
            if any(x in label_clean.lower() for x in ["month", "revenue", "chart", "value", "total", "summary", "note", "http", "orders", "visual"]):
                continue
            val = parse_value_with_suffix(val_str)
            if val is not None:
                items.append({"name": label_clean, "value": val})
        if len(items) >= 2:
            return items

    # Reset items to avoid mixing strategies
    items = []

    # 2. Parse Markdown Table rows
    table_rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", text)
    if table_rows:
        for label, val_str in table_rows:
            label_clean = clean_label(label)
            if any(x in label_clean.lower() for x in ["month", "label", "category", "product", "company", "---", "orders", "visual", "revenue"]):
                continue
            val = parse_value_with_suffix(val_str)
            if val is not None:
                items.append({"name": label_clean, "value": val})
        if len(items) >= 2:
            return items

    items = []

    # 3. Parse colon or dash line formats (e.g., "* Jan: 12,500" or "Monthly Revenue - 50000")
    colon_lines = re.findall(r"(?:^|\n)\s*[*+-]?\s*([a-zA-Z0-9\s\-_/*#]+)\s*[:\-]\s*([$₦€]?\s*-?[\d,]+(?:\.\d+)?\s*[kKmMBb]?)", text)
    if colon_lines:
        for label, val_str in colon_lines:
            label_clean = clean_label(label)
            if any(x in label_clean.lower() for x in ["total", "summary", "note", "http", "orders", "visual", "revenue"]):
                continue
            val = parse_value_with_suffix(val_str)
            if val is not None:
                items.append({"name": label_clean, "value": val})
        if len(items) >= 2:
            return items

    return None

def strip_visual_charts_from_text(text: str) -> str:
    """
    Remove bulky markdown tables and ASCII bar code blocks from the AI text response
    so they don't clutter the chat UI, while keeping observations and advice.
    """
    if not text:
        return ""
        
    # 1. Strip Markdown Table blocks (lines starting and ending with |)
    lines = text.split("\n")
    cleaned_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        # If it starts and ends with |, it is a table line
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            continue
        else:
            if in_table:
                in_table = False
                if not stripped:
                    continue
            cleaned_lines.append(line)
            
    text = "\n".join(cleaned_lines)

    # 2. Strip code blocks containing ASCII graph bars
    code_blocks = re.findall(r"```[a-zA-Z]*\n(.*?)\n```", text, re.DOTALL)
    for block in code_blocks:
        if any(x in block for x in ["█", "▊", "▉", "▎", "▌", "▏", "—", "Chart", "Revenue", "Revenue scaled"]):
            pattern = r"```[a-zA-Z]*\n" + re.escape(block) + r"\n```"
            text = re.sub(pattern, "", text)

    # 3. Clean up duplicate / trailing empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def get_tenant_currency(tenant_id: str, company_id: int | None = None) -> str:
    """
    Fetch the correct currency name (e.g. XAF, USD, EUR) for the tenant from dim_companies.
    """
    from .db import run_query
    from .query_context import build_company_filter_sql
    
    params = {"tenant_id": tenant_id}
    f_sql, f_params = build_company_filter_sql(tenant_id, company_id)
    params.update(f_params)
    
    query = f"SELECT currency_name FROM dim_companies WHERE tenant_id = :tenant_id {f_sql} LIMIT 1"
    try:
        rows = run_query(query, params)
        if rows and rows[0].get("currency_name"):
            return rows[0]["currency_name"]
    except Exception:
        pass
    return "USD"

def fix_currency_symbols(text: str, currency: str) -> str:
    """
    Ensure all financial figures use the correct currency instead of stray '$' or 'USD'.
    """
    if not text or not currency or currency.upper() == "USD":
        return text
        
    # Replace stray "$" or "USD" in monetary contexts (e.g., "$100" -> "XAF 100")
    text = re.sub(r"\$\s*(\d+)", f"{currency} \\1", text)
    text = re.sub(r"(\d+)\s*\$", f"\\1 {currency}", text)
    text = re.sub(r"\bUSD\b", currency, text)
    
    return text


