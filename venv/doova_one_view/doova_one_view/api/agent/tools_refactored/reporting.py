# api/agent/tools_refactored/reporting.py

from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from .common import AgentConfig
from .sales import get_sales_summary_tool
from .inventory import get_inventory_alerts_tool, get_inventory_efficiency_tool
from .finance import get_receivables_analysis_tool, get_cash_flow_health_tool, get_business_health_score_tool

def generate_report_tool(tenant_id: str, company_id: int | None = None, custom_content: str | None = None) -> dict:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filename = f"business_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = reports_dir / filename

    # Basic tools for context
    sales = get_sales_summary_tool(tenant_id, company_id)
    health = get_business_health_score_tool(tenant_id, company_id)
    
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 750
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"DOOVA ONEVIEW — STRATEGIC BUSINESS REPORT")
    y -= 30
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Tenant: {tenant_id} | Date: {datetime.now().strftime('%B %d, %Y')}")
    y -= 40
    
    if custom_content:
        # Simple text wrapping for AI content
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "EXECUTIVE ANALYSIS & RECOMMENDATIONS")
        y -= 20
        c.setFont("Helvetica", 11)
        text_object = c.beginText(40, y)
        for line in custom_content.split('\n'):
            text_object.textLine(line)
        c.drawText(text_object)
    else:
        c.drawString(40, y, f"Health Score: {health['business_health_score']}")
        y -= 20
        c.drawString(40, y, f"Total Revenue: {sales['total_revenue']}")
    
    c.save()

    return {
        "tool_name": "generate_report_tool",
        "download_url": f"{AgentConfig.API_BASE_URL}/reports/{filename}",
        "filename": filename
    }

def get_last_report_tool(tenant_id: str, company_id: int | None = None) -> dict:
    reports_dir = Path("reports")
    files = list(reports_dir.glob(f"business_report_{tenant_id}_*.pdf"))
    if not files: return {"status": "no_reports"}
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    filename = files[0].name
    return {
        "tool_name": "get_last_report_tool",
        "filename": filename,
        "download_url": f"{AgentConfig.API_BASE_URL}/reports/{filename}"
    }
