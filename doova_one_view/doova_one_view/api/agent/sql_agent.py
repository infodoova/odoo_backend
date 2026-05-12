"""
SQL Agent – converts natural language questions into safe PostgreSQL queries.
Uses a multi-pass workflow to generate, execute, and explain results.
"""

import os
import re
from typing import Any
import anthropic
from .db import run_query
from .config import AgentConfig


SQL_AGENT_SYSTEM_PROMPT = """
You are an expert SQL assistant for a business analytics system.

Your job is to:
1. Understand the user's business question.
2. Inspect the provided database schema.
3. Generate a syntactically correct PostgreSQL SELECT query.
4. Execute the query using the provided database tool.
5. Analyze the result.
6. Return a concise and accurate answer.

Rules:
- Only use the tables and columns that exist in the schema provided.
- Never make up table names or column names.
- If the question is ambiguous, ask for clarification before writing SQL.
- Always inspect the schema before generating a query.
- Use PostgreSQL syntax.
- Prefer readable SQL with clear aliases.
- Use LIMIT when the user does not specify how many rows they want.
- Avoid SELECT * unless explicitly necessary.
- For aggregations, explain the meaning of the result.
- Only generate read-only queries.
- If the user asks for INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, refuse politely.
- Never execute destructive queries.
- Do not expose secrets, API keys, passwords, or environment variables.
- Prefer CTEs for complex analysis.
- If multiple interpretations exist, explain your assumption.
- If SQL execution fails, analyze the error and retry once with a corrected query.

Return exactly:
1. SQL query
2. Short explanation
3. Final answer

Database dialect: PostgreSQL

Available schema:
{schema}

Conversation history:
{chat_history}

User question:
{input}
"""


BLOCKED_SQL_WORDS = [
    "insert", "update", "delete", "drop", "alter", "truncate", "create",
    "grant", "revoke", "merge", "copy", "replace", "vacuum", "analyze",
]


def get_database_schema() -> str:
    rows = run_query("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)

    grouped: dict[str, list[str]] = {}
    for row in rows:
        table = row["table_name"]
        column = row["column_name"]
        dtype = row["data_type"]
        grouped.setdefault(table, []).append(f"{column} {dtype}")

    lines = []
    for table, columns in grouped.items():
        lines.append(f"Table: {table}")
        for column in columns:
            lines.append(f"  - {column}")
        lines.append("")

    return "\n".join(lines)


def is_safe_read_only_sql(sql: str) -> bool:
    lowered = sql.lower().strip()
    if not lowered.startswith(("select", "with")):
        return False

    for word in BLOCKED_SQL_WORDS:
        if re.search(rf"\b{word}\b", lowered):
            return False

    return True


def extract_sql_from_text(text: str) -> str | None:
    def looks_like_sql(candidate: str) -> bool:
        lowered = candidate.lower().strip()
        if lowered.startswith("select"):
            return " from " in lowered or "\nfrom " in lowered
        if lowered.startswith("with"):
            return " as " in lowered and "select" in lowered and " from " in lowered
        return False

    code_block = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_block:
        candidate = code_block.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    generic_block = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if generic_block:
        candidate = generic_block.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    match = re.search(r"((?:with\s+.+?select\s+.+?)|(?:select\s+.+?))(?:;|$)", text, re.DOTALL | re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        return candidate if looks_like_sql(candidate) else None

    return None


def format_rows_for_prompt(rows: list[dict[str, Any]], limit: int = 30) -> str:
    if not rows:
        return "No rows returned."
    return str(rows[:limit])


def run_sql_agent(
    user_question: str,
    chat_history: str = "",
    tenant_id: str | None = None,
) -> dict[str, Any]:
    question_lower = (user_question or "").lower()

    for word in BLOCKED_SQL_WORDS:
        if re.search(rf"\b{word}\b", question_lower):
            return {
                "success": False,
                "message": "I can only run safe read-only SELECT queries.",
                "sql": None,
                "rows": [],
            }

    schema = get_database_schema()
    client = anthropic.Anthropic(api_key=AgentConfig.ANTHROPIC_API_KEY)

    tenant_note = ""
    if tenant_id:
        tenant_note = f"\nImportant tenant rule:\n- Current tenant_id is `{tenant_id}`.\n- If a table has a tenant_id column, always filter with tenant_id = '{tenant_id}'.\n"

    prompt = SQL_AGENT_SYSTEM_PROMPT.format(
        schema=schema + tenant_note,
        chat_history=chat_history or "No prior conversation.",
        input=user_question,
    )

    first_response = client.messages.create(
        model=AgentConfig.SQL_AGENT_MODEL,
        max_tokens=1200,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    first_text = first_response.content[0].text
    sql = extract_sql_from_text(first_text)

    if not sql:
        return {"success": False, "message": first_text, "sql": None, "rows": []}

    if not is_safe_read_only_sql(sql):
        return {"success": False, "message": "Unsafe query detected.", "sql": sql, "rows": []}

    try:
        rows = run_query(sql)
    except Exception as exc:
        return {"success": False, "message": f"SQL execution failed: {exc}", "sql": sql, "rows": []}

    result_preview = format_rows_for_prompt(rows)
    final_prompt = f"""
The user asked: {user_question}
The SQL query executed was: {sql}
The query returned: {result_preview}

Now provide:
1. SQL query
2. Short explanation
3. Final answer
Concise and business-friendly.
"""

    final_response = client.messages.create(
        model=AgentConfig.SQL_AGENT_MODEL,
        max_tokens=1200,
        temperature=0,
        messages=[{"role": "user", "content": final_prompt}],
    )

    return {
        "success": True,
        "message": final_response.content[0].text,
        "sql": sql,
        "rows": rows[:50],
    }
