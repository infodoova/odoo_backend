"""
Fast path node – handles simple queries and direct tool lookups using Claude Sonnet.
"""

import anthropic
import json

from .config import AgentConfig
from .tools import run_fast_tool


class FastPathNode:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=AgentConfig.ANTHROPIC_API_KEY
        )

    def run(
        self,
        message: str,
        tenant_id: str,
        company_id: int | None = None,
        companies: list[int] | None = None,
        context: str | None = None,
        memory_summary: str = "",
    ) -> str:
        """
        Fast answer path.
        Used for simple questions or direct answers.

        Tool Integration v1:
        - If a matching business tool exists, run it first.
        - Then ask Claude Sonnet to format the tool result clearly.
        """

        tool_result = run_fast_tool(
            message=message,
            tenant_id=tenant_id,
            company_id=company_id,
            companies=companies,
            context=context,
        )

        # ─────────────────────────────
        # CASE 1: TOOL WAS USED
        # ─────────────────────────────
        if tool_result is not None:
            prompt = f"""
You are a fast financial assistant for Doova OneView.

The user asked a simple business-data question.
A tool was executed and returned structured data.

Your job:
- Format the tool result into a clear answer
- Be concise
- Mention if the data is mock/test data
- Do NOT invent numbers
- Use only the tool result below

Tenant ID: {tenant_id}
Company ID: {company_id}
Companies: {companies}
Context: {context}

Conversation summary:
{memory_summary}

User question:
{message}

Tool result:
{json.dumps(tool_result, indent=2)}
"""

            response = self.client.messages.create(
                model=AgentConfig.FAST_MODEL,
                max_tokens=AgentConfig.MAX_FAST_TOKENS,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return response.content[0].text

        # ─────────────────────────────
        # CASE 2: NO TOOL MATCHED
        # ─────────────────────────────
        prompt = f"""
You are a fast financial assistant for Doova OneView.

Answer the user directly and clearly.

Rules:
- Be concise
- Do not overthink simple questions
- If the question mentions business data, answer in business language
- If exact data is not available yet, explain what endpoint/tool would be needed

Tenant ID: {tenant_id}
Company ID: {company_id}
Companies: {companies}
Context: {context}

Conversation summary:
{memory_summary}

User question:
{message}
"""

        response = self.client.messages.create(
            model=AgentConfig.FAST_MODEL,
            max_tokens=AgentConfig.MAX_FAST_TOKENS,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return response.content[0].text
