# api/agent/report_classifier.py
"""
Dedicated, focused ReportTypeClassifier that sits beside RouterNode.
Resolves user intent and domain context to one of the 12 specialized
domain-specific report templates (or legacy health report) with full
backward compatibility.

Callable from all three report entry points:
1. Chat LangChain Agent (create_report tool)
2. Direct REST API (POST /report)
3. Scheduled Cron Reports (ReportJobManager)
"""

import re
import time
import logging
from typing import Optional, Dict, Any, List
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate

from .config import AgentConfig
from .logger import log_error, logger
from .tools_refactored.template_registry import TEMPLATE_REGISTRY, get_template_metadata

logger = logging.getLogger(__name__)

REPORT_CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert financial and business report classifier.
Your ONLY task is to classify the user's report request into EXACTLY ONE canonical report type key.

Available Canonical Report Types:
- sales: Sales performance, revenue trends, top products, customers, order volume.
- purchase: Procurement spend, purchase orders, vendor concentration, AP aging.
- cashflow: Liquidity, bank balances, operating/investing/financing cash flows.
- inventory: Stock valuation, turnover velocity, days on hand (DIO), low-stock alerts.
- income_statement: Comprehensive P&L statement, COGS, OpEx, EBIT, net margins.
- balance_sheet: Financial position, assets, liabilities, equity, solvency.
- financial_analysis: Diagnostic financial ratios (gross margin, current ratio, ROE, health score).
- monthly_pnl: 12-month P&L grid, seasonality trends, monthly run-rate.
- proforma: Forward-looking financial projections, scenario models (bull/base/bear), forecast targets.
- consolidated: Multi-company / multi-statement executive pack (P&L + Balance Sheet + Cash Flow).
- accounting: General ledger trial balance, AR/AP aging schedules, expense breakdown.
- general: Executive intelligence brief, multi-factor operational snapshot.
- health: General executive health & business vital signs (default fallback).

Output ONLY the lowercase canonical key (e.g. "sales", "cashflow", "proforma", "health"). No explanation."""),
    ("human", """Recent Conversation:
{chat_history}

User Request & Content:
{text}

Canonical Report Type:"""),
])


class ReportTypeClassifier:
    """
    Focused Report Intent Classifier sitting beside RouterNode.
    Uses two-tier resolution:
    - Tier 1: Zero-latency keyword scoring (< 1ms, 0 tokens)
    - Tier 2: Fast LLM classifier fallback for ambiguous requests (~200ms)
    """

    _instance: Optional["ReportTypeClassifier"] = None

    def __init__(self):
        try:
            self.llm = ChatAnthropic(
                model=AgentConfig.ROUTER_MODEL,
                anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
                max_tokens=getattr(AgentConfig, "MAX_REPORT_CLASSIFIER_TOKENS", 30),
                temperature=0.0,
                model_kwargs={
                    "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
                }
            )
            self.prompt = REPORT_CLASSIFIER_PROMPT
        except Exception as e:
            logger.warning(f"ReportTypeClassifier LLM init failed: {e}")
            self.llm = None
            self.prompt = None

    @classmethod
    def get_instance(cls) -> "ReportTypeClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def normalize_report_type(raw_type: str | None) -> str:
        """
        Normalizes aliases and shorthand keys to canonical domain keys.
        Ensures 100% backward compatibility for legacy callers.
        """
        if not raw_type:
            return "health"

        cleaned = str(raw_type).strip().lower()

        if cleaned in TEMPLATE_REGISTRY:
            return cleaned

        for key, meta in TEMPLATE_REGISTRY.items():
            if cleaned in meta.get("aliases", []):
                return key

        if cleaned in ("health", "executive_health", "business_health", "default", "vital_signs"):
            return "health"
        elif cleaned in ("analysis", "executive"):
            return "general"

        return cleaned

    @classmethod
    def classify(
        cls,
        prompt: str = "",
        custom_content: str = "",
        chat_history: list | None = None,
        raw_type: str | None = None,
    ) -> str:
        """
        Classifies user intent into a canonical report type key.
        """
        start = time.time()

        # 0. If explicit raw_type is provided and valid, normalize and return immediately
        if raw_type and raw_type not in ("auto", "none", ""):
            norm = cls.normalize_report_type(raw_type)
            if norm in TEMPLATE_REGISTRY or norm == "health":
                return norm

        combined_text = f"{prompt} {custom_content}".lower().strip()
        if not combined_text:
            return "health"

        # Tier 1: Fast Rule / Keyword Matcher (0ms, 0 tokens)
        tier1_result = cls._keyword_score(combined_text)
        if tier1_result:
            duration = (time.time() - start) * 1000
            logger.debug(f"ReportTypeClassifier Tier 1 Match: {tier1_result} in {duration:.1f}ms")
            return tier1_result

        # Tier 2: Fast LLM Classifier Fallback
        classifier = cls.get_instance()
        if classifier.llm and classifier.prompt:
            try:
                history_str = "None"
                if chat_history and isinstance(chat_history, list):
                    recent = chat_history[-4:]
                    lines = []
                    for m in recent:
                        if isinstance(m, dict):
                            r = "User" if m.get("role") == "user" else "Assistant"
                            c = str(m.get("content") or "")[:120]
                            if c:
                                lines.append(f"{r}: {c}")
                    if lines:
                        history_str = "\n".join(lines)

                chain = classifier.prompt | classifier.llm
                response = chain.invoke({"text": combined_text[:600], "chat_history": history_str})
                raw_out = response.content.strip().lower()
                clean_key = re.sub(r'[^a-z_]', '', raw_out.split()[0] if raw_out.split() else '')

                norm = cls.normalize_report_type(clean_key)
                duration = (time.time() - start) * 1000
                logger.info(f"ReportTypeClassifier Tier 2 LLM: {norm} in {duration:.1f}ms")
                if norm in TEMPLATE_REGISTRY or norm == "health":
                    return norm
            except Exception as e:
                log_error("ReportTypeClassifier.classify", e)

        # Default fallback
        return "health"

    @staticmethod
    def _keyword_score(text: str) -> Optional[str]:
        """
        Scans text for weighted domain keywords.
        Returns canonical key if strong match found.
        """
        scores: Dict[str, int] = {k: 0 for k in TEMPLATE_REGISTRY.keys()}

        # Domain specific high-priority patterns
        patterns = {
            "proforma": [r'\bpro\s*forma\b', r'\bprojections?\b', r'\bforecast(ing|ed)?\b', r'\bscenario(s)?\b', r'\bbull\s*case\b', r'\bbear\s*case\b'],
            "cashflow": [r'\bcash\s*flow\b', r'\bliquidity\b', r'\btreasury\b', r'\bbank\s*balanc', r'\boperating\s*cash\b'],
            "inventory": [r'\binventory\b', r'\bstock(s)?\b', r'\bwarehous', r'\bturnover\b', r'\bdays\s*on\s*hand\b', r'\blow\s*stock\b', r'\breorder\b'],
            "purchase": [r'\bpurchase(s|d|ing)?\b', r'\bprocurement\b', r'\bvendor(s)?\b', r'\bsupplier(s)?\b', r'\bpo(s)?\b', r'\bspend(ing)?\b', r'\bap\s*aging\b'],
            "sales": [r'\bsales?\b', r'\brevenue\s*trend', r'\btop\s*product', r'\btop\s*customer', r'\bvolume\b', r'\border(s)?\b', r'\bcommercial\b'],
            "income_statement": [r'\bincome\s*statement\b', r'\bp\s*&\s*l\b', r'\bpnl\b', r'\bprofit\s*and\s*loss\b', r'\bcogs\b', r'\bopex\b', r'\bgross\s*margin\b', r'\bebit\b'],
            "balance_sheet": [r'\bbalance\s*sheet\b', r'\bassets?\b', r'\bliabilit(y|ies)\b', r'\bequity\b', r'\bsolvency\b'],
            "monthly_pnl": [r'\bmonthly\s*pnl\b', r'\bmonthly\s*performance\b', r'\bseasonality\b', r'\b12\s*month', r'\brun\s*rate\b'],
            "consolidated": [r'\bconsolidat(ed|ion)\b', r'\bmulti\s*company\b', r'\bgroup\s*level\b', r'\bparent\s*company\b'],
            "accounting": [r'\baccounting\b', r'\bgeneral\s*ledger\b', r'\btrial\s*balance\b', r'\bjournal(s)?\b', r'\bar\s*aging\b'],
            "financial_analysis": [r'\bfinancial\s*analysis\b', r'\bratio(s)?\b', r'\bcurrent\s*ratio\b', r'\bquick\s*ratio\b', r'\broe\b', r'\broa\b'],
            "health": [r'\bhealth\s*score\b', r'\bvital\s*sign', r'\bhealth\s*report\b', r'\bcheck\s*up\b'],
            "general": [r'\bgeneral\s*report\b', r'\bexecutive\s*brief\b', r'\boverview\s*report\b'],
        }

        for domain, regexes in patterns.items():
            for pat in regexes:
                if re.search(pat, text):
                    scores[domain] = scores.get(domain, 0) + 3

        # Match generic keywords from TEMPLATE_REGISTRY
        for key, meta in TEMPLATE_REGISTRY.items():
            for kw in meta.get("nlp_keywords", []):
                if kw in text:
                    scores[key] = scores.get(key, 0) + 1

        best_domain, best_score = max(scores.items(), key=lambda x: x[1])
        if best_score >= 2:
            return best_domain

        return None
