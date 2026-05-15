# api/agent/router.py

import time
from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import ROUTER_PROMPT
from .logger import log_router_decision, log_error

class RouterNode:
    """
    High-performance intent classifier for the Doova OneView Agent.
    Routes incoming messages to specialized execution paths (EXECUTE vs PLAN).
    """
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.ROUTER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            temperature=0
        )
        self.prompt = ROUTER_PROMPT

    def classify(self, message: str) -> str:
        """
        Classifies user intent with high precision.
        """
        start = time.time()
        try:
            chain = self.prompt | self.llm
            response = chain.invoke({"message": message})
            decision = response.content.strip().upper()
            
            # Robust validation of LLM decision
            valid_protocols = {"REJECT", "EXECUTE", "PLAN"}
            result = "EXECUTE"
            for protocol in valid_protocols:
                if protocol in decision:
                    result = protocol
                    break

            duration = (time.time() - start) * 1000
            log_router_decision(message, result, duration)
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            log_error("RouterNode.classify", e)
            log_router_decision(message, "EXECUTE (fallback)", duration)
            return "EXECUTE"
