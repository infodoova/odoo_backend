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
            # Use only the first word to avoid substring false-positives
            # (e.g. "PLANNING" matching "PLAN", or a verbose response matching wrong protocol)
            first_token = raw_content.strip().split()[0].upper() if raw_content.strip() else ""

            # Priority: CONFIRM > REJECT > EXECUTE > PLAN (REJECT before PLAN so casual
            # messages aren't accidentally routed to the expensive planning path)
            if first_token == RoutingProtocol.CONFIRM:
                result = RoutingProtocol.CONFIRM
            elif first_token == RoutingProtocol.REJECT:
                result = RoutingProtocol.REJECT
            elif first_token == RoutingProtocol.PLAN:
                result = RoutingProtocol.PLAN
            elif first_token == RoutingProtocol.EXECUTE:
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
