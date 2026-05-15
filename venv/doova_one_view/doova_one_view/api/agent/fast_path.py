# api/agent/fast_path.py

from .langchain_agent import DoovaLangChainAgent

class FastPathNode:
    def __init__(self):
        self.lc_agent = DoovaLangChainAgent()

    def run(
        self,
        message: str,
        tenant_id: str,
        company_id: int | None = None,
        chat_history: list = None,
        memory_summary: str = "",
        on_summary=None
    ) -> str:
        return self.lc_agent.run(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            chat_history=chat_history,
            memory_summary=memory_summary,
            on_summary=on_summary
        )
