"""
Router node – classifies user intent into REJECT, FAST, or REASONING.
Uses a hybrid approach of keyword heuristics and LLM classification.
"""

import anthropic
from .config import AgentConfig
from .tools import normalize_business_text_for_intent


def _is_broad_plan_reasoning_question(message: str) -> bool:
    """
    Force broad multi-domain or strategic questions to REASONING.
    These questions should create a Financial Execution Plan first.
    """
    text = normalize_business_text_for_intent(message)

    reasoning_terms = [
        "analyze", "analysis", "together", "main business risks", "business risks",
        "risk", "risks", "business health", "healthy", "cfo", "management",
        "recommend", "recommendation", "recommendations", "what should we do",
        "what actions", "action plan", "priorities", "priority", "strategy",
        "strategic", "deep analysis", "full analysis",
    ]

    domain_groups = [
        ["sales", "revenue", "orders", "customers", "products"],
        ["inventory", "stock", "low stock", "expiring", "lots", "turnover"],
        ["receivables", "ar", "overdue", "cash flow", "liquidity", "collection"],
        ["accounting", "invoices", "payables", "ap"],
    ]

    has_reasoning_term = any(term in text for term in reasoning_terms)
    matched_domains = 0

    for group in domain_groups:
        if any(term in text for term in group):
            matched_domains += 1

    if has_reasoning_term and matched_domains >= 2:
        return True

    if any(term in text for term in [
        "business health", "main business risks", "cfo-style", "cfo style",
        "management focus", "what should management", "full business analysis",
        "deep business analysis",
    ]):
        return True

    return False


class RouterNode:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=AgentConfig.ANTHROPIC_API_KEY
        )

    def classify(self, message: str) -> str:
        """
        Classify the user message into: REJECT / FAST / REASONING
        """
        text = normalize_business_text_for_intent(message)

        # Broad strategic questions must go to Reasoning
        if _is_broad_plan_reasoning_question(message):
            return "REASONING"

        # ─────────────────────────────
        # HARD FAST RULES
        # ─────────────────────────────
        fast_keywords = [
            "hello", "hi", "help", "what can you do", "explain this chatbot", "how do you work",
            "sales summary", "revenue", "total sales", "sales total",
            "top products", "top selling", "best products",
            "low stock", "inventory alerts", "inventory alert", "stock alert",
            "cash flow health", "cash flow", "liquidity", "accounts receivable", "accounts payable",
            "receivables", "payables", "receivables analysis", "overdue receivables", "overdue invoices",
            "top overdue customers", "who owes", "customers owe", "ar aging", "accounts receivable aging",
            "sales trend", "revenue trend", "time series", "monthly sales", "daily sales", "weekly sales",
            "sales over time", "revenue over time", "monthly revenue", "revenue by month", "sales by month",
            "variance", "compare sales", "compare revenue", "month over month", "period over period",
            "revenue change", "sales change", "forecast sales", "sales forecast", "forecast revenue",
            "revenue forecast", "predict sales", "predict revenue", "next month sales", "next months sales",
            "future sales", "future revenue", "customer metrics", "top customers", "customer ranking",
            "customer revenue", "best customers", "customer risk", "high risk customers", "customer overdue risk",
            "inventory efficiency", "inventory turnover", "turnover ratio", "days inventory",
            "days inventory on hand", "stock efficiency", "inventory performance",
            "business health", "business health score", "company health", "overall health", "health score",
            "how healthy is the business", "business status", "profitability", "profit analysis",
            "profit margin", "gross margin", "gross profit", "most profitable products", "profitable products",
            "category profitability", "margin analysis", "database question", "custom database",
            "sales by company", "revenue by company", "orders by state", "order status",
            "overdue by company", "who owes the most", "inventory value by company", "stock value by company",
            "generate report", "pdf report", "business report", "financial report", "create report",
            "download report", "report pdf", "send alert", "create alert", "notify dashboard",
            "dashboard alert", "make an alert", "alert me", "send email", "email report", "email this",
            "prepare email", "draft email", "send this by email", "email the report",
        ]

        if any(keyword in text for keyword in fast_keywords):
            return "FAST"

        # ─────────────────────────────
        # HARD REASONING RULES
        # ─────────────────────────────
        reasoning_keywords = [
            "why", "root cause", "declining", "decline", "compare", "comparison",
            "analyze", "analysis of why", "forecast", "predict", "recommend",
            "recommendation", "what should we do", "strategy", "plan", "risk", "improve",
        ]

        if any(keyword in text for keyword in reasoning_keywords):
            return "REASONING"

        # LLM classification fallback
        prompt = f"""
You are a financial query classifier.
Your ONLY job is to return one word.

Classify this question:
{message}

Rules:
- REJECT: clearly unrelated to the business (politics, celebs, random nonsense, etc.)
- FAST: simple direct lookup, greeting, help question, or simple explanation.
- REASONING: needs multi-step analysis, comparison, planning, or business advice.

Important:
- Greetings and help questions are FAST.
- Direct tool lookups (sales, stock, etc.) are FAST.
- If unsure, choose FAST.

Return ONLY one of:
REJECT
FAST
REASONING
"""

        response = self.client.messages.create(
            model=AgentConfig.ROUTER_MODEL,
            max_tokens=AgentConfig.MAX_ROUTER_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        decision = response.content[0].text.strip().upper()
        if decision not in ["REJECT", "FAST", "REASONING"]:
            return "FAST"

        return decision
