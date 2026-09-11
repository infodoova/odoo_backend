# api/agent/summarizer.py

from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import SUMMARIZER_PROMPT, ROLLING_SUMMARIZER_PROMPT

class SummarizerNode:
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.SUMMARIZER_MODEL,
            temperature=0.0,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY,
            model_kwargs={
                "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"}
            }
        )
        self.prompt = SUMMARIZER_PROMPT
        self.rolling_prompt = ROLLING_SUMMARIZER_PROMPT

    def summarize(self, history: list, existing_summary: str = "") -> str:
        if not history and not existing_summary:
            return ""
        
        # Convert history objects to string for the prompt
        history_str = "\n".join([
            f"{getattr(msg, 'type', type(msg).__name__)}: {msg.content}"
            for msg in history
            if getattr(msg, "content", None)
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
            return response.content.strip()
        elif history_str:
            chain = self.prompt | self.llm
            response = chain.invoke({"history": history_str})
            return response.content.strip()
        else:
            return clean_existing