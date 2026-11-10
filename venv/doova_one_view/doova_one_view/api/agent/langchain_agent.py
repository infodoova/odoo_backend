# api/agent/langchain_agent.py

import time
from datetime import datetime
from langchain_anthropic import ChatAnthropic
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from .config import AgentConfig
from .langchain_tools import agent_tools
from .summarizer import SummarizerNode
from .prompts import AGENT_SYSTEM_PROMPT
from .table_sink import start_table_sink, end_table_sink, expand_table_markers
from .logger import logger, log_agent_start, log_agent_complete, log_summarization, log_error, log_tool_call, log_chain_event

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.outputs import LLMResult


# ── Thinking-safe LLM wrapper ────────────────────────────────────────
# When thinking mode is active, the AgentExecutor's multi-step loop sends
# prior AI messages (including thinking blocks) back to the API. If a
# thinking block is missing the required "thinking" text field (common
# with streaming/adaptive mode), the API returns a 400 error.
# This subclass intercepts every call and strips incomplete thinking
# blocks before they ever reach the API, making multi-turn tool-calling
# fully compatible with adaptive thinking.

class ThinkingSafeChatAnthropic(ChatAnthropic):
    """ChatAnthropic subclass that strips malformed thinking blocks
    from messages before sending them to the Anthropic API.
    This prevents 'thinking.thinking: Field required' errors in
    multi-turn agent loops where thinking blocks from prior turns
    are missing the required text content."""

    @staticmethod
    def _clean_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
        """Remove incomplete thinking blocks from message content."""
        cleaned = []
        for msg in messages:
            if isinstance(msg, AIMessage) and isinstance(msg.content, list):
                new_content = []
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        # Only keep thinking blocks that have the required "thinking" text field
                        if block.get("thinking") and block.get("signature"):
                            new_content.append(block)
                        # Skip incomplete/malformed thinking blocks entirely
                    elif isinstance(block, dict) and block.get("type") == "redacted_thinking":
                        # Keep redacted thinking blocks only if they have "data"
                        if block.get("data"):
                            new_content.append(block)
                    else:
                        new_content.append(block)
                # If we stripped everything and only had thinking blocks, use empty string
                if not new_content:
                    new_content = ""
                if hasattr(msg, "model_copy"):
                    msg = msg.model_copy(update={"content": new_content})
                else:
                    msg = msg.copy(update={"content": new_content})
            cleaned.append(msg)
        return cleaned

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        messages = self._clean_messages(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        messages = self._clean_messages(messages)
        yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)


# ── Agent Callback Handler & Pricing Model ───────────────────────────

ANTHROPIC_PRICING_PER_1M = {
    # Active Project Models (AgentConfig & .env)
    "claude-sonnet-5-5":            {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-haiku-5-5":  {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00},
    "claude-opus-5-5":              {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},

    # Standard Model Identifiers & Aliases
    "claude-3-7-sonnet-20250219": {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-3-7-sonnet":          {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-3-5-sonnet":          {"input": 3.00, "cache_write": 3.75, "cache_read": 0.30, "output": 15.00},
    "claude-3-5-haiku-20241022":  {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00},
    "claude-3-5-haiku":           {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00},
    "claude-haiku-4-5":           {"input": 0.80, "cache_write": 1.00, "cache_read": 0.08, "output": 4.00},
    "claude-3-opus-20240229":     {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-3-opus":              {"input": 15.00, "cache_write": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-3-haiku-20240307":    {"input": 0.25, "cache_write": 0.30, "cache_read": 0.03, "output": 1.25},
    "claude-3-haiku":             {"input": 0.25, "cache_write": 0.30, "cache_read": 0.03, "output": 1.25},
}
DEFAULT_MODEL_PRICING = ANTHROPIC_PRICING_PER_1M["claude-sonnet-5-5"]


class AgentCallbackHandler(BaseCallbackHandler):
    """Custom handler to bridge LangChain events with our specialized logger
    and track exact token usage and Anthropic API spend."""
    def __init__(self, model_name: str = "claude-sonnet-5-5"):
        super().__init__()
        self.default_model_name = model_name
        self._seen_run_ids = set()
        self.reset()

    def reset(self):
        """Reset token accumulators for a new agent turn."""
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_write_tokens = 0
        self.detected_models = set()
        self.llm_call_count = 0
        self._seen_run_ids.clear()

    def on_llm_end(self, response: LLMResult, *, run_id=None, **kwargs):
        """Extract exact token accounting and prompt-cache statistics from Anthropic LLM result."""
        try:
            if run_id:
                if run_id in self._seen_run_ids:
                    return
                self._seen_run_ids.add(run_id)

            self.llm_call_count += 1
            extracted = False

            # 1. Inspect AIMessage from generations
            if hasattr(response, "generations") and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        msg = getattr(gen, "message", None)
                        if not msg:
                            continue

                        resp_meta = getattr(msg, "response_metadata", {}) or {}
                        raw_usage = resp_meta.get("usage")
                        model = resp_meta.get("model")
                        if model:
                            self.detected_models.add(model)

                        if isinstance(raw_usage, dict):
                            inp = raw_usage.get("input_tokens", 0) or 0
                            out = raw_usage.get("output_tokens", 0) or 0
                            cread = raw_usage.get("cache_read_input_tokens", 0) or 0
                            cwrite = raw_usage.get("cache_creation_input_tokens", 0) or 0

                            self.total_input_tokens += inp
                            self.total_output_tokens += out
                            self.total_cache_read_tokens += cread
                            self.total_cache_write_tokens += cwrite
                            extracted = True
                            continue

                        # Fallback to LangChain usage_metadata
                        usage_meta = getattr(msg, "usage_metadata", None)
                        if isinstance(usage_meta, dict):
                            inp = usage_meta.get("input_tokens", 0) or 0
                            out = usage_meta.get("output_tokens", 0) or 0
                            details = usage_meta.get("input_token_details", {}) or {}
                            cread = details.get("cache_read", 0) or 0
                            cwrite = details.get("cache_creation", 0) or 0
                            base_inp = max(0, inp - cread - cwrite)

                            self.total_input_tokens += base_inp
                            self.total_output_tokens += out
                            self.total_cache_read_tokens += cread
                            self.total_cache_write_tokens += cwrite
                            extracted = True

            # 2. Fallback: Inspect response.llm_output
            if not extracted and hasattr(response, "llm_output") and isinstance(response.llm_output, dict):
                token_usage = response.llm_output.get("token_usage") or response.llm_output.get("usage")
                if isinstance(token_usage, dict):
                    inp = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
                    out = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
                    cread = token_usage.get("cache_read_input_tokens") or 0
                    cwrite = token_usage.get("cache_creation_input_tokens") or 0

                    self.total_input_tokens += inp
                    self.total_output_tokens += out
                    self.total_cache_read_tokens += cread
                    self.total_cache_write_tokens += cwrite
                    extracted = True

            log_chain_event(
                "TOKEN_USAGE",
                f"LLM Call #{self.llm_call_count} | Base In: {self.total_input_tokens} | "
                f"Out: {self.total_output_tokens} | Cache Read: {self.total_cache_read_tokens} | "
                f"Cache Write: {self.total_cache_write_tokens}"
            )
        except Exception as e:
            log_error("AgentCallbackHandler.on_llm_end", e)

    def get_turn_token_usage(self) -> dict:
        """Calculate exact token counts and financial costs for this turn."""
        model_name = next(iter(self.detected_models)) if self.detected_models else self.default_model_name
        model_key = (model_name or "").lower().strip()

        # Direct dictionary match
        if model_key in ANTHROPIC_PRICING_PER_1M:
            rates = ANTHROPIC_PRICING_PER_1M[model_key]
        elif "haiku" in model_key:
            if any(k in model_key for k in ("4-5", "4.5", "3-5", "3.5")):
                rates = ANTHROPIC_PRICING_PER_1M["claude-haiku-5-5"]
            elif "3" in model_key:
                rates = ANTHROPIC_PRICING_PER_1M["claude-3-haiku"]
            else:
                rates = ANTHROPIC_PRICING_PER_1M["claude-haiku-5-5"]
        elif "opus" in model_key:
            rates = ANTHROPIC_PRICING_PER_1M["claude-opus-5-5"]
        elif "sonnet" in model_key:
            rates = ANTHROPIC_PRICING_PER_1M["claude-sonnet-5-5"]
        else:
            rates = DEFAULT_MODEL_PRICING

        cost_input = (self.total_input_tokens * rates["input"]) / 1_000_000.0
        cost_cache_write = (self.total_cache_write_tokens * rates["cache_write"]) / 1_000_000.0
        cost_cache_read = (self.total_cache_read_tokens * rates["cache_read"]) / 1_000_000.0
        cost_output = (self.total_output_tokens * rates["output"]) / 1_000_000.0

        total_cost_usd = cost_input + cost_cache_write + cost_cache_read + cost_output
        cache_savings_usd = max(0.0, ((self.total_cache_read_tokens * (rates["input"] - rates["cache_read"])) / 1_000_000.0))

        total_tokens = (
            self.total_input_tokens +
            self.total_cache_read_tokens +
            self.total_cache_write_tokens +
            self.total_output_tokens
        )

        return {
            "model": model_name,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_read_tokens": self.total_cache_read_tokens,
            "cache_write_tokens": self.total_cache_write_tokens,
            "total_tokens": total_tokens,
            "cost_usd": round(total_cost_usd, 6),
            "cache_savings_usd": round(cache_savings_usd, 6),
            "llm_calls": self.llm_call_count,
            "is_exact": True
        }

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tool_start_time = time.time()
        self.current_tool = serialized.get("name")
        self.current_params = input_str

    def on_tool_end(self, output, **kwargs):
        duration = (time.time() - self.tool_start_time) * 1000
        log_tool_call(self.current_tool, {"input": self.current_params}, output, duration)

    def on_agent_action(self, action, **kwargs):
        log_chain_event("ACTION", f"Agent selecting tool: {action.tool}")


def _patch_runnable_agent_early_stopping():
    """
    Ensure RunnableAgent in LangChain supports early_stopping_method='generate'.
    When max iterations is reached with early_stopping_method='generate',
    performs a final forward pass over intermediate steps to synthesize the
    response rather than raising ValueError or forcing a static error message.
    """
    from langchain_classic.agents.agent import RunnableAgent
    from langchain_core.agents import AgentAction, AgentFinish

    _orig_return_stopped_response = RunnableAgent.return_stopped_response

    def return_stopped_response(self, early_stopping_method: str, intermediate_steps: list, **kwargs):
        if early_stopping_method == "generate":
            try:
                # Forward pass over gathered intermediate steps to generate final answer
                decision = self.plan(intermediate_steps, **kwargs)
                if isinstance(decision, AgentFinish):
                    return decision
                if isinstance(decision, list):
                    for d in decision:
                        if isinstance(d, AgentFinish):
                            return d
                # If model emitted text inside an AgentAction log, extract and return it
                log = getattr(decision, "log", "") if not isinstance(decision, list) else (decision[0].log if decision else "")
                if log and ("```json" in log or len(log.strip()) > 20):
                    return AgentFinish({"output": log}, log)
            except Exception as e:
                logger.warning(f"early_stopping_method='generate' forward pass encountered: {e}")
            return AgentFinish({"output": "Agent stopped due to max iterations."}, "")
        return _orig_return_stopped_response(self, early_stopping_method, intermediate_steps, **kwargs)

    RunnableAgent.return_stopped_response = return_stopped_response

_patch_runnable_agent_early_stopping()


# ── Main Agent ────────────────────────────────────────────────────────

class DoovaLangChainAgent:
    def __init__(
        self,
        model_name=None,
        max_tokens=None,
        enable_thinking=None,
        tools=None,
        max_iterations=None,
        early_stopping_method=None,
    ):
        self.summarizer = SummarizerNode()
        self.model_name = model_name or AgentConfig.FAST_MODEL
        self.callback_handler = AgentCallbackHandler(model_name=self.model_name)
        self.last_token_usage = None

        llm_kwargs = {
            "model": self.model_name,
            "anthropic_api_key": AgentConfig.ANTHROPIC_API_KEY,
            "max_tokens": max_tokens or AgentConfig.MAX_FAST_TOKENS,
            "callbacks": [self.callback_handler],
            "model_kwargs": {
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31,pdfs-2024-09-25"}
            }
        }
        
        use_thinking = enable_thinking if enable_thinking is not None else getattr(AgentConfig, "ENABLE_THINKING", True)
        if use_thinking:
            llm_kwargs["thinking"] = {"type": "adaptive"}
        else:
            llm_kwargs["thinking"] = {"type": "disabled"}

        self.llm = ThinkingSafeChatAnthropic(**llm_kwargs)
        
        active_tools = tools if tools is not None else agent_tools
        self.prompt = AGENT_SYSTEM_PROMPT
        self.agent = create_tool_calling_agent(self.llm, active_tools, self.prompt)
        stopping_method = early_stopping_method or "force"
        self.executor = AgentExecutor(
            agent=self.agent, 
            tools=active_tools, 
            verbose=True,
            max_iterations=max_iterations or 25,
            early_stopping_method=stopping_method,
            handle_parsing_errors=True,
            callbacks=[self.callback_handler]
        )

    def get_last_token_usage(self) -> dict:
        """Retrieve the exact token usage and financial cost of the most recent turn."""
        return getattr(self, "last_token_usage", None) or self.callback_handler.get_turn_token_usage()

    def _format_history(self, history: list) -> list:
        # Canned rejection apologies — skip these turns from context (they carry no business info
        # and, if recent, would displace substantive entity references like company names)
        _REJECTION_STARTERS = (
            "عذراً، يمكنني المساعدة فقط",
            "I'm sorry, I can only assist with business",
            "Lo siento, solo puedo responder",
            "Désolé, je ne peux répondre",
        )

        formatted = []
        for msg in history:
            content = msg.get("content", "")
            payload = msg.get("payload") or {}
            attachments = msg.get("attachments") or payload.get("attachments") or []

            # Skip rejection turns — they carry no useful business context
            if payload.get("is_rejected"):
                continue
            if msg.get("role") == "assistant" and isinstance(content, str):
                if any(content.strip().startswith(s) for s in _REJECTION_STARTERS):
                    continue

            if msg.get("role") == "user":
                if attachments:
                    from .attachment_processor import process_attachments
                    claude_blocks, extracted_text = process_attachments(attachments, persist=False)
                    
                    base_text = (content or "").strip()
                    if extracted_text:
                        base_text = (base_text + "\n\n" + extracted_text).strip()
                        
                    if claude_blocks:
                        user_blocks = []
                        if base_text:
                            user_blocks.append({"type": "text", "text": base_text})
                        clean_blocks = [{k: v for k, v in b.items() if k not in ("_audit_meta", "cache_control")} for b in claude_blocks]
                        user_blocks.extend(clean_blocks)
                        formatted.append(HumanMessage(content=user_blocks))
                    elif base_text:
                        formatted.append(HumanMessage(content=base_text))
                    else:
                        formatted.append(HumanMessage(content=content or "[Attached Document]"))
                else:
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif isinstance(block, str):
                                text_parts.append(block)
                        content = " ".join(text_parts).strip()
                    formatted.append(HumanMessage(content=content or ""))
            elif msg.get("role") == "assistant":
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = " ".join(text_parts).strip()
                formatted.append(AIMessage(content=content or ""))
        return formatted

    def run(
        self,
        message: str,
        tenant_ids: list[str] | None = None,
        company_ids: list[int] | None = None,
        chat_history: list = None,
        memory_summary: str = "",
        on_summary=None,
        attachments: list = None,
        session_id: str | None = None,
        is_voice: bool = False,
        language: str | None = None,
        tenant_id: str | None = None,
        usage_out: dict | None = None,
    ) -> str:
        """Run one turn. If usage_out is given it is filled with this run's exact token usage
        (the shared agent object can serve overlapping requests, so callers should not read
        usage back from it)."""
        start = time.time()
        sink_token = None
        self.callback_handler.reset()
        formatted_history = self._format_history(chat_history or [])
        
        from .query_context import normalize_company_ids, normalize_tenant_ids
        if tenant_id and not tenant_ids:
            tenant_ids = [tenant_id]
        resolved_tenant_ids = normalize_tenant_ids(tenant_ids)
        primary_tenant_id = resolved_tenant_ids[0] if resolved_tenant_ids else (tenant_id or "default")

        resolved_company_ids = normalize_company_ids(company_ids)
        resolved_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None

        # Ensure we always pass the list representation for logging
        log_agent_start(message, primary_tenant_id, resolved_company_ids or resolved_company_id, len(formatted_history))
        
        active_history = formatted_history
        new_summary_generated = None
        
        # Process attachments if present
        claude_blocks = []
        extracted_text = ""
        if attachments:
            from .attachment_processor import process_attachments
            claude_blocks, extracted_text = process_attachments(
                attachments,
                tenant_ids=resolved_tenant_ids,
                company_ids=resolved_company_ids,
                session_id=session_id
            )

        # Extract any multimodal messages (with image/document blocks) so they are NEVER lost during summarization
        multimodal_history_messages = [
            msg for msg in formatted_history
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list) and any(
                isinstance(b, dict) and b.get("type") in ("image", "document") for b in msg.content
            )
        ]

        # Determine total completed prior messages in session to govern rolling summarization
        prior_count = len(formatted_history)
        if session_id:
            try:
                from odoo_app.models.agent import ChatMessage
                total_db_msgs = ChatMessage.objects.filter(
                    session_id=session_id, role__in=["user", "assistant"]
                ).count()
                # If current user message was already saved to DB in routes.py, completed count is total - 1
                if total_db_msgs > 1:
                    prior_count = total_db_msgs - 1
            except Exception as e:
                log_error("DoovaLangChainAgent.check_prior_count", e)

        # Rolling summarization triggers:
        # 1. At SUMMARIZE_EVERY_N (4 messages) when no summary exists yet
        # 2. Every SUMMARIZE_EVERY_N messages (at 4, 8, 12, 16...) to incrementally incorporate new turns
        every_n = AgentConfig.SUMMARIZE_EVERY_N
        should_summarize = (
            (prior_count >= every_n and not memory_summary)
            or (prior_count >= every_n and (prior_count % every_n == 0))
        )

        if should_summarize and len(formatted_history) >= 2:
            sum_start = time.time()
            # If rolling from an existing summary, summarize the new turns since last cycle
            to_summarize = formatted_history[-every_n:] if len(formatted_history) >= every_n else formatted_history
            raw_summary = self.summarizer.summarize(to_summarize, existing_summary=memory_summary)
            new_summary_generated = raw_summary
            sum_duration = (time.time() - sum_start) * 1000
            log_summarization(len(to_summarize), len(raw_summary), sum_duration)
            if raw_summary:
                memory_summary = raw_summary

        # Format memory_summary for executor prompt and enforce passing ONLY the last 2 messages
        if memory_summary:
            clean_summary = memory_summary
            if "PRIOR SESSION FACTS" in clean_summary:
                parts = clean_summary.split("):\n", 1)
                if len(parts) == 2:
                    clean_summary = parts[1].strip()
            memory_summary = (
                "PRIOR SESSION FACTS (use this to avoid redundant tool calls and to contextualize "
                "follow-up questions — do not re-fetch data that is already summarized here):\n"
                + clean_summary
            )
            # Pass the last 6 messages (3 turns) along with the summary.
            # Using 6 instead of 2 preserves entity context (e.g. company names) that the
            # LLM needs for pronoun resolution in follow-up questions.
            active_history = list(formatted_history[-6:]) if len(formatted_history) >= 2 else formatted_history


        # Guarantee that all multimodal image/document blocks remain present in active_history
        for mm_msg in multimodal_history_messages:
            if mm_msg not in active_history:
                active_history.insert(0, mm_msg)

        try:
            from .utils import get_tenant_currency, fix_currency_symbols, replace_tenant_ids_with_names
            currency = get_tenant_currency(primary_tenant_id, resolved_company_id)

            # Build user input payload (multimodal blocks if images/docs attached)
            base_prompt = (message or "").strip()
            if extracted_text:
                base_prompt = (base_prompt + "\n\n" + extracted_text).strip()

            if claude_blocks:
                # Strip internal-only fields (_audit_meta) before sending to Anthropic API.
                # _audit_meta is for internal ETL/test use; the API rejects unknown fields.
                api_blocks = [{k: v for k, v in b.items() if k != "_audit_meta"} for b in claude_blocks]
                user_input = [
                    {"type": "text", "text": base_prompt or "Please analyze the attached document(s) / image(s)."}
                ] + api_blocks
            else:
                user_input = base_prompt or "[No prompt provided]"

            if isinstance(user_input, list):
                input_payload = [HumanMessage(content=user_input)]
            else:
                input_payload = [HumanMessage(content=str(user_input))]

            if is_voice:
                voice_instruction = (
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "VOICE CALL MODE ACTIVE:\n"
                    "- Respond in 2-3 short, natural, conversational spoken sentences suitable for Text-to-Speech.\n"
                    "- STRICTLY NO markdown tables, bullet points, asterisks, hash headers, or lists.\n"
                    "- MANDATORY LANGUAGE: You MUST formulate 100% of your response in the active voice language specified below, regardless of what language the user spoke in.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                # Resolve language code as the absolute master key for voice calls
                import re as _re
                has_arabic = bool(_re.search(r'[\u0600-\u06FF]', message or ""))
                has_latin = bool(_re.search(r'[a-zA-Z]', message or ""))
                lang_str = (language or "").strip().lower().replace("_", "-")

                if has_arabic:
                    target_language_label = (
                        "ARABIC (ar / ar-SA) — DYNAMIC VOICE MATCH:\n"
                        "The user spoke in Arabic (العربية).\n"
                        "You MUST formulate 100% of your response in clean, natural, modern standard Arabic (العربية الفصحى المعاصرة بدون تشكيل مفرط) so ElevenLabs Neural Voice (Rachel) speaks with natural native cadence and flawless pronunciation."
                    )
                elif has_latin and (not lang_str or lang_str in ("auto", "none", "null", "") or lang_str.startswith("en")):
                    target_language_label = (
                        "ENGLISH (en / en-US) — DYNAMIC VOICE MATCH:\n"
                        "The user spoke in English.\n"
                        "You MUST formulate 100% of your response in English."
                    )
                elif lang_str.startswith("fr") or "french" in lang_str:
                    target_language_label = "FRENCH (fr / fr-FR) — DYNAMIC VOICE MATCH:\nYou MUST formulate 100% of your response in French."
                elif lang_str.startswith("es") or "span" in lang_str:
                    target_language_label = "SPANISH (es / es-ES) — DYNAMIC VOICE MATCH:\nYou MUST formulate 100% of your response in Spanish."
                elif has_latin:
                    target_language_label = "ENGLISH (en / en-US) — DYNAMIC VOICE MATCH:\nYou MUST formulate 100% of your response in English."
                else:
                    target_language_label = "Dynamic Language Matching (Match User Input)"
            else:
                # Regular AI Chat Mode: Natural language matching ("as it was")
                voice_instruction = ""
                import re as _re
                if _re.search(r'[\u0600-\u06FF]', message or ""):
                    target_language_label = "ARABIC (ar) — STRICT REQUIREMENT: The user's latest query is in Arabic. You MUST reply 100% in clean, natural, modern Arabic (العربية الفصحى المعاصرة السلسة بدون تشكيل مفرط) for beautiful frontend reading and natural ElevenLabs speech synthesis."
                elif _re.search(r'[a-zA-Z]', message or ""):
                    target_language_label = "ENGLISH (en) — STRICT REQUIREMENT: The user's latest query is in English (e.g. 'let\\'s continue', 'go on', 'what about...'). You MUST switch and reply 100% in ENGLISH. NEVER continue in Arabic or any previous conversation language when the current user utterance is in English."
                else:
                    target_language_label = "English (Default)"

            self.callback_handler.reset()
            # Tables built by tools are kept here and swapped into the reply at the end,
            # so the model never has to retype rows.
            sink_token = start_table_sink()
            # A fresh counter per run: this agent object is shared by every request.
            run_handler = AgentCallbackHandler(model_name=self.model_name)
            response = self.executor.invoke({
                "input": input_payload,
                "tenant_id": primary_tenant_id,
                "tenant_ids": resolved_tenant_ids,
                "company_ids": resolved_company_ids,
                "currency": currency,
                "chat_history": active_history,
                "memory_summary": memory_summary,
                "today": datetime.now().strftime("%Y-%m-%d"),
                "language": target_language_label,
                "is_voice": "TRUE" if is_voice else "FALSE",
                "voice_instruction": voice_instruction
            }, config={"callbacks": [run_handler]})
            raw_output = response["output"]
            run_usage = run_handler.get_turn_token_usage()
            self.last_token_usage = run_usage
            if usage_out is not None:
                usage_out.update(run_usage)

            # Normalize: handle cases where LLM returns a list of content blocks
            if isinstance(raw_output, list):
                output = " ".join(
                    block.get("text", "") for block in raw_output
                    if isinstance(block, dict) and block.get("type") == "text"
                ).strip()
            else:
                output = str(raw_output)

            output = fix_currency_symbols(output, currency)
            output = replace_tenant_ids_with_names(output, resolved_tenant_ids)

            # Ensure PDF links are properly formatted as clickable markdown
            from .routes import format_pdf_links_as_clickable_markdown
            output, pdf_url = format_pdf_links_as_clickable_markdown(output)
            if pdf_url or "Download" in output:
                from .utils import strip_json_chart_from_text
                output = strip_json_chart_from_text(output)

            output = expand_table_markers(output, is_voice=is_voice)
            end_table_sink(sink_token)
            sink_token = None

            duration = (time.time() - start) * 1000
            log_agent_complete(output, duration)
            
            # Persist the newly generated summary via caller callback
            if new_summary_generated and on_summary:
                on_summary(new_summary_generated)
            
            return output
        except Exception as e:
            if sink_token is not None:
                end_table_sink(sink_token)
            duration = (time.time() - start) * 1000
            log_error("DoovaLangChainAgent.run", e)
            raise
