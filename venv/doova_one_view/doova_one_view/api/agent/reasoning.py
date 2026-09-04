# api/agent/reasoning.py

from .langchain_agent import DoovaLangChainAgent
from .config import AgentConfig
import json
from .prompts import PLAN_JSON_GENERATION_PROMPT
from .langchain_tools import agent_tools

class ReasoningNode:
    def __init__(self):
        self.agent = DoovaLangChainAgent(model_name=AgentConfig.REASONING_MODEL, max_tokens=AgentConfig.MAX_REASONING_TOKENS)

    def create_plan(
        self,
        message: str,
        tenant_id: str | None = None,
        company_id: int | None = None,
        memory_summary: str = "",
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None
    ) -> dict:
        # Use the centralized JSON planning prompt with memory context
        context = f"PREVIOUS CONTEXT: {memory_summary}\n" if memory_summary else ""
        full_message = f"{context}USER REQUEST: {message}"
        tools_list_str = ", ".join([t.name for t in agent_tools])
        prompt = PLAN_JSON_GENERATION_PROMPT.format(message=full_message, tools_list=tools_list_str)
        response = self.agent.llm.invoke(prompt)
        try:
            return json.loads(response.content)
        except:
            return {"plan_id": "auto", "status": "PENDING_APPROVAL", "question_summary": message}

    def execute_plan(
        self,
        message: str,
        plan: dict,
        tenant_id: str | None = None,
        company_id: int | None = None,
        memory_summary: str = "",
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        language: str | None = None
    ) -> str:
        # Use the LangChain Agent Executor to fulfill the plan
        return self.agent.run(
            message=f"Execute this plan: {json.dumps(plan)}. Original question: {message}",
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
            tenant_ids=tenant_ids,
            memory_summary=memory_summary,
            language=language
        )

    def run(
        self,
        message: str,
        tenant_id: str | None = None,
        company_id: int | None = None,
        memory_summary: str = "",
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        language: str | None = None
    ) -> str:
        return self.agent.run(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            company_ids=company_ids,
            tenant_ids=tenant_ids,
            memory_summary=memory_summary,
            language=language
        )
