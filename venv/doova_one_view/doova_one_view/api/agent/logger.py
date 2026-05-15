# api/agent/logger.py

import logging
import time
import json
from functools import wraps

# Configure the agent logger
logger = logging.getLogger("doova.agent")
logger.setLevel(logging.DEBUG)

# Console handler with structured formatting
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    "\n🔹 [%(asctime)s] %(levelname)s | %(name)s\n"
    "   %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def log_router_decision(message: str, decision: str, duration_ms: float):
    """Log the router's intent classification decision."""
    logger.info(
        f"🧭 ROUTER DECISION\n"
        f"   Input: \"{message[:80]}{'...' if len(message) > 80 else ''}\"\n"
        f"   Decision: {decision}\n"
        f"   Duration: {duration_ms:.0f}ms"
    )


def log_tool_call(tool_name: str, params: dict, result: dict | str, duration_ms: float):
    """Log a tool execution with its parameters and result summary."""
    result_preview = str(result)[:200] if result else "None"
    logger.info(
        f"🔧 TOOL EXECUTED\n"
        f"   Tool: {tool_name}\n"
        f"   Params: {json.dumps(params, default=str)[:150]}\n"
        f"   Result: {result_preview}\n"
        f"   Duration: {duration_ms:.0f}ms"
    )


def log_agent_start(message: str, tenant_id: str, company_id: int | None, history_length: int):
    """Log when the agent begins processing a request."""
    logger.info(
        f"🧠 AGENT START\n"
        f"   Message: \"{message[:100]}{'...' if len(message) > 100 else ''}\"\n"
        f"   Tenant: {tenant_id}\n"
        f"   Company: {company_id or 'ALL'}\n"
        f"   History: {history_length} messages"
    )


def log_agent_complete(message: str, duration_ms: float, tools_used: int = 0):
    """Log when the agent completes a request."""
    logger.info(
        f"✅ AGENT COMPLETE\n"
        f"   Response: \"{message[:120]}{'...' if len(message) > 120 else ''}\"\n"
        f"   Tools Used: {tools_used}\n"
        f"   Total Duration: {duration_ms:.0f}ms"
    )


def log_summarization(history_length: int, summary_length: int, duration_ms: float):
    """Log a conversation summarization event."""
    logger.info(
        f"📝 SUMMARIZATION\n"
        f"   Input Messages: {history_length}\n"
        f"   Summary Length: {summary_length} chars\n"
        f"   Duration: {duration_ms:.0f}ms"
    )


def log_session_event(event: str, session_id: str, details: str = ""):
    """Log session management events."""
    logger.info(
        f"💬 SESSION {event.upper()}\n"
        f"   Session: {session_id}\n"
        f"   Details: {details}"
    )


def log_error(context: str, error: Exception):
    """Log errors with full context."""
    logger.error(
        f"❌ ERROR in {context}\n"
        f"   Type: {type(error).__name__}\n"
        f"   Message: {str(error)}"
    )


def timed(func):
    """Decorator to time any function and log its duration."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = (time.time() - start) * 1000
            logger.debug(f"⏱️ {func.__name__} completed in {duration:.0f}ms")
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            log_error(func.__name__, e)
            raise
    return wrapper
