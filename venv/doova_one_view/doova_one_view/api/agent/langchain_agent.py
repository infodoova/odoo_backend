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
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage


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


# ── Agent Callback Handler ────────────────────────────────────────────

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


# ── Main Agent ────────────────────────────────────────────────────────

class DoovaLangChainAgent:
    def __init__(self, model_name=None, max_tokens=None):
        self.summarizer = SummarizerNode()
        llm_kwargs = {
            "model": model_name or AgentConfig.FAST_MODEL,
            "anthropic_api_key": AgentConfig.ANTHROPIC_API_KEY,
            "max_tokens": max_tokens or AgentConfig.MAX_FAST_TOKENS,
            "model_kwargs": {
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31,pdfs-2024-09-25"}
            }
        }
        
        if getattr(AgentConfig, "ENABLE_THINKING", False):
            llm_kwargs["thinking"] = {"type": "adaptive"}

        self.llm = ThinkingSafeChatAnthropic(**llm_kwargs)
        
        self.prompt = AGENT_SYSTEM_PROMPT
        self.agent = create_tool_calling_agent(self.llm, agent_tools, self.prompt)
        self.executor = AgentExecutor(
            agent=self.agent, 
            tools=agent_tools, 
            verbose=True,
            max_iterations=15,
            early_stopping_method="force",
            handle_parsing_errors=True,
            callbacks=[AgentCallbackHandler()]
        )

    def _format_history(self, history: list) -> list:
        formatted = []
        for msg in history:
            content = msg.get("content", "")
            payload = msg.get("payload") or {}
            attachments = msg.get("attachments") or payload.get("attachments") or []
            
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
                        user_blocks.extend(claude_blocks)
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
        tenant_id: str | None = None,
        company_id: int | None = None,
        company_ids: list[int] | None = None,
        tenant_ids: list[str] | None = None,
        chat_history: list = None,
        memory_summary: str = "",
        on_summary=None,
        attachments: list = None,
        session_id: str | None = None,
        is_voice: bool = False,
        language: str | None = None
    ) -> str:
        start = time.time()
        formatted_history = self._format_history(chat_history or [])
        
        # Ensure we always pass the list representation for logging
        log_agent_start(message, tenant_id or (tenant_ids[0] if tenant_ids else "default"), company_ids or company_id, len(formatted_history))
        
        active_history = formatted_history
        new_summary_generated = None
        
        # Process attachments if present
        claude_blocks = []
        extracted_text = ""
        if attachments:
            from .attachment_processor import process_attachments
            claude_blocks, extracted_text = process_attachments(
                attachments,
                tenant_id=tenant_id,
                company_id=company_id or (company_ids[0] if company_ids else None),
                session_id=session_id
            )

        # Extract any multimodal messages (with image/document blocks) so they are NEVER lost during summarization
        multimodal_history_messages = [
            msg for msg in formatted_history
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list) and any(
                isinstance(b, dict) and b.get("type") in ("image", "document") for b in msg.content
            )
        ]

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
            to_summarize = formatted_history[:-4]
            active_history = list(formatted_history[-4:])
            memory_summary = self.summarizer.summarize(to_summarize)
            new_summary_generated = memory_summary
            sum_duration = (time.time() - sum_start) * 1000
            log_summarization(len(to_summarize), len(memory_summary), sum_duration)

        # Guarantee that all multimodal image/document blocks remain present in active_history
        for mm_msg in multimodal_history_messages:
            if mm_msg not in active_history:
                active_history.insert(0, mm_msg)

        try:
            from .utils import get_tenant_currency, fix_currency_symbols, replace_tenant_ids_with_names
            from .query_context import normalize_company_ids, normalize_tenant_ids
            
            resolved_tenant_ids = normalize_tenant_ids(tenant_id=tenant_id, tenant_ids=tenant_ids)
            primary_tenant_id = resolved_tenant_ids[0] if resolved_tenant_ids else (tenant_id or "default")

            resolved_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
            resolved_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None

            currency = get_tenant_currency(primary_tenant_id, resolved_company_id)

            # Build user input payload (multimodal blocks if images/docs attached)
            base_prompt = (message or "").strip()
            if extracted_text:
                base_prompt = (base_prompt + "\n\n" + extracted_text).strip()

            if claude_blocks:
                user_input = [
                    {"type": "text", "text": base_prompt or "Please analyze the attached document(s) / image(s)."}
                ] + claude_blocks
            else:
                user_input = base_prompt or "[No prompt provided]"

            if isinstance(user_input, list):
                input_payload = [HumanMessage(content=user_input)]
            else:
                input_payload = [HumanMessage(content=str(user_input))]

            voice_instruction = ""
            if is_voice:
                voice_instruction = (
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "VOICE MODE ACTIVE:\n"
                    "- Respond in 2-3 short, natural, conversational spoken sentences suitable for Text-to-Speech.\n"
                    "- STRICTLY NO markdown tables, bullet points, asterisks, hash headers, or lists.\n"
                    "- STRICTLY match the language of the user's spoken utterance."
                )

            # Resolve language code as the absolute master key
            lang_str = (language or "").strip()
            if lang_str and lang_str.lower() not in ("auto", "none", "null"):
                code_lower = lang_str.lower()
                if code_lower.startswith("en"):
                    target_language_label = "ENGLISH (en) — MASTER OVERRIDE: The system language code is set to English. You MUST reply 100% in English, even if the user utterance contains Arabic words or if chat history contains Arabic."
                elif code_lower.startswith("ar"):
                    target_language_label = "ARABIC (ar) — MASTER OVERRIDE: The system language code is set to Arabic. You MUST reply 100% in Arabic (العربية)."
                elif code_lower.startswith("fr"):
                    target_language_label = "FRENCH (fr) — MASTER OVERRIDE: The system language code is set to French. You MUST reply 100% in French (Français)."
                elif code_lower.startswith("es"):
                    target_language_label = "SPANISH (es) — MASTER OVERRIDE: The system language code is set to Spanish. You MUST reply 100% in Spanish (Español)."
                else:
                    target_language_label = f"{lang_str} — MASTER OVERRIDE: You MUST reply 100% in {lang_str}."
            else:
                import re as _re
                if _re.search(r'[\u0600-\u06FF]', message or ""):
                    target_language_label = "ARABIC (ar) — STRICT REQUIREMENT: The user's latest query is in Arabic. You MUST reply 100% in Arabic (العربية)."
                elif _re.search(r'[a-zA-Z]', message or ""):
                    target_language_label = "ENGLISH (en) — STRICT REQUIREMENT: The user's latest query is in English (e.g. 'let\\'s continue', 'go on', 'what about...'). You MUST switch and reply 100% in ENGLISH. NEVER continue in Arabic or any previous conversation language when the current user utterance is in English."
                else:
                    target_language_label = "English (Default)"

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
            output = replace_tenant_ids_with_names(output, resolved_tenant_ids)

            # Ensure PDF links are properly formatted as clickable markdown
            from .routes import format_pdf_links_as_clickable_markdown
            output, pdf_url = format_pdf_links_as_clickable_markdown(output)
            if pdf_url or "Download" in output:
                from .utils import strip_json_chart_from_text
                output = strip_json_chart_from_text(output)

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
