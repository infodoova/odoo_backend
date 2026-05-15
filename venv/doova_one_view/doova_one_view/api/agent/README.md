# Doova Finance Brain: AI Agent Module

This directory contains the core intelligence of the Doova platform. It implements a multi-model, tool-calling agent designed to act as a Virtual CFO for Odoo-based businesses.

## 🏗 Architecture Overview

The agent system is built on a "Router-Executor" pattern:

1. **Router (`router.py`)**: Classifies user intent (Classify/Execute/Plan) to determine the best processing path.
2. **Fast Path Executor (`fast_path.py` -> `langchain_agent.py`)**: A high-performance tool-calling agent using Anthropic's Claude models. It has access to 28+ specialized financial tools.
3. **Reasoning Path (`langgraph_agent.py`)**: (Experimental) A more complex iterative reasoning engine built with LangGraph for multi-step strategic analysis.
4. **SQL Engine (`sql_agent.py`)**: A fallback mechanism that can generate and execute PostgreSQL queries when specialized tools don't cover the user's specific request.

## 🧠 Core Components

- **`langchain_agent.py`**: The primary implementation of the `DoovaLangChainAgent`. Handles tool orchestration, history formatting, and response normalization.
- **`prompts.py`**: Contains the sophisticated system prompts, including the "Finance Brain" persona, temporal context rules, and Anthropic Prompt Caching markers.
- **`session_manager.py`**: Manages chat history persistence and memory summarization using Django models (`ChatSession`, `ChatMessage`).
- **`summarizer.py`**: Implements periodic history summarization to maintain a lean context window while preserving long-term memory.
- **`logger.py`**: A specialized, Windows-safe, emoji-rich logging system with UTF-8 hardening to prevent console crashes.

## ⚡ Performance Optimizations

- **Anthropic Prompt Caching**: The static parts of the system prompt are marked for caching, reducing input token costs by 50-90%.
- **Memory Persistence**: Summaries are generated every N turns and saved to the database, ensuring the agent remembers context across server restarts without re-processing full histories.
- **Temporal Awareness**: The agent is injected with the real-world current date every turn to prevent "temporal drift" in relative date queries (e.g., "sales today").

## 🛠 Tool Integration

The agent's "hands" are defined in:
- **`langchain_tools.py`**: Bridges the Python tool logic with LangChain's tool-calling interface.
- **`tools_refactored/`**: Contains the modularized implementations of financial, sales, inventory, and reporting logic.
