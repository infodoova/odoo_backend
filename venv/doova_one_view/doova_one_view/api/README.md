# Doova OneView: API Layer

This directory serves as the bridge between the backend business logic and the frontend. It is implemented using **FastAPI** for high-performance asynchronous request handling.

## 🚀 Key Endpoints

- **`/agent/`**: The entry point for the AI Finance Brain. Handles chat messages, session management, and reasoning.
- **`/accounting/`**, **`/sales/`**, **`/inventory/`**: Specialized REST endpoints for the dashboard widgets.
- **`/auth/`**: User authentication and session management.
- **`/tenants/`**: Multi-tenant configuration and Odoo integration settings.

## 🏗 Key Files

- **`app.py`**: The main FastAPI application entry point. Configures middleware, CORS, and includes all sub-routers.
- **`routes.py` (in sub-folders)**: Defines the actual endpoint logic.
- **`dependencies.py`**: Shared FastAPI dependencies (e.g., getting the current user, validating tenant access).
- **`middleware.py`**: Custom request/response processing (logging, error handling).

## 💡 Developer Notes

- **Async First**: Use `async def` for all route handlers to maximize concurrency.
- **Pydantic Schemas**: All request and response bodies must be modeled using Pydantic in the `schemas.py` files of each module.
- **Integration**: The API layer interacts with the `odoo_app` (Django models) using `sync_to_async` to bridge the Django ORM with the FastAPI event loop.
