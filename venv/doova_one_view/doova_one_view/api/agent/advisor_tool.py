"""
Strategic Advisor Tool for Doova One View Agent.
Implements the Executor–Advisor pattern, allowing the fast Executor model
to invoke a high-intelligence Advisor model mid-generation for complex
SQL query planning, anomaly root-cause diagnosis, and strategic CFO guidance.
"""

import json
import logging
import time
from typing import Any, Optional
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage

from .config import AgentConfig
from .prompts import ADVISOR_SYSTEM_PROMPT
from .logger import logger, log_error

logger = logging.getLogger(__name__)


class StrategicAdvisorService:
    """
    Dedicated high-reasoning advisor service.
    Invoked on-demand by the fast executor when deep reasoning or
    complex Odoo data warehouse relationship navigation is needed.
    """

    _advisor_llm: Optional[ChatAnthropic] = None

    @classmethod
    def get_llm(cls) -> ChatAnthropic:
        """Lazy-initialize the high-reasoning Advisor LLM."""
        if cls._advisor_llm is None:
            model_kwargs = {
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
            cls._advisor_llm = ChatAnthropic(
                model=AgentConfig.ADVISOR_MODEL,
                anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
                max_tokens=AgentConfig.MAX_ADVISOR_TOKENS,
                model_kwargs=model_kwargs,
            )
        return cls._advisor_llm

    @classmethod
    def advise_sql(
        cls,
        question: str,
        schema_context: str,
        failed_sql: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Advises on complex multi-table SQL joins or diagnoses SQL runtime errors.
        """
        if not AgentConfig.ENABLE_ADVISOR_TOOL:
            return {
                "advised": False,
                "reason": "Advisor tool is disabled via ENABLE_ADVISOR_TOOL config.",
            }

        start_time = time.time()
        try:
            prompt_content = (
                f"### TASK: Relational SQL Join & Query Planning\n\n"
                f"**User Business Question**: {question}\n\n"
                f"**Target Warehouse Schema Context**:\n{schema_context[:4000]}\n\n"
            )
            if failed_sql or error_message:
                prompt_content += (
                    f"**Previous Failed Query**:\n```sql\n{failed_sql or 'N/A'}\n```\n\n"
                    f"**Database Error Encountered**:\n{error_message or 'N/A'}\n\n"
                    f"Diagnose why this query failed and provide the exact corrected SQL join structure."
                )
            else:
                prompt_content += (
                    "Formulate the optimal PostgreSQL query with clean directional joins, "
                    "proper tenant_id isolation, and indexed equality predicates."
                )

            messages = [
                SystemMessage(content=ADVISOR_SYSTEM_PROMPT),
                HumanMessage(content=prompt_content),
            ]

            llm = cls.get_llm()
            response = llm.invoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)

            duration_ms = (time.time() - start_time) * 1000
            logger.info(f"Advisor SQL guidance completed in {duration_ms:.1f}ms")

            return {
                "advised": True,
                "guidance": content,
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log_error("StrategicAdvisorService.advise_sql", e)
            return {
                "advised": False,
                "error": str(e),
                "duration_ms": duration_ms,
            }

    @classmethod
    def advise_financial_strategy(
        cls,
        question: str,
        metrics_data: Any,
        tenant_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Generates executive CFO-grade financial analysis and strategic recommendations.
        """
        if not AgentConfig.ENABLE_ADVISOR_TOOL:
            return {
                "advised": False,
                "reason": "Advisor tool is disabled via ENABLE_ADVISOR_TOOL config.",
            }

        start_time = time.time()
        try:
            data_str = (
                json.dumps(metrics_data, indent=2, default=str)
                if isinstance(metrics_data, (dict, list))
                else str(metrics_data)
            )

            prompt_content = (
                f"### TASK: Executive Financial Strategy & Anomaly Synthesis\n\n"
                f"**User Business Question**: {question}\n\n"
                f"**Tenant / Company Context**: {tenant_context or 'Multi-entity default'}\n\n"
                f"**Aggregated Financial & Operational Data**:\n{data_str[:5000]}\n\n"
                f"Provide a CFO-level assessment: highlight critical risks, working capital velocity, "
                f"margin variances, and recommended strategic actions."
            )

            messages = [
                SystemMessage(content=ADVISOR_SYSTEM_PROMPT),
                HumanMessage(content=prompt_content),
            ]

            llm = cls.get_llm()
            response = llm.invoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)

            duration_ms = (time.time() - start_time) * 1000
            logger.info(f"Advisor financial strategy completed in {duration_ms:.1f}ms")

            return {
                "advised": True,
                "strategic_assessment": content,
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            log_error("StrategicAdvisorService.advise_financial_strategy", e)
            return {
                "advised": False,
                "error": str(e),
                "duration_ms": duration_ms,
            }


def consult_strategic_advisor_tool(
    problem_type: str,
    question: str,
    context_details: str = "",
) -> str:
    """
    LangChain tool wrapper allowing the executor model to consult the advisor model directly.
    
    :param problem_type: 'sql_planning', 'error_diagnosis', or 'financial_strategy'
    :param question: The user question or business dilemma to resolve
    :param context_details: Supporting metrics, schema context, or error message
    """
    if not AgentConfig.ENABLE_ADVISOR_TOOL:
        return "Advisor tool is currently disabled. Proceeding with standard execution."

    if problem_type in ("sql_planning", "error_diagnosis"):
        res = StrategicAdvisorService.advise_sql(
            question=question,
            schema_context=context_details,
            failed_sql=context_details if problem_type == "error_diagnosis" else None,
        )
        return res.get("guidance") or res.get("error", "No guidance generated.")
    else:
        res = StrategicAdvisorService.advise_financial_strategy(
            question=question,
            metrics_data=context_details,
        )
        return res.get("strategic_assessment") or res.get("error", "No assessment generated.")
