# api/agent/fast_path.py

from .langchain_agent import DoovaLangChainAgent
from .config import AgentConfig

class FastPathNode:
    def __init__(
        self,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
        tools: list | None = None,
        max_iterations: int | None = None,
        early_stopping_method: str | None = None,
    ):
        use_thinking = enable_thinking if enable_thinking is not None else getattr(AgentConfig, "ENABLE_THINKING", True)
        self.lc_agent = DoovaLangChainAgent(
            max_tokens=max_tokens or AgentConfig.MAX_REPORT_TOKENS,
            enable_thinking=use_thinking,
            tools=tools,
            max_iterations=max_iterations,
            early_stopping_method=early_stopping_method,
        )

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
        language: str | None = None
    ) -> str:
        return self.lc_agent.run(
            message=message,
            tenant_ids=tenant_ids,
            company_ids=company_ids,
            chat_history=chat_history,
            memory_summary=memory_summary,
            on_summary=on_summary,
            attachments=attachments,
            session_id=session_id,
            is_voice=is_voice,
            language=language
        )

    def get_last_token_usage(self) -> dict:
        """Retrieve the exact token usage and financial cost of the most recent turn."""
        return self.lc_agent.get_last_token_usage()
