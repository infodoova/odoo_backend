# api/agent/langchain_agent.py

import time
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
    def __init__(self, model_name=None):
        self.summarizer = SummarizerNode()
        self.llm = ChatAnthropic(
            model=model_name or AgentConfig.FAST_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            temperature=0
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

    def run(self, message: str, tenant_id: str, company_id: int = None, chat_history: list = None) -> str:
        start = time.time()
        formatted_history = self._format_history(chat_history or [])
        
        log_agent_start(message, tenant_id, company_id, len(formatted_history))
        
        memory_summary = ""
        active_history = formatted_history
        
        # Check if we need to summarize
        if len(formatted_history) >= AgentConfig.SUMMARIZE_EVERY_N:
            sum_start = time.time()
            to_summarize = formatted_history[:-2]
            active_history = formatted_history[-2:]
            memory_summary = self.summarizer.summarize(to_summarize)
            sum_duration = (time.time() - sum_start) * 1000
            log_summarization(len(to_summarize), len(memory_summary), sum_duration)

        try:
            response = self.executor.invoke({
                "input": message,
                "tenant_id": tenant_id,
                "company_id": company_id,
                "chat_history": active_history,
                "memory_summary": memory_summary
            })
            output = response["output"]
            duration = (time.time() - start) * 1000
            log_agent_complete(output, duration)
            return output
        except Exception as e:
            duration = (time.time() - start) * 1000
            log_error("DoovaLangChainAgent.run", e)
            raise
