# api/agent/router.py

import time
from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import ROUTER_PROMPT, RoutingProtocol
from .logger import log_router_decision, log_error, logger

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
            raw_content = response.content.strip()
            logger.debug(f"ROUTER RAW RESPONSE: {raw_content}")
            decision = raw_content.upper()
            
            # Priority-based validation (EXECUTE > PLAN > REJECT)
            result = RoutingProtocol.EXECUTE # Default fallback
            if RoutingProtocol.PLAN in decision:
                result = RoutingProtocol.PLAN
            elif RoutingProtocol.EXECUTE in decision:
                result = RoutingProtocol.EXECUTE
            elif RoutingProtocol.REJECT in decision:
                result = RoutingProtocol.REJECT
            else:
                result = RoutingProtocol.EXECUTE

            duration = (time.time() - start) * 1000
            log_router_decision(message, result.value, duration)
            return result.value
        except Exception as e:
            duration = (time.time() - start) * 1000
            log_error("RouterNode.classify", e)
            log_router_decision(message, "EXECUTE (fallback)", duration)
            return "EXECUTE"
