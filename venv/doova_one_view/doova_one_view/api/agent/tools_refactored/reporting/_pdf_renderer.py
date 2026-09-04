# doova_one_view/api/agent/tools_refactored/reporting/_pdf_renderer.py

import os
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import markdown

from doova_one_view.api.agent.utils import make_report_url, get_project_logo_b64
from ._formatters import _highlight_negative_numbers_html
from ._template_router import _get_reports_dir

logger = logging.getLogger(__name__)


def render_and_compile_pdf(
    template_file: str,
    context: dict,
    filename_prefix: str,
    tenant_id: str,
    custom_content: str = "",
    logo_path: str | None = None,
    logo_b64: str | None = None,
    logo_url: str | None = None,
) -> dict:
    """
    Renders Jinja2 template with provided context and compiles to PDF via WeasyPrint.
    Returns standardized tool response dict with status, download_url, path, and filename.
    """
    # 1. Resolve Project Logo
    logo_mime = "image/png"
    if not logo_b64:
        discovered_b64, discovered_mime = get_project_logo_b64(custom_logo_path=logo_path)
        if discovered_b64:
            logo_b64 = discovered_b64
            logo_mime = discovered_mime or "image/png"

    # 2. Setup Jinja2 Environment
    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template(template_file)

    # 3. Merge Logo Context
    render_ctx = dict(context)
    render_ctx.update({
        "logo_url": logo_url,
        "logo_b64": logo_b64,
        "logo_mime": logo_mime,
    })

    html_out = template.render(**render_ctx)

    # 4. Highlight Negative Values & Post-Process
    html_out = _highlight_negative_numbers_html(html_out)

    # 5. Output Path & WeasyPrint Compilation
    reports_dir = _get_reports_dir()
    company_name = context.get("company_name", "All_Companies")
    reporting_period = context.get("reporting_period", "All_Time")
    
    cleaned_prefix = re.sub(r'[^A-Za-z0-9]+', '_', filename_prefix.strip()).strip('_')
    tenant_slug = re.sub(r'[^A-Za-z0-9]+', '_', str(tenant_id).strip()).strip('_')[:30]
    company_slug = re.sub(r'[^A-Za-z0-9]+', '_', str(company_name).strip()).strip('_')[:30]
    period_slug = re.sub(r'[^A-Za-z0-9]+', '_', str(reporting_period).strip()).strip('_')[:30]
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{cleaned_prefix}_report_{tenant_slug}_{company_slug}_{period_slug}_{timestamp_str}.pdf"
    output_path = reports_dir / filename

    try:
        HTML(string=html_out).write_pdf(output_path)
    except Exception as e:
        logger.error(f"WeasyPrint PDF write failed: {e}", exc_info=True)
        return {
            'tool_name': 'generate_report_tool',
            'status': 'error',
            'error': f"PDF compilation failed: {str(e)}",
            'filename': filename,
        }

    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'generate_report_tool',
        'status': 'success',
        'download_url': make_report_url(filename),
        'path': relative_path,
        'filename': filename,
    }
