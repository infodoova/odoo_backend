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
    width, height = letter
    
    # Header
    c.setStrokeColorRGB(0.1, 0.4, 0.7)
    c.setLineWidth(2)
    c.line(40, height - 60, width - 40, height - 60)
    
    c.setFont("Helvetica-Bold", 18)
    c.setFillColorRGB(0.1, 0.3, 0.5)
    c.drawString(40, height - 50, "DOOVA ONEVIEW")
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColorRGB(0, 0, 0)
    c.drawRightString(width - 40, height - 50, "Strategic Business Report")
    
    # Metadata
    y = height - 100
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Generated: {datetime.now().strftime('%B %d, %Y %H:%M')}")
    c.drawRightString(width - 40, y, f"Tenant ID: {tenant_id}")
    
    # Business Vital Signs
    y -= 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "BUSINESS VITAL SIGNS")
    y -= 10
    c.setLineWidth(1)
    c.line(40, y, width - 40, y)
    y -= 25
    
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Overall Health Score:")
    c.setFont("Helvetica", 11)
    c.drawString(180, y, f"{health['business_health_score']} / 100")
    
    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Total Annual Revenue:")
    c.setFont("Helvetica", 11)
    c.drawString(180, y, f"{sales['total_revenue']:,}")
    
    # AI Executive Analysis
    y -= 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "EXECUTIVE ANALYSIS & RECOMMENDATIONS")
    y -= 10
    c.line(40, y, width - 40, y)
    y -= 25
    
    if custom_content:
        c.setFont("Helvetica", 10)
        text_object = c.beginText(40, y)
        text_object.setLeading(14)
        
        # Simple character-based wrapping for robustness
        words = custom_content.split()
        current_line = []
        for word in words:
            current_line.append(word)
            if len(" ".join(current_line)) > 90:
                text_object.textLine(" ".join(current_line[:-1]))
                current_line = [word]
        if current_line:
            text_object.textLine(" ".join(current_line))
            
        c.drawText(text_object)
    else:
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(40, y, "No custom AI analysis provided for this report.")
    
    # Footer
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2, 30, "Confidential - Powered by Doova Finance Brain")
    
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
