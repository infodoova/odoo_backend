"""
Memory summarizer – condenses chat turns every N messages using Claude Haiku.
Keeps key figures, dates, and metrics while dropping filler.
"""

import anthropic
from .config import AgentConfig


class MemorySummarizer:
    """
    Progressively summarises conversation history.
    Keeps key figures, dates, and metrics; drops greetings and filler.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=AgentConfig.ANTHROPIC_API_KEY
        )

    def summarize(
        self,
        current_summary: str,
        recent_turns: list[dict],
    ) -> str:
        turns_text = ""

        for turn in recent_turns:
            user_msg = turn.get("user", "")
            assistant_msg = turn.get("assistant", "")
            turns_text += f"User: {user_msg}\n"
            turns_text += f"Assistant: {assistant_msg}\n\n"

        prompt = f"""
Progressively update the running summary of a financial conversation.

Rules:
- Preserve all specific figures, dates, and metrics mentioned
- Track which questions have been answered vs. are still pending
- Note any data sources queried or tools called
- Drop greetings, filler, and redundant restatements
- Keep the summary under 100 words; drop oldest resolved context if needed

EXAMPLE:
Current summary: User asked for January revenue; not yet answered.
New lines:
User: What was the margin?
Assistant: January revenue was $2.4M. Margin was 15%.
New summary: January revenue ($2.4M) and margin (15%) provided. No pending questions.

Current summary:
{current_summary}

New lines:
{turns_text}

Return ONLY the updated summary.
"""

        response = self.client.messages.create(
            model=AgentConfig.SUMMARIZER_MODEL,
            max_tokens=AgentConfig.MAX_SUMMARIZER_TOKENS,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        return response.content[0].text.strip()
