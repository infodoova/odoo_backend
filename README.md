# Doova OneView: Enterprise Strategic Finance Brain

Doova OneView is a sophisticated intelligence platform designed to modernize Odoo ERP data into actionable financial strategy. At its core is the **Finance Brain**—an autonomous AI agent built with LangChain and Anthropic's Claude, capable of performing deep management accounting, audit analysis, and strategic forecasting.

---

## 🚀 Key Features

### 🧠 Autonomous Finance Brain
The agent isn't just a chatbot; it's a **Self-Sufficient Investigator**. Before answering any query, it performs "Reconnaissance" to determine industry benchmarks, customer behavior, and account structures.

*   **28+ Enterprise Tools**:
    *   **Core Statements**: P&L (with margins), Balance Sheet (A=L+E integrity), Trial Balance.
    *   **Financial Ratios**: Current, Quick, Debt-to-Equity, ROE, ROA.
    *   **Audit & Compliance**: Statistical anomaly detection (>3σ), unbalanced entry flagging, VAT liability analysis.
    *   **Strategic Growth**: Moving-average revenue forecasting, customer churn metrics, inventory efficiency.
*   **Dynamic Reporting**: Automated AI-authored PDF reports with custom executive summaries.
*   **Intelligent Routing**: Automatically classifies requests into Fast-Execution (EXECUTE) or High-Stakes Strategy (PLAN) modes.

### 📊 Deep Observability
A custom structured logging system (powered by `logger.py`) provides full transparency into the agent's decision-making cycle, tool execution times, and reasoning steps.

### 🏗️ Hybrid Architecture
*   **FastAPI**: High-performance engine for AI routing and agent execution.
*   **Django**: Robust foundation for user management, administration, and static asset serving.
*   **Odoo Data Warehouse**: Direct SQL integration with tenant isolation and security filters.

---

## 🛠️ Technology Stack

| Category | Technology |
| :--- | :--- |
| **Frameworks** | FastAPI, Django |
| **AI Orchestration** | LangChain, Anthropic (Claude 3.5 Sonnet/Haiku) |
| **Database** | PostgreSQL (Odoo), SQLAlchemy |
| **Observability** | Python Structured Logging |
| **Reporting** | ReportLab, PyPDF |
| **Frontend** | ASGI-compatible Starlette routing |

---

## 📥 Installation

### Prerequisites
*   Python 3.10+
*   PostgreSQL (Odoo Instance)

### Setup
1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd odoo_backend
    ```

2.  **Create and activate virtual environment**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate  # Windows
    source venv/bin/activate # Linux/macOS
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r venv/doova_one_view/requirements.txt
    ```

4.  **Configure Environment**:
    Create a `.env` file in the root directory with the following keys:
    ```env
    ANTHROPIC_API_KEY=your_key_here
    DATABASE_URL=postgresql://user:password@localhost:5432/odoo_db
    DJANGO_SECRET_KEY=your_secret_key
    ```

---

## 🚀 Launching the Project

The project uses an ASGI server to run both Django and FastAPI concurrently.

```bash
# From the project root
uvicorn doova_one_view.asgi:application --host 0.0.0.0 --port 8000
```

*   **FastAPI Endpoints**: `http://localhost:8000/api/v1`
*   **Django Admin**: `http://localhost:8000/admin`
*   **Agent Execution Logs**: Check `agent_execution.log` for real-time AI reasoning logs.

---

## 📂 Project Structure

```text
odoo_backend/
├── doova_one_view/             # Core Project Root
│   ├── api/                    # FastAPI Integration
│   │   ├── agent/              # The "Finance Brain" logic
│   │   │   ├── tools_refactored/ # 28+ SQL-based intelligence tools
│   │   │   ├── prompts.py      # Centralized prompt management
│   │   │   └── logger.py       # Observability system
│   │   └── app.py              # FastAPI application instance
│   ├── settings.py             # Django Settings
│   └── asgi.py                 # ASGI entry point (FastAPI + Django)
├── reports/                    # Generated AI Reports
├── uploads/                    # Temporary document storage
└── README.md                   # You are here
```

---

## ⚖️ Security & Isolation

*   **Tenant Awareness**: Every SQL query is automatically scoped using `tenant_id` filters to prevent data leakage.
*   **Read-Only Safety**: The SQL agent is restricted from destructive operations (DROP, DELETE, UPDATE) via a strict regex-based security layer.

---
© 2026 hussein-ctrl1 | Doova OneView Intelligence
