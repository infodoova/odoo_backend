# doova_one_view/api/agent/tools_refactored/reporting/_ai_synthesis.py

import re
import json
import logging
from typing import Optional, Dict, Any, Tuple

from doova_one_view.api.agent.config import AgentConfig

logger = logging.getLogger(__name__)


def _generate_ai_executive_summary_llm(
    telemetry: dict,
    prompt: str = "",
    custom_content: str = "",
) -> tuple[dict, dict, list] | None:
    """
    Direct AI generation for the Executive Summary Table, Performance Drivers, and Alerts.
    Feeds live financial telemetry to Claude to generate natural, CFO-grade insights.
    Returns (exec_summary, drivers, alerts) or None if LLM is unavailable.
    """
    if not AgentConfig.ANTHROPIC_API_KEY:
        return None

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatAnthropic(
            model=AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            max_tokens=4096,
        )

        system_instruction = (
            "You are a senior Chief Financial Officer (CFO) synthesizing an Executive Business Report for leadership. "
            "Analyze the provided live ERP financial telemetry and output a strict JSON object with EXACTLY 3 keys:\n\n"
            "1. 'exec_summary': An object containing all 6 required string fields:\n"
            "   - 'overall': 1-2 concise executive sentences describing top-line revenue, period growth vs prior, and overall business health.\n"
            "   - 'profitability': 1-2 sentences analyzing gross profit margin %, EBIT operating profit, and net profit retention.\n"
            "   - 'positive_driver': 1 sentence highlighting the #1 revenue-generating product/SKU or strongest commercial force.\n"
            "   - 'negative_driver': 1 sentence pinpointing the main financial drag, overdue customer receivables, cost creep, or bottleneck.\n"
            "   - 'liquidity': 1 sentence evaluating Net Working Capital, Current Ratio, cash buffer, and ability to comfortably pay supplier bills.\n"
            "   - 'action': 1-2 prioritized, realistic leadership decisions.\n\n"
            "2. 'drivers': An object with 'positive' (2-3 items) and 'negative' (2-3 items) lists (each item has 'name', 'current', 'impact', 'explanation').\n"
            "3. 'alerts': A list of 2-3 prioritized management risks (each item has 'priority', 'priority_class', 'title', 'impact', 'action', 'owner', 'status').\n\n"
            "RULES:\n"
            "- Ground all metrics, percentages, and currencies strictly in the provided telemetry numbers.\n"
            "- Write in clear, professional executive language without technical software/code jargon.\n"
            "- Output ONLY the JSON block inside ```json ... ``` tags."
        )

        user_content = f"Financial Telemetry:\n```json\n{json.dumps(telemetry, indent=2)}\n```\n"
        if prompt:
            user_content += f"\nSpecific User Focus / Prompt: {prompt}\n"
        if custom_content and len(custom_content.strip()) > 10:
            user_content += f"\nAdditional Context / Custom Analysis:\n{custom_content[:1200]}\n"

        response = llm.invoke([
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ])
        if hasattr(response, "content"):
            if isinstance(response.content, list):
                raw_text = "".join([
                    c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else (getattr(c, "text", "") if getattr(c, "type", "") == "text" else (c if isinstance(c, str) else ""))
                    for c in response.content
                ])
            else:
                raw_text = str(response.content)
        else:
            raw_text = str(response)

        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw_text)
        if not match:
            match = re.search(r'(\{[\s\S]*?"exec_summary"[\s\S]*?\})', raw_text)

        if match:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and "exec_summary" in parsed:
                exec_summary = parsed.get("exec_summary", {})
                drivers = parsed.get("drivers", {"positive": [], "negative": []})
                alerts = parsed.get("alerts", [])
                required_fields = ["overall", "profitability", "positive_driver", "negative_driver", "liquidity", "action"]
                if all(field in exec_summary and bool(str(exec_summary[field]).strip()) for field in required_fields):
                    logger.info("Successfully synthesized executive summary directly via AI LLM reasoning.")
                    return exec_summary, drivers, alerts
    except Exception as e:
        logger.warning(f"_generate_ai_executive_summary_llm error (falling back to deterministic synthesis): {e}")

    return None


def _generate_ai_domain_analysis(
    domain: str,
    report_data: dict,
    prompt: str = "",
    company_name: str = "the organization",
    period_label: str = "",
    comparison_label: str = "",
    currency: str = "XAF",
    meta: dict | None = None,
) -> str:
    """
    Invokes the AI CFO/Commercial Agent to synthesize a comprehensive, CFO-grade
    markdown analysis for specialized domain reports based on live ERP database metrics.
    """
    if not AgentConfig.ANTHROPIC_API_KEY:
        return ""

    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = ChatAnthropic(
            model=AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            max_tokens=4096,
        )

        title = (meta or {}).get("title", f"{domain.capitalize()} Executive Report")
        subtitle = (meta or {}).get("subtitle", "Comprehensive business performance analysis.")

        has_prior = bool(report_data.get("prior_period"))
        comparative_rule = (
            f"- The telemetry includes a 'prior_period' block with {comparison_label or 'prior period'} comparison data. "
            "You MUST reference specific QoQ/MoM/YoY movements (growth %, absolute delta, acceleration or deceleration) "
            "in Sections 1 and 2. Do NOT write a single-period snapshot analysis when comparative data is provided.\n"
        ) if has_prior else ""

        # Sanitize prompt to remove delivery/format commands that confuse the model
        clean_prompt = prompt or ""
        if clean_prompt:
            clean_prompt = re.sub(r'(?i)\b(send|email)\s+(?:it\s+)?(?:as\s+pdf\s+)?(?:to\s+)?[\w\.\-]+@[\w\.\-]+', '', clean_prompt).strip()
            clean_prompt = re.sub(r'(?i)\b(as\s+pdf|in\s+pdf|export\s+pdf|download\s+pdf|generate\s+pdf)\b', '', clean_prompt).strip()

        system_instruction = (
            f"You are a top-tier Chief Financial Officer (CFO) and Strategic Executive Advisor preparing the official written analysis section for {company_name}'s management report.\n"
            f"Report Type: {title}\n"
            f"Reporting Period: {period_label} (vs {comparison_label})\n\n"
            "Your objective is to write a deeply intelligent, highly structured, data-grounded strategic briefing in Markdown.\n"
            "CRITICAL: This text will be embedded directly into the report PDF document. Do NOT discuss email delivery, file export capabilities, or technical limitations. Write purely the professional business and financial analysis.\n\n"
            "MANDATORY STRUCTURE:\n"
            f"## {title}\n"
            f"*{subtitle}*\n\n"
            "### 1. Executive Summary & Key Takeaways\n"
            "- A crisp, professional summary of performance, top-line scale, bottom-line results, and overall health.\n\n"
            "### 2. Operational & Financial Deep Dive\n"
            "- Granular breakdown of the relevant domain drivers (margins, cost structure, aging buckets, product velocities, liquidity).\n"
            "- Reference exact metrics and numbers from the provided telemetry.\n\n"
            "### 3. Risk Assessment & Financial Governance\n"
            "- Critical vulnerabilities, cost creep, aging exposure, or operational bottlenecks that leadership must address.\n\n"
            "### 4. Strategic Recommendations & Action Plan\n"
            "- 2–3 actionable, pragmatic next steps with clear ownership and expected financial impact.\n\n"
            "RULES:\n"
            "- Base every number, metric, and percentage directly on the provided data.\n"
            f"{comparative_rule}"
            "- Bold all key financial numbers and dates.\n"
            "- If the user provided a specific prompt/question, directly answer every aspect of their request in the narrative.\n"
            "- Write in clean, publication-ready executive language.\n"
            "- OPTIONAL CHARTS: To embed an executive visual chart, output a fenced code block with language `chart`:\n"
            "  ```chart\n"
            "  {\n"
            "    \"chart_type\": \"bar\",\n"
            "    \"title\": \"Example Metric Breakdown\",\n"
            "    \"labels\": [\"Cat A\", \"Cat B\"],\n"
            "    \"values\": [100, 200]\n"
            "  }\n"
            "  ```\n"
            "  Supported types: 'bar', 'horizontal_bar', 'line', 'pie', 'donut', 'waterfall'."
        )

        user_content = f"Live ERP Database Telemetry for {domain.upper()}:\n```json\n{json.dumps(report_data, indent=2, default=str)}\n```\n"
        if clean_prompt:
            user_content += f"\nUser Focus / Executive Inquiries:\n\"{clean_prompt}\"\n"

        response = llm.invoke([
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ])

        if hasattr(response, "content"):
            if isinstance(response.content, list):
                raw_text = "".join([
                    c.get("text", "") if isinstance(c, dict) and c.get("type") == "text" else (getattr(c, "text", "") if getattr(c, "type", "") == "text" else (c if isinstance(c, str) else ""))
                    for c in response.content
                ])
            else:
                raw_text = str(response.content)
        else:
            raw_text = str(response)

        raw_text = raw_text.strip()
        if raw_text.startswith("```markdown"):
            raw_text = raw_text[11:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        return raw_text.strip()

    except Exception as e:
        logger.warning(f"_generate_ai_domain_analysis error: {e}")
        return ""
