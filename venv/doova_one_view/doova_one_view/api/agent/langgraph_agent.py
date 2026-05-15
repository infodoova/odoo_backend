# api/agent/langgraph_agent.py

from typing import Annotated, TypedDict, List, Union
from langgraph.graph import StateGraph, END
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from .config import AgentConfig
from .langchain_tools import agent_tools
from .langchain_agent import DoovaLangChainAgent

class AgentState(TypedDict):
    messages: List[BaseMessage]
    tenant_id: str
    company_id: int
    plan: dict
    status: str  # 'IDLE', 'PLANNING', 'AWAITING_APPROVAL', 'EXECUTING', 'DONE'
    next_node: str

class DoovaLangGraphAgent:
    def __init__(self):
        self.fast_agent = DoovaLangChainAgent()
        self.llm = ChatAnthropic(
            model=AgentConfig.REASONING_MODEL, 
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
        )
        
        workflow = StateGraph(AgentState)
        
        workflow.add_node("router", self.router_node)
        workflow.add_node("fast_path", self.fast_path_node)
        workflow.add_node("planner", self.planner_node)
        
        workflow.set_entry_point("router")
        
        workflow.add_conditional_edges(
            "router",
            lambda x: x["next_node"],
            {
                "fast_path": "fast_path",
                "planner": "planner",
                "end": END
            }
        )
        
        workflow.add_edge("fast_path", END)
        workflow.add_edge("planner", END) # In this simple version, we stop after planning to wait for user
        
        self.app = workflow.compile()

    def router_node(self, state: AgentState):
        msg = state["messages"][-1].content.lower()
        # Simple routing logic
        if any(word in msg for word in ["analyze", "plan", "why", "compare", "strategy"]):
            return {"next_node": "planner"}
        return {"next_node": "fast_path"}

    def fast_path_node(self, state: AgentState):
        response = self.fast_agent.run(
            message=state["messages"][-1].content,
            tenant_id=state["tenant_id"],
            company_id=state["company_id"]
        )
        return {"messages": [AIMessage(content=response)], "status": "DONE"}

    def planner_node(self, state: AgentState):
        # Implementation of Phase 1: Planning
        # For now, just a placeholder that mimics the ReasoningNode behavior
        prompt = f"Create a financial execution plan for: {state['messages'][-1].content}"
        # ... (Call LLM to get JSON plan)
        return {"status": "AWAITING_APPROVAL", "plan": {"id": "123", "steps": ["Check sales"]}}

    def run(self, message: str, tenant_id: str, company_id: int = None):
        inputs = {
            "messages": [HumanMessage(content=message)],
            "tenant_id": tenant_id,
            "company_id": company_id,
            "status": "IDLE"
        }
        final_state = self.app.invoke(inputs)
        return final_state["messages"][-1].content
