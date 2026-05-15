# Doova OneView: Strategic Finance Intelligence for Odoo

Doova OneView is an advanced analytics and AI-powered intelligence platform that integrates directly with Odoo ERP. It transforms raw ERP data into strategic financial insights through a Virtual CFO agent.

## 🏗 High-Level Architecture

The project is a hybrid **Django + FastAPI** application:

- **`odoo_app/`**: A Django application that manages the database schema (PostgreSQL), authentication, and core business models. It acts as the "Source of Truth".
- **`doova_one_view/api/`**: A high-performance FastAPI layer that serves the frontend. It uses the Django ORM to access data while providing modern, asynchronous endpoints.
- **`doova_one_view/api/agent/`**: The "Finance Brain" — a sophisticated AI agent system built with LangChain and Anthropic Claude.

## 📂 Project Structure

```text
├── api/                  # FastAPI Application
│   ├── agent/            # AI Agent (Finance Brain)
│   ├── accounting/       # Financial Reporting Endpoints
│   └── ...               # Sales, Inventory, Auth, etc.
├── odoo_app/             # Django Core (Models, Migrations)
├── manage.py             # Django CLI
├── requirements.txt      # Python Dependencies
└── .env                  # Environment Variables
```

## 🛠 Tech Stack

- **Backend**: Python 3.11+, FastAPI, Django
- **AI**: LangChain, Anthropic Claude (Opus/Sonnet)
- **Database**: PostgreSQL (Primary), SQLite (Development)
- **Reporting**: ReportLab (PDF Generation)
- **Logging**: Custom Windows-hardened SafeLogger

## 🚀 Getting Started

1. **Environment**: Copy `.env.example` to `.env` and configure your Odoo credentials and Anthropic API key.
2. **Setup**:
   ```bash
   pip install -r requirements.txt
   python manage.py migrate
   ```
3. **Run**:
   ```bash
   # Start the FastAPI/Django hybrid server
   uvicorn doova_one_view.asgi:application --reload
   ```

## 🧠 Key Developer Links

- [Agent Architecture](./doova_one_view/api/agent/README.md)
- [Financial Tools Logic](./doova_one_view/api/agent/tools_refactored/README.md)
- [API Documentation](./doova_one_view/api/README.md)
