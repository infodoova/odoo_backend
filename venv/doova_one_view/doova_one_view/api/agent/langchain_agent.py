# api/agent/langchain_agent.py

import time
from datetime import datetime
from langchain_anthropic import ChatAnthropic
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from .config import AgentConfig
from .langchain_tools import agent_tools
from .summarizer import SummarizerNode
from .prompts import AGENT_SYSTEM_PROMPT
from .logger import log_agent_start, log_agent_complete, log_summarization, log_error, log_tool_call, log_chain_event

from langchain_core.callbacks import BaseCallbackHandler

class AgentCallbackHandler(BaseCallbackHandler):
    """Custom handler to bridge LangChain events with our specialized logger."""
    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tool_start_time = time.time()
        self.current_tool = serialized.get("name")
        self.current_params = input_str

    def on_tool_end(self, output, **kwargs):
        duration = (time.time() - self.tool_start_time) * 1000
        log_tool_call(self.current_tool, {"input": self.current_params}, output, duration)

    def on_agent_action(self, action, **kwargs):
        log_chain_event("ACTION", f"Agent selecting tool: {action.tool}")

class DoovaLangChainAgent:
    def __init__(self, model_name=None, max_tokens=None):
        self.summarizer = SummarizerNode()
        self.llm = ChatAnthropic(
            model=model_name or AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            max_tokens=max_tokens or AgentConfig.MAX_FAST_TOKENS,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
        )
        
        self.prompt = AGENT_SYSTEM_PROMPT
        self.agent = create_tool_calling_agent(self.llm, agent_tools, self.prompt)
        self.executor = AgentExecutor(
            agent=self.agent, 
            tools=agent_tools, 
            verbose=True,
            callbacks=[AgentCallbackHandler()]
        )

    def _format_history(self, history: list) -> list:
        from langchain_core.messages import HumanMessage, AIMessage
        formatted = []
        for msg in history:
            if msg.get("role") == "user":
                formatted.append(HumanMessage(content=msg.get("content", "")))
            elif msg.get("role") == "assistant":
                formatted.append(AIMessage(content=msg.get("content", "")))
        return formatted

    def run(self, message: str, tenant_id: str, company_id: int = None, chat_history: list = None, memory_summary: str = "", on_summary=None) -> str:
        start = time.time()
        formatted_history = self._format_history(chat_history or [])
        
        log_agent_start(message, tenant_id, company_id, len(formatted_history))
        
        active_history = formatted_history
        new_summary_generated = None
        
        # Use pre-loaded DB summary if available; otherwise generate if history is long
        if memory_summary:
            # Wrap the raw summary in structured context so the model knows how to use it
            memory_summary = (
                "PRIOR SESSION FACTS (use this to avoid redundant tool calls and to contextualize "
                "follow-up questions — do not re-fetch data that is already summarized here):\n"
                + memory_summary
            )
            # DB has a persisted summary — use it with only the recent messages
            active_history = formatted_history  # already limited to recent N in routes.py
        elif len(formatted_history) >= AgentConfig.SUMMARIZE_EVERY_N:
            # No persisted summary yet — generate and signal caller to save it
            sum_start = time.time()
            to_summarize = formatted_history[:-2]
            active_history = formatted_history[-2:]
            memory_summary = self.summarizer.summarize(to_summarize)
            new_summary_generated = memory_summary
            sum_duration = (time.time() - sum_start) * 1000
            log_summarization(len(to_summarize), len(memory_summary), sum_duration)

        try:
            from .utils import get_tenant_currency, fix_currency_symbols

            resolved_company_id = company_id
            if resolved_company_id is None:
                resolved_company_id = "All Companies"

            currency = get_tenant_currency(tenant_id, resolved_company_id)

            response = self.executor.invoke({
                "input": message,
                "tenant_id": tenant_id,
                "company_id": resolved_company_id,
                "currency": currency,
                "chat_history": active_history,
                "memory_summary": memory_summary,
                "today": datetime.now().strftime("%Y-%m-%d")
            })
            raw_output = response["output"]

            # Normalize: handle cases where LLM returns a list of content blocks
            if isinstance(raw_output, list):
                output = " ".join(
                    block.get("text", "") for block in raw_output
                    if isinstance(block, dict) and block.get("type") == "text"
                ).strip()
            else:
                output = str(raw_output)

            output = fix_currency_symbols(output, currency)

            duration = (time.time() - start) * 1000
            log_agent_complete(output, duration)
            
            # Persist the newly generated summary via caller callback
            if new_summary_generated and on_summary:
                on_summary(new_summary_generated)
            
            return output
        except Exception as e:
            duration = (time.time() - start) * 1000
            log_error("DoovaLangChainAgent.run", e)
            raise
