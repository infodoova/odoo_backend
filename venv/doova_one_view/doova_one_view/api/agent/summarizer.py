# api/agent/summarizer.py

from langchain_anthropic import ChatAnthropic
from .config import AgentConfig
from .prompts import SUMMARIZER_PROMPT

class SummarizerNode:
    def __init__(self):
        self.llm = ChatAnthropic(
            model=AgentConfig.SUMMARIZER_MODEL,
            anthropic_api_key=AgentConfig.ANTHROPIC_API_KEY
        )
        self.prompt = SUMMARIZER_PROMPT

    def summarize(self, history: list) -> str:
        if not history:
            return ""
        
        # Convert history objects to string for the prompt
        history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in history])
        
        chain = self.prompt | self.llm
        response = chain.invoke({"history": history_str})
        return response.content.strip()