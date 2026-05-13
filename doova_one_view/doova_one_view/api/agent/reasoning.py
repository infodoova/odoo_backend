"""
Reasoning node – handles multi-step financial analysis and advisory.
Uses a two-phase Plan & Execute workflow for complex business questions.
"""

import anthropic
import json
from uuid import uuid4
from .config import AgentConfig
from .tools import run_reasoning_tools


class ReasoningNode:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=AgentConfig.ANTHROPIC_API_KEY
        )

    # ─────────────────────────────
    # PHASE 1: CREATE FINANCIAL EXECUTION PLAN
    # ─────────────────────────────
    def create_plan(
        self,
        message: str,
        tenant_id: str,
        company_id: int | None = None,
        memory_summary: str = "",
    ) -> dict:
        """
        Creates a pending financial execution plan.
        This does NOT give the final answer yet.
        """
        plan_id = str(uuid4())

        prompt = f"""
You are the Reasoning Node for a Virtual CFO agent.

The user asked a complex financial/business question.
Your job is NOT to answer yet.
Your job is to create a Financial Execution Plan that the user must approve before final analysis.

Available tools:
- calculate_ratio_tool: safe ratio calculation
- get_sales_summary_tool: revenue, orders, average order value, gross margin
- get_top_products_tool: top products by revenue, margin, or quantity
- get_inventory_alerts_tool: low stock and expiring inventory alerts
- get_inventory_efficiency_tool: inventory value, turnover ratio, days on hand
- get_business_health_score_tool: weighted business health score across core KPIs
- get_cash_flow_health_tool: AR, AP, liquidity ratio, liquidity status
- get_receivables_analysis_tool: AR outstanding, overdue customers, receivables risk
- get_time_series_data_tool: daily, weekly, or monthly business trends
- get_sales_chart_data_tool: structured sales chart data
- analyze_variance_tool: period-over-period comparison and variance analysis
- forecast_sales_tool: sales forecast using historical sales data
- analyze_profitability_tool: gross margin and profitability breakdown
- get_customer_metrics_tool: customer retention, churn risk, and loyalty metrics
- ask_database_custom_question: NL-to-SQL fallback for custom database questions
- generate_report_tool: create business reports and get a download link
- get_last_report_tool: find the most recent business report and get a download link
- send_alert_tool: dashboard notification action after approval
- send_email_tool: email action after approval

Return ONLY valid JSON.
Do not use markdown.
Do not explain outside the JSON.

Required JSON shape:
{{
  "plan_id": "{plan_id}",
  "question_summary": "Brief restatement of what the user asked",
  "data_sources_used": ["specific tool names or expected data sources"],
  "key_findings": ["early observations or assumptions before final analysis"],
  "proposed_analysis_steps": [
    {{
      "step": 1,
      "action": "What analysis step will be done",
      "rationale": "Why this step is needed"
    }}
  ],
  "estimated_depth": "STANDARD or DEEP",
  "status": "PENDING_APPROVAL"
}}

Rules:
- Do NOT give the final answer.
- Do NOT calculate final results yet.
- Create a practical plan focusing only on relevant tools.
- Use action tools like generate_report_tool only after approval.

Tenant ID: {tenant_id}
Company ID: {company_id}
Conversation summary: {memory_summary}
User question: {message}
"""

        response = self.client.messages.create(
            model=AgentConfig.REASONING_MODEL,
            max_tokens=AgentConfig.MAX_REASONING_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()
        try:
            plan = json.loads(raw_text)
        except Exception:
            # Fallback plan if JSON fails
            plan = {
                "plan_id": plan_id,
                "question_summary": message,
                "data_sources_used": [
                    "get_sales_summary_tool",
                    "get_top_products_tool",
                    "get_cash_flow_health_tool"
                ],
                "key_findings": [
                    "A structured analysis is required before giving a final recommendation."
                ],
                "proposed_analysis_steps": [
                    {
                        "step": 1,
                        "action": "Collect sales and margin data",
                        "rationale": "Sales and margin are needed to identify financial performance drivers."
                    },
                    {
                        "step": 2,
                        "action": "Review top products and mix impact",
                        "rationale": "Product mix can explain changes in revenue and profitability."
                    },
                    {
                        "step": 3,
                        "action": "Review cash flow health",
                        "rationale": "Liquidity gives context on financial risk."
                    },
                    {
                        "step": 4,
                        "action": "Generate final recommendation",
                        "rationale": "The user needs a clear business conclusion."
                    }
                ],
                "estimated_depth": "STANDARD",
                "status": "PENDING_APPROVAL"
            }

        plan["plan_id"] = plan.get("plan_id", plan_id)
        plan["status"] = "PENDING_APPROVAL"
        return plan

    # ─────────────────────────────
    # PHASE 2: EXECUTE APPROVED PLAN
    # ─────────────────────────────
    def execute_plan(
        self,
        message: str,
        plan: dict,
        tenant_id: str,
        company_id: int | None = None,
        memory_summary: str = "",
    ) -> str:
        """Executes an approved plan and gives the final advisory answer."""
        tool_results = run_reasoning_tools(
            message=message, tenant_id=tenant_id, company_id=company_id, plan=plan
        )

        prompt = f"""
You are the Reasoning Node for a Virtual CFO agent.

The user approved this Financial Execution Plan.
Now execute the plan and give the final answer.

You have tool results below.
Use ONLY the tool results for specific numbers.
Do NOT invent numbers.
Treat PostgreSQL tool results as real synced business data unless a tool explicitly says the data is mock/test.
Do not add mock/test warnings unless the tool result explicitly says so.

Required answer structure:
1. Answer
2. Context / Tool Findings
3. Recommendation
4. Limitations / Next Data Needed

Rules:
- Give the final advisory answer now.
- Follow the approved plan.
- Do not ask for approval again.
- Show important calculations clearly.
- If the tool results say they came from PostgreSQL or synced Odoo data, treat them as real business data.
- Do not describe the results as mock/test data unless the tool output explicitly says they are mock/test.
- If a tool result contains a "download_url", YOU MUST PROVIDE THIS LINK TO THE USER in your final answer so they can download the file.

Tenant ID: {tenant_id}
Company ID: {company_id}

Conversation summary:
{memory_summary}

Original / latest user message:
{message}

Approved Financial Execution Plan:
{json.dumps(plan, indent=2)}

Tool results:
{json.dumps(tool_results, indent=2)}
"""

        response = self.client.messages.create(
            model=AgentConfig.REASONING_MODEL,
            max_tokens=AgentConfig.MAX_REASONING_TOKENS,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return response.content[0].text

    # ─────────────────────────────
    # LEGACY DIRECT RUN
    # ─────────────────────────────
    def run(
        self,
        message: str,
        tenant_id: str,
        company_id: int | None = None,
        memory_summary: str = "",
    ) -> str:
        """Direct execution without a separate planning phase."""
        tool_results = run_reasoning_tools(
            message=message, tenant_id=tenant_id, company_id=company_id, plan=None
        )

        prompt = f"""
You are the Reasoning Node for a Virtual CFO agent.

You MUST solve the full user request as a chain of operations.

Rules:
- Do NOT stop early
- Do NOT answer only part of the question
- Do NOT ask for clarification if the question is clear
- Follow all steps in order
- For calculations, show steps clearly
- For business analysis, give a clear recommendation
- Keep the answer focused on the user's question
- Use the tool results below for specific numbers
- Do NOT invent numbers

Tenant ID: {tenant_id}
Company ID: {company_id}

Conversation summary:
{memory_summary}

User question:
{message}

Tool results:
{json.dumps(tool_results, indent=2)}
"""

        response = self.client.messages.create(
            model=AgentConfig.REASONING_MODEL,
            max_tokens=AgentConfig.MAX_REASONING_TOKENS,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return response.content[0].text
