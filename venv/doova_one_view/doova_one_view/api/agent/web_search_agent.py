"""
Direct Anthropic Web Search Agent for Doova One View.
Executes user queries with Anthropic's native `web_search` server tool,
allowing Claude to autonomously perform live web searches while retaining
access to all internal ERP business database tools.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from .config import AgentConfig
from .langchain_tools import agent_tools
from .prompts import AGENT_SYSTEM_PROMPT, WEB_SEARCH_SYSTEM_PROMPT_ADDITION
from .logger import log_agent_start, log_agent_complete, log_error, log_tool_call, log_chain_event
from .utils import fix_currency_symbols, replace_tenant_ids_with_names

logger = logging.getLogger(__name__)


def convert_langchain_tool_to_anthropic(tool: Any) -> Dict[str, Any]:
    """
    Converts a LangChain BaseTool into the Anthropic tool JSON schema format.
    """
    input_schema: Dict[str, Any] = {"type": "object", "properties": {}}

    if hasattr(tool, "args_schema") and tool.args_schema is not None:
        schema_fn = getattr(tool.args_schema, "model_json_schema", None) or getattr(tool.args_schema, "schema", None)
        if callable(schema_fn):
            raw_schema = schema_fn()
            input_schema = {
                "type": "object",
                "properties": raw_schema.get("properties", {}),
            }
            if "required" in raw_schema:
                input_schema["required"] = raw_schema["required"]
            if "$defs" in raw_schema:
                input_schema["$defs"] = raw_schema["$defs"]
            if "definitions" in raw_schema:
                input_schema["definitions"] = raw_schema["definitions"]

    return {
        "name": tool.name,
        "description": tool.description or f"Tool for {tool.name}",
        "input_schema": input_schema,
    }


class WebSearchAgent:
    """
    Direct Anthropic API agent that includes the native server-side web_search tool.
    Executes a multi-turn tool-calling loop, resolving internal database tool calls
    and receiving server-side search results and citations.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.api_key = AgentConfig.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model_name or AgentConfig.FAST_MODEL
        self._tools_map = {t.name: t for t in agent_tools}
        self._anthropic_tools = self._build_tools_list()

    def _build_tools_list(self) -> List[Dict[str, Any]]:
        """
        Builds the complete tools array including all internal ERP tools
        plus the native Anthropic web_search and web_fetch server tools.
        """
        tools_list: List[Dict[str, Any]] = []

        # 1a. Native Anthropic web_search server tool definition
        search_version = getattr(AgentConfig, "WEB_SEARCH_TOOL_VERSION", "web_search_20260318")
        max_uses = getattr(AgentConfig, "WEB_SEARCH_MAX_USES", 5)

        web_search_tool: Dict[str, Any] = {
            "type": search_version,
            "name": "web_search",
            "max_uses": max_uses,
        }

        # user_location is optional in Anthropic API and only supports specific ISO codes.
        # If not in the supported list or omitted, global search without user_location is used.
        country = (getattr(AgentConfig, "WEB_SEARCH_DEFAULT_COUNTRY", "") or "").strip().upper()
        timezone = (getattr(AgentConfig, "WEB_SEARCH_DEFAULT_TIMEZONE", "") or "").strip()
        ANTHROPIC_SUPPORTED_COUNTRIES = {"US", "GB", "CA", "AU", "FR", "DE", "ES", "IT", "JP"}
        if country and country in ANTHROPIC_SUPPORTED_COUNTRIES:
            web_search_tool["user_location"] = {
                "type": "approximate",
                "country": country,
                "timezone": timezone or "UTC",
            }

        tools_list.append(web_search_tool)

        # 1b. Native Anthropic web_fetch server tool (reads full page content)
        if getattr(AgentConfig, "ENABLE_WEB_FETCH", True):
            fetch_version = getattr(AgentConfig, "WEB_FETCH_TOOL_VERSION", "web_fetch_20260318")
            fetch_max_uses = getattr(AgentConfig, "WEB_FETCH_MAX_USES", 5)
            web_fetch_tool: Dict[str, Any] = {
                "type": fetch_version,
                "name": "web_fetch",
                "max_uses": fetch_max_uses,
            }
            tools_list.append(web_fetch_tool)

        # 2. Convert all existing internal business database tools
        for tool in agent_tools:
            try:
                # Do not re-add advisor tool if disabled
                if tool.name == "consult_strategic_advisor" and not getattr(AgentConfig, "ENABLE_ADVISOR_TOOL", False):
                    continue
                converted = convert_langchain_tool_to_anthropic(tool)
                tools_list.append(converted)
            except Exception as e:
                logger.warning(f"Failed to convert tool {getattr(tool, 'name', 'unknown')} to Anthropic schema: {e}")

        return tools_list

    def _build_system_prompt(
        self,
        tenant_id: str,
        tenant_ids: List[str],
        company_ids: List[int],
        currency: str,
        memory_summary: str = "",
    ) -> str:
        """
        Renders the comprehensive system prompt combining ERP instructions
        with real-time web search guidance.
        """
        # Format base prompt template
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # AGENT_SYSTEM_PROMPT is a ChatPromptTemplate with placeholders
        base_prompt_text = (
            f"Current Date: {today_str}\n"
            f"Primary Tenant ID: {tenant_id}\n"
            f"Active Tenant IDs: {tenant_ids}\n"
            f"Active Company IDs: {company_ids}\n"
            f"Reporting Currency: {currency}\n"
        )
        if memory_summary:
            base_prompt_text += f"\nSession Context & Prior Summary:\n{memory_summary}\n"

        # Combine with web search operational guidelines
        full_system_prompt = (
            f"{base_prompt_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"AGENT CORE INSTRUCTIONS\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You are the senior AI business advisor for Doova One View.\n"
            f"You have access to 40+ internal business tools, native real-time Web Search, and Web Fetch (deep URL reading).\n\n"
            f"LANGUAGE & LOCALIZATION DIRECTIVE (STRICT):\n"
            f"- You MUST reply strictly in the exact same language as the user's latest query (e.g. if the user query is in English, you MUST reply 100% in English; if in Arabic, reply in Arabic; if in French, reply in French).\n"
            f"- NEVER maintain or reply in an older session language if the user switched languages in their latest query.\n\n"
            f"{WEB_SEARCH_SYSTEM_PROMPT_ADDITION}"
        )
        return full_system_prompt

    def _execute_client_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        Executes an internal Python database tool and returns the JSON/string result.
        """
        start_time = time.time()
        tool = self._tools_map.get(tool_name)
        if not tool:
            return json.dumps({"error": f"Tool '{tool_name}' not found."})

        try:
            log_chain_event("ACTION", f"WebSearchAgent executing internal tool: {tool_name}")
            result = tool.invoke(tool_input)
            duration = (time.time() - start_time) * 1000
            log_tool_call(tool_name, tool_input, result, duration)

            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)
            return str(result)
        except Exception as exc:
            duration = (time.time() - start_time) * 1000
            logger.error(f"Error executing internal tool {tool_name}: {exc}")
            log_tool_call(tool_name, tool_input, {"error": str(exc)}, duration)
            return json.dumps({"error": str(exc)})

    def run(
        self,
        message: str,
        tenant_id: Optional[str] = None,
        company_id: Optional[int] = None,
        company_ids: Optional[List[int]] = None,
        tenant_ids: Optional[List[str]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        memory_summary: str = "",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Executes the query using the Anthropic API with web_search enabled.
        Returns: (final_answer_text, citations_list)
        """
        start_time = time.time()

        from .query_context import normalize_company_ids, normalize_tenant_ids
        from .utils import get_tenant_currency

        resolved_tenant_ids = normalize_tenant_ids(tenant_id=tenant_id, tenant_ids=tenant_ids)
        primary_tenant_id = resolved_tenant_ids[0] if resolved_tenant_ids else (tenant_id or "default")

        resolved_company_ids = normalize_company_ids(company_id=company_id, companies=company_ids)
        resolved_company_id = resolved_company_ids[0] if len(resolved_company_ids) == 1 else None

        currency = get_tenant_currency(primary_tenant_id, resolved_company_id)

        log_agent_start(
            message,
            primary_tenant_id,
            resolved_company_ids or resolved_company_id,
            len(chat_history or []),
        )

        system_prompt = self._build_system_prompt(
            tenant_id=primary_tenant_id,
            tenant_ids=resolved_tenant_ids,
            company_ids=resolved_company_ids,
            currency=currency,
            memory_summary=memory_summary,
        )

        # Build message history for Anthropic API
        messages: List[Dict[str, Any]] = []
        for msg in (chat_history or []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Append current user prompt
        messages.append({"role": "user", "content": message})

        max_iterations = 12
        iteration = 0
        all_citations: List[Dict[str, Any]] = []
        final_text = ""

        try:
            while iteration < max_iterations:
                iteration += 1

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=AgentConfig.MAX_FAST_TOKENS,
                    system=system_prompt,
                    messages=messages,
                    tools=self._anthropic_tools,
                )

                stop_reason = response.stop_reason
                logger.info(f"WebSearchAgent turn {iteration} completed with stop_reason: {stop_reason}")

                # Extract any citations from content blocks
                for block in response.content:
                    # Citations on text blocks
                    if getattr(block, "type", None) == "text" and hasattr(block, "citations") and block.citations:
                        for cit in block.citations:
                            cit_dict = {
                                "url": getattr(cit, "url", ""),
                                "title": getattr(cit, "title", ""),
                                "cited_text": getattr(cit, "cited_text", ""),
                            }
                            if cit_dict["url"] and cit_dict not in all_citations:
                                all_citations.append(cit_dict)

                # Check if Claude is finished
                if stop_reason == "end_turn":
                    # Collect all text blocks into final answer
                    text_parts = [
                        block.text for block in response.content
                        if getattr(block, "type", None) == "text" and hasattr(block, "text")
                    ]
                    final_text = "\n\n".join(text_parts).strip()
                    break

                # Handle pause_turn (Anthropic continuing long server-side search)
                elif stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": response.content})
                    continue

                # Handle tool_use (Claude calling internal database tools or web search)
                elif stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})

                    tool_results_content: List[Dict[str, Any]] = []
                    for block in response.content:
                        if getattr(block, "type", None) == "tool_use":
                            tool_name = block.name
                            tool_input = block.input
                            tool_use_id = block.id

                            # Execute internal tool
                            tool_output_str = self._execute_client_tool(tool_name, tool_input)
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": tool_output_str,
                            })

                    if tool_results_content:
                        messages.append({"role": "user", "content": tool_results_content})
                    else:
                        # Anthropic executed a server tool internally (e.g. web_search), continue turn
                        continue
                else:
                    # Unrecognized stop reason — extract any available text
                    text_parts = [
                        block.text for block in response.content
                        if getattr(block, "type", None) == "text" and hasattr(block, "text")
                    ]
                    final_text = "\n\n".join(text_parts).strip()
                    break

            if not final_text:
                final_text = "I completed the search and analysis but did not generate a final textual response."

            # Post-process currency and tenant placeholders
            final_text = fix_currency_symbols(final_text, currency)
            final_text = replace_tenant_ids_with_names(final_text, resolved_tenant_ids)

            duration = (time.time() - start_time) * 1000
            log_agent_complete(final_text, duration)

            return final_text, all_citations

        except Exception as exc:
            duration = (time.time() - start_time) * 1000
            log_error("WebSearchAgent.run", exc)
            logger.exception(f"WebSearchAgent execution failed: {exc}")
            raise
