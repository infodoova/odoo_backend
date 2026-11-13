# api/agent/summarizer.py

from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .llm_params import thinking_kwargs
from .prompts import SUMMARIZER_PROMPT, ROLLING_SUMMARIZER_PROMPT

from .utils import llm_text


class SummarizerNode:
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.SUMMARIZER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            **thinking_kwargs(AgentConfig.SUMMARIZER_MODEL),
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
        )
        self.prompt = SUMMARIZER_PROMPT
        self.rolling_prompt = ROLLING_SUMMARIZER_PROMPT

    @staticmethod
    def _format_msg_for_summary(msg) -> str:
        content = getattr(msg, "content", None)
        if not content:
            return ""
        role = getattr(msg, "type", type(msg).__name__)
        if isinstance(content, str):
            return f"{role}: {content}"
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "text":
                        text_val = block.get("text", "").strip()
                        if text_val:
                            parts.append(text_val)
                    elif btype == "image":
                        parts.append("[Attached Image]")
                    elif btype == "document":
                        title = block.get("title") or "Document"
                        parts.append(f"[Attached Document: {title}]")
                    else:
                        parts.append(f"[Attachment: {btype}]")
                elif isinstance(block, str):
                    parts.append(block)
            return f"{role}: {' '.join(parts).strip()}" if parts else ""
        return f"{role}: {str(content)}"

    def summarize(self, history: list, existing_summary: str = "") -> str:
        if not history and not existing_summary:
            return ""
        
        # Convert history objects to string for the prompt without raw base64 payloads
        history_str = "\n".join([
            formatted_line
            for msg in history
            for formatted_line in [self._format_msg_for_summary(msg)]
            if formatted_line
        ])
        
        # Clean any prior context wrapper from existing_summary before sending to prompt
        clean_existing = (existing_summary or "").strip()
        if "PRIOR SESSION FACTS" in clean_existing:
            parts = clean_existing.split("):\n", 1)
            if len(parts) == 2:
                clean_existing = parts[1].strip()

        if clean_existing and history_str:
            chain = self.rolling_prompt | self.llm
            response = chain.invoke({
                "existing_summary": clean_existing,
                "history": history_str
            })
            return llm_text(response.content).strip()
        elif history_str:
            chain = self.prompt | self.llm
            response = chain.invoke({"history": history_str})
            return llm_text(response.content).strip()
        else:
            return clean_existing