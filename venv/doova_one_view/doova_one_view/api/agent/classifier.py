# api/agent/classifier.py

import json
import anthropic
from .config import AgentConfig

class IntentClassifier:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=AgentConfig.ANTHROPIC_API_KEY)

    def classify_and_extract(self, message: str) -> dict:
        """
        Uses LLM to determine the intent and extract parameters.
        Returns a dict: {"tool_name": "...", "parameters": {...}}
        """
        prompt = f"""
        You are a business intent classifier for an Odoo-synced data platform.
        Your job is to map a user's natural language question to a specific tool and extract parameters.

        AVAILABLE TOOLS:
        - get_sales_summary_tool: For total sales, revenue, order counts.
        - get_top_products_tool: For best-selling products, most popular items.
        - get_inventory_dashboard_alerts_tool: For low stock, out of stock, expiring items/lots, slow moving items.
        - get_inventory_efficiency_tool: For turnover ratio, days inventory on hand.
        - get_receivables_analysis_tool: For overdue invoices, accounts receivable, who owes money.
        - get_unrealized_currency_gains_losses_tool: For unrealized currency gains/losses, balance sheet FX revaluation, foreign currency adjustments.
        - get_general_ledger_tool: For general ledger, grand livre, full account balances, debit/credit totals.
        - get_partner_ledger_tool: For partner ledger, grand livre des tiers, customer/supplier balances, unreconciled entries, and ledger lines.
        - get_customer_statement_tool: For customer statement, releve client, statement of account, customer open invoices and balances.
        - get_followup_report_tool: For follow up report, rapport de relance, customer follow up, overdue receivables list.
        - get_business_health_score_tool: For overall company performance and health status.
        - generate_report_tool: For creating a PDF report or business summary.
        - get_last_report_tool: For downloading the most recent report.

        EXTRACT PARAMETERS:
        - start_date / end_date (ISO format YYYY-MM-DD if mentioned)
        - limit (integer, default 10)
        - company_id (if mentioned)
        - unreconciled_only (boolean, true if user asks for unreconciled entries, open items, or unpaid/unsettled balances)

        RETURN ONLY JSON:
        {{
            "tool_name": "name_of_the_tool_or_null",
            "parameters": {{
                "start_date": "...",
                "end_date": "...",
                "limit": 10
            }},
            "reasoning": "brief explanation"
        }}

        USER MESSAGE: {message}
        """

        try:
            response = self.client.messages.create(
                model=AgentConfig.ROUTER_MODEL,
                max_tokens=500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.content[0].text
            # Simple JSON extraction
            match = content[content.find('{'):content.rfind('}')+1]
            return json.loads(match)
        except Exception:
            return {"tool_name": None, "parameters": {}}
