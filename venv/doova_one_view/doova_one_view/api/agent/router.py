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

    def classify(self, message: str, chat_history: list | None = None) -> str:
        """
        Classifies user intent with high precision, using conversation history for context.
        """
        start = time.time()
        try:
            history_str = "None (New Conversation)"
            if chat_history and isinstance(chat_history, list) and len(chat_history) > 0:
                recent = chat_history[-6:]  # Last ~3 turns
                history_lines = []
                for m in recent:
                    if isinstance(m, dict):
                        role = "User" if m.get("role") == "user" else "Assistant"
                        content = str(m.get("content") or "").strip()
                        if content:
                            history_lines.append(f"{role}: {content[:150]}")
                if history_lines:
                    history_str = "\n".join(history_lines)

            chain = self.prompt | self.llm
            response = chain.invoke({"message": message, "chat_history": history_str})
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
