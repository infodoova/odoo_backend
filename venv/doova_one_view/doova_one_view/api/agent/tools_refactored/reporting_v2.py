# api/agent/tools_refactored/reporting_v2.py

import os
import io
import base64
from pathlib import Path
from datetime import datetime
import markdown
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from ..utils import make_report_url
from .sales import get_sales_summary_tool, get_time_series_data_tool
from .finance import get_business_health_score_tool, calculate_pnl_tool
from .common import get_companies_tool

def generate_report_tool(
    tenant_id: str, 
    custom_content: str = "", 
    company_id: int | None = None,
    base_currency: str | None = None
) -> dict:
    from ..utils import get_tenant_currency
    
    resolved_company_id = company_id
    currency = base_currency or get_tenant_currency(tenant_id, resolved_company_id)
    
    # 1. ALWAYS Fetch Core KPI Data for the Dashboard
    sales = {}
    health = {}
    pnl = {}
    company_name = "Financial Overview"
    
    try:
        sales = get_sales_summary_tool(tenant_id, resolved_company_id, base_currency=base_currency)
        health = get_business_health_score_tool(tenant_id, resolved_company_id, base_currency=base_currency)
        pnl = calculate_pnl_tool(tenant_id, resolved_company_id, start_date="2026-01-01", end_date=datetime.now().strftime("%Y-%m-%d"), base_currency=base_currency)
        
        # Get company name
        companies = get_companies_tool(tenant_id)
        for c in companies:
            if c.get("id") == resolved_company_id:
                company_name = c.get("name", company_name)
    except Exception:
        pass
        
    revenue_val = sales.get('total_revenue', 0)
    score_val = health.get('business_health_score', 0)
    ebit_val = pnl.get('ebit', 0) if isinstance(pnl, dict) else 0
    
    # Format KPIs
    fmt_revenue = f"{revenue_val:,.0f} {currency}"
    fmt_ebit = f"{ebit_val:,.0f} {currency}"
    
    # Auto-generate summary if not provided by AI
    if not custom_content.strip():
        custom_content = f"""
# Automated Summary
The business is currently operating with a health score of **{score_val}/100** and generated **{fmt_revenue}** in revenue during this period.
"""
            
    # 2. Generate Matplotlib Chart (Sales Trend)
    chart_b64 = ""
    try:
        ts_result = get_time_series_data_tool(tenant_id, resolved_company_id, granularity="month", base_currency=base_currency)
        ts_data = ts_result.get("points", [])
        if ts_data and isinstance(ts_data, list) and len(ts_data) > 0:
            labels = [str(d.get("period", ""))[:7] for d in ts_data] # YYYY-MM
            values = [float(d.get("revenue", 0)) for d in ts_data]
            
            plt.figure(figsize=(9, 3.5), facecolor='white')
            ax = plt.subplot(111)
            ax.plot(labels, values, marker='o', color='#2563eb', linewidth=2.5, markersize=7)
            ax.fill_between(labels, values, color='#eff6ff', alpha=0.6)
            
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#cbd5e1')
            ax.spines['bottom'].set_color('#cbd5e1')
            ax.tick_params(colors='#64748b', labelsize=8)
            ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
            ax.xaxis.grid(False)
            
            plt.title('Revenue Trend', fontsize=14, color='#0f172a', fontweight='bold', pad=20)
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close()
    except Exception as e:
        print(f"Chart generation failed: {e}")
        pass
            
    from .emoji_to_badges import normalize_status_emoji
    
    # Strip decorative emojis which crash standard PDF fonts
    decorative_emojis = ["📊", "🏢", "💰", "🏆", "🏦", "📐", "💧", "📬", "📤", "👥", "📦", "🔍"]
    for e in decorative_emojis:
        custom_content = custom_content.replace(e, "")
        
    # Convert status emojis to HTML badges
    custom_content = normalize_status_emoji(custom_content)

    import re
    import json

    # ── Generic chart renderer ────────────────────────────────────────────
    def _render_chart(chart_type: str, title: str, labels: list, values: list) -> str:
        """
        Render any chart type to a base64 PNG string.
        Handles edge cases: empty data, single value, long labels, many items.
        Returns an HTML <div> with embedded <img>, or a fallback message.
        """
        # Sanitise inputs
        if not values or not labels:
            return ""
        # Ensure equal length
        min_len = min(len(labels), len(values))
        labels = [str(l) for l in labels[:min_len]]
        values = [float(v) for v in values[:min_len]]
        n = len(values)

        # Truncate very long labels (>25 chars)
        display_labels = [l[:22] + "..." if len(l) > 25 else l for l in labels]

        # Dynamic blue palette
        cmap = matplotlib.colormaps['Blues']
        colors = [cmap(0.3 + 0.6 * i / max(n - 1, 1)) for i in range(n)]

        chart_type = chart_type.lower().strip()

        try:
            fig, ax = plt.subplots(figsize=(8, 4), facecolor='white')

            if chart_type == "pie":
                # Explode the largest slice
                max_idx = values.index(max(values))
                explode = [0.05 if i == max_idx else 0 for i in range(n)]

                total = sum(values) or 1
                wedges, _ = ax.pie(
                    values,
                    colors=colors,
                    explode=explode,
                    startangle=90,
                    wedgeprops={'edgecolor': 'white', 'linewidth': 2},
                )

                # Donut hole
                ax.add_artist(plt.Circle((0, 0), 0.55, fc='white'))

                # Legend with label + percentage (avoids text overlap on small slices)
                legend_labels = [
                    f"{lab}  —  {val / total * 100:.1f}%"
                    for lab, val in zip(labels, values)
                ]
                ax.legend(
                    wedges, legend_labels,
                    loc="center left", bbox_to_anchor=(1, 0.5),
                    fontsize=9, frameon=False,
                )

            elif chart_type == "bar":
                bar_colors = colors if n > 1 else ['#2563eb']
                bars = ax.bar(display_labels, values, color=bar_colors, alpha=0.9)
                # Add value labels on top of bars
                for bar, val in zip(bars, values):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val:,.0f}", ha='center', va='bottom',
                        fontsize=7, color='#334155',
                    )

            else:  # line (default)
                ax.plot(display_labels, values, marker='o', color='#2563eb', linewidth=2.5, markersize=6)
                ax.fill_between(display_labels, values, color='#eff6ff', alpha=0.6)

            # Shared styling for non-pie charts
            if chart_type != "pie":
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#cbd5e1')
                ax.spines['bottom'].set_color('#cbd5e1')
                ax.tick_params(colors='#64748b', labelsize=8)
                ax.yaxis.grid(True, linestyle=':', color='#e2e8f0', alpha=0.8)
                ax.xaxis.grid(False)
                # Auto-rotate labels when there are many items or long text
                if n > 5 or any(len(l) > 10 for l in display_labels):
                    plt.xticks(rotation=45, ha='right')

            if title:
                plt.title(title, fontsize=12, color='#0f172a', fontweight='bold', pad=15)
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            img_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)

            return (
                f'<div class="chart-container">'
                f'<img class="chart-image" width="700" '
                f'src="data:image/png;base64,{img_b64}" alt="{title}" />'
                f'</div>'
            )
        except Exception as exc:
            plt.close('all')
            print(f"Chart render error ({chart_type}): {exc}")
            return ""

    # ── Parse ```chart blocks and replace with rendered images ─────────
    def _chart_block_replacer(match):
        json_str = match.group(1)
        try:
            cfg = json.loads(json_str)
        except json.JSONDecodeError:
            return "*(Invalid chart JSON)*"
        return _render_chart(
            chart_type=cfg.get("chart_type", "bar"),
            title=cfg.get("title", ""),
            labels=cfg.get("labels", []),
            values=cfg.get("values", []),
        )

    custom_content = re.sub(
        r'```chart\s*\n(.*?)\n```',
        _chart_block_replacer,
        custom_content,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Convert dynamic Markdown to HTML
    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'sane_lists'])
    body_html = md.convert(custom_content)
    
    from .table_layout import add_dynamic_table_widths
    body_html = add_dynamic_table_widths(body_html)
    
    # 4. Load and Render HTML template
    template_dir = Path(__file__).parent / "templates"
    template_dir.mkdir(exist_ok=True)
    template_path = template_dir / "report_template.html"
    
    if not template_path.exists():
        html_out = f"<html><body>{body_html}</body></html>"
    else:
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("report_template.html")
        html_out = template.render(
            tenant_id=tenant_id,
            company_name=company_name,
            date=datetime.now().strftime('%B %d, %Y'),
            health_score=score_val,
            revenue=fmt_revenue,
            margin=fmt_ebit,
            chart_b64=chart_b64,
            body_html=body_html
        )
    
    # Create output directory and unique filename
    reports_dir = Path('reports')
    reports_dir.mkdir(exist_ok=True)
    filename = f"business_report_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_v2.pdf"
    output_path = reports_dir / filename
    
    # Generate PDF using xhtml2pdf (pure python HTML/CSS to PDF)
    with open(output_path, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(html_out, dest=result_file)
        
    if pisa_status.err:
        raise Exception(f"Failed to generate PDF: {pisa_status.err}")
        
    relative_path = f"/financial-advisor/reports/{filename}"
    return {
        'tool_name': 'generate_report_tool',
        'download_url': make_report_url(filename),
        'path': relative_path,
        'filename': filename,
    }

def get_last_report_tool(tenant_id: str, company_id: int | None = None) -> dict:
    reports_dir = Path('reports')
    files = list(reports_dir.glob(f'business_report_{tenant_id}_*_v2.pdf'))
    if not files:
        # Fallback to older reports if v2 doesn't exist
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
