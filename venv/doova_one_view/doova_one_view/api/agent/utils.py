# api/agent/utils.py

import os
import re
import json
from pathlib import Path
from typing import Any, Optional

def parse_json_chart_from_text(text: str) -> dict | None:
    """Extract the first {type: 'chart'} JSON block from agent output text."""
    if not text:
        return None

    # Look for ```json ... ``` fences first
    for match in re.finditer(r'```json\s*([\s\S]*?)\s*```', text, re.IGNORECASE):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and parsed.get("type") in ("chart", "graph") and parsed.get("chart"):
                return parsed
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

    # Fallback: bare JSON object containing "type": "chart"
    for match in re.finditer(r'\{\s*"type"\s*:\s*"(?:chart|graph)"[\s\S]*?\}(?=\s*$|\s*\n)', text):
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and parsed.get("type") in ("chart", "graph") and parsed.get("chart"):
                return parsed
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

    return None


def strip_json_chart_from_text(text: str) -> str:
    """Remove the JSON chart block (fenced, bare, or trailing fragments) from text, clean trailing whitespace."""
    if not text:
        return ""
    # 1. Remove ```json ... ``` blocks containing chart/graph definition
    text = re.sub(r'```json\s*\{[\s\S]*?"type"\s*:\s*"(?:chart|graph)"[\s\S]*?\}\s*```', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```json\s*[\s\S]*?"chart"\s*:[\s\S]*?```', '', text, flags=re.IGNORECASE)

    # 2. Remove complete bare JSON objects containing "type": "chart" or "graph"
    text = re.sub(r'\{\s*"type"\s*:\s*"(?:chart|graph)"[\s\S]*?\}(?=\s*$|\s*\n)', '', text)
    text = re.sub(r'\{\s*"type"\s*:\s*"(?:chart|graph)"[\s\S]*?\}\s*$', '', text)

    # 3. Remove unclosed or truncated chart JSON fragments at the end of the text
    text = re.sub(r'\{\s*"type"\s*:\s*"(?:chart|graph)"[\s\S]*$', '', text)

    # Collapse excess blank lines and strip trailing whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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

    # 1. Parse ASCII table / series formats (e.g. "May 2025    $141.4M" or "Mar 2026    -$250K")
    ascii_rows = re.findall(
        r"(?:^|\n)\s*([a-zA-Z0-9\s_/*#]{3,20})\s+(-?[$₦€]?\s*-?[\d,]+(?:\.\d+)?\s*[kKmMBb]?)(?=\s|█|▊|▉|▎|▌|▏|—|$)",
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
    table_rows = re.findall(r"\|\s*([^|]+?)\s*\|\s*(-?[$₦€]?\s*-?[^|]+?)\s*\|", text)
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

    # 3. Parse colon or dash line formats (e.g., "* Jan: 12,500" or "Monthly Revenue - -$50000")
    colon_lines = re.findall(r"(?:^|\n)\s*[*+-]?\s*([a-zA-Z0-9\s\-_/*#]+)\s*[:\-]\s*(-?[$₦€]?\s*-?[\d,]+(?:\.\d+)?\s*[kKmMBb]?)", text)
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

def get_tenant_currency(tenant_ids: Any = None, company_ids: Any = None) -> str:
    """
    Fetch the primary native currency name (e.g. XAF, USD, EUR) for the tenant/companies from dim_companies.
    """
    from .db import run_query
    from .query_context import build_company_filter_sql, build_tenant_filter_sql, normalize_company_ids, normalize_tenant_ids
    
    selected_tids = normalize_tenant_ids(tenant_ids)
    selected_cids = normalize_company_ids(company_ids)
    t_sql, t_params = build_tenant_filter_sql(tenant_ids=selected_tids, column_name="tenant_id")
    f_sql, f_params = build_company_filter_sql(company_ids=selected_cids, column_name="id")
    params = {**t_params, **f_params}
    
    query = f"""
        SELECT COALESCE(currency_name, currency_code) AS currency, COUNT(*) AS cnt
        FROM dim_companies
        WHERE 1=1 {t_sql} {f_sql} AND COALESCE(currency_name, currency_code) IS NOT NULL
        GROUP BY COALESCE(currency_name, currency_code)
        ORDER BY cnt DESC, currency DESC
        LIMIT 1
    """
    try:
        rows = run_query(query, params)
        if rows and rows[0].get("currency"):
            return rows[0]["currency"]
    except Exception:
        pass
    return "XAF"

def fix_currency_symbols(text: str, currency: str) -> str:
    """
    Ensure stray dollar signs (e.g. $100) use the tenant's base currency code when appropriate,
    without overwriting legitimate currency codes (like USD, EUR) in multi-currency contexts.
    """
    if not text or not currency:
        return text

    # Do NOT perform currency code replacement if multi-currency context is present
    if any(kw in text.lower() for kw in ["multi-currency", "exchange rate", "base currency", "conversions"]):
        if currency.upper() != "USD":
            text = re.sub(r"\$\s*(\d+)", f"{currency} \\1", text)
        return text

    if currency.upper() != "USD":
        text = re.sub(r"\$\s*(\d+)", f"{currency} \\1", text)
        text = re.sub(r"(\d+)\s*\$", f"\\1 {currency}", text)
        
    return text

def replace_tenant_ids_with_names(text: str, tenant_ids: list[str] | None = None) -> str:
    """
    Replace raw tenant UUIDs in the text with their friendly human-readable names.
    """
    if not text or not isinstance(text, str):
        return text or ""
    try:
        from odoo_app.models import Tenant
        uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        found_uuids = set(re.findall(uuid_pattern, text, flags=re.IGNORECASE))
        if tenant_ids:
            found_uuids.update(t for t in tenant_ids if t and t != "default")

        if found_uuids:
            tenant_map = dict(Tenant.objects.filter(id__in=found_uuids).values_list("id", "name"))
            for uid, name in tenant_map.items():
                if name:
                    text = text.replace(str(uid), str(name))
    except Exception:
        pass
    return text

def get_project_logo_b64(custom_logo_path: str | None = None) -> tuple[str | None, str | None]:
    """
    Auto-discovers and encodes project logo image for report generation.
    Checks explicit path, environment variables, and standard project asset locations.
    Returns: (base64_string, mime_type) or (None, None) if no logo image is found yet.
    """
    import base64
    import mimetypes
    from pathlib import Path
    
    candidate_paths = []
    
    if custom_logo_path:
        candidate_paths.append(Path(custom_logo_path))
        
    env_path = os.getenv("COMPANY_LOGO_PATH") or os.getenv("REPORT_LOGO_PATH")
    if env_path:
        candidate_paths.append(Path(env_path))
        
    # Standard project static/asset locations
    agent_dir = Path(__file__).resolve().parent # doova_one_view/api/agent
    app_dir = agent_dir.parent.parent # doova_one_view module
    project_root = app_dir.parent # backend workspace root
    
    for ext in ["png", "jpg", "jpeg", "svg", "webp"]:
        candidate_paths.extend([
            app_dir / "static" / "images" / f"logo.{ext}",
            app_dir / "static" / f"logo.{ext}",
            project_root / "static" / "images" / f"logo.{ext}",
            project_root / "static" / f"logo.{ext}",
            project_root / "assets" / f"logo.{ext}",
            project_root / "reports" / f"logo.{ext}",
        ])
        
    for p in candidate_paths:
        try:
            if p and p.exists() and p.is_file():
                mime, _ = mimetypes.guess_type(str(p))
                mime = mime or "image/png"
                with open(p, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    return encoded, mime
        except Exception:
            continue
            
    return None, None


