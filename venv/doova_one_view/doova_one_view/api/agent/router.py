# api/agent/router.py

import time
from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import ROUTER_PROMPT, RoutingProtocol
from .logger import log_router_decision, log_error, logger

class RouterNode:
    """
    High-performance intent classifier for the Nexus Agent.
    Routes incoming messages to specialized execution paths (EXECUTE vs PLAN).
    """
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.ROUTER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
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
            # Extract clean tokens from response
            raw_upper = raw_content.upper()
            tokens = [t.strip(".,:;!\"'") for t in raw_upper.split()]

            if RoutingProtocol.CONFIRM.value in tokens or "CONFIRM" in tokens:
                result = RoutingProtocol.CONFIRM
            elif RoutingProtocol.PLAN.value in tokens or "PLAN" in tokens:
                result = RoutingProtocol.PLAN
            elif RoutingProtocol.REJECT.value in tokens or "REJECT" in tokens:
                result = RoutingProtocol.REJECT
            elif RoutingProtocol.EXECUTE.value in tokens or "EXECUTE" in tokens:
                result = RoutingProtocol.EXECUTE
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
