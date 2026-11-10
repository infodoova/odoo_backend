# api/agent/reasoning.py

from .langchain_agent import DoovaLangChainAgent, AgentCallbackHandler
from .config import AgentConfig
import json
from .prompts import PLAN_JSON_GENERATION_PROMPT
from .langchain_tools import agent_tools
from .logger import logger
from .utils import _extract_json_block

PLAN_GENERATION_TRIES = 2
_JSON_ONLY_REMINDER = (
    "\n\nYour previous reply could not be read as the required JSON plan. "
    "Reply again with ONLY the raw JSON object: no markdown fences, no commentary."
)


class PlanGenerationError(Exception):
    """The model did not return a usable plan (a JSON object with a non-empty `steps` list)."""


def _reply_text(content) -> str:
    """Return the text of a model reply, whether it is a string or a list of content blocks
    (adaptive thinking returns a list that can also hold thinking blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p)
    return str(content or "")


def _is_usable_plan(plan) -> bool:
    return (
        isinstance(plan, dict)
        and isinstance(plan.get("steps"), list)
        and len(plan["steps"]) > 0
    )


class ReasoningNode:
    def __init__(self):
        self.agent = DoovaLangChainAgent(model_name=AgentConfig.REASONING_MODEL, max_tokens=AgentConfig.MAX_REASONING_TOKENS)

    def create_plan(
        self,
        message: str,
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        memory_summary: str = "",
        usage_out: dict | None = None,
    ) -> dict:
        """Ask the model for a JSON plan. Retries once with a stricter instruction and
        raises PlanGenerationError instead of returning an empty plan the user could approve.
        If usage_out is given it is filled with the token usage of this call only."""
        # Use the centralized JSON planning prompt with memory context
        context = f"PREVIOUS CONTEXT: {memory_summary}\n" if memory_summary else ""
        full_message = f"{context}USER REQUEST: {message}"
        tools_list_str = ", ".join([t.name for t in agent_tools])
        base_prompt = PLAN_JSON_GENERATION_PROMPT.format(message=full_message, tools_list=tools_list_str)

        # A fresh counter per call: this node is shared by every request.
        handler = AgentCallbackHandler(model_name=getattr(self.agent, "model_name", None))
        try:
            for attempt in range(1, PLAN_GENERATION_TRIES + 1):
                prompt = base_prompt if attempt == 1 else base_prompt + _JSON_ONLY_REMINDER
                response = self.agent.llm.invoke(prompt, config={"callbacks": [handler]})
                metadata = getattr(response, "response_metadata", None)
                if isinstance(metadata, dict) and metadata.get("stop_reason") == "max_tokens":
                    # A cut-off reply can still be "repaired" into valid JSON that silently
                    # drops the later steps, so never accept it.
                    logger.warning(f"PLAN GENERATION | reply {attempt} was cut off at the token limit")
                    continue
                plan = _extract_json_block(_reply_text(response.content))
                if _is_usable_plan(plan):
                    return plan
                logger.warning(
                    f"PLAN GENERATION | reply {attempt}/{PLAN_GENERATION_TRIES} had no usable plan "
                    f"(request: {message[:80]!r})"
                )
        finally:
            # Token usage covers every model call made while planning, including the retry.
            usage = handler.get_turn_token_usage()
            self.agent.last_token_usage = usage
            if usage_out is not None:
                usage_out.update(usage)
        raise PlanGenerationError(
            f"The model returned no usable plan after {PLAN_GENERATION_TRIES} tries."
        )

    def execute_plan(
        self,
        message: str,
        plan: dict,
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        memory_summary: str = "",
        language: str | None = None,
        usage_out: dict | None = None,
    ) -> str:
        # Use the LangChain Agent Executor to fulfill the plan
        return self.agent.run(
            message=f"Execute this plan: {json.dumps(plan)}. Original question: {message}",
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            memory_summary=memory_summary,
            language=language,
            usage_out=usage_out,
        )

    def run(
        self,
        message: str,
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        memory_summary: str = "",
        language: str | None = None
    ) -> str:
        return self.agent.run(
            message=message,
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            memory_summary=memory_summary,
            language=language
        )

    def get_last_token_usage(self) -> dict:
        """Retrieve the exact token usage and financial cost of the most recent turn."""
        return self.agent.get_last_token_usage()
